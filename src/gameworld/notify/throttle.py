"""Throttling of the foreign-attempt notices (pure, D-08, D-29).

At most one notice per player name, world and local day; in total at most
``limit`` single notices per day, after that exactly one collective message. The counting
itself is atomic in the store (``WorldStore.claim_attempt``), only the rule is here.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

Decision = Literal["single", "summary", "none"]

ATTEMPT_LIMIT = 5


def decide(is_new: bool, notified_today: int, summary_claimed: bool, limit: int) -> Decision:
    """Single notice, collective message or nothing for a foreign attempt."""
    if not is_new:
        return "none"
    if notified_today < limit:
        return "single"
    return "none" if summary_claimed else "summary"


def is_case_variant(name: str, invited_names: Iterable[str]) -> bool:
    """Case variant of an invitee (is never reported, D-29)."""
    folded = name.casefold()
    return any(folded == invited.casefold() for invited in invited_names)
