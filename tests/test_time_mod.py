"""Welt-Mod gameworld_time, Regeldatei und Zählbuch (04-RESEARCH.md Pattern 1 bis 3)."""

from __future__ import annotations

import pytest

from gameworld.provisioner import time_mod
from gameworld.provisioner.access_mod import _lua_string  # pyright: ignore[reportPrivateUsage]
from gameworld.provisioner.time_mod import (
    LEDGER_FILE,
    LEDGER_FILE_NAME,
    MOD_CONF,
    MOD_DIR,
    MOD_INIT_LUA,
    MOD_NAME,
    RULES_FILE,
    RULES_FILE_NAME,
    Ledger,
    TimeLine,
    parse_ledger,
    render_time_file,
)

ISSUED = 1792792800
OK = TimeLine(cap=3600, start=1792800000, until=1792836000, reason="ok", next_hint="Sa-10:00")
FREI = TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-")
WORLD = TimeLine(cap=-1, start=0, until=0, reason="welt", next_hint="Mi-10:00")


def test_empty_rules_file_has_header_and_end() -> None:
    assert render_time_file(0, ISSUED, None, {}) == b"gameworld-time 1 0 1792792800\nend\n"


def test_lines_sorted_world_first_ascii_and_deterministic() -> None:
    first = render_time_file(4, ISSUED, WORLD, {"Mia": OK, "Leo": OK, "Papa": FREI})
    second = render_time_file(4, ISSUED, WORLD, {"Papa": FREI, "Leo": OK, "Mia": OK})
    assert first == second
    assert first.decode("ascii").split("\n") == [
        "gameworld-time 1 4 1792792800",
        "welt 0 0 welt Mi-10:00",
        "Leo 3600 1792800000 1792836000 ok Sa-10:00",
        "Mia 3600 1792800000 1792836000 ok Sa-10:00",
        "Papa -1 -1 -1 frei -",
        "end",
        "",
    ]


def test_world_line_with_open_window() -> None:
    open_world = TimeLine(cap=-1, start=1792800000, until=1792807200, reason="ok", next_hint="-")
    assert b"\nwelt 1792800000 1792807200 ok -\n" in render_time_file(1, ISSUED, open_world, {})


@pytest.mark.parametrize("name", ["Mia Leo", "Mia\nLeo", "a" * 21, "M" + chr(0xE4) + "x", "", "Mia\r", "Mia\nend"])
def test_invalid_name_raises(name: str) -> None:
    with pytest.raises(ValueError, match="Spielername"):
        render_time_file(1, ISSUED, None, {name: OK})


@pytest.mark.parametrize("name", ["welt", "end", "Welt", "END", "eNd"])
def test_reserved_names_raise(name: str) -> None:
    with pytest.raises(ValueError, match="Spielername"):
        render_time_file(1, ISSUED, None, {name: OK})


def test_twenty_character_name_is_allowed() -> None:
    assert b"a" * 20 in render_time_file(1, ISSUED, None, {"a" * 20: OK})


@pytest.mark.parametrize("reason", ["", "OK", "welt", "start", "ok x", "ok\nMia"])
def test_invalid_player_reason_raises(reason: str) -> None:
    line = TimeLine(cap=60, start=0, until=0, reason=reason, next_hint="-")
    with pytest.raises(ValueError, match="Grund"):
        render_time_file(1, ISSUED, None, {"Mia": line})


@pytest.mark.parametrize("reason", ["tag", "fenster", "limit", "frei", ""])
def test_invalid_world_reason_raises(reason: str) -> None:
    line = TimeLine(cap=-1, start=0, until=0, reason=reason, next_hint="-")
    with pytest.raises(ValueError, match="Grund"):
        render_time_file(1, ISSUED, line, {})


@pytest.mark.parametrize("hint", ["", "Sa 10:00", "Sa-10:00\nMia", "a" * 17, "Sa_10", "Mo" + chr(0xE4)])
def test_invalid_next_hint_raises(hint: str) -> None:
    line = TimeLine(cap=60, start=0, until=0, reason="ok", next_hint=hint)
    with pytest.raises(ValueError, match="nächste Spielzeit"):
        render_time_file(1, ISSUED, None, {"Mia": line})


@pytest.mark.parametrize(
    "line",
    [
        TimeLine(cap=True, start=0, until=0, reason="ok", next_hint="-"),
        TimeLine(cap=60, start=False, until=0, reason="ok", next_hint="-"),
        TimeLine(cap=-2, start=0, until=0, reason="ok", next_hint="-"),
        TimeLine(cap=60, start=-1, until=0, reason="ok", next_hint="-"),
        TimeLine(cap=60, start=0, until=-1, reason="limit", next_hint="-"),
        TimeLine(cap=0, start=-1, until=-1, reason="frei", next_hint="-"),
        TimeLine(cap=-1, start=0, until=-1, reason="frei", next_hint="-"),
        TimeLine(cap=-1, start=-1, until=-1, reason="ok", next_hint="-"),
    ],
)
def test_invalid_numbers_raise(line: TimeLine) -> None:
    with pytest.raises(ValueError, match="Zahl"):
        render_time_file(1, ISSUED, None, {"Mia": line})


def test_frei_line_is_exactly_minus_one() -> None:
    assert b"\nPapa -1 -1 -1 frei -\n" in render_time_file(1, ISSUED, None, {"Papa": FREI})


def test_cap_minus_one_means_no_limit() -> None:
    line = TimeLine(cap=-1, start=1792800000, until=1792836000, reason="ok", next_hint="-")
    assert b"\nMia -1 1792800000 1792836000 ok -\n" in render_time_file(1, ISSUED, None, {"Mia": line})


@pytest.mark.parametrize(("generation", "issued"), [(-1, ISSUED), (1, -1), (True, ISSUED), (1, False)])
def test_invalid_header_raises(generation: int, issued: int) -> None:
    with pytest.raises(ValueError, match=r"Generation|Zeitpunkt"):
        render_time_file(generation, issued, None, {})


def test_parse_ledger() -> None:
    parsed = parse_ledger(b"gameworld-time-used 1 1792800000 3\nMia 40\nLeo 5\nend\n")
    assert parsed == Ledger(written_at=1792800000, generation=3, seconds={"Mia": 40, "Leo": 5})


def test_parse_ledger_empty_body() -> None:
    assert parse_ledger(b"gameworld-time-used 1 1792800000 0\nend\n") == Ledger(1792800000, 0, {})


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"end\n",
        b"gameworld-time-used 1 1792800000 3\nMia 40\n",
        b"Mia 40\nend\n",
        b"gameworld-time-used 2 1792800000 3\nend\n",
        b"gameworld-time-used 1 1792800000\nend\n",
        b"gameworld-time-used 1 -5 3\nend\n",
        b"\xff\xfe\nend\n",
    ],
)
def test_parse_ledger_rejects_incomplete(content: bytes) -> None:
    assert parse_ledger(content) is None


def test_parse_ledger_skips_invalid_lines() -> None:
    content = (
        b"gameworld-time-used 1 1792800000 3\n"
        b"Mia 40\n" + b"a" * 21 + b" 5\n"
        b"Leo -5\n"
        b"Ben 1.5\n"
        b"Ida 1000000001\n"
        b"Max 1000000000\n"
        b"Tom\n"
        b"M\xc3\xa4x 3\n"
        b"Ole 7 8\n"
        b"end\n"
    )
    parsed = parse_ledger(content)
    assert parsed is not None
    assert parsed.seconds == {"Mia": 40, "Max": 1000000000}


def test_texts() -> None:
    assert time_mod.TEXT_LIMIT == "Deine Spielzeit für heute ist aufgebraucht."
    assert time_mod.TEXT_FENSTER == "Gerade ist keine Spielzeit."
    assert time_mod.TEXT_TAG == "Heute ist kein Spieltag."
    assert time_mod.TEXT_WELT == "Diese Welt ist gerade geschlossen."
    assert time_mod.TEXT_NEXT == " Nächste Spielzeit: "
    assert time_mod.TEXT_WELT_NEXT == " Sie öffnet "
    assert time_mod.TEXT_START == "Gameworld startet gleich. Bitte gleich nochmal versuchen."
    assert time_mod.TEXT_WARN_10 == "Noch 10 Minuten Spielzeit. Denk ans Speichern und Verabschieden."
    assert time_mod.TEXT_WARN_5 == "Noch 5 Minuten."
    assert time_mod.TEXT_WARN_1 == "Noch 1 Minute."
    for text in time_mod.TEXTS:
        assert _lua_string(text) in MOD_INIT_LUA
        assert chr(0x2013) not in text
        assert chr(0x2014) not in text


def test_lua_contains_enforcement_points() -> None:
    for needle in (
        "register_on_prejoinplayer",
        "register_on_joinplayer",
        "register_on_leaveplayer",
        "register_on_shutdown",
        "register_on_mods_loaded",
        "disconnect_player",
        "chat_send_player",
        "safe_file_write",
        "os.time",
        "^gameworld%-time 1 (%d+) %d+$",
        "^gameworld%-time%-used 1 %d+ %d+$",
        "(%-?%d+) (%-?%d+) (%-?%d+)",
        "local TICK = 5",
        "local MIN_LEFT = 60",
        "local WARN = { 600, 300, 60 }",
    ):
        assert needle in MOD_INIT_LUA, needle


def test_lua_warns_only_smallest_threshold() -> None:
    # Beitritt mit 4 min Rest: nur "Noch 5 Minuten.", die 10-Minuten-Warnung gilt als gesendet.
    assert "if l <= w then hit = w" in MOD_INIT_LUA
    assert "if w >= hit then marks[w] = true end" in MOD_INIT_LUA


def test_lua_credits_from_join_time() -> None:
    # Gutschrift ab Beitritt und anteilig beim Verlassen (Pitfall 3), Zählbuch sofort schreiben.
    assert "since[player:get_player_name()] = core.get_us_time()" in MOD_INIT_LUA
    leave = MOD_INIT_LUA.index("core.register_on_leaveplayer")
    assert "write_ledger()" in MOD_INIT_LUA[leave:]


@pytest.mark.parametrize(
    "forbidden", ["kick_player", "os.date", "http", "io.popen", "os.execute", "require", "diag", "until "]
)
def test_lua_has_no_forbidden_calls(forbidden: str) -> None:
    assert forbidden not in MOD_INIT_LUA


def test_lua_source_is_ascii() -> None:
    MOD_INIT_LUA.encode("ascii")
    MOD_CONF.encode("ascii")


def test_paths_and_conf() -> None:
    assert MOD_NAME == "gameworld_time"
    assert MOD_DIR == ".minetest/worlds/world/worldmods/gameworld_time"
    assert RULES_FILE_NAME == "gameworld_time.txt"
    assert LEDGER_FILE_NAME == "gameworld_time_used.txt"
    assert RULES_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_time.txt"
    assert LEDGER_FILE == "/var/lib/minetest/.minetest/worlds/world/gameworld_time_used.txt"
    assert f"name = {MOD_NAME}" in MOD_CONF
    # Pitfall 5: Der Zugangstext gewinnt im Modus OR, weil gameworld_access zuerst lädt.
    assert "depends = gameworld_access" in MOD_CONF
    assert time_mod.TIME_HEADER == "gameworld-time 1"
    assert time_mod.LEDGER_HEADER == "gameworld-time-used 1"
    assert {"ok", "tag", "fenster", "limit", "frei"} == set(time_mod.REASONS)
