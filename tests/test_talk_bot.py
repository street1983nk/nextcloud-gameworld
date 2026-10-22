"""Gameworld-Bot (TALK-02): Registrierung, Freischaltung je Raum, Senden, Webhook-Route."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from gameworld.lifecycle import enabled_handler
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.talk import bot as talk_bot
from gameworld.talk.service import TalkService
from gameworld.worlds.store import WorldStore
from tests.conftest import FakeBot, FakeTalkRooms, appapi_headers, assert_closed, install_fake_nc
from tests.test_lifecycle import fake_nc
from tests.test_pause_api import _row

W1 = "bbbbbbbbbbb1"
W2 = "bbbbbbbbbbb2"
SUFFIX = "/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot"
CHAT = "Geheimnis aus dem Kinderchat 4711"


@dataclass
class FakeBotInfo:
    bot_id: int
    url: str


async def _value(value: object) -> object:
    return value


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


# find_bot_id


def test_find_bot_id_matches_url_suffix() -> None:
    bots = [
        FakeBotInfo(3, "https://cloud.example/ocs/v2.php/apps/app_api/api/v1/talk_proxy/andere/talk/bot"),
        FakeBotInfo(7, f"https://cloud.example/ocs/v2.php{SUFFIX}"),
    ]
    assert talk_bot.find_bot_id(bots) == 7


def test_find_bot_id_without_match_is_none() -> None:
    assert talk_bot.find_bot_id([FakeBotInfo(3, "https://x/ocs/v2.php/apps/foo/bot")]) is None
    assert talk_bot.find_bot_id([]) is None


def test_bot_is_async_talk_bot_with_own_name() -> None:
    assert talk_bot.BOT.display_name == "Gameworld"
    assert talk_bot.BOT.callback_url == "talk/bot"
    assert SUFFIX.endswith(talk_bot.BOT.callback_url)
    assert talk_bot.BOT_URL_SUFFIX == SUFFIX


# register


async def test_register_only_with_bots_available(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AsyncMock()
    monkeypatch.setattr(talk_bot.BOT, "enabled_handler", handler)
    nc: Any = MagicMock()
    nc.talk.bots_available = _value(False)
    assert await talk_bot.register(nc) is False
    handler.assert_not_awaited()
    nc.talk.bots_available = _value(True)
    assert await talk_bot.register(nc) is True
    handler.assert_awaited_once_with(True, nc)


async def test_nc_bot_registers_once_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    async def fake_register(nc: object) -> bool:
        calls.append(nc)
        return True

    monkeypatch.setattr(talk_bot, "register", fake_register)
    install_fake_nc(monkeypatch, MagicMock())
    sender = talk_bot.NcBot()
    assert await sender.register() is True
    assert await sender.register() is True
    assert len(calls) == 1


async def test_nc_bot_retries_register_after_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    results = [False, True]

    async def fake_register(nc: object) -> bool:
        del nc
        return results.pop(0)

    monkeypatch.setattr(talk_bot, "register", fake_register)
    install_fake_nc(monkeypatch, MagicMock())
    sender = talk_bot.NcBot()
    assert await sender.register() is False
    assert await sender.register() is True


# ensure_enabled


def _fake_user_nc(monkeypatch: pytest.MonkeyPatch, bots: list[FakeBotInfo]) -> tuple[Any, list[str | None]]:
    nc: Any = MagicMock()
    nc.talk.list_bots = AsyncMock(return_value=bots)
    nc.talk.enable_bot = AsyncMock()
    recorder = install_fake_nc(monkeypatch, nc)
    return nc, recorder.users


async def test_ensure_enabled_closes_client_also_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """WR-05: Suchen und Freischalten in einem Client, der immer geschlossen wird."""
    nc, acting = _fake_user_nc(monkeypatch, [FakeBotInfo(9, f"http://nc/ocs/v2.php{SUFFIX}")])
    nc.talk.enable_bot = AsyncMock(side_effect=RuntimeError("weg"))
    sender = talk_bot.NcBot()
    with pytest.raises(RuntimeError):
        await sender.ensure_enabled("tok1", "admin")
    assert acting == ["admin"]
    assert_closed(nc, times=1)
    nc.talk.list_bots = AsyncMock(return_value=[])
    with pytest.raises(talk_bot.BotMissingError):
        await sender.ensure_enabled("tok1", "admin")
    assert_closed(nc, times=2)


async def test_ensure_enabled_finds_bot_and_enables_once(monkeypatch: pytest.MonkeyPatch) -> None:
    nc, acting = _fake_user_nc(monkeypatch, [FakeBotInfo(9, f"http://nc/ocs/v2.php{SUFFIX}")])
    sender = talk_bot.NcBot()
    await sender.ensure_enabled("tok/1", "admin")
    await sender.ensure_enabled("tok/1", "admin")
    nc.talk.enable_bot.assert_awaited_once_with("tok%2F1", 9)
    nc.talk.list_bots.assert_awaited_once()
    assert acting == ["admin"]


async def test_ensure_enabled_without_registered_bot_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    nc, _acting = _fake_user_nc(monkeypatch, [])
    sender = talk_bot.NcBot()
    with pytest.raises(talk_bot.BotMissingError):
        await sender.ensure_enabled("tok1", "admin")
    nc.talk.enable_bot.assert_not_awaited()


# send


async def test_send_201_is_true_and_text_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    sent: list[tuple[str, object, bool, str]] = []

    async def fake_send(message: str, reply_to: object, silent: bool = False, token: str = "") -> tuple[Any, str]:
        sent.append((message, reply_to, silent, token))
        return FakeResponse(201), "ref"

    monkeypatch.setattr(talk_bot.BOT, "send_message", fake_send)
    caplog.set_level(logging.DEBUG)
    assert await talk_bot.NcBot().send("tok1", "Lena ist jetzt in der Welt.", silent=True) is True
    assert sent == [("Lena ist jetzt in der Welt.", 0, True, "tok1")]
    assert "Lena" not in caplog.text


@pytest.mark.parametrize("status", [401, 404, 429, 500])
async def test_send_failure_status_is_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status: int
) -> None:
    async def fake_send(message: str, reply_to: object, silent: bool = False, token: str = "") -> tuple[Any, str]:
        del message, reply_to, silent, token
        return FakeResponse(status), "ref"

    monkeypatch.setattr(talk_bot.BOT, "send_message", fake_send)
    caplog.set_level(logging.DEBUG)
    assert await talk_bot.NcBot().send("tok1", "Noch 10 Minuten Spielzeit für Lena.", silent=False) is False
    assert "Lena" not in caplog.text


async def test_send_network_error_is_false(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    async def fake_send(message: str, reply_to: object, silent: bool = False, token: str = "") -> tuple[Any, str]:
        del reply_to, silent, token
        raise RuntimeError(message)

    monkeypatch.setattr(talk_bot.BOT, "send_message", fake_send)
    caplog.set_level(logging.DEBUG)
    assert await talk_bot.NcBot().send("tok1", "Lena hat die Welt verlassen.", silent=True) is False
    assert "Lena" not in caplog.text


async def test_send_401_forgets_room_so_it_is_enabled_again(monkeypatch: pytest.MonkeyPatch) -> None:
    nc, _acting = _fake_user_nc(monkeypatch, [FakeBotInfo(9, f"http://nc/ocs/v2.php{SUFFIX}")])

    async def fake_send(message: str, reply_to: object, silent: bool = False, token: str = "") -> tuple[Any, str]:
        del message, reply_to, silent, token
        return FakeResponse(401), "ref"

    monkeypatch.setattr(talk_bot.BOT, "send_message", fake_send)
    sender = talk_bot.NcBot()
    await sender.ensure_enabled("tok1", "admin")
    assert await sender.send("tok1", "Die Welt ist gestartet.", silent=True) is False
    await sender.ensure_enabled("tok1", "admin")
    assert nc.talk.enable_bot.await_count == 2


# TalkService: Freischaltung je Raum


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    return world_store


async def test_ensure_room_enables_bot(store: WorldStore, fake_talk: FakeTalkRooms, fake_bot: FakeBot) -> None:
    await TalkService(store, fake_talk).ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    assert (row.token, "admin") in fake_bot.enabled


async def test_ensure_room_without_bots_does_not_enable(
    store: WorldStore, fake_talk: FakeTalkRooms, fake_bot: FakeBot
) -> None:
    fake_talk.bots = False
    await TalkService(store, fake_talk).ensure_room(W1, "admin")
    assert store.talk_room(W1) is not None
    assert fake_bot.enabled == []


async def test_bot_error_does_not_break_room(store: WorldStore, fake_talk: FakeTalkRooms, fake_bot: FakeBot) -> None:
    fake_bot.error = RuntimeError("kaputt")
    await TalkService(store, fake_talk).ensure_room(W1, "admin")
    assert store.talk_room(W1) is not None


async def test_reconcile_registers_and_enables_every_room(
    store: WorldStore, fake_talk: FakeTalkRooms, fake_bot: FakeBot
) -> None:
    talk = TalkService(store, fake_talk)
    await talk.reconcile_all("admin")
    tokens = {row.token for row in store.list_talk_rooms()}
    assert len(tokens) == 2
    assert fake_bot.registered >= 1
    fake_bot.enabled.clear()
    await talk.reconcile_all("admin")
    assert {token for token, _uid in fake_bot.enabled} == tokens


async def test_reconcile_without_bots_registers_nothing(
    store: WorldStore, fake_talk: FakeTalkRooms, fake_bot: FakeBot
) -> None:
    fake_talk.bots = False
    await TalkService(store, fake_talk).reconcile_all("admin")
    assert fake_bot.registered == 0
    assert fake_bot.enabled == []


# Lifecycle


async def test_enable_with_talk_error_still_succeeds(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken(nc: object) -> bool:
        del nc
        raise RuntimeError("secret-xyz")

    monkeypatch.setattr(talk_bot, "register", broken)
    nc = fake_nc()
    caplog.set_level(logging.DEBUG)
    assert await enabled_handler(True, nc) == ""
    nc.ui.top_menu.register.assert_awaited_once()
    assert "secret-xyz" not in caplog.text
    assert "Talk-Bot" in caplog.text


async def test_enable_registers_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    async def fake_register(nc: object) -> bool:
        calls.append(nc)
        return True

    monkeypatch.setattr(talk_bot, "register", fake_register)
    nc = fake_nc()
    assert await enabled_handler(True, nc) == ""
    assert calls == [nc]


async def test_disable_unregisters_bot_and_ignores_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AsyncMock(side_effect=RuntimeError("kein Talk"))
    monkeypatch.setattr(talk_bot.BOT, "enabled_handler", handler)
    nc = fake_nc()
    assert await enabled_handler(False, nc) == ""
    handler.assert_awaited_once_with(False, nc)
    nc.ui.top_menu.unregister.assert_awaited_once()


# Webhook-Route


async def test_webhook_with_valid_appapi_auth_answers_200_and_logs_nothing(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    body = {"type": "Create", "object": {"name": "message", "content": json.dumps({"message": CHAT})}}
    response = await client.post("/talk/bot", headers=appapi_headers(""), json=body)
    assert response.status_code == 200
    assert response.content == b""
    assert CHAT not in caplog.text
    assert "4711" not in caplog.text


@pytest.mark.parametrize("user", ["gw-kind", "admin", "gw-fremd"])
async def test_webhook_refuses_every_logged_in_account(
    client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture, user: str
) -> None:
    """IN-01: Über den Nutzer-Proxy erreicht jedes Konto die Route; nur AppAPI ohne Nutzer gilt."""
    caplog.set_level(logging.DEBUG)
    response = await client.post("/talk/bot", headers=appapi_headers(user), json={"x": CHAT})
    assert response.status_code == 403
    assert CHAT not in caplog.text


async def test_webhook_without_auth_is_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/talk/bot", json={"x": CHAT})
    assert response.status_code == 401


async def test_webhook_with_wrong_secret_is_401(client: httpx.AsyncClient) -> None:
    headers = appapi_headers("")
    headers["AUTHORIZATION-APP-API"] = "OmZhbHNjaA=="  # ":falsch"
    response = await client.post("/talk/bot", headers=headers, json={"x": CHAT})
    assert response.status_code == 401


async def test_failed_enable_looks_up_bot_id_again(monkeypatch: pytest.MonkeyPatch) -> None:
    nc, _acting = _fake_user_nc(monkeypatch, [FakeBotInfo(9, f"http://nc/ocs/v2.php{SUFFIX}")])
    nc.talk.enable_bot.side_effect = [RuntimeError("404"), None]
    sender = talk_bot.NcBot()
    with pytest.raises(RuntimeError):
        await sender.ensure_enabled("tok1", "admin")
    await sender.ensure_enabled("tok1", "admin")
    assert nc.talk.list_bots.await_count == 2


async def test_register_forgets_enabled_rooms(monkeypatch: pytest.MonkeyPatch) -> None:
    nc_user, _acting = _fake_user_nc(monkeypatch, [FakeBotInfo(9, f"http://nc/ocs/v2.php{SUFFIX}")])
    sender = talk_bot.NcBot()
    monkeypatch.setattr(talk_bot, "_bot", sender)
    monkeypatch.setattr(talk_bot.BOT, "enabled_handler", AsyncMock())
    await sender.ensure_enabled("tok1", "admin")
    app: Any = MagicMock()
    app.talk.bots_available = _value(True)
    assert await talk_bot.register(app) is True
    await sender.ensure_enabled("tok1", "admin")
    assert nc_user.talk.enable_bot.await_count == 2
