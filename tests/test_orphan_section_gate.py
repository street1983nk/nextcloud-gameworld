"""B3 switch (06-09): /api/me nc_admin and the server block of the orphan routes agree.

Independent of tests/test_orphans.py: own spy instead of a Docker dummy. The UI
shows OrphanSection only for nc_admin === true (frontend/tests/orphans.check.mjs);
this proves that exactly these accounts may use the routes and all others get
403, without the provisioner ever being touched.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from gameworld.access import roles
from gameworld.access.roles import ADMIN_GROUP, ROLE_SPIELER, ROLE_VERWALTER, RoleService
from gameworld.api import worlds
from gameworld.provisioner.client import Orphans
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers, fake_lookup

CONTAINER_ID = "c" * 64
VOLUME = "gameworld-f00dcafe-abc"


class SpyProvisioner:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def list_orphans(self, owned: set[str]) -> Orphans:
        del owned
        self.calls.append("list")
        return Orphans(containers=[], volumes=[])

    def remove_orphan_container(self, cid: str) -> None:
        self.calls.append(f"container:{cid}")

    def remove_orphan_volume(self, name: str, owned_volumes: set[str]) -> None:
        del owned_volumes
        self.calls.append(f"volume:{name}")


@pytest.fixture
def spy(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> SpyProvisioner:
    from gameworld.main import APP

    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    provisioner = SpyProvisioner()
    service: Any = SimpleNamespace(store=store, provisioner=provisioner)
    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, lambda: service)

    async def teachers() -> frozenset[str]:
        return frozenset({ADMIN_GROUP, "lehrkraefte"})

    monkeypatch.setattr(roles, "_role_service", RoleService(fake_lookup, teachers))
    return provisioner


ROUTES: tuple[tuple[str, str, dict[str, str] | None], ...] = (
    ("GET", "/api/admin/orphans", None),
    ("POST", "/api/admin/orphans/container/remove", {"id": CONTAINER_ID}),
    ("POST", "/api/admin/orphans/volume/remove", {"name": VOLUME}),
)


async def _call(client: httpx.AsyncClient, method: str, path: str, body: dict[str, str] | None, user: str) -> int:
    if method == "GET":
        return (await client.get(path, headers=appapi_headers(user))).status_code
    return (await client.post(path, json=body, headers=appapi_headers(user))).status_code


@pytest.mark.parametrize(("user", "role"), [("gw-lehrer", ROLE_VERWALTER), ("gw-kind", ROLE_SPIELER)])
async def test_non_admin_sees_no_section_and_gets_403(
    client: httpx.AsyncClient, spy: SpyProvisioner, user: str, role: str
) -> None:
    me = (await client.get("/api/me", headers=appapi_headers(user))).json()
    assert me["role"] == role
    # The UI switch: without nc_admin === true OrphanSection is not mounted.
    assert me["nc_admin"] is False
    for method, path, body in ROUTES:
        assert await _call(client, method, path, body, user) == 403, path
    assert spy.calls == []


async def test_admin_positive_control(client: httpx.AsyncClient, spy: SpyProvisioner) -> None:
    me = (await client.get("/api/me", headers=appapi_headers("admin"))).json()
    assert me["nc_admin"] is True
    for method, path, body in ROUTES:
        assert await _call(client, method, path, body, "admin") == 200, path
    assert spy.calls == ["list", f"container:{CONTAINER_ID}", "list", f"volume:{VOLUME}", "list"]
