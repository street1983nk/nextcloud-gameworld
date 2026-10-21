"""GET /api/my/playtime: nur die eigene Restzeit, Opt-in und Schwelle 1 Minute (04-07, ZEIT-01).

Die Uhr der Spielzeit-Rechnung ist im Test fest (TimeEngine mit clock), damit
Restzeit, Fensterende und nächste Spielzeit genau prüfbar sind.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.playtime.engine import TimeEngine
from gameworld.playtime.plan import DayRule, WeekPlan
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import appapi_headers
from tests.test_service_lifecycle import FakeProvisioner

BERLIN = ZoneInfo("Europe/Berlin")
# Mittwoch, 21.10.2026 (Sommerzeit bis 25.10.)
WED = date(2026, 10, 21)
FRIEND = "gw-freund"
KEYS = {"limited", "state", "remaining_minutes", "until_minute", "next"}
UNLIMITED = {"limited": False, "state": None, "remaining_minutes": None, "until_minute": None, "next": None}


def _at(hour: int, minute: int = 0, second: int = 0) -> float:
    return datetime(2026, 10, 21, hour, minute, second, tzinfo=BERLIN).timestamp()


class Clock:
    def __init__(self) -> None:
        self.now = _at(15)

    def __call__(self) -> float:
        return self.now


def _daily(limit: int | None, start: int | None = None, end: int | None = None) -> WeekPlan:
    return WeekPlan({weekday: DayRule(True, limit, start, end) for weekday in range(1, 8)})


def _weekend_only() -> WeekPlan:
    days = {weekday: DayRule(False, None, None, None) for weekday in range(1, 6)}
    days |= {weekday: DayRule(True, 120, 600, 1140) for weekday in (6, 7)}
    return WeekPlan(days)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Kind", rotation=0))
    world_store.insert_player(PlayerRow(nc_user=FRIEND, player_name="Freundin", rotation=0))
    return world_store


@pytest.fixture
def service(store: WorldStore, clock: Clock, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    monkeypatch.setattr(world_service, "_time", TimeEngine(store, clock=clock))
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


def _rules(store: WorldStore, nc_user: str, plan: WeekPlan, used_s: int = 0) -> None:
    store.set_child_plan(nc_user, plan, None, "admin", "2026-10-21T10:00:00+00:00")
    if used_s:
        store.add_usage(nc_user, WED, used_s)


async def _mine(client: httpx.AsyncClient, user: str = "gw-kind") -> httpx.Response:
    return await client.get("/api/my/playtime", headers=appapi_headers(user))


async def test_child_without_rules_is_unlimited(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await _mine(client)
    assert response.status_code == 200, response.text
    assert response.json() == UNLIMITED


async def test_limit_with_window_until_19(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    _rules(store, "gw-kind", _daily(60, 540, 1140), used_s=15 * 60)
    response = await _mine(client)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "limited": True,
        "state": "ok",
        "remaining_minutes": 45,
        "until_minute": 1140,
        "next": None,
    }


async def test_rest_below_one_minute_counts_as_used_up(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """Pitfall 8: dieselbe Schwelle wie MIN_LEFT im Welt-Mod (60 s)."""
    del service
    _rules(store, "gw-kind", _daily(60, 540, 1140), used_s=60 * 60 - 30)
    data = (await _mine(client)).json()
    assert data["state"] == "aufgebraucht"
    assert data["remaining_minutes"] == 0
    assert data["until_minute"] is None
    # Heute hat das Fenster schon begonnen: nächste Spielzeit Donnerstag 9 Uhr.
    assert data["next"] == {"weekday": 4, "minute": 540, "days_ahead": 1}


async def test_limit_used_up(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    _rules(store, "gw-kind", _daily(60), used_s=60 * 60)
    data = (await _mine(client)).json()
    assert data["state"] == "aufgebraucht"
    assert data["next"] == {"weekday": 4, "minute": 0, "days_ahead": 1}


async def test_day_not_allowed(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    _rules(store, "gw-kind", _weekend_only())
    data = (await _mine(client)).json()
    assert data == {
        "limited": True,
        "state": "tag",
        "remaining_minutes": 0,
        "until_minute": None,
        "next": {"weekday": 6, "minute": 600, "days_ahead": 3},
    }


async def test_before_window_today(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    _rules(store, "gw-kind", _daily(60, 960, 1140))
    data = (await _mine(client)).json()
    assert data["state"] == "fenster"
    assert data["next"] == {"weekday": 3, "minute": 960, "days_ahead": 0}


async def test_window_ends_within_a_minute(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, clock: Clock
) -> None:
    del service
    _rules(store, "gw-kind", _daily(None, 540, 1140))
    clock.now = _at(18, 59, 30)
    data = (await _mine(client)).json()
    assert data["state"] == "fenster"
    assert data["remaining_minutes"] == 0
    assert data["next"] == {"weekday": 4, "minute": 540, "days_ahead": 1}


async def test_remaining_never_exceeds_window_end(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, clock: Clock
) -> None:
    del service
    _rules(store, "gw-kind", _daily(120, 540, 1140))
    clock.now = _at(18, 30)
    data = (await _mine(client)).json()
    assert data["state"] == "ok"
    assert data["remaining_minutes"] == 30
    assert data["until_minute"] == 1140


async def test_rules_without_limit_or_window(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """Regeln, aber heute ganzer Tag ohne Limit: keine Minuten, kein Ende (Tagesende = null)."""
    del service
    _rules(store, "gw-kind", _daily(None))
    data = (await _mine(client)).json()
    assert data == {"limited": True, "state": "ok", "remaining_minutes": None, "until_minute": None, "next": None}


async def test_answer_has_only_own_values(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    """T-04-37: keine Pläne, keine Verbrauchshistorie, nichts von einem zweiten Kind."""
    del service
    _rules(store, "gw-kind", _daily(60, 540, 1140), used_s=15 * 60)
    _rules(store, FRIEND, _daily(90, 600, 1200), used_s=20 * 60)

    # Positivkontrolle: Das zweite Kind bekommt seine eigenen Werte.
    friend = (await _mine(client, FRIEND)).json()
    assert friend["remaining_minutes"] == 70
    assert friend["until_minute"] == 1200

    response = await _mine(client)
    data = response.json()
    assert set(data) == KEYS
    assert data["remaining_minutes"] == 45
    assert data["until_minute"] == 1140
    text = json.dumps(data)
    for foreign in (FRIEND, "Freundin", "1200", "70", "normal", "holiday", "used_today_s", "nc_user", "player_name"):
        assert foreign not in text


async def test_no_uid_from_browser(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    """T-04-38: Ein UID-Parameter wird ignoriert; die UID kommt aus der signierten Anfrage."""
    del service
    _rules(store, FRIEND, _daily(90))
    response = await client.get(f"/api/my/playtime?nc_user={FRIEND}&uid={FRIEND}", headers=appapi_headers())
    assert response.json() == UNLIMITED


async def test_verwalter_is_free(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    store.insert_player(PlayerRow(nc_user="admin", player_name="Papa", rotation=0))
    _rules(store, "admin", _daily(60))
    response = await _mine(client, "admin")
    assert response.status_code == 200
    assert response.json() == UNLIMITED


async def test_admin_snapshot_is_free(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    """Steht ein Konto im Verwalter-Schnappschuss, ist es freigestellt wie im Welt-Mod (A4)."""
    del service
    _rules(store, "gw-kind", _daily(60))
    store.set_meta("time_admins", json.dumps(["admin", "gw-kind"]))
    assert (await _mine(client)).json() == UNLIMITED


async def test_store_error_is_503(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    del service

    def broken() -> object:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(store, "child_plans", broken)
    response = await _mine(client)
    assert response.status_code == 503
    assert "locked" not in response.text
    assert response.json()["detail"] == "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."


async def test_role_failure_is_503(
    client: httpx.AsyncClient, service: WorldService, role_lookup_error: list[str]
) -> None:
    del service
    response = await _mine(client)
    assert response.status_code == 503
    assert role_lookup_error == ["gw-kind"]


async def test_same_weekday_next_week_is_not_today(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """Nur mittwochs erlaubt und heute aufgebraucht: nächste Spielzeit in 7 Tagen, nicht "heute"."""
    del service
    days = {weekday: DayRule(weekday == 3, 60 if weekday == 3 else None, None, None) for weekday in range(1, 8)}
    _rules(store, "gw-kind", WeekPlan(days), used_s=60 * 60)
    data = (await _mine(client)).json()
    assert data["state"] == "aufgebraucht"
    assert data["next"] == {"weekday": 3, "minute": 0, "days_ahead": 7}


async def test_preset_daily_used_up_at_noon(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, clock: Clock
) -> None:
    """Voreinstellung "Jeden Tag 1 Stunde" (9 bis 19 Uhr), mittags aufgebraucht: morgen ab 9 Uhr."""
    del service
    _rules(store, "gw-kind", _daily(60, 540, 1140), used_s=60 * 60)
    clock.now = _at(12)
    data = (await _mine(client)).json()
    assert data["state"] == "aufgebraucht"
    assert data["next"] == {"weekday": 4, "minute": 540, "days_ahead": 1}
