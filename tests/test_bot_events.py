"""Bot-Meldungen aus der Outbox (TALK-02): Texte, still oder mit Ton, Drossel, Anzeigenamen."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest

from gameworld.config import load_settings
from gameworld.notify import texts
from gameworld.notify.loop import META_LINK_ORIGIN, run_once
from gameworld.notify.texts import bot_clock, md_escape
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import FakeBot, FakeDirectory, FakeNotifier, FakeTalkRooms
from tests.test_pause_api import VERIFIER, _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "ccccccccccc1"
W2 = "ccccccccccc2"
BERLIN = ZoneInfo("Europe/Berlin")
ROOM = "room-w1"


def _epoch(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 21, hour, minute, tzinfo=BERLIN).timestamp())


@pytest.fixture
def store(app_env: Path, fake_directory: FakeDirectory) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.insert_player(PlayerRow(nc_user="lena", player_name="lena", rotation=0))
    world_store.insert_player(PlayerRow(nc_user="tom", player_name="tom_k-2", rotation=0))
    world_store.apply_world_access(W1, {"lena": VERIFIER, "tom": VERIFIER})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    world_store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    world_store.insert_talk_room(W1, ROOM, "admin", "2026-10-21T10:00:00+00:00")
    fake_directory.users["lena"] = ("Lena", True)
    return world_store


@pytest.fixture
def service(store: WorldStore) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())


async def _run(
    service: WorldService, notifier: FakeNotifier, directory: FakeDirectory, now: int, fake_talk: FakeTalkRooms
) -> None:
    del fake_talk
    await run_once(service, notifier, directory, now)


# Reine Bausteine


def test_md_escape_masks_markdown() -> None:
    assert md_escape("lena_k-2") == "lena\\_k\\-2"
    assert md_escape("*fett* [x](y)") == "\\*fett\\* \\[x\\]\\(y\\)"
    assert md_escape("Lena") == "Lena"


def test_bot_clock_always_with_minutes() -> None:
    assert bot_clock(_epoch(18, 30), BERLIN) == "18:30"
    assert bot_clock(_epoch(19, 0), BERLIN) == "19:00"
    assert bot_clock(_epoch(9, 5), BERLIN) == "9:05"


def test_bot_texts_follow_text_rules() -> None:
    constants = [value for name, value in vars(texts).items() if name.startswith("BOT_") and isinstance(value, str)]
    assert len(constants) >= 8
    for value in constants:
        assert chr(0x2013) not in value
        assert chr(0x2014) not in value
        assert "Mitternacht" not in value
        assert not re.search(r"(?<![\d:])0 Uhr", value)
        assert all(ord(char) < 0x2000 for char in value), value
    assert texts.BOT_WARN10 == "Noch 10 Minuten Spielzeit für {name}."


# Beitritt, Verlassen, Drossel


async def test_join_uses_display_name_and_is_silent(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert fake_bot.sent == [(ROOM, "Lena ist jetzt in der Welt.", True)]
    assert store.outbox_batch() == []


async def test_presence_throttled_for_ten_minutes(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    store.add_outbox(W1, "leave", "lena", _epoch(17, 3))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 3), fake_talk)
    assert len(fake_bot.sent) == 1
    store.add_outbox(W1, "join", "Lena", _epoch(17, 11))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 11), fake_talk)
    assert len(fake_bot.sent) == 2
    store.add_outbox(W1, "leave", "lena", _epoch(17, 30))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 30), fake_talk)
    assert fake_bot.sent[-1] == (ROOM, "Lena hat die Welt verlassen.", True)


async def test_failed_send_does_not_update_throttle(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    fake_bot.result = False
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    fake_bot.result = True
    store.add_outbox(W1, "join", "lena", _epoch(17, 1))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 1), fake_talk)
    assert len(fake_bot.sent) == 2


async def test_throttle_is_per_world(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.insert_talk_room(W2, "room-w2", "admin", "2026-10-21T10:00:00+00:00")
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    store.add_outbox(W2, "join", "lena", _epoch(17, 1))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 1), fake_talk)
    assert [token for token, _text, _silent in fake_bot.sent] == [ROOM, "room-w2"]


async def test_name_without_display_name_falls_back_to_escaped_player_name(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W1, "join", "tom_k-2", _epoch(17, 0))
    store.add_outbox(W1, "join", "fremd_1", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert [text for _token, text, _silent in fake_bot.sent] == [
        "tom\\_k\\-2 ist jetzt in der Welt.",
        "fremd\\_1 ist jetzt in der Welt.",
    ]


async def test_display_name_markdown_is_escaped_and_capped(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    fake_directory.users["lena"] = ("**Lena** [x](https://boese.example)" + "a" * 100, True)
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    (_token, text, silent), *_ = fake_bot.sent
    assert silent is False
    assert text.startswith("Noch 10 Minuten Spielzeit für \\*\\*Lena\\*\\* \\[x\\]\\(https://boese\\.example\\)")
    assert "](" not in text


# Spielzeit, Welt, Pause


async def test_warn10_has_sound(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert fake_bot.sent == [(ROOM, "Noch 10 Minuten Spielzeit für Lena.", False)]


@pytest.mark.parametrize("display", ["@all", '@"papa"', "Lena @admin", "@@here"])
def test_bot_name_never_mentions(display: str) -> None:
    """WR-07: Kein echtes @ im Bot-Text, damit ein Anzeigename niemanden anpingt."""
    name = texts.bot_name(display)
    assert "@" not in name
    assert texts.MENTION_SAFE in name


async def test_join_with_mention_display_name_pings_nobody(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    """Negativtest: Ein Kind setzt den Anzeigenamen "@all" und tritt bei, mit Ton (warn10) und still (join)."""
    fake_directory.users["lena"] = ("@all", True)
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert [text for _token, text, _silent in fake_bot.sent] == [
        f"{texts.MENTION_SAFE}all ist jetzt in der Welt.",
        f"Noch 10 Minuten Spielzeit für {texts.MENTION_SAFE}all.",
    ]
    assert all("@" not in text for _token, text, _silent in fake_bot.sent)


async def test_warn10_flood_by_rejoining_rings_once_per_day(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    """WR-02: Neuverbinden alle paar Sekunden erzeugt je Beitritt ein warn10, gesendet wird einmal."""
    for second in range(0, 60, 3):
        store.add_outbox(W1, "warn10", "lena", _epoch(17, 0) + second)
    store.add_outbox(W1, "warn10", "LENA", _epoch(17, 1))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 1), fake_talk)
    assert fake_bot.sent == [(ROOM, "Noch 10 Minuten Spielzeit für Lena.", False)]
    # Auch nach einem Neustart der ExApp (frischer Dienst, gleiche Datenbank) nicht erneut.
    restarted = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    store.add_outbox(W1, "warn10", "lena", _epoch(19, 0))
    await _run(restarted, fake_notifier, fake_directory, _epoch(19, 0), fake_talk)
    assert len(fake_bot.sent) == 1


async def test_warn10_separate_per_person_world_and_day(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    """Positivkontrolle: Andere Person, andere Welt und der nächste Tag bekommen je einen Hinweis."""
    store.apply_world_access(W2, {"lena": VERIFIER})
    store.insert_talk_room(W2, "room-w2", "admin", "2026-10-21T10:00:00+00:00")
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0))
    store.add_outbox(W1, "warn10", "tom_k-2", _epoch(17, 0))
    store.add_outbox(W2, "warn10", "lena", _epoch(17, 0))
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0) + 86400)
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert [(token, text.split(" für ")[1]) for token, text, _silent in fake_bot.sent] == [
        (ROOM, "Lena."),
        (ROOM, "tom\\_k\\-2."),
        ("room-w2", "Lena."),
        (ROOM, "Lena."),
    ]


@pytest.mark.parametrize(
    ("kind", "detail", "text", "silent"),
    [
        ("start", "", "Die Welt ist gestartet.", True),
        ("stop", "", "Die Welt ist gestoppt.", True),
        ("pause_start", str(_epoch(18, 30)), "Pause bis 18:30 Uhr.", False),
        ("pause_start", str(_epoch(19, 0)), "Pause bis 19:00 Uhr.", False),
        ("pause_schluss", "", "Für heute ist Schluss.", False),
        ("pause_end", "", "Die Pause ist vorbei.", True),
    ],
)
async def test_world_and_pause_texts(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
    kind: str,
    detail: str,
    text: str,
    silent: bool,
) -> None:
    store.add_outbox(W1, kind, "", _epoch(18, 0), detail)
    await _run(service, fake_notifier, fake_directory, _epoch(18, 0), fake_talk)
    assert fake_bot.sent == [(ROOM, text, silent)]


async def test_pause_start_with_broken_detail_sends_nothing(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W1, "pause_start", "", _epoch(18, 0), "kaputt")
    await _run(service, fake_notifier, fake_directory, _epoch(18, 0), fake_talk)
    assert fake_bot.sent == []
    assert store.outbox_batch() == []


# Ohne Raum, ohne Talk


async def test_world_without_room_sends_nothing_and_row_is_removed(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.add_outbox(W2, "start", "", _epoch(18, 0))
    store.add_outbox(W2, "join", "lena", _epoch(18, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 0), fake_talk)
    assert fake_bot.sent == []
    assert store.outbox_batch() == []


@pytest.mark.parametrize("missing", ["talk", "bots"])
async def test_without_talk_or_bots_sends_nothing(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
    missing: str,
) -> None:
    setattr(fake_talk, missing, False)
    store.add_outbox(W1, "start", "", _epoch(18, 0))
    store.add_outbox(W1, "warn10", "lena", _epoch(18, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 0), fake_talk)
    assert fake_bot.sent == []
    assert store.outbox_batch() == []


async def test_pending_delete_room_sends_nothing(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
) -> None:
    store.set_talk_state(W1, "delete_pending")
    store.add_outbox(W1, "stop", "", _epoch(18, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 0), fake_talk)
    assert fake_bot.sent == []


async def test_bot_events_log_no_names(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    fake_talk: FakeTalkRooms,
    fake_bot: FakeBot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG")
    fake_bot.result = False
    store.add_outbox(W1, "join", "lena", _epoch(17, 0))
    store.add_outbox(W1, "warn10", "lena", _epoch(17, 0))
    await _run(service, fake_notifier, fake_directory, _epoch(17, 0), fake_talk)
    assert "Lena" not in caplog.text
    assert "lena" not in caplog.text
