"""Ein nicht erreichbarer Docker-Proxy ergibt 503 bzw. docker_status unknown, nie einen 500er."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import ContainerInfo, DockerProvisioner, DockerUnavailableError
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests.conftest import appapi_headers

MESSAGE = (
    "Gameworld erreicht den Docker-Proxy unter tcp://127.0.0.1:23750 nicht. "
    "Bitte prüfen, ob der Dienst gameworld-docker-proxy läuft."
)


class FakeProvisioner:
    """Steht für DockerProvisioner; jede Methode kann einen Fehler werfen."""

    def __init__(self) -> None:
        self.fail_list = False
        self.fail_image = False
        self.fail_discard = False
        self.created: list[str] = []

    def ensure_image(self) -> None:
        if self.fail_image:
            raise DockerUnavailableError(MESSAGE)

    def create_world_container(self, world_id: str, host_port: int, payload: bytes) -> str:
        del host_port, payload
        self.created.append(world_id)
        return f"cid-{world_id}"

    def start(self, container_id: str) -> None:
        del container_id
        raise DockerUnavailableError(MESSAGE)

    def discard(self, container_id: str, *, keep_volume: bool) -> None:
        del container_id, keep_volume
        if self.fail_discard:
            raise DockerUnavailableError("zweiter Fehler beim Aufräumen")

    def list_managed(self) -> dict[str, ContainerInfo]:
        if self.fail_list:
            raise DockerUnavailableError(MESSAGE)
        return {}


@pytest.fixture
def fake() -> FakeProvisioner:
    return FakeProvisioner()


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


@pytest.fixture
def _override(store: WorldStore, fake: FakeProvisioner) -> Iterator[None]:
    from gameworld.main import APP

    service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    APP.dependency_overrides[get_service] = lambda: service
    yield
    APP.dependency_overrides.pop(get_service, None)


def _seed(store: WorldStore) -> None:
    store.insert_world(
        WorldRow(
            id="0123456789ab",
            name="Alte Welt",
            port=30015,
            container_name="gameworld-x-0123456789ab",
            volume_name="gameworld-x-0123456789ab",
            world_key="geheim",
            engine_version="5.17.0",
            desired_state="running",
            op_state="ready",
            last_error=None,
            created_at="2026-10-19T10:00:00+00:00",
        )
    )


@pytest.mark.usefixtures("_override")
async def test_list_shows_unknown_when_proxy_is_down(
    client: httpx.AsyncClient, store: WorldStore, fake: FakeProvisioner
) -> None:
    _seed(store)
    fake.fail_list = True
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200
    worlds = response.json()["worlds"]
    assert len(worlds) == 1
    assert worlds[0]["docker_status"] == "unknown"
    assert "world_key" not in worlds[0]


@pytest.mark.usefixtures("_override")
async def test_create_returns_503_when_proxy_is_down(
    client: httpx.AsyncClient, store: WorldStore, fake: FakeProvisioner
) -> None:
    fake.fail_image = True
    response = await client.post("/api/worlds", json={"name": "Testwelt"}, headers=appapi_headers())
    assert response.status_code == 503
    assert "gameworld-docker-proxy" in response.json()["detail"]
    assert "Traceback" not in response.text
    rows = store.list_worlds()
    assert len(rows) == 1
    assert rows[0].op_state == "failed"
    assert rows[0].last_error == MESSAGE


@pytest.mark.usefixtures("_override")
async def test_failed_cleanup_keeps_original_error(
    client: httpx.AsyncClient, store: WorldStore, fake: FakeProvisioner
) -> None:
    fake.fail_discard = True
    response = await client.post("/api/worlds", json={"name": "Testwelt"}, headers=appapi_headers())
    assert response.status_code == 503
    assert response.json()["detail"] == MESSAGE
    assert len(fake.created) == 1
    rows = store.list_worlds()
    assert rows[0].op_state == "failed"
    assert rows[0].last_error == MESSAGE
