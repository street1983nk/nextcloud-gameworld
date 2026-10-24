"""Erwachsen-Schalter je Konto (ROLLE-04, D-05 bis D-08): Store, Engine, API und Negativtests."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from gameworld.notify.loop import collect_play
from gameworld.worlds.store import WorldStore
from tests.conftest import give_rules

SET_AT = "2026-10-24T10:00:00+00:00"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


def _raw_adults(db: Path) -> list[tuple[str, str, str]]:
    """Inhalt der Tabelle adults per eigener Abfrage (nicht über die Store-Methode)."""
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("SELECT nc_user, set_by, set_at FROM adults ORDER BY nc_user").fetchall()
    finally:
        connection.close()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


# Store


def test_set_and_clear_adult(store: WorldStore, app_env: Path) -> None:
    assert store.adults() == set()
    store.set_adult("gw-kind", set_by="admin", set_at=SET_AT)
    assert store.adults() == {"gw-kind"}
    # Wer und wann bleiben gespeichert (T-06-19).
    assert _raw_adults(app_env / "gameworld.sqlite3") == [("gw-kind", "admin", SET_AT)]
    store.clear_adult("gw-kind")
    assert store.adults() == set()
    assert _raw_adults(app_env / "gameworld.sqlite3") == []


def test_clear_adult_on_unmarked_account_is_no_error(store: WorldStore) -> None:
    store.clear_adult("gw-niemand")
    assert store.adults() == set()


def test_set_adult_twice_replaces_marker(store: WorldStore, app_env: Path) -> None:
    store.set_adult("gw-kind", set_by="admin", set_at=SET_AT)
    store.set_adult("gw-kind", set_by="lehrerin", set_at="2026-10-24T11:00:00+00:00")
    assert _raw_adults(app_env / "gameworld.sqlite3") == [("gw-kind", "lehrerin", "2026-10-24T11:00:00+00:00")]


# Tagesrückblick (D-05: Erwachsene erscheinen nicht)


def test_adult_never_in_daily_review_even_with_minutes_before_switch(store: WorldStore) -> None:
    day = date(2026, 10, 24)
    for uid in ("gw-kind", "gw-oma"):
        give_rules(store, uid)
    # Minuten von heute früh, als gw-oma noch als Kind lief.
    store.book_usage("w1", day, {}, {}, play={"gw-kind": 300, "gw-oma": 300})
    assert collect_play(store, day, ()) == {"gw-kind": {"w1": 300}, "gw-oma": {"w1": 300}}

    store.set_adult("gw-oma", set_by="admin", set_at=SET_AT)

    assert collect_play(store, day, ()) == {"gw-kind": {"w1": 300}}
