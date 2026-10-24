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

Pitfall 6: Gruppen löst Nextcloud nur Admins, Subadmins und Mitgliedern der
Gruppe auf (``/cloud/groups/{gid}/users``, sonst 403). Darum laufen Auflösung und
Abgleich nur im Verwalter-Kontext.

Seit Phase 6 (ROLLE-03, D-01) gibt es Verwalter ohne Nextcloud-Adminrecht. Für
sie gilt die Regel "404 heißt gelöscht nur als NC-Admin" (P-01, 404-Falle):
Nextcloud zeigt einem Gruppen-Verwalter fremde Konten als 404. Darum fragt
Gameworld in ihrem Namen nie ``user()`` je Konto ab, entfernt nie eine direkte
Einladung wegen einer fehlenden Antwort und bricht den Abgleich einer Welt ohne
Änderung ab, sobald eine ihrer Gruppen für sie nicht lesbar ist. Eingeladen
werden nur Konten und Gruppen aus den eigenen Gruppen und Subadmin-Gruppen
(``Actor.groups``); alles andere scheitert vor jeder Store-Änderung mit
``InviteScopeError`` (HTTP 403). Deaktivierte Konten erkennt nur der Abgleich
eines NC-Admins. Ob ein Actor NC-Admin ist, prüft jeder ändernde Ablauf vorher
frisch an der Gruppe admin (``_confirmed``): Ein gemerktes Profil darf nie den
gefährlichen Pfad öffnen.

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

from gameworld.access.accounts import derive_password, new_player_salt, suggest_player_name, validate_player_name
from gameworld.access.directory import (
    MSG_UNAVAILABLE,
    Directory,
    DirectoryRejectedError,
    DirectoryUnavailableError,
    DirectoryUser,
)
from gameworld.access.roles import ADMIN_GROUP, Profile
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
# Einladungs-Umfang eines Gruppen-Verwalters (D-01, UI-SPEC B1), HTTP 403.
MSG_ACCOUNT_OUT_OF_SCOPE = "Dieses Konto ist in keiner deiner Gruppen."
MSG_GROUP_OUT_OF_SCOPE = "Diese Gruppe gehört nicht zu deinen Gruppen."

InviteKey = tuple[str, str]


class InviteTargetError(Exception):
    """Das Ziel einer Einladung ist kein vorhandenes, aktives Konto oder keine Gruppe (HTTP 422)."""


class InviteScopeError(Exception):
    """Das Ziel liegt außerhalb der eigenen Gruppen und Subadmin-Gruppen des Verwalters (HTTP 403, D-01)."""


class PlayerNotFoundError(Exception):
    """Zu diesem Konto gibt es keinen Spieler (HTTP 404)."""


class PlayerNameTakenError(Exception):
    """Der Spielername gehört ohne Rücksicht auf Groß-/Kleinschreibung schon einem anderen Konto (HTTP 409)."""


@dataclass(frozen=True)
class Actor:
    """Handelnder Verwalter einer Änderung.

    nc_admin: Mitglied der Gruppe admin laut Profil; ändernde Abläufe bestätigen
    das vorher frisch (``AccessService._confirmed``). groups: eigene Gruppen plus
    Subadmin-Gruppen, der Einladungs-Umfang eines Nicht-Admins (D-01).
    """

    uid: str
    nc_admin: bool
    groups: frozenset[str] = frozenset()


def actor_of(profile: Profile) -> Actor:
    """Actor aus der Selbstauskunft des angemeldeten Kontos (nie aus Daten des Browsers)."""
    return Actor(
        uid=profile.user_id,
        nc_admin=ADMIN_GROUP in profile.groups,
        groups=frozenset(profile.groups) | frozenset(profile.subadmin),
    )


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
    # Direkt eingeladene Konten, die ein Nicht-Admin nicht prüfen kann: Zugang bleibt, wie er ist.
    kept: set[str] = field(default_factory=set[str])


class AccessService:
    def __init__(self, store: WorldStore, worlds: WorldService, directory: Directory, secret: PlayerSecret) -> None:
        self._store = store
        self._worlds = worlds
        self._directory = directory
        self._secret = secret

    # Öffentliche Abläufe

    async def invite_user(self, world_id: str, actor: Actor, uid: str) -> AccessResult:
        """Lädt ein Konto ein; als Nicht-Admin nur aus den eigenen Gruppen (D-01), ohne Kontoabfrage."""
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        if actor.nc_admin:
            user = await self._directory.user(actor.uid, uid)
            if user is None or not user.enabled:
                raise InviteTargetError(MSG_UNKNOWN_ACCOUNT)
        else:
            await self._require_account_in_scope(actor, uid)
            user = DirectoryUser(uid=uid, display_name=uid, enabled=True)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        invites = await self._invite_keys(world_id) | {(KIND_USER, user.uid)}
        resolution = await self._resolve(actor, invites, {user.uid: user}, strict=False)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def change() -> None:
            self._store.add_invite(world_id, KIND_USER, user.uid, actor.uid, created_at)

        return await self._apply(world_id, change, resolution, secret)

    async def invite_group(self, world_id: str, actor: Actor, gid: str) -> AccessResult:
        """Lädt eine Nextcloud-Gruppe ein; ihre aktiven Mitglieder bekommen Zugang (ZUGANG-02).

        Ein Nicht-Admin lädt nur eigene Gruppen und Subadmin-Gruppen ein (D-01).
        """
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        if not actor.nc_admin and gid not in actor.groups:
            raise InviteScopeError(MSG_GROUP_OUT_OF_SCOPE)
        if not await self._directory.group_exists(actor.uid, gid):
            raise InviteTargetError(MSG_UNKNOWN_GROUP)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        invites = await self._invite_keys(world_id) | {(KIND_GROUP, gid)}
        resolution = await self._resolve(actor, invites, strict=False)
        created_at = datetime.now(UTC).isoformat(timespec="seconds")

        def change() -> None:
            self._store.add_invite(world_id, KIND_GROUP, gid, actor.uid, created_at)

        return await self._apply(world_id, change, resolution, secret)

    async def revoke(self, world_id: str, actor: Actor, kind: str, target: str) -> AccessResult:
        """Entfernt eine Einladung. Löst die übrigen auf und braucht darum wie der Abgleich einen Actor (P-01)."""
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        # Auch den widerrufenen Schlüssel auflösen: So ist unter der Sperre
        # bekannt, wer nur über ihn Zugang hatte, und die keep-Regel kann den
        # Widerruf nicht still rückgängig machen (siehe _apply_sync).
        invites = await self._invite_keys(world_id) | {(kind, target)}
        resolution = await self._resolve(actor, invites, strict=False)

        def change() -> None:
            self._store.remove_invite(world_id, kind, target)

        return await self._apply(world_id, change, resolution, secret, revoked=(kind, target))

    async def sync_world(self, world_id: str, actor: Actor) -> AccessResult:
        """Gleicht eine Welt mit Nextcloud ab: neue Gruppenmitglieder rein, Ausgetretene raus."""
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        result = await self._sync(world_id, actor, secret, blocking=True)
        return AccessResult(applied=True) if result is None else result

    async def sync_all(self, actor: Actor) -> bool:
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
        try:
            actor = await self._confirmed(actor)
        except DirectoryUnavailableError:
            # Ohne Bestätigung kein Abgleich; die Drossel bleibt verbraucht (keine Last bei Störung).
            LOG.warning("Abgleich beim Verwalter-Besuch übersprungen: Nextcloud antwortet nicht")
            return False
        secret = await self._secret.get()
        if not await self._ensure_fingerprint(secret, blocking=False):
            SYNC_STATE.last = None
            return False
        busy = False
        for row in await anyio.to_thread.run_sync(self._store.list_worlds):
            try:
                result = await self._sync(row.id, actor, secret, blocking=False)
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

    async def list_players(self, world_id: str, actor: Actor) -> list[PlayerInfo]:
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
                found = await self._directory.group_members(actor.uid, gid)
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
                    display_name=await self._display_name(actor.uid, nc_user, lookup=actor.nc_admin),
                    player_name=player.player_name,
                    password=_password(secret, player),
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

    async def purge_missing_accounts(self, acting_uid: str) -> list[str]:
        """Vergisst Konten, die Nextcloud eindeutig als gelöscht meldet; gibt sie sortiert zurück.

        Geprüft werden alle Spielerzeilen und alle direkt eingeladenen Konten, im
        Namen des bestätigten Verwalters und außerhalb der Welt-Sperre (Sperr-Regel).
        Vergessen wird nur bei ``None`` (Nextcloud 404/998). Ein deaktiviertes Konto
        bleibt: Es hat ohnehin keinen Zugang und bekommt ihn beim Aktivieren zurück.
        Jede Störung bricht den ganzen Lauf ab, bevor etwas gelöscht ist; ebenso,
        wenn Nextcloud nicht einmal den handelnden Verwalter selbst bestätigt
        (Positivkontrolle gegen eine Fehlkonfiguration, die alles als fehlend meldet).

        Ohne diesen Schritt griffe eine alte direkte Einladung wieder, sobald ein
        Admin ein Konto mit derselben ID neu anlegt, und die Spielerzeile mit
        Rotation 0 gäbe ihm das Passwort des gelöschten Kontos.

        Nur im Namen eines bestätigten NC-Admins (meta nc_admins, D-01, 404-Falle):
        Steht acting_uid dort nicht, gibt es keinen Abgleich und keine Kontoabfrage
        (Tiefenverteidigung zu ``notify.loop.run_hooks``).
        """
        from gameworld.playtime.engine import parse_admins  # spät: playtime.service importiert dieses Modul
        from gameworld.playtime.service import META_NC_ADMINS

        nc_admins = parse_admins(await anyio.to_thread.run_sync(self._store.get_meta, META_NC_ADMINS))
        if acting_uid not in nc_admins:
            LOG.warning("Kontenabgleich abgelehnt: das handelnde Konto ist kein bestätigter Nextcloud-Admin")
            return []
        if await self._directory.user(acting_uid, acting_uid) is None:
            LOG.warning("Nextcloud bestätigt den handelnden Verwalter nicht; gelöschte Konten bleiben vorerst")
            return []
        candidates = await anyio.to_thread.run_sync(self._purge_candidates)
        gone = [uid for uid in sorted(candidates) if await self._directory.user(acting_uid, uid) is None]
        if not gone:
            return []
        forgotten = await anyio.to_thread.run_sync(self._forget_sync, gone)
        if forgotten:
            LOG.info("%d in Nextcloud gelöschte Konten vergessen", len(forgotten))
        return forgotten

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

    async def _confirmed(self, actor: Actor) -> Actor:
        """Bestätigt nc_admin frisch an der Gruppe admin, sonst gilt der Actor als Nicht-Admin.

        Das Profil hinter dem Actor kann bis zu 30 s alt sein. Nur ein frisch
        bestätigter NC-Admin darf den Pfad "404 heißt gelöscht" gehen (P-01):
        Antwortet Nextcloud mit 403/404 oder fehlt das Konto in der Gruppe, folgt
        der sichere Nicht-Admin-Pfad. Eine Störung wird weitergereicht (nichts geschrieben).
        """
        if not actor.nc_admin:
            return actor
        try:
            members = await self._directory.group_members(actor.uid, ADMIN_GROUP)
        except DirectoryRejectedError:
            members = None
        if members is None or actor.uid not in members:
            LOG.warning("Nextcloud bestätigt das Adminrecht nicht; es gelten die Regeln für Gruppen-Verwalter")
            return replace(actor, nc_admin=False)
        return actor

    async def _require_account_in_scope(self, actor: Actor, uid: str) -> None:
        """Das Konto muss in einer eigenen Gruppe oder Subadmin-Gruppe stehen (D-01), sonst 403.

        Gelesen wird je Gruppe im Namen des Verwalters; eine abgelehnte Gruppe
        zählt nicht, eine Störung wird weitergereicht (503). Läuft vor jeder Store-Änderung.
        """
        for gid in sorted(actor.groups):
            try:
                members = await self._directory.group_members(actor.uid, gid)
            except DirectoryRejectedError:
                continue
            if members is not None and uid in members:
                return
        raise InviteScopeError(MSG_ACCOUNT_OUT_OF_SCOPE)

    async def _resolve(
        self,
        actor: Actor,
        invites: set[InviteKey],
        known: dict[str, DirectoryUser] | None = None,
        *,
        strict: bool = True,
    ) -> _Resolution:
        """Löst Einladungen bei Nextcloud auf, als handelnder Verwalter (Pitfall 6).

        NC-Admin (frisch bestätigt): Eine fehlende Gruppe zählt als leer. Jedes
        Konto wird höchstens einmal abgefragt, auch wenn es direkt und über
        Gruppen eingeladen ist.

        Nicht-Admin (404-Falle, P-01): siehe ``_resolve_limited``.
        """
        if not actor.nc_admin:
            return await self._resolve_limited(actor, invites, known or {}, strict=strict)
        cache: dict[str, DirectoryUser | None] = dict(known or {})
        resolution = _Resolution()
        for kind, target in sorted(invites):
            members = None if kind == KIND_USER else await self._directory.group_members(actor.uid, target)
            uids = [target] if kind == KIND_USER else (members or [])
            for uid in uids:
                if uid not in cache:
                    cache[uid] = await self._directory.user(actor.uid, uid)
                user = cache[uid]
                if user is not None and user.enabled:
                    resolution.effective[user.uid] = user
                    resolution.sources.setdefault(user.uid, set()).add((kind, target))
            resolution.resolved.add((kind, target))
        return resolution

    async def _resolve_limited(
        self, actor: Actor, invites: set[InviteKey], known: dict[str, DirectoryUser], *, strict: bool
    ) -> _Resolution:
        """Auflösung im Namen eines Gruppen-Verwalters ohne Adminrecht; entfernt nie wegen einer 404.

        Nie ``user()`` je Konto. Gruppenmitglieder gelten als aktiv, mit der
        Konto-ID als Anzeigename. Direkt eingeladene Konten behalten ihren Zugang
        unverändert (``kept``), außer sie stehen in ``known`` (gerade eingeladen,
        Umfang geprüft). Ist eine Gruppe nicht lesbar (403 oder 404), bricht
        ``strict`` (Abgleich) die Welt ohne Änderung ab; sonst bleibt die Gruppe
        unaufgelöst, und die keep-Regel lässt ihre Zugänge stehen.
        """
        resolution = _Resolution()
        for kind, target in sorted(invites):
            if kind == KIND_USER:
                user = known.get(target)
                if user is None:
                    resolution.kept.add(target)
                else:
                    resolution.effective[user.uid] = user
                    resolution.sources.setdefault(user.uid, set()).add((kind, target))
                resolution.resolved.add((kind, target))
                continue
            try:
                members = await self._directory.group_members(actor.uid, target)
            except DirectoryRejectedError:
                members = None
            if members is None:
                if strict:
                    raise DirectoryRejectedError(MSG_UNAVAILABLE)
                LOG.info("Gruppen-Einladung für den Verwalter nicht lesbar; ihre Zugänge bleiben")
                continue
            for uid in members:
                user = known.get(uid) or DirectoryUser(uid=uid, display_name=uid, enabled=True)
                resolution.effective[user.uid] = user
                resolution.sources.setdefault(user.uid, set()).add((kind, target))
            resolution.resolved.add((kind, target))
        return resolution

    async def _display_name(self, acting_uid: str, nc_user: str, *, lookup: bool = True) -> str:
        """Anzeigename aus Nextcloud; ohne lookup (Nicht-Admin) die Konto-ID, ohne Abfrage."""
        if not lookup:
            return nc_user
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
            password=_password(secret, player),
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

    async def _sync(self, world_id: str, actor: Actor, secret: bytes, *, blocking: bool) -> AccessResult | None:
        resolution = await self._resolve(actor, await self._invite_keys(world_id))
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
            # Ebenso direkte Einladungen, die ein Nicht-Admin nicht prüfen kann (404-Falle).
            keep: set[str] = {uid for uid in resolution.kept if (KIND_USER, uid) in current_keys}
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
        password = _password(secret, player)
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

    def _purge_candidates(self) -> set[str]:
        return {player.nc_user for player in self._store.list_players()} | self._store.direct_invite_targets()

    def _forget_sync(self, gone: list[str]) -> list[str]:
        """Vergisst die geprüften Konten unter der Welt-Sperre und schreibt betroffene Welten neu.

        Ruft nie Nextcloud und nie _ensure_fingerprint. Die Zugangsdatei jeder Welt,
        in der ein vergessenes Konto Zugang hatte, entsteht frisch aus der Datenbank
        (push_access, samt Regeldatei); das Konto steht dann in keiner Datei mehr.
        """
        forgotten: list[str] = []
        affected: set[str] = set()
        with self._worlds.mutation():
            for uid in gone:
                worlds = self._store.player_worlds(uid)
                if self._store.forget_account(uid):
                    forgotten.append(uid)
                    affected.update(worlds)
            for world_id in sorted(affected):
                if self._store.get_world(world_id) is not None:
                    self._worlds.push_access(world_id)
        return forgotten

    def _require_player(self, nc_user: str) -> PlayerRow:
        player = self._store.get_player(nc_user)
        if player is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)
        return player

    @staticmethod
    def _verifier(player: PlayerRow, secret: bytes) -> str:
        """Frischer Verifier mit neuem Salz; Passwort nur im Speicher."""
        return make_verifier(player.player_name, _password(secret, player))

    def _ensure_player(self, user: DirectoryUser) -> PlayerRow:
        player = self._store.get_player(user.uid)
        if player is None:
            name = suggest_player_name(user.display_name, user.uid, self._store.player_names())
            # Frischer Zusatz je Zeile: Ein später unter derselben ID neu angelegtes
            # Konto bekommt nie das Passwort eines gelöschten (purge_missing_accounts).
            player = PlayerRow(nc_user=user.uid, player_name=name, rotation=0, salt=new_player_salt())
            self._store.insert_player(player)
            LOG.info("Spielername %s für ein Nextcloud-Konto angelegt", name)
        return player


def _password(secret: bytes, player: PlayerRow) -> str:
    """Spielpasswort aus Geheimnis und Spielerzeile (Konto, Rotation, Zusatz)."""
    return derive_password(secret, player.nc_user, player.rotation, player.salt)
