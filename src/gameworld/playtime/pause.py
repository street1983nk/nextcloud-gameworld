"""Pause for all worlds of the household (ELTERN-01): time window, tomorrow minutes, state.

Rules (04.1-CONTEXT):

- D-01: A pause applies to all worlds of the household, never to a single world.
- D-02: Duration 15, 30 or 60 minutes, then it ends by itself. "Weiter" ends it
  immediately, "Für heute Schluss" blocks until the start of the next local day.
  The daily quota (``time_usage``) stays unchanged in both cases.
- D-03/D-04: The world mod warns 30 s ahead in chat and then disconnects with the
  pause text; therefore ``ab`` is always 30 s after the trigger.
- D-05: The pause takes effect server-side via the line ``@pause`` of the rule file.
  Disconnected children use up nothing; managers (``frei``) are exempt.
- D-06: Triggering again during a pause keeps ``ab`` and extends ``bis`` at
  most, never shortens it (WR-01); a running "Für heute Schluss" stays.
- D-25: Worlds with an old world mod (without an event file) are restarted
  on trigger so that the pause reliably takes effect (``WorldService.apply_pause_sync``).
- D-29: Time windows keep running during the pause, nothing is extended.

The state lives in SQLite (``pause_state``, exactly one row) and survives
a restart of the ExApp; ``TimeEngine.render`` reads it on every render and
clears an expired pause.

Lock rule (as in playtime/service.py): ``PauseService`` calls no Nextcloud;
all writing runs in a worker thread under ``worlds.mutation()``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import anyio.to_thread

from gameworld.playtime.plan import Holiday, WeekPlan, day_starts, local_day, plan_for

if TYPE_CHECKING:
    from gameworld.worlds.service import WorldService

# Lead time between trigger and disconnect: this long the chat warning applies (D-04).
PAUSE_LEAD_SECONDS = 30
# Allowed durations in minutes (D-02).
PAUSE_MINUTES = (15, 30, 60)
ART_PAUSE = "pause"
ART_SCHLUSS = "schluss"
# Tomorrow is not a play day according to the plan (like time_mod.NO_TOMORROW).
_NO_TOMORROW = -1
# Kinds of the outbox rows per world (sent by the bot in 04.1-06).
OUTBOX_PAUSE_START = "pause_start"
OUTBOX_PAUSE_SCHLUSS = "pause_schluss"
OUTBOX_PAUSE_END = "pause_end"
MSG_BAD_MINUTES = "Eine Pause dauert 15, 30 oder 60 Minuten."


@dataclass(frozen=True)
class PauseState:
    """Pause of the household: who triggered it, disconnect (``ab``), end (``bis``), kind.

    ``started_by`` serves traceability only (T-04.1-15) and never goes to children.
    """

    started_by: str
    ab: int
    bis: int
    art: str


def is_active(state: PauseState | None, now: int) -> bool:
    """Is the pause still in effect? Also during the 30 s lead time; no longer from ``bis``."""
    return state is not None and now < state.bis


def start_window(now: int, minutes: int, current: PauseState | None) -> tuple[int, int]:
    """(ab, bis) of a pause: ab = now + 30 s, bis = ab + duration (D-02, D-04).

    If a pause is already running (``current`` active), its ``ab`` stays (no new
    lead time) and ``bis`` is never shortened (WR-01): a second parent whose
    page does not yet show the running pause can thus neither end it nor move it
    into the past. The new end is the later of the old end and
    now plus duration.
    """
    if minutes not in PAUSE_MINUTES:
        raise ValueError(MSG_BAD_MINUTES)
    if current is not None and is_active(current, now):
        return current.ab, max(current.bis, now + minutes * 60)
    ab = now + PAUSE_LEAD_SECONDS
    return ab, ab + minutes * 60


def schluss_window(now: int, tz: ZoneInfo, current: PauseState | None) -> tuple[int, int]:
    """(ab, bis) for "Für heute Schluss": bis = start of the next local day.

    Without a running pause ab = now + 30 s, otherwise ``ab`` of the running pause stays.
    Shortly before midnight ``ab`` stays before ``bis`` so that the line remains valid.
    """
    bis = day_starts(now, tz)[1]
    ab = current.ab if current is not None and is_active(current, now) else now + PAUSE_LEAD_SECONDS
    return min(ab, bis - 1), bis


def morgen_minutes(
    now: int,
    tz: ZoneInfo,
    plans: Mapping[str, tuple[WeekPlan, WeekPlan | None]],
    holidays: list[Holiday],
    names_by_user: Mapping[str, str],
) -> dict[str, int]:
    """Player name to the start minute of the next local day (line ``@morgen``).

    -1: tomorrow is not a play day according to the plan; 0: whole day without a start time;
    otherwise the window start. Holidays tomorrow use the holiday plan. Accounts without a plan are
    missing (the mod then takes the base text).
    """
    tomorrow = local_day(now, tz) + timedelta(days=1)
    result: dict[str, int] = {}
    for nc_user, name in names_by_user.items():
        if nc_user not in plans:
            continue
        normal, holiday = plans[nc_user]
        rule = plan_for(tomorrow, normal, holiday, holidays).days[tomorrow.isoweekday()]
        if not rule.allowed:
            result[name] = _NO_TOMORROW
        else:
            result[name] = 0 if rule.window_start is None else rule.window_start
    return result


def clock_text(epoch: int, tz: ZoneInfo) -> str:
    """Time H:MM in the household time zone (for page and bot, never for child texts)."""
    local = datetime.fromtimestamp(epoch, tz)
    return f"{local.hour}:{local.minute:02d}"


@dataclass(frozen=True)
class PauseWorldResult:
    """Result per world: rule file arrived (``applied``) and whether it was restarted (D-25)."""

    world_id: str
    name: str
    applied: bool
    restarted: bool


@dataclass(frozen=True)
class PauseResult:
    """New state (None = no pause) and the result per world."""

    state: PauseState | None
    worlds: list[PauseWorldResult]


# Decides the new state under the lock from (running pause or None, now).
PauseDecision = Callable[[PauseState | None, int], PauseState | None]


class PauseService:
    """Start, end, end for today and read the pause (manager API)."""

    def __init__(self, worlds: WorldService) -> None:
        self._worlds = worlds

    def zone(self) -> ZoneInfo:
        """Household time zone for the time of the end (page and bot)."""
        return self._worlds.time.zone()

    async def get(self) -> PauseResult:
        """Current pause or None; an expired pause no longer counts."""
        return await anyio.to_thread.run_sync(self._get_sync)

    async def start(self, acting_uid: str, minutes: int) -> PauseResult:
        """Start or extend a pause; a running "Für heute Schluss" stays unchanged (WR-01)."""
        if minutes not in PAUSE_MINUTES:
            raise ValueError(MSG_BAD_MINUTES)

        def decide(current: PauseState | None, now: int) -> PauseState:
            if current is not None and current.art == ART_SCHLUSS:
                # Never downgrade: the parents' decision "Schluss" applies until tomorrow.
                return current
            ab, bis = start_window(now, minutes, current)
            return PauseState(started_by=acting_uid, ab=ab, bis=bis, art=ART_PAUSE)

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_START)

    async def schluss(self, acting_uid: str) -> PauseResult:
        zone = self._worlds.time.zone()

        def decide(current: PauseState | None, now: int) -> PauseState:
            ab, bis = schluss_window(now, zone, current)
            return PauseState(started_by=acting_uid, ab=ab, bis=bis, art=ART_SCHLUSS)

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_SCHLUSS)

    async def end(self, acting_uid: str) -> PauseResult:
        """End the pause immediately; without a running pause nothing changes (idempotent)."""
        del acting_uid  # Who ends it is not stored (there is no state afterwards).

        def decide(current: PauseState | None, now: int) -> None:
            del current, now

        return await anyio.to_thread.run_sync(self._worlds.apply_pause_sync, decide, OUTBOX_PAUSE_END)

    def _get_sync(self) -> PauseResult:
        state = self._worlds.store.get_pause()
        if not is_active(state, self._worlds.time.now()):
            state = None
        return PauseResult(state=state, worlds=[])
