"""Notification loop as a lifespan task (ELTERN-02, ELTERN-03).

The 15 s tick puts events into the SQLite outbox without a network call (04.1-02).
This loop runs in the event loop, works off the outbox every ``NOTIFY_SECONDS``,
checks the daily review per manager and kicks off the maintenance every ``MAINTENANCE_SECONDS``
(entries from ``MAINTENANCE``: forget deleted accounts, then
the Talk reconciliation from 04.1-05). It has the manager snapshot confirmed by Nextcloud
every ``ADMIN_CHECK_SECONDS`` (CR-01): only an account that Nextcloud currently
confirms as admin acts, never the first one from the snapshot unchecked.

Rules:

- Store access only via ``anyio.to_thread``, never under the world lock;
  network calls only here in the event loop (anti-pattern RESEARCH).
- Recipients are only the managers from the snapshot ``meta time_admins``;
  empty means nobody (fail closed, T-04.1-18).
- Claim first, then send (``claim_attempt``, ``claim_review``): a
  crash loses at most one message, nothing ever arrives twice.
- Every outbox kind has a handler in ``HANDLERS`` (04.1-06 adds join,
  leave, warn10, start, stop, pause_*). Rows without a handler are deleted.
- Logs name only IDs, kinds and error types, never player or display names.
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
# The manager snapshot may stay unchecked in the background at most this long (CR-01): if
# an account loses its admin rights, it drops out of recipients, Talk and free rows by then at the latest.
ADMIN_CHECK_SECONDS = 60
# Base URL of the links, reported by the browser of a manager (POST /api/origin).
META_LINK_ORIGIN = "link_origin"


@dataclass
class LoopState:
    """State of the loop in memory (fresh per test in tests)."""

    last_maintenance: float | None = None
    last_admin_check: float | None = None
    origin_warned: bool = False
    # Account last confirmed as admin by Nextcloud (verify_admins), otherwise None.
    acting: str | None = None
    # Running maintenance (Talk reconciliation) as its own task, at most one (IN-06).
    maintenance_task: asyncio.Task[None] | None = None


LOOP_STATE = LoopState()


@dataclass(frozen=True)
class NotifyContext:
    """What a handler needs for one pass."""

    service: WorldService
    notifier: Notifier
    directory: Directory
    now: int
    tz: ZoneInfo
    admins: tuple[str, ...]
    origin: str | None
    # Account for Talk and directory calls: the last confirmed one if still in the
    # snapshot, otherwise the first from it; None without a manager.
    acting: str | None = None
    # Names cached per pass: player name (casefold) -> (key, bot name).
    names: dict[str, tuple[str, str]] = field(default_factory=dict)


Handler = Callable[[NotifyContext, OutboxRow], Awaitable[None]]
# Builds the notification text in the recipient's language (D-25).
TextBuilder = Callable[[str], NotifyText]
MaintenanceHook = Callable[[WorldService, str], Awaitable[None]]
# Maintenance step and whether it needs a confirmed Nextcloud admin (instead of just any manager).
MaintenanceStep = tuple[MaintenanceHook, bool]


def link_origin(store: WorldStore) -> str | None:
    """Base URL from meta link_origin, otherwise NEXTCLOUD_URL (also with webroot); invalid or empty: None."""
    for candidate in (store.get_meta(META_LINK_ORIGIN), os.environ.get("NEXTCLOUD_URL")):
        if not candidate:
            continue
        try:
            return clean_origin(candidate.rstrip("/").removesuffix("/index.php"))
        except ValueError:
            continue
    return None


def collect_play(store: WorldStore, day: date, admins: Iterable[str]) -> dict[str, dict[str, int]]:
    """Seconds played on a day per child and world; only children with rules, never managers (IN-03).

    "Rules" means: a weekly plan of this household (``child_plans``, like
    ``has_rules`` of the playtime page). Older rows of accounts without rules
    (counted before IN-03) or with rules removed today do not appear either.
    Adults (table ``adults``, ROLLE-04) never appear, not even with
    minutes counted before the switch on the same day.
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
    """Children whose daily limit is reached today (TimeEngine.child_state, reason "limit")."""
    reached: set[str] = set()
    for nc_user in nc_users:
        state = service.time.child_state(nc_user)
        if state is not None and state.reason == "limit":
            reached.add(nc_user)
    return reached


async def display_name(directory: Directory, acting_uid: str, store: WorldStore, nc_user: str) -> str:
    """Display name from Nextcloud, otherwise player name, otherwise account; cleaned and capped."""
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
    """Foreign join attempt: remember, report throttled to all managers (D-07, D-08)."""
    store = context.service.store
    world, invited = await anyio.to_thread.run_sync(_world_and_invited, store, row.world_id)
    if world is None or is_case_variant(row.name, invited):
        return
    day = local_day(row.at, context.tz)
    # IN-05: without recipient or link address only remember, do not use up a notice.
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


# Gameworld bot in the Talk room of the world (TALK-02, D-21 to D-24, D-28)

# Join/leave of the same person in the same world at most every 10 minutes (D-22).
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
    """(Throttle key, name for the text): account and display name, fallback player name."""
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
    """Daily marker of the 10-minute notice per world and person (WR-02)."""
    return f"warn10:{world_id}:{person}"


async def handle_warn10(context: NotifyContext, row: OutboxRow) -> None:
    """10 minutes of playtime left, with sound (D-23, D-28); per world, person and day at most once (WR-02).

    The mod reports again after every reconnect with 5 to 10 minutes remaining. Therefore
    claim the daily marker first, then send: reconnecting never rings
    again on all phones in the room, not even after a restart of the ExApp.
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
    """Pause until H:MM in the household time zone, with sound; nothing without a valid end."""
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
    """Talk reconciliation (04.1-05): create rooms, members, read-only, pending deletions.

    ``acting`` is the account just confirmed by Nextcloud (verify_once, CR-01).
    """
    await get_talk_service(service.store).reconcile_all(acting)


async def purge_accounts(service: WorldService, acting: str) -> None:
    """Forget accounts deleted in Nextcloud: players, invitations, playtime, review.

    ``acting`` is a confirmed Nextcloud admin (meta nc_admins, run_hooks).
    "404 means deleted" applies only on behalf of an admin: a manager from an
    additional group sees foreign accounts as 404 and would wrongly have them forgotten
    (RESEARCH F-04, ROADMAP criterion 5, dabe0c0). Therefore the step first asks
    once more, fresh, whether ``acting`` itself is in the group admin; otherwise
    nothing runs. Before the Talk reconciliation, so that it no longer wants to bring a deleted account into
    rooms. An outage at Nextcloud aborts the run without deleting
    (AccessService.purge_missing_accounts).
    """
    directory = get_directory()
    try:
        members = await directory.group_members(acting, ADMIN_GROUP)
    except DirectoryUnavailableError:
        # Also DirectoryRejectedError (subclass): no admin, no reconciliation.
        LOG.info("Account reconciliation skipped: %s is currently not confirmed as Nextcloud admin", acting)
        return
    if acting not in (members or ()):
        LOG.info("Account reconciliation skipped: %s is no longer a Nextcloud admin", acting)
        return
    access = AccessService(service.store, service, directory, get_player_secret())
    await access.purge_missing_accounts(acting)


# (step, needs a confirmed Nextcloud admin): the account reconciliation runs only as admin (F-04).
MAINTENANCE: list[MaintenanceStep] = [(purge_accounts, True), (talk_reconcile, False)]


def _due_admins(store: WorldStore, admins: tuple[str, ...], day: date, minute: int) -> list[str]:
    due: list[str] = []
    for uid in admins:
        enabled, pref_minute = store.review_pref(uid)
        if review_due(minute, pref_minute, enabled=enabled) and not store.review_was_sent(uid, day):
            due.append(uid)
    return due


async def _reviews(context: NotifyContext) -> None:
    """Daily review: content first, claim, then send (pattern 5, D-14, D-15, WR-03).

    Due only in the short window after the configured minute. Without playtime
    no message comes, but the day counts as done for the due managers:
    later play on the same day triggers no review any more.
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
    """One pass: work off and delete the outbox, then check the review."""
    store = service.store
    admins, origin, tz = await anyio.to_thread.run_sync(_context_data, store, service)
    if origin is None and not LOOP_STATE.origin_warned:
        LOOP_STATE.origin_warned = True
        LOG.warning("No base URL for notification links (link_origin, NEXTCLOUD_URL); nothing is sent")
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
            LOG.warning("Event %s (%s, world %s) not processed: %s", row.id, row.kind, row.world_id, type(exc).__name__)
    if rows:
        await anyio.to_thread.run_sync(store.delete_outbox, [row.id for row in rows])
    await _reviews(context)


async def verify_once(service: WorldService, directory: Directory) -> str | None:
    """Have Nextcloud confirm the snapshot in the background (CR-01); confirmed account or None.

    Never ``admins[0]`` unchecked: only an account whose group query succeeds and
    that is an admin itself counts as acting (TimeService.verify_admins).
    """
    raw = await anyio.to_thread.run_sync(service.store.get_meta, META_TIME_ADMINS)
    admins = sorted(parse_admins(raw))
    acting: str | None = None
    if admins:
        try:
            acting = await TimeService(service, directory).verify_admins(admins)
        except Exception as exc:
            LOG.warning("Manager snapshot not checked: %s", type(exc).__name__)
    LOOP_STATE.acting = acting
    LOOP_STATE.last_admin_check = time.monotonic()
    if acting is not None:
        # Review settings of earlier managers drop out with the confirmed state (IN-03).
        try:
            confirmed = await anyio.to_thread.run_sync(service.store.get_meta, META_TIME_ADMINS)
            await anyio.to_thread.run_sync(service.store.prune_review_prefs, set(parse_admins(confirmed)))
        except Exception as exc:
            LOG.warning("Review settings not cleaned up: %s", type(exc).__name__)
    return acting


def _nc_admin_for(store: WorldStore, acting: str) -> str | None:
    """Confirmed Nextcloud admin for admin steps: ``acting`` itself if in it, otherwise the first; otherwise None."""
    nc_admins = sorted(parse_admins(store.get_meta(META_NC_ADMINS)))
    if acting in nc_admins:
        return acting
    return nc_admins[0] if nc_admins else None


async def run_hooks(service: WorldService, acting: str) -> None:
    """All entries from MAINTENANCE; errors isolated per entry.

    Steps without admin need run with the confirmed manager ``acting``.
    Admin steps (account reconciliation) run only with an account from meta nc_admins;
    if there is none, they are skipped (404 trap, F-04).
    """
    nc_admin: str | None = None
    try:
        nc_admin = await anyio.to_thread.run_sync(_nc_admin_for, service.store, acting)
    except Exception as exc:
        LOG.warning("Nextcloud admins not readable: %s", type(exc).__name__)
    for hook, needs_nc_admin in list(MAINTENANCE):
        hook_acting = nc_admin if needs_nc_admin else acting
        if hook_acting is None:
            LOG.info("Account reconciliation skipped: no confirmed Nextcloud admin")
            continue
        try:
            await hook(service, hook_acting)
        except Exception as exc:
            LOG.warning("Maintenance step failed: %s", type(exc).__name__)


async def maintain_once(service: WorldService, directory: Directory) -> None:
    """Maintenance: confirm snapshot, then MAINTENANCE only with the confirmed account (pitfall 9, CR-01)."""
    acting = await verify_once(service, directory)
    if acting is None:
        return
    await run_hooks(service, acting)


def _due(last: float | None, now: float, seconds: float) -> bool:
    return last is None or now - last >= seconds


def _start_maintenance(service: WorldService) -> None:
    """Maintenance as its own task (IN-06): a slow Talk reconciliation does not hold up notices and review.

    At most one maintenance task at a time; if the previous one is still running, the next waits.
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
    """Pass every interval_seconds, maintenance every MAINTENANCE_SECONDS; runs until CancelledError.

    Before every send the loop checks the manager snapshot as soon as
    ADMIN_CHECK_SECONDS have passed (verify_once): after a restart nothing goes
    to a stored but no longer confirmed manager, and a former
    manager stays at most that long. The maintenance (Talk reconciliation) runs as its
    own task (IN-06) and is cancelled on shutdown.
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
                    LOG.warning("Manager check failed: %s", type(exc).__name__)
            if _due(LOOP_STATE.last_maintenance, now, MAINTENANCE_SECONDS):
                _start_maintenance(service)
            try:
                await run_once(service, notifier, directory, int(time.time()))
            except Exception as exc:
                LOG.warning("Notification pass failed: %s", type(exc).__name__)
            await asyncio.sleep(interval_seconds)
    finally:
        task = LOOP_STATE.maintenance_task
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
