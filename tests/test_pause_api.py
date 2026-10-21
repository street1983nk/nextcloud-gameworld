"""Pause-API über ASGI: Verwalter-Sperre, Validierung, Ausrollen an alle Welten, Neustart alter Mods (04.1-03)."""

from __future__ import annotations

import io
import re
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.playtime.pause import ART_PAUSE, PauseState
from gameworld.playtime.plan import day_starts, local_day
from gameworld.provisioner.client import DockerProvisioner, StatusFile
from gameworld.provisioner.time_mod import RULES_FILE_NAME
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldRow, WorldStore
from tests.conftest import appapi_headers
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
W3 = "aaaaaaaaaaa3"
VERIFIER = "#1#c2FsdA==#dmVyaWZpZXI="
STARTED_AT = "2026-10-19T18:19:46.947430723Z"
FRESH = "2026-10-19T18:19:48.5Z"
BERLIN = ZoneInfo("Europe/Berlin")
EVENTS = b"gameworld-events 1 0\nend\n"


def _row(world_id: str, name: str, port: int) -> WorldRow:
    return WorldRow(
        id=world_id,
        name=name,
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-20T10:00:00+00:00",
    )


def _new_mod(fake: FakeProvisioner, world_id: str) -> None:
    """Laufende Welt mit neuem Mod: Ereignisdatei jünger als StartedAt."""
    fake.extra[world_id] = {"started_at": STARTED_AT}
    fake.events[world_id] = StatusFile(FRESH, EVENTS)


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "running")
    _new_mod(provisioner, W1)
    _new_mod(provisioner, W2)
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Kind", rotation=0))
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER})
    world_store.apply_world_access(W2, {"gw-kind": VERIFIER})
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


def _rules_of(fake: FakeProvisioner, world_id: str) -> str:
    for written_id, archive in reversed(fake.written):
        if written_id != world_id:
            continue
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            if RULES_FILE_NAME in tar.getnames():
                handle = tar.extractfile(RULES_FILE_NAME)
                assert handle is not None
                return handle.read().decode("ascii")
    raise AssertionError("keine Regeldatei geschrieben")


def _outbox(store: WorldStore) -> list[tuple[str, str, str]]:
    return [(row.world_id, row.kind, row.detail) for row in store.outbox_batch(limit=1000)]


def _worlds(data: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(item["id"]): item for item in cast(list[dict[str, object]], data["worlds"])}


async def test_start_pause_rolls_out_to_all_worlds(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del service
    before = int(time.time())
    response = await client.post("/api/pause", json={"minutes": 30}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["active"] is True
    assert data["art"] == "pause"
    assert before + 30 <= data["ab"] <= int(time.time()) + 30
    assert data["bis"] - data["ab"] == 1800
    assert re.fullmatch(r"\d{1,2}:\d{2}", data["until_clock"])
    local = datetime.fromtimestamp(data["bis"], BERLIN)
    assert data["until_clock"] == f"{local.hour}:{local.minute:02d}"
    worlds = _worlds(data)
    assert set(worlds) == {W1, W2}
    assert worlds[W1] == {"id": W1, "name": "Wiese", "applied": True, "restarted": False}
    assert worlds[W2]["applied"] is True
    for world_id in (W1, W2):
        assert f"@pause {data['ab']} {data['bis']} pause" in _rules_of(fake, world_id)
    assert fake.stopped == []
    assert sorted(_outbox(store)) == sorted(
        [(W1, "pause_start", str(data["bis"])), (W2, "pause_start", str(data["bis"]))]
    )
    stored = store.get_pause()
    assert stored is not None
    assert stored.started_by == "admin"


@pytest.mark.parametrize(
    "body",
    [{"minutes": 20}, {"minutes": "30"}, {"minutes": 30, "extra": 1}, {}, {"minutes": 30.0}, {"minutes": True}],
)
async def test_invalid_body_is_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, body: object
) -> None:
    del service
    response = await client.post("/api/pause", json=body, headers=appapi_headers())
    assert response.status_code == 422
    assert store.get_pause() is None


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [("GET", "", None), ("POST", "", {"minutes": 15}), ("POST", "/end", None), ("POST", "/schluss", None)],
)
async def test_child_is_forbidden(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, method: str, path: str, body: object
) -> None:
    del service
    response = await client.request(method, f"/api/pause{path}", json=body, headers=appapi_headers("gw-kind"))
    assert response.status_code != 200
    assert response.status_code == 403
    assert store.get_pause() is None
    assert _outbox(store) == []


async def test_old_mod_world_is_restarted(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner
) -> None:
    del service
    # W1 läuft noch mit altem Mod: keine Ereignisdatei.
    del fake.events[W1]
    response = await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    worlds = _worlds(response.json())
    assert worlds[W1]["restarted"] is True
    assert worlds[W1]["applied"] is True
    assert worlds[W2]["restarted"] is False
    assert fake.stopped == [W1]
    assert fake.started == [W1]
    assert fake.calls.index(f"stop:{W1}") < fake.calls.index(f"start:{W1}")
    # Der Neustart schreibt die Regeldatei mit Pause vor dem Start (_launch).
    assert "@pause" in _rules_of(fake, W1)


async def test_end_pause_removes_line_and_is_idempotent(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del service
    started = await client.post("/api/pause", json={"minutes": 60}, headers=appapi_headers())
    assert started.status_code == 200
    response = await client.post("/api/pause/end", headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["active"] is False
    assert data["art"] is None
    assert data["until_clock"] is None
    assert set(_worlds(data)) == {W1, W2}
    for world_id in (W1, W2):
        assert "@pause" not in _rules_of(fake, world_id)
    assert store.get_pause() is None
    assert [kind for _world, kind, _detail in _outbox(store)].count("pause_end") == 2

    again = await client.post("/api/pause/end", headers=appapi_headers())
    assert again.status_code == 200
    assert again.json()["active"] is False


async def test_schluss_until_next_local_day_keeps_usage(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del service
    today = local_day(int(time.time()), BERLIN)
    store.add_usage("gw-kind", today, 600)
    response = await client.post("/api/pause/schluss", headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["active"] is True
    assert data["art"] == "schluss"
    assert data["bis"] == day_starts(int(time.time()), BERLIN)[1]
    assert f"@pause {data['ab']} {data['bis']} schluss" in _rules_of(fake, W1)
    assert store.usage("gw-kind", today) == 600
    assert sorted(kind for _world, kind, _detail in _outbox(store)) == ["pause_schluss", "pause_schluss"]


async def test_schluss_during_pause_keeps_ab(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    started = (await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())).json()
    schluss = (await client.post("/api/pause/schluss", headers=appapi_headers())).json()
    assert schluss["ab"] == started["ab"]
    assert schluss["art"] == "schluss"


async def test_get_reports_state_and_expiry(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    empty = await client.get("/api/pause", headers=appapi_headers())
    assert empty.status_code == 200
    assert empty.json() == {"active": False, "art": None, "ab": None, "bis": None, "until_clock": None, "worlds": []}

    await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    running = (await client.get("/api/pause", headers=appapi_headers())).json()
    assert running["active"] is True
    assert running["art"] == "pause"

    now = int(time.time())
    store.set_pause(PauseState(started_by="admin", ab=now - 1000, bis=now - 1, art=ART_PAUSE))
    expired = (await client.get("/api/pause", headers=appapi_headers())).json()
    assert expired["active"] is False


async def test_pause_survives_app_restart(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    started = (await client.post("/api/pause", json={"minutes": 30}, headers=appapi_headers())).json()
    # Neuer Prozess: neuer Dienst und neue Rechnung über derselben Datenbank.
    fresh = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    data, _changed = fresh.time.render(W1)
    assert f"@pause {started['ab']} {started['bis']} pause" in data.decode("ascii")
    del service


async def test_world_without_container_is_isolated(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del service
    store.insert_world(_row(W3, "Höhle", 30017))
    response = await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    worlds = _worlds(response.json())
    assert worlds[W3]["applied"] is False
    assert worlds[W3]["restarted"] is False
    assert worlds[W1]["applied"] is True
    assert "@pause" in _rules_of(fake, W2)


async def test_deleted_world_is_skipped(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    store.update_world(W2, desired_state="deleted")
    response = await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    assert response.status_code == 200
    assert set(_worlds(response.json())) == {W1}
    assert [world for world, _kind, _detail in _outbox(store)] == [W1]
