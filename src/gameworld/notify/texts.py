"""Elterntexte der Nextcloud-Benachrichtigungen (rein, 04.1-RESEARCH.md Pitfall 4).

AppAPI reicht Betreff und Text durch ``$l->t()``: ein ``%`` oder ``|`` im Text
lässt die Benachrichtigung verschwinden, ein ``{x}`` ohne Parameter scheitert am
Rich-Validator. Darum stehen hier nur feste Texte mit Platzhaltern. Dynamische
Werte (Spielername, Weltname, Anzeigenamen, Uhrzeit) kommen ausschließlich als
Rich-Parameter vom Typ ``highlight``, vorher bereinigt und gekappt (T-04.1-16).
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

ATTEMPT_SUBJECT = "Unbekannter Spielername in {world}"
ATTEMPT_MESSAGE = "{player} wollte um {time} Uhr beitreten."
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


# Texte des Gameworld-Bots im Talk-Raum (TALK-02, D-21 bis D-24). Kurz, deutsch,
# ohne Gründe und ohne Namen der Eltern. Bot-Nachrichten sind kein Rich-Format:
# Platzhalter werden per str.format nur mit bereinigten, escapten Werten gefüllt.
BOT_JOIN = "{name} ist jetzt in der Welt."
BOT_LEAVE = "{name} hat die Welt verlassen."
BOT_START = "Die Welt ist gestartet."
BOT_STOP = "Die Welt ist gestoppt."
BOT_PAUSE = "Pause bis {clock} Uhr."
BOT_SCHLUSS = "Für heute ist Schluss."
BOT_PAUSE_END = "Die Pause ist vorbei."
BOT_WARN10 = "Noch 10 Minuten Spielzeit für {name}."

# Zeichen, die Talk im Chat als Markdown deuten könnte (04.1-RESEARCH.md, Annahme A3).
_MD_SPECIAL = frozenset("\\`*_{}[]()#+-.!|>~<")


def md_escape(value: str) -> str:
    """Maskiert Markdown-Zeichen mit Backslash (T-04.1-31)."""
    return "".join("\\" + char if char in _MD_SPECIAL else char for char in value)


# Talk wertet "@" in Bot-Nachrichten als Erwähnung aus (spreed ChatManager::sendMessage
# ruft notifyMentionedUsers auch für Bots, am Quelltext von Talk 24.0.6 im Dev-Stack
# geprüft). Ein Anzeigename wie "@all" oder '@"papa"' würde sonst alle oder einzelne
# Mitglieder anpingen (WR-07). Das Vollbreiten-@ sieht gleich aus und erwähnt niemanden.
_MENTION = "@"
MENTION_SAFE = chr(0xFF20)


def bot_name(value: str) -> str:
    """Name für den Bot-Text: bereinigt, auf 64 Zeichen gekappt, ohne Erwähnung, dann escaped."""
    return md_escape(clean_value(value, MAX_DISPLAY).replace(_MENTION, MENTION_SAFE))


def bot_clock(epoch: int, tz: ZoneInfo) -> str:
    """Uhrzeit H:MM in der Haushalts-Zeitzone, immer mit Minuten (etwa 19:00)."""
    local = datetime.fromtimestamp(epoch, tz)
    return f"{local.hour}:{local.minute:02d}"
