"""Verwalter-API für die Handy-Seiten: Fremdversuche, Rückblick, Einstellung, Basis-URL (04.1-04)."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.notify.loop import META_LINK_ORIGIN
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import appapi_headers, give_rules
from tests.test_pause_api import _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 21)


def _household_today(zone: ZoneInfo = BERLIN) -> str:
    return datetime.now(zone).date().isoformat()


@pytest.mark.parametrize("path", ["/api/attempts", "/api/review"])
async def test_without_day_backend_uses_household_today(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, path: str
) -> None:
    """IN-04: Ohne tag nimmt das Backend den heutigen Tag der Haushalts-Zeitzone, nicht die Uhr des Handys."""
    del service
    # Eine Zeitzone weit weg von der Geräteuhr: Pacific/Kiritimati (UTC+14) liegt oft schon im Morgen.
    store.set_meta("time_zone", "Pacific/Kiritimati")
    response = await client.get(path, headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    expected = _household_today(ZoneInfo("Pacific/Kiritimati"))
    assert data["day"] == expected
    assert data["today"] == expected


async def test_explicit_day_is_kept_and_today_reported(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.get("/api/review", params={"day": "2026-10-20"}, headers=appapi_headers())
    assert (response.json()["day"], response.json()["today"]) == ("2026-10-20", _household_today())


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    give_rules(world_store, "gw-kind")
    world_store.insert_player(PlayerRow(nc_user="admin", player_name="Papa", rotation=0))
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    return world_store


@pytest.fixture
def service(store: WorldStore, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


async def test_attempts_lists_world_player_clock_and_count(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    at = int(datetime(2026, 10, 21, 18, 5, tzinfo=BERLIN).timestamp())
    store.claim_attempt(DAY, W1, "Fremder", at)
    store.claim_attempt(DAY, W1, "Fremder", at + 60)
    store.claim_attempt(DAY, W2, "Anderer", at + 120)
    response = await client.get("/api/attempts", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.pop("today") == _household_today()
    assert data == {
        "day": "2026-10-21",
        "attempts": [
            {"world_id": W1, "world_name": "Wiese", "player_name": "Fremder", "clock": "18:05", "count": 2},
            {"world_id": W2, "world_name": "Burg", "player_name": "Anderer", "clock": "18:07", "count": 1},
        ],
    }
    filtered = await client.get("/api/attempts", params={"day": "2026-10-21", "world": W2}, headers=appapi_headers())
    assert [item["player_name"] for item in filtered.json()["attempts"]] == ["Anderer"]


@pytest.mark.parametrize(
    "params",
    [{"day": "2026-13-01"}, {"day": "gestern"}, {"day": ""}, {"day": "2026-10-21", "world": "../etc"}],
)
async def test_attempts_validates_query(
    client: httpx.AsyncClient, service: WorldService, params: dict[str, str]
) -> None:
    del service
    response = await client.get("/api/attempts", params=params, headers=appapi_headers())
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/attempts?day=2026-10-21"),
        ("GET", "/api/review?day=2026-10-21"),
        ("GET", "/api/review/prefs"),
        ("POST", "/api/review/prefs"),
        ("POST", "/api/origin"),
    ],
)
async def test_kid_is_forbidden(client: httpx.AsyncClient, service: WorldService, method: str, path: str) -> None:
    del service
    response = await client.request(method, path, json={}, headers=appapi_headers("gw-kind"))
    assert response.status_code == 403


async def test_review_lists_kids_with_minutes_per_world(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 2000, "admin": 999})
    store.book_usage(W2, DAY, {}, {}, play={"gw-kind": 700})
    response = await client.get("/api/review", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.pop("today") == _household_today()
    assert data == {
        "day": "2026-10-21",
        "kids": [
            {
                "nc_user": "gw-kind",
                "display_name": "Kind (Dev)",
                "minutes": 45,
                "limit_reached": False,
                "worlds": [
                    {"world_id": W2, "world_name": "Burg", "minutes": 12},
                    {"world_id": W1, "world_name": "Wiese", "minutes": 33},
                ],
            }
        ],
    }
    empty = await client.get("/api/review", params={"day": "2026-10-20"}, headers=appapi_headers())
    assert empty.json()["kids"] == []


async def test_review_shows_only_kids_with_rules(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """IN-03 (Owner 22.10.2026): Ein eingeladenes Gastkind ohne Regeln erscheint im Rückblick nirgends."""
    del service
    store.insert_player(PlayerRow(nc_user="gast-kind", player_name="Gast", rotation=0))
    # Auch eine ältere Zeile aus der Zeit vor IN-03 (ohne Regeln gezählt) bleibt unsichtbar.
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 600, "gast-kind": 1800})
    response = await client.get("/api/review", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert [kid["nc_user"] for kid in response.json()["kids"]] == ["gw-kind"]
    assert "gast" not in response.text.casefold()
    # Werden die Regeln entfernt, verschwindet auch das eigene Kind aus dem Rückblick.
    store.clear_child("gw-kind", keep_from=DAY)
    cleared = await client.get("/api/review", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert cleared.json()["kids"] == []


async def test_review_keeps_play_of_deleted_world(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 600})
    store.book_usage("weg123456789", DAY, {}, {}, play={"gw-kind": 1200})
    store.book_usage("weg987654321", DAY, {}, {}, play={"gw-kind": 300})
    store.delete_notify_data("weg123456789")
    store.delete_notify_data("weg987654321")
    response = await client.get("/api/review", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    kid = response.json()["kids"][0]
    assert kid["minutes"] == 35
    assert kid["worlds"] == [
        {"world_id": "", "world_name": "gelöschte Welt", "minutes": 25},
        {"world_id": W1, "world_name": "Wiese", "minutes": 10},
    ]


async def test_review_prefs_read_and_save_per_admin(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    response = await client.get("/api/review/prefs", headers=appapi_headers())
    assert response.json() == {"enabled": True, "minute": 1200}
    saved = await client.post("/api/review/prefs", json={"enabled": False, "minute": 1140}, headers=appapi_headers())
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"enabled": False, "minute": 1140}
    assert store.review_pref("admin") == (False, 1140)
    assert store.review_pref("mama") == (True, 1200)


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": True, "minute": 1440},
        {"enabled": True, "minute": -1},
        {"enabled": True},
        {"enabled": True, "minute": 600, "nc_user": "mama"},
    ],
)
async def test_review_prefs_validation(
    client: httpx.AsyncClient, service: WorldService, body: dict[str, object]
) -> None:
    del service
    response = await client.post("/api/review/prefs", json=body, headers=appapi_headers())
    assert response.status_code == 422


async def _origin(client: httpx.AsyncClient, body: dict[str, object], user: str = "admin") -> httpx.Response:
    return await client.post("/api/origin", json=body, headers=appapi_headers(user))


async def test_origin_saved(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    response = await _origin(client, {"origin": "https://cloud.example"})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "origin": "https://cloud.example",
        "proposed": "https://cloud.example",
        "saved": True,
        "confirm_needed": False,
    }
    assert store.get_meta(META_LINK_ORIGIN) == "https://cloud.example"


async def test_origin_first_wins_change_only_confirmed(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """WR-04: Ein Besuch über eine LAN-Adresse überschreibt nichts ohne Bestätigung."""
    del service
    await _origin(client, {"origin": "https://cloud.example"})
    asked = await _origin(client, {"origin": "https://neu.example"})
    assert asked.status_code == 200
    assert asked.json() == {
        "origin": "https://cloud.example",
        "proposed": "https://neu.example",
        "saved": False,
        "confirm_needed": True,
    }
    assert store.get_meta(META_LINK_ORIGIN) == "https://cloud.example"
    confirmed = await _origin(client, {"origin": "https://neu.example", "confirm": True})
    assert confirmed.json()["saved"] is True
    assert store.get_meta(META_LINK_ORIGIN) == "https://neu.example"


@pytest.mark.parametrize("confirm", [False, True])
async def test_origin_https_never_replaced_by_http(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, confirm: bool
) -> None:
    del service
    store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    response = await _origin(client, {"origin": "http://192.168.1.10", "confirm": confirm})
    assert response.status_code == 200
    assert response.json()["saved"] is False
    # Ohne Rückfrage: http ersetzt https nie, darum fragt die Seite gar nicht.
    assert response.json()["confirm_needed"] is False
    assert store.get_meta(META_LINK_ORIGIN) == "https://cloud.example"


async def test_origin_with_webroot(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    response = await _origin(client, {"origin": "https://example.org", "webroot": "/nextcloud"})
    assert response.status_code == 200, response.text
    assert store.get_meta(META_LINK_ORIGIN) == "https://example.org/nextcloud"


async def test_origin_corrupt_stored_value_is_replaced_without_confirm(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    store.set_meta(META_LINK_ORIGIN, "javascript:alert(1)")
    response = await _origin(client, {"origin": "https://cloud.example"})
    assert response.json()["saved"] is True
    assert store.get_meta(META_LINK_ORIGIN) == "https://cloud.example"


@pytest.mark.parametrize(
    "body",
    [
        {"origin": "https://cloud.example/pfad"},
        {"origin": "javascript:x"},
        {"origin": "https://u:p@cloud.example"},
        {"origin": "x" * 400},
        {"origin": "https://cloud.example", "webroot": "/../admin"},
        {"origin": "https://cloud.example", "webroot": "nextcloud"},
        {"origin": "https://cloud.example", "webroot": "/a?b"},
        {"origin": "https://cloud.example", "confirm": "yes"},
        {"origin": "https://cloud.example", "confirm": 1},
        {"origin": "https://cloud.example", "extra": 1},
        {},
    ],
)
async def test_origin_rejected(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, body: dict[str, object]
) -> None:
    del service
    response = await _origin(client, body)
    assert response.status_code == 422
    assert store.get_meta(META_LINK_ORIGIN) is None


@pytest.mark.parametrize("confirm", [False, True])
async def test_kid_cannot_set_or_confirm_origin(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, confirm: bool
) -> None:
    """Negativtest: Ein Kind setzt nichts, weder zuerst noch mit Bestätigung."""
    del service
    for stored in (None, "https://cloud.example"):
        if stored is not None:
            store.set_meta(META_LINK_ORIGIN, stored)
        response = await _origin(client, {"origin": "http://evil.example", "confirm": confirm}, user="gw-kind")
        assert response.status_code == 403
        assert store.get_meta(META_LINK_ORIGIN) == stored


async def test_origin_change_race_never_overwrites_silently(store: WorldStore) -> None:
    """Gleichzeitige Erstmeldungen: compare_and_set lässt nur eine gewinnen."""
    assert store.compare_and_set_meta(META_LINK_ORIGIN, None, "https://a.example")
    assert not store.compare_and_set_meta(META_LINK_ORIGIN, None, "https://b.example")
    assert not store.compare_and_set_meta(META_LINK_ORIGIN, "https://x.example", "https://b.example")
    assert store.get_meta(META_LINK_ORIGIN) == "https://a.example"
