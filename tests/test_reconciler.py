"""Reconciler ohne Docker: Entscheidungstabelle, Abgleich im Dienst, Schleife und Lifespan (PLATT-02)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI

from gameworld import main as main_module
from gameworld.config import load_settings
from gameworld.main import lifespan
from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    DockerUnavailableError,
    ProvisionerError,
    WorldNotFoundError,
)
from gameworld.worlds import service as service_module
from gameworld.worlds.reconciler import ReconcileAction, decide_boot, decide_periodic, reconcile_forever
from gameworld.worlds.service import (
    RECONCILE_DATA_MISSING,
    RECONCILE_INTERRUPTED,
    RECONCILE_OOM,
    WorldService,
)
from gameworld.worlds.store import WorldRow, WorldStore
from tests.test_service_lifecycle import FakeProvisioner

A = ReconcileAction


def _row(desired: str = "running", op_state: str = "ready", world_id: str = "w1") -> WorldRow:
    return WorldRow(
        id=world_id,
        name="Welt",
        port=30015,
        container_name=f"gameworld-x-{world_id}",
        volume_name=f"gameworld-x-{world_id}",
        world_key="geheim",
        engine_version="5.17.0",
        desired_state=desired,
        op_state=op_state,
        last_error=None,
        created_at="2026-10-19T10:00:00+00:00",
    )


def _container(status: str, *, exit_code: int = 0, oom: bool = False) -> ContainerInfo:
    return ContainerInfo("cid", "gameworld-x-w1", "w1", status, 30015, exit_code=exit_code, oom_killed=oom)


# Entscheidungstabelle (RESEARCH Pattern 4)

BOOT_TABLE = [
    pytest.param(_row(), _container("exited", exit_code=0), True, A.START, id="running-exited-0"),
    pytest.param(_row(), _container("exited", exit_code=137), True, A.START, id="running-exited-137"),
    pytest.param(_row(), _container("exited", exit_code=1), True, A.START, id="running-exited-1"),
    pytest.param(_row(), _container("exited", exit_code=137, oom=True), True, A.MARK_OOM, id="running-oom"),
    pytest.param(_row(), None, True, A.RECREATE, id="running-missing-volume"),
    pytest.param(_row(), None, False, A.MARK_DATA_MISSING, id="running-missing-no-volume"),
    pytest.param(_row("stopped"), _container("running"), True, A.ADOPT_RUNNING, id="stopped-running"),
    pytest.param(_row(op_state="creating"), _container("created"), True, A.MARK_INTERRUPTED, id="creating"),
    pytest.param(_row(op_state="creating"), None, False, A.MARK_INTERRUPTED, id="creating-missing"),
    pytest.param(_row("deleted"), _container("exited"), True, A.RETRY_DELETE, id="deleted"),
    pytest.param(_row("deleted"), None, False, A.RETRY_DELETE, id="deleted-missing"),
    pytest.param(_row(), _container("running"), True, A.NONE, id="running-running"),
    pytest.param(_row("stopped"), _container("exited"), True, A.NONE, id="stopped-exited"),
    pytest.param(_row("stopped"), _container("exited", exit_code=137), True, A.NONE, id="stopped-killed"),
    pytest.param(_row("stopped"), None, True, A.NONE, id="stopped-missing"),
    pytest.param(_row(), _container("created"), True, A.START, id="running-created"),
    pytest.param(_row(op_state="failed"), _container("exited", exit_code=1), True, A.NONE, id="failed-exited"),
    pytest.param(_row(op_state="failed"), None, True, A.NONE, id="failed-missing"),
]


@pytest.mark.parametrize(("row", "container", "volume", "expected"), BOOT_TABLE)
def test_decide_boot(row: WorldRow, container: ContainerInfo | None, volume: bool, expected: ReconcileAction) -> None:
    assert decide_boot(row, container, volume) is expected


@pytest.mark.parametrize(("row", "container", "volume", "_boot"), BOOT_TABLE)
def test_decide_periodic_never_starts_or_recreates(
    row: WorldRow, container: ContainerInfo | None, volume: bool, _boot: ReconcileAction
) -> None:
    del volume
    action = decide_periodic(row, container)
    assert action in {A.NONE, A.ADOPT_RUNNING}
    assert action not in {A.START, A.RECREATE}


def test_decide_periodic_adopts_manually_started_world() -> None:
    assert decide_periodic(_row("stopped"), _container("running")) is A.ADOPT_RUNNING


@pytest.mark.parametrize(
    "container",
    [_container("exited", exit_code=137), _container("exited", exit_code=137, oom=True), None, _container("created")],
)
def test_decide_periodic_leaves_dead_worlds_alone(container: ContainerInfo | None) -> None:
    assert decide_periodic(_row(), container) is A.NONE


# Abgleich im Dienst


@dataclass
class ReconcileFake(FakeProvisioner):
    """FakeProvisioner mit Volumes und Startfehlern pro Welt."""

    volumes: set[str] = field(default_factory=set)
    volume_checks: list[str] = field(default_factory=list)
    failing_starts: dict[str, ProvisionerError] = field(default_factory=dict)
    docker_calls: int = 0

    def list_managed(self) -> dict[str, ContainerInfo]:
        self.docker_calls += 1
        return super().list_managed()

    def volume_exists(self, world_id: str) -> bool:
        self.docker_calls += 1
        self.volume_checks.append(world_id)
        return world_id in self.volumes

    def start_world(self, world_id: str) -> None:
        if world_id in self.failing_starts:
            self._known(world_id)
            raise self.failing_starts[world_id]
        super().start_world(world_id)


@pytest.fixture
def fake() -> ReconcileFake:
    return ReconcileFake()


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: ReconcileFake) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, fake), load_settings())


def _insert(store: WorldStore, world_id: str, *, desired: str = "running", op_state: str = "ready", port: int) -> None:
    row = _row(desired, op_state, world_id)
    row.port = port
    store.insert_world(row)


def _get(store: WorldStore, world_id: str) -> WorldRow:
    row = store.get_world(world_id)
    assert row is not None
    return row


async def test_boot_starts_exited_and_keeps_stopped(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", port=30015)
    _insert(store, "b", desired="stopped", port=30016)
    fake.containers = {"a": (30015, "exited"), "b": (30016, "exited")}
    fake.extra = {"a": {"exit_code": 0}}

    assert await service.boot_reconcile() is True

    assert fake.started == ["a"]
    assert fake.containers["b"] == (30016, "exited")
    assert fake.created == []
    assert _get(store, "a").op_state == "ready"
    # Volume nur bei fehlendem Container abfragen.
    assert fake.volume_checks == []


async def test_boot_recreates_missing_container_from_volume(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", port=30015)
    fake.volumes = {"a"}

    assert await service.boot_reconcile() is True

    assert fake.volume_checks == ["a"]
    assert fake.created == [("a", 30015, True)]
    assert fake.containers["a"] == (30015, "running")


async def test_boot_marks_missing_data(service: WorldService, fake: ReconcileFake, store: WorldStore) -> None:
    _insert(store, "a", port=30015)

    assert await service.boot_reconcile() is True

    row = _get(store, "a")
    assert (row.op_state, row.last_error) == ("failed", RECONCILE_DATA_MISSING)
    assert fake.created == []
    assert fake.started == []


async def test_boot_never_starts_oom_world(service: WorldService, fake: ReconcileFake, store: WorldStore) -> None:
    _insert(store, "a", port=30015)
    fake.containers = {"a": (30015, "exited")}
    fake.extra = {"a": {"exit_code": 137, "oom_killed": True}}

    assert await service.boot_reconcile() is True

    assert fake.started == []
    row = _get(store, "a")
    assert row.last_error == RECONCILE_OOM
    assert row.desired_state == "running"
    assert row.op_state == "ready"


async def test_boot_marks_interrupted_creation(service: WorldService, fake: ReconcileFake, store: WorldStore) -> None:
    _insert(store, "a", op_state="creating", port=30015)
    fake.containers = {"a": (30015, "created")}

    assert await service.boot_reconcile() is True

    row = _get(store, "a")
    assert (row.op_state, row.last_error) == ("failed", RECONCILE_INTERRUPTED)
    assert fake.started == []


async def test_boot_retries_delete(service: WorldService, fake: ReconcileFake, store: WorldStore) -> None:
    _insert(store, "a", desired="deleted", port=30015)
    fake.containers = {"a": (30015, "exited")}

    assert await service.boot_reconcile() is True

    assert fake.removed == [("a", False)]
    assert store.get_world("a") is None


async def test_boot_adopts_manually_started_world(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", desired="stopped", port=30015)
    fake.containers = {"a": (30015, "running")}

    assert await service.boot_reconcile() is True

    assert _get(store, "a").desired_state == "running"
    assert fake.stopped == []


async def test_boot_error_of_one_world_is_isolated(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", port=30015)
    _insert(store, "b", port=30016)
    fake.containers = {"a": (30015, "exited"), "b": (30016, "exited")}
    fake.failing_starts = {"a": ProvisionerError("Docker hat den Start der Welt abgelehnt: kaputt")}

    assert await service.boot_reconcile() is True

    row_a = _get(store, "a")
    assert row_a.op_state == "failed"
    assert row_a.last_error is not None
    assert "kaputt" in row_a.last_error
    assert fake.containers["b"] == (30016, "running")


async def test_boot_aborts_when_docker_disappears(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    """Ein unerreichbarer Proxy markiert keine Welt als kaputt; der nächste Versuch gleicht alles ab."""
    _insert(store, "a", port=30015)
    fake.containers = {"a": (30015, "exited")}
    fake.failing_starts = {"a": DockerUnavailableError("Proxy weg")}

    with pytest.raises(DockerUnavailableError):
        await service.boot_reconcile()

    assert _get(store, "a").op_state == "ready"


async def test_boot_leaves_orphans_alone(
    service: WorldService, fake: ReconcileFake, store: WorldStore, caplog: pytest.LogCaptureFixture
) -> None:
    _insert(store, "a", port=30015)
    fake.containers = {"a": (30015, "running"), "waise1": (30016, "exited"), "waise2": (30017, "running")}

    with caplog.at_level(logging.WARNING, logger=service_module.LOG.name):
        assert await service.boot_reconcile() is True

    assert fake.containers["waise1"] == (30016, "exited")
    assert fake.containers["waise2"] == (30017, "running")
    assert fake.started == []
    assert fake.stopped == []
    assert fake.removed == []
    assert fake.created == []
    assert "verwaiste Welt-Container: 2" in caplog.text


async def test_boot_skips_while_parent_action_runs(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", port=30015)
    fake.containers = {"a": (30015, "exited")}
    assert service_module._LOCK.acquire(blocking=False)
    try:
        assert await service.boot_reconcile() is False
        await service.periodic_reconcile()
    finally:
        service_module._LOCK.release()
    assert fake.docker_calls == 0
    assert fake.started == []


async def test_periodic_never_restarts_but_adopts(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    _insert(store, "a", port=30015)
    _insert(store, "b", desired="stopped", port=30016)
    _insert(store, "c", port=30017)
    fake.containers = {"a": (30015, "exited"), "b": (30016, "running")}
    fake.extra = {"a": {"exit_code": 137}}
    fake.volumes = {"c"}

    await service.periodic_reconcile()

    assert fake.started == []
    assert fake.created == []
    assert fake.volume_checks == []
    assert _get(store, "b").desired_state == "running"
    assert _get(store, "a").op_state == "ready"


async def test_reconcile_invalidates_list_cache(service: WorldService, fake: ReconcileFake, store: WorldStore) -> None:
    _insert(store, "a", desired="stopped", port=30015)
    fake.containers = {"a": (30015, "exited")}
    assert [view.desired_state for view in await service.list_worlds()] == ["stopped"]
    fake.containers = {"a": (30015, "running")}

    await service.periodic_reconcile()

    assert [view.desired_state for view in await service.list_worlds()] == ["running"]


async def test_boot_skips_volume_check_for_stopped_or_deleted_rows(
    service: WorldService, fake: ReconcileFake, store: WorldStore
) -> None:
    """Volume-Abfragen nur, wo eine Neuerzeugung überhaupt in Frage kommt."""
    _insert(store, "a", desired="stopped", port=30015)
    _insert(store, "b", desired="deleted", port=30016)
    fake.remove_error = None

    assert await service.boot_reconcile() is True

    assert fake.volume_checks == []
    assert store.get_world("b") is None
    assert _get(store, "a").op_state == "ready"


async def test_recreate_without_container_raises_not_found_in_fake(fake: ReconcileFake) -> None:
    """Gegenprobe zum Fake: Ohne Container kennt start_world die Welt nicht."""
    with pytest.raises(WorldNotFoundError):
        fake.start_world("a")


# Schleife


@dataclass
class LoopService:
    boot_results: list[bool | Exception]
    periodic_errors: list[Exception] = field(default_factory=list)
    boot_calls: int = 0
    periodic_calls: int = 0

    async def boot_reconcile(self) -> bool:
        self.boot_calls += 1
        result = self.boot_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def periodic_reconcile(self) -> None:
        self.periodic_calls += 1
        if self.periodic_errors:
            raise self.periodic_errors.pop(0)


async def _wait_until(predicate: object, seconds: float = 2.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if callable(predicate) and predicate():
            return
        await asyncio.sleep(0.005)
    pytest.fail("Bedingung nicht erreicht")


async def test_loop_retries_boot_until_docker_answers() -> None:
    fake_service = LoopService(
        boot_results=[DockerUnavailableError("Proxy weg"), False, RuntimeError("unerwartet"), True],
        periodic_errors=[ProvisionerError("kurz weg")],
    )
    task = asyncio.create_task(
        reconcile_forever(
            cast(WorldService, fake_service),
            boot_retry_seconds=0.01,
            interval_seconds=0.01,
        )
    )
    await _wait_until(lambda: fake_service.periodic_calls >= 3)
    assert fake_service.boot_calls == 4
    assert not task.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# Lifespan


async def test_lifespan_does_not_block_on_unreachable_docker(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", "tcp://127.0.0.1:9")
    started: list[object] = []
    real = main_module.reconcile_forever

    async def recording(service: WorldService) -> None:
        started.append(service)
        await real(service)

    monkeypatch.setattr(main_module, "reconcile_forever", recording)
    begin = time.monotonic()
    async with lifespan(FastAPI()):
        await asyncio.sleep(0.05)
    assert time.monotonic() - begin < 2.0
    assert len(started) == 1


async def test_lifespan_starts_no_reconciler_with_invalid_config(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app_env
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "kaputt")
    started: list[object] = []

    async def recording(service: WorldService) -> None:
        started.append(service)

    monkeypatch.setattr(main_module, "reconcile_forever", recording)
    async with lifespan(FastAPI()):
        await asyncio.sleep(0.01)
    assert started == []
