"""Lebenszyklus ohne Docker: Starten, Stoppen, Löschen und die Port-Kollisions-Saga."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import (
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
from gameworld.worlds import service as service_module
from gameworld.worlds.service import (
    LIST_CACHE_SECONDS,
    RECONCILE_DATA_MISSING,
    DeleteOnlyError,
    WorldService,
    WorldView,
)
from gameworld.worlds.store import WorldStore
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

    def start_world(self, world_id: str) -> None:
        port, _ = self._known(world_id)
        self.started.append(world_id)
        self.calls.append(f"start:{world_id}")
        if self.start_errors:
            raise self.start_errors.pop(0)
        self.containers[world_id] = (port, "running")

    def stop(self, world_id: str) -> None:
        port, _ = self._known(world_id)
        self.stopped.append(world_id)
        self.calls.append(f"stop:{world_id}")
        self.containers[world_id] = (port, "exited")

    def remove_world(self, world_id: str, *, keep_volume: bool) -> None:
        self.removed.append((world_id, keep_volume))
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

    assert fake.calls == [f"stop:{created.id}", f"start:{created.id}"]
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
