"""Forget deleted Nextcloud accounts (purge_missing_accounts, forget_account, schema 6).

Finding on the dev stack: a deleted account lost access immediately, but its
player row, direct invitations, play time and review stayed behind. If an admin
later created an account with the same ID, the old invitation worked again,
and with rotation 0 the game password was that of the deleted account.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
from datetime import date
from pathlib import Path
from typing import cast

import pytest

from gameworld.access.accounts import derive_password
from gameworld.access.directory import DirectoryUnavailableError, DirectoryUser
from gameworld.access.roles import Profile
from gameworld.access.service import AccessService
from gameworld.config import load_settings
from gameworld.notify import loop
from gameworld.playtime.service import META_NC_ADMINS
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import ACCOUNT_TABLES, SCHEMA_VERSION, PlayerRow, WorldRow, WorldStore
from tests.conftest import ADMIN_ACTOR, TEST_SECRET, FakeDirectory, StaticSecret, give_rules
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
GONE = "gw-alt"
DAY = date(2026, 10, 22)
# Computed independently (see tests/test_accounts.py): previous derivation without salt.
VECTOR_GW_KIND_0 = "nyd5-hh9q-u45t"


def _world(world_id: str, port: int) -> WorldRow:
    return WorldRow(
        id=world_id,
        name=f"Welt {world_id}",
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-20T10:00:00+00:00",
    )


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "exited")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_world(W1, 30015))
    world_store.insert_world(_world(W2, 30016))
    # admin is a confirmed NC admin (as after verify_admins); without this state
    # purge_missing_accounts rejects every reconciliation (06-02, own negative test).
    world_store.set_meta(META_NC_ADMINS, json.dumps(["admin"]))
    return world_store


@pytest.fixture
def worlds(store: WorldStore, fake: FakeProvisioner) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, fake), load_settings())


@pytest.fixture
def access(
    store: WorldStore, worlds: WorldService, fake_directory: FakeDirectory, fake_secret: StaticSecret
) -> AccessService:
    return AccessService(store, worlds, fake_directory, fake_secret)


def _rows_of(db: Path, nc_user: str) -> dict[str, int]:
    """Rows per table that belong to the account (own query, not via forget_account)."""
    connection = sqlite3.connect(db)
    try:
        counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table} WHERE nc_user = ?", (nc_user,)).fetchone()[0])  # noqa: S608
            for table in ACCOUNT_TABLES
        }
        counts["invites"] = int(
            connection.execute(
                "SELECT COUNT(*) FROM invites WHERE kind = 'user' AND target = ?", (nc_user,)
            ).fetchone()[0]
        )
    finally:
        connection.close()
    return counts


def _all_tables_with_nc_user(db: Path) -> set[str]:
    connection = sqlite3.connect(db)
    try:
        tables = [str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        return {
            table
            for table in tables
            if "nc_user" in {str(info[1]) for info in connection.execute(f"PRAGMA table_info({table})")}
        }
    finally:
        connection.close()


def _last_access_file(fake: FakeProvisioner, world_id: str) -> str:
    content = ""
    for written_world, archive in fake.written:
        if written_world != world_id:
            continue
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            if ACCESS_FILE_NAME not in tar.getnames():
                continue
            member = tar.extractfile(ACCESS_FILE_NAME)
            assert member is not None
            content = member.read().decode("ascii")
    return content


def _generation(store: WorldStore, world_id: str) -> int:
    row = store.get_world(world_id)
    assert row is not None
    return row.access_generation


async def _populate_gone(access: AccessService, store: WorldStore, fake_directory: FakeDirectory) -> None:
    """GONE as a child with everything an account can accumulate; gw-kind as an uninvolved positive control."""
    fake_directory.users[GONE] = ("Mia Lena", True)
    for world_id in (W1, W2):
        await access.invite_user(world_id, ADMIN_ACTOR, GONE)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    for uid in (GONE, "gw-kind"):
        give_rules(store, uid)
        store.add_usage(uid, DAY, 600)
        store.book_usage(W1, DAY, {}, {}, play={uid: 300})
        store.set_review_pref(uid, enabled=False, minute=1100)
        store.claim_review(uid, DAY)
        store.set_bot_presence(W1, uid, "join", 100)


def _db(app_env: Path) -> Path:
    return app_env / "gameworld.sqlite3"


def _mark_adult(db: Path, nc_user: str) -> None:
    """Adult row directly in SQLite (own path, not via a store method, P-08)."""
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT INTO adults (nc_user, set_by, set_at) VALUES (?, 'admin', '2026-10-24T08:00:00+00:00')",
            (nc_user,),
        )
        connection.commit()
    finally:
        connection.close()


async def test_deleted_account_is_forgotten_completely_and_name_freed(
    access: AccessService,
    store: WorldStore,
    fake: FakeProvisioner,
    fake_directory: FakeDirectory,
    app_env: Path,
) -> None:
    await _populate_gone(access, store, fake_directory)
    _mark_adult(_db(app_env), GONE)
    _mark_adult(_db(app_env), "gw-kind")
    before = _rows_of(_db(app_env), GONE)
    # Precondition: every table really contains something (otherwise emptying would prove nothing).
    assert all(count > 0 for count in before.values()), before
    kept_before = _rows_of(_db(app_env), "gw-kind")
    player = store.get_player(GONE)
    assert player is not None
    assert player.player_name == "Mia"
    generations = (_generation(store, W1), _generation(store, W2))
    del fake_directory.users[GONE]

    assert await access.purge_missing_accounts("admin") == [GONE]

    assert set(_rows_of(_db(app_env), GONE).values()) == {0}
    # Uninvolved account unchanged (no deletion beyond the target).
    assert _rows_of(_db(app_env), "gw-kind") == kept_before
    assert store.get_player(GONE) is None
    assert GONE not in {p.nc_user for p in store.list_players()}
    assert "mia" not in store.player_names()
    # Access files rewritten without the account; generation incremented.
    assert _generation(store, W1) == generations[0] + 1
    assert _generation(store, W2) == generations[1] + 1
    assert "Mia" not in _last_access_file(fake, W1)
    assert "Kind " in _last_access_file(fake, W1)
    assert "Mia" not in _last_access_file(fake, W2)
    # The name is free: a new account with the same display name is called Mia again, not Mia2.
    fake_directory.users["gw-neu"] = ("Mia Sophie", True)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-neu")
    newcomer = store.get_player("gw-neu")
    assert newcomer is not None
    assert newcomer.player_name == "Mia"


def test_forget_account_removes_adult_flag_set_via_store(store: WorldStore) -> None:
    """ROLLE-04/P-08: the adult marker goes with the account, that of another stays."""
    store.set_adult(GONE, set_by="admin", set_at="2026-10-24T08:00:00+00:00")
    store.set_adult("gw-kind", set_by="admin", set_at="2026-10-24T08:00:00+00:00")
    assert store.adults() == {GONE, "gw-kind"}

    assert store.forget_account(GONE) is True

    assert store.adults() == {"gw-kind"}


def test_forget_account_covers_every_table_with_nc_user(app_env: Path, store: WorldStore) -> None:
    """Guard: a future table with nc_user must deliberately go into ACCOUNT_TABLES (or be excepted here)."""
    del store
    assert _all_tables_with_nc_user(_db(app_env)) == set(ACCOUNT_TABLES)


async def test_disabled_account_stays(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory, app_env: Path
) -> None:
    await _populate_gone(access, store, fake_directory)
    before = _rows_of(_db(app_env), GONE)
    fake_directory.users[GONE] = ("Mia Lena", False)

    assert await access.purge_missing_accounts("admin") == []

    assert _rows_of(_db(app_env), GONE) == before
    assert store.get_player(GONE) is not None


async def test_directory_failure_deletes_nothing(
    access: AccessService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    app_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure at a later account: even the GONE already recognized as deleted stays."""
    await _populate_gone(access, store, fake_directory)
    before = _rows_of(_db(app_env), GONE)
    kept_before = _rows_of(_db(app_env), "gw-kind")
    del fake_directory.users[GONE]
    original = fake_directory.user

    async def flaky(acting_uid: str, uid: str) -> DirectoryUser | None:
        if uid == "gw-kind":
            raise DirectoryUnavailableError("weg")
        return await original(acting_uid, uid)

    monkeypatch.setattr(fake_directory, "user", flaky)
    with pytest.raises(DirectoryUnavailableError):
        await access.purge_missing_accounts("admin")

    # GONE was queried before the failure (sorted before gw-kind) and still not deleted.
    assert ("admin", GONE) in fake_directory.calls
    assert _rows_of(_db(app_env), GONE) == before
    assert _rows_of(_db(app_env), "gw-kind") == kept_before


async def test_total_failure_deletes_nothing(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory, app_env: Path
) -> None:
    await _populate_gone(access, store, fake_directory)
    before = _rows_of(_db(app_env), GONE)
    del fake_directory.users[GONE]
    fake_directory.error = DirectoryUnavailableError("weg")
    with pytest.raises(DirectoryUnavailableError):
        await access.purge_missing_accounts("admin")
    assert _rows_of(_db(app_env), GONE) == before


async def test_unconfirmed_acting_admin_deletes_nothing(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory, app_env: Path
) -> None:
    """Positive control: if Nextcloud itself reports the acting manager as missing, nothing is deleted."""
    await _populate_gone(access, store, fake_directory)
    before = _rows_of(_db(app_env), GONE)
    kept_before = _rows_of(_db(app_env), "gw-kind")
    # Like a misconfiguration that reports every account as 404.
    fake_directory.users.clear()
    assert await access.purge_missing_accounts("admin") == []
    assert _rows_of(_db(app_env), GONE) == before
    assert _rows_of(_db(app_env), "gw-kind") == kept_before


async def test_recreated_account_has_no_access_and_other_password(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    await _populate_gone(access, store, fake_directory)
    profile = Profile(user_id=GONE, display_name="Mia Lena", groups=())
    [old, _second] = await access.my_worlds(profile)
    old_password = old.password
    del fake_directory.users[GONE]
    assert await access.purge_missing_accounts("admin") == [GONE]

    # An admin creates an account with the same ID again: without a new invitation no access.
    fake_directory.users[GONE] = ("Mia Lena", True)
    for world_id in (W1, W2):
        await access.sync_world(world_id, ADMIN_ACTOR)
    assert GONE not in store.world_access(W1)
    assert GONE not in store.world_access(W2)
    assert await access.my_worlds(profile) == []

    # Invited again: new row with rotation 0, but a different password than the deleted account.
    await access.invite_user(W1, ADMIN_ACTOR, GONE)
    player = store.get_player(GONE)
    assert player is not None
    assert player.rotation == 0
    assert player.salt
    [fresh] = await access.my_worlds(profile)
    assert fresh.password != old_password
    assert fresh.password != derive_password(TEST_SECRET, GONE, 0)


async def test_new_players_get_individual_salt(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.users[GONE] = ("Mia Lena", True)
    await access.invite_user(W1, ADMIN_ACTOR, GONE)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    first, second = store.get_player(GONE), store.get_player("gw-kind")
    assert first is not None
    assert second is not None
    assert len(first.salt) == 32
    assert len(second.salt) == 32
    assert first.salt != second.salt


async def test_existing_row_without_salt_keeps_exact_password(access: AccessService, store: WorldStore) -> None:
    """Row from schema 5 (empty salt): password stays the previous one, even after an invitation to a world."""
    store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Kind", rotation=0))
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    player = store.get_player("gw-kind")
    assert player is not None
    assert player.salt == ""
    [world] = await access.my_worlds(Profile(user_id="gw-kind", display_name="Kind (Dev)", groups=()))
    assert world.password == VECTOR_GW_KIND_0
    [listed] = await access.list_players(W1, ADMIN_ACTOR)
    assert listed.password == VECTOR_GW_KIND_0


async def test_no_directory_calls_under_world_lock(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    await _populate_gone(access, store, fake_directory)
    del fake_directory.users[GONE]
    fake_directory.user_lock_held.clear()
    fake_directory.lock_held.clear()
    assert await access.purge_missing_accounts("admin") == [GONE]
    # Manager, GONE and gw-kind were queried, no query under the lock.
    assert len(fake_directory.user_lock_held) >= 3
    assert not any(fake_directory.user_lock_held)
    assert not any(fake_directory.lock_held)


async def test_maintenance_hook_forgets_deleted_account(
    access: AccessService, store: WorldStore, worlds: WorldService, fake_directory: FakeDirectory
) -> None:
    hooks = [hook for hook, _needs_nc_admin in loop.MAINTENANCE]
    assert hooks.index(loop.purge_accounts) < hooks.index(loop.talk_reconcile)
    # The account reconciliation needs a confirmed Nextcloud admin (F-04), the Talk reconciliation does not.
    assert dict(loop.MAINTENANCE) == {loop.purge_accounts: True, loop.talk_reconcile: False}
    await _populate_gone(access, store, fake_directory)
    del fake_directory.users[GONE]
    await loop.purge_accounts(worlds, "admin")
    assert store.get_player(GONE) is None
    assert store.get_player("gw-kind") is not None


# Schema 5 to 6


def _schema_5_file(tmp_path: Path) -> Path:
    """Real schema 5 file: today's schema without players.salt, with one player."""
    db = tmp_path / "gameworld.sqlite3"
    WorldStore(db).migrate()
    connection = sqlite3.connect(db)
    try:
        connection.execute("ALTER TABLE players DROP COLUMN salt")
        connection.execute("INSERT INTO players (nc_user, player_name, rotation) VALUES ('gw-kind', 'Kind', 2)")
        connection.execute("UPDATE meta SET value = '5' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()
    return db


def _player_columns(db: Path) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return [str(info[1]) for info in connection.execute("PRAGMA table_info(players)")]
    finally:
        connection.close()


def _version(db: Path) -> str:
    connection = sqlite3.connect(db)
    try:
        return str(connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
    finally:
        connection.close()


def test_schema_5_is_migrated_to_6_keeps_player_and_password(tmp_path: Path) -> None:
    db = _schema_5_file(tmp_path)
    assert "salt" not in _player_columns(db)
    assert _version(db) == "5"
    store = WorldStore(db)
    store.migrate()
    assert _version(db) == SCHEMA_VERSION
    assert _player_columns(db) == ["nc_user", "player_name", "rotation", "salt"]
    player = store.get_player("gw-kind")
    assert player is not None
    assert player == PlayerRow("gw-kind", "Kind", 2, "")
    assert derive_password(TEST_SECRET, player.nc_user, player.rotation, player.salt) == derive_password(
        TEST_SECRET, "gw-kind", 2
    )
    # Can be called repeatedly, nothing is lost.
    store.migrate()
    assert store.get_player("gw-kind") == PlayerRow("gw-kind", "Kind", 2, "")
