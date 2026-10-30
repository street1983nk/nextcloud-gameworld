"""Flow of the backup as a background job (BACKUP-01, D-09, D-11, D-14).

The parent request only checks (player online, busy, one-job protection), sets the
world to ``backing_up`` and enters the job as ``running``; then the API
answers 202. The flow itself runs as a tracked task:

1. Space check (pitfall 10), with players a chat notice via ``@halt`` and
   waiting until ``ab`` plus grace period (D-09).
2. Stop, snapshot of the stopped container into an anonymous temp file under
   ``storage_dir/tmp``, in the ``finally`` immediately ``end_offline`` (world starts
   again, D-11, D-14).
3. Restore dry run (``verify_snapshot``): only what the restore path would accept
   is uploaded (T-05-27).
4. Upload into the files of the triggering manager, proof in ``backups``,
   job ``ok``.

Restore (BACKUP-02, D-04, D-05, D-06, D-13, D-15) destroys only when
backup and way back are proven:

A. Without stopping: download, size and SHA-256 against the own proof,
   complete check and filtering (``prepare_restore``). If anything fails,
   the world keeps running unchanged (``abort_offline``).
B. Halt, stop, book and preserve the ledger, checked vor-restore backup
   in Files. If anything fails, the old world starts again (``end_offline``).
C. ``mark_swap``, swap via a fresh volume with a second attempt,
   otherwise fall back to the local safety snapshot, otherwise
   ``RESTORE_INTERRUPTED`` (repeatable).

Every step holds the world lock only briefly (sections from worlds/service.py);
snapshot, dry run and upload run without the lock (pitfall 3). All
failed outcomes go through ``_finish_failed`` with a fixed German
text; only world ID and error type go into the log, never paths, accounts or names.
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Buffer, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

import anyio
import anyio.to_thread

from gameworld.access.roles import get_role_service
from gameworld.backup.archive import (
    KIND_BACKUP,
    KIND_VOR_RESTORE,
    MSG_NO_MAP,
    MSG_NO_SPACE,
    BackupError,
    RestoreRejected,
    SnapshotInfo,
    build_manifest,
    prepare_restore,
    sha256_of,
    verify_snapshot,
    write_snapshot,
)
from gameworld.backup.files import MSG_FILE_GONE, BackupFiles, FilesEntry, FilesError, get_backup_files
from gameworld.backup.naming import all_folder_paths, backup_file_name, with_suffix, world_folder_path
from gameworld.config import load_settings
from gameworld.i18n import translate
from gameworld.notify.links import app_link
from gameworld.notify.loop import link_origin
from gameworld.notify.service import Notifier, get_notifier
from gameworld.notify.texts import failed_subject, job_failed_message
from gameworld.provisioner.client import ProvisionerError, WorldNotFoundError
from gameworld.provisioner.spec import LUANTI_VERSION
from gameworld.provisioner.time_mod import parse_ledger
from gameworld.worlds.service import (
    NOT_FOUND,
    RECONCILE_DATA_MISSING,
    RESTORE_INTERRUPTED,
    OfflineTicket,
    WorldService,
)
from gameworld.worlds.store import BACKUP_JOB_RUNNING, BackupRow

LOG = logging.getLogger(__name__)

# Fixed texts of the job row (D-11); the UI shows them unchanged.
JOB_FAILED = "Die Sicherung ist fehlgeschlagen. Die Welt läuft weiter."
JOB_UNUSABLE = "Die Sicherung war unvollständig und wurde verworfen. Die Welt läuft weiter."
# D-09: confirmation before playing children are briefly disconnected.
PLAYERS_ONLINE_ONE = "In der Welt spielt gerade 1 Kind, es wird kurz getrennt."
PLAYERS_ONLINE_MANY = "In der Welt spielen gerade {count} Kinder, sie werden kurz getrennt."
# Jobs found at start in the state running (process died midway).
JOB_INTERRUPTED = "Die Sicherung wurde durch einen Neustart des Servers unterbrochen."
RESTORE_JOB_INTERRUPTED = "Das Wiederherstellen wurde durch einen Neustart des Servers unterbrochen."
KIND_RESTORE = "restore"

# Restore (BACKUP-02, D-04, D-05, D-13, D-15).
RESTORE_NOT_CONFIRMED = "Bitte das Wiederherstellen bestätigen."
BACKUP_NOT_FOUND = "Diese Sicherung gibt es nicht (mehr)."
RESTORE_TAMPERED = "Die Sicherung wurde verändert und wird nicht eingespielt."
RESTORE_FAILED = "Das Wiederherstellen ist fehlgeschlagen. Die Welt läuft weiter."
RESTORE_FALLBACK = "Das Wiederherstellen ist fehlgeschlagen. Die alte Welt wurde wiederhergestellt."
RESTORE_SWAP_FAILED = "Das Wiederherstellen ist fehlgeschlagen. Bitte erneut wiederherstellen."
# This often the swap with the chosen backup is tried before the fallback applies.
SWAP_ATTEMPTS = 2
# Space for download, restore tar and safety snapshot (pitfall 10, T-05-35).
RESTORE_SPACE_FACTOR = 3
# For these broken worlds there is no state that a vor-restore backup could save (D-15).
NO_SAFETY_ERRORS = frozenset({RECONCILE_DATA_MISSING, RESTORE_INTERRUPTED})

STATE_OK = "ok"
STATE_FAILED = "failed"
OP_BACKING_UP = "backing_up"
OP_RESTORING = "restoring"
# After ``ab`` keep waiting until the time mod has disconnected everyone in its 5 s tick:
# one full tick (the kick comes up to 5 s after ``ab``) plus 2 s for disconnecting and
# saving. With only 2 s the server often stopped before the kick on the dev stack, the child
# then read "Server shutting down." instead of the pause text (acceptance 05-09).
HALT_GRACE_SECONDS = 7
# Space for the spool: twice the last backup of this world (pitfall 10).
SPACE_FACTOR = 2
SPOOL_DIR_NAME = "tmp"
SHUTDOWN_SECONDS = 5.0

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class PlayersOnline(Exception):
    """Children are playing in the world and the confirmation is missing (HTTP 409, D-09)."""

    def __init__(self, count: int) -> None:
        text = PLAYERS_ONLINE_ONE if count == 1 else PLAYERS_ONLINE_MANY.format(count=count)
        super().__init__(text)
        self.count = count


class RestoreNotConfirmed(Exception):
    """Restore without explicit confirmation (HTTP 409, D-04)."""

    def __init__(self) -> None:
        super().__init__(RESTORE_NOT_CONFIRMED)


class BackupNotFound(Exception):
    """No own proof for this file and world (HTTP 404, D-13)."""

    def __init__(self) -> None:
        super().__init__(BACKUP_NOT_FOUND)


class RestoreTampered(BackupError):
    """Size or SHA-256 of the downloaded file differ from the own proof (T-05-29)."""

    def __init__(self) -> None:
        super().__init__(RESTORE_TAMPERED)


class _RestoreOutcome(Exception):
    """Fixed outcome of the swap (fallback or interrupted); the text goes to the job row."""


class _CappedWriter(io.RawIOBase):
    """Caps the restore download at the proven size (T-05-35).

    More bytes than ``proof.size`` mean a swapped file: ``RestoreTampered``
    at once, instead of buffering arbitrary amounts into the spool and checking
    only afterwards (same error class as the body cap from phase 04.2).
    """

    def __init__(self, sink: BinaryIO, limit: int) -> None:
        super().__init__()
        self._sink = sink
        self._left = limit

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer, /) -> int:
        data = memoryview(b).cast("B")
        if len(data) > self._left:
            raise RestoreTampered
        self._left -= len(data)
        return self._sink.write(data)


@dataclass(frozen=True)
class BackupItem:
    """A valid backup in the list; without a path (that lives only in the proof)."""

    file_id: int
    name: str
    size: int
    created_at: str
    kind: str


@dataclass(frozen=True)
class BackupList:
    entries: list[BackupItem]
    total_size: int
    # Files in the folder without a matching own proof (foreign, changed, incomplete).
    other_files: int


def disk_free(path: Path) -> int:
    """Free bytes on the disk of ``path`` (own function, so that tests can replace it)."""
    return shutil.disk_usage(path).free


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def user_text(exc: BaseException, world_id: str) -> str:
    """Fixed German text for an exception of the flow; unknown ones only with type into the log."""
    if isinstance(exc, RestoreRejected) or (isinstance(exc, BackupError) and str(exc) == MSG_NO_MAP):
        LOG.warning("Backup of world %s discarded: %s", world_id, type(exc).__name__)
        return JOB_UNUSABLE
    if isinstance(exc, (BackupError, FilesError, ProvisionerError)):
        LOG.warning("Backup of world %s failed: %s", world_id, type(exc).__name__)
        return str(exc)
    LOG.error("Backup of world %s failed unexpectedly: %s", world_id, type(exc).__name__)
    return JOB_FAILED


def restore_text(exc: BaseException, world_id: str) -> str:
    """Fixed German text for an exception of the restore; unknown ones only with type into the log."""
    if isinstance(exc, (_RestoreOutcome, BackupError, FilesError, ProvisionerError)):
        LOG.warning("Restore of world %s failed: %s", world_id, type(exc).__name__)
        return str(exc)
    LOG.error("Restore of world %s failed unexpectedly: %s", world_id, type(exc).__name__)
    return RESTORE_FAILED


class BackupService:
    """Starts and tracks backup jobs; at most one runs in the whole household."""

    def __init__(
        self,
        worlds: WorldService,
        spool_dir: Path,
        *,
        files: Callable[[], BackupFiles] = get_backup_files,
        notifier: Callable[[], Notifier] = get_notifier,
        clock: Clock = time.time,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.worlds = worlds
        self._spool_dir = spool_dir
        self._files = files
        self._notifier = notifier
        self._clock = clock
        self._sleep = sleep
        self._tasks: set[asyncio.Task[None]] = set()

    # Trigger (parent request)

    async def start_backup(self, world_id: str, uid: str, *, confirm_disconnect: bool) -> None:
        """Checks, sets the world to backing_up and starts the flow in the background.

        Raises PlayersOnline (without confirmation), WorldBusyError, DeleteOnlyError
        or WorldNotFoundError; then nothing is changed.
        """
        started_at = _iso(self._clock())
        ticket = await anyio.to_thread.run_sync(self._prepare, world_id, confirm_disconnect, started_at)
        work = self._run_backup(ticket, uid, started_at)
        try:
            self._spawn(world_id, work)
        except BaseException:
            work.close()
            await anyio.to_thread.run_sync(self._abort_start, ticket, KIND_BACKUP, JOB_FAILED, started_at)
            raise

    def _prepare(self, world_id: str, confirm_disconnect: bool, started_at: str) -> OfflineTicket:
        players = self.worlds.players_online(world_id)
        if players and not confirm_disconnect:
            raise PlayersOnline(players)
        ticket = self.worlds.begin_offline(world_id, OP_BACKING_UP)
        try:
            self.worlds.store.set_backup_job(world_id, KIND_BACKUP, BACKUP_JOB_RUNNING, None, None, started_at, None)
        except BaseException:
            self.worlds.abort_offline(ticket)
            raise
        return ticket

    def _abort_start(self, ticket: OfflineTicket, kind: str, message: str, started_at: str) -> None:
        """The task did not come into being: world back, job no longer running."""
        self.worlds.abort_offline(ticket)
        self.worlds.store.set_backup_job(
            ticket.world_id, kind, STATE_FAILED, message, None, started_at, _iso(self._clock())
        )

    # Flow (background)

    async def _run_backup(self, ticket: OfflineTicket, uid: str, started_at: str) -> None:
        try:
            await self._backup_steps(ticket, uid, started_at)
        except Exception as exc:
            await self._finish_failed(ticket.world_id, uid, KIND_BACKUP, user_text(exc, ticket.world_id), started_at)

    async def _backup_steps(self, ticket: OfflineTicket, uid: str, started_at: str) -> None:
        world_id = ticket.world_id
        try:
            spool = await anyio.to_thread.run_sync(self._open_spool)
        except BaseException:
            # Nothing stopped yet: world back to its old state.
            await self._shielded(self.worlds.abort_offline, ticket)
            raise
        try:
            info = await self._offline_snapshot(ticket, uid, spool)
            await anyio.to_thread.run_sync(self._verify, ticket, spool)
            now = self._clock()
            zone = await anyio.to_thread.run_sync(self.worlds.time.zone)
            # Folder and file name in the account language of the manager whose files receive it.
            language = await get_role_service().language(uid)
            when = datetime.fromtimestamp(now, UTC)
            base_name = backup_file_name(ticket.name, when, KIND_BACKUP, zone=zone, language=language)
            folder = world_folder_path(ticket.name, world_id, language)
            entry = await self._files().upload(uid, folder, base_name, cast(BinaryIO, spool), info.size, with_suffix)
            await anyio.to_thread.run_sync(self._finish_ok, ticket, uid, entry, info, started_at, _iso(now))
        finally:
            spool.close()

    def _open_spool(self) -> IO[bytes]:
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        try:
            return tempfile.TemporaryFile(dir=self._spool_dir)
        except OSError as exc:
            raise BackupError(MSG_NO_SPACE) from exc

    async def _offline_snapshot(self, ticket: OfflineTicket, uid: str, spool: IO[bytes]) -> SnapshotInfo:
        """Space check, chat notice, stop and snapshot; the world always starts again afterwards."""
        world_id = ticket.world_id
        stopping = False
        try:
            await anyio.to_thread.run_sync(self._check_space, world_id, uid)
            ab = await anyio.to_thread.run_sync(self.worlds.announce_halt, world_id, int(self._clock()))
            if ab is not None:
                await self._sleep(max(0.0, ab + HALT_GRACE_SECONDS - self._clock()))
            stopping = True
            await anyio.to_thread.run_sync(self.worlds.stop_for_snapshot, world_id)
            return await anyio.to_thread.run_sync(self._snapshot, ticket, spool, KIND_BACKUP)
        finally:
            if stopping:
                restart_error = await self._shielded(self.worlds.end_offline, world_id, ticket.was_running)
                if restart_error is not None:
                    LOG.warning("World %s: not restarted after the snapshot", world_id)
            else:
                await self._shielded(self.worlds.abort_offline, ticket)

    @staticmethod
    async def _shielded[*A, R](func: Callable[[*A], R], *args: *A) -> R:
        """Finish the reset even if the task is cancelled (shutdown)."""
        # List instead of variable: pyright considers a CancelScope possibly swallowing.
        results: list[R] = []
        with anyio.CancelScope(shield=True):
            results.append(await anyio.to_thread.run_sync(func, *args))
        return results[0]

    def _check_space(self, world_id: str, uid: str) -> None:
        previous = self.worlds.store.backups_for(uid, world_id)
        if not previous:
            return
        if disk_free(self._spool_dir) < SPACE_FACTOR * previous[0].size:
            raise BackupError(MSG_NO_SPACE)

    def _snapshot(self, ticket: OfflineTicket, spool: IO[bytes], kind: str) -> SnapshotInfo:
        manifest = build_manifest(ticket.world_id, ticket.preset, LUANTI_VERSION, _iso(self._clock()), kind)
        sink = cast(BinaryIO, spool)
        return self.worlds.provisioner.snapshot_to(
            ticket.world_id, lambda chunks: write_snapshot(chunks, sink, manifest)
        )

    @staticmethod
    def _verify(ticket: OfflineTicket, spool: IO[bytes]) -> None:
        verify_snapshot(cast(BinaryIO, spool), world_id=ticket.world_id, preset=ticket.preset)

    def _finish_ok(
        self, ticket: OfflineTicket, uid: str, entry: FilesEntry, info: SnapshotInfo, started_at: str, created_at: str
    ) -> None:
        self._add_proof(ticket, uid, entry, info, KIND_BACKUP, created_at)
        self.worlds.store.set_backup_job(
            ticket.world_id, KIND_BACKUP, STATE_OK, None, entry.name, started_at, _iso(self._clock())
        )
        LOG.info("World %s backed up: %d bytes", ticket.world_id, entry.size)

    def _add_proof(
        self, ticket: OfflineTicket, uid: str, entry: FilesEntry, info: SnapshotInfo, kind: str, created_at: str
    ) -> None:
        """Integrity proof of the uploaded file (D-12): only with it is it restorable."""
        self.worlds.store.add_backup(
            BackupRow(
                file_id=entry.file_id,
                owner_uid=uid,
                world_id=ticket.world_id,
                path=entry.path,
                name=entry.name,
                size=entry.size,
                sha256=info.sha256,
                preset=ticket.preset,
                kind=kind,
                created_at=created_at,
            )
        )

    async def _finish_failed(self, world_id: str, uid: str, kind: str, message: str, started_at: str) -> None:
        """Single exit for failed jobs: row failed, then notice to ``uid`` (D-16).

        Only the triggering manager gets the notification, success stays
        silent. An error while notifying does not change the job.
        """
        target = await self._shielded(self._mark_failed, world_id, kind, message, started_at)
        if target is None:
            return
        world_name, origin = target
        # Subject and reason in the account language of the recipient (D-25); the
        # reason is a fixed German job text, translate keeps unknown parts unchanged.
        language = await get_role_service().language(uid)
        text = job_failed_message(failed_subject(kind, language), world_id, world_name, translate(message, language))
        link = app_link(origin) if origin is not None else ""
        try:
            delivered = await self._notifier().notify(uid, text.subject, text.message, text.params, link)
        except Exception as exc:
            LOG.warning("Error notice for world %s not sent: %s", world_id, type(exc).__name__)
            return
        if not delivered:
            LOG.info("Error notice for world %s not delivered", world_id)

    def _mark_failed(self, world_id: str, kind: str, message: str, started_at: str) -> tuple[str, str | None] | None:
        """Row to failed; returns world name and link base, or None without a world."""
        store = self.worlds.store
        row = store.get_world(world_id)
        if row is None:
            return None
        store.set_backup_job(world_id, kind, STATE_FAILED, message, None, started_at, _iso(self._clock()))
        return row.name, link_origin(store)

    # Restore (BACKUP-02): parent request

    async def start_restore(
        self, world_id: str, uid: str, file_id: int, *, confirm: bool, confirm_disconnect: bool
    ) -> None:
        """Checks, sets the world to restoring and starts the flow in the background (D-04).

        Raises RestoreNotConfirmed, WorldNotFoundError, BackupNotFound (unknown,
        foreign or belonging to another world, before any Docker or
        Files call, D-13), PlayersOnline or WorldBusyError; then nothing is
        changed. A broken world (failed, also delete-only) is allowed (D-15).
        """
        if not confirm:
            raise RestoreNotConfirmed
        started_at = _iso(self._clock())
        ticket, proof = await anyio.to_thread.run_sync(
            self._prepare_restore, world_id, uid, file_id, confirm_disconnect, started_at
        )
        work = self._run_restore(ticket, proof, uid, started_at)
        try:
            self._spawn(world_id, work)
        except BaseException:
            work.close()
            await anyio.to_thread.run_sync(self._abort_start, ticket, KIND_RESTORE, RESTORE_FAILED, started_at)
            raise

    def _prepare_restore(
        self, world_id: str, uid: str, file_id: int, confirm_disconnect: bool, started_at: str
    ) -> tuple[OfflineTicket, BackupRow]:
        store = self.worlds.store
        if store.get_world(world_id) is None:
            raise WorldNotFoundError(NOT_FOUND)
        # Only the own proof for exactly this world makes a file trustworthy (T-05-28).
        proof = store.backup_by_file(uid, file_id)
        if proof is None or proof.world_id != world_id:
            raise BackupNotFound
        players = self.worlds.players_online(world_id)
        if players and not confirm_disconnect:
            raise PlayersOnline(players)
        ticket = self.worlds.begin_offline(world_id, OP_RESTORING, allow_failed=True)
        try:
            store.set_backup_job(world_id, KIND_RESTORE, BACKUP_JOB_RUNNING, None, proof.name, started_at, None)
        except BaseException:
            self.worlds.abort_offline(ticket)
            raise
        return ticket, proof

    # Restore: flow (background)

    async def _run_restore(self, ticket: OfflineTicket, proof: BackupRow, uid: str, started_at: str) -> None:
        spools: list[IO[bytes]] = []
        try:
            await self._restore_steps(ticket, proof, uid, started_at, spools)
        except Exception as exc:
            text = restore_text(exc, ticket.world_id)
            await self._finish_failed(ticket.world_id, uid, KIND_RESTORE, text, started_at)
        finally:
            for spool in spools:
                spool.close()

    async def _restore_steps(
        self, ticket: OfflineTicket, proof: BackupRow, uid: str, started_at: str, spools: list[IO[bytes]]
    ) -> None:
        """A: fetch and check (world runs), B: stop and vor-restore, C: swap (RESEARCH pattern 4/5)."""
        try:
            restore = await self._fetch_and_check(ticket, proof, uid, spools)
        except BaseException:
            # Nothing stopped yet: world back to its old state, a broken one stays broken.
            await self._shielded(self.worlds.abort_offline, ticket)
            raise
        ledger, safety = await self._offline_safety(ticket, uid, spools)
        await self._swap(ticket, restore, ledger, safety, spools)
        await anyio.to_thread.run_sync(self._finish_restore_ok, ticket.world_id, proof, started_at)

    async def _new_spool(self, spools: list[IO[bytes]]) -> IO[bytes]:
        spool = await anyio.to_thread.run_sync(self._open_spool)
        spools.append(spool)
        return spool

    async def _fetch_and_check(
        self, ticket: OfflineTicket, proof: BackupRow, uid: str, spools: list[IO[bytes]]
    ) -> IO[bytes]:
        """Phase A: space, capped download, size and SHA-256 against the proof, build the restore tar."""
        await anyio.to_thread.run_sync(self._check_restore_space, proof)
        path = await self._current_path(ticket, proof, uid)
        download = await self._new_spool(spools)
        capped = _CappedWriter(cast(BinaryIO, download), proof.size)
        await self._files().download_to(uid, path, cast(BinaryIO, capped))
        await anyio.to_thread.run_sync(self._check_integrity, download, proof)
        restore = await self._new_spool(spools)
        await anyio.to_thread.run_sync(self._restore_tar, ticket, download, restore)
        return restore

    async def _current_path(self, ticket: OfflineTicket, proof: BackupRow, uid: str) -> str:
        """Current path to the proven file_id; the manager may rename the file in Files.

        Like the list (list_backups), the file_id from the folder listing counts,
        not the path stored at backup time: a renamed backup stays
        restorable, a foreign file under the old name is never
        loaded. If the file_id is missing, the backup is gone (MSG_FILE_GONE).
        Size and SHA-256 remain the authority (_check_integrity).
        """
        # Every language folder: after a language change the backup lies in the previous one.
        for folder in all_folder_paths(ticket.name, ticket.world_id):
            for entry in await self._files().listdir(uid, folder):
                if entry.file_id == proof.file_id:
                    return entry.path
        raise FilesError(MSG_FILE_GONE)

    def _check_restore_space(self, proof: BackupRow) -> None:
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        if disk_free(self._spool_dir) < RESTORE_SPACE_FACTOR * proof.size:
            raise BackupError(MSG_NO_SPACE)

    @staticmethod
    def _check_integrity(download: IO[bytes], proof: BackupRow) -> None:
        """Files is writable for managers: exactly the proven file and only that is put in."""
        download.seek(0, io.SEEK_END)
        size = download.tell()
        if size != proof.size or sha256_of(cast(BinaryIO, download)) != proof.sha256:
            raise RestoreTampered

    @staticmethod
    def _restore_tar(ticket: OfflineTicket, source: IO[bytes], sink: IO[bytes]) -> None:
        """Full check and filtering (plan 01); the manifest must match world and game kind of the row."""
        source.seek(0)
        prepare_restore(
            cast(BinaryIO, source), world_id=ticket.world_id, preset=ticket.preset, sink=cast(BinaryIO, sink)
        )

    async def _offline_safety(
        self, ticket: OfflineTicket, uid: str, spools: list[IO[bytes]]
    ) -> tuple[bytes | None, IO[bytes] | None]:
        """Phase B: halt, stop, ledger, vor-restore backup; if anything fails, the old world starts again."""
        world_id = ticket.world_id
        stopping = False
        try:
            needs_safety = await anyio.to_thread.run_sync(self._needs_safety, ticket)
            ab = await anyio.to_thread.run_sync(self.worlds.announce_halt, world_id, int(self._clock()))
            if ab is not None:
                await self._sleep(max(0.0, ab + HALT_GRACE_SECONDS - self._clock()))
            stopping = True
            await anyio.to_thread.run_sync(self.worlds.stop_for_snapshot, world_id)
            ledger = await anyio.to_thread.run_sync(self._take_ledger, world_id)
            safety = await self._safety_backup(ticket, uid, spools) if needs_safety else None
        except BaseException:
            if stopping:
                await self._shielded(self.worlds.end_offline, world_id, ticket.was_running)
            else:
                await self._shielded(self.worlds.abort_offline, ticket)
            raise
        return ledger, safety

    def _needs_safety(self, ticket: OfflineTicket) -> bool:
        """Is there a state that a vor-restore backup can save (D-05, D-15)?"""
        if ticket.previous_op_state == "failed" and ticket.previous_error in NO_SAFETY_ERRORS:
            return False
        return ticket.world_id in self.worlds.provisioner.list_managed()

    def _take_ledger(self, world_id: str) -> bytes | None:
        """Book the ledger and preserve it unchanged (D-06); if it is missing or broken, None."""
        self.worlds.book_ledger(world_id)
        try:
            status_file = self.worlds.provisioner.read_time_ledger(world_id)
        except WorldNotFoundError:
            return None
        if status_file is None or parse_ledger(status_file.content) is None:
            return None
        return status_file.content

    async def _safety_backup(self, ticket: OfflineTicket, uid: str, spools: list[IO[bytes]]) -> IO[bytes] | None:
        """Checked vor-restore backup in Files with own proof; the spool stays for the fallback.

        If the world has no save state yet (MSG_NO_MAP), there is nothing to preserve:
        None, the swap continues. Any other error aborts before the destruction.
        """
        spool = await self._new_spool(spools)
        try:
            info = await anyio.to_thread.run_sync(self._snapshot, ticket, spool, KIND_VOR_RESTORE)
        except BackupError as exc:
            if str(exc) != MSG_NO_MAP:
                raise
            LOG.info("World %s without save state, no backup before the restore", ticket.world_id)
            return None
        await anyio.to_thread.run_sync(self._verify, ticket, spool)
        now = self._clock()
        zone = await anyio.to_thread.run_sync(self.worlds.time.zone)
        language = await get_role_service().language(uid)
        when = datetime.fromtimestamp(now, UTC)
        base_name = backup_file_name(ticket.name, when, KIND_VOR_RESTORE, zone=zone, language=language)
        folder = world_folder_path(ticket.name, ticket.world_id, language)
        entry = await self._files().upload(uid, folder, base_name, cast(BinaryIO, spool), info.size, with_suffix)
        await anyio.to_thread.run_sync(self._add_proof, ticket, uid, entry, info, KIND_VOR_RESTORE, _iso(now))
        return spool

    async def _swap(
        self,
        ticket: OfflineTicket,
        restore: IO[bytes],
        ledger: bytes | None,
        safety: IO[bytes] | None,
        spools: list[IO[bytes]],
    ) -> None:
        """Phase C: swap with a second attempt, otherwise fall back to the safety snapshot.

        From mark_swap on the old world is no longer safely there: every outcome
        ends in ready (success or fallback) or failed with RESTORE_INTERRUPTED.
        """
        world_id = ticket.world_id
        try:
            await anyio.to_thread.run_sync(self.worlds.mark_swap, world_id)
        except BaseException:
            await self._shielded(self.worlds.end_offline, world_id, ticket.was_running)
            raise
        settled = False
        try:
            if await self._try_swap(world_id, restore, ledger, SWAP_ATTEMPTS):
                settled = True
                await self._finish_swap(ticket)
                return
            if safety is not None and await self._fallback(ticket, safety, ledger, spools):
                settled = True
                await self._finish_swap(ticket)
                raise _RestoreOutcome(RESTORE_FALLBACK)
            settled = True
            await self._shielded(self.worlds.mark_restore_interrupted, world_id)
            raise _RestoreOutcome(RESTORE_SWAP_FAILED)
        except BaseException:
            if not settled:
                await self._shielded(self.worlds.mark_restore_interrupted, world_id)
            raise

    async def _try_swap(self, world_id: str, tar: IO[bytes], ledger: bytes | None, attempts: int) -> bool:
        for attempt in range(1, attempts + 1):
            try:
                await anyio.to_thread.run_sync(self.worlds.restore_swap, world_id, cast(BinaryIO, tar), ledger)
            except Exception as exc:
                LOG.warning("World %s: swap attempt %d failed (%s)", world_id, attempt, type(exc).__name__)
                continue
            return True
        return False

    async def _fallback(
        self, ticket: OfflineTicket, safety: IO[bytes], ledger: bytes | None, spools: list[IO[bytes]]
    ) -> bool:
        """Put the local safety snapshot in the same way (pattern 5 "error in the swap")."""
        fallback = await self._new_spool(spools)
        try:
            await anyio.to_thread.run_sync(self._restore_tar, ticket, safety, fallback)
        except Exception as exc:
            LOG.warning("World %s: fallback not prepared (%s)", ticket.world_id, type(exc).__name__)
            return False
        return await self._try_swap(ticket.world_id, fallback, ledger, 1)

    async def _finish_swap(self, ticket: OfflineTicket) -> None:
        error = await self._shielded(self.worlds.finish_swap, ticket.world_id, ticket.was_running)
        if error is not None:
            # The world data is in place; the world itself shows the start error.
            LOG.warning("World %s: not started after the restore", ticket.world_id)

    def _finish_restore_ok(self, world_id: str, proof: BackupRow, started_at: str) -> None:
        self.worlds.store.set_backup_job(
            world_id, KIND_RESTORE, STATE_OK, None, proof.name, started_at, _iso(self._clock())
        )
        LOG.info("World %s restored", world_id)

    # Restart and list

    def recover_jobs(self) -> int:
        """After the start: jobs in the state running were interrupted (D-11); count.

        Synchronous in the lifespan, before a request can start a new job.
        """
        store = self.worlds.store
        jobs = store.running_backup_jobs()
        finished = _iso(self._clock())
        for job in jobs:
            text = RESTORE_JOB_INTERRUPTED if job.kind == KIND_RESTORE else JOB_INTERRUPTED
            store.set_backup_job(job.world_id, job.kind, STATE_FAILED, text, job.file_name, job.started_at, finished)
            LOG.warning("Job for world %s interrupted by restart", job.world_id)
        return len(jobs)

    async def list_backups(self, world_id: str, uid: str) -> BackupList:
        """Valid backups of this world in the files of ``uid`` (D-07, D-08, D-12, D-13).

        Only files whose (file_id, size) also have an own proof; everything
        else in the folder counts as ``other_files``. Order like the proof
        (newest first). Raises WorldNotFoundError or FilesError.
        """
        row = await anyio.to_thread.run_sync(self.worlds.store.get_world, world_id)
        if row is None:
            raise WorldNotFoundError(NOT_FOUND)
        proofs = await anyio.to_thread.run_sync(self.worlds.store.backups_for, uid, world_id)
        # Every language folder (account language may have changed since older backups).
        files = [
            entry
            for folder in all_folder_paths(row.name, world_id)
            for entry in await self._files().listdir(uid, folder)
        ]
        present = {(entry.file_id, entry.size): entry for entry in files}
        entries: list[BackupItem] = []
        for proof in proofs:
            entry = present.get((proof.file_id, proof.size))
            if entry is None:
                continue
            entries.append(
                BackupItem(
                    file_id=proof.file_id,
                    name=entry.name,
                    size=proof.size,
                    created_at=proof.created_at,
                    kind=proof.kind,
                )
            )
        return BackupList(
            entries=entries,
            total_size=sum(entry.size for entry in entries),
            other_files=len(files) - len(entries),
        )

    # Tracked tasks (pattern talk/service.py)

    def _spawn(self, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(self._tracked(world_id, work))
        self._tasks.add(task)

    async def _tracked(self, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        try:
            await work
        except Exception as exc:
            LOG.warning("Backup job for world %s ended with error: %s", world_id, type(exc).__name__)
        finally:
            current = asyncio.current_task()
            if current is not None:
                self._tasks.discard(current)

    async def drain(self) -> None:
        """Waits until all jobs are finished (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self, grace_seconds: float = SHUTDOWN_SECONDS) -> int:
        """Lifespan end: wait briefly, then cancel; count cancelled.

        A cancelled job still restarts the world in the ``finally`` (shielded);
        its row stays running and becomes failed at the next start.
        """
        pending = set(self._tasks)
        if not pending:
            return 0
        _done, still = await asyncio.wait(pending, timeout=grace_seconds)
        for task in still:
            task.cancel()
        if still:
            await asyncio.gather(*still, return_exceptions=True)
        return len(still)


_backup_service: BackupService | None = None


def get_backup_service(worlds: WorldService) -> BackupService:
    """Module-wide singleton to the world service; tests reset it per test."""
    global _backup_service
    if _backup_service is None or _backup_service.worlds is not worlds:
        _backup_service = BackupService(worlds, load_settings().storage_dir / SPOOL_DIR_NAME)
    return _backup_service


async def shutdown_backups(grace_seconds: float = SHUTDOWN_SECONDS) -> int:
    """Lifespan end: wait for or cancel open jobs; without a service nothing."""
    if _backup_service is None:
        return 0
    return await _backup_service.shutdown(grace_seconds)
