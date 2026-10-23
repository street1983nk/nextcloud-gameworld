"""Minimaler Luanti-Join-Prober (MTP über UDP) mit SRP-Client, nur für Tests.

Belegt Negativ- und Positiv-Join gegen echte Welten ohne Luanti-Client
(Success Criterion 2 der Phase 3). Übernommen aus dem getesteten Spike unter
``.planning/phases/03-zugang-und-rollen/spike/``. ``session()`` (Phase 4,
Spike ``.planning/phases/04-spielzeitlimits/spike/session_probe.py``) tritt
vollständig bis ``on_joinplayer`` bei, hält die Sitzung und schneidet Chat
und Trennen mit.

Ablauf wie der echte Client (Luanti 5.17.0: ``src/network/mtp/internal.h``,
``src/network/mtp/threads.cpp``, ``src/client/client.cpp`` sendInit/startAuth,
``src/network/serverpackethandler.cpp`` handleCommand_Init/SrpBytesA/SrpBytesM):

1. Dummy-Paket zuverlässig mit peer_id 0, der Server antwortet SET_PEER_ID.
2. TOSERVER_INIT (0x02) auf Kanal 1, Antwort TOCLIENT_HELLO (0x02) oder ACCESS_DENIED (0x0A).
3. Optional SRP: TOSERVER_SRP_BYTES_A (0x51) und _M (0x52), Antwort AUTH_ACCEPT (0x03) oder ACCESS_DENIED.

SRP-Client nach ``src/util/srp.cpp``: u = H(pad(A)|pad(B)), k = H(N|pad(g)),
S = (B - k*g^x)^(a + u*x) mod N, K = H(S), M = H(H(N) xor H(g), H(Name), Salz, A, B, K).
"""

from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
from collections.abc import Callable
from typing import Protocol

from gameworld.play.srp_proxy import SrpClient

PROTO = 0x4F457403
SEQ_INITIAL = 65500
ACCESS_DENIED_CODES = {
    0: "WRONG_PASSWORD",
    1: "UNEXPECTED_DATA",
    2: "SINGLEPLAYER",
    3: "WRONG_VERSION",
    4: "WRONG_CHARS_IN_NAME",
    5: "WRONG_NAME",
    6: "TOO_MANY_USERS",
    7: "EMPTY_PASSWORD",
    8: "ALREADY_CONNECTED",
    9: "SERVER_FAIL",
    10: "CUSTOM_STRING",
    11: "SHUTDOWN",
    12: "CRASH",
}


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


class DatagramSocket(Protocol):
    """Was Probe von einem Socket braucht; UDP oder das WebSocket-Relais (tests/e2e/ws_datagram.py)."""

    def sendto(self, data: bytes, address: tuple[str, int], /) -> int: ...

    def recvfrom(self, bufsize: int, /) -> tuple[bytes, tuple[str, int]]: ...

    def settimeout(self, value: float | None, /) -> None: ...

    def close(self) -> None: ...


SocketFactory = Callable[[], DatagramSocket]


def udp_socket() -> DatagramSocket:
    """Vorgabe: echter UDP-Socket wie bisher."""
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


class Probe:
    """Eine UDP-Verbindung im MTP-Protokoll, gerade genug für Init und SRP."""

    def __init__(self, host: str, port: int, timeout: float = 3.0, sock_factory: SocketFactory = udp_socket) -> None:
        self.addr = (host, port)
        self.sock = sock_factory()
        self.sock.settimeout(timeout)
        self.peer_id = 0
        self.seq = {0: SEQ_INITIAL, 1: SEQ_INITIAL, 2: SEQ_INITIAL}

    def send_raw(self, channel: int, body: bytes) -> None:
        """Ein MTP-Paket ohne Zuverlässigkeitsschicht (ACK, PING, DISCO)."""
        self.sock.sendto(struct.pack(">IHB", PROTO, self.peer_id, channel) + body, self.addr)

    def send_reliable(self, channel: int, command: int, payload: bytes = b"") -> None:
        seq = self.seq[channel]
        self.seq[channel] = (seq + 1) % 65536
        self.send_raw(channel, struct.pack(">BH", 3, seq) + b"\x01" + struct.pack(">H", command) + payload)

    def send_original(self, channel: int, command: int, payload: bytes) -> None:
        self.send_raw(channel, b"\x01" + struct.pack(">H", command) + payload)

    def recv_command(self, deadline: float) -> tuple[int, bytes]:
        """Nächstes Nutzpaket (Kommando, Daten); quittiert zuverlässige Pakete."""
        while time.monotonic() < deadline:
            try:
                data, _ = self.sock.recvfrom(65535)
            except TimeoutError:
                continue
            proto, _sender, channel = struct.unpack(">IHB", data[:7])
            if proto != PROTO:
                continue
            result = self.handle(channel, data[7:])
            if result is not None:
                return result
        raise TimeoutError("keine Antwort vom Server")

    def handle(self, channel: int, body: bytes) -> tuple[int, bytes] | None:
        """Verarbeitet ein Paket; liefert (Kommando, Daten) bei einem Nutzpaket."""
        ptype = body[0]
        if ptype == 3:  # RELIABLE
            seq = struct.unpack(">H", body[1:3])[0]
            self.send_raw(channel, struct.pack(">BBH", 0, 0, seq))  # ACK
            return self.handle(channel, body[3:])
        if ptype == 0:  # CONTROL
            if body[1] == 1:  # SET_PEER_ID
                self.peer_id = struct.unpack(">H", body[2:4])[0]
            return None
        if ptype == 1:  # ORIGINAL
            command = struct.unpack(">H", body[1:3])[0]
            return command, body[3:]
        return None  # SPLIT kommt bei Init und SRP nicht vor

    def close(self) -> None:
        try:
            self.send_raw(0, struct.pack(">BB", 0, 3))  # DISCO
        finally:
            self.sock.close()


def _parse_denied(data: bytes) -> dict[str, object]:
    code = data[0]
    reason = ""
    if len(data) >= 3:
        length = struct.unpack(">H", data[1:3])[0]
        reason = data[3 : 3 + length].decode("utf-8", "replace")
    return {"result": "denied", "code": ACCESS_DENIED_CODES.get(code, code), "reason": reason}


def join(
    host: str,
    port: int,
    name: str,
    password: str | None = None,
    timeout: float = 6.0,
    sock_factory: SocketFactory = udp_socket,
) -> dict[str, object]:
    """Ein Join-Versuch; ``result`` ist denied, hello, auth_accept, no_peer_id oder unexpected.

    Ohne Passwort endet der Versuch nach HELLO (``auth_mechs`` 2 heißt: SRP-Konto vorhanden).
    ``sock_factory`` tauscht nur den Transport (Vorgabe UDP), die Protokoll-Logik bleibt gleich.
    """
    probe = Probe(host, port, sock_factory=sock_factory)
    deadline = time.monotonic() + timeout
    try:
        probe.send_reliable(0, 0)  # Dummy, der Server vergibt die peer_id
        while probe.peer_id == 0 and time.monotonic() < deadline:
            try:
                data, _ = probe.sock.recvfrom(65535)
            except TimeoutError:
                probe.send_reliable(0, 0)
                continue
            probe.handle(data[6], data[7:])
        if probe.peer_id == 0:
            return {"result": "no_peer_id"}
        init = struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + _str16(name.encode())
        probe.send_original(1, 0x02, init)
        command, data = probe.recv_command(deadline)
        if command == 0x0A:
            return _parse_denied(data)
        if command != 0x02:
            return {"result": "unexpected", "command": command}
        _ser, _unused, proto, mechs = struct.unpack(">BHHI", data[:9])
        hello: dict[str, object] = {"result": "hello", "proto": proto, "auth_mechs": mechs}
        if password is None:
            return hello
        srp = SrpClient(name, password)
        probe.send_reliable(1, 0x51, _str16(srp.bytes_a()) + b"\x01")
        command, data = probe.recv_command(deadline)
        if command == 0x0A:
            return {**hello, **_parse_denied(data), "stage": "A"}
        if command != 0x60:
            return {**hello, "result": "unexpected", "command": command}
        salt_len = struct.unpack(">H", data[:2])[0]
        salt = data[2 : 2 + salt_len]
        b_len = struct.unpack(">H", data[2 + salt_len : 4 + salt_len])[0]
        bytes_b = data[4 + salt_len : 4 + salt_len + b_len]
        probe.send_reliable(1, 0x52, _str16(srp.process(salt, bytes_b)))
        command, data = probe.recv_command(deadline)
        if command == 0x03:
            return {**hello, "result": "auth_accept"}
        if command == 0x0A:
            return {**hello, **_parse_denied(data), "stage": "M"}
        return {**hello, "result": "unexpected", "command": command}
    finally:
        probe.close()


TOSERVER_INIT2 = 0x11
TOSERVER_CLIENT_READY = 0x43
TOCLIENT_HELLO = 0x02
TOCLIENT_AUTH_ACCEPT = 0x03
TOCLIENT_ACCESS_DENIED = 0x0A
TOCLIENT_CHAT_MESSAGE = 0x2F
TOCLIENT_SRP_BYTES_S_B = 0x60
SESSION_VERSION = b"5.17.0-gameworld-test"
FORMSPEC_VERSION = 10
PING_SECONDS = 3.0


def _wide(data: bytes, offset: int) -> tuple[str, int]:
    """wstring aus dem Protokoll: u16 Länge in Zeichen, dann UTF-16BE."""
    length = struct.unpack(">H", data[offset : offset + 2])[0]
    raw = data[offset + 2 : offset + 2 + 2 * length]
    return raw.decode("utf-16-be", "replace"), offset + 2 + 2 * length


def _chat(data: bytes) -> str:
    """Text einer TOCLIENT_CHAT_MESSAGE: u8 Version, u8 Typ, wstring Absender, wstring Text, u64 Zeit."""
    try:
        _sender, offset = _wide(data, 2)
        message, _ = _wide(data, offset)
    except (struct.error, IndexError):
        return "<unlesbar>"
    return message


def session(
    host: str,
    port: int,
    name: str,
    password: str,
    hold: float,
    timeout: float = 8.0,
) -> dict[str, object]:
    """Vollständiger Join bis ``on_joinplayer``, dann bis ``hold`` Sekunden halten oder bis zum Kick.

    Nach AUTH_ACCEPT wie der echte Client: TOSERVER_INIT2 (Kanal 1, zuverlässig,
    Sprache) und TOSERVER_CLIENT_READY (Version, Formspec-Version); danach
    zuverlässige Pakete quittieren, alle 3 s CONTROL PING senden, Chat (0x2F)
    und ACCESS_DENIED (0x0A) mitschneiden. ``result`` ist held, kicked, denied
    (vor dem Betreten), unexpected oder no_peer_id; ``events`` ist eine Liste
    von ``{"t": Sekunden seit CLIENT_READY, "kind": "chat" | "kick", "text": ...}``.
    ``timeout`` gilt für die Anmeldung bis AUTH_ACCEPT, ``hold`` danach.
    """
    probe = Probe(host, port)
    events: list[dict[str, object]] = []
    deadline = time.monotonic() + timeout
    try:
        probe.send_reliable(0, 0)
        while probe.peer_id == 0 and time.monotonic() < deadline:
            try:
                data, _ = probe.sock.recvfrom(65535)
            except TimeoutError:
                probe.send_reliable(0, 0)
                continue
            probe.handle(data[6], data[7:])
        if probe.peer_id == 0:
            return {"result": "no_peer_id"}
        init = struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + _str16(name.encode())
        probe.send_original(1, 0x02, init)
        command, data = probe.recv_command(deadline)
        if command == TOCLIENT_ACCESS_DENIED:
            return {**_parse_denied(data), "stage": "init"}
        if command != TOCLIENT_HELLO:
            return {"result": "unexpected", "command": command}
        srp = SrpClient(name, password)
        probe.send_reliable(1, 0x51, _str16(srp.bytes_a()) + b"\x01")
        command, data = probe.recv_command(deadline)
        if command == TOCLIENT_ACCESS_DENIED:
            return {**_parse_denied(data), "stage": "A"}
        if command != TOCLIENT_SRP_BYTES_S_B:
            return {"result": "unexpected", "command": command}
        salt_len = struct.unpack(">H", data[:2])[0]
        salt = data[2 : 2 + salt_len]
        b_len = struct.unpack(">H", data[2 + salt_len : 4 + salt_len])[0]
        probe.send_reliable(1, 0x52, _str16(srp.process(salt, data[4 + salt_len : 4 + salt_len + b_len])))
        command, data = probe.recv_command(deadline)
        if command == TOCLIENT_ACCESS_DENIED:
            return {**_parse_denied(data), "stage": "M"}
        if command != TOCLIENT_AUTH_ACCEPT:
            return {"result": "unexpected", "command": command}
        probe.send_reliable(1, TOSERVER_INIT2, _str16(b"de"))
        ready = struct.pack(">BBBB", 5, 17, 0, 0) + _str16(SESSION_VERSION) + struct.pack(">H", FORMSPEC_VERSION)
        probe.send_reliable(1, TOSERVER_CLIENT_READY, ready)
        joined_at = time.monotonic()
        last_ping = joined_at
        probe.sock.settimeout(0.5)
        while time.monotonic() - joined_at < hold:
            if time.monotonic() - last_ping > PING_SECONDS:
                probe.send_raw(0, struct.pack(">BB", 0, 2))  # CONTROL PING
                last_ping = time.monotonic()
            try:
                command, data = probe.recv_command(time.monotonic() + 0.5)
            except TimeoutError:
                continue
            t = round(time.monotonic() - joined_at, 1)
            if command == TOCLIENT_CHAT_MESSAGE:
                events.append({"t": t, "kind": "chat", "text": _chat(data)})
            elif command == TOCLIENT_ACCESS_DENIED:
                denied = _parse_denied(data)
                events.append({"t": t, "kind": "kick", "text": str(denied["reason"])})
                return {
                    "result": "kicked",
                    "after_s": t,
                    "code": denied["code"],
                    "reason": denied["reason"],
                    "events": events,
                }
        return {"result": "held", "after_s": round(time.monotonic() - joined_at, 1), "events": events}
    finally:
        probe.close()


def main(argv: list[str] | None = None) -> int:
    """CLI für Abnahmeskripte: ein Join-Versuch, Ergebnis als JSON auf stdout.

    Das Passwort erscheint nie in der Ausgabe; ``reason`` stammt vom Server.
    Exit 0 auch bei ``denied``: Die Bewertung macht der Aufrufer (jq).
    Mit ``--hold SEKUNDEN`` (Passwort nötig) läuft statt des Join-Versuchs eine
    Sitzung bis ``on_joinplayer``, die so lange gehalten wird (session()).
    """
    parser = argparse.ArgumentParser(description="Luanti-Join-Prober (nur Tests)")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("name")
    parser.add_argument("password", nargs="?", default=None)
    parser.add_argument("--timeout", type=float, default=6.0)
    parser.add_argument("--hold", type=float, default=None, metavar="SEKUNDEN")
    parser.add_argument("--rejoin-after", type=float, default=None, metavar="SEKUNDEN")
    args = parser.parse_args(argv)
    if args.hold is not None and args.password is None:
        parser.error("--hold braucht ein Passwort")
    if args.rejoin_after is not None and args.hold is None:
        parser.error("--rejoin-after braucht --hold")
    try:
        if args.hold is None:
            result = join(args.host, args.port, args.name, args.password, timeout=args.timeout)
        elif args.rejoin_after is None:
            result = session(args.host, args.port, args.name, args.password, args.hold, timeout=args.timeout)
        else:
            result = hold_then_rejoin(
                args.host, args.port, args.name, args.password, args.hold, args.rejoin_after, timeout=args.timeout
            )
    except (TimeoutError, OSError):
        result = {"result": "timeout"}
    print(json.dumps(result, ensure_ascii=False))
    return 0


def hold_then_rejoin(
    host: str, port: int, name: str, password: str, hold: float, rejoin_after: float, timeout: float = 8.0
) -> dict[str, object]:
    """Sitzung halten, trennen und nach ``rejoin_after`` Sekunden im SELBEN Prozess erneut beitreten.

    Für die Wiederbeitritts-Sperre (K6): Zwei getrennte Prober-Aufrufe brauchen je
    einen Prozessstart (uv), dessen Dauer schwankt und die 2-s-Sperre des Mods
    manchmal schon überschreitet. Hier ist der Abstand zwischen Trennen und neuem
    Versuch gemessen (``gap_s``), der Aufrufer prüft ihn mit.
    """
    held = session(host, port, name, password, hold, timeout=timeout)
    left_at = time.monotonic()
    time.sleep(rejoin_after)
    gap = time.monotonic() - left_at
    rejoin = join(host, port, name, password, timeout=timeout)
    return {"result": held.get("result"), "session": held, "rejoin": rejoin, "gap_s": round(gap, 3)}


if __name__ == "__main__":
    sys.exit(main())
