"""GET /api/my/worlds: nur eigene Welten und Zugangsdaten, lazy Gruppen-Provisionierung (03-06)."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from typing import cast

import anyio
import httpx
import pytest

from gameworld.access import roles
from gameworld.access.accounts import derive_password
from gameworld.access.roles import Profile
from gameworld.access.secret import SecretUnavailableError
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds import service as world_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests.conftest import FAKE_PROFILES, TEST_SECRET, FakeDirectory, StaticSecret, appapi_headers
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
PASSWORD = derive_password(TEST_SECRET, "gw-kind", 0)
NEW_SECRET = bytes(range(2, 34))
FRIEND = "gw-freund"
FRIEND_PASSWORD = derive_password(TEST_SECRET, FRIEND, 0)
KIND_GROUPS: dict[str, tuple[str, ...]] = {"gw-kind": ("familie",)}


def _access_writes(fake: FakeProvisioner) -> list[bytes]:
    """Nur Zugangsdatei-Tars; push_access schreibt seit 04-03 zusätzlich die Regeldatei (push_time)."""
    result: list[bytes] = []
    for _world_id, archive in fake.written:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            if ACCESS_FILE_NAME in tar.getnames():
                result.append(archive)
    return result


def _world(world_id: str, name: str, port: int) -> WorldRow:
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


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "exited")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_world(W1, "Waldwelt", 30015))
    world_store.insert_world(_world(W2, "Bergwelt", 30016))
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service_ = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service_)
    return world_service_


@pytest.fixture
def kind_in_familie(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Selbstauskunft: gw-kind ist Mitglied der Gruppe familie."""
    del app_env

    async def lookup(uid: str) -> Profile:
        display_name, groups = FAKE_PROFILES.get(uid, (uid, ()))
        return Profile(user_id=uid, display_name=display_name, groups=KIND_GROUPS.get(uid, groups))

    monkeypatch.setattr(roles, "_role_service", roles.RoleService(lookup))


async def _invite(client: httpx.AsyncClient, world_id: str, kind: str, target: str) -> None:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": kind, "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text


async def _mine(client: httpx.AsyncClient, user: str = "gw-kind") -> httpx.Response:
    return await client.get("/api/my/worlds", headers=appapi_headers(user))


def _lock_free() -> bool:
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


async def test_child_sees_only_own_world(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "user", "gw-kind")
    response = await _mine(client)
    assert response.status_code == 200
    assert response.json() == {
        "worlds": [
            {
                "id": W1,
                "name": "Waldwelt",
                "status": "running",
                "status_text": response.json()["worlds"][0]["status_text"],
                "host": None,
                "port": 30015,
                "player_name": "Kind",
                "password": PASSWORD,
            }
        ]
    }
    assert "Bergwelt" not in response.text
    assert W2 not in response.text


async def test_answer_has_no_foreign_data(
    client: httpx.AsyncClient, service: WorldService, fake_directory: FakeDirectory
) -> None:
    del service
    fake_directory.users[FRIEND] = ("Freundin Fremd", True)
    await _invite(client, W1, "user", "gw-kind")
    await _invite(client, W1, "user", FRIEND)

    # Positivkontrolle: Die Verwalteransicht kennt beide Konten.
    players = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())
    friend = next(p for p in players.json()["players"] if p["nc_user"] == FRIEND)
    assert friend["password"] == FRIEND_PASSWORD

    response = await _mine(client)
    assert response.status_code == 200
    text = json.dumps(response.json())
    for foreign in (FRIEND, "Freundin", str(friend["player_name"]), FRIEND_PASSWORD):
        assert foreign not in text
    [world] = response.json()["worlds"]
    assert set(world) == {"id", "name", "status", "status_text", "host", "port", "player_name", "password"}
    for field in ("players", "memory_used_bytes", "memory_limit_bytes", "docker_status", "container", "world_key"):
        assert field not in text


async def test_group_invite_provisions_on_own_visit(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake: FakeProvisioner,
    fake_directory: FakeDirectory,
    kind_in_familie: None,
) -> None:
    del service, kind_in_familie
    await _invite(client, W1, "user", "gw-kind")
    # Kein Verwalter-Abgleich mit Mitgliedern: Das Verzeichnis liefert die Gruppe leer.
    fake_directory.groups["familie"] = []
    await _invite(client, W2, "group", "familie")
    assert "gw-kind" not in store.world_access(W2)
    row = store.get_world(W2)
    assert row is not None
    generation = row.access_generation
    pushes = len(_access_writes(fake))

    response = await _mine(client)
    assert response.status_code == 200
    assert [w["id"] for w in response.json()["worlds"]] == [W1, W2]
    assert {w["password"] for w in response.json()["worlds"]} == {PASSWORD}
    assert "gw-kind" in store.world_access(W2)
    row = store.get_world(W2)
    assert row is not None
    assert row.access_generation == generation + 1
    assert len(_access_writes(fake)) == pushes + 1

    # Zweiter Aufruf ändert nichts.
    again = await _mine(client)
    assert again.json() == response.json()
    row = store.get_world(W2)
    assert row is not None
    assert row.access_generation == generation + 1
    assert len(_access_writes(fake)) == pushes + 1


async def test_lazy_provisioning_never_removes(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, kind_in_familie: None
) -> None:
    del service, kind_in_familie
    # gw-kind direkt in W1, Gruppe familie nirgends; Profil hat familie.
    await _invite(client, W1, "user", "gw-kind")
    before = store.world_access(W1)
    response = await _mine(client)
    assert [w["id"] for w in response.json()["worlds"]] == [W1]
    assert store.world_access(W1) == before


async def test_lazy_provisioning_needs_own_group(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    """Ohne familie in der eigenen Selbstauskunft kein Zugang (T-03-40)."""
    del service
    fake_directory.groups["familie"] = []
    await _invite(client, W2, "group", "familie")
    assert "gw-kind" not in store.world_access(W2)
    response = await _mine(client)
    assert response.json() == {"worlds": []}
    assert "gw-kind" not in store.world_access(W2)


async def test_account_without_invite_gets_empty_list(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await _mine(client, "gw-niemand")
    assert response.status_code == 200
    assert response.json() == {"worlds": []}


async def test_host_comes_from_setting(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "user", "gw-kind")
    saved = await client.post("/api/settings", json={"join_host": "192.168.178.20"}, headers=appapi_headers())
    assert saved.status_code == 200
    [world] = (await _mine(client)).json()["worlds"]
    assert world["host"] == "192.168.178.20"

    await client.post("/api/settings", json={"join_host": ""}, headers=appapi_headers())
    [world] = (await _mine(client)).json()["worlds"]
    assert world["host"] is None


async def test_failed_world_shows_fixed_text_to_child(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """AR-24: last_error (Docker-Interna wie Containername mit Instanz-ID) erreicht die Kind-Ansicht nie."""
    del service
    await _invite(client, W1, "user", "gw-kind")
    last_error = f"500 Server Error: Container gw-x-{W1} konnte nicht starten"
    store.update_world(W1, op_state="failed", last_error=last_error)

    response = await _mine(client)
    assert response.status_code == 200
    [world] = response.json()["worlds"]
    assert world["status"] == "error"
    assert world["status_text"] == "Diese Welt hat gerade ein Problem. Sag deinen Eltern Bescheid."
    assert last_error not in response.text
    assert f"gw-x-{W1}" not in response.text

    # Positivkontrolle: Die Verwalter-Ansicht zeigt last_error unverändert.
    admin = await client.get("/api/worlds", headers=appapi_headers())
    assert admin.status_code == 200
    assert last_error in admin.text


async def test_role_failure_is_503(
    client: httpx.AsyncClient, service: WorldService, role_lookup_error: list[str]
) -> None:
    del service
    response = await _mine(client)
    assert response.status_code == 503
    assert role_lookup_error == ["gw-kind"]


async def test_secret_failure_is_503(
    client: httpx.AsyncClient, service: WorldService, fake_secret: StaticSecret
) -> None:
    del service
    fake_secret.error = SecretUnavailableError("weg")
    response = await _mine(client)
    assert response.status_code == 503
    assert "weg" not in response.text


async def test_secret_change_before_my_worlds_no_deadlock(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    del service
    await _invite(client, W1, "user", "gw-kind")
    fake_secret.value = NEW_SECRET
    with anyio.fail_after(5):
        response = await _mine(client)
    assert response.status_code == 200
    [world] = response.json()["worlds"]
    assert world["password"] == derive_password(NEW_SECRET, "gw-kind", 0)
    from gameworld.access.secret import fingerprint

    assert store.get_meta("secret_fingerprint") == fingerprint(NEW_SECRET)
    assert _lock_free()


async def test_secret_change_with_busy_lock_shows_no_wrong_password(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    """WR-02: Neues Geheimnis bei belegter Sperre: 503 statt eines noch nicht gültigen Passworts.

    Die Welten tragen noch die alten Verifier; ein Passwort aus dem neuen
    Geheimnis liefe in die Fehlversuch-Sperre des Welt-Mods. Der 5-s-Poll
    bekommt nach Freigabe der Sperre die neuen Zugangsdaten.
    """
    del service
    await _invite(client, W1, "user", "gw-kind")
    fake_secret.value = NEW_SECRET
    new_password = derive_password(NEW_SECRET, "gw-kind", 0)
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    lock.acquire()
    try:
        with anyio.fail_after(5):
            response = await _mine(client)
        # Keine Zugangsdaten, solange die Verifier nicht zum Geheimnis passen.
        assert response.status_code == 503
        assert new_password not in response.text
        assert PASSWORD not in response.text
        # Nichts neu provisioniert: alter Fingerabdruck, alte Verifier.
        from gameworld.access.secret import fingerprint

        assert store.get_meta("secret_fingerprint") == fingerprint(TEST_SECRET)
    finally:
        lock.release()
    # Sperre frei: Neuprovisionierung läuft, das Kind sieht das gültige Passwort.
    response = await _mine(client)
    assert response.status_code == 200
    [world] = response.json()["worlds"]
    assert world["password"] == new_password
    assert store.get_meta("secret_fingerprint") == fingerprint(NEW_SECRET)
    assert _lock_free()


async def test_busy_lock_never_blocks_my_worlds(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    kind_in_familie: None,
) -> None:
    """Belegte Sperre (etwa ein Erzeugen): Antwort sofort, Provisionierung beim nächsten Abruf."""
    del service, kind_in_familie
    fake_directory.groups["familie"] = []
    await _invite(client, W2, "group", "familie")
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    lock.acquire()
    try:
        with anyio.fail_after(5):
            response = await _mine(client)
        assert response.status_code == 200
        assert "gw-kind" not in store.world_access(W2)
    finally:
        lock.release()
    response = await _mine(client)
    assert [w["id"] for w in response.json()["worlds"]] == [W2]
