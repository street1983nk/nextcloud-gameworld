"""Manager API for the pause of all worlds (ELTERN-01, D-01 to D-06, D-25).

Management only: second lock next to the AppAPI route ADMIN (require_verwalter
router-wide, T-04.1-11). The body on start carries only ``minutes`` with exactly
15, 30 or 60 (strict: "30" as text, 30.0 or true are 422, T-04.1-12),
extra fields are 422. "Weiter" (``/end``) and "Für heute Schluss"
(``/schluss``) have no body.

The answer names the state, epochs, the time of day of the end in the
household time zone (H:MM, for the page and bot; child texts stay without a time of day)
and per world whether the rules file arrived and whether the world was restarted,
so that the pause reliably takes hold. Who paused is stored only in the
database (T-04.1-15). GET and POST only, like api/playtime.py.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, refresh_snapshot
from gameworld.playtime.pause import MSG_BAD_MINUTES, PauseResult, PauseService, clock_text
from gameworld.provisioner.client import ProvisionerError

# Every route is management: second lock next to the AppAPI route ADMIN (T-04.1-11). Every
# call refreshes the manager snapshot (CR-01), only after the lock.
router = APIRouter(prefix="/api/pause", dependencies=[Depends(require_verwalter), Depends(refresh_snapshot)])

MSG_UNAVAILABLE = "Die Pause konnte gerade nicht gespeichert werden. Bitte gleich noch einmal versuchen."


def _whole_number(value: object) -> object:
    """Only real JSON integers: 30.0, true or "30" are 422 (T-04.1-12)."""
    if type(value) is not int:
        raise ValueError(MSG_BAD_MINUTES)
    return value


class PauseIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    minutes: Annotated[Literal[15, 30, 60], BeforeValidator(_whole_number)]


class PauseWorldOut(BaseModel):
    id: str
    name: str
    applied: bool
    restarted: bool


class PauseOut(BaseModel):
    active: bool
    art: str | None
    ab: int | None
    bis: int | None
    until_clock: str | None
    worlds: list[PauseWorldOut]


def get_pause_service(worlds: ServiceDep) -> PauseService:
    """Built per request; the state lives in the database of the world service."""
    return PauseService(worlds)


PauseDep = Annotated[PauseService, Depends(get_pause_service)]
VerwalterDep = Annotated[str, Depends(require_verwalter)]


def _out(result: PauseResult, service: PauseService) -> PauseOut:
    worlds = [
        PauseWorldOut(id=item.world_id, name=item.name, applied=item.applied, restarted=item.restarted)
        for item in result.worlds
    ]
    state = result.state
    if state is None:
        return PauseOut(active=False, art=None, ab=None, bis=None, until_clock=None, worlds=worlds)
    return PauseOut(
        active=True,
        art=state.art,
        ab=state.ab,
        bis=state.bis,
        until_clock=clock_text(state.bis, service.zone()),
        worlds=worlds,
    )


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (ValueError, sqlite3.Error, ProvisionerError)


@router.get("")
async def get_pause(service: PauseDep) -> PauseOut:
    try:
        return _out(await service.get(), service)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("")
async def start_pause(body: PauseIn, service: PauseDep, uid: VerwalterDep) -> PauseOut:
    try:
        return _out(await service.start(uid, body.minutes), service)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/end")
async def end_pause(service: PauseDep, uid: VerwalterDep) -> PauseOut:
    try:
        return _out(await service.end(uid), service)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/schluss")
async def stop_for_today(service: PauseDep, uid: VerwalterDep) -> PauseOut:
    try:
        return _out(await service.schluss(uid), service)
    except _ERRORS as exc:
        raise _http_error(exc) from None
