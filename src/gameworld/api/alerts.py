"""Verwalter-API für die Handy-Seiten hinter den Benachrichtigungen (ELTERN-02, ELTERN-03).

- ``GET /api/attempts?day=&world=``: Fremdversuche eines Tages (Seite versuch, D-09)
- ``GET /api/review?day=``: Minuten je Kind und Welt (Seite rueckblick, D-13)
- ``GET``/``POST /api/review/prefs``: Rückblick an/aus und Uhrzeit, je Verwalter (D-12, D-15)
- ``POST /api/origin``: Basis-URL der Links aus dem Browser (Pattern 9, T-04.1-19); die
  erste wird gespeichert, ein Wechsel nur mit ``confirm`` (WR-04)

Alles nur für Verwalter (require_verwalter routerweit, T-04.1-18). ``day`` ist
ein Datum, ``world`` eine Welt-ID; Deep-Link-Parameter wirken nur als Filter
(T-04.1-22). Fehlt ``day``, gilt der heutige Tag der Haushalts-Zeitzone; die
Antwort nennt ihn als ``today`` (IN-04). Verwalter erscheinen im Rückblick
nicht. Nur GET und POST.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from gameworld.access.directory import get_directory
from gameworld.access.roles import require_verwalter
from gameworld.api.language import LangDep
from gameworld.api.worlds import ServiceDep, refresh_snapshot
from gameworld.i18n import translate
from gameworld.notify.links import MAX_BASE, clean_origin, decide_origin, join_base
from gameworld.notify.loop import META_LINK_ORIGIN, collect_play, display_name, limits_reached
from gameworld.notify.review import minutes
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.pause import clock_text
from gameworld.playtime.plan import local_day
from gameworld.worlds.service import WorldService

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN. Jeder Aufruf
# frischt den Verwalter-Schnappschuss auf (CR-01), erst nach der Sperre.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter), Depends(refresh_snapshot)])

# Spielzeit einer heute gelöschten Welt bleibt im Rückblick (Abnahme 04.1-09).
DELETED_WORLD = "gelöschte Welt"
MSG_UNAVAILABLE = "Die Daten sind gerade nicht lesbar. Bitte gleich noch einmal versuchen."

VerwalterDep = Annotated[str, Depends(require_verwalter)]
# Ohne day gilt der heutige Tag der Haushalts-Zeitzone, nie die Uhr des Handys (IN-04).
DayQuery = Annotated[date | None, Query()]
WorldQuery = Annotated[str | None, Query(pattern="^[0-9a-f]{12}$")]


class AttemptOut(BaseModel):
    world_id: str
    world_name: str
    player_name: str
    clock: str
    count: int


class AttemptsOut(BaseModel):
    day: date
    # Heutiger Tag der Haushalts-Zeitzone, damit die Seite "Heute" richtig benennt (IN-04).
    today: date
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
    today: date
    kids: list[ReviewKidOut]


class ReviewPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    minute: Annotated[int, Field(ge=0, le=1439)]


class OriginIn(BaseModel):
    """Origin und Webroot aus dem Browser des Verwalters; ``confirm`` nur nach der Rückfrage (WR-04)."""

    model_config = ConfigDict(extra="forbid")

    origin: Annotated[str, Field(max_length=MAX_BASE)]
    webroot: Annotated[str, Field(max_length=MAX_BASE)] = ""
    confirm: StrictBool = False

    @model_validator(mode="after")
    def _valid_base(self) -> OriginIn:
        join_base(self.origin, self.webroot)
        return self


class OriginOut(BaseModel):
    """``origin``: danach gespeicherte Basis-URL (None: keine). ``confirm_needed``: Rückfrage zeigen."""

    origin: str | None
    proposed: str
    saved: bool
    confirm_needed: bool


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


def _household_today(service: WorldService) -> date:
    """Heutiger Tag in der Haushalts-Zeitzone (meta time_zone), nicht in der des Geräts."""
    return local_day(service.time.now(), service.time.zone())


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
async def get_attempts(service: ServiceDep, day: DayQuery = None, world: WorldQuery = None) -> AttemptsOut:
    try:
        today = await anyio.to_thread.run_sync(_household_today, service)
        chosen = today if day is None else day
        items = await anyio.to_thread.run_sync(_attempts_sync, service, chosen, world)
    except sqlite3.Error:
        raise _unavailable() from None
    return AttemptsOut(day=chosen, today=today, attempts=items)


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
async def get_review(service: ServiceDep, uid: VerwalterDep, language: LangDep, day: DayQuery = None) -> ReviewOut:
    try:
        today = await anyio.to_thread.run_sync(_household_today, service)
        day = today if day is None else day
        play, names, reached = await anyio.to_thread.run_sync(_review_sync, service, day)
    except sqlite3.Error:
        raise _unavailable() from None
    directory = get_directory()
    deleted_world = translate(DELETED_WORLD, language)
    kids: list[ReviewKidOut] = []
    for nc_user, worlds in sorted(play.items()):
        # Alle heute gelöschten Welten zählen als eine Zeile "gelöschte Welt" (leere world_id).
        merged: dict[str, int] = {}
        for world_id, seconds in worlds.items():
            key = world_id if world_id in names else ""
            merged[key] = merged.get(key, 0) + seconds
        world_items = sorted(
            (
                ReviewWorldOut(
                    world_id=world_id, world_name=names.get(world_id, deleted_world), minutes=minutes(seconds)
                )
                for world_id, seconds in merged.items()
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
    return ReviewOut(day=day, today=today, kids=kids)


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


def _stored_origin(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return clean_origin(raw)
    except ValueError:
        return None


# Wie oft ein gleichzeitiger Schreiber das Speichern wiederholen lässt (compare_and_set).
_ORIGIN_ATTEMPTS = 3


def _save_origin_sync(service: WorldService, proposed: str, *, confirm: bool) -> OriginOut:
    """Erste Adresse merken, Wechsel nur bestätigt, nie https durch http (decide_origin)."""
    store = service.store
    for _attempt in range(_ORIGIN_ATTEMPTS):
        raw = store.get_meta(META_LINK_ORIGIN)
        current = _stored_origin(raw)
        decision = decide_origin(current, proposed, confirm=confirm)
        if not decision.store:
            return OriginOut(origin=current, proposed=proposed, saved=False, confirm_needed=decision.confirm_needed)
        if store.compare_and_set_meta(META_LINK_ORIGIN, raw, proposed):
            return OriginOut(origin=proposed, proposed=proposed, saved=True, confirm_needed=False)
    raise sqlite3.OperationalError("link_origin wurde gleichzeitig geändert")


@router.post("/origin")
async def save_origin(body: OriginIn, service: ServiceDep) -> OriginOut:
    """Basis-URL der Links: speichert nur die erste, eine abweichende nur mit ``confirm`` (WR-04).

    Die Bestätigung erzwingt der Server: Ohne ``confirm`` wird eine vorhandene
    Adresse nie ersetzt, die Antwort sagt dann ``confirm_needed``. Eine
    https-Adresse ersetzt nie eine http-Adresse, auch nicht bestätigt.
    """
    proposed = join_base(body.origin, body.webroot)
    try:
        return await anyio.to_thread.run_sync(lambda: _save_origin_sync(service, proposed, confirm=body.confirm))
    except sqlite3.Error:
        raise _unavailable() from None
