"""Archive core for backup and restore, no I/O apart from the file objects passed in.

Backup (BACKUP-01): Docker delivers the world folder of the stopped container
as a tar stream with the prefix ``world/``. :func:`write_snapshot` translates it
by streaming into a tar.gz with the manifest ``gameworld-backup.json`` at the
root and the world data under ``world/``. Runtime files of the own mods and
``worldmods/`` stay out (D-03); they are provisioned fresh after a restore.
SQLite journals stay in: after a hard stop, a hot journal belongs
to the database as a pair (pitfall 1).

Restore (BACKUP-02): the content of a backup in Nextcloud Files
is not trustworthy. :func:`prepare_restore` checks every entry
(paths, types, limits, manifest) and builds a restore tar from it with names
relative to the world folder; code (``.lua``, ``worldmods/``, ``mods/``, ``game/``),
``world.mt`` and ``gameworld_*`` files are discarded. Unsafe entries
abort, they are never silently skipped.

Only counts and error types go into the log, never names from an archive.
"""

from __future__ import annotations

import errno
import gzip
import hashlib
import io
import json
import logging
import tarfile
import time
import zlib
from collections.abc import Buffer, Iterator
from dataclasses import dataclass
from typing import BinaryIO, cast

from gameworld.provisioner import access_mod, status_mod, time_mod
from gameworld.provisioner.archive import LUANTI_UID, safe_relative

LOG = logging.getLogger(__name__)

MSG_BAD_ENTRY = "Die Sicherung enthält ungültige oder unsichere Einträge."
MSG_NO_MAP = "Ohne Weltkarte (map.sqlite) gibt es keine gültige Sicherung."
MSG_FOREIGN_WORLD = "Diese Sicherung gehört zu einer anderen Welt."
MSG_TOO_BIG = "Die Sicherung ist zu groß oder auffällig stark gepackt."
MSG_NO_MANIFEST = "Die Sicherung stammt nicht von Gameworld oder ist beschädigt."
MSG_NO_SPACE = "Nicht genug freier Speicherplatz auf dem Server."
MSG_BROKEN_STREAM = "Die Weltdaten ließen sich nicht vollständig lesen."

MANIFEST_NAME = "gameworld-backup.json"
MANIFEST_FORMAT = 1
MANIFEST_MAX = 64 * 1024
WORLD_PREFIX = "world"
MAP_NAME = "map.sqlite"
KIND_BACKUP = "backup"
KIND_VOR_RESTORE = "vor-restore"
COMPRESS_LEVEL = 6
READ_BUFFER = 1024 * 1024
HASH_BLOCK = 1024 * 1024

# Limits against tar and gzip bombs (T-05-03).
MAX_RESTORE_BYTES = 8 * 1024 * 1024 * 1024
MAX_RESTORE_ENTRIES = 200_000
MAX_RATIO = 50
# Below this unpacked sum MAX_RATIO does not apply: empty SQLite pages
# pack far beyond 50:1, small real worlds must not fail because of it.
RATIO_FLOOR = 256 * 1024 * 1024

# Backup: runtime files of the own mods, names only from their constants (D-03).
BACKUP_EXCLUDED_FILES = frozenset(
    {
        access_mod.ACCESS_FILE_NAME,
        access_mod.STATE_FILE_NAME,
        access_mod.EVENTS_FILE_NAME,
        status_mod.PLAYERS_FILE_NAME,
        time_mod.RULES_FILE_NAME,
        time_mod.LEDGER_FILE_NAME,
    }
)
BACKUP_EXCLUDED_DIRS = frozenset({"worldmods"})

# Restore: everything that is code or is provisioned fresh (T-05-02).
RESTORE_DROP_FILES = frozenset({"world.mt"})
RESTORE_DROP_DIRS = frozenset({"worldmods", "mods", "game"})
RESTORE_DROP_SUFFIX = ".lua"
RESTORE_DROP_PREFIX = "gameworld_"


class BackupError(Exception):
    """Backup or restore failed; the text is fixed and German."""


class RestoreRejected(BackupError):
    """The backup is invalid, tampered with or belongs to another world."""


@dataclass(frozen=True)
class SnapshotInfo:
    size: int
    sha256: str
    skipped: int


@dataclass(frozen=True)
class RestoreInfo:
    entries: int
    unpacked_size: int


class IterStream(io.RawIOBase):
    """File object over a chunk iterator (Docker stream), without collecting the stream."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        super().__init__()
        self._chunks = chunks
        self._rest = memoryview(b"")

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer, /) -> int:
        view = memoryview(buffer).cast("B")
        while not self._rest:
            try:
                self._rest = memoryview(next(self._chunks))
            except StopIteration:
                return 0
        size = min(len(view), len(self._rest))
        view[:size] = self._rest[:size]
        self._rest = self._rest[size:]
        return size


class HashingWriter(io.RawIOBase):
    """Passes bytes through to ``sink``, counts them and computes SHA-256 along the way."""

    def __init__(self, sink: BinaryIO) -> None:
        super().__init__()
        self._sink = sink
        self._hash = hashlib.sha256()
        self.count = 0

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer, /) -> int:
        data = memoryview(b).cast("B")
        self._sink.write(data)
        self._hash.update(data)
        self.count += len(data)
        return len(data)

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


class _DiscardSink(io.RawIOBase):
    """Sink for the dry run of :func:`verify_snapshot`: discards everything."""

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer, /) -> int:
        return memoryview(b).nbytes


def build_manifest(world_id: str, preset: str, luanti_version: str, created_at: str, kind: str) -> bytes:
    """Manifest at the tar root (JSON, sorted keys)."""
    return json.dumps(
        {
            "format": MANIFEST_FORMAT,
            "world_id": world_id,
            "preset": preset,
            "luanti_version": luanti_version,
            "created_at": created_at,
            "kind": kind,
        },
        sort_keys=True,
    ).encode("utf-8")


def world_relative(name: str) -> str | None:
    """``world/x`` as ``x`` (checked via safe_relative), otherwise None."""
    prefix = f"{WORLD_PREFIX}/"
    if not name.startswith(prefix):
        return None
    return safe_relative(name[len(prefix) :])


def _is_world_root(member: tarfile.TarInfo) -> bool:
    return member.isdir() and member.name.rstrip("/") == WORLD_PREFIX


def _normalized(member: tarfile.TarInfo, name: str) -> tarfile.TarInfo:
    """Copy with fixed owner and mode; mtime from the archive (never negative)."""
    info = tarfile.TarInfo(name)
    info.uid = info.gid = LUANTI_UID
    info.uname = info.gname = ""
    info.mtime = max(int(member.mtime), 0)
    if member.isdir():
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
    else:
        info.mode = 0o644
        info.size = member.size
    return info


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, *, mtime: int) -> None:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = LUANTI_UID
    info.uname = info.gname = ""
    info.mode = 0o644
    info.size = len(data)
    info.mtime = mtime
    tar.addfile(info, io.BytesIO(data))


def _backup_excluded(relative: str) -> bool:
    head = relative.split("/", 1)[0]
    return relative in BACKUP_EXCLUDED_FILES or head in BACKUP_EXCLUDED_DIRS


def _no_space(exc: OSError) -> BackupError | None:
    return BackupError(MSG_NO_SPACE) if exc.errno == errno.ENOSPC else None


def write_snapshot(chunks: Iterator[bytes], sink: BinaryIO, manifest: bytes) -> SnapshotInfo:
    """Docker tar stream (prefix ``world/``) filtered as tar.gz into ``sink``.

    Memory stays constant (chunk and read buffer); size and SHA-256 arise
    while writing. Symlinks, hardlinks, devices and unsafe names are
    skipped and counted. If ``world/map.sqlite`` did not arrive as a regular file,
    the function raises BackupError(MSG_NO_MAP) after reading completely: a
    never-started world or a stream cut off at a member boundary must not
    yield a seemingly valid backup (T-05-49). Transport errors from
    ``chunks`` stay unchanged, so that the provisioner maps them.
    """
    hasher = HashingWriter(sink)
    skipped = 0
    written = 0
    has_map = False
    try:
        with tarfile.open(
            fileobj=cast(BinaryIO, hasher), mode="w:gz", compresslevel=COMPRESS_LEVEL, format=tarfile.PAX_FORMAT
        ) as out:
            _add_bytes(out, MANIFEST_NAME, manifest, mtime=int(time.time()))
            source = io.BufferedReader(IterStream(chunks), READ_BUFFER)
            with tarfile.open(fileobj=cast(BinaryIO, source), mode="r|") as src:
                for member in src:
                    if _is_world_root(member):
                        continue
                    if not (member.isfile() or member.isdir()):
                        skipped += 1
                        continue
                    relative = world_relative(member.name)
                    if relative is None:
                        skipped += 1
                        continue
                    if _backup_excluded(relative):
                        continue
                    info = _normalized(member, f"{WORLD_PREFIX}/{relative}")
                    if member.isfile():
                        out.addfile(info, src.extractfile(member))
                        has_map = has_map or relative == MAP_NAME
                    else:
                        out.addfile(info)
                    written += 1
            # The tar ends at the end marker; Docker pads after it. Read the whole stream,
            # so that an abort at the end also arrives as a transport error.
            while source.read(READ_BUFFER):
                pass
            if not has_map:
                raise BackupError(MSG_NO_MAP)
    except (tarfile.TarError, EOFError) as exc:
        LOG.warning("Snapshot stream unreadable: %s", type(exc).__name__)
        raise BackupError(MSG_BROKEN_STREAM) from exc
    except OSError as exc:
        mapped = _no_space(exc)
        if mapped is None:
            raise
        raise mapped from exc
    LOG.info("Snapshot written: %d entries, %d skipped, %d bytes", written, skipped, hasher.count)
    return SnapshotInfo(size=hasher.count, sha256=hasher.hexdigest(), skipped=skipped)


def _check_manifest(raw: bytes, *, world_id: str, preset: str) -> None:
    try:
        manifest = json.loads(raw)
    except ValueError as exc:
        raise RestoreRejected(MSG_NO_MANIFEST) from exc
    if not isinstance(manifest, dict) or manifest.get("format") != MANIFEST_FORMAT:
        raise RestoreRejected(MSG_NO_MANIFEST)
    fields = cast(dict[str, object], manifest)
    if fields.get("world_id") != world_id or fields.get("preset") != preset:
        raise RestoreRejected(MSG_FOREIGN_WORLD)


def _restore_dropped(relative: str) -> bool:
    parts = relative.split("/")
    if parts[0] in RESTORE_DROP_DIRS or relative in RESTORE_DROP_FILES:
        return True
    return relative.endswith(RESTORE_DROP_SUFFIX) or any(part.startswith(RESTORE_DROP_PREFIX) for part in parts)


def _packed_size(source: BinaryIO) -> int:
    source.seek(0, io.SEEK_END)
    size = source.tell()
    source.seek(0)
    return size


class _Limits:
    """Counts entries and unpacked bytes and aborts at a limit (T-05-03)."""

    def __init__(self, packed: int) -> None:
        self._packed = packed
        self.entries = 0
        self.unpacked = 0

    def add(self, member: tarfile.TarInfo) -> None:
        self.entries += 1
        if member.isfile():
            self.unpacked += member.size
        ratio_limit = max(self._packed * MAX_RATIO, RATIO_FLOOR)
        if self.entries > MAX_RESTORE_ENTRIES or self.unpacked > MAX_RESTORE_BYTES or self.unpacked > ratio_limit:
            raise RestoreRejected(MSG_TOO_BIG)


def _restore_pass(source: BinaryIO, *, world_id: str, preset: str, sink: BinaryIO) -> RestoreInfo:
    limits = _Limits(_packed_size(source))
    manifest_seen = False
    has_map = False
    written = 0
    unpacked = 0
    with (
        tarfile.open(fileobj=source, mode="r:gz") as src,
        tarfile.open(fileobj=sink, mode="w:gz", compresslevel=COMPRESS_LEVEL, format=tarfile.PAX_FORMAT) as out,
    ):
        for member in src:
            limits.add(member)
            if member.name == MANIFEST_NAME:
                if manifest_seen or not member.isfile() or member.size > MANIFEST_MAX:
                    raise RestoreRejected(MSG_BAD_ENTRY)
                handle = src.extractfile(member)
                if handle is None:
                    raise RestoreRejected(MSG_BAD_ENTRY)
                _check_manifest(handle.read(MANIFEST_MAX), world_id=world_id, preset=preset)
                manifest_seen = True
                continue
            # Type before everything else: links and devices abort even in discarded folders.
            if not (member.isfile() or member.isdir()):
                raise RestoreRejected(MSG_BAD_ENTRY)
            if _is_world_root(member):
                continue
            relative = world_relative(member.name)
            if relative is None:
                raise RestoreRejected(MSG_BAD_ENTRY)
            if _restore_dropped(relative):
                continue
            info = _normalized(member, relative)
            if member.isfile():
                out.addfile(info, src.extractfile(member))
                unpacked += member.size
                has_map = has_map or relative == MAP_NAME
            else:
                out.addfile(info)
            written += 1
        if not manifest_seen:
            raise RestoreRejected(MSG_NO_MANIFEST)
        if not has_map:
            raise RestoreRejected(MSG_NO_MAP)
    return RestoreInfo(entries=written, unpacked_size=unpacked)


def prepare_restore(source: BinaryIO, *, world_id: str, preset: str, sink: BinaryIO) -> RestoreInfo:
    """Checks a backup in one pass and writes the restore tar (gzip) to ``sink``.

    The restore tar has names relative to the world folder (without ``world/``) and is
    put into place via ``put_archive`` to ``WORLD_PATH``; Docker accepts
    gzip there as well. Owner 30000, mode 0644/0755, mtime from the archive. Raises
    RestoreRejected on every unsafe entry, missing or foreign
    manifest, missing map.sqlite and exceeded limits; then the
    content of ``sink`` is unusable and must be discarded.
    """
    try:
        info = _restore_pass(source, world_id=world_id, preset=preset, sink=sink)
    except RestoreRejected as exc:
        LOG.warning("Backup rejected: %s", exc)
        raise
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        LOG.warning("Backup unreadable: %s", type(exc).__name__)
        raise RestoreRejected(MSG_BAD_ENTRY) from exc
    except OSError as exc:
        mapped = _no_space(exc)
        if mapped is None:
            raise
        raise mapped from exc
    LOG.info("Restore prepared: %d entries, %d bytes unpacked", info.entries, info.unpacked_size)
    return info


def verify_snapshot(source: BinaryIO, *, world_id: str, preset: str) -> RestoreInfo:
    """Dry run with the restore logic over a finished tar.gz, without writing anything.

    Sets the position to 0 before and after (the upload then reads from the start).
    """
    source.seek(0)
    try:
        return prepare_restore(source, world_id=world_id, preset=preset, sink=cast(BinaryIO, _DiscardSink()))
    finally:
        source.seek(0)


def ledger_tar(ledger: bytes) -> bytes:
    """Uncompressed tar with exactly the preserved ledger (D-06), relative to the world folder."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_bytes(tar, time_mod.LEDGER_FILE_NAME, ledger, mtime=int(time.time()))
    return buffer.getvalue()


def sha256_of(fp: BinaryIO) -> str:
    """SHA-256 over the whole content in blocks; position afterwards at 0."""
    fp.seek(0)
    digest = hashlib.sha256()
    while block := fp.read(HASH_BLOCK):
        digest.update(block)
    fp.seek(0)
    return digest.hexdigest()
