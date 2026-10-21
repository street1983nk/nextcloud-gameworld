"""Reine Plan-Auswertung der Spielzeiten mit zoneinfo (04-RESEARCH.md Pattern 4).

Die Container laufen in UTC, nur die ExApp kennt die Zeitzone: Diese Funktionen
rechnen jede lokale Grenze mit ``zoneinfo`` (Vorgabe ``Europe/Berlin``) und
``tzdata`` als Datenbank. Tagesgrenzen entstehen über
``datetime.combine(tag, time(0), tzinfo=tz)`` bis zum Folgetag 00:00, nie über
eine feste Tageslänge: So stimmen Wochentag und Fenster auch an den
Umstellungstagen (23 h und 25 h). Alle Rückgaben sind absolute Epoch-Sekunden,
damit der Welt-Mod sie ohne Zeitzonenwissen durchsetzen kann.

Ein Kind ohne Plan wird gar nicht ausgewertet (Opt-in, O-10); das entscheidet
der Aufrufer in 04-03. Nach dem lokalen Tagesende gibt es ohne neuen Plan keine
Spielzeit (fail closed, O-04): ``until`` reicht nie über den Tag hinaus.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TIME_ZONE = "Europe/Berlin"
# ISO-Wochentag 1..7 (Mo = 1) auf das ASCII-Token für den Kindertext.
WEEKDAY_TOKENS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
_FULL_DAY_MINUTES = 1440
# Tagesanfänge für die Zeile @tage der Regeldatei: heute bis heute+8 (time_mod.DAY_COUNT).
_DAY_STARTS = 9


@dataclass(frozen=True)
class DayRule:
    """Regel eines Wochentags: erlaubt, Tageslimit (Minuten) und ein Fenster (A3)."""

    allowed: bool
    limit_minutes: int | None
    window_start: int | None
    window_end: int | None

    def __post_init__(self) -> None:
        if self.limit_minutes is not None and not 1 <= self.limit_minutes <= _FULL_DAY_MINUTES:
            raise ValueError("Das Tageslimit liegt zwischen 1 und 1440 Minuten oder ist None.")
        start, end = self.window_start, self.window_end
        if (start is None) != (end is None):
            raise ValueError("Ein Zeitfenster braucht Anfang und Ende oder keins von beiden.")
        if start is not None and end is not None:
            if not 0 <= start <= _FULL_DAY_MINUTES - 1:
                raise ValueError("Der Fensteranfang liegt zwischen 0 und 1439 Minuten.")
            if not 1 <= end <= _FULL_DAY_MINUTES:
                raise ValueError("Das Fensterende liegt zwischen 1 und 1440 Minuten.")
            if start >= end:
                raise ValueError("Der Fensteranfang liegt vor dem Fensterende.")


def check_world_window(window_start: int, window_end: int) -> tuple[int, int]:
    """Prüft ein Welt-Fenster mit derselben Regel wie ein Kinder-Fenster (ValueError bei Unsinn)."""
    DayRule(allowed=True, limit_minutes=None, window_start=window_start, window_end=window_end)
    return window_start, window_end


@dataclass(frozen=True)
class WeekPlan:
    """Wochenplan: genau die sieben ISO-Wochentage 1..7 auf je eine DayRule."""

    days: dict[int, DayRule]

    def __post_init__(self) -> None:
        if set(self.days) != set(range(1, 8)):
            raise ValueError("Ein Wochenplan braucht genau die sieben Wochentage 1 bis 7.")


@dataclass(frozen=True)
class Holiday:
    """Ferienzeitraum des Haushalts; Anfang und Ende inklusive (O-08)."""

    start: date
    end: date
    label: str

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("Ein Ferienzeitraum endet nicht vor seinem Beginn.")


@dataclass(frozen=True)
class NextStart:
    """Nächste Fensteröffnung: Epoch, ISO-Wochentag 1..7 und lokale Minute 0..1439.

    Minute 0 heißt: ganzer Tag ohne Startzeit; der Kindertext zeigt dann keine Uhrzeit.
    """

    at: int
    weekday: int
    minute: int

    def token(self) -> str:
        """Bisheriges Token wie ``Sa-10:00`` (6-Feld-Zeile der Regeldatei, für alte Mods)."""
        return f"{WEEKDAY_TOKENS[self.weekday - 1]}-{self.minute // 60:02d}:{self.minute % 60:02d}"


@dataclass(frozen=True)
class ChildState:
    """Auswertung für ein Kind: Fenster (Epoch), Rest in Sekunden, Grund, nächste Zeit.

    ``cap_rest_s`` ist der Rest für den Deckel der Regeldatei (None = kein Limit).
    Er gleicht ``rest_s``, nur vor dem heutigen Fenster nicht: Dort trägt er schon
    den Rest des kommenden Fensters, damit der Welt-Mod ab ``start`` selbst öffnet,
    auch wenn die ExApp bis dahin nicht neu schreibt (WR-02). Vor ``start`` sperrt
    der Mod ohnehin über die Fenstergrenzen.
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
    """Auswertung eines Welt-Zeitfensters (ZEIT-05): Fenster, Grund, nächste Zeit."""

    start: int
    until: int
    reason: str
    next_hint: str
    next_start: NextStart | None = None


@dataclass(frozen=True)
class WindowDay:
    """Ein Wochentag des Welt-Zeitfensters für API und Weltenliste (ZEIT-05)."""

    weekday: int
    open: bool
    window_start: int | None
    window_end: int | None


def window_days(windows: dict[int, tuple[int, int]] | None) -> list[WindowDay] | None:
    """Welt-Fenster als sieben Wochentage; None heißt: kein Fenster, die Welt ist immer offen."""
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
    """Zeitzone aus dem Namen; leer bedeutet Europe/Berlin (meta time_zone, O-02)."""
    return ZoneInfo(name or DEFAULT_TIME_ZONE)


def local_day(now_epoch: int, tz: ZoneInfo) -> date:
    """Lokaler Kalendertag zu einem Epoch-Zeitpunkt."""
    return datetime.fromtimestamp(now_epoch, tz).date()


def day_bounds(day: date, tz: ZoneInfo) -> tuple[int, int]:
    """Lokaler Tag als Epoch ``[start, end)``: 00:00 bis Folgetag 00:00 (nie feste Länge)."""
    start = int(datetime.combine(day, time(0), tzinfo=tz).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time(0), tzinfo=tz).timestamp())
    return start, end


def day_starts(now_epoch: int, tz: ZoneInfo) -> tuple[int, ...]:
    """Neun Epoch-Tagesanfänge ab dem lokalen Tag von ``now`` (über day_bounds, nie feste Tageslänge)."""
    today = local_day(now_epoch, tz)
    return tuple(day_bounds(today + timedelta(days=offset), tz)[0] for offset in range(_DAY_STARTS))


def _minute_time(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def window_bounds(day: date, tz: ZoneInfo, rule: DayRule) -> tuple[int, int]:
    """Epoch-Grenzen des Fensters an diesem lokalen Tag.

    Ohne Fenster (ganzer Tag) von 00:00 bis zum lokalen Tagesende; ein Fensterende
    von 1440 Minuten ist ebenfalls das Tagesende (Folgetag 00:00, O-04).
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
    """Ferienplan, wenn der Tag in einem Zeitraum liegt (inklusive), sonst Normalplan."""
    if holiday is not None and any(period.start <= day <= period.end for period in holidays):
        return holiday
    return normal


def _next_start(now: int, tz: ZoneInfo, rule_for: Callable[[date], DayRule | None]) -> NextStart | None:
    """Nächste erlaubte Fensteröffnung ab jetzt, bis 7 Tage voraus, sonst None."""
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
    """Nächster Start als Token wie ``Sa-10:00`` (Ferienwechsel eingeschlossen)."""
    return _token(_child_next_start(now, tz, normal, holiday, holidays))


def evaluate_child(
    now: int,
    tz: ZoneInfo,
    normal: WeekPlan,
    holiday: WeekPlan | None,
    holidays: list[Holiday],
    used_today_s: int,
) -> ChildState:
    """Rest, Fenster und Grund für ein Kind am lokalen Tag von ``now``.

    Gründe: ``tag`` (heute nicht erlaubt), ``fenster`` (vor oder nach dem Fenster),
    ``limit`` (Tageslimit aufgebraucht), ``ok`` (im Fenster, Rest vorhanden). Rest
    ist None bei einem Tag ohne Limit, sonst Sekunden; bei Sperren 0.
    """
    day = local_day(now, tz)
    rule = plan_for(day, normal, holiday, holidays).days[day.isoweekday()]
    upcoming = _child_next_start(now, tz, normal, holiday, holidays)
    hint = _token(upcoming)
    if not rule.allowed:
        return ChildState(start=0, until=0, rest_s=0, reason="tag", next_hint=hint, day=day, next_start=upcoming)
    window_start, window_end = window_bounds(day, tz, rule)
    # Rest des heutigen Fensters (None = kein Limit), unabhängig davon, ob es schon offen ist.
    window_rest = None if rule.limit_minutes is None else max(rule.limit_minutes * 60 - used_today_s, 0)
    cap_rest: int | None = 0
    if now >= window_end:
        reason, rest = "fenster", 0
    elif now < window_start:
        # Vor dem Fenster: gesperrt über die Grenzen, der Deckel trägt schon das kommende Fenster (WR-02).
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
    """Welt-Zeitfenster (ZEIT-05): None heißt immer offen; sonst Grund ``ok`` oder ``welt``.

    An einem geschlossenen Tag steht ``0 0 welt`` in der Regeldatei (der Mod sieht
    daran sofort geschlossen); außerhalb des Fensters bleiben die Fenstergrenzen
    stehen, damit die Welt am richtigen Zeitpunkt wieder öffnet.
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
