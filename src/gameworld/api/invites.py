"""Einladungen und Spieler einer Welt (Verwaltung, ZUGANG-02).

Der Browser liefert nur Konto-IDs; das Backend lädt nur ein, was Nextcloud dem
Verwalter als vorhandenes, aktives Konto bestätigt. Entfernen läuft als POST
mit Body, weil Konto- und Gruppen-IDs Sonderzeichen enthalten dürfen.
"""

from __future__ import annotations

import unicodedata
from typing import Annotated, Literal

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import require_verwalter
from gameworld.access.secret import PlayerSecret, SecretUnavailableError, get_player_secret
from gameworld.access.service import AccessResult, AccessService, InviteTargetError
from gameworld.api.worlds import ServiceDep, WorldId
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-03-22).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
MSG_INVALID_TARGET = "Ungültige Konto-ID."


def _clean_target(value: str) -> str:
    """Keine leeren Werte, keine Steuer- oder Formatzeichen (T-03-18)."""
    if not value.strip() or any(unicodedata.category(char) in {"Cc", "Cf"} for char in value):
        raise ValueError(MSG_INVALID_TARGET)
    return value


class InviteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Nur Konten in diesem Stand; Gruppen folgen in 03-04.
    kind: Literal["user"]
    target: Annotated[str, Field(max_length=64), AfterValidator(_clean_target)]


class PlayerOut(BaseModel):
    nc_user: str
    display_name: str
    player_name: str
    password: str
    via: str


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
    if isinstance(exc, InviteTargetError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE)


_ERRORS = (WorldNotFoundError, InviteTargetError, DirectoryUnavailableError, SecretUnavailableError)
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
