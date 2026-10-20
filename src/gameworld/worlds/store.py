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
from datetime import date

from gameworld.playtime.plan import DayRule, Holiday, WeekPlan
from gameworld.provisioner.presets import DEFAULT_PRESET_ID

SCHEMA_VERSION = "4"

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
CREATE TABLE IF NOT EXISTS time_children (
  nc_user TEXT PRIMARY KEY,
  updated_by TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS time_plans (
  nc_user TEXT NOT NULL,
  plan TEXT NOT NULL CHECK (plan IN ('normal', 'ferien')),
  weekday INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
  limit_minutes INTEGER CHECK (limit_minutes IS NULL OR limit_minutes BETWEEN 1 AND 1440),
  window_start INTEGER CHECK (window_start IS NULL OR window_start BETWEEN 0 AND 1439),
  window_end INTEGER CHECK (window_end IS NULL OR window_end BETWEEN 1 AND 1440),
  PRIMARY KEY (nc_user, plan, weekday)
);
CREATE TABLE IF NOT EXISTS holidays (
  id INTEGER PRIMARY KEY,
  label TEXT NOT NULL DEFAULT '' CHECK (length(label) <= 60),
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  CHECK (start_date <= end_date)
);
CREATE TABLE IF NOT EXISTS world_windows (
  world_id TEXT NOT NULL,
  weekday INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  window_start INTEGER NOT NULL,
  window_end INTEGER NOT NULL,
  PRIMARY KEY (world_id, weekday)
);
CREATE TABLE IF NOT EXISTS time_usage (
  nc_user TEXT NOT NULL,
  day TEXT NOT NULL,
  seconds INTEGER NOT NULL,
  PRIMARY KEY (nc_user, day)
);
CREATE TABLE IF NOT EXISTS time_ledger_seen (
  world_id TEXT NOT NULL,
  player_name TEXT NOT NULL,
  seconds INTEGER NOT NULL,
  PRIMARY KEY (world_id, player_name)
);
"""

# Namen der sechs Spielzeit-Tabellen aus Schema 4 (Migrationstest, Selbstdokumentation).
TIME_TABLES = frozenset({"time_children", "time_plans", "holidays", "world_windows", "time_usage", "time_ledger_seen"})

# Schema 1 auf 2: Phase-1-Welten spielen Minetest Game, also das Kreativ-Preset.
ADD_PRESET = "ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ'"
# Schema 2 auf 3: Zähler der Zugangsdatei je Welt (Kopfzeile, Rückmeldung des Mods).
ADD_ACCESS_GENERATION = "ALTER TABLE worlds ADD COLUMN access_generation INTEGER NOT NULL DEFAULT 0"
# Schema 3 auf 4: Zähler der Regeldatei je Welt (Zeit-Mod, wie access_generation).
ADD_TIME_GENERATION = "ALTER TABLE worlds ADD COLUMN time_generation INTEGER NOT NULL DEFAULT 0"


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
    time_generation: int = 0


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

# Eine Zeile aus time_plans: nc_user, plan, weekday, allowed, limit_minutes, window_start, window_end.
_PlanRow = tuple[str, str, int, int, int | None, int | None, int | None]


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
            if "time_generation" not in columns:
                connection.execute(ADD_TIME_GENERATION)
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

    def list_players(self) -> list[PlayerRow]:
        """Alle Spieler je Nextcloud-Konto, sortiert nach Spielername (Verwalteransicht Spielzeit)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, player_name, rotation FROM players ORDER BY player_name"
            ).fetchall()
        return [PlayerRow(str(row[0]), str(row[1]), int(row[2])) for row in rows]

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

    def group_invited_worlds(self, gids: set[str]) -> list[str]:
        """Welten mit einer Gruppen-Einladung für eine der Gruppen (lazy Provisionierung, 03-06)."""
        if not gids:
            return []
        placeholders = ", ".join("?" for _ in gids)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT DISTINCT world_id FROM invites WHERE kind = 'group' AND target IN ({placeholders}) "  # noqa: S608
                "ORDER BY world_id",
                sorted(gids),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def access_entries(self, world_id: str) -> dict[str, str]:
        """Inhalt der Zugangsdatei: Spielername auf Verifier."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT players.player_name, world_access.verifier FROM world_access "
                "JOIN players ON players.nc_user = world_access.nc_user WHERE world_access.world_id = ?",
                (world_id,),
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def get_meta(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def player_name_owner(self, player_name: str) -> str | None:
        """Konto, dem der Spielername ohne Rücksicht auf Groß-/Kleinschreibung gehört."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT nc_user FROM players WHERE player_name = ? COLLATE NOCASE", (player_name,)
            ).fetchone()
        return None if row is None else str(row[0])

    def player_worlds(self, nc_user: str) -> list[str]:
        """Welten, in denen das Konto gerade Zugang hat."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT world_id FROM world_access WHERE nc_user = ? ORDER BY world_id", (nc_user,)
            ).fetchall()
        return [str(row[0]) for row in rows]

    def update_player_access(self, player: PlayerRow, verifiers: dict[str, str]) -> None:
        """Name oder Rotation eines Spielers und seine Verifier je Welt, in einer Transaktion.

        ``verifiers`` bildet Welt-ID auf den neuen Verifier ab; jede dieser
        Welten bekommt eine neue Generation.
        """
        with self._connect() as connection:
            connection.execute(
                "UPDATE players SET player_name = ?, rotation = ? WHERE nc_user = ?",
                (player.player_name, player.rotation, player.nc_user),
            )
            for world_id, verifier in sorted(verifiers.items()):
                connection.execute(
                    "UPDATE world_access SET verifier = ? WHERE world_id = ? AND nc_user = ?",
                    (verifier, world_id, player.nc_user),
                )
                connection.execute(
                    "UPDATE worlds SET access_generation = access_generation + 1 WHERE id = ?", (world_id,)
                )

    def delete_access_data(self, world_id: str) -> None:
        """Einladungen und Zugang einer gelöschten Welt; Spieler bleiben (gelten für alle Welten)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM invites WHERE world_id = ?", (world_id,))
            connection.execute("DELETE FROM world_access WHERE world_id = ?", (world_id,))

    # Spielzeit: Regeln, Ferien, Welt-Fenster, Verbrauch und Zählbuchstände (Schema 4)

    @staticmethod
    def _plan_rows(nc_user: str, plan: str, week: WeekPlan) -> list[_PlanRow]:
        return [
            (nc_user, plan, weekday, int(rule.allowed), rule.limit_minutes, rule.window_start, rule.window_end)
            for weekday, rule in sorted(week.days.items())
        ]

    def set_child_plan(
        self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, updated_by: str, updated_at: str
    ) -> None:
        """Wochenplan (und optional Ferienplan) eines Kindes, in einer Transaktion.

        Schreibt die Zeile in ``time_children`` (Kind hat Regeln, O-10) und 7 bzw.
        14 Zeilen ``time_plans`` (normal, ferien). Ein früherer Plan wird ersetzt.
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO time_children (nc_user, updated_by, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user) DO UPDATE SET updated_by = excluded.updated_by, updated_at = excluded.updated_at",
                (nc_user, updated_by, updated_at),
            )
            connection.execute("DELETE FROM time_plans WHERE nc_user = ?", (nc_user,))
            rows = self._plan_rows(nc_user, "normal", normal)
            if holiday is not None:
                rows.extend(self._plan_rows(nc_user, "ferien", holiday))
            connection.executemany(
                "INSERT INTO time_plans (nc_user, plan, weekday, allowed, limit_minutes, window_start, window_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def clear_child(self, nc_user: str) -> None:
        """Entfernt Regeln und Verbrauch eines Kindes (zurück auf keine Begrenzung, O-10)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM time_children WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_plans WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_usage WHERE nc_user = ?", (nc_user,))

    def child_plans(self) -> dict[str, tuple[WeekPlan, WeekPlan | None]]:
        """Nur Kinder mit Zeile in ``time_children``: je Kind Normalplan und Ferienplan (oder None)."""
        with self._connect() as connection:
            children = [str(row[0]) for row in connection.execute("SELECT nc_user FROM time_children").fetchall()]
            rows = connection.execute(
                "SELECT nc_user, plan, weekday, allowed, limit_minutes, window_start, window_end FROM time_plans"
            ).fetchall()
        grouped: dict[str, dict[str, dict[int, DayRule]]] = {}
        for nc_user, plan, weekday, allowed, limit_minutes, window_start, window_end in rows:
            rule = DayRule(bool(allowed), limit_minutes, window_start, window_end)
            grouped.setdefault(str(nc_user), {}).setdefault(str(plan), {})[int(weekday)] = rule
        result: dict[str, tuple[WeekPlan, WeekPlan | None]] = {}
        for nc_user in children:
            plans = grouped.get(nc_user, {})
            if "normal" not in plans:
                continue
            holiday = WeekPlan(days=plans["ferien"]) if "ferien" in plans else None
            result[nc_user] = (WeekPlan(days=plans["normal"]), holiday)
        return result

    def add_usage(self, nc_user: str, day: date, seconds: int) -> None:
        """Addiert verbrauchte Sekunden auf den lokalen Tag eines Kindes (nur Tagessummen, Pitfall 9)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO time_usage (nc_user, day, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user, day) DO UPDATE SET seconds = seconds + excluded.seconds",
                (nc_user, day.isoformat(), seconds),
            )

    def usage(self, nc_user: str, day: date) -> int:
        """Verbrauchte Sekunden eines Kindes an einem lokalen Tag (0, wenn keine Zeile)."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT seconds FROM time_usage WHERE nc_user = ? AND day = ?", (nc_user, day.isoformat())
            ).fetchone()
        return 0 if row is None else int(row[0])

    def prune_usage(self, before_day: date) -> None:
        """Löscht Verbrauchszeilen vor einem Tag (Aufbewahrung heute plus 7 Tage, A8/Pitfall 9)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM time_usage WHERE day < ?", (before_day.isoformat(),))

    def ledger_seen(self, world_id: str) -> dict[str, int]:
        """Zuletzt gesehener Zählbuch-Stand einer Welt: Spielername auf Sekunden."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT player_name, seconds FROM time_ledger_seen WHERE world_id = ?", (world_id,)
            ).fetchall()
        return {str(row[0]): int(row[1]) for row in rows}

    def set_ledger_seen(self, world_id: str, seen: dict[str, int]) -> None:
        """Ersetzt den gesehenen Zählbuch-Stand einer Welt atomar."""
        with self._connect() as connection:
            connection.execute("DELETE FROM time_ledger_seen WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO time_ledger_seen (world_id, player_name, seconds) VALUES (?, ?, ?)",
                [(world_id, name, seconds) for name, seconds in sorted(seen.items())],
            )

    def add_holiday(self, start: date, end: date, label: str) -> int:
        """Ferienzeitraum für den Haushalt anlegen; gibt die neue id zurück (O-08)."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO holidays (label, start_date, end_date) VALUES (?, ?, ?)",
                (label, start.isoformat(), end.isoformat()),
            )
        rowid = cursor.lastrowid
        return int(rowid) if rowid is not None else 0

    def remove_holiday(self, holiday_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
        return cursor.rowcount > 0

    def list_holidays(self) -> list[Holiday]:
        return [holiday for _holiday_id, holiday in self.holiday_rows()]

    def holiday_rows(self) -> list[tuple[int, Holiday]]:
        """Ferienzeiträume mit id, sortiert nach Beginn (für die Verwalter-API)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, start_date, end_date, label FROM holidays ORDER BY start_date, id"
            ).fetchall()
        return [
            (int(row[0]), Holiday(date.fromisoformat(str(row[1])), date.fromisoformat(str(row[2])), str(row[3])))
            for row in rows
        ]

    def set_world_window(self, world_id: str, weekday: int, window_start: int, window_end: int) -> None:
        """Zeitfenster einer Welt an einem Wochentag setzen (ZEIT-05)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO world_windows (world_id, weekday, window_start, window_end) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(world_id, weekday) DO UPDATE SET "
                "window_start = excluded.window_start, window_end = excluded.window_end",
                (world_id, weekday, window_start, window_end),
            )

    def replace_world_window(self, world_id: str, windows: dict[int, tuple[int, int]]) -> None:
        """Alle Zeitfenster einer Welt in einer Transaktion ersetzen (fehlender Wochentag = geschlossen)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO world_windows (world_id, weekday, window_start, window_end) VALUES (?, ?, ?, ?)",
                [(world_id, weekday, start, end) for weekday, (start, end) in sorted(windows.items())],
            )

    def clear_world_window(self, world_id: str) -> None:
        """Alle Zeitfenster einer Welt entfernen (Welt ist dann immer offen)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))

    def world_window(self, world_id: str) -> dict[int, tuple[int, int]] | None:
        """Welt-Fenster je Wochentag oder None (keine Zeilen = immer offen)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT weekday, window_start, window_end FROM world_windows WHERE world_id = ?", (world_id,)
            ).fetchall()
        if not rows:
            return None
        return {int(row[0]): (int(row[1]), int(row[2])) for row in rows}

    def bump_time_generation(self, world_id: str) -> int:
        """Zählt die Generation der Regeldatei einer Welt hoch und gibt den neuen Wert zurück."""
        with self._connect() as connection:
            connection.execute("UPDATE worlds SET time_generation = time_generation + 1 WHERE id = ?", (world_id,))
            row = connection.execute("SELECT time_generation FROM worlds WHERE id = ?", (world_id,)).fetchone()
        return 0 if row is None else int(row[0])

    def delete_time_data(self, world_id: str) -> None:
        """Welt-Fenster und gesehene Zählbuchstände einer gelöschten Welt (kein PRAGMA foreign_keys)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))
            connection.execute("DELETE FROM time_ledger_seen WHERE world_id = ?", (world_id,))
