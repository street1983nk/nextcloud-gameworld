"""Live-Nachweis PLATT-02 gegen den echten Proxy: Reboot- und Update-Simulation.

Ein echter Docker-Neustart würde die übrigen Stacks der Maschine unterbrechen
(RESEARCH Open Question 3). Der Reboot wird deshalb simuliert: Welt-Container
von außen stoppen (wie beim Daemon-Shutdown) und einen NEUEN WorldService aus
derselben Datenbank bauen, so wie eine neu gestartete ExApp. Kreativ-Preset
wegen des RAM-Bedarfs.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from pathlib import Path

import docker
import pytest
from docker.models.containers import Container

from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService, WorldView
from gameworld.worlds.store import WorldStore
from tests.conftest import docker_url

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

PRESET = "mtg_kreativ"
READY_TIMEOUT = 30.0


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        yield client
    finally:
        client.close()


def fresh_service() -> WorldService:
    """Wie eine neu gestartete ExApp: neuer Store, neuer Provisioner, gleiche Datenbank."""
    settings = load_settings()
    store = WorldStore(settings.storage_dir / "gameworld.sqlite3")
    store.migrate()
    return WorldService(store, DockerProvisioner(settings.docker_url, store.instance_id()), settings)


def _container(api: docker.DockerClient, world_id: str) -> Container:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1, f"erwartet genau einen Container für {world_id}, gefunden {len(matches)}"
    return matches[0]


def _state(container: Container) -> str:
    container.reload()
    return str(container.status)


def _volume_name(container: Container) -> str:
    container.reload()
    names = [str(mount["Name"]) for mount in container.attrs["Mounts"] if mount.get("Type") == "volume"]
    assert len(names) == 1, names
    return names[0]


async def _view(service: WorldService, world_id: str) -> WorldView:
    views = {view.id: view for view in await service.list_worlds()}
    return views[world_id]


async def _wait_status(service: WorldService, world_id: str, expected: str, within: float = READY_TIMEOUT) -> WorldView:
    deadline = time.monotonic() + within
    seen: list[str] = []
    while time.monotonic() < deadline:
        view = await _view(service, world_id)
        if not seen or seen[-1] != view.status:
            seen.append(view.status)
        if view.status == expected:
            return view
        await asyncio.sleep(0.5)
    pytest.fail(f"Welt {world_id} ist nach {within} s nicht {expected}, gesehen: {seen}")


async def _boot(service: WorldService) -> None:
    """boot_reconcile wiederholen, bis es gelingt (wie reconcile_forever)."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if await service.boot_reconcile():
            return
        await asyncio.sleep(0.2)
    pytest.fail("boot_reconcile kam nicht zum Zug")


async def _two_worlds(service: WorldService) -> tuple[str, str]:
    """Welt A läuft, Welt B ist per Elternklick gestoppt."""
    world_a = await service.create_world("Welt A", PRESET)
    world_b = await service.create_world("Welt B", PRESET)
    await service.stop_world(world_b.id)
    await _wait_status(service, world_a.id, "running")
    return world_a.id, world_b.id


async def test_boot_restarts_desired_running_worlds_after_reboot(api: docker.DockerClient, app_env: Path) -> None:
    del app_env
    first = fresh_service()
    world_a, world_b = await _two_worlds(first)
    id_a = str(_container(api, world_a).id)
    id_b = str(_container(api, world_b).id)

    # Daemon-Shutdown simulieren: A wird von außen beendet, B war schon gestoppt.
    _container(api, world_a).stop(timeout=30)
    assert _state(_container(api, world_a)) == "exited"

    rebooted = fresh_service()
    begin = time.monotonic()
    await _boot(rebooted)
    await _wait_status(rebooted, world_a, "running")
    assert time.monotonic() - begin < READY_TIMEOUT

    container_a = _container(api, world_a)
    assert str(container_a.id) == id_a, "re-adoptiert über Labels, nicht neu erzeugt"
    assert _state(container_a) == "running"
    container_b = _container(api, world_b)
    assert str(container_b.id) == id_b
    assert _state(container_b) == "exited"
    assert (await _view(rebooted, world_b)).status == "stopped"


async def test_update_keeps_worlds_visible(api: docker.DockerClient, app_env: Path) -> None:
    del app_env
    first = fresh_service()
    world_a, world_b = await _two_worlds(first)
    before = {view.id: (view.preset, view.status) for view in await first.list_worlds()}
    containers = {world_id: str(_container(api, world_id).id) for world_id in (world_a, world_b)}

    # Neue ExApp-Version: neuer Prozess, gleiche Datenbank im persistenten Volume.
    updated = fresh_service()
    await _boot(updated)
    await _wait_status(updated, world_a, "running")
    after = {view.id: (view.preset, view.status) for view in await updated.list_worlds()}

    assert after == before
    assert after[world_a] == (PRESET, "running")
    assert after[world_b] == (PRESET, "stopped")
    assert {world_id: str(_container(api, world_id).id) for world_id in (world_a, world_b)} == containers


async def test_boot_recreates_missing_container_from_volume(api: docker.DockerClient, app_env: Path) -> None:
    del app_env
    first = fresh_service()
    created = await first.create_world("Welt A", PRESET)
    await _wait_status(first, created.id, "running")
    old = _container(api, created.id)
    old_id = str(old.id)
    old_preset = old.labels["gameworld.preset"]
    old_volume = _volume_name(old)

    # docker rm von außen, Volume bleibt.
    old.remove(force=True, v=False)

    rebooted = fresh_service()
    await _boot(rebooted)
    await _wait_status(rebooted, created.id, "running")

    new = _container(api, created.id)
    assert str(new.id) != old_id
    assert _state(new) == "running"
    assert new.labels["gameworld.preset"] == old_preset == PRESET
    assert _volume_name(new) == old_volume


async def test_killed_world_restarts_on_boot_but_not_periodically(api: docker.DockerClient, app_env: Path) -> None:
    del app_env
    first = fresh_service()
    created = await first.create_world("Welt A", PRESET)
    await _wait_status(first, created.id, "running")
    container = _container(api, created.id)

    container.kill()
    assert _state(container) == "exited"
    container.reload()
    assert container.attrs["State"]["ExitCode"] == 137
    assert container.attrs["State"]["OOMKilled"] is False

    # Periodisch: nie neu starten, nur Zustand zeigen.
    await first.periodic_reconcile()
    await asyncio.sleep(1.0)
    await first.periodic_reconcile()
    assert _state(container) == "exited"
    crashed = await _wait_status(first, created.id, "error", within=10.0)
    assert "unerwartet beendet" in crashed.status_text

    # Neuer Prozess (Reboot): Der Boot-Abgleich startet die Welt wieder.
    rebooted = fresh_service()
    await _boot(rebooted)
    await _wait_status(rebooted, created.id, "running")
    assert str(_container(api, created.id).id) == str(container.id)
