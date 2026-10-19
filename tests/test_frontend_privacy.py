"""ZUGANG-01: Die Oberfläche bietet nirgends an, eine Welt öffentlich zu machen."""

from __future__ import annotations

from pathlib import Path

import pytest

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
FORBIDDEN = ("announce", "serverlist", "public", "visibility", "öffentlich machen", "sichtbar machen")


def _sources() -> list[Path]:
    return sorted(path for path in FRONTEND_SRC.rglob("*") if path.is_file())


def test_frontend_sources_exist() -> None:
    names = {path.name for path in _sources()}
    assert {"main.js", "api.js", "App.vue"} <= names


@pytest.mark.parametrize("term", FORBIDDEN)
def test_no_publish_option_in_frontend(term: str) -> None:
    hits = [str(path) for path in _sources() if term in path.read_text(encoding="utf-8").lower()]
    assert hits == [], f"{term!r} kommt vor in {hits}"
