"""SQLite-Ablage des Soll-Zustands in ``$APP_PERSISTENT_STORAGE/gameworld.sqlite3``.

Der Ist-Zustand (läuft, gestoppt) kommt immer aus Docker, nie aus dieser Datei.
Jede Methode öffnet eine eigene Verbindung, weil Aufrufe über
``anyio.to_thread`` aus wechselnden Threads kommen.
"""

from __future__ import annotations

import pathlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass, fields

from gameworld.provisioner.presets import DEFAULT_PRESET_ID

SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS worlds (
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
  created_at TEXT NOT NULL,
  preset TEXT NOT NULL DEFAULT 'mtg_kreativ'
);
"""

# Schema 1 auf 2: Phase-1-Welten spielen Minetest Game, also das Kreativ-Preset.
ADD_PRESET = "ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ'"


@dataclass
class WorldRow:
    id: str
    name: str
    port: int
    container_name: str
    volume_name: str
    world_key: str
    engine_version: str
    desired_state: str
    op_state: str
    last_error: str | None
    created_at: str
    preset: str = DEFAULT_PRESET_ID


COLUMNS = tuple(field.name for field in fields(WorldRow))
UPDATABLE = frozenset(COLUMNS) - {"id"}


class WorldStore:
    def __init__(self, db_path: pathlib.Path) -> None:
        self._db_path = db_path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._db_path, timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self) -> None:
        """Legt das Schema an und hebt ältere Dateien an; mehrfach aufrufbar.

        Die Migration richtet sich nach der tatsächlichen Spaltenliste, nicht
        nach der Versionsnummer: so ist sie idempotent und übersteht auch eine
        abgebrochene frühere Migration. Kein Drop, kein Neuanlegen der Tabelle.
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            columns = {str(info[1]) for info in connection.execute("PRAGMA table_info(worlds)").fetchall()}
            if "preset" not in columns:
                connection.execute(ADD_PRESET)
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )

    def instance_id(self) -> str:
        """Zufällige Instanz-ID, einmal erzeugt und danach stabil."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('instance_id', ?)",
                (secrets.token_hex(4),),
            )
            row = connection.execute("SELECT value FROM meta WHERE key = 'instance_id'").fetchone()
        return str(row[0])

    def insert_world(self, row: WorldRow) -> None:
        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._connect() as connection:
            connection.execute(
                f"INSERT INTO worlds ({', '.join(COLUMNS)}) VALUES ({placeholders})",  # noqa: S608
                astuple(row),
            )

    def update_world(self, world_id: str, **fields: object) -> None:
        unknown = set(fields) - UPDATABLE
        if unknown:
            raise ValueError(f"Unbekannte Spalten: {', '.join(sorted(unknown))}")
        if not fields:
            return
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE worlds SET {assignments} WHERE id = ?",  # noqa: S608
                (*fields.values(), world_id),
            )

    def get_world(self, world_id: str) -> WorldRow | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {', '.join(COLUMNS)} FROM worlds WHERE id = ?",  # noqa: S608
                (world_id,),
            ).fetchone()
        return None if row is None else WorldRow(*row)

    def list_worlds(self) -> list[WorldRow]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {', '.join(COLUMNS)} FROM worlds ORDER BY created_at, id"  # noqa: S608
            ).fetchall()
        return [WorldRow(*row) for row in rows]

    def used_ports(self) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT port FROM worlds").fetchall()
        return {int(row[0]) for row in rows}

    def delete_world(self, world_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM worlds WHERE id = ?", (world_id,))
