"""Wiederherstellen ohne Docker und Nextcloud: Prüfungen, Integrität, vor-restore, Tausch, Rückfall (05-06)."""

from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from gameworld.backup import service as backup_module
from gameworld.backup.archive import MSG_BAD_ENTRY, MSG_NO_SPACE, build_manifest
from gameworld.backup.files import MSG_FILE_GONE, MSG_QUOTA, FilesError
from gameworld.backup.service import (
    BACKUP_NOT_FOUND,
    RESTORE_FALLBACK,
    RESTORE_NOT_CONFIRMED,
    RESTORE_SWAP_FAILED,
    RESTORE_TAMPERED,
    BackupNotFound,
    BackupService,
    PlayersOnline,
    RestoreNotConfirmed,
)
from gameworld.config import load_settings
from gameworld.notify.texts import RESTORE_FAILED_SUBJECT
from gameworld.provisioner.client import DockerProvisioner, ProvisionerError, StatusFile
from gameworld.provisioner.spec import LUANTI_VERSION
from gameworld.provisioner.time_mod import LEDGER_FILE_NAME, LEDGER_HEADER
from gameworld.worlds.service import (
    JOB_RUNNING,
    RECONCILE_DATA_MISSING,
    RESTORE_INTERRUPTED,
    WorldBusyError,
    WorldService,
    delete_only,
)
from gameworld.worlds.store import BackupRow, WorldStore
from tests.conftest import FakeBackupFiles, FakeNotifier
from tests.test_backup_service import (
    ADMIN,
    NOW,
    _halt_rules,
    _halt_write_index,
    _job_state,
    _op_state,
    _rules_in,
    world_tar,
)
from tests.test_service_lifecycle import FRESH, STARTED_AT, FakeProvisioner

PRESET = "mtg_kreativ"
FOLDER = "Gameworld/Sicherungen/Welt"
VOR_RESTORE = "Welt-2026-10-23-1400-vor-restore.tar.gz"
DOCKER_BROKEN = ProvisionerError("Docker hat die Anfrage abgelehnt: kaputt")


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
def sleeps() -> list[float]:
    return []


@pytest.fixture
def backup(service: WorldService, sleeps: list[float], app_env: Path) -> BackupService:
    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return BackupService(service, app_env / "tmp", clock=lambda: float(NOW), sleep=fake_sleep)


def env_tar(env: bytes) -> bytes:
    """Docker-Tar des Weltordners mit eigenem env_meta.txt (unterscheidbare Stände)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        root = tarfile.TarInfo("world")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        for name, data in {"world/env_meta.txt": env, "world/map.sqlite": b"SQLite format 3\x00" + bytes(64)}.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _restored_env(archive: bytes) -> bytes:
    """env_meta.txt aus einem eingespielten Restore-Tar (gzip, Namen relativ zum Weltordner)."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        handle = tar.extractfile("env_meta.txt")
        assert handle is not None
        return handle.read()


def _restored_names(archive: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return tar.getnames()


async def _backed_up(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    *,
    players: bytes = b"",
) -> tuple[str, BackupRow]:
    """Laufende Welt mit einer echten eigenen Sicherung (Stand "alt"); danach spielt der Stand "neu"."""
    created = await service.create_world("Welt")
    world_id = created.id
    fake.extra[world_id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[world_id] = StatusFile(FRESH, b"")
    fake.snapshots[world_id] = env_tar(b"alt")
    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()
    assert _job_state(store, world_id) == ("ok", None)
    proof = store.backups_for(ADMIN, world_id)[0]
    fake.snapshots[world_id] = env_tar(b"neu")
    fake.status_files[world_id] = StatusFile(FRESH, players)
    fake.calls.clear()
    fake.written.clear()
    fake.put_archives.clear()
    fake_files.calls.clear()
    return world_id, proof


def _evil_backup(world_id: str, member: tarfile.TarInfo, data: bytes = b"") -> bytes:
    """Gameworld-Sicherung mit gültigem Manifest und map.sqlite plus einem zusätzlichen Eintrag."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        manifest = build_manifest(world_id, PRESET, LUANTI_VERSION, "2026-10-23T12:00:00+00:00", "backup")
        info = tarfile.TarInfo("gameworld-backup.json")
        info.size = len(manifest)
        tar.addfile(info, io.BytesIO(manifest))
        world_map = b"SQLite format 3\x00" + bytes(64)
        info = tarfile.TarInfo("world/map.sqlite")
        info.size = len(world_map)
        tar.addfile(info, io.BytesIO(world_map))
        if member.isfile():
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
        else:
            tar.addfile(member)
    return buffer.getvalue()


def _register(fake_files: FakeBackupFiles, store: WorldStore, world_id: str, name: str, data: bytes) -> BackupRow:
    """Legt eine Datei in Files ab und trägt einen passenden eigenen Nachweis ein."""
    path = f"{FOLDER}/{name}"
    file_id = fake_files.put(ADMIN, path, data)
    proof = BackupRow(
        file_id=file_id,
        owner_uid=ADMIN,
        world_id=world_id,
        path=path,
        name=name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        preset=PRESET,
        kind="backup",
        created_at="2026-10-23T12:00:00+00:00",
    )
    store.add_backup(proof)
    return proof


def _destroyed(fake: FakeProvisioner) -> bool:
    return any(call.startswith(("stop:", "remove:")) for call in fake.calls)


def _halt_free(service: WorldService, world_id: str) -> bool:
    data, _changed = service.time.render(world_id)
    return not any(line.startswith("@halt") for line in data.decode("ascii").split("\n"))


def _vor_restore_uploads(fake_files: FakeBackupFiles) -> list[str]:
    return [path for method, _uid, path in fake_files.calls if method == "upload" and "vor-restore" in path]


async def _restore(backup: BackupService, world_id: str, proof: BackupRow, *, confirm_disconnect: bool = False) -> None:
    await backup.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=confirm_disconnect)
    await backup.drain()


# Prüfungen im Request (D-04, D-13, D-09)


async def test_restore_requires_confirmation(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)

    with pytest.raises(RestoreNotConfirmed) as caught:
        await backup.start_restore(world_id, ADMIN, proof.file_id, confirm=False, confirm_disconnect=False)

    assert str(caught.value) == RESTORE_NOT_CONFIRMED == "Bitte das Wiederherstellen bestätigen."
    assert fake.calls == []
    assert _op_state(store, world_id) == "ready"


@pytest.mark.parametrize("case", ["unbekannt", "fremder_verwalter", "andere_welt"])
async def test_foreign_or_unknown_file_is_not_found_without_io(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    case: str,
) -> None:
    """T-05-28: Nur der eigene Nachweis zu genau dieser Welt zählt, geprüft vor jedem Docker- oder Files-Aufruf."""
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    other = await service.create_world("Andere")
    file_id = proof.file_id
    if case == "unbekannt":
        file_id = 999_999
    elif case == "fremder_verwalter":
        # Nachweis gehört einem anderen Verwalter (D-13): für ADMIN gibt es ihn nicht.
        file_id = 777
        store.add_backup(replace(proof, file_id=file_id, owner_uid="papa"))
    else:
        world_id = other.id
    fake.calls.clear()
    fake_files.calls.clear()
    list_calls = fake.list_calls

    with pytest.raises(BackupNotFound) as caught:
        await backup.start_restore(world_id, ADMIN, file_id, confirm=True, confirm_disconnect=True)

    assert str(caught.value) == BACKUP_NOT_FOUND == "Diese Sicherung gibt es nicht (mehr)."
    assert fake.calls == []
    assert fake.list_calls == list_calls
    assert fake_files.calls == []
    assert store.running_backup_jobs() == []
    assert _op_state(store, world_id) == "ready"


async def test_players_online_need_confirmation(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")

    with pytest.raises(PlayersOnline, match="1 Kind"):
        await backup.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=False)

    assert _op_state(store, world_id) == "ready"
    assert fake.calls == []


async def test_second_job_is_refused(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    other = await service.create_world("Andere")
    service.begin_offline(other.id, "backing_up")

    with pytest.raises(WorldBusyError, match=JOB_RUNNING):
        await backup.start_restore(world_id, ADMIN, proof.file_id, confirm=True, confirm_disconnect=False)


# Erfolgsfall


async def test_restore_runs_in_order_and_restores_old_state(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")
    ledger = f"{LEDGER_HEADER} {NOW} 0\nMia 120\nend\n".encode("ascii")
    fake.ledgers[world_id] = StatusFile(FRESH, ledger)
    events: list[str] = []
    real_prepare = backup_module.prepare_restore

    def recording_prepare(*args: Any, **kwargs: Any) -> Any:
        events.append("prepare_stopped" if _destroyed(fake) else "prepare")
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(backup_module, "prepare_restore", recording_prepare)
    original_upload = fake_files.upload

    async def recording_upload(*args: Any, **kwargs: Any) -> Any:
        events.append("upload_removed" if f"remove:{world_id}" in fake.calls else "upload")
        assert f"stop:{world_id}" in fake.calls
        assert f"snapshot:{world_id}" in fake.calls
        return await original_upload(*args, **kwargs)

    fake_files.upload = recording_upload  # type: ignore[method-assign]

    await _restore(backup, world_id, proof, confirm_disconnect=True)

    assert _job_state(store, world_id) == ("ok", None)
    job = store.get_backup_job(world_id)
    assert job is not None
    assert (job.kind, job.file_name) == ("restore", proof.name)
    # Download und Prüfung, bevor die Welt angefasst wird; vor-restore-Upload vor der Zerstörung.
    assert fake_files.calls[0] == ("download_to", ADMIN, proof.path)
    assert events == ["prepare", "upload"]
    halt = _halt_write_index(fake, world_id)
    assert halt is not None
    stop = fake.calls.index(f"stop:{world_id}")
    snapshot = fake.calls.index(f"snapshot:{world_id}")
    remove = fake.calls.index(f"remove:{world_id}")
    start = fake.calls.index(f"start:{world_id}")
    assert halt < stop < snapshot < remove < start
    assert world_id in fake.ledger_reads
    # Der Weltinhalt der gewählten Sicherung ist eingespielt, das Zählbuch bewahrt.
    assert _restored_env(fake.put_archives[0][1]) == b"alt"
    with tarfile.open(fileobj=io.BytesIO(fake.put_archives[1][1]), mode="r:") as tar:
        assert tar.getnames() == [LEDGER_FILE_NAME]
        handle = tar.extractfile(LEDGER_FILE_NAME)
        assert handle is not None
        assert handle.read() == ledger
    # vor-restore liegt mit eigenem Nachweis in Files (D-05).
    assert _vor_restore_uploads(fake_files) == [f"{FOLDER}/{VOR_RESTORE}"]
    kinds = {row.name: row.kind for row in store.backups_for(ADMIN, world_id)}
    assert kinds[VOR_RESTORE] == "vor-restore"
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error, row.desired_state) == ("ready", None, "running")
    assert _halt_free(service, world_id)


async def test_restore_with_player_halts_before_stop_while_restoring(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    sleeps: list[float],
) -> None:
    """D-09: @halt steht in der Regeldatei, bevor gestoppt wird, auch im Zustand restoring."""
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")
    states: list[str] = []
    original = fake.write_world_files

    def recording(target: str, archive: bytes) -> None:
        if _halt_rules(archive):
            states.append(_op_state(store, target))
        original(target, archive)

    fake.write_world_files = recording  # type: ignore[method-assign]

    await _restore(backup, world_id, proof, confirm_disconnect=True)

    halt = _halt_write_index(fake, world_id)
    assert halt is not None
    assert halt < fake.calls.index(f"stop:{world_id}")
    assert states == ["restoring"]
    assert sleeps == [pytest.approx(17.0)]
    last = [archive for target, archive in fake.written if target == world_id and _rules_in(archive)]
    assert last
    assert not _halt_rules(last[-1])


async def test_stopped_world_stays_stopped_after_restore(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    await service.stop_world(world_id)
    fake.calls.clear()

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("ok", None)
    assert f"start:{world_id}" not in fake.calls
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.desired_state) == ("ready", "stopped")
    assert _halt_free(service, world_id)


# Integrität und Inhalt (T-05-29, T-05-30): abgelehnt, bevor etwas gestoppt wird


@pytest.mark.parametrize("change", ["inhalt", "groesse"])
async def test_tampered_file_is_rejected_before_stop(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    change: str,
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    file_id, data = fake_files.files[(ADMIN, proof.path)]
    changed = bytes([data[0] ^ 1]) + data[1:] if change == "inhalt" else data + b"x"
    fake_files.files[(ADMIN, proof.path)] = (file_id, changed)

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("failed", RESTORE_TAMPERED)
    assert RESTORE_TAMPERED == "Die Sicherung wurde verändert und wird nicht eingespielt."
    assert not _destroyed(fake)
    assert fake.put_archives == []
    assert _op_state(store, world_id) == "ready"
    assert [(call[0], call[1], call[2]) for call in fake_notifier.calls] == [
        (ADMIN, RESTORE_FAILED_SUBJECT, RESTORE_TAMPERED)
    ]


def _traversal() -> tarfile.TarInfo:
    return tarfile.TarInfo("world/../../etc/cron.d/x")


def _symlink() -> tarfile.TarInfo:
    info = tarfile.TarInfo("world/players.sqlite")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    return info


@pytest.mark.parametrize("member", [_traversal, _symlink])
async def test_unsafe_archive_is_rejected_before_stop(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    member: Callable[[], tarfile.TarInfo],
) -> None:
    world_id, _proof = await _backed_up(backup, service, fake, fake_files, store)
    evil = _register(fake_files, store, world_id, "evil.tar.gz", _evil_backup(world_id, member(), b"boom"))

    await _restore(backup, world_id, evil)

    assert _job_state(store, world_id) == ("failed", MSG_BAD_ENTRY)
    assert not _destroyed(fake)
    assert fake.put_archives == []
    assert _op_state(store, world_id) == "ready"


async def test_failed_world_stays_failed_after_rejection(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    fake_files.files[(ADMIN, proof.path)] = (proof.file_id, b"kaputt")

    await _restore(backup, world_id, proof)

    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RECONCILE_DATA_MISSING)
    assert not _destroyed(fake)


@pytest.mark.parametrize("name", ["world/worldmods/x/init.lua", "world/evil.lua", "world/world.mt"])
async def test_code_from_backup_never_reaches_the_world(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    name: str,
) -> None:
    """T-05-30: Lua und world.mt aus einer Sicherung werden verworfen (Plan 01), nie eingespielt."""
    world_id, _proof = await _backed_up(backup, service, fake, fake_files, store)
    lua = _register(
        fake_files, store, world_id, "lua.tar.gz", _evil_backup(world_id, tarfile.TarInfo(name), b"os.exit()")
    )

    await _restore(backup, world_id, lua)

    assert _job_state(store, world_id) == ("ok", None)
    restored = _restored_names(fake.put_archives[0][1])
    assert "map.sqlite" in restored
    assert not any(entry.endswith((".lua", "world.mt")) or entry.startswith("worldmods") for entry in restored)


async def test_missing_file_fails_before_stop(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    fake_files.files.pop((ADMIN, proof.path))

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("failed", MSG_FILE_GONE)
    assert not _destroyed(fake)


async def test_not_enough_space_fails_before_download(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall 10: Download, Restore-Tar und Sicherheits-Snapshot brauchen das Dreifache."""
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    monkeypatch.setattr(backup_module, "disk_free", lambda path: 3 * proof.size - 1)

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("failed", MSG_NO_SPACE)
    assert fake_files.calls == []
    assert not _destroyed(fake)


# vor-restore-Sicherung (D-05) und kaputte Welten (D-15)


async def test_failed_safety_upload_restarts_old_world(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    fake_notifier: FakeNotifier,
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")
    fake_files.upload_error = FilesError(MSG_QUOTA)

    await _restore(backup, world_id, proof, confirm_disconnect=True)

    assert _job_state(store, world_id) == ("failed", MSG_QUOTA)
    assert f"remove:{world_id}" not in fake.calls
    assert fake.calls[-1] == f"start:{world_id}"
    assert fake.put_archives == []
    assert _op_state(store, world_id) == "ready"
    assert _halt_free(service, world_id)
    assert [(call[0], call[1]) for call in fake_notifier.calls] == [(ADMIN, RESTORE_FAILED_SUBJECT)]


async def test_other_safety_snapshot_error_aborts_before_destruction(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    fake.snapshot_errors = [DOCKER_BROKEN]

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("failed", str(DOCKER_BROKEN))
    assert f"remove:{world_id}" not in fake.calls
    assert fake.calls[-1] == f"start:{world_id}"
    assert _op_state(store, world_id) == "ready"


async def test_delete_only_world_is_restored_without_safety_backup(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    """D-15: Weltdaten fehlen, Container weg: wiederherstellen ohne vor-restore, danach ready."""
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    fake.containers.pop(world_id)
    fake.missing_volumes.add(world_id)

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("ok", None)
    assert f"snapshot:{world_id}" not in fake.calls
    assert _vor_restore_uploads(fake_files) == []
    assert _restored_env(fake.put_archives[0][1]) == b"alt"
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("ready", None)
    assert not delete_only(row)


async def test_world_without_map_is_restored_without_safety_backup(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    """Ohne Spielstand (nie gestartet) gibt es nichts zu bewahren; der Tausch läuft weiter."""
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    fake.snapshots[world_id] = world_tar(with_map=False)

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("ok", None)
    assert f"snapshot:{world_id}" in fake.calls
    assert _vor_restore_uploads(fake_files) == []
    assert _op_state(store, world_id) == "ready"


# Tausch, Rückfall, unterbrochen


async def test_swap_retries_once(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    fake.create_errors = [DOCKER_BROKEN]

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("ok", None)
    assert _restored_env(fake.put_archives[0][1]) == b"alt"
    assert _op_state(store, world_id) == "ready"


async def test_two_swap_failures_fall_back_to_safety_snapshot(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    fake_notifier: FakeNotifier,
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")
    fake.create_errors = [DOCKER_BROKEN, DOCKER_BROKEN]

    await _restore(backup, world_id, proof, confirm_disconnect=True)

    assert _job_state(store, world_id) == ("failed", RESTORE_FALLBACK)
    assert RESTORE_FALLBACK.endswith("Die alte Welt wurde wiederhergestellt.")
    # Eingespielt wurde der Stand von vor dem Wiederherstellen, nicht die gewählte Sicherung.
    assert _restored_env(fake.put_archives[0][1]) == b"neu"
    assert fake.calls[-1] == f"start:{world_id}"
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("ready", None)
    assert _halt_free(service, world_id)
    assert [(call[0], call[1]) for call in fake_notifier.calls] == [(ADMIN, RESTORE_FAILED_SUBJECT)]


async def test_failed_fallback_marks_restore_interrupted(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store, players=b"Mia\n")
    fake.create_errors = [DOCKER_BROKEN, DOCKER_BROKEN, DOCKER_BROKEN]

    await _restore(backup, world_id, proof, confirm_disconnect=True)

    assert _job_state(store, world_id) == ("failed", RESTORE_SWAP_FAILED)
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RESTORE_INTERRUPTED)
    assert not delete_only(row)
    assert _halt_free(service, world_id)


async def test_without_safety_two_swap_failures_mark_interrupted(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    fake.create_errors = [DOCKER_BROKEN, DOCKER_BROKEN]

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("failed", RESTORE_SWAP_FAILED)
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RESTORE_INTERRUPTED)
    assert fake.put_archives == []


async def test_interrupted_world_can_be_restored_again(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    store.update_world(world_id, op_state="failed", last_error=RESTORE_INTERRUPTED)

    await _restore(backup, world_id, proof)

    assert _job_state(store, world_id) == ("ok", None)
    assert _vor_restore_uploads(fake_files) == []
    assert _op_state(store, world_id) == "ready"


# Temp-Dateien


@pytest.mark.parametrize("outcome", ["ok", "manipuliert", "rueckfall"])
async def test_all_spools_are_closed(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    app_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcome: str,
) -> None:
    world_id, proof = await _backed_up(backup, service, fake, fake_files, store)
    if outcome == "manipuliert":
        fake_files.files[(ADMIN, proof.path)] = (proof.file_id, b"kaputt")
    elif outcome == "rueckfall":
        fake.create_errors = [DOCKER_BROKEN, DOCKER_BROKEN]
    opened: list[tuple[str | None, Any]] = []
    real: Callable[..., Any] = tempfile.TemporaryFile

    def recording(*args: Any, **kwargs: Any) -> Any:
        handle = real(*args, **kwargs)
        opened.append((str(kwargs.get("dir")), handle))
        return handle

    monkeypatch.setattr(backup_module.tempfile, "TemporaryFile", recording)

    await _restore(backup, world_id, proof)

    expected = {"ok": 3, "manipuliert": 1, "rueckfall": 4}[outcome]
    assert len(opened) == expected
    assert all(Path(cast(str, directory)) == app_env / "tmp" for directory, _handle in opened)
    assert all(handle.closed for _directory, handle in opened)
