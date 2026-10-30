"""Folder and file names of the backups (D-01, D-02, D-05, pitfall 4/5, T-05-05)."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from gameworld.backup.naming import (
    BACKUPS_ROOT,
    all_folder_paths,
    backup_file_name,
    folder_name,
    folder_path,
    with_suffix,
    world_folder_path,
)

WORLD_ID = "a1b2c3d4e5f6"
FALLBACK = "Welt-a1b2c3"
BERLIN = ZoneInfo("Europe/Berlin")


def test_plain_name_is_kept() -> None:
    assert folder_name("Burg", WORLD_ID) == "Burg"
    assert folder_name("Burg der Kinder", WORLD_ID) == "Burg der Kinder"


@pytest.mark.parametrize("name", ["..", ".", "", " . ", "...", "   ", " .. "])
def test_dot_and_empty_names_fall_back(name: str) -> None:
    assert folder_name(name, WORLD_ID) == FALLBACK


def test_trailing_dots_and_spaces_are_removed() -> None:
    assert folder_name("Burg. ", WORLD_ID) == "Burg"
    assert folder_name(" .Burg", WORLD_ID) == "Burg"


@pytest.mark.parametrize("name", ["CON", "nul", "COM1", "LPT9", "Prn", "aux", "con.txt", "COM9 "])
def test_reserved_names_fall_back(name: str) -> None:
    assert folder_name(name, WORLD_ID) == FALLBACK


def test_reserved_prefix_is_not_reserved() -> None:
    assert folder_name("Console", WORLD_ID) == "Console"


@pytest.mark.parametrize("name", ["a/b", "a\\b", "../x", "/", "\\", "a:b", 'x*?|<>"'])
def test_never_a_separator(name: str) -> None:
    result = folder_name(name, WORLD_ID)
    assert "/" not in result
    assert "\\" not in result
    assert result not in ("", ".", "..")


def test_folder_path() -> None:
    assert BACKUPS_ROOT == "Gameworld/Sicherungen"
    assert folder_path("Burg") == "Gameworld/Sicherungen/Burg"


def test_backup_file_name() -> None:
    when = datetime(2026, 10, 23, 14, 5, tzinfo=BERLIN)
    assert backup_file_name("Burg", when, "backup") == "Burg-2026-10-23-1405.tar.gz"


def test_vor_restore_file_name() -> None:
    when = datetime(2026, 10, 23, 14, 5, tzinfo=BERLIN)
    assert backup_file_name("Burg", when, "vor-restore") == "Burg-2026-10-23-1405-vor-restore.tar.gz"


def test_file_name_uses_given_zone() -> None:
    when = datetime(2026, 10, 23, 12, 5, tzinfo=UTC)
    assert backup_file_name("Burg", when, "backup", zone=BERLIN) == "Burg-2026-10-23-1405.tar.gz"


def test_file_name_keeps_spaces_and_cleans_edges() -> None:
    when = datetime(2026, 1, 2, 3, 4, tzinfo=BERLIN)
    assert backup_file_name("Burg der Kinder. ", when, "backup") == "Burg der Kinder-2026-01-02-0304.tar.gz"


def test_file_name_of_unusable_world_name() -> None:
    when = datetime(2026, 1, 2, 3, 4, tzinfo=BERLIN)
    assert backup_file_name("..", when, "backup") == "Welt-2026-01-02-0304.tar.gz"
    assert "/" not in backup_file_name("a/b", when, "backup")


def test_file_name_rejects_naive_time_and_unknown_kind() -> None:
    with pytest.raises(ValueError, match="ohne Zeitzone"):
        backup_file_name("Burg", datetime(2026, 1, 2, 3, 4), "backup", zone=BERLIN)
    with pytest.raises(ValueError, match="Unbekannte Art"):
        backup_file_name("Burg", datetime(2026, 1, 2, 3, 4, tzinfo=BERLIN), "irgendwas")


def test_with_suffix() -> None:
    assert with_suffix("Burg-2026-10-23-1405.tar.gz", 1) == "Burg-2026-10-23-1405.tar.gz"
    assert with_suffix("Burg-2026-10-23-1405.tar.gz", 2) == "Burg-2026-10-23-1405-2.tar.gz"
    assert with_suffix("Burg-2026-10-23-1405-vor-restore.tar.gz", 3) == "Burg-2026-10-23-1405-vor-restore-3.tar.gz"


# --- Names in the account language (owner decision 30.10.2026) -----------------------------


@pytest.mark.parametrize(
    ("language", "root", "suffix", "fallback"),
    [
        ("de", "Gameworld/Sicherungen", "vor-restore", "Welt"),
        ("en", "Gameworld/Backups", "before-restore", "World"),
        ("fr", "Gameworld/Sauvegardes", "avant-restauration", "Monde"),
    ],
)
def test_names_follow_the_language(language: str, root: str, suffix: str, fallback: str) -> None:
    when = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
    assert world_folder_path("Burg", WORLD_ID, language) == f"{root}/Burg"
    assert world_folder_path("..", WORLD_ID, language) == f"{root}/{fallback}-a1b2c3"
    assert backup_file_name("Burg", when, "vor-restore", zone=BERLIN, language=language) == (
        f"Burg-2026-10-23-1400-{suffix}.tar.gz"
    )
    assert backup_file_name("..", when, "backup", zone=BERLIN, language=language) == (
        f"{fallback}-2026-10-23-1400.tar.gz"
    )


def test_unknown_language_and_default_stay_german() -> None:
    assert world_folder_path("Burg", WORLD_ID, "es") == "Gameworld/Sicherungen/Burg"
    assert world_folder_path("Burg", WORLD_ID) == "Gameworld/Sicherungen/Burg"
    assert folder_path("Burg", "en") == "Gameworld/Backups/Burg"


def test_all_folder_paths_name_every_language_once() -> None:
    assert all_folder_paths("Burg", WORLD_ID) == [
        "Gameworld/Sicherungen/Burg",
        "Gameworld/Backups/Burg",
        "Gameworld/Sauvegardes/Burg",
    ]
    # Fallback names differ per language, still one folder per language.
    assert all_folder_paths("..", WORLD_ID) == [
        "Gameworld/Sicherungen/Welt-a1b2c3",
        "Gameworld/Backups/World-a1b2c3",
        "Gameworld/Sauvegardes/Monde-a1b2c3",
    ]
