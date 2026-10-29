"""Live proof D-09 against real Luanti: chat notice and disconnect before the cold backup.

The unit test proves the halt only as a Lua string. Here Mia really sits in the world
via the prober (tests/e2e/luanti_probe.session); the real WorldService
reads the status file via ``players_online`` and calls ``announce_halt``
(sets ``@halt`` and writes the rules file immediately). The time mod sends the
chat notice and disconnects from the time ``from`` on. Negative control: during the
halt a join is rejected. Positive control: after ``clear_halt`` Mia
gets back in. The expected texts are literals in the test, not imported from
time_mod (counter-check independent of the renderer). Game passwords
are never printed.
"""

from __future__ import annotations

import time
from functools import partial
from pathlib import Path

import anyio
import anyio.to_thread
import httpx
import pytest

from gameworld.api import worlds as worlds_api
from gameworld.worlds.service import HALT_LEAD_SECONDS, WorldService
from tests.conftest import FakeDirectory, appapi_headers
from tests.e2e.luanti_probe import session
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world, delete_world

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

TEXT_HALT_SOON = "Die Welt macht gleich eine kurze Pause."
TEXT_HALT = "Die Welt macht kurz Pause. Gleich geht es weiter."
JOIN_TIMEOUT = 30.0
SESSION_HOLD = HALT_LEAD_SECONDS + 15.0
ONLINE_TIMEOUT = 20.0
# The time mod checks every 5 s; a kick before ``from`` may come at most this early.
MOD_TICK_SLACK = 2.0
# After a disconnect the mod briefly blocks the rejoin (K6); only check after that.
REJOIN_COOLDOWN = 3.0
CLEAR_TIMEOUT = 15.0
SHORT_HOLD = 3.0


@pytest.fixture
def mia(fake_directory: FakeDirectory) -> str:
    fake_directory.users["gw-mia"] = ("Mia", True)
    return "gw-mia"


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


def _events(result: dict[str, object], kind: str) -> list[dict[str, object]]:
    events = result.get("events")
    assert isinstance(events, list)
    return [dict(event) for event in events if isinstance(event, dict) and event.get("kind") == kind]


def _public(result: dict[str, object]) -> dict[str, object]:
    """Result without the event list for error messages (passwords never appear in it)."""
    return {key: value for key, value in result.items() if key != "events"}


async def _wait_online(service: WorldService, world_id: str, expected: int) -> None:
    deadline = time.monotonic() + ONLINE_TIMEOUT
    seen = -1
    while time.monotonic() < deadline:
        seen = await anyio.to_thread.run_sync(service.players_online, world_id)
        if seen == expected:
            return
        await anyio.sleep(0.5)
    pytest.fail(f"players_online meldet {seen}, erwartet {expected}")


def _clear_halt(service: WorldService, world_id: str) -> None:
    with service.mutation():
        service.time.clear_halt(world_id)
        assert service.push_time(world_id), "Regeldatei ohne Halt nicht geschrieben"


async def test_halt_notice_and_kick(client: httpx.AsyncClient, app_env: Path, mia: str) -> None:
    del app_env
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    service = worlds_api.get_service()
    name, password = await _invite(client, world_id, mia)
    assert name == "Mia"

    # (1) Mia is connected, the real read path of the status file counts her, then the halt.
    result: dict[str, object] = {}
    ended_at: list[float] = []
    halt_at: list[int] = []

    async def play() -> None:
        outcome = await anyio.to_thread.run_sync(
            partial(session, HOST, port, name, password, SESSION_HOLD, JOIN_TIMEOUT)
        )
        ended_at.append(time.time())
        result.update(outcome)

    async with anyio.create_task_group() as group:
        group.start_soon(play)
        await _wait_online(service, world_id, 1)
        ab = await anyio.to_thread.run_sync(service.announce_halt, world_id, int(time.time()))
        assert ab is not None, "announce_halt sah keinen Spieler"
        halt_at.append(ab)

    assert result["result"] == "kicked", _public(result)
    assert result["reason"] == TEXT_HALT, _public(result)
    chats = [event for event in _events(result, "chat") if event.get("text") == TEXT_HALT_SOON]
    kicks = _events(result, "kick")
    assert chats, f"kein Chat-Hinweis: {_events(result, 'chat')}"
    assert len(kicks) == 1, kicks
    assert kicks[0]["text"] == TEXT_HALT
    assert float(str(chats[0]["t"])) < float(str(kicks[0]["t"])), "Hinweis kam nach dem Trennen"
    assert ended_at[0] >= halt_at[0] - MOD_TICK_SLACK, (ended_at[0], halt_at[0])

    # (2) Negative control: during the halt a join is rejected.
    await anyio.sleep(REJOIN_COOLDOWN)
    denied = await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, SHORT_HOLD, JOIN_TIMEOUT))
    assert denied["result"] == "denied", _public(denied)
    assert TEXT_HALT in str(denied["reason"]), _public(denied)

    # (3) Positive control: after clear_halt plus push_time Mia gets back in (the mod reloads on its tick).
    await anyio.to_thread.run_sync(_clear_halt, service, world_id)
    deadline = time.monotonic() + CLEAR_TIMEOUT
    accepted: dict[str, object] = {}
    while time.monotonic() < deadline:
        accepted = await anyio.to_thread.run_sync(
            partial(session, HOST, port, name, password, SHORT_HOLD, JOIN_TIMEOUT)
        )
        if accepted["result"] != "denied" or TEXT_HALT not in str(accepted.get("reason")):
            break
        await anyio.sleep(1.0)
    assert accepted["result"] == "held", _public(accepted)

    await delete_world(client, world_id)
