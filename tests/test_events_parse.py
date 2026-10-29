"""Pure parser of the event file and cursor rule (first contact, jump back, fresh file)."""

from gameworld.events.parse import (
    FIRST_CONTACT_MAX_AGE,
    MAX_AGE,
    MAX_AHEAD,
    Event,
    new_events,
    parse_events,
    plausible,
)

NOW = 1_800_000_000


def _file(seq: int, lines: list[str], *, head: str = "gameworld-events 1", end: bool = True) -> bytes:
    body = [f"{head} {seq}", *lines]
    if end:
        body.append("end")
    return ("\n".join(body) + "\n").encode()


def _events(first: int, last: int, *, at: int = NOW - 10) -> list[Event]:
    return [Event(seq, at, "join", "lena") for seq in range(first, last + 1)]


def test_parse_valid_file() -> None:
    content = _file(3, ["1 100 join lena", "2 110 deny Fremder_1", "3 120 warn10 max-2"])
    assert parse_events(content) == (
        3,
        [Event(1, 100, "join", "lena"), Event(2, 110, "deny", "Fremder_1"), Event(3, 120, "warn10", "max-2")],
    )


def test_parse_empty_file_after_mods_loaded() -> None:
    assert parse_events(_file(0, [])) == (0, [])


def test_parse_rejects_missing_head_end_or_version() -> None:
    assert parse_events(b"") is None
    assert parse_events(_file(1, ["1 100 join lena"], end=False)) is None
    assert parse_events(_file(1, ["1 100 join lena"], head="gameworld-events 2")) is None
    assert parse_events(b"1 100 join lena\nend\n") is None
    assert parse_events(_file(1, [], head="gameworld-events 1 x")) is None


def test_parse_skips_invalid_lines() -> None:
    lines = [
        "1 100 kick lena",  # unknown kind
        "2 100 join " + "a" * 21,  # Name too long
        "3 100 join le na",  # Space in the name
        "4 100 join le%na",  # foreign character
        "1234567890123 100 join lena",  # More than 12 digits
        "5 1234567890123 join lena",  # More than 12 digits
        "6 100 join lena ",  # Rest after the name
        "7 100 join lena",
    ]
    assert parse_events(_file(7, lines)) == (7, [Event(7, 100, "join", "lena")])


def test_parse_non_ascii_does_not_raise() -> None:
    content = "gameworld-events 1 2\n1 100 join läna\n2 100 join lena\nend\n".encode()
    assert parse_events(content) == (2, [Event(2, 100, "join", "lena")])
    assert parse_events(b"\xff\xfe\x00garbage") is None


def test_first_contact_fresh_file_reports_all() -> None:
    events = _events(1, 7)
    assert new_events(None, 7, events, now=NOW) == (events, 7)


def test_first_contact_old_file_only_anchors() -> None:
    events = [*_events(1, 6), Event(7, NOW - FIRST_CONTACT_MAX_AGE - 1, "join", "lena")]
    assert new_events(None, 7, events, now=NOW) == ([], 7)


def test_first_contact_trimmed_ring_only_anchors() -> None:
    assert new_events(None, 7, _events(3, 7), now=NOW) == ([], 7)


def test_first_contact_empty_file_anchors_zero() -> None:
    assert new_events(None, 0, [], now=NOW) == ([], 0)


def test_cursor_reports_only_newer() -> None:
    events = _events(4, 7)
    assert new_events(5, 7, events, now=NOW) == (events[2:], 7)


def test_sequence_jump_back_only_anchors() -> None:
    assert new_events(9, 3, _events(1, 3), now=NOW) == ([], 3)


def test_fresh_boundary_exactly_max_age_counts() -> None:
    events = [Event(1, NOW - FIRST_CONTACT_MAX_AGE, "join", "lena")]
    assert new_events(None, 1, events, now=NOW) == (events, 1)


def test_plausible_keeps_recent_and_drops_far_past_and_future() -> None:
    """IN-10: future and ancient timestamps from a manipulated file are dropped."""
    now = 1_800_000_000
    events = [
        Event(1, now, "deny", "Jetzt"),
        Event(2, now - MAX_AGE, "deny", "Gestern"),
        Event(3, now + MAX_AHEAD, "deny", "Uhrabweichung"),
        Event(4, now - MAX_AGE - 1, "deny", "Zualt"),
        Event(5, now + MAX_AHEAD + 1, "deny", "Zukunft"),
        Event(6, 999_999_999_999, "deny", "Jahr33658"),
        Event(7, 0, "deny", "Epoch0"),
    ]
    assert [event.name for event in plausible(events, now=now)] == ["Jetzt", "Gestern", "Uhrabweichung"]
