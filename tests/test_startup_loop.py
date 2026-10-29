"""Event loop choice at startup (debug session backend-windows-invalidstate).

On Windows uvicorn starts with the selector loop, because the proactor loop crashes
with InvalidStateError when open connections are finalized off-thread.
Everywhere else uvicorn's default "auto" stays (uvloop in the Linux container).
"""

from __future__ import annotations

import asyncio
import sys

import pytest
import uvicorn

from gameworld import main


def test_windows_startet_mit_selector_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert main._uvicorn_loop() == "asyncio:SelectorEventLoop"


def test_linux_bleibt_bei_uvicorn_vorgabe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert main._uvicorn_loop() == "auto"


def test_uvicorn_laedt_den_selector_loop_als_factory() -> None:
    config = uvicorn.Config("gameworld.main:APP", loop="asyncio:SelectorEventLoop")
    assert config.get_loop_factory() is asyncio.SelectorEventLoop
