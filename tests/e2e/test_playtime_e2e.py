"""Ende-zu-Ende: Tageslimit und Zeitfenster pro Kind aus der Datenbank bis in den Spielserver.

Anders als test_time_mod_e2e schreibt hier NICHT der Test die Regeldatei, sondern
die ExApp: Der Verwalter setzt Regeln per POST /api/playtime, die Einladung und der
15-s-Takt (hier vom Test per service.tick_time getrieben, ASGI ohne Lifespan) halten
die Regeldatei aktuell, der Mod aus 04-01 setzt durch.

Belegt Success Criterion 1 (per API), 5 und 6 (Regeln aus der Datenbank, über
Neustart und über mehrere Welten) samt Positivkontrolle. Seriell, MTG kreativ.
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
from gameworld.provisioner.time_mod import RULES_FILE, TEXT_FENSTER, TEXT_LIMIT
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
    """Läuft ein Zeittest nahe 00:00, bis 00:01 warten: Ein Fenster darf nie über 24:00 laufen."""
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
    """Deckel eines Spielers aus der Regeldatei der Welt (docker get_archive)."""
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
    """Hält eine Sitzung und treibt währenddessen den Zeittakt (ASGI ohne Lifespan)."""
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

    # (1) Tageslimit 2 min: Vorwarnung, Trennen; zweites Konto ohne Regeln hält (Positivkontrolle).
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
    assert TEXT_LIMIT in str(kind_result["reason"]), kind_result
    assert ctrl_result["result"] == "held", ctrl_result
    assert 105 <= _usage(app_env, "gw-kind") <= 135
    assert _usage(app_env, "gw-kind2") == 0

    # Rejoin nach der 2-s-Sperre scheitert mit demselben Text.
    await anyio.sleep(COOLDOWN_PAUSE)
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert TEXT_LIMIT in str(denied["reason"]), denied
    await _no_error_worlds(client)

    # (2) Neustart: Regeln kommen aus der Datenbank, der Join scheitert weiter (Success Criterion 6).
    restarted = await client.post(f"/api/worlds/{world_a}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    world = await wait_for_status(client, world_a, "running", MTG_READY)
    port = int(str(world["port"]))
    assert world["time_restart_needed"] is False
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert TEXT_LIMIT in str(denied["reason"]), denied
    await _no_error_worlds(client)

    # (3) Zwei Welten, ein Kontingent: Deckel in Welt B sinkt mit dem Verbrauch in Welt A (O-03).
    await _clear_rules(client, "gw-kind")
    await _set_rules(client, "gw-kind", _every_day(limit=3))
    world_b, _ = await create_running_world(client, "mtg_kreativ", MTG_READY)
    await _invite(client, world_b, "gw-kind")
    # Direkt nach der Einladung, noch vor jedem Takt: die Regeldatei der Welt B trägt das Kind.
    assert _rules_cap(world_b, kind_name) is not None

    port_a = await _port(client, world_a)
    held = await _hold_with_ticks(service, port_a, kind_name, kind_pw, 70.0)
    assert held["result"] == "held", held

    usage = _usage(app_env, "gw-kind")
    cap_b = _rules_cap(world_b, kind_name)
    assert cap_b is not None
    assert abs(cap_b - (180 - usage)) <= 10, (cap_b, usage)
    await _no_error_worlds(client)

    # (4) Zeitfenster: am Fensterende getrennt mit "Gerade ist keine Spielzeit.".
    await _midnight_guard()
    await _clear_rules(client, "gw-kind")
    now_minute = datetime.now(BERLIN).hour * 60 + datetime.now(BERLIN).minute
    await _set_rules(client, "gw-kind", _every_day(ws=0, we=now_minute + 3))
    port_a = await _port(client, world_a)
    window = await _hold_with_ticks(service, port_a, kind_name, kind_pw, 240.0)
    assert window["result"] == "kicked", window
    assert float(str(window["after_s"])) < 200, window
    assert TEXT_FENSTER in str(window["reason"]), window
    await _no_error_worlds(client)

    # (5) Opt-in: ohne Regeln bleibt das Kind verbunden.
    await anyio.sleep(COOLDOWN_PAUSE)
    await _clear_rules(client, "gw-kind")
    port_a = await _port(client, world_a)
    assert join(HOST, port_a, kind_name, kind_pw)["result"] == "auth_accept"
    free = session(HOST, port_a, kind_name, kind_pw, hold=20.0, timeout=JOIN_TIMEOUT)
    assert free["result"] == "held", free
    await _no_error_worlds(client)

    # Aufräumen: beide Welten löschen (das Cleanup-Fixture entfernt die Volumes sicherheitshalber).
    for world_id in (world_a, world_b):
        deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
        assert deleted.status_code == 204, deleted.text
