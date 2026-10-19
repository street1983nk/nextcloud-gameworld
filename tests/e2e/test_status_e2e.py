"""Live-Nachweis gegen den echten Proxy: Der Status kommt aus Docker, Neustart, Bereitschaft."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import httpx
import pytest
from docker.models.containers import Container

from gameworld.worlds.status import parse_docker_time
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers, docker_url

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

READY_TIMEOUT = 30.0
MTG_LIMIT = 536870912


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        yield client
    finally:
        client.close()


def _container(api: docker.DockerClient, world_id: str) -> Container:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1, f"erwartet genau einen Container für {world_id}, gefunden {len(matches)}"
    return matches[0]


async def _world(client: httpx.AsyncClient, world_id: str) -> dict[str, object]:
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200, response.text
    worlds = {str(world["id"]): world for world in response.json()["worlds"]}
    return worlds[world_id]


# Testhelfer: Die Frist ist bewusst Teil der Schnittstelle (Plan 02-05), daher ASYNC109 aus.
async def wait_for_status(
    client: httpx.AsyncClient,
    world_id: str,
    expected: str,
    timeout: float = 10.0,  # noqa: ASYNC109
) -> dict[str, object]:
    """Fragt GET /api/worlds alle 0,5 s, bis der Status erscheint.

    Die Weltenliste wird 2 s zwischengespeichert; Änderungen von außen
    (container.stop, container.kill) erscheinen deshalb erst verzögert.
    Änderungen über die API verwerfen den Cache selbst.
    """
    deadline = time.monotonic() + timeout
    seen: list[str] = []
    while time.monotonic() < deadline:
        world = await _world(client, world_id)
        status = str(world["status"])
        if not seen or seen[-1] != status:
            seen.append(status)
        if status == expected:
            return world
        await asyncio.sleep(0.5)
    pytest.fail(f"Welt {world_id} ist nach {timeout} s nicht {expected}, gesehen: {seen}")


def _desired_state(storage: Path, world_id: str) -> str:
    row = WorldStore(storage / "gameworld.sqlite3").get_world(world_id)
    assert row is not None
    return row.desired_state


def _started_at(container: Container) -> str:
    container.reload()
    return str(container.attrs["State"]["StartedAt"])


async def test_status_comes_from_docker_and_restart_works(
    client: httpx.AsyncClient, api: docker.DockerClient, app_env: Path
) -> None:
    created = await client.post(
        "/api/worlds", json={"name": "Statuswelt", "preset": "mtg_kreativ"}, headers=appapi_headers()
    )
    assert created.status_code == 201, created.text
    world_id = str(created.json()["id"])
    assert created.json()["status"] in {"starting", "running"}

    ready = await wait_for_status(client, world_id, "running", READY_TIMEOUT)
    assert ready["status_text"] == "Läuft"
    # WELT-03: RAM aus docker stats (Kreativ-Preset 512 MiB), noch niemand online.
    used = ready["memory_used_bytes"]
    assert isinstance(used, int)
    assert 0 < used <= MTG_LIMIT
    assert ready["memory_limit_bytes"] == MTG_LIMIT
    assert ready["players"] == []
    container = _container(api, world_id)

    # Stop von außen: Das Dashboard zeigt "Gestoppt", die Datenbank bleibt unverändert.
    container.stop(timeout=30)
    stopped = await wait_for_status(client, world_id, "stopped")
    assert (stopped["status"], stopped["status_text"]) == ("stopped", "Gestoppt")
    assert stopped["memory_used_bytes"] is None
    assert stopped["memory_limit_bytes"] is None
    assert stopped["players"] == []
    assert _desired_state(app_env, world_id) == "running"

    started = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    assert started.status_code == 200, started.text
    await wait_for_status(client, world_id, "running", READY_TIMEOUT)

    # SIGKILL von außen: Fehler mit Klartext und Exit-Code.
    container.kill()
    killed = await wait_for_status(client, world_id, "error")
    assert killed["status"] == "error"
    assert "unerwartet beendet" in str(killed["status_text"])
    assert "137" in str(killed["status_text"])
    assert _desired_state(app_env, world_id) == "running"

    before = parse_docker_time(_started_at(container))
    assert before is not None
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    await wait_for_status(client, world_id, "running", READY_TIMEOUT)
    after = parse_docker_time(_started_at(_container(api, world_id)))
    assert after is not None
    assert after > before


async def test_restart_of_running_world_gets_new_start_time(
    client: httpx.AsyncClient, api: docker.DockerClient
) -> None:
    created = await client.post("/api/worlds", json={"name": "Neustartwelt"}, headers=appapi_headers())
    assert created.status_code == 201, created.text
    world_id = str(created.json()["id"])
    await wait_for_status(client, world_id, "running", READY_TIMEOUT)
    before = parse_docker_time(_started_at(_container(api, world_id)))
    assert before is not None

    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    # Direkt nach dem Neustart ist die Status-Datei älter als StartedAt, also höchstens "starting".
    assert restarted.json()["status"] in {"starting", "running"}
    await wait_for_status(client, world_id, "running", READY_TIMEOUT)
    after = parse_docker_time(_started_at(_container(api, world_id)))
    assert after is not None
    assert after > before


async def test_unknown_world_restart_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds/0123456789ab/restart", headers=appapi_headers())
    assert response.status_code == 404
