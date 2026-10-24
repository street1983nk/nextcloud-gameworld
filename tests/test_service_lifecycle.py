"""Lebenszyklus ohne Docker: Starten, Stoppen, Löschen und die Port-Kollisions-Saga."""

from __future__ import annotations

import io
import sqlite3
import tarfile
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import BinaryIO, cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.playtime.pause import ART_PAUSE, OUTBOX_PAUSE_START, PauseState
from gameworld.playtime.plan import DayRule, WeekPlan
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME, render_access_file
from gameworld.provisioner.client import (
    SNAPSHOT_CHUNK,
    ContainerInfo,
    DockerProvisioner,
    DockerUnavailableError,
    MemoryUsage,
    PortInUseError,
    ProvisionerError,
    StatusFile,
    WorldNotFoundError,
)
from gameworld.provisioner.presets import MTG_KREATIV, PRESETS
from gameworld.provisioner.spec import WorldPayload
from gameworld.provisioner.time_mod import LEDGER_FILE_NAME, LEDGER_HEADER, RULES_FILE_NAME
from gameworld.worlds import service as service_module
from gameworld.worlds.service import (
    CREATE_FAILED,
    HALT_LEAD_SECONDS,
    JOB_RUNNING,
    LIST_CACHE_SECONDS,
    PAYLOAD_FAILED,
    RECONCILE_DATA_MISSING,
    RECONCILE_INTERRUPTED,
    WORLD_BUSY,
    DeleteOnlyError,
    OfflineTicket,
    WorldBusyError,
    WorldService,
    WorldView,
)
from gameworld.worlds.store import BackupRow, WorldStore
from tests.conftest import appapi_headers


@dataclass
class FakeProvisioner:
    """Bildet die Schnittstelle von DockerProvisioner nach und protokolliert jeden Aufruf."""

    start_errors: list[ProvisionerError] = field(default_factory=list)
    create_errors: list[ProvisionerError] = field(default_factory=list)
    remove_error: ProvisionerError | None = None
    host_ports: set[int] = field(default_factory=set)
    containers: dict[str, tuple[int, str]] = field(default_factory=dict)
    created: list[tuple[str, int, bool]] = field(default_factory=list)
    started: list[str] = field(default_factory=list)
    stopped: list[str] = field(default_factory=list)
    removed: list[tuple[str, bool]] = field(default_factory=list)
    # Reihenfolge der Mutationen ("stop:<id>", "start:<id>") für den Neustart.
    calls: list[str] = field(default_factory=list)
    # Zusätzliche Inspect-Felder pro Welt (exit_code, oom_killed, started_at, schema).
    extra: dict[str, dict[str, object]] = field(default_factory=dict)
    status_files: dict[str, StatusFile] = field(default_factory=dict)
    status_error: ProvisionerError | None = None
    status_reads: list[str] = field(default_factory=list)
    memory: dict[str, MemoryUsage] = field(default_factory=dict)
    memory_errors: dict[str, ProvisionerError] = field(default_factory=dict)
    memory_reads: list[str] = field(default_factory=list)
    list_error: ProvisionerError | None = None
    list_calls: int = 0
    # Welten, deren Volume (Weltdaten) fehlt, etwa nach docker volume prune.
    missing_volumes: set[str] = field(default_factory=set)
    # Per write_world_files geschriebene Tars (Welt, Archiv), in Reihenfolge.
    written: list[tuple[str, bytes]] = field(default_factory=list)
    # State-Dateien des Zugangs-Mods pro Welt (fehlt: None) und ein optionaler Lesefehler.
    access_states: dict[str, StatusFile] = field(default_factory=dict)
    access_state_error: ProvisionerError | None = None
    access_state_reads: list[str] = field(default_factory=list)
    # Zählbücher des Zeit-Mods pro Welt (fehlt: None) und ein optionaler Lesefehler.
    ledgers: dict[str, StatusFile] = field(default_factory=dict)
    ledger_error: ProvisionerError | None = None
    ledger_reads: list[str] = field(default_factory=list)
    # Ereignisdateien des Zugangs-Mods pro Welt (fehlt: None) und ein optionaler Lesefehler.
    events: dict[str, StatusFile] = field(default_factory=dict)
    events_error: ProvisionerError | None = None
    event_reads: list[str] = field(default_factory=list)
    # Snapshots (Tar-Bytes des Weltordners) pro Welt, Fehlerinjektion und eingespielte Restore-Tars.
    snapshots: dict[str, bytes] = field(default_factory=dict)
    snapshot_errors: list[Exception] = field(default_factory=list)
    put_archives: list[tuple[str, bytes]] = field(default_factory=list)
    # Aufräumen beim Deaktivieren (06-08): Stopp-Timeouts, Fehler je Welt, künstliche Dauer.
    stop_timeouts: list[int] = field(default_factory=list)
    stop_errors: dict[str, ProvisionerError] = field(default_factory=dict)
    stop_delay: float = 0.0

    def ensure_image(self) -> None:
        return None

    def create_world_container(
        self, world_id: str, host_port: int, payload: bytes, *, reuse_volume: bool = False
    ) -> str:
        assert payload
        if self.create_errors:
            raise self.create_errors.pop(0)
        self.created.append((world_id, host_port, reuse_volume))
        self.containers[world_id] = (host_port, "created")
        return f"cid-{world_id}"

    def _known(self, world_id: str) -> tuple[int, str]:
        if world_id not in self.containers:
            raise WorldNotFoundError("Diese Welt gibt es nicht (mehr).")
        return self.containers[world_id]

    def write_world_files(self, world_id: str, archive: bytes) -> None:
        self._known(world_id)
        assert archive
        self.written.append((world_id, archive))
        self.calls.append(f"files:{world_id}")

    def start_world(self, world_id: str) -> None:
        port, _ = self._known(world_id)
        self.started.append(world_id)
        self.calls.append(f"start:{world_id}")
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.containers[world_id] = (port, "running")

    def stop(self, world_id: str, *, timeout: int = 30) -> None:
        port, _ = self._known(world_id)
        self.stop_timeouts.append(timeout)
        if world_id in self.stop_errors:
            raise self.stop_errors[world_id]
        if self.stop_delay:
            time.sleep(self.stop_delay)
        self.stopped.append(world_id)
        self.calls.append(f"stop:{world_id}")
        self.containers[world_id] = (port, "exited")

    def remove_world(self, world_id: str, *, keep_volume: bool) -> None:
        self.removed.append((world_id, keep_volume))
        self.calls.append(f"remove:{world_id}")
        if self.remove_error is not None:
            raise self.remove_error
        self.containers.pop(world_id, None)

    def volume_exists(self, world_id: str) -> bool:
        return world_id not in self.missing_volumes

    def used_host_ports(self, lo: int, hi: int) -> set[int]:
        ports = self.host_ports | {port for port, _ in self.containers.values()}
        return {port for port in ports if lo <= port <= hi}

    def list_managed(self) -> dict[str, ContainerInfo]:
        self.list_calls += 1
        if self.list_error is not None:
            raise self.list_error
        return {
            world_id: ContainerInfo(
                f"cid-{world_id}",
                f"gameworld-x-{world_id}",
                world_id,
                status,
                port,
                **self.extra.get(world_id, {}),  # pyright: ignore[reportArgumentType]
            )
            for world_id, (port, status) in self.containers.items()
        }

    def read_status_file(self, world_id: str) -> StatusFile | None:
        self._known(world_id)
        self.status_reads.append(world_id)
        if self.status_error is not None:
            raise self.status_error
        return self.status_files.get(world_id)

    def read_access_state(self, world_id: str) -> StatusFile | None:
        self._known(world_id)
        self.access_state_reads.append(world_id)
        if self.access_state_error is not None:
            raise self.access_state_error
        return self.access_states.get(world_id)

    def read_time_ledger(self, world_id: str) -> StatusFile | None:
        self._known(world_id)
        self.ledger_reads.append(world_id)
        if self.ledger_error is not None:
            raise self.ledger_error
        return self.ledgers.get(world_id)

    def read_events(self, world_id: str) -> StatusFile | None:
        self._known(world_id)
        self.event_reads.append(world_id)
        if self.events_error is not None:
            raise self.events_error
        return self.events.get(world_id)

    def snapshot_to[T](self, world_id: str, write: Callable[[Iterator[bytes]], T]) -> T:
        """Wie DockerProvisioner.snapshot_to: nur bei gestopptem Container, Strom in Stücken."""
        _, status = self._known(world_id)
        self.calls.append(f"snapshot:{world_id}")
        if self.snapshot_errors:
            raise self.snapshot_errors.pop(0)
        if status == "running":
            raise ProvisionerError("Die Welt läuft noch; eine Sicherung braucht eine gestoppte Welt.")
        data = self.snapshots.get(world_id, b"")
        return write(iter([data[index : index + SNAPSHOT_CHUNK] for index in range(0, len(data), SNAPSHOT_CHUNK)]))

    def put_world_archive(self, world_id: str, archive: BinaryIO) -> None:
        self._known(world_id)
        self.put_archives.append((world_id, archive.read()))
        self.calls.append(f"put_archive:{world_id}")

    def memory_bytes(self, world_id: str) -> MemoryUsage | None:
        _, status = self._known(world_id)
        self.memory_reads.append(world_id)
        if world_id in self.memory_errors:
            raise self.memory_errors[world_id]
        if status != "running":
            return None
        return self.memory.get(world_id)


class Clock:
    """Steuert time.monotonic im Dienst (Cache der Weltenliste)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    fake_clock = Clock()
    monkeypatch.setattr(service_module, "monotonic", fake_clock)
    return fake_clock


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
def payload_args(monkeypatch: pytest.MonkeyPatch) -> list[tuple[object, ...]]:
    """Zeichnet alle Positionsargumente von build_world_payload auf und ruft die echte Funktion."""
    calls: list[tuple[object, ...]] = []
    real = service_module.build_world_payload

    def wrapper(*args: object) -> WorldPayload:
        calls.append(args)
        return real(*args)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(service_module, "build_world_payload", wrapper)
    return calls


def _has_arg_line(calls: list[tuple[object, ...]], line: str) -> bool:
    return any(isinstance(arg, str) and line in arg.splitlines() for args in calls for arg in args)


async def test_new_world_defaults_to_kreativ_payload(
    service: WorldService, store: WorldStore, payload_args: list[tuple[object, ...]]
) -> None:
    created = await service.create_world("Welt")
    assert created.preset == "mtg_kreativ"
    assert created.preset_title == "Bauen (kreativ)"
    row = store.get_world(created.id)
    assert row is not None
    assert row.preset == "mtg_kreativ"
    assert _has_arg_line(payload_args, "creative_mode = true")


async def test_unknown_preset_is_rejected_before_anything(service: WorldService, store: WorldStore) -> None:
    with pytest.raises(ValueError, match="Unbekannte Spielart"):
        await service.create_world("Welt", "survival_hart")
    assert store.list_worlds() == []


async def test_list_worlds_carries_preset(service: WorldService) -> None:
    await service.create_world("Welt", "mtg_kreativ")
    views = await service.list_worlds()
    assert [(view.preset, view.preset_title) for view in views] == [("mtg_kreativ", "Bauen (kreativ)")]


async def test_saga_recreation_uses_row_preset(
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    payload_args: list[tuple[object, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die Neuerzeugung in der Port-Saga baut aus row.preset, nie aus einer Vorgabe (Pitfall 2)."""
    marker = replace(MTG_KREATIV, id="test_spiel", conf_lines=("creative_mode = false",))
    monkeypatch.setitem(PRESETS, marker.id, marker)
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    store.update_world(created.id, preset=marker.id)
    payload_args.clear()
    fake.start_errors = [PortInUseError(30015)]

    await service.start_world(created.id)

    assert _has_arg_line(payload_args, "creative_mode = false")
    assert not _has_arg_line(payload_args, "creative_mode = true")


async def test_failed_create_with_successful_cleanup_leaves_no_row(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.start_errors = [DockerUnavailableError("Proxy weg")]
    with pytest.raises(DockerUnavailableError):
        await service.create_world("Welt")
    assert len(fake.removed) == 1
    assert fake.removed[0][1] is False
    assert store.list_worlds() == []
    assert store.used_ports() == set()


async def test_failed_container_creation_is_cleaned_up(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Scheitert create_world_container, kann ein Volume übrig sein: Aufräumen läuft, dann keine Zeile."""
    fake.create_errors = [DockerUnavailableError("Proxy weg")]
    with pytest.raises(DockerUnavailableError):
        await service.create_world("Welt")
    assert len(fake.removed) == 1
    assert store.list_worlds() == []


async def test_failed_create_with_failed_cleanup_keeps_failed_row(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.start_errors = [DockerUnavailableError("Proxy weg")]
    fake.remove_error = ProvisionerError("Aufräumen kaputt")
    with pytest.raises(DockerUnavailableError):
        await service.create_world("Welt")
    rows = store.list_worlds()
    assert len(rows) == 1
    assert rows[0].op_state == "failed"
    assert rows[0].last_error == "Proxy weg"


async def test_two_worlds_get_different_ports(service: WorldService) -> None:
    first = await service.create_world("Welt A")
    second = await service.create_world("Welt B")
    assert first.port == 30015
    assert second.port == 30016


async def test_port_bound_by_foreign_container_is_skipped(service: WorldService, fake: FakeProvisioner) -> None:
    fake.host_ports = {30015}
    created = await service.create_world("Welt")
    assert created.port == 30016


async def test_port_conflict_on_start_recreates_with_next_port(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.created.clear()
    fake.start_errors = [PortInUseError(30015)]

    view = await service.start_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.port == 30016
    assert row.op_state == "ready"
    assert view.port == 30016
    assert view.docker_status == "running"
    assert fake.removed == [(created.id, True)]
    assert fake.created == [(created.id, 30016, True)]


async def test_port_conflict_on_create_recreates_with_next_port(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.start_errors = [PortInUseError(30015)]
    created = await service.create_world("Welt")
    assert created.port == 30016
    row = store.get_world(created.id)
    assert row is not None
    assert row.port == 30016
    assert row.op_state == "ready"
    assert fake.removed == [(created.id, True)]


async def test_three_port_conflicts_give_up(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.started.clear()
    fake.start_errors = [PortInUseError(30015), PortInUseError(30016), PortInUseError(30017)]

    with pytest.raises(ProvisionerError):
        await service.start_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error is not None
    assert "UDP-Port" in row.last_error
    assert len(fake.started) == 3


async def test_start_recreates_missing_container_from_volume(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Container weg (docker rm von außen oder Saga-Fehlerpfad), Volume da: Start erzeugt neu."""
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)
    fake.created.clear()

    view = await service.start_world(created.id)

    assert fake.created == [(created.id, created.port, True)]
    assert view.docker_status == "running"
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "ready"
    assert row.last_error is None


async def test_saga_failure_leaves_recoverable_world(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Scheitert die Neuerzeugung in der Port-Saga, rettet der nächste Start die Welt (CR-01)."""
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.start_errors = [PortInUseError(30015)]
    fake.create_errors = [DockerUnavailableError("Proxy weg")]

    with pytest.raises(DockerUnavailableError):
        await service.start_world(created.id)

    # Der Fehlerpfad hinterlässt genau den kritischen Zustand: Volume ohne Container.
    assert created.id not in fake.containers
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"

    fake.created.clear()
    view = await service.start_world(created.id)

    assert view.docker_status == "running"
    assert fake.created == [(created.id, row.port, True)]
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "ready"
    assert row.last_error is None


async def test_recreated_container_still_runs_port_saga(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Auch der neu erzeugte Container durchläuft bei Port-Kollision die Saga."""
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)
    fake.created.clear()
    fake.start_errors = [PortInUseError(30015)]

    view = await service.start_world(created.id)

    assert view.port == 30016
    assert view.docker_status == "running"
    assert fake.created == [(created.id, 30015, True), (created.id, 30016, True)]


async def test_stop_with_missing_container_is_noop(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Ein fehlender Container ist bereits gestoppt: Stoppen ist Erfolg, kein 404."""
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)

    view = await service.stop_world(created.id)

    assert view.docker_status == "missing"
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "stopped"
    assert row.op_state == "ready"
    assert row.last_error is None


async def test_stop_and_start_set_desired_state(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")

    stopped = await service.stop_world(created.id)
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "stopped"
    assert stopped.docker_status == "exited"

    started = await service.start_world(created.id)
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "running"
    assert started.docker_status == "running"


async def test_delete_removes_row_after_docker_cleanup(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.delete_world(created.id)
    assert fake.removed == [(created.id, False)]
    assert store.get_world(created.id) is None


async def test_delete_removes_world_window_and_seen_ledger(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    other = await service.create_world("Andere")
    for world_id in (created.id, other.id):
        store.replace_world_window(world_id, {3: (600, 720)})
        store.set_ledger_seen(world_id, {"Kind": 30})

    await service.delete_world(created.id)

    assert store.world_window(created.id) is None
    assert store.ledger_seen(created.id) == {}
    # Die andere Welt behält ihre Daten.
    assert store.world_window(other.id) == {3: (600, 720)}
    assert store.ledger_seen(other.id) == {"Kind": 30}


async def test_list_worlds_carries_time_window(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    assert {view.id: view for view in await service.list_worlds()}[created.id].time_window is None

    # Wie ein Dienst unter der Sperre ändern: Der Listen-Cache wird dabei verworfen.
    with service.try_mutation() as acquired:
        assert acquired
        store.replace_world_window(created.id, {1: (600, 720)})

    [view] = [view for view in await service.list_worlds() if view.id == created.id]
    assert view.time_window is not None
    assert [day.open for day in view.time_window] == [True, False, False, False, False, False, False]


async def test_failed_delete_keeps_row(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    fake.remove_error = ProvisionerError("Docker hat die Anfrage abgelehnt: kaputt")

    with pytest.raises(ProvisionerError):
        await service.delete_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error == "Docker hat die Anfrage abgelehnt: kaputt"


STARTED_AT = "2026-10-19T18:19:46.947430723Z"


async def _status_of(service: WorldService, world_id: str) -> tuple[str, str]:
    views = {view.id: view for view in await service.list_worlds()}
    return views[world_id].status, views[world_id].status_text


async def test_external_clean_stop_shows_stopped_without_db_change(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Status kommt aus Docker: Stop von außen, desired_state bleibt running."""
    created = await service.create_world("Welt")
    fake.containers[created.id] = (created.port, "exited")
    fake.extra[created.id] = {"exit_code": 0}

    assert await _status_of(service, created.id) == ("stopped", "Gestoppt")
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "running"


async def test_external_kill_shows_error_with_code(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.containers[created.id] = (created.port, "exited")
    fake.extra[created.id] = {"exit_code": 137}

    assert await _status_of(service, created.id) == ("error", "Die Welt wurde unerwartet beendet (Code 137).")


async def test_oom_shows_error(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.containers[created.id] = (created.port, "exited")
    fake.extra[created.id] = {"exit_code": 137, "oom_killed": True}

    assert await _status_of(service, created.id) == (
        "error",
        "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet.",
    )


async def test_stale_status_file_is_starting_fresh_is_running(
    service: WorldService, fake: FakeProvisioner, clock: Clock
) -> None:
    """Pitfall 3: Eine Status-Datei aus dem letzten Lauf zählt nicht als bereit."""
    created = await service.create_world("Welt")
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}

    fake.status_files[created.id] = StatusFile("2026-10-19T18:00:00.123456789Z", b"")
    assert await _status_of(service, created.id) == ("starting", "Startet gerade")

    fake.status_files[created.id] = StatusFile("2026-10-19T18:19:48.5Z", b"")
    clock.advance(LIST_CACHE_SECONDS)
    assert await _status_of(service, created.id) == ("running", "Läuft")


async def test_missing_status_file_is_starting(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    assert await _status_of(service, created.id) == ("starting", "Startet gerade")


async def test_status_file_error_is_isolated(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_error = DockerUnavailableError("Proxy weg")
    assert await _status_of(service, created.id) == ("starting", "Startet gerade")


async def test_status_file_only_read_for_running_schema_two(service: WorldService, fake: FakeProvisioner) -> None:
    old = await service.create_world("Alt")
    new = await service.create_world("Neu")
    fake.extra[new.id] = {"schema": "2", "started_at": STARTED_AT}
    await service.list_worlds()
    assert fake.status_reads == [new.id]

    fake.status_reads.clear()
    await service.stop_world(new.id)
    await service.list_worlds()
    assert old.id not in fake.status_reads
    assert new.id not in fake.status_reads


async def test_missing_container_shows_recoverable_error(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)
    assert await _status_of(service, created.id) == (
        "error",
        "Der Server der Welt fehlt. Starten stellt ihn wieder her, falls die Weltdaten noch da sind.",
    )
    assert (await _view_of(service, created.id)).delete_only is False


async def test_restart_stops_then_launches(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    fake.calls.clear()

    view = await service.restart_world(created.id)

    assert fake.calls == [f"stop:{created.id}", f"files:{created.id}", f"start:{created.id}"]
    assert view.status == "running"
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "running"
    assert row.op_state == "ready"


async def test_restart_of_stopped_world_starts_it(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)

    view = await service.restart_world(created.id)

    assert view.status == "running"
    row = store.get_world(created.id)
    assert row is not None
    assert row.desired_state == "running"


async def test_restart_with_missing_container_recreates(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)
    fake.created.clear()

    view = await service.restart_world(created.id)

    assert fake.created == [(created.id, created.port, True)]
    assert view.status == "running"


async def test_restart_runs_port_saga(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.start_errors = [PortInUseError(30015)]

    view = await service.restart_world(created.id)

    assert view.port == 30016


async def test_failed_restart_marks_world_failed(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    fake.start_errors = [DockerUnavailableError("Proxy weg")]

    with pytest.raises(DockerUnavailableError):
        await service.restart_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error == "Proxy weg"
    assert await _status_of(service, created.id) == ("error", "Proxy weg")


FRESH = "2026-10-19T18:19:48.5Z"
STALE = "2026-10-19T18:00:00Z"
MEM = MemoryUsage(used=19200000, limit=536870912)


async def _view_of(service: WorldService, world_id: str) -> WorldView:
    return {view.id: view for view in await service.list_worlds()}[world_id]


async def _running_world(service: WorldService, fake: FakeProvisioner, name: str, mtime: str = FRESH) -> str:
    created = await service.create_world(name)
    fake.extra[created.id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[created.id] = StatusFile(mtime, b"Mia\nLeo\n<script>\n192.168.0.5\n")
    fake.memory[created.id] = MEM
    return created.id


async def test_running_world_shows_players_and_memory(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    view = await _view_of(service, world_id)
    assert view.status == "running"
    assert view.players == ["Mia", "Leo"]
    assert (view.memory_used_bytes, view.memory_limit_bytes) == (MEM.used, MEM.limit)


async def test_status_file_older_than_start_shows_no_players(service: WorldService, fake: FakeProvisioner) -> None:
    """Namen aus einem früheren Lauf (Datei älter als StartedAt) erscheinen nie."""
    world_id = await _running_world(service, fake, "Welt", mtime=STALE)
    view = await _view_of(service, world_id)
    assert view.status == "starting"
    assert view.players == []
    # Der Container läuft, der RAM ist trotzdem sichtbar.
    assert view.memory_used_bytes == MEM.used


async def test_stopped_world_has_no_players_and_no_memory(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.memory_reads.clear()
    view = await service.stop_world(world_id)
    assert view.status == "stopped"
    assert view.players == []
    assert view.memory_used_bytes is None
    assert view.memory_limit_bytes is None
    assert world_id not in fake.memory_reads


async def test_error_world_has_no_players(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.containers[world_id] = (fake.containers[world_id][0], "exited")
    fake.extra[world_id]["exit_code"] = 137
    view = await _view_of(service, world_id)
    assert view.status == "error"
    assert view.players == []
    assert view.memory_used_bytes is None


async def test_old_schema_world_has_memory_but_no_players(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Alt")
    fake.memory[created.id] = MEM
    view = await _view_of(service, created.id)
    assert view.status == "running"
    assert view.players == []
    assert view.memory_used_bytes == MEM.used


async def test_memory_error_is_isolated_per_world(service: WorldService, fake: FakeProvisioner) -> None:
    broken = await _running_world(service, fake, "Kaputt")
    healthy = await _running_world(service, fake, "Heil")
    fake.memory_errors[broken] = DockerUnavailableError("Proxy weg")
    views = {view.id: view for view in await service.list_worlds()}
    assert views[broken].memory_used_bytes is None
    assert views[broken].memory_limit_bytes is None
    assert views[broken].players == ["Mia", "Leo"]
    assert views[healthy].memory_used_bytes == MEM.used
    assert views[healthy].players == ["Mia", "Leo"]


async def test_status_file_error_gives_no_players(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.status_error = DockerUnavailableError("Proxy weg")
    view = await _view_of(service, world_id)
    assert view.players == []
    assert view.memory_used_bytes == MEM.used


async def test_list_is_cached_for_two_seconds(service: WorldService, fake: FakeProvisioner, clock: Clock) -> None:
    await service.create_world("Welt")
    await service.list_worlds()
    calls = fake.list_calls
    await service.list_worlds()
    clock.advance(LIST_CACHE_SECONDS - 0.1)
    await service.list_worlds()
    assert fake.list_calls == calls
    clock.advance(0.1)
    await service.list_worlds()
    assert fake.list_calls == calls + 1


@pytest.mark.usefixtures("clock")
@pytest.mark.parametrize("operation", ["start_world", "stop_world", "restart_world", "delete_world"])
async def test_mutation_invalidates_cache(service: WorldService, fake: FakeProvisioner, operation: str) -> None:
    created = await service.create_world("Welt")
    await service.list_worlds()
    await getattr(service, operation)(created.id)
    calls = fake.list_calls
    await service.list_worlds()
    assert fake.list_calls == calls + 1


@pytest.mark.usefixtures("clock")
async def test_create_invalidates_cache(service: WorldService) -> None:
    await service.create_world("Erste")
    assert len(await service.list_worlds()) == 1
    await service.create_world("Zweite")
    assert len(await service.list_worlds()) == 2


@pytest.mark.usefixtures("clock")
async def test_failed_mutation_invalidates_cache(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    await service.list_worlds()
    fake.start_errors = [DockerUnavailableError("Proxy weg")]
    with pytest.raises(DockerUnavailableError):
        await service.restart_world(created.id)
    assert await _status_of(service, created.id) == ("error", "Proxy weg")


@pytest.mark.usefixtures("clock")
async def test_unknown_status_is_not_cached(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.list_error = DockerUnavailableError("Proxy weg")
    assert (await _status_of(service, created.id))[0] == "unknown"
    fake.list_error = None
    assert await _status_of(service, created.id) == ("running", "Läuft")


@pytest.mark.usefixtures("clock")
async def test_cache_returns_copies(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    first = await _view_of(service, world_id)
    first.players.append("Eindringling")
    first.status = "kaputt"
    second = await _view_of(service, world_id)
    assert second.players == ["Mia", "Leo"]
    assert second.status == "running"


@pytest.mark.usefixtures("_override")
async def test_api_lists_players_and_memory(client: httpx.AsyncClient, fake: FakeProvisioner) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    fake.extra[world_id] = {"schema": "2", "started_at": STARTED_AT}
    fake.status_files[world_id] = StatusFile(FRESH, b"Leo\n")
    fake.memory[world_id] = MEM
    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.json()["players"] == []
    assert stopped.json()["memory_used_bytes"] is None
    assert stopped.json()["memory_limit_bytes"] is None
    await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    listing = await client.get("/api/worlds", headers=appapi_headers())
    world = listing.json()["worlds"][0]
    assert world["players"] == ["Leo"]
    assert world["memory_used_bytes"] == MEM.used
    assert world["memory_limit_bytes"] == MEM.limit


@pytest.mark.parametrize("operation", ["start_world", "stop_world", "delete_world", "restart_world"])
async def test_unknown_world_raises_not_found(service: WorldService, operation: str) -> None:
    with pytest.raises(WorldNotFoundError):
        await getattr(service, operation)("0123456789ab")


@pytest.fixture
def _override(service: WorldService) -> Iterator[None]:
    from gameworld.main import APP

    APP.dependency_overrides[get_service] = lambda: service
    yield
    APP.dependency_overrides.pop(get_service, None)


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize("world_id", ["xyz", "..etc", "0123456789AB", "0123456789abc"])
@pytest.mark.parametrize(
    ("method", "suffix"), [("POST", "/start"), ("POST", "/stop"), ("POST", "/restart"), ("DELETE", "")]
)
async def test_invalid_world_id_returns_422(client: httpx.AsyncClient, world_id: str, method: str, suffix: str) -> None:
    response = await client.request(method, f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())
    assert response.status_code == 422


@pytest.mark.usefixtures("_override")
async def test_path_traversal_never_reaches_a_route(client: httpx.AsyncClient) -> None:
    response = await client.request("DELETE", "/api/worlds/..%2Fetc", headers=appapi_headers())
    assert response.status_code in {404, 405, 422}


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize(
    ("method", "suffix"), [("POST", "/start"), ("POST", "/stop"), ("POST", "/restart"), ("DELETE", "")]
)
async def test_unknown_world_returns_404(client: httpx.AsyncClient, method: str, suffix: str) -> None:
    response = await client.request(method, f"/api/worlds/0123456789ab{suffix}", headers=appapi_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "Diese Welt gibt es nicht (mehr)."}


@pytest.mark.usefixtures("_override")
async def test_api_lifecycle_round_trip(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    assert created.status_code == 201
    assert created.json()["preset"] == "mtg_kreativ"
    assert created.json()["preset_title"] == "Bauen (kreativ)"
    world_id = created.json()["id"]

    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.status_code == 200
    assert stopped.json()["docker_status"] == "exited"
    assert (stopped.json()["status"], stopped.json()["status_text"]) == ("stopped", "Gestoppt")
    assert "world_key" not in stopped.json()

    started = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    assert started.status_code == 200
    assert started.json()["docker_status"] == "running"
    assert (started.json()["status"], started.json()["status_text"]) == ("running", "Läuft")

    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200
    assert restarted.json()["status"] == "running"
    assert "world_key" not in restarted.json()

    deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
    assert deleted.status_code == 204
    listing = await client.get("/api/worlds", headers=appapi_headers())
    assert listing.json()["worlds"] == []


@pytest.mark.usefixtures("_override")
@pytest.mark.parametrize(("suffix", "expected_status"), [("/start", "running"), ("/stop", "missing")])
async def test_world_without_container_is_recoverable_via_api(
    client: httpx.AsyncClient, fake: FakeProvisioner, suffix: str, expected_status: str
) -> None:
    """Welt mit Volume, aber ohne Container: Start und Stop antworten 200, nie 404 (CR-01)."""
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    fake.containers.pop(world_id)

    response = await client.post(f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())

    assert response.status_code == 200
    assert response.json()["docker_status"] == expected_status


# CR-01 (Phase-2-Review): Fehlen die Weltdaten, entsteht nie eine leere Welt unter altem Namen.


@pytest.mark.parametrize("operation", ["start_world", "restart_world"])
@pytest.mark.parametrize("stopped_first", [False, True])
async def test_missing_volume_never_recreates_empty_world(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, operation: str, stopped_first: bool
) -> None:
    """Container und Volume weg (prune): kein create, die Welt wird "nur löschen"."""
    created = await service.create_world("Welt")
    if stopped_first:
        await service.stop_world(created.id)
    fake.containers.pop(created.id)
    fake.missing_volumes.add(created.id)
    fake.created.clear()

    with pytest.raises(DeleteOnlyError, match="Weltdaten fehlen"):
        await getattr(service, operation)(created.id)

    assert fake.created == []
    row = store.get_world(created.id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RECONCILE_DATA_MISSING)
    view = await _view_of(service, created.id)
    assert (view.status, view.status_text, view.delete_only) == ("error", RECONCILE_DATA_MISSING, True)


@pytest.mark.parametrize("operation", ["start_world", "restart_world"])
async def test_delete_only_world_refuses_start_without_touching_docker(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, operation: str
) -> None:
    """Auch wenn das Volume wieder auftaucht: Start ändert weder Docker noch die Zeile."""
    created = await service.create_world("Welt")
    store.update_world(created.id, op_state="failed", last_error=RECONCILE_DATA_MISSING, desired_state="stopped")
    fake.calls.clear()
    fake.created.clear()

    with pytest.raises(DeleteOnlyError):
        await getattr(service, operation)(created.id)

    assert fake.calls == []
    assert fake.created == []
    row = store.get_world(created.id)
    assert row is not None
    assert (row.desired_state, row.op_state, row.last_error) == ("stopped", "failed", RECONCILE_DATA_MISSING)

    await service.delete_world(created.id)
    assert store.get_world(created.id) is None


async def test_other_failed_world_stays_startable(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Gegenprobe: Ein gewöhnlicher Fehler sperrt Starten nicht."""
    created = await service.create_world("Welt")
    store.update_world(created.id, op_state="failed", last_error="Proxy weg")
    assert (await _view_of(service, created.id)).delete_only is False

    view = await service.start_world(created.id)

    assert view.status == "running"
    assert view.delete_only is False


@pytest.mark.usefixtures("_override")
async def test_api_delete_only_world_answers_409_and_allows_delete(
    client: httpx.AsyncClient, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    assert created.json()["delete_only"] is False
    fake.containers.pop(world_id)
    fake.missing_volumes.add(world_id)

    for suffix in ("/start", "/restart"):
        response = await client.post(f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())
        assert response.status_code == 409
        assert response.json() == {"detail": RECONCILE_DATA_MISSING}

    world = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"][0]
    assert (world["status"], world["status_text"], world["delete_only"]) == ("error", RECONCILE_DATA_MISSING, True)

    deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
    assert deleted.status_code == 204
    assert store.get_world(world_id) is None


@pytest.mark.usefixtures("_override")
async def test_api_interrupted_world_answers_409(
    client: httpx.AsyncClient, fake: FakeProvisioner, store: WorldStore
) -> None:
    """WR-05: Container existiert, Erstellen brach ab; Start und Neustart lassen ihn unberührt."""
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_INTERRUPTED)
    fake.calls.clear()

    for suffix in ("/start", "/restart"):
        response = await client.post(f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())
        assert response.status_code == 409
        assert response.json() == {"detail": RECONCILE_INTERRUPTED}

    assert fake.calls == []
    world = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"][0]
    assert world["delete_only"] is True
    assert world["last_error"] == RECONCILE_INTERRUPTED


# WR-01 (Phase-2-Review): Auch Fehler außerhalb von ProvisionerError räumen das Erzeugen auf.


def _no_space(*args: object) -> WorldPayload:
    del args
    raise OSError(28, "No space left on device")


async def test_payload_os_error_on_create_leaves_no_creating_row(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ENOSPC beim Spoolen des Spiels: keine Zeile auf creating, Port frei, deutsche Meldung."""
    monkeypatch.setattr(service_module, "build_world_payload", _no_space)

    with pytest.raises(ProvisionerError) as raised:
        await service.create_world("Welt")

    assert str(raised.value) == PAYLOAD_FAILED
    assert isinstance(raised.value.__cause__, OSError)
    assert store.list_worlds() == []
    assert store.used_ports() == set()
    # touched_docker war schon wahr: Aufräumen samt Volume lief.
    assert [keep for _, keep in fake.removed] == [False]


async def test_unexpected_error_on_create_is_cleaned_up(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.create_errors = [RuntimeError("unerwartet")]  # pyright: ignore[reportAttributeAccessIssue]

    with pytest.raises(ProvisionerError, match=CREATE_FAILED):
        await service.create_world("Welt")

    assert store.list_worlds() == []
    assert len(fake.removed) == 1


async def test_unexpected_error_with_failed_cleanup_marks_failed_not_creating(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    fake.create_errors = [RuntimeError("unerwartet")]  # pyright: ignore[reportAttributeAccessIssue]
    fake.remove_error = ProvisionerError("Aufräumen kaputt")

    with pytest.raises(ProvisionerError, match=CREATE_FAILED):
        await service.create_world("Welt")

    rows = store.list_worlds()
    assert [(row.op_state, row.last_error) for row in rows] == [("failed", CREATE_FAILED)]


async def test_payload_os_error_on_start_saga_marks_failed(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auch die Neuerzeugung beim Start bekommt einen ProvisionerError statt eines rohen OSError."""
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.start_errors = [PortInUseError(30015)]
    monkeypatch.setattr(service_module, "build_world_payload", _no_space)

    with pytest.raises(ProvisionerError, match="Speicherplatz"):
        await service.start_world(created.id)

    row = store.get_world(created.id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", PAYLOAD_FAILED)
    # Nach dem Freiräumen bleibt die Welt startbar (Volume ist erhalten).
    assert (await _view_of(service, created.id)).delete_only is False


@pytest.mark.usefixtures("_override")
async def test_api_create_with_payload_error_answers_german_500(
    client: httpx.AsyncClient, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_module, "build_world_payload", _no_space)

    response = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())

    assert response.status_code == 500
    assert response.json() == {"detail": PAYLOAD_FAILED}
    assert store.list_worlds() == []


@pytest.mark.usefixtures("_override")
async def test_api_list_survives_unknown_preset(client: httpx.AsyncClient, store: WorldStore) -> None:
    """WR-02: Eine Zeile mit unbekannter Spielart macht GET /api/worlds nicht zum 500er."""
    first = (await client.post("/api/worlds", json={"name": "Alt"}, headers=appapi_headers())).json()
    second = (await client.post("/api/worlds", json={"name": "Neu"}, headers=appapi_headers())).json()
    store.update_world(first["id"], preset="entfernt")

    response = await client.get("/api/worlds", headers=appapi_headers())

    assert response.status_code == 200
    worlds = {world["id"]: world for world in response.json()["worlds"]}
    assert worlds[first["id"]]["status"] == "error"
    assert worlds[first["id"]]["preset_title"] == "Unbekannte Spielart"
    assert worlds[second["id"]]["status"] == "running"


# 03-01: Mods und Zugangsdatei vor jedem Start (Nachrüsten älterer Welten).

EMPTY_ACCESS = render_access_file(0, {})


def _access_of(archive_bytes: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
        names = tar.getnames()
        assert "worldmods/gameworld_access/init.lua" in names
        assert "worldmods/gameworld_status/init.lua" in names
        handle = tar.extractfile(ACCESS_FILE_NAME)
        assert handle is not None
        return handle.read()


async def test_create_writes_files_before_start(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    assert fake.calls == [f"files:{created.id}", f"start:{created.id}"]
    assert _access_of(fake.written[0][1]) == EMPTY_ACCESS


async def test_start_writes_files_before_start(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    fake.calls.clear()

    await service.start_world(created.id)

    assert fake.calls == [f"files:{created.id}", f"start:{created.id}"]


async def test_missing_container_on_write_recreates_then_writes_and_starts(
    service: WorldService, fake: FakeProvisioner
) -> None:
    """WorldNotFoundError schon beim Schreiben nimmt den Neuerzeugungspfad, danach Schreiben und Start."""
    created = await service.create_world("Welt")
    fake.containers.pop(created.id)
    fake.calls.clear()
    fake.created.clear()
    fake.written.clear()

    view = await service.start_world(created.id)

    assert fake.created == [(created.id, created.port, True)]
    assert fake.calls == [f"files:{created.id}", f"start:{created.id}"]
    assert [world for world, _ in fake.written] == [created.id]
    assert view.status == "running"


async def test_payload_carries_empty_access_file(service: WorldService, payload_args: list[tuple[object, ...]]) -> None:
    await service.create_world("Welt")
    assert payload_args[0][3] == EMPTY_ACCESS


# 04-01: Zeit-Mod und Regeldatei in jeder Welt, vor jedem Start neu geschrieben.


def _time_rules_of(archive_bytes: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
        names = tar.getnames()
        assert "worldmods/gameworld_time/init.lua" in names
        assert "worldmods/gameworld_time/mod.conf" in names
        assert RULES_FILE_NAME in names
        assert LEDGER_FILE_NAME not in names
        handle = tar.extractfile(RULES_FILE_NAME)
        assert handle is not None
        return handle.read()


def _assert_empty_rules(content: bytes) -> None:
    lines = content.decode("ascii").split("\n")
    head = lines[0].split(" ")
    # Generation kommt jetzt aus der Datenbank (ab 04-03), nicht mehr fest 0.
    assert head[:2] == ["gameworld-time", "1"]
    assert int(head[2]) >= 0
    assert int(head[3]) > 0
    assert lines[1:] == ["end", ""]


async def test_payload_carries_empty_time_rules(service: WorldService, payload_args: list[tuple[object, ...]]) -> None:
    await service.create_world("Welt")
    time_file = payload_args[0][4]
    assert isinstance(time_file, bytes)
    _assert_empty_rules(time_file)


async def test_every_start_writes_time_mod_and_rules(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    _assert_empty_rules(_time_rules_of(fake.written[0][1]))
    await service.stop_world(created.id)
    fake.written.clear()

    await service.restart_world(created.id)

    assert [world for world, _ in fake.written] == [created.id]
    _assert_empty_rules(_time_rules_of(fake.written[0][1]))


# 03-05: Spielernamen und Zugangsschutz-Status in der Weltenliste, kein Weltschlüssel in der API.

VERIFIER = "#1#c2FsdA==#dmVyaWZpZXI="


def _invite_players(store: WorldStore, world_id: str, *names: str) -> None:
    from gameworld.worlds.store import PlayerRow

    verifiers: dict[str, str] = {}
    for name in names:
        nc_user = f"nc-{name.lower()}"
        if store.get_player(nc_user) is None:
            store.insert_player(PlayerRow(nc_user=nc_user, player_name=name, rotation=0))
        verifiers[nc_user] = VERIFIER
    store.apply_world_access(world_id, verifiers)


async def test_fresh_access_state_needs_no_restart(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.access_states[world_id] = StatusFile(FRESH, b"3")
    view = await _view_of(service, world_id)
    assert view.status == "running"
    assert view.access_restart_needed is False


async def test_missing_access_state_needs_restart(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    view = await _view_of(service, world_id)
    assert view.status == "running"
    assert view.access_restart_needed is True


async def test_stale_access_state_needs_restart(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.access_states[world_id] = StatusFile(STALE, b"1")
    assert (await _view_of(service, world_id)).access_restart_needed is True


@pytest.mark.usefixtures("clock")
async def test_access_state_only_read_when_running(service: WorldService, fake: FakeProvisioner) -> None:
    """Gestoppt, startend oder fehlerhaft: kein Hinweis, kein Lesen der State-Datei."""
    starting = await _running_world(service, fake, "Startend", mtime=STALE)
    stopped = await _running_world(service, fake, "Gestoppt")
    await service.stop_world(stopped)
    broken = await _running_world(service, fake, "Kaputt")
    fake.containers[broken] = (fake.containers[broken][0], "exited")
    fake.extra[broken]["exit_code"] = 137
    fake.access_state_reads.clear()

    views = {view.id: view for view in await service.list_worlds()}

    assert [views[world].status for world in (starting, stopped, broken)] == ["starting", "stopped", "error"]
    assert all(views[world].access_restart_needed is False for world in (starting, stopped, broken))
    assert fake.access_state_reads == []


async def test_access_state_error_is_isolated(service: WorldService, fake: FakeProvisioner) -> None:
    first = await _running_world(service, fake, "Eins")
    second = await _running_world(service, fake, "Zwei")
    fake.access_state_error = ProvisionerError("Der Zugangsstand der Welt ist nicht lesbar.")
    views = {view.id: view for view in await service.list_worlds()}
    assert views[first].access_restart_needed is False
    assert views[second].access_restart_needed is False
    assert views[first].status == views[second].status == "running"


async def test_invited_players_are_sorted_names(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia", "Leo")
    view = await _view_of(service, created.id)
    assert view.invited_players == ["Leo", "Mia"]
    assert VERIFIER not in repr(view)


@pytest.mark.usefixtures("clock")
async def test_invited_players_shown_when_docker_unreachable(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    fake.list_error = DockerUnavailableError("Proxy weg")
    view = await _view_of(service, created.id)
    assert view.status == "unknown"
    assert view.invited_players == ["Mia"]
    assert view.access_restart_needed is False


@pytest.mark.usefixtures("clock")
async def test_cache_copies_invited_players(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    first = await _view_of(service, created.id)
    first.invited_players.append("Eindringling")
    assert (await _view_of(service, created.id)).invited_players == ["Mia"]


@pytest.mark.usefixtures("_override")
async def test_api_create_has_no_world_key_but_new_fields(client: httpx.AsyncClient, store: WorldStore) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    assert created.status_code == 201
    body = created.json()
    assert "world_key" not in body
    row = store.get_world(body["id"])
    assert row is not None
    assert row.world_key
    assert row.world_key not in created.text
    assert body["invited_players"] == []
    assert isinstance(body["access_restart_needed"], bool)
    assert isinstance(body["time_restart_needed"], bool)
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"][0]
    assert {"invited_players", "access_restart_needed", "time_restart_needed"} <= listing.keys()
    assert "world_key" not in listing


# 04-03: Zeit-Mod aus Schema 4 (Zählbuch verbuchen, Regeldatei rendern, Neustart-Hinweis)

TIME_WEEK = WeekPlan({weekday: DayRule(True, 60, None, None) for weekday in range(1, 8)})


def _rules_of(archive_bytes: bytes) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
        if RULES_FILE_NAME not in tar.getnames():
            return b""
        handle = tar.extractfile(RULES_FILE_NAME)
        assert handle is not None
        return handle.read()


def _ledger_status(mtime: str, written_at: int, **seconds: int) -> StatusFile:
    lines = [f"{LEDGER_HEADER} {written_at} 0", *(f"{name} {value}" for name, value in seconds.items()), "end", ""]
    return StatusFile(mtime, "\n".join(lines).encode("ascii"))


def _tar_names(archive_bytes: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as tar:
        return tar.getnames()


async def test_push_access_also_pushes_time_rules(service: WorldService, fake: FakeProvisioner) -> None:
    """Einladungspfad: push_access schreibt im selben Sperrblock auch die Regeldatei (push_time)."""
    created = await service.create_world("Welt")
    fake.written.clear()
    with service.mutation():
        assert service.push_access(created.id) is True
    assert len(fake.written) == 2
    assert ACCESS_FILE_NAME in _tar_names(fake.written[0][1])
    assert RULES_FILE_NAME in _tar_names(fake.written[1][1])


async def test_newly_invited_child_appears_in_rules_immediately(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    fake.written.clear()
    with service.mutation():
        service.push_access(created.id)
    assert b"\nMia " in _rules_of(fake.written[1][1])


async def test_launch_books_ledger_before_rendering(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """_launch liest das Zählbuch vor dem Rendern (Pitfall 7) und verbucht Kinder mit Regeln."""
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    store.set_ledger_seen(created.id, {"Mia": 10})
    fake.ledgers[created.id] = _ledger_status(FRESH, int(time.time()), Mia=70)
    await service.stop_world(created.id)
    fake.ledger_reads.clear()

    await service.start_world(created.id)

    assert created.id in fake.ledger_reads
    from gameworld.playtime.plan import load_zone, local_day

    berlin_day = local_day(int(time.time()), load_zone(""))
    assert store.usage("nc-mia", berlin_day) == 60
    assert store.ledger_seen(created.id) == {"Mia": 70}


async def test_tick_time_skips_when_locked(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    del created
    fake.written.clear()
    assert service_module._LOCK.acquire(blocking=False)
    try:
        service.tick_time()
    finally:
        service_module._LOCK.release()
    assert fake.written == []


async def test_tick_time_renders_running_worlds(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    fake.written.clear()
    fake.ledger_reads.clear()

    service.tick_time()

    assert created.id in fake.ledger_reads
    assert any(b"\nMia " in _rules_of(archive) for _world_id, archive in fake.written)


async def test_tick_time_isolates_read_error(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = await service.create_world("Kaputt")
    healthy = await service.create_world("Heil")
    _invite_players(store, healthy.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    fake.written.clear()
    real = fake.read_time_ledger

    def flaky(world_id: str) -> StatusFile | None:
        if world_id == broken.id:
            raise ProvisionerError("Das Spielzeit-Zählbuch der Welt ist nicht lesbar.")
        return real(world_id)

    monkeypatch.setattr(fake, "read_time_ledger", flaky)
    service.tick_time()

    assert any(b"\nMia " in _rules_of(archive) for world_id, archive in fake.written if world_id == healthy.id)


@pytest.mark.parametrize(
    ("stage", "error"),
    [
        ("book", sqlite3.OperationalError("database is locked")),
        ("render", ValueError("kaputte Zeile")),
        ("render", sqlite3.OperationalError("database is locked")),
        ("events", sqlite3.OperationalError("database is locked")),
    ],
)
async def test_tick_time_isolates_database_and_value_errors(
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    stage: str,
    error: Exception,
) -> None:
    """WR-06: Ein Datenbank- oder Wertfehler in Welt A setzt Welt B im selben Takt nicht aus."""
    broken = await service.create_world("Kaputt")
    healthy = await service.create_world("Heil")
    _invite_players(store, healthy.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    fake.written.clear()
    engine = service.time
    targets = {
        "book": (service, "_book_ledger"),
        "render": (engine, "render"),
        "events": (service, "_collect_events"),
    }
    owner, name = targets[stage]
    real = getattr(owner, name)

    def flaky(world_id: str, *args: object) -> object:
        if world_id == broken.id:
            raise error
        return real(world_id, *args)

    monkeypatch.setattr(owner, name, flaky)
    with caplog.at_level("WARNING"):
        service.tick_time()

    assert any(b"\nMia " in _rules_of(archive) for world_id, archive in fake.written if world_id == healthy.id)
    assert broken.id in caplog.text
    assert type(error).__name__ in caplog.text


async def test_tick_time_does_not_swallow_programming_errors(
    service: WorldService, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gegenprobe: Andere Fehlertypen (Programmfehler) bleiben sichtbar und werden nicht verschluckt."""
    await service.create_world("Welt")

    def broken(world_id: str) -> tuple[bytes, bool]:
        del world_id
        raise TypeError("Programmfehler")

    monkeypatch.setattr(service.time, "render", broken)
    with pytest.raises(TypeError):
        service.tick_time()


async def test_incomplete_ledger_is_logged_not_silent(
    service: WorldService, fake: FakeProvisioner, caplog: pytest.LogCaptureFixture
) -> None:
    """WR-03: Ein vorhandenes Zählbuch ohne Schlusszeile wird nicht still übergangen."""
    created = await service.create_world("Welt")
    fake.ledgers[created.id] = StatusFile(FRESH, b"gameworld-time-used 1 1 0\nMia 40\n")
    with caplog.at_level("WARNING"):
        service.tick_time()
    assert "Zählbuch unvollständig" in caplog.text
    assert "Mia" not in caplog.text


async def test_failed_push_time_is_retried_by_next_tick(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01: Scheitert das Schreiben einmal, schreibt der nächste Takt die Regeldatei sicher nach."""
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    real = fake.write_world_files

    def broken(world_id: str, archive: bytes) -> None:
        raise ProvisionerError("Docker ist gerade nicht erreichbar.")

    monkeypatch.setattr(fake, "write_world_files", broken)
    with service.mutation():
        assert service.push_time(created.id) is False
    monkeypatch.setattr(fake, "write_world_files", real)
    fake.written.clear()

    service.tick_time()

    assert any(b"\nMia " in _rules_of(archive) for world_id, archive in fake.written if world_id == created.id)


async def test_failed_tick_write_is_retried_by_next_tick(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CR-01: Auch ein im Takt gescheitertes Schreiben holt der folgende Takt nach."""
    created = await service.create_world("Welt")
    _invite_players(store, created.id, "Mia")
    store.set_child_plan("nc-mia", TIME_WEEK, None, "admin", "t")
    real = fake.write_world_files
    calls: list[str] = []

    def broken(world_id: str, archive: bytes) -> None:
        calls.append(world_id)
        raise ProvisionerError("Docker ist gerade nicht erreichbar.")

    monkeypatch.setattr(fake, "write_world_files", broken)
    service.tick_time()
    assert calls == [created.id]
    monkeypatch.setattr(fake, "write_world_files", real)
    fake.written.clear()

    service.tick_time()

    assert any(b"\nMia " in _rules_of(archive) for world_id, archive in fake.written if world_id == created.id)
    fake.written.clear()
    service.tick_time()
    # Nach dem erfolgreichen Schreiben bleibt es beim alten Verhalten: nichts Neues zu schreiben.
    assert fake.written == []


async def test_time_restart_needed_missing_ledger(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    view = await _view_of(service, world_id)
    assert view.status == "running"
    assert view.time_restart_needed is True


async def test_time_restart_needed_fresh_ledger(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.ledgers[world_id] = StatusFile(FRESH, b"gameworld-time-used 1 1 0\nend\n")
    assert (await _view_of(service, world_id)).time_restart_needed is False


async def test_time_restart_needed_stale_ledger(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.ledgers[world_id] = StatusFile(STALE, b"gameworld-time-used 1 1 0\nend\n")
    assert (await _view_of(service, world_id)).time_restart_needed is True


async def test_time_restart_needed_read_error_is_false(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.ledger_error = ProvisionerError("Das Spielzeit-Zählbuch der Welt ist nicht lesbar.")
    assert (await _view_of(service, world_id)).time_restart_needed is False


# 04.1-02: Ereignisse, Start/Stopp und Fähigkeits-Merker im Takt (kein Netz, nur SQLite)


def _events_file(mtime: str, seq: int, *lines: tuple[int, int, str, str]) -> StatusFile:
    body = [f"gameworld-events 1 {seq}", *(f"{s} {at} {kind} {name}" for s, at, kind, name in lines), "end", ""]
    return StatusFile(mtime, "\n".join(body).encode("ascii"))


def _outbox(store: WorldStore) -> list[tuple[str, str, str]]:
    return [(row.world_id, row.kind, row.name) for row in store.outbox_batch(limit=1000)]


async def test_tick_old_event_file_anchors_then_reports_new_lines(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    old = int(time.time()) - 1000
    lines = [(1, old, "join", "Mia"), (2, old + 5, "leave", "Mia"), (3, old + 9, "deny", "Fremd")]
    fake.events[created.id] = _events_file(FRESH, 3, *lines)

    service.tick_time()

    assert created.id in fake.event_reads
    assert _outbox(store) == []
    assert store.event_cursor(created.id) == 3

    now = int(time.time())
    fake.events[created.id] = _events_file(FRESH, 5, *lines, (4, now, "join", "Leo"), (5, now, "warn10", "Leo"))
    service.tick_time()

    assert _outbox(store) == [(created.id, "join", "Leo"), (created.id, "warn10", "Leo")]
    assert store.event_cursor(created.id) == 5


async def test_tick_fresh_event_file_reports_first_events(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    fake.events[created.id] = _events_file(FRESH, 1, (1, int(time.time()) - 10, "join", "lena"))

    service.tick_time()

    assert _outbox(store) == [(created.id, "join", "lena")]
    assert store.event_cursor(created.id) == 1
    # Derselbe Stand im nächsten Takt: nichts doppelt.
    service.tick_time()
    assert len(_outbox(store)) == 1


async def test_tick_drops_future_deny_from_manipulated_file(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """IN-10: Eine deny-Zeile mit Zukunftsdatum landet nicht in der Outbox; der Cursor rückt trotzdem vor."""
    created = await service.create_world("Welt")
    now = int(time.time())
    fake.events[created.id] = _events_file(
        FRESH, 2, (1, now - 5, "deny", "Echt"), (2, 999_999_999_999, "deny", "Zukunft")
    )
    service.tick_time()
    assert _outbox(store) == [(created.id, "deny", "Echt")]
    assert store.event_cursor(created.id) == 2


async def test_tick_event_errors_are_isolated_per_world(
    service: WorldService,
    fake: FakeProvisioner,
    store: WorldStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = await service.create_world("Kaputt")
    garbled = await service.create_world("Halb")
    healthy = await service.create_world("Heil")
    now = int(time.time())
    fake.events[garbled.id] = StatusFile(FRESH, f"gameworld-events 1 1\n1 {now} join Geheimname\n".encode())
    fake.events[healthy.id] = _events_file(FRESH, 1, (1, now, "join", "Mia"))
    real = fake.read_events

    def flaky(world_id: str) -> StatusFile | None:
        if world_id == broken.id:
            raise ProvisionerError("Die Ereignisdatei der Welt ist nicht lesbar.")
        return real(world_id)

    monkeypatch.setattr(fake, "read_events", flaky)
    with caplog.at_level("WARNING"):
        service.tick_time()

    assert _outbox(store) == [(healthy.id, "join", "Mia")]
    assert store.event_cursor(broken.id) is None
    assert store.event_cursor(garbled.id) is None
    assert broken.id in caplog.text
    assert garbled.id in caplog.text
    assert "Geheimname" not in caplog.text


async def test_tick_reports_start_and_stop_from_docker_state(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    service.tick_time()
    # Erste Beobachtung verankert nur.
    assert _outbox(store) == []
    assert store.run_state(created.id) is True

    port, _ = fake.containers[created.id]
    fake.containers[created.id] = (port, "exited")
    service.tick_time()
    assert _outbox(store) == [(created.id, "stop", "")]
    assert store.run_state(created.id) is False

    fake.containers[created.id] = (port, "running")
    service.tick_time()
    assert _outbox(store) == [(created.id, "stop", ""), (created.id, "start", "")]

    # Neustart zwischen zwei Takten: gewollt ruhig, keine Meldung.
    await service.restart_world(created.id)
    service.tick_time()
    assert len(_outbox(store)) == 2


async def test_events_restart_needed_missing_file(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    view = await _view_of(service, world_id)
    assert view.status == "running"
    assert view.events_restart_needed is True


async def test_events_restart_needed_fresh_file(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.events[world_id] = _events_file(FRESH, 0)
    assert (await _view_of(service, world_id)).events_restart_needed is False


async def test_events_restart_needed_stale_file(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.events[world_id] = _events_file(STALE, 0)
    assert (await _view_of(service, world_id)).events_restart_needed is True


async def test_events_restart_needed_read_error_is_false(
    service: WorldService, fake: FakeProvisioner, caplog: pytest.LogCaptureFixture
) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.events_error = ProvisionerError("Die Ereignisdatei der Welt ist nicht lesbar.")
    with caplog.at_level("WARNING"):
        assert (await _view_of(service, world_id)).events_restart_needed is False
    assert world_id in caplog.text


async def test_events_restart_needed_false_when_stopped(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    await service.stop_world(world_id)
    assert (await _view_of(service, world_id)).events_restart_needed is False


async def test_delete_removes_notify_data(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    other = await service.create_world("Andere")
    for world_id in (created.id, other.id):
        store.take_events(world_id, 2, [("join", "Mia", 1, "")])
        store.set_run_state(world_id, running=True)

    await service.delete_world(created.id)

    assert store.event_cursor(created.id) is None
    assert store.run_state(created.id) is None
    assert [row.world_id for row in store.outbox_batch()] == [other.id]
    assert store.event_cursor(other.id) == 2


async def test_retry_delete_removes_notify_data(service: WorldService, store: WorldStore) -> None:
    from gameworld.worlds.reconciler import ReconcileAction

    created = await service.create_world("Welt")
    store.take_events(created.id, 2, [("join", "Mia", 1, "")])
    store.set_run_state(created.id, running=True)
    store.update_world(created.id, desired_state="deleted")
    row = store.get_world(created.id)
    assert row is not None

    service._apply(row, ReconcileAction.RETRY_DELETE)  # pyright: ignore[reportPrivateUsage]

    assert store.get_world(created.id) is None
    assert store.event_cursor(created.id) is None
    assert store.run_state(created.id) is None
    assert store.outbox_batch() == []


@pytest.mark.usefixtures("_override")
async def test_api_world_carries_events_restart_needed(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    assert created.status_code == 201
    assert isinstance(created.json()["events_restart_needed"], bool)
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"][0]
    assert "events_restart_needed" in listing


# Phase 5 (05-04): Busy-Zustände sperren Elternaktionen, ohne Pause und Takt zu blockieren.

BUSY_STATES = ["backing_up", "restoring", "restoring_swap"]


def _job(store: WorldStore, world_id: str, state: str, message: str | None = None) -> None:
    store.set_backup_job(
        world_id, "backup", state, message, "Welt 2026-10-23.tar.gz", "2026-10-23T10:00:00+00:00", None
    )


@pytest.mark.parametrize("op_state", BUSY_STATES)
@pytest.mark.parametrize("operation", ["start_world", "stop_world", "restart_world", "delete_world"])
async def test_busy_world_refuses_parent_actions(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, op_state: str, operation: str
) -> None:
    created = await service.create_world("Welt")
    store.update_world(created.id, op_state=op_state)
    fake.calls.clear()
    fake.removed.clear()

    with pytest.raises(WorldBusyError, match="gerade gesichert oder wiederhergestellt"):
        await getattr(service, operation)(created.id)

    assert fake.calls == []
    assert fake.removed == []
    row = store.get_world(created.id)
    assert row is not None
    assert (row.desired_state, row.op_state) == ("running", op_state)


async def test_delete_refused_while_job_runs_in_upload_phase(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Upload-Phase: op_state ist wieder ready, der Job steht noch auf running (T-05-45)."""
    created = await service.create_world("Welt")
    _job(store, created.id, "running")
    fake.calls.clear()

    with pytest.raises(WorldBusyError):
        await service.delete_world(created.id)

    assert fake.calls == []
    assert fake.removed == []
    row = store.get_world(created.id)
    assert row is not None
    assert (row.desired_state, row.op_state) == ("running", "ready")
    job = store.get_backup_job(created.id)
    assert job is not None
    assert job.state == "running"


@pytest.mark.parametrize("state", ["ok", "failed"])
async def test_delete_with_finished_job_removes_job_but_keeps_backups(
    service: WorldService, store: WorldStore, state: str
) -> None:
    created = await service.create_world("Welt")
    _job(store, created.id, state)
    store.add_backup(
        BackupRow(
            file_id=42,
            owner_uid="eltern",
            world_id=created.id,
            path="/Gameworld/Welt/Welt.tar.gz",
            name="Welt.tar.gz",
            size=10,
            sha256="0" * 64,
            preset="mtg_kreativ",
            kind="backup",
            created_at="2026-10-23T10:00:00+00:00",
        )
    )

    await service.delete_world(created.id)

    assert store.get_world(created.id) is None
    assert store.get_backup_job(created.id) is None
    assert [row.file_id for row in store.backups_for("eltern", created.id)] == [42]


@pytest.mark.usefixtures("_override")
async def test_api_busy_world_answers_409(client: httpx.AsyncClient, fake: FakeProvisioner, store: WorldStore) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    store.update_world(world_id, op_state="backing_up")
    fake.calls.clear()

    for method, suffix in (("POST", "/start"), ("POST", "/stop"), ("POST", "/restart"), ("DELETE", "")):
        response = await client.request(method, f"/api/worlds/{world_id}{suffix}", headers=appapi_headers())
        assert response.status_code == 409
        assert response.json() == {"detail": "Die Welt wird gerade gesichert oder wiederhergestellt."}
    assert fake.calls == []


@pytest.mark.usefixtures("_override")
async def test_api_delete_with_running_job_answers_409(client: httpx.AsyncClient, store: WorldStore) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    _job(store, world_id, "running")

    response = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())

    assert response.status_code == 409
    assert response.json() == {"detail": WORLD_BUSY}
    assert store.get_world(world_id) is not None


def _pause_now(current: PauseState | None, now: int) -> PauseState:
    del current
    return PauseState(started_by="eltern", ab=now, bis=now + 600, art=ART_PAUSE)


async def test_pause_writes_rules_but_never_restarts_busy_world(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Alter Mod (keine Ereignisdatei) würde neu starten; busy Welten bekommen nur die Regeldatei."""
    busy = await _running_world(service, fake, "Busy")
    ready = await _running_world(service, fake, "Bereit")
    store.update_world(busy, op_state="backing_up")
    fake.calls.clear()

    result = service.apply_pause_sync(_pause_now, OUTBOX_PAUSE_START)

    assert f"stop:{busy}" not in fake.calls
    assert f"start:{busy}" not in fake.calls
    assert f"files:{busy}" in fake.calls
    # Gegenprobe: Die bereite Welt mit altem Mod startet neu.
    assert f"stop:{ready}" in fake.calls
    by_id = {world.world_id: world for world in result.worlds}
    assert (by_id[busy].applied, by_id[busy].restarted) == (True, False)
    assert by_id[ready].restarted is True
    row = store.get_world(busy)
    assert row is not None
    assert row.op_state == "backing_up"


@pytest.mark.parametrize("op_state", BUSY_STATES)
async def test_tick_reports_no_stop_or_start_for_busy_world(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, op_state: str
) -> None:
    created = await service.create_world("Welt")
    service.tick_time()
    assert store.run_state(created.id) is True
    store.update_world(created.id, op_state=op_state)
    port, _ = fake.containers[created.id]
    fake.containers[created.id] = (port, "exited")

    service.tick_time()
    fake.containers[created.id] = (port, "running")
    store.update_world(created.id, op_state="ready")
    service.tick_time()

    assert _outbox(store) == []


@pytest.mark.parametrize("op_state", BUSY_STATES)
async def test_busy_world_reads_no_status_file(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, op_state: str
) -> None:
    world_id = await _running_world(service, fake, "Welt")
    store.update_world(world_id, op_state=op_state)
    fake.status_reads.clear()

    view = await _view_of(service, world_id)

    assert world_id not in fake.status_reads
    assert view.players == []
    expected = "backing_up" if op_state == "backing_up" else "restoring"
    assert view.status == expected


async def test_list_carries_backup_job(
    service: WorldService, fake: FakeProvisioner, store: WorldStore, clock: Clock
) -> None:
    created = await service.create_world("Welt")
    assert (await _view_of(service, created.id)).backup_job is None
    clock.advance(LIST_CACHE_SECONDS)

    store.set_backup_job(
        created.id,
        "backup",
        "failed",
        "Kein Platz",
        "Welt.tar.gz",
        "2026-10-23T10:00:00+00:00",
        "2026-10-23T10:01:00+00:00",
    )
    job = (await _view_of(service, created.id)).backup_job
    assert job is not None
    assert (job.kind, job.state, job.message, job.file_name, job.finished_at) == (
        "backup",
        "failed",
        "Kein Platz",
        "Welt.tar.gz",
        "2026-10-23T10:01:00+00:00",
    )

    # Auch ohne Docker bleibt der Fehler sichtbar (D-11).
    fake.list_error = DockerUnavailableError("Proxy weg")
    clock.advance(LIST_CACHE_SECONDS)
    unknown = await _view_of(service, created.id)
    assert unknown.status == "unknown"
    assert unknown.backup_job is not None
    assert unknown.backup_job.state == "failed"


@pytest.mark.usefixtures("_override")
async def test_api_world_carries_backup_job(client: httpx.AsyncClient, store: WorldStore) -> None:
    created = await client.post("/api/worlds", json={"name": "Welt"}, headers=appapi_headers())
    world_id = created.json()["id"]
    assert created.json()["backup_job"] is None
    store.set_backup_job(world_id, "restore", "failed", "Kaputt", "x.tar.gz", "2026-10-23T10:00:00+00:00", None)

    world = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"][0]

    assert world["backup_job"] == {
        "kind": "restore",
        "state": "failed",
        "message": "Kaputt",
        "file_name": "x.tar.gz",
        "finished_at": None,
    }


# 05-04 Task 3: kurze Offline-Abschnitte, die der Hintergrund-Job aneinanderreiht.


def _rules_written(fake: FakeProvisioner, world_id: str) -> list[bytes]:
    """Regeldateien aus allen Tars, die an diese Welt gingen, in Schreibreihenfolge."""
    result: list[bytes] = []
    for target, archive in fake.written:
        if target != world_id:
            continue
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            if RULES_FILE_NAME in tar.getnames():
                handle = tar.extractfile(RULES_FILE_NAME)
                assert handle is not None
                result.append(handle.read())
    return result


async def test_begin_offline_sets_busy_state_and_returns_ticket(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    fake.calls.clear()

    ticket = service.begin_offline(created.id, "backing_up")

    assert ticket == OfflineTicket(
        world_id=created.id,
        was_running=True,
        preset="mtg_kreativ",
        name="Welt",
        previous_op_state="ready",
        previous_error=None,
    )
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "backing_up"
    assert fake.calls == []
    assert (await _view_of(service, created.id)).status == "backing_up"


async def test_begin_offline_of_stopped_world_was_not_running(service: WorldService) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    assert service.begin_offline(created.id, "backing_up").was_running is False


async def test_begin_offline_refuses_busy_world(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    service.begin_offline(created.id, "backing_up")
    with pytest.raises(WorldBusyError, match=WORLD_BUSY):
        service.begin_offline(created.id, "restoring")
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "backing_up"


async def test_begin_offline_allows_only_one_job_at_a_time(service: WorldService, store: WorldStore) -> None:
    first = await service.create_world("Erste")
    second = await service.create_world("Zweite")
    service.begin_offline(first.id, "backing_up")

    with pytest.raises(WorldBusyError, match=JOB_RUNNING):
        service.begin_offline(second.id, "backing_up")

    row = store.get_world(second.id)
    assert row is not None
    assert row.op_state == "ready"


async def test_begin_offline_refuses_while_job_uploads(service: WorldService, store: WorldStore) -> None:
    """Upload-Phase einer anderen Welt (op_state ready, Job running) sperrt ebenfalls."""
    first = await service.create_world("Erste")
    second = await service.create_world("Zweite")
    _job(store, first.id, "running")

    with pytest.raises(WorldBusyError, match=JOB_RUNNING):
        service.begin_offline(second.id, "backing_up")


async def test_begin_offline_refuses_delete_only_unless_allowed(service: WorldService, store: WorldStore) -> None:
    created = await service.create_world("Welt")
    store.update_world(created.id, op_state="failed", last_error=RECONCILE_DATA_MISSING)

    with pytest.raises(DeleteOnlyError):
        service.begin_offline(created.id, "backing_up")
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"

    ticket = service.begin_offline(created.id, "restoring", allow_failed=True)
    assert (ticket.previous_op_state, ticket.previous_error) == ("failed", RECONCILE_DATA_MISSING)
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "restoring"


async def test_begin_offline_rejects_non_busy_state(service: WorldService) -> None:
    created = await service.create_world("Welt")
    with pytest.raises(ValueError, match="op_state"):
        service.begin_offline(created.id, "ready")


async def test_players_online_reads_status_file_while_busy(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """D-09, T-05-46: Auch im Busy-Zustand zählt die Status-Datei, sonst fehlte der Chat-Hinweis."""
    world_id = await _running_world(service, fake, "Welt")
    service.begin_offline(world_id, "backing_up")

    assert service.players_online(world_id) == 2

    # Die Ansicht bleibt bei Busy-Zuständen ohne Spieler (Task 2).
    view = await _view_of(service, world_id)
    assert view.players == []
    assert view.status == "backing_up"
    row = store.get_world(world_id)
    assert row is not None
    assert row.op_state == "backing_up"


async def test_players_online_is_zero_without_live_players(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    port, _ = fake.containers[world_id]

    fake.containers[world_id] = (port, "exited")
    assert service.players_online(world_id) == 0

    fake.containers[world_id] = (port, "running")
    fake.status_files[world_id] = StatusFile(STALE, b"Mia\n")
    assert service.players_online(world_id) == 0

    fake.status_files.pop(world_id)
    assert service.players_online(world_id) == 0

    fake.status_files[world_id] = StatusFile(FRESH, b"Mia\n")
    fake.status_error = DockerUnavailableError("Proxy weg")
    assert service.players_online(world_id) == 0

    fake.status_error = None
    assert service.players_online(world_id) == 1

    fake.containers.pop(world_id)
    assert service.players_online(world_id) == 0

    fake.list_error = DockerUnavailableError("Proxy weg")
    assert service.players_online(world_id) == 0


async def test_announce_halt_writes_halt_line_while_busy(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.status_files[world_id] = StatusFile(FRESH, b"Mia\n")
    service.begin_offline(world_id, "backing_up")
    fake.written.clear()
    now = int(time.time())

    ab = service.announce_halt(world_id, now)

    assert ab == now + HALT_LEAD_SECONDS
    rules = _rules_written(fake, world_id)
    assert rules
    assert f"@halt {ab}" in rules[-1].decode("ascii").split("\n")


async def test_announce_halt_without_players_changes_nothing(service: WorldService, fake: FakeProvisioner) -> None:
    world_id = await _running_world(service, fake, "Welt")
    fake.status_files[world_id] = StatusFile(FRESH, b"")
    service.begin_offline(world_id, "backing_up")
    fake.written.clear()

    assert service.announce_halt(world_id, int(time.time())) is None
    assert fake.written == []


async def test_stop_for_snapshot_stops_without_booking(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    service.begin_offline(created.id, "backing_up")
    fake.calls.clear()
    fake.ledger_reads.clear()

    service.stop_for_snapshot(created.id)

    assert fake.calls == [f"stop:{created.id}"]
    assert fake.ledger_reads == []
    row = store.get_world(created.id)
    assert row is not None
    assert (row.op_state, row.desired_state) == ("backing_up", "running")

    # Fehlender Container ist kein Fehler.
    fake.containers.pop(created.id)
    service.stop_for_snapshot(created.id)


async def test_end_offline_restarts_running_world_and_clears_halt(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    world_id = await _running_world(service, fake, "Welt")
    service.begin_offline(world_id, "backing_up")
    assert service.announce_halt(world_id, int(time.time())) is not None
    service.stop_for_snapshot(world_id)
    fake.calls.clear()
    fake.written.clear()

    assert service.end_offline(world_id, was_running=True) is None

    assert f"start:{world_id}" in fake.calls
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("ready", None)
    rules = _rules_written(fake, world_id)
    assert rules
    assert not any(line.startswith("@halt") for line in rules[-1].decode("ascii").split("\n"))


async def test_end_offline_keeps_stopped_world_stopped(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    ticket = service.begin_offline(created.id, "backing_up")
    fake.calls.clear()

    assert service.end_offline(created.id, ticket.was_running) is None

    assert fake.calls == []
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "ready"


async def test_end_offline_reports_launch_failure_without_raising(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Pitfall 7: Der Zustand kehrt immer auf ready oder failed zurück."""
    created = await service.create_world("Welt")
    service.begin_offline(created.id, "backing_up")
    service.stop_for_snapshot(created.id)
    fake.start_errors = [ProvisionerError("Docker hat den Start der Welt abgelehnt: kaputt")]

    error = service.end_offline(created.id, was_running=True)

    assert isinstance(error, ProvisionerError)
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"
    assert row.last_error is not None
    assert "kaputt" in row.last_error


async def test_end_offline_reports_unexpected_error_without_raising(
    service: WorldService, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = await service.create_world("Welt")
    service.begin_offline(created.id, "backing_up")

    def broken(row: object) -> None:
        del row
        raise ValueError("kaputt")

    monkeypatch.setattr(service, "_launch", broken)

    error = service.end_offline(created.id, was_running=True)

    assert isinstance(error, ProvisionerError)
    row = store.get_world(created.id)
    assert row is not None
    assert row.op_state == "failed"


async def test_book_ledger_is_public_entry(service: WorldService, fake: FakeProvisioner) -> None:
    created = await service.create_world("Welt")
    fake.ledger_reads.clear()
    service.book_ledger(created.id)
    assert fake.ledger_reads == [created.id]


async def test_offline_sections_hold_lock_only_briefly(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """T-05-16: Zwischen stop_for_snapshot und end_offline läuft eine Pause ohne Warten durch."""
    world_id = await _running_world(service, fake, "Welt")
    stopped = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def job() -> None:
        try:
            ticket = service.begin_offline(world_id, "backing_up")
            service.stop_for_snapshot(world_id)
            stopped.set()
            release.wait(5)
            service.end_offline(world_id, ticket.was_running)
        except BaseException as exc:
            errors.append(exc)
            stopped.set()

    worker = threading.Thread(target=job)
    worker.start()
    try:
        assert stopped.wait(5)
        begin = time.monotonic()
        result = service.apply_pause_sync(_pause_now, OUTBOX_PAUSE_START)
        elapsed = time.monotonic() - begin
    finally:
        release.set()
        worker.join(5)

    assert errors == []
    assert elapsed < 1.0
    assert [(world.world_id, world.restarted) for world in result.worlds] == [(world_id, False)]
    row = store.get_world(world_id)
    assert row is not None
    assert row.op_state == "ready"
    assert f"start:{world_id}" in fake.calls


async def test_fake_snapshot_streams_chunks_and_refuses_running(fake: FakeProvisioner) -> None:
    fake.containers["w"] = (30015, "running")
    fake.snapshots["w"] = b"x" * (2 * SNAPSHOT_CHUNK + 5)
    with pytest.raises(ProvisionerError):
        fake.snapshot_to("w", lambda chunks: list(chunks))

    fake.containers["w"] = (30015, "exited")
    sizes = fake.snapshot_to("w", lambda chunks: [len(chunk) for chunk in chunks])
    assert sizes == [SNAPSHOT_CHUNK, SNAPSHOT_CHUNK, 5]

    fake.snapshot_errors = [DockerUnavailableError("Proxy weg")]
    with pytest.raises(DockerUnavailableError):
        fake.snapshot_to("w", lambda chunks: list(chunks))

    fake.put_world_archive("w", io.BytesIO(b"tar"))
    assert fake.put_archives == [("w", b"tar")]
    assert fake.calls[-1] == "put_archive:w"


# 05-06 Task 1: Tausch über frisches Volume (restore_swap, D-06, T-05-32, T-05-33, T-05-50)


def _record_creates(fake: FakeProvisioner) -> None:
    """Schreibt jedes create_world_container zusätzlich als "create:<id>" in calls."""
    original = fake.create_world_container

    def recording(world_id: str, host_port: int, payload: bytes, *, reuse_volume: bool = False) -> str:
        fake.calls.append(f"create:{world_id}")
        return original(world_id, host_port, payload, reuse_volume=reuse_volume)

    fake.create_world_container = recording  # type: ignore[method-assign]


def _halt_lines(data: bytes) -> list[str]:
    return [line for line in data.decode("ascii").split("\n") if line.startswith("@halt")]


async def _swap_ready(service: WorldService, fake: FakeProvisioner, name: str = "Welt") -> OfflineTicket:
    """Welt im Zustand restoring, gestoppt, Aufrufprotokoll geleert."""
    world_id = await _running_world(service, fake, name)
    ticket = service.begin_offline(world_id, "restoring", allow_failed=True)
    service.stop_for_snapshot(world_id)
    fake.calls.clear()
    fake.written.clear()
    fake.put_archives.clear()
    return ticket


async def test_mark_swap_persists_before_remove(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """T-05-33: Beim remove steht restoring_swap schon in der Datenbank (Boot-Abgleich, Plan 04)."""
    ticket = await _swap_ready(service, fake)
    world_id = ticket.world_id
    seen: list[str] = []
    original = fake.remove_world

    def recording(target: str, *, keep_volume: bool) -> None:
        row = store.get_world(target)
        assert row is not None
        seen.append(row.op_state)
        original(target, keep_volume=keep_volume)

    fake.remove_world = recording  # type: ignore[method-assign]

    service.mark_swap(world_id)
    assert fake.calls == []
    service.restore_swap(world_id, io.BytesIO(b"restore-tar"), None)

    assert seen == ["restoring_swap"]


async def test_restore_swap_rebuilds_on_fresh_volume_in_order(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    ticket = await _swap_ready(service, fake)
    world_id = ticket.world_id
    before = store.get_world(world_id)
    assert before is not None
    _record_creates(fake)
    restore = io.BytesIO(b"restore-tar")
    restore.read()  # Position am Ende: restore_swap muss selbst zurückspulen.

    service.mark_swap(world_id)
    service.restore_swap(world_id, restore, b"zaehlbuch")
    assert service.finish_swap(world_id, was_running=True) is None

    remove = fake.calls.index(f"remove:{world_id}")
    create = fake.calls.index(f"create:{world_id}")
    puts = [index for index, call in enumerate(fake.calls) if call == f"put_archive:{world_id}"]
    start = fake.calls.index(f"start:{world_id}")
    assert len(puts) == 2
    assert remove < create < puts[0] < puts[1] < start
    # Frisches Volume (T-05-32): Ein heißes Journal der kaputten Welt überlebt nicht.
    assert fake.removed[-1] == (world_id, False)
    assert fake.created[-1] == (world_id, before.port, False)
    assert fake.put_archives[0] == (world_id, b"restore-tar")
    with tarfile.open(fileobj=io.BytesIO(fake.put_archives[1][1]), mode="r:") as tar:
        assert tar.getnames() == [LEDGER_FILE_NAME]
        handle = tar.extractfile(LEDGER_FILE_NAME)
        assert handle is not None
        assert handle.read() == b"zaehlbuch"
    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error, row.desired_state) == ("ready", None, "running")


async def test_restore_swap_without_ledger_puts_only_world(service: WorldService, fake: FakeProvisioner) -> None:
    ticket = await _swap_ready(service, fake)
    service.mark_swap(ticket.world_id)
    service.restore_swap(ticket.world_id, io.BytesIO(b"restore-tar"), None)
    assert fake.put_archives == [(ticket.world_id, b"restore-tar")]


async def test_restore_swap_renders_rules_without_halt(
    service: WorldService, fake: FakeProvisioner, payload_args: list[tuple[object, ...]]
) -> None:
    """T-05-50: Die frisch angelegte Welt bekommt eine Regeldatei ohne @halt."""
    ticket = await _swap_ready(service, fake)
    world_id = ticket.world_id
    service.time.set_halt(world_id, int(time.time()) + HALT_LEAD_SECONDS)
    data, _changed = service.time.render(world_id)
    assert _halt_lines(data)  # Positivkontrolle: Ohne clear_halt stünde der Halt drin.
    payload_args.clear()

    service.mark_swap(world_id)
    service.restore_swap(world_id, io.BytesIO(b"restore-tar"), None)

    assert len(payload_args) == 1
    rules = payload_args[0][4]
    assert isinstance(rules, bytes)
    assert _halt_lines(rules) == []


async def test_restore_swap_resets_event_cursor(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    ticket = await _swap_ready(service, fake)
    store.take_events(ticket.world_id, 41, [])
    assert store.event_cursor(ticket.world_id) == 41

    service.mark_swap(ticket.world_id)
    service.restore_swap(ticket.world_id, io.BytesIO(b"restore-tar"), None)

    assert store.event_cursor(ticket.world_id) is None


async def test_restore_swap_tolerates_missing_container(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """D-15: Eine kaputte Welt ohne Container lässt sich trotzdem neu aufbauen."""
    created = await service.create_world("Kaputt")
    store.update_world(created.id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    fake.containers.pop(created.id)
    service.begin_offline(created.id, "restoring", allow_failed=True)
    fake.remove_error = WorldNotFoundError("Diese Welt gibt es nicht (mehr).")

    service.mark_swap(created.id)
    service.restore_swap(created.id, io.BytesIO(b"restore-tar"), None)
    fake.remove_error = None
    assert service.finish_swap(created.id, was_running=True) is None

    row = store.get_world(created.id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("ready", None)
    assert not service_module.delete_only(row)


async def test_restore_swap_passes_errors_to_caller(service: WorldService, fake: FakeProvisioner) -> None:
    ticket = await _swap_ready(service, fake)
    fake.create_errors = [ProvisionerError("Docker hat die Anfrage abgelehnt: kaputt")]
    service.mark_swap(ticket.world_id)
    with pytest.raises(ProvisionerError, match="kaputt"):
        service.restore_swap(ticket.world_id, io.BytesIO(b"restore-tar"), None)


async def test_finish_swap_keeps_stopped_world_stopped_and_without_halt(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    created = await service.create_world("Welt")
    await service.stop_world(created.id)
    ticket = service.begin_offline(created.id, "restoring", allow_failed=True)
    assert not ticket.was_running
    service.mark_swap(created.id)
    service.restore_swap(created.id, io.BytesIO(b"restore-tar"), None)
    service.time.set_halt(created.id, int(time.time()) + HALT_LEAD_SECONDS)
    fake.calls.clear()

    assert service.finish_swap(created.id, was_running=False) is None

    assert not any(call.startswith("start:") for call in fake.calls)
    row = store.get_world(created.id)
    assert row is not None
    assert (row.op_state, row.last_error, row.desired_state) == ("ready", None, "stopped")
    data, _changed = service.time.render(created.id)
    assert _halt_lines(data) == []


async def test_finish_swap_reports_launch_failure_without_raising(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    ticket = await _swap_ready(service, fake)
    service.mark_swap(ticket.world_id)
    service.restore_swap(ticket.world_id, io.BytesIO(b"restore-tar"), None)
    fake.start_errors = [ProvisionerError("Docker hat den Start der Welt abgelehnt: kaputt")]

    error = service.finish_swap(ticket.world_id, was_running=True)

    assert isinstance(error, ProvisionerError)
    row = store.get_world(ticket.world_id)
    assert row is not None
    assert row.op_state == "failed"


async def test_restore_swap_runs_without_lock(service: WorldService, fake: FakeProvisioner, store: WorldStore) -> None:
    """Pitfall 3: Während der Docker-Schritte des Tauschs läuft eine Pause ohne Warten durch."""
    ticket = await _swap_ready(service, fake)
    world_id = ticket.world_id
    inside = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    original = fake.put_world_archive

    def blocking(target: str, archive: BinaryIO) -> None:
        inside.set()
        release.wait(5)
        original(target, archive)

    fake.put_world_archive = blocking  # type: ignore[method-assign]

    def job() -> None:
        try:
            service.mark_swap(world_id)
            service.restore_swap(world_id, io.BytesIO(b"restore-tar"), None)
        except BaseException as exc:
            errors.append(exc)
            inside.set()

    worker = threading.Thread(target=job)
    worker.start()
    try:
        assert inside.wait(5)
        begin = time.monotonic()
        result = service.apply_pause_sync(_pause_now, OUTBOX_PAUSE_START)
        elapsed = time.monotonic() - begin
    finally:
        release.set()
        worker.join(5)

    assert errors == []
    assert elapsed < 1.0
    assert [(world.world_id, world.restarted) for world in result.worlds] == [(world_id, False)]
    row = store.get_world(world_id)
    assert row is not None
    assert row.op_state == "restoring_swap"


async def test_mark_restore_interrupted_is_repeatable_failed_without_halt(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    ticket = await _swap_ready(service, fake)
    service.time.set_halt(ticket.world_id, int(time.time()) + HALT_LEAD_SECONDS)
    service.mark_swap(ticket.world_id)

    service.mark_restore_interrupted(ticket.world_id)

    row = store.get_world(ticket.world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", service_module.RESTORE_INTERRUPTED)
    assert not service_module.delete_only(row)
    data, _changed = service.time.render(ticket.world_id)
    assert _halt_lines(data) == []


async def test_abort_offline_restores_failed_world_without_halt(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Abbruch vor der Zerstörung: Eine kaputte Welt bleibt kaputt, kein Docker-Stopp, kein Halt."""
    world_id = await _running_world(service, fake, "Welt")
    store.update_world(world_id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
    ticket = service.begin_offline(world_id, "restoring", allow_failed=True)
    service.time.set_halt(world_id, int(time.time()) + HALT_LEAD_SECONDS)
    fake.calls.clear()

    service.abort_offline(ticket)

    row = store.get_world(world_id)
    assert row is not None
    assert (row.op_state, row.last_error) == ("failed", RECONCILE_DATA_MISSING)
    assert not any(call.startswith(("stop:", "start:", "remove:")) for call in fake.calls)
    data, _changed = service.time.render(world_id)
    assert _halt_lines(data) == []


# Aufräumen beim Deaktivieren (06-08, D-17 Option A)


async def _three_worlds(service: WorldService) -> tuple[str, str, str]:
    """Zwei laufende Welten und eine gestoppte."""
    first = await service.create_world("Eins")
    second = await service.create_world("Zwei")
    third = await service.create_world("Drei")
    await service.stop_world(third.id)
    return first.id, second.id, third.id


async def test_teardown_all_removes_every_container_and_keeps_volumes(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    first, second, third = await _three_worlds(service)
    desired_before = {row.id: row.desired_state for row in store.list_worlds()}
    fake.stopped.clear()

    assert await service.teardown() == 0

    assert fake.containers == {}
    assert sorted(fake.removed[-3:]) == sorted([(first, True), (second, True), (third, True)])
    assert all(keep for _world, keep in fake.removed[-3:])
    # Nur laufende Welten werden gestoppt, mit kurzem Timeout (P-07).
    assert sorted(fake.stopped) == sorted([first, second])
    assert fake.stop_timeouts[-2:] == [service_module.TEARDOWN_STOP_TIMEOUT] * 2
    # Soll-Zustand und Zeilen bleiben unverändert (Boot-Abgleich baut daraus neu).
    assert {row.id: row.desired_state for row in store.list_worlds()} == desired_before
    assert desired_before == {first: "running", second: "running", third: "stopped"}


async def test_teardown_error_of_one_world_does_not_stop_the_others(
    service: WorldService, fake: FakeProvisioner, caplog: pytest.LogCaptureFixture
) -> None:
    """Fehler einer Welt stoppt die anderen nicht; gezählt, nie nach außen geworfen."""
    first, second, third = await _three_worlds(service)
    fake.stop_errors[first] = ProvisionerError("Docker hat den Stopp abgelehnt: geheim-intern")

    errors = await service.teardown()

    assert errors == 1
    assert second not in fake.containers
    assert third not in fake.containers
    # Entfernen wird auch nach gescheitertem Stopp versucht (force beendet den Prozess).
    assert (first, True) in fake.removed
    assert "geheim-intern" not in caplog.text
    assert "ProvisionerError" in caplog.text


async def test_teardown_list_failure_returns_error_count(service: WorldService, fake: FakeProvisioner) -> None:
    await service.create_world("Welt")
    fake.list_error = DockerUnavailableError("Proxy weg")
    assert await service.teardown() == 1
    assert fake.removed == []


async def test_teardown_runs_worlds_in_parallel(service: WorldService, fake: FakeProvisioner) -> None:
    for name in ("Eins", "Zwei", "Drei", "Vier"):
        await service.create_world(name)
    fake.stop_delay = 0.4

    began = time.monotonic()
    assert await service.teardown() == 0
    elapsed = time.monotonic() - began

    assert fake.containers == {}
    # Seriell wären es mindestens 1,6 s.
    assert elapsed < 1.2


async def test_teardown_deadline_counts_hanging_worlds(
    service: WorldService, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch
) -> None:
    await service.create_world("Eins")
    await service.create_world("Zwei")
    monkeypatch.setattr(service_module, "TEARDOWN_DEADLINE", 0.1)
    fake.stop_delay = 0.5

    began = time.monotonic()
    errors = await service.teardown()

    assert errors == 2
    assert time.monotonic() - began < 0.45


async def test_teardown_proceeds_without_lock(
    service: WorldService, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hängt eine Elternaktion, räumt teardown_all nach kurzer Wartezeit trotzdem auf."""
    await service.create_world("Welt")
    monkeypatch.setattr(service_module, "TEARDOWN_LOCK_WAIT", 0.05)
    assert service_module._LOCK.acquire(blocking=False)
    try:
        assert service.teardown_all() == 0
    finally:
        service_module._LOCK.release()
    assert fake.containers == {}


async def test_boot_reconcile_rebuilds_after_teardown(
    service: WorldService, fake: FakeProvisioner, store: WorldStore
) -> None:
    """Boot-Abgleich baut nach teardown neu: Container fehlt, Volume da, Soll running -> RECREATE."""
    first, second, third = await _three_worlds(service)
    assert await service.teardown() == 0
    fake.created.clear()

    assert await service.boot_reconcile()

    rebuilt = {world_id for world_id, _port, reuse in fake.created if reuse}
    assert rebuilt == {first, second}
    assert fake.containers[first][1] == "running"
    assert fake.containers[second][1] == "running"
    # Gestoppt gewünschte Welt bleibt ohne Container, bis die Eltern sie starten.
    assert third not in fake.containers
    for world_id in (first, second, third):
        row = store.get_world(world_id)
        assert row is not None
        assert row.op_state == "ready"
