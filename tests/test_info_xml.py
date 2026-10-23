"""ExApp-Manifest: Version im Lockstep, Routen USER vor ADMIN, Env-Variablen, NC-Fenster."""

from __future__ import annotations

import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

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
    assert _text(root, "version") == project["version"]


EXPECTED_ROUTES = [
    ("^/js/.*", "GET", "USER"),
    ("^/img/.*", "GET", "USER"),
    ("^/api/me$", "GET", "USER"),
    ("^/api/my/.*", "GET", "USER"),
    ("^/api/my/play-ticket$", "POST", "USER"),
    ("^/play/.*", "GET,POST", "USER"),
    ("^/talk/bot$", "POST", "USER"),
    ("^/api/.*", "GET,POST,DELETE", "ADMIN"),
]


def _routes() -> list[tuple[str, str, str]]:
    return [
        (_text(route, "url"), _text(route, "verb"), _text(route, "access_level"))
        for route in _root().findall("./external-app/routes/route")
    ]


def test_route_order_and_levels() -> None:
    """Erste passende Route gewinnt: USER-Routen zuerst, Verwaltung als ADMIN dahinter."""
    assert _routes() == EXPECTED_ROUTES


def test_user_routes_are_anchored_or_static() -> None:
    """AppAPI hängt keinen End-Anker an: USER-Routen unter /api/ brauchen "$" oder ^/api/my/."""
    for url, _verb, level in _routes():
        if level == "USER" and url.startswith("^/api/"):
            assert url.endswith("$") or url == "^/api/my/.*", url


def test_talk_bot_route_is_anchored_post_before_admin() -> None:
    """Webhook des Gameworld-Bots (04.1-06): nur POST, fest verankert, vor dem ADMIN-Auffangmuster."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/talk/bot$", "POST", "USER") in routes
    assert urls.index("^/talk/bot$") < urls.index("^/api/.*")


def test_play_routes_before_admin() -> None:
    """Browser-Spike 04.2: Ticket (nur POST, verankert) und Spielseite stehen vor dem ADMIN-Auffangmuster."""
    routes = _routes()
    urls = [url for url, _verb, _level in routes]
    assert ("^/api/my/play-ticket$", "POST", "USER") in routes
    assert ("^/play/.*", "GET,POST", "USER") in routes
    assert urls.index("^/api/my/play-ticket$") < urls.index("^/api/.*")
    assert urls.index("^/play/.*") < urls.index("^/api/.*")


def test_admin_catch_all_is_last() -> None:
    routes = _routes()
    assert routes[-1] == ("^/api/.*", "GET,POST,DELETE", "ADMIN")
    assert [level for _url, _verb, level in routes].count("ADMIN") == 1


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
    assert nextcloud.get("max-version") == "34"


def test_no_public_or_announce_setting() -> None:
    content = INFO_XML.read_text(encoding="utf-8").lower()
    assert "announce" not in content
    assert "public" not in content
