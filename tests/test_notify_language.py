"""Notifications in the recipient's account language, bot texts in the world language (06-23, D-25, D-27)."""

from __future__ import annotations

import re
import string

import pytest

from gameworld.notify import texts
from gameworld.notify.review import review_line
from gameworld.notify.texts import (
    BOT_TEXTS,
    NOTIFY_TEXTS,
    attempt_message,
    bot_name,
    bot_text,
    failed_subject,
    job_failed_message,
    review_message,
    summary_message,
)
from gameworld.talk import bot as talk_bot

LANGUAGES = ("de", "en", "fr")
NBSP = chr(0xA0)
RIGHT_QUOTE = chr(0x2019)
_FORMATTER = string.Formatter()
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|und|welt|ist|nicht)\b", re.IGNORECASE)


def _placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in _FORMATTER.parse(template) if name}


def _all_texts(language: str) -> list[str]:
    return [*NOTIFY_TEXTS[language], *BOT_TEXTS[language]]


# Text tables


def test_tables_cover_all_languages() -> None:
    assert set(NOTIFY_TEXTS) == set(LANGUAGES)
    assert set(BOT_TEXTS) == set(LANGUAGES)


def test_german_is_unchanged_source() -> None:
    de = NOTIFY_TEXTS["de"]
    assert de.attempt_subject == "Unbekannter Spielername in {world}"
    assert de.attempt_message == "{player} wollte um {time} beitreten."
    assert de.summary_subject == "Weitere Beitrittsversuche"
    assert de.summary_message == "Heute gab es weitere Beitrittsversuche, siehe Gameworld."
    assert de.review_subject == "Tagesrückblick"
    assert de.review_message == "Heute gespielt: {kids}"
    assert de.review_limit_suffix == " (Limit erreicht)"
    assert de.backup_failed_subject == "Sicherung von {world} fehlgeschlagen"
    assert de.restore_failed_subject == "Wiederherstellen von {world} fehlgeschlagen"
    assert BOT_TEXTS["de"].join == "{name} ist jetzt in der Welt."
    assert BOT_TEXTS["de"].warn10 == "Noch 10 Minuten Spielzeit für {name}."


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_percent_or_pipe_and_same_placeholders(language: str) -> None:
    """04.1 Pitfall 4: % or | makes the notification disappear; placeholders match German (T-06-89)."""
    for value, german in zip(_all_texts(language), _all_texts("de"), strict=True):
        assert "%" not in value, value
        assert "|" not in value, value
        assert _placeholders(value) == _placeholders(german), value
        assert chr(0x2013) not in value
        assert chr(0x2014) not in value
        # Only Latin text plus the French non-breaking space and apostrophe, no emojis.
        assert all(ord(char) < 0x2000 or char == RIGHT_QUOTE for char in value), value


def test_text_rule_check_positive_control() -> None:
    assert "%" in "50 % gespielt"
    assert _placeholders("{a} und {b}") != _placeholders("{a}")


def test_english_has_no_german_features() -> None:
    assert GERMAN.search(NOTIFY_TEXTS["de"].review_subject)  # positive control
    for value in _all_texts("en"):
        assert not GERMAN.search(value), value


def test_french_typography() -> None:
    plain_space = re.compile(r" [?!;:]")
    missing = re.compile(rf"[^\s{NBSP}\d}}/]([?!;:])(\s|$)")
    assert missing.search("Joué: x")  # positive control
    for value in _all_texts("fr"):
        assert not plain_space.search(value), value
        assert not missing.search(value), value
        assert "'" not in value, value
    assert NOTIFY_TEXTS["fr"].review_message == f"Joué aujourd{RIGHT_QUOTE}hui{NBSP}: {{kids}}"
    source = texts.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        content = handle.read()
    assert NBSP not in content, "write the escape, not the character"
    assert RIGHT_QUOTE not in content, "write the escape, not the character"


# Builders


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_placeholder_has_a_parameter(language: str) -> None:
    built = [
        attempt_message("w1", "Wiese", "Fremder", "18:05", language=language),
        summary_message(language=language),
        review_message("Lena 45 min", language=language),
        job_failed_message(failed_subject("backup", language), "w1", "Wiese", "Grund"),
        job_failed_message(failed_subject("restore", language), "w1", "Wiese", "Grund"),
    ]
    for text in built:
        assert _placeholders(text.subject) | _placeholders(text.message) <= set(text.params), text


def test_builders_default_to_german() -> None:
    assert attempt_message("w1", "Wiese", "Fremder", "18:05") == attempt_message(
        "w1", "Wiese", "Fremder", "18:05", language="de"
    )
    assert summary_message().subject == "Weitere Beitrittsversuche"
    assert review_message("x").subject == "Tagesrückblick"
    assert failed_subject("backup") == texts.BACKUP_FAILED_SUBJECT
    assert failed_subject("restore") == texts.RESTORE_FAILED_SUBJECT


def test_english_attempt_keeps_the_parameters() -> None:
    german = attempt_message("w1", "Wiese", "Fremder", "18:05", language="de")
    english = attempt_message("w1", "Wiese", "Fremder", "18:05", language="en")
    assert english.subject == "Unknown player name in {world}"
    assert english.message == "{player} tried to join at {time}."
    assert english.params == german.params


def test_french_subjects() -> None:
    assert review_message("x", language="fr").subject == "Récap du jour"
    assert summary_message(language="fr").subject == "Autres tentatives de connexion"
    assert failed_subject("backup", "fr") == "Échec de la sauvegarde de {world}"


def test_unsupported_account_language_gets_english() -> None:
    assert attempt_message("w1", "W", "P", "1:00", language="xx").subject == "Unknown player name in {world}"
    assert review_message("x", language="").subject == "Daily summary"
    assert failed_subject("restore", "es") == "Restore of {world} failed"


# Daily summary line


def test_review_line_per_language() -> None:
    entries = [("Tom", 3600, True), ("Lena", 2700, False)]
    assert review_line(entries) == "Lena 45 Min., Tom 60 Min. (Limit erreicht)"
    assert review_line(entries, language="de") == "Lena 45 Min., Tom 60 Min. (Limit erreicht)"
    assert review_line(entries, language="en") == "Lena 45 min, Tom 60 min (limit reached)"
    assert review_line(entries, language="fr") == "Lena 45 min, Tom 60 min (limite atteinte)"
    assert review_line([("Lena", 0, False)], language="fr") is None


# Bot texts


def test_bot_text_per_world_language() -> None:
    name = bot_name("Lena")
    assert bot_text("join", "de", name=name) == "Lena ist jetzt in der Welt."
    assert bot_text("join", "en", name=name) == "Lena is now in the world."
    assert bot_text("join", "fr", name=name) == "Lena est maintenant dans le monde."
    assert bot_text("pause", "en", clock="19:00") == "Break until 19:00."
    assert bot_text("pause", "fr", clock="19:00") == f"Pause jusqu{RIGHT_QUOTE}à 19:00."
    assert bot_text("start", "en") == "The world has started."


def test_bot_text_unknown_world_language_is_german() -> None:
    assert bot_text("stop", "xx") == "Die Welt ist gestoppt."
    assert bot_text("warn10", "", name="Tom") == "Noch 10 Minuten Spielzeit für Tom."


@pytest.mark.parametrize("language", LANGUAGES)
def test_bot_text_never_mentions(language: str) -> None:
    """T-06-91: bot_name runs before every language, so "@all" pings nobody."""
    for key in ("join", "leave", "warn10"):
        sent = bot_text(key, language, name=bot_name("@all"))
        assert "@" not in sent, sent
        assert texts.MENTION_SAFE in sent
    assert "\\*" in bot_text("join", language, name=bot_name("*fett*"))


# Talk bot description (registered once for all accounts, so English)


def _looks_german(value: str) -> bool:
    return bool(re.search(r"[äöüÄÖÜß]|\b(der|die|das|und|welt|welten)\b", value, re.IGNORECASE))


def test_bot_description_is_english() -> None:
    assert talk_bot.BOT.description == "Reports events from Gameworld worlds"
    assert not _looks_german(talk_bot.BOT.description)
    assert talk_bot.BOT.display_name == "Gameworld"
    assert talk_bot.BOT.callback_url == "talk/bot"


def test_bot_description_check_positive_control() -> None:
    assert _looks_german("Meldet Ereignisse der Gameworld-Welten")
