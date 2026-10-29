"""GET/POST /api/settings: player address (join_host), managers only, strictly validated (T-03-41, T-03-42)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.test_service_lifecycle import FakeProvisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


@pytest.fixture
def service(store: WorldStore, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


async def _save(client: httpx.AsyncClient, value: object, user: str = "admin") -> httpx.Response:
    return await client.post("/api/settings", json={"join_host": value}, headers=appapi_headers(user))


async def test_default_is_empty(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.get("/api/settings", headers=appapi_headers())
    assert response.status_code == 200
    assert response.json() == {"join_host": ""}


@pytest.mark.parametrize(
    "value",
    ["192.168.178.20", "gameserver.fritz.box", "heimserver", "fd00::20", "a" * 63 + ".lan", ""],
)
async def test_valid_hosts_are_saved(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, value: str
) -> None:
    del service
    response = await _save(client, value)
    assert response.status_code == 200, response.text
    assert response.json() == {"join_host": value}
    assert store.get_meta("join_host") == value
    listed = await client.get("/api/settings", headers=appapi_headers())
    assert listed.json() == {"join_host": value}


@pytest.mark.parametrize(
    "value",
    [
        "http://x",
        "a/b",
        "host:30000",
        "192.168.178.20:30000",
        "[::1]",
        "bad\nhost",
        "bad\x00host",
        "zero​width",
        "a" * 254,
        "-start.lan",
        "end-.lan",
        "a..b",
        "a" * 64 + ".lan",
        "leer zeichen",
        "<b>x</b>",
        "umlaut-ä.lan",
    ],
)
async def test_invalid_hosts_are_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, value: str
) -> None:
    del service
    response = await _save(client, value)
    assert response.status_code == 422
    assert store.get_meta("join_host") is None


async def test_extra_fields_are_422(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post("/api/settings", json={"join_host": "x.lan", "other": 1}, headers=appapi_headers())
    assert response.status_code == 422


@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_child_gets_403(client: httpx.AsyncClient, service: WorldService, store: WorldStore, method: str) -> None:
    del service
    response = await client.request(
        method,
        "/api/settings",
        json={"join_host": "x.lan"} if method == "POST" else None,
        headers=appapi_headers("gw-kind"),
    )
    assert response.status_code == 403
    assert store.get_meta("join_host") is None
