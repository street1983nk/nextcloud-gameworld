"""End to end: daily limit and time window per child from the database to the game server.

Unlike test_time_mod_e2e, here the test does NOT write the rules file, the ExApp does:
the manager sets rules via POST /api/playtime, the invitation and the
15 s tick (driven here by the test via service.tick_time, ASGI without lifespan) keep
the rules file current, the mod from 04-01 enforces it.

Proves success criterion 1 (via API), 5 and 6 (rules from the database, across
restart and across several worlds) including a positive control. Serial, MTG creative.
"""

from __future__ import annotations

import io
import tarfile
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

import anyio
import anyio.to_thread
import httpx
import pytest

from gameworld.api import worlds as worlds_api
from gameworld.provisioner.time_mod import RULES_FILE, TEXT_FENSTER, TEXT_LIMIT, kid_text
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import join, session
from tests.e2e.test_status_e2e import wait_for_status
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world, docker_api

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

JOIN_TIMEOUT = 30.0
COOLDOWN_PAUSE = 2.5
TICK_EVERY = 5.0
BERLIN = ZoneInfo("Europe/Berlin")


async def _midnight_guard() -> None:
    """If a time test runs near 00:00, wait until 00:01: a window must never run past 24:00."""
    now = datetime.now(BERLIN)
    if now.hour == 23 and now.minute >= 50:
        target = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        await anyio.sleep((target - now).total_seconds())


def _chats(result: dict[str, object]) -> list[str]:
    events = result.get("events")
    assert isinstance(events, list)
    return [str(event["text"]) for event in events if isinstance(event, dict) and event.get("kind") == "chat"]


def _day(weekday: int, *, allowed: bool = True, limit: int | None = None, ws: int | None = None, we: int | None = None):
    day: dict[str, object] = {"weekday": weekday, "allowed": allowed}
    if limit is not None:
        day["limit_minutes"] = limit
    if ws is not None:
        day["window_start"] = ws
    if we is not None:
        day["window_end"] = we
    return day


def _tomorrow_weekday() -> int:
    """ISO weekday of tomorrow in Berlin (for the expected child sentence)."""
    return (datetime.now(BERLIN).date() + timedelta(days=1)).isoweekday()


def _every_day(*, limit: int | None = None, ws: int | None = None, we: int | None = None) -> dict[str, object]:
    return {"normal": [_day(weekday, limit=limit, ws=ws, we=we) for weekday in range(1, 8)]}


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


async def _set_rules(client: httpx.AsyncClient, nc_user: str, body: dict[str, object]) -> dict[str, object]:
    response = await client.post(f"/api/playtime/children/{nc_user}", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    return dict(response.json())


async def _clear_rules(client: httpx.AsyncClient, nc_user: str) -> None:
    response = await client.delete(f"/api/playtime/children/{nc_user}", headers=appapi_headers())
    assert response.status_code == 200, response.text


async def _port(client: httpx.AsyncClient, world_id: str) -> int:
    worlds = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    return int(next(w for w in worlds if w["id"] == world_id)["port"])


async def _no_error_worlds(client: httpx.AsyncClient) -> None:
    worlds = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    assert all(w["status"] != "error" for w in worlds), worlds


def _usage(app_env: Path, nc_user: str) -> int:
    today = datetime.now(BERLIN).date()
    return WorldStore(app_env / "gameworld.sqlite3").usage(nc_user, today)


def _rules_cap(world_id: str, name: str) -> int | None:
    """Cap of a player from the world's rules file (docker get_archive)."""
    api = docker_api()
    try:
        [container] = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
        stream, _ = container.get_archive(RULES_FILE)
        raw = b"".join(stream)
    finally:
        api.close()
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        member = tar.next()
        assert member is not None
        handle = tar.extractfile(member)
        assert handle is not None
        content = handle.read().decode("ascii")
    for line in content.split("\n"):
        parts = line.split(" ")
        if parts[0] == name:
            return int(parts[1])
    return None


async def _tick(service: WorldService) -> None:
    await anyio.to_thread.run_sync(service.tick_time)


async def _hold_with_ticks(
    service: WorldService, port: int, name: str, password: str, hold: float
) -> dict[str, object]:
    """Holds a session and drives the time tick meanwhile (ASGI without lifespan)."""
    result: dict[str, object] = {}

    async def run() -> None:
        result.update(await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, hold, JOIN_TIMEOUT)))

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        while not result:
            await anyio.sleep(TICK_EVERY)
            await _tick(service)
    await _tick(service)
    return result


async def test_playtime_e2e(client: httpx.AsyncClient, app_env: Path) -> None:
    await _midnight_guard()
    world_a, _ = await create_running_world(client, "mtg_kreativ", MTG_READY)
    service = worlds_api.get_service()
    kind_name, kind_pw = await _invite(client, world_a, "gw-kind")
    ctrl_name, ctrl_pw = await _invite(client, world_a, "gw-kind2")

    # (1) Daily limit 2 min: advance warning, disconnect; second account without rules holds (positive control).
    await _set_rules(client, "gw-kind", _every_day(limit=2))
    port = await _port(client, world_a)
    kind_result: dict[str, object] = {}
    ctrl_result: dict[str, object] = {}

    async def run_kind() -> None:
        kind_result.update(
            await anyio.to_thread.run_sync(partial(session, HOST, port, kind_name, kind_pw, 170.0, JOIN_TIMEOUT))
        )

    async def run_ctrl() -> None:
        ctrl_result.update(
            await anyio.to_thread.run_sync(partial(session, HOST, port, ctrl_name, ctrl_pw, 150.0, JOIN_TIMEOUT))
        )

    async with anyio.create_task_group() as group:
        group.start_soon(run_kind)
        group.start_soon(run_ctrl)
        while not kind_result:
            await anyio.sleep(TICK_EVERY)
            await _tick(service)
    await _tick(service)

    assert kind_result["result"] == "kicked", kind_result
    assert 105 <= float(str(kind_result["after_s"])) <= 135, kind_result
    assert any("Noch 1 Minute." in chat for chat in _chats(kind_result)), kind_result
    # Whole day without a start time: "Morgen kannst du wieder spielen.", without a time of day.
    assert kid_text("limit", 1, _tomorrow_weekday(), 0) in str(kind_result["reason"]), kind_result
    assert TEXT_LIMIT in str(kind_result["reason"]), kind_result
    assert ctrl_result["result"] == "held", ctrl_result
    assert 105 <= _usage(app_env, "gw-kind") <= 135
    assert _usage(app_env, "gw-kind2") == 0

    # Rejoin after the 2 s block fails with the same text.
    await anyio.sleep(COOLDOWN_PAUSE)
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert TEXT_LIMIT in str(denied["reason"]), denied
    await _no_error_worlds(client)

    # (2) Restart: rules come from the database, the join keeps failing (success criterion 6).
    restarted = await client.post(f"/api/worlds/{world_a}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    world = await wait_for_status(client, world_a, "running", MTG_READY)
    port = int(str(world["port"]))
    assert world["time_restart_needed"] is False
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert TEXT_LIMIT in str(denied["reason"]), denied
    await _no_error_worlds(client)

    # (3) Two worlds, one allowance: the cap in world B drops with the usage in world A (O-03).
    # Removing and setting again keeps today's usage (WR-04, owner decision): about 2 min
    # are already used, so the new limit of 5 min leaves about 3 min.
    used_before = _usage(app_env, "gw-kind")
    await _clear_rules(client, "gw-kind")
    assert _usage(app_env, "gw-kind") == used_before
    await _set_rules(client, "gw-kind", _every_day(limit=5))
    world_b, _ = await create_running_world(client, "mtg_kreativ", MTG_READY)
    await _invite(client, world_b, "gw-kind")
    # Right after the invitation, before any tick: the rules file of world B carries the child.
    assert _rules_cap(world_b, kind_name) is not None

    port_a = await _port(client, world_a)
    held = await _hold_with_ticks(service, port_a, kind_name, kind_pw, 70.0)
    assert held["result"] == "held", held

    usage = _usage(app_env, "gw-kind")
    cap_b = _rules_cap(world_b, kind_name)
    assert cap_b is not None
    assert abs(cap_b - (300 - usage)) <= 10, (cap_b, usage)
    await _no_error_worlds(client)

    # (4) Time window: disconnected at the window end with "Jetzt ist keine Spielzeit." (plus day reference).
    await _midnight_guard()
    await _clear_rules(client, "gw-kind")
    now_minute = datetime.now(BERLIN).hour * 60 + datetime.now(BERLIN).minute
    await _set_rules(client, "gw-kind", _every_day(ws=0, we=now_minute + 3))
    port_a = await _port(client, world_a)
    window = await _hold_with_ticks(service, port_a, kind_name, kind_pw, 240.0)
    assert window["result"] == "kicked", window
    assert float(str(window["after_s"])) < 200, window
    assert TEXT_FENSTER in str(window["reason"]), window
    # Window from 0:00 means: no real start time, so without a time of day.
    assert kid_text("fenster", 1, _tomorrow_weekday(), 0) in str(window["reason"]), window
    await _no_error_worlds(client)

    # (5) Opt-in: without rules the child stays connected.
    await anyio.sleep(COOLDOWN_PAUSE)
    await _clear_rules(client, "gw-kind")
    port_a = await _port(client, world_a)
    assert join(HOST, port_a, kind_name, kind_pw)["result"] == "auth_accept"
    free = session(HOST, port_a, kind_name, kind_pw, hold=20.0, timeout=JOIN_TIMEOUT)
    assert free["result"] == "held", free
    await _no_error_worlds(client)

    # Cleanup: delete both worlds (the cleanup fixture removes the volumes for safety).
    for world_id in (world_a, world_b):
        deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
        assert deleted.status_code == 204, deleted.text
