"""Verbuchung des Zählbuchs (rein): Zuwachs, Rücksprung, Erstkontakt, Tageszuordnung.

Deckt Pitfall 7 und T-04-10 ab: Ein Rücksprung (Restore, neues Volume) oder ein
Erstkontakt verankert nur neu, nie negativ.
"""

from datetime import date
from zoneinfo import ZoneInfo

from gameworld.playtime.ledger import attribution_day, increments

BERLIN = ZoneInfo("Europe/Berlin")


def test_increment_and_first_contact() -> None:
    # Leo taucht zum ersten Mal auf: nur verankern, nicht als Zuwachs zählen.
    delta, seen = increments({"Mia": 40}, {"Mia": 55, "Leo": 7})
    assert delta == {"Mia": 15}
    assert seen == {"Mia": 55, "Leo": 7}


def test_regression_anchors_without_negative() -> None:
    # Rücksprung (Zählbuch zurückgesetzt): neu verankern, nie negativ verbuchen.
    delta, seen = increments({"Mia": 40}, {"Mia": 10})
    assert delta == {}
    assert seen == {"Mia": 10}


def test_no_change_no_delta() -> None:
    delta, seen = increments({"Mia": 40}, {"Mia": 40})
    assert delta == {}
    assert seen == {"Mia": 40}


def test_increments_case_insensitive_like_player_name() -> None:
    # Zuordnung wie players.player_name (NOCASE); Ausgabe mit dem Namen aus current.
    delta, seen = increments({"Mia": 40}, {"mia": 55})
    assert delta == {"mia": 15}
    assert seen == {"mia": 55}


def test_increments_does_not_mutate_inputs() -> None:
    seen_in = {"Mia": 40}
    current_in = {"Mia": 55}
    increments(seen_in, current_in)
    assert seen_in == {"Mia": 40}
    assert current_in == {"Mia": 55}


def test_attribution_day_uses_header_time() -> None:
    # 2026-10-25 01:00 lokal (Sommerzeit-Ende); der Tag kommt aus dem Schreibzeitpunkt.
    written_at = 1792882800  # 2026-10-25 00:00:00Z = 02:00 lokal
    assert attribution_day(written_at, BERLIN) == date(2026, 10, 25)
    # Kurz vor Mitternacht am Vortag.
    assert attribution_day(1792879200 - 1, BERLIN) == date(2026, 10, 24)
