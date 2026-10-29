"""Maintain playtime rules per child, holidays and time zone (ZEIT-01, ZEIT-03, ZEIT-04, manager).

Only the ExApp can compute a quota across all worlds (O-03): this service
writes the weekly plan (and the holiday plan) of a child into the database and
pushes the rule file immediately into every world of the child (``WorldService.push_time``),
without a world restart. Holiday periods and time zone apply to the whole household
(O-08, O-02): every change rewrites the rule file of all worlds, so that no
world keeps running with the old plan or old day boundaries.

A world time window (ZEIT-05) only sets the world line of the rule file: children cannot
get in outside it and are disconnected at the window end, the world itself keeps
running (O-05, no stop, no intervention in the parents' desired state).

Manager snapshot (O-11/A4, ROLLE-03): the time tick has no acting
user, but only an authorized account resolves groups. Therefore
``refresh_admins`` fetches, in the context of a verified manager, the members of each
manager group (throttled) and keeps the state PER GROUP (table
verwalter_snapshot). If the account may not read a group (403, e.g. a teacher
on the group admin) or Nextcloud is disturbed, exactly the state of that group
stays (P-03). The union of all group states stands as meta ``time_admins`` (JSON,
sorted, the acting manager always in it); all existing readers see it
unchanged. Separately, meta ``nc_admins`` keeps the confirmed members of the
group admin: only they may trigger the account reconciliation (404 trap, F-04). Without
any state there is no exemption (fail closed).

Lock rule (as in access/service.py, _LOCK is not reentrant): Nextcloud calls
(display name, group admin) always run outside ``worlds.mutation()`` and
always BEFORE entering; under the lock only the store and writing the
rule file. Dashboard paths take the lock only via ``try_mutation()``. The
display name is an extra: if Nextcloud fails, the account name stands instead of the
display name, the rule itself does not depend on it.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.access.directory import Directory, DirectoryRejectedError, DirectoryUnavailableError
from gameworld.access.roles import ADMIN_GROUP, META_VERWALTER_GROUPS, parse_verwalter_groups
from gameworld.access.service import MSG_NO_PLAYER, PlayerNotFoundError
from gameworld.playtime.engine import META_TIME_ADMINS, parse_admins
from gameworld.playtime.plan import (
    DEFAULT_TIME_ZONE,
    ChildState,
    Holiday,
    NextStart,
    WeekPlan,
    WindowDay,
    evaluate_world,
    load_zone,
    local_day,
    window_days,
)
from gameworld.provisioner.client import WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND, WorldService
from gameworld.worlds.store import WorldStore

LOG = logging.getLogger(__name__)

# Data minimization: at most this many holiday periods (T-04-23).
MAX_HOLIDAYS = 50
MSG_TOO_MANY_HOLIDAYS = f"Es sind höchstens {MAX_HOLIDAYS} Ferienzeiträume möglich."
MSG_NO_HOLIDAY = "Diesen Ferienzeitraum gibt es nicht."
MSG_ADMIN_NO_RULES = "Verwalter haben keine Spielzeitregeln."
MSG_ADULT_IS_VERWALTER = "Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln."
MSG_WINDOW_NEEDS_OPEN_DAY = "Eine Welt mit Zeitfenster braucht mindestens einen offenen Tag."
# Fetch the manager snapshot from Nextcloud at most this often (like SYNC_INTERVAL_SECONDS).
ADMINS_INTERVAL_SECONDS = 60
# Confirmed members of the group admin (JSON, sorted); only they trigger the account reconciliation.
# Deliberately here and not in playtime/engine.py (the adult plan changes engine.py).
META_NC_ADMINS = "nc_admins"
# Child view: less rest counts as used up, same threshold as MIN_LEFT in the world mod (pitfall 8).
MIN_LEFT_SECONDS = 60
# Read errors of the time rules (database, time zone, broken rows) become 503.
_READ_ERRORS = (sqlite3.Error, ValueError, KeyError)


@dataclass
class AdminsState:
    """Time (monotonic) of the last query of the manager groups."""

    last: float | None = None


ADMINS_STATE = AdminsState()


class HolidayNotFoundError(LookupError):
    """Unknown holiday id (404)."""


@dataclass
class _GroupRead:
    """Result of the queries of one manager group in a run.

    ``answer``: last successful member list (Nextcloud's answer), None without
    success. ``confirmed``: accounts that could read the group themselves AND are
    in it (CR-01). ``rejected``: accounts to which Nextcloud denied the group.
    """

    answer: frozenset[str] | None = None
    confirmed: set[str] = field(default_factory=set[str])
    rejected: set[str] = field(default_factory=set[str])
    outage: bool = False


@dataclass(frozen=True)
class _AdminsUpdate:
    """New manager state: per group, union (JSON), NC admins (JSON, None = unchanged)."""

    stands: dict[str, frozenset[str]]
    union: str
    nc_admins: str | None
    seen_at: str | None = None


def _next_stands(
    groups: list[str], previous: dict[str, set[str]], reads: dict[str, _GroupRead]
) -> dict[str, frozenset[str]]:
    """State per group: Nextcloud's answer, otherwise the last state without the rejected accounts.

    An account that is in the state of a group and still may not read it
    no longer belongs to it (members read their own group). Whoever merely has
    no rights on the group and is not in it changes nothing (P-03).
    """
    stands: dict[str, frozenset[str]] = {}
    for gid in groups:
        read = reads[gid]
        if read.answer is not None:
            stands[gid] = read.answer
        else:
            stands[gid] = frozenset(previous.get(gid, set[str]()) - read.rejected)
    return stands


def _json_list(uids: Iterable[str]) -> str:
    return json.dumps(sorted(set(uids)))


def _union(groups: Iterable[Iterable[str]]) -> set[str]:
    result: set[str] = set()
    for uids in groups:
        result.update(uids)
    return result


@dataclass(frozen=True)
class ChildView:
    """Playtime view of a child: rules, today's usage and current evaluation."""

    nc_user: str
    display_name: str
    player_name: str
    has_rules: bool
    normal: WeekPlan | None
    holiday: WeekPlan | None
    used_today_s: int
    state: ChildState | None
    # Adult switch (ROLLE-04): plan dormant, the account plays without rules.
    adult: bool = False


@dataclass(frozen=True)
class HolidayView:
    """Holiday period with id; active means: today's local date lies in it."""

    id: int
    label: str
    start_date: date
    end_date: date
    active: bool


@dataclass(frozen=True)
class PlaytimeView:
    """All children (accounts with a player row), holiday periods and time zone of the household."""

    time_zone: str
    holidays: list[HolidayView]
    children: list[ChildView]


@dataclass(frozen=True)
class ChildResult:
    """Result of set_child/clear_child: the new view and whether the worlds carry it yet."""

    child: ChildView
    applied: bool


@dataclass(frozen=True)
class HolidayResult:
    """Result of add_holiday/remove_holiday: the period and whether all worlds carry it."""

    holiday: HolidayView
    applied: bool


@dataclass(frozen=True)
class WorldWindowResult:
    """Result of set_world_window/clear_world_window: window (None = always open) and applied."""

    world_id: str
    time_window: list[WindowDay] | None
    applied: bool


@dataclass(frozen=True)
class NextTime:
    """Next start for the child view: ISO weekday 1..7, local minute 0..1439, days from today.

    ``days_ahead`` 0 means today, 7 means the same weekday in a week: only this way
    can the display say "today" without knowing the household's time zone.
    """

    weekday: int
    minute: int
    days_ahead: int


@dataclass(frozen=True)
class MyPlaytime:
    """A child's own remaining time (child view, 04-07); deliberately without plans and usage.

    ``state``: ok | aufgebraucht | fenster | tag (None without rules). ``remaining_minutes``
    rounded down and never beyond the window end, None without a limit. ``until_minute``
    local from 00:00, None means end of day. ``next`` only when playing is currently not allowed.
    """

    limited: bool
    state: str | None
    remaining_minutes: int | None
    until_minute: int | None
    next: NextTime | None


UNLIMITED = MyPlaytime(limited=False, state=None, remaining_minutes=None, until_minute=None, next=None)


@dataclass(frozen=True)
class WindowSlot:
    """An opening window of a world: weekday, minutes (end 1440 = end of day) and days from today.

    ``days_ahead`` 0 means today (also for the open window), 7 the same weekday
    in a week; with it the child view says "Heute", "Morgen" or "Am Samstag".
    """

    weekday: int
    start: int
    end: int
    days_ahead: int


@dataclass(frozen=True)
class MyWorldWindow:
    """Window status of a world for the child view: open (None = no window) and the current or next one."""

    open: bool | None
    next: WindowSlot | None


NO_WINDOW = MyWorldWindow(open=None, next=None)


class PlaytimeUnavailableError(RuntimeError):
    """The time rules could not be read (503, never data of others)."""


def next_time(start: NextStart | None, now: int, tz: ZoneInfo) -> NextTime | None:
    """Next start (plan.NextStart) as weekday, minute and days from today; None yields None.

    The days come from the absolute epoch of the start, not from the token
    ``Sa-10:00``: if the start is a week later on the same weekday, but at
    a later time than now, that means 7 and not "today" (WR-01).
    """
    if start is None:
        return None
    days_ahead = (local_day(start.at, tz) - local_day(now, tz)).days
    return NextTime(weekday=start.weekday, minute=start.minute, days_ahead=days_ahead)


def _until_minute(until: int, day: date, tz: ZoneInfo) -> int | None:
    """Local minute of the window end; None if it is the end of day (next day 00:00)."""
    local = datetime.fromtimestamp(until, tz)
    if local.date() != day:
        return None
    return local.hour * 60 + local.minute


def kid_playtime(state: ChildState, now: int, tz: ZoneInfo) -> MyPlaytime:
    """Evaluation of a child into the structure of the child view (pure).

    Below MIN_LEFT_SECONDS of rest the time counts as used up or the window
    as closed (pitfall 8, the same threshold as MIN_LEFT in the world mod). The minutes
    never reach beyond the window end.
    """
    if state.reason == "tag":
        blocked: str | None = "tag"
    elif state.reason == "limit":
        blocked = "aufgebraucht"
    elif state.reason == "fenster" or state.until - now < MIN_LEFT_SECONDS:
        blocked = "fenster"
    elif state.rest_s is not None and state.rest_s < MIN_LEFT_SECONDS:
        blocked = "aufgebraucht"
    else:
        blocked = None
    if blocked is not None:
        upcoming = next_time(state.next_start, now, tz)
        return MyPlaytime(limited=True, state=blocked, remaining_minutes=0, until_minute=None, next=upcoming)
    remaining = None if state.rest_s is None else min(state.rest_s, state.until - now) // 60
    return MyPlaytime(
        limited=True,
        state="ok",
        remaining_minutes=remaining,
        until_minute=_until_minute(state.until, state.day, tz),
        next=None,
    )


def world_window_status(now: int, tz: ZoneInfo, windows: dict[int, tuple[int, int]] | None) -> MyWorldWindow:
    """World window for the child view: open now plus today's, otherwise the next window (no weekly plan)."""
    state = evaluate_world(now, tz, windows)
    if state is None or windows is None:
        return NO_WINDOW
    if state.reason == "ok":
        today = local_day(now, tz).isoweekday()
        start, end = windows[today]
        return MyWorldWindow(open=True, next=WindowSlot(weekday=today, start=start, end=end, days_ahead=0))
    upcoming = next_time(state.next_start, now, tz)
    slot = None if upcoming is None else windows.get(upcoming.weekday)
    if upcoming is None or slot is None:
        return MyWorldWindow(open=False, next=None)
    return MyWorldWindow(
        open=False,
        next=WindowSlot(weekday=upcoming.weekday, start=slot[0], end=slot[1], days_ahead=upcoming.days_ahead),
    )


@dataclass(frozen=True)
class _Snapshot:
    time_zone: str
    holidays: list[HolidayView]
    rows: list[ChildView]


class TimeService:
    def __init__(self, worlds: WorldService, directory: Directory) -> None:
        self._worlds = worlds
        self._store: WorldStore = worlds.store
        self._directory = directory

    async def refresh_admins(self, acting_uid: str, *, force: bool = False, blocking: bool = True) -> bool:
        """Refresh the manager snapshot per manager group; True if time_admins changed.

        Call only in the context of a verified manager and never under
        ``mutation()`` (the group queries run beforehand, outside the lock).
        Throttled to ADMINS_INTERVAL_SECONDS, except with ``force``. Each group
        individually: rejection (403, e.g. a teacher on the group admin) or a disturbance
        leaves exactly the state of that group in place (P-03). If the
        union changes, all worlds get the new rule file: ``blocking`` under
        ``mutation()``, otherwise (dashboard) via ``try_mutation()``; if the lock is busy,
        the next call catches up.
        """
        now = monotonic()
        if not force and ADMINS_STATE.last is not None and now - ADMINS_STATE.last < ADMINS_INTERVAL_SECONDS:
            return False
        ADMINS_STATE.last = now
        groups = await self._verwalter_groups()
        reads = await self._read_groups(groups, [acting_uid])
        if any(read.outage for read in reads.values()):
            LOG.warning("A manager group is not retrievable, its last state stays")
            ADMINS_STATE.last = None
        if all(read.answer is None and not read.rejected for read in reads.values()):
            # Mere disturbance: nothing new to know, the last state stays unchanged.
            return False
        update = await anyio.to_thread.run_sync(self._plan_refresh, groups, reads, acting_uid)
        if update is None:
            return False
        if blocking:
            return await anyio.to_thread.run_sync(self._store_admins_sync, update)
        return await anyio.to_thread.run_sync(self._try_store_admins_sync, update)

    async def verify_admins(self, candidates: Iterable[str]) -> str | None:
        """Background check of the snapshot without a verified manager (CR-01); confirmed account or None.

        Asks each manager group in turn as the accounts from ``candidates``.
        An account is confirmed only if it can read a group itself AND is in
        it; an account is never inserted unchecked. A successful answer
        replaces the state of that group. Without an answer it stays (a teacher without
        rights on the group admin never empties it, P-03); only accounts that were in it
        and were rejected drop out. If Nextcloud explicitly rejects every account
        (401/403), the snapshot becomes empty (fail closed, no
        recipients, no exemption). meta ``nc_admins`` gets the members of the group
        admin just read; without an answer on admin it is empty,
        then no account reconciliation runs (F-04). Beforehand Nextcloud must accept the ExApp
        itself (Directory.app_accepted), otherwise the check does not even ask
        and the state stays. On a mere disturbance the last state stays, but
        no account counts as confirmed. Lock busy: None, the next run
        tries again.
        """
        # Control probe first: as long as Nextcloud rejects the ExApp itself (startup,
        # re-registration), every account gets 401. That is a disturbance, not a
        # rejection of the accounts; without the probe every restart would empty the
        # snapshot. After, not before: a later probe might already succeed
        # while the queries were still rejected (observed on the dev stack).
        if not await self._directory.app_accepted():
            LOG.warning("Manager snapshot not confirmed, Nextcloud is currently not accepting Gameworld")
            return None
        order = list(dict.fromkeys(candidates))
        if not order:
            return None
        groups = await self._verwalter_groups()
        reads = await self._read_groups(groups, order)
        if all(read.answer is None and not read.rejected for read in reads.values()):
            LOG.warning("Manager snapshot not confirmed, the last state stays")
            return None
        confirmed = _union(read.confirmed for read in reads.values())
        acting = next((uid for uid in order if uid in confirmed), None)
        seen_at = datetime.now(UTC).isoformat(timespec="seconds")
        update = await anyio.to_thread.run_sync(self._plan_verify, groups, reads, seen_at)
        if not await anyio.to_thread.run_sync(self._store_admins_background_sync, update):
            return None
        if acting is None:
            LOG.warning("No account of the manager snapshot is confirmed, the state follows the answers")
            return None
        ADMINS_STATE.last = monotonic()
        return acting

    async def _verwalter_groups(self) -> list[str]:
        """Configured manager groups, admin first; a broken configuration means admin only (fail closed)."""
        raw = await anyio.to_thread.run_sync(self._store.get_meta, META_VERWALTER_GROUPS)
        return sorted(parse_verwalter_groups(raw), key=lambda gid: (gid != ADMIN_GROUP, gid))

    async def _read_groups(self, groups: list[str], candidates: list[str]) -> dict[str, _GroupRead]:
        """Each group as the candidates in turn, until one reads it and is in it.

        Outside any lock (lock rule); an error affects only that one group.
        """
        reads: dict[str, _GroupRead] = {}
        for gid in groups:
            read = _GroupRead()
            for uid in candidates:
                try:
                    members = await self._directory.group_members(uid, gid)
                except DirectoryRejectedError:
                    read.rejected.add(uid)
                    continue
                except DirectoryUnavailableError:
                    read.outage = True
                    continue
                read.answer = frozenset(members or ())
                if uid in read.answer:
                    read.confirmed.add(uid)
                    break
            reads[gid] = read
        return reads

    async def list_children(self, acting_uid: str) -> PlaytimeView:
        """All accounts with a player row (without managers), each with rules, usage and evaluation."""
        await self.refresh_admins(acting_uid)
        snapshot = await anyio.to_thread.run_sync(self._snapshot)
        children: list[ChildView] = []
        for row in snapshot.rows:
            display = await self._display_name(acting_uid, row.nc_user)
            children.append(replace(row, display_name=display))
        return PlaytimeView(time_zone=snapshot.time_zone, holidays=snapshot.holidays, children=children)

    async def set_child(
        self, acting_uid: str, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None = None
    ) -> ChildResult:
        """Set the weekly and holiday plan of a child and write the rule file into all its worlds.

        ``holiday`` None means: during holidays the normal plan applies. It rejects
        manager accounts (ValueError, 422): they are exempt (A4).
        """
        await self._require_player(nc_user)
        await self.refresh_admins(acting_uid, force=True)
        applied = await anyio.to_thread.run_sync(self._set_sync, nc_user, normal, holiday, acting_uid)
        return await self._result(acting_uid, nc_user, applied)

    async def clear_child(self, acting_uid: str, nc_user: str) -> ChildResult:
        """Remove the rules of a child (back to no limit, O-10); today's usage stays."""
        await self._require_player(nc_user)
        await self.refresh_admins(acting_uid, force=True)
        applied = await anyio.to_thread.run_sync(self._clear_sync, nc_user)
        return await self._result(acting_uid, nc_user, applied)

    async def set_adult(self, acting_uid: str, nc_user: str, *, adult: bool) -> bool:
        """Adult switch of an invited account (ROLLE-04, D-05/D-08); True if all worlds carry it.

        Call only from the manager router (D-06). Acts exclusively on the
        time rules (frei line, no booking), never on administration or
        Luanti rights. Unknown account: PlayerNotFoundError; a manager account
        cannot be marked as an adult (ValueError MSG_ADULT_IS_VERWALTER).
        """
        # Nextcloud query outside the lock (lock rule), then a fresh manager state.
        await self.refresh_admins(acting_uid, force=True)
        return await anyio.to_thread.run_sync(self._adult_sync, nc_user, adult, acting_uid)

    async def add_holiday(self, holiday: Holiday) -> HolidayResult:
        """Create a holiday period for the household and rewrite all worlds (O-08)."""
        return await anyio.to_thread.run_sync(self._add_holiday_sync, holiday)

    async def remove_holiday(self, holiday_id: int) -> HolidayResult:
        """Remove a holiday period; from now on the normal plan applies again where it took effect."""
        return await anyio.to_thread.run_sync(self._remove_holiday_sync, holiday_id)

    async def set_time_zone(self, time_zone: str) -> bool:
        """Set the time zone (the caller checks against ``available_timezones``) and rewrite all worlds."""
        return await anyio.to_thread.run_sync(self._set_time_zone_sync, time_zone)

    async def set_world_window(
        self, acting_uid: str, world_id: str, windows: dict[int, tuple[int, int]]
    ) -> WorldWindowResult:
        """Set the weekly time window of a world (missing weekday = closed) and write the rule file.

        The world keeps running (O-05); outside the window the mod blocks children
        on joining and disconnects connected ones at the window end.
        """
        if not windows:
            raise ValueError(MSG_WINDOW_NEEDS_OPEN_DAY)
        await self._require_world(world_id)
        await self.refresh_admins(acting_uid, force=True)
        return await anyio.to_thread.run_sync(self._window_sync, world_id, windows)

    async def clear_world_window(self, acting_uid: str, world_id: str) -> WorldWindowResult:
        """Remove the time window: the world is always open from now on, without a restart."""
        await self._require_world(world_id)
        await self.refresh_admins(acting_uid, force=True)
        return await anyio.to_thread.run_sync(self._window_sync, world_id, None)

    async def my_playtime(self, nc_user: str, *, exempt: bool) -> MyPlaytime:
        """A child's own remaining time for the child view; ``nc_user`` comes from the signed request.

        ``exempt`` (manager by self-declaration) and accounts in the manager snapshot
        are free as in the world mod (A4); without rules no limit (O-10). Only
        reads, without a lock. Read error: PlaytimeUnavailableError.
        """
        if exempt:
            return UNLIMITED
        return await anyio.to_thread.run_sync(self._my_playtime_sync, nc_user)

    async def my_world_windows(self, world_ids: list[str]) -> dict[str, MyWorldWindow]:
        """Window status per own world (open now, current or next window); read error: 503."""
        return await anyio.to_thread.run_sync(self._my_world_windows_sync, world_ids)

    def _my_playtime_sync(self, nc_user: str) -> MyPlaytime:
        try:
            # Free set as in the world mod: managers and adults (ROLLE-04).
            if nc_user in self._admins() or nc_user in self._store.adults():
                return UNLIMITED
            engine = self._worlds.time
            state = engine.child_state(nc_user)
            if state is None:
                return UNLIMITED
            return kid_playtime(state, engine.now(), self._zone())
        except _READ_ERRORS as exc:
            LOG.warning("Playtime for the child view not readable: %s", type(exc).__name__)
            raise PlaytimeUnavailableError from exc

    def _my_world_windows_sync(self, world_ids: list[str]) -> dict[str, MyWorldWindow]:
        try:
            now = self._worlds.time.now()
            tz = self._zone()
            return {
                world_id: world_window_status(now, tz, self._store.world_window(world_id)) for world_id in world_ids
            }
        except _READ_ERRORS as exc:
            LOG.warning("World time window for the child view not readable: %s", type(exc).__name__)
            raise PlaytimeUnavailableError from exc

    def _zone(self) -> ZoneInfo:
        return load_zone(self._store.get_meta("time_zone") or "")

    # Under the lock (worker thread)

    def _previous_stands(self) -> dict[str, set[str]]:
        """Last state per group; before the first run with schema 8 the old snapshot counts as group admin."""
        stands = self._store.group_snapshot()
        if not stands:
            legacy = self._admins()
            if legacy:
                stands = {ADMIN_GROUP: set(legacy)}
        return stands

    def _plan_refresh(self, groups: list[str], reads: dict[str, _GroupRead], acting_uid: str) -> _AdminsUpdate | None:
        """New state after a manager visit; None if nothing changes (then no lock)."""
        stands = _next_stands(groups, self._previous_stands(), reads)
        union = _json_list(_union(stands.values()) | {acting_uid})
        admin_read = reads[ADMIN_GROUP]
        if admin_read.answer is not None:
            nc_admins: str | None = _json_list(admin_read.answer)
        elif admin_read.rejected:
            current = parse_admins(self._store.get_meta(META_NC_ADMINS))
            nc_admins = _json_list(current - admin_read.rejected)
        else:
            nc_admins = None
        update = _AdminsUpdate(stands=stands, union=union, nc_admins=nc_admins)
        return update if self._differs(update) else None

    def _plan_verify(self, groups: list[str], reads: dict[str, _GroupRead], seen_at: str) -> _AdminsUpdate:
        """New state after the background check; nc_admins only from a fresh answer of the group admin."""
        stands = _next_stands(groups, self._previous_stands(), reads)
        answered = any(read.answer is not None for read in reads.values())
        outage = any(read.outage for read in reads.values())
        if not answered and not outage:
            # Every query of every account rejected: nobody is confirmed anymore (fail closed).
            stands = {gid: frozenset[str]() for gid in groups}
        admin_answer = reads[ADMIN_GROUP].answer
        return _AdminsUpdate(
            stands=stands,
            union=_json_list(_union(stands.values())),
            nc_admins=_json_list(admin_answer or ()),
            seen_at=seen_at,
        )

    def _differs(self, update: _AdminsUpdate) -> bool:
        current = {gid: frozenset(uids) for gid, uids in self._store.group_snapshot().items()}
        wanted = {gid: uids for gid, uids in update.stands.items() if uids}
        if current != wanted or self._store.get_meta(META_TIME_ADMINS) != update.union:
            return True
        return update.nc_admins is not None and self._store.get_meta(META_NC_ADMINS) != update.nc_admins

    def _store_admins_sync(self, update: _AdminsUpdate) -> bool:
        with self._worlds.mutation():
            return self._apply_admins(update)

    def _try_store_admins_sync(self, update: _AdminsUpdate) -> bool:
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                # Lock busy: the next manager call tries again.
                ADMINS_STATE.last = None
                return False
            return self._apply_admins(update)

    def _store_admins_background_sync(self, update: _AdminsUpdate) -> bool:
        """Background: store the state without waiting; True if it applies now."""
        with self._worlds.try_mutation() as acquired:
            if not acquired:
                return False
            self._apply_admins(update)
            return True

    def _apply_admins(self, update: _AdminsUpdate) -> bool:
        """Only under the lock: store state per group, NC admins, service age and union.

        True if time_admins is new; then all worlds get the new rule file.
        """
        for gid, uids in sorted(update.stands.items()):
            self._store.replace_group_snapshot(gid, set(uids))
        self._store.drop_group_snapshots(keep=set(update.stands))
        if update.nc_admins is not None:
            self._store.set_meta(META_NC_ADMINS, update.nc_admins)
        if update.seen_at is not None:
            self._store.sync_verwalter_seen(set(parse_admins(update.union)), update.seen_at)
        if self._store.get_meta(META_TIME_ADMINS) == update.union:
            return False
        self._store.set_meta(META_TIME_ADMINS, update.union)
        self._refresh_all_worlds()
        return True

    def _admins(self) -> frozenset[str]:
        return parse_admins(self._store.get_meta(META_TIME_ADMINS))

    def _window_sync(self, world_id: str, windows: dict[int, tuple[int, int]] | None) -> WorldWindowResult:
        with self._worlds.mutation():
            if self._store.get_world(world_id) is None:
                raise WorldNotFoundError(NOT_FOUND)
            if windows is None:
                self._store.clear_world_window(world_id)
            else:
                self._store.replace_world_window(world_id, windows)
            applied = self._worlds.push_time(world_id)
            current = window_days(self._store.world_window(world_id))
        return WorldWindowResult(world_id=world_id, time_window=current, applied=applied)

    def _set_sync(self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, acting_uid: str) -> bool:
        updated_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._worlds.mutation():
            if nc_user in self._admins():
                raise ValueError(MSG_ADMIN_NO_RULES)
            self._store.set_child_plan(nc_user, normal, holiday, acting_uid, updated_at)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _adult_sync(self, nc_user: str, adult: bool, acting_uid: str) -> bool:
        set_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._worlds.mutation():
            if self._store.get_player(nc_user) is None:
                raise PlayerNotFoundError(MSG_NO_PLAYER)
            if adult:
                if nc_user in self._admins():
                    raise ValueError(MSG_ADULT_IS_VERWALTER)
                self._store.set_adult(nc_user, acting_uid, set_at)
            else:
                # Back to child is always allowed, also for an account that has since become a manager.
                self._store.clear_adult(nc_user)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _clear_sync(self, nc_user: str) -> bool:
        with self._worlds.mutation():
            # Keep today's usage: setting again gives no fresh quota (WR-04).
            today = local_day(self._worlds.time.now(), self._zone())
            self._store.clear_child(nc_user, keep_from=today)
            return all(self._worlds.push_time(world_id) for world_id in self._store.player_worlds(nc_user))

    def _add_holiday_sync(self, holiday: Holiday) -> HolidayResult:
        with self._worlds.mutation():
            # Count and create under the same lock: two parallel requests
            # cannot exceed the upper limit together.
            if len(self._store.holiday_rows()) >= MAX_HOLIDAYS:
                raise ValueError(MSG_TOO_MANY_HOLIDAYS)
            holiday_id = self._store.add_holiday(holiday.start, holiday.end, holiday.label)
            applied = self._refresh_all_worlds()
            view = self._holiday_view(holiday_id, holiday)
        return HolidayResult(holiday=view, applied=applied)

    def _remove_holiday_sync(self, holiday_id: int) -> HolidayResult:
        with self._worlds.mutation():
            found = next((item for hid, item in self._store.holiday_rows() if hid == holiday_id), None)
            if found is None or not self._store.remove_holiday(holiday_id):
                raise HolidayNotFoundError(MSG_NO_HOLIDAY)
            applied = self._refresh_all_worlds()
            view = self._holiday_view(holiday_id, found)
        return HolidayResult(holiday=view, applied=applied)

    def _set_time_zone_sync(self, time_zone: str) -> bool:
        with self._worlds.mutation():
            self._store.set_meta("time_zone", time_zone)
            return self._refresh_all_worlds()

    def _refresh_all_worlds(self) -> bool:
        """Rewrite the rule file of all worlds in the database; only under mutation().

        Without a container the next start writes it (push_time then returns False).
        Result: do all worlds already carry the new state?
        """
        results = [self._worlds.push_time(row.id) for row in self._store.list_worlds()]
        return all(results)

    def _today(self) -> date:
        return local_day(int(time.time()), self._zone())

    def _holiday_view(self, holiday_id: int, holiday: Holiday, today: date | None = None) -> HolidayView:
        day = self._today() if today is None else today
        return HolidayView(
            id=holiday_id,
            label=holiday.label,
            start_date=holiday.start,
            end_date=holiday.end,
            active=holiday.start <= day <= holiday.end,
        )

    def _snapshot(self, *, without_admins: bool = True) -> _Snapshot:
        tz_name = self._store.get_meta("time_zone") or DEFAULT_TIME_ZONE
        today = local_day(int(time.time()), load_zone(tz_name))
        plans = self._store.child_plans()
        holidays = [self._holiday_view(hid, item, today) for hid, item in self._store.holiday_rows()]
        # Managers do not appear in the child list (A4); the single view after clear_child shows them.
        admins = self._admins() if without_admins else frozenset[str]()
        adults = self._store.adults()
        rows: list[ChildView] = []
        for player in self._store.list_players():
            if player.nc_user in admins:
                continue
            has_rules = player.nc_user in plans
            normal, holiday = plans[player.nc_user] if has_rules else (None, None)
            rows.append(
                ChildView(
                    nc_user=player.nc_user,
                    display_name=player.nc_user,
                    player_name=player.player_name,
                    has_rules=has_rules,
                    normal=normal,
                    holiday=holiday,
                    used_today_s=self._store.usage(player.nc_user, today),
                    state=self._worlds.time.child_state(player.nc_user),
                    adult=player.nc_user in adults,
                )
            )
        return _Snapshot(time_zone=tz_name, holidays=holidays, rows=rows)

    def _child_snapshot(self, nc_user: str) -> ChildView:
        for row in self._snapshot(without_admins=False).rows:
            if row.nc_user == nc_user:
                return row
        raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _result(self, acting_uid: str, nc_user: str, applied: bool) -> ChildResult:
        row = await anyio.to_thread.run_sync(self._child_snapshot, nc_user)
        display = await self._display_name(acting_uid, nc_user)
        return ChildResult(child=replace(row, display_name=display), applied=applied)

    async def _require_world(self, world_id: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_world, world_id) is None:
            raise WorldNotFoundError(NOT_FOUND)

    async def _require_player(self, nc_user: str) -> None:
        if await anyio.to_thread.run_sync(self._store.get_player, nc_user) is None:
            raise PlayerNotFoundError(MSG_NO_PLAYER)

    async def _display_name(self, acting_uid: str, nc_user: str) -> str:
        try:
            user = await self._directory.user(acting_uid, nc_user)
        except DirectoryUnavailableError:
            return nc_user
        return nc_user if user is None else user.display_name
