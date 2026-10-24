"""Server texts in the account language at the API boundary (D-25).

German accounts get exactly the previous texts; en and fr accounts get the
translation. Positive controls run the same request as a German account.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import AfterValidator, BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

from gameworld.access import roles
from gameworld.access.roles import Profile, RoleService, UserDep
from gameworld.api.language import LangDep, install_language_handlers
from tests import conftest
from tests.conftest import appapi_headers, fake_lookup

KID = "gw-kind"


@pytest.fixture
def lang(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Sets the account language of single fake accounts for one test."""

    def put(uid: str, language: str) -> None:
        monkeypatch.setitem(conftest.FAKE_LANGUAGES, uid, language)

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
