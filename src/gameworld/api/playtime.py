"""Verwalter-API für Spielzeit-Regeln je Kind (ZEIT-01).

Nur Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (require_verwalter
routerweit, T-04-15). Der Körper kennt in diesem Plan nur den Wochenplan
"normal" (genau 7 Wochentage); Ferien kommen in 04-04. Ein Tag mit Limit und
ohne Fenster bildet "maximal 2 Stunden" ab, mit Fenster "nur bis 19 Uhr".

Setzen läuft über POST, Entfernen über DELETE (info.xml ^/api/.* ADMIN deckt GET,
POST, DELETE; eine neue HTTP-Methode wird nicht eingeführt). Ungültige Eingaben
(Felder, Minuten, Fenster) weist schon das Pydantic-Modell bzw. die
Plan-Validierung mit 422 ab (T-04-16).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import require_verwalter
from gameworld.access.secret import SecretUnavailableError
from gameworld.access.service import PlayerNotFoundError
from gameworld.api.invites import _clean_target  # pyright: ignore[reportPrivateUsage]
from gameworld.api.worlds import ServiceDep
from gameworld.playtime.plan import ChildState, DayRule, WeekPlan
from gameworld.playtime.service import ChildResult, ChildView, PlaytimeView, TimeService

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-04-15).
router = APIRouter(prefix="/api/playtime", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
# Ohne Zusatz (Token "-") steht in der Antwort null.
_NO_HINT = "-"


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
    used_today_s: int
    state: StateOut | None
    # Nur bei POST/DELETE gesetzt: Tragen die Welten die Regeln schon?
    applied: bool | None = None


class PlaytimeOut(BaseModel):
    time_zone: str
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


def _to_week(body: ChildPlanIn) -> WeekPlan:
    """ChildPlanIn in einen WeekPlan; jede ungültige Regel wirft ValueError (422)."""
    return WeekPlan(
        {day.weekday: DayRule(day.allowed, day.limit_minutes, day.window_start, day.window_end) for day in body.normal}
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
        used_today_s=child.used_today_s,
        state=_state_out(child.state),
        applied=applied,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, PlayerNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (PlayerNotFoundError, ValueError, DirectoryUnavailableError, SecretUnavailableError)


def _playtime_out(view: PlaytimeView) -> PlaytimeOut:
    return PlaytimeOut(time_zone=view.time_zone, children=[_child_out(child) for child in view.children])


@router.get("")
async def get_playtime(service: TimeDep, uid: VerwalterDep) -> PlaytimeOut:
    try:
        return _playtime_out(await service.list_children(uid))
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/children/{nc_user}")
async def set_child(nc_user: NcUser, body: ChildPlanIn, service: TimeDep, uid: VerwalterDep) -> ChildOut:
    try:
        result: ChildResult = await service.set_child(uid, _clean_target(nc_user), _to_week(body))
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
