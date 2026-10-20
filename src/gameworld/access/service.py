"""Einladungen und Spielerzugang je Welt (ZUGANG-02, ZUGANG-03, ROLLE-02).

Ablauf jeder Änderung:

1. Außerhalb der Sperre (async): Welt prüfen, Konten und Gruppen bei
   Nextcloud im Namen des Verwalters auflösen, Geheimnis laden und dessen
   Fingerabdruck prüfen. Scheitert hier etwas, ist nichts geschrieben (T-03-24).
2. Unter der Welt-Sperre im Worker-Thread: Einladung schreiben, effektive
   Spieler abgleichen, bei Änderung Generation hochzählen und die Zugangsdatei
   sofort in die Welt schreiben (``WorldService.push_access``). Im selben
   Sperrblock schreibt push_access auch die Regeldatei des Zeit-Mods
   (``push_time``): Ein frisch eingeladenes Kind mit Spielzeit-Regeln steht sofort
   mit Zeile in der Regeldatei, nicht erst nach dem nächsten 15-s-Takt.

Effektive Spieler einer Welt sind die direkt eingeladenen Konten plus die
Mitglieder eingeladener Gruppen, jeweils nur, wenn Nextcloud sie als vorhanden
und aktiv bestätigt. Die Mitgliedschaft kommt immer frisch aus Nextcloud
(ROLLE-02); Gameworld speichert nur die Einladung der Gruppe.

Pitfall 6: Gruppen löst nur ein Admin auf (``get_members`` gibt Nicht-Admins
403). Darum laufen Auflösung und Abgleich nur im Verwalter-Kontext.

Sperr-Regel (Deadlock-Schutz): ``worlds._LOCK`` ist ein threading.Lock und
nicht reentrant. ``_ensure_fingerprint`` ist ein eigener asynchroner Schritt
direkt nach dem Laden des Geheimnisses, außerhalb von ``worlds.mutation()``.
``reprovision_all`` nimmt die Sperre selbst und gibt sie frei, bevor die
aufrufende Methode ihren eigenen Schritt unter der Sperre beginnt.

Passwörter, Geheimnis und Verifier werden nie protokolliert.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from time import monotonic

import anyio.to_thread

from gameworld.access.accounts import derive_password, suggest_player_name, validate_player_name
from gameworld.access.directory import Directory, DirectoryUnavailableError, DirectoryUser
from gameworld.access.roles import Profile
from gameworld.access.secret import PlayerSecret, SecretUnavailableError, fingerprint
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds.service import NOT_FOUND, WorldService
from gameworld.worlds.store import PlayerRow, WorldStore

LOG = logging.getLogger(__name__)

KIND_USER = "user"
KIND_GROUP = "group"
FINGERPRINT_KEY = "secret_fingerprint"
# Abgleich beim Verwalter-Besuch höchstens so oft (pro Prozess, T-03-26).
SYNC_INTERVAL_SECONDS = 60

MSG_UNKNOWN_ACCOUNT = "Dieses Nextcloud-Konto gibt es nicht oder es ist deaktiviert."
MSG_UNKNOWN_GROUP = "Diese Nextcloud-Gruppe gibt es nicht."
MSG_NO_PLAYER = "Für dieses Nextcloud-Konto gibt es noch keinen Spieler."
MSG_NAME_TAKEN = "Diesen Spielernamen hat schon jemand anderes."
MSG_REPROVISION_PENDING = "Die Zugangsdaten werden gerade erneuert; bitte gleich noch einmal abrufen."

InviteKey = tuple[str, str]


class InviteTargetError(Exception):
    """Das Ziel einer Einladung ist kein vorhandenes, aktives Konto oder keine Gruppe (HTTP 422)."""


class PlayerNotFoundError(Exception):
    """Zu diesem Konto gibt es keinen Spieler (HTTP 404)."""


class PlayerNameTakenError(Exception):
    """Der Spielername gehört ohne Rücksicht auf Groß-/Kleinschreibung schon einem anderen Konto (HTTP 409)."""


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


@dataclass(frozen=True)
class PlayerChange:
    """Ergebnis von Passwort neu und Umbenennen; applied wie bei AccessResult, über alle Welten."""

    nc_user: str
    display_name: str
    player_name: str
    password: str
    applied: bool


@dataclass(frozen=True)
class MyWorld:
    """Zugangsdaten des anfragenden Kontos für eine Welt (nur eigene Daten, Pitfall 7)."""

    world_id: str
    player_name: str
    password: str


@dataclass
class SyncState:
    """Zeitpunkt (monotonic) des letzten Abgleichs beim Verwalter-Besuch."""

    last: float | None = None


SYNC_STATE = SyncState()


@dataclass
class _Resolution:
    """Effektive Spieler samt der Einladungen, über die sie kommen."""

    effective: dict[str, DirectoryUser] = field(default_factory=dict[str, DirectoryUser])
    sources: dict[str, set[InviteKey]] = field(default_factory=dict[str, set[InviteKey]])
    resolved: set[InviteKey] = field(default_factory=set[InviteKey])


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
        await self._ensure_fingerprint(secret)
        invites = await self._invite_keys(world_id) | {(KIND_USER, user.uid)}
        resolution = await self._resolve(acting_uid, invites, {user.uid: user})
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def change() -> None:
            self._store.add_invite(world_id, KIND_USER, user.uid, acting_uid, created_at)

        return await self._apply(world_id, change, resolution, secret)

    async def invite_group(self, world_id: str, acting_uid: str, gid: str) -> AccessResult:
        """Lädt eine Nextcloud-Gruppe ein; ihre aktiven Mitglieder bekommen Zugang (ZUGANG-02)."""
        await self._require_world(world_id)
        if not await self._directory.group_exists(acting_uid, gid):
            raise InviteTargetError(MSG_UNKNOWN_GROUP)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        invites = await self._invite_keys(world_id) | {(KIND_GROUP, gid)}
        resolution = await self._resolve(acting_uid, invites)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def change() -> None:
            self._store.add_invite(world_id, KIND_GROUP, gid, acting_uid, created_at)

        return await self._apply(world_id, change, resolution, secret)

    async def revoke(self, world_id: str, acting_uid: str, kind: str, target: str) -> AccessResult:
        await self._require_world(world_id)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        # Auch den widerrufenen Schlüssel auflösen: So ist unter der Sperre
        # bekannt, wer nur über ihn Zugang hatte, und die keep-Regel kann den
        # Widerruf nicht still rückgängig machen (siehe _apply_sync).
        invites = await self._invite_keys(world_id) | {(kind, target)}
        resolution = await self._resolve(acting_uid, invites)

        def change() -> None:
            self._store.remove_invite(world_id, kind, target)

        return await self._apply(world_id, change, resolution, secret, revoked=(kind, target))

    async def sync_world(self, world_id: str, acting_uid: str) -> AccessResult:
        """Gleicht eine Welt mit Nextcloud ab: neue Gruppenmitglieder rein, Ausgetretene raus."""
        await self._require_world(world_id)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        result = await self._sync(world_id, acting_uid, secret, blocking=True)
        return AccessResult(applied=True) if result is None else result

    async def sync_all(self, acting_uid: str) -> bool:
        """Abgleich aller Welten beim Verwalter-Besuch, höchstens alle SYNC_INTERVAL_SECONDS.

        Wartet nie auf die Welt-Sperre: Läuft gerade eine Aktion (etwa ein
        Erzeugen), wird die betroffene Welt übersprungen und der nächste Besuch
        versucht es erneut. Ein Fehler einer Welt bricht die anderen nicht ab.
        True, wenn ein Abgleich lief.
        """
        now = monotonic()
        if SYNC_STATE.last is not None and now - SYNC_STATE.last < SYNC_INTERVAL_SECONDS:
            return False
        SYNC_STATE.last = now
        secret = await self._secret.get()
        if not await self._ensure_fingerprint(secret, blocking=False):
            SYNC_STATE.last = None
            return False
        busy = False
        for row in await anyio.to_thread.run_sync(self._store.list_worlds):
            try:
                result = await self._sync(row.id, acting_uid, secret, blocking=False)
            except Exception as exc:
                LOG.warning("Abgleich von Welt %s gescheitert: %s", row.id, type(exc).__name__)
                continue
            busy = busy or result is None
        if busy:
            SYNC_STATE.last = None
        return True

    async def rotate_password(self, acting_uid: str, nc_user: str) -> PlayerChange:
        """Passwort neu (T-03-29): Rotation +1, alle Verifier des Kontos neu, ohne Welt-Neustart."""
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)

        def run() -> tuple[PlayerRow, bool]:
            with self._worlds.mutation():
                player = self._require_player(nc_user)
                updated = replace(player, rotation=player.rotation + 1)
                return updated, self._rewrite_player(updated, secret)

        player, applied = await anyio.to_thread.run_sync(run)
        return await self._change(acting_uid, player, secret, applied)

    async def rename_player(self, acting_uid: str, nc_user: str, new_name: str) -> PlayerChange:
        """Neuer Spielername für alle Welten des Kontos.

        In Luanti ist das ein neues Konto: Inventar und Rechte des alten Namens
        bleiben in der Welt verwaist zurück.
        """
        name = validate_player_name(new_name)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)

        def run() -> tuple[PlayerRow, bool]:
            with self._worlds.mutation():
                player = self._require_player(nc_user)
                owner = self._store.player_name_owner(name)
                if owner is not None and owner != nc_user:
                    raise PlayerNameTakenError(MSG_NAME_TAKEN)
                if player.player_name == name:
                    return player, True
                updated = replace(player, player_name=name)
                return updated, self._rewrite_player(updated, secret)

        player, applied = await anyio.to_thread.run_sync(run)
        return await self._change(acting_uid, player, secret, applied)

    async def list_players(self, world_id: str, acting_uid: str) -> list[PlayerInfo]:
        await self._require_world(world_id)
        secret = await self._secret.get()
        # Eigener Schritt außerhalb von worlds.mutation() (Sperr-Regel, nicht
        # reentrant). Wie WR-02 bei my_worlds (AR-25, T-03-30): Konnte nach
        # einem Geheimniswechsel wegen belegter Sperre noch nicht neu
        # provisioniert werden, zeigt die Verwalteransicht kein Passwort, das
        # die Welten noch nicht kennen (503 beim Aufrufer).
        if not await self._ensure_fingerprint(secret, blocking=False):
            raise SecretUnavailableError(MSG_REPROVISION_PENDING)
        access = await anyio.to_thread.run_sync(self._store.world_access, world_id)
        invites = await self._invite_keys(world_id)
        direct = {target for kind, target in invites if kind == KIND_USER}
        groups = sorted(target for kind, target in invites if kind == KIND_GROUP)
        members: dict[str, set[str]] = {}
        for gid in groups:
            try:
                found = await self._directory.group_members(acting_uid, gid)
            except DirectoryUnavailableError:
                found = None
            members[gid] = set(found or [])
        players: list[PlayerInfo] = []
        for nc_user in sorted(access):
            player = await anyio.to_thread.run_sync(self._store.get_player, nc_user)
            if player is None:
                continue
            via = KIND_USER
            if nc_user not in direct:
                via = next((f"{KIND_GROUP}:{gid}" for gid in groups if nc_user in members[gid]), KIND_GROUP)
            players.append(
                PlayerInfo(
                    nc_user=nc_user,
                    display_name=await self._display_name(acting_uid, nc_user),
                    player_name=player.player_name,
                    password=derive_password(secret, nc_user, player.rotation),
                    via=via,
                )
            )
        return players

    async def my_worlds(self, profile: Profile) -> list[MyWorld]:
        """Eigene Welten samt Zugangsdaten, nur für profile.user_id (ZUGANG-04, ROLLE-01).

        Das Profil stammt aus der Selbstauskunft im Namen des angemeldeten
        Kontos (signierte AppAPI-Anfrage), nie aus Daten des Browsers.

        Lazy Provisionierung (ZUGANG-02 ohne Verwalter-Besuch): Steht eine der
        eigenen Gruppen in einer Gruppen-Einladung und hat das Konto dort noch
        keinen Zugang, bekommt es ihn jetzt. Nur Hinzufügen: Entfernen braucht
        die Gruppenauflösung im Verwalter-Kontext (Pitfall 6), siehe sync_all.

        Wartet nie auf die Welt-Sperre (Polling alle 5 s darf nie hinter einem
        Erzeugen hängen und keine Worker-Threads stapeln): Bei belegter Sperre
        folgen Fingerabdruck-Abgleich und Provisionierung beim nächsten Abruf.

        Konnte nach einem Geheimniswechsel wegen belegter Sperre noch nicht neu
        provisioniert werden, antwortet der Abruf mit SecretUnavailableError
        (503 beim Aufrufer): Die Welten tragen dann noch die alten Verifier,
        und ein Passwort aus dem neuen Geheimnis wäre irreführend; das Kind
        tippte sich damit in die Fehlversuch-Sperre des Welt-Mods.
        """
        uid = profile.user_id
        secret = await self._secret.get()
        # Eigener Schritt außerhalb von worlds.mutation() (Sperr-Regel, nicht reentrant).
        if not await self._ensure_fingerprint(secret, blocking=False):
            # Lieber kurz nicht verfügbar als ein noch nicht gültiges Passwort
            # anzeigen; der 5-s-Poll versucht es ohnehin gleich erneut.
            raise SecretUnavailableError(MSG_REPROVISION_PENDING)
        groups = set(profile.groups)
        pending = await anyio.to_thread.run_sync(self._pending_group_worlds, uid, groups)
        if pending:
            user = DirectoryUser(uid=uid, display_name=profile.display_name, enabled=True)
            await anyio.to_thread.run_sync(self._provision_self, pending, user, groups, secret)
        return await anyio.to_thread.run_sync(self._my_worlds_sync, uid, secret)

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

    async def _invite_keys(self, world_id: str) -> set[InviteKey]:
        invites = await anyio.to_thread.run_sync(self._store.list_invites, world_id)
        return {(invite.kind, invite.target) for invite in invites}

    async def _resolve(
        self, acting_uid: str, invites: set[InviteKey], known: dict[str, DirectoryUser] | None = None
    ) -> _Resolution:
        """Löst Einladungen bei Nextcloud auf, als handelnder Verwalter (Pitfall 6).

        Eine fehlende Gruppe zählt als leer. Jedes Konto wird höchstens einmal
        abgefragt, auch wenn es direkt und über Gruppen eingeladen ist.
        """
        cache: dict[str, DirectoryUser | None] = dict(known or {})
        resolution = _Resolution()
        for kind, target in sorted(invites):
            members = None if kind == KIND_USER else await self._directory.group_members(acting_uid, target)
            uids = [target] if kind == KIND_USER else (members or [])
            for uid in uids:
                if uid not in cache:
                    cache[uid] = await self._directory.user(acting_uid, uid)
                user = cache[uid]
                if user is not None and user.enabled:
                    resolution.effective[user.uid] = user
                    resolution.sources.setdefault(user.uid, set()).add((kind, target))
            resolution.resolved.add((kind, target))
        return resolution

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name

    async def _change(self, acting_uid: str, player: PlayerRow, secret: bytes, applied: bool) -> PlayerChange:
        return PlayerChange(
            nc_user=player.nc_user,
            display_name=await self._display_name(acting_uid, player.nc_user),
            player_name=player.player_name,
            password=derive_password(secret, player.nc_user, player.rotation),
            applied=applied,
        )

    async def _ensure_fingerprint(self, secret: bytes, *, blocking: bool = True) -> bool:
        """Erkennt ein neues Geheimnis am Fingerabdruck (T-03-30); False nur, wenn nicht gewartet wurde.

        Eigener Schritt außerhalb von worlds.mutation(): Nie aus Code heraus
        aufrufen, der die Welt-Sperre hält (nicht reentrant).
        """
        current = fingerprint(secret)
        stored = await anyio.to_thread.run_sync(self._store.get_meta, FINGERPRINT_KEY)
        if stored == current:
            return True
        if stored is None:
            # Erster Lauf: Die vorhandenen Verifier stammen aus diesem Geheimnis.
            await anyio.to_thread.run_sync(self._store.set_meta, FINGERPRINT_KEY, current)
            return True
        LOG.warning("Das Spielgeheimnis in Nextcloud hat sich geändert; alle Welten bekommen neue Zugangsdaten")
        return await anyio.to_thread.run_sync(self.reprovision_all, secret, blocking)

    async def _apply(
        self,
        world_id: str,
        change: Callable[[], None],
        resolution: _Resolution,
        secret: bytes,
        revoked: InviteKey | None = None,
    ) -> AccessResult:
        result = await anyio.to_thread.run_sync(self._apply_sync, world_id, change, resolution, secret, True, revoked)
        return AccessResult(applied=True) if result is None else result

    async def _sync(self, world_id: str, acting_uid: str, secret: bytes, *, blocking: bool) -> AccessResult | None:
        resolution = await self._resolve(acting_uid, await self._invite_keys(world_id))
        return await anyio.to_thread.run_sync(self._apply_sync, world_id, None, resolution, secret, blocking)

    # Unter der Sperre (Worker-Thread)

    @contextlib.contextmanager
    def _locked(self, blocking: bool) -> Iterator[bool]:
        if blocking:
            with self._worlds.mutation():
                yield True
        else:
            with self._worlds.try_mutation() as acquired:
                yield acquired

    def reprovision_all(self, secret: bytes, blocking: bool = True) -> bool:
        """Neue Verifier in allen Welten nach einem Wechsel des Geheimnisses.

        Nimmt worlds.mutation() selbst, einmal für alle Welten, speichert den
        neuen Fingerabdruck in derselben Sperrphase und gibt die Sperre vor der
        Rückkehr frei. Ruft nie _ensure_fingerprint. False nur ohne Warten bei
        belegter Sperre.
        """
        current = fingerprint(secret)
        with self._locked(blocking) as acquired:
            if not acquired:
                return False
            if self._store.get_meta(FINGERPRINT_KEY) == current:
                return True
            changed: list[str] = []
            for row in self._store.list_worlds():
                access = self._store.world_access(row.id)
                if not access:
                    continue
                target: dict[str, str] = {}
                for uid in access:
                    player = self._store.get_player(uid)
                    if player is not None:
                        target[uid] = self._verifier(player, secret)
                self._store.apply_world_access(row.id, target)
                changed.append(row.id)
            self._store.set_meta(FINGERPRINT_KEY, current)
            for world_id in changed:
                self._worlds.push_access(world_id)
        return True

    def _apply_sync(
        self,
        world_id: str,
        change: Callable[[], None] | None,
        resolution: _Resolution,
        secret: bytes,
        blocking: bool,
        revoked: InviteKey | None = None,
    ) -> AccessResult | None:
        """None nur ohne Warten bei belegter Sperre."""
        with self._locked(blocking) as acquired:
            if not acquired:
                return None
            if self._store.get_world(world_id) is None:
                raise WorldNotFoundError(NOT_FOUND)
            if change is not None:
                change()
            current_keys = {(invite.kind, invite.target) for invite in self._store.list_invites(world_id)}
            wanted = {
                uid: user
                for uid, user in resolution.effective.items()
                if resolution.sources.get(uid, set()) & current_keys
            }
            # Parallel neu Eingeladene (nicht aufgelöst) behalten ihren Stand bis zum nächsten Abgleich.
            keep: set[str] = set()
            unresolved = current_keys - resolution.resolved
            for kind, target in unresolved:
                if kind == KIND_USER:
                    keep.add(target)
                else:
                    keep |= set(self._store.world_access(world_id))
            if unresolved:
                # Der Blick auf die Einladungen war veraltet: Drossel aufheben,
                # der nächste Verwalter-Besuch gleicht sofort ab.
                SYNC_STATE.last = None
            if revoked is not None:
                # Ein expliziter Widerruf gewinnt gegen die keep-Regel: Konten,
                # die nur über den widerrufenen Schlüssel Zugang hatten, werden
                # nie still zurückgeholt; der nächste Abgleich ergänzt, was eine
                # parallele Einladung legitim hinzugefügt hat.
                if revoked[0] == KIND_USER:
                    keep.discard(revoked[1])
                for uid, sources in resolution.sources.items():
                    if revoked in sources and uid not in wanted:
                        keep.discard(uid)
            if not self._apply_effective(world_id, wanted, keep, secret):
                return AccessResult(applied=True)
            return AccessResult(applied=self._worlds.push_access(world_id))

    def _apply_effective(
        self, world_id: str, effective: dict[str, DirectoryUser], keep: set[str], secret: bytes
    ) -> bool:
        """Gleicht world_access mit den effektiven Spielern ab; True bei Änderung.

        Läuft unter worlds.mutation(); ruft nie _ensure_fingerprint. Fehlende
        Spieler bekommen einen Namen; Verifier entstehen nur für neue Einträge,
        vorhandene bleiben samt Salz stehen (deterministische Datei).
        """
        current = self._store.world_access(world_id)
        target: dict[str, str] = {uid: current[uid] for uid in keep if uid in current}
        for uid, user in sorted(effective.items()):
            if uid in current:
                target[uid] = current[uid]
                continue
            player = self._ensure_player(user)
            target[uid] = self._verifier(player, secret)
        if target == current:
            return False
        self._store.apply_world_access(world_id, target)
        return True

    def _pending_group_worlds(self, uid: str, groups: set[str]) -> list[str]:
        """Welten mit Einladung einer eigenen Gruppe, in denen das Konto noch keinen Zugang hat."""
        return [
            world_id
            for world_id in self._store.group_invited_worlds(groups)
            if uid not in self._store.world_access(world_id)
        ]

    def _provision_self(self, world_ids: list[str], user: DirectoryUser, groups: set[str], secret: bytes) -> None:
        """Ergänzt das eigene Konto in Welten seiner Gruppen-Einladungen; nur Hinzufügen.

        Ohne Warten auf die Sperre; unter ihr wird jede Welt neu geprüft (Welt
        gelöscht, Einladung entfernt, schon eingetragen). Ruft nie _ensure_fingerprint.
        """
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                return
            invited = set(self._store.group_invited_worlds(groups))
            for world_id in world_ids:
                if world_id not in invited or self._store.get_world(world_id) is None:
                    continue
                current = self._store.world_access(world_id)
                if user.uid in current:
                    continue
                player = self._ensure_player(user)
                self._store.apply_world_access(world_id, {**current, user.uid: self._verifier(player, secret)})
                LOG.info("Welt %s: Konto über eigene Gruppen-Einladung ergänzt", world_id)
                self._worlds.push_access(world_id)

    def _my_worlds_sync(self, uid: str, secret: bytes) -> list[MyWorld]:
        player = self._store.get_player(uid)
        if player is None:
            return []
        password = derive_password(secret, uid, player.rotation)
        return [
            MyWorld(world_id=world_id, player_name=player.player_name, password=password)
            for world_id in self._store.player_worlds(uid)
        ]

    def _rewrite_player(self, player: PlayerRow, secret: bytes) -> bool:
        """Neuer Name oder neue Rotation: alle Verifier des Kontos neu, in einer Transaktion.

        Läuft unter worlds.mutation(); ruft nie _ensure_fingerprint. Danach
        wird jede betroffene Welt sofort beschrieben (kein Neustart nötig).
        """
        world_ids = self._store.player_worlds(player.nc_user)
        verifiers = {world_id: self._verifier(player, secret) for world_id in world_ids}
        self._store.update_player_access(player, verifiers)
        pushed = [self._worlds.push_access(world_id) for world_id in world_ids]
        return all(pushed)

    def _require_player(self, nc_user: str) -> PlayerRow:
        player = self._store.get_player(nc_user)
        if player is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)
        return player

    @staticmethod
    def _verifier(player: PlayerRow, secret: bytes) -> str:
        """Frischer Verifier mit neuem Salz; Passwort nur im Speicher."""
        return make_verifier(player.player_name, derive_password(secret, player.nc_user, player.rotation))

    def _ensure_player(self, user: DirectoryUser) -> PlayerRow:
        player = self._store.get_player(user.uid)
        if player is None:
            name = suggest_player_name(user.display_name, user.uid, self._store.player_names())
            player = PlayerRow(nc_user=user.uid, player_name=name, rotation=0)
            self._store.insert_player(player)
            LOG.info("Spielername %s für ein Nextcloud-Konto angelegt", name)
        return player
