"""Parent texts of the Nextcloud notifications and the Talk bot (pure, 04.1-RESEARCH.md Pitfall 4).

AppAPI passes subject and message through ``$l->t()``: a ``%`` or ``|`` makes the
notification disappear, a ``{x}`` without a parameter fails the rich validator.
So only fixed texts with placeholders live here. Dynamic values (player name,
world name, display names, time) come only as rich parameters of type
``highlight``, cleaned and capped first (T-04.1-16).

Languages (D-25, D-27): notifications follow the account language of each
recipient (``NOTIFY_TEXTS``, fallback en like any account outside de/en/fr);
bot messages follow the world language (``BOT_TEXTS``, fallback de because the
language comes from the world row and older worlds are German). The German
constants below stay the source and are byte-identical to the texts before 06-23.
"""

from __future__ import annotations

import unicodedata
from datetime import datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo

ATTEMPT_SUBJECT = "Unbekannter Spielername in {world}"
ATTEMPT_MESSAGE = "{player} wollte um {time} beitreten."
SUMMARY_SUBJECT = "Weitere Beitrittsversuche"
SUMMARY_MESSAGE = "Heute gab es weitere Beitrittsversuche, siehe Gameworld."
REVIEW_SUBJECT = "Tagesrückblick"
REVIEW_MESSAGE = "Heute gespielt: {kids}"
REVIEW_LIMIT_SUFFIX = " (Limit erreicht)"
# Sicherung und Wiederherstellen (Phase 5, D-16): nur Fehler, nur an den auslösenden Verwalter.
BACKUP_FAILED_SUBJECT = "Sicherung von {world} fehlgeschlagen"
RESTORE_FAILED_SUBJECT = "Wiederherstellen von {world} fehlgeschlagen"

MAX_PLAYER = 20
# Grund eines fehlgeschlagenen Auftrags (fester Text, trotzdem bereinigt und gekappt).
MAX_REASON = 300
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


class NotifyStrings(NamedTuple):
    """All notification texts of one language (same placeholders as German)."""

    attempt_subject: str
    attempt_message: str
    summary_subject: str
    summary_message: str
    review_subject: str
    review_message: str
    review_limit_suffix: str
    # Minute unit in the daily summary line (review.review_line).
    review_minutes: str
    backup_failed_subject: str
    restore_failed_subject: str


NOTIFY_TEXTS: dict[str, NotifyStrings] = {
    "de": NotifyStrings(
        attempt_subject=ATTEMPT_SUBJECT,
        attempt_message=ATTEMPT_MESSAGE,
        summary_subject=SUMMARY_SUBJECT,
        summary_message=SUMMARY_MESSAGE,
        review_subject=REVIEW_SUBJECT,
        review_message=REVIEW_MESSAGE,
        review_limit_suffix=REVIEW_LIMIT_SUFFIX,
        review_minutes="Min.",
        backup_failed_subject=BACKUP_FAILED_SUBJECT,
        restore_failed_subject=RESTORE_FAILED_SUBJECT,
    ),
    "en": NotifyStrings(
        attempt_subject="Unknown player name in {world}",
        attempt_message="{player} tried to join at {time}.",
        summary_subject="More join attempts",
        summary_message="There were more join attempts today, see Gameworld.",
        review_subject="Daily summary",
        review_message="Played today: {kids}",
        review_limit_suffix=" (limit reached)",
        review_minutes="min",
        backup_failed_subject="Backup of {world} failed",
        restore_failed_subject="Restore of {world} failed",
    ),
    "fr": NotifyStrings(
        attempt_subject="Nom de joueur inconnu dans {world}",
        attempt_message="{player} a voulu se connecter à {time}.",
        summary_subject="Autres tentatives de connexion",
        summary_message="Il y a eu d\u2019autres tentatives de connexion aujourd\u2019hui, voir Gameworld.",
        review_subject="Récap du jour",
        review_message="Joué aujourd\u2019hui\u00a0: {kids}",
        review_limit_suffix=" (limite atteinte)",
        review_minutes="min",
        backup_failed_subject="Échec de la sauvegarde de {world}",
        restore_failed_subject="Échec de la restauration de {world}",
    ),
}
# Account languages outside de/en/fr get English (same fallback as the UI, 06-18).
NOTIFY_FALLBACK = "en"


def notify_strings(language: str) -> NotifyStrings:
    """Notification texts of ``language``; unknown languages give English."""
    return NOTIFY_TEXTS.get(language, NOTIFY_TEXTS[NOTIFY_FALLBACK])


def failed_subject(kind: str, language: str = "de") -> str:
    """Subject of a failed backup (``kind`` "backup") or restore (``kind`` "restore") job."""
    strings = notify_strings(language)
    return strings.restore_failed_subject if kind == "restore" else strings.backup_failed_subject


def attempt_message(world_id: str, world_name: str, player: str, clock: str, *, language: str = "de") -> NotifyText:
    """Single join attempt notice: world, player name and time only as parameters."""
    player_clean = clean_value(player, MAX_PLAYER)
    params = {
        "world": highlight(world_id, clean_value(world_name, MAX_WORLD)),
        "player": highlight(f"player-{player_clean.casefold()}", player_clean),
        "time": highlight("time", clean_value(clock, 5)),
    }
    strings = notify_strings(language)
    return NotifyText(strings.attempt_subject, strings.attempt_message, params)


def job_failed_message(subject: str, world_id: str, world_name: str, reason: str) -> NotifyText:
    """Fehler eines Sicherungs- oder Wiederherstellungsauftrags; Weltname nur als Parameter.

    Der Grund ist ein fester Text des Ablaufs; er wird trotzdem von Format- und
    Steuerzeichen befreit, weil Docker-Meldungen darin vorkommen können.
    """
    params = {"world": highlight(world_id, clean_value(world_name, MAX_WORLD))}
    return NotifyText(subject, clean_value(reason, MAX_REASON), params)


def summary_message(*, language: str = "de") -> NotifyText:
    """Collective notice after the fifth single notice of a day (D-08)."""
    strings = notify_strings(language)
    return NotifyText(strings.summary_subject, strings.summary_message, {})


def review_message(kids_text: str, *, language: str = "de") -> NotifyText:
    """Daily summary; ``kids_text`` is the finished line from review.review_line in the same language."""
    strings = notify_strings(language)
    return NotifyText(
        strings.review_subject,
        strings.review_message,
        {"kids": highlight("kids", clean_value(kids_text, MAX_KIDS_LINE))},
    )


# Texte des Gameworld-Bots im Talk-Raum (TALK-02, D-21 bis D-24). Kurz, deutsch,
# ohne Gründe und ohne Namen der Eltern. Bot-Nachrichten sind kein Rich-Format:
# Platzhalter werden per str.format nur mit bereinigten, escapten Werten gefüllt.
BOT_JOIN = "{name} ist jetzt in der Welt."
BOT_LEAVE = "{name} hat die Welt verlassen."
BOT_START = "Die Welt ist gestartet."
BOT_STOP = "Die Welt ist gestoppt."
BOT_PAUSE = "Pause bis {clock}."
BOT_SCHLUSS = "Für heute ist Schluss."
BOT_PAUSE_END = "Die Pause ist vorbei."
BOT_WARN10 = "Noch 10 Minuten Spielzeit für {name}."


class BotStrings(NamedTuple):
    """All bot texts of one language (same placeholders as German)."""

    join: str
    leave: str
    start: str
    stop: str
    pause: str
    schluss: str
    pause_end: str
    warn10: str


BOT_TEXTS: dict[str, BotStrings] = {
    "de": BotStrings(BOT_JOIN, BOT_LEAVE, BOT_START, BOT_STOP, BOT_PAUSE, BOT_SCHLUSS, BOT_PAUSE_END, BOT_WARN10),
    "en": BotStrings(
        join="{name} is now in the world.",
        leave="{name} has left the world.",
        start="The world has started.",
        stop="The world has stopped.",
        pause="Break until {clock}.",
        schluss="Playtime is over for today.",
        pause_end="The break is over.",
        warn10="10 minutes of playtime left for {name}.",
    ),
    "fr": BotStrings(
        join="{name} est maintenant dans le monde.",
        leave="{name} a quitté le monde.",
        start="Le monde a démarré.",
        stop="Le monde est arrêté.",
        pause="Pause jusqu\u2019à {clock}.",
        schluss="C\u2019est fini pour aujourd\u2019hui.",
        pause_end="La pause est terminée.",
        warn10="Encore 10 minutes de temps de jeu pour {name}.",
    ),
}
# The language comes from the world row; worlds from before schema 9 are German (06-22).
BOT_FALLBACK = "de"


def bot_text(key: str, language: str, **values: str) -> str:
    """Bot text ``key`` (field of BotStrings) in the world language, filled via str.format.

    Values must already be cleaned and escaped (bot_name, bot_clock); unknown
    languages give German.
    """
    strings = BOT_TEXTS.get(language, BOT_TEXTS[BOT_FALLBACK])
    template: str = getattr(strings, key)
    return template.format(**values) if values else template


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
