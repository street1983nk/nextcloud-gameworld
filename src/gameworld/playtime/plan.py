"""Pure plan evaluation of the playtimes with zoneinfo (04-RESEARCH.md pattern 4).

The containers run in UTC, only the ExApp knows the time zone: these functions
compute every local boundary with ``zoneinfo`` (default ``Europe/Berlin``) and
``tzdata`` as the database. Day boundaries are built via
``datetime.combine(day, time(0), tzinfo=tz)`` up to the next day 00:00, never via
a fixed day length: this keeps weekday and window correct on the
changeover days (23 h and 25 h). All return values are absolute epoch seconds,
so the world mod can enforce them without time zone knowledge.

A child without a plan is not evaluated at all (opt-in, O-10); the caller
decides that in 04-03. After the local end of day there is no playtime without
a new plan (fail closed, O-04): ``until`` never reaches beyond the day.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIME_ZONE = "Europe/Berlin"
# Rule texts (German = message ID, D-25); they reach the client as 422 via str(exc).
MSG_LIMIT_RANGE = "Das Tageslimit liegt zwischen 1 und 1440 Minuten oder ist None."
MSG_WINDOW_BOTH_OR_NONE = "Ein Zeitfenster braucht Anfang und Ende oder keins von beiden."
MSG_WINDOW_START_RANGE = "Der Fensteranfang liegt zwischen 0 und 1439 Minuten."
MSG_WINDOW_END_RANGE = "Das Fensterende liegt zwischen 1 und 1440 Minuten."
MSG_WINDOW_START_BEFORE_END = "Der Fensteranfang liegt vor dem Fensterende."
MSG_WEEK_SEVEN_DAYS = "Ein Wochenplan braucht genau die sieben Wochentage 1 bis 7."
MSG_HOLIDAY_ENDS_BEFORE_START = "Ein Ferienzeitraum endet nicht vor seinem Beginn."
# ISO weekday 1..7 (Mon = 1) to the ASCII token for the child text.
WEEKDAY_TOKENS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_FULL_DAY_MINUTES = 1440
# Day starts for the line @tage of the rule file: today to today+8 (time_mod.DAY_COUNT).
_DAY_STARTS = 9


@dataclass(frozen=True)
class DayRule:
    """Rule of one weekday: allowed, daily limit (minutes) and a window (A3)."""

    allowed: bool
    limit_minutes: int | None
    window_start: int | None
    window_end: int | None

    def __post_init__(self) -> None:
        if self.limit_minutes is not None and not 1 <= self.limit_minutes <= _FULL_DAY_MINUTES:
            raise ValueError(MSG_LIMIT_RANGE)
        start, end = self.window_start, self.window_end
        if (start is None) != (end is None):
            raise ValueError(MSG_WINDOW_BOTH_OR_NONE)
        if start is not None and end is not None:
            if not 0 <= start <= _FULL_DAY_MINUTES - 1:
                raise ValueError(MSG_WINDOW_START_RANGE)
            if not 1 <= end <= _FULL_DAY_MINUTES:
                raise ValueError(MSG_WINDOW_END_RANGE)
            if start >= end:
                raise ValueError(MSG_WINDOW_START_BEFORE_END)


def check_world_window(window_start: int, window_end: int) -> tuple[int, int]:
    """Check a world window with the same rule as a child window (ValueError on nonsense)."""
    DayRule(allowed=True, limit_minutes=None, window_start=window_start, window_end=window_end)
    return window_start, window_end


@dataclass(frozen=True)
class WeekPlan:
    """Weekly plan: exactly the seven ISO weekdays 1..7, each to one DayRule."""

    days: dict[int, DayRule]

    def __post_init__(self) -> None:
        if set(self.days) != set(range(1, 8)):
            raise ValueError(MSG_WEEK_SEVEN_DAYS)


@dataclass(frozen=True)
class Holiday:
    """Holiday period of the household; start and end inclusive (O-08)."""

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(MSG_HOLIDAY_ENDS_BEFORE_START)


@dataclass(frozen=True)
class NextStart:
    """Next window opening: epoch, ISO weekday 1..7 and local minute 0..1439.

    Minute 0 means: whole day without a start time; the child text then shows no clock time.
    """

    at: int
    weekday: int
    minute: int

    def token(self) -> str:
        """Former token like ``Sa-10:00`` (6-field line of the rule file, for old mods)."""
        return f"{WEEKDAY_TOKENS[self.weekday - 1]}-{self.minute // 60:02d}:{self.minute % 60:02d}"


@dataclass(frozen=True)
class ChildState:
    """Evaluation for a child: window (epoch), rest in seconds, reason, next time.

    ``cap_rest_s`` is the rest for the cap of the rule file (None = no limit).
    It equals ``rest_s``, except before today's window: there it already carries
    the rest of the coming window, so the world mod opens by itself from ``start``,
    even if the ExApp does not rewrite until then (WR-02). Before ``start`` the mod
    blocks anyway via the window boundaries.
    """

    start: int
    until: int
    rest_s: int | None
    reason: str
    next_hint: str
    day: date
    next_start: NextStart | None = None
    cap_rest_s: int | None = 0


@dataclass(frozen=True)
class WorldState:
    """Evaluation of a world time window (ZEIT-05): window, reason, next time."""

    start: int
    until: int
    reason: str
    next_hint: str
    next_start: NextStart | None = None


@dataclass(frozen=True)
class WindowDay:
    """One weekday of the world time window for the API and the world list (ZEIT-05)."""

    weekday: int
    open: bool
    window_start: int | None
    window_end: int | None


def window_days(windows: dict[int, tuple[int, int]] | None) -> list[WindowDay] | None:
    """World window as seven weekdays; None means: no window, the world is always open."""
    if windows is None:
        return None
    days: list[WindowDay] = []
    for weekday in range(1, 8):
        window = windows.get(weekday)
        if window is None:
            days.append(WindowDay(weekday=weekday, open=False, window_start=None, window_end=None))
        else:
            days.append(WindowDay(weekday=weekday, open=True, window_start=window[0], window_end=window[1]))
    return days


def load_zone(name: str) -> ZoneInfo:
    """Time zone from the name; empty means Europe/Berlin (meta time_zone, O-02)."""
    return ZoneInfo(name or DEFAULT_TIME_ZONE)


def local_day(now_epoch: int, tz: ZoneInfo) -> date:
    """Local calendar day for an epoch timestamp."""
    return datetime.fromtimestamp(now_epoch, tz).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[int, int]:
    """Local day as epoch ``[start, end)``: 00:00 to next day 00:00 (never a fixed length)."""
    start = int(datetime.combine(day, time(0), tzinfo=tz).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz).timestamp())
    return start, end


def day_starts(now_epoch: int, tz: ZoneInfo) -> tuple[int, ...]:
    """Nine epoch day starts from the local day of ``now`` (via day_bounds, never a fixed day length)."""
    today = local_day(now_epoch, tz)
    return tuple(day_bounds(today + timedelta(days=offset), tz)[0] for offset in range(_DAY_STARTS))


def _minute_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def window_bounds(day: date, tz: ZoneInfo, rule: DayRule) -> tuple[int, int]:
    """Epoch boundaries of the window on this local day.

    Without a window (whole day) from 00:00 to the local end of day; a window end
    of 1440 minutes is likewise the end of day (next day 00:00, O-04).
    """
    day_start, day_end = day_bounds(day, tz)
    start, end = rule.window_start, rule.window_end
    if start is None or end is None:
        return day_start, day_end
    window_start = int(datetime.combine(day, _minute_time(start), tzinfo=tz).timestamp())
    if end >= _FULL_DAY_MINUTES:
        return window_start, day_end
    window_end = int(datetime.combine(day, _minute_time(end), tzinfo=tz).timestamp())
    return window_start, window_end


def plan_for(day: date, normal: WeekPlan, holiday: WeekPlan | None, holidays: list[Holiday]) -> WeekPlan:
    """Holiday plan if the day lies in a period (inclusive), otherwise the normal plan."""
    if holiday is not None and any(period.start <= day <= period.end for period in holidays):
        return holiday
    return normal


def _next_start(now: int, tz: ZoneInfo, rule_for: Callable[[date], DayRule | None]) -> NextStart | None:
    """Next allowed window opening from now, up to 7 days ahead, otherwise None."""
    today = local_day(now, tz)
    for offset in range(8):
        day = today + timedelta(days=offset)
        rule = rule_for(day)
        if rule is None or not rule.allowed:
            continue
        window_start, _ = window_bounds(day, tz, rule)
        if window_start > now:
            minutes = rule.window_start if rule.window_start is not None else 0
            return NextStart(at=window_start, weekday=day.isoweekday(), minute=minutes)
    return None


def _token(start: NextStart | None) -> str:
    return "-" if start is None else start.token()


def _child_next_start(
    now: int, tz: ZoneInfo, normal: WeekPlan, holiday: WeekPlan | None, holidays: list[Holiday]
) -> NextStart | None:
    return _next_start(now, tz, lambda day: plan_for(day, normal, holiday, holidays).days[day.isoweekday()])


def next_hint(now: int, tz: ZoneInfo, normal: WeekPlan, holiday: WeekPlan | None, holidays: list[Holiday]) -> str:
    """Next start as a token like ``Sa-10:00`` (holiday change included)."""
    return _token(_child_next_start(now, tz, normal, holiday, holidays))


def evaluate_child(
    now: int,
    tz: ZoneInfo,
    normal: WeekPlan,
    holiday: WeekPlan | None,
    holidays: list[Holiday],
    used_today_s: int,
) -> ChildState:
    """Rest, window and reason for a child on the local day of ``now``.

    Reasons: ``tag`` (not allowed today), ``fenster`` (before or after the window),
    ``limit`` (daily limit used up), ``ok`` (in the window, rest left). Rest
    is None on a day without a limit, otherwise seconds; 0 when blocked.
    """
    day = local_day(now, tz)
    rule = plan_for(day, normal, holiday, holidays).days[day.isoweekday()]
    upcoming = _child_next_start(now, tz, normal, holiday, holidays)
    hint = _token(upcoming)
    if not rule.allowed:
        return ChildState(start=0, until=0, rest_s=0, reason="tag", next_hint=hint, day=day, next_start=upcoming)
    window_start, window_end = window_bounds(day, tz, rule)
    # Rest of today's window (None = no limit), regardless of whether it is already open.
    window_rest = None if rule.limit_minutes is None else max(rule.limit_minutes * 60 - used_today_s, 0)
    cap_rest: int | None = 0
    if now >= window_end:
        reason, rest = "fenster", 0
    elif now < window_start:
        # Before the window: blocked via the boundaries, the cap already carries the coming window (WR-02).
        reason, rest, cap_rest = "fenster", 0, window_rest
    elif window_rest is None:
        reason, rest, cap_rest = "ok", None, None
    else:
        reason, rest = ("limit", 0) if window_rest <= 0 else ("ok", window_rest)
        cap_rest = rest
    return ChildState(
        start=window_start,
        until=window_end,
        rest_s=rest,
        reason=reason,
        next_hint=hint,
        day=day,
        next_start=upcoming,
        cap_rest_s=cap_rest,
    )


def _world_rule(windows: dict[int, tuple[int, int]], day: date) -> DayRule | None:
    window = windows.get(day.isoweekday())
    if window is None:
        return None
    return DayRule(allowed=True, limit_minutes=None, window_start=window[0], window_end=window[1])


def evaluate_world(now: int, tz: ZoneInfo, windows: dict[int, tuple[int, int]] | None) -> WorldState | None:
    """World time window (ZEIT-05): None means always open; otherwise reason ``ok`` or ``welt``.

    On a closed day ``0 0 welt`` stands in the rule file (the mod sees it as
    closed immediately); outside the window the window boundaries stay in place,
    so the world opens again at the right time.
    """
    if windows is None:
        return None
    day = local_day(now, tz)
    upcoming = _next_start(now, tz, lambda current: _world_rule(windows, current))
    hint = _token(upcoming)
    rule = _world_rule(windows, day)
    if rule is None:
        return WorldState(start=0, until=0, reason="welt", next_hint=hint, next_start=upcoming)
    window_start, window_end = window_bounds(day, tz, rule)
    reason = "ok" if window_start <= now < window_end else "welt"
    return WorldState(start=window_start, until=window_end, reason=reason, next_hint=hint, next_start=upcoming)
