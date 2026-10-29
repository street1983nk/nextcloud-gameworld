"""The ExApp's playtime calculation: book, render, maintain usage.

Only this layer connects the pure modules (``playtime.plan``,
``playtime.ledger``, ``provisioner.time_mod``) with the database (schema 4). It
is synchronous and knows no Docker: it only reads and writes the store and
pure functions. The caller (``WorldService``) reads the counter ledger from the
world and writes the rule file; the 15 s tick and the invitation path call
these methods under the world lock or ``try_mutation`` respectively.

``book`` books the ledger increases of a world to the local day of each child
with rules (one quota across all worlds, O-03) and re-anchors the state seen.
``render`` computes the rule file per world from the database: for every
invited child with rules a line with an absolute window and cap in ledger units
(state seen plus remaining seconds), for every invited manager account from the
``time_admins`` snapshot and for every account marked as an adult (table
``adults``, ROLLE-04) the line ``frei`` (O-11/A4), plus the world line from the
world window. The rule part is cached per world; only on a change does the
generation count up and the head get a new timestamp, so the bytes do not
change on every tick (pitfall 6).

For the child text, ``render`` writes no finished relative day ("tomorrow")
but absolute epochs (quick 261021-481): per line the next start (``@start``)
and once the day starts from today to today+8 (``@tage``). The mod computes
"Heute", "Morgen" or "Am Samstag" against its own clock; the text thus stays
correct after midnight even if the rule file is not yet new. The epochs do not
change with the clock, ``@tage`` only once per day.

A running household pause (``pause_state``, ELTERN-01) is written by ``render``
as ``@pause`` into every world, for "Für heute Schluss" plus ``@morgen`` per
child of the world with a plan. Pause and tomorrow minutes are part of the
cache key; after expiry the pause drops out (new generation) and the row in
``pause_state`` is deleted.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import astuple, dataclass, field
from datetime import datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from gameworld.playtime.ledger import attribution_day, increments
from gameworld.playtime.pause import ART_SCHLUSS, OUTBOX_PAUSE_END, morgen_minutes
from gameworld.playtime.plan import (
    ChildState,
    NextStart,
    day_starts,
    evaluate_child,
    evaluate_world,
    load_zone,
    local_day,
)
from gameworld.provisioner.time_mod import DayGrid, Ledger, PauseLine, TimeLine, render_time_file
from gameworld.worlds.store import WorldStore

# Prune usage at most once per hour (A8/pitfall 9).
_PRUNE_INTERVAL_SECONDS = 3600
# Retention: today and 7 days back.
_RETENTION_DAYS = 7
# meta key of the manager snapshot (JSON list, sorted; playtime/service.py).
META_TIME_ADMINS = "time_admins"
# Managers are exempt (O-11/A4): world window and own limits do not apply.
_FREI = TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-")


def _next_fields(start: NextStart | None) -> tuple[int, int]:
    """Fields next_at and next_minute of a TimeLine; -1 -1 means: no next start."""
    return (-1, -1) if start is None else (start.at, start.minute)


def _anchor(previous: tuple[int, int] | None, cap: int, seen: int) -> int:
    """Ledger anchor @base for the cap (WR-06); -1 without a cap.

    If the cap stays the same, the old anchor stays too: otherwise the bytes
    would change on every tick in which the child plays here (pitfall 6). The
    old anchor is never above the mod's state, so the cap still applies unchanged.
    """
    if cap < 0:
        return -1
    if previous is not None and previous[0] == cap:
        return previous[1]
    return seen


def parse_admins(raw: str | None) -> frozenset[str]:
    """Manager snapshot from meta; if missing or broken, there is no exemption (fail closed)."""
    if not raw:
        return frozenset()
    try:
        value: object = json.loads(raw)
    except ValueError:
        return frozenset()
    if not isinstance(value, list):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))  # pyright: ignore[reportUnknownVariableType]


@dataclass(frozen=True)
class _Rendered:
    """Per-world cache: rule part, generation, timestamp and finished bytes."""

    key: tuple[object, ...]
    generation: int
    issued_at: int
    data: bytes
    # Per player name (cap, anchor): the anchor @base stays as long as the cap is the same (WR-06).
    bases: dict[str, tuple[int, int]] = field(default_factory=dict[str, tuple[int, int]])


class TimeEngine:
    """Computes rule files from schema 4 and books ledger increases (pure except for the store)."""

    def __init__(self, store: WorldStore, clock: Callable[[], float] = time.time) -> None:
        self._store = store
        self._clock = clock
        # Last rendered state per world (memory): prevents the bytes from
        # changing on every tick (new generation only on a real change).
        self._cache: dict[str, _Rendered] = {}
        # Halt time per world before the cold backup (D-09): in memory only, never in
        # SQLite. After a process restart, startup renders the file without a halt
        # (T-05-14). Callers hold the world lock during push_time.
        self._halts: dict[str, int] = {}
        self._last_prune: int | None = None

    def _now(self) -> int:
        return int(self._clock())

    def now(self) -> int:
        """Now (epoch) by this calculation's clock; the child view computes with the same clock."""
        return self._now()

    def _zone(self) -> ZoneInfo:
        return load_zone(self._store.get_meta("time_zone") or "")

    def zone(self) -> ZoneInfo:
        """Household time zone (meta time_zone, default Europe/Berlin), e.g. for "Für heute Schluss"."""
        return self._zone()

    def _active_pause(self, now: int) -> PauseLine | None:
        """Running pause as the line ``@pause``; an expired one is deleted from pause_state."""
        state = self._store.get_pause()
        if state is None:
            return None
        if now >= state.bis:
            # Delete only what has expired by now: a pause that was just set stays.
            # If a short pause expires by itself, the bot reports it quietly in every world
            # as with "Weiter" (IN-09); "Für heute Schluss" ends quietly at midnight.
            self._store.expire_pause(now, OUTBOX_PAUSE_END)
            return None
        return PauseLine(ab=state.ab, bis=state.bis, art=state.art)

    def _admins(self) -> frozenset[str]:
        return parse_admins(self._store.get_meta(META_TIME_ADMINS))

    def _frei(self, admins: frozenset[str]) -> frozenset[str]:
        """Free set: manager union plus adults (ROLLE-04, time rules only, never rights)."""
        return admins | frozenset(self._store.adults())

    def book(self, world_id: str, ledger: Ledger | None) -> None:
        """Book the ledger increases; re-anchor the state seen.

        Only children with rules are booked against their quota (opt-in, O-10);
        for all other names the state is only anchored (protection against
        double counting). The daily playtime per world (``play_daily``, review)
        also counts only children with rules of this household and never managers
        from the snapshot (IN-03, owner decision 22.10.2026 "Nur Kinder mit Regeln"):
        invited children of other families without rules appear nowhere with
        minutes. Adults (ROLLE-04) are booked neither to usage nor to the daily
        playtime: what was played as an adult does not count, even if a dormant
        plan exists in the database. A missing ledger (None) changes nothing.
        """
        if ledger is None:
            return
        seen = self._store.ledger_seen(world_id)
        delta, new_seen = increments(seen, ledger.seconds)
        usage: dict[str, int] = {}
        play: dict[str, int] = {}
        tz = self._zone()
        day = attribution_day(ledger.written_at, tz)
        if delta:
            plans = self._store.child_plans()
            admins = self._admins()
            adults = self._store.adults()
            for name, seconds in delta.items():
                nc_user = self._store.player_name_owner(name)
                if nc_user is None:
                    continue
                if nc_user not in plans:
                    continue
                if nc_user in adults and nc_user not in admins:
                    continue
                usage[nc_user] = usage.get(nc_user, 0) + seconds
                if nc_user not in admins:
                    play[nc_user] = play.get(nc_user, 0) + seconds
        # Usage, daily playtime and new state in one transaction: never booked twice (WR-05).
        self._store.book_usage(world_id, day, usage, new_seen, play=play)

    def render(self, world_id: str) -> tuple[bytes, bool]:
        """Rule file of the world from the database; (bytes, changed).

        ``changed`` False means: the rule part stayed the same, the bytes
        and the generation are unchanged (anti-pattern "rewrite the rule file
        on every tick").
        """
        tz = self._zone()
        now = self._now()
        plans = self._store.child_plans()
        holidays = self._store.list_holidays()
        seen = self._store.ledger_seen(world_id)
        frei = self._frei(self._admins())
        today = local_day(now, tz)
        cached = self._cache.get(world_id)
        previous = {} if cached is None else cached.bases
        players: dict[str, TimeLine] = {}
        # Children of this world with a plan (account to player name) for the @morgen lines.
        names_by_user: dict[str, str] = {}
        for name in self._store.access_entries(world_id):
            nc_user = self._store.player_name_owner(name)
            if nc_user is None:
                continue
            if nc_user in frei:
                # Invited managers and adults: line frei, even without a world window (A4, ROLLE-04).
                players[name] = _FREI
                continue
            if nc_user not in plans:
                continue
            names_by_user[nc_user] = name
            normal, holiday = plans[nc_user]
            used = self._store.usage(nc_user, today)
            state = evaluate_child(now, tz, normal, holiday, holidays, used)
            # cap_rest_s instead of rest_s: before the window the mod opens from "from" by itself (WR-02).
            cap = -1 if state.cap_rest_s is None else seen.get(name, 0) + state.cap_rest_s
            next_at, next_minute = _next_fields(state.next_start)
            players[name] = TimeLine(
                cap=cap,
                start=state.start,
                until=state.until,
                reason=state.reason,
                next_hint=state.next_hint,
                next_at=next_at,
                next_minute=next_minute,
                base=_anchor(previous.get(name), cap, seen.get(name, 0)),
            )
        world_line = self._world_line(world_id, now, tz)
        lines = [*players.values(), *([] if world_line is None else [world_line])]
        days = None
        if any(line.next_at >= 0 for line in lines):
            # Day boundaries only if a line carries a next start (otherwise bytes as before).
            days = DayGrid(weekday=today.isoweekday(), starts=day_starts(now, tz))
        pause = self._active_pause(now)
        morgen = None
        if pause is not None and pause.art == ART_SCHLUSS:
            morgen = morgen_minutes(now, tz, plans, holidays, names_by_user)
        rendered = self._render_cached(
            world_id, world_line, players, now, days, pause, morgen, halt=self._halts.get(world_id), frei=frei
        )
        self._maybe_prune(now, tz)
        return rendered

    def set_halt(self, world_id: str, ab: int) -> None:
        """Remember the halt of the world (epoch ``ab``); the next ``render`` writes ``@halt``.

        The time mod announces the halt in chat, blocks joins and disconnects all
        players from ``ab`` (05-RESEARCH.md pattern 6). The halt is process state,
        not a cache: ``forget`` leaves it in place, only ``clear_halt`` removes it.
        """
        self._halts[world_id] = ab

    def clear_halt(self, world_id: str) -> None:
        """Remove the halt of the world; the next ``render`` writes the file without ``@halt``."""
        self._halts.pop(world_id, None)

    def forget(self, world_id: str) -> None:
        """Discard the rendered state of the world (CR-01).

        After a failed write of the rule file: the next ``render``
        returns ``changed`` True (with a new generation), so the tick writes the
        file again instead of treating the state that never arrived as written.
        """
        self._cache.pop(world_id, None)

    def child_state(self, nc_user: str) -> ChildState | None:
        """Evaluation for a child (API and child view); None means: no rules (opt-in)."""
        plans = self._store.child_plans()
        if nc_user not in plans:
            return None
        tz = self._zone()
        now = self._now()
        normal, holiday = plans[nc_user]
        holidays = self._store.list_holidays()
        used = self._store.usage(nc_user, local_day(now, tz))
        return evaluate_child(now, tz, normal, holiday, holidays, used)

    def _world_line(self, world_id: str, now: int, tz: ZoneInfo) -> TimeLine | None:
        state = evaluate_world(now, tz, self._store.world_window(world_id))
        if state is None:
            return None
        next_at, next_minute = _next_fields(state.next_start)
        return TimeLine(
            cap=0,
            start=state.start,
            until=state.until,
            reason=state.reason,
            next_hint=state.next_hint,
            next_at=next_at,
            next_minute=next_minute,
        )

    def _render_cached(
        self,
        world_id: str,
        world_line: TimeLine | None,
        players: dict[str, TimeLine],
        now: int,
        days: DayGrid | None,
        pause: PauseLine | None = None,
        morgen: dict[str, int] | None = None,
        *,
        halt: int | None = None,
        frei: frozenset[str] = frozenset(),
    ) -> tuple[bytes, bool]:
        # Pause, tomorrow minutes and halt belong in the key, otherwise the tick
        # never writes them (the halt gets into the rule file at the next push_time).
        # The free set likewise: toggling the adult switch must yield new bytes
        # (T-06-18), even if the lines happen to stay the same.
        key = (
            *self._body_key(world_line, players, days),
            pause,
            None if morgen is None else tuple(sorted(morgen.items())),
            halt,
            tuple(sorted(frei)),
        )
        cached = self._cache.get(world_id)
        if cached is not None and cached.key == key:
            return cached.data, False
        generation = self._store.bump_time_generation(world_id)
        data = render_time_file(generation, now, world_line, players, days=days, pause=pause, morgen=morgen, halt=halt)
        bases = {name: (line.cap, line.base) for name, line in players.items() if line.base >= 0}
        self._cache[world_id] = _Rendered(key=key, generation=generation, issued_at=now, data=data, bases=bases)
        return data, True

    @staticmethod
    def _body_key(
        world_line: TimeLine | None, players: dict[str, TimeLine], days: DayGrid | None
    ) -> tuple[object, ...]:
        world = None if world_line is None else astuple(world_line)
        grid = None if days is None else astuple(days)
        return (world, tuple(sorted((name, astuple(line)) for name, line in players.items())), grid)

    def _maybe_prune(self, now: int, tz: ZoneInfo) -> None:
        if self._last_prune is not None and now - self._last_prune < _PRUNE_INTERVAL_SECONDS:
            return
        self._last_prune = now
        cut = local_day(now, tz) - timedelta(days=_RETENTION_DAYS)
        self._store.prune_usage(cut)
        # Daily data from schema 5 with the same retention (T-04.1-10).
        self._store.prune_play_daily(cut)
        self._store.prune_join_attempts(cut)
        self._store.prune_daily_flags(cut)
        self._store.prune_review_sent(cut)
        # Bot throttle (account and time per world) with the same period (IN-03).
        self._store.prune_bot_presence(int(datetime.combine(cut, dt_time(0), tz).timestamp()))
