"""Talk room per world: create, reconcile members, read-only, delete (TALK-01).

Gameworld is the source of truth: members are exactly the accounts from
``world_access`` plus the managers from the snapshot (D-16). Everything
else is removed by the reconciliation. World flows never depend on Talk (D-20): hooks
run as tracked tasks, errors stay isolated per world, a failed
delete stays ``delete_pending`` and is repeated in the 5 min reconciliation.

Lock rule: Talk calls never under ``worlds.mutation()``, store access via
``anyio.to_thread.run_sync``. Logs only with world ID and type name (T-04.1-27).
Call settings stay at the Talk default (D-18).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import anyio.to_thread

from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.talk.bot import get_bot
from gameworld.talk.rooms import (
    ACTOR_USERS,
    MODERATOR_TYPES,
    MSG_UNAVAILABLE,
    TYPE_OWNER,
    TYPE_USER,
    RoomGoneError,
    RoomMember,
    TalkRooms,
    TalkUnavailableError,
    get_talk_rooms,
)
from gameworld.worlds.store import TALK_STATE_DELETE_PENDING, TALK_STATE_OK, TalkRoomRow, WorldStore

LOG = logging.getLogger(__name__)

# Capability query at most every 5 minutes (pitfall 8).
TALK_INTERVAL_SECONDS = 300.0
ROOM_PREFIX = "Gameworld: "
# For this long shutdown waits for open Talk hooks, then it aborts them (IN-06).
SHUTDOWN_SECONDS = 5.0


@dataclass
class TalkState:
    """Cached availability; module-wide, fresh per test in tests."""

    checked_at: float | None = None
    available: bool = False
    bots: bool = False


TALK_STATE = TalkState()


@dataclass(frozen=True)
class TalkWorldStatus:
    world_id: str
    world_name: str
    has_room: bool
    read_only: bool
    owner_not_admin: bool
    # Room token for the link in Talk; None without a finished room.
    token: str | None = None
    # Nextcloud account of the room owner, only if he is no longer a manager (D-27, D-19).
    owner_display: str | None = None
    # Old room without a moderator (blocked case, D-16): only a Nextcloud admin can delete it via occ.
    orphaned_token: str | None = None


@dataclass(frozen=True)
class TalkStatus:
    available: bool
    bots: bool
    worlds: list[TalkWorldStatus]


def room_name(world_name: str) -> str:
    return f"{ROOM_PREFIX}{world_name}"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class TalkService:
    """Keeps rooms and members in Talk in line with the Gameworld data."""

    def __init__(self, store: WorldStore, rooms: TalkRooms) -> None:
        self.store = store
        self._rooms = rooms
        self._tasks: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    # Helpers

    def _lock(self, world_id: str) -> asyncio.Lock:
        lock = self._locks.get(world_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[world_id] = lock
        return lock

    async def _admins(self) -> list[str]:
        raw = await anyio.to_thread.run_sync(self.store.get_meta, META_TIME_ADMINS)
        return sorted(parse_admins(raw))

    async def is_available(self, acting_uid: str, *, fresh: bool = False) -> tuple[bool, bool]:
        """(Talk present, bots present); asked at most every TALK_INTERVAL_SECONDS, error means: not present.

        ``fresh`` bypasses the cache (only the rare reconciliation, reconcile_all).
        """
        state = TALK_STATE
        now = monotonic()
        if not fresh and state.checked_at is not None and now - state.checked_at < TALK_INTERVAL_SECONDS:
            return state.available, state.bots
        try:
            talk, bots = await self._rooms.available(acting_uid)
        except Exception as exc:
            LOG.warning("Talk availability not checked: %s", type(exc).__name__)
            talk, bots = False, False
        state.checked_at = now
        state.available = talk
        state.bots = bots
        return talk, bots

    @staticmethod
    def _candidates(row: TalkRoomRow, admins: list[str]) -> list[str]:
        """Acting account: owner if still a manager, otherwise the managers in turn."""
        if row.owner_uid in admins:
            return [row.owner_uid, *(uid for uid in admins if uid != row.owner_uid)]
        return list(admins)

    # Create room

    async def ensure_room(self, world_id: str, acting_uid: str) -> None:
        """Creates the room if the world does not have one yet, and reconciles the members."""
        talk, bots = await self.is_available(acting_uid)
        if not talk:
            return
        async with self._lock(world_id):
            world = await anyio.to_thread.run_sync(self.store.get_world, world_id)
            if world is None:
                return
            row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if row is None:
                token = await self._rooms.create(acting_uid, room_name(world.name))
                inserted = await anyio.to_thread.run_sync(
                    self.store.insert_talk_room, world_id, token, acting_uid, _now()
                )
                if not inserted:
                    await self._rooms.delete(acting_uid, token)
            await self._sync_locked(world_id)
            if bots:
                await self._enable_bot(world_id, acting_uid)

    async def _replace_locked(self, world_id: str, acting_uid: str) -> bool:
        """New room for the existing row (blocked case, new creation); False without a world or row."""
        world = await anyio.to_thread.run_sync(self.store.get_world, world_id)
        if world is None:
            return False
        token = await self._rooms.create(acting_uid, room_name(world.name))
        replaced = await anyio.to_thread.run_sync(self.store.replace_talk_token, world_id, token, acting_uid, _now())
        if not replaced:
            await self._rooms.delete(acting_uid, token)
        return replaced

    async def _enable_bot(self, world_id: str, acting_uid: str) -> None:
        """Enable the Gameworld bot in the room (TALK-02); an error does not disturb the room."""
        row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
        if row is None or row.state != TALK_STATE_OK:
            return
        try:
            await get_bot().ensure_enabled(row.token, acting_uid)
        except Exception as exc:
            LOG.warning("Bot for world %s not enabled: %s", world_id, type(exc).__name__)

    # Reconcile members

    async def sync_members(self, world_id: str) -> None:
        """Target = world_access plus manager snapshot; empty snapshot: do nothing (pitfall 9)."""
        async with self._lock(world_id):
            await self._sync_locked(world_id)

    async def _acting_members(self, row: TalkRoomRow, admins: list[str]) -> tuple[str, list[RoomMember]] | None:
        """First account that sees the room; room gone for the owner: delete the row, reconciliation creates anew."""
        candidates = self._candidates(row, admins)
        for acting in candidates:
            try:
                return acting, await self._rooms.participants(acting, row.token)
            except RoomGoneError:
                continue
        if row.owner_uid in candidates:
            LOG.warning("Talk room of world %s is missing in Talk, it is recreated", row.world_id)
            await anyio.to_thread.run_sync(self.store.delete_talk_room, row.world_id)
        return None

    async def _sync_locked(self, world_id: str) -> None:
        admins = await self._admins()
        if not admins:
            return
        row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
        if row is None or row.state != TALK_STATE_OK:
            return
        talk, _bots = await self.is_available(admins[0])
        if not talk:
            return
        found = await self._acting_members(row, admins)
        if found is None:
            return
        acting, members = found
        access = await anyio.to_thread.run_sync(self.store.world_access, world_id)
        admin_set = set(admins)
        want = set(access) | admin_set
        token = row.token
        for member in members:
            if member.participant_type == TYPE_OWNER:
                continue
            wanted = member.actor_type == ACTOR_USERS and member.actor_id in want
            if wanted and (member.actor_id in admin_set or member.participant_type not in MODERATOR_TYPES):
                continue
            # Demote moderators first (pitfall 5); children then stay as participants.
            if member.participant_type in MODERATOR_TYPES:
                await self._rooms.demote(acting, token, member.attendee_id)
            if not wanted:
                await self._rooms.remove_attendee(acting, token, member.attendee_id)
        present = {m.actor_id for m in members if m.actor_type == ACTOR_USERS}
        missing = sorted(want - present)
        for uid in missing:
            await self._rooms.add_user(acting, token, uid)
        if missing:
            members = await self._rooms.participants(acting, token)
        for member in members:
            if (
                member.actor_type == ACTOR_USERS
                and member.actor_id in admin_set
                and member.participant_type == TYPE_USER
            ):
                await self._rooms.promote(acting, token, member.attendee_id)

    # Taking over orphaned rooms (D-16, D-19)

    async def _successors(self, admins: list[str]) -> list[str]:
        """Confirmed managers by service age (verwalter_seen), then not yet seen ones by account ID."""
        seniority = await anyio.to_thread.run_sync(self.store.verwalter_seniority)
        admin_set = set(admins)
        ordered = [uid for uid in seniority if uid in admin_set]
        seen = set(ordered)
        return ordered + [uid for uid in admins if uid not in seen]

    async def _take_over_locked(self, world_id: str, admins: list[str]) -> None:
        """Gives every room a capable Gameworld owner; only with a confirmed account (CR-01).

        Owner gone or no longer a manager: the longest-serving manager who sees the room
        becomes owner and moderator. Talk has no owner change (F-09): a
        former manager who remains owner in Talk is reported as ``former_owner``. If
        no manager sees the room (blocked case), a new room is created; the old token stays
        as ``orphaned_token``, only a Nextcloud admin can delete it via occ.
        """
        row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
        if row is None or row.state != TALK_STATE_OK:
            return
        admin_set = set(admins)
        successors = await self._successors(admins)
        if row.owner_uid in admin_set:
            order = [row.owner_uid, *(uid for uid in successors if uid != row.owner_uid)]
        else:
            order = successors
        found: tuple[str, list[RoomMember]] | None = None
        for candidate in order:
            try:
                found = candidate, await self._rooms.participants(candidate, row.token)
            except RoomGoneError:
                continue
            break
        if found is None:
            if row.owner_uid in admin_set:
                # Room gone for the owner: the reconciliation deletes the row and creates anew.
                return
            LOG.warning("Talk room of world %s has no moderator anymore, a new room is created", world_id)
            if await self._replace_locked(world_id, successors[0]):
                await anyio.to_thread.run_sync(self.store.set_talk_orphaned, world_id, row.token)
            return
        candidate, members = found
        former = next(
            (
                m.actor_id
                for m in members
                if m.participant_type == TYPE_OWNER and m.actor_type == ACTOR_USERS and m.actor_id not in admin_set
            ),
            None,
        )
        owner = row.owner_uid
        if owner not in admin_set:
            owner = candidate
            await self._promote_owner(row.token, owner, members, admin_set)
            LOG.info("Talk room of world %s has a new Gameworld owner", world_id)
        if owner != row.owner_uid or former != row.former_owner:
            await anyio.to_thread.run_sync(self.store.set_talk_owner, world_id, owner, former)

    async def _promote_owner(self, token: str, owner: str, members: list[RoomMember], admin_set: set[str]) -> None:
        """New owner becomes moderator; promoted by a manager who already is one."""
        mine = next((m for m in members if m.actor_type == ACTOR_USERS and m.actor_id == owner), None)
        if mine is None or mine.participant_type != TYPE_USER:
            return
        promoter = next(
            (
                m.actor_id
                for m in members
                if m.actor_type == ACTOR_USERS
                and m.actor_id in admin_set
                and (m.participant_type == TYPE_OWNER or m.participant_type in MODERATOR_TYPES)
            ),
            owner,
        )
        await self._rooms.promote(promoter, token, mine.attendee_id)

    async def recreate_room(self, world_id: str, acting_uid: str) -> bool:
        """Recreate the room (D-19): delete the old room including history, create a new one without the former manager.

        Only at the express request of a manager (route after confirmation in the
        UI), never automatically. False without a room, world or as a non-manager;
        Talk errors go to the caller as ``TalkUnavailableError``, if even the
        delete fails, the old room remains. Never under ``worlds.mutation()``.
        """
        talk, bots = await self.is_available(acting_uid)
        if not talk:
            raise TalkUnavailableError(MSG_UNAVAILABLE)
        admins = await self._admins()
        if acting_uid not in admins:
            return False
        async with self._lock(world_id):
            row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if row is None or row.state != TALK_STATE_OK:
                return False
            await self._rooms.delete(acting_uid, row.token)
            if not await self._replace_locked(world_id, acting_uid):
                return False
            await self._sync_locked(world_id)
            fresh = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if fresh is not None and fresh.read_only:
                await self._rooms.set_read_only(acting_uid, fresh.token, on=True)
            if bots:
                await self._enable_bot(world_id, acting_uid)
        return True

    # Read-only (D-17)

    async def set_read_only(self, world_id: str, *, on: bool) -> bool:
        """Remembers the switch and sets it in Talk; False if Talk has not accepted it yet.

        The reconciliation enforces the remembered state later anyway.
        """
        changed = await anyio.to_thread.run_sync(lambda: self.store.set_talk_read_only(world_id, on=on))
        if not changed:
            return False
        admins = await self._admins()
        if not admins:
            return False
        async with self._lock(world_id):
            row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if row is None or row.state != TALK_STATE_OK:
                return False
            try:
                await self._rooms.set_read_only(self._candidates(row, admins)[0], row.token, on=on)
            except Exception as exc:
                LOG.warning("Read-only for world %s not set: %s", world_id, type(exc).__name__)
                return False
        return True

    # Delete (D-19)

    async def delete_room(self, world_id: str) -> None:
        """Deletes the room of the world; if Talk fails, delete_pending stays for the reconciliation."""
        async with self._lock(world_id):
            row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if row is None:
                return
            if row.state != TALK_STATE_DELETE_PENDING:
                await anyio.to_thread.run_sync(self.store.set_talk_state, world_id, TALK_STATE_DELETE_PENDING)
            admins = await self._admins()
            if not admins:
                return
            talk, _bots = await self.is_available(admins[0])
            if not talk:
                return
            try:
                await self._rooms.delete(self._candidates(row, admins)[0], row.token)
            except TalkUnavailableError:
                return
            await anyio.to_thread.run_sync(self.store.delete_talk_room, world_id)

    # 5 min reconciliation

    async def reconcile_all(self, acting_uid: str | None = None) -> None:
        """Deletes open rooms, creates missing ones (backfill D-16/D-20), reconciles all.

        ``acting_uid`` is the account that Nextcloud has just confirmed as admin
        (notify.loop.verify_once, CR-01); only then is a new room created. Without a
        confirmed account in the snapshot the reconciliation creates no rooms.
        """
        admins = await self._admins()
        if not admins:
            return
        acting = acting_uid if acting_uid in admins else None
        # Fresh instead of from the cache: cache and maintenance both run on the 300 s tick, a
        # cache that has barely not expired would otherwise postpone the backfill by a whole
        # tick (06-12, measured in regression 4.1 K6).
        talk, bots = await self.is_available(acting or admins[0], fresh=True)
        if not talk:
            return
        if bots:
            # Once per process; catches up the registration if Talk came later (pitfall 8).
            try:
                await get_bot().register()
            except Exception as exc:
                LOG.warning("Talk bot not registered: %s", type(exc).__name__)
        worlds = await anyio.to_thread.run_sync(self.store.list_worlds)
        rows = await anyio.to_thread.run_sync(self.store.list_talk_rooms)
        world_ids = {world.id for world in worlds}
        with_room: set[str] = set()
        for row in rows:
            if row.state == TALK_STATE_DELETE_PENDING or row.world_id not in world_ids:
                await self._isolated("Löschen", row.world_id, self.delete_room(row.world_id))
            else:
                with_room.add(row.world_id)
        for world in worlds:
            if world.id in with_room:
                # Takeover only with a confirmed account (CR-01, T-06-25).
                work = self._reconcile_room(world.id, admins, bots=bots, take_over=acting is not None)
                await self._isolated("Abgleich", world.id, work)
            elif acting is not None:
                # Owner of a new children's room becomes only a confirmed manager (CR-01).
                await self._isolated("Anlegen", world.id, self.ensure_room(world.id, acting))

    async def _reconcile_room(self, world_id: str, admins: list[str], *, bots: bool, take_over: bool) -> None:
        async with self._lock(world_id):
            if take_over:
                await self._take_over_locked(world_id, admins)
            await self._sync_locked(world_id)
            row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
            if row is None or row.state != TALK_STATE_OK:
                return
            acting = self._candidates(row, admins)[0]
            await self._rooms.ensure_private(acting, row.token)
            await self._rooms.set_read_only(acting, row.token, on=row.read_only)
            if bots:
                await self._enable_bot(world_id, acting)

    @staticmethod
    async def _isolated(what: str, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        try:
            await work
        except Exception as exc:
            LOG.warning("Talk %s for world %s failed: %s", what, world_id, type(exc).__name__)

    # Status for GET /api/talk

    async def status(self, acting_uid: str) -> TalkStatus:
        talk, bots = await self.is_available(acting_uid)
        admins = set(await self._admins())
        worlds = await anyio.to_thread.run_sync(self.store.list_worlds)
        rows = {row.world_id: row for row in await anyio.to_thread.run_sync(self.store.list_talk_rooms)}
        items: list[TalkWorldStatus] = []
        for world in worlds:
            row = rows.get(world.id)
            has_room = row is not None and row.state == TALK_STATE_OK
            owner_display: str | None = None
            if row is not None and has_room:
                # former_owner: former manager remains Talk owner (D-19); otherwise not yet taken over.
                owner_display = row.former_owner or (row.owner_uid if row.owner_uid not in admins else None)
            owner_not_admin = owner_display is not None
            items.append(
                TalkWorldStatus(
                    world_id=world.id,
                    world_name=world.name,
                    has_room=has_room,
                    read_only=row is not None and row.read_only,
                    owner_not_admin=owner_not_admin,
                    token=row.token if row is not None and has_room else None,
                    owner_display=owner_display,
                    orphaned_token=row.orphaned_token if row is not None else None,
                )
            )
        return TalkStatus(available=talk, bots=bots, worlds=items)

    # Tracked hooks: the parent request never waits for Talk.

    def _spawn(self, what: str, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(self._tracked(what, world_id, work))
        self._tasks.add(task)

    async def _tracked(self, what: str, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        try:
            await self._isolated(what, world_id, work)
        finally:
            current = asyncio.current_task()
            if current is not None:
                self._tasks.discard(current)

    def schedule_ensure(self, world_id: str, acting_uid: str) -> None:
        self._spawn("Anlegen", world_id, self.ensure_room(world_id, acting_uid))

    def schedule_sync(self, world_id: str) -> None:
        self._spawn("Abgleich", world_id, self.sync_members(world_id))

    def schedule_delete(self, world_id: str) -> None:
        self._spawn("Löschen", world_id, self.delete_room(world_id))

    async def drain(self) -> None:
        """Waits until all tracked hooks are finished (tests, shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self, grace_seconds: float = SHUTDOWN_SECONDS) -> int:
        """On shutdown (IN-06): wait up to ``grace_seconds``, then abort open hooks; number aborted.

        An aborted delete stays ``delete_pending`` and is repeated in the next
        reconciliation after the start.
        """
        pending = set(self._tasks)
        if not pending:
            return 0
        _done, still = await asyncio.wait(pending, timeout=grace_seconds)
        for task in still:
            task.cancel()
        if still:
            await asyncio.gather(*still, return_exceptions=True)
        return len(still)


_talk_service: TalkService | None = None


def get_talk_service(store: WorldStore) -> TalkService:
    """Module-wide singleton to the world store; tests reset it per test."""
    global _talk_service
    if _talk_service is None or _talk_service.store is not store:
        _talk_service = TalkService(store, get_talk_rooms())
    return _talk_service


async def shutdown_talk(grace_seconds: float = SHUTDOWN_SECONDS) -> int:
    """Lifespan end: wait for or abort open Talk hooks; without a service nothing (IN-06)."""
    if _talk_service is None:
        return 0
    return await _talk_service.shutdown(grace_seconds)
