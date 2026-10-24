"""Verwalter-Gruppen (ROLLE-03): Rolle aus konfigurierten Gruppen, NC-Admin-Sperre ohne Cache.

Negativfälle sind Pflicht (Owner-Regel): kaputte Konfiguration gibt nie mehr Rechte,
ein Verwalter aus einer Zusatzgruppe ist kein Nextcloud-Admin. Die Gegenproben laufen
über eigene Wege (rohes SQLite, echte Route), nicht über die geprüfte Funktion selbst.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from gameworld.access import roles
from gameworld.access.roles import (
    ADMIN_GROUP,
    META_VERWALTER_GROUPS,
    MSG_NC_ADMIN_ONLY,
    ROLE_SPIELER,
    ROLE_VERWALTER,
    Profile,
    RoleService,
    parse_verwalter_groups,
    require_nc_admin,
    role_of,
)
from gameworld.api import worlds
from tests.conftest import appapi_headers, fake_lookup

LEHRER = "gw-lehrer"
WITH_TEACHERS = frozenset({ADMIN_GROUP, "lehrkraefte"})


def _counting_lookup(calls: list[str]) -> roles.Lookup:
    async def lookup(uid: str) -> Profile:
        calls.append(uid)
        return await fake_lookup(uid)

    return lookup


def _groups(value: frozenset[str]) -> roles.GroupsSource:
    async def source() -> frozenset[str]:
        return value

    return source


# Konfiguration lesen (T-06-01)


def test_missing_config_means_only_admin() -> None:
    assert parse_verwalter_groups(None) == frozenset({"admin"})
    assert parse_verwalter_groups("") == frozenset({"admin"})


@pytest.mark.parametrize("raw", ["kaputt", "{", '{"lehrkraefte": true}', '"lehrkraefte"', "42", "null"])
def test_broken_config_means_only_admin(raw: str) -> None:
    assert parse_verwalter_groups(raw) == frozenset({"admin"})


def test_configured_groups_always_include_admin() -> None:
    assert parse_verwalter_groups('["lehrkraefte"]') == frozenset({"admin", "lehrkraefte"})
    assert parse_verwalter_groups("[]") == frozenset({"admin"})


def test_invalid_entries_are_dropped() -> None:
    raw = json.dumps(["lehrkraefte", "", 7, None, ["x"], "x" * 65, "y" * 64])
    assert parse_verwalter_groups(raw) == frozenset({"admin", "lehrkraefte", "y" * 64})


# Rolle aus der Selbstauskunft gegen die Gruppenmenge


def test_teacher_is_verwalter_only_when_group_configured() -> None:
    teacher = Profile(user_id=LEHRER, display_name="Lehrer", groups=("lehrkraefte",))
    assert role_of(teacher, WITH_TEACHERS) == ROLE_VERWALTER
    assert role_of(teacher, frozenset({ADMIN_GROUP})) == ROLE_SPIELER
    # Ohne Angabe gilt nur admin (bestehende Aufrufer bleiben unverändert).
    assert role_of(teacher) == ROLE_SPIELER


def test_child_in_other_group_stays_spieler() -> None:
    child = Profile(user_id="gw-kind-k", display_name="Kind", groups=("klasse",))
    assert role_of(child, WITH_TEACHERS) == ROLE_SPIELER


async def test_role_service_uses_configured_groups() -> None:
    service = RoleService(fake_lookup, _groups(WITH_TEACHERS))
    assert await service.role(LEHRER) == ROLE_VERWALTER
    assert await service.role("gw-kind-k") == ROLE_SPIELER
    assert await service.role("admin") == ROLE_VERWALTER


async def test_role_service_without_source_is_only_admin() -> None:
    service = RoleService(fake_lookup)
    assert await service.role(LEHRER) == ROLE_SPIELER
    assert await service.role("admin") == ROLE_VERWALTER


async def test_source_without_admin_still_keeps_admin() -> None:
    service = RoleService(fake_lookup, _groups(frozenset({"lehrkraefte"})))
    assert await service.role("admin") == ROLE_VERWALTER


async def test_failing_group_source_falls_back_to_admin_not_503(caplog: pytest.LogCaptureFixture) -> None:
    async def broken() -> frozenset[str]:
        raise RuntimeError("geheimer Fehlertext")

    service = RoleService(fake_lookup, broken)
    # Fail closed: Der Lehrer verliert die Rolle, admin behält sie, keine Störung nach außen.
    assert await service.role(LEHRER) == ROLE_SPIELER
    assert await service.role("admin") == ROLE_VERWALTER
    assert "RuntimeError" in caplog.text
    assert "geheimer Fehlertext" not in caplog.text


async def test_invalidate_drops_cached_profiles() -> None:
    profiles: dict[str, tuple[str, ...]] = {LEHRER: ("lehrkraefte",)}

    async def lookup(uid: str) -> Profile:
        return Profile(user_id=uid, display_name=uid, groups=profiles.get(uid, ()))

    service = RoleService(lookup, _groups(WITH_TEACHERS))
    assert await service.role(LEHRER) == ROLE_VERWALTER
    profiles[LEHRER] = ()
    # Noch im 30-s-Cache: alter Stand.
    assert await service.role(LEHRER) == ROLE_VERWALTER
    service.invalidate()
    assert await service.role(LEHRER) == ROLE_SPIELER


# require_nc_admin (T-06-02): nur Gruppe admin, nie aus dem Cache


async def test_nc_admin_passes_for_admin() -> None:
    service = RoleService(fake_lookup, _groups(WITH_TEACHERS))
    assert await require_nc_admin("admin", service) == "admin"


async def test_verwalter_from_extra_group_is_not_nc_admin() -> None:
    service = RoleService(fake_lookup, _groups(WITH_TEACHERS))
    # Vorbedingung: Der Lehrer ist wirklich Verwalter (sonst bewiese das 403 nichts).
    assert await service.role(LEHRER) == ROLE_VERWALTER
    with pytest.raises(HTTPException) as caught:
        await require_nc_admin(LEHRER, service)
    assert caught.value.status_code == 403
    assert caught.value.detail == MSG_NC_ADMIN_ONLY
    assert MSG_NC_ADMIN_ONLY == "Nur Nextcloud-Admins dürfen das ändern."


async def test_nc_admin_lookup_error_gives_503() -> None:
    async def failing(uid: str) -> Profile:
        raise ConnectionError(uid)

    with pytest.raises(HTTPException) as caught:
        await require_nc_admin("admin", RoleService(failing))
    assert caught.value.status_code == 503
    assert caught.value.detail == roles.MSG_UNAVAILABLE


async def test_nc_admin_asks_nextcloud_on_every_call() -> None:
    calls: list[str] = []
    service = RoleService(_counting_lookup(calls), _groups(WITH_TEACHERS))
    await service.role("admin")
    assert calls == ["admin"]
    # Der Rollen-Cache ist warm, require_nc_admin fragt trotzdem jedes Mal neu.
    await require_nc_admin("admin", service)
    await require_nc_admin("admin", service)
    assert calls == ["admin", "admin", "admin"]


async def test_nc_admin_sees_loss_of_admin_group_immediately() -> None:
    groups: dict[str, tuple[str, ...]] = {"admin": ("admin",)}

    async def lookup(uid: str) -> Profile:
        return Profile(user_id=uid, display_name=uid, groups=groups.get(uid, ()))

    service = RoleService(lookup)
    assert await require_nc_admin("admin", service) == "admin"
    groups["admin"] = ("lehrkraefte",)
    with pytest.raises(HTTPException) as caught:
        await require_nc_admin("admin", service)
    assert caught.value.status_code == 403


# Ende zu Ende: echte Gruppenquelle aus dem Store, Konfiguration per rohem SQLite


def _write_meta_raw(db: Path, value: str) -> None:
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (META_VERWALTER_GROUPS, value),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.fixture
def stored_groups(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Rollen-Dienst mit der echten Gruppenquelle (meta im Store des Weltdienstes)."""
    monkeypatch.setattr(
        roles,
        "_role_service",
        RoleService(fake_lookup, roles._stored_verwalter_groups),  # pyright: ignore[reportPrivateUsage]
    )
    worlds.get_service().store.migrate()
    return app_env / "gameworld.sqlite3"


class _EmptyService:
    async def list_worlds(self) -> list[object]:
        return []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 403),
        ("kaputt", 403),
        ('["andere"]', 403),
        ('["lehrkraefte"]', 200),
    ],
)
async def test_teacher_route_access_follows_stored_config(
    client: httpx.AsyncClient,
    stored_groups: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str | None,
    expected: int,
) -> None:
    if raw is not None:
        _write_meta_raw(stored_groups, raw)
    from gameworld.main import APP

    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, _EmptyService)
    response = await client.get("/api/worlds", headers=appapi_headers(LEHRER))
    assert response.status_code == expected
    # Positivkontrolle: admin kommt unabhängig von der Konfiguration immer hinein.
    admin = await client.get("/api/worlds", headers=appapi_headers())
    assert admin.status_code == 200
    # Ein Kind aus der Klasse wird nie Verwalter.
    child = await client.get("/api/worlds", headers=appapi_headers("gw-kind-k"))
    assert child.status_code == 403
