"""i18n core (D-25): language normalization, translation with German as message ID, catalog coverage."""

from __future__ import annotations

import ast
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from gameworld import i18n
from gameworld.access import roles
from gameworld.i18n import catalog_en, catalog_fr, normalize_language, translate
from gameworld.provisioner import presets
from gameworld.worlds import status

NBSP = chr(0xA0)
RIGHT_QUOTE = chr(0x2019)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("de_DE", "de"),
        ("de-CH", "de"),
        ("DE", "de"),
        ("en_GB", "en"),
        ("en", "en"),
        ("fr", "fr"),
        ("fr_CA", "fr"),
        ("pt_BR", "en"),
        ("", "en"),
        (None, "en"),
        (5, "en"),
        ("<script>", "en"),
    ],
)
def test_normalize_language(raw: object, expected: str) -> None:
    assert normalize_language(raw) == expected


def test_german_is_returned_as_the_same_object() -> None:
    assert translate(roles.MSG_FORBIDDEN, "de") is roles.MSG_FORBIDDEN


def test_english_and_french_entries() -> None:
    assert translate(roles.MSG_FORBIDDEN, "en") == "Only parents can manage worlds."
    assert translate(roles.MSG_FORBIDDEN, "fr") == "Seuls les parents peuvent gérer les mondes."


def test_unsupported_language_falls_back_to_english() -> None:
    assert translate(roles.MSG_FORBIDDEN, "pt") == "Only parents can manage worlds."


def test_template_keeps_the_value() -> None:
    german = status.TEXT_CRASHED.format(code=137)
    assert translate(german, "en") == "The world stopped unexpectedly (code 137)."
    assert translate(german, "de") == german


def test_unknown_text_stays_german() -> None:
    assert translate("unbekannter Text", "fr") == "unbekannter Text"
    assert translate("unbekannter Text", "en") == "unbekannter Text"


def test_long_text_skips_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_catalog(language: str) -> object:
        raise AssertionError(f"catalog for {language} must not be consulted")

    monkeypatch.setattr(i18n, "_catalog", no_catalog)
    long_text = "x" * 5000
    assert translate(long_text, "en") is long_text


def test_long_template_text_is_not_searched() -> None:
    # Would match TEXT_CRASHED, but the length cap comes first (T-06-77).
    german = status.TEXT_CRASHED.format(code="9" * 3000)
    assert translate(german, "en") == german


def test_placeholders_and_repeated_placeholder() -> None:
    assert i18n.placeholders("a {x} b {y} c {x}") == frozenset({"x", "y"})
    pattern = i18n._compile("a {x} b {x}")  # pyright: ignore[reportPrivateUsage]
    assert pattern.fullmatch("a 1 b 1") is not None
    assert pattern.fullmatch("a 1 b 2") is None


def test_unknown_preset_message_uses_translated_titles() -> None:
    german = presets._unknown_message()  # pyright: ignore[reportPrivateUsage]
    assert translate(german, "en") == "Unknown game type. Allowed: Build (creative), Adventure (gentle)."
    assert "Construire (créatif)" in translate(german, "fr")


# --- catalog coverage (Task 2): every server-text constant has an en and fr entry -------------

SRC = Path(__file__).resolve().parents[1] / "src" / "gameworld"
EXCEPTIONS_FILE = Path(__file__).with_name("i18n_exceptions.tsv")

# API-near modules (06-18 Task 2); access_mod/time_mod (06-22) and notify/texts (06-23) are excluded.
_CONSTANT_DIRS = ("access", "api", "backup", "playtime", "worlds")
_CONSTANT_FILES = (
    "config.py",
    "nc.py",
    "notify/links.py",
    "play/ticket_api.py",
    "provisioner/presets.py",
    "provisioner/setup_check.py",
    "provisioner/client.py",
    "talk/rooms.py",
)
_CONSTANT_NAME = re.compile(r"^(MSG_|TEXT_)[A-Z0-9_]+$|^(NOT_FOUND\w*|BACKUP_NOT_FOUND|PORTS_EXHAUSTED|JOB_RUNNING)$")
# Server texts with other names that are stored (last_error, job messages) or answered directly.
EXTRA_TEXTS: dict[str, tuple[str, ...]] = {
    "worlds/service.py": (
        "PAYLOAD_FAILED",
        "CREATE_FAILED",
        "RECONCILE_OOM",
        "RECONCILE_DATA_MISSING",
        "RECONCILE_INTERRUPTED",
        "RESTORE_INTERRUPTED",
        "WORLD_BUSY",
        "OFFLINE_RESTART_FAILED",
        "RECONCILE_FAILED",
        "UNKNOWN_PRESET_TITLE",
    ),
    "backup/service.py": (
        "JOB_FAILED",
        "JOB_UNUSABLE",
        "PLAYERS_ONLINE_ONE",
        "PLAYERS_ONLINE_MANY",
        "JOB_INTERRUPTED",
        "RESTORE_JOB_INTERRUPTED",
        "RESTORE_NOT_CONFIRMED",
        "RESTORE_TAMPERED",
        "RESTORE_FAILED",
        "RESTORE_FALLBACK",
        "RESTORE_SWAP_FAILED",
    ),
    "provisioner/client.py": ("SNAPSHOT_RUNNING",),
    "api/alerts.py": ("DELETED_WORLD",),
}
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|und|nicht|bitte|ist|kein|gerade|welt)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExceptionRow:
    file: str
    line: int
    reason: str


def load_exceptions() -> list[ExceptionRow]:
    """Rows of tests/i18n_exceptions.tsv (header: file, line, reason; paths relative to the repo)."""
    rows = EXCEPTIONS_FILE.read_text(encoding="utf-8").splitlines()
    assert rows[0].split("\t") == ["file", "line", "reason"], rows[0]
    result: list[ExceptionRow] = []
    for raw in rows[1:]:
        if not raw.strip():
            continue
        file, line, reason = raw.split("\t")
        result.append(ExceptionRow(file, int(line), reason))
    return result


def _module_name(relative: str) -> str:
    return "gameworld." + relative.removesuffix(".py").replace("/", ".")


def constant_files() -> list[str]:
    found = [
        path.relative_to(SRC).as_posix() for folder in _CONSTANT_DIRS for path in sorted((SRC / folder).glob("*.py"))
    ]
    return found + list(_CONSTANT_FILES)


def _targets(node: ast.stmt) -> list[ast.expr]:
    if isinstance(node, ast.Assign):
        return list(node.targets)
    if isinstance(node, ast.AnnAssign):
        return [node.target]
    return []


def server_constants() -> list[tuple[str, int, str, str]]:
    """(file, line, name, value) of every server-text constant at module level."""
    result: list[tuple[str, int, str, str]] = []
    for relative in constant_files():
        tree = ast.parse((SRC / relative).read_text(encoding="utf-8"))
        module = importlib.import_module(_module_name(relative))
        extra = EXTRA_TEXTS.get(relative, ())
        for node in tree.body:
            for target in _targets(node):
                if isinstance(target, ast.Name) and (_CONSTANT_NAME.match(target.id) or target.id in extra):
                    value = getattr(module, target.id)
                    if isinstance(value, str):
                        result.append((f"src/gameworld/{relative}", node.lineno, target.id, value))
    return result


def covered(text: str, language: str) -> bool:
    catalog = catalog_en if language == "en" else catalog_fr
    return text in catalog.MESSAGES or text in catalog.TEMPLATES


def test_extra_texts_exist() -> None:
    names = {(file, name) for file, _, name, _ in server_constants()}
    for relative, extra in EXTRA_TEXTS.items():
        for name in extra:
            assert (f"src/gameworld/{relative}", name) in names, (relative, name)


def test_every_server_constant_has_en_and_fr() -> None:
    excepted = {(row.file, row.line) for row in load_exceptions()}
    constants = server_constants()
    assert len(constants) > 100
    missing = [
        (file, line, name)
        for file, line, name, value in constants
        if (file, line) not in excepted and not (covered(value, "en") and covered(value, "fr"))
    ]
    assert missing == []


def test_coverage_check_catches_a_missing_entry() -> None:
    """Positive control: a German text without entry is reported as uncovered."""
    assert not covered("Ein ganz neuer Text.", "en")
    assert not covered("Ein ganz neuer Text.", "fr")


def test_preset_texts_have_en_and_fr() -> None:
    for preset in presets.PRESETS.values():
        for text in (preset.title, preset.description):
            assert covered(text, "en"), text
            assert covered(text, "fr"), text


@pytest.mark.parametrize("language", ["en", "fr"])
def test_catalog_keys_are_german_sources(language: str) -> None:
    """No orphan keys: every key is a known constant or a message built from them."""
    catalog = catalog_en if language == "en" else catalog_fr
    known = {value for _, _, _, value in server_constants()}
    known |= {text for preset in presets.PRESETS.values() for text in (preset.title, preset.description)}
    known.add(presets._unknown_message())  # pyright: ignore[reportPrivateUsage]
    stray = [key for key in [*catalog.MESSAGES, *catalog.TEMPLATES] if key not in known]
    assert stray == []
    assert set(catalog_en.MESSAGES) == set(catalog_fr.MESSAGES)
    assert set(catalog_en.TEMPLATES) == set(catalog_fr.TEMPLATES)


@pytest.mark.parametrize("language", ["en", "fr"])
def test_templates_keep_their_placeholders(language: str) -> None:
    catalog = catalog_en if language == "en" else catalog_fr
    for source, target in catalog.TEMPLATES.items():
        assert i18n.placeholders(source), source
        assert i18n.placeholders(source) == i18n.placeholders(target), source


@pytest.mark.parametrize("language", ["en", "fr"])
def test_templates_round_trip(language: str) -> None:
    catalog = catalog_en if language == "en" else catalog_fr
    for source, target in catalog.TEMPLATES.items():
        values = {name: f"<{name} 42>" for name in i18n.placeholders(source)}
        assert translate(source.format(**values), language) == target.format(**values), source


def test_english_has_no_german_features() -> None:
    assert GERMAN.search(roles.MSG_FORBIDDEN)  # positive control
    for value in [*catalog_en.MESSAGES.values(), *catalog_en.TEMPLATES.values()]:
        assert not GERMAN.search(value), value


def test_french_typography() -> None:
    """Non-breaking space before ? ! ; : (written as escape in the source), never a plain space or none."""
    plain_space = re.compile(r" [?!;:]")
    missing = re.compile(rf"[^\s{NBSP}\d}}/]([?!;:])(\s|$)")
    assert missing.search("Erreur: x")  # positive control
    assert plain_space.search("Erreur : x")  # positive control
    assert not missing.search(f"Erreur{NBSP}: x")
    for value in [*catalog_fr.MESSAGES.values(), *catalog_fr.TEMPLATES.values()]:
        assert not plain_space.search(value), value
        assert not missing.search(value), value
        # The apostrophe is the typographic one; ASCII quotes only around values like '{raw}'.
        assert "'" not in re.sub(r"'[^'\s]*'", "", value), value
    source = (SRC / "i18n" / "catalog_fr.py").read_text(encoding="utf-8")
    assert NBSP not in source, "write the escape, not the character"
    assert RIGHT_QUOTE not in source, "write the escape, not the character"


def test_no_dashes_or_emojis_in_catalogs() -> None:
    for catalog in (catalog_en, catalog_fr):
        for value in [*catalog.MESSAGES.values(), *catalog.TEMPLATES.values()]:
            assert chr(0x2013) not in value, value
            assert chr(0x2014) not in value, value
            assert all(ord(char) < 0x2600 for char in value), value
