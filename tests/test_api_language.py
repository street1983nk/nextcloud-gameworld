"""Server texts in the account language at the API boundary (D-25).

German accounts get exactly the previous texts; en and fr accounts get the
translation. Positive controls run the same request as a German account.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, cast

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import AfterValidator, BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from gameworld.access import roles
from gameworld.access.roles import Profile, RoleService, UserDep
from gameworld.api import csrf as csrf_api
from gameworld.api import me as me_api
from gameworld.api import setup_check as setup_check_api
from gameworld.api import worlds as worlds_api
from gameworld.api.language import LangDep, install_language_handlers
from gameworld.backup import service as backup_service
from gameworld.config import load_settings
from gameworld.provisioner import presets
from gameworld.provisioner import setup_check as setup_texts
from gameworld.provisioner.client import DockerProvisioner
from gameworld.provisioner.setup_check import CheckItem, SetupCheckResult
from gameworld.worlds import service as world_service
from gameworld.worlds import status as status_texts
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests import conftest
from tests.conftest import appapi_headers, fake_lookup
from tests.test_service_lifecycle import FakeProvisioner

KID = "gw-kind"


@pytest.fixture
def lang(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Sets the account language of single fake accounts for one test."""

    def put(uid: str, language: str) -> None:
        monkeypatch.setitem(conftest.FAKE_LANGUAGES, uid, language)
        # A fresh role service: the previous one remembers profile and language for 30 s.
        monkeypatch.setattr(roles, "_role_service", RoleService(fake_lookup))

    return put


# --- /api/me and the role texts -------------------------------------------------------------


@pytest.mark.parametrize(("language", "expected"), [("en", "en"), ("fr", "fr"), ("de", "de")])
async def test_me_reports_the_account_language(
    client: httpx.AsyncClient, lang: Any, language: str, expected: str
) -> None:
    lang(KID, language)
    response = await client.get("/api/me", headers=appapi_headers(KID))
    assert response.status_code == 200
    assert response.json()["language"] == expected


async def test_me_without_language_is_german(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/me", headers=appapi_headers())
    assert response.json()["language"] == "de"


async def test_forbidden_in_english_for_an_english_kid(client: httpx.AsyncClient, lang: Any) -> None:
    lang(KID, "en")
    response = await client.get("/api/worlds", headers=appapi_headers(KID))
    assert response.status_code == 403
    assert response.json() == {"detail": "Only parents can manage worlds."}


async def test_forbidden_in_french_for_a_french_kid(client: httpx.AsyncClient, lang: Any) -> None:
    lang(KID, "fr")
    response = await client.get("/api/worlds", headers=appapi_headers(KID))
    assert response.status_code == 403
    assert response.json() == {"detail": "Seuls les parents peuvent gérer les mondes."}


async def test_forbidden_stays_german_for_a_german_kid(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/worlds", headers=appapi_headers(KID))
    assert response.status_code == 403
    assert response.json() == {"detail": roles.MSG_FORBIDDEN}


async def test_nc_admin_only_in_english(client: httpx.AsyncClient, lang: Any) -> None:
    lang("gw-lehrer", "en")
    response = await client.get("/api/admin/verwalter-groups", headers=appapi_headers("gw-lehrer"))
    assert response.status_code == 403
    assert response.json() == {"detail": "Only Nextcloud admins can change this."}


# --- language source and failure behavior ---------------------------------------------------------


async def test_nc_profile_normalizes_the_nextcloud_language(monkeypatch: pytest.MonkeyPatch) -> None:
    info = SimpleNamespace(display_name="Kind", groups=["familie"], subadmin=[], language="fr_FR")

    class FakeUsers:
        async def get_user(self) -> SimpleNamespace:
            return info

    @contextlib.asynccontextmanager
    async def fake_nc_as(uid: str) -> AsyncIterator[SimpleNamespace]:
        del uid
        yield SimpleNamespace(users=FakeUsers())

    monkeypatch.setattr(roles, "nc_as", fake_nc_as)
    assert (await roles.nc_profile(KID)).language == "fr"
    info.language = "pt_BR"
    assert (await roles.nc_profile(KID)).language == "en"
    info.language = ""
    assert (await roles.nc_profile(KID)).language == "en"


class Switch:
    """Lookup that answers until ``down`` is set, then raises; ``calls`` counts the calls."""

    def __init__(self, language: str) -> None:
        self.language = language
        self.down = False
        self.calls = 0

    async def __call__(self, uid: str) -> Profile:
        self.calls += 1
        if self.down:
            raise RuntimeError("Nextcloud weg")
        profile = await fake_lookup(uid)
        return Profile(profile.user_id, profile.display_name, profile.groups, language=self.language)


async def test_outage_after_success_keeps_the_last_language(
    client: httpx.AsyncClient, app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app_env
    lookup = Switch("en")
    service = RoleService(lookup)
    monkeypatch.setattr(roles, "_role_service", service)
    assert (await client.get("/api/me", headers=appapi_headers())).json()["language"] == "en"
    service.invalidate()
    lookup.down = True
    response = await client.get("/api/me", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json() == {"detail": "Nextcloud is not responding right now. Please try again in a moment."}


async def test_outage_after_success_keeps_german(
    client: httpx.AsyncClient, app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del app_env
    lookup = Switch("de")
    service = RoleService(lookup)
    monkeypatch.setattr(roles, "_role_service", service)
    assert (await client.get("/api/me", headers=appapi_headers())).status_code == 200
    service.invalidate()
    lookup.down = True
    response = await client.get("/api/me", headers=appapi_headers())
    assert response.json() == {"detail": roles.MSG_UNAVAILABLE}


async def test_outage_for_an_unseen_account_is_english_without_extra_lookup(
    client: httpx.AsyncClient, role_lookup_error: list[str]
) -> None:
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json() == {"detail": "Nextcloud is not responding right now. Please try again in a moment."}
    # The handler asks for the language but never asks Nextcloud a second time (T-06-76).
    assert role_lookup_error == ["admin"]


async def test_language_uses_the_cached_profile(app_env: Path) -> None:
    del app_env
    lookup = Switch("fr")
    service = RoleService(lookup)
    await service.profile(KID)
    assert await service.language(KID) == "fr"
    assert await service.language(KID) == "fr"
    assert lookup.calls == 1


async def test_language_never_raises(app_env: Path) -> None:
    del app_env

    async def broken(uid: str) -> Profile:
        raise RuntimeError(uid)

    assert await RoleService(broken).language(KID) == "en"


async def test_nc_admin_check_remembers_the_language_without_caching_the_role(app_env: Path) -> None:
    del app_env
    lookup = Switch("fr")
    service = RoleService(lookup)
    assert await service.nc_admin("admin") is True
    assert await service.language("admin") == "fr"
    assert lookup.calls == 1
    # The role cache stays untouched: the next role question asks Nextcloud again.
    await service.role("admin")
    assert lookup.calls == 2


# --- handler details: unsigned, headers, validation messages -----------------------------------


def _german_note(value: str) -> str:
    if value == "bad":
        raise ValueError(roles.MSG_NOT_LOGGED_IN)
    return value


class Body(BaseModel):
    count: int
    note: Annotated[str, AfterValidator(_german_note)] = ""


class UserFromHeader:
    """Test middleware: puts X-Test-User into scope["username"] like AppAPIAuthMiddleware."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for key, value in scope["headers"]:
                if key == b"x-test-user":
                    scope["username"] = value.decode()
        await self.app(scope, receive, send)


def _mini_app() -> FastAPI:
    app = FastAPI()
    install_language_handlers(app)
    app.add_middleware(UserFromHeader)

    @app.get("/who")
    async def who(uid: UserDep, language: LangDep) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"uid": uid, "language": language}

    @app.get("/locked")
    async def locked() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(401, detail=roles.MSG_NOT_LOGGED_IN, headers={"WWW-Authenticate": "Basic"})

    @app.post("/body")
    async def body(payload: Body) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"count": payload.count}

    return app


@pytest.fixture
async def mini(app_env: Path) -> AsyncIterator[httpx.AsyncClient]:
    del app_env
    transport = httpx.ASGITransport(app=_mini_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_unsigned_request_gets_english(mini: httpx.AsyncClient) -> None:
    response = await mini.get("/who")
    assert response.status_code == 401
    assert response.json() == {"detail": "Not logged in."}


async def test_lang_dependency(mini: httpx.AsyncClient, lang: Any) -> None:
    lang(KID, "fr")
    assert (await mini.get("/who", headers={"X-Test-User": KID})).json() == {"uid": KID, "language": "fr"}


async def test_status_and_headers_survive_translation(mini: httpx.AsyncClient, lang: Any) -> None:
    lang(KID, "en")
    english = await mini.get("/locked", headers={"X-Test-User": KID})
    german = await mini.get("/locked", headers={"X-Test-User": "admin"})
    for response in (english, german):
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Basic"
    assert english.json() == {"detail": "Not logged in."}
    assert german.json() == {"detail": roles.MSG_NOT_LOGGED_IN}


async def test_validator_message_is_translated(mini: httpx.AsyncClient, lang: Any) -> None:
    lang(KID, "en")
    response = await mini.post("/body", json={"count": "x", "note": "bad"}, headers={"X-Test-User": KID})
    assert response.status_code == 422
    messages = sorted(entry["msg"] for entry in response.json()["detail"])
    assert messages == [
        "Input should be a valid integer, unable to parse string as an integer",
        "Value error, Not logged in.",
    ]


async def test_validator_message_stays_german(mini: httpx.AsyncClient) -> None:
    response = await mini.post("/body", json={"count": 1, "note": "bad"}, headers={"X-Test-User": "admin"})
    assert response.status_code == 422
    assert [entry["msg"] for entry in response.json()["detail"]] == [f"Value error, {roles.MSG_NOT_LOGGED_IN}"]


# --- response fields and router errors in the account language (Task 2) ----------------------

W1, W2, W3, W4, W5 = "aaaaaaaaaaa1", "aaaaaaaaaaa2", "aaaaaaaaaaa3", "aaaaaaaaaaa4", "aaaaaaaaaaa5"
UNKNOWN = "bbbbbbbbbbbb"
# Words and umlauts that only German texts have; world and player names are user data and excluded.
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|und|nicht|bitte|ist|kein|gerade|welt)\b", re.IGNORECASE)
NAMES = ("Waldwelt", "Bergwelt", "Kaputtwelt", "Sicherwelt", "Absturzwelt")


def german_in(text: str | None) -> bool:
    if text is None:
        return False
    for name in NAMES:
        text = text.replace(name, "")
    return GERMAN.search(text) is not None


def test_german_detector_positive_control() -> None:
    assert german_in(roles.MSG_FORBIDDEN)
    assert german_in(world_service.RECONCILE_DATA_MISSING)
    assert not german_in("Only parents can manage worlds.")
    assert not german_in("Waldwelt")


def _row(world_id: str, name: str, port: int, *, op_state: str = "ready", last_error: str | None = None) -> WorldRow:
    return WorldRow(
        id=world_id,
        name=name,
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state=op_state,
        last_error=last_error,
        created_at="2026-10-20T10:00:00+00:00",
    )


@pytest.fixture
def worlds_env(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> WorldStore:
    """Five worlds with server texts: running, stopped, failed (stored error), failed backup job, crashed."""
    from gameworld.main import APP

    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    store.insert_world(_row(W1, "Waldwelt", 30015))
    store.insert_world(_row(W2, "Bergwelt", 30016))
    store.insert_world(
        _row(W3, "Kaputtwelt", 30017, op_state="failed", last_error=world_service.RECONCILE_DATA_MISSING)
    )
    store.insert_world(_row(W4, "Sicherwelt", 30018))
    store.insert_world(_row(W5, "Absturzwelt", 30019))
    store.set_backup_job(W4, "backup", "failed", backup_service.JOB_FAILED, None, "2026-10-20T10:00:00+00:00", None)
    fake = FakeProvisioner()
    fake.containers[W1] = (30015, "running")
    fake.containers[W2] = (30016, "exited")
    fake.containers[W4] = (30018, "exited")
    fake.containers[W5] = (30019, "exited")
    fake.extra[W5] = {"exit_code": 137}
    service = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, worlds_api.get_service, lambda: service)
    return store


def _world_texts(world: dict[str, Any]) -> list[str | None]:
    job = world.get("backup_job") or {}
    return [world["status_text"], world["preset_title"], world["last_error"], job.get("message")]


async def test_world_list_in_english(client: httpx.AsyncClient, worlds_env: WorldStore, lang: Any) -> None:
    del worlds_env
    lang("admin", "en")
    response = await client.get("/api/worlds", headers=appapi_headers())
    assert response.status_code == 200
    worlds = {item["id"]: item for item in response.json()["worlds"]}
    assert len(worlds) == 5
    for world in worlds.values():
        for text in _world_texts(world):
            assert not german_in(text), (world["id"], text)
    assert worlds[W1]["preset_title"] == "Build (creative)"
    assert worlds[W3]["last_error"] == "The world data is missing. The world can only be deleted."
    assert worlds[W4]["backup_job"]["message"] == "The backup failed. The world keeps running."
    assert worlds[W5]["status_text"] == "The world stopped unexpectedly (code 137)."


async def test_world_list_in_french(client: httpx.AsyncClient, worlds_env: WorldStore, lang: Any) -> None:
    del worlds_env
    lang("admin", "fr")
    worlds = {item["id"]: item for item in (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]}
    assert worlds[W1]["preset_title"] == "Construire (créatif)"
    assert worlds[W5]["status_text"] == f"Le monde s{chr(0x2019)}est arrêté de façon inattendue (code 137)."
    for world in worlds.values():
        for text in _world_texts(world):
            assert not german_in(text), (world["id"], text)


async def test_world_list_stays_german(client: httpx.AsyncClient, worlds_env: WorldStore) -> None:
    del worlds_env
    worlds = {item["id"]: item for item in (await client.get("/api/worlds", headers=appapi_headers())).json()["worlds"]}
    assert worlds[W1]["preset_title"] == presets.MTG_KREATIV.title
    assert worlds[W1]["status_text"] == status_texts.TEXT_RUNNING
    assert worlds[W3]["last_error"] == world_service.RECONCILE_DATA_MISSING
    assert worlds[W4]["backup_job"]["message"] == backup_service.JOB_FAILED
    assert worlds[W5]["status_text"] == status_texts.TEXT_CRASHED.format(code=137)
    assert any(german_in(text) for world in worlds.values() for text in _world_texts(world))


async def test_presets_in_english_and_german(client: httpx.AsyncClient, lang: Any) -> None:
    german = (await client.get("/api/presets", headers=appapi_headers())).json()["presets"]
    assert [item["title"] for item in german] == [preset.title for preset in presets.PRESETS.values()]
    lang("admin", "en")
    english = (await client.get("/api/presets", headers=appapi_headers())).json()["presets"]
    assert [item["title"] for item in english] == ["Build (creative)", "Adventure (gentle)"]
    for item in english:
        assert not german_in(item["title"]), item
        assert not german_in(item["description"]), item


async def test_my_worlds_in_english(client: httpx.AsyncClient, worlds_env: WorldStore, lang: Any) -> None:
    del worlds_env
    for world_id in (W1, W3, W4):
        invited = await client.post(
            f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": KID}, headers=appapi_headers()
        )
        assert invited.status_code == 200, invited.text
    german = {
        item["id"]: item for item in (await client.get("/api/my/worlds", headers=appapi_headers(KID))).json()["worlds"]
    }
    assert german[W3]["status_text"] == me_api.TEXT_WELT_PROBLEM
    lang(KID, "en")
    english = {
        item["id"]: item for item in (await client.get("/api/my/worlds", headers=appapi_headers(KID))).json()["worlds"]
    }
    assert english[W1]["status_text"] == "Running"
    assert english[W3]["status_text"] == "This world has a problem right now. Tell your parents."
    for item in english.values():
        assert not german_in(item["status_text"]), item


def _all_setup_items() -> list[CheckItem]:
    values = {
        "host": "proxy.local",
        "port": 2375,
        "docker_url": "tcp://proxy.local:2375",
        "shown": "1.41",
        "version": "1.47",
        "method": "GET",
        "path": "/info",
        "code": 500,
        "error_type": "ConnectionError",
        "docs_url": setup_texts.DOCS_URL,
    }
    items: list[CheckItem] = []
    for name in sorted(vars(setup_texts)):
        if name.startswith(("MSG_", "TEXT_")):
            text: str = getattr(setup_texts, name)
            items.append(CheckItem(id=name.lower(), ok=False, severity="warning", message=text.format(**values)))
    return items


async def test_setup_check_in_english(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, lang: Any) -> None:
    items = _all_setup_items()
    assert len(items) > 20
    result = SetupCheckResult(ok=False, items=items)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: result)
    german = (await client.get("/api/setup-check", headers=appapi_headers())).json()["items"]
    assert [item["message"] for item in german] == [item.message for item in items]
    lang("admin", "en")
    english = (await client.get("/api/setup-check", headers=appapi_headers())).json()["items"]
    for item in english:
        assert not german_in(item["message"]), item
        assert setup_texts.DOCS_URL in item["message"] or "Guide" not in item["message"]


async def test_setup_check_config_error_in_english(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, lang: Any
) -> None:
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "kaputt")
    lang("admin", "en")
    items = (await client.get("/api/setup-check", headers=appapi_headers())).json()["items"]
    assert items[0]["id"] == "config"
    assert items[0]["message"].startswith("GAMEWORLD_PORT_RANGE is invalid: 'kaputt'.")


SEVEN_OPEN_DAYS = {
    "days": [{"weekday": day, "open": True, "window_start": 600, "window_end": 1080} for day in range(1, 8)]
}
ROUTER_ERRORS = [
    ("POST", f"/api/worlds/{UNKNOWN}/start", None, 404),
    ("POST", f"/api/worlds/{UNKNOWN}/backups", None, 404),
    ("GET", f"/api/worlds/{UNKNOWN}/players", None, 404),
    ("POST", f"/api/worlds/{UNKNOWN}/talk/read-only", None, 404),
    ("POST", f"/api/playtime/worlds/{UNKNOWN}/window", SEVEN_OPEN_DAYS, 404),
    ("POST", f"/api/worlds/{W3}/start", None, 409),
    ("POST", f"/api/worlds/{W1}/talk/read-only", None, 409),
    ("POST", "/api/settings", {"join_host": "http://x:1"}, 422),
]


@pytest.mark.parametrize(("method", "path", "body", "code"), ROUTER_ERRORS)
async def test_router_errors_in_english(
    client: httpx.AsyncClient,
    worlds_env: WorldStore,
    lang: Any,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    code: int,
) -> None:
    del worlds_env
    german = await client.request(method, path, json=body, headers=appapi_headers())
    assert german.status_code == code, german.text
    assert german_in(german.text), german.text  # positive control: the German answer is detected
    lang("admin", "en")
    english = await client.request(method, path, json=body, headers=appapi_headers())
    assert english.status_code == code
    detail = english.json()["detail"]
    texts = [detail] if isinstance(detail, str) else [entry["msg"] for entry in detail]
    for text in texts:
        assert not german_in(text), text


async def test_alerts_503_in_english(
    client: httpx.AsyncClient, worlds_env: WorldStore, monkeypatch: pytest.MonkeyPatch, lang: Any
) -> None:
    def broken(*args: object, **kwargs: object) -> object:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(worlds_env, "review_pref", broken)
    lang("admin", "en")
    response = await client.get("/api/review/prefs", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json() == {"detail": "The data cannot be read right now. Please try again in a moment."}


async def test_csrf_refusal_in_english(client: httpx.AsyncClient, lang: Any) -> None:
    lang("admin", "en")
    headers = {**appapi_headers(), "Content-Type": "text/plain"}
    response = await client.post("/api/pause/end", content="x", headers=headers)
    assert response.status_code == 403
    assert response.json() == {"detail": "Gameworld only accepts changes as JSON from its own page."}
    german = await client.post(
        "/api/pause/end", content="x", headers={**appapi_headers(), "Content-Type": "text/plain"}
    )
    assert german.status_code == 403


async def test_csrf_refusal_stays_german(client: httpx.AsyncClient) -> None:
    headers = {**appapi_headers(), "Content-Type": "text/plain"}
    response = await client.post("/api/pause/end", content="x", headers=headers)
    assert response.json() == {"detail": csrf_api.MSG_NOT_JSON}
