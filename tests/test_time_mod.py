"""Welt-Mod gameworld_time, Regeldatei und Zählbuch (04-RESEARCH.md Pattern 1 bis 3)."""

from __future__ import annotations

import re

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
    DayGrid,
    Ledger,
    TimeLine,
    kid_text,
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
    assert time_mod.TEXT_LIMIT == "Deine Spielzeit für heute ist vorbei."
    assert time_mod.TEXT_FENSTER == "Jetzt ist keine Spielzeit."
    assert time_mod.TEXT_FENSTER_EARLY == "Jetzt ist noch keine Spielzeit."
    assert time_mod.TEXT_TAG == "Heute ist kein Spieltag."
    assert time_mod.TEXT_WELT == "Diese Welt ist gerade zu."
    assert time_mod.TEXT_START == "Gameworld startet gleich. Bitte gleich nochmal versuchen."
    assert time_mod.TEXT_WARN_10 == "Noch 10 Minuten Spielzeit. Komm langsam zum Ende und verabschiede dich."
    assert time_mod.TEXT_WARN_5 == "Noch 5 Minuten."
    assert time_mod.TEXT_WARN_1 == "Noch 1 Minute."
    assert not hasattr(time_mod, "TEXT_NEXT")
    assert not hasattr(time_mod, "TEXT_WELT_NEXT")
    assert time_mod.WEEKDAY_NAMES == ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
    for text in (*time_mod.TEXTS, *time_mod.WEEKDAY_NAMES):
        assert _lua_string(text) in MOD_INIT_LUA, text
        assert chr(0x2013) not in text
        assert chr(0x2014) not in text


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("limit", 1, 6, 540), "Deine Spielzeit für heute ist vorbei. Morgen ab 9 Uhr kannst du wieder spielen."),
        (("tag", 3, 6, 540), "Heute ist kein Spieltag. Am Samstag ab 9 Uhr kannst du wieder spielen."),
        (("fenster", 0, 3, 900), "Jetzt ist noch keine Spielzeit. Heute ab 15 Uhr kannst du spielen."),
        (("fenster", 1, 4, 900), "Jetzt ist keine Spielzeit. Morgen ab 15 Uhr kannst du wieder spielen."),
        (("welt", 2, 3, 600), "Diese Welt ist gerade zu. Am Mittwoch ab 10 Uhr ist sie wieder offen."),
        (("welt", 0, 3, 600), "Diese Welt ist gerade zu. Heute ab 10 Uhr ist sie wieder offen."),
        (("welt", 1, 4, 0), "Diese Welt ist gerade zu. Morgen ist sie wieder offen."),
        (("limit", 1, 4, 0), "Deine Spielzeit für heute ist vorbei. Morgen kannst du wieder spielen."),
        (("limit", None, None, None), "Deine Spielzeit für heute ist vorbei."),
        (("tag", None, None, None), "Heute ist kein Spieltag."),
        (("fenster", None, None, None), "Jetzt ist keine Spielzeit."),
        (("welt", None, None, None), "Diese Welt ist gerade zu."),
        (("limit", 8, 6, 540), "Deine Spielzeit für heute ist vorbei."),
        (("limit", -1, 6, 540), "Deine Spielzeit für heute ist vorbei."),
        (("limit", 1, 8, 540), "Deine Spielzeit für heute ist vorbei."),
        (("limit", 1, 6, 1440), "Deine Spielzeit für heute ist vorbei."),
        (("start", 1, 6, 540), "Gameworld startet gleich. Bitte gleich nochmal versuchen."),
    ],
)
def test_kid_text(args: tuple[str, int | None, int | None, int | None], expected: str) -> None:
    assert kid_text(*args) == expected


def test_kid_text_next_week_with_minutes() -> None:
    assert kid_text("tag", 7, 6, 870).endswith("Nächsten Samstag ab 14:30 Uhr kannst du wieder spielen.")


def test_kid_text_never_says_midnight() -> None:
    forbidden = re.compile(r"(?<!\d)0 Uhr|00:00|Mitternacht|24 Uhr|\d+\.\d+\.")
    for reason in ("limit", "tag", "fenster", "welt"):
        for days_ahead in range(8):
            for weekday in range(1, 8):
                for minute in (0, 540, 870, 1439):
                    text = kid_text(reason, days_ahead, weekday, minute)
                    # "0 Uhr" nur als eigene Zahl: "14:30 Uhr" ist erlaubt, "0 Uhr" nie.
                    assert not forbidden.search(text), text


DAYS = DayGrid(weekday=3, starts=tuple(1792792800 + 86400 * k for k in range(9)))


def test_rules_file_without_days_is_unchanged() -> None:
    plain = render_time_file(4, ISSUED, WORLD, {"Mia": OK, "Papa": FREI})
    assert plain == render_time_file(4, ISSUED, WORLD, {"Mia": OK, "Papa": FREI}, days=None)
    assert b"@" not in plain


def test_rules_file_with_days_and_starts() -> None:
    mia = TimeLine(
        cap=3600,
        start=1792800000,
        until=1792836000,
        reason="limit",
        next_hint="Do-09:00",
        next_at=1792911600,
        next_minute=540,
    )
    world = TimeLine(cap=-1, start=0, until=0, reason="welt", next_hint="Mi-10:00", next_at=1792836000, next_minute=600)
    data = render_time_file(4, ISSUED, world, {"Mia": mia, "Papa": FREI, "Leo": OK}, days=DAYS)
    starts = " ".join(str(value) for value in DAYS.starts)
    assert data.decode("ascii").split("\n") == [
        "gameworld-time 1 4 1792792800",
        f"@tage 3 {starts}",
        "welt 0 0 welt Mi-10:00",
        "@start welt 1792836000 600",
        "Leo 3600 1792800000 1792836000 ok Sa-10:00",
        "Mia 3600 1792800000 1792836000 limit Do-09:00",
        "@start Mia 1792911600 540",
        "Papa -1 -1 -1 frei -",
        "end",
        "",
    ]


@pytest.mark.parametrize(
    "days",
    [
        DayGrid(weekday=3, starts=DAYS.starts[:8]),
        DayGrid(weekday=3, starts=(*DAYS.starts, DAYS.starts[-1] + 86400)),
        DayGrid(weekday=3, starts=(DAYS.starts[1], DAYS.starts[0], *DAYS.starts[2:])),
        DayGrid(weekday=3, starts=(DAYS.starts[0], DAYS.starts[0], *DAYS.starts[2:])),
        DayGrid(weekday=3, starts=(-5, *DAYS.starts[1:])),
        DayGrid(weekday=0, starts=DAYS.starts),
        DayGrid(weekday=8, starts=DAYS.starts),
        DayGrid(weekday=True, starts=DAYS.starts),
    ],
)
def test_invalid_days_raise(days: DayGrid) -> None:
    with pytest.raises(ValueError, match="Tagesgrenzen"):
        render_time_file(1, ISSUED, None, {}, days=days)


@pytest.mark.parametrize(
    "line",
    [
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_at=1792911600),
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_minute=540),
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_at=1792911600, next_minute=1440),
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_at=-2, next_minute=540),
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_at=1792911600, next_minute=-2),
        TimeLine(cap=60, start=0, until=0, reason="limit", next_hint="-", next_at=True, next_minute=540),
        TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-", next_at=1792911600, next_minute=540),
    ],
)
def test_invalid_next_start_raises(line: TimeLine) -> None:
    with pytest.raises(ValueError, match="nächster Start"):
        render_time_file(1, ISSUED, None, {"Mia": line}, days=DAYS)


def test_lua_parses_day_and_start_lines() -> None:
    for needle in ("^@tage ", "^@start ([%w_%-]+) (%d+) (%d+)$", "math.floor", "%d:%02d"):
        assert needle in MOD_INIT_LUA, needle
    # Alte Mods lesen nur Zeilen ab [%w_%-]; das Muster bleibt, @-Zeilen passen nie darauf.
    assert "^([%w_%-]+) (%-?%d+) (%-?%d+) (%-?%d+) (%a+) ([%w:%-]+)$" in MOD_INIT_LUA


def test_rules_file_with_base_line() -> None:
    """WR-06: @base folgt der Zeile mit Deckel (nach @start), Zeilen ohne Anker bleiben wie bisher."""
    mia = TimeLine(
        cap=3600,
        start=1792800000,
        until=1792836000,
        reason="ok",
        next_hint="-",
        next_at=1792911600,
        next_minute=540,
        base=900,
    )
    data = render_time_file(4, ISSUED, None, {"Mia": mia, "Leo": OK}, days=DAYS)
    lines = data.decode("ascii").split("\n")
    index = lines.index("Mia 3600 1792800000 1792836000 ok -")
    assert lines[index + 1 : index + 3] == ["@start Mia 1792911600 540", "@base Mia 900"]
    assert not any(line.startswith("@base Leo") for line in lines)


@pytest.mark.parametrize(
    "line",
    [
        TimeLine(cap=60, start=0, until=0, reason="ok", next_hint="-", base=-2),
        TimeLine(cap=60, start=0, until=0, reason="ok", next_hint="-", base=61),
        TimeLine(cap=-1, start=0, until=0, reason="ok", next_hint="-", base=0),
        TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-", base=0),
        TimeLine(cap=60, start=0, until=0, reason="ok", next_hint="-", base=True),
    ],
)
def test_invalid_base_raises(line: TimeLine) -> None:
    with pytest.raises(ValueError, match="Anker"):
        render_time_file(1, ISSUED, None, {"Mia": line})


def test_lua_shifts_cap_when_ledger_is_behind_base() -> None:
    """WR-06: Der Mod liest @base und zieht den Rückstand des Zählbuchs vom Deckel ab."""
    assert "^@base ([%w_%-]+) (%d+)$" in MOD_INIT_LUA
    assert "local behind = base - (used[name] or 0)" in MOD_INIT_LUA
    assert "local rest = r.cap - (shifts[name] or 0) - (used[name] or 0)" in MOD_INIT_LUA


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
