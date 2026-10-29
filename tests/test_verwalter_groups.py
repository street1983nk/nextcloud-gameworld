"""Manager groups (ROLLE-03): role from configured groups, NC admin lock without cache.

Negative cases are mandatory (owner rule): a broken configuration never gives more rights,
a manager from an additional group is not a Nextcloud admin. The cross-checks run
via their own paths (raw SQLite, real route), not via the checked function itself.
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
from tests.test_pause_api import VERIFIER, _new_mod, _row  # pyright: ignore[reportPrivateUsage]
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


# Read configuration (T-06-01)


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


# Role from the self-lookup against the group set


def test_teacher_is_verwalter_only_when_group_configured() -> None:
    teacher = Profile(user_id=LEHRER, display_name="Lehrer", groups=("lehrkraefte",))
    assert role_of(teacher, WITH_TEACHERS) == ROLE_VERWALTER
    assert role_of(teacher, frozenset({ADMIN_GROUP})) == ROLE_SPIELER
    # Without a value only admin counts (existing callers stay unchanged).
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
    # Fail closed: the teacher loses the role, admin keeps it, no outage to the outside.
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
    # Still in the 30 s cache: old state.
    assert await service.role(LEHRER) == ROLE_VERWALTER
    service.invalidate()
    assert await service.role(LEHRER) == ROLE_SPIELER


# require_nc_admin (T-06-02): only group admin, never from the cache


async def test_nc_admin_passes_for_admin() -> None:
    service = RoleService(fake_lookup, _groups(WITH_TEACHERS))
    assert await require_nc_admin("admin", service) == "admin"


async def test_verwalter_from_extra_group_is_not_nc_admin() -> None:
    service = RoleService(fake_lookup, _groups(WITH_TEACHERS))
    # Precondition: the teacher really is a manager (otherwise the 403 would prove nothing).
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
    # The role cache is warm, require_nc_admin asks anew every time anyway.
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


# End to end: real group source from the store, configuration via raw SQLite


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
    """Role service with the real group source (meta in the store of the world service)."""
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
    # Positive control: admin always gets in, independent of the configuration.
    admin = await client.get("/api/worlds", headers=appapi_headers())
    assert admin.status_code == 200
    # A child from the class never becomes a manager.
    child = await client.get("/api/worlds", headers=appapi_headers("gw-kind-k"))
    assert child.status_code == 403


# Snapshot per group (T-06-04) and account reconciliation only as NC admin (T-06-03)

W1 = "aaaaaaaaaaa1"
GONE = "gw-geloescht"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    """A household after the update: group admin with admin, teachers configured as an additional group."""
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    # An account that Nextcloud does not (or no longer) deliver: for the teacher it would look deleted (404).
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
    """Like Nextcloud: the teacher may not read the group admin (403), but his own."""
    fake_directory.answers[(LEHRER, ADMIN_GROUP)] = DirectoryRejectedError("403")
    return fake_directory


def _raw_snapshot(db: Path) -> dict[str, list[str]]:
    """State per group straight from SQLite (own path, not via group_snapshot)."""
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
    # Each group individually on behalf of the teacher; the 403 on admin does not empty its state.
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
    # admin is read and replaced, lehrkraefte stays as it was because of the outage.
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin", "papa"], "lehrkraefte": [LEHRER, "gw-lehrer2"]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER, "gw-lehrer2", "papa"]


async def test_verify_with_teacher_only_confirms_teacher_and_no_nc_admin(
    service: WorldService, school: FakeDirectory, app_env: Path
) -> None:
    acting = await TimeService(service, school).verify_admins([LEHRER])
    assert acting == LEHRER
    # The admin state stays: only a refused candidate without a right to admin arrived there.
    assert _raw_snapshot(_db(app_env)) == {"admin": ["admin"], "lehrkraefte": [LEHRER]}
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER]
    # Without a fresh answer of the group admin there is no confirmed NC admin.
    assert _raw_meta(_db(app_env), META_NC_ADMINS) == []


async def test_verify_with_admin_records_nc_admins(service: WorldService, school: FakeDirectory, app_env: Path) -> None:
    acting = await TimeService(service, school).verify_admins(["admin", LEHRER])
    assert acting == "admin"
    assert _raw_meta(_db(app_env), META_NC_ADMINS) == ["admin"]
    assert _raw_meta(_db(app_env), META_TIME_ADMINS) == ["admin", LEHRER]


async def test_verify_never_confirms_rejected_account(
    service: WorldService, school: FakeDirectory, store: WorldStore, app_env: Path
) -> None:
    # A former teacher is still in the state, Nextcloud refuses him every group.
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
    # admin keeps the first day, the teacher gets today's.
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
    """Negative test with the real account reconciliation: no call on behalf of the teacher, nothing forgotten."""
    monkeypatch.setattr(loop, "MAINTENANCE", [(loop.purge_accounts, True)])
    store.set_meta(META_NC_ADMINS, "[]")
    await loop.run_hooks(service, LEHRER)
    assert school.calls == []
    assert school.group_calls == []
    assert store.get_player(GONE) is not None


async def test_stale_nc_admin_entry_is_checked_fresh_before_purge(
    service: WorldService, store: WorldStore, school: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the teacher is in nc_admins (stale or tampered), the reconciliation checks fresh and leaves it."""
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
    """Whole maintenance run: the teacher alone forgets nothing; with admin (positive control) GONE is forgotten."""
    monkeypatch.setattr(loop, "MAINTENANCE", [(loop.purge_accounts, True)])
    store.set_meta(META_TIME_ADMINS, json.dumps(candidates))
    if "admin" not in candidates:
        # The teacher alone cannot read the group admin: its state stays, he does not get into nc_admins.
        school.groups["admin"] = ["admin"]
    await loop.maintain_once(service, school)
    assert loop.LOOP_STATE.acting == candidates[0]
    assert (store.get_player(GONE) is None) is forgotten
    # The uninvolved child always stays.
    assert store.get_player("gw-kind") is not None
    purge_actors = {acting for acting, _uid in school.calls}
    assert purge_actors == ({"admin"} if forgotten else set())


# Admin API of the manager groups (06-02, D-02, T-06-07, T-06-11) and /api/me (T-06-10)

ADMIN_PATHS = [
    ("GET", "/api/admin/verwalter-groups", None),
    ("POST", "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"}),
    ("POST", "/api/admin/verwalter-groups/remove", {"gid": "lehrkraefte"}),
    ("GET", "/api/admin/groups?search=leh", None),
]


@pytest.fixture
def admin_api(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    """Empty household with a real group source; W1 created admin (no owner_uid on worlds)."""
    from gameworld.main import APP

    world_store = WorldStore(_db(app_env))
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER})
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    _new_mod(provisioner, W1)
    world_service = WorldService(world_store, cast(DockerProvisioner, provisioner), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, lambda: world_service)
    monkeypatch.setattr(
        roles,
        "_role_service",
        RoleService(fake_lookup, roles._stored_verwalter_groups),  # pyright: ignore[reportPrivateUsage]
    )
    monkeypatch.setattr(worlds, "_service", world_service)
    return world_service


async def _post(client: httpx.AsyncClient, path: str, body: object, user: str = "admin") -> httpx.Response:
    return await client.post(path, json=body, headers=appapi_headers(user))


@pytest.mark.usefixtures("admin_api")
async def test_admin_reads_empty_verwalter_groups(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/admin/verwalter-groups", headers=appapi_headers())
    assert response.status_code == 200
    assert response.json() == {"groups": []}


@pytest.mark.usefixtures("admin_api")
async def test_add_and_remove_take_effect_without_waiting(client: httpx.AsyncClient, app_env: Path) -> None:
    db = _db(app_env)
    # Before: the teacher is a player (and his profile is now in the 30 s cache).
    assert (await client.get("/api/worlds", headers=appapi_headers(LEHRER))).status_code == 403

    added = await _post(client, "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"})
    assert added.status_code == 200
    assert added.json() == {"groups": ["lehrkraefte"]}
    assert _raw_meta(db, META_VERWALTER_GROUPS) == ["lehrkraefte"]
    assert (await client.get("/api/worlds", headers=appapi_headers(LEHRER))).status_code == 200
    # Manager state re-read without throttle: lehrkraefte now has a state.
    assert _raw_snapshot(db).get("lehrkraefte") == [LEHRER]

    removed = await _post(client, "/api/admin/verwalter-groups/remove", {"gid": "lehrkraefte"})
    assert removed.status_code == 200
    assert removed.json() == {"groups": []}
    assert _raw_meta(db, META_VERWALTER_GROUPS) == []
    assert (await client.get("/api/worlds", headers=appapi_headers(LEHRER))).status_code == 403
    assert "lehrkraefte" not in _raw_snapshot(db)


@pytest.mark.usefixtures("admin_api")
async def test_add_is_idempotent_and_remove_of_unknown_keeps_list(client: httpx.AsyncClient, app_env: Path) -> None:
    assert (await _post(client, "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"})).status_code == 200
    again = await _post(client, "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"})
    assert again.json() == {"groups": ["lehrkraefte"]}
    other = await _post(client, "/api/admin/verwalter-groups/remove", {"gid": "gibt-es-nicht"})
    assert other.status_code == 200
    assert other.json() == {"groups": ["lehrkraefte"]}
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) == ["lehrkraefte"]


@pytest.mark.usefixtures("admin_api")
@pytest.mark.parametrize(
    ("path", "body", "detail"),
    [
        ("/api/admin/verwalter-groups/add", {"gid": "unbekannt"}, "Diese Gruppe gibt es in Nextcloud nicht."),
        ("/api/admin/verwalter-groups/add", {"gid": "admin"}, "Die Gruppe admin verwaltet Gameworld immer."),
        ("/api/admin/verwalter-groups/remove", {"gid": "admin"}, "Die Gruppe admin verwaltet Gameworld immer."),
    ],
)
async def test_invalid_group_changes_are_422_without_meta_change(
    client: httpx.AsyncClient, app_env: Path, path: str, body: dict[str, str], detail: str
) -> None:
    response = await _post(client, path, body)
    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) is None


@pytest.mark.usefixtures("admin_api")
@pytest.mark.parametrize(
    "body",
    [
        {"gid": "lehrkraefte", "extra": 1},
        {"gid": ""},
        {"gid": "x" * 65},
        {"gid": "leh​rkraefte"},
        {},
    ],
)
async def test_bad_bodies_are_422(client: httpx.AsyncClient, app_env: Path, body: dict[str, object]) -> None:
    response = await _post(client, "/api/admin/verwalter-groups/add", body)
    assert response.status_code == 422
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) is None


async def test_concurrent_change_gives_409(
    client: httpx.AsyncClient, admin_api: WorldService, app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []

    def always_conflict(key: str, expected: str | None, value: str) -> bool:
        attempts.append(key)
        return False

    monkeypatch.setattr(admin_api.store, "compare_and_set_meta", always_conflict)
    response = await _post(client, "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"})
    assert response.status_code == 409
    assert response.json() == {"detail": "Die Verwalter-Gruppen wurden gerade geändert. Bitte neu laden."}
    assert attempts == [META_VERWALTER_GROUPS, META_VERWALTER_GROUPS]
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) is None


@pytest.mark.usefixtures("admin_api")
async def test_group_search(client: httpx.AsyncClient, fake_directory: FakeDirectory) -> None:
    response = await client.get("/api/admin/groups?search=leh", headers=appapi_headers())
    assert response.status_code == 200
    assert response.json() == {"groups": [{"id": "lehrkraefte", "display_name": "Lehrkräfte"}]}
    assert fake_directory.search_calls == [("admin", "leh", 20)]
    for index in range(30):
        fake_directory.groups[f"gruppe{index:02d}"] = []
    many = await client.get("/api/admin/groups?search=gruppe", headers=appapi_headers())
    assert len(many.json()["groups"]) == 20
    too_long = await client.get(f"/api/admin/groups?search={'x' * 65}", headers=appapi_headers())
    assert too_long.status_code == 422
    fake_directory.search_error = DirectoryUnavailableError("weg")
    down = await client.get("/api/admin/groups?search=leh", headers=appapi_headers())
    assert down.status_code == 503
    assert down.json() == {"detail": "Die Gruppensuche in Nextcloud ist gerade nicht möglich."}


@pytest.mark.usefixtures("admin_api")
async def test_add_with_nextcloud_down_is_503(
    client: httpx.AsyncClient, fake_directory: FakeDirectory, app_env: Path
) -> None:
    fake_directory.error = DirectoryUnavailableError("weg")
    response = await _post(client, "/api/admin/verwalter-groups/add", {"gid": "lehrkraefte"})
    assert response.status_code == 503
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) is None


@pytest.mark.parametrize("user", [LEHRER, "gw-kind", "gw-kind-k"])
@pytest.mark.parametrize(("method", "path", "body"), ADMIN_PATHS)
async def test_admin_routes_are_403_for_everyone_but_nc_admins(
    client: httpx.AsyncClient,
    admin_api: WorldService,
    fake_directory: FakeDirectory,
    app_env: Path,
    user: str,
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    # The teacher is a manager (lehrkraefte configured), but no NC admin.
    _write_meta_raw(_db(app_env), json.dumps(["lehrkraefte"]))
    assert (await client.get("/api/worlds", headers=appapi_headers(LEHRER))).status_code == 200
    fake_directory.group_calls.clear()
    response = await client.request(method, path, json=body, headers=appapi_headers(user))
    assert response.status_code == 403
    assert response.json() == {"detail": MSG_NC_ADMIN_ONLY}
    assert _raw_meta(_db(app_env), META_VERWALTER_GROUPS) == ["lehrkraefte"]
    assert fake_directory.search_calls == []
    assert fake_directory.group_calls == []
    del admin_api


@pytest.mark.usefixtures("admin_api")
@pytest.mark.parametrize(("method", "path", "body"), ADMIN_PATHS)
async def test_admin_routes_are_503_on_lookup_failure(
    client: httpx.AsyncClient,
    role_lookup_error: list[str],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    response = await client.request(method, path, json=body, headers=appapi_headers())
    assert response.status_code == 503
    assert role_lookup_error == ["admin"]


@pytest.mark.usefixtures("admin_api")
async def test_me_carries_nc_admin_and_invite_groups(client: httpx.AsyncClient, app_env: Path) -> None:
    _write_meta_raw(_db(app_env), json.dumps(["lehrkraefte"]))
    admin = (await client.get("/api/me", headers=appapi_headers())).json()
    assert (admin["role"], admin["nc_admin"], admin["invite_groups"]) == (ROLE_VERWALTER, True, ["admin"])
    teacher = (await client.get("/api/me", headers=appapi_headers(LEHRER))).json()
    assert teacher == {
        "user_id": LEHRER,
        "display_name": "Lehrer (Dev)",
        "role": ROLE_VERWALTER,
        "nc_admin": False,
        "invite_groups": ["klasse", "lehrkraefte"],
        "language": "de",
    }
    child = (await client.get("/api/me", headers=appapi_headers("gw-kind-k"))).json()
    assert (child["role"], child["nc_admin"], child["invite_groups"]) == (ROLE_SPIELER, False, [])


@pytest.mark.usefixtures("admin_api")
async def test_teacher_manages_all_worlds_and_household_settings(client: httpx.AsyncClient, app_env: Path) -> None:
    """D-03/D-04: managers from lehrkraefte see all worlds and operate household settings."""
    _write_meta_raw(_db(app_env), json.dumps(["lehrkraefte"]))
    headers = appapi_headers(LEHRER)
    listed = await client.get("/api/worlds", headers=headers)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["worlds"]] == [W1]
    assert (await client.post("/api/settings", json={"join_host": "spiel.example"}, headers=headers)).status_code == 200
    assert (await client.post("/api/pause", json={"minutes": 15}, headers=headers)).status_code == 200
    holiday = {"label": "Ferien", "start_date": "2026-12-21", "end_date": "2027-01-06"}
    assert (await client.post("/api/playtime/holidays", json=holiday, headers=headers)).status_code == 200
    zone = await client.post("/api/playtime/time-zone", json={"time_zone": "Europe/Vienna"}, headers=headers)
    assert zone.status_code == 200
    # Cross-check: the same as a child of the class stays locked.
    child = appapi_headers("gw-kind-k")
    assert (await client.post("/api/pause", json={"minutes": 15}, headers=child)).status_code == 403
