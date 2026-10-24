"""ExApp-Manifest: Version im Lockstep, feste Routen vor dem Auffangmuster, alles USER, Env-Variablen, NC-Fenster."""

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
