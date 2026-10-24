"""Notifications in the recipient's account language, bot texts in the world language (06-23, D-25, D-27)."""

from __future__ import annotations

import json
import re
import string
from datetime import date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from gameworld.backup.files import MSG_QUOTA
from gameworld.backup.service import BackupService
from gameworld.config import load_settings
from gameworld.notify import texts
from gameworld.notify.loop import META_LINK_ORIGIN, run_once
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
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.talk import bot as talk_bot
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import FAKE_LANGUAGES, FakeBot, FakeDirectory, FakeNotifier, FakeTalkRooms, give_rules
from tests.test_pause_api import VERIFIER, _row
from tests.test_service_lifecycle import FakeProvisioner

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


# Task 2: delivery per recipient language, bot per world language, failed backups


W1 = "ddddddddddd1"
ROOM = "room-lang"
BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 21)
STARTED = "2026-10-21T10:00:00+00:00"


def _epoch(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 21, hour, minute, tzinfo=BERLIN).timestamp())


@pytest.fixture
def store(app_env: Path, fake_directory: FakeDirectory) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    give_rules(world_store, "gw-kind")
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "en-verwalter"]))
    world_store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    world_store.insert_talk_room(W1, ROOM, "admin", STARTED)
    fake_directory.users["gw-kind"] = ("Lena", True)
    return world_store


@pytest.fixture
def service(store: WorldStore) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())


@pytest.fixture
def languages(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setitem(FAKE_LANGUAGES, "en-verwalter", "en")
    monkeypatch.setitem(FAKE_LANGUAGES, "fr-verwalter", "fr")
    return FAKE_LANGUAGES


Sent = dict[str, tuple[str, str, dict[str, dict[str, str]]]]


def _by_uid(notifier: FakeNotifier) -> Sent:
    return {uid: (subject, message, params) for uid, subject, message, params, _link in notifier.calls}


async def test_join_attempt_in_each_recipients_language(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    languages: dict[str, str],
) -> None:
    del languages
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 6))
    sent = _by_uid(fake_notifier)
    assert sent["admin"][:2] == ("Unbekannter Spielername in {world}", "{player} wollte um {time} beitreten.")
    assert sent["en-verwalter"][:2] == ("Unknown player name in {world}", "{player} tried to join at {time}.")
    assert sent["admin"][2] == sent["en-verwalter"][2]
    assert sent["admin"][2]["time"]["name"] == "18:05"


async def test_summary_in_each_recipients_language(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    languages: dict[str, str],
) -> None:
    del languages
    for index in range(6):
        store.add_outbox(W1, "deny", f"Fremder{index}", _epoch(18, index))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 10))
    subjects = {(uid, subject) for uid, subject, _message, _params, _link in fake_notifier.calls}
    assert ("admin", "Weitere Beitrittsversuche") in subjects
    assert ("en-verwalter", "More join attempts") in subjects


async def test_daily_summary_in_each_recipients_language(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    languages: dict[str, str],
) -> None:
    del languages
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 2700})
    await run_once(service, fake_notifier, fake_directory, _epoch(20, 0))
    sent = _by_uid(fake_notifier)
    assert sent["admin"][:2] == ("Tagesrückblick", "Heute gespielt: {kids}")
    assert sent["admin"][2]["kids"]["name"] == "Lena 45 Min."
    assert sent["en-verwalter"][:2] == ("Daily summary", "Played today: {kids}")
    assert sent["en-verwalter"][2]["kids"]["name"] == "Lena 45 min"


async def test_language_lookup_failure_still_notifies(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    role_lookup_error: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The lookup fails: the notice still goes out in the fallback language, no exception, no UID in logs."""
    caplog.set_level("DEBUG")
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert role_lookup_error  # the lookup was really asked (positive control)
    assert {call[0] for call in fake_notifier.calls} == {"admin", "en-verwalter"}
    assert {call[1] for call in fake_notifier.calls} == {"Unknown player name in {world}"}
    assert store.outbox_batch() == []
    assert "en-verwalter" not in caplog.text
    assert "Fremder" not in caplog.text
    assert "Unknown player" not in caplog.text


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("en", ["Lena is now in the world.", "The world has started.", "Break until 19:00."]),
        ("fr", ["Lena est maintenant dans le monde.", "Le monde a démarré.", f"Pause jusqu{RIGHT_QUOTE}à 19:00."]),
        ("de", ["Lena ist jetzt in der Welt.", "Die Welt ist gestartet.", "Pause bis 19:00."]),
        ("xx", ["Lena ist jetzt in der Welt.", "Die Welt ist gestartet.", "Pause bis 19:00."]),
    ],
)
async def test_bot_follows_world_language(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
    language: str,
    expected: list[str],
) -> None:
    del fake_talk
    store.update_world(W1, language=language)
    store.add_outbox(W1, "join", "Lena", _epoch(18, 0))
    store.add_outbox(W1, "start", "", _epoch(18, 0))
    store.add_outbox(W1, "pause_start", "", _epoch(18, 0), str(_epoch(19, 0)))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 0))
    assert [text for _room, text, _silent in fake_bot.sent] == expected


async def test_bot_all_texts_in_english_world(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    del fake_talk
    store.update_world(W1, language="en")
    store.add_outbox(W1, "warn10", "Lena", _epoch(17, 0))
    store.add_outbox(W1, "stop", "", _epoch(17, 1))
    store.add_outbox(W1, "pause_schluss", "", _epoch(17, 2))
    store.add_outbox(W1, "pause_end", "", _epoch(17, 3))
    store.add_outbox(W1, "leave", "Lena", _epoch(17, 4))
    await run_once(service, fake_notifier, fake_directory, _epoch(17, 5))
    assert fake_bot.sent == [
        (ROOM, "10 minutes of playtime left for Lena.", False),
        (ROOM, "The world has stopped.", True),
        (ROOM, "Playtime is over for today.", False),
        (ROOM, "The break is over.", True),
        (ROOM, "Lena has left the world.", True),
    ]


async def test_bot_in_french_world_never_mentions(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    del fake_talk
    store.update_world(W1, language="fr")
    fake_directory.users["gw-kind"] = ("@all", True)
    store.add_outbox(W1, "join", "Lena", _epoch(18, 0))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 0))
    assert fake_bot.sent == [(ROOM, f"{texts.MENTION_SAFE}all est maintenant dans le monde.", True)]


# Failed backup or restore notice to the triggering manager


@pytest.fixture
def backup(service: WorldService, app_env: Path) -> BackupService:
    async def no_sleep(seconds: float) -> None:
        del seconds

    return BackupService(service, app_env / "tmp", clock=lambda: 1_792_756_800.0, sleep=no_sleep)


async def _fail(backup: BackupService, uid: str, kind: str, message: str) -> None:
    await backup._finish_failed(W1, uid, kind, message, STARTED)  # pyright: ignore[reportPrivateUsage]


async def test_failed_backup_in_recipients_language(
    backup: BackupService, fake_notifier: FakeNotifier, languages: dict[str, str]
) -> None:
    del languages
    await _fail(backup, "fr-verwalter", "backup", MSG_QUOTA)
    await _fail(backup, "admin", "restore", MSG_QUOTA)
    sent = _by_uid(fake_notifier)
    assert sent["fr-verwalter"][:2] == (
        "Échec de la sauvegarde de {world}",
        f"Pas assez d{RIGHT_QUOTE}espace de stockage dans tes fichiers Nextcloud.",
    )
    assert sent["fr-verwalter"][2] == {"world": {"type": "highlight", "id": W1, "name": "Wiese"}}
    assert sent["admin"][:2] == ("Wiederherstellen von {world} fehlgeschlagen", MSG_QUOTA)


async def test_failed_backup_keeps_untranslated_docker_detail(
    backup: BackupService, fake_notifier: FakeNotifier, languages: dict[str, str]
) -> None:
    """A reason outside the catalog stays as it is, still cleaned of format characters."""
    del languages
    await _fail(backup, "en-verwalter", "backup", "docker: 100% kaputt | x")
    _uid, subject, message, _params, _link = fake_notifier.calls[0]
    assert subject == "Backup of {world} failed"
    assert message == "docker: 100 kaputt  x"
