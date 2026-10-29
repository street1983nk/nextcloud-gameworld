"""SQLite storage of the desired state in ``$APP_PERSISTENT_STORAGE/gameworld.sqlite3``.

The actual state (running, stopped) always comes from Docker, never from this file.
Every method opens its own connection, because calls via
``anyio.to_thread`` come from changing threads.

Schema 3 (phase 3) stores for each invited Nextcloud account only the
player name and a rotation counter. Play passwords are deliberately not stored here:
they are derived from a secret in the Nextcloud configuration
(access/accounts.py, access/secret.py). Only the SRP verifiers per world
live in ``world_access``.
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
from gameworld.playtime.pause import ART_PAUSE, PauseState
from gameworld.playtime.plan import DayRule, Holiday, WeekPlan
from gameworld.provisioner.presets import DEFAULT_PRESET_ID

SCHEMA_VERSION = "9"

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
  preset TEXT NOT NULL DEFAULT 'mtg_kreativ',
  language TEXT NOT NULL DEFAULT 'de',
  launched_language TEXT
);
CREATE TABLE IF NOT EXISTS players (
  nc_user TEXT PRIMARY KEY,
  player_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
  rotation INTEGER NOT NULL DEFAULT 0,
  salt TEXT NOT NULL DEFAULT ''
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
CREATE TABLE IF NOT EXISTS backups (
  file_id INTEGER NOT NULL,
  owner_uid TEXT NOT NULL,
  world_id TEXT NOT NULL,
  path TEXT NOT NULL,
  name TEXT NOT NULL,
  size INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  preset TEXT NOT NULL,
  kind TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (owner_uid, file_id)
);
CREATE INDEX IF NOT EXISTS backups_owner_world ON backups (owner_uid, world_id);
CREATE TABLE IF NOT EXISTS backup_jobs (
  world_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  state TEXT NOT NULL,
  message TEXT,
  file_name TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS adults (
  nc_user TEXT PRIMARY KEY,
  set_by TEXT NOT NULL,
  set_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verwalter_seen (
  uid TEXT PRIMARY KEY,
  first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verwalter_snapshot (
  gid TEXT NOT NULL,
  uid TEXT NOT NULL,
  PRIMARY KEY (gid, uid)
);
"""

# Names of the six playtime tables from schema 4 (migration test, self-documentation).
TIME_TABLES = frozenset({"time_children", "time_plans", "holidays", "world_windows", "time_usage", "time_ledger_seen"})
# Names of the tables from schema 5 (phase 4.1: notification, pause, review, Talk).
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
# Names of the tables from schema 7 (phase 5: backup proofs and backup jobs).
BACKUP_TABLES = frozenset({"backups", "backup_jobs"})
# Names of the tables from schema 8 (phase 6: adult switch, service age and state per manager group).
ROLE_TABLES = frozenset({"adults", "verwalter_seen", "verwalter_snapshot"})
# State of a running backup or restore job (boot reconciliation, D-11).
BACKUP_JOB_RUNNING = "running"
# At most this many rows in the outbox; the oldest drop out (T-04.1-07).
OUTBOX_MAX = 1000
# An outbox row before storing: kind, player name (or empty), epoch, extra.
OutboxEntry = tuple[str, str, int, str]
# Daily marker of the summary message for foreign attempts (D-08).
FLAG_ATTEMPTS_SUMMARY = "attempts_summary"
# Daily marker per reported single notice: attempt:<world>:<name casefold> (IN-05).
FLAG_ATTEMPT_PREFIX = "attempt:"
# Default of the review: 20:00 household time zone (D-12).
REVIEW_DEFAULT_MINUTE = 1200

# Schema 1 to 2: phase 1 worlds play Minetest Game, i.e. the creative preset.
ADD_PRESET = "ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ'"
# Schema 2 to 3: counter of the access file per world (header line, feedback from the mod).
ADD_ACCESS_GENERATION = "ALTER TABLE worlds ADD COLUMN access_generation INTEGER NOT NULL DEFAULT 0"
# Schema 3 to 4: counter of the rule file per world (time mod, like access_generation).
ADD_TIME_GENERATION = "ALTER TABLE worlds ADD COLUMN time_generation INTEGER NOT NULL DEFAULT 0"
# Schema 5 to 6: salt of the password derivation per player row. Existing rows
# get the empty value and thus keep exactly their previous password.
ADD_PLAYER_SALT = "ALTER TABLE players ADD COLUMN salt TEXT NOT NULL DEFAULT ''"
# Schema 7 to 8: token of an old room without a capable moderator (D-16) and
# former manager who is still owner in Talk (D-19). Both empty as long as neither applies.
ADD_TALK_ORPHANED = "ALTER TABLE talk_rooms ADD COLUMN orphaned_token TEXT"
ADD_TALK_FORMER_OWNER = "ALTER TABLE talk_rooms ADD COLUMN former_owner TEXT"
# Schema 8 to 9: world language of the mod texts (D-27). Existing worlds become 'de'
# because their texts are German today; the account-language default applies to new
# worlds only. launched_language is the language the running server was started with.
ADD_WORLD_LANGUAGE = "ALTER TABLE worlds ADD COLUMN language TEXT NOT NULL DEFAULT 'de'"
ADD_WORLD_LAUNCHED_LANGUAGE = "ALTER TABLE worlds ADD COLUMN launched_language TEXT"
# Tables whose rows belong to a Nextcloud account (column nc_user), for forget_account.
# adults belongs here (P-08): otherwise a newly created account with the same ID would be an adult at once.
# Not included: talk_rooms.owner_uid (the room belongs to the world), invites.invited_by (who
# invited), time_ledger_seen (player name per world, protects against double booking),
# backups.owner_uid (a manager, not a child account, like talk_rooms.owner_uid) as well as
# verwalter_seen and verwalter_snapshot (managers, maintained via the group snapshot).
ACCOUNT_TABLES = (
    "players",
    "world_access",
    "time_children",
    "time_plans",
    "time_usage",
    "play_daily",
    "review_prefs",
    "review_sent",
    "bot_presence",
    "adults",
)


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
    # World language of the mod texts (D-27) and the language of the last successful start.
    language: str = "de"
    launched_language: str | None = None


@dataclass(frozen=True)
class PlayerRow:
    """Player per Nextcloud account; the password follows from secret, account, rotation and salt.

    ``salt`` empty: row from schema 5 or older (previous derivation, accounts.derive_password).
    """

    nc_user: str
    player_name: str
    rotation: int
    salt: str = ""


@dataclass(frozen=True)
class InviteRow:
    world_id: str
    kind: str
    target: str
    invited_by: str
    created_at: str


@dataclass(frozen=True)
class OutboxRow:
    """An event not yet sent (the tick files it, the event loop sends it)."""

    id: int
    world_id: str
    kind: str
    name: str
    at: int
    detail: str


@dataclass(frozen=True)
class AttemptRow:
    """A remembered foreign attempt of a day (page versuch)."""

    world_id: str
    player_name: str
    first_at: int
    count: int


@dataclass(frozen=True)
class TalkRoomRow:
    """Talk room of a world; state ok or delete_pending (world gone, room not yet).

    ``orphaned_token``: token of an old room that no manager can moderate anymore
    (D-16). ``former_owner``: former manager who is still owner in Talk (D-19).
    """

    world_id: str
    token: str
    owner_uid: str
    read_only: bool
    created_at: str
    state: str
    orphaned_token: str | None = None
    former_owner: str | None = None


@dataclass(frozen=True)
class BackupRow:
    """Integrity proof of a backup in Nextcloud Files (D-12).

    Only files with their own entry may be restored (BACKUP-02). The
    entry belongs to the manager in whose Files the file lies (D-13). Rows
    survive the deletion of the world (D-08): the files remain in
    Files, a later import (v2) needs the proof.
    """

    file_id: int
    owner_uid: str
    world_id: str
    path: str
    name: str
    size: int
    sha256: str
    preset: str
    kind: str
    created_at: str


@dataclass(frozen=True)
class BackupJobRow:
    """State of the last backup or restore job of a world (D-11).

    Exactly one row per world; it is removed when the world is deleted (plan 04).
    """

    world_id: str
    kind: str
    state: str
    message: str | None
    file_name: str | None
    started_at: str
    finished_at: str | None


TALK_STATE_OK = "ok"
TALK_STATE_DELETE_PENDING = "delete_pending"
TALK_STATES = frozenset({TALK_STATE_OK, TALK_STATE_DELETE_PENDING})

COLUMNS = tuple(field.name for field in fields(WorldRow))
UPDATABLE = frozenset(COLUMNS) - {"id"}

# A row from time_plans: nc_user, plan, weekday, allowed, limit_minutes, window_start, window_end.
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
        """Create the schema and upgrade older files; may be called repeatedly.

        The migration follows the actual column list, not
        the version number: so it is idempotent and survives even an
        aborted earlier migration. No drop, no recreating of the table.
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
            if "language" not in columns:
                connection.execute(ADD_WORLD_LANGUAGE)
            if "launched_language" not in columns:
                connection.execute(ADD_WORLD_LAUNCHED_LANGUAGE)
            player_columns = {str(info[1]) for info in connection.execute("PRAGMA table_info(players)").fetchall()}
            if "salt" not in player_columns:
                connection.execute(ADD_PLAYER_SALT)
            talk_columns = {str(info[1]) for info in connection.execute("PRAGMA table_info(talk_rooms)").fetchall()}
            if "orphaned_token" not in talk_columns:
                connection.execute(ADD_TALK_ORPHANED)
            if "former_owner" not in talk_columns:
                connection.execute(ADD_TALK_FORMER_OWNER)
            connection.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (SCHEMA_VERSION,),
            )

    def instance_id(self) -> str:
        """Random instance ID, generated once and stable afterwards."""
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

    def set_world_language(self, world_id: str, language: str) -> bool:
        """Store the world language; False if the world does not exist (the caller checks the value)."""
        with self._connect() as connection:
            cursor = connection.execute("UPDATE worlds SET language = ? WHERE id = ?", (language, world_id))
        return cursor.rowcount > 0

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

    # Players, invitations and access (schema 3)

    def get_player(self, nc_user: str) -> PlayerRow | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT nc_user, player_name, rotation, salt FROM players WHERE nc_user = ?", (nc_user,)
            ).fetchone()
        return None if row is None else PlayerRow(str(row[0]), str(row[1]), int(row[2]), str(row[3]))

    def player_names(self) -> set[str]:
        """All assigned player names, lower-cased (comparison like COLLATE NOCASE)."""
        with self._connect() as connection:
            rows = connection.execute("SELECT player_name FROM players").fetchall()
        return {str(row[0]).lower() for row in rows}

    def insert_player(self, row: PlayerRow) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO players (nc_user, player_name, rotation, salt) VALUES (?, ?, ?, ?)",
                (row.nc_user, row.player_name, row.rotation, row.salt),
            )

    def list_players(self) -> list[PlayerRow]:
        """All players per Nextcloud account, sorted by player name (manager view playtime)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, player_name, rotation, salt FROM players ORDER BY player_name"
            ).fetchall()
        return [PlayerRow(str(row[0]), str(row[1]), int(row[2]), str(row[3])) for row in rows]

    def add_invite(self, world_id: str, kind: str, target: str, invited_by: str, created_at: str) -> None:
        """Create an invitation; an existing one stays unchanged (first inviter, first time)."""
        with self._connect() as connection:
            connection.execute(
                # ON CONFLICT instead of OR IGNORE: an invalid kind still fails on the CHECK.
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
        """Effective players of the world: Nextcloud account to verifier."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, verifier FROM world_access WHERE world_id = ?", (world_id,)
            ).fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def apply_world_access(self, world_id: str, verifiers: dict[str, str]) -> int:
        """Replace the access of the world and count the generation up, in one transaction.

        Returns the new generation.
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
        """Worlds with a group invitation for one of the groups (lazy provisioning, 03-06)."""
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
        """Content of the access file: player name to verifier."""
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
        """Set ``value`` only if the value is still ``expected`` (None: none yet); True on success.

        Two simultaneous reports thus never overwrite each other (WR-04).
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
        """Account that owns the player name, ignoring upper/lower case."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT nc_user FROM players WHERE player_name = ? COLLATE NOCASE", (player_name,)
            ).fetchone()
        return None if row is None else str(row[0])

    def player_worlds(self, nc_user: str) -> list[str]:
        """Worlds in which the account currently has access."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT world_id FROM world_access WHERE nc_user = ? ORDER BY world_id", (nc_user,)
            ).fetchall()
        return [str(row[0]) for row in rows]

    def update_player_access(self, player: PlayerRow, verifiers: dict[str, str]) -> None:
        """Name or rotation of a player and its verifiers per world, in one transaction.

        ``verifiers`` maps world ID to the new verifier; each of these
        worlds gets a new generation.
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

    def direct_invite_targets(self) -> set[str]:
        """All directly invited accounts across all worlds (kind user)."""
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT target FROM invites WHERE kind = 'user'").fetchall()
        return {str(row[0]) for row in rows}

    def forget_account(self, nc_user: str) -> bool:
        """Forget an account deleted in Nextcloud completely, in ONE transaction.

        Deletes player row (the player name becomes free), direct invitations,
        access per world, playtime rules, usage, review data and the
        bot throttle of this account. Worlds in which it had access get a
        new generation; the caller rewrites the access file under the same
        lock. Call only under worlds.mutation(). True if something was deleted.
        """
        with self._connect() as connection:
            worlds = [
                str(row[0])
                for row in connection.execute(
                    "SELECT world_id FROM world_access WHERE nc_user = ? ORDER BY world_id", (nc_user,)
                ).fetchall()
            ]
            removed = connection.execute("DELETE FROM invites WHERE kind = 'user' AND target = ?", (nc_user,)).rowcount
            for table in ACCOUNT_TABLES:
                removed += connection.execute(
                    f"DELETE FROM {table} WHERE nc_user = ?",  # noqa: S608
                    (nc_user,),
                ).rowcount
            connection.executemany(
                "UPDATE worlds SET access_generation = access_generation + 1 WHERE id = ?",
                [(world_id,) for world_id in worlds],
            )
        return removed > 0

    # Adult switch per account (schema 8, ROLLE-04, D-05)

    def set_adult(self, nc_user: str, set_by: str, set_at: str) -> None:
        """Mark an account as an adult; who and when stay stored (T-06-19)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO adults (nc_user, set_by, set_at) VALUES (?, ?, ?)",
                (nc_user, set_by, set_at),
            )

    def clear_adult(self, nc_user: str) -> None:
        """Remove the mark; an unmarked account is not an error."""
        with self._connect() as connection:
            connection.execute("DELETE FROM adults WHERE nc_user = ?", (nc_user,))

    def adults(self) -> set[str]:
        """All accounts marked as adults."""
        with self._connect() as connection:
            rows = connection.execute("SELECT nc_user FROM adults").fetchall()
        return {str(row[0]) for row in rows}

    def delete_access_data(self, world_id: str) -> None:
        """Invitations and access of a deleted world; players stay (they apply to all worlds)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM invites WHERE world_id = ?", (world_id,))
            connection.execute("DELETE FROM world_access WHERE world_id = ?", (world_id,))

    # Playtime: rules, holidays, world windows, usage and ledger states (schema 4)

    @staticmethod
    def _plan_rows(nc_user: str, plan: str, week: WeekPlan) -> list[_PlanRow]:
        return [
            (nc_user, plan, weekday, int(rule.allowed), rule.limit_minutes, rule.window_start, rule.window_end)
            for weekday, rule in sorted(week.days.items())
        ]

    def set_child_plan(
        self, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None, updated_by: str, updated_at: str
    ) -> None:
        """Weekly plan (and optionally holiday plan) of a child, in one transaction.

        Writes the row in ``time_children`` (child has rules, O-10) and 7 or
        14 rows ``time_plans`` (normal, ferien). An earlier plan is replaced.
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
        """Remove rules of a child (back to no limit, O-10) and old usage.

        Usage from ``keep_from`` (today, local) stays: if parents set
        rules again the same day, there is no fresh quota (WR-04,
        owner decision). Older days nobody needs anymore (data minimization).
        """
        with self._connect() as connection:
            connection.execute("DELETE FROM time_children WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_plans WHERE nc_user = ?", (nc_user,))
            connection.execute("DELETE FROM time_usage WHERE nc_user = ? AND day < ?", (nc_user, keep_from.isoformat()))

    def child_plans(self) -> dict[str, tuple[WeekPlan, WeekPlan | None]]:
        """Only children with a row in ``time_children``: per child normal plan and holiday plan (or None)."""
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
        """Add used seconds to the local day of a child (daily totals only, pitfall 9)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO time_usage (nc_user, day, seconds) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user, day) DO UPDATE SET seconds = seconds + excluded.seconds",
                (nc_user, day.isoformat(), seconds),
            )

    def usage(self, nc_user: str, day: date) -> int:
        """Used seconds of a child on a local day (0 if no row)."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT seconds FROM time_usage WHERE nc_user = ? AND day = ?", (nc_user, day.isoformat())
            ).fetchone()
        return 0 if row is None else int(row[0])

    def prune_usage(self, before_day: date) -> None:
        """Delete usage rows before a day (retention today plus 7 days, A8/pitfall 9)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM time_usage WHERE day < ?", (before_day.isoformat(),))

    def ledger_seen(self, world_id: str) -> dict[str, int]:
        """Last seen ledger state of a world: player name to seconds."""
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
        """Book seconds per child and anchor the seen ledger state in ONE transaction.

        If a step fails (database locked, process abort), both stay
        at the old state: the next tick books the same increase exactly once,
        never twice (WR-05). ``play`` (account to seconds) lands in the same
        transaction in ``play_daily`` per world; which accounts count is decided by the
        caller (TimeEngine.book: only children with rules, IN-03).
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
        """Replace the seen ledger state of a world atomically."""
        with self._connect() as connection:
            connection.execute("DELETE FROM time_ledger_seen WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO time_ledger_seen (world_id, player_name, seconds) VALUES (?, ?, ?)",
                [(world_id, name, seconds) for name, seconds in sorted(seen.items())],
            )

    def add_holiday(self, start: date, end: date, label: str) -> int:
        """Create a holiday period for the household; returns the new id (O-08)."""
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
        """Holiday periods with id, sorted by start (for the manager API)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, start_date, end_date, label FROM holidays ORDER BY start_date, id"
            ).fetchall()
        return [
            (int(row[0]), Holiday(date.fromisoformat(str(row[1])), date.fromisoformat(str(row[2])), str(row[3])))
            for row in rows
        ]

    def set_world_window(self, world_id: str, weekday: int, window_start: int, window_end: int) -> None:
        """Set a time window of a world on a weekday (ZEIT-05)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO world_windows (world_id, weekday, window_start, window_end) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(world_id, weekday) DO UPDATE SET "
                "window_start = excluded.window_start, window_end = excluded.window_end",
                (world_id, weekday, window_start, window_end),
            )

    def replace_world_window(self, world_id: str, windows: dict[int, tuple[int, int]]) -> None:
        """Replace all time windows of a world in one transaction (missing weekday = closed)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))
            connection.executemany(
                "INSERT INTO world_windows (world_id, weekday, window_start, window_end) VALUES (?, ?, ?, ?)",
                [(world_id, weekday, start, end) for weekday, (start, end) in sorted(windows.items())],
            )

    def clear_world_window(self, world_id: str) -> None:
        """Remove all time windows of a world (the world is then always open)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))

    def world_window(self, world_id: str) -> dict[int, tuple[int, int]] | None:
        """World window per weekday or None (no rows = always open)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT weekday, window_start, window_end FROM world_windows WHERE world_id = ?", (world_id,)
            ).fetchall()
        if not rows:
            return None
        return {int(row[0]): (int(row[1]), int(row[2])) for row in rows}

    def bump_time_generation(self, world_id: str) -> int:
        """Count up the generation of a world's rule file and return the new value."""
        with self._connect() as connection:
            connection.execute("UPDATE worlds SET time_generation = time_generation + 1 WHERE id = ?", (world_id,))
            row = connection.execute("SELECT time_generation FROM worlds WHERE id = ?", (world_id,)).fetchone()
        return 0 if row is None else int(row[0])

    def delete_time_data(self, world_id: str) -> None:
        """World window and seen ledger states of a deleted world (no PRAGMA foreign_keys)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM world_windows WHERE world_id = ?", (world_id,))
            connection.execute("DELETE FROM time_ledger_seen WHERE world_id = ?", (world_id,))

    # Pause of the household (schema 5, exactly one row, ELTERN-01)

    def get_pause(self) -> PauseState | None:
        """Stored pause or None; whether it still applies is decided by the caller (pause.is_active)."""
        with self._connect() as connection:
            row = connection.execute("SELECT started_by, ab, bis, art FROM pause_state WHERE id = 1").fetchone()
        return None if row is None else PauseState(str(row[0]), int(row[1]), int(row[2]), str(row[3]))

    def set_pause(self, state: PauseState) -> None:
        """Set the pause; an existing row is overwritten."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pause_state (id, started_by, ab, bis, art) VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET started_by = excluded.started_by, ab = excluded.ab, "
                "bis = excluded.bis, art = excluded.art",
                (state.started_by, state.ab, state.bis, state.art),
            )

    def expire_pause(self, now: int, kind: str) -> bool:
        """Delete an expired pause and create one outbox row ``kind`` per world, in ONE transaction (IN-09).

        Only a short pause (kind ``pause``) is reported, "Für heute Schluss"
        ends quietly at midnight. True if a pause had expired.
        """
        with self._connect() as connection:
            row = connection.execute("SELECT art FROM pause_state WHERE id = 1 AND bis <= ?", (now,)).fetchone()
            if row is None:
                return False
            connection.execute("DELETE FROM pause_state WHERE id = 1 AND bis <= ?", (now,))
            if str(row[0]) == ART_PAUSE:
                worlds = connection.execute("SELECT id FROM worlds WHERE desired_state != 'deleted'").fetchall()
                connection.executemany(
                    "INSERT INTO event_outbox (world_id, kind, name, at, detail) VALUES (?, ?, '', ?, '')",
                    [(str(world[0]), kind, now) for world in worlds],
                )
                self._cap_outbox(connection)
        return True

    def clear_pause(self, *, ended_by: int | None = None) -> None:
        """Delete the pause; with ``ended_by`` only if it has expired by then (bis <= ended_by)."""
        with self._connect() as connection:
            if ended_by is None:
                connection.execute("DELETE FROM pause_state")
            else:
                connection.execute("DELETE FROM pause_state WHERE bis <= ?", (ended_by,))

    # Events, run state, daily playtime per world and throttles (schema 5)

    def event_cursor(self, world_id: str) -> int | None:
        """Last processed sequence of the event file or None (first contact)."""
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
        """Set the cursor and put new events into the outbox, in ONE transaction.

        Afterwards at most OUTBOX_MAX rows, the oldest drop out (T-04.1-07).
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
        """Put a single event without an event file (start, stop, pause) into the outbox."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO event_outbox (world_id, kind, name, at, detail) VALUES (?, ?, ?, ?, ?)",
                (world_id, kind, name, at, detail),
            )
            self._cap_outbox(connection)

    def outbox_batch(self, limit: int = 100) -> list[OutboxRow]:
        """Oldest outbox rows first, at most ``limit``."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, world_id, kind, name, at, detail FROM event_outbox ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [OutboxRow(int(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]), str(row[5])) for row in rows]

    def delete_outbox(self, ids: list[int]) -> None:
        """Remove sent (or discarded) outbox rows."""
        with self._connect() as connection:
            connection.executemany("DELETE FROM event_outbox WHERE id = ?", [(row_id,) for row_id in ids])

    def run_state(self, world_id: str) -> bool | None:
        """Run state last observed in the tick, or None (never observed)."""
        with self._connect() as connection:
            row = connection.execute("SELECT running FROM world_run_state WHERE world_id = ?", (world_id,)).fetchone()
        return None if row is None else bool(row[0])

    def set_run_state(self, world_id: str, *, running: bool) -> None:
        """Record the observed run state of a world (pitfall 10)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO world_run_state (world_id, running) VALUES (?, ?) "
                "ON CONFLICT(world_id) DO UPDATE SET running = excluded.running",
                (world_id, int(running)),
            )

    def play_seconds(self, day: date) -> dict[tuple[str, str], int]:
        """Seconds played on a local day per (account, world)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT nc_user, world_id, seconds FROM play_daily WHERE day = ?", (day.isoformat(),)
            ).fetchall()
        return {(str(row[0]), str(row[1])): int(row[2]) for row in rows}

    def _prune_days(self, table: str, before_day: date) -> None:
        with self._connect() as connection:
            connection.execute(f"DELETE FROM {table} WHERE day < ?", (before_day.isoformat(),))  # noqa: S608

    def prune_play_daily(self, before_day: date) -> None:
        """Delete daily playtime per world before a day (7 days like time_usage)."""
        self._prune_days("play_daily", before_day)

    def prune_join_attempts(self, before_day: date) -> None:
        """Delete remembered foreign attempts before a day."""
        self._prune_days("join_attempts", before_day)

    def prune_daily_flags(self, before_day: date) -> None:
        """Delete daily markers before a day."""
        self._prune_days("daily_flags", before_day)

    def prune_review_sent(self, before_day: date) -> None:
        """Delete send markers of the review before a day."""
        self._prune_days("review_sent", before_day)

    # Foreign attempts and daily review (schema 5, 04.1-04)

    def claim_attempt(
        self, day: date, world_id: str, name: str, at: int, limit: int = ATTEMPT_LIMIT, *, notify: bool = True
    ) -> Decision:
        """Remember a foreign attempt and claim the send, in ONE transaction (D-08, pattern 6).

        One row per (day, world, name case-insensitive); repeated attempts
        only count ``count`` up. A single notice per name, world and day,
        as long as fewer than ``limit`` are reported today, afterwards once a day the
        summary message (marker ``attempts_summary``). The caller sends only
        afterwards: nothing ever arrives twice.

        IN-05: without ``notify`` (no recipients or no link address) it is only
        remembered, nothing is claimed; the next attempt with recipients can still
        trigger the notice. Counting happens in ``daily_flags`` (marker
        ``attempt:<world>:<name>``), not via ``join_attempts``: deleting a world
        thus does not lower the daily counter.
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
            # Candidate is a name for which no notice has been claimed today yet.
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
        """Claim a daily marker: True only on the first call per (day, marker), also after a restart."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO daily_flags (day, flag) VALUES (?, ?)", (day.isoformat(), flag)
            )
        return cursor.rowcount == 1

    def attempts(self, day: date, world_id: str | None = None) -> list[AttemptRow]:
        """Foreign attempts of a local day (optionally only one world), earliest first."""
        query = "SELECT world_id, player_name, first_at, count FROM join_attempts WHERE day = ?"
        args: tuple[str, ...] = (day.isoformat(),)
        if world_id is not None:
            query += " AND world_id = ?"
            args = (*args, world_id)
        with self._connect() as connection:
            rows = connection.execute(f"{query} ORDER BY first_at, world_id, name_fold", args).fetchall()
        return [AttemptRow(str(row[0]), str(row[1]), int(row[2]), int(row[3])) for row in rows]

    def claim_review(self, nc_user: str, day: date) -> bool:
        """Claim the review: True only on the first call per manager and day (D-15, pattern 5)."""
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO review_sent (nc_user, day) VALUES (?, ?)", (nc_user, day.isoformat())
            )
        return cursor.rowcount == 1

    def review_was_sent(self, nc_user: str, day: date) -> bool:
        """Already claimed? Saves the loop recomputing the content after sending."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM review_sent WHERE nc_user = ? AND day = ?", (nc_user, day.isoformat())
            ).fetchone()
        return row is not None

    def review_pref(self, nc_user: str) -> tuple[bool, int]:
        """(enabled, minute) of a manager; without a row the default is on, 20:00 (D-12, D-15)."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT enabled, minute FROM review_prefs WHERE nc_user = ?", (nc_user,)
            ).fetchone()
        return (True, REVIEW_DEFAULT_MINUTE) if row is None else (bool(row[0]), int(row[1]))

    def set_review_pref(self, nc_user: str, *, enabled: bool, minute: int) -> None:
        """Store the review setting of a manager."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO review_prefs (nc_user, enabled, minute) VALUES (?, ?, ?) "
                "ON CONFLICT(nc_user) DO UPDATE SET enabled = excluded.enabled, minute = excluded.minute",
                (nc_user, int(enabled), minute),
            )

    def delete_notify_data(self, world_id: str) -> None:
        """Event data of a deleted world; the Talk room stays (own reconciliation).

        ``play_daily`` stays until the normal retention period: the review in the
        evening also counts playtime in a world deleted today.
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

    # Throttle of the bot messages join/leave (D-22, TALK-02)

    def bot_presence_at(self, world_id: str, person: str) -> int | None:
        """Time of the last bot message about this person in this world, or None."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT last_at FROM bot_presence WHERE world_id = ? AND nc_user = ?", (world_id, person)
            ).fetchone()
        return None if row is None else int(row[0])

    def set_bot_presence(self, world_id: str, person: str, kind: str, at: int) -> None:
        """Remember the sent message (call only after successful sending)."""
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO bot_presence (world_id, nc_user, last_kind, last_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(world_id, nc_user) DO UPDATE SET last_kind = excluded.last_kind, "
                "last_at = excluded.last_at",
                (world_id, person, kind, at),
            )

    def prune_bot_presence(self, before_at: int) -> None:
        """Delete bot throttle older than ``before_at`` (epoch), period like the daily data (IN-03)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM bot_presence WHERE last_at < ?", (before_at,))

    def prune_review_prefs(self, keep: set[str]) -> int:
        """Delete review settings of accounts outside ``keep`` (confirmed managers) (IN-03).

        Empty ``keep`` deletes nothing: without a confirmed state everything stays as it is.
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

    # Talk rooms (phase 4.1, TALK-01)

    def talk_room(self, world_id: str) -> TalkRoomRow | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_TALK_SELECT} FROM talk_rooms WHERE world_id = ?",  # noqa: S608
                (world_id,),
            ).fetchone()
        return None if row is None else _talk_row(row)

    def list_talk_rooms(self) -> list[TalkRoomRow]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_TALK_SELECT} FROM talk_rooms ORDER BY world_id"  # noqa: S608
            ).fetchall()
        return [_talk_row(row) for row in rows]

    def insert_talk_room(self, world_id: str, token: str, owner_uid: str, created_at: str) -> bool:
        """Remember a new room; False if the world already has one (no second room)."""
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

    def set_talk_owner(self, world_id: str, owner_uid: str, former_owner: str | None) -> None:
        """Gameworld owner of the room (D-16) and former manager who is still owner in Talk (D-19)."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE talk_rooms SET owner_uid = ?, former_owner = ? WHERE world_id = ?",
                (owner_uid, former_owner, world_id),
            )

    def set_talk_orphaned(self, world_id: str, token: str | None) -> None:
        """Remember the old room that no manager can moderate anymore (blocked case, D-16)."""
        with self._connect() as connection:
            connection.execute("UPDATE talk_rooms SET orphaned_token = ? WHERE world_id = ?", (token, world_id))

    def replace_talk_token(self, world_id: str, token: str, owner_uid: str, created_at: str) -> bool:
        """New room for the same world; read-only and ``orphaned_token`` stay, ``former_owner`` is dropped."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE talk_rooms SET token = ?, owner_uid = ?, created_at = ?, former_owner = NULL, state = ? "
                "WHERE world_id = ?",
                (token, owner_uid, created_at, TALK_STATE_OK, world_id),
            )
        return cursor.rowcount == 1

    def delete_talk_room(self, world_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM talk_rooms WHERE world_id = ?", (world_id,))

    # Manager groups: state per group and service age (schema 8, phase 6, ROLLE-03)

    def group_snapshot(self) -> dict[str, set[str]]:
        """Last confirmed member state per manager group."""
        with self._connect() as connection:
            rows = connection.execute("SELECT gid, uid FROM verwalter_snapshot ORDER BY gid, uid").fetchall()
        snapshot: dict[str, set[str]] = {}
        for gid, uid in rows:
            snapshot.setdefault(str(gid), set()).add(str(uid))
        return snapshot

    def replace_group_snapshot(self, gid: str, uids: set[str]) -> None:
        """Replace the state of exactly this group in one transaction; other groups stay."""
        with self._connect() as connection:
            connection.execute("DELETE FROM verwalter_snapshot WHERE gid = ?", (gid,))
            connection.executemany(
                "INSERT INTO verwalter_snapshot (gid, uid) VALUES (?, ?)", [(gid, uid) for uid in sorted(uids)]
            )

    def drop_group_snapshots(self, keep: set[str]) -> None:
        """Forget the state of all groups outside ``keep`` (groups no longer configured)."""
        with self._connect() as connection:
            rows = connection.execute("SELECT DISTINCT gid FROM verwalter_snapshot").fetchall()
            gone = [(str(row[0]),) for row in rows if str(row[0]) not in keep]
            connection.executemany("DELETE FROM verwalter_snapshot WHERE gid = ?", gone)

    def sync_verwalter_seen(self, uids: set[str], now_iso: str) -> None:
        """New managers get ``now_iso`` as their first day, former ones drop out (D-16)."""
        with self._connect() as connection:
            rows = connection.execute("SELECT uid FROM verwalter_seen").fetchall()
            gone = [(str(row[0]),) for row in rows if str(row[0]) not in uids]
            connection.executemany("DELETE FROM verwalter_seen WHERE uid = ?", gone)
            connection.executemany(
                "INSERT OR IGNORE INTO verwalter_seen (uid, first_seen) VALUES (?, ?)",
                [(uid, now_iso) for uid in sorted(uids)],
            )

    def verwalter_seniority(self) -> list[str]:
        """Managers by service age: first seen first, ties by account ID."""
        with self._connect() as connection:
            rows = connection.execute("SELECT uid FROM verwalter_seen ORDER BY first_seen, uid").fetchall()
        return [str(row[0]) for row in rows]

    # Backups (schema 7, phase 5)

    def add_backup(self, row: BackupRow) -> None:
        """Store the proof; the same (owner_uid, file_id) replaces the entry (Files assigns file_id once)."""
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO backups ({', '.join(_BACKUP_COLUMNS)}) "  # noqa: S608
                f"VALUES ({', '.join('?' for _ in _BACKUP_COLUMNS)})",
                astuple(row),
            )

    def backups_for(self, owner_uid: str, world_id: str) -> list[BackupRow]:
        """Backups of a world in this manager's Files, newest first (D-13)."""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_BACKUP_COLUMNS)} FROM backups "  # noqa: S608
                "WHERE owner_uid = ? AND world_id = ? ORDER BY created_at DESC, file_id DESC",
                (owner_uid, world_id),
            ).fetchall()
        return [_backup_row(row) for row in rows]

    def backup_by_file(self, owner_uid: str, file_id: int) -> BackupRow | None:
        """Proof for a file of this manager only; foreign entries yield None (D-13)."""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {', '.join(_BACKUP_COLUMNS)} FROM backups WHERE owner_uid = ? AND file_id = ?",  # noqa: S608
                (owner_uid, file_id),
            ).fetchone()
        return None if row is None else _backup_row(row)

    def set_backup_job(
        self,
        world_id: str,
        kind: str,
        state: str,
        message: str | None,
        file_name: str | None,
        started_at: str,
        finished_at: str | None,
    ) -> None:
        """Set the job state of a world; the one row per world is overwritten."""
        with self._connect() as connection:
            connection.execute(
                f"INSERT OR REPLACE INTO backup_jobs ({', '.join(_JOB_COLUMNS)}) "  # noqa: S608
                f"VALUES ({', '.join('?' for _ in _JOB_COLUMNS)})",
                (world_id, kind, state, message, file_name, started_at, finished_at),
            )

    def get_backup_job(self, world_id: str) -> BackupJobRow | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {', '.join(_JOB_COLUMNS)} FROM backup_jobs WHERE world_id = ?",  # noqa: S608
                (world_id,),
            ).fetchone()
        return None if row is None else _job_row(row)

    def running_backup_jobs(self) -> list[BackupJobRow]:
        """Jobs in state running (interrupted by a restart, boot reconciliation)."""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {', '.join(_JOB_COLUMNS)} FROM backup_jobs WHERE state = ? ORDER BY world_id",  # noqa: S608
                (BACKUP_JOB_RUNNING,),
            ).fetchall()
        return [_job_row(row) for row in rows]

    def delete_backup_job(self, world_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM backup_jobs WHERE world_id = ?", (world_id,))

    def reset_event_cursor(self, world_id: str) -> None:
        """Cursor of the event file of this world only, forget (re-anchor after a restore)."""
        with self._connect() as connection:
            connection.execute("DELETE FROM event_cursor WHERE world_id = ?", (world_id,))


_BACKUP_COLUMNS = tuple(field.name for field in fields(BackupRow))
_TALK_SELECT = ", ".join(field.name for field in fields(TalkRoomRow))
_JOB_COLUMNS = tuple(field.name for field in fields(BackupJobRow))


def _optional_text(value: object) -> str | None:
    return None if value is None else str(value)


def _backup_row(row: tuple[object, ...]) -> BackupRow:
    return BackupRow(
        file_id=int(str(row[0])),
        owner_uid=str(row[1]),
        world_id=str(row[2]),
        path=str(row[3]),
        name=str(row[4]),
        size=int(str(row[5])),
        sha256=str(row[6]),
        preset=str(row[7]),
        kind=str(row[8]),
        created_at=str(row[9]),
    )


def _job_row(row: tuple[object, ...]) -> BackupJobRow:
    return BackupJobRow(
        world_id=str(row[0]),
        kind=str(row[1]),
        state=str(row[2]),
        message=_optional_text(row[3]),
        file_name=_optional_text(row[4]),
        started_at=str(row[5]),
        finished_at=_optional_text(row[6]),
    )


def _talk_row(row: tuple[object, ...]) -> TalkRoomRow:
    return TalkRoomRow(
        world_id=str(row[0]),
        token=str(row[1]),
        owner_uid=str(row[2]),
        read_only=bool(row[3]),
        created_at=str(row[4]),
        state=str(row[5]),
        orphaned_token=_optional_text(row[6]),
        former_owner=_optional_text(row[7]),
    )
