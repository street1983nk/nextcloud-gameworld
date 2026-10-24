"""Verwalter-Gruppen (ROLLE-03): Rolle aus konfigurierten Gruppen, NC-Admin-Sperre ohne Cache.

Negativfälle sind Pflicht (Owner-Regel): kaputte Konfiguration gibt nie mehr Rechte,
ein Verwalter aus einer Zusatzgruppe ist kein Nextcloud-Admin. Die Gegenproben laufen
über eigene Wege (rohes SQLite, echte Route), nicht über die geprüfte Funktion selbst.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import HTTPException

from gameworld.access import roles
from gameworld.access.directory import DirectoryRejectedError, DirectoryUnavailableError
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
from gameworld.config import load_settings
from gameworld.notify import loop
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.playtime.service import META_NC_ADMINS, TimeService
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import FakeDirectory, appapi_headers, fake_lookup
from tests.test_pause_api import VERIFIER, _row
from tests.test_service_lifecycle import FakeProvisioner

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


# Schnappschuss je Gruppe (T-06-04) und Kontenabgleich nur als NC-Admin (T-06-03)

W1 = "aaaaaaaaaaa1"
GONE = "gw-geloescht"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    """Ein Haushalt nach dem Update: Gruppe admin mit admin, Lehrkräfte als Zusatzgruppe konfiguriert."""
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    # Ein Konto, das Nextcloud nicht (mehr) liefert: Für den Lehrer sähe es aus wie gelöscht (404).
    world_store.insert_player(PlayerRow(nc_user=GONE, player_name="Weg", rotation=0))
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER, GONE: VERIFIER})
    world_store.set_meta(META_VERWALTER_GROUPS, json.dumps(["lehrkraefte"]))
    world_store.replace_group_snapshot(ADMIN_GROUP, {"admin"})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    return world_store


@pytest.fixture
def service(store: WorldStore) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())


@pytest.fixture
def school(fake_directory: FakeDirectory) -> FakeDirectory:
    """Wie Nextcloud: Der Lehrer darf die Gruppe admin nicht lesen (403), seine eigene schon."""
    fake_directory.answers[(LEHRER, ADMIN_GROUP)] = DirectoryRejectedError("403")
    return fake_directory


def _raw_snapshot(db: Path) -> dict[str, list[str]]:
    """Stand je Gruppe direkt aus SQLite (eigener Weg, nicht über group_snapshot)."""
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("SELECT gid, uid FROM verwalter_snapshot ORDER BY gid, uid").fetchall()
    finally:
        connection.close()
    result: dict[str, list[str]] = {}
    for gid, uid in rows:
        result.setdefault(str(gid), []).append(str(uid))
    return result


def _raw_meta(db: Path, key: str) -> object:
    connection = sqlite3.connect(db)
    try:
        row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    finally:
        connection.close()
    return None if row is None else json.loads(str(row[0]))


def _db(app_env: Path) -> Path:
    return app_env / "gameworld.sqlite3"


async def test_teacher_without_admin_right_keeps_admin_stand(
    service: WorldService, school: FakeDirectory, app_env: Path
) -> None:
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin"]}
    await TimeService(service, school).refresh_admins(LEHRER, force=True)
    # Jede Gruppe einzeln im Namen des Lehrers; die 403 auf admin leert deren Stand nicht.
    assert school.group_calls == [(LEHRER, "admin"), (LEHRER, "lehrkraefte")]
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin"], "lehrkraefte": [LEHRER]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER]


async def test_outage_on_one_group_keeps_only_that_stand(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    store.replace_group_snapshot("lehrkraefte", {LEHRER, "gw-lehrer2"})
    school.answers[("admin", "lehrkraefte")] = DirectoryUnavailableError("weg")
    school.groups["admin"] = ["admin", "papa"]
    await TimeService(service, school).refresh_admins("admin", force=True)
    # admin ist gelesen und ersetzt, lehrkraefte bleibt wegen der Störung wie es war.
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin", "papa"], "lehrkraefte": [LEHRER, "gw-lehrer2"]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER, "gw-lehrer2", "papa"]


async def test_verify_with_teacher_only_confirms_teacher_and_no_nc_admin(
    service: WorldService, school: FakeDirectory, app_env: Path
) -> None:
    acting = await TimeService(service, school).verify_admins([LEHRER])
    assert acting == LEHRER
    # Der admin-Stand bleibt: Nur ein abgelehnter Kandidat ohne Recht auf admin kam dorthin.
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin"], "lehrkraefte": [LEHRER]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER]
    # Ohne frische Antwort der Gruppe admin gibt es keinen bestätigten NC-Admin.
    assert _raw_meta(_db(app_env), META_NC_ADMINS) == []


async def test_verify_with_admin_records_nc_admins(service: WorldService, school: FakeDirectory, app_env: Path) -> None:
    acting = await TimeService(service, school).verify_admins(["admin", LEHRER])
    assert acting == "admin"
    assert _raw_meta(_db(app_env), META_NC_ADMINS) == ["admin"]
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER]


async def test_verify_never_confirms_rejected_account(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    # Ein Ex-Lehrer steht noch im Stand, Nextcloud verweigert ihm jede Gruppe.
    store.replace_group_snapshot("lehrkraefte", {"gw-ex"})
    school.answers[("gw-ex", ADMIN_GROUP)] = DirectoryRejectedError("403")
    school.answers[("gw-ex", "lehrkraefte")] = DirectoryRejectedError("403")
    assert await TimeService(service, school).verify_admins(["gw-ex"]) is None
    assert _raw_snapshot(_db(app_env)) == {}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == []
    assert _raw_meta(_db(app_env), META_NC_ADMINS) == []


async def test_removed_group_drops_its_stand_and_members(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    await TimeService(service, school).verify_admins(["admin", LEHRER])
    assert LEHRER in cast(list[str], _raw_meta(_db(app_env), META_TIME_ADMINS))
    store.set_meta(META_VERWALTER_GROUPS, "[]")
    assert await TimeService(service, school).verify_admins(["admin", LEHRER]) == "admin"
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin"]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin"]


async def test_broken_config_only_reads_group_admin(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    store.set_meta(META_VERWALTER_GROUPS, "kaputt")
    await TimeService(service, school).refresh_admins(LEHRER, force=True)
    assert school.group_calls == [(LEHRER, "admin")]
    assert "lehrkraefte" not in _raw_snapshot(_db(app_env))


async def test_seniority_follows_first_confirmation(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    store.set_meta(META_VERWALTER_GROUPS, "[]")
    await TimeService(service, school).verify_admins(["admin"])
    connection = sqlite3.connect(_db(app_env))
    try:
        connection.execute("UPDATE verwalter_seen SET first_seen = '2026-10-01T08:00:00+00:00'")
        connection.commit()
    finally:
        connection.close()
    store.set_meta(META_VERWALTER_GROUPS, json.dumps(["lehrkraefte"]))
    await TimeService(service, school).verify_admins([LEHRER, "admin"])
    connection = sqlite3.connect(_db(app_env))
    try:
        seen = dict(connection.execute("SELECT uid, first_seen FROM verwalter_seen").fetchall())
    finally:
        connection.close()
    assert set(seen) == {"admin", LEHRER}
    # admin behält den ersten Tag, der Lehrer bekommt den heutigen.
    assert seen["admin"] == "2026-10-01T08:00:00+00:00"
    assert seen[LEHRER] > seen["admin"]
    assert store.verwalter_seniority() == ["admin", LEHRER]


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(self, world_service: WorldService, acting_uid: str) -> None:
        del world_service
        self.calls.append(acting_uid)


async def test_purge_never_runs_without_confirmed_nc_admin(
    service: WorldService, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    purge, talk = _Recorder(), _Recorder()
    monkeypatch.setattr(loop, "MAINTENANCE", [(purge, True), (talk, False)])
    store.set_meta(META_NC_ADMINS, "[]")
    await loop.run_hooks(service, LEHRER)
    assert purge.calls == []
    assert talk.calls == [LEHRER]


async def test_purge_never_runs_with_broken_nc_admins(
    service: WorldService, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    purge = _Recorder()
    monkeypatch.setattr(loop, "MAINTENANCE", [(purge, True)])
    store.set_meta(META_NC_ADMINS, "kaputt")
    await loop.run_hooks(service, "admin")
    assert purge.calls == []


async def test_purge_runs_once_as_confirmed_nc_admin(
    service: WorldService, store: WorldStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    purge, talk = _Recorder(), _Recorder()
    monkeypatch.setattr(loop, "MAINTENANCE", [(purge, True), (talk, False)])
    store.set_meta(META_NC_ADMINS, json.dumps(["admin"]))
    await loop.run_hooks(service, LEHRER)
    assert purge.calls == ["admin"]
    assert talk.calls == [LEHRER]
    purge.calls.clear()
    await loop.run_hooks(service, "admin")
    assert purge.calls == ["admin"]


async def test_teacher_run_never_asks_directory_for_purge(
    service: WorldService, store: WorldStore, school: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negativtest mit dem echten Kontenabgleich: kein Aufruf im Namen des Lehrers, nichts vergessen."""
    monkeypatch.setattr(loop, "MAINTENANCE", [(loop.purge_accounts, True)])
    store.set_meta(META_NC_ADMINS, "[]")
    await loop.run_hooks(service, LEHRER)
    assert school.calls == []
    assert school.group_calls == []
    assert store.get_player(GONE) is not None


async def test_stale_nc_admin_entry_is_checked_fresh_before_purge(
    service: WorldService, store: WorldStore, school: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steht der Lehrer (veraltet oder manipuliert) in nc_admins, prüft der Abgleich frisch und lässt es."""
    monkeypatch.setattr(loop, "MAINTENANCE", [(loop.purge_accounts, True)])
    store.set_meta(META_NC_ADMINS, json.dumps([LEHRER]))
    await loop.run_hooks(service, LEHRER)
    assert school.group_calls == [(LEHRER, ADMIN_GROUP)]
    assert school.calls == []
    assert store.get_player(GONE) is not None


@pytest.mark.parametrize(("candidates", "forgotten"), [([LEHRER], False), (["admin", LEHRER], True)])
async def test_maintenance_end_to_end_purges_only_with_admin(
    service: WorldService,
    store: WorldStore,
    school: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
    candidates: list[str],
    forgotten: bool,
) -> None:
    """Ganzer Wartungslauf: Lehrer allein vergisst nichts; mit admin (Positivkontrolle) wird GONE vergessen."""
    monkeypatch.setattr(loop, "MAINTENANCE", [(loop.purge_accounts, True)])
    store.set_meta(META_TIME_ADMINS, json.dumps(candidates))
    if "admin" not in candidates:
        # Der Lehrer allein kann die Gruppe admin nicht lesen: ihr Stand bleibt, er kommt nicht in nc_admins.
        school.groups["admin"] = ["admin"]
    await loop.maintain_once(service, school)
    assert loop.LOOP_STATE.acting == candidates[0]
    assert (store.get_player(GONE) is None) is forgotten
    # Das unbeteiligte Kind bleibt immer.
    assert store.get_player("gw-kind") is not None
    purge_actors = {acting for acting, _uid in school.calls}
    assert purge_actors == ({"admin"} if forgotten else set())
