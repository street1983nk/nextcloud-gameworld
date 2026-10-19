"""Gemeinsame Fixtures: AppAPI-Umgebung, signierte Header, ASGI-Client, Docker-Gate."""

from __future__ import annotations

import contextlib
import os
import sqlite3
from base64 import b64encode
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest

from gameworld.access.roles import Profile

APP_ID = "gameworld"
APP_VERSION = "0.1.0"
APP_CREDENTIAL = "test-secret-gameworld"
DEFAULT_DOCKER_URL = "tcp://127.0.0.1:23750"
DOCKER_HINT = "Docker-Proxy nicht erreichbar: docker compose -f scripts/dev/compose.yaml up -d"


def docker_url() -> str:
    return os.environ.get("GAMEWORLD_DOCKER_URL", DEFAULT_DOCKER_URL)


def _ping_url(url: str) -> str:
    parts = urlsplit(url)
    return f"http://{parts.hostname}:{parts.port or 2375}/_ping"


def _proxy_reachable() -> bool:
    try:
        response = httpx.get(_ping_url(docker_url()), timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and response.text.strip() == "OK"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    del config
    docker_items = [item for item in items if item.get_closest_marker("docker") is not None]
    if not docker_items or _proxy_reachable():
        return
    if os.environ.get("GAMEWORLD_REQUIRE_DOCKER") == "1":
        fail = pytest.mark.usefixtures("_docker_required")
        for item in docker_items:
            item.add_marker(fail)
        return
    skip = pytest.mark.skip(reason=DOCKER_HINT)
    for item in docker_items:
        item.add_marker(skip)


@pytest.fixture
def _docker_required() -> None:
    pytest.fail(DOCKER_HINT)


def appapi_headers(user: str = "admin") -> dict[str, str]:
    """Die Header, die AppAPI für einen Nutzer mitschickt."""
    authorization = b64encode(f"{user}:{APP_CREDENTIAL}".encode()).decode()
    return {
        "EX-APP-ID": APP_ID,
        "EX-APP-VERSION": APP_VERSION,
        "AUTHORIZATION-APP-API": authorization,
        "AA-VERSION": "32.0.0",
    }


@pytest.fixture
def app_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """AppAPI-Umgebung mit leerem Speicher; das Service-Singleton beginnt frisch."""
    monkeypatch.setenv("APP_ID", APP_ID)
    monkeypatch.setenv("APP_VERSION", APP_VERSION)
    monkeypatch.setenv("APP_SECRET", APP_CREDENTIAL)
    monkeypatch.setenv("NEXTCLOUD_URL", "http://localhost:8091")
    monkeypatch.setenv("APP_PERSISTENT_STORAGE", str(tmp_path))
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", docker_url())
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "30015-30019")

    from gameworld.access import roles
    from gameworld.api import worlds

    monkeypatch.setattr(worlds, "_service", None)
    monkeypatch.setattr(roles, "_role_service", roles.RoleService(fake_lookup))
    return tmp_path


FAKE_PROFILES: dict[str, tuple[str, tuple[str, ...]]] = {
    "admin": ("Admin", ("admin",)),
    "gw-kind": ("Kind (Dev)", ()),
}


async def fake_lookup(uid: str) -> Profile:
    """Selbstauskunft ohne Nextcloud: admin ist Verwalter, alle anderen Spieler."""
    display_name, groups = FAKE_PROFILES.get(uid, (uid, ()))
    return Profile(user_id=uid, display_name=display_name, groups=groups)


@pytest.fixture
def role_lookup_error(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Die Selbstauskunft wirft; die Liste zählt die Aufrufe."""
    del app_env
    from gameworld.access import roles

    calls: list[str] = []

    async def failing(uid: str) -> Profile:
        calls.append(uid)
        raise RuntimeError("Nextcloud weg")

    monkeypatch.setattr(roles, "_role_service", roles.RoleService(failing))
    return calls


@pytest.fixture
async def client(app_env: Path) -> AsyncIterator[httpx.AsyncClient]:
    del app_env
    from gameworld.main import APP

    transport = httpx.ASGITransport(app=APP)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


def _instance_id(storage: Path) -> str | None:
    db = storage / "gameworld.sqlite3"
    if not db.exists():
        return None
    connection = sqlite3.connect(db)
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = 'instance_id'").fetchone()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    return None if row is None else str(row[0])


@pytest.fixture
def docker_cleanup(app_env: Path) -> Iterator[None]:
    """Entfernt nach dem Test alle Container und Volumes der Test-Instanz."""
    yield
    instance = _instance_id(app_env)
    if instance is None:
        return
    import docker
    import docker.errors

    api = docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)
    try:
        for container in api.containers.list(all=True, filters={"label": [f"gameworld.instance={instance}"]}):
            name = container.name
            container.remove(force=True, v=True)
            if name:
                with contextlib.suppress(docker.errors.NotFound):
                    api.volumes.get(name).remove(force=True)
    finally:
        api.close()
