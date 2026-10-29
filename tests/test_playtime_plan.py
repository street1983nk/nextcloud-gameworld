"""Pure plan evaluation with golden vectors (04-RESEARCH.md pattern 4).

The epoch numbers come verbatim from the golden vector table of the research
(``spike/golden_tz.py``, computed in ``python:3.13-slim-trixie``): this pins the
time calculation against switch days (23 h and 25 h), holiday changes and end of
day.
"""

import itertools
from datetime import date
from zoneinfo import ZoneInfo

import pytest

from gameworld.playtime.plan import (
    DEFAULT_TIME_ZONE,
    ChildState,
    DayRule,
    Holiday,
    NextStart,
    WeekPlan,
    WorldState,
    day_bounds,
    day_starts,
    evaluate_child,
    evaluate_world,
    load_zone,
    local_day,
    next_hint,
    plan_for,
    window_bounds,
)

BERLIN = ZoneInfo("Europe/Berlin")

# Golden vectors: local day as epoch [start, end).
SA_24 = (1792792800, 1792879200)  # 2026-10-24, 24 h
SO_25 = (1792879200, 1792969200)  # 2026-10-25, 25 h (end of summer time)
MO_26 = (1792969200, 1793055600)  # 2026-10-26, 24 h
SO_29_03 = (1774738800, 1774821600)  # 2026-03-29, 23 h (start of summer time)
# 19:00 local on the switch days.
CLOSE_24 = 1792861200
CLOSE_25 = 1792951200
CLOSE_26 = 1793037600
CLOSE_29_03 = 1774803600


def _day(rule: DayRule, **overrides: DayRule) -> WeekPlan:
    """Weekly plan with one rule for all days, single days via the keys wd1..wd7."""
    days = dict.fromkeys(range(1, 8), rule)
    for name, value in overrides.items():
        days[int(name.removeprefix("wd"))] = value
    return WeekPlan(days=days)


def test_zoneinfo_berlin_loads() -> None:
    # Without tzdata this call raises ZoneInfoNotFoundError on Windows.
    assert load_zone("").key == DEFAULT_TIME_ZONE
    assert load_zone("Europe/Berlin").key == "Europe/Berlin"


def test_day_bounds_golden_vectors() -> None:
    assert day_bounds(date(2026, 10, 24), BERLIN) == SA_24
    assert day_bounds(date(2026, 10, 25), BERLIN) == SO_25
    assert day_bounds(date(2026, 10, 26), BERLIN) == MO_26
    assert day_bounds(date(2026, 3, 29), BERLIN) == SO_29_03
    assert SA_24[1] - SA_24[0] == 24 * 3600
    assert SO_25[1] - SO_25[0] == 25 * 3600
    assert SO_29_03[1] - SO_29_03[0] == 23 * 3600


def test_window_end_1900_across_dst() -> None:
    rule = DayRule(allowed=True, limit_minutes=None, window_start=9 * 60, window_end=19 * 60)
    assert window_bounds(date(2026, 10, 24), BERLIN, rule)[1] == CLOSE_24
    assert window_bounds(date(2026, 10, 25), BERLIN, rule)[1] == CLOSE_25
    assert window_bounds(date(2026, 10, 26), BERLIN, rule)[1] == CLOSE_26
    assert window_bounds(date(2026, 3, 29), BERLIN, rule)[1] == CLOSE_29_03


def test_window_whole_day_runs_to_local_midnight() -> None:
    rule = DayRule(allowed=True, limit_minutes=None, window_start=None, window_end=None)
    assert window_bounds(date(2026, 10, 25), BERLIN, rule) == SO_25


def test_window_end_1440_is_local_midnight() -> None:
    rule = DayRule(allowed=True, limit_minutes=None, window_start=9 * 60, window_end=1440)
    assert window_bounds(date(2026, 10, 25), BERLIN, rule)[1] == SO_25[1]


def test_local_day() -> None:
    assert local_day(SO_25[0], BERLIN) == date(2026, 10, 25)
    assert local_day(SO_25[1] - 1, BERLIN) == date(2026, 10, 25)
    assert local_day(SO_25[1], BERLIN) == date(2026, 10, 26)


def test_plan_for_holiday_switch_at_date() -> None:
    normal = _day(DayRule(True, 60, None, None))
    holiday = _day(DayRule(True, 120, None, None))
    holidays = [Holiday(date(2026, 10, 24), date(2026, 10, 26), "Herbstferien")]
    assert plan_for(date(2026, 10, 23), normal, holiday, holidays) is normal
    assert plan_for(date(2026, 10, 24), normal, holiday, holidays) is holiday
    assert plan_for(date(2026, 10, 26), normal, holiday, holidays) is holiday
    assert plan_for(date(2026, 10, 27), normal, holiday, holidays) is normal


def test_plan_for_without_holiday_plan_keeps_normal() -> None:
    normal = _day(DayRule(True, 60, None, None))
    holidays = [Holiday(date(2026, 10, 24), date(2026, 10, 26), "Herbstferien")]
    assert plan_for(date(2026, 10, 25), normal, None, holidays) is normal


def test_evaluate_child_day_not_allowed() -> None:
    plan = _day(DayRule(False, None, None, None))
    state = evaluate_child(MO_26[0] + 12 * 3600, BERLIN, plan, None, [], 0)
    assert isinstance(state, ChildState)
    assert (state.start, state.until, state.rest_s, state.reason) == (0, 0, 0, "tag")


def test_evaluate_child_before_window() -> None:
    rule = DayRule(True, None, 15 * 60, 19 * 60)
    plan = _day(rule)
    now = MO_26[0] + 10 * 3600  # 10:00 local, window only from 15:00
    state = evaluate_child(now, BERLIN, plan, None, [], 0)
    win_start, win_end = window_bounds(date(2026, 10, 26), BERLIN, rule)
    assert (state.start, state.until, state.rest_s, state.reason) == (win_start, win_end, 0, "fenster")
    # WR-02: without a limit the cap before the window already carries "no limit".
    assert state.cap_rest_s is None


def test_evaluate_child_before_window_cap_rest_is_coming_window() -> None:
    """WR-02: before the window rest_s is 0 (blocked), cap_rest_s the rest of the coming window."""
    rule = DayRule(True, 60, 15 * 60, 19 * 60)
    now = MO_26[0] + 10 * 3600
    state = evaluate_child(now, BERLIN, _day(rule), None, [], 20 * 60)
    assert (state.rest_s, state.reason, state.cap_rest_s) == (0, "fenster", 40 * 60)
    used_up = evaluate_child(now, BERLIN, _day(rule), None, [], 60 * 60)
    assert used_up.cap_rest_s == 0
    after = evaluate_child(MO_26[0] + 20 * 3600, BERLIN, _day(rule), None, [], 0)
    assert (after.rest_s, after.reason, after.cap_rest_s) == (0, "fenster", 0)
    inside = evaluate_child(MO_26[0] + 16 * 3600, BERLIN, _day(rule), None, [], 45 * 60)
    assert inside.cap_rest_s == inside.rest_s == 900


def test_evaluate_child_in_window_with_limit() -> None:
    rule = DayRule(True, 60, 15 * 60, 19 * 60)
    plan = _day(rule)
    now = MO_26[0] + 16 * 3600  # 16:00 local, inside the window
    state = evaluate_child(now, BERLIN, plan, None, [], 45 * 60)
    assert state.reason == "ok"
    assert state.rest_s == 900
    assert state.until == CLOSE_26


def test_evaluate_child_limit_used_up() -> None:
    rule = DayRule(True, 60, 15 * 60, 19 * 60)
    plan = _day(rule)
    now = MO_26[0] + 16 * 3600
    state = evaluate_child(now, BERLIN, plan, None, [], 60 * 60)
    assert state.reason == "limit"
    assert state.rest_s == 0


def test_evaluate_child_whole_day_without_limit() -> None:
    plan = _day(DayRule(True, None, None, None))
    now = MO_26[0] + 12 * 3600
    state = evaluate_child(now, BERLIN, plan, None, [], 0)
    assert state.reason == "ok"
    assert state.rest_s is None
    assert state.until == MO_26[1]  # local end of day, never beyond it (O-04)


def test_next_hint_weekend_from_wednesday() -> None:
    allowed = DayRule(True, None, 10 * 60, 19 * 60)
    closed = DayRule(False, None, None, None)
    # Sat and Sun allowed from 10:00, Mon to Fri blocked.
    plan = _day(closed, wd6=allowed, wd7=allowed)
    wednesday = date(2026, 10, 21)  # ISO weekday 3
    assert wednesday.isoweekday() == 3
    now = day_bounds(wednesday, BERLIN)[0] + 12 * 3600
    assert next_hint(now, BERLIN, plan, None, []) == "Sa-10:00"


def test_next_hint_crosses_holiday_end() -> None:
    normal = _day(DayRule(False, None, None, None))  # Normal plan: never allowed
    holiday = _day(DayRule(True, None, 9 * 60, 20 * 60))  # Holidays: daily from 09:00
    holidays = [Holiday(date(2026, 10, 20), date(2026, 10, 22), "Ferien")]
    now = day_bounds(date(2026, 10, 23), BERLIN)[0] + 12 * 3600  # Fri after the end of the holidays
    # Normal plan never allowed from now on -> no play time in 7 days.
    assert next_hint(now, BERLIN, normal, holiday, holidays) == "-"


def test_next_hint_none_within_seven_days() -> None:
    plan = _day(DayRule(False, None, None, None))
    assert next_hint(MO_26[0], BERLIN, plan, None, []) == "-"


def test_child_next_hint_on_tag_reason() -> None:
    allowed = DayRule(True, None, 10 * 60, 19 * 60)
    closed = DayRule(False, None, None, None)
    plan = _day(closed, wd6=allowed, wd7=allowed)
    wednesday = date(2026, 10, 21)
    now = day_bounds(wednesday, BERLIN)[0] + 12 * 3600
    state = evaluate_child(now, BERLIN, plan, None, [], 0)
    assert state.reason == "tag"
    assert state.next_hint == "Sa-10:00"


def test_evaluate_world_no_windows_is_open() -> None:
    assert evaluate_world(MO_26[0], BERLIN, None) is None


def test_evaluate_world_closed_day() -> None:
    windows = {3: (10 * 60, 12 * 60)}  # only Wednesday open
    state = evaluate_world(MO_26[0] + 12 * 3600, BERLIN, windows)  # Monday
    assert isinstance(state, WorldState)
    assert (state.start, state.until, state.reason) == (0, 0, "welt")


def test_evaluate_world_in_window() -> None:
    windows = {1: (15 * 60, 19 * 60)}  # Monday 15 to 19 o'clock
    now = MO_26[0] + 16 * 3600
    state = evaluate_world(now, BERLIN, windows)
    assert state is not None
    assert state.reason == "ok"
    assert state.until == CLOSE_26


def test_evaluate_world_outside_window_same_day() -> None:
    windows = {1: (15 * 60, 19 * 60)}
    state = evaluate_world(MO_26[0] + 10 * 3600, BERLIN, windows)  # before the window
    assert state is not None
    assert state.reason == "welt"
    assert state.next_hint == "Mo-15:00"


def test_day_rule_validation() -> None:
    with pytest.raises(ValueError, match="Tageslimit"):
        DayRule(True, 0, None, None)
    with pytest.raises(ValueError, match="Tageslimit"):
        DayRule(True, 1441, None, None)
    with pytest.raises(ValueError, match="Zeitfenster"):
        DayRule(True, None, 60, None)
    with pytest.raises(ValueError, match="Fensteranfang"):
        DayRule(True, None, 1440, 1440)
    with pytest.raises(ValueError, match="Fensterende"):
        DayRule(True, None, 0, 0)
    with pytest.raises(ValueError, match="vor dem Fensterende"):
        DayRule(True, None, 600, 600)
    # Valid boundary values do not raise.
    DayRule(True, 1, 0, 1440)
    DayRule(True, 1440, 1439, 1440)


def test_week_plan_needs_seven_days() -> None:
    rule = DayRule(True, None, None, None)
    with pytest.raises(ValueError, match="sieben Wochentage"):
        WeekPlan(days={1: rule, 2: rule})
    with pytest.raises(ValueError, match="sieben Wochentage"):
        WeekPlan(days=dict.fromkeys(range(7), rule))


def test_holiday_validation() -> None:
    with pytest.raises(ValueError, match="endet nicht vor"):
        Holiday(date(2026, 10, 26), date(2026, 10, 24), "falsch")


# Next start as epoch and day starts for the @tage row (quick 261021-481)


def test_next_start_carries_epoch_weekday_and_minute() -> None:
    plan = _day(DayRule(True, 60, 540, 1140))
    state = evaluate_child(SA_24[0] + 12 * 3600, BERLIN, plan, None, [], 3600)
    assert state.reason == "limit"
    # Sunday 25.10. 09:00 local: the clock is already set back at 3:00, so start of day + 10 h.
    assert state.next_start == NextStart(at=SO_25[0] + 10 * 3600, weekday=7, minute=540)
    assert state.next_hint == "So-09:00"
    assert state.next_start is not None
    assert state.next_start.token() == state.next_hint


def test_next_start_without_window_has_minute_zero() -> None:
    plan = _day(DayRule(True, 60, None, None))
    state = evaluate_child(SA_24[0] + 12 * 3600, BERLIN, plan, None, [], 3600)
    assert state.next_start == NextStart(at=SO_25[0], weekday=7, minute=0)
    assert state.next_hint == "So-00:00"


def test_next_start_none_without_any_allowed_day() -> None:
    plan = _day(DayRule(False, None, None, None))
    state = evaluate_child(SA_24[0] + 12 * 3600, BERLIN, plan, None, [], 0)
    assert state.next_start is None
    assert state.next_hint == "-"


def test_world_next_start() -> None:
    state = evaluate_world(SA_24[0] + 12 * 3600, BERLIN, {1: (600, 720)})
    assert state is not None
    assert state.next_start == NextStart(at=MO_26[0] + 10 * 3600, weekday=1, minute=600)
    assert state.next_hint == "Mo-10:00"


def test_day_starts_autumn_change() -> None:
    starts = day_starts(SA_24[0] + 12 * 3600, BERLIN)
    assert len(starts) == 9
    assert starts[:3] == (SA_24[0], SO_25[0], MO_26[0])
    # Sunday 25.10. has 25 h, the other days 24 h.
    assert starts[2] - starts[1] == 25 * 3600
    assert all(later - earlier == 24 * 3600 for earlier, later in itertools.pairwise(starts[2:]))


def test_day_starts_spring_change() -> None:
    starts = day_starts(SO_29_03[0] + 12 * 3600, BERLIN)
    assert starts[:2] == SO_29_03
    assert starts[1] - starts[0] == 23 * 3600
    assert all(later > earlier for earlier, later in itertools.pairwise(starts))
