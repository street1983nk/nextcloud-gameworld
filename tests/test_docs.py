"""Public docs: fixed anchors, language versions, links and typography (06-11, T-06-50).

Store users have no repository. The setup check and the section
"Reste früherer Installationen" therefore link fixed URLs to docs/install.md; a renamed anchor
would be a dead link in every error message. These tests tie the URL constants from
the code to the anchors in both language versions.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest

from gameworld.provisioner.setup_check import DOCS_URL

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
ORPHANS_JS = ROOT / "frontend" / "src" / "orphans.js"
BLOB = "https://github.com/street1983nk/nextcloud-gameworld/blob/master/"

INSTALL = DOCS / "install.md"
INSTALL_DE = DOCS / "install.de.md"
PRIVACY = DOCS / "privacy.md"
PRIVACY_DE = DOCS / "privacy.de.md"
READMES = [ROOT / "README.md", ROOT / "README.de.md", ROOT / "README.fr.md"]
STORE_LISTING = DOCS / "store-listing.md"

PUBLIC_DOCS = sorted(DOCS.glob("*.md")) + READMES

# Emoji blocks (pictographs, symbols, dingbats, variation selector); arrows and
# mathematical symbols stay allowed.
DASHES = (chr(0x2013), chr(0x2014))  # en dash and em dash
EMOJI = re.compile(f"[{chr(0x1F000)}-{chr(0x1FAFF)}{chr(0x2600)}-{chr(0x27BF)}{chr(0xFE0F)}]")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ids(text: str) -> set[str]:
    return set(re.findall(r'<a id="([^"]+)"></a>', text))


def _slug(heading: str) -> str:
    """GitHub anchor of a heading: lowercase, punctuation removed, spaces to hyphens."""
    text = unicodedata.normalize("NFC", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def _anchors(text: str) -> set[str]:
    headings = re.findall(r"^#{1,6} (.+)$", text, flags=re.MULTILINE)
    return _ids(text) | {_slug(h) for h in headings}


def _url_anchor(url: str) -> tuple[str, str]:
    assert url.startswith(BLOB), url
    path, _, anchor = url.removeprefix(BLOB).partition("#")
    return path, anchor


def _cleanup_docs_url() -> str:
    match = re.search(r"export const CLEANUP_DOCS_URL = '([^']+)'", _read(ORPHANS_JS))
    assert match is not None, "CLEANUP_DOCS_URL fehlt in frontend/src/orphans.js"
    return match.group(1)


@pytest.mark.parametrize("path", [INSTALL, INSTALL_DE], ids=lambda p: p.name)
def test_install_has_fixed_anchors(path: Path) -> None:
    ids = _ids(_read(path))
    assert "setup-check" in ids
    assert "cleanup" in ids


def test_setup_check_url_points_at_anchor() -> None:
    path, anchor = _url_anchor(DOCS_URL)
    assert path == "docs/install.md"
    assert anchor == "setup-check"
    assert anchor in _ids(_read(ROOT / path))


def test_cleanup_url_points_at_anchor() -> None:
    path, anchor = _url_anchor(_cleanup_docs_url())
    assert path == "docs/install.md"
    assert anchor == "cleanup"
    assert anchor in _ids(_read(ROOT / path))


def test_anchors_precede_their_sections() -> None:
    """The anchor sits directly before the matching heading, in both versions."""
    for path, setup, cleanup in [
        (INSTALL, "## 7. Setup check", "## 13. Uninstalling and cleaning up"),
        (INSTALL_DE, "## 7. Setup-Check", "## 13. Deinstallieren und aufräumen"),
    ]:
        text = _read(path)
        assert f'<a id="setup-check"></a>\n\n{setup}\n' in text, path.name
        assert f'<a id="cleanup"></a>\n\n{cleanup}\n' in text, path.name


@pytest.mark.parametrize(
    ("path", "other"),
    [
        (PRIVACY, "privacy.de.md"),
        (PRIVACY_DE, "privacy.md"),
        (INSTALL, "install.de.md"),
        (INSTALL_DE, "install.md"),
    ],
    ids=lambda v: v.name if isinstance(v, Path) else v,
)
def test_language_versions_link_each_other(path: Path, other: str) -> None:
    head = "\n".join(_read(path).splitlines()[:12])
    assert f"]({other})" in head


def test_install_versions_share_structure() -> None:
    """Same structure: the same number of main and sub sections, same numbers."""

    def numbers(text: str) -> list[str]:
        return re.findall(r"^## (\d+)\. ", text, flags=re.MULTILINE)

    en, de = _read(INSTALL), _read(INSTALL_DE)
    assert numbers(en) == numbers(de) == [str(n) for n in range(1, 14)]
    assert len(re.findall(r"^### ", en, flags=re.MULTILINE)) == len(re.findall(r"^### ", de, flags=re.MULTILINE))


@pytest.mark.parametrize("path", [PRIVACY, PRIVACY_DE], ids=lambda p: p.name)
def test_privacy_names_privileges(path: Path) -> None:
    text = _read(path)
    for word in (
        "CONTAINERS",
        "IMAGES",
        "POST",
        "VOLUMES",
        "UDP",
        "nextcloud-aio",
        "uid 10001",
        "gameworld-orphans.sh",
    ):
        assert word in text, (path.name, word)


def test_privacy_section_first() -> None:
    """D-11: the privileges section comes directly after the short version."""
    en = re.findall(r"^## (.+)$", _read(PRIVACY), flags=re.MULTILINE)
    de = re.findall(r"^## (.+)$", _read(PRIVACY_DE), flags=re.MULTILINE)
    assert en[:2] == ["The short version", "What this app may do and why"]
    assert de[:2] == ["Kurz gesagt", "Was diese App darf und warum"]


@pytest.mark.parametrize("path", PUBLIC_DOCS, ids=lambda p: p.name)
def test_no_dashes_or_emojis(path: Path) -> None:
    text = _read(path)
    for dash in DASHES:
        assert dash not in text
    assert EMOJI.search(text) is None


@pytest.mark.parametrize("path", PUBLIC_DOCS, ids=lambda p: p.name)
def test_relative_links_resolve(path: Path) -> None:
    text = _read(path)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        file_part, _, anchor = target.partition("#")
        linked = (path.parent / file_part).resolve() if file_part else path
        assert linked.is_file(), (path.name, target)
        if anchor:
            assert anchor in _anchors(_read(linked)), (path.name, target)


def _mermaid(path: Path) -> str:
    match = re.search(r"```mermaid\n.*?```", _read(path), flags=re.DOTALL)
    assert match is not None, path.name
    return match.group(0)


def test_readmes_language_switch_and_sections() -> None:
    for path in READMES:
        text = _read(path)
        first = text.splitlines()[0]
        for name in ("README.md", "README.de.md", "README.fr.md"):
            if name != path.name:
                assert f"]({name})" in first, (path.name, name)
        assert "img.shields.io" in text
        assert "actions/workflows/image.yml" in text
        assert "AGPL--3.0--or--later" in text
        assert "Nextcloud-32--35" in text
        assert "\n## Screenshots\n" in text
        assert "docs/install" in text
        assert "docs/privacy" in text
        assert "gameworld-orphans.sh" in text


def test_readme_mermaid_identical() -> None:
    blocks = {_mermaid(path) for path in READMES}
    assert len(blocks) == 1
    block = blocks.pop()
    for node in ("AppAPI", "HaRP", "Gameworld ExApp", "docker-socket-proxy", "World container", "Nextcloud Files"):
        assert node in block, node


def test_readme_fr_links_english_docs() -> None:
    text = _read(ROOT / "README.fr.md")
    assert ".de.md" not in text.replace("README.de.md", "")


def test_store_listing_draft_marker() -> None:
    text = _read(STORE_LISTING)
    assert "Abnahme: offen" in text
    assert "## Was bewusst nicht drinsteht" in text
