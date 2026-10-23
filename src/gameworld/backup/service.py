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

Wiederherstellen (BACKUP-02, D-04, D-05, D-06, D-13, D-15) zerstört erst, wenn
Sicherung und Rückweg bewiesen sind:

A. Ohne Stopp: Download, Größe und SHA-256 gegen den eigenen Nachweis,
   vollständige Prüfung und Filterung (``prepare_restore``). Scheitert etwas,
   läuft die Welt unverändert weiter (``abort_offline``).
B. Halt, Stopp, Zählbuch verbuchen und bewahren, geprüfte vor-restore-Sicherung
   in Files. Scheitert etwas, startet die alte Welt wieder (``end_offline``).
C. ``mark_swap``, Tausch über ein frisches Volume mit einem zweiten Versuch,
   sonst Rückfall auf den lokalen Sicherheits-Snapshot, sonst
   ``RESTORE_INTERRUPTED`` (wiederholbar).

Die Welt-Sperre hält jeder Schritt nur kurz (Abschnitte aus worlds/service.py);
Snapshot, Probelauf und Upload laufen ohne Sperre (Pitfall 3). Alle
fehlgeschlagenen Ausgänge laufen über ``_finish_failed`` mit festem deutschem
Text; ins Log kommen nur Welt-ID und Fehlertyp, nie Pfade, Konten oder Namen.
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, BinaryIO, cast

import anyio
import anyio.to_thread

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
from gameworld.backup.files import BackupFiles, FilesEntry, FilesError, get_backup_files
from gameworld.backup.naming import backup_file_name, folder_name, folder_path, with_suffix
from gameworld.config import load_settings
from gameworld.notify.links import app_link
from gameworld.notify.loop import link_origin
from gameworld.notify.service import Notifier, get_notifier
from gameworld.notify.texts import BACKUP_FAILED_SUBJECT, RESTORE_FAILED_SUBJECT, job_failed_message
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

# Festtexte der Auftragszeile (D-11); die Oberfläche zeigt sie unverändert.
JOB_FAILED = "Die Sicherung ist fehlgeschlagen. Die Welt läuft weiter."
JOB_UNUSABLE = "Die Sicherung war unvollständig und wurde verworfen. Die Welt läuft weiter."
# D-09: Bestätigung, bevor spielende Kinder kurz getrennt werden.
PLAYERS_ONLINE_ONE = "In der Welt spielt gerade 1 Kind, es wird kurz getrennt."
PLAYERS_ONLINE_MANY = "In der Welt spielen gerade {count} Kinder, sie werden kurz getrennt."
# Beim Start gefundene Aufträge im Zustand running (Prozess starb mittendrin).
JOB_INTERRUPTED = "Die Sicherung wurde durch einen Neustart des Servers unterbrochen."
RESTORE_JOB_INTERRUPTED = "Das Wiederherstellen wurde durch einen Neustart des Servers unterbrochen."
KIND_RESTORE = "restore"
FAILED_SUBJECTS = {KIND_BACKUP: BACKUP_FAILED_SUBJECT, KIND_RESTORE: RESTORE_FAILED_SUBJECT}

# Wiederherstellen (BACKUP-02, D-04, D-05, D-13, D-15).
RESTORE_NOT_CONFIRMED = "Bitte das Wiederherstellen bestätigen."
BACKUP_NOT_FOUND = "Diese Sicherung gibt es nicht (mehr)."
RESTORE_TAMPERED = "Die Sicherung wurde verändert und wird nicht eingespielt."
RESTORE_FAILED = "Das Wiederherstellen ist fehlgeschlagen. Die Welt läuft weiter."
RESTORE_FALLBACK = "Das Wiederherstellen ist fehlgeschlagen. Die alte Welt wurde wiederhergestellt."
RESTORE_SWAP_FAILED = "Das Wiederherstellen ist fehlgeschlagen. Bitte erneut wiederherstellen."
# So oft wird der Tausch mit der gewählten Sicherung versucht, bevor der Rückfall greift.
SWAP_ATTEMPTS = 2
# Platz für Download, Restore-Tar und Sicherheits-Snapshot (Pitfall 10, T-05-35).
RESTORE_SPACE_FACTOR = 3
# Für diese kaputten Welten gibt es keinen Stand, den eine vor-restore-Sicherung retten könnte (D-15).
NO_SAFETY_ERRORS = frozenset({RECONCILE_DATA_MISSING, RESTORE_INTERRUPTED})

STATE_OK = "ok"
STATE_FAILED = "failed"
OP_BACKING_UP = "backing_up"
OP_RESTORING = "restoring"
# Nach ``ab`` noch so lange warten, bis der Zeit-Mod im 5-s-Takt alle getrennt hat:
# ein voller Takt (der Kick kommt bis zu 5 s nach ``ab``) plus 2 s für Trennen und
# Speichern. Mit nur 2 s stoppte der Server am Dev-Stack oft vor dem Kick, das Kind
# las dann "Server shutting down." statt des Pausentexts (Abnahme 05-09).
HALT_GRACE_SECONDS = 7
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


class RestoreNotConfirmed(Exception):
    """Wiederherstellen ohne ausdrückliche Bestätigung (HTTP 409, D-04)."""

    def __init__(self) -> None:
        super().__init__(RESTORE_NOT_CONFIRMED)


class BackupNotFound(Exception):
    """Kein eigener Nachweis zu dieser Datei und Welt (HTTP 404, D-13)."""

    def __init__(self) -> None:
        super().__init__(BACKUP_NOT_FOUND)


class RestoreTampered(BackupError):
    """Größe oder SHA-256 der heruntergeladenen Datei weichen vom eigenen Nachweis ab (T-05-29)."""

    def __init__(self) -> None:
        super().__init__(RESTORE_TAMPERED)


class _RestoreOutcome(Exception):
    """Fester Ausgang des Tauschs (Rückfall oder unterbrochen); der Text geht an die Auftragszeile."""


@dataclass(frozen=True)
class BackupItem:
    """Eine gültige Sicherung in der Liste; ohne Pfad (der liegt nur im Nachweis)."""

    file_id: int
    name: str
    size: int
    created_at: str
    kind: str


@dataclass(frozen=True)
class BackupList:
    entries: list[BackupItem]
    total_size: int
    # Dateien im Ordner ohne passenden eigenen Nachweis (fremd, verändert, unvollständig).
    other_files: int


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


def restore_text(exc: BaseException, world_id: str) -> str:
    """Fester deutscher Text zu einer Ausnahme des Wiederherstellens; Unbekanntes nur mit Typ ins Log."""
    if isinstance(exc, (_RestoreOutcome, BackupError, FilesError, ProvisionerError)):
        LOG.warning("Wiederherstellen von Welt %s gescheitert: %s", world_id, type(exc).__name__)
        return str(exc)
    LOG.error("Wiederherstellen von Welt %s scheiterte unerwartet: %s", world_id, type(exc).__name__)
    return RESTORE_FAILED


class BackupService:
    """Startet und verfolgt Sicherungsaufträge; höchstens einer läuft im ganzen Haushalt."""

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
        """Der Task kam nicht zustande: Welt zurück, Auftrag nicht mehr running."""
        self.worlds.abort_offline(ticket)
        self.worlds.store.set_backup_job(
            ticket.world_id, kind, STATE_FAILED, message, None, started_at, _iso(self._clock())
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
            return await anyio.to_thread.run_sync(self._snapshot, ticket, spool, KIND_BACKUP)
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
        LOG.info("Welt %s gesichert: %d Bytes", ticket.world_id, entry.size)

    def _add_proof(
        self, ticket: OfflineTicket, uid: str, entry: FilesEntry, info: SnapshotInfo, kind: str, created_at: str
    ) -> None:
        """Integritätsnachweis der hochgeladenen Datei (D-12): nur damit ist sie wiederherstellbar."""
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
        """Einziger Ausgang für fehlgeschlagene Aufträge: Zeile failed, dann Hinweis an ``uid`` (D-16).

        Nur der auslösende Verwalter bekommt die Benachrichtigung, Erfolg bleibt
        still. Ein Fehler beim Benachrichtigen ändert den Auftrag nicht.
        """
        target = await self._shielded(self._mark_failed, world_id, kind, message, started_at)
        if target is None:
            return
        world_name, origin = target
        text = job_failed_message(FAILED_SUBJECTS.get(kind, BACKUP_FAILED_SUBJECT), world_id, world_name, message)
        link = app_link(origin) if origin is not None else ""
        try:
            delivered = await self._notifier().notify(uid, text.subject, text.message, text.params, link)
        except Exception as exc:
            LOG.warning("Fehler-Hinweis zu Welt %s nicht gesendet: %s", world_id, type(exc).__name__)
            return
        if not delivered:
            LOG.info("Fehler-Hinweis zu Welt %s nicht zugestellt", world_id)

    def _mark_failed(self, world_id: str, kind: str, message: str, started_at: str) -> tuple[str, str | None] | None:
        """Zeile auf failed; liefert Weltname und Link-Basis, oder None ohne Welt."""
        store = self.worlds.store
        row = store.get_world(world_id)
        if row is None:
            return None
        store.set_backup_job(world_id, kind, STATE_FAILED, message, None, started_at, _iso(self._clock()))
        return row.name, link_origin(store)

    # Wiederherstellen (BACKUP-02): Eltern-Request

    async def start_restore(
        self, world_id: str, uid: str, file_id: int, *, confirm: bool, confirm_disconnect: bool
    ) -> None:
        """Prüft, setzt die Welt auf restoring und startet den Ablauf im Hintergrund (D-04).

        Wirft RestoreNotConfirmed, WorldNotFoundError, BackupNotFound (unbekannte,
        fremde oder zu einer anderen Welt gehörende Datei, vor jedem Docker- oder
        Files-Aufruf, D-13), PlayersOnline oder WorldBusyError; dann ist nichts
        verändert. Eine kaputte Welt (failed, auch delete-only) ist erlaubt (D-15).
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
        # Nur der eigene Nachweis zu genau dieser Welt macht eine Datei vertrauenswürdig (T-05-28).
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

    # Wiederherstellen: Ablauf (Hintergrund)

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
        """A: holen und prüfen (Welt läuft), B: Stopp und vor-restore, C: Tausch (RESEARCH Pattern 4/5)."""
        try:
            restore = await self._fetch_and_check(ticket, proof, uid, spools)
        except BaseException:
            # Noch nichts gestoppt: Welt in ihren alten Zustand zurück, auch eine kaputte bleibt kaputt.
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
        """Phase A: Platz, Download, Größe und SHA-256 gegen den Nachweis, Restore-Tar bauen."""
        await anyio.to_thread.run_sync(self._check_restore_space, proof)
        download = await self._new_spool(spools)
        await self._files().download_to(uid, proof.path, cast(BinaryIO, download))
        await anyio.to_thread.run_sync(self._check_integrity, download, proof)
        restore = await self._new_spool(spools)
        await anyio.to_thread.run_sync(self._restore_tar, ticket, download, restore)
        return restore

    def _check_restore_space(self, proof: BackupRow) -> None:
        self._spool_dir.mkdir(parents=True, exist_ok=True)
        if disk_free(self._spool_dir) < RESTORE_SPACE_FACTOR * proof.size:
            raise BackupError(MSG_NO_SPACE)

    @staticmethod
    def _check_integrity(download: IO[bytes], proof: BackupRow) -> None:
        """Files ist für Verwalter beschreibbar: nur exakt die nachgewiesene Datei wird eingespielt."""
        download.seek(0, io.SEEK_END)
        size = download.tell()
        if size != proof.size or sha256_of(cast(BinaryIO, download)) != proof.sha256:
            raise RestoreTampered

    @staticmethod
    def _restore_tar(ticket: OfflineTicket, source: IO[bytes], sink: IO[bytes]) -> None:
        """Volle Prüfung und Filterung (Plan 01); Manifest muss zu Welt und Spielart der Zeile passen."""
        source.seek(0)
        prepare_restore(
            cast(BinaryIO, source), world_id=ticket.world_id, preset=ticket.preset, sink=cast(BinaryIO, sink)
        )

    async def _offline_safety(
        self, ticket: OfflineTicket, uid: str, spools: list[IO[bytes]]
    ) -> tuple[bytes | None, IO[bytes] | None]:
        """Phase B: Halt, Stopp, Zählbuch, vor-restore-Sicherung; scheitert etwas, startet die alte Welt."""
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
        """Gibt es einen Stand, den eine vor-restore-Sicherung retten kann (D-05, D-15)?"""
        if ticket.previous_op_state == "failed" and ticket.previous_error in NO_SAFETY_ERRORS:
            return False
        return ticket.world_id in self.worlds.provisioner.list_managed()

    def _take_ledger(self, world_id: str) -> bytes | None:
        """Zählbuch verbuchen und unverändert bewahren (D-06); fehlt oder ist es kaputt, None."""
        self.worlds.book_ledger(world_id)
        try:
            status_file = self.worlds.provisioner.read_time_ledger(world_id)
        except WorldNotFoundError:
            return None
        if status_file is None or parse_ledger(status_file.content) is None:
            return None
        return status_file.content

    async def _safety_backup(self, ticket: OfflineTicket, uid: str, spools: list[IO[bytes]]) -> IO[bytes] | None:
        """Geprüfte vor-restore-Sicherung in Files mit eigenem Nachweis; der Spool bleibt für den Rückfall.

        Hat die Welt noch keinen Spielstand (MSG_NO_MAP), gibt es nichts zu bewahren:
        None, der Tausch läuft weiter. Jeder andere Fehler bricht vor der Zerstörung ab.
        """
        spool = await self._new_spool(spools)
        try:
            info = await anyio.to_thread.run_sync(self._snapshot, ticket, spool, KIND_VOR_RESTORE)
        except BackupError as exc:
            if str(exc) != MSG_NO_MAP:
                raise
            LOG.info("Welt %s ohne Spielstand, keine Sicherung vor dem Wiederherstellen", ticket.world_id)
            return None
        await anyio.to_thread.run_sync(self._verify, ticket, spool)
        now = self._clock()
        zone = await anyio.to_thread.run_sync(self.worlds.time.zone)
        base_name = backup_file_name(ticket.name, datetime.fromtimestamp(now, UTC), KIND_VOR_RESTORE, zone=zone)
        folder = folder_path(folder_name(ticket.name, ticket.world_id))
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
        """Phase C: Tausch mit einem zweiten Versuch, sonst Rückfall auf den Sicherheits-Snapshot.

        Ab mark_swap ist die alte Welt nicht mehr sicher vorhanden: Jeder Ausgang
        endet in ready (Erfolg oder Rückfall) oder failed mit RESTORE_INTERRUPTED.
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
                LOG.warning("Welt %s: Tausch Versuch %d gescheitert (%s)", world_id, attempt, type(exc).__name__)
                continue
            return True
        return False

    async def _fallback(
        self, ticket: OfflineTicket, safety: IO[bytes], ledger: bytes | None, spools: list[IO[bytes]]
    ) -> bool:
        """Den lokalen Sicherheits-Snapshot auf demselben Weg einspielen (Pattern 5 "Fehler im Tausch")."""
        fallback = await self._new_spool(spools)
        try:
            await anyio.to_thread.run_sync(self._restore_tar, ticket, safety, fallback)
        except Exception as exc:
            LOG.warning("Welt %s: Rückfall nicht vorbereitet (%s)", ticket.world_id, type(exc).__name__)
            return False
        return await self._try_swap(ticket.world_id, fallback, ledger, 1)

    async def _finish_swap(self, ticket: OfflineTicket) -> None:
        error = await self._shielded(self.worlds.finish_swap, ticket.world_id, ticket.was_running)
        if error is not None:
            # Die Weltdaten sind eingespielt; den Startfehler zeigt die Welt selbst.
            LOG.warning("Welt %s: nach dem Wiederherstellen nicht gestartet", ticket.world_id)

    def _finish_restore_ok(self, world_id: str, proof: BackupRow, started_at: str) -> None:
        self.worlds.store.set_backup_job(
            world_id, KIND_RESTORE, STATE_OK, None, proof.name, started_at, _iso(self._clock())
        )
        LOG.info("Welt %s wiederhergestellt", world_id)

    # Wiederanlauf und Liste

    def recover_jobs(self) -> int:
        """Nach dem Start: Aufträge im Zustand running wurden unterbrochen (D-11); Anzahl.

        Synchron im Lifespan, bevor ein Request einen neuen Auftrag starten kann.
        """
        store = self.worlds.store
        jobs = store.running_backup_jobs()
        finished = _iso(self._clock())
        for job in jobs:
            text = RESTORE_JOB_INTERRUPTED if job.kind == KIND_RESTORE else JOB_INTERRUPTED
            store.set_backup_job(job.world_id, job.kind, STATE_FAILED, text, job.file_name, job.started_at, finished)
            LOG.warning("Auftrag für Welt %s durch Neustart unterbrochen", job.world_id)
        return len(jobs)

    async def list_backups(self, world_id: str, uid: str) -> BackupList:
        """Gültige Sicherungen dieser Welt in den Files von ``uid`` (D-07, D-08, D-12, D-13).

        Nur Dateien, deren (file_id, Größe) auch ein eigener Nachweis hat; alles
        andere im Ordner zählt ``other_files``. Reihenfolge wie der Nachweis
        (neueste zuerst). Wirft WorldNotFoundError oder FilesError.
        """
        row = await anyio.to_thread.run_sync(self.worlds.store.get_world, world_id)
        if row is None:
            raise WorldNotFoundError(NOT_FOUND)
        proofs = await anyio.to_thread.run_sync(self.worlds.store.backups_for, uid, world_id)
        files = await self._files().listdir(uid, folder_path(folder_name(row.name, world_id)))
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
