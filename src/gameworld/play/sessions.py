"""Sitzungen des WebSocket-Proxys (04.2-07, D-01/D-02).

``NEWADDR`` legt nach eingelöstem WS-Ticket eine Sitzung an: Passcode mit 128 Bit
(``secrets.token_urlsafe(16)``), gebunden an Konto (UID), Welt, Spielername und das
UDP-Ziel der Welt. Das Ziel steht im eingefrorenen ``SessionKey`` und lässt sich nach
``create`` nicht mehr ändern; der Proxy sendet nie an ein Ziel aus dem Frame.

Grenzen: höchstens eine Sitzung je (UID, Welt), höchstens BIND_LIMIT BINDs je
Passcode (der Client öffnet je UDP-Socket eine eigene Verbindung, RESEARCH Pitfall 8),
eine Sitzung ohne BIND verfällt nach UNBOUND_SECONDS. Nach dem letzten BIND-Ende ist
die Sitzung vorbei und (UID, Welt) wieder frei.

Messwerte für RESEARCH Open Question 2 (wie viele WS-Verbindungen und BINDs öffnet der
5.17-Client): Beim Sitzungsende genau eine Zeile ``play session end binds=<n>
newaddr=<k>``, nur Zahlen, ohne UID, Spielername, Passcode oder Ticket.
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
    """Unveränderliche Bindung einer Sitzung; ``target`` ist das einzige UDP-Ziel."""

    uid: str
    world_id: str
    player_name: str
    target: tuple[str, int]
    passcode: str


class Session:
    """Eine Sitzung: feste Bindung (``key``), Zähler und ein Wächter für alle BINDs."""

    __slots__ = ("active_binds", "binds", "created_at", "guard", "key", "takeover")

    def __init__(self, key: SessionKey, created_at: float) -> None:
        self.key = key
        self.created_at = created_at
        self.binds = 0
        self.active_binds = 0
        # Ein Wächter je Sitzung, nicht je BIND: ein zweiter Socket teilt den Namenszustand.
        self.guard = ClientGuard(key.player_name)
        # Variante A (proxy_srp): ws.py hängt die SRP-Übernahme an, sonst None (Variante B).
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
    """Sitzung abgelehnt; ``reason`` ist eine der ASCII-Konstanten REASON_*, nie ein Wert."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SessionRegistry:
    """Offene Sitzungen im Speicher; jeder Aufruf räumt zuerst verfallene ab."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._sessions: dict[str, Session] = {}
        self._active: dict[tuple[str, str], str] = {}
        self._newaddr: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def _end(self, session: Session) -> None:
        """Entfernt die Sitzung und schreibt die Zählerzeile (nur Zahlen)."""
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
        """Neue Sitzung oder SessionError("busy"), solange (uid, world_id) eine aktive hat."""
        pair = (uid, world_id)
        with self._lock:
            now = self._clock()
            self._expire(now)
            # Zählt jeden NEWADDR-Versuch nach eingelöstem Ticket, auch abgelehnte.
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
        """Zählt einen BIND; ``uid`` None (Modus dev) prüft das Konto nicht."""
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
        """Ende eines BIND; nach dem letzten endet die Sitzung. Unbekannte Passcodes: nichts."""
        with self._lock:
            session = self._sessions.get(passcode)
            if session is None or session.active_binds == 0:
                return
            session.active_binds -= 1
            if session.active_binds == 0:
                self._end(session)


_session_registry: SessionRegistry | None = None


def get_session_registry() -> SessionRegistry:
    """FastAPI-Dependency: modulweites Singleton (Tests setzen eigene Instanzen per Override)."""
    global _session_registry
    if _session_registry is None:
        _session_registry = SessionRegistry()
    return _session_registry


SessionRegistryDep = Annotated[SessionRegistry, Depends(get_session_registry)]
