"""i18n core (D-25): language normalization and translation with German as message ID."""

from __future__ import annotations

import pytest

from gameworld import i18n
from gameworld.access import roles
from gameworld.i18n import normalize_language, translate
from gameworld.worlds import status


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
