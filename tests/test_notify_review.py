"""Daily review: due time and row per child (D-12 to D-15)."""

from gameworld.notify.review import REVIEW_GRACE_MINUTES, minutes, review_due, review_line


def test_review_line_formats_minutes_and_limit() -> None:
    line = review_line([("Tom", 3600, True), ("Lena", 2700, False)])
    assert line == "Lena 45 Min., Tom 60 Min. (Limit erreicht)"


def test_review_line_empty_is_none() -> None:
    assert review_line([]) is None
    assert review_line([("Lena", 0, False)]) is None


def test_minutes_rounds_with_floor_of_one() -> None:
    assert minutes(20) == 1
    assert minutes(89) == 1
    assert minutes(91) == 2
    assert minutes(2700) == 45
    assert minutes(0) == 0


def test_review_due() -> None:
    assert not review_due(1199, 1200, enabled=True)
    assert review_due(1200, 1200, enabled=True)
    assert review_due(1229, 1200, enabled=True)
    assert not review_due(1300, 1200, enabled=False)


def test_review_due_only_in_window_after_pref() -> None:
    """WR-03: after the 30-minute window the review is no longer due, not even late in the evening."""
    assert REVIEW_GRACE_MINUTES == 30
    assert not review_due(1230, 1200, enabled=True)
    assert not review_due(1290, 1200, enabled=True)
    assert not review_due(1439, 1200, enabled=True)
    # Set early (0:15): no longer due at 9 in the morning.
    assert review_due(15, 15, enabled=True)
    assert not review_due(540, 15, enabled=True)
    # Set late (23:45): due until the end of the day, never beyond the day.
    assert review_due(1439, 1425, enabled=True)
    assert not review_due(0, 1425, enabled=True)
