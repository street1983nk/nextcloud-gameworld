"""Hilfen der Backup-e2e-Tests (Phase 5): Files-Attrappe und unabhängige Prüfwerkzeuge.

``LocalFolderFiles`` erfüllt das BackupFiles-Protocol auf einem lokalen Ordner je
Konto; den echten Nextcloud-Weg belegt Plan 09. Alle Prüfhelfer arbeiten
bewusst NICHT über den Provisioner der ExApp (Owner-Regel "Gegenprobe nie mit
dem Muster der Umsetzung"): Dateien kommen über einen eigenen Docker-Client
(``api.api.get_archive``) aus dem Container, SQLite-Dateien werden nur lesend
(``mode=ro``) mit der Standardbibliothek geöffnet. Auch die gefälschten
Sicherungen baut dieses Modul selbst (eigenes Manifest, eigenes Tar), nicht über
den Archiv-Kern. Spielpasswörter erscheinen hier nie.
"""

from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tarfile
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import docker

from gameworld.backup.files import MSG_FILE_GONE, MSG_NAME_EXHAUSTED, MSG_UPLOAD_INCOMPLETE, FilesEntry, FilesError

# Eigene Literale statt Konstanten der Umsetzung (unabhängige Gegenprobe).
MANIFEST = "gameworld-backup.json"
WORLD = "world"
LUANTI_UID = 30000
FORGED_KINDS = ("traversal", "symlink", "lua", "foreign_preset")
MAX_SUFFIX = 99


class LocalFolderFiles:
    """BackupFiles-Attrappe: ``root/<uid>/<Ordnerpfad>/<Name>``, file_id fortlaufend.

    ``uploads`` protokolliert jeden gelungenen Upload als (uid, Pfad), damit Tests
    belegen können, dass etwa keine vor-restore-Sicherung entstand.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.uploads: list[tuple[str, str]] = []
        self._ids: dict[tuple[str, str], int] = {}
        self._next_id = 1000

    def _local(self, uid: str, path: str) -> Path:
        parts = PurePosixPath(path.lstrip("/")).parts
        if not parts or any(part in {"", ".", ".."} for part in parts) or "/" in uid or uid in {"", ".", ".."}:
            raise FilesError(MSG_FILE_GONE)
        return self.root.joinpath(uid, *parts)

    def _entry(self, uid: str, path: str) -> FilesEntry:
        local = self._local(uid, path)
        stat = local.stat()
        key = (uid, path)
        if key not in self._ids:
            self._next_id += 1
            self._ids[key] = self._next_id
        return FilesEntry(
            file_id=self._ids[key],
            path=path,
            name=local.name,
            size=stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, UTC),
        )

    async def upload(
        self, uid: str, folder_path: str, base_name: str, spool: BinaryIO, size: int, suffix: Callable[[str, int], str]
    ) -> FilesEntry:
        for n in range(1, MAX_SUFFIX + 1):
            target = f"{folder_path}/{suffix(base_name, n)}"
            if not self._local(uid, target).exists():
                break
        else:
            raise FilesError(MSG_NAME_EXHAUSTED)
        local = self._local(uid, target)
        local.parent.mkdir(parents=True, exist_ok=True)
        spool.seek(0)
        with local.open("wb") as out:
            shutil.copyfileobj(spool, out)
        if local.stat().st_size != size:
            local.unlink()
            raise FilesError(MSG_UPLOAD_INCOMPLETE)
        self.uploads.append((uid, target))
        return self._entry(uid, target)

    async def listdir(self, uid: str, folder_path: str) -> list[FilesEntry]:
        folder = self._local(uid, folder_path)
        if not folder.is_dir():
            return []
        children = sorted(child.name for child in folder.iterdir() if child.is_file())
        return [self._entry(uid, f"{folder_path}/{name}") for name in children]

    async def stat(self, uid: str, path: str) -> FilesEntry | None:
        local = self._local(uid, path)
        return self._entry(uid, path) if local.is_file() else None

    async def download_to(self, uid: str, path: str, fp: BinaryIO) -> None:
        local = self._local(uid, path)
        if not local.is_file():
            raise FilesError(MSG_FILE_GONE)
        with local.open("rb") as source:
            shutil.copyfileobj(source, fp)

    async def delete_own(self, uid: str, path: str) -> None:
        self._local(uid, path).unlink(missing_ok=True)

    # Nur für Tests

    def read_bytes(self, uid: str, path: str) -> bytes:
        return self._local(uid, path).read_bytes()

    def replace_bytes(self, uid: str, path: str, data: bytes) -> None:
        """Tauscht den Inhalt einer abgelegten Datei aus (Manipulation durch einen Verwalter in Files)."""
        local = self._local(uid, path)
        assert local.is_file(), "nur vorhandene Dateien tauschen"
        local.write_bytes(data)

    def put(self, uid: str, path: str, data: bytes) -> FilesEntry:
        """Legt eine Datei direkt ab (gefälschte Sicherung) und liefert ihren Eintrag."""
        local = self._local(uid, path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)
        return self._entry(uid, path)


# Unabhängige Prüfhelfer (eigener Docker-Client, sqlite3 nur lesend)


def copy_out(api: docker.DockerClient, container: str, path: str, dest_dir: Path) -> Path:
    """Holt ``path`` (Datei oder Ordner) über den eigenen Client aus dem Container nach ``dest_dir``.

    Rohes ``GET /containers/{id}/archive``, eigenes Entpacken mit dem
    data-Filter (keine Links nach außen, keine absoluten Pfade). Liefert den
    lokalen Pfad des Ziels (``dest_dir/<Basisname>``).
    """
    stream, _stat = api.api.get_archive(container, path)
    raw = b"".join(stream)
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
        tar.extractall(dest_dir, filter="data")
    return dest_dir / PurePosixPath(path).name


def put_files(api: docker.DockerClient, container: str, target_dir: str, files: dict[str, bytes]) -> None:
    """Legt Dateien über den eigenen Client in den Container (Zerstörung im Test)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.uid = info.gid = LUANTI_UID
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    assert api.api.put_archive(container, target_dir, buffer.getvalue()), "Docker nahm die Dateien nicht an"


def _read_only(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)


def players_in(players_sqlite: Path) -> set[str]:
    """Spielernamen aus players.sqlite (Tabelle ``player``), nur lesend."""
    connection = _read_only(players_sqlite)
    try:
        return {str(row[0]) for row in connection.execute("SELECT name FROM player")}
    finally:
        connection.close()


def integrity_ok(db: Path) -> bool:
    """PRAGMA integrity_check ergibt genau ``ok``; eine unlesbare Datei ergibt False."""
    try:
        connection = _read_only(db)
    except sqlite3.Error:
        return False
    try:
        rows = connection.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.DatabaseError:
        return False
    finally:
        connection.close()
    return rows == [("ok",)]


def block_count(map_sqlite: Path) -> int:
    """Anzahl gespeicherter Kartenblöcke (Tabelle ``blocks``), nur lesend."""
    connection = _read_only(map_sqlite)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM blocks").fetchone()[0])
    finally:
        connection.close()


def member_names(archive: bytes) -> list[str]:
    """Namen aller Einträge eines tar.gz."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        return tar.getnames()


def extract_member(archive: bytes, name: str, dest: Path) -> Path:
    """Eine reguläre Datei aus einem tar.gz nach ``dest`` schreiben (eigener Entpacker)."""
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        member = tar.getmember(name)
        assert member.isfile(), name
        handle = tar.extractfile(member)
        assert handle is not None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(handle.read())
    return dest


def manifest_of(archive: bytes) -> dict[str, object]:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        handle = tar.extractfile(MANIFEST)
        assert handle is not None
        return dict(json.loads(handle.read()))


# Tar-Fälscher für Negativtests


def minimal_map() -> bytes:
    """Kleine gültige SQLite-Datei mit Tabelle ``blocks`` (Luanti-Altschema), ein Block."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "map.sqlite"
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE blocks (pos INT PRIMARY KEY, data BLOB)")
            connection.execute("INSERT INTO blocks VALUES (0, x'00')")
            connection.commit()
        finally:
            connection.close()
        return path.read_bytes()


def _file(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.uid = info.gid = LUANTI_UID
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _other_preset(preset: str) -> str:
    return "voxelibre_sanft" if preset != "voxelibre_sanft" else "mtg_kreativ"


def forged_backup(kind: str, world_id: str, preset: str, *, map_bytes: bytes | None = None) -> bytes:
    """Eine manipulierte Sicherung als tar.gz, jeweils mit gültiger ``world/map.sqlite``.

    ``traversal``: Eintrag ``world/../x``; ``symlink``: Link ``world/link`` nach
    außen; ``lua``: Code in ``world/worldmods/x/init.lua``; ``foreign_preset``:
    Manifest mit anderer Spielart.
    """
    if kind not in FORGED_KINDS:
        msg = f"unbekannter Fälschungsfall: {kind}"
        raise ValueError(msg)
    manifest = {
        "format": 1,
        "world_id": world_id,
        "preset": _other_preset(preset) if kind == "foreign_preset" else preset,
        "luanti_version": "5.17.0",
        "created_at": datetime.now(UTC).isoformat(),
        "kind": "backup",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        _file(tar, MANIFEST, json.dumps(manifest, sort_keys=True).encode())
        root = tarfile.TarInfo(WORLD)
        root.type = tarfile.DIRTYPE
        root.mode = 0o755
        tar.addfile(root)
        _file(tar, f"{WORLD}/map.sqlite", map_bytes if map_bytes is not None else minimal_map())
        if kind == "traversal":
            _file(tar, f"{WORLD}/../x", b"draussen")
        elif kind == "symlink":
            link = tarfile.TarInfo(f"{WORLD}/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
        elif kind == "lua":
            _file(tar, f"{WORLD}/worldmods/x/init.lua", b'core.log("action", "fremder Code")\n')
    return buffer.getvalue()
