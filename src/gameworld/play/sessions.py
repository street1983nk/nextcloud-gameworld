"""Sessions of the WebSocket proxy (04.2-07, D-01/D-02).

``NEWADDR`` creates a session after a redeemed WS ticket: passcode with 128 bits
(``secrets.token_urlsafe(16)``), bound to account (UID), world, player name and the
UDP destination of the world. The destination is in the frozen ``SessionKey`` and cannot be changed after
``create``; the proxy never sends to a destination from the frame.

Limits: at most one session per (UID, world), at most BIND_LIMIT BINDs per
passcode (the client opens its own connection per UDP socket, RESEARCH pitfall 8),
a session without BIND expires after UNBOUND_SECONDS. After the last BIND ends,
the session is over and (UID, world) is free again.

Measurements for RESEARCH open question 2 (how many WS connections and BINDs does the
5.17 client open): at session end exactly one line ``play session end binds=<n>
newaddr=<k>``, numbers only, without UID, player name, passcode or ticket.
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from gameworld.play.mtp import ClientGuard
from gameworld.play.srp_proxy import SrpTakeover

LOG = logging.getLogger(__name__)

BIND_LIMIT = 4
UNBOUND_SECONDS = 60.0

REASON_BUSY = "busy"
REASON_UNKNOWN = "unknown"
REASON_UID_MISMATCH = "uid_mismatch"
REASON_TOO_MANY_BINDS = "too_many_binds"
REASON_ENDED = "ended"


@dataclass(frozen=True)
class SessionKey:
    """Immutable binding of a session; ``target`` is the only UDP destination."""

    uid: str
    world_id: str
    player_name: str
    target: tuple[str, int]
    passcode: str


class Session:
    """A session: fixed binding (``key``), counters and a guard for all BINDs."""

    __slots__ = ("active_binds", "binds", "created_at", "guard", "key", "takeover")

    def __init__(self, key: SessionKey, created_at: float) -> None:
        self.key = key
        self.created_at = created_at
        self.binds = 0
        self.active_binds = 0
        # One guard per session, not per BIND: a second socket shares the name state.
        self.guard = ClientGuard(key.player_name)
        # Variant A (proxy_srp): ws.py attaches the SRP takeover, otherwise None (variant B).
        self.takeover: SrpTakeover | None = None

    @property
    def uid(self) -> str:
        return self.key.uid

    @property
    def world_id(self) -> str:
        return self.key.world_id

    @property
    def player_name(self) -> str:
        return self.key.player_name

    @property
    def target(self) -> tuple[str, int]:
        return self.key.target

    @property
    def passcode(self) -> str:
        return self.key.passcode


class SessionError(Exception):
    """Session rejected; ``reason`` is one of the ASCII constants REASON_*, never a value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SessionRegistry:
    """Open sessions in memory; every call first clears expired ones."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._active: dict[tuple[str, str], str] = {}
        self._newaddr: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def _end(self, session: Session) -> None:
        """Removes the session and writes the counter line (numbers only)."""
        pair = (session.uid, session.world_id)
        self._sessions.pop(session.passcode, None)
        if self._active.get(pair) == session.passcode:
            del self._active[pair]
        LOG.info("play session end binds=%d newaddr=%d", session.binds, self._newaddr.get(pair, 0))

    def _expire(self, now: float) -> None:
        stale = [
            session
            for session in self._sessions.values()
            if session.binds == 0 and now - session.created_at >= UNBOUND_SECONDS
        ]
        for session in stale:
            self._end(session)

    def create(self, uid: str, world_id: str, player_name: str, target: tuple[str, int]) -> Session:
        """New session or SessionError("busy") as long as (uid, world_id) has an active one."""
        pair = (uid, world_id)
        with self._lock:
            now = self._clock()
            self._expire(now)
            # Counts every NEWADDR attempt after a redeemed ticket, also rejected ones.
            self._newaddr[pair] = self._newaddr.get(pair, 0) + 1
            if pair in self._active:
                raise SessionError(REASON_BUSY)
            key = SessionKey(
                uid=uid,
                world_id=world_id,
                player_name=player_name,
                target=(target[0], target[1]),
                passcode=secrets.token_urlsafe(16),
            )
            session = Session(key, now)
            self._sessions[key.passcode] = session
            self._active[pair] = key.passcode
            return session

    def bind(self, passcode: str, uid: str | None = None) -> Session:
        """Counts a BIND; ``uid`` None (mode dev) does not check the account."""
        with self._lock:
            self._expire(self._clock())
            session = self._sessions.get(passcode)
            if session is None:
                raise SessionError(REASON_UNKNOWN)
            if uid is not None and session.uid != uid:
                raise SessionError(REASON_UID_MISMATCH)
            if session.guard.ended:
                raise SessionError(REASON_ENDED)
            if session.binds >= BIND_LIMIT:
                raise SessionError(REASON_TOO_MANY_BINDS)
            session.binds += 1
            session.active_binds += 1
            return session

    def unbind(self, passcode: str) -> None:
        """End of a BIND; after the last one the session ends. Unknown passcodes: nothing."""
        with self._lock:
            session = self._sessions.get(passcode)
            if session is None or session.active_binds == 0:
                return
            session.active_binds -= 1
            if session.active_binds == 0:
                self._end(session)


_session_registry: SessionRegistry | None = None


def get_session_registry() -> SessionRegistry:
    """FastAPI dependency: module-wide singleton (tests set their own instances via override)."""
    global _session_registry
    if _session_registry is None:
        _session_registry = SessionRegistry()
    return _session_registry


SessionRegistryDep = Annotated[SessionRegistry, Depends(get_session_registry)]
