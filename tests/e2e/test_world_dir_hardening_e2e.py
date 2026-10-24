"""AR-23 (D-21): Luanti 5.17.0 mit gehärtetem Weltordner, gegen den echten Docker-Proxy.

Zielrechte: Weltordner root:30000 Modus 1775 (Sticky-Bit, Gruppen-Schreibrecht
für Luanti), worldmods mit allen Unterordnern root:root 0755, Mod-Dateien root
0644, Zugangs- und Regeldatei root 0444. Belegt wird zweierlei:

1. Luanti läuft damit sauber: startet, lässt einen eingeladenen Spieler 10 s
   spielen und schreibt map.sqlite, players.sqlite/auth.sqlite, env_meta.txt
   und das Zählbuch des Zeit-Mods (alle per eigener Temp-Datei und
   Umbenennen); im Containerlog steht kein "Permission denied" und kein
   "ERROR[Main]".
2. Ein Prozess mit Luantis Rechten (uid 30000, keine Capabilities) kann
   Zugangsdatei, Regeldatei und worldmods weder löschen noch umbenennen noch
   überschreiben; eigene Dateien im Weltordner anlegen und umbenennen kann er.

Gegenprobe unabhängig von der Umsetzung (T-06-32): eigener Docker-Client,
eigene Literale, Prüfungen über einen kurzlebigen Hilfscontainer aus dem
gepinnten Luanti-Image (User 30000:30000, Volume eingehängt, ``sh -c``), nie
über exec und nie über den DockerProvisioner. Spielpasswörter werden nie
ausgegeben.
"""

from __future__ import annotations

import io
import tarfile
import time
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

# Eigene Literale, bewusst nicht aus gameworld.provisioner importiert.
IMAGE = "ghcr.io/luanti-org/luanti@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"
DATA = "/var/lib/minetest"
WORLDS = f"{DATA}/.minetest/worlds"
WORLD = f"{WORLDS}/world"
LUANTI = 30000
HOLD = 10.0
JOIN_TIMEOUT = 30.0
STOP_SECONDS = 30
HELPER_SECONDS = 60
# Dateien, die Luanti selbst schreibt (Spielstand) plus das Zählbuch des Zeit-Mods.
WRITTEN_BY_LUANTI = ("map.sqlite", "env_meta.txt", "gameworld_time_used.txt")
PLAYER_DBS = ("players.sqlite", "auth.sqlite")
# Schreibversuche als uid 30000, die scheitern müssen (Name -> Shell-Befehl).
ATTACKS = {
    "rm_access": "rm -f gameworld_access.txt",
    "mv_access": "mv gameworld_access.txt ar23_moved.txt",
    "write_time": "printf x > gameworld_time.txt",
    "replace_time": "printf x > ar23_over.txt && mv -f ar23_over.txt gameworld_time.txt",
    "rm_worldmods": "rm -rf worldmods",
    "new_in_worldmods": "printf x > worldmods/ar23_evil.lua",
    "write_mod": "printf x > worldmods/gameworld_access/init.lua",
}
# Positivkontrolle: so legt Luanti seine Temp-Dateien an.
OWN_FILE = "printf x > ar23_probe.tmp && mv ar23_probe.tmp ar23_probe.txt && rm ar23_probe.txt"
STAT_PATHS = (".", "worldmods", "worldmods/*", "worldmods/*/*", "gameworld_access.txt", "gameworld_time.txt")


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


def _fetch(container: Container, path: str) -> list[tuple[tarfile.TarInfo, bytes | None]]:
    stream, _stat = container.get_archive(path)
    raw = b"".join(stream)
    members: list[tuple[tarfile.TarInfo, bytes | None]] = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        for member in tar.getmembers():
            handle = tar.extractfile(member) if member.isfile() else None
            members.append((member, None if handle is None else handle.read()))
    return members


def _owned_by_root(members: list[tuple[tarfile.TarInfo, bytes | None]], *, dir_mode: int, file_mode: int) -> bytes:
    """Dieselben Einträge als Tar, aber root-eigen mit festen Modi (aktuelle mtime)."""
    buffer = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for member, data in members:
            info = tarfile.TarInfo(member.name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = now
            if member.isdir():
                info.type = tarfile.DIRTYPE
                info.mode = dir_mode
                tar.addfile(info)
            else:
                assert member.isfile(), member.name
                assert data is not None, member.name
                info.mode = file_mode
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _world_dir_tar() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        info = tarfile.TarInfo("world")
        info.type = tarfile.DIRTYPE
        info.uid, info.gid = 0, LUANTI
        info.mode = 0o1775
        info.mtime = int(time.time())
        tar.addfile(info)
    return buffer.getvalue()


def harden_by_hand(container: Container) -> None:
    """Setzt die Zielrechte im Volume der gestoppten Welt per put_archive (eigener Client)."""
    worldmods = _fetch(container, f"{WORLD}/worldmods")
    assert container.put_archive(WORLD, _owned_by_root(worldmods, dir_mode=0o755, file_mode=0o644))
    for name in ("gameworld_access.txt", "gameworld_time.txt"):
        rules = _fetch(container, f"{WORLD}/{name}")
        assert container.put_archive(WORLD, _owned_by_root(rules, dir_mode=0o755, file_mode=0o444))
    assert container.put_archive(WORLDS, _world_dir_tar())


def run_as_luanti(api: docker.DockerClient, volume: str, script: str) -> str:
    """Kurzlebiger Hilfscontainer mit Luantis Rechten; liefert stdout, räumt sich immer weg."""
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
    names = " ".join((*WRITTEN_BY_LUANTI, *PLAYER_DBS))
    out = run_as_luanti(api, volume, f"for f in {names}; do stat -c 'M %n %Y' \"$f\" 2>/dev/null || true; done")
    stamps: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "M":
            stamps[parts[1]] = int(parts[2])
    return stamps


def stat_rights(api: docker.DockerClient, volume: str) -> dict[str, str]:
    """``Pfad -> "uid:gid modus"`` aus ``stat`` im Hilfscontainer (oktal, ohne führende Null)."""
    out = run_as_luanti(api, volume, f"stat -c 'S %n %u:%g %a' {' '.join(STAT_PATHS)}")
    rights: dict[str, str] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] == "S":
            rights[parts[1]] = f"{parts[2]} {parts[3]}"
    return rights


def attack_results(api: docker.DockerClient, volume: str) -> dict[str, int]:
    """Exit-Code je Schreibversuch als uid 30000 plus Positivkontrolle ``own_file``."""
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


def _wait_listening(container: Container, since: int, timeout: float = MTG_READY) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        container.reload()
        if "listening on" in container.logs(since=since).decode("utf-8", errors="replace"):
            return
        if container.status == "exited":
            break
        time.sleep(0.5)
    tail = container.logs(tail=40).decode("utf-8", errors="replace")
    pytest.fail(f"Luanti startet mit gehärtetem Weltordner nicht (Status {container.status}):\n{tail}")


async def test_luanti_runs_and_is_locked_out_with_hardened_world_dir(
    client: httpx.AsyncClient, api: docker.DockerClient
) -> None:
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    name, password = await _invite(client, world_id)
    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.status_code == 200, stopped.text
    await wait_for_status(client, world_id, "stopped", MTG_READY)

    container = _world_container(api, world_id)
    volume = str(container.name)
    harden_by_hand(container)
    assert_hardened(stat_rights(api, volume))
    before = _mtimes(api, volume)

    # Start am Provisioner vorbei: _launch würde worldmods heute wieder Luanti übergeben.
    since = int(time.time()) - 1
    container.start()
    _wait_listening(container, since)
    held = await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, HOLD, JOIN_TIMEOUT))
    assert held["result"] == "held", {key: value for key, value in held.items() if key != "events"}
    container.stop(timeout=STOP_SECONDS)

    log = container.logs().decode("utf-8", errors="replace")
    bad = [line for line in log.splitlines() if "Permission denied" in line or "ERROR[Main]" in line]
    assert not bad, bad

    after = _mtimes(api, volume)
    for written in WRITTEN_BY_LUANTI:
        assert written in after, f"{written} fehlt nach dem Spiel: {after}"
        assert after[written] > before.get(written, 0), (written, before, after)
    assert any(db in after and after[db] > before.get(db, 0) for db in PLAYER_DBS), (before, after)

    # Luanti hat die Rechte nicht verändert (kann es auch nicht), dann die Schreibversuche.
    rights = stat_rights(api, volume)
    print(f"AR-23 Rechte nach dem Spiel: {rights}")
    print(f"AR-23 mtime vorher {before}, nachher {after}")
    assert_hardened(rights)
    codes = attack_results(api, volume)
    print(f"AR-23 Exit-Codes als uid 30000: {codes}")
    assert_luanti_locked_out(codes)
    # Nach den Angriffen: Dateien und Rechte unverändert.
    assert_hardened(stat_rights(api, volume))
