"""Relay between a WebSocket connection after ``BIND OK`` and the world via UDP (04.2-07).

One UDP socket per BIND, connected (``remote_addr``) to the destination from the session.
The head of a frame is only checked (``target_allowed``), never used as a destination; so
the proxy is neither an open UDP relay into the home network nor an amplifier. A connected
UDP socket also accepts only replies from exactly this destination.

Towards the world per frame: size, head, destination rule, packet rate, ClientGuard (plan 05); only
then ``sendto``. Towards the browser: datagrams of the world are observed by the guard
(AUTH_ACCEPT) and wrapped with the virtual server as source. Without a datagram from the world
for IDLE_SECONDS the relay ends. Teardown always runs in the ``finally``.

Logs only with counters and fixed reasons, never with player name, passcode, ticket or
packet content; the numbers are measurements for plans 08 and 10.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from gameworld.play.commands import VIRTUAL_SERVER, target_allowed
from gameworld.play.framing import EP_HEADER, MAX_PAYLOAD, FrameError, pack, unpack
from gameworld.play.mtp import Verdict
from gameworld.play.sessions import Session, SessionRegistry
from gameworld.play.srp_proxy import SrpTakeoverError

LOG = logging.getLogger(__name__)

IDLE_SECONDS = 60.0
RATE_PER_SECOND = 1000
RATE_BURST = 200
MAX_FRAME = EP_HEADER.size + MAX_PAYLOAD
QUEUE_LIMIT = 1024

END_CLIENT_CLOSED = "client_closed"
END_TEXT = "text_after_bind"
END_FRAME_SIZE = "frame_too_large"
END_FRAME = "bad_frame"
END_IDLE = "idle"
END_SOCKET = "socket_closed"
END_SRP_TAKEOVER = "srp_takeover"

# Reasons that point to a faulty or malicious client: close with 1008.
_POLICY_ENDS = frozenset({END_TEXT, END_FRAME_SIZE, END_FRAME, END_SRP_TAKEOVER})

ProtocolFactory = Callable[[], asyncio.DatagramProtocol]
EndpointFactory = Callable[[ProtocolFactory, Session], Awaitable[asyncio.DatagramTransport]]


@dataclass
class RelayStats:
    """Counters of a BIND; ``end_reason`` is a fixed ASCII constant."""

    frames_in: int = 0
    frames_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    dropped_target: int = 0
    dropped_rate: int = 0
    dropped_size: int = 0
    dropped_queue: int = 0
    srp_replaced: int = 0
    end_reason: str = ""


class TokenBucket:
    """Packet rate towards the world: ``rate`` packets per second, bursts up to ``burst``."""

    def __init__(self, rate: float, burst: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._rate = rate
        self._burst = burst
        self._clock = clock
        self._tokens = burst
        self._last = clock()

    def take(self) -> bool:
        now = self._clock()
        self._tokens = min(self._burst, self._tokens + (now - self._last) * self._rate)
        self._last = now
        if self._tokens < 1:
            return False
        self._tokens -= 1
        return True


class _WorldProtocol(asyncio.DatagramProtocol):
    """Puts datagrams of the world into a bounded queue; None means socket closed."""

    def __init__(self, queue: asyncio.Queue[bytes | None], stats: RelayStats) -> None:
        self._queue = queue
        self._stats = stats

    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        del addr  # The socket is connected to the session destination, other senders do not get through.
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            self._stats.dropped_queue += 1

    def error_received(self, exc: Exception) -> None:
        # ICMP "port unreachable" (world just gone): no abort, the idle timeout handles it.
        del exc

    def connection_lost(self, exc: Exception | None) -> None:
        del exc
        with contextlib.suppress(asyncio.QueueFull):
            self._queue.put_nowait(None)


async def open_world_endpoint(protocol_factory: ProtocolFactory, session: Session) -> asyncio.DatagramTransport:
    """Own UDP socket per BIND, connected to the destination of the session (never from the frame)."""
    loop = asyncio.get_running_loop()
    transport, _protocol = await loop.create_datagram_endpoint(protocol_factory, remote_addr=session.target)
    return transport


async def _to_world(ws: WebSocket, session: Session, transport: asyncio.DatagramTransport, stats: RelayStats) -> str:
    bucket = TokenBucket(RATE_PER_SECOND, RATE_BURST)
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            return END_CLIENT_CLOSED
        data = message.get("bytes")
        if data is None:
            return END_TEXT
        if len(data) > MAX_FRAME:
            return END_FRAME_SIZE
        try:
            host, port, payload = unpack(data)
        except FrameError:
            return END_FRAME
        stats.frames_in += 1
        stats.bytes_in += len(payload)
        if not target_allowed(host, port):
            stats.dropped_target += 1
            continue
        if not bucket.take():
            stats.dropped_rate += 1
            continue
        result = session.guard.check(payload)
        if result.verdict is Verdict.END:
            return f"guard_{result.reason}"
        # Variant A: first the guard (name, FIRST_SRP), then the SRP replacement, then sendto.
        out = payload
        if session.takeover is not None:
            try:
                out = session.takeover.client_packet(payload)
            except SrpTakeoverError:
                return END_SRP_TAKEOVER
            if out is not payload:
                stats.srp_replaced += 1
        transport.sendto(out)


async def _to_browser(ws: WebSocket, session: Session, queue: asyncio.Queue[bytes | None], stats: RelayStats) -> str:
    while True:
        try:
            # Read the module variable each round: tests lower IDLE_SECONDS.
            async with asyncio.timeout(IDLE_SECONDS):
                data = await queue.get()
        except TimeoutError:
            return END_IDLE
        if data is None:
            return END_SOCKET
        session.guard.observe_server(data)
        if session.takeover is not None:
            try:
                session.takeover.server_packet(data)
            except SrpTakeoverError:
                return END_SRP_TAKEOVER
        if len(data) > MAX_PAYLOAD:
            stats.dropped_size += 1
            continue
        await ws.send_bytes(pack(VIRTUAL_SERVER[0], VIRTUAL_SERVER[1], data))
        stats.frames_out += 1
        stats.bytes_out += len(data)


async def relay(
    ws: WebSocket,
    session: Session,
    stats: RelayStats,
    registry: SessionRegistry,
    endpoint_factory: EndpointFactory = open_world_endpoint,
) -> None:
    """Forwards until the first end reason; always releases the BIND and closes the connection."""
    started = time.monotonic()
    transport: asyncio.DatagramTransport | None = None
    tasks: list[asyncio.Task[str]] = []
    try:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=QUEUE_LIMIT)
        transport = await endpoint_factory(lambda: _WorldProtocol(queue, stats), session)
        tasks = [
            asyncio.create_task(_to_world(ws, session, transport, stats)),
            asyncio.create_task(_to_browser(ws, session, queue, stats)),
        ]
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        try:
            stats.end_reason = next(iter(done)).result()
        except WebSocketDisconnect:
            # Sending to a browser that has been closed in the meantime.
            stats.end_reason = END_CLIENT_CLOSED
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if transport is not None:
            transport.close()
        registry.unbind(session.passcode)
        LOG.info(
            "play relay end seconds=%.1f frames_in=%d frames_out=%d bytes_in=%d bytes_out=%d "
            "dropped_target=%d dropped_rate=%d dropped_size=%d dropped_queue=%d srp_replaced=%d reason=%s",
            time.monotonic() - started,
            stats.frames_in,
            stats.frames_out,
            stats.bytes_in,
            stats.bytes_out,
            stats.dropped_target,
            stats.dropped_rate,
            stats.dropped_size,
            stats.dropped_queue,
            stats.srp_replaced,
            stats.end_reason or "error",
        )
    if stats.end_reason != END_CLIENT_CLOSED:
        policy = stats.end_reason in _POLICY_ENDS or stats.end_reason.startswith("guard_")
        code = 1008 if policy else 1000
        with contextlib.suppress(Exception):
            await ws.close(code=code)
