"""Ende-zu-Ende: Pause aller Welten (ELTERN-01) von der Verwalter-API bis in den Spielserver.

Der Verwalter löst per POST /api/pause eine Pause aus; die ExApp schreibt sofort
``@pause`` in die Regeldatei, der Zeit-Mod aus 04.1-01 warnt 30 s vorher im Chat
und trennt dann mit dem Pausentext. Belegt Success Criterion 1 per API und
Prober: Vorwarnung, Trennen eines Kindes ohne und eines Kindes mit Regeln,
Beitrittssperre während der Pause, ein eingeladener Verwalter bleibt verbunden
(Positivkontrolle), die Pausenzeit erscheint nicht in time_usage, "Weiter" öffnet
ohne Neustart, "Für heute Schluss" sperrt mit dem Schluss-Text. Nebenbei belegt
er die Ereignisdatei aus 04.1-01/02 (Kopf, join, leave, deny). Seriell, eine
MTG-kreativ-Welt.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

import anyio
import anyio.to_thread
import httpx
import pytest

from gameworld.api import worlds as worlds_api
from gameworld.events.parse import parse_events
from gameworld.provisioner.access_mod import EVENTS_HEADER
from gameworld.provisioner.time_mod import TEXT_PAUSE, TEXT_PAUSE_SOON, pause_text
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import join, session
from tests.e2e.time_helpers import (
    HOST,
    MTG_READY,
    container_status,
    create_running_world,
    delete_world,
    docker_api,
    provisioner,
    started_at,
)

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

JOIN_TIMEOUT = 30.0
COOLDOWN_PAUSE = 3.0
TICK_EVERY = 5.0
BERLIN = ZoneInfo("Europe/Berlin")
NOT_INVITED = "nicht eingeladen"
# Kinder halten länger, als die Pause bis zum Trennen braucht; der Verwalter noch länger.
KID_HOLD = 90.0
ADMIN_HOLD = 75.0
# Zeit zwischen Start der Sitzungen und dem Auslösen: alle sind sicher verbunden.
JOIN_SETTLE = 6.0


async def _midnight_guard() -> None:
    """Nahe 00:00 bis 00:01 warten: "Für heute Schluss" und Tagesverbrauch hängen am lokalen Tag."""
    now = datetime.now(BERLIN)
    if now.hour == 23 and now.minute >= 50:
        target = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        await anyio.sleep((target - now).total_seconds())


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


async def _world(client: httpx.AsyncClient, world_id: str) -> dict[str, object]:
    worlds = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    return dict(next(w for w in worlds if w["id"] == world_id))


def _chats(result: dict[str, object]) -> list[str]:
    events = result.get("events")
    assert isinstance(events, list)
    return [str(event["text"]) for event in events if isinstance(event, dict) and event.get("kind") == "chat"]


def _usage(app_env: Path, nc_user: str) -> int:
    return WorldStore(app_env / "gameworld.sqlite3").usage(nc_user, datetime.now(BERLIN).date())


async def _tick(service: WorldService) -> None:
    await anyio.to_thread.run_sync(service.tick_time)


async def _post(client: httpx.AsyncClient, path: str, body: object = None) -> dict[str, object]:
    response = await client.post(f"/api/pause{path}", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    return dict(response.json())


def _events_file(app_env: Path, world_id: str) -> bytes:
    events = provisioner(app_env).read_events(world_id)
    assert events is not None, "Ereignisdatei fehlt"
    return events.content


async def test_pause_e2e(client: httpx.AsyncClient, app_env: Path) -> None:
    await _midnight_guard()
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    service = worlds_api.get_service()
    kind_name, kind_pw = await _invite(client, world_id, "gw-kind")
    rules_name, rules_pw = await _invite(client, world_id, "gw-kind2")
    admin_name, admin_pw = await _invite(client, world_id, "admin")

    # Kind mit Regeln: heute erlaubt, Limit 120 min, ganzer Tag (morgen ohne Startzeit).
    plan = {"normal": [{"weekday": day, "allowed": True, "limit_minutes": 120} for day in range(1, 8)]}
    rules = await client.post("/api/playtime/children/gw-kind2", json=plan, headers=appapi_headers())
    assert rules.status_code == 200, rules.text
    # Verwalter-Schnappschuss: GET /api/playtime als admin füllt meta time_admins (admin ist frei).
    listed = await client.get("/api/playtime", headers=appapi_headers())
    assert listed.status_code == 200, listed.text
    assert '"admin"' in (WorldStore(app_env / "gameworld.sqlite3").get_meta("time_admins") or "")
    await _tick(service)

    world = await _world(client, world_id)
    assert world["events_restart_needed"] is False, world
    assert _events_file(app_env, world_id).startswith(f"{EVENTS_HEADER} ".encode()), "Kopf fehlt"
    api = docker_api()
    try:
        started_before = started_at(api, world_id)
    finally:
        api.close()

    # (1) Pause während drei laufender Sitzungen.
    results: dict[str, dict[str, object]] = {"kind": {}, "rules": {}, "admin": {}}
    ended_at: dict[str, float] = {}
    posted: dict[str, object] = {}

    async def run(key: str, name: str, password: str, hold: float) -> None:
        outcome = await anyio.to_thread.run_sync(partial(session, HOST, port, name, password, hold, JOIN_TIMEOUT))
        ended_at[key] = time.monotonic()
        results[key].update(outcome)

    async with anyio.create_task_group() as group:
        group.start_soon(run, "kind", kind_name, kind_pw, KID_HOLD)
        group.start_soon(run, "rules", rules_name, rules_pw, KID_HOLD)
        group.start_soon(run, "admin", admin_name, admin_pw, ADMIN_HOLD)
        await anyio.sleep(JOIN_SETTLE)
        await _tick(service)
        posted_at = time.monotonic()
        posted.update(await _post(client, "", {"minutes": 15}))
        while not (results["kind"] and results["rules"] and results["admin"]):
            await anyio.sleep(TICK_EVERY)
            await _tick(service)

    assert posted["active"] is True, posted
    assert posted["art"] == "pause", posted
    [world_result] = posted["worlds"]  # pyright: ignore[reportGeneralTypeIssues]
    assert world_result == {"id": world_id, "name": "Zeitwelt", "applied": True, "restarted": False}
    for key in ("kind", "rules"):
        result = results[key]
        assert result["result"] == "kicked", result
        assert TEXT_PAUSE in str(result["reason"]), result
        assert any(TEXT_PAUSE_SOON in chat for chat in _chats(result)), result
        assert 25.0 <= ended_at[key] - posted_at <= 40.0, (key, ended_at[key] - posted_at)
    # Positivkontrolle: der eingeladene Verwalter bleibt verbunden.
    assert results["admin"]["result"] == "held", results["admin"]

    # (2) Beitrittssperre während der Pause; ein Fremder bekommt weiter den Zugangstext.
    await anyio.sleep(COOLDOWN_PAUSE)
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert TEXT_PAUSE in str(denied["reason"]), denied
    stranger = join(HOST, port, "Fremder")
    assert stranger["result"] == "denied", stranger
    assert NOT_INVITED in str(stranger["reason"]), stranger

    # Ereignisdatei: Kopf, join und leave des Kindes, deny des Fremden (Beleg 04.1-01/02).
    await anyio.sleep(1.0)
    parsed = parse_events(_events_file(app_env, world_id))
    assert parsed is not None
    _seq, events = parsed
    kinds = {(event.kind, event.name) for event in events}
    assert ("join", kind_name) in kinds, events
    assert ("leave", kind_name) in kinds, events
    assert ("deny", "Fremder") in kinds, events

    # (3) Pausenzeit zählt nicht: zwei Takte mit Abstand, der Verbrauch steht.
    await _tick(service)
    used = _usage(app_env, "gw-kind2")
    assert used > 0, "Positivkontrolle: vor der Pause wurde gespielt"
    await anyio.sleep(15.0)
    await _tick(service)
    assert _usage(app_env, "gw-kind2") == used
    assert _usage(app_env, "gw-kind") == 0

    # (4) Weiter: Pause sofort vorbei, das Kind kommt ohne Neustart hinein.
    ended = await _post(client, "/end")
    assert ended["active"] is False, ended
    accepted = join(HOST, port, kind_name, kind_pw)
    assert accepted["result"] == "auth_accept", accepted
    api = docker_api()
    try:
        assert container_status(api, world_id) == "running"
        assert started_at(api, world_id) == started_before
    finally:
        api.close()

    # (5) Für heute Schluss: Kind mit Regeln abgelehnt mit dem Schluss-Text (morgen ganzer Tag, Minute 0).
    await anyio.sleep(COOLDOWN_PAUSE)
    schluss = await _post(client, "/schluss")
    assert schluss["art"] == "schluss", schluss
    locked = join(HOST, port, rules_name, rules_pw)
    assert locked["result"] == "denied", locked
    assert pause_text("schluss", 0) in str(locked["reason"]), locked
    assert _usage(app_env, "gw-kind2") == used

    # Aufräumen: Pause beenden, Welt löschen (das Cleanup-Fixture entfernt Reste).
    await _post(client, "/end")
    await delete_world(client, world_id)
