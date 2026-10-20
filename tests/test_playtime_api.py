"""Spielzeit-API über ASGI: Verwalter-Sperre, Setzen/Entfernen, Validierung und sofortiger Push."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from typing import cast

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
    from datetime import date

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
    ("method", "path"),
    [("GET", ""), ("POST", "/children/gw-kind"), ("DELETE", "/children/gw-kind")],
)
async def test_child_is_forbidden(client: httpx.AsyncClient, service: WorldService, method: str, path: str) -> None:
    del service
    response = await client.request(
        method,
        f"/api/playtime{path}",
        json=_plan_body() if method == "POST" else None,
        headers=appapi_headers("gw-kind"),
    )
    assert response.status_code != 200
    assert response.status_code == 403
