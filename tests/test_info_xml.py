"""ExApp-Manifest: Version im Lockstep, alle Routen ADMIN, Env-Variablen, NC-Fenster."""

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


def test_every_route_is_admin() -> None:
    routes = _root().findall("./external-app/routes/route")
    assert len(routes) >= 3
    by_url: dict[str, str] = {}
    for route in routes:
        assert _text(route, "access_level") == "ADMIN"
        by_url[_text(route, "url")] = _text(route, "verb")
    # Kanonische Form mit führendem Schrägstrich, wie AppAPI 34 und HaRP sie prüfen.
    assert by_url["^/js/.*"] == "GET"
    assert by_url["^/img/.*"] == "GET"
    assert set(by_url["^/api/.*"].split(",")) == {"GET", "POST", "DELETE"}


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
