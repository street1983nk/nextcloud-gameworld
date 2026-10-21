"""Elterntexte der Nextcloud-Benachrichtigungen (rein, 04.1-RESEARCH.md Pitfall 4).

AppAPI reicht Betreff und Text durch ``$l->t()``: ein ``%`` oder ``|`` im Text
lässt die Benachrichtigung verschwinden, ein ``{x}`` ohne Parameter scheitert am
Rich-Validator. Darum stehen hier nur feste Texte mit Platzhaltern. Dynamische
Werte (Spielername, Weltname, Anzeigenamen, Uhrzeit) kommen ausschließlich als
Rich-Parameter vom Typ ``highlight``, vorher bereinigt und gekappt (T-04.1-16).
"""

from __future__ import annotations

import unicodedata
from typing import NamedTuple

ATTEMPT_SUBJECT = "Unbekannter Spielername in {world}"
ATTEMPT_MESSAGE = "{player} wollte um {time} Uhr beitreten. Tippe hier, um nachzusehen."
SUMMARY_SUBJECT = "Weitere Beitrittsversuche"
SUMMARY_MESSAGE = "Heute gab es weitere Beitrittsversuche, siehe Gameworld."
REVIEW_SUBJECT = "Tagesrückblick"
REVIEW_MESSAGE = "Heute gespielt: {kids}"
REVIEW_LIMIT_SUFFIX = " (Limit erreicht)"

MAX_PLAYER = 20
MAX_WORLD = 40
MAX_DISPLAY = 64
# Die Rückblick-Zeile selbst (viele Kinder) bleibt unter dieser Länge.
MAX_KIDS_LINE = 400

_FORMAT_CHARS = frozenset("%|{}")

Params = dict[str, dict[str, str]]


class NotifyText(NamedTuple):
    subject: str
    message: str
    params: Params


def clean_value(value: str, limit: int) -> str:
    """Entfernt Format- und Steuerzeichen, kappt auf ``limit``; leer wird "?"."""
    kept = "".join(
        char for char in value if char not in _FORMAT_CHARS and unicodedata.category(char) not in {"Cc", "Cf"}
    )
    cleaned = kept.strip()[:limit].strip()
    return cleaned or "?"


def highlight(param_id: str, name: str) -> dict[str, str]:
    """Rich-Parameter vom Typ highlight (OCP RichObjectStrings Definitions)."""
    return {"type": "highlight", "id": param_id, "name": name}


def attempt_message(world_id: str, world_name: str, player: str, clock: str) -> NotifyText:
    """Einzelhinweis Fremdversuch: Welt, Spielername und Uhrzeit nur in Parametern."""
    player_clean = clean_value(player, MAX_PLAYER)
    params = {
        "world": highlight(world_id, clean_value(world_name, MAX_WORLD)),
        "player": highlight(f"player-{player_clean.casefold()}", player_clean),
        "time": highlight("time", clean_value(clock, 5)),
    }
    return NotifyText(ATTEMPT_SUBJECT, ATTEMPT_MESSAGE, params)


def summary_message() -> NotifyText:
    """Sammelnachricht nach dem fünften Einzelhinweis eines Tages (D-08)."""
    return NotifyText(SUMMARY_SUBJECT, SUMMARY_MESSAGE, {})


def review_message(kids_text: str) -> NotifyText:
    """Tagesrückblick; ``kids_text`` ist die fertige Zeile aus review.review_line."""
    return NotifyText(
        REVIEW_SUBJECT, REVIEW_MESSAGE, {"kids": highlight("kids", clean_value(kids_text, MAX_KIDS_LINE))}
    )
