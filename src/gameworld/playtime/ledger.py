"""Verbuchung des Zählbuchs (rein), 04-RESEARCH.md Pattern 5 und Code Example.

Jede Welt schreibt ein eigenes, monotones Zählbuch (Sekunden je Spielername).
``increments`` vergleicht den aktuellen Stand mit dem zuletzt gesehenen und gibt
nur den echten Zuwachs je Name zurück, dazu den neuen gesehenen Stand.

Zwei Fälle verankern nur neu, ohne Zuwachs (Schutz gegen Doppel- oder
Minuszählung, Pitfall 7 und T-04-10):

- Erstkontakt: Ein Name, der zum ersten Mal auftaucht, wurde womöglich schon vor
  dem ersten ExApp-Blick gespielt. Nur verankern ist die sichere Wahl gegen
  Doppelzählung; höchstens die Zeit vor dem ersten Blick geht verloren.
- Rücksprung: Ein Restore oder ein neues Volume bringt ein kleineres Zählbuch.
  Es wird neu verankert, nie negativ verbucht.

Namen werden ohne Rücksicht auf Groß-/Kleinschreibung zugeordnet wie
``players.player_name`` (COLLATE NOCASE); der Zuwachs trägt den Namen aus dem
aktuellen Zählbuch. ``attribution_day`` ordnet einen Zuwachs dem lokalen Tag des
Zählbuch-Kopfs zu (Schreibzeitpunkt), nicht dem Lesezeitpunkt.
"""

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from gameworld.playtime.plan import local_day


def increments(seen: dict[str, int], current: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """(Zuwachs je Name, neuer gesehener Stand). Rücksprung und Erstkontakt nur verankern."""
    seen_by_fold = {name.casefold(): value for name, value in seen.items()}
    delta: dict[str, int] = {}
    for name, value in current.items():
        before = seen_by_fold.get(name.casefold())
        if before is not None and value > before:
            delta[name] = value - before
    return delta, dict(current)


def attribution_day(written_at: int, tz: ZoneInfo) -> date:
    """Lokaler Kalendertag des Zählbuch-Kopfs (Schreibzeitpunkt, nicht Lesezeitpunkt)."""
    return local_day(written_at, tz)
