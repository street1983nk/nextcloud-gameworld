"""Live-Nachweis ZUGANG-02/03: Ein per API eingeladenes Konto kommt mit genau den
provisionierten Daten in die laufende Welt, ohne Neustart; Widerruf sperrt wieder.
Dazu 03-04: Gruppe, Passwort neu, Umbenennen und Austritt wirken ohne Neustart.

Nextcloud-Verzeichnis und Geheimnis sind die Fakes aus tests/conftest.py
(gw-kind aktiv, Geheimnis bytes(range(32))); Welt, Mod und Join sind echt.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import docker
import httpx
import pytest

from gameworld.worlds.store import WorldStore
from tests.conftest import FakeDirectory, appapi_headers, docker_url
from tests.e2e.luanti_probe import join
from tests.e2e.test_access_e2e import assert_denied, wait_for_state
from tests.e2e.test_status_e2e import wait_for_status

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

HOST = "127.0.0.1"
MTG_READY = 30.0
NOT_INVITED = "nicht eingeladen"
INVITE = {"kind": "user", "target": "gw-kind"}
GROUP = {"kind": "group", "target": "familie"}
# Passt nie: Das Alphabet der echten Passwörter kennt kein "0" und kein "1".
WRONG_PASSWORD = "0000-1111-0000"  # noqa: S105


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        yield client
    finally:
        client.close()


async def _create_running(client: httpx.AsyncClient, name: str) -> tuple[str, int]:
    created = await client.post("/api/worlds", json={"name": name, "preset": "mtg_kreativ"}, headers=appapi_headers())
    assert created.status_code == 201, created.text
    body = created.json()
    await wait_for_status(client, str(body["id"]), "running", MTG_READY)
    return str(body["id"]), int(str(body["port"]))


def _started_at(api: docker.DockerClient, world_id: str) -> tuple[str, str]:
    [container] = api.containers.list(filters={"label": [f"gameworld.world_id={world_id}"]})
    return str(container.id), str(container.attrs["State"]["StartedAt"])


def _generation(app_env: Path, world_id: str) -> int:
    row = WorldStore(app_env / "gameworld.sqlite3").get_world(world_id)
    assert row is not None
    return row.access_generation


async def test_invited_account_joins_and_revoked_one_cannot(
    client: httpx.AsyncClient, app_env: Path, api: docker.DockerClient
) -> None:
    world_id, port = await _create_running(client, "Einladungswelt")

    # Vor der Einladung: niemand kommt rein.
    assert_denied(join(HOST, port, "Kind"), "CUSTOM_STRING", NOT_INVITED)

    # Einladung über die API; Name und Passwort kommen aus der Antwort.
    invited = await client.post(f"/api/worlds/{world_id}/invites", json=INVITE, headers=appapi_headers())
    assert invited.status_code == 200, invited.text
    body = invited.json()
    assert body["applied"] is True
    [player] = body["players"]
    name, password = str(player["player_name"]), str(player["password"])
    assert name == "Kind"

    # Ohne Neustart: genau diese Daten öffnen die laufende Welt.
    assert join(HOST, port, name, password)["result"] == "auth_accept"
    assert_denied(join(HOST, port, name, WRONG_PASSWORD), "WRONG_PASSWORD")
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)

    # Der Mod hat die Generation aus der Datenbank geladen.
    generation = _generation(app_env, world_id)
    assert generation == 1
    wait_for_state(api, world_id, str(generation))

    # Neustart: Die Datei kommt jetzt aus Schema 3, die Einladung bleibt wirksam.
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    await wait_for_status(client, world_id, "running", MTG_READY)
    port = int(str(restarted.json()["port"]))
    assert join(HOST, port, name, password)["result"] == "auth_accept"
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)
    wait_for_state(api, world_id, str(generation))

    # Widerruf sperrt beim nächsten Join.
    removed = await client.post(f"/api/worlds/{world_id}/invites/remove", json=INVITE, headers=appapi_headers())
    assert removed.status_code == 200, removed.text
    assert removed.json()["applied"] is True
    assert_denied(join(HOST, port, name, password), "CUSTOM_STRING", NOT_INVITED)

    # A2: Ein Name und ein Passwort für alle Welten.
    second_id, _ = await _create_running(client, "Zweite Welt")
    second = await client.post(f"/api/worlds/{second_id}/invites", json=INVITE, headers=appapi_headers())
    assert second.status_code == 200, second.text
    [again] = second.json()["players"]
    assert (again["player_name"], again["password"]) == (name, password)

    # A3: Das Passwort steht nirgends in der Datenbank, der Spielername schon (Positivkontrolle).
    raw = (app_env / "gameworld.sqlite3").read_bytes()
    assert password.encode() not in raw
    assert name.encode() in raw


async def test_group_rotation_rename_and_sync_in_running_world(
    client: httpx.AsyncClient,
    app_env: Path,
    api: docker.DockerClient,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """03-04 gegen eine echte Welt: Gruppe, Passwort neu, Umbenennen, Austritt; nie ein Neustart."""
    world_id, port = await _create_running(client, "Gruppenwelt")
    started = _started_at(api, world_id)

    # Gruppe familie einladen: gw-kind (aktiv) kommt rein, gw-aus (deaktiviert) nicht.
    invited = await client.post(f"/api/worlds/{world_id}/invites", json=GROUP, headers=appapi_headers())
    assert invited.status_code == 200, invited.text
    [player] = invited.json()["players"]
    assert (player["nc_user"], player["via"]) == ("gw-kind", "group:familie")
    name, old_password = str(player["player_name"]), str(player["password"])
    assert join(HOST, port, name, old_password)["result"] == "auth_accept"

    # Passwort neu: das alte scheitert sofort, das neue gilt; kein POST /restart dazwischen.
    rotated = await client.post("/api/players/password", json={"nc_user": "gw-kind"}, headers=appapi_headers())
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["applied"] is True
    new_password = str(rotated.json()["password"])
    assert new_password != old_password
    wait_for_state(api, world_id, str(_generation(app_env, world_id)))
    assert_denied(join(HOST, port, name, old_password), "WRONG_PASSWORD")
    assert join(HOST, port, name, new_password)["result"] == "auth_accept"

    # Umbenennen: der neue Name gilt, der alte ist nicht mehr eingeladen.
    renamed = await client.post(
        "/api/players/name", json={"nc_user": "gw-kind", "player_name": "KindNeu"}, headers=appapi_headers()
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["applied"] is True
    wait_for_state(api, world_id, str(_generation(app_env, world_id)))
    assert join(HOST, port, "KindNeu", new_password)["result"] == "auth_accept"
    assert_denied(join(HOST, port, name, new_password), "CUSTOM_STRING", NOT_INVITED)

    # Austritt aus der Gruppe wirkt beim nächsten Verwalter-Besuch (Drossel hier aus).
    from gameworld.access import service as access_service

    monkeypatch.setattr(access_service, "SYNC_INTERVAL_SECONDS", 0)
    fake_directory.groups["familie"].remove("gw-kind")
    listed = await client.get("/api/worlds", headers=appapi_headers())
    assert listed.status_code == 200
    wait_for_state(api, world_id, str(_generation(app_env, world_id)))
    assert_denied(join(HOST, port, "KindNeu", new_password), "CUSTOM_STRING", NOT_INVITED)

    # Kein Neustart im ganzen Ablauf: derselbe Container, derselbe Startzeitpunkt.
    assert _started_at(api, world_id) == started


async def test_group_member_fetches_own_data_and_joins_without_parent_visit(
    client: httpx.AsyncClient, fake_directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """03-06: Gruppe eingeladen, kein Verwalter-Abgleich mit Mitgliedern; das Kind holt sich
    über /api/my/worlds selbst Zugang und kommt mit genau diesen Daten in die laufende Welt."""
    from gameworld.access import roles
    from gameworld.access.roles import Profile

    async def lookup(uid: str) -> Profile:
        if uid == "admin":
            return Profile(user_id=uid, display_name="Admin", groups=("admin",))
        return Profile(user_id=uid, display_name="Kind (Dev)", groups=("familie",))

    monkeypatch.setattr(roles, "_role_service", roles.RoleService(lookup))
    # Das Verzeichnis kennt kein Mitglied: Nur die Selbstauskunft des Kindes nennt die Gruppe.
    fake_directory.groups["familie"] = []

    world_id, port = await _create_running(client, "Familienwelt")
    invited = await client.post(f"/api/worlds/{world_id}/invites", json=GROUP, headers=appapi_headers())
    assert invited.status_code == 200, invited.text
    assert invited.json()["players"] == []
    assert_denied(join(HOST, port, "Kind"), "CUSTOM_STRING", NOT_INVITED)

    mine = await client.get("/api/my/worlds", headers=appapi_headers("gw-kind"))
    assert mine.status_code == 200, mine.text
    [world] = mine.json()["worlds"]
    assert (world["id"], world["port"], world["status"]) == (world_id, port, "running")
    name, password = str(world["player_name"]), str(world["password"])
    assert join(HOST, port, name, password)["result"] == "auth_accept"
