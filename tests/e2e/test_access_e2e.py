"""Live proof ZUGANG-03: only invited players get into real Luanti worlds (MTG and VoxeLibre).

The join prober (tests/e2e/luanti_probe.py) speaks the Luanti protocol over
UDP like a real client. The access file is written here by the test itself via
put_archive (DockerProvisioner.write_world_files) to check edge cases such as half
files; real invitations via the API are evidenced by
test_invite_join_e2e.py (03-03). Serial, at most one VoxeLibre world at a time.
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
# Fixed test passwords for throwaway worlds, not a secret.
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

    # (1) A fresh world is closed (A0): strangers fail server-side before login.
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)

    # (2) Mia invited, file into the running world.
    _invite(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
    assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)
    # Before the first account "Mia": a wrong spelling gets the German hint (pitfall 3).
    assert_denied(join(HOST, port, "mia", MIA_PASSWORD), "CUSTOM_STRING", CASE_HINT)
    hello = join(HOST, port, "Mia")
    assert (hello["result"], hello["auth_mechs"]) == ("hello", 2), hello
    assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    assert_denied(join(HOST, port, "Mia", "Falsch-Wort-11"), "WRONG_PASSWORD")
    # The world key (default_password) does not open a provisioned account (A9).
    # Since 03-05 no longer in the API response, hence read from the database.
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

    # (3) Half file (head without a closing line): the old state stays (A6).
    half = f"{ACCESS_HEADER} 2\nLeo {make_verifier('Leo', LEO_PASSWORD)}\n".encode("ascii")
    _write_access(app_env, world_id, half)
    assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    assert_denied(join(HOST, port, "Leo", LEO_PASSWORD), "CUSTOM_STRING", NOT_INVITED)

    # Revocation: only Leo remains (generation 2); Mia fails on the next join.
    _invite(app_env, world_id, 2, {"Leo": LEO_PASSWORD})
    assert_denied(join(HOST, port, "Mia", MIA_PASSWORD), "CUSTOM_STRING", NOT_INVITED)
    assert join(HOST, port, "Leo", LEO_PASSWORD)["result"] == "auth_accept"

    # (4) The mod reports the loaded generation in the state file (tick 5 s).
    wait_for_state(api, world_id, "2")

    # (5) Restart: _launch rewrites the file from the DB. Since 03-03 the state
    # from the DB is authoritative (schema 3): this world has no invitations,
    # Leo was only in the test file and is out afterwards, generation 0.
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

    # (6) Five failed attempts block the name, afterwards even the right password does not help (A10).
    for attempt in range(5):
        assert_denied(join(HOST, port, "Leo", f"Falsch-Wort-{attempt}"), "WRONG_PASSWORD")
    assert_denied(join(HOST, port, "Leo", LEO_PASSWORD), "CUSTOM_STRING", LOCKED)


async def test_voxelibre_world_enforces_invitations(client: httpx.AsyncClient, app_env: Path) -> None:
    created = await _create_running(client, "voxelibre_sanft", VOXELIBRE_READY)
    world_id, port = str(created["id"]), int(str(created["port"]))
    try:
        # (7) VoxeLibre registers no auth handler of its own: the same enforcement applies.
        assert_denied(join(HOST, port, "Fremder"), "CUSTOM_STRING", NOT_INVITED)
        _invite(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
        assert join(HOST, port, "Mia", MIA_PASSWORD)["result"] == "auth_accept"
    finally:
        deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
        assert deleted.status_code == 204, deleted.text
