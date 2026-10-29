"""Backup API over ASGI: manager lock, strict body, 202, errors 409/404/422, list (05-05)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.backup.service import get_backup_service
from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner, StatusFile
from gameworld.worlds.service import RECONCILE_DATA_MISSING, WorldService
from gameworld.worlds.store import WorldStore
from tests import conftest
from tests.conftest import FakeBackupFiles, appapi_headers
from tests.test_backup_service import world_tar
from tests.test_service_lifecycle import FRESH, STARTED_AT, FakeProvisioner

UNKNOWN = "0123456789ab"


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


@pytest.fixture
def _override(service: WorldService) -> Iterator[None]:
    from gameworld.main import APP

    APP.dependency_overrides[get_service] = lambda: service
    yield
    APP.dependency_overrides.pop(get_service, None)


async def _world(service: WorldService, fake: FakeProvisioner, name: str = "Burg", players: bytes = b"") -> str:
    created = await service.create_world(name)
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[created.id] = StatusFile(FRESH, players)
    fake.snapshots[created.id] = world_tar()
    return created.id


class _Gate:
    """Holds the fake upload until ``release`` is set."""

    def __init__(self, files: FakeBackupFiles) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        original = files.upload

        async def blocked(*args: Any, **kwargs: Any) -> Any:
            self.entered.set()
            await self.release.wait()
            return await original(*args, **kwargs)

        files.upload = blocked  # type: ignore[method-assign]


async def _post(client: httpx.AsyncClient, world_id: str, body: object, user: str = "admin") -> httpx.Response:
    return await client.post(f"/api/worlds/{world_id}/backups", json=body, headers=appapi_headers(user))


# Trigger


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("body", [{}, {"confirm_disconnect": True}, {"confirm_disconnect": False}])
async def test_post_backup_returns_202_with_running_job(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, body: object
) -> None:
    world_id = await _world(service, fake)
    gate = _Gate(fake_files)

    response = await _post(client, world_id, body)

    assert response.status_code == 202
    payload = response.json()
    assert payload["id"] == world_id
    assert payload["backup_job"]["state"] == "running"
    assert payload["backup_job"]["kind"] == "backup"
    await asyncio.wait_for(gate.entered.wait(), 5)
    gate.release.set()
    await get_backup_service(service).drain()


@pytest.mark.usefixtures("_override")
async def test_child_gets_403(client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _world(service, fake)
    assert (await _post(client, world_id, {}, user="gw-kind")).status_code == 403
    listing = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers("gw-kind"))
    assert listing.status_code == 403
    assert fake.calls.count(f"stop:{world_id}") == 0


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("world_id", ["xyz", "0123456789AB", "0123456789abc"])
async def test_invalid_world_id_is_422(client: httpx.AsyncClient, world_id: str) -> None:
    assert (await _post(client, world_id, {})).status_code == 422
    listing = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers())
    assert listing.status_code == 422


@pytest.mark.usefixtures("_override")
async def test_unknown_world_is_404(client: httpx.AsyncClient) -> None:
    response = await _post(client, UNKNOWN, {})
    assert response.status_code == 404
    assert response.json() == {"detail": "Diese Welt gibt es nicht (mehr)."}
    listing = await client.get(f"/api/worlds/{UNKNOWN}/backups", headers=appapi_headers())
    assert listing.status_code == 404


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize(
    "body",
    [
        {"confirm_disconnect": "true"},
        {"confirm_disconnect": 1},
        {"confirm_disconnect": True, "path": "/etc"},
        {"uid": "papa"},
        [],
    ],
)
async def test_strict_body_is_422(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, body: object
) -> None:
    world_id = await _world(service, fake)
    response = await _post(client, world_id, body)
    assert response.status_code == 422
    assert store.get_backup_job(world_id) is None


@pytest.mark.usefixtures("_override")
async def test_players_online_without_confirm_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id = await _world(service, fake, players=b"Mia\nLeo\n")

    response = await _post(client, world_id, {})

    assert response.status_code == 409
    assert response.json() == {"detail": "In der Welt spielen gerade 2 Kinder, sie werden kurz getrennt."}
    assert store.get_backup_job(world_id) is None
    row = store.get_world(world_id)
    assert row is not None
    assert row.op_state == "ready"


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("op_state", ["backing_up", "restoring", "restoring_swap"])
async def test_busy_world_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, op_state: str
) -> None:
    world_id = await _world(service, fake)
    store.update_world(world_id, op_state=op_state)
    response = await _post(client, world_id, {})
    assert response.status_code == 409


@pytest.mark.usefixtures("_override")
async def test_running_job_elsewhere_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles
) -> None:
    first = await _world(service, fake, name="Erste")
    second = await _world(service, fake, name="Zweite")
    gate = _Gate(fake_files)

    assert (await _post(client, first, {})).status_code == 202
    await asyncio.wait_for(gate.entered.wait(), 5)
    response = await _post(client, second, {})
    assert response.status_code == 409
    assert response.json() == {"detail": "Es läuft schon eine Sicherung oder Wiederherstellung. Bitte kurz warten."}
    # Delete during the upload: also 409 (T-05-48).
    deleted = await client.delete(f"/api/worlds/{first}", headers=appapi_headers())
    assert deleted.status_code == 409
    gate.release.set()
    await get_backup_service(service).drain()


@pytest.mark.usefixtures("_override")
async def test_delete_only_world_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id = await _world(service, fake)
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    response = await _post(client, world_id, {})
    assert response.status_code == 409


@pytest.mark.usefixtures("_override")
async def test_pause_answers_during_long_upload(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles
) -> None:
    """Pitfall 3: the global lock is free during the upload."""
    world_id = await _world(service, fake)
    gate = _Gate(fake_files)
    assert (await _post(client, world_id, {})).status_code == 202
    await asyncio.wait_for(gate.entered.wait(), 5)

    begin = time.monotonic()
    paused = await client.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    elapsed = time.monotonic() - begin

    assert paused.status_code == 200
    assert elapsed < 2.0
    gate.release.set()
    await get_backup_service(service).drain()


# List


@pytest.mark.usefixtures("_override")
async def test_list_shows_own_backup_after_upload_only_for_owner(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(conftest.FAKE_PROFILES, "papa", ("Papa", ("admin",)))
    world_id = await _world(service, fake)

    empty = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers())
    assert empty.status_code == 200
    assert empty.json() == {"backups": [], "total_size": 0, "other_files": 0}

    assert (await _post(client, world_id, {})).status_code == 202
    await get_backup_service(service).drain()

    listing = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers())
    assert listing.status_code == 200
    payload = listing.json()
    assert len(payload["backups"]) == 1
    item = payload["backups"][0]
    assert set(item) == {"file_id", "name", "size", "created_at", "kind"}
    assert item["kind"] == "backup"
    assert item["name"].startswith("Burg-")
    assert item["name"].endswith(".tar.gz")
    assert isinstance(item["file_id"], int)
    assert payload["total_size"] == item["size"]
    assert payload["other_files"] == 0

    # D-13: a second manager does not see the first one's backup.
    other = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers("papa"))
    assert other.status_code == 200
    assert other.json() == {"backups": [], "total_size": 0, "other_files": 0}

    # The world list shows the finished job.
    worlds = await client.get("/api/worlds", headers=appapi_headers())
    job = next(world["backup_job"] for world in worlds.json()["worlds"] if world["id"] == world_id)
    assert (job["state"], job["file_name"]) == ("ok", item["name"])


@pytest.mark.usefixtures("_override")
async def test_list_files_error_is_503(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles
) -> None:
    from gameworld.backup.files import MSG_FILES_FAILED, FilesError

    world_id = await _world(service, fake)

    async def broken(uid: str, folder_path: str) -> list[Any]:
        del uid, folder_path
        raise FilesError(MSG_FILES_FAILED)

    fake_files.listdir = broken  # type: ignore[method-assign]

    response = await client.get(f"/api/worlds/{world_id}/backups", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json() == {"detail": MSG_FILES_FAILED}
