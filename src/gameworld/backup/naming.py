"""Folder and file names of the backups in Nextcloud Files (D-01, D-02, D-05), pure and without I/O.

World names allow dots (``normalize_world_name``), ``..`` or ``.`` would break out
of ``Gameworld/Sicherungen`` as a folder name; Nextcloud with
Windows-compatible file names rejects a trailing dot or space and
reserved names (pitfall 4). Unusable names are therefore replaced by
``Welt-<id6>``. The affiliation of a backup never comes from the
folder name, but from the DB entry. The caller passes the household time zone
(TimeEngine.zone()).

Folder, fallback names and the suffix of the safety backup follow the account
language of the manager in whose files the backup lands (de, en, fr). After a
language change, older backups stay in the folder of the previous language;
``all_folder_paths`` therefore names the folder of a world in every language.
"""

from __future__ import annotations

import re
from datetime import datetime, tzinfo

from gameworld.backup.archive import KIND_BACKUP, KIND_VOR_RESTORE

# Language-dependent names; German is the source and the default.
BACKUPS_ROOTS = {"de": "Gameworld/Sicherungen", "en": "Gameworld/Backups", "fr": "Gameworld/Sauvegardes"}
FALLBACK_FILE_BASES = {"de": "Welt", "en": "World", "fr": "Monde"}
PRE_RESTORE_SUFFIXES = {"de": "vor-restore", "en": "before-restore", "fr": "avant-restauration"}
NAME_LANGUAGES = tuple(BACKUPS_ROOTS)
DEFAULT_NAME_LANGUAGE = "de"
BACKUPS_ROOT = BACKUPS_ROOTS[DEFAULT_NAME_LANGUAGE]
ARCHIVE_SUFFIX = ".tar.gz"
MAX_PART_LENGTH = 64
RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}
)
# Everything except letters, digits, space, dot, hyphen and underscore
# (slashes, colon, control characters, Windows special characters) becomes "-".
_DISALLOWED = re.compile(r"[^\w .\-]")
_WHITESPACE = re.compile(r"\s+")
_EDGES = " ."


def _clean(world_name: str) -> str | None:
    """Cleaned name part or None if it is unusable as a path part."""
    name = _DISALLOWED.sub("-", _WHITESPACE.sub(" ", world_name))
    name = name[:MAX_PART_LENGTH].strip(_EDGES)
    if not name or name.strip("-") == "":
        return None
    if name.split(".", 1)[0].strip().upper() in RESERVED_NAMES:
        return None
    return name


def _name_language(language: str) -> str:
    return language if language in BACKUPS_ROOTS else DEFAULT_NAME_LANGUAGE


def folder_name(world_name: str, world_id: str, language: str = DEFAULT_NAME_LANGUAGE) -> str:
    """Folder of the world under the backups root; never empty, ``.``, ``..``, reserved or with a slash."""
    return _clean(world_name) or f"{FALLBACK_FILE_BASES[_name_language(language)]}-{world_id[:6]}"


def folder_path(folder: str, language: str = DEFAULT_NAME_LANGUAGE) -> str:
    return f"{BACKUPS_ROOTS[_name_language(language)]}/{folder}"


def world_folder_path(world_name: str, world_id: str, language: str = DEFAULT_NAME_LANGUAGE) -> str:
    """Folder for new backups of a world in ``language``."""
    return folder_path(folder_name(world_name, world_id, language), language)


def all_folder_paths(world_name: str, world_id: str) -> list[str]:
    """Folder of the world in every language, without duplicates (listing and restore search all)."""
    paths = [world_folder_path(world_name, world_id, language) for language in NAME_LANGUAGES]
    return list(dict.fromkeys(paths))


def backup_file_name(
    world_name: str,
    when: datetime,
    kind: str,
    *,
    zone: tzinfo | None = None,
    language: str = DEFAULT_NAME_LANGUAGE,
) -> str:
    """``<worldname>-YYYY-MM-DD-HHMM.tar.gz`` (D-02), with a suffix for ``vor-restore`` (D-05).

    ``when`` must carry a time zone; ``zone`` converts the timestamp into the
    household time zone.
    """
    if when.tzinfo is None:
        raise ValueError("Zeitpunkt ohne Zeitzone")
    if kind not in (KIND_BACKUP, KIND_VOR_RESTORE):
        raise ValueError(f"Unbekannte Art der Sicherung: {kind}")
    local = when.astimezone(zone) if zone is not None else when
    name_language = _name_language(language)
    base = f"{_clean(world_name) or FALLBACK_FILE_BASES[name_language]}-{local:%Y-%m-%d-%H%M}"
    if kind == KIND_VOR_RESTORE:
        base = f"{base}-{PRE_RESTORE_SUFFIXES[name_language]}"
    return f"{base}{ARCHIVE_SUFFIX}"


def with_suffix(name: str, n: int) -> str:
    """Collision name: ``-2``, ``-3`` ... before ``.tar.gz``; ``n`` 1 leaves the name unchanged (pitfall 5)."""
    if n <= 1:
        return name
    if name.endswith(ARCHIVE_SUFFIX):
        return f"{name[: -len(ARCHIVE_SUFFIX)]}-{n}{ARCHIVE_SUFFIX}"
    return f"{name}-{n}"
