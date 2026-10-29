"""Folder and file names of the backups in Nextcloud Files (D-01, D-02, D-05), pure and without I/O.

World names allow dots (``normalize_world_name``), ``..`` or ``.`` would break out
of ``Gameworld/Sicherungen`` as a folder name; Nextcloud with
Windows-compatible file names rejects a trailing dot or space and
reserved names (pitfall 4). Unusable names are therefore replaced by
``Welt-<id6>``. The affiliation of a backup never comes from the
folder name, but from the DB entry. The caller passes the household time zone
(TimeEngine.zone()).
"""

from __future__ import annotations

import re
from datetime import datetime, tzinfo

from gameworld.backup.archive import KIND_BACKUP, KIND_VOR_RESTORE

BACKUPS_ROOT = "Gameworld/Sicherungen"
FALLBACK_PREFIX = "Welt-"
FALLBACK_FILE_BASE = "Welt"
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


def folder_name(world_name: str, world_id: str) -> str:
    """Folder of the world under BACKUPS_ROOT; never empty, ``.``, ``..``, reserved or with a slash."""
    return _clean(world_name) or f"{FALLBACK_PREFIX}{world_id[:6]}"


def folder_path(folder: str) -> str:
    return f"{BACKUPS_ROOT}/{folder}"


def backup_file_name(world_name: str, when: datetime, kind: str, *, zone: tzinfo | None = None) -> str:
    """``<worldname>-YYYY-MM-DD-HHMM.tar.gz`` (D-02), with a suffix for ``vor-restore`` (D-05).

    ``when`` must carry a time zone; ``zone`` converts the timestamp into the
    household time zone.
    """
    if when.tzinfo is None:
        raise ValueError("Zeitpunkt ohne Zeitzone")
    if kind not in (KIND_BACKUP, KIND_VOR_RESTORE):
        raise ValueError(f"Unbekannte Art der Sicherung: {kind}")
    local = when.astimezone(zone) if zone is not None else when
    base = f"{_clean(world_name) or FALLBACK_FILE_BASE}-{local:%Y-%m-%d-%H%M}"
    if kind == KIND_VOR_RESTORE:
        base = f"{base}-{KIND_VOR_RESTORE}"
    return f"{base}{ARCHIVE_SUFFIX}"


def with_suffix(name: str, n: int) -> str:
    """Collision name: ``-2``, ``-3`` ... before ``.tar.gz``; ``n`` 1 leaves the name unchanged (pitfall 5)."""
    if n <= 1:
        return name
    if name.endswith(ARCHIVE_SUFFIX):
        return f"{name[: -len(ARCHIVE_SUFFIX)]}-{n}{ARCHIVE_SUFFIX}"
    return f"{name}-{n}"
