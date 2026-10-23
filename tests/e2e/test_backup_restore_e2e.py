"""Live-Nachweis BACKUP-01/02 gegen den echten Docker-Proxy (Erfolgskriterien 2 und 3).

Roundtrip: Mia spielt vor der Sicherung, Leo danach; dann wird die Welt
zerstört (Zufallsbytes als map.sqlite plus ein heißes map.sqlite-journal) und aus
der ersten Sicherung wiederhergestellt. Die Gegenprobe läuft über ein
unabhängiges Muster (tests/e2e/backup_helpers.py): eigener Docker-Client für
Container-Zustand, Ereignisse und Dateien, Python-sqlite3 nur lesend; nie über
den DockerProvisioner der ExApp. Byte-Gleichheit von map.sqlite wird bewusst
nicht geprüft (RESEARCH A8), wohl aber Integrität und Blockzahl.

Negativfälle: manipulierte Sicherungen mit korrektem eigenen Nachweis (damit
die Inhaltsprüfung und nicht der Hash greift) und eine nachträglich getauschte
Datei (Hash passt nicht) lassen die Welt unverändert laufen. Code aus einer
Sicherung (worldmods/x/init.lua) wird verworfen, nie eingespielt (05-06).

Absturz: Der Prozess "stirbt" im Tausch nach mark_swap und remove_world; ein
neuer Dienst auf derselben Datenbank (boot_reconcile plus recover_jobs) zeigt
RESTORE_INTERRUPTED, nicht delete-only, und ein erneuter Restore gelingt.
Seriell, Kreativ-Preset wegen des RAM-Bedarfs. Spielpasswörter werden nie ausgegeben.
"""

from __future__ import annotations

import hashlib
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import anyio
import anyio.to_thread
import docker
import httpx
import pytest
from docker.models.containers import Container

from gameworld.api import worlds as worlds_api
from gameworld.backup import files as files_module
from gameworld.backup.service import BackupService
from gameworld.worlds.service import RESTORE_INTERRUPTED, WorldService, WorldView
from gameworld.worlds.store import BackupRow, WorldStore
from tests.conftest import FakeDirectory, appapi_headers, docker_url
from tests.e2e.backup_helpers import (
    LocalFolderFiles,
    block_count,
    copy_out,
    extract_member,
    forged_backup,
    integrity_ok,
    manifest_of,
    member_names,
    players_in,
    put_files,
)
from tests.e2e.luanti_probe import session
from tests.e2e.test_reconcile_e2e import fresh_service
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

PRESET = "mtg_kreativ"
ADMIN = "admin"
HOLD = 5.0
JOIN_TIMEOUT = 30.0
READY_TIMEOUT = 60.0
# Eigene Literale (unabhängig von den Konstanten der Umsetzung).
WORLD_PATH = "/var/lib/minetest/.minetest/worlds/world"
LEDGER = "gameworld_time_used.txt"
MANIFEST = "gameworld-backup.json"
TEXT_TAMPERED = "Die Sicherung wurde verändert und wird nicht eingespielt."
TEXT_RESTORE_INTERRUPTED_JOB = "Das Wiederherstellen wurde durch einen Neustart des Servers unterbrochen."
NEGATIVE_CASES = ("traversal", "symlink", "foreign_preset", "swapped")


class SimulatedCrash(BaseException):
    """Prozessabbruch mitten im Tausch: keine Exception, damit kein Fehlerpfad sie fängt."""


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=120)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def files(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> LocalFolderFiles:
    fake = LocalFolderFiles(app_env / "files")
    monkeypatch.setattr(files_module, "_files", fake)
    return fake


@pytest.fixture
def kids(fake_directory: FakeDirectory) -> None:
    fake_directory.users["gw-mia"] = ("Mia", True)
    fake_directory.users["gw-leo"] = ("Leo", True)


def _backups(service: WorldService, app_env: Path) -> BackupService:
    return BackupService(service, app_env / "tmp")


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


async def _play(port: int, credentials: tuple[str, str]) -> None:
    """Spielstandwirksamer Beitritt: bis on_joinplayer, HOLD Sekunden halten, dann trennen."""
    name, password = credentials
    result = await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, HOLD, JOIN_TIMEOUT))
    assert result["result"] == "held", {key: value for key, value in result.items() if key != "events"}


def _container(api: docker.DockerClient, world_id: str) -> Container:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1, f"erwartet genau einen Container für {world_id}, gefunden {len(matches)}"
    container = matches[0]
    container.reload()
    return container


def _containers(api: docker.DockerClient, world_id: str) -> int:
    return len(api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]}))


def _volume_name(container: Container) -> str:
    names = [str(mount["Name"]) for mount in container.attrs["Mounts"] if mount.get("Type") == "volume"]
    assert len(names) == 1, names
    return names[0]


def _started_at(container: Container) -> str:
    return str((container.attrs.get("State") or {}).get("StartedAt") or "")


async def _view(service: WorldService, world_id: str) -> WorldView:
    return {view.id: view for view in await service.list_worlds()}[world_id]


async def _wait_status(service: WorldService, world_id: str, expected: str, within: float = READY_TIMEOUT) -> WorldView:
    deadline = time.monotonic() + within
    seen: list[str] = []
    while time.monotonic() < deadline:
        view = await _view(service, world_id)
        if not seen or seen[-1] != view.status:
            seen.append(view.status)
        if view.status == expected:
            return view
        await anyio.sleep(0.5)
    pytest.fail(f"Welt {world_id} ist nach {within} s nicht {expected}, gesehen: {seen}")


async def _boot(service: WorldService) -> None:
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if await service.boot_reconcile():
            return
        await anyio.sleep(0.2)
    pytest.fail("boot_reconcile kam nicht zum Zug")


def _store(app_env: Path) -> WorldStore:
    return WorldStore(app_env / "gameworld.sqlite3")


def _job(app_env: Path, world_id: str) -> tuple[str, str, str | None]:
    job = _store(app_env).get_backup_job(world_id)
    assert job is not None, "kein Auftrag eingetragen"
    return job.kind, job.state, job.message


def _first_backup(app_env: Path, world_id: str) -> BackupRow:
    rows = [row for row in _store(app_env).backups_for(ADMIN, world_id) if row.kind == "backup"]
    assert rows, "keine Sicherung mit Nachweis"
    return rows[-1]


def _container_events(api: docker.DockerClient, container_id: str, since: int, until: int) -> list[str]:
    """Aktionen der Docker-Ereignisse dieses Containers in zeitlicher Folge (eigener Client)."""
    events: Any = api.events(since=since, until=until, decode=True, filters={"container": container_id})
    return [str(event.get("Action") or event.get("status")) for event in events if event.get("Type") == "container"]


async def _backup_watched(
    service: WorldService,
    backups: BackupService,
    api: docker.DockerClient,
    world_id: str,
    monkeypatch: pytest.MonkeyPatch,
    app_env: Path,
) -> list[str]:
    """Sicherung mit Bestätigung; liefert den Container-Zustand, den der eigene Client beim Snapshot sah."""
    seen: list[str] = []
    original: Callable[..., Any] = service.provisioner.snapshot_to

    def watched(target: str, write: Callable[..., Any]) -> Any:
        seen.append(str(_container(api, target).status))
        return original(target, write)

    monkeypatch.setattr(service.provisioner, "snapshot_to", watched)
    try:
        await backups.start_backup(world_id, ADMIN, confirm_disconnect=True)
        await backups.drain()
    finally:
        monkeypatch.setattr(service.provisioner, "snapshot_to", original)
    assert _job(app_env, world_id)[:2] == ("backup", "ok"), _job(app_env, world_id)
    return seen


# Roundtrip (Erfolgskriterium 3) mit Snapshot am gestoppten Container (Erfolgskriterium 2)


async def test_backup_restore_roundtrip(
    client: httpx.AsyncClient,
    app_env: Path,
    api: docker.DockerClient,
    files: LocalFolderFiles,
    kids: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del kids
    world_id, port = await create_running_world(client, PRESET, MTG_READY)
    service = worlds_api.get_service()
    backups = _backups(service, app_env)
    mia = await _invite(client, world_id, "gw-mia")
    leo = await _invite(client, world_id, "gw-leo")
    assert (mia[0], leo[0]) == ("Mia", "Leo")

    # (1) Mia spielt, dann Sicherung; der eigene Client belegt den gestoppten Container.
    await _play(port, mia)
    container_id = str(_container(api, world_id).id)
    since = int(time.time()) - 30
    seen = await _backup_watched(service, backups, api, world_id, monkeypatch, app_env)
    assert seen == ["exited"], f"Snapshot sah den Container im Zustand {seen}"
    actions = _container_events(api, container_id, since, int(time.time()) + 2)
    assert "die" in actions, actions
    died = actions.index("die")
    restarted = actions.index("start", died)
    assert "archive-path" in actions[died:restarted], f"kein Lesen zwischen Stopp und Start: {actions}"
    await _wait_status(service, world_id, "running")

    # Archiv in der Attrappe: Manifest und Karte ja, Mod-Laufzeitdateien und worldmods nein.
    [(uid, backup_path)] = files.uploads
    assert uid == ADMIN
    archive = files.read_bytes(ADMIN, backup_path)
    names = member_names(archive)
    assert MANIFEST in names, names
    assert "world/map.sqlite" in names, names
    assert not [n for n in names if n.rsplit("/", 1)[-1].startswith("gameworld_")], names
    assert not [n for n in names if n == "world/worldmods" or n.startswith("world/worldmods/")], names
    manifest = manifest_of(archive)
    assert (manifest["world_id"], manifest["preset"]) == (world_id, PRESET)
    backup_dir = tmp_path / "backup"
    blocks_in_backup = block_count(extract_member(archive, "world/map.sqlite", backup_dir / "map.sqlite"))
    assert blocks_in_backup > 0
    assert "Mia" in players_in(extract_member(archive, "world/players.sqlite", backup_dir / "players.sqlite"))

    # (2) Leo spielt danach, dann Zerstörung bei gestoppter Welt über den eigenen Client.
    await _play(port, leo)
    await service.stop_world(world_id)
    stopped = _container(api, world_id)
    assert stopped.status == "exited"
    put_files(
        api,
        str(stopped.id),
        WORLD_PATH,
        {"map.sqlite": os.urandom(64 * 1024), "map.sqlite-journal": os.urandom(4096)},
    )
    broken_dir = tmp_path / "broken"
    broken = copy_out(api, str(stopped.id), WORLD_PATH, broken_dir)
    assert not integrity_ok(broken / "map.sqlite"), "Positivkontrolle: die Karte ist wirklich kaputt"
    assert (broken / "map.sqlite-journal").exists()
    assert "Leo" in players_in(broken / "players.sqlite")
    ledger_before = (broken / LEDGER).read_bytes()

    # (3) Wiederherstellen der ersten Sicherung.
    proof = _first_backup(app_env, world_id)
    assert proof.path == backup_path
    await backups.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=True)
    await backups.drain()
    assert _job(app_env, world_id)[:2] == ("restore", "ok"), _job(app_env, world_id)

    # (4) Gegenprobe vor dem ersten Start: eigener Client, sqlite3 nur lesend.
    restored_container = _container(api, world_id)
    assert restored_container.status in {"created", "exited"}, restored_container.status
    after = copy_out(api, str(restored_container.id), WORLD_PATH, tmp_path / "after")
    players = players_in(after / "players.sqlite")
    assert "Mia" in players, players
    assert "Leo" not in players, players
    assert integrity_ok(after / "map.sqlite")
    assert block_count(after / "map.sqlite") == blocks_in_backup
    assert not (after / "map.sqlite-journal").exists()
    assert (after / LEDGER).read_bytes() == ledger_before
    safety = [path for owner, path in files.uploads if owner == ADMIN and "vor-restore" in path]
    assert len(safety) == 1, files.uploads
    safety_archive = files.read_bytes(ADMIN, safety[0])
    safety_players = extract_member(safety_archive, "world/players.sqlite", tmp_path / "safety" / "players.sqlite")
    assert "Leo" in players_in(safety_players)

    # (5) Die wiederhergestellte Welt läuft und Mia kommt hinein.
    await service.start_world(world_id)
    await _wait_status(service, world_id, "running")
    await _play(port, mia)


# Manipulierte Sicherungen (T-05-40): die Welt bleibt unverändert und läuft


async def _world_with_backup(
    client: httpx.AsyncClient, app_env: Path, api: docker.DockerClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, int, WorldService, BackupService]:
    world_id, port = await create_running_world(client, PRESET, MTG_READY)
    service = worlds_api.get_service()
    backups = _backups(service, app_env)
    await _backup_watched(service, backups, api, world_id, monkeypatch, app_env)
    await _wait_status(service, world_id, "running")
    return world_id, port, service, backups


def _register_forged(app_env: Path, files: LocalFolderFiles, world_id: str, folder: str, data: bytes, kind: str) -> int:
    """Gefälschte Datei mit korrektem eigenen Nachweis (SHA passt), damit die Inhaltsprüfung greift."""
    entry = files.put(ADMIN, f"{folder}/gefaelscht-{kind}.tar.gz", data)
    _store(app_env).add_backup(
        BackupRow(
            file_id=entry.file_id,
            owner_uid=ADMIN,
            world_id=world_id,
            path=entry.path,
            name=entry.name,
            size=entry.size,
            sha256=hashlib.sha256(data).hexdigest(),
            preset=PRESET,
            kind="backup",
            created_at=datetime.now(UTC).isoformat(),
        )
    )
    return entry.file_id


@pytest.mark.parametrize("case", NEGATIVE_CASES)
async def test_manipulated_backup_is_rejected(
    case: str,
    client: httpx.AsyncClient,
    app_env: Path,
    api: docker.DockerClient,
    files: LocalFolderFiles,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    world_id, _port, service, backups = await _world_with_backup(client, app_env, api, monkeypatch)
    proof = _first_backup(app_env, world_id)
    folder = proof.path.rsplit("/", 1)[0]
    real_map = extract_member(files.read_bytes(ADMIN, proof.path), "world/map.sqlite", tmp_path / "map.sqlite")
    if case == "swapped":
        # Nachträglich in Files getauscht: gleiche Größe, anderer Inhalt, der Nachweis passt nicht mehr.
        original = bytearray(files.read_bytes(ADMIN, proof.path))
        original[len(original) // 2] ^= 0xFF
        files.replace_bytes(ADMIN, proof.path, bytes(original))
        file_id = proof.file_id
    else:
        forged = forged_backup(case, world_id, PRESET, map_bytes=real_map.read_bytes())
        file_id = _register_forged(app_env, files, world_id, folder, forged, case)

    before = _container(api, world_id)
    before_id, before_volume, before_started = str(before.id), _volume_name(before), _started_at(before)
    uploads_before = list(files.uploads)

    await backups.start_restore(world_id, ADMIN, file_id, confirm=True, confirm_disconnect=True)
    await backups.drain()

    kind, state, message = _job(app_env, world_id)
    assert (kind, state) == ("restore", "failed"), (kind, state, message)
    if case == "swapped":
        assert message == TEXT_TAMPERED
    after = _container(api, world_id)
    assert str(after.id) == before_id
    assert _volume_name(after) == before_volume
    assert after.status == "running"
    assert _started_at(after) == before_started, "die Welt wurde nie gestoppt"
    assert files.uploads == uploads_before, "keine vor-restore-Sicherung bei abgelehnter Datei"
    view = await _wait_status(service, world_id, "running", within=10.0)
    assert view.op_state == "ready"
    assert view.delete_only is False


async def test_lua_in_backup_is_dropped_not_installed(
    client: httpx.AsyncClient,
    app_env: Path,
    api: docker.DockerClient,
    files: LocalFolderFiles,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Code aus einer Sicherung landet nie in der Welt (05-06: verworfen statt abgelehnt)."""
    world_id, _port, service, backups = await _world_with_backup(client, app_env, api, monkeypatch)
    proof = _first_backup(app_env, world_id)
    folder = proof.path.rsplit("/", 1)[0]
    real_map = extract_member(files.read_bytes(ADMIN, proof.path), "world/map.sqlite", tmp_path / "map.sqlite")
    forged = forged_backup("lua", world_id, PRESET, map_bytes=real_map.read_bytes())
    file_id = _register_forged(app_env, files, world_id, folder, forged, "lua")

    await backups.start_restore(world_id, ADMIN, file_id, confirm=True, confirm_disconnect=True)
    await backups.drain()
    assert _job(app_env, world_id)[:2] == ("restore", "ok"), _job(app_env, world_id)
    await _wait_status(service, world_id, "running")

    restored = _container(api, world_id)
    world = copy_out(api, str(restored.id), WORLD_PATH, tmp_path / "after")
    assert not (world / "worldmods" / "x").exists(), "fremder Code wurde eingespielt"
    assert not list(world.rglob("x/init.lua"))
    assert (world / "worldmods").is_dir(), "Positivkontrolle: eigene Mods frisch provisioniert"
    assert integrity_ok(world / "map.sqlite")


# Absturz mitten im Tausch (T-05-33, D-15)


async def test_crash_during_swap_recovers_as_restore_interrupted(
    client: httpx.AsyncClient,
    app_env: Path,
    api: docker.DockerClient,
    files: LocalFolderFiles,
    kids: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    del kids, files
    world_id, port = await create_running_world(client, PRESET, MTG_READY)
    crashed = worlds_api.get_service()
    backups = _backups(crashed, app_env)
    mia = await _invite(client, world_id, "gw-mia")
    await _play(port, mia)
    await _backup_watched(crashed, backups, api, world_id, monkeypatch, app_env)
    await _wait_status(crashed, world_id, "running")
    proof = _first_backup(app_env, world_id)

    # Fehlerinjektion: Nach mark_swap und remove_world stirbt der Prozess beim Neuaufbau.
    removed: list[str] = []
    original_remove = crashed.provisioner.remove_world

    def remove_world(target: str, *, keep_volume: bool) -> None:
        removed.append(target)
        original_remove(target, keep_volume=keep_volume)

    def create_world_container(*_args: object, **_kwargs: object) -> str:
        raise SimulatedCrash

    monkeypatch.setattr(crashed.provisioner, "remove_world", remove_world)
    monkeypatch.setattr(crashed.provisioner, "create_world_container", create_world_container)
    # Ein toter Prozess schreibt nichts mehr: kein mark_restore_interrupted aus dem Fehlerpfad.
    monkeypatch.setattr(crashed, "mark_restore_interrupted", lambda _world_id: None)

    await backups.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=True)
    await backups.drain()
    assert removed == [world_id]
    assert _containers(api, world_id) == 0, "der alte Container ist weg"
    row = _store(app_env).get_world(world_id)
    assert row is not None
    assert row.op_state == "restoring_swap", "Zustand wie nach einem echten Prozesstod"
    assert _job(app_env, world_id)[:2] == ("restore", "running")

    # Neustart des Dienstes: boot_reconcile, dann recover_jobs eines frischen BackupService.
    rebooted = fresh_service()
    await _boot(rebooted)
    recovered = _backups(rebooted, app_env)
    assert recovered.recover_jobs() == 1
    row = _store(app_env).get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RESTORE_INTERRUPTED)
    view = await _view(rebooted, world_id)
    assert view.delete_only is False
    assert _job(app_env, world_id) == ("restore", "failed", TEXT_RESTORE_INTERRUPTED_JOB)
    assert _containers(api, world_id) == 0, "eine unterbrochene Welt wird nie halb gestartet"

    # Erneuter Restore über den frischen Dienst gelingt, Mia ist da.
    await recovered.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=True)
    await recovered.drain()
    assert _job(app_env, world_id)[:2] == ("restore", "ok"), _job(app_env, world_id)
    await _wait_status(rebooted, world_id, "running")
    await rebooted.stop_world(world_id)
    world = copy_out(api, str(_container(api, world_id).id), WORLD_PATH, tmp_path / "after")
    assert "Mia" in players_in(world / "players.sqlite")
    assert integrity_ok(world / "map.sqlite")
