"""ExApp manifest: version in lockstep, fixed routes before the catch-all, everything USER, env variables, NC window."""

from __future__ import annotations

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INFO_XML = ROOT / "appinfo" / "info.xml"


def _root() -> ET.Element:
    return ET.parse(INFO_XML).getroot()  # noqa: S314 - own, versioned file


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path)
    assert found is not None, path
    return (found.text or "").strip()


def test_id_and_version_lockstep() -> None:
    root = _root()
    assert _text(root, "id") == "gameworld"
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert _text(root, "version") == project["version"] == "1.0.0"


def test_image_tag_lockstep() -> None:
    """T-06-45: store archive and image run on the same version (image.yml checks the same)."""
    root = _root()
    docker = root.find("./external-app/docker-install")
    assert docker is not None
    assert _text(docker, "registry") == "ghcr.io"
    assert _text(docker, "image") == "street1983nk/gameworld"
    assert _text(docker, "image-tag") == _text(root, "version")


EXPECTED_ROUTES = [
    ("^/js/.*", "GET", "USER"),
    ("^/img/.*", "GET", "USER"),
    ("^/api/me$", "GET", "USER"),
    ("^/api/my/.*", "GET", "USER"),
    ("^/api/my/play-ticket$", "POST", "USER"),
    ("^/play/.*", "GET,POST", "USER"),
    ("^/talk/bot$", "POST", "USER"),
    ("^/api/.*", "GET,POST,DELETE", "USER"),
]


def _routes() -> list[tuple[str, str, str]]:
    return [
        (_text(route, "url"), _text(route, "verb"), _text(route, "access_level"))
        for route in _root().findall("./external-app/routes/route")
    ]


def test_route_order_and_levels() -> None:
    """The first matching route wins: fixed routes first, the catch-all of the administration behind it (USER)."""
    assert _routes() == EXPECTED_ROUTES


def test_user_routes_are_anchored_or_static() -> None:
    """AppAPI appends no end anchor: fixed routes under /api/ need "$" or ^/api/my/.

    Only the catch-all ^/api/.* as the last route is excepted (USER since phase 6).
    """
    for url, _verb, level in _routes()[:-1]:
        if level == "USER" and url.startswith("^/api/"):
            assert url.endswith("$") or url == "^/api/my/.*", url


def test_talk_bot_route_is_anchored_post_before_admin() -> None:
    """Webhook of the Gameworld bot (04.1-06): POST only, firmly anchored, before the catch-all ^/api/.*."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/talk/bot$", "POST", "USER") in routes
    assert urls.index("^/talk/bot$") < urls.index("^/api/.*")


def test_play_routes_before_admin() -> None:
    """Browser spike 04.2: ticket (POST only, anchored) and play page come before the catch-all ^/api/.*."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/api/my/play-ticket$", "POST", "USER") in routes
    assert ("^/play/.*", "GET,POST", "USER") in routes
    assert urls.index("^/api/my/play-ticket$") < urls.index("^/api/.*")
    assert urls.index("^/play/.*") < urls.index("^/api/.*")


def test_api_catch_all_is_last_and_no_admin_level() -> None:
    """Since phase 6 no AppAPI ADMIN level (F-03); the block is evidenced by tests/test_route_guards.py."""
    routes = _routes()
    assert routes[-1] == ("^/api/.*", "GET,POST,DELETE", "USER")
    assert [level for _url, _verb, level in routes].count("ADMIN") == 0
    assert "<access_level>ADMIN</access_level>" not in INFO_XML.read_text(encoding="utf-8")


def test_environment_defaults() -> None:
    variables = {
        _text(var, "name"): _text(var, "default")
        for var in _root().findall("./external-app/environment-variables/variable")
    }
    assert variables["GAMEWORLD_DOCKER_URL"] == "tcp://gameworld-docker-proxy:2375"
    assert variables["GAMEWORLD_PORT_RANGE"] == "30000-30019"


def test_nextcloud_window() -> None:
    nextcloud = _root().find("./dependencies/nextcloud")
    assert nextcloud is not None
    assert nextcloud.get("min-version") == "33"
    assert nextcloud.get("max-version") == "35"


def test_no_public_or_announce_setting() -> None:
    content = INFO_XML.read_text(encoding="utf-8").lower()
    assert "announce" not in content
    assert "public" not in content


# --- Store texts (06-11, D-09, D-11, T-06-48) -------------------------------------------

LANGS = {None, "de", "fr"}
PRIVILEGES_HEADING = {
    None: "What this app may do and why",
    "de": "Was diese App darf und warum",
    "fr": "Ce que cette application peut faire et pourquoi",
}
# D-25: the interface follows the account language (de, en, fr); in-game texts follow the world.
INTERFACE_LINE = {
    None: "- Interface: German, English, French (follows the Nextcloud account language); in-game texts per world",
    "de": "- Oberfläche: Deutsch, Englisch, Französisch (folgt der Nextcloud-Kontosprache); Spieltexte je Welt",
    "fr": "- Interface : allemand, anglais, français (selon la langue du compte Nextcloud) ; textes du jeu par monde",
}
# Lines from before D-25 that must be gone, not merely extended.
OLD_INTERFACE_LINES = {"- Interface: German", "- Oberfläche: Deutsch", "- Interface : allemand"}
SCREENSHOT_BASE = "https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/master/docs/screenshots/"
SCREENSHOTS = [
    "worlds-v1-en.png",
    "invite-v1-en.png",
    "kids-view-v1-en.png",
    "backups-v1-en.png",
    "playtime-v1-en.png",
    "mobile-v1-en.png",
]
DOC_BASE = "https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/"

# Order of elements according to info.xsd; an element in the wrong place fails on upload.
XSD_ORDER = [
    "id",
    "name",
    "summary",
    "description",
    "version",
    "licence",
    "author",
    "namespace",
    "documentation",
    "category",
    "website",
    "bugs",
    "repository",
    "screenshot",
    "dependencies",
    "external-app",
]


def _by_lang(tag: str) -> dict[str | None, str]:
    found: dict[str | None, str] = {}
    for element in _root().findall(tag):
        lang = element.get("lang")
        assert lang not in found, (tag, lang)
        found[lang] = (element.text or "").strip()
    return found


@pytest.mark.parametrize("tag", ["summary", "description"])
def test_store_texts_in_three_languages(tag: str) -> None:
    texts = _by_lang(tag)
    assert set(texts) == LANGS
    assert all(texts.values()), tag


def test_name_exactly_once_without_lang() -> None:
    """AppAPI reads info.xml via simplexml/json; several <name> become an array.

    Verified on 24.10.2026 with occ app_api:app:register --info-xml via HaRP (06-12):
    the app was then called "Array" (ExAppService::getAppInfo -> setName). The same
    path applies to the store installation. Hence exactly one <name>, without lang.
    """
    names = _root().findall("name")
    assert len(names) == 1
    assert names[0].get("lang") is None
    assert (names[0].text or "").strip() == "Gameworld"


def test_name_and_summary_length() -> None:
    for tag in ("name", "summary"):
        for lang, text in _by_lang(tag).items():
            assert len(text) <= 128, (tag, lang)


def test_description_leads_with_privileges() -> None:
    """D-11: after at most one introductory sentence comes the privileges section."""
    for lang, text in _by_lang("description").items():
        headings = [line for line in text.splitlines() if line.startswith("#")]
        assert headings, lang
        assert headings[0] == f"### {PRIVILEGES_HEADING[lang]}", lang
        intro = text.split(headings[0], 1)[0].strip()
        assert intro.count("\n") == 0, lang


def test_description_names_interface_language() -> None:
    for lang, text in _by_lang("description").items():
        assert INTERFACE_LINE[lang] in text.splitlines(), lang
        assert not OLD_INTERFACE_LINES & set(text.splitlines()), lang


def test_description_honest_about_uninstall() -> None:
    """D-15/D-17: volumes and backups stay, world containers are removed (T-06-51)."""
    texts = _by_lang("description")
    assert "gameworld-orphans.sh" in texts[None]
    for text in texts.values():
        assert "gameworld-orphans.sh" in text
        assert "root" in text
        assert "UDP" in text


def test_description_store_markdown_subset() -> None:
    """The store renders only headings, paragraphs, lists, links and emphasis."""
    for lang, text in _by_lang("description").items():
        assert "`" not in text, lang
        assert "|" not in text, lang
        for dash in (chr(0x2013), chr(0x2014)):
            assert dash not in text, lang


def test_categories() -> None:
    assert [element.text for element in _root().findall("category")] == ["games", "tools"]


def test_documentation_links() -> None:
    documentation = _root().find("documentation")
    assert documentation is not None
    assert _text(documentation, "user") == DOC_BASE + "install.md"
    assert _text(documentation, "admin") == DOC_BASE + "install.md"
    assert _text(documentation, "developer") == DOC_BASE + "dev-setup.md"
    for target in ("install.md", "dev-setup.md"):
        assert (ROOT / "docs" / target).is_file()


def test_six_versioned_screenshots() -> None:
    urls = [(element.text or "").strip() for element in _root().findall("screenshot")]
    assert urls == [SCREENSHOT_BASE + name for name in SCREENSHOTS]


def test_element_order_follows_xsd() -> None:
    seen = [child.tag for child in _root()]
    order = [tag for tag in XSD_ORDER if tag in seen]
    collapsed = [tag for index, tag in enumerate(seen) if index == 0 or seen[index - 1] != tag]
    assert collapsed == order


def test_store_listing_matches_info_xml() -> None:
    """docs/store-listing.md is the single source: every text appears there verbatim."""
    listing = (ROOT / "docs" / "store-listing.md").read_text(encoding="utf-8")
    for tag in ("name", "summary", "description"):
        for lang, text in _by_lang(tag).items():
            assert text in listing, (tag, lang)


# --- Cross-promotion of the sister apps (06-13, D-28, T-06-107) --------------------------

CROSS_PROMO_LEAD = {None: "From the same developer: ", "de": "Vom selben Entwickler: ", "fr": "Du même développeur : "}
SISTER_APPS = ("Findling Search", "MCP Connector")
# Marketing words that a fact-style sentence never needs (lowercase, matched as whole words).
PROMO_WORDS = {
    "best",
    "easy",
    "easily",
    "now",
    "amazing",
    "powerful",
    "simple",
    "simply",
    "beste",
    "besten",
    "einfach",
    "jetzt",
    "toll",
    "stark",
    "meilleur",
    "meilleure",
    "facile",
    "facilement",
    "maintenant",
    "puissant",
}


def _listing_section(listing: str, lang: str | None) -> str:
    """The description block of one language in docs/store-listing.md."""
    heading = "### `<description>`" if lang is None else f'### `<description lang="{lang}">`'
    start = listing.index(heading)
    fence = "```markdown\n"
    block_start = listing.index(fence, start) + len(fence)
    return listing[block_start : listing.index("\n```", block_start)]


def _cross_promo_sentence(listing: str, lang: str | None) -> str:
    lines = [line for line in _listing_section(listing, lang).splitlines() if line.startswith(CROSS_PROMO_LEAD[lang])]
    assert len(lines) == 1, (lang, lines)
    return lines[0]


def _cross_promo_problems(sentence: str, description: str) -> list[str]:
    """Empty if the sentence names both sister apps, is plain fact and sits once, verbatim, at the end."""
    problems = []
    if description.count(sentence) != 1:
        problems.append("not exactly once in the description")
    if not description.rstrip().endswith(sentence):
        problems.append("not at the end of the description")
    for app in SISTER_APPS:
        if sentence.count(app) != 1:
            problems.append(f"names {app} not exactly once")
    words = set(re.findall(r"[^\W\d_]+", sentence.lower()))
    if words & PROMO_WORDS:
        problems.append(f"marketing words {sorted(words & PROMO_WORDS)}")
    if sentence.count(".") != 1 or not sentence.endswith("."):
        problems.append("not exactly one sentence")
    return problems


def test_cross_promo_sentence_per_language() -> None:
    listing = (ROOT / "docs" / "store-listing.md").read_text(encoding="utf-8")
    for lang, description in _by_lang("description").items():
        sentence = _cross_promo_sentence(listing, lang)
        assert _cross_promo_problems(sentence, description) == [], lang


def test_cross_promo_check_rejects_variants() -> None:
    """Positive control: the same check refuses altered, promotional or misplaced sentences."""
    listing = (ROOT / "docs" / "store-listing.md").read_text(encoding="utf-8")
    description = _by_lang("description")[None]
    sentence = _cross_promo_sentence(listing, None)
    assert "to Nextcloud)" in sentence
    altered = sentence.replace("to Nextcloud)", "to Nextcloud files)")
    assert _cross_promo_problems(altered, description) != []
    promotional = sentence.replace("From the same developer", "Now from the same developer")
    assert _cross_promo_problems(promotional, description.replace(sentence, promotional)) != []
    missing_app = sentence.replace("MCP Connector", "another app")
    assert _cross_promo_problems(missing_app, description.replace(sentence, missing_app)) != []
    moved = sentence + "\n\nMore text."
    assert _cross_promo_problems(sentence, description.replace(sentence, moved)) != []
