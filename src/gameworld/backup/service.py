"""Ablauf der Sicherung als Hintergrund-Auftrag (BACKUP-01, D-09, D-11, D-14).

Der Eltern-Request prüft nur (Spieler online, Busy, Ein-Job-Schutz), setzt die
Welt auf ``backing_up`` und trägt den Auftrag als ``running`` ein; dann
antwortet die API 202. Der Ablauf selbst läuft als verfolgter Task:

1. Platzprüfung (Pitfall 10), bei Spielern Chat-Hinweis über ``@halt`` und
   Warten bis ``ab`` plus Gnadenfrist (D-09).
2. Stopp, Snapshot am gestoppten Container in eine anonyme Temp-Datei unter
   ``storage_dir/tmp``, im ``finally`` sofort ``end_offline`` (Welt startet
   wieder, D-11, D-14).
3. Restore-Probelauf (``verify_snapshot``): Nur was der Restore-Pfad annähme,
   wird hochgeladen (T-05-27).
4. Upload in die Files des auslösenden Verwalters, Nachweis in ``backups``,
   Auftrag ``ok``.

Die Welt-Sperre hält jeder Schritt nur kurz (Abschnitte aus worlds/service.py);
Snapshot, Probelauf und Upload laufen ohne Sperre (Pitfall 3). Alle
fehlgeschlagenen Ausgänge laufen über ``_finish_failed`` mit festem deutschem
Text; ins Log kommen nur Welt-ID und Fehlertyp, nie Pfade, Konten oder Namen.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

import anyio
import anyio.to_thread

from gameworld.backup.archive import (
    KIND_BACKUP,
    MSG_NO_MAP,
    MSG_NO_SPACE,
    BackupError,
    RestoreRejected,
    SnapshotInfo,
    build_manifest,
    verify_snapshot,
    write_snapshot,
)
from gameworld.backup.files import BackupFiles, FilesEntry, FilesError, get_backup_files
from gameworld.backup.naming import backup_file_name, folder_name, folder_path, with_suffix
from gameworld.config import load_settings
from gameworld.provisioner.client import ProvisionerError
from gameworld.provisioner.spec import LUANTI_VERSION
from gameworld.worlds.service import OfflineTicket, WorldService
from gameworld.worlds.store import BACKUP_JOB_RUNNING, BackupRow

LOG = logging.getLogger(__name__)

# Festtexte der Auftragszeile (D-11); die Oberfläche zeigt sie unverändert.
JOB_FAILED = "Die Sicherung ist fehlgeschlagen. Die Welt läuft weiter."
JOB_UNUSABLE = "Die Sicherung war unvollständig und wurde verworfen. Die Welt läuft weiter."
# D-09: Bestätigung, bevor spielende Kinder kurz getrennt werden.
PLAYERS_ONLINE_ONE = "In der Welt spielt gerade 1 Kind, es wird kurz getrennt."
PLAYERS_ONLINE_MANY = "In der Welt spielen gerade {count} Kinder, sie werden kurz getrennt."

STATE_OK = "ok"
STATE_FAILED = "failed"
OP_BACKING_UP = "backing_up"
# Nach ``ab`` noch so lange warten, bis der Zeit-Mod im 5-s-Takt alle getrennt hat.
HALT_GRACE_SECONDS = 2
# Platz für den Spool: das Doppelte der letzten Sicherung dieser Welt (Pitfall 10).
SPACE_FACTOR = 2
SPOOL_DIR_NAME = "tmp"
SHUTDOWN_SECONDS = 5.0

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class PlayersOnline(Exception):
    """In der Welt spielen Kinder, und die Bestätigung fehlt (HTTP 409, D-09)."""

    def __init__(self, count: int) -> None:
        text = PLAYERS_ONLINE_ONE if count == 1 else PLAYERS_ONLINE_MANY.format(count=count)
        super().__init__(text)
        self.count = count


def disk_free(path: Path) -> int:
    """Freie Bytes auf dem Datenträger von ``path`` (eigene Funktion, damit Tests sie ersetzen)."""
    return shutil.disk_usage(path).free


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat()


def user_text(exc: BaseException, world_id: str) -> str:
    """Fester deutscher Text zu einer Ausnahme des Ablaufs; Unbekanntes nur mit Typ ins Log."""
    if isinstance(exc, RestoreRejected) or (isinstance(exc, BackupError) and str(exc) == MSG_NO_MAP):
        LOG.warning("Sicherung von Welt %s verworfen: %s", world_id, type(exc).__name__)
        return JOB_UNUSABLE
    if isinstance(exc, (BackupError, FilesError, ProvisionerError)):
        LOG.warning("Sicherung von Welt %s gescheitert: %s", world_id, type(exc).__name__)
        return str(exc)
    LOG.error("Sicherung von Welt %s scheiterte unerwartet: %s", world_id, type(exc).__name__)
    return JOB_FAILED


class BackupService:
    """Startet und verfolgt Sicherungsaufträge; höchstens einer läuft im ganzen Haushalt."""

    def __init__(
        self,
        worlds: WorldService,
        spool_dir: Path,
        *,
        files: Callable[[], BackupFiles] = get_backup_files,
        clock: Clock = time.time,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.worlds = worlds
        self._spool_dir = spool_dir
        self._files = files
        self._clock = clock
        self._sleep = sleep
        self._tasks: set[asyncio.Task[None]] = set()

    # Auslösen (Eltern-Request)

    async def start_backup(self, world_id: str, uid: str, *, confirm_disconnect: bool) -> None:
        """Prüft, setzt die Welt auf backing_up und startet den Ablauf im Hintergrund.

        Wirft PlayersOnline (ohne Bestätigung), WorldBusyError, DeleteOnlyError
        oder WorldNotFoundError; dann ist nichts verändert.
        """
        started_at = _iso(self._clock())
        ticket = await anyio.to_thread.run_sync(self._prepare, world_id, confirm_disconnect, started_at)
        work = self._run_backup(ticket, uid, started_at)
        try:
            self._spawn(world_id, work)
        except BaseException:
            work.close()
            await anyio.to_thread.run_sync(self._abort_start, ticket, started_at)
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

    def _abort_start(self, ticket: OfflineTicket, started_at: str) -> None:
        """Der Task kam nicht zustande: Welt zurück, Auftrag nicht mehr running."""
        self.worlds.abort_offline(ticket)
        self.worlds.store.set_backup_job(
            ticket.world_id, KIND_BACKUP, STATE_FAILED, JOB_FAILED, None, started_at, _iso(self._clock())
        )

    # Ablauf (Hintergrund)

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
            # Noch nichts gestoppt: Welt in ihren alten Zustand zurück.
            await self._shielded(self.worlds.abort_offline, ticket)
            raise
        try:
            info = await self._offline_snapshot(ticket, uid, spool)
            await anyio.to_thread.run_sync(self._verify, ticket, spool)
            now = self._clock()
            zone = await anyio.to_thread.run_sync(self.worlds.time.zone)
            base_name = backup_file_name(ticket.name, datetime.fromtimestamp(now, UTC), KIND_BACKUP, zone=zone)
            folder = folder_path(folder_name(ticket.name, world_id))
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
        """Platzprüfung, Chat-Hinweis, Stopp und Snapshot; die Welt startet danach immer wieder."""
        world_id = ticket.world_id
        stopping = False
        try:
            await anyio.to_thread.run_sync(self._check_space, world_id, uid)
            ab = await anyio.to_thread.run_sync(self.worlds.announce_halt, world_id, int(self._clock()))
            if ab is not None:
                await self._sleep(max(0.0, ab + HALT_GRACE_SECONDS - self._clock()))
            stopping = True
            await anyio.to_thread.run_sync(self.worlds.stop_for_snapshot, world_id)
            return await anyio.to_thread.run_sync(self._snapshot, ticket, spool)
        finally:
            if stopping:
                restart_error = await self._shielded(self.worlds.end_offline, world_id, ticket.was_running)
                if restart_error is not None:
                    LOG.warning("Welt %s: nach dem Snapshot nicht wieder gestartet", world_id)
            else:
                await self._shielded(self.worlds.abort_offline, ticket)

    @staticmethod
    async def _shielded[*A, R](func: Callable[[*A], R], *args: *A) -> R:
        """Zurücksetzen auch bei Abbruch des Tasks (Herunterfahren) zu Ende führen."""
        # Liste statt Variable: pyright hält einen CancelScope für möglicherweise schluckend.
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

    def _snapshot(self, ticket: OfflineTicket, spool: IO[bytes]) -> SnapshotInfo:
        manifest = build_manifest(ticket.world_id, ticket.preset, LUANTI_VERSION, _iso(self._clock()), KIND_BACKUP)
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
        store = self.worlds.store
        store.add_backup(
            BackupRow(
                file_id=entry.file_id,
                owner_uid=uid,
                world_id=ticket.world_id,
                path=entry.path,
                name=entry.name,
                size=entry.size,
                sha256=info.sha256,
                preset=ticket.preset,
                kind=KIND_BACKUP,
                created_at=created_at,
            )
        )
        store.set_backup_job(ticket.world_id, KIND_BACKUP, STATE_OK, None, entry.name, started_at, _iso(self._clock()))
        LOG.info("Welt %s gesichert: %d Bytes", ticket.world_id, entry.size)

    async def _finish_failed(self, world_id: str, uid: str, kind: str, message: str, started_at: str) -> None:
        """Einziger Ausgang für fehlgeschlagene Aufträge: Zeile failed mit festem Text."""
        del uid  # Task 2: Benachrichtigung an den auslösenden Verwalter (D-16)
        await self._shielded(self._mark_failed, world_id, kind, message, started_at)

    def _mark_failed(self, world_id: str, kind: str, message: str, started_at: str) -> None:
        if self.worlds.store.get_world(world_id) is None:
            return
        self.worlds.store.set_backup_job(world_id, kind, STATE_FAILED, message, None, started_at, _iso(self._clock()))

    # Verfolgte Tasks (Muster talk/service.py)

    def _spawn(self, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        task = asyncio.get_running_loop().create_task(self._tracked(world_id, work))
        self._tasks.add(task)

    async def _tracked(self, world_id: str, work: Coroutine[Any, Any, None]) -> None:
        try:
            await work
        except Exception as exc:
            LOG.warning("Sicherungsauftrag für Welt %s endete mit Fehler: %s", world_id, type(exc).__name__)
        finally:
            current = asyncio.current_task()
            if current is not None:
                self._tasks.discard(current)

    async def drain(self) -> None:
        """Wartet, bis alle Aufträge fertig sind (Tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self, grace_seconds: float = SHUTDOWN_SECONDS) -> int:
        """Lifespan-Ende: kurz warten, dann abbrechen; Anzahl abgebrochen.

        Ein abgebrochener Auftrag startet die Welt im ``finally`` noch (abgeschirmt)
        neu; seine Zeile bleibt running und wird beim nächsten Start failed.
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
    """Modulweites Singleton zum Welt-Dienst; Tests setzen es je Test zurück."""
    global _backup_service
    if _backup_service is None or _backup_service.worlds is not worlds:
        _backup_service = BackupService(worlds, load_settings().storage_dir / SPOOL_DIR_NAME)
    return _backup_service


async def shutdown_backups(grace_seconds: float = SHUTDOWN_SECONDS) -> int:
    """Lifespan-Ende: offene Aufträge abwarten oder abbrechen; ohne Dienst nichts."""
    if _backup_service is None:
        return 0
    return await _backup_service.shutdown(grace_seconds)
