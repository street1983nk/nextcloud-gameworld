"""Ereignisdatei ``gameworld_events.txt`` lesen und neue Ereignisse bestimmen (rein, ohne I/O).

Die Datei schreibt der Zugangs-Mod (Plan 04.1-01) und ist damit vom Lua-Prozess
beschreibbar, also unvertrauenswürdig (T-04.1-06): Jede Zeile muss exakt passen,
Art aus der Allowlist, Name wie PLAYER_NAME, Zahlen höchstens 12 Ziffern.
Ungültige Zeilen fallen weg; fehlt Kopf oder Schlusszeile, gilt die Datei als
nicht lesbar (None).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gameworld.provisioner.access_mod import EVENT_KINDS, EVENTS_HEADER
from gameworld.provisioner.status_mod import PLAYER_NAME

# Erstkontakt: Eine Datei, deren Ereignisse alle höchstens so alt sind (Sekunden)
# und die bei Sequenz 1 beginnt, stammt von einer gerade gestarteten Welt.
FIRST_CONTACT_MAX_AGE = 120

_HEAD = re.compile(re.escape(EVENTS_HEADER) + r" ([0-9]{1,12})")
_LINE = re.compile(r"([0-9]{1,12}) ([0-9]{1,12}) ([a-z0-9]{1,12}) (\S{1,20})")


@dataclass(frozen=True)
class Event:
    """Eine Zeile der Ereignisdatei: Sequenz, Epoch-Sekunden, Art, Spielername."""

    seq: int
    at: int
    kind: str
    name: str


def parse_events(content: bytes) -> tuple[int, list[Event]] | None:
    """Letzte Sequenz und gültige Ereignisse, oder None ohne Kopf, Version oder Schlusszeile."""
    lines = content.decode("ascii", "replace").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2 or lines[-1] != "end":
        return None
    head = _HEAD.fullmatch(lines[0])
    if head is None:
        return None
    events: list[Event] = []
    for raw in lines[1:-1]:
        match = _LINE.fullmatch(raw)
        if match is None or match.group(3) not in EVENT_KINDS or not PLAYER_NAME.fullmatch(match.group(4)):
            continue
        events.append(Event(int(match.group(1)), int(match.group(2)), match.group(3), match.group(4)))
    return int(head.group(1)), events


def new_events(cursor: int | None, last_seq: int, events: list[Event], *, now: int) -> tuple[list[Event], int]:
    """Noch nicht gemeldete Ereignisse und der neue Cursor.

    Reihenfolge der Regeln (Pitfall 6, T-04.1-09):
    1. Rücksprung der Sequenz (Restore, neues Volume): nur verankern.
    2. Bekannter Cursor: alles mit höherer Sequenz.
    3. Erstkontakt mit frischer Datei (beginnt bei 1, alles höchstens
       FIRST_CONTACT_MAX_AGE alt): Anker 0, also alle Ereignisse.
    4. Sonst Erstkontakt mit alter Datei: nur verankern, keine Flut nach dem Update.
    ``now`` kommt vom Aufrufer (Epoch-Sekunden), damit die Funktion rein bleibt.
    """
    if cursor is not None and last_seq < cursor:
        return [], last_seq
    if cursor is not None:
        return [event for event in events if cursor < event.seq <= last_seq], last_seq
    if (
        events
        and min(event.seq for event in events) == 1
        and all(event.at >= now - FIRST_CONTACT_MAX_AGE for event in events)
    ):
        return [event for event in events if event.seq <= last_seq], last_seq
    return [], last_seq
