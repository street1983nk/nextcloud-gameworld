"""Sicherungsdienst ohne Docker und Nextcloud: Ablauf, Fehlerpfade, Chat-Hinweis, Liste (05-05)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, cast

import pytest

from gameworld.backup import service as backup_module
from gameworld.backup.archive import MSG_BAD_ENTRY, MSG_NO_SPACE, RestoreRejected
from gameworld.backup.files import MSG_QUOTA, FilesError
from gameworld.backup.service import (
    JOB_FAILED,
    JOB_UNUSABLE,
    BackupService,
    PlayersOnline,
)
from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner, ProvisionerError, StatusFile
from gameworld.provisioner.time_mod import RULES_FILE_NAME
from gameworld.worlds.service import JOB_RUNNING, WorldBusyError, WorldService
from gameworld.worlds.store import BackupRow, WorldStore
from tests.conftest import FakeBackupFiles
from tests.test_service_lifecycle import FRESH, STARTED_AT, FakeProvisioner

# 2026-10-23 12:00 UTC, in Berlin (Sommerzeit) 14:00.
NOW = 1_792_756_800
ADMIN = "admin"


def world_tar(*, with_map: bool = True) -> bytes:
    """Tar-Strom wie Docker get_archive: Präfix world/, optional mit map.sqlite."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        root = tarfile.TarInfo("world")
        root.type = tarfile.DIRTYPE
        tar.addfile(root)
        files = {"world/env_meta.txt": b"game_time = 1\n"}
        if with_map:
            files["world/map.sqlite"] = b"SQLite format 3\x00" + bytes(4096)
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


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


async def _world(service: WorldService, fake: FakeProvisioner, name: str = "Welt", players: bytes = b"") -> str:
    """Laufende Welt mit Status-Mod; ``players`` steht frisch in der Status-Datei."""
    created = await service.create_world(name)
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[created.id] = StatusFile(FRESH, players)
    fake.snapshots[created.id] = world_tar()
    return created.id


def _halt_rules(archive: bytes) -> bool:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        if RULES_FILE_NAME not in tar.getnames():
            return False
        handle = tar.extractfile(RULES_FILE_NAME)
        assert handle is not None
        return any(line.startswith("@halt ") for line in handle.read().decode("ascii").split("\n"))


def _halt_write_index(fake: FakeProvisioner, world_id: str) -> int | None:
    """Index in ``calls`` des ersten Schreibvorgangs mit @halt für diese Welt."""
    written = 0
    for index, call in enumerate(fake.calls):
        if not call.startswith("files:"):
            continue
        target, archive = fake.written[written]
        written += 1
        if target == world_id and _halt_rules(archive):
            return index
    return None


def _uploads(files: FakeBackupFiles) -> list[tuple[str, str, str]]:
    return [call for call in files.calls if call[0] == "upload"]


def _job_state(store: WorldStore, world_id: str) -> tuple[str, str | None]:
    job = store.get_backup_job(world_id)
    assert job is not None
    return job.state, job.message


def _op_state(store: WorldStore, world_id: str) -> str:
    row = store.get_world(world_id)
    assert row is not None
    return row.op_state


# Bestätigung bei Spielern (D-09)


@pytest.mark.parametrize(
    ("players", "text"),
    [
        (b"Mia\nLeo\n", "In der Welt spielen gerade 2 Kinder, sie werden kurz getrennt."),
        (b"Mia\n", "In der Welt spielt gerade 1 Kind, es wird kurz getrennt."),
    ],
)
async def test_players_online_need_confirmation(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, store: WorldStore, players: bytes, text: str
) -> None:
    world_id = await _world(service, fake, players=players)
    fake.calls.clear()

    with pytest.raises(PlayersOnline) as caught:
        await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)

    assert str(caught.value) == text
    assert caught.value.count == len(players.split())
    assert _op_state(store, world_id) == "ready"
    assert store.get_backup_job(world_id) is None
    assert fake.calls == []


# Erfolgsfall


async def test_backup_runs_in_order_and_uploads_after_restart(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()
    calls_at_upload: list[list[str]] = []
    original = fake_files.upload

    async def recording(*args: Any, **kwargs: Any) -> Any:
        calls_at_upload.append(list(fake.calls))
        assert _op_state(store, world_id) == "ready"
        return await original(*args, **kwargs)

    fake_files.upload = recording  # type: ignore[method-assign]

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    assert _job_state(store, world_id) == ("running", None)
    await backup.drain()

    assert _job_state(store, world_id) == ("ok", None)
    snapshot = fake.calls.index(f"snapshot:{world_id}")
    stop = fake.calls.index(f"stop:{world_id}")
    start = fake.calls.index(f"start:{world_id}")
    assert stop < snapshot < start
    assert len(calls_at_upload) == 1
    assert f"start:{world_id}" in calls_at_upload[0]
    assert _op_state(store, world_id) == "ready"


async def test_backup_without_players_neither_halts_nor_waits(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, sleeps: list[float]
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()
    fake.written.clear()

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert sleeps == []
    assert _halt_write_index(fake, world_id) is None


async def test_backup_with_player_halts_before_stop(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, store: WorldStore, sleeps: list[float]
) -> None:
    """D-09, T-05-47: @halt steht in der Regeldatei, bevor der Container stoppt."""
    world_id = await _world(service, fake, players=b"Mia\n")
    fake.calls.clear()
    fake.written.clear()

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=True)
    await backup.drain()

    halt = _halt_write_index(fake, world_id)
    assert halt is not None
    assert halt < fake.calls.index(f"stop:{world_id}")
    # Gewartet wird bis ab (jetzt + 15 s) plus 2 s Gnadenfrist.
    assert sleeps == [pytest.approx(17.0)]
    assert _job_state(store, world_id) == ("ok", None)
    # Nach dem Neustart steht kein Halt mehr in der Regeldatei.
    last = [archive for target, archive in fake.written if target == world_id and _rules_in(archive)]
    assert last
    assert not _halt_rules(last[-1])


def _rules_in(archive: bytes) -> bool:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        return RULES_FILE_NAME in tar.getnames()


async def test_backup_records_proof_row(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id = await _world(service, fake, name="Burg")

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    rows = store.backups_for(ADMIN, world_id)
    assert len(rows) == 1
    row = rows[0]
    path = "Gameworld/Sicherungen/Burg/Burg-2026-10-23-1400.tar.gz"
    file_id, data = fake_files.files[(ADMIN, path)]
    assert row == BackupRow(
        file_id=file_id,
        owner_uid=ADMIN,
        world_id=world_id,
        path=path,
        name="Burg-2026-10-23-1400.tar.gz",
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        preset="mtg_kreativ",
        kind="backup",
        created_at=row.created_at,
    )
    assert row.created_at.startswith("2026-10-23T12:00:00")
    job = store.get_backup_job(world_id)
    assert job is not None
    assert (job.kind, job.file_name) == ("backup", "Burg-2026-10-23-1400.tar.gz")
    assert job.finished_at is not None


async def test_second_backup_in_same_minute_gets_suffix(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id = await _world(service, fake, name="Burg")
    for _ in range(2):
        await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
        await backup.drain()
    names = sorted(row.name for row in store.backups_for(ADMIN, world_id))
    assert names == ["Burg-2026-10-23-1400-2.tar.gz", "Burg-2026-10-23-1400.tar.gz"]


async def test_stopped_world_stays_stopped(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id = await _world(service, fake)
    await service.stop_world(world_id)
    fake.calls.clear()

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert f"start:{world_id}" not in fake.calls
    assert _job_state(store, world_id) == ("ok", None)


# Fehlerpfade (D-11)


async def test_snapshot_error_restarts_world_and_fails_job(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()
    fake.snapshot_errors = [ProvisionerError("Docker hat die Anfrage abgelehnt: kaputt")]

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert fake.calls.index(f"snapshot:{world_id}") < fake.calls.index(f"start:{world_id}")
    assert _job_state(store, world_id) == ("failed", "Docker hat die Anfrage abgelehnt: kaputt")
    assert _uploads(fake_files) == []
    assert store.backups_for(ADMIN, world_id) == []
    assert _op_state(store, world_id) == "ready"


async def test_snapshot_without_map_is_unusable(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    """Nie gestartete Welt (kein map.sqlite): Job failed statt einer scheinbar gültigen Sicherung."""
    world_id = await _world(service, fake)
    fake.snapshots[world_id] = world_tar(with_map=False)
    fake.calls.clear()

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert _job_state(store, world_id) == ("failed", JOB_UNUSABLE)
    assert f"start:{world_id}" in fake.calls
    assert _uploads(fake_files) == []
    assert store.backups_for(ADMIN, world_id) == []


async def test_failed_dry_run_is_unusable(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_id = await _world(service, fake)

    def rejecting(source: BinaryIO, *, world_id: str, preset: str) -> object:
        del source, world_id, preset
        raise RestoreRejected(MSG_BAD_ENTRY)

    monkeypatch.setattr(backup_module, "verify_snapshot", rejecting)

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert _job_state(store, world_id) == ("failed", JOB_UNUSABLE)
    assert _uploads(fake_files) == []
    assert store.backups_for(ADMIN, world_id) == []


async def test_upload_error_keeps_world_running_and_fails_job(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()
    fake_files.upload_error = FilesError(MSG_QUOTA)

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert f"start:{world_id}" in fake.calls
    assert fake.containers[world_id][1] == "running"
    assert _job_state(store, world_id) == ("failed", MSG_QUOTA)
    assert store.backups_for(ADMIN, world_id) == []


async def test_unexpected_error_has_fixed_text(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()

    def broken(*args: object) -> object:
        del args
        raise RuntimeError("/geheimer/pfad")

    monkeypatch.setattr(backup_module, "write_snapshot", broken)

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert _job_state(store, world_id) == ("failed", JOB_FAILED)
    assert f"start:{world_id}" in fake.calls


async def test_too_little_space_fails_before_stop(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pitfall 10: freier Platz unter 2 x letzter Sicherung, kein Stopp, Welt bleibt wie sie war."""
    world_id = await _world(service, fake)
    store.add_backup(
        BackupRow(
            file_id=7,
            owner_uid=ADMIN,
            world_id=world_id,
            path="Gameworld/Sicherungen/Welt/alt.tar.gz",
            name="alt.tar.gz",
            size=1000,
            sha256="0" * 64,
            preset="mtg_kreativ",
            kind="backup",
            created_at="2026-10-22T10:00:00+00:00",
        )
    )
    monkeypatch.setattr(backup_module, "disk_free", lambda path: 1999)
    fake.calls.clear()

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert _job_state(store, world_id) == ("failed", MSG_NO_SPACE)
    assert f"stop:{world_id}" not in fake.calls
    assert _op_state(store, world_id) == "ready"

    monkeypatch.setattr(backup_module, "disk_free", lambda path: 2000)
    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()
    assert _job_state(store, world_id) == ("ok", None)


@pytest.mark.parametrize("fail", [False, True])
async def test_spool_lives_in_tmp_and_is_closed(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    fake_files: FakeBackupFiles,
    app_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    fail: bool,
) -> None:
    world_id = await _world(service, fake)
    if fail:
        fake_files.upload_error = FilesError(MSG_QUOTA)
    opened: list[tuple[str | None, Any]] = []
    real: Callable[..., Any] = tempfile.TemporaryFile

    def recording(*args: Any, **kwargs: Any) -> Any:
        handle = real(*args, **kwargs)
        opened.append((str(kwargs.get("dir")), handle))
        return handle

    monkeypatch.setattr(backup_module.tempfile, "TemporaryFile", recording)

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    assert len(opened) == 1
    assert Path(cast(str, opened[0][0])) == app_env / "tmp"
    assert opened[0][1].closed


# Ein Auftrag zur Zeit, Abbruch vor dem Ablauf


async def test_second_backup_while_running_is_refused(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    first = await _world(service, fake, name="Erste")
    second = await _world(service, fake, name="Zweite")
    release = asyncio.Event()
    entered = asyncio.Event()
    original = fake_files.upload

    async def blocked(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    fake_files.upload = blocked  # type: ignore[method-assign]

    await backup.start_backup(first, ADMIN, confirm_disconnect=False)
    await asyncio.wait_for(entered.wait(), 5)
    for world_id in (first, second):
        with pytest.raises(WorldBusyError, match=JOB_RUNNING):
            await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    release.set()
    await backup.drain()

    assert _job_state(store, first) == ("ok", None)
    assert store.get_backup_job(second) is None


async def test_delete_during_upload_is_refused(
    backup: BackupService, service: WorldService, fake: FakeProvisioner, fake_files: FakeBackupFiles, store: WorldStore
) -> None:
    """T-05-48: op_state ist schon ready, der laufende Job sperrt das Löschen."""
    world_id = await _world(service, fake)
    release = asyncio.Event()
    entered = asyncio.Event()
    original = fake_files.upload

    async def blocked(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    fake_files.upload = blocked  # type: ignore[method-assign]

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await asyncio.wait_for(entered.wait(), 5)
    assert _op_state(store, world_id) == "ready"
    with pytest.raises(WorldBusyError):
        await service.delete_world(world_id)
    release.set()
    await backup.drain()

    assert store.get_world(world_id) is not None
    assert _job_state(store, world_id) == ("ok", None)


async def test_job_row_failure_aborts_offline(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_id = await _world(service, fake)
    fake.calls.clear()

    def broken(*args: object) -> None:
        del args
        raise OSError("Platte")

    monkeypatch.setattr(service.store, "set_backup_job", broken)

    with pytest.raises(OSError, match="Platte"):
        await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)

    assert _op_state(store, world_id) == "ready"
    assert fake.calls == [f"files:{world_id}"]


async def test_spawn_failure_aborts_offline_and_frees_job(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world_id = await _world(service, fake)

    def broken(world_id: str, work: Any) -> None:
        del world_id, work
        raise RuntimeError("keine Schleife")

    monkeypatch.setattr(backup, "_spawn", broken)

    with pytest.raises(RuntimeError):
        await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)

    assert _op_state(store, world_id) == "ready"
    assert store.running_backup_jobs() == []


async def test_failed_world_keeps_failed_state_after_abort(
    backup: BackupService,
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Eine gewöhnlich fehlgeschlagene Welt bleibt sicherbar; ein Abbruch stellt failed wieder her."""
    world_id = await _world(service, fake)
    store.update_world(world_id, op_state="failed", last_error="Proxy weg")
    monkeypatch.setattr(backup_module, "disk_free", lambda path: 0)
    store.add_backup(
        BackupRow(7, ADMIN, world_id, "p/alt.tar.gz", "alt.tar.gz", 10, "0" * 64, "mtg_kreativ", "backup", "2026-10-22")
    )

    await backup.start_backup(world_id, ADMIN, confirm_disconnect=False)
    await backup.drain()

    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", "Proxy weg")
    assert _job_state(store, world_id) == ("failed", MSG_NO_SPACE)


async def test_abort_offline_writes_rules_without_halt(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Abbruch vor dem Stopp: Die laufende Welt bekommt sofort eine Regeldatei ohne @halt."""
    world_id = await _world(service, fake, players=b"Mia\n")
    ticket = service.begin_offline(world_id, "backing_up")
    assert service.announce_halt(world_id, NOW) is not None
    fake.written.clear()
    fake.calls.clear()

    service.abort_offline(ticket)

    assert _op_state(store, world_id) == "ready"
    rules = [archive for target, archive in fake.written if target == world_id and _rules_in(archive)]
    assert rules
    assert not _halt_rules(rules[-1])
    assert not any(call.startswith(("stop:", "start:")) for call in fake.calls)
