"""AR-23 (D-21, 06-07): Luanti 5.17.0 in the hardened world directory, against the real Docker proxy.

First a spike (permissions set by hand, commit 7032359), now lasting proof
for the real creation: a world created via the API has the world directory
root:30000 mode 1775 (sticky bit, group write permission for Luanti), worldmods
with all subfolders root:root 0755, mod files root 0644, access and
rules file root 0444; world.mt stays with Luanti. Two things are proven:

1. Luanti runs cleanly with it: starts via the normal start path, lets an
   invited player play for 10 s and writes map.sqlite,
   players.sqlite/auth.sqlite, env_meta.txt and the ledger of the time mod
   (via its own temp file and rename); the container log has no
   "Permission denied" and no "ERROR[Main]".
2. A process with Luanti's rights (uid 30000, no capabilities) can neither delete
   nor rename nor overwrite the access file, rules file and worldmods; it can
   create and rename its own files in the world directory.

Counter-check independent of the implementation (T-06-32): own Docker client,
own literals, checks via a short-lived helper container from the
pinned Luanti image (user 30000:30000, volume mounted, ``sh -c``), never
via exec and never via the DockerProvisioner. Game passwords are never
printed.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import partial

import anyio.to_thread
import docker
import httpx
import pytest
from docker.models.containers import Container

from tests.conftest import appapi_headers, docker_url
from tests.e2e.luanti_probe import session
from tests.e2e.test_status_e2e import wait_for_status
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

# Own literals, deliberately not imported from gameworld.provisioner.
IMAGE = "ghcr.io/luanti-org/luanti@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"
DATA = "/var/lib/minetest"
WORLD = f"{DATA}/.minetest/worlds/world"
LUANTI = 30000
HOLD = 10.0
JOIN_TIMEOUT = 30.0
HELPER_SECONDS = 60
# Files that Luanti writes itself (save game) plus the ledger of the time mod.
WRITTEN_BY_LUANTI = ("map.sqlite", "env_meta.txt", "gameworld_time_used.txt")
PLAYER_DBS = ("players.sqlite", "auth.sqlite")
# Write attempts as uid 30000 that must fail (name -> shell command).
ATTACKS = {
    "rm_access": "rm -f gameworld_access.txt",
    "mv_access": "mv gameworld_access.txt ar23_moved.txt",
    "write_time": "printf x > gameworld_time.txt",
    "replace_time": "printf x > ar23_over.txt && mv -f ar23_over.txt gameworld_time.txt",
    "rm_worldmods": "rm -rf worldmods",
    "new_in_worldmods": "printf x > worldmods/ar23_evil.lua",
    "write_mod": "printf x > worldmods/gameworld_access/init.lua",
}
# Positive control: this is how Luanti creates its temp files.
OWN_FILE = "printf x > ar23_probe.tmp && mv ar23_probe.tmp ar23_probe.txt && rm ar23_probe.txt"
STAT_PATHS = (
    ".",
    "worldmods",
    "worldmods/*",
    "worldmods/*/*",
    "gameworld_access.txt",
    "gameworld_time.txt",
    "world.mt",
)


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=120)
    try:
        yield client
    finally:
        client.close()


def _world_container(api: docker.DockerClient, world_id: str) -> Container:
    [container] = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    container.reload()
    return container


def run_as_luanti(api: docker.DockerClient, volume: str, script: str) -> str:
    """Short-lived helper container with Luanti's rights; returns stdout, always cleans itself up."""
    helper = api.containers.create(
        IMAGE,
        entrypoint=["sh", "-c"],
        command=[f"cd {WORLD} && {{ {script}; }}"],
        user=f"{LUANTI}:{LUANTI}",
        volumes={volume: {"bind": DATA, "mode": "rw"}},
        network_mode="none",
        read_only=True,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        mem_limit="64m",
        labels={"gameworld.spike": "ar23"},
    )
    try:
        helper.start()
        result = helper.wait(timeout=HELPER_SECONDS)
        output = helper.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        assert result["StatusCode"] == 0, output
        return output
    finally:
        helper.remove(force=True)


def _mtimes(api: docker.DockerClient, volume: str) -> dict[str, int]:
    names = " ".join((*WRITTEN_BY_LUANTI, *PLAYER_DBS, "world.mt"))
    out = run_as_luanti(api, volume, f"for f in {names}; do stat -c 'M %n %Y' \"$f\" 2>/dev/null || true; done")
    stamps: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "M":
            stamps[parts[1]] = int(parts[2])
    return stamps


def stat_rights(api: docker.DockerClient, volume: str) -> dict[str, str]:
    """``path -> "uid:gid mode"`` from ``stat`` in the helper container (octal, without a leading zero)."""
    out = run_as_luanti(api, volume, f"stat -c 'S %n %u:%g %a' {' '.join(STAT_PATHS)}")
    rights: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "S":
            rights[parts[1]] = f"{parts[2]} {parts[3]}"
    return rights


def attack_results(api: docker.DockerClient, volume: str) -> dict[str, int]:
    """Exit code per write attempt as uid 30000 plus positive control ``own_file``."""
    steps = [f'( {command} ) </dev/null >/dev/null 2>&1; echo "R {name} $?"' for name, command in ATTACKS.items()]
    steps.append(f'( {OWN_FILE} ) >/dev/null 2>&1; echo "R own_file $?"')
    steps.append("rm -f ar23_over.txt")
    out = run_as_luanti(api, volume, "; ".join(steps))
    codes: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "R":
            codes[parts[1]] = int(parts[2])
    return codes


def assert_hardened(rights: dict[str, str]) -> None:
    assert rights["."] == f"0:{LUANTI} 1775", rights
    assert rights["worldmods"] == "0:0 755", rights
    mods = {path: value for path, value in rights.items() if path.startswith("worldmods/")}
    mod_dirs = {path: value for path, value in mods.items() if path.count("/") == 1}
    mod_files = {path: value for path, value in mods.items() if path.count("/") == 2}
    assert len(mod_dirs) >= 3, rights
    assert mod_files, rights
    assert all(value == "0:0 755" for value in mod_dirs.values()), mod_dirs
    assert all(value == "0:0 644" for value in mod_files.values()), mod_files
    assert rights["gameworld_access.txt"] == "0:0 444", rights
    assert rights["gameworld_time.txt"] == "0:0 444", rights
    assert rights["world.mt"] == f"{LUANTI}:{LUANTI} 644", rights


def assert_luanti_locked_out(codes: dict[str, int]) -> None:
    assert set(codes) == {*ATTACKS, "own_file"}, codes
    succeeded = [name for name in ATTACKS if codes[name] == 0]
    assert not succeeded, f"Als uid 30000 gelungen: {succeeded}"
    assert codes["own_file"] == 0, "Luanti kann im Weltordner keine eigene Datei anlegen und umbenennen"


async def _invite(client: httpx.AsyncClient, world_id: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": "gw-kind"}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    [player] = response.json()["players"]
    return str(player["player_name"]), str(player["password"])


async def _stop(client: httpx.AsyncClient, world_id: str) -> None:
    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.status_code == 200, stopped.text
    await wait_for_status(client, world_id, "stopped", MTG_READY)


async def test_new_world_is_hardened_and_luanti_still_writes(
    client: httpx.AsyncClient, api: docker.DockerClient
) -> None:
    world_id, _ = await create_running_world(client, "mtg_kreativ", MTG_READY)
    name, password = await _invite(client, world_id)
    await _stop(client, world_id)

    volume = str(_world_container(api, world_id).name)
    # Real creation, nothing set by hand.
    assert_hardened(stat_rights(api, volume))
    before = _mtimes(api, volume)

    # Normal start path (_launch rewrites mods, access and rules file).
    started = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    assert started.status_code == 200, started.text
    world = await wait_for_status(client, world_id, "running", MTG_READY)
    port = int(str(world["port"]))
    held = await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, HOLD, JOIN_TIMEOUT))
    assert held["result"] == "held", {key: value for key, value in held.items() if key != "events"}
    await _stop(client, world_id)

    log = _world_container(api, world_id).logs().decode("utf-8", errors="replace")
    bad = [line for line in log.splitlines() if "Permission denied" in line or "ERROR[Main]" in line]
    assert not bad, bad

    after = _mtimes(api, volume)
    print(f"AR-23 mtime vorher {before}, nachher {after}")
    for written in WRITTEN_BY_LUANTI:
        assert written in after, f"{written} fehlt nach dem Spiel: {after}"
        assert after[written] > before.get(written, 0), (written, before, after)
    assert any(db in after and after[db] > before.get(db, 0) for db in PLAYER_DBS), (before, after)

    # After the start (worldmods freshly applied) still hardened, then the write attempts.
    rights = stat_rights(api, volume)
    print(f"AR-23 Rechte nach dem Spiel: {rights}")
    assert_hardened(rights)
    codes = attack_results(api, volume)
    print(f"AR-23 Exit-Codes als uid 30000: {codes}")
    assert_luanti_locked_out(codes)
    # After the attacks: files and permissions unchanged.
    assert_hardened(stat_rights(api, volume))
