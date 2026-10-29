"""One-time tickets of the browser spike (04.2-06, D-02/D-09/D-10).

A ticket is a random value of 128 bits (16 bytes from ``secrets``), valid for
TICKET_SECONDS, redeemable exactly once and bound to purpose, account (UID), world and
player name. Two purposes:

- ``launch``: from POST /api/my/play-ticket (signed AppAPI request) for the
  play page, to be redeemed in POST /play/launch.
- ``ws``: from /play/launch for the proxy's WebSocket connection (plan 07).

Redeeming always removes the ticket first, even if expiry, purpose or
UID do not match afterwards: a rejected ticket is burnt. The length of the raw value
is checked before any dictionary access.

The module logs nothing; token values belong in no log.
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
    """Binding of a redeemed ticket; does not contain the token value itself."""

    uid: str
    world_id: str
    player_name: str
    purpose: Purpose
    issued_at: float


class TicketError(Exception):
    """Ticket rejected; ``reason`` is one of the ASCII constants REASON_*, never the token value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TicketStore:
    """Open tickets in memory, oldest first (insertion order of the dict)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._tickets: dict[str, Ticket] = {}
        self._lock = threading.Lock()

    def _expired(self, ticket: Ticket, now: float) -> bool:
        return now - ticket.issued_at >= TICKET_SECONDS

    def issue(self, purpose: Purpose, *, uid: str, world_id: str, player_name: str) -> str:
        """New ticket; clears expired ones and keeps at most MAX_OPEN_PER_UID open per account."""
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
        """Redeems exactly once; ``uid`` None (mode dev) does not check the account."""
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
    """FastAPI dependency: module-wide singleton (tests reset it per test)."""
    global _ticket_store
    if _ticket_store is None:
        _ticket_store = TicketStore()
    return _ticket_store


TicketStoreDep = Annotated[TicketStore, Depends(get_ticket_store)]
