"""Ein-Mal-Tickets des Browser-Spikes (04.2-06, D-02/D-09/D-10).

Ein Ticket ist ein Zufallswert mit 128 Bit (16 Bytes aus ``secrets``), gilt
TICKET_SECONDS, ist genau einmal einlösbar und an Zweck, Konto (UID), Welt und
Spielername gebunden. Zwei Zwecke:

- ``launch``: von POST /api/my/play-ticket (signierte AppAPI-Anfrage) für die
  Spielseite, einzulösen in POST /play/launch.
- ``ws``: von /play/launch für die WebSocket-Verbindung des Proxys (Plan 07).

Einlösen entfernt das Ticket immer zuerst, auch wenn danach Ablauf, Zweck oder
UID nicht passen: Ein abgelehntes Ticket ist verbrannt. Die Länge des Rohwerts
wird vor jedem Wörterbuchzugriff geprüft.

Das Modul loggt nichts; Tokenwerte gehören in kein Log.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends

TICKET_SECONDS = 60.0
MAX_OPEN_PER_UID = 4
TOKEN_MAX = 64

Purpose = Literal["launch", "ws"]

REASON_USED_OR_UNKNOWN = "used_or_unknown"
REASON_EXPIRED = "expired"
REASON_PURPOSE = "purpose"
REASON_UID_MISMATCH = "uid_mismatch"
REASON_MALFORMED = "malformed"


@dataclass(frozen=True)
class Ticket:
    """Bindung eines eingelösten Tickets; enthält den Tokenwert selbst nicht."""

    uid: str
    world_id: str
    player_name: str
    purpose: Purpose
    issued_at: float


class TicketError(Exception):
    """Ticket abgelehnt; ``reason`` ist eine der ASCII-Konstanten REASON_*, nie der Tokenwert."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TicketStore:
    """Offene Tickets im Speicher, ältestes zuerst (Einfügereihenfolge des dict)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def _expired(self, ticket: Ticket, now: float) -> bool:
        return now - ticket.issued_at >= TICKET_SECONDS

    def issue(self, purpose: Purpose, *, uid: str, world_id: str, player_name: str) -> str:
        """Neues Ticket; räumt Abgelaufene ab und hält höchstens MAX_OPEN_PER_UID je Konto offen."""
        with self._lock:
            now = self._clock()
            for token in [token for token, ticket in self._tickets.items() if self._expired(ticket, now)]:
                del self._tickets[token]
            own = [token for token, ticket in self._tickets.items() if ticket.uid == uid]
            for token in own[: max(0, len(own) - MAX_OPEN_PER_UID + 1)]:
                del self._tickets[token]
            token = secrets.token_urlsafe(16)
            self._tickets[token] = Ticket(
                uid=uid, world_id=world_id, player_name=player_name, purpose=purpose, issued_at=now
            )
            return token

    def redeem(self, token: str, purpose: Purpose, *, uid: str | None) -> Ticket:
        """Löst genau einmal ein; ``uid`` None (Modus dev) prüft das Konto nicht."""
        if not isinstance(token, str) or not 1 <= len(token) <= TOKEN_MAX:
            raise TicketError(REASON_MALFORMED)
        with self._lock:
            ticket = self._tickets.pop(token, None)
            now = self._clock()
        if ticket is None:
            raise TicketError(REASON_USED_OR_UNKNOWN)
        if self._expired(ticket, now):
            raise TicketError(REASON_EXPIRED)
        if ticket.purpose != purpose:
            raise TicketError(REASON_PURPOSE)
        if uid is not None and ticket.uid != uid:
            raise TicketError(REASON_UID_MISMATCH)
        return ticket


_ticket_store: TicketStore | None = None


def get_ticket_store() -> TicketStore:
    """FastAPI-Dependency: modulweites Singleton (Tests setzen es je Test zurück)."""
    global _ticket_store
    if _ticket_store is None:
        _ticket_store = TicketStore()
    return _ticket_store


TicketStoreDep = Annotated[TicketStore, Depends(get_ticket_store)]
