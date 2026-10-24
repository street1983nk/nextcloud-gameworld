"""Das Tar, das beim Erzeugen einer Welt in ihr Volume geschrieben wird.

Inhalt: ``minetest.conf`` (root-eigen, 0444, der Server kann sie lesen, aber
nicht umschreiben), die Welt-Metadaten, die Welt-Mods gameworld_status,
gameworld_access und gameworld_time, Zugangs- und Regeldatei (root-eigen, 0444)
und das Spiel des Presets. Das Zählbuch des Zeit-Mods steht nie im Tar: Es
gehört dem Mod und überlebt so jeden Neustart.

Rechte (AR-23, 06-07, gegen echtes Luanti belegt in
tests/e2e/test_world_dir_hardening_e2e.py): Der Weltordner gehört root mit
Gruppe 30000 und Modus 1775. Luanti legt darin eigene Dateien an und benennt
sie um (map.sqlite, env_meta.txt, Zählbuch per Temp-Datei), kann wegen des
Sticky-Bits aber root-eigene Dateien (Zugangs- und Regeldatei) weder löschen
noch umbenennen. ``worldmods`` mit allen Mods gehört root (Ordner 0755,
Dateien 0644), Luanti liest die Mods nur. Alles andere (world.mt, Spiel,
übrige Ordner) gehört dem Luanti-Nutzer 30000.

Dazu kommen drei kleine Tars relativ zum Weltordner: ``build_world_files``
(alle Mods, Zugangs- und Regeldatei, vor jedem Start), ``build_access_tar``
(nur die Zugangsdatei, bei Einladungsänderungen in die laufende Welt) und
``build_time_tar`` (nur die Regeldatei).

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


# Die Welt-Mods (Inhalt von init.lua und mod.conf), Verzeichnisse relativ zu /var/lib/minetest.
WORLD_MODS = world_mods("de")
ACCESS_FILE_MODE = 0o444
# AR-23: Weltordner root:30000 mit Sticky-Bit, root-eigene Ordner (worldmods) 0755.
WORLD_DIR_MODE = 0o1775
ROOT_DIR_MODE = 0o755
LUANTI_DIR_MODE = 0o755
FILE_MODE = 0o644


def _verified_zip(preset: Preset) -> pathlib.Path:
    """Pfad des Spiel-Zips, nur wenn der Hash zur Konstante im Preset passt."""
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
    """Normalisierter relativer Pfad oder None, wenn er aus dem Ziel ausbrechen würde.

    Öffentlich, weil auch die Restore-Prüfung (backup/archive.py) sie nutzt.
    """
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return None
    if ".." in name.split("/"):
        return None
    cleaned = normpath(name)
    if cleaned in (".", "") or cleaned.startswith("../"):
        return None
    return cleaned


# Alter Name, bestehende Aufrufer und Tests bleiben unverändert.
_safe_relative = safe_relative


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
    """Ordner, den Luanti nur liest (worldmods und die Mods darin)."""
    _add_dir(tar, name, uid=ROOT_UID, gid=ROOT_UID, mode=ROOT_DIR_MODE)


def _add_mod_files(tar: tarfile.TarFile, mod_dir: str, init_lua: str, mod_conf: str) -> None:
    """init.lua und mod.conf eines Welt-Mods, root-eigen und nur für root schreibbar."""
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
    """Zugangsdatei root-eigen und nur lesbar; aktuelle mtime, damit Docker sie sicher ersetzt."""
    _add_file(tar, name, access_file, uid=ROOT_UID, mode=ACCESS_FILE_MODE, mtime=int(time.time()))


def _relative_to_world(path: str) -> str:
    """Pfad unter dem Weltordner relativ zu ihm (``worldmods/...``)."""
    prefix = f"{WORLD_DIR}/"
    if not path.startswith(prefix):
        raise ValueError(f"Pfad liegt nicht im Weltordner: {path}")
    return path[len(prefix) :]


def build_world_files(access_file: bytes, time_file: bytes | None = None, *, language: str = "de") -> bytes:
    """Unkomprimiertes Tar für ``put_archive`` in den Weltordner: alle Mods, Zugangs- und Regeldatei.

    Läuft vor jedem Start (``_launch``): aktualisiert den Mod-Code nach
    App-Updates und rüstet Welten ohne Zugangs- oder Zeit-Mod nach. Alle Namen
    sind relativ zum Weltordner, ohne ``..`` und ohne absoluten Pfad.
    ``worldmods`` und die Mods darin sind root-eigen (AR-23); den Weltordner
    selbst setzt nur ``build_world_payload``, denn einen Eintrag für ``.``
    übergeht Docker beim Einspielen. Bestehende Welten behalten deshalb ihren
    Weltordner, bekommen aber beim nächsten Start ein root-eigenes worldmods.
    ``time_file`` None lässt die Regeldatei weg (nur für ältere Testaufrufe;
    ``_launch`` übergibt sie immer). ``language``: world language of the mod texts (D-27).
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
    """Tar mit genau der Zugangsdatei, relativ zum Weltordner (für laufende Welten)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        _add_access_file(tar, access_mod.ACCESS_FILE_NAME, access_file)
    return buffer.getvalue()


def build_time_tar(time_file: bytes) -> bytes:
    """Tar mit genau der Regeldatei, relativ zum Weltordner (für laufende Welten)."""
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
    """Unkomprimiertes Tar für ``put_archive`` nach ``/var/lib/minetest``.

    Der Aufrufer schließt ``archive`` nach ``put_archive`` (gibt die temporäre
    Datei frei). Die Spielerliste des Status-Mods steht nie im Payload: Der Mod legt
    die Datei erst beim Start an, sonst wäre die Bereitschaftsprüfung falsch. Das
    gilt auch für die State-Datei des Zugangs-Mods und das Zählbuch des
    Zeit-Mods. ``access_file`` ist die Zugangsdatei (bei neuen Welten: Kopf und
    Schlusszeile, niemand eingeladen), ``time_file`` die Regeldatei (None: keine).
    ``language``: world language of the mod texts (D-27).
    """
    mods = world_mods(language)
    game_root = f".minetest/games/{preset.game_dir}"
    zip_path = _verified_zip(preset)
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)  # noqa: SIM115
    try:
        with zipfile.ZipFile(zip_path) as zipped:
            game = _game_entries(zipped)
            # Luanti-eigene Ordner; Weltordner und worldmods kommen gesondert (AR-23).
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
                # world.mt bleibt Luanti: Im e2e-Lauf schreibt Luanti sie nicht neu (mtime bleibt 0),
                # müsste es aber (etwa beim Speichern geänderter Welteinstellungen), ginge das nur so.
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
