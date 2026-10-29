"""Talk hooks in world and invitation routes as well as GET /api/talk and the read-only switch (04.1-05)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.talk.rooms import TalkUnavailableError
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import FakeTalkRooms, appapi_headers
from tests.test_pause_api import _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
UNKNOWN = "bbbbbbbbbbbb"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    return world_store


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    return provisioner


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


async def _drain(store: WorldStore) -> None:
    await get_talk_service(store).drain()


async def test_create_world_gets_room(client: httpx.AsyncClient, service: WorldService, store: WorldStore) -> None:
    del service
    created = await client.post("/api/worlds", json={"name": "Insel"}, headers=appapi_headers())
    assert created.status_code == 201, created.text
    await _drain(store)
    row = store.talk_room(created.json()["id"])
    assert row is not None
    assert row.owner_uid == "admin"


async def test_without_talk_routes_answer_as_before(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    del service
    fake_talk.talk = False
    created = await client.post("/api/worlds", json={"name": "Insel"}, headers=appapi_headers())
    assert created.status_code == 201
    invited = await client.post(
        f"/api/worlds/{W1}/invites", json={"kind": "user", "target": "gw-kind"}, headers=appapi_headers()
    )
    assert invited.status_code == 200
    await _drain(store)
    assert store.list_talk_rooms() == []
    status = await client.get("/api/talk", headers=appapi_headers())
    assert status.status_code == 200
    assert status.json()["available"] is False


async def test_talk_failure_never_breaks_world_routes(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    del service
    fake_talk.error = RuntimeError("Talk kaputt")
    created = await client.post("/api/worlds", json={"name": "Insel"}, headers=appapi_headers())
    assert created.status_code == 201
    deleted = await client.delete(f"/api/worlds/{W1}", headers=appapi_headers())
    assert deleted.status_code == 204
    await _drain(store)


async def test_delete_world_deletes_room(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    talk = get_talk_service(service.store)
    await talk.ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    response = await client.delete(f"/api/worlds/{W1}", headers=appapi_headers())
    assert response.status_code == 204
    await _drain(store)
    assert ("delete", "admin", (row.token,)) in fake_talk.calls
    assert store.talk_room(W1) is None


async def test_invite_and_remove_sync_room(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await get_talk_service(service.store).ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    body = {"kind": "user", "target": "gw-kind"}
    invited = await client.post(f"/api/worlds/{W1}/invites", json=body, headers=appapi_headers())
    assert invited.status_code == 200, invited.text
    await _drain(store)
    assert ("add_user", "admin", (row.token, "gw-kind")) in fake_talk.calls
    removed = await client.post(f"/api/worlds/{W1}/invites/remove", json=body, headers=appapi_headers())
    assert removed.status_code == 200
    await _drain(store)
    assert "remove_attendee" in fake_talk.methods()
    assert {m.actor_id for m in fake_talk.rooms[row.token]} == {"admin"}


async def test_group_invite_counts_via_world_access(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await get_talk_service(service.store).ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    response = await client.post(
        f"/api/worlds/{W1}/invites", json={"kind": "group", "target": "familie"}, headers=appapi_headers()
    )
    assert response.status_code == 200
    await _drain(store)
    members = {m.actor_id: m.actor_type for m in fake_talk.rooms[row.token]}
    # Group familie: gw-kind active (gw-aus deactivated, without access); never as a Talk group.
    assert members == {"admin": "users", "gw-kind": "users"}


async def test_talk_status_and_read_only(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await get_talk_service(service.store).ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    status = await client.get("/api/talk", headers=appapi_headers())
    assert status.status_code == 200
    assert status.json() == {
        "available": True,
        "bots": True,
        "worlds": [
            {
                "world_id": W1,
                "world_name": "Wiese",
                "has_room": True,
                "read_only": False,
                "owner_not_admin": False,
                "token": row.token,
                # Only filled when the room owner is no longer a manager (D-27).
                "owner_display": None,
                # Only filled in the lock case (D-16).
                "orphaned_token": None,
            }
        ],
    }
    on = await client.post(f"/api/worlds/{W1}/talk/read-only", headers=appapi_headers())
    assert on.status_code == 200
    assert on.json() == {"world_id": W1, "read_only": True, "applied": True}
    assert fake_talk.read_only[row.token] is True
    off = await client.delete(f"/api/worlds/{W1}/talk/read-only", headers=appapi_headers())
    assert off.json() == {"world_id": W1, "read_only": False, "applied": True}
    assert fake_talk.read_only[row.token] is False


async def test_read_only_unknown_world_is_404(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post(f"/api/worlds/{UNKNOWN}/talk/read-only", headers=appapi_headers())
    assert response.status_code == 404


async def test_read_only_without_room_is_409(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post(f"/api/worlds/{W1}/talk/read-only", headers=appapi_headers())
    assert response.status_code == 409


@pytest.mark.parametrize("world_id", ["xyz", "..etc", "0123456789AB"])
async def test_read_only_validates_world_id(client: httpx.AsyncClient, service: WorldService, world_id: str) -> None:
    del service
    response = await client.post(f"/api/worlds/{world_id}/talk/read-only", headers=appapi_headers())
    assert response.status_code in {404, 422}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/talk"),
        ("POST", f"/api/worlds/{W1}/talk/read-only"),
        ("DELETE", f"/api/worlds/{W1}/talk/read-only"),
        ("POST", f"/api/worlds/{W1}/talk/recreate"),
    ],
)
async def test_kid_is_forbidden(client: httpx.AsyncClient, service: WorldService, method: str, path: str) -> None:
    del service
    response = await client.request(method, path, headers=appapi_headers("gw-kind"))
    assert response.status_code == 403


# Recreate the room (06-06, D-19)


async def test_recreate_gives_new_room_without_ex_admin(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "gw-alt"]))
    await get_talk_service(service.store).ensure_room(W1, "gw-alt")
    old = store.talk_room(W1)
    assert old is not None
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    await get_talk_service(service.store).reconcile_all("admin")
    before = await client.get("/api/talk", headers=appapi_headers())
    line = before.json()["worlds"][0]
    assert (line["owner_not_admin"], line["owner_display"], line["orphaned_token"]) == (True, "gw-alt", None)
    response = await client.post(f"/api/worlds/{W1}/talk/recreate", headers=appapi_headers())
    assert response.status_code == 200, response.text
    body = response.json()
    new = store.talk_room(W1)
    assert new is not None
    assert new.token != old.token
    assert body == {
        "world_id": W1,
        "world_name": "Wiese",
        "has_room": True,
        "read_only": False,
        "owner_not_admin": False,
        "token": new.token,
        "owner_display": None,
        "orphaned_token": None,
    }
    assert old.token not in fake_talk.rooms
    assert "gw-alt" not in {m.actor_id for m in fake_talk.rooms[new.token]}


async def test_recreate_unknown_world_is_404(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await client.post(f"/api/worlds/{UNKNOWN}/talk/recreate", headers=appapi_headers())
    assert response.status_code == 404


async def test_recreate_without_room_is_409(
    client: httpx.AsyncClient, service: WorldService, fake_talk: FakeTalkRooms
) -> None:
    del service
    response = await client.post(f"/api/worlds/{W1}/talk/recreate", headers=appapi_headers())
    assert response.status_code == 409
    assert "create" not in fake_talk.methods()


async def test_recreate_talk_down_is_503_and_keeps_room(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await get_talk_service(service.store).ensure_room(W1, "admin")
    old = store.talk_room(W1)
    assert old is not None
    fake_talk.error = TalkUnavailableError("weg")
    response = await client.post(f"/api/worlds/{W1}/talk/recreate", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json()["detail"] == "Talk antwortet gerade nicht. Bitte gleich noch einmal versuchen."
    assert store.talk_room(W1) == old
    assert old.token in fake_talk.rooms


async def test_kid_cannot_recreate_and_room_stays(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await get_talk_service(service.store).ensure_room(W1, "admin")
    old = store.talk_room(W1)
    assert old is not None
    fake_talk.calls.clear()
    response = await client.post(f"/api/worlds/{W1}/talk/recreate", headers=appapi_headers("gw-kind"))
    assert response.status_code == 403
    assert store.talk_room(W1) == old
    assert fake_talk.calls == []
