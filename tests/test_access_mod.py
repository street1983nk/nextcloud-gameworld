"""Welt-Mod gameworld_access und Zugangsdatei (03-RESEARCH.md Pattern 1 und 3)."""

from __future__ import annotations

import pytest

from gameworld.provisioner import access_mod
from gameworld.provisioner.access_mod import (
    ACCESS_FILE,
    ACCESS_FILE_NAME,
    MOD_CONF,
    MOD_DIR,
    MOD_INIT_LUA,
    MOD_NAME,
    STATE_FILE,
    STATE_FILE_NAME,
    render_access_file,
)
from gameworld.provisioner.luanti_auth import make_verifier

SALT = bytes(range(16))
MIA = make_verifier("Mia", "Sonne-Baum-42", SALT)
LEO = make_verifier("Leo", "Tiger-Wolke-17", SALT)


def test_empty_access_file_has_header_and_end() -> None:
    assert render_access_file(0, {}) == b"gameworld-access 1 0\nend\n"


def test_entries_sorted_ascii_and_deterministic() -> None:
    first = render_access_file(7, {"Mia": MIA, "Leo": LEO})
    second = render_access_file(7, {"Leo": LEO, "Mia": MIA})
    assert first == second
    text = first.decode("ascii")
    lines = text.split("\n")
    assert lines[0] == "gameworld-access 1 7"
    assert lines[1] == f"Leo {LEO}"
    assert lines[2] == f"Mia {MIA}"
    assert text.endswith("end\n")


@pytest.mark.parametrize(
    "name",
    ["Mia Leo", "Mia\nLeo", "a" * 21, "Mäx", "", "Mia\r"],
)
def test_invalid_name_raises(name: str) -> None:
    with pytest.raises(ValueError, match="Zugangseintrag"):
        render_access_file(1, {name: MIA})


@pytest.mark.parametrize(
    "verifier",
    ["", "geheim", "#2#abc#def", "#1#abc", f"{MIA}\nFremder {MIA}", f"{MIA} x"],
)
def test_invalid_verifier_raises(verifier: str) -> None:
    with pytest.raises(ValueError, match="Zugangseintrag"):
        render_access_file(1, {"Mia": verifier})


def test_negative_generation_raises() -> None:
    with pytest.raises(ValueError, match="Generation"):
        render_access_file(-1, {})


def test_twenty_character_name_is_allowed() -> None:
    assert b"a" * 20 in render_access_file(1, {"a" * 20: MIA})


def test_lua_contains_enforcement_points() -> None:
    for needle in (
        "register_on_prejoinplayer",
        "set_player_password",
        "register_on_authplayer",
        "kick_player",
        "safe_file_write",
        "^gameworld%-access 1 (%d+)$",
    ):
        assert needle in MOD_INIT_LUA


@pytest.mark.parametrize("forbidden", ["http", "io.popen", "os.execute", "require"])
def test_lua_has_no_dangerous_calls(forbidden: str) -> None:
    assert forbidden not in MOD_INIT_LUA


def test_lua_texts_and_limits() -> None:
    assert "Du bist in diese Welt nicht eingeladen. Frag deine Eltern." in MOD_INIT_LUA
    assert "Deine Einladung für diese Welt wurde beendet." in MOD_INIT_LUA
    assert "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen." in MOD_INIT_LUA
    assert "Achte auf Groß- und Kleinschreibung: " in MOD_INIT_LUA
    assert "local FAIL_LIMIT = 5" in MOD_INIT_LUA
    assert "local LOCK_SECONDS = 600" in MOD_INIT_LUA
    # Keine IP-Adressen und kein Debug-Log aus dem Spike.
    assert "gameworld_spike" not in MOD_INIT_LUA
    assert "check_password_entry" not in MOD_INIT_LUA


def test_lua_is_ascii_safe_outside_texts() -> None:
    # Gedankenstriche sind verboten (Owner-Regel).
    assert "–" not in MOD_INIT_LUA
    assert "—" not in MOD_INIT_LUA


def test_paths_and_conf() -> None:
    assert MOD_NAME == "gameworld_access"
    assert MOD_DIR == ".minetest/worlds/world/worldmods/gameworld_access"
    assert ACCESS_FILE_NAME == "gameworld_access.txt"
    assert STATE_FILE_NAME == "gameworld_access_state.txt"
    assert ACCESS_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_access.txt"
    assert STATE_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_access_state.txt"
    assert f"name = {MOD_NAME}" in MOD_CONF
    assert access_mod.ACCESS_HEADER == "gameworld-access 1"
