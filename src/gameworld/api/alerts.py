"""Verwalter-API für die Handy-Seiten hinter den Benachrichtigungen (ELTERN-02, ELTERN-03).

- ``GET /api/attempts?day=&world=``: Fremdversuche eines Tages (Seite versuch, D-09)
- ``GET /api/review?day=``: Minuten je Kind und Welt (Seite rueckblick, D-13)
- ``GET``/``POST /api/review/prefs``: Rückblick an/aus und Uhrzeit, je Verwalter (D-12, D-15)
- ``POST /api/origin``: Basis-URL der Links aus dem Browser (Pattern 9, T-04.1-19)

Alles nur für Verwalter (require_verwalter routerweit, T-04.1-18). ``day`` ist
ein Datum, ``world`` eine Welt-ID; Deep-Link-Parameter wirken nur als Filter
(T-04.1-22). Verwalter erscheinen im Rückblick nicht. Nur GET und POST.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import get_directory
from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep
from gameworld.notify.links import clean_origin
from gameworld.notify.loop import META_LINK_ORIGIN, collect_play, display_name, limits_reached
from gameworld.notify.review import minutes
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.pause import clock_text
from gameworld.playtime.plan import local_day
from gameworld.worlds.service import WorldService

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Die Daten sind gerade nicht lesbar. Bitte gleich noch einmal versuchen."

VerwalterDep = Annotated[str, Depends(require_verwalter)]
DayQuery = Annotated[date, Query()]
WorldQuery = Annotated[str | None, Query(pattern="^[0-9a-f]{12}$")]


class AttemptOut(BaseModel):
    world_id: str
    world_name: str
    player_name: str
    clock: str
    count: int


class AttemptsOut(BaseModel):
    day: date
    attempts: list[AttemptOut]


class ReviewWorldOut(BaseModel):
    world_id: str
    world_name: str
    minutes: int


class ReviewKidOut(BaseModel):
    nc_user: str
    display_name: str
    minutes: int
    limit_reached: bool
    worlds: list[ReviewWorldOut]


class ReviewOut(BaseModel):
    day: date
    kids: list[ReviewKidOut]


class ReviewPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    minute: Annotated[int, Field(ge=0, le=1439)]


class OriginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: Annotated[str, Field(max_length=300), AfterValidator(clean_origin)]


class OriginOut(BaseModel):
    origin: str


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


def _attempts_sync(service: WorldService, day: date, world: str | None) -> list[AttemptOut]:
    store = service.store
    tz = service.time.zone()
    names = {row.id: row.name for row in store.list_worlds()}
    return [
        AttemptOut(
            world_id=row.world_id,
            world_name=names.get(row.world_id, "?"),
            player_name=row.player_name,
            clock=clock_text(row.first_at, tz),
            count=row.count,
        )
        for row in store.attempts(day, world)
    ]


@router.get("/attempts")
async def get_attempts(service: ServiceDep, day: DayQuery, world: WorldQuery = None) -> AttemptsOut:
    try:
        items = await anyio.to_thread.run_sync(_attempts_sync, service, day, world)
    except sqlite3.Error:
        raise _unavailable() from None
    return AttemptsOut(day=day, attempts=items)


def _review_sync(service: WorldService, day: date) -> tuple[dict[str, dict[str, int]], dict[str, str], set[str]]:
    store = service.store
    admins = parse_admins(store.get_meta(META_TIME_ADMINS))
    play = collect_play(store, day, admins)
    names = {row.id: row.name for row in store.list_worlds()}
    today = local_day(service.time.now(), service.time.zone())
    # "Limit erreicht" kennt nur der heutige Tag (Auswertung mit der aktuellen Uhr).
    reached = limits_reached(service, list(play)) if day == today else set()
    return play, names, reached


@router.get("/review")
async def get_review(service: ServiceDep, day: DayQuery, uid: VerwalterDep) -> ReviewOut:
    try:
        play, names, reached = await anyio.to_thread.run_sync(_review_sync, service, day)
    except sqlite3.Error:
        raise _unavailable() from None
    directory = get_directory()
    kids: list[ReviewKidOut] = []
    for nc_user, worlds in sorted(play.items()):
        world_items = sorted(
            (
                ReviewWorldOut(world_id=world_id, world_name=names.get(world_id, "?"), minutes=minutes(seconds))
                for world_id, seconds in worlds.items()
            ),
            key=lambda item: (item.world_name.casefold(), item.world_id),
        )
        kids.append(
            ReviewKidOut(
                nc_user=nc_user,
                display_name=await display_name(directory, uid, service.store, nc_user),
                minutes=minutes(sum(worlds.values())),
                limit_reached=nc_user in reached,
                worlds=world_items,
            )
        )
    kids.sort(key=lambda kid: (kid.display_name.casefold(), kid.nc_user))
    return ReviewOut(day=day, kids=kids)


@router.get("/review/prefs")
async def get_review_prefs(service: ServiceDep, uid: VerwalterDep) -> ReviewPrefs:
    try:
        enabled, minute = await anyio.to_thread.run_sync(service.store.review_pref, uid)
    except sqlite3.Error:
        raise _unavailable() from None
    return ReviewPrefs(enabled=enabled, minute=minute)


@router.post("/review/prefs")
async def save_review_prefs(body: ReviewPrefs, service: ServiceDep, uid: VerwalterDep) -> ReviewPrefs:
    def save() -> None:
        service.store.set_review_pref(uid, enabled=body.enabled, minute=body.minute)

    try:
        await anyio.to_thread.run_sync(save)
    except sqlite3.Error:
        raise _unavailable() from None
    return body


@router.post("/origin")
async def save_origin(body: OriginIn, service: ServiceDep) -> OriginOut:
    try:
        await anyio.to_thread.run_sync(service.store.set_meta, META_LINK_ORIGIN, body.origin)
    except sqlite3.Error:
        raise _unavailable() from None
    return OriginOut(origin=body.origin)
