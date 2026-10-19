"""Schema-Migration der Welt-Datenbank (Schema 1 auf 2 auf 3) und Zugangsdaten."""

import pathlib
import sqlite3

import pytest

from gameworld.worlds.store import InviteRow, PlayerRow, WorldRow, WorldStore

# Phase-1-DDL wörtlich, damit die Migration gegen eine echte Altdatei läuft.
SCHEMA_1 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE worlds (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  port INTEGER NOT NULL UNIQUE,
  container_name TEXT NOT NULL UNIQUE,
  volume_name TEXT NOT NULL UNIQUE,
  world_key TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  desired_state TEXT NOT NULL,
  op_state TEXT NOT NULL,
  last_error TEXT,
  created_at TEXT NOT NULL
);
INSERT INTO meta (key, value) VALUES ('schema_version', '1');
INSERT INTO worlds VALUES ('w1', 'Alte Welt', 30001, 'gw-a-w1', 'gw-a-w1', 'k', '5.17.0',
  'running', 'ready', NULL, '2026-10-01T10:00:00+00:00');
"""


def _schema_version(db: pathlib.Path) -> str:
    connection = sqlite3.connect(db)
    try:
        return str(connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0])
    finally:
        connection.close()


def _schema_1(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "gameworld.sqlite3"
    connection = sqlite3.connect(db)
    try:
        connection.executescript(SCHEMA_1)
        connection.commit()
    finally:
        connection.close()
    return db


def _row(world_id: str, port: int, preset: str) -> WorldRow:
    return WorldRow(
        id=world_id,
        name="Neue Welt",
        port=port,
        container_name=f"gw-a-{world_id}",
        volume_name=f"gw-a-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-19T10:00:00+00:00",
        preset=preset,
    )


def test_schema_1_is_migrated_to_3(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "3"
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.preset == "mtg_kreativ"


def test_migrate_twice_is_noop(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == "3"
    assert [row.id for row in store.list_worlds()] == ["w1"]


def test_fresh_file_gets_schema_3(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "neu" / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "3"
    store.insert_world(_row("w2", 30002, "anderes_preset"))
    world = store.get_world("w2")
    assert world is not None
    assert world.preset == "anderes_preset"


# Schema 3 (03-03): Spieler, Einladungen, Zugang je Welt, ohne Passwortfeld (A3).

SCHEMA_2_EXTRA = """
ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ';
UPDATE meta SET value = '2' WHERE key = 'schema_version';
"""


def _schema_2(tmp_path: pathlib.Path) -> pathlib.Path:
    db = _schema_1(tmp_path)
    connection = sqlite3.connect(db)
    try:
        connection.executescript(SCHEMA_2_EXTRA)
        connection.commit()
    finally:
        connection.close()
    return db


def _columns(db: pathlib.Path, table: str) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return [str(info[1]) for info in connection.execute(f"PRAGMA table_info({table})").fetchall()]
    finally:
        connection.close()


def _tables(db: pathlib.Path) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return [str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    finally:
        connection.close()


def _store3(tmp_path: pathlib.Path) -> WorldStore:
    store = WorldStore(tmp_path / "gameworld.sqlite3")
    store.migrate()
    store.insert_world(_row("w1", 30001, "mtg_kreativ"))
    store.insert_world(_row("w2", 30002, "mtg_kreativ"))
    return store


def test_schema_2_is_migrated_to_3(tmp_path: pathlib.Path) -> None:
    db = _schema_2(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == "3"
    assert {"players", "invites", "world_access"} <= set(_tables(db))
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.access_generation == 0


def test_players_have_no_password_column(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    del store
    db = tmp_path / "gameworld.sqlite3"
    assert _columns(db, "players") == ["nc_user", "player_name", "rotation"]
    for table in _tables(db):
        assert not [column for column in _columns(db, table) if "pass" in column.lower()], table


def test_player_name_is_unique_case_insensitive(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.insert_player(PlayerRow("a", "Mia", 0))
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_player(PlayerRow("b", "mia", 0))
    assert store.player_names() == {"mia"}
    player = store.get_player("a")
    assert player == PlayerRow("a", "Mia", 0)
    assert store.get_player("b") is None


def test_invites_roundtrip(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.add_invite("w1", "user", "gw-kind", "admin", "2026-10-20T10:00:00+00:00")
    store.add_invite("w1", "user", "gw-kind", "admin", "2026-10-20T11:00:00+00:00")
    invites = store.list_invites("w1")
    assert invites == [InviteRow("w1", "user", "gw-kind", "admin", "2026-10-20T10:00:00+00:00")]
    assert store.list_invites("w2") == []
    assert store.remove_invite("w1", "user", "gw-kind") is True
    assert store.remove_invite("w1", "user", "gw-kind") is False
    with pytest.raises(sqlite3.IntegrityError):
        store.add_invite("w1", "kanal", "x", "admin", "t")


def test_apply_world_access_bumps_generation(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.insert_player(PlayerRow("gw-kind", "Kind", 0))
    assert store.apply_world_access("w1", {"gw-kind": "#1#AA==#BB=="}) == 1
    assert store.world_access("w1") == {"gw-kind": "#1#AA==#BB=="}
    assert store.access_entries("w1") == {"Kind": "#1#AA==#BB=="}
    assert store.world_access("w2") == {}
    assert store.apply_world_access("w1", {}) == 2
    assert store.access_entries("w1") == {}
    world = store.get_world("w1")
    assert world is not None
    assert world.access_generation == 2


def test_delete_access_data_only_touches_one_world(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.insert_player(PlayerRow("gw-kind", "Kind", 0))
    for world_id in ("w1", "w2"):
        store.add_invite(world_id, "user", "gw-kind", "admin", "t")
        store.apply_world_access(world_id, {"gw-kind": "#1#AA==#BB=="})
    store.delete_access_data("w1")
    assert store.list_invites("w1") == []
    assert store.world_access("w1") == {}
    assert len(store.list_invites("w2")) == 1
    assert store.world_access("w2") == {"gw-kind": "#1#AA==#BB=="}
    assert store.get_player("gw-kind") is not None
