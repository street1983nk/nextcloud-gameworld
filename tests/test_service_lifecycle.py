"""Lebenszyklus ohne Docker: Starten, Stoppen, Löschen und die Port-Kollisions-Saga."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    PortInUseError,
    ProvisionerError,
    WorldNotFoundError,
)
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers


@dataclass
class FakeProvisioner:
    """Bildet die Schnittstelle von DockerProvisioner nach und protokolliert jeden Aufruf."""

    start_errors: list[ProvisionerError] = field(default_factory=list)
    remove_error: ProvisionerError | None = None
    host_ports: set[int] = field(default_factory=set)
    containers: dict[str, tuple[int, str]] = field(default_factory=dict)
    created: list[tuple[str, int, bool]] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    removed: list[tuple[str, bool]] = field(default_factory=list)

    def ensure_image(self) -> None:
        return None

    def create_world_container(self, world_id: str, host_port: int, payload: bytes, *, reuse_volume: bool = False) -> str:
        assert payload
        self.created.append((world_id, host_port, reuse_volume))
        self.containers[world_id] = (host_port, "created")
        return f"cid-{world_id}"

    def _known(self, world_id: str) -> tuple[int, str]:
        if world_id not in self.containers:
            raise WorldNotFoundError("Diese Welt gibt es nicht (mehr).")
        return self.containers[world_id]

    def start_world(self, world_id: str) -> None:
        port, _ = self._known(world_id)
        self.started.append(world_id)
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.containers[world_id] = (port, "running")

    def stop(self, world_id: str) -> None:
        port, _ = self._known(world_id)
        self.stopped.append(world_id)
        self.containers[world_id] = (port, "exited")

    def remove_world(self, world_id: str, *, keep_volume: bool) -> None:
        self.removed.append((world_id, keep_volume))
        if self.remove_error is not None:
            raise self.remove_error
        self.containers.pop(world_id, None)

    def used_host_ports(self, lo: int, hi: int) -> set[int]:
        ports = self.host_ports | {port for port, _ in self.containers.values()}
        return {port for port in ports if lo <= port <= hi}

    def list_managed(self) -> dict[str, ContainerInfo]:
        return {
            world_id: ContainerInfo(f"cid-{world_id}", f"gameworld-x-{world_id}", world_id, status, port)
            for world_id, (port, status) in self.containers.items()
        }


@pytest.fixture
def fake() -> FakeProvisioner:
    return FakeProvisioner()


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, fake), load_settings())


async def test_two_worlds_get_different_ports(service: WorldService) -> None:
    first = await service.create_world("Welt A")
    second = await service.create_world("Welt B")
    assert first.port == 30015
    assert second.port == 30016


async def test_port_bound_by_foreign_container_is_skipped(service: WorldService, fake: FakeProvisioner) -> None:
    fake.host_ports = {30015}
    created = await service.create_world("Welt")
    assert created.port == 30016


async def test_port_conflict_on_start_recreates_with_next_port(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.created.clear()
    fake.start_errors = [PortInUseError(30015)]

    view = await service.start_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.port == 30016
    assert row.op_state == "ready"
    assert view.port == 30016
    assert view.docker_status == "running"
    assert fake.removed == [(created.id, True)]
    assert fake.created == [(created.id, 30016, True)]


async def test_port_conflict_on_create_recreates_with_next_port(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.start_errors = [PortInUseError(30015)]
    created = await service.create_world("Welt")
    assert created.port == 30016
    row = store.get_world(created.id)
    assert row is not None
    assert row.port == 30016
    assert row.op_state == "ready"
    assert fake.removed == [(created.id, True)]


async def test_three_port_conflicts_give_up(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.started.clear()
    fake.start_errors = [PortInUseError(30015), PortInUseError(30016), PortInUseError(30017)]

    with pytest.raises(ProvisionerError):
        await service.start_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error is not None
    assert "UDP-Port" in row.last_error
    assert len(fake.started) == 3


async def test_stop_and_start_set_desired_state(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")

    stopped = await service.stop_world(created.id)
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "stopped"
    assert stopped.docker_status == "exited"

    started = await service.start_world(created.id)
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "running"
    assert started.docker_status == "running"


async def test_delete_removes_row_after_docker_cleanup(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.delete_world(created.id)
    assert fake.removed == [(created.id, False)]
    assert store.get_world(created.id) is None


async def test_failed_delete_keeps_row(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    fake.remove_error = ProvisionerError("Docker hat die Anfrage abgelehnt: kaputt")

    with pytest.raises(ProvisionerError):
        await service.delete_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error == "Docker hat die Anfrage abgelehnt: kaputt"


@pytest.mark.parametrize("operation", ["start_world", "stop_world", "delete_world"])
async def test_unknown_world_raises_not_found(service: WorldService, operation: str) -> None:
    with pytest.raises(WorldNotFoundError):
        await getattr(service, operation)("0123456789ab")


@pytest.fixture
def _override(service: WorldService) -> Iterator[None]:
    from gameworld.main import APP

    APP.dependency_overrides[get_service] = lambda: service
    yield
    APP.dependency_overrides.pop(get_service, None)


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("world_id", ["xyz", "..etc", "0123456789AB", "0123456789abc"])
@pytest.mark.parametrize(("method", "suffix"), [("POST", "/start"), ("POST", "/stop"), ("DELETE", "")])
async def test_invalid_world_id_returns_422(client: httpx.AsyncClient, world_id: str, method: str, suffix: str) -> None:
    response = await client.request(method, f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())
    assert response.status_code == 422


@pytest.mark.usefixtures("_override")
async def test_path_traversal_never_reaches_a_route(client: httpx.AsyncClient) -> None:
    response = await client.request("DELETE", "/api/worlds/..%2Fetc", headers=appapi_headers())
    assert response.status_code in {404, 405, 422}


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize(("method", "suffix"), [("POST", "/start"), ("POST", "/stop"), ("DELETE", "")])
async def test_unknown_world_returns_404(client: httpx.AsyncClient, method: str, suffix: str) -> None:
    response = await client.request(method, f"/api/worlds/0123456789ab{suffix}", headers=appapi_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "Diese Welt gibt es nicht (mehr)."}


@pytest.mark.usefixtures("_override")
async def test_api_lifecycle_round_trip(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    assert created.status_code == 201
    world_id = created.json()["id"]

    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.status_code == 200
    assert stopped.json()["docker_status"] == "exited"
    assert "world_key" not in stopped.json()

    started = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    assert started.status_code == 200
    assert started.json()["docker_status"] == "running"

    deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
    assert deleted.status_code == 204
    listing = await client.get("/api/worlds", headers=appapi_headers())
    assert listing.json()["worlds"] == []
