"""Einladungen und Spielerzugang je Welt (ZUGANG-02, ZUGANG-03).

Ablauf jeder Änderung:

1. Außerhalb der Sperre (async): Welt prüfen, Konten bei Nextcloud im Namen
   des Verwalters bestätigen lassen, Geheimnis laden. Scheitert hier etwas,
   ist nichts geschrieben (T-03-24).
2. Unter der Welt-Sperre im Worker-Thread: Einladung schreiben, effektive
   Spieler abgleichen, bei Änderung Generation hochzählen und die Zugangsdatei
   sofort in die Welt schreiben (``WorldService.push_access``).

Effektive Spieler sind in diesem Stand die direkt eingeladenen Konten, die
Nextcloud als vorhanden und aktiv bestätigt (Gruppen folgen in 03-04).
Passwörter, Geheimnis und Verifier werden nie protokolliert.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import anyio.to_thread

from gameworld.access.accounts import derive_password, suggest_player_name
from gameworld.access.directory import Directory, DirectoryUnavailableError, DirectoryUser
from gameworld.access.secret import PlayerSecret
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds.service import NOT_FOUND, WorldService
from gameworld.worlds.store import PlayerRow, WorldStore

LOG = logging.getLogger(__name__)

KIND_USER = "user"
MSG_UNKNOWN_ACCOUNT = "Dieses Nextcloud-Konto gibt es nicht oder es ist deaktiviert."


class InviteTargetError(Exception):
    """Das Ziel einer Einladung ist kein vorhandenes, aktives Nextcloud-Konto (HTTP 422)."""


@dataclass(frozen=True)
class AccessResult:
    """applied: Die Zugangsdatei der Welt entspricht der Datenbank.

    False heißt, die Welt hat (noch) keinen Container oder Docker war nicht
    erreichbar; der nächste Start schreibt die Datei.
    """

    applied: bool


@dataclass(frozen=True)
class PlayerInfo:
    nc_user: str
    display_name: str
    player_name: str
    password: str
    via: str


class AccessService:
    def __init__(self, store: WorldStore, worlds: WorldService, directory: Directory, secret: PlayerSecret) -> None:
        self._store = store
        self._worlds = worlds
        self._directory = directory
        self._secret = secret

    # Öffentliche Abläufe

    async def invite_user(self, world_id: str, acting_uid: str, uid: str) -> AccessResult:
        await self._require_world(world_id)
        user = await self._directory.user(acting_uid, uid)
        if user is None or not user.enabled:
            raise InviteTargetError(MSG_UNKNOWN_ACCOUNT)
        secret = await self._secret.get()
        others = {invite for invite in await self._user_invites(world_id) if invite != user.uid}
        effective, checked = await self._confirm(acting_uid, others)
        effective[user.uid] = user
        checked.add(user.uid)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def change() -> None:
            self._store.add_invite(world_id, KIND_USER, user.uid, acting_uid, created_at)

        return await anyio.to_thread.run_sync(self._apply_sync, world_id, change, effective, checked, secret)

    async def revoke(self, world_id: str, acting_uid: str, kind: str, target: str) -> AccessResult:
        await self._require_world(world_id)
        secret = await self._secret.get()
        removed = target if kind == KIND_USER else None
        remaining = {invite for invite in await self._user_invites(world_id) if invite != removed}
        effective, checked = await self._confirm(acting_uid, remaining)

        def change() -> None:
            self._store.remove_invite(world_id, kind, target)

        return await anyio.to_thread.run_sync(self._apply_sync, world_id, change, effective, checked, secret)

    async def list_players(self, world_id: str, acting_uid: str) -> list[PlayerInfo]:
        await self._require_world(world_id)
        secret = await self._secret.get()
        access = await anyio.to_thread.run_sync(self._store.world_access, world_id)
        players: list[PlayerInfo] = []
        for nc_user in sorted(access):
            player = await anyio.to_thread.run_sync(self._store.get_player, nc_user)
            if player is None:
                continue
            players.append(
                PlayerInfo(
                    nc_user=nc_user,
                    display_name=await self._display_name(acting_uid, nc_user),
                    player_name=player.player_name,
                    password=derive_password(secret, nc_user, player.rotation),
                    via=KIND_USER,
                )
            )
        return players

    def list_invites(self, world_id: str) -> list[tuple[str, str, str, str]]:
        """Einladungen als (kind, target, invited_by, created_at), für die Verwalteransicht."""
        return [
            (invite.kind, invite.target, invite.invited_by, invite.created_at)
            for invite in self._store.list_invites(world_id)
        ]

    # Hilfen außerhalb der Sperre

    async def _require_world(self, world_id: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_world, world_id) is None:
            raise WorldNotFoundError(NOT_FOUND)

    async def _user_invites(self, world_id: str) -> set[str]:
        invites = await anyio.to_thread.run_sync(self._store.list_invites, world_id)
        return {invite.target for invite in invites if invite.kind == KIND_USER}

    async def _confirm(self, acting_uid: str, uids: set[str]) -> tuple[dict[str, DirectoryUser], set[str]]:
        """Bestätigt Konten bei Nextcloud; liefert die aktiven und alle geprüften IDs."""
        effective: dict[str, DirectoryUser] = {}
        checked: set[str] = set()
        for uid in sorted(uids):
            user = await self._directory.user(acting_uid, uid)
            checked.add(uid)
            if user is not None and user.enabled:
                effective[uid] = user
        return effective, checked

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name

    # Unter der Sperre (Worker-Thread)

    def _apply_sync(
        self,
        world_id: str,
        change: Callable[[], None],
        effective: dict[str, DirectoryUser],
        checked: set[str],
        secret: bytes,
    ) -> AccessResult:
        with self._worlds.mutation():
            if self._store.get_world(world_id) is None:
                raise WorldNotFoundError(NOT_FOUND)
            change()
            invited = {invite.target for invite in self._store.list_invites(world_id) if invite.kind == KIND_USER}
            # Eingeladen und bestätigt; parallel neu Eingeladene (nicht geprüft) behalten ihren Stand.
            wanted = {uid: user for uid, user in effective.items() if uid in invited}
            keep = {uid for uid in invited if uid not in checked}
            if not self._apply_effective(world_id, wanted, keep, secret):
                return AccessResult(applied=True)
            return AccessResult(applied=self._worlds.push_access(world_id))

    def _apply_effective(
        self, world_id: str, effective: dict[str, DirectoryUser], keep: set[str], secret: bytes
    ) -> bool:
        """Gleicht world_access mit den effektiven Spielern ab; True bei Änderung.

        Fehlende Spieler bekommen einen Namen; Verifier entstehen nur für neue
        Einträge, vorhandene bleiben samt Salz stehen (deterministische Datei).
        """
        current = self._store.world_access(world_id)
        target: dict[str, str] = {uid: current[uid] for uid in keep if uid in current}
        for uid, user in sorted(effective.items()):
            if uid in current:
                target[uid] = current[uid]
                continue
            player = self._ensure_player(user)
            target[uid] = make_verifier(player.player_name, derive_password(secret, uid, player.rotation))
        if target == current:
            return False
        self._store.apply_world_access(world_id, target)
        return True

    def _ensure_player(self, user: DirectoryUser) -> PlayerRow:
        player = self._store.get_player(user.uid)
        if player is None:
            name = suggest_player_name(user.display_name, user.uid, self._store.player_names())
            player = PlayerRow(nc_user=user.uid, player_name=name, rotation=0)
            self._store.insert_player(player)
            LOG.info("Spielername %s für ein Nextcloud-Konto angelegt", name)
        return player
