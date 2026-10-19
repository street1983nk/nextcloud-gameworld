"""Das Tar, das beim Erzeugen einer Welt in ihr Volume geschrieben wird.

Inhalt: ``minetest.conf`` (root-eigen, 0444, der Server kann sie lesen, aber
nicht umschreiben), die Welt-Metadaten, der Welt-Mod gameworld_status und das
Spiel des Presets. Alles außer der conf gehört dem Luanti-Nutzer 30000.

Das Spiel-Zip wird vor jeder Nutzung per SHA256 gegen die Konstante im Preset
geprüft. Die Spieldateien werden einzeln ins Tar gestreamt, das Tar liegt bis
8 MiB im Speicher und darüber in einer temporären Datei: VoxeLibre (84 MB Zip,
rund 110 MB Tar) soll den ExApp-Prozess nicht um 200 MB anwachsen lassen.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import tarfile
import tempfile
import zipfile
from posixpath import normpath
from typing import BinaryIO, cast

from gameworld.provisioner.client import ProvisionerError
from gameworld.provisioner.presets import Preset
from gameworld.provisioner.spec import WorldPayload
from gameworld.provisioner.status_mod import MOD_CONF, MOD_DIR, MOD_INIT_LUA

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GAMES_DIR = REPO_ROOT / "vendor" / "games"

LUANTI_UID = 30000
ROOT_UID = 0
FIXED_MTIME = 0
SPOOL_MAX_BYTES = 8 * 1024 * 1024
WORLD_DIR = ".minetest/worlds/world"


def _verified_zip(preset: Preset) -> pathlib.Path:
    """Pfad des Spiel-Zips, nur wenn der Hash zur Konstante im Preset passt."""
    path = GAMES_DIR / preset.game_zip
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise ProvisionerError(
            f"Die mitgelieferte Spieldatei fehlt: {preset.game_zip}. Bitte sh scripts/fetch-games.sh ausführen."
        ) from exc
    if digest != preset.game_sha256:
        raise ProvisionerError(
            f"Die mitgelieferte Spieldatei ist beschädigt oder verändert ({preset.game_zip}). "
            "Bitte Gameworld neu installieren."
        )
    return path


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


def _game_entries(zipped: zipfile.ZipFile) -> list[tuple[str, zipfile.ZipInfo]]:
    """Dateien des Spiels relativ zum Verzeichnis, das ``game.conf`` enthält (ohne Inhalt)."""
    entries: list[tuple[str, zipfile.ZipInfo]] = []
    for info in zipped.infolist():
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
    game = [(name[len(prefix) :], info) for name, info in entries if name.startswith(prefix) and name[len(prefix) :]]
    return sorted(game, key=lambda entry: entry[0])


def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.uid = info.gid = LUANTI_UID
    info.mode = 0o755
    info.mtime = FIXED_MTIME
    tar.addfile(info)


def _file_info(name: str, size: int, *, uid: int, mode: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = uid
    info.mode = mode
    info.size = size
    info.mtime = FIXED_MTIME
    return info


def _add_file(tar: tarfile.TarFile, name: str, data: bytes, *, uid: int = LUANTI_UID, mode: int = 0o644) -> None:
    tar.addfile(_file_info(name, len(data), uid=uid, mode=mode), io.BytesIO(data))


def build_world_payload(preset: Preset, minetest_conf: str, world_mt: str) -> WorldPayload:
    """Unkomprimiertes Tar für ``put_archive`` nach ``/var/lib/minetest``.

    Der Aufrufer schließt ``archive`` nach ``put_archive`` (gibt die temporäre
    Datei frei). Die Spielerliste des Status-Mods steht nie im Payload: Der Mod legt
    die Datei erst beim Start an, sonst wäre die Bereitschaftsprüfung falsch.
    """
    game_root = f".minetest/games/{preset.game_dir}"
    zip_path = _verified_zip(preset)
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)  # noqa: SIM115
    try:
        with zipfile.ZipFile(zip_path) as zipped:
            game = _game_entries(zipped)
            directories = {
                ".minetest",
                ".minetest/worlds",
                WORLD_DIR,
                f"{WORLD_DIR}/worldmods",
                MOD_DIR,
                ".minetest/games",
                game_root,
            }
            for name, _ in game:
                parts = name.split("/")[:-1]
                for depth in range(1, len(parts) + 1):
                    directories.add(f"{game_root}/{'/'.join(parts[:depth])}")

            with tarfile.open(fileobj=cast(BinaryIO, spool), mode="w", format=tarfile.PAX_FORMAT) as tar:
                _add_file(tar, "minetest.conf", minetest_conf.encode("utf-8"), uid=ROOT_UID, mode=0o444)
                for directory in sorted(directories, key=lambda path: (path.count("/"), path)):
                    _add_dir(tar, directory)
                _add_file(tar, f"{WORLD_DIR}/world.mt", world_mt.encode("utf-8"))
                _add_file(tar, f"{MOD_DIR}/init.lua", MOD_INIT_LUA.encode("utf-8"))
                _add_file(tar, f"{MOD_DIR}/mod.conf", MOD_CONF.encode("utf-8"))
                for name, info in game:
                    with zipped.open(info) as source:
                        member = _file_info(f"{game_root}/{name}", info.file_size, uid=LUANTI_UID, mode=0o644)
                        tar.addfile(member, source)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return WorldPayload(preset, cast(BinaryIO, spool))
