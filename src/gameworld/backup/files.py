"""Storage of backups in Nextcloud Files on behalf of the triggering manager (D-01, D-13).

One own short-lived client ``nc_as(uid, ...)`` per operation with a generous
WebDAV timeout (600 s, pitfall 6) and upload v1 (``chunked_upload_v2=False``);
never a shared client, sessions are always closed (WR-05, T-05-07).

An upload counts as successful only when ``by_path`` shows the file with exactly the
local size (T-05-09). Because WebDAV PUT silently overwrites, the
upload first goes to an own, unique temp name; the target name (``-2``,
``-3`` ..., pitfall 5) is then assigned by a MOVE with ``Overwrite: F``. A file of
the same name that appeared in the TOCTOU window stays untouched (412, next
suffix). On failure only the own temp or freshly moved file is
deleted, never an existing one (T-05-08, D-08, WR-03).

Folder paths are always built by the caller (``naming.folder_path``), this module composes
nothing from world names. Only the error type and status code go into the log, never
paths, file names or accounts (T-05-12). Errors appear as ``FilesError`` with
a fixed German text; the flow (plan 05) treats it like ``BackupError``.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, BinaryIO, Protocol
from uuid import uuid4

import anyio
from nc_py_api import NextcloudException

from gameworld.backup.archive import BackupError
from gameworld.nc import nc_as

LOG = logging.getLogger(__name__)

DAV_TIMEOUT = 600
UPLOAD_CHUNK = 10 * 1024 * 1024
MAX_SUFFIX = 99
# Cleanup after an error or abort takes at most this long (own target file).
CLEANUP_TIMEOUT = 30
STATUS_NOT_FOUND = 404
# MKCOL on an existing folder answers 405 Method Not Allowed.
STATUS_EXISTS = 405
# MOVE with "Overwrite: F" onto an existing target answers 412 Precondition Failed.
STATUS_TARGET_EXISTS = 412
STATUS_QUOTA = 507
# Temp suffix of the upload; ".part" is reserved in Nextcloud for internal partial uploads.
TEMP_SUFFIX = ".gwtmp"

MSG_QUOTA = "Nicht genug Speicherplatz in deinen Nextcloud-Dateien."
MSG_UPLOAD_INCOMPLETE = "Die Sicherung wurde nicht vollständig in Nextcloud gespeichert."
MSG_FILE_GONE = "Diese Sicherung liegt nicht mehr in deinen Nextcloud-Dateien."
MSG_FILES_FAILED = "Nextcloud-Dateien sind gerade nicht erreichbar."
MSG_NAME_EXHAUSTED = "Zu viele Sicherungen mit gleichem Namen. Bitte versuche es in einer Minute erneut."


class FilesError(Exception):
    """Error of the Files storage; ``str(exc)`` is always a fixed German text."""


@dataclass(frozen=True)
class FilesEntry:
    file_id: int
    path: str
    name: str
    size: int
    modified: datetime | None = None


# suffix(name, n) is naming.with_suffix: n 1 leaves the name unchanged.
SuffixFn = Callable[[str, int], str]


class BackupFiles(Protocol):
    async def upload(
        self, uid: str, folder_path: str, base_name: str, spool: BinaryIO, size: int, suffix: SuffixFn
    ) -> FilesEntry:
        """Uploads ``spool`` under a free name into ``folder_path`` and proves the size."""
        ...

    async def listdir(self, uid: str, folder_path: str) -> list[FilesEntry]:
        """Files in the folder; a missing folder gives an empty list."""
        ...

    async def stat(self, uid: str, path: str) -> FilesEntry | None:
        """File at ``path`` or None."""
        ...

    async def download_to(self, uid: str, path: str, fp: BinaryIO) -> None:
        """Streams the file to ``fp``; if it is missing, FilesError(MSG_FILE_GONE)."""
        ...

    async def delete_own(self, uid: str, path: str) -> None:
        """Deletes an own target file; if it is missing, nothing happens."""
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
    """Fixed text for an exception; only type and status code are logged."""
    if isinstance(exc, FilesError):
        return exc
    if isinstance(exc, NextcloudException):
        LOG.warning("Nextcloud files: %s failed, status %s", action, exc.status_code)
        if exc.status_code == STATUS_QUOTA:
            return FilesError(MSG_QUOTA)
        return FilesError(MSG_FILES_FAILED)
    LOG.warning("Nextcloud files: %s failed: %s", action, type(exc).__name__)
    return FilesError(MSG_FILES_FAILED)


async def _by_path(nc: Any, path: str) -> Any | None:
    try:
        return await nc.files.by_path(path)
    except NextcloudException as exc:
        if exc.status_code == STATUS_NOT_FOUND:
            return None
        raise


async def _makedirs(nc: Any, folder_path: str) -> None:
    """Creates ``folder_path`` level by level; existing levels (405) are fine.

    Deliberately not ``nc.files.makedirs``: it composes the levels with ``os.path.join``,
    on Windows this yields ``Gameworld\\Sicherungen`` and Nextcloud
    rejects the backslash with 400 (proven on the dev stack). WebDAV paths are always
    separated by ``/``.
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
    """Real storage via nc_py_api ``files`` (WebDAV) on behalf of ``uid``."""

    async def upload(
        self, uid: str, folder_path: str, base_name: str, spool: BinaryIO, size: int, suffix: SuffixFn
    ) -> FilesEntry:
        try:
            async with _client(uid) as nc:
                await _makedirs(nc, folder_path)
                # WR-03: PUT overwrites silently; therefore first upload to an own, unique
                # temp name and then rename by MOVE with "Overwrite: F".
                created = f"{folder_path}/.{base_name}.{uuid4().hex}{TEMP_SUFFIX}"
                try:
                    spool.seek(0)
                    await nc.files.upload_stream(created, spool, chunk_size=UPLOAD_CHUNK)
                    node = await _by_path(nc, created)
                    if node is None or int(node.info.size) != size:
                        raise FilesError(MSG_UPLOAD_INCOMPLETE)
                    created = await self._move_to_free_target(nc, folder_path, base_name, suffix, created)
                    node = await _by_path(nc, created)
                    if node is None:
                        raise FilesError(MSG_UPLOAD_INCOMPLETE)
                    return _entry(node)
                except BaseException:
                    # Only the own temp or freshly moved file; also on abort, time-limited.
                    with anyio.move_on_after(CLEANUP_TIMEOUT, shield=True), contextlib.suppress(Exception):
                        await nc.files.delete(created, not_fail=True)
                    raise
        except Exception as exc:
            raise _map_error(exc, "Upload") from exc

    @staticmethod
    async def _move_to_free_target(nc: Any, folder_path: str, base_name: str, suffix: SuffixFn, temp: str) -> str:
        """MOVE with "Overwrite: F" to the first free name; a target that appeared in the window stays untouched."""
        for n in range(1, MAX_SUFFIX + 1):
            target = f"{folder_path}/{suffix(base_name, n)}"
            if await _by_path(nc, target) is not None:
                continue
            try:
                await nc.files.move(temp, target)
            except NextcloudException as exc:
                if exc.status_code == STATUS_TARGET_EXISTS:
                    continue
                raise
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
        except BackupError:
            # From the write target itself (e.g. size cap of the restore): pass through unchanged.
            raise
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
    """Module-wide singleton; tests inject a fake."""
    global _files
    if _files is None:
        _files = NcBackupFiles()
    return _files
