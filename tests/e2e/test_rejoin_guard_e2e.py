"""Live-Nachweis O-12: Die Wiederbeitritts-Sperre fängt den Rejoin-Absturz von Luanti 5.17.0 ab.

Ohne Sperre stürzt eine Welt ab, wenn derselbe Name binnen etwa 0,2 s nach dem
Verlassen wieder beitritt (04-RESEARCH.md Pitfall 1, MTG und VoxeLibre). Mit
Sperre lehnt gameworld_access den zweiten Join im Prejoin mit einem Wartetext
ab, der Container läuft weiter, StartedAt bleibt gleich. Seriell, höchstens
eine VoxeLibre-Welt gleichzeitig.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import anyio
import docker
import httpx
import pytest

from tests.e2e.luanti_probe import join, session
from tests.e2e.time_helpers import (
    HOST,
    MTG_READY,
    VOXELIBRE_READY,
    container_status,
    create_running_world,
    delete_world,
    docker_api,
    started_at,
    write_access,
)

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

# Festes Testpasswort für Wegwerfwelten, kein Geheimnis.
MIA_PASSWORD = "Sonne-Baum-42"  # noqa: S105
WAIT_TEXT = "einen Moment warten"
REJOIN_GAP = 0.2
COOLDOWN_PAUSE = 2.5
ROUNDS = 5
# Die erste Sitzung einer frischen Welt darf länger brauchen (Definitionen, Medien).
FIRST_TIMEOUT = 30.0


@pytest.fixture
def api() -> Iterator[docker.DockerClient]:
    client = docker_api()
    try:
        yield client
    finally:
        client.close()


def _rejoin_round(port: int) -> None:
    """Sitzung 2 s halten, schließen, nach 0,2 s erneut beitreten: Wartetext statt Absturz."""
    held = session(HOST, port, "Mia", MIA_PASSWORD, hold=2, timeout=FIRST_TIMEOUT)
    assert held["result"] == "held", held
    time.sleep(REJOIN_GAP)
    second = join(HOST, port, "Mia", MIA_PASSWORD)
    assert second["result"] == "denied", second
    assert second["code"] == "CUSTOM_STRING", second
    assert WAIT_TEXT in str(second["reason"]), second


def _assert_alive(api: docker.DockerClient, world_id: str, started: str) -> None:
    assert container_status(api, world_id) == "running"
    assert started_at(api, world_id) == started, "Container wurde neu gestartet (Absturz?)"


async def test_mtg_rejoin_guard_prevents_crash(
    client: httpx.AsyncClient, app_env: Path, api: docker.DockerClient
) -> None:
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    write_access(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
    started = started_at(api, world_id)

    first = session(HOST, port, "Mia", MIA_PASSWORD, hold=3, timeout=FIRST_TIMEOUT)
    assert first["result"] == "held", first

    for _ in range(ROUNDS):
        await anyio.sleep(COOLDOWN_PAUSE)
        _rejoin_round(port)
        _assert_alive(api, world_id, started)

    await anyio.sleep(5)
    _assert_alive(api, world_id, started)

    # Gegenprobe: Nach 2,5 s Pause klappt der Beitritt wieder.
    await anyio.sleep(COOLDOWN_PAUSE)
    again = session(HOST, port, "Mia", MIA_PASSWORD, hold=3, timeout=FIRST_TIMEOUT)
    assert again["result"] == "held", again
    _assert_alive(api, world_id, started)


async def test_voxelibre_rejoin_guard_prevents_crash(
    client: httpx.AsyncClient, app_env: Path, api: docker.DockerClient
) -> None:
    world_id, port = await create_running_world(client, "voxelibre_sanft", VOXELIBRE_READY)
    try:
        write_access(app_env, world_id, 1, {"Mia": MIA_PASSWORD})
        started = started_at(api, world_id)
        _rejoin_round(port)
        await anyio.sleep(1)
        _assert_alive(api, world_id, started)
    finally:
        await delete_world(client, world_id)
