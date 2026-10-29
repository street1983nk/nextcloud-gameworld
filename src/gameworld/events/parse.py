"""Read the event file ``gameworld_events.txt`` and determine new events (pure, no I/O).

The file is written by the access mod (plan 04.1-01) and is therefore writable by the
Lua process, hence untrustworthy (T-04.1-06): every line must match exactly,
kind from the allowlist, name like PLAYER_NAME, numbers at most 12 digits.
Invalid lines are dropped; if the head or closing line is missing, the file counts as
unreadable (None).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gameworld.provisioner.access_mod import EVENT_KINDS, EVENTS_HEADER
from gameworld.provisioner.status_mod import PLAYER_NAME

# First contact: a file whose events are all at most this old (seconds)
# and which starts at sequence 1 comes from a world that has just started.
FIRST_CONTACT_MAX_AGE = 120
# Plausible timestamps (IN-10): one day back (ExApp off for a long time), 5 minutes ahead (clock drift).
MAX_AGE = 86400
MAX_AHEAD = 300

_HEAD = re.compile(re.escape(EVENTS_HEADER) + r" ([0-9]{1,12})")
_LINE = re.compile(r"([0-9]{1,12}) ([0-9]{1,12}) ([a-z0-9]{1,12}) (\S{1,20})")


@dataclass(frozen=True)
class Event:
    """One line of the event file: sequence, epoch seconds, kind, player name."""

    seq: int
    at: int
    kind: str
    name: str


def parse_events(content: bytes) -> tuple[int, list[Event]] | None:
    """Last sequence and valid events, or None without head, version or closing line."""
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


def plausible(events: list[Event], *, now: int) -> list[Event]:
    """Only events with a plausible timestamp: at most MAX_AGE old, at most MAX_AHEAD in the future (IN-10).

    The file is untrustworthy: a tampered Lua process could otherwise create
    foreign attempts with a future date that never fall under the deletion period.
    """
    return [event for event in events if now - MAX_AGE <= event.at <= now + MAX_AHEAD]


def new_events(cursor: int | None, last_seq: int, events: list[Event], *, now: int) -> tuple[list[Event], int]:
    """Events not yet reported and the new cursor.

    Order of the rules (pitfall 6, T-04.1-09):
    1. Sequence going backwards (restore, new volume): only anchor.
    2. Known cursor: everything with a higher sequence.
    3. First contact with a fresh file (starts at 1, everything at most
       FIRST_CONTACT_MAX_AGE old): anchor 0, i.e. all events.
    4. Otherwise first contact with an old file: only anchor, no flood after the update.
    ``now`` comes from the caller (epoch seconds), so that the function stays pure.
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
