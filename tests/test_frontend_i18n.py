"""Structure gate for the i18n work (D-25, plan 06-24).

Four parts, each with a positive control:

1. No user-visible German text in frontend/src outside frontend/src/i18n. Exceptions
   live only in tests/frontend_i18n_exceptions.tsv (file, line, literal, reason) and
   are matched in both directions: a stale or reasonless entry fails as well.
2. Umlaut audit: no German value (de dictionaries, backend MSG_/TEXT_ constants, the
   German text bundles) uses an ASCII replacement spelling such as "fuer" or "ueber".
3. Leftover German audit: no en or fr value (frontend dictionaries, server catalogs,
   mod, notification and bot bundles) and no English or French documentation contains
   German. Exceptions live in tests/i18n_foreign_exceptions.tsv (file, key, literal,
   reason) and cover proper names and deliberate German artefacts only.
4. No en dash, em dash or emoji anywhere under frontend/src.

Special characters are built with chr() so this file stays plain ASCII.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
I18N_DIR = FRONTEND_SRC / "i18n"
BACKEND_SRC = ROOT / "src" / "gameworld"
EXCEPTIONS_TSV = ROOT / "tests" / "frontend_i18n_exceptions.tsv"
FOREIGN_EXCEPTIONS_TSV = ROOT / "tests" / "i18n_foreign_exceptions.tsv"
LANGUAGES = ("de", "en", "fr")

AE, OE, UE = chr(0xE4), chr(0xF6), chr(0xFC)
GERMAN_CHARS = AE + OE + UE + chr(0xC4) + chr(0xD6) + chr(0xDC) + chr(0xDF)

# Part 1: German markers in frontend source literals (whole words, any case).
FRONTEND_WORDS = (
    "der",
    "die",
    "das",
    "und",
    "nicht",
    "bitte",
    "ist",
    "du",
    "dein",
    "deine",
    "kein",
    "keine",
    "noch",
    "wird",
    "gerade",
    "Welt",
    "Spieler",
    "Sicherung",
    "Pause",
    "Einladung",
    "Spielzeit",
    "Eltern",
    "Kinder",
)

# Part 3: German markers in en/fr values. Function words match as whole words, the
# nouns also as word starts ("Sicherungen", "Spielers"). The extra words make the
# scan stricter than the plan list; none of them is an English or French word.
FOREIGN_WORDS = (
    "der",
    "die",
    "das",
    "und",
    "nicht",
    "bitte",
    "ist",
    "dein",
    "deine",
    "kein",
    "keine",
    "noch",
    "wird",
    "gerade",
    "oder",
    "sich",
    "wenn",
    "werden",
    "kann",
    "auch",
    "jetzt",
    "sind",
    "zum",
    "zur",
    "beim",
    "nur",
    "mit",
    "ein",
    "eine",
    "einen",
    "auf",
    "aus",
    "von",
    "nach",
    "den",
    "dem",
    "im",
    "zu",
    "wir",
    "ihr",
    "uns",
    "sie",
    "neu",
    "neue",
    "neues",
    "neuen",
    "Raum",
    "gibt",
)
FOREIGN_STEMS = (
    "Welt",
    "Spieler",
    "Sicherung",
    "Einladung",
    "Spielzeit",
    "Eltern",
    "Kinder",
    "Verwalter",
    "Woche",
    "Uhr",
    "Minuten",
    "Stunde",
    "Passwort",
    "Einstellung",
    "Anleitung",
    "Beitritt",
    "Ferien",
    "Zeitfenster",
    "Zeitzone",
    "Spielst",
    "Schluss",
    "einlad",
    "Wiederherst",
    "Erwachsen",
    "Gruppe",
    "Konto",
    "Hinweis",
    "Datei",
    "Ordner",
    "Abenteuer",
    "Bauen",
    "Antwort",
    "Befehl",
    "Deutsch",
    "Fassung",
)

# Part 2: ASCII replacement spellings (case-insensitive substrings, stems included).
ASCII_REPLACEMENTS = (
    "fuer",
    "ueber",
    "koennen",
    "koennt",
    "muessen",
    "muesst",
    "moechte",
    "waehle",
    "waehl",
    "loeschen",
    "loesch",
    "groesse",
    "schliessen",
    "schliess",
    "heisst",
    "spaeter",
    "naechste",
    "zugaenge",
    "zugaeng",
    "zurueck",
    "moeglich",
    "aender",
    "oeffn",
    "schluessel",
    "wuerde",
    "natuerlich",
    "spaet",
)

STATIC_ATTRS = frozenset(
    {"label", "title", "aria-label", "placeholder", "text", "name", "message", "alt", "description"}
)
I18N_KEY = re.compile(r"^(core|parent|admin|kids|world)(\.[A-Za-z0-9_]*)+\.?$")


def _word_pattern(words: Iterable[str], stems: Iterable[str] = ()) -> re.Pattern[str]:
    # \w is Unicode-aware, so "der" inside "précéder" is no word of its own.
    parts = [rf"(?<!\w){re.escape(word)}(?!\w)" for word in words]
    parts += [rf"(?<!\w){re.escape(stem)}" for stem in stems]
    return re.compile("|".join(parts) + f"|[{GERMAN_CHARS}]", re.IGNORECASE)


FRONTEND_GERMAN = _word_pattern(FRONTEND_WORDS)
FOREIGN_GERMAN = _word_pattern(FOREIGN_WORDS, FOREIGN_STEMS)
ASCII_REPLACEMENT = re.compile("|".join(ASCII_REPLACEMENTS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Small JavaScript and Vue scanner (comments removed, literals with line numbers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Literal:
    line: int
    text: str


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
_REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")


def _decode_escape(src: str, i: int) -> tuple[str, int]:
    """Decode the escape starting after a backslash at src[i]; return text and next index."""
    char = src[i]
    if char == "u":
        if src[i + 1] == "{":
            end = src.index("}", i)
            return chr(int(src[i + 2 : end], 16)), end + 1
        return chr(int(src[i + 1 : i + 5], 16)), i + 5
    if char == "x":
        return chr(int(src[i + 1 : i + 3], 16)), i + 3
    if char == "\n":
        return "", i + 1
    return _ESCAPES.get(char, char), i + 1


def _line_at(src: str, index: int, base: int) -> int:
    return base + src.count("\n", 0, index)


def js_literals(src: str, base: int = 1) -> list[Literal]:
    """All string and template literals of a JavaScript snippet, comments skipped.

    Template literals yield their static parts joined by "${}"; the expressions
    inside ${...} are scanned recursively.
    """
    found: list[Literal] = []
    i, n = 0, len(src)
    last = ""
    while i < n:
        char = src[i]
        if src.startswith("//", i):
            end = src.find("\n", i)
            i = n if end < 0 else end
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        if char in "'\"":
            start, i, out = i, i + 1, []
            while i < n and src[i] != char:
                if src[i] == "\\":
                    text, i = _decode_escape(src, i + 1)
                    out.append(text)
                else:
                    out.append(src[i])
                    i += 1
            found.append(Literal(_line_at(src, start, base), "".join(out)))
            i += 1
            last = char
            continue
        if char == "`":
            start, i, out = i, i + 1, []
            while i < n and src[i] != "`":
                if src[i] == "\\":
                    text, i = _decode_escape(src, i + 1)
                    out.append(text)
                elif src.startswith("${", i):
                    depth, j = 1, i + 2
                    while j < n and depth:
                        if src[j] == "{":
                            depth += 1
                        elif src[j] == "}":
                            depth -= 1
                        elif src[j] in "'\"`":
                            # Skip nested literals so their braces do not count.
                            quote, j = src[j], j + 1
                            while j < n and src[j] != quote:
                                j += 2 if src[j] == "\\" else 1
                        j += 1
                    found.extend(js_literals(src[i + 2 : j - 1], _line_at(src, i, base)))
                    out.append("${}")
                    i = j
                else:
                    out.append(src[i])
                    i += 1
            found.append(Literal(_line_at(src, start, base), "".join(out)))
            i += 1
            last = "`"
            continue
        if char == "/" and (
            last in _REGEX_PRECEDERS or last == "" or re.search(r"\breturn\s*$", src[max(0, i - 8) : i])
        ):
            # Regular expression literal: skip it, it is never user-visible text.
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            i = j + 1
            last = "/"
            continue
        if not char.isspace():
            last = char
        i += 1
    return found


_TAG = re.compile(
    r"<(/?)([A-Za-z][\w.-]*)((?:\s+[^\s=>/\"']+(?:\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))?)*)\s*/?>",
    re.DOTALL,
)
_ATTR = re.compile(r"([^\s=>/\"']+)(?:\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+)))?", re.DOTALL)
_MUSTACHE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def _blank(match: re.Match[str]) -> str:
    """Replace a match by spaces, keeping newlines so line numbers stay right."""
    return re.sub(r"[^\n]", " ", match.group(0))


def template_literals(src: str, base: int) -> list[Literal]:
    """Text nodes, static text attributes and literals in expressions of a Vue template."""
    src = re.sub(r"<!--.*?-->", _blank, src, flags=re.DOTALL)
    found: list[Literal] = []

    def text_node(text: str, offset: int) -> None:
        cursor = 0
        for match in _MUSTACHE.finditer(text):
            static = text[cursor : match.start()]
            if static.strip():
                found.append(
                    Literal(
                        _line_at(src, offset + cursor + len(static) - len(static.lstrip()), base),
                        " ".join(static.split()),
                    )
                )
            found.extend(js_literals(match.group(1), _line_at(src, offset + match.start(), base)))
            cursor = match.end()
        static = text[cursor:]
        if static.strip():
            lead = len(static) - len(static.lstrip())
            found.append(Literal(_line_at(src, offset + cursor + lead, base), " ".join(static.split())))

    position = 0
    for tag in _TAG.finditer(src):
        text_node(src[position : tag.start()], position)
        attr_offset = tag.start(3)
        for attr in _ATTR.finditer(tag.group(3)):
            name = attr.group(1)
            value = next((group for group in attr.groups()[1:] if group is not None), None)
            if value is None:
                continue
            value_offset = attr_offset + attr.start(
                2 if attr.group(2) is not None else 3 if attr.group(3) is not None else 4
            )
            line = _line_at(src, value_offset, base)
            if name.startswith((":", "@", "#", "v-")):
                found.extend(js_literals(value, line))
            elif name in STATIC_ATTRS and value.strip():
                found.append(Literal(line, value))
        position = tag.end()
    text_node(src[position:], position)
    return found


def vue_literals(src: str) -> list[Literal]:
    """Literals of a single-file component: template part and script part."""
    found: list[Literal] = []
    start = src.find("<template")
    end = src.rfind("</template>")
    if start >= 0 and end > start:
        open_end = src.index(">", start) + 1
        found.extend(template_literals(src[open_end:end], _line_at(src, open_end, 1)))
    for script in re.finditer(r"<script[^>]*>(.*?)</script>", src, re.DOTALL):
        found.extend(js_literals(script.group(1), _line_at(src, script.start(1), 1)))
    return found


def file_literals(path: Path) -> list[Literal]:
    src = path.read_text(encoding="utf-8")
    if path.suffix == ".vue":
        return vue_literals(src)
    if path.suffix in {".js", ".mjs"}:
        return js_literals(src)
    return []


def german_findings(literals: Iterable[Literal]) -> list[Literal]:
    """Literals with a German marker; dictionary keys never count as visible text."""
    return [lit for lit in literals if not I18N_KEY.match(lit.text) and FRONTEND_GERMAN.search(lit.text)]


def _frontend_files() -> list[Path]:
    return sorted(
        path
        for path in FRONTEND_SRC.rglob("*")
        if path.is_file() and path.suffix in {".vue", ".js"} and I18N_DIR not in path.parents
    )


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _read_tsv(path: Path, columns: int) -> list[list[str]]:
    rows: list[list[str]] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        parts = raw.split("\t")
        assert len(parts) == columns, f"{path.name}:{number}: expected {columns} columns, got {len(parts)}"
        assert parts[-1].strip(), f"{path.name}:{number}: reason missing"
        rows.append(parts)
    return rows


# ---------------------------------------------------------------------------
# Part 1: no German hard-coded text outside the dictionaries
# ---------------------------------------------------------------------------


def test_scanner_positive_control() -> None:
    """Injected German text is reported in a template, a script literal and an attribute."""
    sample = (
        "<template>\n"
        "  <div>\n"
        "    <!-- Bitte nicht melden: Kommentar -->\n"
        "    Bitte warten\n"
        '    <NcButton label="Speichern" :text="t(\'kids.common.save\')" />\n'
        "    <span>{{ ok ? 'Spieler fehlt' : t('core.x') }}</span>\n"
        "  </div>\n"
        "</template>\n"
        "<script setup>\n"
        "// Die Welt ist weg (comment, ignored)\n"
        "const done = 'Welt gel" + OE + "scht'\n"
        "const key = 'parent.view.restart.access'\n"
        "const re = /'die'/\n"
        "const tpl = `Noch ${count} Minuten`\n"
        "</script>\n"
    )
    found = {(lit.line, lit.text) for lit in german_findings(vue_literals(sample))}
    assert (4, "Bitte warten") in found
    assert (11, "Welt gel" + OE + "scht") in found
    assert (6, "Spieler fehlt") in found
    assert (14, "Noch ${} Minuten") in found
    assert not any("Kommentar" in text or "comment" in text for _, text in found)
    assert not any(text.startswith("parent.") for _, text in found)
    # label="Speichern" has no marker word, but the static attribute itself is read.
    attrs = {(lit.line, lit.text) for lit in vue_literals(sample)}
    assert (5, "Speichern") in attrs
    assert german_findings([Literal(1, "Speichern f" + UE + "r sp" + AE + "ter")])


def test_no_german_hard_coded_text_outside_dictionaries() -> None:
    findings = {
        (_rel(path), str(lit.line), lit.text)
        for path in _frontend_files()
        for lit in german_findings(file_literals(path))
    }
    rows = _read_tsv(EXCEPTIONS_TSV, 4)
    allowed = {(file, line, literal) for file, line, literal, _reason in rows}
    for file, line, literal, _reason in rows:
        source_line = (ROOT / file).read_text(encoding="utf-8").splitlines()[int(line) - 1]
        # Template literals are reported with their expressions folded to "${}".
        source_line = re.sub(r"\$\{[^}]*\}", "${}", source_line)
        assert literal in source_line, f"{file}:{line}: exception literal {literal!r} not on that line"
    unexpected = sorted(findings - allowed)
    stale = sorted(allowed - findings)
    assert not unexpected, "German text outside frontend/src/i18n:\n" + "\n".join(map(repr, unexpected))
    assert not stale, "Stale entries in frontend_i18n_exceptions.tsv:\n" + "\n".join(map(repr, stale))


# ---------------------------------------------------------------------------
# Dictionary and backend value collectors
# ---------------------------------------------------------------------------


def dictionary_values(path: Path) -> dict[str, str]:
    """Key/value pairs of one flat dictionary file (export default { 'key': 'value' })."""
    literals = js_literals(path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    index = 0
    while index < len(literals):
        key = literals[index].text
        assert I18N_KEY.match(key), f"{_rel(path)}:{literals[index].line}: unexpected literal {key!r}"
        assert index + 1 < len(literals), f"{_rel(path)}: key {key!r} without value"
        values[key] = literals[index + 1].text
        index += 2
    return values


def _dictionaries(language: str) -> Iterator[tuple[str, str, str]]:
    for path in sorted((I18N_DIR / language).glob("*.js")):
        if path.name == "index.js":
            continue
        for key, value in dictionary_values(path).items():
            yield _rel(path), key, value


def _constant_text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "{}" for part in node.values)  # type: ignore[union-attr]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _constant_text(node.left), _constant_text(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def backend_german_constants() -> Iterator[tuple[str, str, str]]:
    """Module-level MSG_*/TEXT_* string constants of the backend (German sources)."""
    for path in sorted(BACKEND_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [cast("ast.expr", node.target)], node.value
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.startswith(("MSG_", "TEXT_")):
                    text = _constant_text(value)
                    if text is not None:
                        yield _rel(path), target.id, text


def _bundles() -> dict[str, dict[str, object]]:
    from gameworld.notify import texts
    from gameworld.provisioner import access_mod, time_mod

    return {
        "src/gameworld/provisioner/access_mod.py": dict(access_mod.MOD_TEXTS),
        "src/gameworld/provisioner/time_mod.py": dict(time_mod.MOD_TEXTS),
        "src/gameworld/notify/texts.py:NOTIFY_TEXTS": dict(texts.NOTIFY_TEXTS),
        "src/gameworld/notify/texts.py:BOT_TEXTS": dict(texts.BOT_TEXTS),
    }


def _bundle_values(language: str) -> Iterator[tuple[str, str, str]]:
    for source, bundle in _bundles().items():
        entry = bundle[language]
        file = source.split(":")[0]
        name = source.split(":")[1] if ":" in source else "MOD_TEXTS"
        for field, value in entry._asdict().items():  # type: ignore[attr-defined]
            if isinstance(value, str):
                yield file, f"{name}.{language}.{field}", value


def _catalog_values(language: str) -> Iterator[tuple[str, str, str]]:
    import importlib

    module = importlib.import_module(f"gameworld.i18n.catalog_{language}")
    file = f"src/gameworld/i18n/catalog_{language}.py"
    for table in ("MESSAGES", "TEMPLATES"):
        for value in getattr(module, table).values():
            yield file, table, value


# ---------------------------------------------------------------------------
# Part 2: umlaut audit of the German values
# ---------------------------------------------------------------------------


def ascii_replacements(text: str) -> list[str]:
    return [match.group(0) for match in ASCII_REPLACEMENT.finditer(text)]


def test_umlaut_audit_positive_control() -> None:
    assert ascii_replacements("Das gilt fuer alle") == ["fuer"]
    assert ascii_replacements("Spaeter loeschen") == ["Spaeter", "loeschen"]
    assert ascii_replacements("Zugaenge ueberpruefen, geloescht") == ["Zugaenge", "ueber", "loesch"]
    assert not ascii_replacements("F" + UE + "r alle, sp" + AE + "ter l" + OE + "schen")


def _german_values() -> Iterator[tuple[str, str, str]]:
    yield from _dictionaries("de")
    yield from backend_german_constants()
    yield from _bundle_values("de")


def test_collectors_find_values() -> None:
    """Positive control for the collectors: known values appear in each source."""
    de = {key: value for _file, key, value in _dictionaries("de")}
    assert de["world.language.label"] == "Sprache im Spiel"
    assert len(de) > 300
    constants = {name for _file, name, _value in backend_german_constants()}
    assert len(constants) > 50
    assert any(name.startswith("TEXT_") for name in constants)
    assert len(list(_catalog_values("en"))) > 100
    assert len(list(_catalog_values("fr"))) > 100
    assert {key.split(".")[0] for _file, key, _value in _bundle_values("en")} == {
        "MOD_TEXTS",
        "NOTIFY_TEXTS",
        "BOT_TEXTS",
    }


def test_german_values_use_real_umlauts() -> None:
    bad = [(file, key, hits) for file, key, value in _german_values() if (hits := ascii_replacements(value))]
    assert not bad, "ASCII replacement spellings in German texts:\n" + "\n".join(map(repr, bad))


# ---------------------------------------------------------------------------
# Part 3: no German leftovers in English and French values and documents
# ---------------------------------------------------------------------------


_TOKEN_STRIP = "\"'`()[]{}<>,.;:!?*_" + chr(0xA0) + chr(0xAB) + chr(0xBB) + chr(0x2019)


def german_tokens(text: str) -> set[str]:
    """Whitespace-delimited tokens of text that carry a German marker.

    Markdown links are split at "](" so a link text and its target count separately.
    """
    tokens: set[str] = set()
    for token in re.split(r"[\s" + chr(0xA0) + r"]+|\]\(", text):
        if FOREIGN_GERMAN.search(token):
            tokens.add(token.strip(_TOKEN_STRIP))
    return tokens


def _foreign_values() -> Iterator[tuple[str, str, str]]:
    for language in ("en", "fr"):
        yield from _dictionaries(language)
        yield from _catalog_values(language)
        yield from _bundle_values(language)


def _section(text: str, start: str, end: str) -> str:
    begin = text.index(start)
    return text[text.index("\n", begin) : text.index(end, begin)]


def _foreign_documents() -> Iterator[tuple[str, str, str]]:
    for name in ("README.md", "README.fr.md", "docs/install.md", "docs/privacy.md"):
        yield name, "doc", (ROOT / name).read_text(encoding="utf-8")
    listing = (ROOT / "docs" / "store-listing.md").read_text(encoding="utf-8")
    yield "docs/store-listing.md", "en", _section(listing, "## Englisch", "## Deutsch")
    yield "docs/store-listing.md", "fr", _section(listing, "## Franz" + OE + "sisch", "## Was bewusst")


def foreign_findings(entries: Iterable[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    return {(file, key, token) for file, key, value in entries for token in german_tokens(value)}


def test_foreign_audit_positive_control() -> None:
    """One injected German sentence each in en and fr is reported, real words are not."""
    entries = [
        ("en.js", "x.en", "Please wait, die Welt wird gerade gesichert."),
        ("fr.js", "x.fr", "Le monde est pr" + chr(0xEA) + "t. Bitte warten, noch 5 Minuten."),
        (
            "ok.js",
            "x.ok",
            "The world is ready. Le monde des joueurs est pr" + chr(0xEA) + "t, Fran" + chr(0xE7) + "ais.",
        ),
        ("path.js", "x.path", "Files folder Gameworld/Sicherungen and Gr" + OE + chr(0xDF) + "e"),
    ]
    found = foreign_findings(entries)
    assert {token for file, _key, token in found if file == "en.js"} == {"die", "Welt", "wird", "gerade"}
    assert {token for file, _key, token in found if file == "fr.js"} == {"Bitte", "noch", "Minuten"}
    assert not [item for item in found if item[0] == "ok.js"]
    assert {token for file, _key, token in found if file == "path.js"} == {
        "Gameworld/Sicherungen",
        "Gr" + OE + chr(0xDF) + "e",
    }
    # Documents: the section cut of the store listing keeps the German part out.
    assert "Was diese App darf" not in next(text for _f, key, text in _foreign_documents() if key == "en")
    assert "Ce que fait Gameworld" in next(text for _f, key, text in _foreign_documents() if key == "fr")


def _check_against(findings: set[tuple[str, str, str]], scope: set[str]) -> None:
    rows = _read_tsv(FOREIGN_EXCEPTIONS_TSV, 4)
    allowed = {(file, key, literal) for file, key, literal, _reason in rows if file in scope}
    unexpected = sorted(findings - allowed)
    stale = sorted(allowed - findings)
    assert not unexpected, "German leftovers in en/fr:\n" + "\n".join(map(repr, unexpected))
    assert not stale, "Stale entries in i18n_foreign_exceptions.tsv:\n" + "\n".join(map(repr, stale))


def test_no_german_in_english_and_french_values() -> None:
    entries = list(_foreign_values())
    _check_against(foreign_findings(entries), {file for file, _key, _value in entries})


def test_no_german_in_english_and_french_documents() -> None:
    entries = list(_foreign_documents())
    _check_against(foreign_findings(entries), {file for file, _key, _value in entries})


# ---------------------------------------------------------------------------
# Part 4: typography of the frontend sources
# ---------------------------------------------------------------------------


_EMOJI = re.compile("[" + chr(0x1F300) + "-" + chr(0x1FAFF) + chr(0x2600) + "-" + chr(0x27BF) + chr(0xFE0F) + "]")
_DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")


def test_typography_positive_control() -> None:
    assert _DASHES.search("a " + chr(0x2014) + " b")
    assert _EMOJI.search("ok " + chr(0x1F600))
    assert not _DASHES.search("a - b")
    assert not _EMOJI.search("ok")


@pytest.mark.parametrize("path", sorted(p for p in FRONTEND_SRC.rglob("*") if p.is_file()), ids=_rel)
def test_frontend_sources_have_no_dashes_or_emoji(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert not _DASHES.search(text), f"{_rel(path)}: en or em dash"
    assert not _EMOJI.search(text), f"{_rel(path)}: emoji"
