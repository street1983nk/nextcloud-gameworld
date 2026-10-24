"""Admin-Abschnitt: Verwalter-Gruppen einstellen und Gruppen suchen (ROLLE-03, D-02).

Nur echte Nextcloud-Admins (Mitglieder der Gruppe admin). Die Sperre sitzt
serverseitig am ganzen Router (``require_nc_admin``, fragt Nextcloud bei jedem
Aufruf frisch); die Weiche in der Oberfläche ist nur Komfort. Die Gruppe admin
verwaltet Gameworld immer, steht darum nie in der gespeicherten Liste und ist
nicht entfernbar. Jede Änderung wirkt sofort: Der Rollen-Cache wird verworfen,
und der Verwalter-Stand (frei-Zeilen, Benachrichtigungs-Empfänger,
Talk-Moderatoren) wird ohne Drossel neu gelesen.
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import (
    ADMIN_GROUP,
    GROUP_ID_MAX,
    META_VERWALTER_GROUPS,
    MSG_UNAVAILABLE,
    NcAdminDep,
    RolesDep,
    parse_verwalter_groups,
    require_nc_admin,
)
from gameworld.api.invites import _clean_target  # pyright: ignore[reportPrivateUsage]
from gameworld.api.worlds import ServiceDep
from gameworld.playtime.service import TimeService
from gameworld.worlds.store import WorldStore

LOG = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_nc_admin)])

MSG_ADMIN_FIXED = "Die Gruppe admin verwaltet Gameworld immer."
MSG_UNKNOWN_GROUP = "Diese Gruppe gibt es in Nextcloud nicht."
MSG_CONFLICT = "Die Verwalter-Gruppen wurden gerade geändert. Bitte neu laden."
MSG_SEARCH_UNAVAILABLE = "Die Gruppensuche in Nextcloud ist gerade nicht möglich."
SEARCH_LIMIT = 20

DirectoryDep = Annotated[Directory, Depends(get_directory)]


class GroupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gid: Annotated[str, Field(min_length=1, max_length=GROUP_ID_MAX), AfterValidator(_clean_target)]


class GroupsOut(BaseModel):
    """Zusätzliche Verwalter-Gruppen, sortiert; admin steht nie darin (die Oberfläche stellt es fest voran)."""

    groups: list[str]


class GroupHit(BaseModel):
    id: str
    display_name: str


class GroupSearchOut(BaseModel):
    groups: list[GroupHit]


def _extra_groups(raw: str | None) -> list[str]:
    return sorted(parse_verwalter_groups(raw) - {ADMIN_GROUP})


async def _change(store: WorldStore, edit: set[str], *, add: bool) -> tuple[list[str], bool]:
    """Liest, ändert und schreibt per compare_and_set_meta; ein Konflikt wird einmal neu versucht.

    Gibt die neue Liste und ob sich etwas geändert hat zurück; 409 nach zweitem Konflikt.
    """
    for _attempt in range(2):
        raw = await anyio.to_thread.run_sync(store.get_meta, META_VERWALTER_GROUPS)
        current = set(_extra_groups(raw))
        wanted = current | edit if add else current - edit
        if wanted == current:
            return sorted(current), False
        value = json.dumps(sorted(wanted))
        if await anyio.to_thread.run_sync(store.compare_and_set_meta, META_VERWALTER_GROUPS, raw, value):
            return sorted(wanted), True
    raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_CONFLICT)


async def _follow(uid: str, roles: RolesDep, service: ServiceDep, directory: Directory) -> None:
    """Wirkung sofort: Rollen-Cache weg, Verwalter-Stand ohne Drossel neu (best effort)."""
    roles.invalidate()
    try:
        await TimeService(service, directory).refresh_admins(uid, force=True)
    except Exception as exc:
        LOG.warning("Verwalter-Stand nach Gruppenänderung nicht aufgefrischt: %s", type(exc).__name__)


@router.get("/verwalter-groups")
async def get_verwalter_groups(service: ServiceDep) -> GroupsOut:
    raw = await anyio.to_thread.run_sync(service.store.get_meta, META_VERWALTER_GROUPS)
    return GroupsOut(groups=_extra_groups(raw))


@router.post("/verwalter-groups/add")
async def add_verwalter_group(
    body: GroupIn, uid: NcAdminDep, roles: RolesDep, service: ServiceDep, directory: DirectoryDep
) -> GroupsOut:
    if body.gid == ADMIN_GROUP:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=MSG_ADMIN_FIXED)
    try:
        exists = await directory.group_exists(uid, body.gid)
    except DirectoryUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if not exists:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=MSG_UNKNOWN_GROUP)
    groups, changed = await _change(service.store, {body.gid}, add=True)
    if changed:
        LOG.info("Verwalter-Gruppe ergänzt")
        await _follow(uid, roles, service, directory)
    return GroupsOut(groups=groups)


@router.post("/verwalter-groups/remove")
async def remove_verwalter_group(
    body: GroupIn, uid: NcAdminDep, roles: RolesDep, service: ServiceDep, directory: DirectoryDep
) -> GroupsOut:
    if body.gid == ADMIN_GROUP:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=MSG_ADMIN_FIXED)
    groups, changed = await _change(service.store, {body.gid}, add=False)
    if changed:
        LOG.info("Verwalter-Gruppe entfernt")
        await _follow(uid, roles, service, directory)
    return GroupsOut(groups=groups)


@router.get("/groups")
async def search_groups(
    uid: NcAdminDep, directory: DirectoryDep, search: Annotated[str, Query(max_length=GROUP_ID_MAX)] = ""
) -> GroupSearchOut:
    try:
        hits = await directory.search_groups(uid, search, limit=SEARCH_LIMIT)
    except DirectoryUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_SEARCH_UNAVAILABLE) from None
    return GroupSearchOut(groups=[GroupHit(id=gid, display_name=name) for gid, name in hits[:SEARCH_LIMIT]])
