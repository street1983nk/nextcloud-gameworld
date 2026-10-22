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

from gameworld.notify.throttle import ATTEMPT_LIMIT, Decision, decide
from gameworld.playtime.pause import PauseState
from gameworld.playtime.plan import DayRule, Holiday, WeekPlan
from gameworld.provisioner.presets import DEFAULT_PRESET_ID

SCHEMA_VERSION = "5"

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
CREATE TABLE IF NOT EXISTS pause_state (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  started_by TEXT NOT NULL,
  ab INTEGER NOT NULL,
  bis INTEGER NOT NULL,
  art TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS play_daily (
  day TEXT NOT NULL,
  nc_user TEXT NOT NULL,
  world_id TEXT NOT NULL,
  seconds INTEGER NOT NULL,
  PRIMARY KEY (day, nc_user, world_id)
);
CREATE TABLE IF NOT EXISTS event_cursor (
  world_id TEXT PRIMARY KEY,
  seq INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS event_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  world_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL DEFAULT '',
  at INTEGER NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS world_run_state (
  world_id TEXT PRIMARY KEY,
  running INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS join_attempts (
  day TEXT NOT NULL,
  world_id TEXT NOT NULL,
  name_fold TEXT NOT NULL,
  player_name TEXT NOT NULL,
  first_at INTEGER NOT NULL,
  last_at INTEGER NOT NULL,
  count INTEGER NOT NULL,
  notified INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, world_id, name_fold)
);
CREATE TABLE IF NOT EXISTS daily_flags (
  day TEXT NOT NULL,
  flag TEXT NOT NULL,
  PRIMARY KEY (day, flag)
);
CREATE TABLE IF NOT EXISTS review_prefs (
  nc_user TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  minute INTEGER NOT NULL DEFAULT 1200
);
CREATE TABLE IF NOT EXISTS review_sent (
  nc_user TEXT NOT NULL,
  day TEXT NOT NULL,
  PRIMARY KEY (nc_user, day)
);
CREATE TABLE IF NOT EXISTS bot_presence (
  world_id TEXT NOT NULL,
  nc_user TEXT NOT NULL,
  last_kind TEXT NOT NULL,
  last_at INTEGER NOT NULL,
  PRIMARY KEY (world_id, nc_user)
);
CREATE TABLE IF NOT EXISTS talk_rooms (
  world_id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  owner_uid TEXT NOT NULL,
  read_only INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'ok'
);
"""

# Namen der sechs Spielzeit-Tabellen aus Schema 4 (Migrationstest, Selbstdokumentation).
TIME_TABLES = frozenset({"time_children", "time_plans", "holidays", "world_windows", "time_usage", "time_ledger_seen"})
# Namen der Tabellen aus Schema 5 (Phase 4.1: Benachrichtigung, Pause, Rückblick, Talk).
NOTIFY_TABLES = frozenset(
    {
        "pause_state",
        "play_daily",
        "event_cursor",
        "event_outbox",
        "world_run_state",
        "join_attempts",
        "daily_flags",
        "review_prefs",
        "review_sent",
        "bot_presence",
        "talk_rooms",
    }
)
# Höchstens so viele Zeilen in der Outbox; die ältesten fallen weg (T-04.1-07).
OUTBOX_MAX = 1000
# Eine Outbox-Zeile vor dem Speichern: Art, Spielername (oder leer), Epoch, Zusatz.
OutboxEntry = tuple[str, str, int, str]
# Tages-Merker der Sammelnachricht für Fremdversuche (D-08).
FLAG_ATTEMPTS_SUMMARY = "attempts_summary"
# Tages-Merker je gemeldetem Einzelhinweis: attempt:<Welt>:<Name casefold> (IN-05).
FLAG_ATTEMPT_PREFIX = "attempt:"
# Vorgabe des Rückblicks: 20:00 Uhr Haushalts-Zeitzone (D-12).
REVIEW_DEFAULT_MINUTE = 1200

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


@dataclass(frozen=True)
class OutboxRow:
    """Ein noch nicht versendetes Ereignis (Takt legt ab, Event-Loop versendet)."""

    id: int
    world_id: str
    kind: str
    name: str
    at: int
    detail: str


@dataclass(frozen=True)
class AttemptRow:
    """Ein gemerkter Fremdversuch eines Tages (Seite versuch)."""

    world_id: str
    player_name: str
    first_at: int
    count: int


@dataclass(frozen=True)
class TalkRoomRow:
    """Talk-Raum einer Welt; state ok oder delete_pending (Welt weg, Raum noch nicht)."""

    world_id: str
    token: str
    owner_uid: str
    read_only: bool
    created_at: str
    state: str


TALK_STATE_OK = "ok"
TALK_STATE_DELETE_PENDING = "delete_pending"
TALK_STATES = frozenset({TALK_STATE_OK, TALK_STATE_DELETE_PENDING})

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

    def compare_and_set_meta(self, key: str, expected: str | None, value: str) -> bool:
        """Setzt ``value`` nur, wenn der Wert noch ``expected`` ist (None: noch keiner); True bei Erfolg.

        Zwei gleichzeitige Meldungen überschreiben sich so nie gegenseitig (WR-04).
        """
        with self._connect() as connection:
            if expected is None:
                cursor = connection.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, value))
            else:
                cursor = connection.execute(
                    "UPDATE meta SET value = ? WHERE key = ? AND value = ?", (value, key, expected)
                )
        return cursor.rowcount == 1

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

    def clear_child(self, nc_user: str, keep_from: date) -> None:
        """Entfernt Regeln eines Kindes (zurück auf keine Begrenzung, O-10) und alten Verbrauch.

        Der Verbrauch ab ``keep_from`` (heute, lokal) bleibt stehen: Setzen Eltern
        am selben Tag wieder Regeln, gibt es kein frisches Kontingent (WR-04,
        Owner-Entscheid). Ältere Tage braucht niemand mehr (Datensparsamkeit).
        """
        with self._connect() as connection:
            connection.execute("DELETE FROM time_children WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_plans WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_usage WHERE nc_user = ? AND day < ?", (nc_user, keep_from.isoformat()))

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

    def book_usage(
        self,
        world_id: str,
        day: date,
        usage: dict[str, int],
        seen: dict[str, int],
        *,
        play: dict[str, int] | None = None,
    ) -> None:
        """Verbucht Sekunden je Kind und verankert den gesehenen Zählbuch-Stand in EINER Transaktion.

        Scheitert ein Schritt (Datenbank gesperrt, Prozessabbruch), bleibt beides
        beim alten Stand: Der nächste Takt verbucht denselben Zuwachs genau einmal,
        nie doppelt (WR-05). ``play`` (Konto auf Sekunden) landet in derselben
        Transaktion in ``play_daily`` je Welt; welche Konten zählen, entscheidet der
        Aufrufer (TimeEngine.book: nur Kinder mit Regeln, IN-03).
        """
        with self._connect() as connection:
            connection.executemany(
                "INSERT INTO time_usage (nc_user, day, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user, day) DO UPDATE SET seconds = seconds + excluded.seconds",
                [(nc_user, day.isoformat(), seconds) for nc_user, seconds in sorted(usage.items())],
            )
            connection.executemany(
                "INSERT INTO play_daily (day, nc_user, world_id, seconds) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, nc_user, world_id) DO UPDATE SET seconds = seconds + excluded.seconds",
                [(day.isoformat(), nc_user, world_id, seconds) for nc_user, seconds in sorted((play or {}).items())],
            )
            connection.execute("DELETE FROM time_ledger_seen WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO time_ledger_seen (world_id, player_name, seconds) VALUES (?, ?, ?)",
                [(world_id, name, seconds) for name, seconds in sorted(seen.items())],
            )

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

    # Pause des Haushalts (Schema 5, genau eine Zeile, ELTERN-01)

    def get_pause(self) -> PauseState | None:
        """Gespeicherte Pause oder None; ob sie noch gilt, entscheidet der Aufrufer (pause.is_active)."""
        with self._connect() as connection:
            row = connection.execute("SELECT started_by, ab, bis, art FROM pause_state WHERE id = 1").fetchone()
        return None if row is None else PauseState(str(row[0]), int(row[1]), int(row[2]), str(row[3]))

    def set_pause(self, state: PauseState) -> None:
        """Pause setzen; eine vorhandene Zeile wird überschrieben."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pause_state (id, started_by, ab, bis, art) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET started_by = excluded.started_by, ab = excluded.ab, "
                "bis = excluded.bis, art = excluded.art",
                (state.started_by, state.ab, state.bis, state.art),
            )

    def clear_pause(self, *, ended_by: int | None = None) -> None:
        """Pause löschen; mit ``ended_by`` nur, wenn sie bis dahin abgelaufen ist (bis <= ended_by)."""
        with self._connect() as connection:
            if ended_by is None:
                connection.execute("DELETE FROM pause_state")
            else:
                connection.execute("DELETE FROM pause_state WHERE bis <= ?", (ended_by,))

    # Ereignisse, Laufzustand, Tagesspielzeit je Welt und Drosseln (Schema 5)

    def event_cursor(self, world_id: str) -> int | None:
        """Zuletzt verarbeitete Sequenz der Ereignisdatei oder None (Erstkontakt)."""
        with self._connect() as connection:
            row = connection.execute("SELECT seq FROM event_cursor WHERE world_id = ?", (world_id,)).fetchone()
        return None if row is None else int(row[0])

    @staticmethod
    def _cap_outbox(connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM event_outbox WHERE id NOT IN (SELECT id FROM event_outbox ORDER BY id DESC LIMIT ?)",
            (OUTBOX_MAX,),
        )

    def take_events(self, world_id: str, cursor: int, rows: list[OutboxEntry]) -> None:
        """Cursor setzen und neue Ereignisse in die Outbox legen, in EINER Transaktion.

        Danach höchstens OUTBOX_MAX Zeilen, die ältesten fallen weg (T-04.1-07).
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO event_cursor (world_id, seq) VALUES (?, ?) "
                "ON CONFLICT(world_id) DO UPDATE SET seq = excluded.seq",
                (world_id, cursor),
            )
            connection.executemany(
                "INSERT INTO event_outbox (world_id, kind, name, at, detail) VALUES (?, ?, ?, ?, ?)",
                [(world_id, kind, name, at, detail) for kind, name, at, detail in rows],
            )
            self._cap_outbox(connection)

    def add_outbox(self, world_id: str, kind: str, name: str, at: int, detail: str = "") -> None:
        """Einzelnes Ereignis ohne Ereignisdatei (Start, Stopp, Pause) in die Outbox legen."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO event_outbox (world_id, kind, name, at, detail) VALUES (?, ?, ?, ?, ?)",
                (world_id, kind, name, at, detail),
            )
            self._cap_outbox(connection)

    def outbox_batch(self, limit: int = 100) -> list[OutboxRow]:
        """Älteste Outbox-Zeilen zuerst, höchstens ``limit``."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, world_id, kind, name, at, detail FROM event_outbox ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [OutboxRow(int(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]), str(row[5])) for row in rows]

    def delete_outbox(self, ids: list[int]) -> None:
        """Versendete (oder verworfene) Outbox-Zeilen entfernen."""
        with self._connect() as connection:
            connection.executemany("DELETE FROM event_outbox WHERE id = ?", [(row_id,) for row_id in ids])

    def run_state(self, world_id: str) -> bool | None:
        """Zuletzt im Takt beobachteter Laufzustand oder None (noch nie beobachtet)."""
        with self._connect() as connection:
            row = connection.execute("SELECT running FROM world_run_state WHERE world_id = ?", (world_id,)).fetchone()
        return None if row is None else bool(row[0])

    def set_run_state(self, world_id: str, *, running: bool) -> None:
        """Beobachteten Laufzustand einer Welt festhalten (Pitfall 10)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO world_run_state (world_id, running) VALUES (?, ?) "
                "ON CONFLICT(world_id) DO UPDATE SET running = excluded.running",
                (world_id, int(running)),
            )

    def play_seconds(self, day: date) -> dict[tuple[str, str], int]:
        """Gespielte Sekunden eines lokalen Tages je (Konto, Welt)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, world_id, seconds FROM play_daily WHERE day = ?", (day.isoformat(),)
            ).fetchall()
        return {(str(row[0]), str(row[1])): int(row[2]) for row in rows}

    def _prune_days(self, table: str, before_day: date) -> None:
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {table} WHERE day < ?", (before_day.isoformat(),))  # noqa: S608

    def prune_play_daily(self, before_day: date) -> None:
        """Tagesspielzeit je Welt vor einem Tag löschen (7 Tage wie time_usage)."""
        self._prune_days("play_daily", before_day)

    def prune_join_attempts(self, before_day: date) -> None:
        """Gemerkte Fremdversuche vor einem Tag löschen."""
        self._prune_days("join_attempts", before_day)

    def prune_daily_flags(self, before_day: date) -> None:
        """Tages-Merker vor einem Tag löschen."""
        self._prune_days("daily_flags", before_day)

    def prune_review_sent(self, before_day: date) -> None:
        """Versand-Merker des Rückblicks vor einem Tag löschen."""
        self._prune_days("review_sent", before_day)

    # Fremdversuche und Tagesrückblick (Schema 5, 04.1-04)

    def claim_attempt(
        self, day: date, world_id: str, name: str, at: int, limit: int = ATTEMPT_LIMIT, *, notify: bool = True
    ) -> Decision:
        """Fremdversuch merken und den Versand beanspruchen, in EINER Transaktion (D-08, Pattern 6).

        Je (Tag, Welt, Name ohne Groß/Klein) eine Zeile; wiederholte Versuche
        zählen nur ``count`` hoch. Ein Einzelhinweis je Name, Welt und Tag,
        solange heute weniger als ``limit`` gemeldet sind, danach einmal am Tag die
        Sammelnachricht (Merker ``attempts_summary``). Der Aufrufer sendet erst
        danach: doppelt kommt nie etwas.

        IN-05: Ohne ``notify`` (keine Empfänger oder keine Link-Adresse) wird nur
        gemerkt, nichts beansprucht; der nächste Versuch mit Empfängern kann den
        Hinweis noch auslösen. Gezählt wird in ``daily_flags`` (Merker
        ``attempt:<Welt>:<Name>``), nicht über ``join_attempts``: Löschen einer Welt
        senkt den Tageszähler so nicht.
        """
        day_text = day.isoformat()
        fold = name.casefold()
        flag = f"{FLAG_ATTEMPT_PREFIX}{world_id}:{fold}"
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO join_attempts "
                "(day, world_id, name_fold, player_name, first_at, last_at, count, notified) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 0)",
                (day_text, world_id, fold, name, at, at),
            )
            is_new = cursor.rowcount == 1
            if not is_new:
                connection.execute(
                    "UPDATE join_attempts SET count = count + 1, last_at = max(last_at, ?) "
                    "WHERE day = ? AND world_id = ? AND name_fold = ?",
                    (at, day_text, world_id, fold),
                )
            if not notify:
                return "none"
            claimed = connection.execute(
                "SELECT 1 FROM daily_flags WHERE day = ? AND flag = ?", (day_text, flag)
            ).fetchone()
            notified = connection.execute(
                "SELECT count(*) FROM daily_flags WHERE day = ? AND flag LIKE ?", (day_text, f"{FLAG_ATTEMPT_PREFIX}%")
            ).fetchone()
            summary = connection.execute(
                "SELECT 1 FROM daily_flags WHERE day = ? AND flag = ?", (day_text, FLAG_ATTEMPTS_SUMMARY)
            ).fetchone()
            seen_before = connection.execute(
                "SELECT notified FROM join_attempts WHERE day = ? AND world_id = ? AND name_fold = ?",
                (day_text, world_id, fold),
            ).fetchone()
            # Kandidat ist ein Name, für den heute noch kein Hinweis beansprucht ist.
            is_candidate = claimed is None and (is_new or int(seen_before[0]) == 0)
            decision = decide(is_candidate, int(notified[0]), summary is not None, limit)
            if decision == "single":
                connection.execute("INSERT OR IGNORE INTO daily_flags (day, flag) VALUES (?, ?)", (day_text, flag))
                connection.execute(
                    "UPDATE join_attempts SET notified = 1 WHERE day = ? AND world_id = ? AND name_fold = ?",
                    (day_text, world_id, fold),
                )
            elif decision == "summary":
                connection.execute(
                    "INSERT OR IGNORE INTO daily_flags (day, flag) VALUES (?, ?)", (day_text, FLAG_ATTEMPTS_SUMMARY)
                )
        return decision

    def claim_daily_flag(self, day: date, flag: str) -> bool:
        """Tages-Merker beanspruchen: True nur beim ersten Aufruf je (Tag, Merker), auch nach Neustart."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO daily_flags (day, flag) VALUES (?, ?)", (day.isoformat(), flag)
            )
        return cursor.rowcount == 1

    def attempts(self, day: date, world_id: str | None = None) -> list[AttemptRow]:
        """Fremdversuche eines lokalen Tages (optional nur einer Welt), früheste zuerst."""
        query = "SELECT world_id, player_name, first_at, count FROM join_attempts WHERE day = ?"
        args: tuple[str, ...] = (day.isoformat(),)
        if world_id is not None:
            query += " AND world_id = ?"
            args = (*args, world_id)
        with self._connect() as connection:
            rows = connection.execute(f"{query} ORDER BY first_at, world_id, name_fold", args).fetchall()
        return [AttemptRow(str(row[0]), str(row[1]), int(row[2]), int(row[3])) for row in rows]

    def claim_review(self, nc_user: str, day: date) -> bool:
        """Rückblick beanspruchen: True nur beim ersten Aufruf je Verwalter und Tag (D-15, Pattern 5)."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO review_sent (nc_user, day) VALUES (?, ?)", (nc_user, day.isoformat())
            )
        return cursor.rowcount == 1

    def review_was_sent(self, nc_user: str, day: date) -> bool:
        """Schon beansprucht? Spart dem Loop nach dem Versand das Neuberechnen des Inhalts."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM review_sent WHERE nc_user = ? AND day = ?", (nc_user, day.isoformat())
            ).fetchone()
        return row is not None

    def review_pref(self, nc_user: str) -> tuple[bool, int]:
        """(eingeschaltet, Minute) eines Verwalters; ohne Zeile Vorgabe an, 20:00 (D-12, D-15)."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT enabled, minute FROM review_prefs WHERE nc_user = ?", (nc_user,)
            ).fetchone()
        return (True, REVIEW_DEFAULT_MINUTE) if row is None else (bool(row[0]), int(row[1]))

    def set_review_pref(self, nc_user: str, *, enabled: bool, minute: int) -> None:
        """Rückblick-Einstellung eines Verwalters speichern."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO review_prefs (nc_user, enabled, minute) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user) DO UPDATE SET enabled = excluded.enabled, minute = excluded.minute",
                (nc_user, int(enabled), minute),
            )

    def delete_notify_data(self, world_id: str) -> None:
        """Ereignisdaten einer gelöschten Welt; der Talk-Raum bleibt (eigener Abgleich).

        ``play_daily`` bleibt bis zur normalen Aufbewahrungsfrist: Der Rückblick am
        Abend zählt auch Spielzeit in einer heute gelöschten Welt.
        """
        with self._connect() as connection:
            for table in (
                "event_cursor",
                "event_outbox",
                "world_run_state",
                "join_attempts",
                "bot_presence",
            ):
                connection.execute(f"DELETE FROM {table} WHERE world_id = ?", (world_id,))  # noqa: S608

    # Drossel der Bot-Meldungen Beitritt/Verlassen (D-22, TALK-02)

    def bot_presence_at(self, world_id: str, person: str) -> int | None:
        """Zeitpunkt der letzten Bot-Meldung zu dieser Person in dieser Welt oder None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_at FROM bot_presence WHERE world_id = ? AND nc_user = ?", (world_id, person)
            ).fetchone()
        return None if row is None else int(row[0])

    def set_bot_presence(self, world_id: str, person: str, kind: str, at: int) -> None:
        """Merkt die gesendete Meldung (nur nach erfolgreichem Senden aufrufen)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_presence (world_id, nc_user, last_kind, last_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(world_id, nc_user) DO UPDATE SET last_kind = excluded.last_kind, "
                "last_at = excluded.last_at",
                (world_id, person, kind, at),
            )

    def prune_bot_presence(self, before_at: int) -> None:
        """Bot-Drossel älter als ``before_at`` (Epoch) löschen, Frist wie die Tagesdaten (IN-03)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM bot_presence WHERE last_at < ?", (before_at,))

    def prune_review_prefs(self, keep: set[str]) -> int:
        """Rückblick-Einstellungen von Konten außerhalb ``keep`` (bestätigte Verwalter) löschen (IN-03).

        Leeres ``keep`` löscht nichts: Ohne bestätigten Stand bleibt alles, wie es ist.
        """
        if not keep:
            return 0
        marks = ",".join("?" * len(keep))
        with self._connect() as connection:
            cursor = connection.execute(
                f"DELETE FROM review_prefs WHERE nc_user NOT IN ({marks})",  # noqa: S608
                tuple(sorted(keep)),
            )
        return cursor.rowcount

    # Talk-Räume (Phase 4.1, TALK-01)

    def talk_room(self, world_id: str) -> TalkRoomRow | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT world_id, token, owner_uid, read_only, created_at, state FROM talk_rooms WHERE world_id = ?",
                (world_id,),
            ).fetchone()
        return None if row is None else _talk_row(row)

    def list_talk_rooms(self) -> list[TalkRoomRow]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT world_id, token, owner_uid, read_only, created_at, state FROM talk_rooms ORDER BY world_id"
            ).fetchall()
        return [_talk_row(row) for row in rows]

    def insert_talk_room(self, world_id: str, token: str, owner_uid: str, created_at: str) -> bool:
        """Merkt einen neuen Raum; False, wenn die Welt schon einen hat (kein zweiter Raum)."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO talk_rooms (world_id, token, owner_uid, read_only, created_at, state) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (world_id, token, owner_uid, created_at, TALK_STATE_OK),
            )
        return cursor.rowcount == 1

    def set_talk_read_only(self, world_id: str, *, on: bool) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE talk_rooms SET read_only = ? WHERE world_id = ?", (int(on), world_id))
        return cursor.rowcount == 1

    def set_talk_state(self, world_id: str, state: str) -> None:
        if state not in TALK_STATES:
            raise ValueError("Unbekannter Raumzustand")
        with self._connect() as connection:
            connection.execute("UPDATE talk_rooms SET state = ? WHERE world_id = ?", (state, world_id))

    def delete_talk_room(self, world_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM talk_rooms WHERE world_id = ?", (world_id,))


def _talk_row(row: tuple[object, ...]) -> TalkRoomRow:
    return TalkRoomRow(
        world_id=str(row[0]),
        token=str(row[1]),
        owner_uid=str(row[2]),
        read_only=bool(row[3]),
        created_at=str(row[4]),
        state=str(row[5]),
    )
