"""ExApp-Manifest: Version im Lockstep, feste Routen vor dem Auffangmuster, alles USER, Env-Variablen, NC-Fenster."""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INFO_XML = ROOT / "appinfo" / "info.xml"


def _root() -> ET.Element:
    return ET.parse(INFO_XML).getroot()  # noqa: S314 - eigene, versionierte Datei


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
    """T-06-45: Store-Archiv und Image laufen auf derselben Version (image.yml prüft dasselbe)."""
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
    """Erste passende Route gewinnt: feste Routen zuerst, das Auffangmuster der Verwaltung dahinter (USER)."""
    assert _routes() == EXPECTED_ROUTES


def test_user_routes_are_anchored_or_static() -> None:
    """AppAPI hängt keinen End-Anker an: feste Routen unter /api/ brauchen "$" oder ^/api/my/.

    Ausgenommen ist nur das Auffangmuster ^/api/.* als letzte Route (seit Phase 6 USER).
    """
    for url, _verb, level in _routes()[:-1]:
        if level == "USER" and url.startswith("^/api/"):
            assert url.endswith("$") or url == "^/api/my/.*", url


def test_talk_bot_route_is_anchored_post_before_admin() -> None:
    """Webhook des Gameworld-Bots (04.1-06): nur POST, fest verankert, vor dem Auffangmuster ^/api/.*."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/talk/bot$", "POST", "USER") in routes
    assert urls.index("^/talk/bot$") < urls.index("^/api/.*")


def test_play_routes_before_admin() -> None:
    """Browser-Spike 04.2: Ticket (nur POST, verankert) und Spielseite stehen vor dem Auffangmuster ^/api/.*."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/api/my/play-ticket$", "POST", "USER") in routes
    assert ("^/play/.*", "GET,POST", "USER") in routes
    assert urls.index("^/api/my/play-ticket$") < urls.index("^/api/.*")
    assert urls.index("^/play/.*") < urls.index("^/api/.*")


def test_api_catch_all_is_last_and_no_admin_level() -> None:
    """Seit Phase 6 keine AppAPI-ADMIN-Stufe (F-03); die Sperre belegt tests/test_route_guards.py."""
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
    assert nextcloud.get("min-version") == "32"
    assert nextcloud.get("max-version") == "35"


def test_no_public_or_announce_setting() -> None:
    content = INFO_XML.read_text(encoding="utf-8").lower()
    assert "announce" not in content
    assert "public" not in content


# --- Store-Texte (06-11, D-09, D-11, T-06-48) -------------------------------------------

LANGS = {None, "de", "fr"}
PRIVILEGES_HEADING = {
    None: "What this app may do and why",
    "de": "Was diese App darf und warum",
    "fr": "Ce que cette application peut faire et pourquoi",
}
INTERFACE_LINE = {None: "Interface: German", "de": "Oberfläche: Deutsch", "fr": "Interface : allemand"}
SCREENSHOT_BASE = "https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/master/docs/screenshots/"
SCREENSHOTS = [
    "worlds-v1.png",
    "invite-v1.png",
    "kids-view-v1.png",
    "backups-v1.png",
    "playtime-v1.png",
    "mobile-v1.png",
]
DOC_BASE = "https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/"

# Reihenfolge der Elemente laut info.xsd; ein Element an falscher Stelle scheitert beim Upload.
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


@pytest.mark.parametrize("tag", ["name", "summary", "description"])
def test_store_texts_in_three_languages(tag: str) -> None:
    texts = _by_lang(tag)
    assert set(texts) == LANGS
    assert all(texts.values()), tag


def test_name_and_summary_length() -> None:
    for tag in ("name", "summary"):
        for lang, text in _by_lang(tag).items():
            assert len(text) <= 128, (tag, lang)


def test_description_leads_with_privileges() -> None:
    """D-11: nach höchstens einem Einleitungssatz kommt der Privilegien-Abschnitt."""
    for lang, text in _by_lang("description").items():
        headings = [line for line in text.splitlines() if line.startswith("#")]
        assert headings, lang
        assert headings[0] == f"### {PRIVILEGES_HEADING[lang]}", lang
        intro = text.split(headings[0], 1)[0].strip()
        assert intro.count("\n") == 0, lang


def test_description_names_interface_language() -> None:
    for lang, text in _by_lang("description").items():
        assert INTERFACE_LINE[lang] in text, lang


def test_description_honest_about_uninstall() -> None:
    """D-15/D-17: Volumes und Sicherungen bleiben, Welt-Container werden entfernt (T-06-51)."""
    texts = _by_lang("description")
    assert "gameworld-orphans.sh" in texts[None]
    for text in texts.values():
        assert "gameworld-orphans.sh" in text
        assert "root" in text
        assert "UDP" in text


def test_description_store_markdown_subset() -> None:
    """Der Store rendert nur Überschriften, Absätze, Listen, Links und Hervorhebungen."""
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
    """docs/store-listing.md ist die eine Quelle: jeder Text steht dort wortgleich."""
    listing = (ROOT / "docs" / "store-listing.md").read_text(encoding="utf-8")
    for tag in ("name", "summary", "description"):
        for lang, text in _by_lang(tag).items():
            assert text in listing, (tag, lang)
