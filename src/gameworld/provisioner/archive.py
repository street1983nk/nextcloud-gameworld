"""The tar that is written into the volume of a world when it is created.

Contents: ``minetest.conf`` (root-owned, 0444, the server can read it but
not rewrite it), the world metadata, the world mods gameworld_status,
gameworld_access and gameworld_time, access and rule file (root-owned, 0444)
and the game of the preset. The ledger of the time mod is never in the tar: it
belongs to the mod and thus survives every restart.

Permissions (AR-23, 06-07, proven against real Luanti in
tests/e2e/test_world_dir_hardening_e2e.py): the world folder belongs to root with
group 30000 and mode 1775. Luanti creates its own files in it and renames
them (map.sqlite, env_meta.txt, ledger via temp file), but because of the
sticky bit it can neither delete nor rename root-owned files (access and
rule file). ``worldmods`` with all mods belongs to root (folders 0755,
files 0644), Luanti only reads the mods. Everything else (world.mt, game,
other folders) belongs to the Luanti user 30000.

In addition there are three small tars relative to the world folder: ``build_world_files``
(all mods, access and rule file, before every start), ``build_access_tar``
(only the access file, on invitation changes into the running world) and
``build_time_tar`` (only the rule file).

The game zip is checked by SHA256 against the constant in the preset before every use.
The game files are streamed into the tar one by one, the tar stays in memory up to
8 MiB and above that in a temporary file: VoxeLibre (84 MB zip,
about 110 MB tar) should not make the ExApp process grow by 200 MB.
"""

from __future__ import annotations

import hashlib
import io
import pathlib
import tarfile
import tempfile
import time
import zipfile
from posixpath import normpath
from typing import BinaryIO, cast

from gameworld.provisioner import access_mod, status_mod, time_mod
from gameworld.provisioner.client import ProvisionerError
from gameworld.provisioner.presets import Preset
from gameworld.provisioner.spec import WorldPayload

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
GAMES_DIR = REPO_ROOT / "vendor" / "games"
# Game zip problems reach the client via str(exc) (D-25); the file name is inserted, never translated.
TEXT_GAME_ZIP_MISSING = "Die mitgelieferte Spieldatei fehlt: {game_zip}. Bitte sh scripts/fetch-games.sh ausführen."
TEXT_GAME_ZIP_TAMPERED = (
    "Die mitgelieferte Spieldatei ist beschädigt oder verändert ({game_zip}). Bitte Gameworld neu installieren."
)
MSG_NO_GAME_CONF = "Die mitgelieferte Spieldatei enthält keine game.conf."

LUANTI_UID = 30000
ROOT_UID = 0
FIXED_MTIME = 0
SPOOL_MAX_BYTES = 8 * 1024 * 1024
WORLD_DIR = ".minetest/worlds/world"


def world_mods(language: str = "de") -> tuple[tuple[str, str, str], ...]:
    """The world mods (directory relative to /var/lib/minetest, init.lua, mod.conf).

    ``language`` is the world language (D-27): only the text literals of the access
    and time mod change, the status mod has no texts. Unsupported values give German.
    """
    return (
        (status_mod.MOD_DIR, status_mod.MOD_INIT_LUA, status_mod.MOD_CONF),
        (access_mod.MOD_DIR, access_mod.mod_init_lua(language), access_mod.MOD_CONF),
        (time_mod.MOD_DIR, time_mod.mod_init_lua(language), time_mod.MOD_CONF),
    )


# The world mods (content of init.lua and mod.conf), directories relative to /var/lib/minetest.
WORLD_MODS = world_mods("de")
ACCESS_FILE_MODE = 0o444
# AR-23: world folder root:30000 with sticky bit, root-owned folders (worldmods) 0755.
WORLD_DIR_MODE = 0o1775
ROOT_DIR_MODE = 0o755
LUANTI_DIR_MODE = 0o755
FILE_MODE = 0o644


def _verified_zip(preset: Preset) -> pathlib.Path:
    """Path of the game zip, only if the hash matches the constant in the preset."""
    path = GAMES_DIR / preset.game_zip
    try:
        with path.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise ProvisionerError(TEXT_GAME_ZIP_MISSING.format(game_zip=preset.game_zip)) from exc
    if digest != preset.game_sha256:
        raise ProvisionerError(TEXT_GAME_ZIP_TAMPERED.format(game_zip=preset.game_zip))
    return path


def safe_relative(name: str) -> str | None:
    """Normalized relative path or None if it would escape from the target.

    Public because the restore check (backup/archive.py) uses it too.
    """
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return None
    if ".." in name.split("/"):
        return None
    cleaned = normpath(name)
    if cleaned in (".", "") or cleaned.startswith("../"):
        return None
    return cleaned


# Old name, existing callers and tests stay unchanged.
_safe_relative = safe_relative


def _game_entries(zipped: zipfile.ZipFile) -> list[tuple[str, zipfile.ZipInfo]]:
    """Files of the game relative to the directory containing ``game.conf`` (without content)."""
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
        raise ProvisionerError(MSG_NO_GAME_CONF)
    prefix = roots[0]
    game = [(name[len(prefix) :], info) for name, info in entries if name.startswith(prefix) and name[len(prefix) :]]
    return sorted(game, key=lambda entry: entry[0])


def _add_dir(
    tar: tarfile.TarFile, name: str, *, uid: int = LUANTI_UID, gid: int = LUANTI_UID, mode: int = LUANTI_DIR_MODE
) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.uid = uid
    info.gid = gid
    info.mode = mode
    info.mtime = FIXED_MTIME
    tar.addfile(info)


def _add_root_dir(tar: tarfile.TarFile, name: str) -> None:
    """Folder that Luanti only reads (worldmods and the mods in it)."""
    _add_dir(tar, name, uid=ROOT_UID, gid=ROOT_UID, mode=ROOT_DIR_MODE)


def _add_mod_files(tar: tarfile.TarFile, mod_dir: str, init_lua: str, mod_conf: str) -> None:
    """init.lua and mod.conf of a world mod, root-owned and writable only for root."""
    _add_file(tar, f"{mod_dir}/init.lua", init_lua.encode("utf-8"), uid=ROOT_UID, mode=FILE_MODE)
    _add_file(tar, f"{mod_dir}/mod.conf", mod_conf.encode("utf-8"), uid=ROOT_UID, mode=FILE_MODE)


def _file_info(name: str, size: int, *, uid: int, mode: int, mtime: int = FIXED_MTIME) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = uid
    info.mode = mode
    info.size = size
    info.mtime = mtime
    return info


def _add_file(
    tar: tarfile.TarFile,
    name: str,
    data: bytes,
    *,
    uid: int = LUANTI_UID,
    mode: int = FILE_MODE,
    mtime: int = FIXED_MTIME,
) -> None:
    tar.addfile(_file_info(name, len(data), uid=uid, mode=mode, mtime=mtime), io.BytesIO(data))


def _add_access_file(tar: tarfile.TarFile, name: str, access_file: bytes) -> None:
    """Access file root-owned and read-only; current mtime, so that Docker replaces it reliably."""
    _add_file(tar, name, access_file, uid=ROOT_UID, mode=ACCESS_FILE_MODE, mtime=int(time.time()))


def _relative_to_world(path: str) -> str:
    """Path under the world folder relative to it (``worldmods/...``)."""
    prefix = f"{WORLD_DIR}/"
    if not path.startswith(prefix):
        raise ValueError(f"Pfad liegt nicht im Weltordner: {path}")
    return path[len(prefix) :]


def build_world_files(access_file: bytes, time_file: bytes | None = None, *, language: str = "de") -> bytes:
    """Uncompressed tar for ``put_archive`` into the world folder: all mods, access and rule file.

    Runs before every start (``_launch``): updates the mod code after
    app updates and retrofits worlds without an access or time mod. All names
    are relative to the world folder, without ``..`` and without an absolute path.
    ``worldmods`` and the mods in it are root-owned (AR-23); the world folder
    itself is set only by ``build_world_payload``, because Docker ignores an
    entry for ``.`` when installing. Existing worlds therefore keep their
    world folder, but get a root-owned worldmods at the next start.
    ``time_file`` None omits the rule file (only for older test calls;
    ``_launch`` always passes it). ``language``: world language of the mod texts (D-27).
    """
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_root_dir(tar, "worldmods")
        for mod_dir, init_lua, mod_conf in world_mods(language):
            relative = _relative_to_world(mod_dir)
            _add_root_dir(tar, relative)
            _add_mod_files(tar, relative, init_lua, mod_conf)
        _add_access_file(tar, access_mod.ACCESS_FILE_NAME, access_file)
        if time_file is not None:
            _add_access_file(tar, time_mod.RULES_FILE_NAME, time_file)
    return buffer.getvalue()


def build_access_tar(access_file: bytes) -> bytes:
    """Tar with exactly the access file, relative to the world folder (for running worlds)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_access_file(tar, access_mod.ACCESS_FILE_NAME, access_file)
    return buffer.getvalue()


def build_time_tar(time_file: bytes) -> bytes:
    """Tar with exactly the rule file, relative to the world folder (for running worlds)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_access_file(tar, time_mod.RULES_FILE_NAME, time_file)
    return buffer.getvalue()


def build_world_payload(
    preset: Preset,
    minetest_conf: str,
    world_mt: str,
    access_file: bytes,
    time_file: bytes | None = None,
    *,
    language: str = "de",
) -> WorldPayload:
    """Uncompressed tar for ``put_archive`` to ``/var/lib/minetest``.

    The caller closes ``archive`` after ``put_archive`` (releases the temporary
    file). The player list of the status mod is never in the payload: the mod creates
    the file only at start, otherwise the readiness check would be wrong. The
    same holds for the state file of the access mod and the ledger of the
    time mod. ``access_file`` is the access file (for new worlds: head and
    closing line, nobody invited), ``time_file`` the rule file (None: none).
    ``language``: world language of the mod texts (D-27).
    """
    mods = world_mods(language)
    game_root = f".minetest/games/{preset.game_dir}"
    zip_path = _verified_zip(preset)
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)  # noqa: SIM115
    try:
        with zipfile.ZipFile(zip_path) as zipped:
            game = _game_entries(zipped)
            # Luanti's own folders; world folder and worldmods come separately (AR-23).
            root_dirs = [f"{WORLD_DIR}/worldmods", *(mod_dir for mod_dir, _, _ in mods)]
            directories = {".minetest", ".minetest/worlds", ".minetest/games", game_root}
            for name, _ in game:
                parts = name.split("/")[:-1]
                for depth in range(1, len(parts) + 1):
                    directories.add(f"{game_root}/{'/'.join(parts[:depth])}")

            with tarfile.open(fileobj=cast(BinaryIO, spool), mode="w", format=tarfile.PAX_FORMAT) as tar:
                _add_file(tar, "minetest.conf", minetest_conf.encode("utf-8"), uid=ROOT_UID, mode=0o444)
                for directory in sorted(directories, key=lambda path: (path.count("/"), path)):
                    _add_dir(tar, directory)
                _add_dir(tar, WORLD_DIR, uid=ROOT_UID, gid=LUANTI_UID, mode=WORLD_DIR_MODE)
                for directory in root_dirs:
                    _add_root_dir(tar, directory)
                # world.mt stays with Luanti: in the e2e run Luanti does not rewrite it (mtime stays 0),
                # but it would have to (e.g. when saving changed world settings), that only works this way.
                _add_file(tar, f"{WORLD_DIR}/world.mt", world_mt.encode("utf-8"))
                for mod_dir, init_lua, mod_conf in mods:
                    _add_mod_files(tar, mod_dir, init_lua, mod_conf)
                _add_access_file(tar, f"{WORLD_DIR}/{access_mod.ACCESS_FILE_NAME}", access_file)
                if time_file is not None:
                    _add_access_file(tar, f"{WORLD_DIR}/{time_mod.RULES_FILE_NAME}", time_file)
                for name, info in game:
                    with zipped.open(info) as source:
                        member = _file_info(f"{game_root}/{name}", info.file_size, uid=LUANTI_UID, mode=FILE_MODE)
                        tar.addfile(member, source)
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return WorldPayload(preset, cast(BinaryIO, spool))
