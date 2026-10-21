"""Benachrichtigungs-Loop als Lifespan-Task (ELTERN-02, ELTERN-03).

Der 15-s-Takt legt Ereignisse ohne Netzaufruf in die SQLite-Outbox (04.1-02).
Dieser Loop läuft im Event-Loop, arbeitet die Outbox alle ``NOTIFY_SECONDS`` ab,
prüft den Tagesrückblick je Verwalter und stößt alle ``MAINTENANCE_SECONDS``
die Wartung an (Verwalter-Schnappschuss auffrischen, Einträge aus
``MAINTENANCE``, etwa der Talk-Abgleich aus 04.1-05).

Regeln:

- Store-Zugriffe nur per ``anyio.to_thread``, nie unter der Welt-Sperre;
  Netzaufrufe nur hier im Event-Loop (Anti-Pattern RESEARCH).
- Empfänger sind nur die Verwalter aus dem Schnappschuss ``meta time_admins``;
  leer heißt niemand (fail closed, T-04.1-18).
- Erst beanspruchen, dann senden (``claim_attempt``, ``claim_review``): ein
  Absturz verliert höchstens eine Nachricht, doppelt kommt nie etwas.
- Jede Outbox-Art hat einen Handler in ``HANDLERS`` (04.1-06 ergänzt join,
  leave, warn10, start, stop, pause_*). Zeilen ohne Handler werden gelöscht.
- Logs nennen nur IDs, Arten und Fehlertypen, nie Spieler- oder Anzeigenamen.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.notify.links import clean_origin, page_link
from gameworld.notify.review import review_due, review_line
from gameworld.notify.service import Notifier, get_notifier
from gameworld.notify.texts import (
    MAX_DISPLAY,
    NotifyText,
    attempt_message,
    clean_value,
    review_message,
    summary_message,
)
from gameworld.notify.throttle import is_case_variant
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.pause import clock_text
from gameworld.playtime.plan import local_day
from gameworld.playtime.service import TimeService
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import OutboxRow, WorldRow, WorldStore

LOG = logging.getLogger(__name__)

NOTIFY_SECONDS = 5.0
MAINTENANCE_SECONDS = 300
# Basis-URL der Links, gemeldet vom Browser eines Verwalters (POST /api/origin).
META_LINK_ORIGIN = "link_origin"


@dataclass
class LoopState:
    """Zustand des Loops im Speicher (in Tests je Test frisch)."""

    last_maintenance: float | None = None
    origin_warned: bool = False


LOOP_STATE = LoopState()


@dataclass(frozen=True)
class NotifyContext:
    """Was ein Handler für einen Durchlauf braucht."""

    service: WorldService
    notifier: Notifier
    directory: Directory
    now: int
    tz: ZoneInfo
    admins: tuple[str, ...]
    origin: str | None


Handler = Callable[[NotifyContext, OutboxRow], Awaitable[None]]
MaintenanceHook = Callable[[WorldService, str], Awaitable[None]]


def link_origin(store: WorldStore) -> str | None:
    """Basis-URL aus meta link_origin, sonst NEXTCLOUD_URL; beides ungültig oder leer: None."""
    for candidate in (store.get_meta(META_LINK_ORIGIN), os.environ.get("NEXTCLOUD_URL")):
        if not candidate:
            continue
        try:
            return clean_origin(candidate.rstrip("/"))
        except ValueError:
            continue
    return None


def collect_play(store: WorldStore, day: date, admins: Iterable[str]) -> dict[str, dict[str, int]]:
    """Gespielte Sekunden eines Tages je Kind und Welt; Verwalter zählen nicht."""
    excluded = set(admins)
    result: dict[str, dict[str, int]] = {}
    for (nc_user, world_id), seconds in store.play_seconds(day).items():
        if nc_user in excluded or seconds <= 0:
            continue
        result.setdefault(nc_user, {})[world_id] = seconds
    return result


def limits_reached(service: WorldService, nc_users: Iterable[str]) -> set[str]:
    """Kinder, deren Tageslimit heute erreicht ist (TimeEngine.child_state, Grund "limit")."""
    reached: set[str] = set()
    for nc_user in nc_users:
        state = service.time.child_state(nc_user)
        if state is not None and state.reason == "limit":
            reached.add(nc_user)
    return reached


async def display_name(directory: Directory, acting_uid: str, store: WorldStore, nc_user: str) -> str:
    """Anzeigename aus Nextcloud, sonst Spielername, sonst Konto; bereinigt und gekappt."""
    try:
        user = await directory.user(acting_uid, nc_user)
    except DirectoryUnavailableError:
        user = None
    if user is not None:
        return clean_value(user.display_name, MAX_DISPLAY)
    player = await anyio.to_thread.run_sync(store.get_player, nc_user)
    return clean_value(player.player_name if player is not None else nc_user, MAX_DISPLAY)


async def _deliver(
    context: NotifyContext, uids: Iterable[str], text: NotifyText, page: str, params: dict[str, str]
) -> None:
    if context.origin is None:
        return
    link = page_link(context.origin, page, params)
    for uid in uids:
        await context.notifier.notify(uid, text.subject, text.message, text.params, link)


def _world_and_invited(store: WorldStore, world_id: str) -> tuple[WorldRow | None, set[str]]:
    world = store.get_world(world_id)
    if world is None or world.desired_state == "deleted":
        return None, set()
    return world, set(store.access_entries(world_id))


async def handle_deny(context: NotifyContext, row: OutboxRow) -> None:
    """Fremder Beitrittsversuch: merken, gedrosselt an alle Verwalter melden (D-07, D-08)."""
    store = context.service.store
    world, invited = await anyio.to_thread.run_sync(_world_and_invited, store, row.world_id)
    if world is None or is_case_variant(row.name, invited):
        return
    day = local_day(row.at, context.tz)
    decision = await anyio.to_thread.run_sync(store.claim_attempt, day, row.world_id, row.name, row.at)
    if decision == "single":
        text = attempt_message(world.id, world.name, row.name, clock_text(row.at, context.tz))
        await _deliver(context, context.admins, text, "versuch", {"welt": world.id, "tag": day.isoformat()})
    elif decision == "summary":
        await _deliver(context, context.admins, summary_message(), "versuch", {"tag": day.isoformat()})


HANDLERS: dict[str, Handler] = {"deny": handle_deny}


async def talk_reconcile(service: WorldService, acting: str) -> None:
    """Talk-Abgleich (04.1-05): Räume anlegen, Mitglieder, nur lesen, offene Löschungen."""
    del acting
    await get_talk_service(service.store).reconcile_all()


MAINTENANCE: list[MaintenanceHook] = [talk_reconcile]


def _due_admins(store: WorldStore, admins: tuple[str, ...], day: date, minute: int) -> list[str]:
    due: list[str] = []
    for uid in admins:
        enabled, pref_minute = store.review_pref(uid)
        if review_due(minute, pref_minute, enabled=enabled) and not store.review_was_sent(uid, day):
            due.append(uid)
    return due


async def _reviews(context: NotifyContext) -> None:
    """Tagesrückblick: Inhalt zuerst, nur mit Inhalt beanspruchen, dann senden (Pattern 5, D-14, D-15)."""
    if not context.admins or context.origin is None:
        return
    store = context.service.store
    local = datetime.fromtimestamp(context.now, context.tz)
    day = local.date()
    due = await anyio.to_thread.run_sync(_due_admins, store, context.admins, day, local.hour * 60 + local.minute)
    if not due:
        return
    play = await anyio.to_thread.run_sync(collect_play, store, day, context.admins)
    if not play:
        return
    reached = await anyio.to_thread.run_sync(limits_reached, context.service, list(play))
    entries = [
        (
            await display_name(context.directory, context.admins[0], store, nc_user),
            sum(worlds.values()),
            nc_user in reached,
        )
        for nc_user, worlds in sorted(play.items())
    ]
    line = review_line(entries)
    if line is None:
        return
    text = review_message(line)
    for uid in due:
        if await anyio.to_thread.run_sync(store.claim_review, uid, day):
            await _deliver(context, (uid,), text, "rueckblick", {"tag": day.isoformat()})


def _context_data(store: WorldStore, service: WorldService) -> tuple[tuple[str, ...], str | None, ZoneInfo]:
    admins = tuple(sorted(parse_admins(store.get_meta(META_TIME_ADMINS))))
    return admins, link_origin(store), service.time.zone()


async def run_once(service: WorldService, notifier: Notifier, directory: Directory, now: int) -> None:
    """Ein Durchlauf: Outbox abarbeiten und löschen, dann Rückblick prüfen."""
    store = service.store
    admins, origin, tz = await anyio.to_thread.run_sync(_context_data, store, service)
    if origin is None and not LOOP_STATE.origin_warned:
        LOOP_STATE.origin_warned = True
        LOG.warning("Keine Basis-URL für Benachrichtigungs-Links (link_origin, NEXTCLOUD_URL); es wird nichts gesendet")
    context = NotifyContext(service, notifier, directory, now, tz, admins, origin)
    rows = await anyio.to_thread.run_sync(store.outbox_batch)
    for row in rows:
        handler = HANDLERS.get(row.kind)
        if handler is None:
            continue
        try:
            await handler(context, row)
        except Exception as exc:
            LOG.warning(
                "Ereignis %s (%s, Welt %s) nicht verarbeitet: %s", row.id, row.kind, row.world_id, type(exc).__name__
            )
    if rows:
        await anyio.to_thread.run_sync(store.delete_outbox, [row.id for row in rows])
    await _reviews(context)


async def maintain_once(service: WorldService, directory: Directory) -> None:
    """Wartung: Schnappschuss mit dem ersten bekannten Verwalter auffrischen, dann MAINTENANCE (Pitfall 9)."""
    raw = await anyio.to_thread.run_sync(service.store.get_meta, META_TIME_ADMINS)
    admins = sorted(parse_admins(raw))
    if not admins:
        return
    acting = admins[0]
    try:
        await TimeService(service, directory).refresh_admins(acting, blocking=False)
    except Exception as exc:
        LOG.warning("Verwalter-Schnappschuss nicht aufgefrischt: %s", type(exc).__name__)
    for hook in list(MAINTENANCE):
        try:
            await hook(service, acting)
        except Exception as exc:
            LOG.warning("Wartungsschritt fehlgeschlagen: %s", type(exc).__name__)


async def notify_forever(service: WorldService, *, interval_seconds: float = NOTIFY_SECONDS) -> None:
    """Durchlauf im Abstand interval_seconds, Wartung alle MAINTENANCE_SECONDS; läuft bis CancelledError."""
    notifier = get_notifier()
    directory = get_directory()
    while True:
        try:
            await run_once(service, notifier, directory, int(time.time()))
        except Exception as exc:
            LOG.warning("Benachrichtigungs-Durchlauf fehlgeschlagen: %s", type(exc).__name__)
        now = time.monotonic()
        if LOOP_STATE.last_maintenance is None or now - LOOP_STATE.last_maintenance >= MAINTENANCE_SECONDS:
            LOOP_STATE.last_maintenance = now
            try:
                await maintain_once(service, directory)
            except Exception as exc:
                LOG.warning("Wartung fehlgeschlagen: %s", type(exc).__name__)
        await asyncio.sleep(interval_seconds)
