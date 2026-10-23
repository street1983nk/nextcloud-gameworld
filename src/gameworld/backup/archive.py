"""Archiv-Kern für Sicherung und Wiederherstellung, ohne I/O außer den übergebenen Datei-Objekten.

Sicherung (BACKUP-01): Docker liefert den Weltordner des gestoppten Containers
als Tar-Strom mit Präfix ``world/``. :func:`write_snapshot` übersetzt ihn
gestreamt in ein tar.gz mit dem Manifest ``gameworld-backup.json`` an der
Wurzel und den Weltdaten unter ``world/``. Laufzeitdateien der eigenen Mods und
``worldmods/`` bleiben draußen (D-03); sie werden nach einem Restore frisch
provisioniert. SQLite-Journale bleiben drin: Nach einem harten Stopp gehört ein
heißes Journal als Paar zur Datenbank (Pitfall 1).

Wiederherstellung (BACKUP-02): Der Inhalt einer Sicherung in Nextcloud Files
ist nicht vertrauenswürdig. :func:`prepare_restore` prüft jeden Eintrag
(Pfade, Typen, Grenzen, Manifest) und baut daraus ein Restore-Tar mit Namen
relativ zum Weltordner; Code (``.lua``, ``worldmods/``, ``mods/``, ``game/``),
``world.mt`` und ``gameworld_*``-Dateien werden verworfen. Unsichere Einträge
brechen ab, sie werden nie still übersprungen.

Ins Log kommen nur Zählwerte und Fehlertypen, nie Namen aus einem Archiv.
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

# Grenzen gegen Tar- und gzip-Bomben (T-05-03).
MAX_RESTORE_BYTES = 8 * 1024 * 1024 * 1024
MAX_RESTORE_ENTRIES = 200_000
MAX_RATIO = 50
# Unter dieser entpackten Summe greift MAX_RATIO nicht: leere SQLite-Seiten
# packen weit über 50:1, kleine echte Welten dürfen daran nicht scheitern.
RATIO_FLOOR = 256 * 1024 * 1024

# Sicherung: Laufzeitdateien der eigenen Mods, Namen nur aus deren Konstanten (D-03).
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

# Wiederherstellung: alles, was Code ist oder frisch provisioniert wird (T-05-02).
RESTORE_DROP_FILES = frozenset({"world.mt"})
RESTORE_DROP_DIRS = frozenset({"worldmods", "mods", "game"})
RESTORE_DROP_SUFFIX = ".lua"
RESTORE_DROP_PREFIX = "gameworld_"


class BackupError(Exception):
    """Sicherung oder Wiederherstellung gescheitert; der Text ist fest und deutsch."""


class RestoreRejected(BackupError):
    """Die Sicherung ist ungültig, manipuliert oder gehört zu einer anderen Welt."""


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
    """Datei-Objekt über einen Chunk-Iterator (Docker-Strom), ohne den Strom zu sammeln."""

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
    """Reicht Bytes an ``sink`` durch, zählt sie und rechnet SHA-256 mit."""

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
    """Senke für den Probelauf von :func:`verify_snapshot`: verwirft alles."""

    def writable(self) -> bool:
        return True

    def write(self, b: Buffer, /) -> int:
        return memoryview(b).nbytes


def build_manifest(world_id: str, preset: str, luanti_version: str, created_at: str, kind: str) -> bytes:
    """Manifest an der Tar-Wurzel (JSON, sortierte Schlüssel)."""
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
    """``world/x`` als ``x`` (geprüft über safe_relative), sonst None."""
    prefix = f"{WORLD_PREFIX}/"
    if not name.startswith(prefix):
        return None
    return safe_relative(name[len(prefix) :])


def _is_world_root(member: tarfile.TarInfo) -> bool:
    return member.isdir() and member.name.rstrip("/") == WORLD_PREFIX


def _normalized(member: tarfile.TarInfo, name: str) -> tarfile.TarInfo:
    """Kopie mit festem Besitzer und Modus; mtime aus dem Archiv (nie negativ)."""
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
    """Docker-Tar-Strom (Präfix ``world/``) gefiltert als tar.gz nach ``sink``.

    Speicher bleibt konstant (Chunk- und Lesepuffer); Größe und SHA-256 entstehen
    beim Schreiben. Symlinks, Hardlinks, Geräte und unsichere Namen werden
    übersprungen und gezählt. Kam ``world/map.sqlite`` nicht als reguläre Datei,
    wirft die Funktion nach dem vollständigen Lesen BackupError(MSG_NO_MAP): eine
    nie gestartete Welt oder ein an einer Member-Grenze abgerissener Strom darf
    keine scheinbar gültige Sicherung ergeben (T-05-49). Transportfehler aus
    ``chunks`` bleiben unverändert, damit der Provisioner sie abbildet.
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
            # Tar endet an der Endmarke; Docker füllt danach auf. Den Strom ganz
            # lesen, damit auch ein Abbruch am Ende als Transportfehler ankommt.
            while source.read(READ_BUFFER):
                pass
            if not has_map:
                raise BackupError(MSG_NO_MAP)
    except (tarfile.TarError, EOFError) as exc:
        LOG.warning("Snapshot-Strom nicht lesbar: %s", type(exc).__name__)
        raise BackupError(MSG_BROKEN_STREAM) from exc
    except OSError as exc:
        mapped = _no_space(exc)
        if mapped is None:
            raise
        raise mapped from exc
    LOG.info("Snapshot geschrieben: %d Einträge, %d übersprungen, %d Bytes", written, skipped, hasher.count)
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
    """Zählt Einträge und entpackte Bytes und bricht bei einer Grenze ab (T-05-03)."""

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
            # Typ vor allem anderen: Links und Geräte brechen auch in verworfenen Ordnern ab.
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
    """Prüft eine Sicherung in einem Durchlauf und schreibt das Restore-Tar (gzip) nach ``sink``.

    Das Restore-Tar hat Namen relativ zum Weltordner (ohne ``world/``) und wird
    per ``put_archive`` nach ``WORLD_PATH`` eingespielt; Docker nimmt dort auch
    gzip an. Besitzer 30000, Modus 0644/0755, mtime aus dem Archiv. Wirft
    RestoreRejected bei jedem unsicheren Eintrag, fehlendem oder fremdem
    Manifest, fehlender map.sqlite und überschrittenen Grenzen; dann ist der
    Inhalt von ``sink`` unbrauchbar und gehört verworfen.
    """
    try:
        info = _restore_pass(source, world_id=world_id, preset=preset, sink=sink)
    except RestoreRejected as exc:
        LOG.warning("Sicherung abgelehnt: %s", exc)
        raise
    except (tarfile.TarError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        LOG.warning("Sicherung nicht lesbar: %s", type(exc).__name__)
        raise RestoreRejected(MSG_BAD_ENTRY) from exc
    except OSError as exc:
        mapped = _no_space(exc)
        if mapped is None:
            raise
        raise mapped from exc
    LOG.info("Restore vorbereitet: %d Einträge, %d Bytes entpackt", info.entries, info.unpacked_size)
    return info


def verify_snapshot(source: BinaryIO, *, world_id: str, preset: str) -> RestoreInfo:
    """Probelauf mit der Restore-Logik über ein fertiges tar.gz, ohne etwas zu schreiben.

    Setzt die Position vorher und nachher auf 0 (Upload liest danach von vorn).
    """
    source.seek(0)
    try:
        return prepare_restore(source, world_id=world_id, preset=preset, sink=cast(BinaryIO, _DiscardSink()))
    finally:
        source.seek(0)


def ledger_tar(ledger: bytes) -> bytes:
    """Unkomprimiertes Tar mit genau dem bewahrten Zählbuch (D-06), relativ zum Weltordner."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_bytes(tar, time_mod.LEDGER_FILE_NAME, ledger, mtime=int(time.time()))
    return buffer.getvalue()


def sha256_of(fp: BinaryIO) -> str:
    """SHA-256 über den ganzen Inhalt in Blöcken; Position danach auf 0."""
    fp.seek(0)
    digest = hashlib.sha256()
    while block := fp.read(HASH_BLOCK):
        digest.update(block)
    fp.seek(0)
    return digest.hexdigest()
