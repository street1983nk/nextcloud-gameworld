"""Verwalter-API für Spielzeit-Regeln je Kind, Ferien und Zeitzone (ZEIT-01, ZEIT-03, ZEIT-04).

Nur Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (require_verwalter
routerweit, T-04-15, T-04-24). Der Körper eines Kindes trägt den Wochenplan
"normal" (genau 7 Wochentage) und optional den Ferienplan "holiday" (null heißt:
in den Ferien gilt der Normalplan). Ein Tag mit Limit und ohne Fenster bildet
"maximal 2 Stunden" ab, mit Fenster "nur bis 19 Uhr".

Ferienzeiträume gelten für den ganzen Haushalt (O-08): ISO-Datum, von <= bis,
höchstens 366 Tage, Bezeichnung höchstens 60 Zeichen ohne Steuerzeichen,
höchstens 50 Zeiträume (T-04-23). Die Zeitzone hat eine eigene Route, damit der
Vertrag von /api/settings unverändert bleibt; angenommen werden nur Namen aus
zoneinfo.available_timezones() (nie ein Pfad, T-04-22).

Setzen läuft über POST, Entfernen über DELETE (info.xml ^/api/.* ADMIN deckt GET,
POST, DELETE; eine neue HTTP-Methode wird nicht eingeführt). Ungültige Eingaben
weist schon das Pydantic-Modell bzw. die Plan-Validierung mit 422 ab (T-04-16).
"""

from __future__ import annotations

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
from gameworld.api.worlds import ServiceDep
from gameworld.playtime.plan import ChildState, DayRule, Holiday, WeekPlan
from gameworld.playtime.service import (
    ChildResult,
    ChildView,
    HolidayNotFoundError,
    HolidayResult,
    HolidayView,
    PlaytimeView,
    TimeService,
)

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-04-15).
router = APIRouter(prefix="/api/playtime", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
# Ohne Zusatz (Token "-") steht in der Antwort null.
_NO_HINT = "-"
# Einmal beim Import: die gültigen IANA-Namen (tzdata). Alles andere ist 422 (T-04-22).
_TIME_ZONES = frozenset(available_timezones())
MAX_HOLIDAY_DAYS = 366
MAX_LABEL_LENGTH = 60


def _printable_label(value: str) -> str:
    """Bezeichnung ohne Steuerzeichen und Zeilenumbrüche (T-04-23)."""
    if not value.isprintable():
        raise ValueError("Die Bezeichnung darf keine Steuerzeichen oder Zeilenumbrüche enthalten.")
    return value.strip()


def _known_zone(value: str) -> str:
    """Nur IANA-Namen aus available_timezones(), nie ein Pfad (T-04-22)."""
    if value not in _TIME_ZONES:
        raise ValueError("Unbekannte Zeitzone.")
    return value


class DayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weekday: int = Field(ge=1, le=7)
    allowed: bool
    # Bereiche prüft die Plan-Validierung (DayRule): Limit 1..1440, Fenster 0..1439 bzw. 1..1440.
    limit_minutes: int | None = None
    window_start: int | None = None
    window_end: int | None = None


class ChildPlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Genau die sieben Wochentage; Dubletten und fehlende Tage weist WeekPlan mit ValueError ab.
    normal: list[DayIn]
    # Ferienplan, gleiche Prüfung; null heißt: in den Ferien gilt der Normalplan.
    holiday: list[DayIn] | None = None


class HolidayIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, AfterValidator(_printable_label)] = Field(default="", max_length=MAX_LABEL_LENGTH)
    # ISO JJJJ-MM-TT; ein ungültiges Datum (etwa 2026-02-30) weist Pydantic ab.
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _range(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("Ein Ferienzeitraum endet nicht vor seinem Beginn.")
        if (self.end_date - self.start_date).days + 1 > MAX_HOLIDAY_DAYS:
            raise ValueError(f"Ein Ferienzeitraum dauert höchstens {MAX_HOLIDAY_DAYS} Tage.")
        return self


class TimeZoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time_zone: Annotated[str, AfterValidator(_known_zone)] = Field(max_length=64)


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
    # Nur bei POST/DELETE gesetzt: Tragen die Welten die Regeln schon?
    applied: bool | None = None


class HolidayOut(BaseModel):
    id: int
    label: str
    start_date: date
    end_date: date
    active: bool
    # Nur bei POST/DELETE gesetzt: Tragen alle Welten den neuen Stand schon?
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
    """Je Anfrage gebaut, wie get_access_service; Zustand liegt in Store und Welt-Dienst."""
    return TimeService(worlds, directory)


TimeDep = Annotated[TimeService, Depends(get_time_service)]
VerwalterDep = Annotated[str, Depends(require_verwalter)]
NcUser = Annotated[str, Path(max_length=64)]


def _to_week(days: list[DayIn]) -> WeekPlan:
    """Tage in einen WeekPlan; jede ungültige Regel wirft ValueError (422)."""
    return WeekPlan(
        {day.weekday: DayRule(day.allowed, day.limit_minutes, day.window_start, day.window_end) for day in days}
    )


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
    if isinstance(exc, PlayerNotFoundError | HolidayNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (PlayerNotFoundError, HolidayNotFoundError, ValueError, DirectoryUnavailableError, SecretUnavailableError)


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
