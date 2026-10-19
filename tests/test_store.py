"""Schema-Migration der Welt-Datenbank (Schema 1 auf 2, Preset-Spalte)."""

import pathlib
import sqlite3

from gameworld.worlds.store import WorldRow, WorldStore

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


def test_schema_1_is_migrated_to_2(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "2"
    world = store.get_world("w1")
    assert world is not None
    assert world.name == "Alte Welt"
    assert world.preset == "mtg_kreativ"


def test_migrate_twice_is_noop(tmp_path: pathlib.Path) -> None:
    db = _schema_1(tmp_path)
    store = WorldStore(db)
    store.migrate()
    store.migrate()
    assert _schema_version(db) == "2"
    assert [row.id for row in store.list_worlds()] == ["w1"]


def test_fresh_file_gets_schema_2(tmp_path: pathlib.Path) -> None:
    db = tmp_path / "neu" / "gameworld.sqlite3"
    store = WorldStore(db)
    store.migrate()
    assert _schema_version(db) == "2"
    store.insert_world(_row("w2", 30002, "anderes_preset"))
    world = store.get_world("w2")
    assert world is not None
    assert world.preset == "anderes_preset"
