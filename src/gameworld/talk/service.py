"""Talk-Raum je Welt: anlegen, Mitglieder abgleichen, nur lesen, löschen (TALK-01).

Gameworld ist die Soll-Quelle: Mitglieder sind genau die Konten aus
``world_access`` plus die Verwalter aus dem Schnappschuss (D-16). Alles
andere entfernt der Abgleich. Welt-Abläufe hängen nie an Talk (D-20): Hooks
laufen als verfolgte Tasks, Fehler bleiben je Welt isoliert, ein gescheitertes
Löschen bleibt ``delete_pending`` und wird im 5-min-Abgleich wiederholt.

Sperr-Regel: Talk-Aufrufe nie unter ``worlds.mutation()``, Store-Zugriffe per
``anyio.to_thread.run_sync``. Logs nur mit Welt-ID und Typname (T-04.1-27).
Anruf-Einstellungen bleiben auf Talk-Standard (D-18).
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

# Capability-Abfrage höchstens alle 5 Minuten (Pitfall 8).
TALK_INTERVAL_SECONDS = 300.0
ROOM_PREFIX = "Gameworld: "


@dataclass
class TalkState:
    """Zwischengespeicherte Verfügbarkeit; modulweit, in Tests je Test frisch."""

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
    # Raum-Token für den Link in Talk; None ohne fertigen Raum.
    token: str | None = None
    # Nextcloud-Konto des Raum-Owners, nur wenn er kein Verwalter mehr ist (D-27).
    owner_display: str | None = None


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
    """Hält Räume und Mitglieder in Talk passend zu den Gameworld-Daten."""

    def __init__(self, store: WorldStore, rooms: TalkRooms) -> None:
        self.store = store
        self._rooms = rooms
        self._tasks: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = {}

    # Hilfen

    def _lock(self, world_id: str) -> asyncio.Lock:
        lock = self._locks.get(world_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[world_id] = lock
        return lock

    async def _admins(self) -> list[str]:
        raw = await anyio.to_thread.run_sync(self.store.get_meta, META_TIME_ADMINS)
        return sorted(parse_admins(raw))

    async def is_available(self, acting_uid: str) -> tuple[bool, bool]:
        """(Talk da, Bots da); höchstens alle TALK_INTERVAL_SECONDS gefragt, Fehler heißt: nicht da."""
        state = TALK_STATE
        now = monotonic()
        if state.checked_at is not None and now - state.checked_at < TALK_INTERVAL_SECONDS:
            return state.available, state.bots
        try:
            talk, bots = await self._rooms.available(acting_uid)
        except Exception as exc:
            LOG.warning("Talk-Verfügbarkeit nicht geprüft: %s", type(exc).__name__)
            talk, bots = False, False
        state.checked_at = now
        state.available = talk
        state.bots = bots
        return talk, bots

    @staticmethod
    def _candidates(row: TalkRoomRow, admins: list[str]) -> list[str]:
        """Handelndes Konto: Owner, falls noch Verwalter, sonst die Verwalter der Reihe nach."""
        if row.owner_uid in admins:
            return [row.owner_uid, *(uid for uid in admins if uid != row.owner_uid)]
        return list(admins)

    # Raum anlegen

    async def ensure_room(self, world_id: str, acting_uid: str) -> None:
        """Legt den Raum an, falls die Welt noch keinen hat, und gleicht die Mitglieder ab."""
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

    async def _enable_bot(self, world_id: str, acting_uid: str) -> None:
        """Gameworld-Bot im Raum freischalten (TALK-02); ein Fehler stört den Raum nicht."""
        row = await anyio.to_thread.run_sync(self.store.talk_room, world_id)
        if row is None or row.state != TALK_STATE_OK:
            return
        try:
            await get_bot().ensure_enabled(row.token, acting_uid)
        except Exception as exc:
            LOG.warning("Bot für Welt %s nicht freigeschaltet: %s", world_id, type(exc).__name__)

    # Mitglieder abgleichen

    async def sync_members(self, world_id: str) -> None:
        """Soll = world_access plus Verwalter-Schnappschuss; leerer Schnappschuss: nichts tun (Pitfall 9)."""
        async with self._lock(world_id):
            await self._sync_locked(world_id)

    async def _acting_members(self, row: TalkRoomRow, admins: list[str]) -> tuple[str, list[RoomMember]] | None:
        """Erstes Konto, das den Raum sieht; Raum für den Owner weg: Zeile löschen, Abgleich legt neu an."""
        candidates = self._candidates(row, admins)
        for acting in candidates:
            try:
                return acting, await self._rooms.participants(acting, row.token)
            except RoomGoneError:
                continue
        if row.owner_uid in candidates:
            LOG.warning("Talk-Raum der Welt %s fehlt in Talk, wird neu angelegt", row.world_id)
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
            # Moderatoren erst zurückstufen (Pitfall 5); Kinder bleiben dann als Teilnehmer.
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

    # Nur lesen (D-17)

    async def set_read_only(self, world_id: str, *, on: bool) -> bool:
        """Merkt den Schalter und setzt ihn in Talk; False, wenn Talk ihn noch nicht übernommen hat.

        Der Abgleich erzwingt den gemerkten Stand später ohnehin.
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
                LOG.warning("Nur-lesen für Welt %s nicht gesetzt: %s", world_id, type(exc).__name__)
                return False
        return True

    # Löschen (D-19)

    async def delete_room(self, world_id: str) -> None:
        """Löscht den Raum der Welt; scheitert Talk, bleibt delete_pending für den Abgleich."""
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

    # 5-min-Abgleich

    async def reconcile_all(self) -> None:
        """Löscht offene Räume, legt fehlende an (Backfill D-16/D-20), gleicht alle ab."""
        admins = await self._admins()
        if not admins:
            return
        talk, bots = await self.is_available(admins[0])
        if not talk:
            return
        if bots:
            # Einmal je Prozess; holt die Registrierung nach, wenn Talk später kam (Pitfall 8).
            try:
                await get_bot().register()
            except Exception as exc:
                LOG.warning("Talk-Bot nicht registriert: %s", type(exc).__name__)
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
                await self._isolated("Abgleich", world.id, self._reconcile_room(world.id, admins, bots=bots))
            else:
                await self._isolated("Anlegen", world.id, self.ensure_room(world.id, admins[0]))

    async def _reconcile_room(self, world_id: str, admins: list[str], *, bots: bool) -> None:
        async with self._lock(world_id):
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
            LOG.warning("Talk-%s für Welt %s gescheitert: %s", what, world_id, type(exc).__name__)

    # Status für GET /api/talk

    async def status(self, acting_uid: str) -> TalkStatus:
        talk, bots = await self.is_available(acting_uid)
        admins = set(await self._admins())
        worlds = await anyio.to_thread.run_sync(self.store.list_worlds)
        rows = {row.world_id: row for row in await anyio.to_thread.run_sync(self.store.list_talk_rooms)}
        items: list[TalkWorldStatus] = []
        for world in worlds:
            row = rows.get(world.id)
            has_room = row is not None and row.state == TALK_STATE_OK
            owner_not_admin = row is not None and has_room and row.owner_uid not in admins
            items.append(
                TalkWorldStatus(
                    world_id=world.id,
                    world_name=world.name,
                    has_room=has_room,
                    read_only=row is not None and row.read_only,
                    owner_not_admin=owner_not_admin,
                    token=row.token if row is not None and has_room else None,
                    owner_display=row.owner_uid if row is not None and owner_not_admin else None,
                )
            )
        return TalkStatus(available=talk, bots=bots, worlds=items)

    # Verfolgte Hooks: der Eltern-Request wartet nie auf Talk.

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
        """Wartet, bis alle verfolgten Hooks fertig sind (Tests, Herunterfahren)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


_talk_service: TalkService | None = None


def get_talk_service(store: WorldStore) -> TalkService:
    """Modulweites Singleton zum Welt-Speicher; Tests setzen es je Test zurück."""
    global _talk_service
    if _talk_service is None or _talk_service.store is not store:
        _talk_service = TalkService(store, get_talk_rooms())
    return _talk_service
