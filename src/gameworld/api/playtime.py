"""Manager API for playtime rules per child, holidays, time zone and world windows (ZEIT-01, ZEIT-03..05).

Management only: second lock next to the AppAPI route ADMIN (require_verwalter
router-wide, T-04-15, T-04-24). The body of a child carries the weekly plan
"normal" (exactly 7 weekdays) and optionally the holiday plan "holiday" (null means:
during holidays the normal plan applies). A day with a limit and without a window represents
"at most 2 hours", with a window "only until 7 pm".

Holiday periods apply to the whole household (O-08): ISO date, from <= to,
at most 366 days, label at most 60 characters without control characters,
at most 50 periods (T-04-23). The time zone has its own route, so that the
contract of /api/settings stays unchanged; only names from
zoneinfo.available_timezones() are accepted (never a path, T-04-22).

The time window of a world (ZEIT-05) arrives as exactly seven weekdays with
"open" and window in minutes; a closed day has no window. The world
keeps running (O-05): only children are turned away outside it or disconnected
at the end of the window, managers are exempt (A4).

Setting runs via POST, removal via DELETE (info.xml ^/api/.* ADMIN covers GET,
POST, DELETE; no new HTTP method is introduced). Invalid input
is rejected with 422 already by the Pydantic model or the plan validation (T-04-16).
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Annotated, Self
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import require_verwalter
from gameworld.access.secret import SecretUnavailableError
from gameworld.access.service import PlayerNotFoundError
from gameworld.api.invites import _clean_target  # pyright: ignore[reportPrivateUsage]
from gameworld.api.worlds import ServiceDep, WindowDayOut, WorldId
from gameworld.playtime.plan import (
    MSG_HOLIDAY_ENDS_BEFORE_START,
    ChildState,
    DayRule,
    Holiday,
    WeekPlan,
    check_world_window,
)
from gameworld.playtime.service import (
    ChildResult,
    ChildView,
    HolidayNotFoundError,
    HolidayResult,
    HolidayView,
    PlaytimeView,
    TimeService,
    WorldWindowResult,
)
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND

# Every route is management: second lock next to the AppAPI route ADMIN (T-04-15).
router = APIRouter(prefix="/api/playtime", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
# Without a hint (token "-") the answer has null.
_NO_HINT = "-"
# Once at import: the valid IANA names (tzdata). Anything else is 422 (T-04-22).
_TIME_ZONES = frozenset(available_timezones())
MAX_HOLIDAY_DAYS = 366
MAX_LABEL_LENGTH = 60

# Validator texts (German = message ID, D-25). They reach the client as 422
# ("Value error, <text>" or as detail via _http_error) and are translated there.
MSG_PLAYTIME_LABEL_CONTROL = "Die Bezeichnung darf keine Steuerzeichen oder Zeilenumbrüche enthalten."
MSG_PLAYTIME_UNKNOWN_ZONE = "Unbekannte Zeitzone."
TEXT_HOLIDAY_MAX_DAYS = "Ein Ferienzeitraum dauert höchstens {days} Tage."
MSG_WINDOW_SEVEN_DAYS = "Ein Zeitfenster braucht genau die sieben Wochentage 1 bis 7."
MSG_WEEKDAY_TWICE = "Jeder Wochentag darf nur einmal vorkommen."
MSG_CLOSED_DAY_WINDOW = "Ein geschlossener Tag hat kein Zeitfenster."
MSG_OPEN_DAY_NEEDS_TIMES = "Ein offener Tag braucht Anfang und Ende des Zeitfensters."


def _printable_label(value: str) -> str:
    """Label without control characters and line breaks (T-04-23)."""
    if not value.isprintable():
        raise ValueError(MSG_PLAYTIME_LABEL_CONTROL)
    return value.strip()


def _known_zone(value: str) -> str:
    """Only IANA names from available_timezones(), never a path (T-04-22)."""
    if value not in _TIME_ZONES:
        raise ValueError(MSG_PLAYTIME_UNKNOWN_ZONE)
    return value


class DayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=1, le=7)
    allowed: bool
    # Ranges are checked by the plan validation (DayRule): limit 1..1440, window 0..1439 or 1..1440.
    limit_minutes: int | None = None
    window_start: int | None = None
    window_end: int | None = None


class ChildPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly the seven weekdays; duplicates and missing days are rejected by WeekPlan with ValueError.
    normal: list[DayIn]
    # Holiday plan, same check; null means: during holidays the normal plan applies.
    holiday: list[DayIn] | None = None


class HolidayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, AfterValidator(_printable_label)] = Field(default="", max_length=MAX_LABEL_LENGTH)
    # ISO YYYY-MM-DD; an invalid date (e.g. 2026-02-30) is rejected by Pydantic.
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError(MSG_HOLIDAY_ENDS_BEFORE_START)
        if (self.end_date - self.start_date).days + 1 > MAX_HOLIDAY_DAYS:
            raise ValueError(TEXT_HOLIDAY_MAX_DAYS.format(days=MAX_HOLIDAY_DAYS))
        return self


class TimeZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_zone: Annotated[str, AfterValidator(_known_zone)] = Field(max_length=64)


class WindowDayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=1, le=7)
    open: bool
    # Ranges are checked by check_world_window (like DayRule): start 0..1439, end 1..1440, start before end.
    window_start: int | None = None
    window_end: int | None = None


class WorldWindowIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: list[WindowDayIn] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def _seven_days(self) -> Self:
        if {day.weekday for day in self.days} != set(range(1, 8)):
            raise ValueError(MSG_WINDOW_SEVEN_DAYS)
        return self


class WorldWindowOut(BaseModel):
    world_id: str
    time_window: list[WindowDayOut] | None
    applied: bool


class DayOut(BaseModel):
    weekday: int
    allowed: bool
    limit_minutes: int | None
    window_start: int | None
    window_end: int | None


class StateOut(BaseModel):
    reason: str
    rest_s: int | None
    start: int
    until: int
    next_hint: str | None


class ChildOut(BaseModel):
    nc_user: str
    display_name: str
    player_name: str
    has_rules: bool
    normal: list[DayOut] | None
    holiday: list[DayOut] | None
    used_today_s: int
    state: StateOut | None
    # Adult switch (ROLLE-04): plan rests, the account plays without rules.
    adult: bool = False
    # Set only on POST/DELETE: do the worlds already carry the rules?
    applied: bool | None = None


class HolidayOut(BaseModel):
    id: int
    label: str
    start_date: date
    end_date: date
    active: bool
    # Set only on POST/DELETE: do all worlds already carry the new state?
    applied: bool | None = None


class TimeZoneOut(BaseModel):
    time_zone: str
    applied: bool


class PlaytimeOut(BaseModel):
    time_zone: str
    holidays: list[HolidayOut]
    children: list[ChildOut]


def get_time_service(
    worlds: ServiceDep,
    directory: Annotated[Directory, Depends(get_directory)],
) -> TimeService:
    """Built per request, like get_access_service; state lives in store and world service."""
    return TimeService(worlds, directory)


TimeDep = Annotated[TimeService, Depends(get_time_service)]
VerwalterDep = Annotated[str, Depends(require_verwalter)]
NcUser = Annotated[str, Path(max_length=64)]


def _to_week(days: list[DayIn]) -> WeekPlan:
    """Days into a WeekPlan; any invalid rule raises ValueError (422)."""
    # The dict below swallowed duplicates (the last entry would win), hence each day only once (AR-4-07).
    if len(days) != len({day.weekday for day in days}):
        raise ValueError(MSG_WEEKDAY_TWICE)
    return WeekPlan(
        {day.weekday: DayRule(day.allowed, day.limit_minutes, day.window_start, day.window_end) for day in days}
    )


def _to_windows(days: list[WindowDayIn]) -> dict[int, tuple[int, int]]:
    """Open days onto their window; any invalid entry raises ValueError (422)."""
    windows: dict[int, tuple[int, int]] = {}
    for day in days:
        if not day.open:
            if day.window_start is not None or day.window_end is not None:
                raise ValueError(MSG_CLOSED_DAY_WINDOW)
            continue
        if day.window_start is None or day.window_end is None:
            raise ValueError(MSG_OPEN_DAY_NEEDS_TIMES)
        windows[day.weekday] = check_world_window(day.window_start, day.window_end)
    return windows


def _window_out(result: WorldWindowResult) -> WorldWindowOut:
    days = None if result.time_window is None else [WindowDayOut(**asdict(day)) for day in result.time_window]
    return WorldWindowOut(world_id=result.world_id, time_window=days, applied=result.applied)


def _days_out(week: WeekPlan) -> list[DayOut]:
    return [
        DayOut(
            weekday=weekday,
            allowed=rule.allowed,
            limit_minutes=rule.limit_minutes,
            window_start=rule.window_start,
            window_end=rule.window_end,
        )
        for weekday, rule in sorted(week.days.items())
    ]


def _state_out(state: ChildState | None) -> StateOut | None:
    if state is None:
        return None
    return StateOut(
        reason=state.reason,
        rest_s=state.rest_s,
        start=state.start,
        until=state.until,
        next_hint=None if state.next_hint == _NO_HINT else state.next_hint,
    )


def _child_out(child: ChildView, applied: bool | None = None) -> ChildOut:
    return ChildOut(
        nc_user=child.nc_user,
        display_name=child.display_name,
        player_name=child.player_name,
        has_rules=child.has_rules,
        normal=None if child.normal is None else _days_out(child.normal),
        holiday=None if child.holiday is None else _days_out(child.holiday),
        used_today_s=child.used_today_s,
        state=_state_out(child.state),
        adult=child.adult,
        applied=applied,
    )


def _holiday_out(view: HolidayView, applied: bool | None = None) -> HolidayOut:
    return HolidayOut(
        id=view.id,
        label=view.label,
        start_date=view.start_date,
        end_date=view.end_date,
        active=view.active,
        applied=applied,
    )


def _holiday_result_out(result: HolidayResult) -> HolidayOut:
    return _holiday_out(result.holiday, result.applied)


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, PlayerNotFoundError | HolidayNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (
    PlayerNotFoundError,
    HolidayNotFoundError,
    WorldNotFoundError,
    ValueError,
    DirectoryUnavailableError,
    SecretUnavailableError,
)


def _playtime_out(view: PlaytimeView) -> PlaytimeOut:
    return PlaytimeOut(
        time_zone=view.time_zone,
        holidays=[_holiday_out(item) for item in view.holidays],
        children=[_child_out(child) for child in view.children],
    )


@router.get("")
async def get_playtime(service: TimeDep, uid: VerwalterDep) -> PlaytimeOut:
    try:
        return _playtime_out(await service.list_children(uid))
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/children/{nc_user}")
async def set_child(nc_user: NcUser, body: ChildPlanIn, service: TimeDep, uid: VerwalterDep) -> ChildOut:
    try:
        normal = _to_week(body.normal)
        holiday = None if body.holiday is None else _to_week(body.holiday)
        result: ChildResult = await service.set_child(uid, _clean_target(nc_user), normal, holiday)
        return _child_out(result.child, result.applied)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.delete("/children/{nc_user}")
async def clear_child(nc_user: NcUser, service: TimeDep, uid: VerwalterDep) -> ChildOut:
    try:
        result = await service.clear_child(uid, _clean_target(nc_user))
        return _child_out(result.child, result.applied)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/holidays")
async def add_holiday(body: HolidayIn, service: TimeDep) -> HolidayOut:
    try:
        holiday = Holiday(body.start_date, body.end_date, body.label)
        return _holiday_result_out(await service.add_holiday(holiday))
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.delete("/holidays/{holiday_id}")
async def remove_holiday(holiday_id: Annotated[int, Path(ge=1)], service: TimeDep) -> HolidayOut:
    try:
        return _holiday_result_out(await service.remove_holiday(holiday_id))
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/time-zone")
async def set_time_zone(body: TimeZoneIn, service: TimeDep) -> TimeZoneOut:
    try:
        applied = await service.set_time_zone(body.time_zone)
    except _ERRORS as exc:
        raise _http_error(exc) from None
    return TimeZoneOut(time_zone=body.time_zone, applied=applied)


@router.post("/worlds/{world_id}/window")
async def set_world_window(
    world_id: WorldId, body: WorldWindowIn, service: TimeDep, uid: VerwalterDep
) -> WorldWindowOut:
    try:
        return _window_out(await service.set_world_window(uid, world_id, _to_windows(body.days)))
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.delete("/worlds/{world_id}/window")
async def clear_world_window(world_id: WorldId, service: TimeDep, uid: VerwalterDep) -> WorldWindowOut:
    try:
        return _window_out(await service.clear_world_window(uid, world_id))
    except _ERRORS as exc:
        raise _http_error(exc) from None
