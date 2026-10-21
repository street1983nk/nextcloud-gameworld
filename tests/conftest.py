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

from gameworld.access.directory import DirectoryUser
from gameworld.access.roles import Profile
from gameworld.access.secret import PlayerSecret
from gameworld.talk.rooms import RoomMember

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

    from gameworld.access import directory, roles, secret
    from gameworld.access import service as access_service
    from gameworld.api import worlds
    from gameworld.playtime import service as playtime_service

    monkeypatch.setattr(worlds, "_service", None)
    # Drossel des Abgleichs beim Verwalter-Besuch beginnt je Test frisch.
    monkeypatch.setattr(access_service, "SYNC_STATE", access_service.SyncState())
    # Ebenso die Drossel des Verwalter-Schnappschusses (04-05).
    monkeypatch.setattr(playtime_service, "ADMINS_STATE", playtime_service.AdminsState())
    monkeypatch.setattr(roles, "_role_service", roles.RoleService(fake_lookup))
    monkeypatch.setattr(directory, "_directory", FakeDirectory())
    monkeypatch.setattr(secret, "_player_secret", StaticSecret())
    # Benachrichtigungen ohne Nextcloud; Zustand des Benachrichtigungs-Loops frisch (04.1-04).
    from gameworld.notify import loop as notify_loop
    from gameworld.notify import service as notify_service

    monkeypatch.setattr(notify_service, "_notifier", FakeNotifier())
    monkeypatch.setattr(notify_loop, "LOOP_STATE", notify_loop.LoopState())
    # Talk ohne Nextcloud; Verfügbarkeits-Cache und Dienst-Singleton frisch (04.1-05).
    from gameworld.talk import rooms as talk_rooms
    from gameworld.talk import service as talk_service

    monkeypatch.setattr(talk_rooms, "_rooms", FakeTalkRooms())
    monkeypatch.setattr(talk_service, "_talk_service", None)
    monkeypatch.setattr(talk_service, "TALK_STATE", talk_service.TalkState())
    return tmp_path


class FakeTalkRooms:
    """Talk-Räume im Speicher; ``talk``/``bots`` simulieren die Capabilities, ``error`` eine Störung.

    ``calls`` protokolliert jeden Aufruf als (Methode, handelndes Konto, Argumente).
    """

    def __init__(self) -> None:
        self.talk = True
        self.bots = True
        self.rooms: dict[str, list[RoomMember]] = {}
        self.read_only: dict[str, bool] = {}
        self.calls: list[tuple[str, str, tuple[object, ...]]] = []
        self.error: Exception | None = None
        self._next_id = 1

    def _record(self, method: str, acting_uid: str, *args: object) -> None:
        self.calls.append((method, acting_uid, args))
        if self.error is not None:
            raise self.error

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _members(self, token: str) -> list[RoomMember]:
        from gameworld.talk.rooms import RoomGoneError

        if token not in self.rooms:
            raise RoomGoneError("weg")
        return self.rooms[token]

    def methods(self) -> list[str]:
        return [call[0] for call in self.calls]

    async def available(self, acting_uid: str) -> tuple[bool, bool]:
        self._record("available", acting_uid)
        return self.talk, self.talk and self.bots

    async def create(self, acting_uid: str, name: str) -> str:
        self._record("create", acting_uid, name)
        token = f"tok{self._new_id()}"
        self.rooms[token] = [RoomMember(self._new_id(), "users", acting_uid, 1)]
        return token

    async def participants(self, acting_uid: str, token: str) -> list[RoomMember]:
        self._record("participants", acting_uid, token)
        return list(self._members(token))

    async def add_user(self, acting_uid: str, token: str, uid: str) -> None:
        self._record("add_user", acting_uid, token, uid)
        self._members(token).append(RoomMember(self._new_id(), "users", uid, 3))

    async def remove_attendee(self, acting_uid: str, token: str, attendee_id: int) -> None:
        self._record("remove_attendee", acting_uid, token, attendee_id)
        members = self._members(token)
        members[:] = [m for m in members if m.attendee_id != attendee_id]

    def _retype(self, token: str, attendee_id: int, participant_type: int) -> None:
        members = self._members(token)
        members[:] = [
            RoomMember(m.attendee_id, m.actor_type, m.actor_id, participant_type) if m.attendee_id == attendee_id else m
            for m in members
        ]

    async def promote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        self._record("promote", acting_uid, token, attendee_id)
        self._retype(token, attendee_id, 2)

    async def demote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        self._record("demote", acting_uid, token, attendee_id)
        self._retype(token, attendee_id, 3)

    async def set_read_only(self, acting_uid: str, token: str, *, on: bool) -> None:
        self._record("set_read_only", acting_uid, token, on)
        self.read_only[token] = on

    async def ensure_private(self, acting_uid: str, token: str) -> None:
        self._record("ensure_private", acting_uid, token)

    async def delete(self, acting_uid: str, token: str) -> None:
        self._record("delete", acting_uid, token)
        self.rooms.pop(token, None)


@pytest.fixture
def fake_talk(app_env: Path) -> FakeTalkRooms:
    del app_env
    from gameworld.talk import rooms as talk_rooms

    assert isinstance(talk_rooms._rooms, FakeTalkRooms)  # pyright: ignore[reportPrivateUsage]
    return talk_rooms._rooms  # pyright: ignore[reportPrivateUsage]


class FakeNotifier:
    """Sammelt Benachrichtigungen statt sie über AppAPI zu senden; ``result`` simuliert Erfolg."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, dict[str, str]], str]] = []
        self.result = True

    async def notify(self, uid: str, subject: str, message: str, params: dict[str, dict[str, str]], link: str) -> bool:
        self.calls.append((uid, subject, message, params, link))
        return self.result


@pytest.fixture
def fake_notifier(app_env: Path) -> FakeNotifier:
    del app_env
    from gameworld.notify import service as notify_service

    assert isinstance(notify_service._notifier, FakeNotifier)  # pyright: ignore[reportPrivateUsage]
    return notify_service._notifier  # pyright: ignore[reportPrivateUsage]


# Geheimnis der Tests; das echte liegt nur in Nextcloud (appconfig_ex).
TEST_SECRET = bytes(range(32))


class FakeDirectory:
    """Nextcloud-Konten ohne Nextcloud: gw-kind aktiv, gw-aus deaktiviert, alles andere fehlt.

    gw-kind2 und admin sind aktiv (Spielzeit-e2e: zweites Kind als Positivkontrolle,
    admin für Welt-Fenster ab 04-05). Gruppe familie: gw-kind und gw-aus, Gruppe admin:
    admin (Verwalter-Schnappschuss, 04-05); im Test änderbar (groups). ``lock_held``
    hält für jede Gruppenabfrage fest, ob die Welt-Sperre dabei belegt war (Sperrregel:
    Nextcloud-Aufrufe nie unter mutation()).
    """

    def __init__(self) -> None:
        self.users: dict[str, tuple[str, bool]] = {
            "gw-kind": ("Kind (Dev)", True),
            "gw-kind2": ("Kind 2 (Dev)", True),
            "gw-aus": ("Aus (Dev)", False),
            "admin": ("Admin (Dev)", True),
        }
        self.groups: dict[str, list[str]] = {"familie": ["gw-kind", "gw-aus"], "admin": ["admin"]}
        self.lock_held: list[bool] = []
        self.calls: list[tuple[str, str]] = []
        self.group_calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        self.calls.append((acting_uid, uid))
        if self.error is not None:
            raise self.error
        entry = self.users.get(uid)
        return None if entry is None else DirectoryUser(uid=uid, display_name=entry[0], enabled=entry[1])

    async def group_members(self, acting_uid: str, gid: str) -> list[str] | None:
        from gameworld.worlds import service as world_service

        self.group_calls.append((acting_uid, gid))
        self.lock_held.append(world_service._LOCK.locked())  # pyright: ignore[reportPrivateUsage]
        if self.error is not None:
            raise self.error
        members = self.groups.get(gid)
        return None if members is None else list(members)

    async def group_exists(self, acting_uid: str, gid: str) -> bool:
        return await self.group_members(acting_uid, gid) is not None


class StaticSecret(PlayerSecret):
    """Festes Geheimnis statt appconfig_ex; error simuliert eine Störung."""

    def __init__(self, value: bytes = TEST_SECRET) -> None:
        super().__init__()
        self.value = value
        self.error: Exception | None = None

    async def get(self) -> bytes:
        if self.error is not None:
            raise self.error
        return self.value


@pytest.fixture
def fake_directory(app_env: Path) -> FakeDirectory:
    del app_env
    from gameworld.access import directory

    assert isinstance(directory._directory, FakeDirectory)  # pyright: ignore[reportPrivateUsage]
    return directory._directory  # pyright: ignore[reportPrivateUsage]


@pytest.fixture
def fake_secret(app_env: Path) -> StaticSecret:
    del app_env
    from gameworld.access import secret

    assert isinstance(secret._player_secret, StaticSecret)  # pyright: ignore[reportPrivateUsage]
    return secret._player_secret  # pyright: ignore[reportPrivateUsage]


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
    # Offene Talk-Hooks (verfolgte Tasks) vor dem Schließen der Schleife abarbeiten.
    from gameworld.talk import service as talk_service

    pending = talk_service._talk_service  # pyright: ignore[reportPrivateUsage]
    if pending is not None:
        await pending.drain()


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
