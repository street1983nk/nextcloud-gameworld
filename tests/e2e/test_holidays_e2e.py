"""Ende-zu-Ende: Wochentag, automatische Ferienumschaltung und Zeitzone im Spielserver.

Der Verwalter pflegt Wochenplan, Ferienplan, Haushalts-Ferien und Zeitzone per
API; die ExApp schreibt die Regeldatei sofort in die laufende Welt (ohne
Neustart), der Mod aus 04-01 setzt durch. Belegt Success Criterion 2
(Wochenplan pro Wochentag, ohne UI) und 3 (Ferien mit Umschaltung am lokalen
Datum) samt Zeitzonen-Einstellung (O-02, O-08). Seriell, MTG kreativ.

Die Erwartungen rechnet der Test selbst mit zoneinfo (lokaler Tag, Tagesgrenzen,
Wochentag), unabhängig von ``playtime.plan``; nur die ASCII-Wochentagskürzel
kommen als Vertrag aus ``WEEKDAY_TOKENS``.
"""

from __future__ import annotations

import io
import tarfile
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import anyio
import httpx
import pytest

from gameworld.playtime.plan import WEEKDAY_TOKENS
from gameworld.provisioner.time_mod import RULES_FILE, TEXT_NEXT, TEXT_TAG
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import join, session
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world, delete_world, docker_api, started_at

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

JOIN_TIMEOUT = 30.0
COOLDOWN_PAUSE = 2.5
BERLIN = ZoneInfo("Europe/Berlin")
KIRITIMATI = "Pacific/Kiritimati"


async def _midnight_guard() -> None:
    """Nahe 00:00 bis 00:01 warten: Heute und morgen dürfen sich im Test nicht verschieben."""
    now = datetime.now(BERLIN)
    if now.hour == 23 and now.minute >= 50:
        target = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        await anyio.sleep((target - now).total_seconds())


def _local_today(zone: ZoneInfo) -> date:
    return datetime.now(zone).date()


def _day_bounds(day: date, zone: ZoneInfo) -> tuple[int, int]:
    """Lokaler Tag als Epoch: 00:00 bis Folgetag 00:00 (eigene Rechnung des Tests)."""
    start = datetime.combine(day, time(0), tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time(0), tzinfo=zone)
    return int(start.timestamp()), int(end.timestamp())


def _day(weekday: int, *, allowed: bool, limit: int | None = None, ws: int | None = None, we: int | None = None):
    day: dict[str, object] = {"weekday": weekday, "allowed": allowed}
    if limit is not None:
        day["limit_minutes"] = limit
    if ws is not None:
        day["window_start"] = ws
    if we is not None:
        day["window_end"] = we
    return day


def _only_tomorrow(tomorrow_weekday: int) -> list[dict[str, object]]:
    """Nur morgen erlaubt, 10:00 bis 12:00, Limit 60 min; alle anderen Tage nicht erlaubt."""
    return [
        _day(wd, allowed=True, limit=60, ws=600, we=720) if wd == tomorrow_weekday else _day(wd, allowed=False)
        for wd in range(1, 8)
    ]


def _every_day_free() -> list[dict[str, object]]:
    """Jeden Tag erlaubt, ganzer Tag, ohne Limit."""
    return [_day(wd, allowed=True) for wd in range(1, 8)]


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> tuple[str, str]:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


async def _set_rules(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.post("/api/playtime/children/gw-kind", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert response.json()["applied"] is True


async def _add_holiday(client: httpx.AsyncClient, start: date, end: date, label: str) -> int:
    body = {"label": label, "start_date": start.isoformat(), "end_date": end.isoformat()}
    response = await client.post("/api/playtime/holidays", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert response.json()["applied"] is True
    return int(response.json()["id"])


async def _remove_holiday(client: httpx.AsyncClient, holiday_id: int) -> None:
    response = await client.delete(f"/api/playtime/holidays/{holiday_id}", headers=appapi_headers())
    assert response.status_code == 200, response.text


async def _set_zone(client: httpx.AsyncClient, name: str) -> httpx.Response:
    return await client.post("/api/playtime/time-zone", json={"time_zone": name}, headers=appapi_headers())


def _rules_line(world_id: str, name: str) -> list[str]:
    """Zeile eines Spielers aus der Regeldatei der Welt (docker get_archive)."""
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
            return parts
    raise AssertionError(f"keine Zeile für {name} in der Regeldatei")


def _started(world_id: str) -> str:
    api = docker_api()
    try:
        return started_at(api, world_id)
    finally:
        api.close()


async def _denied_with(port: int, name: str, password: str, text: str) -> None:
    await anyio.sleep(COOLDOWN_PAUSE)
    denied = join(HOST, port, name, password)
    assert denied["result"] == "denied", denied
    assert text in str(denied["reason"]), denied


async def test_holidays_e2e(client: httpx.AsyncClient) -> None:
    await _midnight_guard()
    zone_set = await _set_zone(client, "Europe/Berlin")
    assert zone_set.status_code == 200, zone_set.text
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    kind_name, kind_pw = await _invite(client, world_id, "gw-kind")
    first_start = _started(world_id)

    today = _local_today(BERLIN)
    tomorrow = today + timedelta(days=1)
    tomorrow_token = WEEKDAY_TOKENS[tomorrow.isoweekday() - 1]

    # (1) Wochenplan: nur morgen erlaubt; heute lehnt der Server mit Wochentag und Uhrzeit ab.
    await _set_rules(client, {"normal": _only_tomorrow(tomorrow.isoweekday())})
    await _denied_with(port, kind_name, kind_pw, f"{TEXT_TAG}{TEXT_NEXT}{tomorrow_token} 10:00")

    # (2) Ferien heute: Ferienplan gilt ohne Zutun und ohne Neustart.
    await _set_rules(client, {"normal": _only_tomorrow(tomorrow.isoweekday()), "holiday": _every_day_free()})
    # Ferienplan gesetzt, aber noch kein Zeitraum: weiter Normalplan.
    await _denied_with(port, kind_name, kind_pw, TEXT_TAG)
    holiday_id = await _add_holiday(client, today, today, "Heute frei")
    listed = (await client.get("/api/playtime", headers=appapi_headers())).json()
    assert [item["active"] for item in listed["holidays"]] == [True], listed["holidays"]
    await anyio.sleep(COOLDOWN_PAUSE)
    assert join(HOST, port, kind_name, kind_pw)["result"] == "auth_accept"
    held = session(HOST, port, kind_name, kind_pw, hold=15.0, timeout=JOIN_TIMEOUT)
    assert held["result"] == "held", held
    assert _started(world_id) == first_start, "Die Welt wurde neu gestartet"
    line = _rules_line(world_id, kind_name)
    assert line[4] == "ok", line
    assert int(line[1]) == -1, line  # ohne Limit
    assert (int(line[2]), int(line[3])) == _day_bounds(today, BERLIN), line

    # (3) Ferien entfernt: sofort wieder der Normalplan.
    await _remove_holiday(client, holiday_id)
    assert _rules_line(world_id, kind_name)[4] == "tag"
    await _denied_with(port, kind_name, kind_pw, TEXT_TAG)

    # (4) Ferien von vorgestern bis gestern: am heutigen Datum gilt der Normalplan.
    past_id = await _add_holiday(client, today - timedelta(days=2), today - timedelta(days=1), "Vorbei")
    listed = (await client.get("/api/playtime", headers=appapi_headers())).json()
    assert [item["active"] for item in listed["holidays"]] == [False], listed["holidays"]
    await _denied_with(port, kind_name, kind_pw, TEXT_TAG)

    # (5) Zeitzone: die Tagesgrenzen folgen sofort der neuen Zone (jeden Tag frei, damit sie sichtbar sind).
    await _set_rules(client, {"normal": _every_day_free()})
    berlin_line = _rules_line(world_id, kind_name)
    assert (int(berlin_line[2]), int(berlin_line[3])) == _day_bounds(_local_today(BERLIN), BERLIN), berlin_line
    try:
        switched = await _set_zone(client, KIRITIMATI)
        assert switched.status_code == 200, switched.text
        assert switched.json()["applied"] is True
        kiri = ZoneInfo(KIRITIMATI)
        kiri_line = _rules_line(world_id, kind_name)
        assert kiri_line[4] == "ok", kiri_line
        assert (int(kiri_line[2]), int(kiri_line[3])) == _day_bounds(_local_today(kiri), kiri), kiri_line
        assert kiri_line[2:4] != berlin_line[2:4]
        listed = (await client.get("/api/playtime", headers=appapi_headers())).json()
        assert listed["time_zone"] == KIRITIMATI
        assert (await _set_zone(client, "Mars/Base")).status_code == 422
    finally:
        restored = await _set_zone(client, "Europe/Berlin")
        assert restored.status_code == 200, restored.text
    assert (await client.get("/api/playtime", headers=appapi_headers())).json()["time_zone"] == "Europe/Berlin"
    assert _started(world_id) == first_start, "Die Welt wurde neu gestartet"

    # Aufräumen: Ferien, Regeln, Welt.
    await _remove_holiday(client, past_id)
    cleared = await client.delete("/api/playtime/children/gw-kind", headers=appapi_headers())
    assert cleared.status_code == 200, cleared.text
    assert (await client.get("/api/playtime", headers=appapi_headers())).json()["holidays"] == []
    await delete_world(client, world_id)
