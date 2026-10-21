"""Verwalter-API für die Pause aller Welten (ELTERN-01, D-01 bis D-06, D-25).

Nur Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (require_verwalter
routerweit, T-04.1-11). Der Körper beim Start trägt nur ``minutes`` mit genau
15, 30 oder 60 (strikt: "30" als Text, 30.0 oder true sind 422, T-04.1-12),
Zusatzfelder sind 422. "Weiter" (``/end``) und "Für heute Schluss"
(``/schluss``) haben keinen Körper.

Die Antwort nennt Zustand, Epochs, die Uhrzeit des Endes in der
Haushalts-Zeitzone (H:MM, für Seite und Bot; Kindertexte bleiben ohne Uhrzeit)
und je Welt, ob die Regeldatei angekommen ist und ob die Welt neu gestartet
wurde, damit die Pause sicher greift. Wer pausiert hat, steht nur in der
Datenbank (T-04.1-15). Nur GET und POST, wie api/playtime.py.
"""

from __future__ import annotations

import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep
from gameworld.playtime.pause import MSG_BAD_MINUTES, PauseResult, PauseService, clock_text
from gameworld.provisioner.client import ProvisionerError

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-04.1-11).
router = APIRouter(prefix="/api/pause", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Die Pause konnte gerade nicht gespeichert werden. Bitte gleich noch einmal versuchen."


def _whole_number(value: object) -> object:
    """Nur echte JSON-Ganzzahlen: 30.0, true oder "30" sind 422 (T-04.1-12)."""
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
    """Je Anfrage gebaut; der Zustand liegt in der Datenbank des Welt-Dienstes."""
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
