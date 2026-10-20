"""Einladungen und Spieler (Verwaltung, ZUGANG-02, ROLLE-02).

Der Browser liefert nur Konto- und Gruppen-IDs; das Backend lädt nur ein, was
Nextcloud dem Verwalter als vorhandenes, aktives Konto oder als Gruppe
bestätigt. Entfernen läuft als POST mit Body, weil Konto- und Gruppen-IDs
Sonderzeichen enthalten dürfen. Passwort neu und Umbenennen gelten für alle
Welten eines Kontos (A2).
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import require_verwalter
from gameworld.access.secret import PlayerSecret, SecretUnavailableError, get_player_secret
from gameworld.access.service import (
    KIND_GROUP,
    AccessResult,
    AccessService,
    InviteTargetError,
    PlayerChange,
    PlayerNameTakenError,
    PlayerNotFoundError,
)
from gameworld.api.worlds import ServiceDep, WorldId
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-03-22).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
MSG_INVALID_TARGET = "Ungültige Konto- oder Gruppen-ID."
MSG_INVALID_HOST = "Bitte nur einen Rechnernamen oder eine IP-Adresse eintragen, ohne http:// und ohne Port."
# Spieler-Adresse (Pattern 7): leer heißt Hostname des Browsers.
JOIN_HOST_KEY = "join_host"
_HOST_LABEL = re.compile(r"[A-Za-z0-9-]{1,63}")


def _clean_target(value: str) -> str:
    """Keine leeren Werte, keine Steuer- oder Formatzeichen (T-03-18)."""
    if not value.strip() or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise ValueError(MSG_INVALID_TARGET)
    return value


def _clean_host(value: str) -> str:
    """Spieler-Adresse: leer, Hostname oder IP-Literal; kein Schema, Pfad, Port (T-03-42)."""
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
    # Ein Doppelpunkt ist nur in IPv6-Literalen erlaubt (oben schon angenommen).
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
    # Die Luanti-Regel prüft der Dienst (validate_player_name, 422 mit deutscher Meldung).
    player_name: Annotated[str, Field(max_length=20)]


class PlayerOut(BaseModel):
    nc_user: str
    display_name: str
    player_name: str
    password: str
    via: str


class PlayerChangeOut(BaseModel):
    """Spieler nach Passwort neu oder Umbenennen; applied: in allen Welten schon wirksam."""

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
    # Nur bei Änderungen: Liegt die neue Zugangsdatei schon in der Welt?
    applied: bool | None = None


def get_access_service(
    worlds: ServiceDep,
    directory: Annotated[Directory, Depends(get_directory)],
    secret: Annotated[PlayerSecret, Depends(get_player_secret)],
) -> AccessService:
    """Zustandslos bis auf die Singletons dahinter; je Anfrage gebaut."""
    return AccessService(worlds.store, worlds, directory, secret)


AccessDep = Annotated[AccessService, Depends(get_access_service)]


async def _players(access: AccessService, world_id: str, uid: str, result: AccessResult | None) -> PlayersOut:
    players = await access.list_players(world_id, uid)
    invites = await anyio.to_thread.run_sync(access.list_invites, world_id)
    return PlayersOut(
        players=[
            PlayerOut(
                nc_user=player.nc_user,
                display_name=player.display_name,
                player_name=player.player_name,
                password=player.password,
                via=player.via,
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
    """Feste deutsche Meldungen; nie Ausnahmetexte mit Daten aus Nextcloud."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, PlayerNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, PlayerNameTakenError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (InviteTargetError, ValueError)):
        # Nur eigene, feste Meldungen (MSG_UNKNOWN_*, MSG_INVALID_NAME).
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (WorldNotFoundError, InviteTargetError, DirectoryUnavailableError, SecretUnavailableError)
# Passwort neu und Umbenennen: dazu Spieler fehlt, Name vergeben, Name ungültig.
_PLAYER_ERRORS = (*_ERRORS, PlayerNotFoundError, PlayerNameTakenError, ValueError)
VerwalterDep = Annotated[str, Depends(require_verwalter)]


@router.get("/worlds/{world_id}/players")
async def list_players(world_id: WorldId, access: AccessDep, uid: VerwalterDep) -> PlayersOut:
    try:
        return await _players(access, world_id, uid, None)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/invites")
async def invite(world_id: WorldId, body: InviteRequest, access: AccessDep, uid: VerwalterDep) -> PlayersOut:
    try:
        if body.kind == KIND_GROUP:
            result = await access.invite_group(world_id, uid, body.target)
        else:
            result = await access.invite_user(world_id, uid, body.target)
        return await _players(access, world_id, uid, result)
    except _ERRORS as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/invites/remove")
async def remove_invite(world_id: WorldId, body: InviteRequest, access: AccessDep, uid: VerwalterDep) -> PlayersOut:
    try:
        result = await access.revoke(world_id, uid, body.kind, body.target)
        return await _players(access, world_id, uid, result)
    except _ERRORS as exc:
        raise _http_error(exc) from None


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
    """Passwort neu (T-03-29): Das alte gilt sofort nicht mehr, in allen Welten, ohne Neustart."""
    try:
        return _change_out(await access.rotate_password(uid, body.nc_user))
    except _PLAYER_ERRORS as exc:
        raise _http_error(exc) from None


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
