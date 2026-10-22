"""Kurzlebige Nextcloud-Clients (WR-05): Konto ohne Capabilities-Request, Sessions immer zu."""

from __future__ import annotations

import asyncio
from base64 import b64decode
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nc_py_api import AsyncNextcloudApp

from gameworld import nc as nc_mod
from gameworld.access import roles
from gameworld.access.directory import DirectoryUnavailableError, NcDirectory
from gameworld.access.secret import PlayerSecret
from gameworld.nc import close_nc, nc_app, nc_as
from tests.conftest import assert_closed, install_fake_nc


def _spy_close(nc: AsyncNextcloudApp) -> list[AsyncMock]:
    """Ersetzt close beider echter Sessions durch einen Spion, der das echte close aufruft."""
    spies: list[AsyncMock] = []
    session: Any = nc._session  # pyright: ignore[reportPrivateUsage]
    for name in ("adapter", "adapter_dav"):
        adapter = getattr(session, name)
        spy = AsyncMock(wraps=adapter.close)
        adapter.close = spy
        spies.append(spy)
    return spies


async def _auth_user(nc: AsyncNextcloudApp) -> str:
    """Konto, das nc_py_api beim nächsten Request in AUTHORIZATION-APP-API schreibt."""
    session: Any = nc._session  # pyright: ignore[reportPrivateUsage]
    request = SimpleNamespace(headers={})
    await session._add_auth(request)
    user, _secret = b64decode(request.headers["AUTHORIZATION-APP-API"]).decode().split(":", 1)
    return user


async def test_nc_as_sets_user_without_capabilities_request(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    from nc_py_api import _session

    async def no_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("set_user bzw. Capabilities-Request ist nicht nötig")

    monkeypatch.setattr(_session.AsyncNcSessionBasic, "update_server_info", no_request)
    async with nc_as("mama") as nc:
        spies = _spy_close(nc)
        assert await _auth_user(nc) == "mama"
        session: Any = nc._session  # pyright: ignore[reportPrivateUsage]
        assert session._capabilities == {}
    for spy in spies:
        spy.assert_awaited_once()


async def test_nc_as_closes_sessions_when_body_raises(app_env: Path) -> None:
    del app_env
    spies: list[AsyncMock] = []

    async def body() -> None:
        async with nc_as("mama") as nc:
            spies.extend(_spy_close(nc))
            raise RuntimeError("kaputt")

    with pytest.raises(RuntimeError, match="kaputt"):
        await body()
    assert len(spies) == 2
    for spy in spies:
        spy.assert_awaited_once()


async def test_nc_app_has_no_user_and_closes(app_env: Path) -> None:
    del app_env
    async with nc_app() as nc:
        spies = _spy_close(nc)
        assert await _auth_user(nc) == ""
    for spy in spies:
        spy.assert_awaited_once()


async def test_parallel_clients_never_share_identity(app_env: Path) -> None:
    """Kein geteilter Client über set_user: Gleichzeitige Abläufe behalten ihr Konto (Identitäts-Rennen)."""
    del app_env

    async def who(uid: str) -> str:
        async with nc_as(uid) as nc:
            await asyncio.sleep(0)
            return await _auth_user(nc)

    results = await asyncio.gather(*(who(uid) for uid in ["mama", "papa", "lena"] * 5))
    assert results == ["mama", "papa", "lena"] * 5


async def test_nc_as_refuses_empty_user(app_env: Path) -> None:
    del app_env
    with pytest.raises(ValueError, match="Konto-ID"):
        async with nc_as(""):
            pass


async def test_close_errors_are_swallowed() -> None:
    nc = MagicMock()
    nc._session.adapter.close = AsyncMock(side_effect=OSError("weg"))
    nc._session.adapter_dav.close = AsyncMock()
    await close_nc(nc)
    nc._session.adapter_dav.close.assert_awaited_once()
    await close_nc(object())


async def test_directory_and_roles_close_even_on_error(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    app = MagicMock()
    app.users.get_user = AsyncMock(side_effect=OSError("weg"))
    app.users_groups.get_members = AsyncMock(side_effect=OSError("weg"))
    recorder = install_fake_nc(monkeypatch, app)
    with pytest.raises(DirectoryUnavailableError):
        await NcDirectory().user("admin", "gw-kind")
    with pytest.raises(DirectoryUnavailableError):
        await NcDirectory().group_members("admin", "admin")
    with pytest.raises(OSError, match="weg"):
        await roles.nc_profile("gw-kind")
    assert recorder.users == ["admin", "admin", "gw-kind"]
    assert_closed(app, times=3)


async def test_player_secret_closes_its_client() -> None:
    app = MagicMock()
    app.appconfig_ex.get_value = AsyncMock(return_value="ab" * 32)
    app._session.adapter.close = AsyncMock()
    app._session.adapter_dav.close = AsyncMock()
    assert await PlayerSecret(lambda: app).get() == bytes.fromhex("ab" * 32)  # pyright: ignore[reportArgumentType]
    assert_closed(app, times=1)


def test_module_builds_clients_only_here() -> None:
    """Nur gameworld.nc baut AsyncNextcloudApp; alle anderen nutzen nc_as/nc_app (grep-Gegenprobe)."""
    src = Path(nc_mod.__file__).resolve().parent
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name != "nc.py" and "AsyncNextcloudApp(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
