"""Ablage der Sicherungen in Nextcloud Files im Namen des auslösenden Verwalters (D-01, D-13).

Je Vorgang ein eigener, kurzlebiger Client ``nc_as(uid, ...)`` mit großzügigem
WebDAV-Timeout (600 s, Pitfall 6) und Upload v1 (``chunked_upload_v2=False``);
nie ein geteilter Client, Sessions werden immer geschlossen (WR-05, T-05-07).

Ein Upload gilt erst als gelungen, wenn ``by_path`` die Datei mit exakt der
lokalen Größe zeigt (T-05-09). Der Zielname wird vorher per ``by_path`` frei
gewählt (``-2``, ``-3`` ..., Pitfall 5); im Fehlerfall wird nur dieser frisch
gewählte Name gelöscht, nie eine vorhandene Datei (T-05-08).

Ordnerpfade baut immer der Aufrufer (``naming.folder_path``), dieses Modul setzt
nichts aus Weltnamen zusammen. Ins Log kommen nur Fehlertyp und Statuscode, nie
Pfade, Dateinamen oder Konten (T-05-12). Fehler erscheinen als ``FilesError`` mit
festem deutschem Text; der Ablauf (Plan 05) behandelt ihn wie ``BackupError``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Protocol

import anyio
from nc_py_api import NextcloudException

from gameworld.nc import nc_as

LOG = logging.getLogger(__name__)

DAV_TIMEOUT = 600
UPLOAD_CHUNK = 10 * 1024 * 1024
MAX_SUFFIX = 99
# Höchstens so lange wird nach einem Fehler oder Abbruch aufgeräumt (eigene Zieldatei).
CLEANUP_TIMEOUT = 30
STATUS_NOT_FOUND = 404
# MKCOL auf einen vorhandenen Ordner antwortet 405 Method Not Allowed.
STATUS_EXISTS = 405
STATUS_QUOTA = 507

MSG_QUOTA = "Nicht genug Speicherplatz in deinen Nextcloud-Dateien."
MSG_UPLOAD_INCOMPLETE = "Die Sicherung wurde nicht vollständig in Nextcloud gespeichert."
MSG_FILE_GONE = "Diese Sicherung liegt nicht mehr in deinen Nextcloud-Dateien."
MSG_FILES_FAILED = "Nextcloud-Dateien sind gerade nicht erreichbar."
MSG_NAME_EXHAUSTED = "Zu viele Sicherungen mit gleichem Namen. Bitte versuche es in einer Minute erneut."


class FilesError(Exception):
    """Fehler der Files-Ablage; ``str(exc)`` ist immer ein fester deutscher Text."""


@dataclass(frozen=True)
class FilesEntry:
    file_id: int
    path: str
    name: str
    size: int
    modified: datetime | None = None


# suffix(name, n) ist naming.with_suffix: n 1 lässt den Namen unverändert.
SuffixFn = Callable[[str, int], str]


class BackupFiles(Protocol):
    async def upload(
        self, uid: str, folder_path: str, base_name: str, spool: BinaryIO, size: int, suffix: SuffixFn
    ) -> FilesEntry:
        """Lädt ``spool`` unter einem freien Namen in ``folder_path`` und weist die Größe nach."""
        ...

    async def listdir(self, uid: str, folder_path: str) -> list[FilesEntry]:
        """Dateien im Ordner; ein fehlender Ordner ergibt eine leere Liste."""
        ...

    async def stat(self, uid: str, path: str) -> FilesEntry | None:
        """Datei unter ``path`` oder None."""
        ...

    async def download_to(self, uid: str, path: str, fp: BinaryIO) -> None:
        """Streamt die Datei nach ``fp``; fehlt sie, FilesError(MSG_FILE_GONE)."""
        ...

    async def delete_own(self, uid: str, path: str) -> None:
        """Löscht eine eigene Zieldatei; fehlt sie, passiert nichts."""
        ...


def _entry(node: Any) -> FilesEntry:
    modified = node.info.last_modified
    return FilesEntry(
        file_id=int(node.info.fileid),
        path=str(node.user_path).rstrip("/"),
        name=str(node.name),
        size=int(node.info.size),
        modified=modified if isinstance(modified, datetime) else None,
    )


def _map_error(exc: Exception, action: str) -> FilesError:
    """Fester Text zu einer Ausnahme; geloggt werden nur Typ und Statuscode."""
    if isinstance(exc, FilesError):
        return exc
    if isinstance(exc, NextcloudException):
        LOG.warning("Nextcloud-Dateien: %s gescheitert, Status %s", action, exc.status_code)
        if exc.status_code == STATUS_QUOTA:
            return FilesError(MSG_QUOTA)
        return FilesError(MSG_FILES_FAILED)
    LOG.warning("Nextcloud-Dateien: %s gescheitert: %s", action, type(exc).__name__)
    return FilesError(MSG_FILES_FAILED)


async def _by_path(nc: Any, path: str) -> Any | None:
    try:
        return await nc.files.by_path(path)
    except NextcloudException as exc:
        if exc.status_code == STATUS_NOT_FOUND:
            return None
        raise


async def _makedirs(nc: Any, folder_path: str) -> None:
    """Legt ``folder_path`` Stufe für Stufe an; vorhandene Stufen (405) sind in Ordnung.

    Bewusst nicht ``nc.files.makedirs``: Es setzt die Stufen mit ``os.path.join``
    zusammen, unter Windows entsteht so ``Gameworld\\Sicherungen`` und Nextcloud
    lehnt den Backslash mit 400 ab (am Dev-Stack belegt). WebDAV-Pfade trennt
    immer ``/``.
    """
    parts = [part for part in folder_path.split("/") if part]
    for depth in range(1, len(parts) + 1):
        try:
            await nc.files.mkdir("/".join(parts[:depth]))
        except NextcloudException as exc:
            if exc.status_code != STATUS_EXISTS:
                raise


def _client(uid: str) -> contextlib.AbstractAsyncContextManager[Any]:
    return nc_as(uid, npa_timeout_dav=DAV_TIMEOUT, chunked_upload_v2=False)


class NcBackupFiles:
    """Echte Ablage über nc_py_api ``files`` (WebDAV) im Namen von ``uid``."""

    async def upload(
        self, uid: str, folder_path: str, base_name: str, spool: BinaryIO, size: int, suffix: SuffixFn
    ) -> FilesEntry:
        try:
            async with _client(uid) as nc:
                await _makedirs(nc, folder_path)
                target = await self._free_target(nc, folder_path, base_name, suffix)
                try:
                    spool.seek(0)
                    await nc.files.upload_stream(target, spool, chunk_size=UPLOAD_CHUNK)
                    node = await _by_path(nc, target)
                    if node is None or int(node.info.size) != size:
                        raise FilesError(MSG_UPLOAD_INCOMPLETE)
                    return _entry(node)
                except BaseException:
                    # Nur der frisch gewählte Name; auch bei Abbruch, aber zeitlich begrenzt.
                    with anyio.move_on_after(CLEANUP_TIMEOUT, shield=True), contextlib.suppress(Exception):
                        await nc.files.delete(target, not_fail=True)
                    raise
        except Exception as exc:
            raise _map_error(exc, "Upload") from exc

    @staticmethod
    async def _free_target(nc: Any, folder_path: str, base_name: str, suffix: SuffixFn) -> str:
        for n in range(1, MAX_SUFFIX + 1):
            target = f"{folder_path}/{suffix(base_name, n)}"
            if await _by_path(nc, target) is None:
                return target
        raise FilesError(MSG_NAME_EXHAUSTED)

    async def listdir(self, uid: str, folder_path: str) -> list[FilesEntry]:
        try:
            async with _client(uid) as nc:
                nodes = await nc.files.listdir(folder_path)
        except NextcloudException as exc:
            if exc.status_code == STATUS_NOT_FOUND:
                return []
            raise _map_error(exc, "Auflisten") from exc
        except Exception as exc:
            raise _map_error(exc, "Auflisten") from exc
        return [_entry(node) for node in nodes if not node.is_dir]

    async def stat(self, uid: str, path: str) -> FilesEntry | None:
        try:
            async with _client(uid) as nc:
                node = await _by_path(nc, path)
        except Exception as exc:
            raise _map_error(exc, "Abfrage") from exc
        return None if node is None or node.is_dir else _entry(node)

    async def download_to(self, uid: str, path: str, fp: BinaryIO) -> None:
        try:
            async with _client(uid) as nc:
                await nc.files.download2stream(path, fp, chunk_size=UPLOAD_CHUNK)
        except NextcloudException as exc:
            if exc.status_code == STATUS_NOT_FOUND:
                raise FilesError(MSG_FILE_GONE) from exc
            raise _map_error(exc, "Download") from exc
        except Exception as exc:
            raise _map_error(exc, "Download") from exc

    async def delete_own(self, uid: str, path: str) -> None:
        try:
            async with _client(uid) as nc:
                await nc.files.delete(path, not_fail=True)
        except Exception as exc:
            raise _map_error(exc, "Löschen") from exc


_files: BackupFiles | None = None


def get_backup_files() -> BackupFiles:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _files
    if _files is None:
        _files = NcBackupFiles()
    return _files
