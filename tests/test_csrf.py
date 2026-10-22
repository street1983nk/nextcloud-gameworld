"""JSON-Pflicht für zustandsändernde Anfragen (IN-08): Cross-Site-Formulare kommen nicht durch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.csrf import MSG_FOREIGN, MSG_NOT_JSON, refusal
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.notify.loop import META_LINK_ORIGIN
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.test_pause_api import _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"

FORM = "application/x-www-form-urlencoded"
CROSS = {"Origin": "http://evil.example", "Referer": "http://evil.example/", "Sec-Fetch-Site": "cross-site"}


def _scope(method: str, user: str, headers: dict[str, str]) -> dict[str, object]:
    raw = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
    return {"type": "http", "method": method, "username": user, "headers": raw}


@pytest.mark.parametrize(
    ("method", "user", "headers", "expected"),
    [
        # Positivkontrollen: das eigene Frontend und AppAPI selbst.
        ("POST", "admin", {"content-type": "application/json"}, None),
        ("POST", "admin", {"content-type": "application/json; charset=utf-8"}, None),
        ("DELETE", "admin", {"content-type": "APPLICATION/JSON"}, None),
        ("POST", "admin", {"content-type": "application/json", "sec-fetch-site": "same-origin"}, None),
        ("POST", "admin", {"content-type": "application/json", "sec-fetch-site": "none"}, None),
        ("POST", "", {"content-type": FORM}, None),
        ("PUT", "", {}, None),
        ("GET", "admin", {"content-type": FORM, "sec-fetch-site": "cross-site"}, None),
        ("HEAD", "admin", {}, None),
        # Manipulierte Eingaben: alles, was ein Formular oder eine fremde Seite schicken kann.
        ("POST", "admin", {}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": FORM}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": "multipart/form-data; boundary=x"}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": "text/plain"}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": "application/jsonx"}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": "text/plain; application/json"}, MSG_NOT_JSON),
        ("DELETE", "gw-kind", {}, MSG_NOT_JSON),
        ("PATCH", "admin", {"content-type": FORM}, MSG_NOT_JSON),
        ("POST", "admin", {"content-type": "application/json", "sec-fetch-site": "cross-site"}, MSG_FOREIGN),
        ("POST", "admin", {"content-type": "application/json", "sec-fetch-site": "Same-Site"}, MSG_FOREIGN),
    ],
)
def test_refusal_rule(method: str, user: str, headers: dict[str, str], expected: str | None) -> None:
    assert refusal(_scope(method, user, headers)) == expected


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    return world_store


@pytest.fixture
def service(store: WorldStore, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


def _headers(user: str, content_type: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    return {**appapi_headers(user), "Content-Type": content_type, **(extra or {})}


async def test_cross_site_form_cannot_end_running_pause(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """Der Angriff aus dem Dev-Stack-Beleg: Formular-POST auf /api/pause/end mit Sitzung des Verwalters."""
    del service
    started = await client.post("/api/pause", json={"minutes": 30}, headers=appapi_headers())
    assert started.status_code == 200
    for content_type, extra in ((FORM, CROSS), ("text/plain", CROSS), (FORM, None), ("", None)):
        attack = await client.post("/api/pause/end", content=b"", headers=_headers("admin", content_type, extra))
        assert attack.status_code == 403, (content_type, attack.text)
        assert store.get_pause() is not None
    # JSON, aber von einer fremden Seite (Sec-Fetch-Site): ebenfalls 403.
    foreign = await client.post("/api/pause/end", json={}, headers={**appapi_headers(), **CROSS})
    assert foreign.status_code == 403
    assert store.get_pause() is not None
    # Positivkontrolle: dieselbe Anfrage wie das Frontend beendet die Pause.
    ok = await client.post("/api/pause/end", json={}, headers=appapi_headers())
    assert ok.status_code == 200
    assert store.get_pause() is None


async def test_form_post_with_json_body_is_refused_before_parsing(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    """text/plain mit JSON-Text (der klassische Formular-Trick) ändert die Link-Adresse nicht."""
    del service
    body = json.dumps({"origin": "http://evil.example", "confirm": True}).encode()
    response = await client.post("/api/origin", content=body, headers=_headers("admin", "text/plain", CROSS))
    assert response.status_code == 403
    assert store.get_meta(META_LINK_ORIGIN) is None


async def test_cross_site_delete_cannot_remove_world(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore
) -> None:
    del service
    response = await client.delete(f"/api/worlds/{W1}", headers=_headers("admin", FORM, CROSS))
    assert response.status_code == 403
    assert store.get_world(W1) is not None


async def test_kid_is_refused_either_way(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    for content_type in (FORM, "application/json"):
        response = await client.post(
            "/api/pause", content=b'{"minutes": 15}', headers=_headers("gw-kind", content_type)
        )
        assert response.status_code == 403
    assert store.get_pause() is None


async def test_appapi_calls_without_user_are_not_affected(client: httpx.AsyncClient) -> None:
    """AppAPI selbst (talk_proxy ohne Nutzer) schickt kein JSON-Pflichtfeld mit; das bleibt erlaubt."""
    response = await client.post("/talk/bot", content=b"x", headers=_headers("", "text/plain"))
    assert response.status_code == 200


async def test_reads_are_not_affected(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.get("/api/pause", headers=_headers("admin", FORM, CROSS))
    assert response.status_code == 200
