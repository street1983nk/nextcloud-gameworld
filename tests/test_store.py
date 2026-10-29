"""Schema migration of the world database (schema 1 to 8), access data, backup records and manager state."""

import pathlib
import sqlite3
from datetime import date

import pytest

from gameworld.playtime.plan import DayRule, Holiday, WeekPlan
from gameworld.worlds.store import (
    BACKUP_TABLES,
    NOTIFY_TABLES,
    OUTBOX_MAX,
    ROLE_TABLES,
    SCHEMA_VERSION,
    TIME_TABLES,
    BackupJobRow,
    BackupRow,
    InviteRow,
    OutboxRow,
    PlayerRow,
    WorldRow,
    WorldStore,
)

# Phase 1 DDL verbatim, so that the migration runs against a real old file.
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
    assert _schema_version(db) == SCHEMA_VERSION
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.preset == "mtg_kreativ"


def test_migrate_twice_is_noop(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert [row.id for row in store.list_worlds()] == ["w1"]


def test_fresh_file_gets_current_schema(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "neu" / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert TIME_TABLES.issubset(_tables(db))
    store.insert_world(_row("w2", 30002, "anderes_preset"))
    world = store.get_world("w2")
    assert world is not None
    assert world.preset == "anderes_preset"
    assert world.time_generation == 0


# Schema 3 (03-03): players, invitations, access per world, without a password field (A3).

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
    assert _schema_version(db) == SCHEMA_VERSION
    assert {"players", "invites", "world_access"} <= set(_tables(db))
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.access_generation == 0


def test_players_have_no_password_column(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    del store
    db = tmp_path / "gameworld.sqlite3"
    assert _columns(db, "players") == ["nc_user", "player_name", "rotation", "salt"]
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


# Schema 4 (04-02): play time rules, holidays, world window, usage, ledger states.

# Real schema 3 DDL with data, so that migration 3 to 4 runs against old data.
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
    assert _schema_version(db) == SCHEMA_VERSION
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
    assert _schema_version(db) == SCHEMA_VERSION
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
    # With a holiday plan: 14 rows, holiday plan present.
    store.set_child_plan("gw-kind", _week(), _week(limit=120, start=540, end=1200), "admin", "t2")
    assert _plan_row_count(db) == 14
    normal, holiday = store.child_plans()["gw-kind"]
    assert holiday is not None
    assert holiday.days[7] == DayRule(True, 120, 540, 1200)


def test_clear_child_removes_rules_and_old_usage_keeps_today(tmp_path: pathlib.Path) -> None:
    """WR-04: rules gone, old usage gone, today's stays (no fresh allowance)."""
    store = _store3(tmp_path)
    store.set_child_plan("gw-kind", _week(), None, "admin", "t")
    store.add_usage("gw-kind", date(2026, 10, 20), 300)
    store.add_usage("gw-kind", date(2026, 10, 21), 1800)
    store.clear_child("gw-kind", keep_from=date(2026, 10, 21))
    assert store.child_plans() == {}
    assert store.usage("gw-kind", date(2026, 10, 20)) == 0
    assert store.usage("gw-kind", date(2026, 10, 21)) == 1800


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
    store.set_world_window("w1", 3, 600, 780)  # overwrites the same weekday
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


# Schema 5 (phase 4.1): notification, pause, review, Talk.


def _schema_4_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Real schema 4 file: today's schema without the tables from schema 5, with data."""
    db = _schema_3_file(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.set_child_plan("gw-kind", _week(), None, "admin", "t")
    store.add_usage("gw-kind", date(2026, 10, 21), 600)
    store.set_ledger_seen("w1", {"Mia": 600})
    connection = sqlite3.connect(db)
    try:
        for table in NOTIFY_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("UPDATE meta SET value = '4' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()
    return db


def test_schema_4_is_migrated_to_5_keeps_data(tmp_path: pathlib.Path) -> None:
    db = _schema_4_file(tmp_path)
    assert _schema_version(db) == "4"
    assert not NOTIFY_TABLES & set(_tables(db))
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert NOTIFY_TABLES.issubset(_tables(db))
    assert TIME_TABLES.issubset(_tables(db))
    world = store.get_world("w1")
    assert world is not None
    assert world.access_generation == 2
    assert store.get_player("gw-kind") == PlayerRow("gw-kind", "Mia", 1)
    assert store.world_access("w1") == {"gw-kind": "#1#AA==#BB=="}
    assert set(store.child_plans()) == {"gw-kind"}
    assert store.usage("gw-kind", date(2026, 10, 21)) == 600
    assert store.ledger_seen("w1") == {"Mia": 600}


def test_schema_4_to_5_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _schema_4_file(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.take_events("w1", 3, [("join", "Mia", 100, "")])
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert store.event_cursor("w1") == 3
    assert len(store.outbox_batch()) == 1


def test_take_events_writes_cursor_and_outbox(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.event_cursor("w1") is None
    store.take_events("w1", 0, [])
    assert store.event_cursor("w1") == 0
    assert store.outbox_batch() == []
    store.take_events("w1", 2, [("join", "Mia", 100, ""), ("leave", "Mia", 200, "")])
    store.add_outbox("w2", "start", "", 150)
    assert store.event_cursor("w1") == 2
    batch = store.outbox_batch()
    assert [(row.world_id, row.kind, row.name, row.at, row.detail) for row in batch] == [
        ("w1", "join", "Mia", 100, ""),
        ("w1", "leave", "Mia", 200, ""),
        ("w2", "start", "", 150, ""),
    ]
    assert all(isinstance(row, OutboxRow) for row in batch)
    assert [row.id for row in store.outbox_batch(limit=2)] == [batch[0].id, batch[1].id]
    store.delete_outbox([batch[0].id, batch[2].id])
    assert [row.id for row in store.outbox_batch()] == [batch[1].id]
    store.delete_outbox([])
    assert len(store.outbox_batch()) == 1


def test_outbox_is_capped_oldest_first(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.take_events("w1", 1, [("deny", "a", 1, "")])
    rows = [("deny", f"n{index}", index, "") for index in range(OUTBOX_MAX + 5)]
    store.take_events("w1", OUTBOX_MAX + 6, rows)
    batch = store.outbox_batch(limit=OUTBOX_MAX + 100)
    assert len(batch) == OUTBOX_MAX
    assert batch[0].name == "n5"
    assert batch[-1].name == f"n{OUTBOX_MAX + 4}"
    store.add_outbox("w1", "stop", "", 9)
    batch = store.outbox_batch(limit=OUTBOX_MAX + 100)
    assert len(batch) == OUTBOX_MAX
    assert batch[0].name == "n6"


def test_run_state_roundtrip(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.run_state("w1") is None
    store.set_run_state("w1", running=True)
    assert store.run_state("w1") is True
    store.set_run_state("w1", running=False)
    assert store.run_state("w1") is False


def test_book_usage_writes_play_daily_in_same_call(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    day = date(2026, 10, 21)
    store.book_usage("w1", day, {"gw-kind": 30}, {"Mia": 30}, play={"gw-kind": 30, "gw-frei": 15})
    store.book_usage("w1", day, {}, {"Mia": 45}, play={"gw-kind": 15})
    store.book_usage("w2", day, {}, {}, play={"gw-kind": 5})
    store.book_usage("w2", day, {}, {})
    assert store.play_seconds(day) == {("gw-kind", "w1"): 45, ("gw-frei", "w1"): 15, ("gw-kind", "w2"): 5}
    assert store.play_seconds(date(2026, 10, 20)) == {}
    assert store.usage("gw-kind", day) == 30


def _insert_attempt_flag_review(db: pathlib.Path, world_id: str, day: date) -> None:
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            "INSERT INTO join_attempts (day, world_id, name_fold, player_name, first_at, last_at, count) "
            "VALUES (?, ?, 'fremd', 'Fremd', 1, 1, 1)",
            (day.isoformat(), world_id),
        )
        connection.execute("INSERT OR IGNORE INTO daily_flags (day, flag) VALUES (?, 'x')", (day.isoformat(),))
        connection.execute("INSERT OR IGNORE INTO review_sent (nc_user, day) VALUES ('admin', ?)", (day.isoformat(),))
        connection.commit()
    finally:
        connection.close()


def _days(db: pathlib.Path, table: str) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return sorted(str(row[0]) for row in connection.execute(f"SELECT day FROM {table}"))  # noqa: S608
    finally:
        connection.close()


def test_prune_notify_tables(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    db = tmp_path / "gameworld.sqlite3"
    old, new = date(2026, 10, 10), date(2026, 10, 20)
    for day in (old, new):
        store.book_usage("w1", day, {}, {}, play={"gw-kind": 10})
        _insert_attempt_flag_review(db, "w1", day)
    cut = date(2026, 10, 15)
    store.prune_play_daily(cut)
    store.prune_join_attempts(cut)
    store.prune_daily_flags(cut)
    store.prune_review_sent(cut)
    assert store.play_seconds(old) == {}
    assert store.play_seconds(new) == {("gw-kind", "w1"): 10}
    for table in ("join_attempts", "daily_flags", "review_sent"):
        assert _days(db, table) == [new.isoformat()], table


def _world_ids(db: pathlib.Path, table: str) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return sorted(str(row[0]) for row in connection.execute(f"SELECT world_id FROM {table}"))  # noqa: S608
    finally:
        connection.close()


def test_delete_notify_data_only_touches_one_world(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    day = date(2026, 10, 21)
    db = tmp_path / "gameworld.sqlite3"
    for world_id in ("w1", "w2"):
        store.take_events(world_id, 1, [("join", "Mia", 1, "")])
        store.set_run_state(world_id, running=True)
        store.book_usage(world_id, day, {}, {}, play={"gw-kind": 10})
        _insert_attempt_flag_review(db, world_id, day)
        connection = sqlite3.connect(db)
        try:
            connection.execute(
                "INSERT INTO bot_presence (world_id, nc_user, last_kind, last_at) VALUES (?, 'gw-kind', 'join', 1)",
                (world_id,),
            )
            connection.execute(
                "INSERT INTO talk_rooms (world_id, token, owner_uid, created_at) VALUES (?, 'tok', 'admin', 't')",
                (world_id,),
            )
            connection.commit()
        finally:
            connection.close()
    store.delete_notify_data("w1")
    assert store.event_cursor("w1") is None
    assert store.event_cursor("w2") == 1
    assert [row.world_id for row in store.outbox_batch()] == ["w2"]
    assert store.run_state("w1") is None
    assert store.run_state("w2") is True
    # Play time stays for the review of the day (acceptance 04.1-09).
    assert store.play_seconds(day) == {("gw-kind", "w1"): 10, ("gw-kind", "w2"): 10}
    assert _world_ids(db, "join_attempts") == ["w2"]
    assert _world_ids(db, "bot_presence") == ["w2"]
    assert _world_ids(db, "talk_rooms") == ["w1", "w2"]


# Schema 7 (phase 5): backups and backup jobs.


def _schema_6_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Real schema 6 file: today's schema without the tables from schema 7, with data."""
    db = tmp_path / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    store.insert_world(_row("w1", 30001, "mtg_kreativ"))
    store.take_events("w1", 4, [])
    connection = sqlite3.connect(db)
    try:
        for table in BACKUP_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("UPDATE meta SET value = '6' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()
    return db


def test_fresh_db_has_backup_tables(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "gameworld.sqlite3"
    WorldStore(db).migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert BACKUP_TABLES.issubset(_tables(db))


def test_schema_6_is_migrated_to_7_keeps_data(tmp_path: pathlib.Path) -> None:
    db = _schema_6_file(tmp_path)
    assert _schema_version(db) == "6"
    assert not BACKUP_TABLES & set(_tables(db))
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert BACKUP_TABLES.issubset(_tables(db))
    assert NOTIFY_TABLES.issubset(_tables(db))
    assert store.get_world("w1") is not None
    assert store.event_cursor("w1") == 4


def _backup(
    file_id: int, owner: str = "admin", world: str = "w1", created: str = "2026-10-23T14:05:00+00:00"
) -> BackupRow:
    return BackupRow(
        file_id=file_id,
        owner_uid=owner,
        world_id=world,
        path=f"Gameworld/Burg/Burg-{file_id}.tar.gz",
        name=f"Burg-{file_id}.tar.gz",
        size=1000 + file_id,
        sha256="ab" * 32,
        preset="mtg_kreativ",
        kind="manual",
        created_at=created,
    )


def test_backups_for_lists_only_own_world_newest_first(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    older = _backup(1, created="2026-10-23T10:00:00+00:00")
    newer = _backup(2, created="2026-10-23T12:00:00+00:00")
    store.add_backup(older)
    store.add_backup(newer)
    store.add_backup(_backup(3, world="w2"))
    store.add_backup(_backup(4, owner="papa"))
    assert store.backups_for("admin", "w1") == [newer, older]
    assert store.backups_for("admin", "w2") == [_backup(3, world="w2")]
    assert store.backups_for("papa", "w1") == [_backup(4, owner="papa")]
    assert store.backups_for("gw-kind", "w1") == []


def test_backup_by_file_is_owner_scoped(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    row = _backup(7)
    store.add_backup(row)
    assert store.backup_by_file("admin", 7) == row
    assert store.backup_by_file("papa", 7) is None
    assert store.backup_by_file("admin", 8) is None


def test_add_backup_same_file_id_replaces(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.add_backup(_backup(7))
    replaced = BackupRow(**{**_backup(7).__dict__, "size": 5, "sha256": "cd" * 32})
    store.add_backup(replaced)
    assert store.backups_for("admin", "w1") == [replaced]
    # The same file_id of another manager is a separate entry.
    store.add_backup(_backup(7, owner="papa"))
    assert store.backup_by_file("admin", 7) == replaced


def test_backup_job_roundtrip(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.get_backup_job("w1") is None
    store.set_backup_job("w1", "backup", "running", None, None, "2026-10-23T14:05:00+00:00", None)
    store.set_backup_job("w2", "restore", "done", None, "Burg.tar.gz", "t1", "t2")
    job = store.get_backup_job("w1")
    assert job == BackupJobRow("w1", "backup", "running", None, None, "2026-10-23T14:05:00+00:00", None)
    assert store.running_backup_jobs() == [job]
    store.set_backup_job("w1", "backup", "failed", "Nicht genug Speicherplatz.", "Burg.tar.gz", "t1", "t3")
    assert store.get_backup_job("w1") == BackupJobRow(
        "w1", "backup", "failed", "Nicht genug Speicherplatz.", "Burg.tar.gz", "t1", "t3"
    )
    assert store.running_backup_jobs() == []
    store.delete_backup_job("w1")
    assert store.get_backup_job("w1") is None
    assert store.get_backup_job("w2") == BackupJobRow("w2", "restore", "done", None, "Burg.tar.gz", "t1", "t2")


def test_reset_event_cursor_only_one_world(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.take_events("w1", 5, [])
    store.take_events("w2", 9, [])
    store.reset_event_cursor("w1")
    assert store.event_cursor("w1") is None
    assert store.event_cursor("w2") == 9


# Schema 8 (phase 6): adult switch, tenure, manager state per group, Talk takeover.


def _talk_columns(db: pathlib.Path) -> set[str]:
    connection = sqlite3.connect(db)
    try:
        return {str(info[1]) for info in connection.execute("PRAGMA table_info(talk_rooms)").fetchall()}
    finally:
        connection.close()


def _schema_7_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Real schema 7 file: without the tables from schema 8 and without the two Talk columns, with data."""
    db = tmp_path / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    store.insert_world(_row("w1", 30001, "mtg_kreativ"))
    assert store.insert_talk_room("w1", "tok1", "admin", "2026-10-24T08:00:00+00:00")
    connection = sqlite3.connect(db)
    try:
        for table in ROLE_TABLES:
            connection.execute(f"DROP TABLE {table}")
        connection.execute("ALTER TABLE talk_rooms DROP COLUMN orphaned_token")
        connection.execute("ALTER TABLE talk_rooms DROP COLUMN former_owner")
        connection.execute("UPDATE meta SET value = '7' WHERE key = 'schema_version'")
        connection.commit()
    finally:
        connection.close()
    return db


def test_fresh_db_is_schema_8_with_role_tables(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "gameworld.sqlite3"
    WorldStore(db).migrate()
    # Schema 9 (06-22) adds the world language on top of the role tables of schema 8.
    assert SCHEMA_VERSION == "9"
    assert _schema_version(db) == SCHEMA_VERSION
    assert {"adults", "verwalter_seen", "verwalter_snapshot"} == ROLE_TABLES
    assert ROLE_TABLES.issubset(_tables(db))
    assert {"orphaned_token", "former_owner"}.issubset(_talk_columns(db))


def test_schema_7_is_migrated_to_8_keeps_data_and_is_idempotent(tmp_path: pathlib.Path) -> None:
    db = _schema_7_file(tmp_path)
    assert _schema_version(db) == "7"
    assert not ROLE_TABLES & set(_tables(db))
    assert not {"orphaned_token", "former_owner"} & _talk_columns(db)
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert ROLE_TABLES.issubset(_tables(db))
    assert {"orphaned_token", "former_owner"}.issubset(_talk_columns(db))
    room = store.talk_room("w1")
    assert room is not None
    assert (room.token, room.owner_uid, room.orphaned_token, room.former_owner) == ("tok1", "admin", None, None)
    store.migrate()
    assert _schema_version(db) == SCHEMA_VERSION
    assert store.list_talk_rooms() == [room]
    assert store.get_world("w1") is not None


def test_group_snapshot_is_replaced_per_group(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    assert store.group_snapshot() == {}
    store.replace_group_snapshot("admin", {"admin"})
    store.replace_group_snapshot("lehrkraefte", {"gw-lehrer", "gw-lehrer2"})
    store.replace_group_snapshot("lehrkraefte", {"gw-lehrer"})
    assert store.group_snapshot() == {"admin": {"admin"}, "lehrkraefte": {"gw-lehrer"}}
    store.replace_group_snapshot("lehrkraefte", set())
    assert store.group_snapshot() == {"admin": {"admin"}}


def test_drop_group_snapshots_keeps_only_listed_groups(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.replace_group_snapshot("admin", {"admin"})
    store.replace_group_snapshot("lehrkraefte", {"gw-lehrer"})
    store.replace_group_snapshot("alt", {"gw-alt"})
    store.drop_group_snapshots(keep={"admin", "lehrkraefte"})
    assert store.group_snapshot() == {"admin": {"admin"}, "lehrkraefte": {"gw-lehrer"}}


def test_verwalter_seen_keeps_first_day_and_orders_by_seniority(tmp_path: pathlib.Path) -> None:
    store = _store3(tmp_path)
    store.sync_verwalter_seen({"zora"}, "2026-10-01T08:00:00+00:00")
    store.sync_verwalter_seen({"zora", "anna", "bert"}, "2026-10-02T08:00:00+00:00")
    store.sync_verwalter_seen({"zora", "anna", "bert"}, "2026-10-03T08:00:00+00:00")
    # zora seen first; anna and bert on the same day, tie broken by account ID.
    assert store.verwalter_seniority() == ["zora", "anna", "bert"]
    store.sync_verwalter_seen({"anna", "bert"}, "2026-10-04T08:00:00+00:00")
    assert store.verwalter_seniority() == ["anna", "bert"]
    # Whoever comes back starts over (no tenure from the time before).
    store.sync_verwalter_seen({"anna", "bert", "zora"}, "2026-10-05T08:00:00+00:00")
    assert store.verwalter_seniority() == ["anna", "bert", "zora"]


def _adult_rows(db: pathlib.Path) -> list[str]:
    connection = sqlite3.connect(db)
    try:
        return [str(row[0]) for row in connection.execute("SELECT nc_user FROM adults ORDER BY nc_user")]
    finally:
        connection.close()


def test_forget_account_removes_adult_row_of_this_account_only(tmp_path: pathlib.Path) -> None:
    """P-08: a newly created identical account ID must never be an adult immediately."""
    store = _store3(tmp_path)
    db = tmp_path / "gameworld.sqlite3"
    connection = sqlite3.connect(db)
    try:
        connection.executemany(
            "INSERT INTO adults (nc_user, set_by, set_at) VALUES (?, 'admin', '2026-10-24T08:00:00+00:00')",
            [("gw-weg",), ("gw-bleibt",)],
        )
        connection.commit()
    finally:
        connection.close()
    assert store.forget_account("gw-weg") is True
    assert _adult_rows(db) == ["gw-bleibt"]
