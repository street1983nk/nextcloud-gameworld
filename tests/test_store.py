"""Schema-Migration der Welt-Datenbank (Schema 1 auf 2 auf 3 auf 4) und Zugangsdaten."""

import pathlib
import sqlite3
from datetime import date

import pytest

from gameworld.playtime.plan import DayRule, Holiday, WeekPlan
from gameworld.worlds.store import TIME_TABLES, InviteRow, PlayerRow, WorldRow, WorldStore

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
    assert _schema_version(db) == "4"
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.preset == "mtg_kreativ"


def test_migrate_twice_is_noop(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == "4"
    assert [row.id for row in store.list_worlds()] == ["w1"]


def test_fresh_file_gets_schema_4(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "neu" / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "4"
    assert TIME_TABLES.issubset(_tables(db))
    store.insert_world(_row("w2", 30002, "anderes_preset"))
    world = store.get_world("w2")
    assert world is not None
    assert world.preset == "anderes_preset"
    assert world.time_generation == 0


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
    assert _schema_version(db) == "4"
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


# Schema 4 (04-02): Spielzeit-Regeln, Ferien, Welt-Fenster, Verbrauch, Zählbuchstände.

# Echte Schema-3-DDL mit Daten, damit die Migration 3 auf 4 gegen Altbestand läuft.
SCHEMA_3 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE worlds (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, port INTEGER NOT NULL UNIQUE,
  container_name TEXT NOT NULL UNIQUE, volume_name TEXT NOT NULL UNIQUE, world_key TEXT NOT NULL,
  engine_version TEXT NOT NULL, desired_state TEXT NOT NULL, op_state TEXT NOT NULL, last_error TEXT,
  created_at TEXT NOT NULL, preset TEXT NOT NULL DEFAULT 'mtg_kreativ',
  access_generation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE players (nc_user TEXT PRIMARY KEY, player_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  rotation INTEGER NOT NULL DEFAULT 0);
CREATE TABLE invites (world_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('user', 'group')),
  target TEXT NOT NULL, invited_by TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (world_id, kind, target));
CREATE TABLE world_access (world_id TEXT NOT NULL, nc_user TEXT NOT NULL, verifier TEXT NOT NULL,
  PRIMARY KEY (world_id, nc_user));
INSERT INTO meta (key, value) VALUES ('schema_version', '3');
INSERT INTO worlds VALUES ('w1', 'Alte Welt', 30001, 'gw-a-w1', 'gw-a-w1', 'k', '5.17.0',
  'running', 'ready', NULL, '2026-10-01T10:00:00+00:00', 'mtg_kreativ', 2);
INSERT INTO players VALUES ('gw-kind', 'Mia', 1);
INSERT INTO invites VALUES ('w1', 'user', 'gw-kind', 'admin', '2026-10-01T10:00:00+00:00');
INSERT INTO world_access VALUES ('w1', 'gw-kind', '#1#AA==#BB==');
"""


def _schema_3_file(tmp_path: pathlib.Path) -> pathlib.Path:
    db = tmp_path / "gameworld.sqlite3"
    connection = sqlite3.connect(db)
    try:
        connection.executescript(SCHEMA_3)
        connection.commit()
    finally:
        connection.close()
    return db


def _week(allowed: bool = True, limit: int | None = 60, start: int | None = 900, end: int | None = 1140) -> WeekPlan:
    return WeekPlan(days=dict.fromkeys(range(1, 8), DayRule(allowed, limit, start, end)))


def test_schema_3_is_migrated_to_4_keeps_data(tmp_path: pathlib.Path) -> None:
    db = _schema_3_file(tmp_path)
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "4"
    assert TIME_TABLES.issubset(_tables(db))
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.access_generation == 2
    assert world.time_generation == 0
    assert store.get_player("gw-kind") == PlayerRow("gw-kind", "Mia", 1)
    assert len(store.list_invites("w1")) == 1
    assert store.world_access("w1") == {"gw-kind": "#1#AA==#BB=="}


def test_schema_3_to_4_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _schema_3_file(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == "4"
    assert [row.id for row in store.list_worlds()] == ["w1"]
    assert store.get_world("w1") is not None


def test_set_child_plan_writes_7_or_14_rows(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    db = tmp_path / "gameworld.sqlite3"
    store.set_child_plan("gw-kind", _week(), None, "admin", "2026-10-20T10:00:00+00:00")
    assert _plan_row_count(db) == 7
    plans = store.child_plans()
    assert set(plans) == {"gw-kind"}
    normal, holiday = plans["gw-kind"]
    assert holiday is None
    assert normal.days[1] == DayRule(True, 60, 900, 1140)
    # Mit Ferienplan: 14 Zeilen, Ferienplan vorhanden.
    store.set_child_plan("gw-kind", _week(), _week(limit=120, start=540, end=1200), "admin", "t2")
    assert _plan_row_count(db) == 14
    normal, holiday = store.child_plans()["gw-kind"]
    assert holiday is not None
    assert holiday.days[7] == DayRule(True, 120, 540, 1200)


def test_clear_child_removes_rules_and_usage(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.set_child_plan("gw-kind", _week(), None, "admin", "t")
    store.add_usage("gw-kind", date(2026, 10, 20), 300)
    store.clear_child("gw-kind")
    assert store.child_plans() == {}
    assert store.usage("gw-kind", date(2026, 10, 20)) == 0


def test_child_plans_only_children_with_rules(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.child_plans() == {}
    store.set_child_plan("gw-kind", _week(allowed=False, limit=None, start=None, end=None), None, "admin", "t")
    assert set(store.child_plans()) == {"gw-kind"}


def test_usage_adds_and_prunes(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.add_usage("gw-kind", date(2026, 10, 20), 300)
    store.add_usage("gw-kind", date(2026, 10, 20), 120)
    assert store.usage("gw-kind", date(2026, 10, 20)) == 420
    store.add_usage("gw-kind", date(2026, 10, 10), 999)
    store.prune_usage(date(2026, 10, 13))
    assert store.usage("gw-kind", date(2026, 10, 10)) == 0
    assert store.usage("gw-kind", date(2026, 10, 20)) == 420


def test_ledger_seen_replaces_atomically(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.set_ledger_seen("w1", {"Mia": 40, "Leo": 7})
    assert store.ledger_seen("w1") == {"Mia": 40, "Leo": 7}
    store.set_ledger_seen("w1", {"Mia": 55})
    assert store.ledger_seen("w1") == {"Mia": 55}
    assert store.ledger_seen("w2") == {}


def test_holidays_crud(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    first = store.add_holiday(date(2026, 10, 24), date(2026, 10, 26), "Herbstferien")
    store.add_holiday(date(2026, 12, 23), date(2027, 1, 6), "Weihnachten")
    holidays = store.list_holidays()
    assert holidays[0] == Holiday(date(2026, 10, 24), date(2026, 10, 26), "Herbstferien")
    assert len(holidays) == 2
    assert store.remove_holiday(first) is True
    assert store.remove_holiday(first) is False
    assert [h.label for h in store.list_holidays()] == ["Weihnachten"]


def test_world_windows(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.world_window("w1") is None
    store.set_world_window("w1", 3, 600, 720)
    store.set_world_window("w1", 3, 600, 780)  # überschreibt denselben Wochentag
    store.set_world_window("w1", 5, 900, 1020)
    assert store.world_window("w1") == {3: (600, 780), 5: (900, 1020)}
    store.clear_world_window("w1")
    assert store.world_window("w1") is None


def test_bump_time_generation(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.bump_time_generation("w1") == 1
    assert store.bump_time_generation("w1") == 2
    world = store.get_world("w1")
    assert world is not None
    assert world.time_generation == 2


def test_delete_time_data_only_touches_one_world(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    for world_id in ("w1", "w2"):
        store.set_world_window(world_id, 1, 600, 720)
        store.set_ledger_seen(world_id, {"Mia": 10})
    store.delete_time_data("w1")
    assert store.world_window("w1") is None
    assert store.ledger_seen("w1") == {}
    assert store.world_window("w2") == {1: (600, 720)}
    assert store.ledger_seen("w2") == {"Mia": 10}


def _plan_row_count(db: pathlib.Path) -> int:
    connection = sqlite3.connect(db)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM time_plans").fetchone()[0])
    finally:
        connection.close()
