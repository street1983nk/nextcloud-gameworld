"""ZUGANG-01: Die Oberfläche bietet nirgends an, eine Welt öffentlich zu machen."""

from __future__ import annotations

from pathlib import Path

import pytest

FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
FORBIDDEN = ("announce", "serverlist", "public", "visibility", "öffentlich machen", "sichtbar machen")
# Browser-API der Page Visibility (Polling nur bei sichtbarem Tab, 02-04): kein
# Schalter für Weltsichtbarkeit, wird vor der Suche entfernt.
DOM_ALLOWED = ("document.visibilitystate", "'visibilitychange'")


def _sources() -> list[Path]:
    return sorted(path for path in FRONTEND_SRC.rglob("*") if path.is_file())


def _text(path: Path) -> str:
    text = path.read_text(encoding="utf-8").lower()
    for allowed in DOM_ALLOWED:
        text = text.replace(allowed, "")
    return text


def test_dom_allowlist_does_not_hide_visibility_options() -> None:
    """Gegenprobe: Ein Feld "visibility" bleibt verboten, nur die DOM-API ist ausgenommen."""
    sample = "document.visibilityState === 'visible'; addEventListener('visibilitychange'); { visibility: 'x' }"
    stripped = sample.lower()
    for allowed in DOM_ALLOWED:
        stripped = stripped.replace(allowed, "")
    assert "visibility" in stripped
    assert stripped.count("visibility") == 1


def test_frontend_sources_exist() -> None:
    names = {path.name for path in _sources()}
    assert {"main.js", "api.js", "App.vue"} <= names


@pytest.mark.parametrize("term", FORBIDDEN)
def test_no_publish_option_in_frontend(term: str) -> None:
    hits = [str(path) for path in _sources() if term in _text(path)]
    assert hits == [], f"{term!r} kommt vor in {hits}"
