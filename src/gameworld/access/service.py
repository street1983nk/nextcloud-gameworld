"""Invitations and player access per world (ZUGANG-02, ZUGANG-03, ROLLE-02).

Flow of every change:

1. Outside the lock (async): check the world, resolve accounts and groups at
   Nextcloud on behalf of the manager, load the secret and check its
   fingerprint. If anything fails here, nothing has been written (T-03-24).
2. Under the world lock in the worker thread: write the invitation, reconcile the
   effective players, on a change bump the generation and write the access file
   into the world immediately (``WorldService.push_access``). In the same
   lock block, push_access also writes the rules file of the time mod
   (``push_time``): a freshly invited child with playtime rules appears
   with a row in the rules file at once, not only after the next 15 s tick.

Effective players of a world are the directly invited accounts plus the
members of invited groups, each only if Nextcloud confirms them as existing
and active. Membership always comes fresh from Nextcloud
(ROLLE-02); Gameworld stores only the invitation of the group.

Pitfall 6: Nextcloud resolves groups only for admins, subadmins and members of the
group (``/cloud/groups/{gid}/users``, otherwise 403). Therefore resolution and
reconciliation only run in the manager context.

Since phase 6 (ROLLE-03, D-01) there are managers without the Nextcloud admin right. For
them the rule "404 means deleted only as NC admin" applies (P-01, 404 trap):
Nextcloud shows a group manager foreign accounts as 404. Therefore
Gameworld never queries ``user()`` per account on their behalf, never removes a direct
invitation because of a missing answer and aborts the reconciliation of a world without
change as soon as one of its groups is unreadable for them. Only accounts and groups
from their own groups and subadmin groups can be invited
(``Actor.groups``); anything else fails before any store change with
``InviteScopeError`` (HTTP 403). Deactivated accounts are recognized only by the
reconciliation of an NC admin. Every changing flow checks beforehand, freshly against
the group admin, whether an actor is an NC admin (``_confirmed``): a remembered profile must never
open the dangerous path.

Lock rule (deadlock protection): ``worlds._LOCK`` is a threading.Lock and
not reentrant. ``_ensure_fingerprint`` is a separate asynchronous step
right after loading the secret, outside ``worlds.mutation()``.
``reprovision_all`` takes the lock itself and releases it before
the calling method starts its own step under the lock.

Passwords, secret and verifiers are never logged.
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
# Reconciliation on a manager visit at most this often (per process, T-03-26).
SYNC_INTERVAL_SECONDS = 60

MSG_UNKNOWN_ACCOUNT = "Dieses Nextcloud-Konto gibt es nicht oder es ist deaktiviert."
MSG_UNKNOWN_GROUP = "Diese Nextcloud-Gruppe gibt es nicht."
MSG_NO_PLAYER = "Für dieses Nextcloud-Konto gibt es noch keinen Spieler."
MSG_NAME_TAKEN = "Diesen Spielernamen hat schon jemand anderes."
MSG_REPROVISION_PENDING = "Die Zugangsdaten werden gerade erneuert; bitte gleich noch einmal abrufen."
# Invitation scope of a group manager (D-01, UI-SPEC B1), HTTP 403.
MSG_ACCOUNT_OUT_OF_SCOPE = "Dieses Konto ist in keiner deiner Gruppen."
MSG_GROUP_OUT_OF_SCOPE = "Diese Gruppe gehört nicht zu deinen Gruppen."

InviteKey = tuple[str, str]


class InviteTargetError(Exception):
    """The target of an invitation is not an existing, active account or not a group (HTTP 422)."""


class InviteScopeError(Exception):
    """The target is outside the manager's own groups and subadmin groups (HTTP 403, D-01)."""


class PlayerNotFoundError(Exception):
    """There is no player for this account (HTTP 404)."""


class PlayerNameTakenError(Exception):
    """The player name already belongs to another account, ignoring case (HTTP 409)."""


@dataclass(frozen=True)
class Actor:
    """Acting manager of a change.

    nc_admin: member of the group admin according to the profile; changing flows confirm
    this freshly beforehand (``AccessService._confirmed``). groups: own groups plus
    subadmin groups, the invitation scope of a non-admin (D-01).
    """

    uid: str
    nc_admin: bool
    groups: frozenset[str] = frozenset()


def actor_of(profile: Profile) -> Actor:
    """Actor from the self-lookup of the signed-in account (never from browser data)."""
    return Actor(
        uid=profile.user_id,
        nc_admin=ADMIN_GROUP in profile.groups,
        groups=frozenset(profile.groups) | frozenset(profile.subadmin),
    )


@dataclass(frozen=True)
class AccessResult:
    """applied: the access file of the world matches the database.

    False means the world has no container (yet) or Docker was not
    reachable; the next start writes the file.
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
    """Result of new password and rename; applied as in AccessResult, across all worlds."""

    nc_user: str
    display_name: str
    player_name: str
    password: str
    applied: bool


@dataclass(frozen=True)
class MyWorld:
    """Access data of the requesting account for a world (own data only, pitfall 7)."""

    world_id: str
    player_name: str
    password: str


@dataclass
class SyncState:
    """Time (monotonic) of the last reconciliation on a manager visit."""

    last: float | None = None


SYNC_STATE = SyncState()


@dataclass
class _Resolution:
    """Effective players together with the invitations through which they come."""

    effective: dict[str, DirectoryUser] = field(default_factory=dict[str, DirectoryUser])
    sources: dict[str, set[InviteKey]] = field(default_factory=dict[str, set[InviteKey]])
    resolved: set[InviteKey] = field(default_factory=set[InviteKey])
    # Directly invited accounts that a non-admin cannot check: access stays as it is.
    kept: set[str] = field(default_factory=set[str])


class AccessService:
    def __init__(self, store: WorldStore, worlds: WorldService, directory: Directory, secret: PlayerSecret) -> None:
        self._store = store
        self._worlds = worlds
        self._directory = directory
        self._secret = secret

    # Public flows

    async def invite_user(self, world_id: str, actor: Actor, uid: str) -> AccessResult:
        """Invite an account; as a non-admin only from the own groups (D-01), without account query."""
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
        """Invite a Nextcloud group; its active members get access (ZUGANG-02).

        A non-admin invites only own groups and subadmin groups (D-01).
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
        """Remove an invitation. Resolves the rest, so it needs an actor like the reconciliation (P-01)."""
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        # Also resolve the revoked key: this way it is known under the lock
        # who had access only through it, and the keep rule cannot
        # silently undo the revocation (see _apply_sync).
        invites = await self._invite_keys(world_id) | {(kind, target)}
        resolution = await self._resolve(actor, invites, strict=False)

        def change() -> None:
            self._store.remove_invite(world_id, kind, target)

        return await self._apply(world_id, change, resolution, secret, revoked=(kind, target))

    async def sync_world(self, world_id: str, actor: Actor) -> AccessResult:
        """Reconcile a world with Nextcloud: new group members in, departed ones out."""
        await self._require_world(world_id)
        actor = await self._confirmed(actor)
        secret = await self._secret.get()
        await self._ensure_fingerprint(secret)
        result = await self._sync(world_id, actor, secret, blocking=True)
        return AccessResult(applied=True) if result is None else result

    async def sync_all(self, actor: Actor) -> bool:
        """Reconciliation of all worlds on a manager visit, at most every SYNC_INTERVAL_SECONDS.

        Never waits for the world lock: if an action is running (e.g. a
        creation), the affected world is skipped and the next visit
        tries again. An error in one world does not abort the others.
        True if a reconciliation ran.
        """
        now = monotonic()
        if SYNC_STATE.last is not None and now - SYNC_STATE.last < SYNC_INTERVAL_SECONDS:
            return False
        SYNC_STATE.last = now
        try:
            actor = await self._confirmed(actor)
        except DirectoryUnavailableError:
            # No reconciliation without confirmation; the throttle stays used up (no load during an outage).
            LOG.warning("Reconciliation on manager visit skipped: Nextcloud does not answer")
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
                LOG.warning("Reconciliation of world %s failed: %s", row.id, type(exc).__name__)
                continue
            busy = busy or result is None
        if busy:
            SYNC_STATE.last = None
        return True

    async def rotate_password(self, acting_uid: str, nc_user: str) -> PlayerChange:
        """New password (T-03-29): rotation +1, all verifiers of the account anew, without world restart."""
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
        """New player name for all worlds of the account.

        In Luanti this is a new account: inventory and privileges of the old name
        stay behind orphaned in the world.
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
        # Separate step outside worlds.mutation() (lock rule, not
        # reentrant). Like WR-02 at my_worlds (AR-25, T-03-30): if, after
        # a secret change, re-provisioning was not yet possible because the lock was busy,
        # the manager view shows no password that the worlds
        # do not know yet (503 at the caller).
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
        """Own worlds together with access data, only for profile.user_id (ZUGANG-04, ROLLE-01).

        The profile comes from the self-lookup on behalf of the signed-in
        account (signed AppAPI request), never from browser data.

        Lazy provisioning (ZUGANG-02 without a manager visit): if one of the
        own groups is in a group invitation and the account has no access there
        yet, it gets it now. Adding only: removing needs
        the group resolution in the manager context (pitfall 6), see sync_all.

        Never waits for the world lock (polling every 5 s must never hang behind a
        creation and must not pile up worker threads): with a busy lock,
        fingerprint reconciliation and provisioning follow on the next call.

        If, after a secret change, re-provisioning was not yet possible because the lock was busy,
        the call answers with SecretUnavailableError
        (503 at the caller): the worlds then still carry the old verifiers,
        and a password from the new secret would be misleading; the child
        would type themselves into the failed-attempt lock of the world mod.
        """
        uid = profile.user_id
        secret = await self._secret.get()
        # Separate step outside worlds.mutation() (lock rule, not reentrant).
        if not await self._ensure_fingerprint(secret, blocking=False):
            # Better briefly unavailable than showing a password that is not
            # valid yet; the 5 s poll tries again right away anyway.
            raise SecretUnavailableError(MSG_REPROVISION_PENDING)
        groups = set(profile.groups)
        pending = await anyio.to_thread.run_sync(self._pending_group_worlds, uid, groups)
        if pending:
            user = DirectoryUser(uid=uid, display_name=profile.display_name, enabled=True)
            await anyio.to_thread.run_sync(self._provision_self, pending, user, groups, secret)
        return await anyio.to_thread.run_sync(self._my_worlds_sync, uid, secret)

    async def purge_missing_accounts(self, acting_uid: str) -> list[str]:
        """Forget accounts that Nextcloud unambiguously reports as deleted; returns them sorted.

        All player rows and all directly invited accounts are checked, on behalf
        of the confirmed manager and outside the world lock (lock rule).
        Only ``None`` (Nextcloud 404/998) is forgotten. A deactivated account
        stays: it has no access anyway and gets it back on activation.
        Any outage aborts the whole run before anything is deleted; likewise
        if Nextcloud does not even confirm the acting manager itself
        (positive control against a misconfiguration that reports everything as missing).

        Without this step an old direct invitation would apply again as soon as an
        admin recreates an account with the same ID, and the player row with
        rotation 0 would give it the password of the deleted account.

        Only on behalf of a confirmed NC admin (meta nc_admins, D-01, 404 trap):
        if acting_uid is not listed there, there is no reconciliation and no account query
        (defense in depth to ``notify.loop.run_hooks``).
        """
        from gameworld.playtime.engine import parse_admins  # late: playtime.service imports this module
        from gameworld.playtime.service import META_NC_ADMINS

        nc_admins = parse_admins(await anyio.to_thread.run_sync(self._store.get_meta, META_NC_ADMINS))
        if acting_uid not in nc_admins:
            LOG.warning("Account reconciliation refused: the acting account is not a confirmed Nextcloud admin")
            return []
        if await self._directory.user(acting_uid, acting_uid) is None:
            LOG.warning("Nextcloud does not confirm the acting manager; deleted accounts stay for now")
            return []
        candidates = await anyio.to_thread.run_sync(self._purge_candidates)
        gone = [uid for uid in sorted(candidates) if await self._directory.user(acting_uid, uid) is None]
        if not gone:
            return []
        forgotten = await anyio.to_thread.run_sync(self._forget_sync, gone)
        if forgotten:
            LOG.info("%d accounts deleted in Nextcloud forgotten", len(forgotten))
        return forgotten

    def list_invites(self, world_id: str) -> list[tuple[str, str, str, str]]:
        """Invitations as (kind, target, invited_by, created_at), for the manager view."""
        return [
            (invite.kind, invite.target, invite.invited_by, invite.created_at)
            for invite in self._store.list_invites(world_id)
        ]

    # Helpers outside the lock

    async def _require_world(self, world_id: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_world, world_id) is None:
            raise WorldNotFoundError(NOT_FOUND)

    async def _invite_keys(self, world_id: str) -> set[InviteKey]:
        invites = await anyio.to_thread.run_sync(self._store.list_invites, world_id)
        return {(invite.kind, invite.target) for invite in invites}

    async def _confirmed(self, actor: Actor) -> Actor:
        """Confirm nc_admin freshly against the group admin, otherwise the actor counts as non-admin.

        The profile behind the actor can be up to 30 s old. Only a freshly
        confirmed NC admin may take the path "404 means deleted" (P-01):
        if Nextcloud answers 403/404 or the account is missing from the group, the
        safe non-admin path follows. An outage is passed on (nothing written).
        """
        if not actor.nc_admin:
            return actor
        try:
            members = await self._directory.group_members(actor.uid, ADMIN_GROUP)
        except DirectoryRejectedError:
            members = None
        if members is None or actor.uid not in members:
            LOG.warning("Nextcloud does not confirm the admin right; the rules for group managers apply")
            return replace(actor, nc_admin=False)
        return actor

    async def _require_account_in_scope(self, actor: Actor, uid: str) -> None:
        """The account must be in an own group or subadmin group (D-01), otherwise 403.

        Read per group on behalf of the manager; a refused group
        does not count, an outage is passed on (503). Runs before any store change.
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
        """Resolve invitations at Nextcloud as the acting manager (pitfall 6).

        NC admin (freshly confirmed): a missing group counts as empty. Each
        account is queried at most once, even if it is invited directly and via
        groups.

        Non-admin (404 trap, P-01): see ``_resolve_limited``.
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
        """Resolution on behalf of a group manager without admin right; never removes because of a 404.

        Never ``user()`` per account. Group members count as active, with the
        account ID as display name. Directly invited accounts keep their access
        unchanged (``kept``), unless they are in ``known`` (just invited,
        scope checked). If a group is unreadable (403 or 404), ``strict``
        (reconciliation) aborts the world without change; otherwise the group stays
        unresolved, and the keep rule leaves its accesses in place.
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
                LOG.info("Group invitation not readable for the manager; its accesses stay")
                continue
            for uid in members:
                user = known.get(uid) or DirectoryUser(uid=uid, display_name=uid, enabled=True)
                resolution.effective[user.uid] = user
                resolution.sources.setdefault(user.uid, set()).add((kind, target))
            resolution.resolved.add((kind, target))
        return resolution

    async def _display_name(self, acting_uid: str, nc_user: str, *, lookup: bool = True) -> str:
        """Display name from Nextcloud; without lookup (non-admin) the account ID, without a query."""
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
        """Detect a new secret by its fingerprint (T-03-30); False only if it did not wait.

        Separate step outside worlds.mutation(): never call from code
        that holds the world lock (not reentrant).
        """
        current = fingerprint(secret)
        stored = await anyio.to_thread.run_sync(self._store.get_meta, FINGERPRINT_KEY)
        if stored == current:
            return True
        if stored is None:
            # First run: the existing verifiers come from this secret.
            await anyio.to_thread.run_sync(self._store.set_meta, FINGERPRINT_KEY, current)
            return True
        LOG.warning("The game secret in Nextcloud has changed; all worlds get new access data")
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

    # Under the lock (worker thread)

    @contextlib.contextmanager
    def _locked(self, blocking: bool) -> Iterator[bool]:
        if blocking:
            with self._worlds.mutation():
                yield True
        else:
            with self._worlds.try_mutation() as acquired:
                yield acquired

    def reprovision_all(self, secret: bytes, blocking: bool = True) -> bool:
        """New verifiers in all worlds after a change of the secret.

        Takes worlds.mutation() itself, once for all worlds, stores the
        new fingerprint in the same lock phase and releases the lock before
        returning. Never calls _ensure_fingerprint. False only without waiting
        when the lock is busy.
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
        """None only without waiting when the lock is busy."""
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
            # Newly invited in parallel (not resolved) keep their state until the next reconciliation.
            # Likewise direct invitations that a non-admin cannot check (404 trap).
            keep: set[str] = {uid for uid in resolution.kept if (KIND_USER, uid) in current_keys}
            unresolved = current_keys - resolution.resolved
            for kind, target in unresolved:
                if kind == KIND_USER:
                    keep.add(target)
                else:
                    keep |= set(self._store.world_access(world_id))
            if unresolved:
                # The view of the invitations was stale: lift the throttle,
                # the next manager visit reconciles immediately.
                SYNC_STATE.last = None
            if revoked is not None:
                # An explicit revocation wins over the keep rule: accounts
                # that had access only through the revoked key are
                # never silently brought back; the next reconciliation adds what
                # a parallel invitation legitimately added.
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
        """Reconcile world_access with the effective players; True on change.

        Runs under worlds.mutation(); never calls _ensure_fingerprint. Missing
        players get a name; verifiers are created only for new entries,
        existing ones stay including their salt (deterministic file).
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
        """Worlds with an invitation of an own group in which the account has no access yet."""
        return [
            world_id
            for world_id in self._store.group_invited_worlds(groups)
            if uid not in self._store.world_access(world_id)
        ]

    def _provision_self(self, world_ids: list[str], user: DirectoryUser, groups: set[str], secret: bytes) -> None:
        """Add the own account to worlds of its group invitations; adding only.

        Without waiting for the lock; under it every world is checked again (world
        deleted, invitation removed, already entered). Never calls _ensure_fingerprint.
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
                LOG.info("World %s: account added via own group invitation", world_id)
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
        """New name or new rotation: all verifiers of the account anew, in one transaction.

        Runs under worlds.mutation(); never calls _ensure_fingerprint. Afterwards
        every affected world is written immediately (no restart needed).
        """
        world_ids = self._store.player_worlds(player.nc_user)
        verifiers = {world_id: self._verifier(player, secret) for world_id in world_ids}
        self._store.update_player_access(player, verifiers)
        pushed = [self._worlds.push_access(world_id) for world_id in world_ids]
        return all(pushed)

    def _purge_candidates(self) -> set[str]:
        return {player.nc_user for player in self._store.list_players()} | self._store.direct_invite_targets()

    def _forget_sync(self, gone: list[str]) -> list[str]:
        """Forget the checked accounts under the world lock and rewrite affected worlds.

        Never calls Nextcloud and never _ensure_fingerprint. The access file of every world
        in which a forgotten account had access is created fresh from the database
        (push_access, including the rules file); the account is then in no file any more.
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
        """Fresh verifier with a new salt; password only in memory."""
        return make_verifier(player.player_name, _password(secret, player))

    def _ensure_player(self, user: DirectoryUser) -> PlayerRow:
        player = self._store.get_player(user.uid)
        if player is None:
            name = suggest_player_name(user.display_name, user.uid, self._store.player_names())
            # Fresh salt per row: an account created later under the same ID
            # never gets the password of a deleted one (purge_missing_accounts).
            player = PlayerRow(nc_user=user.uid, player_name=name, rotation=0, salt=new_player_salt())
            self._store.insert_player(player)
            LOG.info("Player name %s created for a Nextcloud account", name)
        return player


def _password(secret: bytes, player: PlayerRow) -> str:
    """Game password from secret and player row (account, rotation, salt)."""
    return derive_password(secret, player.nc_user, player.rotation, player.salt)
