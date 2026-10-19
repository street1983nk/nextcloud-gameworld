"""SQLite-Ablage des Soll-Zustands in ``$APP_PERSISTENT_STORAGE/gameworld.sqlite3``.

Der Ist-Zustand (läuft, gestoppt) kommt immer aus Docker, nie aus dieser Datei.
Jede Methode öffnet eine eigene Verbindung, weil Aufrufe über
``anyio.to_thread`` aus wechselnden Threads kommen.

Schema 3 (Phase 3) speichert zu jedem eingeladenen Nextcloud-Konto nur
Spielername und Rotationszähler. Spielpasswörter stehen hier bewusst nicht:
Sie werden aus einem Geheimnis in der Nextcloud-Konfiguration abgeleitet
(access/accounts.py, access/secret.py). In ``world_access`` liegen nur die
SRP-Verifier je Welt.
"""

from __future__ import annotations

import pathlib
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import astuple, dataclass, fields

from gameworld.provisioner.presets import DEFAULT_PRESET_ID

SCHEMA_VERSION = "3"

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
CREATE TABLE IF NOT EXISTS players (
  nc_user TEXT PRIMARY KEY,
  player_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  rotation INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS invites (
  world_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('user', 'group')),
  target TEXT NOT NULL,
  invited_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (world_id, kind, target)
);
CREATE TABLE IF NOT EXISTS world_access (
  world_id TEXT NOT NULL,
  nc_user TEXT NOT NULL,
  verifier TEXT NOT NULL,
  PRIMARY KEY (world_id, nc_user)
);
"""

# Schema 1 auf 2: Phase-1-Welten spielen Minetest Game, also das Kreativ-Preset.
ADD_PRESET = "ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ'"
# Schema 2 auf 3: Zähler der Zugangsdatei je Welt (Kopfzeile, Rückmeldung des Mods).
ADD_ACCESS_GENERATION = "ALTER TABLE worlds ADD COLUMN access_generation INTEGER NOT NULL DEFAULT 0"


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
    access_generation: int = 0


@dataclass(frozen=True)
class PlayerRow:
    """Spieler je Nextcloud-Konto; das Passwort folgt aus Geheimnis, Konto und Rotation."""

    nc_user: str
    player_name: str
    rotation: int


@dataclass(frozen=True)
class InviteRow:
    world_id: str
    kind: str
    target: str
    invited_by: str
    created_at: str


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
            if "access_generation" not in columns:
                connection.execute(ADD_ACCESS_GENERATION)
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

    # Spieler, Einladungen und Zugang (Schema 3)

    def get_player(self, nc_user: str) -> PlayerRow | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT nc_user, player_name, rotation FROM players WHERE nc_user = ?", (nc_user,)
            ).fetchone()
        return None if row is None else PlayerRow(str(row[0]), str(row[1]), int(row[2]))

    def player_names(self) -> set[str]:
        """Alle vergebenen Spielernamen, kleingeschrieben (Vergleich wie COLLATE NOCASE)."""
        with self._connect() as connection:
            rows = connection.execute("SELECT player_name FROM players").fetchall()
        return {str(row[0]).lower() for row in rows}

    def insert_player(self, row: PlayerRow) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO players (nc_user, player_name, rotation) VALUES (?, ?, ?)",
                (row.nc_user, row.player_name, row.rotation),
            )

    def add_invite(self, world_id: str, kind: str, target: str, invited_by: str, created_at: str) -> None:
        """Einladung anlegen; eine vorhandene bleibt unverändert (erster Einladender, erster Zeitpunkt)."""
        with self._connect() as connection:
            connection.execute(
                # ON CONFLICT statt OR IGNORE: Ein ungültiges kind scheitert weiter am CHECK.
                "INSERT INTO invites (world_id, kind, target, invited_by, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT (world_id, kind, target) DO NOTHING",
                (world_id, kind, target, invited_by, created_at),
            )

    def remove_invite(self, world_id: str, kind: str, target: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM invites WHERE world_id = ? AND kind = ? AND target = ?", (world_id, kind, target)
            )
        return cursor.rowcount > 0

    def list_invites(self, world_id: str) -> list[InviteRow]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT world_id, kind, target, invited_by, created_at FROM invites "
                "WHERE world_id = ? ORDER BY kind, target",
                (world_id,),
            ).fetchall()
        return [InviteRow(*(str(value) for value in row)) for row in rows]

    def world_access(self, world_id: str) -> dict[str, str]:
        """Effektive Spieler der Welt: Nextcloud-Konto auf Verifier."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, verifier FROM world_access WHERE world_id = ?", (world_id,)
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def apply_world_access(self, world_id: str, verifiers: dict[str, str]) -> int:
        """Ersetzt den Zugang der Welt und zählt die Generation hoch, in einer Transaktion.

        Gibt die neue Generation zurück.
        """
        with self._connect() as connection:
            connection.execute("DELETE FROM world_access WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO world_access (world_id, nc_user, verifier) VALUES (?, ?, ?)",
                [(world_id, nc_user, verifier) for nc_user, verifier in sorted(verifiers.items())],
            )
            connection.execute("UPDATE worlds SET access_generation = access_generation + 1 WHERE id = ?", (world_id,))
            row = connection.execute("SELECT access_generation FROM worlds WHERE id = ?", (world_id,)).fetchone()
        return 0 if row is None else int(row[0])

    def access_entries(self, world_id: str) -> dict[str, str]:
        """Inhalt der Zugangsdatei: Spielername auf Verifier."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT players.player_name, world_access.verifier FROM world_access "
                "JOIN players ON players.nc_user = world_access.nc_user WHERE world_access.world_id = ?",
                (world_id,),
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def delete_access_data(self, world_id: str) -> None:
        """Einladungen und Zugang einer gelöschten Welt; Spieler bleiben (gelten für alle Welten)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM invites WHERE world_id = ?", (world_id,))
            connection.execute("DELETE FROM world_access WHERE world_id = ?", (world_id,))
