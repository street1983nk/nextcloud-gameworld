"""Booking of the counter ledger (pure), 04-RESEARCH.md pattern 5 and code example.

Each world writes its own monotonic counter ledger (seconds per player name).
``increments`` compares the current state with the last one seen and returns
only the real increase per name, plus the new state seen.

Two cases only re-anchor, without an increase (protection against double or
negative counting, pitfall 7 and T-04-10):

- First contact: a name that appears for the first time may already have been
  played before the first ExApp look. Anchoring only is the safe choice against
  double counting; at most the time before the first look is lost.
- Rollback: a restore or a new volume brings a smaller ledger. It is
  re-anchored, never booked as negative.

Names are matched case-insensitively like ``players.player_name``
(COLLATE NOCASE); the increase carries the name from the current ledger.
``attribution_day`` assigns an increase to the local day of the ledger head
(time of writing), not of reading.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from gameworld.playtime.plan import local_day


def increments(seen: dict[str, int], current: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """(Increase per name, new state seen). Rollback and first contact only anchor."""
    seen_by_fold = {name.casefold(): value for name, value in seen.items()}
    delta: dict[str, int] = {}
    for name, value in current.items():
        before = seen_by_fold.get(name.casefold())
        if before is not None and value > before:
            delta[name] = value - before
    return delta, dict(current)


def attribution_day(written_at: int, tz: ZoneInfo) -> date:
    """Local calendar day of the ledger head (time of writing, not of reading)."""
    return local_day(written_at, tz)
