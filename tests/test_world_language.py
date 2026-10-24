"""World language of the mod texts (D-27, 06-22): schema 9, account-language default, switch route."""

from __future__ import annotations

import io
import pathlib
import sqlite3
import tarfile
from pathlib import Path
from typing import Any, cast

import httpx
import pytest

from gameworld.access import roles
from gameworld.access.roles import RoleService
from gameworld.api import worlds as worlds_api
from gameworld.config import load_settings
from gameworld.provisioner import access_mod, time_mod
from gameworld.provisioner.client import DockerProvisioner, WorldNotFoundError
from gameworld.worlds import service as service_module
from gameworld.worlds.service import MSG_WORLD_LANGUAGE_UNSUPPORTED, WorldService
from gameworld.worlds.store import SCHEMA_VERSION, WorldRow, WorldStore
from tests import conftest
from tests.conftest import appapi_headers, fake_lookup
from tests.test_service_lifecycle import FakeProvisioner

KID = "gw-kind"
UNKNOWN = "bbbbbbbbbbbb"


def _row(world_id: str, port: int, **extra: Any) -> WorldRow:
    return WorldRow(
        id=world_id,
        name="Sprachwelt",
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-24T10:00:00+00:00",
        **extra,
    )


def _columns(db: pathlib.Path) -> dict[str, tuple[str, int, str | None]]:
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("PRAGMA table_info(worlds)").fetchall()
    finally:
        connection.close()
    return {str(row[1]): (str(row[2]), int(row[3]), row[4]) for row in rows}


def _version(db: pathlib.Path) -> str:
    connection = sqlite3.connect(db)
    try:
        return str(connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
    finally:
        connection.close()


# --- schema 9 ----------------------------------------------------------------------------------


def _schema_8_file(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    store.insert_world(_row("w1", 30001))
    connection = sqlite3.connect(db)
    try:
        connection.execute("ALTER TABLE worlds DROP COLUMN language")
        connection.execute("ALTER TABLE worlds DROP COLUMN launched_language")
        connection.execute("UPDATE meta SET value = '8' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()
    return db


def test_fresh_db_is_schema_9_with_language_columns(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "gameworld.sqlite3"
    WorldStore(db).migrate()
    assert SCHEMA_VERSION == "9"
    assert _version(db) == "9"
    columns = _columns(db)
    assert columns["language"] == ("TEXT", 1, "'de'")
    assert columns["launched_language"] == ("TEXT", 0, None)


def test_schema_8_is_migrated_to_9_existing_worlds_stay_german(tmp_path: pathlib.Path) -> None:
    db = _schema_8_file(tmp_path)
    assert _version(db) == "8"
    assert "language" not in _columns(db)
    store = WorldStore(db)
    store.migrate()
    assert _version(db) == "9"
    row = store.get_world("w1")
    assert row is not None
    assert (row.language, row.launched_language) == ("de", None)
    # Idempotent: a second run changes nothing and does not fail on existing columns.
    store.migrate()
    assert _version(db) == "9"
    assert store.get_world("w1") == row


def test_set_world_language_in_the_store(tmp_path: pathlib.Path) -> None:
    store = WorldStore(tmp_path / "gameworld.sqlite3")
    store.migrate()
    store.insert_world(_row("w1", 30001))
    assert store.set_world_language("w1", "fr") is True
    row = store.get_world("w1")
    assert row is not None
    assert row.language == "fr"
    assert store.set_world_language("nope", "fr") is False


# --- API ---------------------------------------------------------------------------------------


@pytest.fixture
def lang(monkeypatch: pytest.MonkeyPatch) -> Any:
    def put(uid: str, language: str) -> None:
        monkeypatch.setitem(conftest.FAKE_LANGUAGES, uid, language)
        monkeypatch.setattr(roles, "_role_service", RoleService(fake_lookup))

    return put


class Env:
    def __init__(self, store: WorldStore, fake: FakeProvisioner, payload_languages: list[object]) -> None:
        self.store = store
        self.fake = fake
        self.payload_languages = payload_languages


@pytest.fixture
def env(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    from gameworld.main import APP

    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    fake = FakeProvisioner()
    service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, worlds_api.get_service, lambda: service)
    payload_languages: list[object] = []
    real = service_module.build_world_payload

    def recording(*args: Any, **kwargs: Any) -> Any:
        payload_languages.append(kwargs.get("language"))
        return real(*args, **kwargs)

    monkeypatch.setattr(service_module, "build_world_payload", recording)
    return Env(store, fake, payload_languages)


def _mods(archive: bytes) -> dict[str, bytes]:
    """init.lua of every mod in a world-files tar, by mod directory."""
    result: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.name.endswith("/init.lua"):
                extracted = tar.extractfile(member)
                assert extracted is not None
                result[member.name.split("/")[-2]] = extracted.read()
    return result


async def _create(client: httpx.AsyncClient, uid: str = "admin") -> dict[str, Any]:
    response = await client.post("/api/worlds", json={"name": "Sprachwelt"}, headers=appapi_headers(uid))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("language", ["en", "fr", "de"])
async def test_new_world_gets_the_account_language(
    client: httpx.AsyncClient, env: Env, lang: Any, language: str
) -> None:
    lang("admin", language)
    body = await _create(client)
    assert body["language"] == language
    assert body["language_restart_needed"] is False
    row = env.store.get_world(body["id"])
    assert row is not None
    assert (row.language, row.launched_language) == (language, language)
    # Payload and the files written before the start both carry the language.
    assert env.payload_languages == [language]
    mods = _mods(env.fake.written[-1][1])
    assert mods[access_mod.MOD_NAME] == access_mod.mod_init_lua(language).encode()
    assert mods[time_mod.MOD_NAME] == time_mod.mod_init_lua(language).encode()


async def test_new_world_for_a_default_account_is_german(client: httpx.AsyncClient, env: Env) -> None:
    """The fake admin has no explicit language (de): German mods, byte-identical to before."""
    body = await _create(client)
    assert body["language"] == "de"
    mods = _mods(env.fake.written[-1][1])
    assert mods[access_mod.MOD_NAME] == access_mod.MOD_INIT_LUA.encode()
    assert mods[time_mod.MOD_NAME] == time_mod.MOD_INIT_LUA.encode()


async def test_create_body_with_language_is_refused(client: httpx.AsyncClient, env: Env) -> None:
    """The request body stays unchanged: the language comes from the account, never from the body."""
    del env
    response = await client.post("/api/worlds", json={"name": "Sprachwelt", "language": "fr"}, headers=appapi_headers())
    assert response.status_code == 422


async def test_switch_language_running_world_needs_restart(client: httpx.AsyncClient, env: Env) -> None:
    body = await _create(client)
    world_id = body["id"]
    response = await client.post(f"/api/worlds/{world_id}/language", json={"language": "fr"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    switched = response.json()
    assert switched["language"] == "fr"
    assert switched["status"] == "running"
    assert switched["language_restart_needed"] is True
    # No automatic restart: the switch itself never touches the container (T-06-88).
    starts = list(env.fake.started)
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    assert listing[0]["language_restart_needed"] is True
    assert env.fake.started == starts
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    assert restarted.json()["language_restart_needed"] is False
    row = env.store.get_world(world_id)
    assert row is not None
    assert row.launched_language == "fr"
    mods = _mods(env.fake.written[-1][1])
    assert mods[time_mod.MOD_NAME] == time_mod.mod_init_lua("fr").encode()


async def test_switch_back_before_restart_clears_the_hint(client: httpx.AsyncClient, env: Env) -> None:
    world_id = (await _create(client))["id"]
    await client.post(f"/api/worlds/{world_id}/language", json={"language": "en"}, headers=appapi_headers())
    back = await client.post(f"/api/worlds/{world_id}/language", json={"language": "de"}, headers=appapi_headers())
    assert back.json()["language_restart_needed"] is False
    del env


async def test_stopped_world_needs_no_restart(client: httpx.AsyncClient, env: Env) -> None:
    world_id = (await _create(client))["id"]
    stopped = await client.post(f"/api/worlds/{world_id}/stop", headers=appapi_headers())
    assert stopped.status_code == 200
    switched = await client.post(f"/api/worlds/{world_id}/language", json={"language": "en"}, headers=appapi_headers())
    assert switched.json()["status"] != "running"
    assert switched.json()["language_restart_needed"] is False
    started = await client.post(f"/api/worlds/{world_id}/start", headers=appapi_headers())
    assert started.json()["language"] == "en"
    assert started.json()["language_restart_needed"] is False
    assert _mods(env.fake.written[-1][1])[access_mod.MOD_NAME] == access_mod.mod_init_lua("en").encode()


async def test_world_running_before_schema_9_counts_as_german(client: httpx.AsyncClient, env: Env) -> None:
    """launched_language NULL (started before the update) means German mods are running."""
    env.store.insert_world(_row("aaaaaaaaaaa1", 30015))
    env.fake.containers["aaaaaaaaaaa1"] = (30015, "running")
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    assert (listing[0]["status"], listing[0]["language"], listing[0]["language_restart_needed"]) == (
        "running",
        "de",
        False,
    )
    switched = await client.post("/api/worlds/aaaaaaaaaaa1/language", json={"language": "en"}, headers=appapi_headers())
    assert switched.json()["language_restart_needed"] is True


@pytest.mark.parametrize("value", ["xx", "", "DE", "en-US", None, 1])
async def test_invalid_language_is_422(client: httpx.AsyncClient, env: Env, value: object) -> None:
    world_id = (await _create(client))["id"]
    response = await client.post(f"/api/worlds/{world_id}/language", json={"language": value}, headers=appapi_headers())
    assert response.status_code == 422
    row = env.store.get_world(world_id)
    assert row is not None
    assert row.language == "de"


async def test_extra_field_is_422(client: httpx.AsyncClient, env: Env) -> None:
    world_id = (await _create(client))["id"]
    response = await client.post(
        f"/api/worlds/{world_id}/language", json={"language": "fr", "restart": True}, headers=appapi_headers()
    )
    assert response.status_code == 422
    del env


async def test_player_gets_403(client: httpx.AsyncClient, env: Env) -> None:
    world_id = (await _create(client))["id"]
    response = await client.post(
        f"/api/worlds/{world_id}/language", json={"language": "fr"}, headers=appapi_headers(KID)
    )
    assert response.status_code == 403
    row = env.store.get_world(world_id)
    assert row is not None
    assert row.language == "de"


async def test_unknown_world_is_404(client: httpx.AsyncClient, env: Env, lang: Any) -> None:
    del env
    response = await client.post(f"/api/worlds/{UNKNOWN}/language", json={"language": "fr"}, headers=appapi_headers())
    assert response.status_code == 404
    lang("admin", "en")
    english = await client.post(f"/api/worlds/{UNKNOWN}/language", json={"language": "fr"}, headers=appapi_headers())
    assert english.json() == {"detail": "This world does not exist (anymore)."}


async def test_put_is_not_offered(client: httpx.AsyncClient, env: Env) -> None:
    """AppAPI allows only GET, POST and DELETE under /api; the route is POST."""
    world_id = (await _create(client))["id"]
    response = await client.put(f"/api/worlds/{world_id}/language", json={"language": "fr"}, headers=appapi_headers())
    assert response.status_code == 405
    del env


# --- fail safe: a stored value outside de/en/fr ------------------------------------------------


async def test_stored_garbage_gives_german_mods_and_api(client: httpx.AsyncClient, env: Env) -> None:
    world_id = (await _create(client))["id"]
    env.store.update_world(world_id, language='xx"); os.exit() --')
    listing = (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]
    assert listing[0]["language"] == "de"
    assert listing[0]["language_restart_needed"] is False
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200
    assert restarted.json()["language"] == "de"
    mods = _mods(env.fake.written[-1][1])
    assert mods[access_mod.MOD_NAME] == access_mod.MOD_INIT_LUA.encode()
    assert mods[time_mod.MOD_NAME] == time_mod.MOD_INIT_LUA.encode()
    for content in mods.values():
        assert b"os.exit" not in content


# --- service level -----------------------------------------------------------------------------


async def test_service_refuses_unsupported_language(app_env: Path) -> None:
    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    with pytest.raises(ValueError, match=MSG_WORLD_LANGUAGE_UNSUPPORTED):
        await service.set_world_language(UNKNOWN, "xx")
    with pytest.raises(WorldNotFoundError):
        await service.set_world_language(UNKNOWN, "fr")


async def test_service_create_with_unsupported_language_is_german(app_env: Path) -> None:
    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    view = await service.create_world("Sprachwelt", language="xx")
    assert view.language == "de"
    row = store.get_world(view.id)
    assert row is not None
    assert row.language == "de"
