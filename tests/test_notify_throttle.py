"""Drosselung der Fremdversuche (D-08, D-29) und Ansprüche im Store (04.1-04)."""

import pathlib
from datetime import date

import pytest

from gameworld.notify.throttle import decide, is_case_variant
from gameworld.worlds.store import WorldStore

DAY = date(2026, 10, 21)
WORLD = "abc123def456"


@pytest.fixture
def store(tmp_path: pathlib.Path) -> WorldStore:
    result = WorldStore(tmp_path / "gameworld.sqlite3")
    result.migrate()
    return result


@pytest.mark.parametrize(
    ("is_new", "notified", "summary_claimed", "expected"),
    [
        (True, 0, False, "single"),
        (True, 4, False, "single"),
        (True, 5, False, "summary"),
        (True, 5, True, "none"),
        (True, 9, True, "none"),
        (False, 0, False, "none"),
        (False, 5, False, "none"),
    ],
)
def test_decide(is_new: bool, notified: int, summary_claimed: bool, expected: str) -> None:  # noqa: FBT001
    assert decide(is_new, notified, summary_claimed, 5) == expected


def test_is_case_variant() -> None:
    assert is_case_variant("lena", {"Lena", "Tom"})
    assert is_case_variant("TOM", {"Lena", "Tom"})
    assert not is_case_variant("Fremder", {"Lena", "Tom"})
    assert not is_case_variant("Fremder", set())


def test_claim_attempt_one_per_name_world_day(store: WorldStore) -> None:
    assert store.claim_attempt(DAY, WORLD, "Fremder", 1000) == "single"
    assert store.claim_attempt(DAY, WORLD, "FREMDER", 1100) == "none"
    rows = store.attempts(DAY)
    assert len(rows) == 1
    row = rows[0]
    assert (row.world_id, row.player_name, row.first_at, row.count) == (WORLD, "Fremder", 1000, 2)
    # Andere Welt oder anderer Tag zählen neu.
    assert store.claim_attempt(DAY, "000000000001", "Fremder", 1200) == "single"
    assert store.claim_attempt(date(2026, 10, 22), WORLD, "Fremder", 90000) == "single"


def test_claim_attempt_five_singles_then_one_summary(store: WorldStore) -> None:
    results = [store.claim_attempt(DAY, WORLD, f"Name{index}", 1000 + index) for index in range(7)]
    assert results == ["single"] * 5 + ["summary", "none"]
    # Ein schon bekannter Name ändert nach der Sammelnachricht nichts.
    assert store.claim_attempt(DAY, WORLD, "Name0", 2000) == "none"
    assert len(store.attempts(DAY)) == 7
    assert store.claim_attempt(date(2026, 10, 22), WORLD, "Name9", 90000) == "single"


def test_attempts_filter_by_world(store: WorldStore) -> None:
    store.claim_attempt(DAY, WORLD, "Fremder", 1000)
    store.claim_attempt(DAY, "000000000001", "Anderer", 1100)
    assert [row.player_name for row in store.attempts(DAY, WORLD)] == ["Fremder"]
    assert {row.player_name for row in store.attempts(DAY)} == {"Fremder", "Anderer"}
    assert store.attempts(date(2026, 10, 20)) == []


def test_claim_review_once_per_user_and_day(store: WorldStore) -> None:
    assert store.claim_review("mama", DAY)
    assert not store.claim_review("mama", DAY)
    assert store.claim_review("papa", DAY)
    assert store.claim_review("mama", date(2026, 10, 22))


def test_review_pref_default_and_save(store: WorldStore) -> None:
    assert store.review_pref("mama") == (True, 1200)
    store.set_review_pref("mama", enabled=False, minute=1140)
    assert store.review_pref("mama") == (False, 1140)
    store.set_review_pref("mama", enabled=True, minute=1260)
    assert store.review_pref("mama") == (True, 1260)
    assert store.review_pref("papa") == (True, 1200)
