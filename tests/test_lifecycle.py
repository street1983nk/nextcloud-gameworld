"""Lifecycle der ExApp: Top-Menü, Skript und Initial State beim Aktivieren und Deaktivieren."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gameworld import lifecycle
from gameworld.lifecycle import api_base, enabled_handler


class Ready:
    """Mehrfach awaitbarer Wert (wie die awaitbaren Properties von nc_py_api)."""

    def __init__(self, value: object) -> None:
        self.value = value

    def __await__(self) -> Generator[None, None, object]:
        yield from ()
        return self.value


def fake_nc() -> Any:
    nc = MagicMock()
    # Ohne Talk-Bots: der Bot wird nicht registriert (04.1-06).
    nc.talk.bots_available = Ready(False)
    nc.ui.resources.set_initial_state = AsyncMock()
    nc.ui.resources.set_script = AsyncMock()
    nc.ui.resources.delete_script = AsyncMock()
    nc.ui.top_menu.register = AsyncMock()
    nc.ui.top_menu.unregister = AsyncMock()
    return nc


class FakeWorlds:
    """Steht für WorldService: zählt teardown und boot_reconcile, wirft auf Wunsch."""

    def __init__(self) -> None:
        self.teardowns = 0
        self.boots = 0
        self.teardown_error: BaseException | None = None
        self.teardown_result = 0
        self.boot_error: BaseException | None = None

    async def teardown(self) -> int:
        self.teardowns += 1
        if self.teardown_error is not None:
            raise self.teardown_error
        return self.teardown_result

    async def boot_reconcile(self) -> bool:
        self.boots += 1
        if self.boot_error is not None:
            raise self.boot_error
        return True


@pytest.fixture(autouse=True)
def worlds(monkeypatch: pytest.MonkeyPatch) -> FakeWorlds:
    """Nie den echten Dienst: Der würde Docker ansprechen (Live-Umgebung)."""
    fake = FakeWorlds()
    monkeypatch.setattr(lifecycle, "get_service", lambda: fake)
    return fake


async def _drain() -> None:
    """Lässt angestoßene Hintergrund-Tasks laufen."""
    for _ in range(5):
        await asyncio.sleep(0)


def test_enabled_handler_is_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(enabled_handler)


async def test_enable_registers_admin_top_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HP_SHARED_KEY", raising=False)
    nc = fake_nc()
    assert await enabled_handler(True, nc) == ""
    nc.ui.resources.set_initial_state.assert_awaited_once_with(
        "top_menu", "gameworld", "gameworld_config", {"apiBase": api_base()}
    )
    nc.ui.resources.set_script.assert_awaited_once_with("top_menu", "gameworld", "js/gameworld-main")
    nc.ui.top_menu.register.assert_awaited_once_with("gameworld", "Gameworld", "img/app.svg", admin_required=False)
    nc.ui.top_menu.unregister.assert_not_awaited()


async def test_disable_removes_top_menu_and_script() -> None:
    nc = fake_nc()
    assert await enabled_handler(False, nc) == ""
    nc.ui.top_menu.unregister.assert_awaited_once_with("gameworld")
    nc.ui.resources.delete_script.assert_awaited_once_with("top_menu", "gameworld", "js/gameworld-main")
    nc.ui.top_menu.register.assert_not_awaited()


async def test_enable_error_is_returned_as_text() -> None:
    nc = fake_nc()
    nc.ui.top_menu.register.side_effect = RuntimeError("kaputt")
    result = await enabled_handler(True, nc)
    assert result
    assert "Gameworld" in result


def test_api_base_manual_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HP_SHARED_KEY", raising=False)
    assert api_base() == "/index.php/apps/app_api/proxy/gameworld"


def test_api_base_harp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HP_SHARED_KEY", "harp-key")
    assert api_base() == "/exapps/gameworld"


async def test_disable_tears_down_worlds_after_menu_and_bot(worlds: FakeWorlds) -> None:
    nc = fake_nc()
    assert await enabled_handler(False, nc) == ""
    assert worlds.teardowns == 1
    assert worlds.boots == 0
    nc.ui.top_menu.unregister.assert_awaited_once_with("gameworld")


async def test_disable_teardown_error_is_only_logged(worlds: FakeWorlds, caplog: pytest.LogCaptureFixture) -> None:
    worlds.teardown_error = RuntimeError("geheime Docker-Meldung")
    assert await enabled_handler(False, fake_nc()) == ""
    assert "RuntimeError" in caplog.text
    assert "geheime Docker-Meldung" not in caplog.text


async def test_disable_teardown_timeout_still_returns_empty(worlds: FakeWorlds) -> None:
    # anyio.fail_after wirft TimeoutError; dieselbe Klasse aus teardown deckt den Zweig ab.
    worlds.teardown_error = TimeoutError()
    assert await enabled_handler(False, fake_nc()) == ""


async def test_disable_reports_partial_teardown_in_log(worlds: FakeWorlds, caplog: pytest.LogCaptureFixture) -> None:
    worlds.teardown_result = 2
    assert await enabled_handler(False, fake_nc()) == ""
    assert "2 Fehler" in caplog.text


async def test_disable_menu_error_still_tears_down_nothing(worlds: FakeWorlds) -> None:
    """Scheitert schon das Menü, meldet der Handler den Fehler (Bestand) und räumt nicht auf."""
    nc = fake_nc()
    nc.ui.top_menu.unregister.side_effect = RuntimeError("kaputt")
    assert await enabled_handler(False, nc) != ""
    assert worlds.teardowns == 0


async def test_enable_schedules_boot_reconcile_without_waiting(worlds: FakeWorlds) -> None:
    assert await enabled_handler(True, fake_nc()) == ""
    assert worlds.teardowns == 0
    await _drain()
    assert worlds.boots == 1
    assert not lifecycle._BACKGROUND  # pyright: ignore[reportPrivateUsage]


async def test_enable_boot_error_is_only_logged(worlds: FakeWorlds, caplog: pytest.LogCaptureFixture) -> None:
    worlds.boot_error = RuntimeError("geheim")
    assert await enabled_handler(True, fake_nc()) == ""
    await _drain()
    assert "RuntimeError" in caplog.text
    assert "geheim" not in caplog.text


async def test_enable_without_service_still_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> object:
        raise ValueError("APP_PERSISTENT_STORAGE fehlt")

    monkeypatch.setattr(lifecycle, "get_service", broken)
    assert await enabled_handler(True, fake_nc()) == ""
    assert await enabled_handler(False, fake_nc()) == ""
