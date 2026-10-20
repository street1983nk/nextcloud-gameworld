"""Spielzeit-API über ASGI: Verwalter-Sperre, Setzen/Entfernen, Validierung und sofortiger Push."""

from __future__ import annotations

import io
import tarfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner
from gameworld.provisioner.time_mod import RULES_FILE_NAME
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldRow, WorldStore
from tests.conftest import appapi_headers
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
W3 = "aaaaaaaaaaa3"
VERIFIER = "#1#c2FsdA==#dmVyaWZpZXI="


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(
        WorldRow(
            id=W1,
            name="Testwelt",
            port=30015,
            container_name="gw-x-w1",
            volume_name="gw-x-w1",
            world_key="k",
            engine_version="5.17.0",
            desired_state="running",
            op_state="ready",
            last_error=None,
            created_at="2026-10-20T10:00:00+00:00",
        )
    )
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Kind", rotation=0))
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER})
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


def _day(weekday: int, *, allowed: bool = True, limit: int | None = 120) -> dict[str, object]:
    day: dict[str, object] = {"weekday": weekday, "allowed": allowed}
    if limit is not None:
        day["limit_minutes"] = limit
    return day


def _plan_body() -> dict[str, object]:
    return {"normal": [_day(weekday) for weekday in range(1, 8)]}


def _last_rules(fake: FakeProvisioner) -> str:
    for _world_id, archive in reversed(fake.written):
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            if RULES_FILE_NAME in tar.getnames():
                handle = tar.extractfile(RULES_FILE_NAME)
                assert handle is not None
                return handle.read().decode("ascii")
    raise AssertionError("keine Regeldatei geschrieben")


async def test_get_playtime_lists_players_with_defaults(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.get("/api/playtime", headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["time_zone"] == "Europe/Berlin"
    [child] = data["children"]
    assert child["nc_user"] == "gw-kind"
    assert child["display_name"] == "Kind (Dev)"
    assert child["player_name"] == "Kind"
    assert child["has_rules"] is False
    assert child["normal"] is None
    assert child["used_today_s"] == 0
    assert child["state"] is None


async def test_post_sets_rules_and_pushes_immediately(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del service
    fake.written.clear()
    response = await client.post("/api/playtime/children/gw-kind", json=_plan_body(), headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_rules"] is True
    assert data["applied"] is True
    assert len(data["normal"]) == 7
    assert data["state"]["reason"] == "ok"
    # Die Regeldatei der Welt des Kindes wurde sofort geschrieben.
    assert "\nKind " in _last_rules(fake)
    assert "gw-kind" in store.child_plans()


@pytest.mark.parametrize(
    "body",
    [
        {"normal": [_day(weekday) for weekday in range(1, 7)]},  # nur 6 Tage
        {"normal": [_day(1), _day(1), *(_day(weekday) for weekday in range(3, 8))]},  # Dublette
        {"normal": [_day(1, limit=0), *(_day(weekday) for weekday in range(2, 8))]},  # Limit 0
        {"normal": [_day(1, limit=1441), *(_day(weekday) for weekday in range(2, 8))]},  # Limit 1441
        {
            "normal": [
                {"weekday": 1, "allowed": True, "window_start": 600, "window_end": 600},
                *(_day(weekday) for weekday in range(2, 8)),
            ]
        },  # Fenster Ende <= Anfang
        {
            "normal": [
                {"weekday": 1, "allowed": True, "window_start": 600},
                *(_day(weekday) for weekday in range(2, 8)),
            ]
        },  # nur ein Fensterfeld
        {"normal": [{"weekday": 1, "allowed": True, "foo": 1}, *(_day(weekday) for weekday in range(2, 8))]},  # Feld
        {"normal": [_day(weekday) for weekday in range(1, 8)], "extra": 1},  # unbekanntes Plan-Feld
    ],
)
async def test_invalid_body_is_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, body: object
) -> None:
    del service
    response = await client.post("/api/playtime/children/gw-kind", json=body, headers=appapi_headers())
    assert response.status_code == 422
    assert "gw-kind" not in store.child_plans()


async def test_post_unknown_account_is_404(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post("/api/playtime/children/niemand", json=_plan_body(), headers=appapi_headers())
    assert response.status_code == 404
    assert "Spieler" in response.json()["detail"]


async def test_delete_clears_rules_and_usage(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    posted = await client.post("/api/playtime/children/gw-kind", json=_plan_body(), headers=appapi_headers())
    assert posted.status_code == 200
    store.add_usage("gw-kind", date.today(), 300)

    response = await client.delete("/api/playtime/children/gw-kind", headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["has_rules"] is False
    assert data["applied"] is True
    assert data["normal"] is None
    assert data["state"] is None
    assert "gw-kind" not in store.child_plans()
    assert store.usage("gw-kind", date.today()) == 0


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "", None),
        ("POST", "/children/gw-kind", _plan_body()),
        ("DELETE", "/children/gw-kind", None),
        ("POST", "/holidays", {"label": "Ferien", "start_date": "2026-10-20", "end_date": "2026-10-30"}),
        ("DELETE", "/holidays/1", None),
        ("POST", "/time-zone", {"time_zone": "Europe/Vienna"}),
    ],
)
async def test_child_is_forbidden(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, method: str, path: str, body: object
) -> None:
    del service
    store.add_holiday(date(2026, 1, 1), date(2026, 1, 2), "Bestand")
    response = await client.request(method, f"/api/playtime{path}", json=body, headers=appapi_headers("gw-kind"))
    assert response.status_code != 200
    assert response.status_code == 403
    # Nichts verändert: der Bestand bleibt, keine neuen Ferien, Zeitzone unverändert.
    assert len(store.list_holidays()) == 1
    assert store.get_meta("time_zone") in (None, "", "Europe/Berlin")


# Ferienplan je Kind, Haushalts-Ferien und Zeitzone (04-04)


def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Berlin")).date()


def _holiday_body(start: date, end: date, label: str = "Herbstferien") -> dict[str, object]:
    return {"label": label, "start_date": start.isoformat(), "end_date": end.isoformat()}


async def test_post_with_holiday_plan_and_null(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    body = {**_plan_body(), "holiday": [_day(weekday, limit=None) for weekday in range(1, 8)]}
    response = await client.post("/api/playtime/children/gw-kind", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert len(response.json()["holiday"]) == 7

    listed = (await client.get("/api/playtime", headers=appapi_headers())).json()
    [child] = listed["children"]
    assert len(child["holiday"]) == 7
    assert child["holiday"][0]["limit_minutes"] is None
    assert store.child_plans()["gw-kind"][1] is not None

    response = await client.post("/api/playtime/children/gw-kind", json=_plan_body(), headers=appapi_headers())
    assert response.status_code == 200
    assert response.json()["holiday"] is None
    [child] = (await client.get("/api/playtime", headers=appapi_headers())).json()["children"]
    assert child["holiday"] is None


async def test_invalid_holiday_plan_is_422(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    body = {**_plan_body(), "holiday": [_day(weekday) for weekday in range(1, 7)]}
    response = await client.post("/api/playtime/children/gw-kind", json=body, headers=appapi_headers())
    assert response.status_code == 422
    assert "gw-kind" not in store.child_plans()


async def test_holidays_add_list_active_and_delete(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    today = _today()
    later = await client.post(
        "/api/playtime/holidays",
        json=_holiday_body(today + timedelta(days=30), today + timedelta(days=40), "Später"),
        headers=appapi_headers(),
    )
    assert later.status_code == 200, later.text
    now = await client.post("/api/playtime/holidays", json=_holiday_body(today, today), headers=appapi_headers())
    assert now.status_code == 200, now.text
    holiday_id = now.json()["id"]
    assert isinstance(holiday_id, int)

    data = (await client.get("/api/playtime", headers=appapi_headers())).json()
    holidays = data["holidays"]
    assert [item["label"] for item in holidays] == ["Herbstferien", "Später"]
    assert [item["active"] for item in holidays] == [True, False]
    assert holidays[0]["start_date"] == today.isoformat()

    deleted = await client.delete(f"/api/playtime/holidays/{holiday_id}", headers=appapi_headers())
    assert deleted.status_code == 200, deleted.text
    assert [item.label for item in store.list_holidays()] == ["Später"]

    missing = await client.delete(f"/api/playtime/holidays/{holiday_id}", headers=appapi_headers())
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"label": "x", "start_date": "2026-11-02", "end_date": "2026-11-01"},  # von nach bis
        {"label": "x", "start_date": "2026-02-30", "end_date": "2026-03-01"},  # kein Datum
        {"label": "x", "start_date": "2026-01-01", "end_date": "2027-01-03"},  # länger als 366 Tage
        {"label": "x" * 61, "start_date": "2026-11-01", "end_date": "2026-11-02"},  # Label zu lang
        {"label": "a\nb", "start_date": "2026-11-01", "end_date": "2026-11-02"},  # Zeilenumbruch
        {"label": "x", "start_date": "2026-11-01", "end_date": "2026-11-02", "extra": 1},  # Feld
        {"label": "x", "start_date": "2026-11-01"},  # bis fehlt
    ],
)
async def test_invalid_holiday_is_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, body: object
) -> None:
    del service
    response = await client.post("/api/playtime/holidays", json=body, headers=appapi_headers())
    assert response.status_code == 422, response.text
    assert store.list_holidays() == []


async def test_holiday_366_days_is_ok(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    body = {"start_date": "2026-01-01", "end_date": "2027-01-01"}
    response = await client.post("/api/playtime/holidays", json=body, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert response.json()["label"] == ""


async def test_51st_holiday_is_422(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    for index in range(50):
        day = date(2030, 1, 1) + timedelta(days=index)
        store.add_holiday(day, day, f"F{index}")
    response = await client.post(
        "/api/playtime/holidays", json=_holiday_body(date(2031, 1, 1), date(2031, 1, 2)), headers=appapi_headers()
    )
    assert response.status_code == 422
    assert len(store.list_holidays()) == 50


async def test_time_zone_set_and_listed(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    response = await client.post(
        "/api/playtime/time-zone", json={"time_zone": "Europe/Vienna"}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    assert response.json()["time_zone"] == "Europe/Vienna"
    assert store.get_meta("time_zone") == "Europe/Vienna"
    data = (await client.get("/api/playtime", headers=appapi_headers())).json()
    assert data["time_zone"] == "Europe/Vienna"


@pytest.mark.parametrize("name", ["Mars/Base", "", "../etc", "/etc/passwd", "Europe/../../etc"])
async def test_invalid_time_zone_is_422(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, name: str
) -> None:
    del service
    response = await client.post("/api/playtime/time-zone", json={"time_zone": name}, headers=appapi_headers())
    assert response.status_code == 422
    assert store.get_meta("time_zone") in (None, "")


def _second_worlds(store: WorldStore, fake: FakeProvisioner) -> None:
    """Welt W2 mit Container, Welt W3 ohne Container (der nächste Start schreibt)."""
    for world_id, port in ((W2, 30016), (W3, 30017)):
        store.insert_world(
            WorldRow(
                id=world_id,
                name="Weitere",
                port=port,
                container_name=f"gw-x-{world_id}",
                volume_name=f"gw-x-{world_id}",
                world_key="k",
                engine_version="5.17.0",
                desired_state="running",
                op_state="ready",
                last_error=None,
                created_at="2026-10-20T10:00:00+00:00",
            )
        )
    fake.containers[W2] = (30016, "running")


def _rules_worlds(fake: FakeProvisioner) -> set[str]:
    worlds: set[str] = set()
    for world_id, archive in fake.written:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            if RULES_FILE_NAME in tar.getnames():
                worlds.add(world_id)
    return worlds


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", "/holidays", {"label": "x", "start_date": "2026-11-01", "end_date": "2026-11-02"}),
        ("DELETE", "/holidays/{id}", None),
        ("POST", "/time-zone", {"time_zone": "Europe/Vienna"}),
    ],
)
async def test_changes_push_all_worlds(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake: FakeProvisioner,
    method: str,
    path: str,
    body: object,
) -> None:
    del service
    _second_worlds(store, fake)
    holiday_id = store.add_holiday(date(2026, 12, 1), date(2026, 12, 2), "Bestand")
    fake.written.clear()
    response = await client.request(
        method, f"/api/playtime{path.replace('{id}', str(holiday_id))}", json=body, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    assert _rules_worlds(fake) == {W1, W2}
    # W3 hat keinen Container: nicht alle Welten tragen die Änderung schon.
    assert response.json()["applied"] is False


async def test_holiday_switches_rules_immediately(
    client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner
) -> None:
    del service
    weekday = _today().isoweekday()
    normal = [_day(wd, allowed=wd != weekday) for wd in range(1, 8)]
    holiday = [_day(wd, limit=None) for wd in range(1, 8)]
    posted = await client.post(
        "/api/playtime/children/gw-kind", json={"normal": normal, "holiday": holiday}, headers=appapi_headers()
    )
    assert posted.status_code == 200, posted.text
    assert _last_rules(fake).split("\nKind ")[1].split("\n")[0].split(" ")[3] == "tag"

    today = _today()
    added = await client.post("/api/playtime/holidays", json=_holiday_body(today, today), headers=appapi_headers())
    assert added.status_code == 200
    line = _last_rules(fake).split("\nKind ")[1].split("\n")[0]
    assert line.split(" ")[3] == "ok"
