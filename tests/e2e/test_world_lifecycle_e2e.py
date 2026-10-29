"""Two parallel worlds, stop, start, delete and instance protection against the real proxy."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator

import docker
import docker.errors
import httpx
import pytest
from docker.models.containers import Container

from gameworld.provisioner.client import DockerProvisioner, WorldNotFoundError
from gameworld.provisioner.spec import LUANTI_IMAGE
from tests.conftest import appapi_headers, docker_url

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

FOREIGN_INSTANCE = "fremd0000"
FOREIGN_WORLD = "f0f0f0f0f0f0"


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


def _wait_running(container: Container, *, running: bool, timeout: float = 35.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container.reload()
        if bool(container.attrs["State"]["Running"]) is running:
            return
        time.sleep(0.5)
    pytest.fail(f"Container {container.name} ist nach {timeout} s nicht Running={running}")


async def _create(client: httpx.AsyncClient, name: str) -> dict[str, object]:
    response = await client.post("/api/worlds", json={"name": name}, headers=appapi_headers())
    assert response.status_code == 201, response.text
    return response.json()


async def test_two_parallel_worlds_stop_start_delete(client: httpx.AsyncClient, api: docker.DockerClient) -> None:
    world_a = await _create(client, "Welt A")
    world_b = await _create(client, "Welt B")
    id_a, id_b = str(world_a["id"]), str(world_b["id"])
    assert world_a["port"] != world_b["port"]

    container_a = _container(api, id_a)
    container_b = _container(api, id_b)
    name_a = str(container_a.name)
    _wait_running(container_a, running=True)
    _wait_running(container_b, running=True)

    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    statuses = {world["id"]: world["docker_status"] for world in listing}
    assert statuses == {id_a: "running", id_b: "running"}

    stopped = await client.post(f"/api/worlds/{id_a}/stop", headers=appapi_headers())
    assert stopped.status_code == 200, stopped.text
    _wait_running(container_a, running=False)
    container_b.reload()
    assert container_b.attrs["State"]["Running"] is True

    started = await client.post(f"/api/worlds/{id_a}/start", headers=appapi_headers())
    assert started.status_code == 200, started.text
    assert started.json()["docker_status"] == "running"
    _wait_running(container_a, running=True)

    deleted = await client.delete(f"/api/worlds/{id_a}", headers=appapi_headers())
    assert deleted.status_code == 204, deleted.text
    assert api.containers.list(all=True, filters={"label": [f"gameworld.world_id={id_a}"]}) == []
    assert [volume for volume in api.volumes.list(filters={"name": name_a}) if volume.name == name_a] == []
    container_b.reload()
    assert container_b.attrs["State"]["Running"] is True

    deleted_b = await client.delete(f"/api/worlds/{id_b}", headers=appapi_headers())
    assert deleted_b.status_code == 204, deleted_b.text
    assert api.containers.list(all=True, filters={"label": [f"gameworld.world_id={id_b}"]}) == []
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    assert listing == []


async def test_foreign_instance_container_is_untouchable(client: httpx.AsyncClient, api: docker.DockerClient) -> None:
    # Create a world of the test instance so that instance ID and provisioner are fixed.
    own = await _create(client, "Eigene Welt")
    foreign = api.containers.create(
        LUANTI_IMAGE,
        command=["--version"],
        name=f"gameworld-{FOREIGN_INSTANCE}-{FOREIGN_WORLD}",
        labels={
            "gameworld.managed": "true",
            "gameworld.instance": FOREIGN_INSTANCE,
            "gameworld.world_id": FOREIGN_WORLD,
        },
    )
    try:
        before = foreign.attrs["State"]
        for method, suffix in (("POST", "/start"), ("POST", "/stop"), ("DELETE", "")):
            response = await client.request(method, f"/api/worlds/{FOREIGN_WORLD}{suffix}", headers=appapi_headers())
            assert response.status_code == 404, f"{method} {suffix}: {response.text}"

        # Even directly on the provisioner of the test instance the foreign container stays untouched.
        own_container = _container(api, str(own["id"]))
        provisioner = DockerProvisioner(docker_url(), own_container.labels["gameworld.instance"])
        with pytest.raises(WorldNotFoundError):
            provisioner.start_world(FOREIGN_WORLD)
        with pytest.raises(WorldNotFoundError):
            provisioner.stop(FOREIGN_WORLD)
        provisioner.remove_world(FOREIGN_WORLD, keep_volume=False)

        foreign.reload()
        assert foreign.attrs["State"]["Status"] == before["Status"] == "created"
        assert foreign.attrs["State"]["StartedAt"] == before["StartedAt"]
    finally:
        with contextlib.suppress(docker.errors.NotFound):
            foreign.remove(force=True, v=True)
