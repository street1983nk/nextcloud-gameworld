"""Roles from Nextcloud groups (ROLLE-01, ROLLE-02): administration only for the group admin."""

from __future__ import annotations

import httpx
import pytest

from gameworld.access import roles
from gameworld.access.roles import Profile, RoleService, RoleUnavailableError
from gameworld.api import worlds
from tests.conftest import appapi_headers

FORBIDDEN = "Nur Eltern können Welten verwalten."
KID = "gw-kind"

ADMIN_ROUTES = [
    ("GET", "/api/worlds"),
    ("POST", "/api/worlds"),
    ("POST", "/api/worlds/abc123/start"),
    ("POST", "/api/worlds/abc123/stop"),
    ("POST", "/api/worlds/abc123/restart"),
    ("DELETE", "/api/worlds/abc123"),
    ("GET", "/api/presets"),
    ("GET", "/api/setup-check"),
]


@pytest.fixture
def no_service(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """World service and setup check must never run for non-managers."""
    calls: list[str] = []

    def forbidden_service() -> worlds.WorldService:
        calls.append("get_service")
        raise AssertionError("Dienst für Nicht-Verwalter aufgerufen")

    def forbidden_check(docker_url: str) -> object:
        calls.append(docker_url)
        raise AssertionError("Setup-Check für Nicht-Verwalter aufgerufen")

    from gameworld.api import setup_check
    from gameworld.main import APP

    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, forbidden_service)
    monkeypatch.setattr(setup_check, "run_setup_check", forbidden_check)
    return calls


@pytest.mark.parametrize(("method", "path"), ADMIN_ROUTES)
async def test_admin_routes_forbidden_for_players(
    client: httpx.AsyncClient, no_service: list[str], method: str, path: str
) -> None:
    body = {"name": "x"} if (method, path) == ("POST", "/api/worlds") else None
    response = await client.request(method, path, json=body, headers=appapi_headers(KID))
    assert response.status_code == 403
    assert response.json()["detail"] == FORBIDDEN
    assert no_service == []


async def test_admin_lists_worlds(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyService:
        async def list_worlds(self) -> list[object]:
            return []

    from gameworld.main import APP

    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, EmptyService)
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200


async def test_me_for_player(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me", headers=appapi_headers(KID))
    assert response.status_code == 200
    assert response.json() == {
        "user_id": KID,
        "display_name": "Kind (Dev)",
        "role": "spieler",
        "nc_admin": False,
        "invite_groups": [],
        "language": "de",
    }


async def test_me_for_admin(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me", headers=appapi_headers())
    assert response.status_code == 200
    assert response.json() == {
        "user_id": "admin",
        "display_name": "Admin",
        "role": "verwalter",
        "nc_admin": True,
        "invite_groups": ["admin"],
        "language": "de",
    }


@pytest.mark.parametrize("path", ["/api/worlds", "/api/me"])
async def test_lookup_error_gives_503_and_is_not_cached(
    client: httpx.AsyncClient, role_lookup_error: list[str], path: str
) -> None:
    first = await client.get(path, headers=appapi_headers())
    assert first.status_code == 503
    # Account never seen, its language is unknown: fallback en (D-25, 06-18).
    assert first.json()["detail"] == "Nextcloud is not responding right now. Please try again in a moment."
    second = await client.get(path, headers=appapi_headers())
    assert second.status_code == 503
    assert role_lookup_error == ["admin", "admin"]


async def test_unsigned_me_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me")
    assert response.status_code == 401


async def test_success_is_cached_for_30_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    now = [100.0]

    async def lookup(uid: str) -> Profile:
        calls.append(uid)
        return Profile(user_id=uid, display_name=uid, groups=("admin",))

    monkeypatch.setattr(roles.time, "monotonic", lambda: now[0])
    service = RoleService(lookup)
    assert await service.role("admin") == roles.ROLE_VERWALTER
    now[0] += 29.0
    assert await service.role("admin") == roles.ROLE_VERWALTER
    assert calls == ["admin"]
    now[0] += 2.0
    await service.role("admin")
    assert calls == ["admin", "admin"]


async def test_cache_is_per_user() -> None:
    calls: list[str] = []

    async def lookup(uid: str) -> Profile:
        calls.append(uid)
        return Profile(user_id=uid, display_name=uid, groups=("admin",) if uid == "admin" else ())

    service = RoleService(lookup)
    assert await service.role("admin") == roles.ROLE_VERWALTER
    assert await service.role(KID) == roles.ROLE_SPIELER
    assert calls == ["admin", KID]


async def test_lookup_exception_becomes_role_unavailable() -> None:
    async def lookup(uid: str) -> Profile:
        raise ValueError(uid)

    with pytest.raises(RoleUnavailableError):
        await RoleService(lookup).role("admin")
