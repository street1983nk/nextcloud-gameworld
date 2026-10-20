"""Live-Nachweis ZUGANG-03: Nur Eingeladene kommen in echte Luanti-Welten (MTG und VoxeLibre).

Der Join-Prober (tests/e2e/luanti_probe.py) spricht das Luanti-Protokoll über
UDP wie ein echter Client. Die Zugangsdatei schreibt hier der Test selbst per
put_archive (DockerProvisioner.write_world_files), um Grenzfälle wie halbe
Dateien zu prüfen; echte Einladungen über die API belegt
test_invite_join_e2e.py (03-03). Seriell, höchstens eine VoxeLibre-Welt gleichzeitig.
"""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import docker.errors
import httpx
import pytest

from gameworld.provisioner.access_mod import ACCESS_HEADER, STATE_FILE, render_access_file
from gameworld.provisioner.archive import build_access_tar
from gameworld.provisioner.client import DockerProvisioner
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers, docker_url
from tests.e2e.luanti_probe import join
from tests.e2e.test_status_e2e import wait_for_status

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

HOST = "127.0.0.1"
MTG_READY = 30.0
VOXELIBRE_READY = 90.0
STATE_TIMEOUT = 10.0
# Feste Testpasswörter für Wegwerfwelten, kein Geheimnis.
MIA_PASSWORD = "Sonne-Baum-42"  # noqa: S105
LEO_PASSWORD = "Tiger-Wolke-17"  # noqa: S105
NOT_INVITED = "nicht eingeladen"
CASE_HINT = "Gro\N{LATIN SMALL LETTER SHARP S}- und Kleinschreibung"
LOCKED = "Zu viele falsche Passw\N{LATIN SMALL LETTER O WITH DIAERESIS}rter"


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        yield client
    finally:
        client.close()


async def _create_running(client: httpx.AsyncClient, preset: str, ready_seconds: float) -> dict[str, object]:
    created = await client.post("/api/worlds", json={"name": "Zugangswelt", "preset": preset}, headers=appapi_headers())
    assert created.status_code == 201, created.text
    body = created.json()
    await wait_for_status(client, str(body["id"]), "running", ready_seconds)
    return body


def _provisioner(app_env: Path) -> DockerProvisioner:
    return DockerProvisioner(docker_url(), WorldStore(app_env / "gameworld.sqlite3").instance_id())


def _write_access(app_env: Path, world_id: str, content: bytes) -> None:
    _provisioner(app_env).write_world_files(world_id, build_access_tar(content))


def _invite(app_env: Path, world_id: str, generation: int, players: dict[str, str]) -> None:
    entries = {name: make_verifier(name, password) for name, password in players.items()}
    _write_access(app_env, world_id, render_access_file(generation, entries))


def read_state(api: docker.DockerClient, world_id: str) -> str | None:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1
    try:
        stream, _ = matches[0].get_archive(STATE_FILE)
    except docker.errors.NotFound:
        return None
    raw = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        member = tar.next()
        assert member is not None
        handle = tar.extractfile(member)
        assert handle is not None
        return handle.read().decode("ascii")


def wait_for_state(api: docker.DockerClient, world_id: str, expected: str) -> None:
    deadline = time.monotonic() + STATE_TIMEOUT
    seen: str | None = None
    while time.monotonic() < deadline:
        seen = read_state(api, world_id)
        if seen == expected:
            return
        time.sleep(0.5)
    pytest.fail(f"State-Datei zeigt nach {STATE_TIMEOUT} s {seen!r} statt Generation {expected}")


def assert_denied(result: dict[str, object], code: str, text: str | None = None) -> None:
    assert result["result"] == "denied", result
    assert result["code"] == code, result
    if text is not None:
        assert text in str(result["reason"]), result


async def test_fresh_world_is_closed_and_invitation_opens_it(client: httpx.AsyncClient, app_env: Path) -> None:
    created = await _create_running(client, "mtg_kreativ", MTG_READY)
    world_id, port = str(created["id"]), int(str(created["port"]))

    # (1) Frische Welt ist zu (A0): Fremde scheitern serverseitig vor der Anmeldung.
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)

    # (2) Mia eingeladen, Datei in die laufende Welt.
    _invite(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)
    # Vor dem ersten Konto "Mia": falsche Schreibweise bekommt den deutschen Hinweis (Pitfall 3).
    assert_denied(join(HOST, port, "mia", MIA_PASSWORD), "CUSTOM_STRING", CASE_HINT)
    hello = join(HOST, port, "Mia")
    assert (hello["result"], hello["auth_mechs"]) == ("hello", 2), hello
    assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    assert_denied(join(HOST, port, "Mia", "Falsch-Wort-11"), "WRONG_PASSWORD")
    # Der Weltschlüssel (default_password) öffnet ein provisioniertes Konto nicht (A9).
    # Seit 03-05 nicht mehr in der API-Antwort, deshalb aus der Datenbank gelesen.
    row = WorldStore(app_env / "gameworld.sqlite3").get_world(world_id)
    assert row is not None
    assert_denied(join(HOST, port, "Mia", row.world_key), "WRONG_PASSWORD")


async def test_half_file_revocation_state_and_restart(
    client: httpx.AsyncClient, app_env: Path, api: docker.DockerClient
) -> None:
    created = await _create_running(client, "mtg_kreativ", MTG_READY)
    world_id, port = str(created["id"]), int(str(created["port"]))
    _invite(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
    assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"

    # (3) Halbe Datei (Kopf ohne Schlusszeile): Der alte Stand bleibt (A6).
    half = f"{ACCESS_HEADER} 2\nLeo {make_verifier('Leo', LEO_PASSWORD)}\n".encode("ascii")
    _write_access(app_env, world_id, half)
    assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    assert_denied(join(HOST, port, "Leo", LEO_PASSWORD), "CUSTOM_STRING", NOT_INVITED)

    # Widerruf: Nur noch Leo (Generation 2); Mia scheitert beim nächsten Join.
    _invite(app_env, world_id, 2, {"Leo": LEO_PASSWORD})
    assert_denied(join(HOST, port, "Mia", MIA_PASSWORD), "CUSTOM_STRING", NOT_INVITED)
    assert join(HOST, port, "Leo", LEO_PASSWORD)["result"] == "auth_accept"

    # (4) Der Mod meldet die geladene Generation in der State-Datei (Takt 5 s).
    wait_for_state(api, world_id, "2")

    # (5) Neustart: _launch schreibt die Datei aus der DB neu. Seit 03-03 ist der
    # Zustand aus der DB maßgeblich (Schema 3): Diese Welt hat keine Einladungen,
    # Leo stand nur in der Test-Datei und ist danach draußen, Generation 0.
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    await wait_for_status(client, world_id, "running", MTG_READY)
    port = int(str(restarted.json()["port"]))
    assert_denied(join(HOST, port, "Leo", LEO_PASSWORD), "CUSTOM_STRING", NOT_INVITED)
    wait_for_state(api, world_id, "0")


async def test_five_wrong_passwords_lock_the_name(client: httpx.AsyncClient, app_env: Path) -> None:
    created = await _create_running(client, "mtg_kreativ", MTG_READY)
    world_id, port = str(created["id"]), int(str(created["port"]))
    _invite(app_env, world_id, 3, {"Leo": LEO_PASSWORD})

    # (6) Fünf Fehlversuche sperren den Namen, danach hilft auch das richtige Passwort nicht (A10).
    for attempt in range(5):
        assert_denied(join(HOST, port, "Leo", f"Falsch-Wort-{attempt}"), "WRONG_PASSWORD")
    assert_denied(join(HOST, port, "Leo", LEO_PASSWORD), "CUSTOM_STRING", LOCKED)


async def test_voxelibre_world_enforces_invitations(client: httpx.AsyncClient, app_env: Path) -> None:
    created = await _create_running(client, "voxelibre_sanft", VOXELIBRE_READY)
    world_id, port = str(created["id"]), int(str(created["port"]))
    try:
        # (7) VoxeLibre registriert keinen eigenen Auth-Handler: dieselbe Durchsetzung greift.
        assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)
        _invite(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
        assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    finally:
        deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
        assert deleted.status_code == 204, deleted.text
