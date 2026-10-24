"""Benachrichtigungs-Loop als Lifespan-Task (ELTERN-02, ELTERN-03).

Der 15-s-Takt legt Ereignisse ohne Netzaufruf in die SQLite-Outbox (04.1-02).
Dieser Loop läuft im Event-Loop, arbeitet die Outbox alle ``NOTIFY_SECONDS`` ab,
prüft den Tagesrückblick je Verwalter und stößt alle ``MAINTENANCE_SECONDS``
die Wartung an (Einträge aus ``MAINTENANCE``: gelöschte Konten vergessen, dann
der Talk-Abgleich aus 04.1-05). Den Verwalter-Schnappschuss lässt er alle ``ADMIN_CHECK_SECONDS`` von
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
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryUnavailableError, get_directory
from gameworld.access.roles import ADMIN_GROUP, get_role_service
from gameworld.access.secret import get_player_secret
from gameworld.access.service import AccessService
from gameworld.notify.links import clean_origin, page_link
from gameworld.notify.review import review_due, review_line
from gameworld.notify.service import Notifier, get_notifier
from gameworld.notify.texts import (
    MAX_DISPLAY,
    NotifyText,
    attempt_message,
    bot_clock,
    bot_name,
    bot_text,
    clean_value,
    review_message,
    summary_message,
)
from gameworld.notify.throttle import Decision, is_case_variant
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.pause import OUTBOX_PAUSE_END, OUTBOX_PAUSE_SCHLUSS, OUTBOX_PAUSE_START, clock_text
from gameworld.playtime.plan import local_day
from gameworld.playtime.service import META_NC_ADMINS, TimeService
from gameworld.talk.bot import get_bot
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import WorldService, world_language
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
    # Laufende Wartung (Talk-Abgleich) als eigener Task, höchstens einer (IN-06).
    maintenance_task: asyncio.Task[None] | None = None


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
# Builds the notification text in the recipient's language (D-25).
TextBuilder = Callable[[str], NotifyText]
MaintenanceHook = Callable[[WorldService, str], Awaitable[None]]
# Wartungsschritt und ob er einen bestätigten Nextcloud-Admin braucht (statt irgendeines Verwalters).
MaintenanceStep = tuple[MaintenanceHook, bool]


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
    """Gespielte Sekunden eines Tages je Kind und Welt; nur Kinder mit Regeln, nie Verwalter (IN-03).

    "Regeln" heißt: ein Wochenplan dieses Haushalts (``child_plans``, wie
    ``has_rules`` der Spielzeit-Seite). Auch ältere Zeilen von Konten ohne Regeln
    (vor IN-03 gezählt) oder mit heute entfernten Regeln erscheinen nicht.
    Erwachsene (Tabelle ``adults``, ROLLE-04) erscheinen nie, auch nicht mit
    Minuten, die vor dem Umschalten am selben Tag gezählt wurden.
    """
    excluded = set(admins) | store.adults()
    with_rules = set(store.child_plans())
    result: dict[str, dict[str, int]] = {}
    for (nc_user, world_id), seconds in store.play_seconds(day).items():
        if nc_user in excluded or nc_user not in with_rules or seconds <= 0:
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
    context: NotifyContext, uids: Iterable[str], build: TextBuilder, page: str, params: dict[str, str]
) -> None:
    """Send to each recipient in their account language (D-25).

    RoleService.language never raises: on a lookup failure it gives the last
    known language or en, so the notification still goes out. No log line here
    names the recipient or the text (T-06-90).
    """
    if context.origin is None:
        return
    link = page_link(context.origin, page, params)
    roles = get_role_service()
    for uid in uids:
        text = build(await roles.language(uid))
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
    # IN-05: Ohne Empfänger oder Link-Adresse nur merken, keinen Hinweis verbrauchen.
    can_send = context.origin is not None and bool(context.admins)

    def claim() -> Decision:
        return store.claim_attempt(day, row.world_id, row.name, row.at, notify=can_send)

    decision = await anyio.to_thread.run_sync(claim)
    if decision == "single":
        clock = clock_text(row.at, context.tz)

        def attempt(language: str) -> NotifyText:
            return attempt_message(world.id, world.name, row.name, clock, language=language)

        await _deliver(context, context.admins, attempt, "versuch", {"welt": world.id, "tag": day.isoformat()})
    elif decision == "summary":

        def summary(language: str) -> NotifyText:
            return summary_message(language=language)

        await _deliver(context, context.admins, summary, "versuch", {"tag": day.isoformat()})


# Gameworld-Bot im Talk-Raum der Welt (TALK-02, D-21 bis D-24, D-28)

# Beitritt/Verlassen derselben Person in derselben Welt höchstens alle 10 Minuten (D-22).
PRESENCE_SECONDS = 600


# Talk room token and world language (D-27: everyone in the world sees the same language).
BotRoom = tuple[str, str]


def _room_token(store: WorldStore, world_id: str) -> BotRoom | None:
    world = store.get_world(world_id)
    if world is None or world.desired_state == "deleted":
        return None
    row = store.talk_room(world_id)
    if row is None or row.state != TALK_STATE_OK:
        return None
    return row.token, world_language(world)


async def _bot_room(context: NotifyContext, world_id: str) -> BotRoom | None:
    """(Room token, world language) if Talk with bots is there and the world has a room; else None."""
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


def _fixed(key: str, *, silent: bool) -> Handler:
    """Handler for a fixed bot text without names (start, stop, end of day, end of break), world language."""

    async def handler(context: NotifyContext, row: OutboxRow) -> None:
        room = await _bot_room(context, row.world_id)
        if room is not None:
            token, language = room
            await get_bot().send(token, bot_text(key, language), silent=silent)

    return handler


def _presence(key: str) -> Handler:
    """Join or leave, silent and throttled via bot_presence (D-22, D-28), world language."""

    async def handler(context: NotifyContext, row: OutboxRow) -> None:
        room = await _bot_room(context, row.world_id)
        if room is None:
            return
        token, language = room
        store = context.service.store
        person, name = await _bot_person(context, row.name)
        last = await anyio.to_thread.run_sync(store.bot_presence_at, row.world_id, person)
        if last is not None and row.at - last < PRESENCE_SECONDS:
            return
        if await get_bot().send(token, bot_text(key, language, name=name), silent=True):
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
    room = await _bot_room(context, row.world_id)
    if room is None:
        return
    token, language = room
    person, name = await _bot_person(context, row.name)
    day = local_day(row.at, context.tz)
    store = context.service.store
    if not await anyio.to_thread.run_sync(store.claim_daily_flag, day, warn10_flag(row.world_id, person)):
        return
    await get_bot().send(token, bot_text("warn10", language, name=name), silent=False)


async def handle_pause_start(context: NotifyContext, row: OutboxRow) -> None:
    """Pause bis H:MM in Haushalts-Zeitzone, mit Ton; ohne gültiges Ende nichts."""
    try:
        bis = int(row.detail)
    except ValueError:
        return
    room = await _bot_room(context, row.world_id)
    if room is not None:
        token, language = room
        await get_bot().send(token, bot_text("pause", language, clock=bot_clock(bis, context.tz)), silent=False)


HANDLERS: dict[str, Handler] = {
    "deny": handle_deny,
    "join": _presence("join"),
    "leave": _presence("leave"),
    "warn10": handle_warn10,
    "start": _fixed("start", silent=True),
    "stop": _fixed("stop", silent=True),
    OUTBOX_PAUSE_START: handle_pause_start,
    OUTBOX_PAUSE_SCHLUSS: _fixed("schluss", silent=False),
    OUTBOX_PAUSE_END: _fixed("pause_end", silent=True),
}


async def talk_reconcile(service: WorldService, acting: str) -> None:
    """Talk-Abgleich (04.1-05): Räume anlegen, Mitglieder, nur lesen, offene Löschungen.

    ``acting`` ist das eben von Nextcloud bestätigte Konto (verify_once, CR-01).
    """
    await get_talk_service(service.store).reconcile_all(acting)


async def purge_accounts(service: WorldService, acting: str) -> None:
    """In Nextcloud gelöschte Konten vergessen: Spieler, Einladungen, Spielzeit, Rückblick.

    ``acting`` ist ein bestätigter Nextcloud-Admin (meta nc_admins, run_hooks).
    "404 heißt gelöscht" gilt nur im Namen eines Admins: Ein Verwalter aus einer
    Zusatzgruppe sieht fremde Konten als 404 und ließe sie fälschlich vergessen
    (RESEARCH F-04, ROADMAP Kriterium 5, dabe0c0). Darum fragt der Schritt vorher
    noch einmal frisch, ob ``acting`` selbst in der Gruppe admin steht; sonst
    läuft nichts. Vor dem Talk-Abgleich, damit der kein gelöschtes Konto mehr in
    Räume holen will. Eine Störung bei Nextcloud bricht den Lauf ohne Löschen ab
    (AccessService.purge_missing_accounts).
    """
    directory = get_directory()
    try:
        members = await directory.group_members(acting, ADMIN_GROUP)
    except DirectoryUnavailableError:
        # Auch DirectoryRejectedError (Unterklasse): kein Admin, kein Abgleich.
        LOG.info("Kontenabgleich übersprungen: %s ist gerade nicht als Nextcloud-Admin bestätigt", acting)
        return
    if acting not in (members or ()):
        LOG.info("Kontenabgleich übersprungen: %s ist kein Nextcloud-Admin mehr", acting)
        return
    access = AccessService(service.store, service, directory, get_player_secret())
    await access.purge_missing_accounts(acting)


# (Schritt, braucht bestätigten Nextcloud-Admin): Der Kontenabgleich läuft nur als Admin (F-04).
MAINTENANCE: list[MaintenanceStep] = [(purge_accounts, True), (talk_reconcile, False)]


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
    if review_line(entries) is None:
        for uid in due:
            await anyio.to_thread.run_sync(store.claim_review, uid, day)
        return

    def review(language: str) -> NotifyText:
        # The line was not None above, and the entries do not depend on the language.
        return review_message(review_line(entries, language=language) or "", language=language)

    for uid in due:
        if await anyio.to_thread.run_sync(store.claim_review, uid, day):
            await _deliver(context, (uid,), review, "rueckblick", {"tag": day.isoformat()})


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
    if acting is not None:
        # Rückblick-Einstellungen früherer Verwalter fallen mit dem bestätigten Stand weg (IN-03).
        try:
            confirmed = await anyio.to_thread.run_sync(service.store.get_meta, META_TIME_ADMINS)
            await anyio.to_thread.run_sync(service.store.prune_review_prefs, set(parse_admins(confirmed)))
        except Exception as exc:
            LOG.warning("Rückblick-Einstellungen nicht aufgeräumt: %s", type(exc).__name__)
    return acting


def _nc_admin_for(store: WorldStore, acting: str) -> str | None:
    """Bestätigter Nextcloud-Admin für Admin-Schritte: ``acting`` selbst, falls darin, sonst der erste; sonst None."""
    nc_admins = sorted(parse_admins(store.get_meta(META_NC_ADMINS)))
    if acting in nc_admins:
        return acting
    return nc_admins[0] if nc_admins else None


async def run_hooks(service: WorldService, acting: str) -> None:
    """Alle Einträge aus MAINTENANCE; Fehler je Eintrag isoliert.

    Schritte ohne Admin-Bedarf laufen mit dem bestätigten Verwalter ``acting``.
    Admin-Schritte (Kontenabgleich) laufen nur mit einem Konto aus meta nc_admins;
    gibt es keins, werden sie übersprungen (404-Falle, F-04).
    """
    nc_admin: str | None = None
    try:
        nc_admin = await anyio.to_thread.run_sync(_nc_admin_for, service.store, acting)
    except Exception as exc:
        LOG.warning("Nextcloud-Admins nicht lesbar: %s", type(exc).__name__)
    for hook, needs_nc_admin in list(MAINTENANCE):
        hook_acting = nc_admin if needs_nc_admin else acting
        if hook_acting is None:
            LOG.info("Kontenabgleich übersprungen: kein bestätigter Nextcloud-Admin")
            continue
        try:
            await hook(service, hook_acting)
        except Exception as exc:
            LOG.warning("Wartungsschritt fehlgeschlagen: %s", type(exc).__name__)


async def maintain_once(service: WorldService, directory: Directory) -> None:
    """Wartung: Schnappschuss bestätigen, dann MAINTENANCE nur mit dem bestätigten Konto (Pitfall 9, CR-01)."""
    acting = await verify_once(service, directory)
    if acting is None:
        return
    await run_hooks(service, acting)


def _due(last: float | None, now: float, seconds: float) -> bool:
    return last is None or now - last >= seconds


def _start_maintenance(service: WorldService) -> None:
    """Wartung als eigener Task (IN-06): Ein langsamer Talk-Abgleich hält Hinweise und Rückblick nicht auf.

    Höchstens ein Wartungs-Task zugleich; läuft der vorige noch, wartet der nächste.
    """
    task = LOOP_STATE.maintenance_task
    if task is not None and not task.done():
        return
    acting = LOOP_STATE.acting
    LOOP_STATE.last_maintenance = time.monotonic()
    if acting is None:
        return
    LOOP_STATE.maintenance_task = asyncio.get_running_loop().create_task(run_hooks(service, acting))


async def notify_forever(service: WorldService, *, interval_seconds: float = NOTIFY_SECONDS) -> None:
    """Durchlauf im Abstand interval_seconds, Wartung alle MAINTENANCE_SECONDS; läuft bis CancelledError.

    Vor jedem Versand prüft der Loop den Verwalter-Schnappschuss, sobald
    ADMIN_CHECK_SECONDS vorbei sind (verify_once): Nach einem Neustart geht nichts
    an einen gespeicherten, aber nicht mehr bestätigten Verwalter, und ein früherer
    Verwalter bleibt höchstens so lange. Die Wartung (Talk-Abgleich) läuft als
    eigener Task (IN-06) und wird beim Beenden mit abgebrochen.
    """
    notifier = get_notifier()
    directory = get_directory()
    try:
        while True:
            now = time.monotonic()
            if _due(LOOP_STATE.last_admin_check, now, ADMIN_CHECK_SECONDS):
                try:
                    await verify_once(service, directory)
                except Exception as exc:
                    LOG.warning("Verwalter-Prüfung fehlgeschlagen: %s", type(exc).__name__)
            if _due(LOOP_STATE.last_maintenance, now, MAINTENANCE_SECONDS):
                _start_maintenance(service)
            try:
                await run_once(service, notifier, directory, int(time.time()))
            except Exception as exc:
                LOG.warning("Benachrichtigungs-Durchlauf fehlgeschlagen: %s", type(exc).__name__)
            await asyncio.sleep(interval_seconds)
    finally:
        task = LOOP_STATE.maintenance_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
