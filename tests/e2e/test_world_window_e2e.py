"""Ende-zu-Ende: Zeitfenster pro Welt (ZEIT-05) mit Verwalter-Freistellung bis in den Spielserver.

Der Verwalter setzt das Wochen-Zeitfenster einer Welt per POST
/api/playtime/worlds/{id}/window; die ExApp schreibt die Welt-Zeile der
Regeldatei, der Zeit-Mod aus 04-01 setzt durch. Belegt Success Criterion 4:
außerhalb des Fensters kommt ein Kind nicht hinein, am Fensterende wird es mit
Vorwarnung getrennt, die Welt läuft weiter (O-05: Container running, StartedAt
und desired_state unverändert). Eingeladene Verwalter stehen mit "frei" in der
Regeldatei und kommen auch außerhalb hinein (O-11/A4); ein nicht eingeladener
Name bekommt weiter den Zugangstext (T-04-30). Seriell, MTG kreativ.
"""

from __future__ import annotations

import sqlite3
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
from gameworld.provisioner.time_mod import TEXT_WARN_1, TEXT_WELT, kid_text
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import join, session
from tests.e2e.time_helpers import HOST, MTG_READY, container_status, create_running_world, docker_api, started_at

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

JOIN_TIMEOUT = 30.0
COOLDOWN_PAUSE = 2.5
BERLIN = ZoneInfo("Europe/Berlin")
NOT_INVITED = "nicht eingeladen"


async def _midnight_guard() -> None:
    """Läuft der Test nahe 00:00, bis 00:01 warten: Ein Fenster darf nie über 24:00 laufen."""
    now = datetime.now(BERLIN)
    if now.hour == 23 and now.minute >= 50:
        target = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        await anyio.sleep((target - now).total_seconds())


def _days(open_days: dict[int, tuple[int, int]]) -> list[dict[str, object]]:
    days: list[dict[str, object]] = []
    for weekday in range(1, 8):
        window = open_days.get(weekday)
        if window is None:
            days.append({"weekday": weekday, "open": False})
        else:
            days.append({"weekday": weekday, "open": True, "window_start": window[0], "window_end": window[1]})
    return days


async def _set_window(client: httpx.AsyncClient, world_id: str, open_days: dict[int, tuple[int, int]]) -> None:
    response = await client.post(
        f"/api/playtime/worlds/{world_id}/window", json={"days": _days(open_days)}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    assert response.json()["applied"] is True, response.text


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


def _events(result: dict[str, object]) -> list[dict[str, object]]:
    events = result.get("events")
    assert isinstance(events, list)
    return [dict(event) for event in events if isinstance(event, dict)]  # pyright: ignore[reportUnknownArgumentType]


def _db_rows(app_env: Path, sql: str, world_id: str) -> list[tuple[object, ...]]:
    connection = sqlite3.connect(app_env / "gameworld.sqlite3")
    try:
        return connection.execute(sql, (world_id,)).fetchall()
    finally:
        connection.close()


async def test_world_window_e2e(client: httpx.AsyncClient, app_env: Path) -> None:
    await _midnight_guard()
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    kind_name, kind_pw = await _invite(client, world_id, "gw-kind")
    admin_name, admin_pw = await _invite(client, world_id, "admin")

    # Verwalter-Schnappschuss: GET /api/playtime als admin füllt meta time_admins.
    listed = await client.get("/api/playtime", headers=appapi_headers())
    assert listed.status_code == 200, listed.text
    assert "admin" not in [child["nc_user"] for child in listed.json()["children"]]
    assert '"admin"' in (WorldStore(app_env / "gameworld.sqlite3").get_meta("time_admins") or "")

    api = docker_api()
    try:
        started_before = started_at(api, world_id)
    finally:
        api.close()

    # (1) Geschlossen: Fenster nur morgen 10:00 bis 12:00, heute zu.
    today = datetime.now(BERLIN).date()
    tomorrow = today + timedelta(days=1)
    await _set_window(client, world_id, {tomorrow.isoweekday(): (600, 720)})
    denied = join(HOST, port, kind_name, kind_pw)
    assert denied["result"] == "denied", denied
    assert kid_text("welt", 1, tomorrow.isoweekday(), 600) in str(denied["reason"]), denied

    accepted = join(HOST, port, admin_name, admin_pw)
    assert accepted["result"] == "auth_accept", accepted
    await anyio.sleep(COOLDOWN_PAUSE)
    held = session(HOST, port, admin_name, admin_pw, hold=10.0, timeout=JOIN_TIMEOUT)
    assert held["result"] == "held", held

    # Zugangstext gewinnt: ein Fremder erfährt nichts über das Fenster (T-04-30).
    stranger = join(HOST, port, "Fremder")
    assert stranger["result"] == "denied", stranger
    assert NOT_INVITED in str(stranger["reason"]), stranger
    assert TEXT_WELT not in str(stranger["reason"]), stranger

    # (2) Fensterende live: heute 00:00 bis jetzt plus 3 Minuten.
    await _midnight_guard()
    now = datetime.now(BERLIN)
    end_minute = now.hour * 60 + now.minute + 3
    await _set_window(client, world_id, {now.date().isoweekday(): (0, end_minute)})
    window_end = datetime.combine(now.date(), datetime.min.time(), tzinfo=BERLIN) + timedelta(minutes=end_minute)
    admin_hold = window_end.timestamp() - time.time() + 25.0
    await anyio.sleep(COOLDOWN_PAUSE)

    kind_result: dict[str, object] = {}
    admin_result: dict[str, object] = {}

    async def run_kind() -> None:
        kind_result.update(
            await anyio.to_thread.run_sync(partial(session, HOST, port, kind_name, kind_pw, 240.0, JOIN_TIMEOUT))
        )

    async def run_admin() -> None:
        admin_result.update(
            await anyio.to_thread.run_sync(partial(session, HOST, port, admin_name, admin_pw, admin_hold, JOIN_TIMEOUT))
        )

    async with anyio.create_task_group() as group:
        group.start_soon(run_kind)
        group.start_soon(run_admin)

    assert kind_result["result"] == "kicked", kind_result
    assert float(str(kind_result["after_s"])) < 200, kind_result
    assert TEXT_WELT in str(kind_result["reason"]), kind_result
    events = _events(kind_result)
    kick_at = next(float(str(e["t"])) for e in events if e.get("kind") == "kick")
    warned = [e for e in events if e.get("kind") == "chat" and TEXT_WARN_1 in str(e.get("text"))]
    assert warned, kind_result
    assert float(str(warned[0]["t"])) < kick_at, kind_result
    # Der Verwalter hält über das Fensterende hinaus (frei).
    assert admin_result["result"] == "held", admin_result

    # (3) Die Welt läuft weiter: Container running, StartedAt und desired_state unverändert (O-05).
    api = docker_api()
    try:
        assert container_status(api, world_id) == "running"
        assert started_at(api, world_id) == started_before
    finally:
        api.close()
    assert _db_rows(app_env, "SELECT desired_state FROM worlds WHERE id = ?", world_id) == [("running",)]
    world = await _world(client, world_id)
    assert world["status"] == "running", world
    assert world["time_window"] is not None

    # (4) Fenster entfernen: Das Kind kommt ohne Neustart wieder hinein.
    await anyio.sleep(COOLDOWN_PAUSE)
    cleared = await client.delete(f"/api/playtime/worlds/{world_id}/window", headers=appapi_headers())
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["time_window"] is None
    assert join(HOST, port, kind_name, kind_pw)["result"] == "auth_accept"
    api = docker_api()
    try:
        assert started_at(api, world_id) == started_before
    finally:
        api.close()

    # (5) Welt löschen: keine Welt-Fenster und keine Zählbuchstände der Welt mehr.
    # Positivkontrolle: vor dem Löschen stehen Fenster und (nach einem Takt) Zählbuchstände da.
    await _set_window(client, world_id, {today.isoweekday(): (0, 1440)})
    await anyio.to_thread.run_sync(worlds_api.get_service().tick_time)
    assert _db_rows(app_env, "SELECT weekday FROM world_windows WHERE world_id = ?", world_id) != []
    assert _db_rows(app_env, "SELECT player_name FROM time_ledger_seen WHERE world_id = ?", world_id) != []
    deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
    assert deleted.status_code == 204, deleted.text
    assert _db_rows(app_env, "SELECT weekday FROM world_windows WHERE world_id = ?", world_id) == []
    assert _db_rows(app_env, "SELECT player_name FROM time_ledger_seen WHERE world_id = ?", world_id) == []
