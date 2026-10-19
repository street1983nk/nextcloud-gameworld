"""Invites-API über ASGI: Rechte, Validierung, Fehlercodes und keine Lecks in Logs oder Fehlern."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.access.accounts import derive_password
from gameworld.access.directory import DirectoryUnavailableError
from gameworld.access.secret import SecretUnavailableError
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner, DockerUnavailableError
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests.conftest import TEST_SECRET, FakeDirectory, StaticSecret, appapi_headers
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
PASSWORD = derive_password(TEST_SECRET, "gw-kind", 0)
INVITE = {"kind": "user", "target": "gw-kind"}


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(
        WorldRow(
            id=W1,
            name="Testwelt",
            port=30015,
            container_name="gw-x-w1",
            volume_name="gw-x-w1",
            world_key="k",
            engine_version="5.17.0",
            desired_state="running",
            op_state="ready",
            last_error=None,
            created_at="2026-10-20T10:00:00+00:00",
        )
    )
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


async def _invite(client: httpx.AsyncClient, body: object = None, user: str = "admin") -> httpx.Response:
    return await client.post(
        f"/api/worlds/{W1}/invites", json=INVITE if body is None else body, headers=appapi_headers(user)
    )


async def test_admin_invites_account(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await _invite(client)
    assert response.status_code == 200
    data = response.json()
    assert data["applied"] is True
    assert data["players"] == [
        {
            "nc_user": "gw-kind",
            "display_name": "Kind (Dev)",
            "player_name": "Kind",
            "password": PASSWORD,
            "via": "user",
        }
    ]
    assert [(i["kind"], i["target"], i["invited_by"]) for i in data["invites"]] == [("user", "gw-kind", "admin")]

    listed = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())
    assert listed.status_code == 200
    assert listed.json()["players"] == data["players"]
    assert listed.json()["applied"] is None


async def test_remove_invite(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    await _invite(client)
    response = await client.post(f"/api/worlds/{W1}/invites/remove", json=INVITE, headers=appapi_headers())
    assert response.status_code == 200
    assert response.json() == {"players": [], "invites": [], "applied": True}
    assert store.world_access(W1) == {}


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "invites"), ("POST", "invites/remove"), ("GET", "players")],
)
async def test_child_gets_403(client: httpx.AsyncClient, service: WorldService, method: str, path: str) -> None:
    del service
    response = await client.request(
        method,
        f"/api/worlds/{W1}/{path}",
        json=INVITE if method == "POST" else None,
        headers=appapi_headers("gw-kind"),
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "user", "target": "gw\x00kind"},
        {"kind": "user", "target": "gw\nkind"},
        {"kind": "user", "target": "gw​kind"},
        {"kind": "user", "target": "x" * 65},
        {"kind": "user", "target": ""},
        {"kind": "user", "target": "   "},
        {"kind": "group", "target": "familie"},
        {"kind": "user", "target": "gw-kind", "admin": True},
        {"target": "gw-kind"},
    ],
)
async def test_invalid_body_is_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, body: object
) -> None:
    del service
    response = await _invite(client, body)
    assert response.status_code == 422
    assert store.list_invites(W1) == []


async def test_unknown_account_is_422(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await _invite(client, {"kind": "user", "target": "gw-aus"})
    assert response.status_code == 422
    assert "deaktiviert" in response.json()["detail"]


async def test_unknown_world_is_404(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post("/api/worlds/bbbbbbbbbbbb/invites", json=INVITE, headers=appapi_headers())
    assert response.status_code == 404
    bad_id = await client.post("/api/worlds/..%2Fx/invites", json=INVITE, headers=appapi_headers())
    assert bad_id.status_code in {404, 422}


async def test_nextcloud_or_secret_down_is_503(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
) -> None:
    del service
    fake_directory.error = DirectoryUnavailableError("weg")
    assert (await _invite(client)).status_code == 503
    fake_directory.error = None
    fake_secret.error = SecretUnavailableError("weg")
    assert (await _invite(client)).status_code == 503
    assert (await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())).status_code == 503
    assert store.list_invites(W1) == []


async def test_nothing_secret_leaks_into_logs_or_errors(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake: FakeProvisioner,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del service
    caplog.set_level(logging.DEBUG)
    error_bodies: list[str] = []
    verifiers: set[str] = set()

    # Erfolgspfade: Einladen, Auflisten, Entfernen, erneut Einladen.
    assert (await _invite(client)).status_code == 200
    verifiers |= set(store.world_access(W1).values())
    assert (await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())).status_code == 200
    removed = await client.post(f"/api/worlds/{W1}/invites/remove", json=INVITE, headers=appapi_headers())
    assert removed.status_code == 200

    # Fehlerpfade.
    for target in ("fremd", "gw-aus"):
        response = await _invite(client, {"kind": "user", "target": target})
        assert response.status_code == 422
        error_bodies.append(response.text)

    def broken(world_id: str, archive: bytes) -> None:
        del world_id, archive
        raise DockerUnavailableError("Der Docker-Proxy ist nicht erreichbar.")

    monkeypatch.setattr(fake, "write_world_files", broken)
    docker_gone = await _invite(client)
    assert docker_gone.status_code == 200
    assert docker_gone.json()["applied"] is False
    verifiers |= set(store.world_access(W1).values())

    fake_secret.error = SecretUnavailableError("weg")
    response = await _invite(client)
    assert response.status_code == 503
    error_bodies.append(response.text)
    fake_secret.error = None

    fake_directory.error = DirectoryUnavailableError("weg")
    response = await _invite(client)
    assert response.status_code == 503
    error_bodies.append(response.text)

    assert verifiers
    forbidden = [PASSWORD, TEST_SECRET.hex(), repr(TEST_SECRET), *verifiers]
    # Auch Teile des Verifiers (Salz, v) dürfen nicht auftauchen.
    forbidden += [part for verifier in verifiers for part in verifier.split("#") if len(part) > 8]
    for needle in forbidden:
        assert needle not in caplog.text
        for body in error_bodies:
            assert needle not in body
    assert caplog.records, "Ohne Log-Einträge wäre der Test wertlos"
