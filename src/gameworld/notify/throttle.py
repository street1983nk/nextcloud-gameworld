"""Drosselung der Fremdversuch-Hinweise (rein, D-08, D-29).

Höchstens ein Hinweis je Spielername, Welt und lokalem Tag; insgesamt höchstens
``limit`` Einzelhinweise am Tag, danach genau eine Sammelnachricht. Die Zählung
selbst steht atomar im Store (``WorldStore.claim_attempt``), hier nur die Regel.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

Decision = Literal["single", "summary", "none"]

ATTEMPT_LIMIT = 5


def decide(is_new: bool, notified_today: int, summary_claimed: bool, limit: int) -> Decision:
    """Einzelhinweis, Sammelnachricht oder nichts für einen Fremdversuch."""
    if not is_new:
        return "none"
    if notified_today < limit:
        return "single"
    return "none" if summary_claimed else "summary"


def is_case_variant(name: str, invited_names: Iterable[str]) -> bool:
    """Groß/Klein-Variante eines Eingeladenen (wird nie gemeldet, D-29)."""
    folded = name.casefold()
    return any(folded == invited.casefold() for invited in invited_names)
