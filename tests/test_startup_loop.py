"""Event-Loop-Wahl beim Start (Debug-Session backend-windows-invalidstate).

Unter Windows startet uvicorn mit dem Selector-Loop, weil der Proactor-Loop bei
Off-Thread-Finalisierung offener Verbindungen mit InvalidStateError abstürzt.
Überall sonst bleibt uvicorns Vorgabe "auto" (im Linux-Container uvloop).
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
