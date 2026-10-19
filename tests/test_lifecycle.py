"""Lifecycle der ExApp: Top-Menü, Skript und Initial State beim Aktivieren und Deaktivieren."""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gameworld.lifecycle import api_base, enabled_handler


def fake_nc() -> Any:
    nc = MagicMock()
    nc.ui.resources.set_initial_state = AsyncMock()
    nc.ui.resources.set_script = AsyncMock()
    nc.ui.resources.delete_script = AsyncMock()
    nc.ui.top_menu.register = AsyncMock()
    nc.ui.top_menu.unregister = AsyncMock()
    return nc


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
