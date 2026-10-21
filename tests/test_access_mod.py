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
    ["Mia Leo", "Mia\nLeo", "a" * 21, "M" + chr(0xE4) + "x", "", "Mia\r"],
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
        "disconnect_player",
        "register_on_leaveplayer",
        "get_player_by_name",
        "local COOLDOWN = 2",
        "safe_file_write",
        "^gameworld%-access 1 (%d+)$",
    ):
        assert needle in MOD_INIT_LUA


def test_revocation_uses_disconnect_without_kicked_prefix() -> None:
    # kick_player stellt "Kicked: " vor den Kindertext (04-RESEARCH.md State of the Art).
    assert "kick_player" not in MOD_INIT_LUA
    assert "core.disconnect_player(name, KICK)" in MOD_INIT_LUA


def test_rejoin_guard_text_and_order() -> None:
    assert access_mod.TEXT_WAIT == "Bitte einen Moment warten und dann nochmal beitreten."
    assert f"local WAIT = {access_mod._lua_string(access_mod.TEXT_WAIT)}" in MOD_INIT_LUA
    # Nicht Eingeladene bekommen nie den Wartetext: Die Sperre steht nach der
    # Einladungsprüfung und vor set_player_password.
    deny = MOD_INIT_LUA.index("return DENY")
    wait = MOD_INIT_LUA.index("return WAIT")
    password = MOD_INIT_LUA.index("core.set_player_password(name, hash)")
    assert deny < wait < password
    # Alte Einträge werden beim Prüfen gelöscht (kein Wachstum).
    assert "left_at[name] = nil" in MOD_INIT_LUA


@pytest.mark.parametrize("forbidden", ["http", "io.popen", "os.execute", "require"])
def test_lua_has_no_dangerous_calls(forbidden: str) -> None:
    assert forbidden not in MOD_INIT_LUA


def test_lua_texts_and_limits() -> None:
    assert access_mod.TEXT_DENY == "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
    assert access_mod.TEXT_KICK == "Deine Einladung für diese Welt wurde beendet."
    assert access_mod.TEXT_LOCKED == "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen."
    assert access_mod.TEXT_CASE_HINT == "Achte auf Groß- und Kleinschreibung: "
    for text in (access_mod.TEXT_DENY, access_mod.TEXT_KICK, access_mod.TEXT_LOCKED, access_mod.TEXT_CASE_HINT):
        assert access_mod._lua_string(text) in MOD_INIT_LUA
    assert "local FAIL_LIMIT = 5" in MOD_INIT_LUA
    assert "local LOCK_SECONDS = 600" in MOD_INIT_LUA
    # Kein Debug-Log aus dem Spike.
    assert "gameworld_spike" not in MOD_INIT_LUA
    assert "check_password_entry" not in MOD_INIT_LUA


def test_lua_string_escapes_utf8_as_decimal() -> None:
    assert access_mod._lua_string("f" + chr(0xFC) + "r") == r'"f\195\188r"'
    assert access_mod._lua_string('a"b' + chr(0x5C) + "c") == r'"a\034b\092c"'


def test_lua_source_is_ascii_without_dashes() -> None:
    assert MOD_INIT_LUA.isascii()
    assert MOD_CONF.isascii()
    # Gedankenstriche sind verboten (Owner-Regel), auch in den Texten.
    for text in (
        access_mod.TEXT_DENY,
        access_mod.TEXT_KICK,
        access_mod.TEXT_LOCKED,
        access_mod.TEXT_CASE_HINT,
        access_mod.TEXT_WAIT,
    ):
        assert chr(0x2013) not in text
        assert chr(0x2014) not in text


def test_paths_and_conf() -> None:
    assert MOD_NAME == "gameworld_access"
    assert MOD_DIR == ".minetest/worlds/world/worldmods/gameworld_access"
    assert ACCESS_FILE_NAME == "gameworld_access.txt"
    assert STATE_FILE_NAME == "gameworld_access_state.txt"
    assert ACCESS_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_access.txt"
    assert STATE_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_access_state.txt"
    assert f"name = {MOD_NAME}" in MOD_CONF
    assert access_mod.ACCESS_HEADER == "gameworld-access 1"


def test_events_constants() -> None:
    """Phase 4.1 Pattern 1: Ereignisdatei der Welt, einziger Weg von der Welt zur ExApp."""
    assert access_mod.EVENTS_FILE_NAME == "gameworld_events.txt"
    assert access_mod.EVENTS_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_events.txt"
    assert access_mod.EVENTS_HEADER == "gameworld-events 1"
    assert access_mod.EVENTS_MAX_LINES == 200
    assert frozenset({"deny", "join", "leave", "warn10"}) == access_mod.EVENT_KINDS
    assert access_mod.DENY_PER_NAME_SECONDS == 60
    assert access_mod.DENY_PER_MINUTE == 30
    assert f'world .. "/{access_mod.EVENTS_FILE_NAME}"' in MOD_INIT_LUA


def _prejoin_body() -> str:
    start = MOD_INIT_LUA.index("core.register_on_prejoinplayer(function(name)")
    end = MOD_INIT_LUA.index("\nend)", start)
    return MOD_INIT_LUA[start:end]


def test_deny_event_only_before_return_deny() -> None:
    """D-10, D-29: Nur fremde Namen melden, nie Tippfehler, Sperre oder Wartezeit."""
    assert MOD_INIT_LUA.count('event("deny"') == 1
    body = _prejoin_body()
    deny_event = body.index('event("deny", name)')
    return_deny = body.index("return DENY")
    assert deny_event < return_deny
    # Zwischen Meldung und return DENY steht kein anderer Zweig.
    between = body[deny_event:return_deny]
    for other in ("return CASE_HINT", "return LOCKED", "return WAIT"):
        assert other not in between
    for other in ("return CASE_HINT", "return LOCKED", "return WAIT"):
        assert body.index(other) < deny_event or body.index(other) > return_deny
    # Die CASE_HINT-Zeile meldet nichts.
    assert "return CASE_HINT .. variant end" in body
    assert "if locked(name) then return LOCKED end" in body


def test_join_and_leave_events() -> None:
    assert "core.register_on_joinplayer(function(player)" in MOD_INIT_LUA
    join = MOD_INIT_LUA.index("core.register_on_joinplayer(function(player)")
    assert 'event("join", ' in MOD_INIT_LUA[join : MOD_INIT_LUA.index("end)", join)]
    leave = MOD_INIT_LUA.index("core.register_on_leaveplayer(function(player)")
    assert 'event("leave", ' in MOD_INIT_LUA[leave : MOD_INIT_LUA.index("end)", leave)]


def test_events_global_export() -> None:
    # Luanti-Konvention: Global mit Modnamen, damit gameworld_time warn10 meldet.
    assert "gameworld_access = { event = event }" in MOD_INIT_LUA
    assert MOD_INIT_LUA.rstrip().endswith("gameworld_access = { event = event }")


def test_events_file_written_atomically_and_bounded() -> None:
    for needle in (
        "local EVENTS_MAX = 200",
        "core.safe_file_write(events_path,",
        "^gameworld%-events 1 (%d+)$",
        "^(%d+) (%d+) (%l+%d*) ([%w_%-]+)$",
        "local KINDS = { deny = true, join = true, leave = true, warn10 = true }",
        'name:match("^[%w_%-]+$")',
        "#name > 20",
        "os.time()",
    ):
        assert needle in MOD_INIT_LUA, needle
    # Beim Laden einmal schreiben: Fähigkeits-Merker für die ExApp (Pattern 3).
    loaded = MOD_INIT_LUA[MOD_INIT_LUA.index("core.register_on_mods_loaded") :]
    assert "write_events()" in loaded


def test_deny_flood_is_throttled() -> None:
    """T-04.1-01: je Name ein deny pro 60 s, höchstens 30 pro gleitender Minute."""
    for needle in ("local DENY_NAME_SECONDS = 60", "local DENY_PER_MINUTE = 30", "local function deny_allowed(name)"):
        assert needle in MOD_INIT_LUA, needle
    body = _prejoin_body()
    assert 'if deny_allowed(name) then event("deny", name) end' in body


def test_events_contain_no_ip_or_password() -> None:
    write = MOD_INIT_LUA[MOD_INIT_LUA.index("local function write_events()") :]
    write = write[: write.index("\nend\n")]
    for forbidden in ("get_player_ip", "_ip", "hash", "password", "allowed"):
        assert forbidden not in write
