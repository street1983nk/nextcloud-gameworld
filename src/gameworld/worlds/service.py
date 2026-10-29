"""Lifecycle of the worlds: create, list, start, stop, delete.

docker-py is synchronous; every Docker call therefore runs via
``anyio.to_thread.run_sync``. All mutating flows run under one
lock, so that port allocation and re-creation never interleave. The
world key is never logged.
"""

from __future__ import annotations

import contextlib
import io
import logging
import secrets
import sqlite3
import tarfile
import threading
import uuid
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import BinaryIO

import anyio.to_thread

from gameworld.backup.archive import ledger_tar
from gameworld.config import Settings
from gameworld.events.parse import new_events, parse_events, plausible
from gameworld.i18n import SUPPORTED_LANGUAGES
from gameworld.playtime.engine import TimeEngine
from gameworld.playtime.pause import (
    OUTBOX_PAUSE_START,
    PauseDecision,
    PauseResult,
    PauseWorldResult,
    is_active,
)
from gameworld.playtime.plan import WindowDay, window_days
from gameworld.provisioner.access_mod import render_access_file
from gameworld.provisioner.archive import build_access_tar, build_time_tar, build_world_files, build_world_payload
from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    DockerUnavailableError,
    MemoryUsage,
    PortInUseError,
    ProvisionerError,
    StatusFile,
    WorldNotFoundError,
)
from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.presets import DEFAULT_PRESET_ID, PRESETS, get_preset
from gameworld.provisioner.spec import LUANTI_VERSION, WorldPayload, resource_name
from gameworld.provisioner.status_mod import parse_players
from gameworld.provisioner.time_mod import parse_ledger
from gameworld.worlds.ports import NoFreePortError, allocate_port
from gameworld.worlds.reconciler import (
    BUSY_OP_STATES,
    ReconcileAction,
    decide_boot,
    decide_periodic,
    needs_volume_check,
)
from gameworld.worlds.status import (
    ERROR,
    RUNNING,
    STATUS_MOD_SCHEMA,
    WorldStatus,
    derive_status,
    parse_docker_time,
    schema_version,
)
from gameworld.worlds.store import BACKUP_JOB_RUNNING, BackupJobRow, WorldRow, WorldStore

LOG = logging.getLogger(__name__)

# One lock per process: port allocation, re-creation and deletion must not interleave.
_LOCK = threading.Lock()

# At most this many start attempts when the host port is taken (T-01-20).
MAX_START_ATTEMPTS = 3
# For this long the world list counts as fresh: several open tabs (one poll every
# 5 s each) thus do not multiply the Docker queries (T-02-25). Every mutation
# discards the cache, changes from outside appear at most 2 s later.
LIST_CACHE_SECONDS = 2.0
PORTS_EXHAUSTED = "Kein freier UDP-Port gefunden. Bitte den Portbereich GAMEWORLD_PORT_RANGE prüfen."
NOT_FOUND = "Diese Welt gibt es nicht (mehr)."
# Building the payload failed on the file system (VoxeLibre spools about 110 MB to /tmp) or on the game zip (WR-01).
PAYLOAD_FAILED = (
    "Die Weltdaten konnten nicht vorbereitet werden. Bitte freien Speicherplatz auf dem Server prüfen "
    "und es erneut versuchen."
)
# Unexpected error while creating; details are only in the log (WR-01).
CREATE_FAILED = "Die Welt konnte nicht erstellt werden. Bitte es später erneut versuchen."
# Messages of the reconciliation (worlds/reconciler.py) on the world.
RECONCILE_OOM = "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet."
RECONCILE_DATA_MISSING = "Die Weltdaten fehlen. Die Welt kann nur gelöscht werden."
RECONCILE_INTERRUPTED = "Das Erstellen wurde unterbrochen. Bitte die Welt löschen und neu erstellen."
# Process died in the middle of swapping the world data (op_state restoring_swap, RESEARCH pitfall 2).
# Deliberately NOT in DELETE_ONLY_ERRORS: restoring stays allowed in state failed (D-15),
# and the backup before the restore lies in Files.
RESTORE_INTERRUPTED = (
    "Das Wiederherstellen wurde unterbrochen. Bitte erneut wiederherstellen; "
    "die Sicherung vor dem Wiederherstellen liegt in Files."
)
# Parent action on a world that is currently being backed up or restored (HTTP 409).
WORLD_BUSY = "Die Welt wird gerade gesichert oder wiederhergestellt."
# Only reachable from code paths outside the API (the route accepts de/en/fr only).
MSG_WORLD_LANGUAGE_UNSUPPORTED = "Diese Sprache gibt es für die Spieltexte nicht."
# Worlds started before schema 9 (launched_language NULL) run German mod texts.
LEGACY_LAUNCH_LANGUAGE = "de"
# Global one-job guard (RESEARCH pattern 7): at most one job in the whole household.
JOB_RUNNING = "Es läuft schon eine Sicherung oder Wiederherstellung. Bitte kurz warten."
# Unexpected error while restarting after the offline section; details only in the log.
OFFLINE_RESTART_FAILED = "Die Welt konnte danach nicht wieder gestartet werden. Bitte die Welt starten."
# For this long the time mod announces the halt in chat before it disconnects everyone (D-09).
HALT_LEAD_SECONDS = 15
# Unexpected error in the boot reconciliation of a world; details only in the log (WR-02).
RECONCILE_FAILED = "Die Welt konnte nach dem Neustart des Servers nicht wiederhergestellt werden."
# Row with a game type this version does not know (preset removed or renamed, WR-02).
UNKNOWN_PRESET_TITLE = "Unbekannte Spielart"
TEXT_UNKNOWN_PRESET = (
    "Die Spielart dieser Welt kennt Gameworld nicht. Bitte Gameworld aktualisieren oder die Welt löschen."
)
# In these states, starting would create an empty world under the old name
# (CR-01) or start a game that was only partly installed and delete the
# abort message (WR-05); only deleting remains.
DELETE_ONLY_ERRORS = frozenset({RECONCILE_DATA_MISSING, RECONCILE_INTERRUPTED})
# Errors that hit only the affected world in the time tick (WR-06): locked or broken
# database, invalid row while rendering. Programming errors of another kind stay visible.
_TICK_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, ValueError, KeyError)

# Cleanup on deactivation (D-17 option A, P-07): AppAPI waits 60 s for the
# answer of /enabled. Stop per container is short, all in parallel, total deadline with a
# buffer below the handler's time limit (50 s, lifecycle.py).
TEARDOWN_STOP_TIMEOUT = 5
TEARDOWN_LOCK_WAIT = 10.0
TEARDOWN_DEADLINE = 45.0
TEARDOWN_WORKERS = 8
# In these states no server process runs anymore, stopping is then unnecessary.
_STOPPED_STATES = frozenset({"created", "exited", "dead"})

UNKNOWN = "unknown"
MISSING = "missing"


class DeleteOnlyError(ProvisionerError):
    """The world can no longer be started, only deleted (HTTP 409)."""


class WorldBusyError(ProvisionerError):
    """The world is currently being backed up or restored (HTTP 409)."""


def delete_only(row: WorldRow) -> bool:
    """May this world only be deleted? Determined by the row, not by the UI text."""
    return row.op_state == "failed" and row.last_error in DELETE_ONLY_ERRORS


@dataclass(frozen=True)
class OfflineTicket:
    """Result of begin_offline: what the job needs to restart or reset.

    previous_op_state and previous_error make it possible to reset a restore
    of a broken world that was rejected before the destruction to its old
    state (plan 06).
    """

    world_id: str
    was_running: bool
    preset: str
    name: str
    previous_op_state: str
    previous_error: str | None


@dataclass(frozen=True)
class BackupJobView:
    """Last backup or restore job of a world (D-11), for managers only."""

    kind: str
    state: str
    message: str | None
    file_name: str | None
    finished_at: str | None


def _job_view(job: BackupJobRow | None) -> BackupJobView | None:
    if job is None:
        return None
    return BackupJobView(
        kind=job.kind, state=job.state, message=job.message, file_name=job.file_name, finished_at=job.finished_at
    )


@dataclass
class WorldView:
    id: str
    name: str
    port: int
    docker_status: str
    op_state: str
    desired_state: str
    last_error: str | None
    created_at: str
    preset: str
    preset_title: str
    # Derived from Docker (worlds/status.py); docker_status stays for phase 1 scripts.
    status: str
    status_text: str
    # WELT-03: players only for status running, RAM only for a running container.
    players: list[str]
    memory_used_bytes: int | None
    memory_limit_bytes: int | None
    # World data missing or creating aborted: the UI offers only delete, starting gives 409.
    delete_only: bool
    # Player names of all invitees (from the database, never passwords or verifiers).
    invited_players: list[str]
    # Does the world run without loaded access protection (started before the update)? Only for status running.
    access_restart_needed: bool
    # Does the world run without a loaded time mod (no ledger)? Then it needs a restart.
    time_restart_needed: bool
    # Does the world run with an old access mod without an event file? Then no notices arrive, restart needed.
    events_restart_needed: bool
    # World time window (ZEIT-05): seven weekdays or None (always open).
    time_window: list[WindowDay] | None = None
    # Last job (D-11): errors stay visible after reloading. Never to children (AR-24).
    backup_job: BackupJobView | None = None
    # World language of the mod texts (D-27) and whether the running server still speaks another one.
    language: str = "de"
    language_restart_needed: bool = False


def world_language(row: WorldRow) -> str:
    """Effective world language; a stored value outside de/en/fr gives German (fail safe, T-06-85)."""
    return row.language if row.language in SUPPORTED_LANGUAGES else "de"


def _language_restart_needed(row: WorldRow, status: WorldStatus) -> bool:
    """The running server was started with another language than the stored one (D-27).

    Only for status running; no automatic restart, the parents decide when (T-06-88).
    """
    if status.code != RUNNING:
        return False
    launched = row.launched_language or LEGACY_LAUNCH_LANGUAGE
    return launched != world_language(row)


def _view(
    row: WorldRow,
    docker_status: str,
    status: WorldStatus,
    players: list[str] | None = None,
    memory: MemoryUsage | None = None,
    *,
    invited_players: list[str],
    access_restart_needed: bool = False,
    time_restart_needed: bool = False,
    events_restart_needed: bool = False,
    time_window: list[WindowDay] | None = None,
    backup_job: BackupJobView | None = None,
) -> WorldView:
    preset = PRESETS.get(row.preset)
    # UNKNOWN (Docker not reachable) takes precedence over the preset error.
    if preset is None and status.code != UNKNOWN:
        # Only this one world shows the error; the list of all worlds stays readable (WR-02).
        status = WorldStatus(ERROR, TEXT_UNKNOWN_PRESET)
        players = None
        access_restart_needed = False
        time_restart_needed = False
        events_restart_needed = False
    return WorldView(
        id=row.id,
        name=row.name,
        port=row.port,
        docker_status=docker_status,
        op_state=row.op_state,
        desired_state=row.desired_state,
        last_error=row.last_error,
        created_at=row.created_at,
        preset=row.preset,
        preset_title=UNKNOWN_PRESET_TITLE if preset is None else preset.title,
        status=status.code,
        status_text=status.text,
        players=players or [],
        memory_used_bytes=None if memory is None else memory.used,
        memory_limit_bytes=None if memory is None else memory.limit,
        delete_only=delete_only(row),
        invited_players=invited_players,
        access_restart_needed=access_restart_needed,
        time_restart_needed=time_restart_needed,
        events_restart_needed=events_restart_needed,
        time_window=time_window,
        backup_job=backup_job,
        language=world_language(row),
        language_restart_needed=_language_restart_needed(row, status),
    )


def _copy(view: WorldView) -> WorldView:
    """Independent copy, so callers never change the cache."""
    return replace(
        view,
        players=list(view.players),
        invited_players=list(view.invited_players),
        time_window=None if view.time_window is None else list(view.time_window),
    )


class WorldService:
    def __init__(self, store: WorldStore, provisioner: DockerProvisioner, settings: Settings) -> None:
        self._store = store
        self._provisioner = provisioner
        self._settings = settings
        # Computes rule files from schema 4 and books the ledger (synchronous, store only).
        self._time = TimeEngine(store)
        # Cache of the world list: (time from monotonic, views). The
        # generation prevents a list begun before a mutation from
        # still landing in the cache afterwards.
        self._cache_lock = threading.Lock()
        self._list_cache: tuple[float, list[WorldView]] | None = None
        self._cache_generation = 0

    async def create_world(self, name: str, preset_id: str = DEFAULT_PRESET_ID, language: str = "de") -> WorldView:
        """``language``: world language of the mod texts (D-27), by default the creating admin's
        account language; an unsupported value gives German."""
        clean = normalize_world_name(name)
        # Unknown presets fail before the lock, port allocation and database.
        get_preset(preset_id)
        chosen = language if language in SUPPORTED_LANGUAGES else "de"
        return await anyio.to_thread.run_sync(self._create_world_sync, clean, preset_id, chosen)

    async def set_world_language(self, world_id: str, language: str) -> WorldView:
        """Change the world language (D-27); it applies from the next start, no restart here.

        ValueError for an unsupported language, WorldNotFoundError for an unknown world.
        Only the store changes under the mutation lock, no Docker or Nextcloud call (T-06-88).
        """
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(MSG_WORLD_LANGUAGE_UNSUPPORTED)
        return await anyio.to_thread.run_sync(self._set_world_language_sync, world_id, language)

    async def list_worlds(self) -> list[WorldView]:
        return await anyio.to_thread.run_sync(self._list_worlds_sync)

    async def start_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._start_world_sync, world_id)

    async def stop_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._stop_world_sync, world_id)

    async def restart_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._restart_world_sync, world_id)

    async def delete_world(self, world_id: str) -> None:
        await anyio.to_thread.run_sync(self._delete_world_sync, world_id)

    # Reconciliation (worlds/reconciler.py). abandon_on_cancel: on shutdown
    # the lifespan does not wait for a hanging Docker call (up to 60 s);
    # the thread releases _LOCK in its finally anyway.

    async def boot_reconcile(self) -> bool:
        """Reconciliation at process start; False if a parent action is currently running."""
        return await anyio.to_thread.run_sync(self._boot_reconcile_sync, abandon_on_cancel=True)

    async def periodic_reconcile(self) -> None:
        """State upkeep without start or re-creation; skipped if _LOCK is taken."""
        await anyio.to_thread.run_sync(self._periodic_reconcile_sync, abandon_on_cancel=True)

    async def teardown(self) -> int:
        """Remove all own world containers (deactivation); number of errors, never an exception."""
        return await anyio.to_thread.run_sync(self.teardown_all, abandon_on_cancel=True)

    def teardown_all(self) -> int:
        """Stop and remove all world containers of this instance; volumes and desired state stay.

        D-17 option A: AppAPI calls /enabled with 0 right before deactivation, update and
        uninstall (RESEARCH F-02). Without cleanup, worlds would keep running
        after an uninstall without rules (T-06-33). World rows and
        desired_state stay unchanged, so that the boot reconciliation at the next
        start rebuilds every world that should be running from its volume (RECREATE).

        Waits at most TEARDOWN_LOCK_WAIT for _LOCK and cleans up afterwards even without
        it: AppAPI ends the process anyway, an abort would leave
        unmanaged worlds behind. The worlds proceed in parallel (P-07), one world with
        an error does not hold the others up. Only world ID and type name go into the log.
        """
        held = _LOCK.acquire(timeout=TEARDOWN_LOCK_WAIT)
        if not held:
            LOG.warning("Cleanup on deactivation without lock: a parent action is still running")
        try:
            try:
                managed = self._provisioner.list_managed()
            except Exception as exc:
                LOG.warning("Cleanup on deactivation: world containers not retrievable (%s)", type(exc).__name__)
                return 1
            if not managed:
                return 0
            return self._teardown_parallel(managed)
        finally:
            if held:
                _LOCK.release()
            self._invalidate_cache()

    def _teardown_parallel(self, managed: dict[str, ContainerInfo]) -> int:
        pool = ThreadPoolExecutor(max_workers=TEARDOWN_WORKERS, thread_name_prefix="gameworld-teardown")
        try:
            futures = {pool.submit(self._teardown_one, info): world_id for world_id, info in managed.items()}
            done, pending = wait(futures, timeout=TEARDOWN_DEADLINE)
            errors = len(pending) + sum(1 for future in done if not future.result())
            for future in pending:
                LOG.warning("Cleanup of world %s: deadline exceeded", futures[future])
        finally:
            # Do not wait for hanging Docker calls; the deadline counts more than a clean finish.
            pool.shutdown(wait=False, cancel_futures=True)
        LOG.info("Cleanup on deactivation: %d worlds, %d errors", len(managed), errors)
        return errors

    def _teardown_one(self, info: ContainerInfo) -> bool:
        """Stop one world and remove its container; True without any error."""
        ok = True
        if info.status not in _STOPPED_STATES:
            try:
                self._provisioner.stop(info.world_id, timeout=TEARDOWN_STOP_TIMEOUT)
            except Exception as exc:
                # Continue to removal: force ends the process even without a stop.
                LOG.warning("Cleanup of world %s: stop failed (%s)", info.world_id, type(exc).__name__)
                ok = False
        try:
            self._provisioner.remove_world(info.world_id, keep_volume=True)
        except Exception as exc:
            LOG.warning("Cleanup of world %s: removal failed (%s)", info.world_id, type(exc).__name__)
            ok = False
        return ok

    # Helpers

    @property
    def store(self) -> WorldStore:
        """Shared store for the access service (access/service.py)."""
        return self._store

    @property
    def time(self) -> TimeEngine:
        """Playtime calculation for the playtime service (playtime/service.py): used read-only."""
        return self._time

    @property
    def provisioner(self) -> DockerProvisioner:
        """Docker access for the backup service (backup/service.py): only snapshot_to, without the lock.

        The snapshot reads a stopped container (snapshot_to checks that itself);
        stop and restart run via stop_for_snapshot and end_offline.
        """
        return self._provisioner

    def _access_file(self, row: WorldRow) -> bytes:
        """Access file of the world, fresh from schema 3 (generation and verifier per player name).

        The same desired state yields the same bytes: the verifiers are stored with
        their salt in the database and are not re-salted on every render.
        """
        fresh = self._store.get_world(row.id)
        generation = row.access_generation if fresh is None else fresh.access_generation
        return render_access_file(generation, self._store.access_entries(row.id))

    def _time_file(self, row: WorldRow) -> bytes:
        """Rule file of the time mod for this world, fresh from schema 4.

        Before rendering, the ledger of the world is read and booked (pitfall
        7: also with a stopped container, before the new start touches the volume).
        Without rules it stays with head and closing line (opt-in, O-10).
        """
        try:
            self._book_ledger(row.id)
        except ProvisionerError as exc:
            # An unreadable ledger must not prevent the start; the rest comes from the DB.
            LOG.warning("World %s: ledger not readable before rendering: %s", row.id, exc)
        data, _changed = self._time.render(row.id)
        return data

    def _book_ledger(self, world_id: str) -> None:
        """Read the ledger of the world and book the increases; if missing, nothing happens.

        A missing container (WorldNotFoundError) means: book nothing.
        Other read errors (ProvisionerError) are passed on by the caller and
        isolated per world (tick_time); the file content is never logged.
        """
        try:
            status_file = self._provisioner.read_time_ledger(world_id)
        except WorldNotFoundError:
            return
        if status_file is None:
            return
        ledger = parse_ledger(status_file.content)
        if ledger is None and status_file.content:
            # Present, but without head or closing line: never skip silently (WR-03).
            # Usually half written (the next tick heals it), permanently it means: too large or broken.
            LOG.warning(
                "World %s: ledger incomplete (%d bytes), not booked in this tick",
                world_id,
                len(status_file.content),
            )
        self._time.book(world_id, ledger)

    def mutation(self) -> contextlib.AbstractContextManager[None]:
        """Same lock as world mutations, with cache discard (for the access service).

        Enter only from a worker thread (anyio.to_thread), never in the event loop.
        """
        return self._mutating()

    @contextlib.contextmanager
    def try_mutation(self) -> Iterator[bool]:
        """Like mutation(), but without waiting: returns False if an action is currently running.

        For reconciliations when listing: reading status must never wait behind a
        create (pitfall 6 from phase 2). Enter only from a worker thread.
        """
        if not _LOCK.acquire(blocking=False):
            yield False
            return
        self._invalidate_cache()
        try:
            yield True
        finally:
            _LOCK.release()
            self._invalidate_cache()

    def push_access(self, world_id: str) -> bool:
        """Write the current access and rule file into the running or stopped world.

        Call only inside mutation(). False means: the files are not yet in
        the world; the database stays authoritative, and the next start
        writes them (_launch). push_time follows in the same lock block: a freshly
        invited child with rules is in the rule file immediately, not only after
        the next tick. File contents are never logged.
        """
        access_file = self._access_file(self._row(world_id))
        try:
            self._provisioner.write_world_files(world_id, build_access_tar(access_file))
        except WorldNotFoundError:
            LOG.info("World %s: no container, the access file comes at the next start", world_id)
            return False
        except ProvisionerError as exc:
            LOG.warning("World %s: access file not written, it comes at the next start: %s", world_id, exc)
            return False
        return self.push_time(world_id)

    def push_time(self, world_id: str) -> bool:
        """Write the current rule file into the running or stopped world.

        Call only inside mutation() (or try_mutation). Always renders
        fresh from the database (on a change the generation counts up) and
        writes it. False means: no container or Docker gone, the next start
        writes it. File contents are never logged.
        """
        data, _changed = self._time.render(world_id)
        try:
            self._write_time(world_id, data)
        except WorldNotFoundError:
            LOG.info("World %s: no container, the rule file comes at the next start", world_id)
            return False
        except ProvisionerError as exc:
            LOG.warning("World %s: rule file not written, it comes at the next start: %s", world_id, exc)
            return False
        return True

    def _write_time(self, world_id: str, data: bytes) -> None:
        """Write the rule file; if that fails, the rendered state is discarded (CR-01).

        Without the discard the render cache would treat the state that never arrived as
        written, and the 15 s tick (only on ``changed``) would never catch it up.
        """
        try:
            self._provisioner.write_world_files(world_id, build_time_tar(data))
        except BaseException:
            self._time.forget(world_id)
            raise

    def _collect_events(self, world_id: str, now: int) -> None:
        """Put new lines of the event file into the SQLite outbox (no network call).

        Cursor and outbox rows land in one transaction (store.take_events);
        first contact with an old file and rollback only anchor (new_events).
        If the file (old mod) or the container is missing, nothing happens. An
        incomplete file is reported with its size, never with its content.
        """
        try:
            events_file = self._provisioner.read_events(world_id)
        except WorldNotFoundError:
            return
        if events_file is None:
            return
        parsed = parse_events(events_file.content)
        if parsed is None:
            if events_file.content:
                LOG.warning(
                    "World %s: event file incomplete (%d bytes), skipped in this tick",
                    world_id,
                    len(events_file.content),
                )
            return
        last_seq, events = parsed
        cursor = self._store.event_cursor(world_id)
        fresh, new_cursor = new_events(cursor, last_seq, events, now=now)
        if not fresh and new_cursor == cursor:
            return
        # Implausible timestamps are dropped, the cursor advances anyway (IN-10).
        kept = plausible(fresh, now=now)
        self._store.take_events(world_id, new_cursor, [(event.kind, event.name, event.at, "") for event in kept])

    def _track_run_state(self, rows: list[WorldRow], managed: dict[str, ContainerInfo], now: int) -> None:
        """Start and stop from the observed Docker state (pitfall 10), never from requests.

        The first observation of a world only anchors. A restart between two
        ticks does not appear (deliberately quiet). Worlds being deleted do not count.
        """
        for row in rows:
            # Busy worlds stop on purpose (backup, restore): no "world off/on" to Talk
            # (pitfall 9). The run state stays; afterwards only a real change reports.
            if row.desired_state == "deleted" or row.op_state in BUSY_OP_STATES:
                continue
            info = managed.get(row.id)
            running = info is not None and info.status == RUNNING
            before = self._store.run_state(row.id)
            if before is running:
                continue
            if before is not None:
                self._store.add_outbox(row.id, "start" if running else "stop", "", now)
            self._store.set_run_state(row.id, running=running)

    def tick_time(self) -> None:
        """15 s time tick: book the ledger of all running worlds, write changed rule files.

        Takes only try_mutation() (never blocking, pitfall 6): if a
        parent action is running, the tick is skipped. First all worlds are booked,
        then rendered: so world B sees the usage from world A (one quota across
        all worlds, O-03). An error of one world affects only that world. In addition,
        start/stop transitions and new events land in the SQLite outbox;
        sending happens only in the event loop (phase 4.1), the tick makes no network call.
        """
        with self.try_mutation() as acquired:
            if not acquired:
                return
            managed = self._provisioner.list_managed()
            rows = self._store.list_worlds()
            running = [row for row in rows if (info := managed.get(row.id)) is not None and info.status == RUNNING]
            now = self._time.now()
            try:
                self._track_run_state(rows, managed, now)
            except _TICK_ERRORS as exc:
                # The next tick catches up start/stop reports; the rule files take precedence.
                LOG.warning("Run state not recorded in the tick (%s)", type(exc).__name__)
            for row in running:
                try:
                    self._book_ledger(row.id)
                except ProvisionerError as exc:
                    LOG.warning("World %s: ledger not booked in the tick: %s", row.id, exc)
                except _TICK_ERRORS as exc:
                    # WR-06: locked database or broken row hits only this world.
                    LOG.warning("World %s: ledger not booked in the tick (%s)", row.id, type(exc).__name__)
                try:
                    self._collect_events(row.id, now)
                except (ProvisionerError, *_TICK_ERRORS) as exc:
                    # Only world ID and error type, never file content or player names (T-04.1-08).
                    LOG.warning("World %s: events not read in the tick (%s)", row.id, type(exc).__name__)
            for row in running:
                try:
                    data, changed = self._time.render(row.id)
                    if changed:
                        self._write_time(row.id, data)
                except ProvisionerError as exc:
                    LOG.warning("World %s: rule file not written in the tick: %s", row.id, exc)
                except _TICK_ERRORS as exc:
                    # WR-06: the next tick renders again; the remaining worlds get their file anyway.
                    self._time.forget(row.id)
                    LOG.warning("World %s: rule file not written in the tick (%s)", row.id, type(exc).__name__)

    def apply_pause_sync(self, decide: PauseDecision, outbox_kind: str) -> PauseResult:
        """Set or end a pause and roll it out to all worlds immediately (ELTERN-01, D-01, D-25).

        Everything under mutation() in a worker thread (never in the event loop):
        ``decide`` gets the running pause (or None) and now and returns the
        new state (None = no pause). Afterwards every world gets the rule file
        (push_time, result ``applied``). If a world is still running with an
        old mod when the pause is set (no event file from this run), it is restarted
        without warning (stop plus _launch, never _restart_world_sync: _LOCK is not
        reentrant). Each world gets an outbox row for the bot (04.1-06), for
        ``pause_start`` with the end as extra. Ending without a running pause
        changes nothing and creates no row. Errors stay isolated per world.
        """
        with self._mutating():
            now = self._time.now()
            current = self._store.get_pause()
            if not is_active(current, now):
                current = None
            state = decide(current, now)
            if state is None:
                self._store.clear_pause()
            else:
                self._store.set_pause(state)
            try:
                managed = self._provisioner.list_managed()
            except ProvisionerError as exc:
                # Without the Docker list no restart; push_time reports per world itself.
                LOG.warning("Pause: Docker list not retrievable (%s)", type(exc).__name__)
                managed = {}
            detail = str(state.bis) if state is not None and outbox_kind == OUTBOX_PAUSE_START else ""
            # The bot reports only a real change (WR-01): a pause button during
            # "Für heute Schluss" or without a later end changes nothing and reports nothing.
            announce = (state is not None or current is not None) and state != current
            results: list[PauseWorldResult] = []
            for row in self._store.list_worlds():
                if row.desired_state == "deleted":
                    continue
                results.append(self._pause_world(row, managed.get(row.id), restart=state is not None))
                if announce:
                    self._store.add_outbox(row.id, outbox_kind, "", now, detail)
            return PauseResult(state=state, worlds=results)

    def _pause_world(self, row: WorldRow, container: ContainerInfo | None, *, restart: bool) -> PauseWorldResult:
        """Rule file with the new pause state into a world; restart old mods of running worlds (D-25).

        Busy worlds (backup, restore) get only the rule file: the container
        currently belongs to the job, which starts the world itself afterwards.
        """
        if (
            restart
            and row.op_state not in BUSY_OP_STATES
            and not delete_only(row)
            and container is not None
            and container.status == RUNNING
            # Fail closed (AR-41-09): if the mod state is unclear, the world restarts.
            # The pause disconnects everyone anyway, only this makes @pause reliably effective.
            and self._events_restart_needed(row, container, WorldStatus(RUNNING, ""), unknown=True)
        ):
            try:
                try:
                    self._provisioner.stop(row.id)
                except WorldNotFoundError:
                    LOG.info("World %s: container missing, the restart for the pause recreates it", row.id)
                self._launch(row)
            except ProvisionerError as exc:
                # Only world ID and error type (T-04.1-08); the world shows the error as on restart.
                LOG.warning("World %s: restart for the pause failed (%s)", row.id, type(exc).__name__)
                self._fail(row.id, exc)
                return PauseWorldResult(world_id=row.id, name=row.name, applied=False, restarted=False)
            self._store.update_world(row.id, op_state="ready", last_error=None)
            return PauseWorldResult(world_id=row.id, name=row.name, applied=True, restarted=True)
        return PauseWorldResult(world_id=row.id, name=row.name, applied=self.push_time(row.id), restarted=False)

    # Offline sections for backup and restore (plan 05/06).
    #
    # Synchronous, called from worker threads via anyio.to_thread and never
    # nested (_LOCK is not reentrant). Each section holds _LOCK only
    # for its own duration: between two sections (snapshot, upload,
    # waiting time of the chat notice) pause, invitations and time tick
    # keep running (RESEARCH pitfall 3). The busy state is carried by the database.

    def begin_offline(self, world_id: str, op_state: str, *, allow_failed: bool = False) -> OfflineTicket:
        """Put the world into a busy state and return the ticket for the job.

        Raises WorldBusyError if this world is already busy (WORLD_BUSY) or
        another job is running anywhere (JOB_RUNNING, also in the upload phase).
        A world that can only be deleted cannot be backed up
        (DeleteOnlyError); allow_failed=True (restore, D-15) allows it.
        """
        if op_state not in BUSY_OP_STATES:
            msg = f"Kein Busy-Zustand als op_state: {op_state}"
            raise ValueError(msg)
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            if not allow_failed:
                self._refuse_delete_only(row)
            others_busy = any(other.op_state in BUSY_OP_STATES for other in self._store.list_worlds())
            if others_busy or self._store.running_backup_jobs():
                raise WorldBusyError(JOB_RUNNING)
            self._store.update_world(world_id, op_state=op_state)
            return OfflineTicket(
                world_id=world_id,
                was_running=row.desired_state == "running",
                preset=row.preset,
                name=row.name,
                previous_op_state=row.op_state,
                previous_error=row.last_error,
            )

    def players_online(self, world_id: str) -> int:
        """Players according to the status file of this run, independent of op_state (D-09, T-05-46).

        Deliberately does not read via _status_file or _view: those return nothing
        in busy states, but announce_halt runs only after begin_offline.
        Without _LOCK (read only). A stopped or missing container, a world without a
        status mod, a file from an earlier run and any Docker error yield 0.
        """
        try:
            container = self._provisioner.list_managed().get(world_id)
            if container is None or container.status != RUNNING or schema_version(container.schema) < STATUS_MOD_SCHEMA:
                return 0
            status_file = self._provisioner.read_status_file(world_id)
        except ProvisionerError as exc:
            LOG.warning("World %s: players not countable before the halt (%s)", world_id, type(exc).__name__)
            return 0
        if status_file is None:
            return 0
        written = parse_docker_time(status_file.mtime)
        started = parse_docker_time(container.started_at)
        # Names from an earlier run never count (pitfall 3 from phase 2).
        if written is None or started is None or written < started:
            return 0
        return len(parse_players(status_file.content))

    def announce_halt(self, world_id: str, now: int) -> int | None:
        """Announce the halt in chat if anyone is playing; returns the time ``ab`` or None.

        Sets the volatile halt in the time calculation and writes the rule file
        immediately (push_time); the time mod warns, blocks joins and disconnects from ``ab``.
        """
        if self.players_online(world_id) == 0:
            return None
        ab = now + HALT_LEAD_SECONDS
        with self._mutating():
            self._time.set_halt(world_id, ab)
            if not self.push_time(world_id):
                LOG.warning("World %s: halt notice not written into the world", world_id)
        return ab

    def stop_for_snapshot(self, world_id: str) -> None:
        """Stop the container for the snapshot; books nothing and changes no parent wish.

        A missing container is no error (the snapshot then reports it itself).
        """
        with self._mutating():
            try:
                self._provisioner.stop(world_id)
            except WorldNotFoundError:
                LOG.info("World %s: container missing, stopping before the snapshot is a no-op", world_id)

    def end_offline(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """End the offline section: halt gone, restart if was_running, state back.

        Pattern _restart_world_sync without the stop. The state ALWAYS returns to ready
        or failed (D-11, pitfall 7); a start error is not raised
        but returned, so the job reports it as a job error.
        """
        with self._mutating():
            self._time.clear_halt(world_id)
            return self._relaunch(world_id, was_running)

    def abort_offline(self, ticket: OfflineTicket) -> None:
        """Abort a job before the stop: state as before, halt gone, no Docker call.

        Resets op_state and last_error to previous_op_state and previous_error from
        the ticket (a previously failed world stays failed).
        The world is still running: the rule file is written immediately without ``@halt``,
        otherwise the time mod would disconnect the children anyway. If the world is gone
        meanwhile, nothing happens.
        """
        with self._mutating():
            self._time.clear_halt(ticket.world_id)
            if self._store.get_world(ticket.world_id) is None:
                return
            self._store.update_world(
                ticket.world_id, op_state=ticket.previous_op_state, last_error=ticket.previous_error
            )
            if not self.push_time(ticket.world_id):
                LOG.warning("World %s: rule file without halt not written, the tick catches up", ticket.world_id)

    def book_ledger(self, world_id: str) -> None:
        """Public entry for _book_ledger (restore, D-06), under the lock."""
        with self._mutating():
            self._book_ledger(world_id)

    # Swapping the world data on restore (plan 06, RESEARCH pattern 5).

    def mark_swap(self, world_id: str) -> None:
        """Persist restoring_swap before anything is destroyed (T-05-33).

        If the process dies afterwards, the boot reconciliation turns it into RESTORE_INTERRUPTED
        (repeatable, not delete-only) instead of starting the world with a half volume.
        """
        with self._mutating():
            self._row(world_id)
            self._store.update_world(world_id, op_state="restoring_swap")

    def restore_swap(self, world_id: str, restore_tar: BinaryIO, ledger: bytes | None) -> None:
        """Rebuild the world over a fresh volume and install the world content.

        The phase 1 creation path (_payload) supplies preset world.mt, mods and
        a fresh access and rule file with today's invitations and rules
        (D-06); on top comes the filtered world content, then the preserved
        ledger. The old volume with its hot SQLite journal is dropped (T-05-32).
        The Docker steps run without _LOCK, the busy state is carried by the
        database. Errors go to the caller, who repeats the swap.
        """
        # Before _payload: otherwise the new rule file renders the halt too (T-05-50).
        self._time.clear_halt(world_id)
        row = self._row(world_id)
        try:
            self._provisioner.remove_world(world_id, keep_volume=False)
        except WorldNotFoundError:
            LOG.info("World %s: no container before the swap", world_id)
        self._provisioner.ensure_image()
        with self._payload(row) as payload:
            self._provisioner.create_world_container(row.id, row.port, payload, reuse_volume=False)
        restore_tar.seek(0)
        self._provisioner.put_world_archive(world_id, restore_tar)
        if ledger is not None:
            self._provisioner.put_world_archive(world_id, io.BytesIO(ledger_tar(ledger)))
        # New event file in the fresh volume: first contact re-anchors, no old reports.
        self._store.reset_event_cursor(world_id)
        self._time.forget(world_id)
        self._invalidate_cache()

    def finish_swap(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """End of the swap: halt gone, start if was_running, state ready (pattern end_offline).

        The parent wish (desired_state) stays unchanged. A start error is
        returned, not raised; the world is then in failed.
        """
        with self._mutating():
            self._time.clear_halt(world_id)
            return self._relaunch(world_id, was_running)

    def mark_restore_interrupted(self, world_id: str) -> None:
        """Swap finally failed: failed with RESTORE_INTERRUPTED, repeatable (D-15)."""
        with self._mutating():
            self._time.clear_halt(world_id)
            self._time.forget(world_id)
            if self._store.get_world(world_id) is None:
                return
            self._store.update_world(world_id, op_state="failed", last_error=RESTORE_INTERRUPTED)

    def _relaunch(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """Common restart; only under _mutating(), after the halt was removed."""
        self._time.forget(world_id)
        try:
            row = self._row(world_id)
            if was_running:
                self._launch(row)
        except ProvisionerError as exc:
            LOG.warning("World %s: restart after the offline section failed (%s)", world_id, exc)
            self._fail(world_id, exc)
            return exc
        except Exception:
            LOG.exception("World %s: restart after the offline section failed unexpectedly", world_id)
            failure = ProvisionerError(OFFLINE_RESTART_FAILED)
            self._fail(world_id, failure)
            return failure
        self._store.update_world(world_id, op_state="ready", last_error=None)
        return None

    @contextlib.contextmanager
    def _payload(self, row: WorldRow) -> Iterator[WorldPayload]:
        """Content from the preset of the DB row, also on re-creation (pitfall 2).

        Closes the tar (temporary file) after installing, also on error.
        File system and archive errors (full disk, broken zip) arrive as
        ProvisionerError, so every caller takes its cleanup path (WR-01).
        """
        preset = get_preset(row.preset)
        try:
            payload = build_world_payload(
                preset,
                render_minetest_conf(row.name, row.world_key, preset),
                render_world_mt(preset),
                self._access_file(row),
                self._time_file(row),
                language=world_language(row),
            )
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            LOG.warning("World data for world %s not prepared: %r", row.id, exc)
            raise ProvisionerError(PAYLOAD_FAILED) from exc
        try:
            yield payload
        finally:
            payload.archive.close()

    def _row(self, world_id: str) -> WorldRow:
        row = self._store.get_world(world_id)
        if row is None:
            raise WorldNotFoundError(NOT_FOUND)
        return row

    def _used_ports(self) -> set[int]:
        """Ports from the database and all ports bound by containers of the host."""
        low, high = self._settings.port_range
        used = self._store.used_ports()
        try:
            used |= self._provisioner.used_host_ports(low, high)
        except ProvisionerError as exc:
            # The next Docker call then fails anyway with a clear message.
            LOG.warning("Bound host ports not retrievable, database ports only: %s", exc)
        return used

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._list_cache = None
            self._cache_generation += 1

    @contextlib.contextmanager
    def _mutating(self) -> Iterator[None]:
        """Mutation under _LOCK; the list cache is discarded before and after, also on errors."""
        self._invalidate_cache()
        try:
            with _LOCK:
                yield
        finally:
            self._invalidate_cache()

    def _views(self, rows: list[WorldRow]) -> list[WorldView]:
        return self._collect(rows)[0]

    def _collect(self, rows: list[WorldRow]) -> tuple[list[WorldView], bool]:
        """Views with status from Docker: one list_managed, status file only where needed.

        Single code path for list and single view. The database supplies only
        creating/failed and the parent wish, everything else comes from Docker.
        The second value says whether Docker was reachable (only then is it cached).
        """
        try:
            managed = self._provisioner.list_managed()
        except ProvisionerError as exc:
            LOG.warning("Docker status not retrievable, showing unknown: %s", exc)
            unknown = [
                _view(
                    row,
                    UNKNOWN,
                    derive_status(
                        op_state=row.op_state,
                        desired_state=row.desired_state,
                        last_error=row.last_error,
                        container=None,
                        reachable=False,
                        status_mtime=None,
                    ),
                    invited_players=self._invited(row),
                    time_window=self._time_window(row),
                    backup_job=self._backup_job(row),
                )
                for row in rows
            ]
            return unknown, False
        return [self._view_from_docker(row, managed.get(row.id)) for row in rows], True

    def _status_file(self, row: WorldRow, container: ContainerInfo | None) -> StatusFile | None:
        """Status file (mtime and content), only for running worlds with a status mod (schema 2)."""
        if (
            container is None
            or container.status != "running"
            or row.op_state in {"creating", "failed"}
            # Busy: status and text come from op_state alone (D-10); the player count
            # for the chat notice reads directly (players_online).
            or row.op_state in BUSY_OP_STATES
            or schema_version(container.schema) < STATUS_MOD_SCHEMA
        ):
            return None
        try:
            status_file = self._provisioner.read_status_file(row.id)
        except ProvisionerError as exc:
            # Isolated per world: the world then shows "Startet gerade", the list stays.
            LOG.warning("Status file of world %s not readable: %s", row.id, exc)
            return None
        return status_file

    def _invited(self, row: WorldRow) -> list[str]:
        """Player names of the invitees, sorted; only the names, never the verifiers."""
        return sorted(self._store.access_entries(row.id))

    def _time_window(self, row: WorldRow) -> list[WindowDay] | None:
        """World time window from the database (ZEIT-05); None means: always open."""
        return window_days(self._store.world_window(row.id))

    def _backup_job(self, row: WorldRow) -> BackupJobView | None:
        """Last job of the world from the database (D-11), independent of Docker."""
        return _job_view(self._store.get_backup_job(row.id))

    def _access_restart_needed(self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus) -> bool:
        """Does the world still run without loaded access protection (03-RESEARCH.md pitfall 4)?

        Only for status running: the access mod writes its state file as soon as
        it has loaded an access file. If it is missing or older than the
        start of the container, the world was started before the update and needs
        a restart. Same rule as readiness (mtime >= StartedAt).
        A read error affects only this world: False plus a warning.
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            state = self._provisioner.read_access_state(row.id)
        except ProvisionerError as exc:
            LOG.warning("Access state of world %s not readable: %s", row.id, exc)
            return False
        if state is None:
            return True
        written = parse_docker_time(state.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            # Without a readable start time, only the presence of the file counts.
            return False
        return written is None or written < started

    def _time_restart_needed(self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus) -> bool:
        """Does the world still run without a loaded time mod (started before the update)?

        Only for status running: the time mod writes its ledger on mods_loaded.
        If it is missing or older than the start of the container, the world does not carry
        the time mod yet and needs a restart. Same rule and isolation
        as _access_restart_needed; a read error affects only this world.
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            ledger = self._provisioner.read_time_ledger(row.id)
        except ProvisionerError as exc:
            LOG.warning("Playtime state of world %s not readable: %s", row.id, exc)
            return False
        if ledger is None:
            return True
        written = parse_docker_time(ledger.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            return False
        return written is None or written < started

    def _events_restart_needed(
        self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus, *, unknown: bool = False
    ) -> bool:
        """Does the world still run with an old access mod without an event file (pattern 3)?

        Only for status running: the new mod writes the event file on
        mods_loaded. If it is missing or older than the start of the container,
        no notices arrive from this world until it restarts. Same rule
        and isolation as _time_restart_needed; a read error or a missing
        StartedAt yields ``unknown`` (display: False, pause: True).
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            events_file = self._provisioner.read_events(row.id)
        except ProvisionerError as exc:
            LOG.warning("Event file of world %s not readable: %s", row.id, exc)
            return unknown
        if events_file is None:
            return True
        written = parse_docker_time(events_file.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            return unknown
        return written is None or written < started

    def _memory(self, row: WorldRow, container: ContainerInfo | None) -> MemoryUsage | None:
        """RAM only for running containers; an error affects only this world."""
        if container is None or container.status != "running":
            return None
        try:
            return self._provisioner.memory_bytes(row.id)
        except ProvisionerError as exc:
            LOG.warning("Memory of world %s not retrievable: %s", row.id, exc)
            return None

    def _view_from_docker(self, row: WorldRow, container: ContainerInfo | None) -> WorldView:
        status_file = self._status_file(row, container)
        status = derive_status(
            op_state=row.op_state,
            desired_state=row.desired_state,
            last_error=row.last_error,
            container=container,
            reachable=True,
            status_mtime=None if status_file is None else status_file.mtime,
        )
        # Players only from a file of this run: running presupposes mtime >= StartedAt (pitfall 3).
        players = parse_players(status_file.content) if status.code == RUNNING and status_file is not None else []
        docker_status = MISSING if container is None else container.status
        return _view(
            row,
            docker_status,
            status,
            players,
            self._memory(row, container),
            invited_players=self._invited(row),
            access_restart_needed=self._access_restart_needed(row, container, status),
            time_restart_needed=self._time_restart_needed(row, container, status),
            events_restart_needed=self._events_restart_needed(row, container, status),
            time_window=self._time_window(row),
            backup_job=self._backup_job(row),
        )

    def _launch(self, row: WorldRow) -> None:
        """Start the container; if the port is taken, re-create with the next free port.

        Before every start attempt it writes all three world mods, the current
        access file and the rule file of the time mod into the world folder
        (put_archive, no exec): so older worlds also get the access and
        time mod, and the mod code follows app updates. The ledger in the volume
        stays untouched.
        The volume with the world data is preserved; only minetest.conf,
        world.mt and the game are installed again (deterministic content).
        If the container is missing entirely (error path of the port saga or docker rm from
        outside), it is re-created from the existing volume instead of reporting the world
        as vanished. If the volume is missing too, the start ends with
        DeleteOnlyError instead of an empty world. At most MAX_START_ATTEMPTS
        start attempts when the port is taken, then NoFreePortError.
        """
        tried = {row.port}
        recreated = False
        attempt = 0
        while True:
            try:
                # In the same try: if the container is already missing while writing, the re-creation applies.
                language = world_language(row)
                world_files = build_world_files(self._access_file(row), self._time_file(row), language=language)
                try:
                    self._provisioner.write_world_files(row.id, world_files)
                except BaseException:
                    # Rule file did not arrive: the next tick writes it again (CR-01).
                    self._time.forget(row.id)
                    raise
                self._provisioner.start_world(row.id)
                # The running mods now speak this language (language_restart_needed, D-27).
                if row.launched_language != language:
                    self._store.update_world(row.id, launched_language=language)
                    row.launched_language = language
                return
            except WorldNotFoundError:
                # Volume present, container gone: re-create from the volume.
                # At most once per start; the re-creation continues through the
                # port saga on the next loop pass.
                if recreated:
                    raise
                if not self._provisioner.volume_exists(row.id):
                    # Never create an empty world under the old name: Docker
                    # silently created a missing volume empty on mount (CR-01).
                    raise DeleteOnlyError(RECONCILE_DATA_MISSING) from None
                recreated = True
                LOG.warning("World %s: container missing, re-creating it from the volume", row.id)
                self._provisioner.ensure_image()
                with self._payload(row) as payload:
                    self._provisioner.create_world_container(row.id, row.port, payload, reuse_volume=True)
                continue
            except PortInUseError as exc:
                attempt += 1
                LOG.warning("World %s: start attempt %d failed: %s", row.id, attempt, exc)
                if attempt == MAX_START_ATTEMPTS:
                    break
            self._provisioner.remove_world(row.id, keep_volume=True)
            try:
                port = allocate_port(self._settings.port_range, self._used_ports() | tried)
            except NoFreePortError:
                break
            tried.add(port)
            self._provisioner.ensure_image()
            with self._payload(row) as payload:
                self._provisioner.create_world_container(row.id, port, payload, reuse_volume=True)
            self._store.update_world(row.id, port=port)
            row.port = port
        raise NoFreePortError(PORTS_EXHAUSTED)

    def _fail(self, world_id: str, exc: ProvisionerError) -> None:
        self._store.update_world(world_id, op_state="failed", last_error=str(exc))

    def _discard_failed_create(self, world_id: str, exc: ProvisionerError, *, touched_docker: bool) -> None:
        """Clean up after a failed create, so that no failed row occupies a UDP port.

        If demonstrably nothing was created in Docker (error already at
        ensure_image), the row is deleted without a Docker call. Otherwise it is
        cleaned up; if that succeeds, the row disappears too. Only if the
        cleanup fails does the row stay as failed with the original
        message, so that a later delete removes container and volume.
        """
        if touched_docker:
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as cleanup:
                LOG.warning("Cleanup after failed creation of world %s failed: %s", world_id, cleanup)
                self._fail(world_id, exc)
                return
        self._store.delete_world(world_id)

    def _current(self, world_id: str) -> WorldView:
        return self._views([self._row(world_id)])[0]

    @staticmethod
    def _refuse_delete_only(row: WorldRow) -> None:
        """Start and restart of a world that can only be deleted change nothing."""
        if delete_only(row):
            raise DeleteOnlyError(row.last_error or RECONCILE_DATA_MISSING)

    @staticmethod
    def _refuse_busy(row: WorldRow) -> None:
        """During backup or restore the container belongs to the job (T-05-15)."""
        if row.op_state in BUSY_OP_STATES:
            raise WorldBusyError(WORLD_BUSY)

    def _refuse_job_running(self, world_id: str) -> None:
        """Block deleting during the upload phase (T-05-45).

        After end_offline, op_state is back at ready, but the job is still
        running. Without this block, deleting would remove the job row, the
        one-job guard would fall away and the completion would write an orphaned row.
        """
        job = self._store.get_backup_job(world_id)
        if job is not None and job.state == BACKUP_JOB_RUNNING:
            raise WorldBusyError(WORLD_BUSY)

    # Flows

    def _create_world_sync(self, name: str, preset_id: str, language: str) -> WorldView:
        with self._mutating():
            instance = self._store.instance_id()
            world_id = uuid.uuid4().hex[:12]
            secret = secrets.token_urlsafe(9)
            port = allocate_port(self._settings.port_range, self._used_ports())
            resource = resource_name(instance, world_id)
            row = WorldRow(
                id=world_id,
                name=name,
                port=port,
                container_name=resource,
                volume_name=resource,
                world_key=secret,
                engine_version=LUANTI_VERSION,
                desired_state="running",
                op_state="creating",
                last_error=None,
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                preset=preset_id,
                language=language,
            )
            self._store.insert_world(row)

            # From create_world_container on, a volume or container may have been created.
            touched_docker = False
            try:
                self._provisioner.ensure_image()
                touched_docker = True
                with self._payload(row) as payload:
                    self._provisioner.create_world_container(world_id, port, payload)
                self._launch(row)
            except ProvisionerError as exc:
                self._discard_failed_create(world_id, exc, touched_docker=touched_docker)
                raise
            except Exception as exc:
                # Every other error takes the same cleanup path: otherwise the
                # row would stay on creating until the process restarts and occupy its port (WR-01).
                LOG.exception("Creating world %s failed unexpectedly", world_id)
                failure = ProvisionerError(CREATE_FAILED)
                self._discard_failed_create(world_id, failure, touched_docker=touched_docker)
                raise failure from exc

            self._store.update_world(world_id, op_state="ready")
            # Since 03-05 the world key is no longer displayed; access goes through
            # provisioned accounts. It stays as default_password in the conf.
            return self._current(world_id)

    def _set_world_language_sync(self, world_id: str, language: str) -> WorldView:
        with self._mutating():
            if not self._store.set_world_language(world_id, language):
                raise WorldNotFoundError(NOT_FOUND)
            return self._current(world_id)

    def _list_worlds_sync(self) -> list[WorldView]:
        # Without _LOCK (pitfall 6): reading status must never wait behind a create.
        with self._cache_lock:
            cached = self._list_cache
            generation = self._cache_generation
        if cached is not None and monotonic() - cached[0] < LIST_CACHE_SECONDS:
            return [_copy(view) for view in cached[1]]
        taken = monotonic()
        views, reachable = self._collect(self._store.list_worlds())
        # "Docker not reachable" is never cached: the next query checks again.
        if reachable:
            with self._cache_lock:
                if self._cache_generation == generation:
                    self._list_cache = (taken, [_copy(view) for view in views])
        return views

    def _start_world_sync(self, world_id: str) -> WorldView:
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            self._refuse_delete_only(row)
            self._store.update_world(world_id, desired_state="running")
            try:
                self._launch(row)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _stop_world_sync(self, world_id: str) -> WorldView:
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            self._store.update_world(world_id, desired_state="stopped")
            try:
                self._provisioner.stop(world_id)
            except WorldNotFoundError:
                # The DB row exists (checked above): a missing container
                # is already stopped, stopping is then a no-op.
                LOG.info("World %s: container missing, stopping is a no-op", world_id)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _restart_world_sync(self, world_id: str) -> WorldView:
        """Restart as stop plus _launch, never container.restart (RESEARCH pattern 3).

        So the port saga and re-creation from the volume apply as on start.
        """
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            self._refuse_delete_only(row)
            self._store.update_world(world_id, desired_state="running")
            try:
                try:
                    self._provisioner.stop(world_id)
                except WorldNotFoundError:
                    LOG.info("World %s: container missing, the restart recreates it", world_id)
                self._launch(row)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _boot_reconcile_sync(self) -> bool:
        # Not blocking (pitfall 6): if a parent action is running, the reconciliation comes back later.
        if not _LOCK.acquire(blocking=False):
            LOG.info("Boot reconciliation postponed: a parent action is running")
            return False
        try:
            managed = self._provisioner.list_managed()
            rows = self._store.list_worlds()
            known = {row.id for row in rows}
            orphans = [world_id for world_id in managed if world_id not in known]
            if orphans:
                # Never touch: without a row, world key and parent wish are missing.
                LOG.warning("orphaned world containers: %d (%s)", len(orphans), ", ".join(sorted(orphans)))
            for row in rows:
                self._reconcile_row(row, managed.get(row.id))
            return True
        finally:
            _LOCK.release()
            self._invalidate_cache()

    def _reconcile_row(self, row: WorldRow, container: ContainerInfo | None) -> None:
        """Reconcile one world; errors stay with this world, unless Docker is gone entirely."""
        action = ReconcileAction.NONE
        try:
            volume = needs_volume_check(row, container) and self._provisioner.volume_exists(row.id)
            action = decide_boot(row, container, volume)
            if action is ReconcileAction.CLEAR_BUSY:
                # Aborted backup or restore before the swap: the world data
                # is unchanged. Back to ready, then treat the fresh row like any other
                # (D-11: the world starts again if it should be running).
                LOG.info("Reconciliation of world %s: %s", row.id, action.value)
                self._apply(row, action)
                row = self._row(row.id)
                volume = needs_volume_check(row, container) and self._provisioner.volume_exists(row.id)
                action = decide_boot(row, container, volume)
            if action is ReconcileAction.NONE:
                return
            LOG.info("Reconciliation of world %s: %s", row.id, action.value)
            self._apply(row, action)
        except DockerUnavailableError:
            # Proxy gone: mark no world as broken, the whole reconciliation repeats.
            raise
        except ProvisionerError as exc:
            LOG.warning("Reconciliation of world %s (%s) failed: %s", row.id, action.value, exc)
            self._fail(row.id, exc)
        except Exception:
            # E.g. ValueError from get_preset (unknown game type): otherwise the
            # whole boot reconciliation would abort, repeat every 5 s, and no world behind it would start (WR-02).
            LOG.exception("Reconciliation of world %s (%s) failed unexpectedly", row.id, action.value)
            self._fail(row.id, ProvisionerError(RECONCILE_FAILED))

    def _apply(self, row: WorldRow, action: ReconcileAction) -> None:
        match action:
            case ReconcileAction.START | ReconcileAction.RECREATE:
                # RECREATE runs via the re-creation path in _launch (volume, row.preset).
                self._launch(row)
                self._store.update_world(row.id, op_state="ready", last_error=None)
            case ReconcileAction.MARK_OOM:
                self._store.update_world(row.id, last_error=RECONCILE_OOM)
            case ReconcileAction.MARK_DATA_MISSING:
                self._store.update_world(row.id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
            case ReconcileAction.MARK_INTERRUPTED:
                self._store.update_world(row.id, op_state="failed", last_error=RECONCILE_INTERRUPTED)
            case ReconcileAction.RETRY_DELETE:
                self._provisioner.remove_world(row.id, keep_volume=False)
                self._store.delete_world(row.id)
                self._store.delete_access_data(row.id)
                self._store.delete_time_data(row.id)
                self._store.delete_notify_data(row.id)
                self._store.delete_backup_job(row.id)
            case ReconcileAction.CLEAR_BUSY:
                # Afterwards _reconcile_row evaluates the fresh row by the normal rules.
                self._store.update_world(row.id, op_state="ready")
            case ReconcileAction.MARK_RESTORE_INTERRUPTED:
                self._store.update_world(row.id, op_state="failed", last_error=RESTORE_INTERRUPTED)
            case ReconcileAction.ADOPT_RUNNING:
                self._store.update_world(row.id, desired_state="running")
            case ReconcileAction.NONE:
                pass

    def _periodic_reconcile_sync(self) -> None:
        if not _LOCK.acquire(blocking=False):
            return
        changed = False
        try:
            managed = self._provisioner.list_managed()
            for row in self._store.list_worlds():
                if decide_periodic(row, managed.get(row.id)) is ReconcileAction.ADOPT_RUNNING:
                    LOG.info("Reconciliation of world %s: started by hand, desired state now running", row.id)
                    self._store.update_world(row.id, desired_state="running")
                    changed = True
        finally:
            _LOCK.release()
        if changed:
            self._invalidate_cache()

    def _delete_world_sync(self, world_id: str) -> None:
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            self._refuse_job_running(world_id)
            self._store.update_world(world_id, desired_state="deleted")
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            # Only after successful cleanup: no volume without an entry (T-01-21).
            self._store.delete_world(world_id)
            # No PRAGMA foreign_keys: explicitly delete invitations, access, world windows and
            # seen ledger states of the world, plus cursor,
            # outbox, run state, foreign attempts and bot throttle (schema 5). The
            # daily playtime (play_daily) stays until the normal period, so that the
            # review in the evening also counts a world deleted today.
            self._store.delete_access_data(world_id)
            self._store.delete_time_data(world_id)
            self._store.delete_notify_data(world_id)
            # Only the job state; the backup proofs (backups) stay (D-08, plan 02).
            self._store.delete_backup_job(world_id)
