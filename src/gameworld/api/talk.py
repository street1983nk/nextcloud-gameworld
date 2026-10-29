"""Talk API for managers: state of the rooms, read-only switch, recreate room (TALK-01, D-17, D-19).

GET, POST and DELETE only (no PUT, like api/playtime.py): "read-only" on is
POST, off is DELETE. Without Talk, GET answers with ``available: false``.
"""

from __future__ import annotations

from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, WorldId
from gameworld.talk.rooms import TalkUnavailableError
from gameworld.talk.service import TalkWorldStatus, get_talk_service
from gameworld.worlds.service import NOT_FOUND

# Every route is management: second lock next to the AppAPI route ADMIN (T-04.1-28).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_NO_ROOM = "Diese Welt hat noch keinen Talk-Raum. Er entsteht beim nächsten Abgleich, sobald Talk bereit ist."
MSG_TALK_DOWN = "Talk antwortet gerade nicht. Bitte gleich noch einmal versuchen."

VerwalterDep = Annotated[str, Depends(require_verwalter)]


class TalkWorldOut(BaseModel):
    world_id: str
    world_name: str
    has_room: bool
    read_only: bool
    # Room owner is no longer a manager (D-27): he stays in the room, the world page shows a hint.
    owner_not_admin: bool
    # Room token for the link "Open Talk room" (visible to managers only, T-04.1-42); None without a room.
    token: str | None
    # Account of the former manager, only for owner_not_admin; the UI outputs it only as text.
    owner_display: str | None
    # Old room without a moderator (locked case, D-16) for the occ hint; otherwise None.
    orphaned_token: str | None


class TalkStatusOut(BaseModel):
    available: bool
    bots: bool
    worlds: list[TalkWorldOut]


class TalkReadOnlyOut(BaseModel):
    world_id: str
    read_only: bool
    # False: noted, Talk picks it up at the next reconciliation at the latest.
    applied: bool


@router.get("/talk")
async def get_talk(service: ServiceDep, uid: VerwalterDep) -> TalkStatusOut:
    result = await get_talk_service(service.store).status(uid)
    return TalkStatusOut(
        available=result.available,
        bots=result.bots,
        worlds=[_world_out(item) for item in result.worlds],
    )


def _world_out(item: TalkWorldStatus) -> TalkWorldOut:
    return TalkWorldOut(
        world_id=item.world_id,
        world_name=item.world_name,
        has_room=item.has_room,
        read_only=item.read_only,
        owner_not_admin=item.owner_not_admin,
        token=item.token,
        owner_display=item.owner_display,
        orphaned_token=item.orphaned_token,
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


@router.post("/worlds/{world_id}/talk/recreate")
async def talk_recreate(world_id: WorldId, service: ServiceDep, uid: VerwalterDep) -> TalkWorldOut:
    """Recreate the room (D-19); the UI asks beforehand, the old history is lost."""
    store = service.store
    if await anyio.to_thread.run_sync(store.get_world, world_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if await anyio.to_thread.run_sync(store.talk_room, world_id) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_NO_ROOM)
    talk = get_talk_service(store)
    try:
        done = await talk.recreate_room(world_id, uid)
    except TalkUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_TALK_DOWN) from None
    if not done:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_NO_ROOM)
    result = await talk.status(uid)
    item = next((world for world in result.worlds if world.world_id == world_id), None)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    return _world_out(item)
