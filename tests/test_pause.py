"""Pause (ELTERN-01): reine Zeitfenster-Logik, Morgen-Minuten und Zustand in SQLite (04.1-03)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from gameworld.playtime.pause import (
    ART_PAUSE,
    ART_SCHLUSS,
    PAUSE_LEAD_SECONDS,
    PAUSE_MINUTES,
    PauseState,
    is_active,
    morgen_minutes,
    schluss_window,
    start_window,
)
from gameworld.playtime.plan import DayRule, Holiday, WeekPlan, day_starts, load_zone, local_day
from gameworld.worlds.store import WorldStore

# Sa 2026-10-24 12:00 Europe/Berlin; morgen ist Sonntag (Umstellung auf Winterzeit).
FIXED = 1792836000
ZONE = load_zone("")
TOMORROW = local_day(FIXED, ZONE) + timedelta(days=1)


def _week(*, allowed: bool = True, ws: int | None = None, we: int | None = None) -> WeekPlan:
    return WeekPlan({weekday: DayRule(allowed, None, ws, we) for weekday in range(1, 8)})


def _sunday_only(rule: DayRule) -> WeekPlan:
    days = {weekday: DayRule(True, None, None, None) for weekday in range(1, 8)}
    days[TOMORROW.isoweekday()] = rule
    return WeekPlan(days)


def test_constants() -> None:
    assert PAUSE_LEAD_SECONDS == 30
    assert PAUSE_MINUTES == (15, 30, 60)
    assert (ART_PAUSE, ART_SCHLUSS) == ("pause", "schluss")


def test_start_window_fresh() -> None:
    assert start_window(1000, 15, None) == (1030, 1930)


def test_start_window_keeps_ab_of_running_pause() -> None:
    current = PauseState(started_by="admin", ab=1030, bis=1930, art=ART_PAUSE)
    assert start_window(1200, 60, current) == (1030, 1030 + 3600)


def test_start_window_rejects_other_minutes() -> None:
    with pytest.raises(ValueError, match="15, 30 oder 60"):
        start_window(1000, 20, None)


def test_schluss_window_without_pause() -> None:
    ab, bis = schluss_window(FIXED, ZONE, None)
    assert ab == FIXED + 30
    assert bis == day_starts(FIXED, ZONE)[1]


def test_schluss_window_keeps_ab_of_running_pause() -> None:
    current = PauseState(started_by="admin", ab=FIXED - 100, bis=FIXED + 800, art=ART_PAUSE)
    assert schluss_window(FIXED, ZONE, current) == (FIXED - 100, day_starts(FIXED, ZONE)[1])


def test_schluss_window_just_before_midnight_keeps_valid_line() -> None:
    midnight = day_starts(FIXED, ZONE)[1]
    ab, bis = schluss_window(midnight - 10, ZONE, None)
    assert bis == midnight
    assert ab < bis


def test_is_active() -> None:
    state = PauseState(started_by="admin", ab=100, bis=200, art=ART_PAUSE)
    assert is_active(None, 150) is False
    assert is_active(state, 50) is True
    assert is_active(state, 199) is True
    assert is_active(state, 200) is False


def test_morgen_minutes_window_start() -> None:
    plans = {"gw-mia": (_sunday_only(DayRule(True, None, 540, 1140)), None)}
    assert morgen_minutes(FIXED, ZONE, plans, [], {"gw-mia": "Mia"}) == {"Mia": 540}


def test_morgen_minutes_whole_day_and_not_allowed_and_no_plan() -> None:
    plans = {
        "gw-mia": (_sunday_only(DayRule(True, 60, None, None)), None),
        "gw-leo": (_sunday_only(DayRule(False, None, None, None)), None),
    }
    names = {"gw-mia": "Mia", "gw-leo": "Leo", "gw-ohne": "Ohne"}
    assert morgen_minutes(FIXED, ZONE, plans, [], names) == {"Mia": 0, "Leo": -1}


def test_morgen_minutes_uses_holiday_plan() -> None:
    normal = _sunday_only(DayRule(False, None, None, None))
    holiday = _week(ws=600, we=1200)
    plans = {"gw-mia": (normal, holiday)}
    holidays = [Holiday(TOMORROW, TOMORROW + timedelta(days=3), "Herbst")]
    assert morgen_minutes(FIXED, ZONE, plans, holidays, {"gw-mia": "Mia"}) == {"Mia": 600}
    # Ferien erst übermorgen: morgen gilt noch der Normalplan.
    later = [Holiday(TOMORROW + timedelta(days=1), TOMORROW + timedelta(days=3), "Herbst")]
    assert morgen_minutes(FIXED, ZONE, plans, later, {"gw-mia": "Mia"}) == {"Mia": -1}


# Zustand in SQLite


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


def test_store_pause_roundtrip(store: WorldStore) -> None:
    assert store.get_pause() is None
    first = PauseState(started_by="admin", ab=100, bis=200, art=ART_PAUSE)
    store.set_pause(first)
    assert store.get_pause() == first
    second = PauseState(started_by="mama", ab=100, bis=900, art=ART_SCHLUSS)
    store.set_pause(second)
    assert store.get_pause() == second
    store.clear_pause()
    assert store.get_pause() is None


def test_store_clear_pause_only_if_ended(store: WorldStore) -> None:
    state = PauseState(started_by="admin", ab=100, bis=200, art=ART_PAUSE)
    store.set_pause(state)
    store.clear_pause(ended_by=199)
    assert store.get_pause() == state
    store.clear_pause(ended_by=200)
    assert store.get_pause() is None


def test_store_pause_survives_new_store_instance(store: WorldStore, app_env: Path) -> None:
    state = PauseState(started_by="admin", ab=100, bis=200, art=ART_PAUSE)
    store.set_pause(state)
    again = WorldStore(app_env / "gameworld.sqlite3")
    again.migrate()
    assert again.get_pause() == state
