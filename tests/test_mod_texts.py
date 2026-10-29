"""World mods speak the world language (D-27, 06-22): German stays byte-identical, only literals change."""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from gameworld import i18n
from gameworld.provisioner import access_mod, archive, time_mod
from gameworld.provisioner.access_mod import _lua_string  # pyright: ignore[reportPrivateUsage]

# Re-pinned after D-26 comment translation (06-26): only Lua comment lines changed, see 06-26-SUMMARY.
# Previously measured on the base commit 83c0730 before 06-22 (access fc1e5327..., time 5039a654...).
GOLDEN_ACCESS_DE = "d2aecfe0ca5b60566a215753c420521093f13699291321d76c9d7a53c6b8dca2"
GOLDEN_TIME_DE = "d88731c9485f0cc4cf95ada37dc741adce88a34e286564490ddb93eba27d0eb5"

LANGUAGES = ("de", "en", "fr")
NBSP = chr(0x00A0)
APOSTROPHE = chr(0x2019)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _strings(bundle: Any) -> list[str]:
    """Every text of a bundle, weekday names included."""
    result: list[str] = []
    for value in bundle:
        if isinstance(value, tuple):
            result.extend(str(item) for item in value)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        else:
            result.append(str(value))
    return result


def _all_texts(language: str) -> list[str]:
    return _strings(access_mod.MOD_TEXTS[language]) + _strings(time_mod.MOD_TEXTS[language])


# --- German is byte-identical ------------------------------------------------------------------


def test_golden_hash_german_access_mod() -> None:
    assert _sha(access_mod.mod_init_lua("de")) == GOLDEN_ACCESS_DE
    assert _sha(access_mod.MOD_INIT_LUA) == GOLDEN_ACCESS_DE


def test_golden_hash_german_time_mod() -> None:
    assert _sha(time_mod.mod_init_lua("de")) == GOLDEN_TIME_DE
    assert _sha(time_mod.MOD_INIT_LUA) == GOLDEN_TIME_DE


def test_golden_positive_control() -> None:
    """The hash check notices a single changed character."""
    assert _sha(access_mod.mod_init_lua("en")) != GOLDEN_ACCESS_DE
    assert _sha(time_mod.mod_init_lua("fr")) != GOLDEN_TIME_DE


def test_german_bundle_uses_the_existing_constants() -> None:
    de = access_mod.MOD_TEXTS["de"]
    assert (de.deny, de.kick, de.locked, de.case_hint, de.wait) == (
        access_mod.TEXT_DENY,
        access_mod.TEXT_KICK,
        access_mod.TEXT_LOCKED,
        access_mod.TEXT_CASE_HINT,
        access_mod.TEXT_WAIT,
    )
    t = time_mod.MOD_TEXTS["de"]
    assert t.weekdays == time_mod.WEEKDAY_NAMES
    assert t.pause == time_mod.TEXT_PAUSE
    assert t.halt == time_mod.TEXT_HALT
    assert t.clock_unit == time_mod.CLOCK_UNIT
    # Every German constant of TEXTS is part of the bundle.
    assert set(time_mod.TEXTS) <= set(_strings(t))


@pytest.mark.parametrize("raw", ["xx", "", None, "DE", "en-US", 7])
def test_unsupported_language_gives_german(raw: Any) -> None:
    assert access_mod.mod_init_lua(raw) == access_mod.MOD_INIT_LUA
    assert time_mod.mod_init_lua(raw) == time_mod.MOD_INIT_LUA
    assert time_mod.kid_text("limit", language=raw) == time_mod.TEXT_LIMIT
    assert time_mod.pause_text("pause", None, language=raw) == time_mod.TEXT_PAUSE


def test_bundles_cover_exactly_the_supported_languages() -> None:
    assert set(access_mod.MOD_TEXTS) == set(i18n.SUPPORTED_LANGUAGES)
    assert set(time_mod.MOD_TEXTS) == set(i18n.SUPPORTED_LANGUAGES)


# --- Lua code is the same in every language, only literals change ------------------------------


@pytest.mark.parametrize("module", [access_mod, time_mod])
@pytest.mark.parametrize("language", ["en", "fr"])
def test_only_literal_lines_differ(module: Any, language: str) -> None:
    german = module.mod_init_lua("de").split("\n")
    other = module.mod_init_lua(language).split("\n")
    assert len(german) == len(other)
    literals = [_lua_string(text) for text in _strings(module.MOD_TEXTS[language])]
    changed = [(a, b) for a, b in zip(german, other, strict=True) if a != b]
    assert changed  # positive control: the language really changes something
    for _, line in changed:
        assert any(literal in line for literal in literals), line
        # The line is a plain text assignment: name = literal(s), nothing else.
        stripped = re.sub(r'"(?:[^"\\]|\\.)*"', '""', line)
        assert re.fullmatch(r'\s*(local [A-Z_]+ = \{? ?|\[\d+\] = |[a-z]+ = )("", )*""(,| \})?', stripped), line


@pytest.mark.parametrize("module", [access_mod, time_mod])
@pytest.mark.parametrize("language", LANGUAGES)
def test_lua_source_stays_ascii(module: Any, language: str) -> None:
    assert module.mod_init_lua(language).isascii()


@pytest.mark.parametrize("language", LANGUAGES)
def test_access_literals_in_lua(language: str) -> None:
    lua = access_mod.mod_init_lua(language)
    t = access_mod.MOD_TEXTS[language]
    for name, value in (
        ("DENY", t.deny),
        ("KICK", t.kick),
        ("LOCKED", t.locked),
        ("CASE_HINT", t.case_hint),
        ("WAIT", t.wait),
    ):
        assert f"local {name} = {_lua_string(value)}\n" in lua, name


@pytest.mark.parametrize("language", LANGUAGES)
def test_time_literals_in_lua_mirror_python(language: str) -> None:
    """Each Lua local carries the bundle text that kid_text/pause_text use in Python."""
    lua = time_mod.mod_init_lua(language)
    t = time_mod.MOD_TEXTS[language]
    for name, value in (
        ("FENSTER_EARLY", t.fenster_early),
        ("PLAY", t.play),
        ("PLAY_AGAIN", t.play_again),
        ("OPEN_AGAIN", t.open_again),
        ("DAY_TODAY", t.day_today),
        ("DAY_TOMORROW", t.day_tomorrow),
        ("DAY_ON", t.day_on),
        ("DAY_NEXT", t.day_next),
        ("CLOCK_FROM", t.clock_from),
        ("CLOCK_UNIT", t.clock_unit),
        ("PAUSE_TEXT", t.pause),
        ("PAUSE_SOON", t.pause_soon),
        ("SCHLUSS", t.schluss),
        ("HALT_SOON_TEXT", t.halt_soon),
        ("HALT_TEXT", t.halt),
    ):
        assert f"local {name} = {_lua_string(value)}\n" in lua, name
    reasons = (("limit", t.limit), ("fenster", t.fenster), ("tag", t.tag), ("welt", t.welt), ("start", t.start))
    for key, value in reasons:
        assert f"  {key} = {_lua_string(value)},\n" in lua, key
    for seconds, value in ((600, t.warn_10), (300, t.warn_5), (60, t.warn_1)):
        assert f"  [{seconds}] = {_lua_string(value)},\n" in lua, seconds
    weekdays = ", ".join(_lua_string(day) for day in t.weekdays)
    assert f"local WEEKDAYS = {{ {weekdays} }}\n" in lua


# --- Python sentences per language -------------------------------------------------------------

KID_CASES: list[tuple[str, tuple[Any, ...], dict[str, Any], str]] = [
    ("en", ("fenster", 0, 3, 900), {}, "It is not playtime yet. Today from 15:00 you can play."),
    ("en", ("limit", 1, 4, 540), {}, "Your playtime for today is over. Tomorrow from 9:00 you can play again."),
    ("en", ("tag", 3, 6, 0), {}, "Today is not a play day. On Saturday you can play again."),
    ("en", ("tag", 7, 6, 870), {}, "Today is not a play day. Next Saturday from 14:30 you can play again."),
    ("en", ("welt", 1, 4, 600), {}, "This world is closed right now. Tomorrow from 10:00 it will be open again."),
    ("en", ("start",), {}, "Gameworld is starting. Please try again in a moment."),
    ("en", ("fenster", 0, 3, 900), {"reached": True}, "Gameworld is starting. Please try again in a moment."),
    ("en", ("limit",), {}, "Your playtime for today is over."),
    (
        "fr",
        ("fenster", 0, 3, 900),
        {},
        "Ce n\u2019est pas encore l\u2019heure de jouer. Aujourd\u2019hui à partir de 15 h, tu peux jouer.",
    ),
    (
        "fr",
        ("limit", 1, 4, 540),
        {},
        "Ton temps de jeu pour aujourd\u2019hui est terminé. Demain à partir de 9 h, tu pourras rejouer.",
    ),
    ("fr", ("tag", 3, 6, 0), {}, "Aujourd\u2019hui, ce n\u2019est pas un jour de jeu. Ce samedi, tu pourras rejouer."),
    (
        "fr",
        ("tag", 7, 6, 870),
        {},
        (
            "Aujourd\u2019hui, ce n\u2019est pas un jour de jeu. "
            "La semaine prochaine, samedi à partir de 14:30, tu pourras rejouer."
        ),
    ),
    (
        "fr",
        ("welt", 1, 4, 600),
        {},
        "Ce monde est fermé pour le moment. Demain à partir de 10 h, il sera de nouveau ouvert.",
    ),
    ("fr", ("start",), {}, "Gameworld démarre. Réessaie dans un instant."),
    ("fr", ("fenster", 0, 3, 900), {"reached": True}, "Gameworld démarre. Réessaie dans un instant."),
    ("fr", ("limit",), {}, "Ton temps de jeu pour aujourd\u2019hui est terminé."),
]


@pytest.mark.parametrize(("language", "args", "kwargs", "expected"), KID_CASES)
def test_kid_text_per_language(language: str, args: tuple[Any, ...], kwargs: dict[str, Any], expected: str) -> None:
    assert time_mod.kid_text(*args, language=language, **kwargs) == expected


def test_kid_text_german_default_unchanged() -> None:
    for args in (("fenster", 0, 3, 900), ("limit", 1, 4, 540), ("tag", 7, 6, 870), ("welt", 2, 1, 0)):
        assert time_mod.kid_text(*args) == time_mod.kid_text(*args, language="de")
    expected = "Jetzt ist noch keine Spielzeit. Heute ab 15 Uhr kannst du spielen."
    assert time_mod.kid_text("fenster", 0, 3, 900) == expected


@pytest.mark.parametrize(
    ("language", "art", "minute", "expected"),
    [
        ("fr", "schluss", 540, "C\u2019est fini pour aujourd\u2019hui. Demain à partir de 9 h, tu pourras rejouer."),
        ("fr", "schluss", 0, "C\u2019est fini pour aujourd\u2019hui. Demain, tu pourras rejouer."),
        ("fr", "schluss", -1, "C\u2019est fini pour aujourd\u2019hui."),
        ("fr", "pause", None, "Petite pause. Tes parents ont besoin de toi. Ensuite, tu pourras continuer à jouer."),
        ("en", "schluss", 570, "That is it for today. Tomorrow from 9:30 you can play again."),
        ("en", "schluss", None, "That is it for today. Tomorrow you can play again."),
        ("en", "pause", None, "Short break! Your parents need you right now. You can keep playing afterwards."),
        ("de", "schluss", 540, "Für heute ist Schluss. Morgen ab 9 Uhr kannst du wieder spielen."),
    ],
)
def test_pause_text_per_language(language: str, art: str, minute: int | None, expected: str) -> None:
    assert time_mod.pause_text(art, minute, language=language) == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_never_midnight_in_any_language(language: str) -> None:
    banned = ("0 Uhr", "0:00", "0 h", "midnight", "minuit", "Mitternacht")
    for reason in ("limit", "fenster", "tag", "welt"):
        for days_ahead in range(8):
            for minute in (0, 1, 59, 60, 540, 1439):
                text = time_mod.kid_text(reason, days_ahead, 3, minute, language=language)
                assert not any(re.search(rf"(?<!\d){re.escape(word)}", text) for word in banned), text
    for minute in (-1, 0, 1, 540, None):
        text = time_mod.pause_text("schluss", minute, language=language)
        assert not any(re.search(rf"(?<!\d){re.escape(word)}", text) for word in banned), text


# --- Text hygiene ------------------------------------------------------------------------------

EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_forbidden_characters(language: str) -> None:
    for text in _all_texts(language):
        assert text, language
        for forbidden in ("%", "|", chr(0x2013), chr(0x2014), "\n", "\r"):
            assert forbidden not in text, (language, text)
        assert not EMOJI.search(text), text
        lowered = text.lower()
        for word in ("0 uhr", "midnight", "minuit", "mitternacht"):
            assert word not in lowered, text


def test_forbidden_character_check_positive_control() -> None:
    assert EMOJI.search("Hallo \U0001f600")
    assert chr(0x2014) in f"a {chr(0x2014)} b"


def test_english_texts_have_no_german() -> None:
    german = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|und|nicht|bitte|ist|kein|gerade|welt|uhr)\b", re.IGNORECASE)
    assert german.search(access_mod.TEXT_DENY)  # positive control
    for text in _all_texts("en"):
        assert not german.search(text), text


def test_french_typography() -> None:
    """Typographic apostrophe; no ? ! ; : in the texts (they would need a non-breaking space)."""
    for text in _all_texts("fr"):
        assert "'" not in text, text
        assert not re.search(r"[?!;:]", text), text
        assert NBSP not in text, text
    assert any(APOSTROPHE in text for text in _all_texts("fr"))


def test_case_hint_never_names_a_player() -> None:
    """IN-07 in every language: the hint stays generic, no placeholder or name."""
    for language in LANGUAGES:
        hint = access_mod.MOD_TEXTS[language].case_hint
        assert "{" not in hint
        assert "%" not in hint


# --- Archive -----------------------------------------------------------------------------------

ACCESS = b"gameworld-access 1 0\nend\n"
RULES = b"gameworld-time 1 0 0\nend\n"


def test_world_files_carry_the_language() -> None:
    raw = archive.build_world_files(ACCESS, RULES, language="en")
    assert access_mod.mod_init_lua("en").encode() in raw
    assert time_mod.mod_init_lua("en").encode() in raw
    assert access_mod.MOD_INIT_LUA.encode() not in raw


def test_world_files_default_is_byte_identical_german() -> None:
    assert archive.build_world_files(ACCESS, RULES) == archive.build_world_files(ACCESS, RULES, language="de")
    assert archive.world_mods("de") == archive.WORLD_MODS
    assert archive.world_mods("xx") == archive.WORLD_MODS


def test_world_mods_keep_the_status_mod_and_order() -> None:
    mods = archive.world_mods("fr")
    assert [mod_dir for mod_dir, _, _ in mods] == [mod_dir for mod_dir, _, _ in archive.WORLD_MODS]
    assert mods[0] == archive.WORLD_MODS[0]
    assert mods[1][1] == access_mod.mod_init_lua("fr")
    assert mods[2][1] == time_mod.mod_init_lua("fr")
    assert [conf for _, _, conf in mods] == [conf for _, _, conf in archive.WORLD_MODS]
