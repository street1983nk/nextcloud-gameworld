"""Datagramm-Socket über das WebSocket-Relais von Gameworld, nur für Tests (04.2-08).

Bildet die Socket-Schnittstelle nach, die ``luanti_probe.Probe`` braucht (sendto,
recvfrom, settimeout, close), und spricht dabei das Protokoll des Browser-Clients
(paradust7/webshims ``src/emsocket/proxy.js``): eine erste Verbindung mit ``NEWADDR``
(Antwort ``ADDR <ip> <passcode> <joincode>``, danach schließt der Server), eine zweite
mit ``BIND <passcode> UDP 30000`` (Antwort ``BIND OK``), dann je Binärnachricht ein
Datagramm mit 24 Byte Kopf ``u32 Magic | 16 Byte IPv6 | u16 Port | u16 Länge``.

Der Kopf wird hier mit eigenem struct gebaut, nicht mit ``gameworld.play.framing``
(Gegenprobe nie mit dem Muster der Umsetzung). Schließt der Server das Relais (etwa
weil der Wächter einen fremden Namen erkennt), verhält sich der Socket wie ein UDP-Socket
ohne Gegenstelle: sendto verwirft still, recvfrom läuft in den Timeout.
"""

from __future__ import annotations

import ipaddress
import struct
import time
from contextlib import ExitStack

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Origin

MAGIC = 0x778B4CF6
HEAD = struct.Struct("!I16sHH")
VIRTUAL_PORT = 30000
CONNECT_SECONDS = 5.0


class RelayRefusedError(ConnectionError):
    """NEWADDR oder BIND wurde abgelehnt; ``code`` ist der Abschlusscode des Servers."""

    def __init__(self, stage: str, code: int | None) -> None:
        super().__init__(f"{stage} abgelehnt (Code {code})")
        self.stage = stage
        self.code = code


def _head(host: str, port: int, length: int) -> bytes:
    ip = ipaddress.ip_address(host)
    raw = ipaddress.IPv6Address(f"::ffff:{ip}").packed if ip.version == 4 else ip.packed
    return HEAD.pack(MAGIC, raw, port, length)


def _close_code(conn: ClientConnection) -> int | None:
    """Code aus dem Close-Frame des Servers (None, solange offen)."""
    code = conn.close_code
    return None if code is None else int(code)


def request_passcode(url: str, origin: str) -> str:
    """Erste Verbindung: NEWADDR, Passcode aus ADDR; RelayRefusedError bei Ablehnung."""
    with connect(url, origin=Origin(origin), open_timeout=CONNECT_SECONDS) as conn:
        conn.send("NEWADDR")
        try:
            reply = conn.recv(timeout=CONNECT_SECONDS)
        except ConnectionClosed:
            raise RelayRefusedError("NEWADDR", _close_code(conn)) from None
    if not isinstance(reply, str):
        raise RelayRefusedError("NEWADDR", None)
    parts = reply.split(" ")
    if len(parts) != 4 or parts[0] != "ADDR":
        raise RelayRefusedError("NEWADDR", None)
    return parts[2]


class WsDatagramSocket:
    """Socket-Ersatz für Probe über NEWADDR und BIND am Gameworld-Proxy."""

    def __init__(self, url: str, origin: str) -> None:
        passcode = request_passcode(url, origin)
        self._stack = ExitStack()
        self._conn = self._stack.enter_context(connect(url, origin=Origin(origin), open_timeout=CONNECT_SECONDS))
        self._conn.send(f"BIND {passcode} UDP {VIRTUAL_PORT}")
        try:
            reply = self._conn.recv(timeout=CONNECT_SECONDS)
        except ConnectionClosed:
            self._stack.close()
            raise RelayRefusedError("BIND", _close_code(self._conn)) from None
        if reply != "BIND OK":
            self._stack.close()
            raise RelayRefusedError("BIND", _close_code(self._conn))
        self._timeout: float | None = None
        self.closed_by_server = False
        self.sent = 0
        self.received = 0

    @property
    def close_code(self) -> int | None:
        """Abschlusscode des Servers, sobald das Relais geschlossen ist."""
        return _close_code(self._conn)

    def settimeout(self, value: float | None, /) -> None:
        self._timeout = value

    def sendto(self, data: bytes, address: tuple[str, int], /) -> int:
        host, port = address
        if self.closed_by_server:
            return len(data)
        try:
            self._conn.send(_head(host, port, len(data)) + data)
        except ConnectionClosed:
            self.closed_by_server = True
        else:
            self.sent += 1
        return len(data)

    def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[str, int]]:
        deadline = None if self._timeout is None else time.monotonic() + self._timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
            if self.closed_by_server:
                # Wie UDP ohne Gegenstelle: nichts kommt mehr.
                if remaining is not None:
                    time.sleep(remaining)
                raise TimeoutError("Relais geschlossen")
            try:
                message = self._conn.recv(timeout=remaining)
            except ConnectionClosed:
                self.closed_by_server = True
                continue
            if isinstance(message, str):
                continue
            magic, raw_ip, port, length = HEAD.unpack_from(message)
            if magic != MAGIC or len(message) != HEAD.size + length:
                continue
            ip = ipaddress.IPv6Address(raw_ip)
            self.received += 1
            payload = message[HEAD.size :]
            return payload[:bufsize], (str(ip.ipv4_mapped or ip), port)

    def close(self) -> None:
        self._stack.close()
