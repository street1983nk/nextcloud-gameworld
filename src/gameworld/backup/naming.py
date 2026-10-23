"""Ordner- und Dateinamen der Sicherungen in Nextcloud Files (D-01, D-02, D-05), rein und ohne I/O.

Weltnamen erlauben Punkte (``normalize_world_name``), ``..`` oder ``.`` würden
als Ordnername aus ``Gameworld/Sicherungen`` ausbrechen; Nextcloud mit
Windows-kompatiblen Dateinamen lehnt Punkt oder Leerzeichen am Ende und
reservierte Namen ab (Pitfall 4). Unbrauchbare Namen werden deshalb durch
``Welt-<id6>`` ersetzt. Die Zugehörigkeit einer Sicherung kommt nie aus dem
Ordnernamen, sondern aus dem DB-Eintrag. Die Haushalts-Zeitzone übergibt der
Aufrufer (TimeEngine.zone()).
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
# Alles außer Buchstaben, Ziffern, Leerzeichen, Punkt, Bindestrich und Unterstrich
# (Schrägstriche, Doppelpunkt, Steuerzeichen, Windows-Sonderzeichen) wird zu "-".
_DISALLOWED = re.compile(r"[^\w .\-]")
_WHITESPACE = re.compile(r"\s+")
_EDGES = " ."


def _clean(world_name: str) -> str | None:
    """Bereinigter Namensteil oder None, wenn er als Pfadteil unbrauchbar ist."""
    name = _DISALLOWED.sub("-", _WHITESPACE.sub(" ", world_name))
    name = name[:MAX_PART_LENGTH].strip(_EDGES)
    if not name or name.strip("-") == "":
        return None
    if name.split(".", 1)[0].strip().upper() in RESERVED_NAMES:
        return None
    return name


def folder_name(world_name: str, world_id: str) -> str:
    """Ordner der Welt unter BACKUPS_ROOT; nie leer, ``.``, ``..``, reserviert oder mit Schrägstrich."""
    return _clean(world_name) or f"{FALLBACK_PREFIX}{world_id[:6]}"


def folder_path(folder: str) -> str:
    return f"{BACKUPS_ROOT}/{folder}"


def backup_file_name(world_name: str, when: datetime, kind: str, *, zone: tzinfo | None = None) -> str:
    """``<weltname>-JJJJ-MM-TT-HHMM.tar.gz`` (D-02), bei ``vor-restore`` mit Zusatz (D-05).

    ``when`` muss eine Zeitzone tragen; ``zone`` rechnet den Zeitstempel in die
    Haushalts-Zeitzone um.
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
    """Kollisionsname: ``-2``, ``-3`` ... vor ``.tar.gz``; ``n`` 1 lässt den Namen unverändert (Pitfall 5)."""
    if n <= 1:
        return name
    if name.endswith(ARCHIVE_SUFFIX):
        return f"{name[: -len(ARCHIVE_SUFFIX)]}-{n}{ARCHIVE_SUFFIX}"
    return f"{name}-{n}"
