"""WR-01: Eine ungültige Umgebung verhindert weder den App-Start noch die Fehlermeldung.

Der Prozess muss hochkommen, damit /api/setup-check den Befund "config" melden
kann; die Welt-Routen antworten dann mit 503 und der deutschen Meldung.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from gameworld.config import load_settings
from gameworld.main import lifespan
from tests.conftest import appapi_headers

INVALID_RANGE = "kaputt"


async def test_lifespan_starts_despite_invalid_port_range(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", INVALID_RANGE)
    app = FastAPI()
    # Ohne den WR-01-Fix bricht der Lifespan hier mit ValueError ab und
    # uvicorn würde die ExApp gar nicht erst starten.
    async with lifespan(app):
        pass


async def test_setup_check_reports_config_finding(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", INVALID_RANGE)
    response = await client.get("/api/setup-check", headers=appapi_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert [item["id"] for item in body["items"]] == ["config"]
    assert "GAMEWORLD_PORT_RANGE" in body["items"][0]["message"]


async def test_world_routes_answer_503_with_invalid_config(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", INVALID_RANGE)
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 503
    assert "GAMEWORLD_PORT_RANGE" in response.json()["detail"]


async def test_unusable_storage_is_a_config_error(
    app_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    del app_env
    blocker = tmp_path / "datei-statt-verzeichnis"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(blocker))
    with pytest.raises(ValueError, match="APP_PERSISTENT_STORAGE"):
        load_settings()
