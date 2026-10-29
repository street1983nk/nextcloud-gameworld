"""Invitations and players (management, ZUGANG-02, ROLLE-02).

The browser supplies only account and group IDs; the backend invites only what
Nextcloud confirms to the manager as an existing, active account or as a group.
Removal runs as POST with a body, because account and group IDs
may contain special characters. New password and rename apply to all
worlds of an account (A2). The adult switch (ROLLE-04) deliberately lives here
in the manager router: only managers set it (D-06), never a child via /api/my/.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import unicodedata
from collections.abc import Callable
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import RolesDep, RoleUnavailableError, require_verwalter
from gameworld.access.secret import PlayerSecret, SecretUnavailableError, get_player_secret
from gameworld.access.service import (
    KIND_GROUP,
    AccessResult,
    AccessService,
    Actor,
    InviteScopeError,
    InviteTargetError,
    PlayerChange,
    PlayerNameTakenError,
    PlayerNotFoundError,
    actor_of,
)
from gameworld.api.worlds import ServiceDep, WorldId
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.service import MSG_ADULT_IS_VERWALTER, TimeService
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import NOT_FOUND
from gameworld.worlds.store import WorldStore

LOG = logging.getLogger(__name__)

# Every route is management: router-wide lock require_verwalter (T-03-22, ROLLE-03).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
MSG_INVALID_TARGET = "Ungültige Konto- oder Gruppen-ID."
MSG_INVALID_HOST = "Bitte nur einen Rechnernamen oder eine IP-Adresse eintragen, ohne http:// und ohne Port."
# Player address (pattern 7): empty means hostname of the browser.
JOIN_HOST_KEY = "join_host"
_HOST_LABEL = re.compile(r"[A-Za-z0-9-]{1,63}")


def _clean_target(value: str) -> str:
    """No empty values, no control or format characters (T-03-18)."""
    if not value.strip() or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise ValueError(MSG_INVALID_TARGET)
    return value


def _clean_host(value: str) -> str:
    """Player address: empty, hostname or IP literal; no scheme, path, port (T-03-42)."""
    if not value:
        return value
    if len(value) > 253 or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise ValueError(MSG_INVALID_HOST)
    if "://" in value or "/" in value:
        raise ValueError(MSG_INVALID_HOST)
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is not None:
        return value
    # A colon is only allowed in IPv6 literals (already accepted above).
    if ":" in value:
        raise ValueError(MSG_INVALID_HOST)
    for label in value.split("."):
        if not _HOST_LABEL.fullmatch(label) or label.startswith("-") or label.endswith("-"):
            raise ValueError(MSG_INVALID_HOST)
    return value


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    join_host: Annotated[str, Field(max_length=253), AfterValidator(_clean_host)]


class SettingsOut(BaseModel):
    join_host: str


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["user", "group"]
    target: Annotated[str, Field(max_length=64), AfterValidator(_clean_target)]


class PlayerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nc_user: Annotated[str, Field(max_length=64), AfterValidator(_clean_target)]


class RenameRequest(PlayerRef):
    # The service checks the Luanti rule (validate_player_name, 422 with a message in German source text).
    player_name: Annotated[str, Field(max_length=20)]


class AdultIn(PlayerRef):
    """Adult switch of an account (ROLLE-04); extra="forbid" like PlayerRef."""

    adult: bool


class AdultOut(BaseModel):
    nc_user: str
    adult: bool
    # Do all worlds of the account already carry the new rules file?
    applied: bool


class PlayerOut(BaseModel):
    nc_user: str
    display_name: str
    player_name: str
    password: str
    via: str
    # Adult switch, manager account, playtime rules (chips of the player list, 06-05).
    adult: bool = False
    verwalter: bool = False
    has_rules: bool = False


class PlayerChangeOut(BaseModel):
    """Player after new password or rename; applied: already effective in all worlds."""

    nc_user: str
    display_name: str
    player_name: str
    password: str
    applied: bool


class InviteOut(BaseModel):
    kind: str
    target: str
    invited_by: str
    created_at: str


class PlayersOut(BaseModel):
    players: list[PlayerOut]
    invites: list[InviteOut]
    # Only on changes: is the new access file already in the world?
    applied: bool | None = None


def get_access_service(
    worlds: ServiceDep,
    directory: Annotated[Directory, Depends(get_directory)],
    secret: Annotated[PlayerSecret, Depends(get_player_secret)],
) -> AccessService:
    """Stateless apart from the singletons behind it; built per request."""
    return AccessService(worlds.store, worlds, directory, secret)


AccessDep = Annotated[AccessService, Depends(get_access_service)]


def get_time_service(
    worlds: ServiceDep,
    directory: Annotated[Directory, Depends(get_directory)],
) -> TimeService:
    """Like api.playtime.get_time_service (cannot be imported there: api.playtime imports this module)."""
    return TimeService(worlds, directory)


TimeDep = Annotated[TimeService, Depends(get_time_service)]


def _player_flags(store: WorldStore) -> tuple[set[str], frozenset[str], set[str]]:
    """Adults, manager union and accounts with rules from the store (worker thread)."""
    return store.adults(), parse_admins(store.get_meta(META_TIME_ADMINS)), set(store.child_plans())


async def _players(
    access: AccessService, store: WorldStore, world_id: str, actor: Actor, result: AccessResult | None
) -> PlayersOut:
    players = await access.list_players(world_id, actor)
    invites = await anyio.to_thread.run_sync(access.list_invites, world_id)
    adults, verwalter, with_rules = await anyio.to_thread.run_sync(_player_flags, store)
    return PlayersOut(
        players=[
            PlayerOut(
                nc_user=player.nc_user,
                display_name=player.display_name,
                player_name=player.player_name,
                password=player.password,
                via=player.via,
                adult=player.nc_user in adults,
                verwalter=player.nc_user in verwalter,
                has_rules=player.nc_user in with_rules,
            )
            for player in players
        ],
        invites=[
            InviteOut(kind=kind, target=target, invited_by=invited_by, created_at=created_at)
            for kind, target, invited_by, created_at in invites
        ],
        applied=None if result is None else result.applied,
    )


def _http_error(exc: Exception) -> HTTPException:
    """Fixed German messages; never exception texts with data from Nextcloud."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, PlayerNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PlayerNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, InviteScopeError):
        # Only the fixed texts MSG_*_OUT_OF_SCOPE (D-01), never Nextcloud data.
        return HTTPException(status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, (InviteTargetError, ValueError)):
        # Only own, fixed messages (MSG_UNKNOWN_*, MSG_INVALID_NAME).
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (
    WorldNotFoundError,
    InviteTargetError,
    InviteScopeError,
    DirectoryUnavailableError,
    SecretUnavailableError,
)
# New password and rename: in addition player missing, name taken, name invalid.
_PLAYER_ERRORS = (*_ERRORS, PlayerNotFoundError, PlayerNameTakenError, ValueError)
VerwalterDep = Annotated[str, Depends(require_verwalter)]


async def current_actor(uid: VerwalterDep, roles: RolesDep) -> Actor:
    """Acting manager from his self-lookup (groups, subadmin groups, D-01)."""
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return actor_of(profile)


ActorDep = Annotated[Actor, Depends(current_actor)]


@router.get("/worlds/{world_id}/players")
async def list_players(world_id: WorldId, access: AccessDep, actor: ActorDep, service: ServiceDep) -> PlayersOut:
    try:
        return await _players(access, service.store, world_id, actor, None)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/invites")
async def invite(
    world_id: WorldId, body: InviteRequest, access: AccessDep, actor: ActorDep, service: ServiceDep
) -> PlayersOut:
    try:
        if body.kind == KIND_GROUP:
            result = await access.invite_group(world_id, actor, body.target)
        else:
            result = await access.invite_user(world_id, actor, body.target)
    except _ERRORS as exc:
        raise _http_error(exc) from None
    # Talk room follows world_access (D-16), best effort and never blocking (D-20).
    _talk_hook(lambda: get_talk_service(service.store).schedule_sync(world_id))
    try:
        return await _players(access, service.store, world_id, actor, result)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/invites/remove")
async def remove_invite(
    world_id: WorldId, body: InviteRequest, access: AccessDep, actor: ActorDep, service: ServiceDep
) -> PlayersOut:
    try:
        result = await access.revoke(world_id, actor, body.kind, body.target)
    except _ERRORS as exc:
        raise _http_error(exc) from None
    _talk_hook(lambda: get_talk_service(service.store).schedule_sync(world_id))
    try:
        return await _players(access, service.store, world_id, actor, result)
    except _ERRORS as exc:
        raise _http_error(exc) from None


def _talk_hook(start: Callable[[], None]) -> None:
    """Starts the Talk reconciliation as a tracked task; an error there never reaches the route (D-20)."""
    try:
        start()
    except Exception as exc:
        LOG.warning("Talk reconciliation not started: %s", type(exc).__name__)


def _change_out(change: PlayerChange) -> PlayerChangeOut:
    return PlayerChangeOut(
        nc_user=change.nc_user,
        display_name=change.display_name,
        player_name=change.player_name,
        password=change.password,
        applied=change.applied,
    )


@router.post("/players/password")
async def reset_password(body: PlayerRef, access: AccessDep, uid: VerwalterDep) -> PlayerChangeOut:
    """New password (T-03-29): the old one stops working at once, in all worlds, without restart."""
    try:
        return _change_out(await access.rotate_password(uid, body.nc_user))
    except _PLAYER_ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/players/adult")
async def set_adult(body: AdultIn, playtime: TimeDep, uid: VerwalterDep) -> AdultOut:
    """Adult switch (ROLLE-04): takes effect immediately in all worlds of the account, on the time rules only."""
    try:
        applied = await playtime.set_adult(uid, body.nc_user, adult=body.adult)
    except ValueError as exc:
        if str(exc) == MSG_ADULT_IS_VERWALTER:
            raise HTTPException(status.HTTP_409_CONFLICT, detail=MSG_ADULT_IS_VERWALTER) from None
        raise _http_error(exc) from None
    except _PLAYER_ERRORS as exc:
        raise _http_error(exc) from None
    return AdultOut(nc_user=body.nc_user, adult=body.adult, applied=applied)


@router.get("/settings")
async def get_settings(service: ServiceDep) -> SettingsOut:
    value = await anyio.to_thread.run_sync(service.store.get_meta, JOIN_HOST_KEY)
    return SettingsOut(join_host=value or "")


@router.post("/settings")
async def save_settings(body: SettingsIn, service: ServiceDep) -> SettingsOut:
    await anyio.to_thread.run_sync(service.store.set_meta, JOIN_HOST_KEY, body.join_host)
    return SettingsOut(join_host=body.join_host)


@router.post("/players/name")
async def rename_player(body: RenameRequest, access: AccessDep, uid: VerwalterDep) -> PlayerChangeOut:
    try:
        return _change_out(await access.rename_player(uid, body.nc_user, body.player_name))
    except _PLAYER_ERRORS as exc:
        raise _http_error(exc) from None
