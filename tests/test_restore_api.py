"""Restore-API über ASGI: Verwalter-Sperre, strenger Body, 202, Fehler 403/404/409/422 (05-06)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
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

NOT_FOUND_TEXT = "Diese Sicherung gibt es nicht (mehr)."
CONFIRM_TEXT = "Bitte das Wiederherstellen bestätigen."


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


async def _backed_up(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, name: str = "Burg"
) -> tuple[str, int]:
    """Welt mit einer eigenen Sicherung über die echte Backup-Route; liefert (Welt, file_id)."""
    created = await service.create_world(name)
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[created.id] = StatusFile(FRESH, b"")
    fake.snapshots[created.id] = world_tar()
    response = await client.post(f"/api/worlds/{created.id}/backups", json={}, headers=appapi_headers())
    assert response.status_code == 202
    await get_backup_service(service).drain()
    proofs = store.backups_for("admin", created.id)
    assert len(proofs) == 1
    fake.calls.clear()
    return created.id, proofs[0].file_id


async def _post(client: httpx.AsyncClient, world_id: str, body: object, user: str = "admin") -> httpx.Response:
    return await client.post(f"/api/worlds/{world_id}/restore", json=body, headers=appapi_headers(user))


def _untouched(fake: FakeProvisioner, store: WorldStore, world_id: str) -> None:
    assert not any(call.startswith(("stop:", "remove:")) for call in fake.calls)
    row = store.get_world(world_id)
    assert row is not None
    assert row.op_state == "ready"
    job = store.get_backup_job(world_id)
    assert job is None or job.kind == "backup"


@pytest.mark.usefixtures("_override")
async def test_post_restore_returns_202_with_restoring_status(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 202
    payload = response.json()
    assert payload["id"] == world_id
    assert payload["status"] == "restoring"
    assert (payload["backup_job"]["kind"], payload["backup_job"]["state"]) == ("restore", "running")
    await get_backup_service(service).drain()
    job = store.get_backup_job(world_id)
    assert job is not None
    assert (job.kind, job.state) == ("restore", "ok")
    assert f"remove:{world_id}" in fake.calls


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("body", [{"file_id": 1, "confirm": False}, {"file_id": 1}])
async def test_missing_confirmation_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, body: dict[str, Any]
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)

    response = await _post(client, world_id, {**body, "file_id": file_id})

    assert response.status_code == 409
    assert response.json() == {"detail": CONFIRM_TEXT}
    _untouched(fake, store, world_id)


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize(
    "body",
    [
        {"file_id": "7", "confirm": True},
        {"file_id": 7.0, "confirm": True},
        {"file_id": 7.5, "confirm": True},
        {"file_id": -7, "confirm": True},
        {"file_id": 0, "confirm": True},
        {"file_id": True, "confirm": True},
        {"file_id": 2**63, "confirm": True},
        {"file_id": 7, "confirm": "true"},
        {"file_id": 7, "confirm": True, "path": "/etc/passwd"},
        {"file_id": 7, "confirm": True, "uid": "papa"},
        {"confirm": True},
        [],
    ],
)
async def test_strict_body_is_422(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, body: object
) -> None:
    world_id, _file_id = await _backed_up(client, service, fake, store)

    response = await _post(client, world_id, body)

    assert response.status_code == 422
    _untouched(fake, store, world_id)


@pytest.mark.usefixtures("_override")
async def test_file_of_other_admin_is_404(
    client: httpx.AsyncClient,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-13: Die Sicherung des Verwalters admin ist für papa nicht wiederherstellbar."""
    monkeypatch.setitem(conftest.FAKE_PROFILES, "papa", ("Papa", ("admin",)))
    world_id, file_id = await _backed_up(client, service, fake, store)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True}, user="papa")

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_TEXT}
    _untouched(fake, store, world_id)


@pytest.mark.usefixtures("_override")
async def test_file_of_other_world_is_404(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)
    other = await service.create_world("Andere")

    response = await _post(client, other.id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 404
    assert response.json() == {"detail": NOT_FOUND_TEXT}
    _untouched(fake, store, world_id)
    _untouched(fake, store, other.id)


@pytest.mark.usefixtures("_override")
async def test_unknown_file_and_world_are_404(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, _file_id = await _backed_up(client, service, fake, store)

    unknown_file = await _post(client, world_id, {"file_id": 999_999, "confirm": True})
    assert unknown_file.status_code == 404
    assert unknown_file.json() == {"detail": NOT_FOUND_TEXT}

    unknown_world = await _post(client, "0123456789ab", {"file_id": 1, "confirm": True})
    assert unknown_world.status_code == 404
    assert unknown_world.json() == {"detail": "Diese Welt gibt es nicht (mehr)."}


@pytest.mark.usefixtures("_override")
async def test_child_gets_403(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True}, user="gw-kind")

    assert response.status_code == 403
    _untouched(fake, store, world_id)


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("op_state", ["backing_up", "restoring", "restoring_swap"])
async def test_busy_world_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore, op_state: str
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)
    store.update_world(world_id, op_state=op_state)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 409


@pytest.mark.usefixtures("_override")
async def test_running_job_elsewhere_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)
    other = await service.create_world("Andere")
    store.set_backup_job(other.id, "backup", "running", None, None, "2026-10-23T10:00:00+00:00", None)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 409
    assert response.json() == {"detail": "Es läuft schon eine Sicherung oder Wiederherstellung. Bitte kurz warten."}
    _untouched(fake, store, world_id)


@pytest.mark.usefixtures("_override")
async def test_players_online_without_confirm_disconnect_is_409(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id, file_id = await _backed_up(client, service, fake, store)
    fake.status_files[world_id] = StatusFile(FRESH, b"Mia\n")

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 409
    assert response.json() == {"detail": "In der Welt spielt gerade 1 Kind, es wird kurz getrennt."}
    _untouched(fake, store, world_id)

    confirmed = await _post(client, world_id, {"file_id": file_id, "confirm": True, "confirm_disconnect": True})
    assert confirmed.status_code == 202
    await get_backup_service(service).drain()


@pytest.mark.usefixtures("_override")
async def test_delete_only_world_can_be_restored(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """D-15: Weltdaten fehlen heißt nicht nur noch löschen, sondern auch wiederherstellen."""
    world_id, file_id = await _backed_up(client, service, fake, store)
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})

    assert response.status_code == 202
    await get_backup_service(service).drain()
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("ready", None)


@pytest.mark.usefixtures("_override")
async def test_restore_of_tampered_file_keeps_world(
    client: httpx.AsyncClient,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    fake_files: FakeBackupFiles,
) -> None:
    """202, aber im Hintergrund abgelehnt: Die Welt läuft unverändert weiter (T-05-29)."""
    world_id, file_id = await _backed_up(client, service, fake, store)
    proof = store.backup_by_file("admin", file_id)
    assert proof is not None
    store.add_backup(replace(proof, sha256="0" * 64))

    response = await _post(client, world_id, {"file_id": file_id, "confirm": True})
    assert response.status_code == 202
    await asyncio.wait_for(get_backup_service(service).drain(), 5)

    job = store.get_backup_job(world_id)
    assert job is not None
    assert (job.kind, job.state, job.message) == (
        "restore",
        "failed",
        "Die Sicherung wurde verändert und wird nicht eingespielt.",
    )
    assert not any(call.startswith(("stop:", "remove:")) for call in fake.calls)
    assert (fake_files.calls[-1][0], fake_files.calls[-1][1]) == ("download_to", "admin")
