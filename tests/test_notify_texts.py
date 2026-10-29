"""Parent texts of the notifications, sanitizing and deep links (04.1-04, pitfall 4, pattern 9)."""

import re

import pytest

from gameworld.notify import links, texts

DASHES = chr(0x2013) + chr(0x2014)
FORBIDDEN = re.compile(rf"%|\||[{DASHES}]|Mitternacht|(?<![0-9])0(:00)? Uhr")
FIXED_TEXTS = (
    texts.ATTEMPT_SUBJECT,
    texts.ATTEMPT_MESSAGE,
    texts.SUMMARY_SUBJECT,
    texts.SUMMARY_MESSAGE,
    texts.REVIEW_SUBJECT,
    texts.REVIEW_MESSAGE,
    texts.REVIEW_LIMIT_SUFFIX,
)


def test_clean_value_strips_format_and_control_chars() -> None:
    cleaned = texts.clean_value("Le%na|{x}\n", 20)
    for char in "%|{}\n":
        assert char not in cleaned
    assert cleaned == "Lenax"
    assert len(texts.clean_value("a" * 50, 20)) == 20


@pytest.mark.parametrize("value", ["", "%|{}", "\n\t\x00", "   "])
def test_clean_value_empty_becomes_question_mark(value: str) -> None:
    assert texts.clean_value(value, 20) == "?"


def test_fixed_texts_follow_text_rules() -> None:
    for text in FIXED_TEXTS:
        assert not FORBIDDEN.search(text), text


def test_attempt_message_keeps_values_in_highlight_params() -> None:
    subject, message, params = texts.attempt_message("abc123def456", "Baum%haus", "Fre{md}er", "18:05")
    assert subject == "Unbekannter Spielername in {world}"
    assert message == "{player} wollte um {time} beitreten."
    assert set(params) == {"world", "player", "time"}
    for param in params.values():
        assert param["type"] == "highlight"
        assert param["id"]
    assert params["world"]["name"] == "Baumhaus"
    assert params["player"]["name"] == "Fremder"
    assert params["time"]["name"] == "18:05"
    # Values never appear raw in the text.
    assert "Baum" not in subject + message
    assert "Fremd" not in subject + message


def test_attempt_message_caps_lengths() -> None:
    _subject, _message, params = texts.attempt_message("abc123def456", "W" * 99, "P" * 99, "9:00")
    assert len(params["world"]["name"]) == texts.MAX_WORLD
    assert len(params["player"]["name"]) == texts.MAX_PLAYER


def test_summary_message_has_no_placeholders() -> None:
    subject, message, params = texts.summary_message()
    assert subject == "Weitere Beitrittsversuche"
    assert message == "Heute gab es weitere Beitrittsversuche, siehe Gameworld."
    assert params == {}


def test_review_message_uses_kids_placeholder() -> None:
    subject, message, params = texts.review_message("Lena 45 Min., Tom 60 Min. (Limit erreicht)")
    assert subject == "Tagesrückblick"
    assert message == "Heute gespielt: {kids}"
    assert params["kids"]["type"] == "highlight"
    assert params["kids"]["name"] == "Lena 45 Min., Tom 60 Min. (Limit erreicht)"


def test_page_link_is_absolute_path_not_hash() -> None:
    link = links.page_link("https://cloud.example", "versuch", {"welt": "abc123def456", "tag": "2026-10-21"})
    assert link == (
        "https://cloud.example/index.php/apps/app_api/embedded/gameworld/gameworld/versuch"
        "?welt=abc123def456&tag=2026-10-21"
    )
    assert "#" not in link
    assert links.page_link("http://localhost:8091", "rueckblick", {}) == (
        "http://localhost:8091/index.php/apps/app_api/embedded/gameworld/gameworld/rueckblick"
    )


def test_page_link_rejects_unknown_page_and_long_links() -> None:
    with pytest.raises(ValueError, match="Seite"):
        links.page_link("https://cloud.example", "admin", {})
    with pytest.raises(ValueError, match="lang"):
        links.page_link("https://cloud.example", "versuch", {"x": "y" * 4000})


@pytest.mark.parametrize(
    "value",
    [
        "https://cloud.example",
        "http://localhost:8091",
        "https://192.168.1.10:8443",
        "https://[::1]:8443",
        "https://Cloud.Example.org",
        "https://example.org/nextcloud",
        "https://example.org/apps/nc-1.2_x~y",
    ],
)
def test_clean_origin_accepts_scheme_host_port(value: str) -> None:
    assert links.clean_origin(value) == value


def test_page_link_with_webroot() -> None:
    """WR-04: Nextcloud in a subfolder; the link no longer leads to the 404 under /index.php."""
    assert links.page_link("https://example.org/nextcloud", "pause", {}) == (
        "https://example.org/nextcloud/index.php/apps/app_api/embedded/gameworld/gameworld/pause"
    )


def test_join_base_origin_plus_webroot() -> None:
    assert links.join_base("https://example.org", "/nextcloud") == "https://example.org/nextcloud"
    assert links.join_base("http://localhost:8091", "") == "http://localhost:8091"


@pytest.mark.parametrize(
    ("origin", "webroot"),
    [
        ("https://example.org/pfad", ""),
        ("https://example.org", "nextcloud"),
        ("https://example.org", "/nextcloud/"),
        ("https://example.org", "/"),
        ("https://example.org", "/../admin"),
        ("https://example.org", "/a/./b"),
        ("https://example.org", "/%2e%2e"),
        ("https://example.org", "/a b"),
        ("https://example.org", "/a?x=1"),
        ("https://example.org", "/a#x"),
        ("https://example.org", "//evil.example"),
        ("https://example.org", "/a\\b"),
        ("https://example.org", "/" + "a" * 300),
    ],
)
def test_join_base_rejects_manipulated_parts(origin: str, webroot: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        links.join_base(origin, webroot)


@pytest.mark.parametrize(
    ("current", "proposed", "confirm", "store", "confirm_needed"),
    [
        (None, "http://192.168.1.10", False, True, False),
        ("https://cloud.example", "https://cloud.example", False, False, False),
        ("https://cloud.example", "https://cloud.example", True, False, False),
        ("https://cloud.example", "https://neu.example", False, False, True),
        ("https://cloud.example", "https://neu.example", True, True, False),
        ("http://192.168.1.10", "https://cloud.example", False, False, True),
        ("http://192.168.1.10", "https://cloud.example", True, True, False),
        # https is never replaced by http, not even confirmed, and without a prompt.
        ("https://cloud.example", "http://192.168.1.10", False, False, False),
        ("https://cloud.example", "http://192.168.1.10", True, False, False),
        ("https://cloud.example", "http://cloud.example", True, False, False),
    ],
)
def test_decide_origin(current: str | None, proposed: str, confirm: bool, store: bool, confirm_needed: bool) -> None:
    decision = links.decide_origin(current, proposed, confirm=confirm)
    assert (decision.store, decision.confirm_needed) == (store, confirm_needed)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "cloud.example",
        "https://cloud.example/",
        "https://cloud.example/pfad/",
        "https://cloud.example/..",
        "https://cloud.example/a/./b",
        "https://cloud.example//b",
        "https://user:pw@cloud.example",
        "https://cloud.example#x",
        "https://cloud.example?x=1",
        "javascript:x",
        "ftp://cloud.example",
        "https://cloud.example:0",
        "https://cloud.example:70000",
        "https://-bad.example",
        "https://cloud.example\n",
        "https://",
    ],
)
def test_clean_origin_rejects_everything_else(value: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        links.clean_origin(value)
