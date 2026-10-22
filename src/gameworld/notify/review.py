"""Tagesrückblick (rein, D-12 bis D-15).

``review_line`` baut "Lena 45 Min., Tom 60 Min. (Limit erreicht)" aus
(Anzeigename, Sekunden, Limit erreicht); ohne Spielzeit gibt es keine Zeile und
damit keine Nachricht (D-14). ``review_due`` prüft, ob die lokale Minute im
kurzen Fenster ab der eingestellten Minute des Verwalters liegt (WR-03).
"""

from __future__ import annotations

from collections.abc import Iterable

from gameworld.notify.texts import REVIEW_LIMIT_SUFFIX

ReviewEntry = tuple[str, int, bool]
# So lange nach der eingestellten Minute darf der Rückblick noch kommen (Neustart, Takt).
REVIEW_GRACE_MINUTES = 30


def minutes(seconds: int) -> int:
    """Gerundete Minuten, aber mindestens 1 bei Spielzeit > 0."""
    if seconds <= 0:
        return 0
    return max(1, round(seconds / 60))


def review_line(entries: Iterable[ReviewEntry]) -> str | None:
    """Zeile je Kind, sortiert nach Anzeigename; None ohne Spielzeit."""
    parts = [
        f"{name} {minutes(seconds)} Min.{REVIEW_LIMIT_SUFFIX if limit_reached else ''}"
        for name, seconds, limit_reached in sorted(entries, key=lambda entry: entry[0].casefold())
        if seconds > 0
    ]
    return ", ".join(parts) if parts else None


def review_due(local_minute: int, pref_minute: int, *, enabled: bool) -> bool:
    """Fällig nur im Fenster REVIEW_GRACE_MINUTES ab der eingestellten Minute; abgeschaltet nie (WR-03).

    Später am Tag kommt kein Rückblick mehr: Sonst käme er beim ersten Spielen
    nach der Uhrzeit mit Teildaten, bei früher Uhrzeit sogar morgens.
    """
    return enabled and pref_minute <= local_minute < pref_minute + REVIEW_GRACE_MINUTES
