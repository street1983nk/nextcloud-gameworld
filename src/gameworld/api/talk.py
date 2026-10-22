"""Talk-API für Verwalter: Stand der Räume und Nur-lesen-Schalter (TALK-01, D-17, D-27).

Nur GET, POST und DELETE (kein PUT, wie api/playtime.py): "nur lesen" an ist
POST, aus ist DELETE. Ohne Talk antwortet GET mit ``available: false``.
"""

from __future__ import annotations

from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, WorldId
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import NOT_FOUND

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-04.1-28).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_NO_ROOM = "Diese Welt hat noch keinen Talk-Raum. Er entsteht beim nächsten Abgleich, sobald Talk bereit ist."

VerwalterDep = Annotated[str, Depends(require_verwalter)]


class TalkWorldOut(BaseModel):
    world_id: str
    world_name: str
    has_room: bool
    read_only: bool
    # Raum-Owner ist kein Verwalter mehr (D-27): er bleibt im Raum, die Weltseite zeigt einen Hinweis.
    owner_not_admin: bool
    # Raum-Token für den Link "Talk-Raum öffnen" (nur Verwaltern sichtbar, T-04.1-42); None ohne Raum.
    token: str | None
    # Konto des früheren Verwalters, nur bei owner_not_admin; die Oberfläche gibt es nur als Text aus.
    owner_display: str | None


class TalkStatusOut(BaseModel):
    available: bool
    bots: bool
    worlds: list[TalkWorldOut]


class TalkReadOnlyOut(BaseModel):
    world_id: str
    read_only: bool
    # False: gemerkt, Talk übernimmt es spätestens beim nächsten Abgleich.
    applied: bool


@router.get("/talk")
async def get_talk(service: ServiceDep, uid: VerwalterDep) -> TalkStatusOut:
    result = await get_talk_service(service.store).status(uid)
    return TalkStatusOut(
        available=result.available,
        bots=result.bots,
        worlds=[
            TalkWorldOut(
                world_id=item.world_id,
                world_name=item.world_name,
                has_room=item.has_room,
                read_only=item.read_only,
                owner_not_admin=item.owner_not_admin,
                token=item.token,
                owner_display=item.owner_display,
            )
            for item in result.worlds
        ],
    )


async def _read_only(world_id: str, service: ServiceDep, *, on: bool) -> TalkReadOnlyOut:
    store = service.store
    if await anyio.to_thread.run_sync(store.get_world, world_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if await anyio.to_thread.run_sync(store.talk_room, world_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_NO_ROOM)
    applied = await get_talk_service(store).set_read_only(world_id, on=on)
    return TalkReadOnlyOut(world_id=world_id, read_only=on, applied=applied)


@router.post("/worlds/{world_id}/talk/read-only")
async def talk_read_only_on(world_id: WorldId, service: ServiceDep) -> TalkReadOnlyOut:
    return await _read_only(world_id, service, on=True)


@router.delete("/worlds/{world_id}/talk/read-only")
async def talk_read_only_off(world_id: WorldId, service: ServiceDep) -> TalkReadOnlyOut:
    return await _read_only(world_id, service, on=False)
