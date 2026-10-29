"""Live proof of both presets against the real proxy (WELT-01).

The tests run serially and create at most one VoxeLibre world
at a time (RAM rule of the home server). Checked are game, memory limit,
gentle switch, the world mod gameworld_status under mod security and the
re-creation of a VoxeLibre world after removing its container (pitfall 2).
"""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Iterator

import docker
import docker.errors
import httpx
import pytest
from docker.models.containers import Container

from gameworld.provisioner.status_mod import PLAYERS_FILE
from tests.conftest import appapi_headers, docker_url

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

DATA_DIR = "/var/lib/minetest"
WORLD_MT = f"{DATA_DIR}/.minetest/worlds/world/world.mt"


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        yield client
    finally:
        client.close()


def _container(api: docker.DockerClient, world_id: str) -> Container:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1, matches
    return matches[0]


def _read_file(container: Container, path: str) -> str:
    stream, _ = container.get_archive(path)
    raw = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        member = tar.getmembers()[0]
        handle = tar.extractfile(member)
        assert handle is not None
        return handle.read().decode("utf-8")


def _wait_for_status_file(container: Container, timeout: float) -> float:
    """Waits until the mod has written the player list; returns the wait time."""
    started = time.monotonic()
    deadline = started + timeout
    while time.monotonic() < deadline:
        container.reload()
        if container.status == "exited":
            break
        try:
            _read_file(container, PLAYERS_FILE)
        except docker.errors.NotFound:
            time.sleep(0.5)
            continue
        return time.monotonic() - started
    logs = container.logs().decode("utf-8", errors="replace")
    pytest.fail(f"Status-Datei fehlt nach {timeout} s. Status {container.status}, Log:\n{logs}")


async def _create(client: httpx.AsyncClient, body: dict[str, str]) -> tuple[dict[str, object], float]:
    started = time.monotonic()
    response = await client.post("/api/worlds", json=body, headers=appapi_headers())
    elapsed = time.monotonic() - started
    assert response.status_code == 201, response.text
    return response.json(), elapsed


async def test_voxelibre_world_runs_with_one_gib(client: httpx.AsyncClient, api: docker.DockerClient) -> None:
    created, elapsed = await _create(client, {"name": "Abenteuer Test", "preset": "voxelibre_sanft"})
    print(f"VoxeLibre-Welt erzeugt in {elapsed:.1f} s")
    assert created["preset"] == "voxelibre_sanft"
    container = _container(api, str(created["id"]))

    host = container.attrs["HostConfig"]
    assert host["Memory"] == 1073741824
    assert host["MemorySwap"] == 1073741824
    assert host["RestartPolicy"]["Name"] == "no"
    labels = container.attrs["Config"]["Labels"]
    assert labels["gameworld.preset"] == "voxelibre_sanft"
    assert labels["gameworld.schema"] == "2"

    conf = _read_file(container, f"{DATA_DIR}/minetest.conf").splitlines()
    for expected in ("only_peaceful_mobs = true", "mcl_keepInventory = true", "creative_mode = false"):
        assert expected in conf, expected
    assert [line for line in conf if line.split("=", 1)[0].strip() == "default_privs"] == [
        "default_privs = interact, shout"
    ]
    assert "gameid = mineclone2" in _read_file(container, WORLD_MT).splitlines()
    assert "title" in _read_file(container, f"{DATA_DIR}/.minetest/games/mineclone2/game.conf")

    ready = _wait_for_status_file(container, 60.0)
    print(f"VoxeLibre-Status-Datei nach {ready:.1f} s")
    container.reload()
    assert container.attrs["State"]["Running"] is True
    assert "ModError" not in container.logs().decode("utf-8", errors="replace")


async def test_kreativ_world_keeps_512_mib_and_writes_status_file(
    client: httpx.AsyncClient, api: docker.DockerClient
) -> None:
    created, elapsed = await _create(client, {"name": "Kreativ Test"})
    print(f"Kreativwelt erzeugt in {elapsed:.1f} s")
    assert created["preset"] == "mtg_kreativ"
    container = _container(api, str(created["id"]))
    host = container.attrs["HostConfig"]
    assert host["Memory"] == 536870912
    assert host["MemorySwap"] == 536870912
    assert container.attrs["Config"]["Labels"]["gameworld.schema"] == "2"
    assert "gameid = minetest" in _read_file(container, WORLD_MT).splitlines()
    _wait_for_status_file(container, 30.0)
    assert "ModError" not in container.logs().decode("utf-8", errors="replace")


async def test_recreated_voxelibre_world_keeps_its_game(client: httpx.AsyncClient, api: docker.DockerClient) -> None:
    created, _ = await _create(client, {"name": "Abenteuer Neu", "preset": "voxelibre_sanft"})
    world_id = str(created["id"])
    # Remove from outside, the volume with the world data stays.
    _container(api, world_id).remove(force=True, v=False)

    started = time.monotonic()
    response = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    print(f"VoxeLibre-Neuerzeugung in {time.monotonic() - started:.1f} s")
    assert response.status_code == 200, response.text

    container = _container(api, world_id)
    assert container.attrs["HostConfig"]["Memory"] == 1073741824
    assert container.attrs["HostConfig"]["MemorySwap"] == 1073741824
    assert container.attrs["Config"]["Labels"]["gameworld.preset"] == "voxelibre_sanft"
    assert "gameid = mineclone2" in _read_file(container, WORLD_MT).splitlines()
