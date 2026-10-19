"""Das Tar, das beim Erzeugen einer Welt in ihr Volume geschrieben wird.

Inhalt: ``minetest.conf`` (root-eigen, 0444, der Server kann sie lesen, aber
nicht umschreiben), die Welt-Metadaten und das mitgelieferte Spiel. Alles außer
der conf gehört dem Luanti-Nutzer 30000.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import tarfile
import zipfile
from posixpath import normpath

from gameworld.provisioner.client import ProvisionerError

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GAME_ZIP = REPO_ROOT / "vendor" / "games" / "minetest_game-38214.zip"
GAME_ZIP_SHA256 = "5b364f6b0cf31ec336319492e14106d932eb86b65a91ded99f4b25f4876519dc"
GAME_ID = "minetest_game"

LUANTI_UID = 30000
ROOT_UID = 0
FIXED_MTIME = 0


def _load_game_zip() -> bytes:
    try:
        data = GAME_ZIP.read_bytes()
    except OSError as exc:
        raise ProvisionerError(f"Die mitgelieferte Spieldatei fehlt: {GAME_ZIP.name}.") from exc
    if hashlib.sha256(data).hexdigest() != GAME_ZIP_SHA256:
        raise ProvisionerError(
            f"Die mitgelieferte Spieldatei ist beschädigt oder verändert ({GAME_ZIP.name}). "
            "Bitte Gameworld neu installieren."
        )
    return data


def _safe_relative(name: str) -> str | None:
    """Normalisierter relativer Pfad oder None, wenn er aus dem Ziel ausbrechen würde."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return None
    if ".." in name.split("/"):
        return None
    cleaned = normpath(name)
    if cleaned in (".", "") or cleaned.startswith("../"):
        return None
    return cleaned


def _game_files(data: bytes) -> list[tuple[str, bytes]]:
    """Dateien des Spiels relativ zum Verzeichnis, das ``game.conf`` enthält."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries: list[tuple[str, zipfile.ZipInfo]] = []
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_relative(info.filename)
            if relative is not None:
                entries.append((relative, info))
        roots = sorted(
            (
                name.rsplit("/", 1)[0] + "/" if "/" in name else ""
                for name, _ in entries
                if name.split("/")[-1] == "game.conf"
            ),
            key=len,
        )
        if not roots:
            raise ProvisionerError("Die mitgelieferte Spieldatei enthält keine game.conf.")
        prefix = roots[0]
        return [
            (name[len(prefix) :], archive.read(info))
            for name, info in entries
            if name.startswith(prefix) and name[len(prefix) :]
        ]


def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.uid = info.gid = LUANTI_UID
    info.mode = 0o755
    info.mtime = FIXED_MTIME
    tar.addfile(info)


def _add_file(tar: tarfile.TarFile, name: str, data: bytes, *, uid: int = LUANTI_UID, mode: int = 0o644) -> None:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = uid
    info.mode = mode
    info.size = len(data)
    info.mtime = FIXED_MTIME
    tar.addfile(info, io.BytesIO(data))


def build_world_payload(minetest_conf: str, world_mt: str) -> bytes:
    """Unkomprimiertes Tar für ``put_archive`` nach ``/var/lib/minetest``."""
    game_root = f".minetest/games/{GAME_ID}"
    game = _game_files(_load_game_zip())

    directories = {".minetest", ".minetest/worlds", ".minetest/worlds/world", ".minetest/games", game_root}
    for name, _ in game:
        parts = name.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            directories.add(f"{game_root}/{'/'.join(parts[:depth])}")

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_file(tar, "minetest.conf", minetest_conf.encode("utf-8"), uid=ROOT_UID, mode=0o444)
        for directory in sorted(directories, key=lambda path: (path.count("/"), path)):
            _add_dir(tar, directory)
        _add_file(tar, ".minetest/worlds/world/world.mt", world_mt.encode("utf-8"))
        for name, data in sorted(game):
            _add_file(tar, f"{game_root}/{name}", data)
    return buffer.getvalue()
