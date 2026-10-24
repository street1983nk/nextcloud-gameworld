"""Invites-API über ASGI: Rechte, Validierung, Fehlercodes und keine Lecks in Logs oder Fehlern."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import cast

import anyio
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
from tests.conftest import TEST_SALT, TEST_SECRET, FakeDirectory, StaticSecret, appapi_headers, fake_lookup
from tests.test_service_lifecycle import FakeProvisioner

# Fester Zusatz neuer Spielerzeilen, damit die Passwörter hier vorab berechenbar sind.
pytestmark = pytest.mark.usefixtures("fixed_salt")

W1 = "aaaaaaaaaaa1"
PASSWORD = derive_password(TEST_SECRET, "gw-kind", 0, TEST_SALT)
PASSWORD_1 = derive_password(TEST_SECRET, "gw-kind", 1, TEST_SALT)
PASSWORD_2 = derive_password(TEST_SECRET, "gw-kind", 2, TEST_SALT)
INVITE = {"kind": "user", "target": "gw-kind"}
GROUP = {"kind": "group", "target": "familie"}
KIND = {"nc_user": "gw-kind"}


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
        {"kind": "team", "target": "familie"},
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


async def test_secret_change_with_busy_lock_hides_player_passwords(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    """AR-25 (wie WR-02): Neues Geheimnis bei belegter Sperre: 503 statt noch nicht gültiger Passwörter.

    Die Welten tragen noch die alten Verifier; ein Passwort aus dem neuen
    Geheimnis liefe in die Fehlversuch-Sperre des Welt-Mods. Nach Freigabe
    der Sperre provisioniert der nächste Abruf neu und zeigt das gültige.
    """
    del service
    from gameworld.access.secret import fingerprint
    from gameworld.worlds import service as world_service

    assert (await _invite(client)).status_code == 200
    new_secret = bytes(range(2, 34))
    fake_secret.value = new_secret
    new_password = derive_password(new_secret, "gw-kind", 0, TEST_SALT)
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    lock.acquire()
    try:
        with anyio.fail_after(5):
            response = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())
        # Keine Passwörter, solange die Verifier nicht zum Geheimnis passen.
        assert response.status_code == 503
        assert new_password not in response.text
        assert PASSWORD not in response.text
        # Nichts neu provisioniert: alter Fingerabdruck, alte Verifier.
        assert store.get_meta("secret_fingerprint") == fingerprint(TEST_SECRET)
    finally:
        lock.release()
    # Sperre frei: Neuprovisionierung läuft, die Verwalteransicht zeigt das gültige Passwort.
    response = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())
    assert response.status_code == 200
    [player] = response.json()["players"]
    assert player["password"] == new_password
    assert store.get_meta("secret_fingerprint") == fingerprint(new_secret)


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


# 03-04: Gruppen, Passwort neu, Umbenennen, Abgleich beim Verwalter-Besuch


async def test_admin_invites_group(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    response = await _invite(client, GROUP)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [(p["nc_user"], p["via"], p["password"]) for p in data["players"]] == [
        ("gw-kind", "group:familie", PASSWORD)
    ]
    assert [(i["kind"], i["target"]) for i in data["invites"]] == [("group", "familie")]
    assert set(store.world_access(W1)) == {"gw-kind"}
    removed = await client.post(f"/api/worlds/{W1}/invites/remove", json=GROUP, headers=appapi_headers())
    assert removed.status_code == 200
    assert store.world_access(W1) == {}


async def test_unknown_group_is_422(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    response = await _invite(client, {"kind": "group", "target": "fremde-gruppe"})
    assert response.status_code == 422
    assert "Gruppe" in response.json()["detail"]
    assert store.list_invites(W1) == []


async def test_password_reset_gives_new_password(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client)
    response = await client.post("/api/players/password", json=KIND, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert response.json() == {
        "nc_user": "gw-kind",
        "display_name": "Kind (Dev)",
        "player_name": "Kind",
        "password": PASSWORD_1,
        "applied": True,
    }
    assert PASSWORD_1 != PASSWORD
    listed = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())
    assert listed.json()["players"][0]["password"] == PASSWORD_1


async def test_password_reset_unknown_player_is_404(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post("/api/players/password", json={"nc_user": "niemand"}, headers=appapi_headers())
    assert response.status_code == 404


async def _rename(client: httpx.AsyncClient, nc_user: str, player_name: str) -> httpx.Response:
    return await client.post(
        "/api/players/name", json={"nc_user": nc_user, "player_name": player_name}, headers=appapi_headers()
    )


async def test_rename(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    del service
    fake_directory.users["gw-mia"] = ("Mia", True)
    await _invite(client)
    await _invite(client, {"kind": "user", "target": "gw-mia"})

    ok = await _rename(client, "gw-kind", "KindNeu")
    assert ok.status_code == 200, ok.text
    assert (ok.json()["player_name"], ok.json()["password"]) == ("KindNeu", PASSWORD)
    assert set(store.access_entries(W1)) == {"KindNeu", "Mia"}

    assert (await _rename(client, "gw-kind", "mia")).status_code == 409
    for bad in ("singleplayer", "Mia Neu", "Müller", "x" * 21, ""):
        assert (await _rename(client, "gw-kind", bad)).status_code == 422, bad
    assert set(store.access_entries(W1)) == {"KindNeu", "Mia"}
    assert (await _rename(client, "niemand", "Neu")).status_code == 404


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (f"/api/worlds/{W1}/invites", GROUP),
        ("/api/players/password", KIND),
        ("/api/players/name", {"nc_user": "gw-kind", "player_name": "Hack"}),
    ],
)
async def test_child_gets_403_on_new_routes(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, path: str, body: object
) -> None:
    del service
    response = await client.post(path, json=body, headers=appapi_headers("gw-kind"))
    assert response.status_code == 403
    assert store.list_invites(W1) == []
    assert store.get_player("gw-kind") is None


async def test_world_list_syncs_group_membership_throttled(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del service
    from gameworld.access import service as access_service

    clock = [5000.0]
    monkeypatch.setattr(access_service, "monotonic", lambda: clock[0])
    await _invite(client, GROUP)
    assert (await client.get("/api/worlds", headers=appapi_headers())).status_code == 200

    fake_directory.groups["familie"].remove("gw-kind")
    clock[0] += 30
    assert (await client.get("/api/worlds", headers=appapi_headers())).status_code == 200
    assert set(store.world_access(W1)) == {"gw-kind"}, "innerhalb der Drossel kein Abgleich"

    clock[0] += 31
    assert (await client.get("/api/worlds", headers=appapi_headers())).status_code == 200
    assert store.world_access(W1) == {}


async def test_world_list_survives_sync_failure(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
    caplog: pytest.LogCaptureFixture,
) -> None:
    del service
    from gameworld.access import service as access_service

    await _invite(client, GROUP)
    fake_directory.error = DirectoryUnavailableError("weg")
    caplog.set_level(logging.WARNING)
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200
    assert [world["id"] for world in response.json()["worlds"]] == [W1]
    assert set(store.world_access(W1)) == {"gw-kind"}, "Nextcloud weg entfernt niemanden"

    access_service.SYNC_STATE.last = None
    fake_directory.error = None
    fake_secret.error = SecretUnavailableError("weg")
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200
    assert "Abgleich" in caplog.text


async def test_rotation_rename_and_groups_leak_nothing(
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
    fake_directory.users["gw-mia"] = ("Mia", True)

    # Erfolgspfade: Gruppe, direkt, Passwort neu (zweimal), Umbenennen, Abgleich.
    assert (await _invite(client, GROUP)).status_code == 200
    assert (await _invite(client, {"kind": "user", "target": "gw-mia"})).status_code == 200
    verifiers |= set(store.world_access(W1).values())
    for _ in range(2):
        response = await client.post("/api/players/password", json=KIND, headers=appapi_headers())
        assert response.status_code == 200
        verifiers |= set(store.world_access(W1).values())
    assert (await _rename(client, "gw-kind", "KindNeu")).status_code == 200
    verifiers |= set(store.world_access(W1).values())
    assert (await client.get("/api/worlds", headers=appapi_headers())).status_code == 200

    # Fehlerpfade mit Body.
    for path, body, code in [
        ("/api/players/name", {"nc_user": "gw-kind", "player_name": "mia"}, 409),
        ("/api/players/name", {"nc_user": "gw-kind", "player_name": "singleplayer"}, 422),
        ("/api/players/name", {"nc_user": "niemand", "player_name": "Neu"}, 404),
        ("/api/players/password", {"nc_user": "niemand"}, 404),
        (f"/api/worlds/{W1}/invites", {"kind": "group", "target": "fremde-gruppe"}, 422),
    ]:
        response = await client.post(path, json=body, headers=appapi_headers())
        assert response.status_code == code, (path, body)
        error_bodies.append(response.text)

    fake_secret.error = SecretUnavailableError("weg")
    for path, body in [("/api/players/password", KIND), (f"/api/worlds/{W1}/invites", GROUP)]:
        response = await client.post(path, json=body, headers=appapi_headers())
        assert response.status_code == 503
        error_bodies.append(response.text)
    fake_secret.error = None

    fake_directory.error = DirectoryUnavailableError("weg")
    response = await _invite(client, GROUP)
    assert response.status_code == 503
    error_bodies.append(response.text)
    fake_directory.error = None

    def broken(world_id: str, archive: bytes) -> None:
        del world_id, archive
        raise DockerUnavailableError("Der Docker-Proxy ist nicht erreichbar.")

    monkeypatch.setattr(fake, "write_world_files", broken)
    docker_gone = await client.post("/api/players/password", json=KIND, headers=appapi_headers())
    assert docker_gone.status_code == 200
    assert docker_gone.json()["applied"] is False
    verifiers |= set(store.world_access(W1).values())

    passwords = [PASSWORD, PASSWORD_1, PASSWORD_2, derive_password(TEST_SECRET, "gw-kind", 3, TEST_SALT)]
    passwords.append(derive_password(TEST_SECRET, "gw-mia", 0, TEST_SALT))
    forbidden = [*passwords, TEST_SECRET.hex(), repr(TEST_SECRET), *verifiers]
    # Auch Teile der Verifier (Salz, v) dürfen nicht auftauchen.
    forbidden += [part for verifier in verifiers for part in verifier.split("#") if len(part) > 8]
    assert len(verifiers) >= 4
    for needle in forbidden:
        assert needle not in caplog.text
        for body in error_bodies:
            assert needle not in body
    assert caplog.records, "Ohne Log-Einträge wäre der Test wertlos"


# Gruppen-Verwalter über die API (06-02, D-01). Gegenprobe roh per sqlite3.


@pytest.fixture
def teachers(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """lehrkraefte ist Verwalter-Gruppe; gw-lehrer verwaltet damit, ohne NC-Admin zu sein."""
    del app_env
    from gameworld.access import roles

    async def groups() -> frozenset[str]:
        return frozenset({"admin", "lehrkraefte"})

    monkeypatch.setattr(roles, "_role_service", roles.RoleService(fake_lookup, groups))


def _raw_rows(app_env: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    connection = sqlite3.connect(app_env / "gameworld.sqlite3")
    try:
        invites = connection.execute("SELECT world_id, kind, target FROM invites ORDER BY kind, target").fetchall()
        access = connection.execute("SELECT world_id, nc_user FROM world_access ORDER BY nc_user").fetchall()
    finally:
        connection.close()
    return invites, access


@pytest.mark.usefixtures("teachers")
async def test_teacher_invite_outside_own_groups_is_403_without_db_change(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner, app_env: Path
) -> None:
    del service
    before = _raw_rows(app_env)
    written = len(fake.written)
    response = await _invite(client, {"kind": "user", "target": "gw-kind-out"}, user="gw-lehrer")
    assert response.status_code == 403
    assert response.json() == {"detail": "Dieses Konto ist in keiner deiner Gruppen."}
    response = await _invite(client, {"kind": "group", "target": "familie"}, user="gw-lehrer")
    assert response.status_code == 403
    assert response.json() == {"detail": "Diese Gruppe gehört nicht zu deinen Gruppen."}
    assert _raw_rows(app_env) == before
    assert len(fake.written) == written


@pytest.mark.usefixtures("teachers")
async def test_teacher_invites_own_class_member(
    client: httpx.AsyncClient, service: WorldService, fake_directory: FakeDirectory, app_env: Path
) -> None:
    del service
    response = await _invite(client, {"kind": "user", "target": "gw-kind-k"}, user="gw-lehrer")
    assert response.status_code == 200
    body = response.json()
    assert [(p["nc_user"], p["display_name"]) for p in body["players"]] == [("gw-kind-k", "gw-kind-k")]
    assert _raw_rows(app_env)[1] == [(W1, "gw-kind-k")]
    assert all(acting != "gw-lehrer" for acting, _uid in fake_directory.calls)


@pytest.mark.usefixtures("teachers")
async def test_teacher_world_list_sync_removes_nothing(
    client: httpx.AsyncClient, service: WorldService, fake_directory: FakeDirectory, app_env: Path
) -> None:
    """Dashboard als Lehrer: Nextcloud antwortet auf jedes Einzelkonto mit 404, kein Zugang fällt weg."""
    del service
    assert (await _invite(client, {"kind": "user", "target": "gw-kind-out"})).status_code == 200
    assert (await _invite(client, {"kind": "group", "target": "klasse"})).status_code == 200
    from gameworld.access import service as access_service

    access_service.SYNC_STATE.last = None
    before = _raw_rows(app_env)
    fake_directory.users.clear()
    response = await client.get("/api/worlds", headers=appapi_headers("gw-lehrer"))
    assert response.status_code == 200
    assert access_service.SYNC_STATE.last is not None  # der Abgleich lief wirklich
    assert _raw_rows(app_env) == before


async def test_actor_lookup_failure_is_503(
    client: httpx.AsyncClient, service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rolle aus dem Cache, Profil danach nicht lesbar: 503 statt Einladung ohne Umfang."""
    del service
    from gameworld.access import roles
    from gameworld.access.roles import RoleService, RoleUnavailableError

    async def failing_profile(self: RoleService, uid: str) -> roles.Profile:
        raise RoleUnavailableError(uid)

    async def verwalter(self: RoleService, uid: str) -> str:
        return roles.ROLE_VERWALTER

    monkeypatch.setattr(RoleService, "role", verwalter)
    monkeypatch.setattr(RoleService, "profile", failing_profile)
    response = await _invite(client)
    assert response.status_code == 503
