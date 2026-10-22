"""Benachrichtigungs-Loop als Lifespan-Task (ELTERN-02, ELTERN-03).

Der 15-s-Takt legt Ereignisse ohne Netzaufruf in die SQLite-Outbox (04.1-02).
Dieser Loop läuft im Event-Loop, arbeitet die Outbox alle ``NOTIFY_SECONDS`` ab,
prüft den Tagesrückblick je Verwalter und stößt alle ``MAINTENANCE_SECONDS``
die Wartung an (Einträge aus ``MAINTENANCE``, etwa der Talk-Abgleich aus
04.1-05). Den Verwalter-Schnappschuss lässt er alle ``ADMIN_CHECK_SECONDS`` von
Nextcloud bestätigen (CR-01): Handelnd ist nur ein Konto, das Nextcloud gerade
als Admin bestätigt, nie ungeprüft das erste aus dem Schnappschuss.

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
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.notify.links import clean_origin, page_link
from gameworld.notify.review import review_due, review_line
from gameworld.notify.service import Notifier, get_notifier
from gameworld.notify.texts import (
    BOT_JOIN,
    BOT_LEAVE,
    BOT_PAUSE,
    BOT_PAUSE_END,
    BOT_SCHLUSS,
    BOT_START,
    BOT_STOP,
    BOT_WARN10,
    MAX_DISPLAY,
    NotifyText,
    attempt_message,
    bot_clock,
    bot_name,
    clean_value,
    review_message,
    summary_message,
)
from gameworld.notify.throttle import is_case_variant
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.pause import OUTBOX_PAUSE_END, OUTBOX_PAUSE_SCHLUSS, OUTBOX_PAUSE_START, clock_text
from gameworld.playtime.plan import local_day
from gameworld.playtime.service import TimeService
from gameworld.talk.bot import get_bot
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import TALK_STATE_OK, OutboxRow, WorldRow, WorldStore

LOG = logging.getLogger(__name__)

NOTIFY_SECONDS = 5.0
MAINTENANCE_SECONDS = 300
# Verwalter-Schnappschuss im Hintergrund höchstens so lange ungeprüft (CR-01): Verliert
# ein Konto die Adminrechte, fällt es spätestens dann aus Empfängern, Talk und frei.
ADMIN_CHECK_SECONDS = 60
# Basis-URL der Links, gemeldet vom Browser eines Verwalters (POST /api/origin).
META_LINK_ORIGIN = "link_origin"


@dataclass
class LoopState:
    """Zustand des Loops im Speicher (in Tests je Test frisch)."""

    last_maintenance: float | None = None
    last_admin_check: float | None = None
    origin_warned: bool = False
    # Zuletzt von Nextcloud als Admin bestätigtes Konto (verify_admins), sonst None.
    acting: str | None = None


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
    # Konto für Talk- und Verzeichnis-Aufrufe: das zuletzt bestätigte, falls noch im
    # Schnappschuss, sonst das erste daraus; None ohne Verwalter.
    acting: str | None = None
    # Namen je Durchlauf zwischengespeichert: Spielername (casefold) -> (Schlüssel, Bot-Name).
    names: dict[str, tuple[str, str]] = field(default_factory=dict)


Handler = Callable[[NotifyContext, OutboxRow], Awaitable[None]]
MaintenanceHook = Callable[[WorldService, str], Awaitable[None]]


def link_origin(store: WorldStore) -> str | None:
    """Basis-URL aus meta link_origin, sonst NEXTCLOUD_URL (auch mit Webroot); ungültig oder leer: None."""
    for candidate in (store.get_meta(META_LINK_ORIGIN), os.environ.get("NEXTCLOUD_URL")):
        if not candidate:
            continue
        try:
            return clean_origin(candidate.rstrip("/").removesuffix("/index.php"))
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


# Gameworld-Bot im Talk-Raum der Welt (TALK-02, D-21 bis D-24, D-28)

# Beitritt/Verlassen derselben Person in derselben Welt höchstens alle 10 Minuten (D-22).
PRESENCE_SECONDS = 600


def _room_token(store: WorldStore, world_id: str) -> str | None:
    world = store.get_world(world_id)
    if world is None or world.desired_state == "deleted":
        return None
    row = store.talk_room(world_id)
    if row is None or row.state != TALK_STATE_OK:
        return None
    return row.token


async def _bot_room(context: NotifyContext, world_id: str) -> str | None:
    """Raum-Token, wenn Talk mit Bots da ist und die Welt einen Raum hat; sonst None."""
    if context.acting is None:
        return None
    store = context.service.store
    talk, bots = await get_talk_service(store).is_available(context.acting)
    if not talk or not bots:
        return None
    return await anyio.to_thread.run_sync(_room_token, store, world_id)


async def _bot_person(context: NotifyContext, player_name: str) -> tuple[str, str]:
    """(Drossel-Schlüssel, Name für den Text): Konto und Anzeigename, Rückfall Spielername."""
    cached = context.names.get(player_name.casefold())
    if cached is not None:
        return cached
    store = context.service.store
    nc_user = await anyio.to_thread.run_sync(store.player_name_owner, player_name)
    label = player_name
    acting = context.acting
    if nc_user is not None and acting is not None:
        try:
            user = await context.directory.user(acting, nc_user)
        except DirectoryUnavailableError:
            user = None
        if user is not None:
            label = user.display_name
    result = (nc_user or player_name.casefold(), bot_name(label))
    context.names[player_name.casefold()] = result
    return result


def _fixed(text: str, *, silent: bool) -> Handler:
    """Handler für einen festen Bot-Text ohne Namen (Start, Stopp, Schluss, Pausenende)."""

    async def handler(context: NotifyContext, row: OutboxRow) -> None:
        token = await _bot_room(context, row.world_id)
        if token is not None:
            await get_bot().send(token, text, silent=silent)

    return handler


def _presence(template: str) -> Handler:
    """Beitritt oder Verlassen, still und gedrosselt über bot_presence (D-22, D-28)."""

    async def handler(context: NotifyContext, row: OutboxRow) -> None:
        token = await _bot_room(context, row.world_id)
        if token is None:
            return
        store = context.service.store
        person, name = await _bot_person(context, row.name)
        last = await anyio.to_thread.run_sync(store.bot_presence_at, row.world_id, person)
        if last is not None and row.at - last < PRESENCE_SECONDS:
            return
        if await get_bot().send(token, template.format(name=name), silent=True):
            await anyio.to_thread.run_sync(store.set_bot_presence, row.world_id, person, row.kind, row.at)

    return handler


def warn10_flag(world_id: str, person: str) -> str:
    """Tages-Merker des 10-Minuten-Hinweises je Welt und Person (WR-02)."""
    return f"warn10:{world_id}:{person}"


async def handle_warn10(context: NotifyContext, row: OutboxRow) -> None:
    """Noch 10 Minuten Spielzeit, mit Ton (D-23, D-28); je Welt, Person und Tag höchstens einmal (WR-02).

    Der Mod meldet nach jedem Neuverbinden mit 5 bis 10 Minuten Rest erneut. Darum
    erst den Tages-Merker beanspruchen, dann senden: Neuverbinden klingelt nie
    wieder auf allen Handys im Raum, auch nicht nach einem Neustart der ExApp.
    """
    token = await _bot_room(context, row.world_id)
    if token is None:
        return
    person, name = await _bot_person(context, row.name)
    day = local_day(row.at, context.tz)
    store = context.service.store
    if not await anyio.to_thread.run_sync(store.claim_daily_flag, day, warn10_flag(row.world_id, person)):
        return
    await get_bot().send(token, BOT_WARN10.format(name=name), silent=False)


async def handle_pause_start(context: NotifyContext, row: OutboxRow) -> None:
    """Pause bis H:MM Uhr in Haushalts-Zeitzone, mit Ton; ohne gültiges Ende nichts."""
    try:
        bis = int(row.detail)
    except ValueError:
        return
    token = await _bot_room(context, row.world_id)
    if token is not None:
        await get_bot().send(token, BOT_PAUSE.format(clock=bot_clock(bis, context.tz)), silent=False)


HANDLERS: dict[str, Handler] = {
    "deny": handle_deny,
    "join": _presence(BOT_JOIN),
    "leave": _presence(BOT_LEAVE),
    "warn10": handle_warn10,
    "start": _fixed(BOT_START, silent=True),
    "stop": _fixed(BOT_STOP, silent=True),
    OUTBOX_PAUSE_START: handle_pause_start,
    OUTBOX_PAUSE_SCHLUSS: _fixed(BOT_SCHLUSS, silent=False),
    OUTBOX_PAUSE_END: _fixed(BOT_PAUSE_END, silent=True),
}


async def talk_reconcile(service: WorldService, acting: str) -> None:
    """Talk-Abgleich (04.1-05): Räume anlegen, Mitglieder, nur lesen, offene Löschungen.

    ``acting`` ist das eben von Nextcloud bestätigte Konto (verify_once, CR-01).
    """
    await get_talk_service(service.store).reconcile_all(acting)


MAINTENANCE: list[MaintenanceHook] = [talk_reconcile]


def _due_admins(store: WorldStore, admins: tuple[str, ...], day: date, minute: int) -> list[str]:
    due: list[str] = []
    for uid in admins:
        enabled, pref_minute = store.review_pref(uid)
        if review_due(minute, pref_minute, enabled=enabled) and not store.review_was_sent(uid, day):
            due.append(uid)
    return due


async def _reviews(context: NotifyContext) -> None:
    """Tagesrückblick: Inhalt zuerst, beanspruchen, dann senden (Pattern 5, D-14, D-15, WR-03).

    Fällig nur im kurzen Fenster nach der eingestellten Minute. Ohne Spielzeit
    kommt keine Nachricht, der Tag gilt für die fälligen Verwalter aber als
    erledigt: Späteres Spielen am selben Tag löst keinen Rückblick mehr aus.
    """
    acting = context.acting
    if acting is None or not context.admins or context.origin is None:
        return
    store = context.service.store
    local = datetime.fromtimestamp(context.now, context.tz)
    day = local.date()
    due = await anyio.to_thread.run_sync(_due_admins, store, context.admins, day, local.hour * 60 + local.minute)
    if not due:
        return
    play = await anyio.to_thread.run_sync(collect_play, store, day, context.admins)
    if not play:
        for uid in due:
            await anyio.to_thread.run_sync(store.claim_review, uid, day)
        return
    reached = await anyio.to_thread.run_sync(limits_reached, context.service, list(play))
    entries = [
        (
            await display_name(context.directory, acting, store, nc_user),
            sum(worlds.values()),
            nc_user in reached,
        )
        for nc_user, worlds in sorted(play.items())
    ]
    line = review_line(entries)
    if line is None:
        for uid in due:
            await anyio.to_thread.run_sync(store.claim_review, uid, day)
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
    acting = LOOP_STATE.acting if LOOP_STATE.acting in admins else (admins[0] if admins else None)
    context = NotifyContext(service, notifier, directory, now, tz, admins, origin, acting)
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


async def verify_once(service: WorldService, directory: Directory) -> str | None:
    """Schnappschuss im Hintergrund von Nextcloud bestätigen lassen (CR-01); bestätigtes Konto oder None.

    Nie ``admins[0]`` ungeprüft: Erst ein Konto, dessen Gruppenabfrage gelingt und
    das selbst Admin ist, gilt als handelnd (TimeService.verify_admins).
    """
    raw = await anyio.to_thread.run_sync(service.store.get_meta, META_TIME_ADMINS)
    admins = sorted(parse_admins(raw))
    acting: str | None = None
    if admins:
        try:
            acting = await TimeService(service, directory).verify_admins(admins)
        except Exception as exc:
            LOG.warning("Verwalter-Schnappschuss nicht geprüft: %s", type(exc).__name__)
    LOOP_STATE.acting = acting
    LOOP_STATE.last_admin_check = time.monotonic()
    return acting


async def maintain_once(service: WorldService, directory: Directory) -> None:
    """Wartung: Schnappschuss bestätigen, dann MAINTENANCE nur mit dem bestätigten Konto (Pitfall 9, CR-01)."""
    acting = await verify_once(service, directory)
    if acting is None:
        return
    for hook in list(MAINTENANCE):
        try:
            await hook(service, acting)
        except Exception as exc:
            LOG.warning("Wartungsschritt fehlgeschlagen: %s", type(exc).__name__)


def _due(last: float | None, now: float, seconds: float) -> bool:
    return last is None or now - last >= seconds


async def notify_forever(service: WorldService, *, interval_seconds: float = NOTIFY_SECONDS) -> None:
    """Durchlauf im Abstand interval_seconds, Wartung alle MAINTENANCE_SECONDS; läuft bis CancelledError.

    Dazwischen prüft der Loop den Verwalter-Schnappschuss alle ADMIN_CHECK_SECONDS
    (verify_once), damit ein früherer Verwalter nicht bis zur nächsten Wartung bleibt.
    """
    notifier = get_notifier()
    directory = get_directory()
    while True:
        # Erst prüfen, dann senden: Nach einem Neustart geht nichts an einen
        # gespeicherten, aber nicht mehr bestätigten Verwalter.
        now = time.monotonic()
        if _due(LOOP_STATE.last_maintenance, now, MAINTENANCE_SECONDS):
            LOOP_STATE.last_maintenance = now
            try:
                await maintain_once(service, directory)
            except Exception as exc:
                LOG.warning("Wartung fehlgeschlagen: %s", type(exc).__name__)
        elif _due(LOOP_STATE.last_admin_check, now, ADMIN_CHECK_SECONDS):
            try:
                await verify_once(service, directory)
            except Exception as exc:
                LOG.warning("Verwalter-Prüfung fehlgeschlagen: %s", type(exc).__name__)
        try:
            await run_once(service, notifier, directory, int(time.time()))
        except Exception as exc:
            LOG.warning("Benachrichtigungs-Durchlauf fehlgeschlagen: %s", type(exc).__name__)
        await asyncio.sleep(interval_seconds)
