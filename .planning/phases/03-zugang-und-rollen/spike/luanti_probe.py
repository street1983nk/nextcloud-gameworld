"""Minimaler Luanti-Join-Prober (MTP über UDP) für Negativ- und Positiv-Join-Tests.

Ablauf wie der echte Client (src/network/mtp/threads.cpp, src/client/client.cpp):
1. Dummy-Paket zuverlässig mit peer_id 0 -> Server antwortet SET_PEER_ID.
2. TOSERVER_INIT (0x02) auf Kanal 1 -> TOCLIENT_HELLO (0x02) oder ACCESS_DENIED (0x0A).
3. Optional: SRP (0x51 A, 0x52 M) -> TOCLIENT_AUTH_ACCEPT (0x03) oder ACCESS_DENIED.
"""

from __future__ import annotations

import socket
import struct
import time

from luanti_srp import SrpClient

PROTO = 0x4F457403
SEQ_INITIAL = 65500
ACCESS_DENIED_CODES = {
    0: "WRONG_PASSWORD", 1: "UNEXPECTED_DATA", 2: "SINGLEPLAYER", 3: "WRONG_VERSION",
    4: "WRONG_CHARS_IN_NAME", 5: "WRONG_NAME", 6: "TOO_MANY_USERS", 7: "EMPTY_PASSWORD",
    8: "ALREADY_CONNECTED", 9: "SERVER_FAIL", 10: "CUSTOM_STRING", 11: "SHUTDOWN", 12: "CRASH",
}


def _str16(b: bytes) -> bytes:
    return struct.pack(">H", len(b)) + b


class Probe:
    def __init__(self, host: str, port: int, timeout: float = 3.0) -> None:
        self.addr = (host, port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.peer_id = 0
        self.seq = {0: SEQ_INITIAL, 1: SEQ_INITIAL, 2: SEQ_INITIAL}

    def _send(self, channel: int, body: bytes) -> None:
        self.sock.sendto(struct.pack(">IHB", PROTO, self.peer_id, channel) + body, self.addr)

    def send_reliable(self, channel: int, command: int, payload: bytes = b"") -> None:
        seq = self.seq[channel]
        self.seq[channel] = (seq + 1) % 65536
        self._send(channel, struct.pack(">BH", 3, seq) + b"\x01" + struct.pack(">H", command) + payload)

    def send_original(self, channel: int, command: int, payload: bytes) -> None:
        self._send(channel, b"\x01" + struct.pack(">H", command) + payload)

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
            body = data[7:]
            result = self._handle(channel, body)
            if result is not None:
                return result
        raise TimeoutError("keine Antwort vom Server")

    def _handle(self, channel: int, body: bytes) -> tuple[int, bytes] | None:
        ptype = body[0]
        if ptype == 3:  # RELIABLE
            seq = struct.unpack(">H", body[1:3])[0]
            self._send(channel, struct.pack(">BBH", 0, 0, seq))  # ACK
            return self._handle(channel, body[3:])
        if ptype == 0:  # CONTROL
            ctrl = body[1]
            if ctrl == 1:  # SET_PEER_ID
                self.peer_id = struct.unpack(">H", body[2:4])[0]
            return None
        if ptype == 1:  # ORIGINAL
            command = struct.unpack(">H", body[1:3])[0]
            return command, body[3:]
        return None  # SPLIT kommt in dieser Phase nicht vor

    def close(self) -> None:
        try:
            self._send(0, struct.pack(">BB", 0, 3))  # DISCO
        finally:
            self.sock.close()


def _parse_denied(data: bytes) -> dict[str, object]:
    code = data[0]
    reason = ""
    if len(data) >= 3:
        length = struct.unpack(">H", data[1:3])[0]
        reason = data[3 : 3 + length].decode("utf-8", "replace")
    return {"result": "denied", "code": ACCESS_DENIED_CODES.get(code, code), "reason": reason}


def join(host: str, port: int, name: str, password: str | None = None, timeout: float = 6.0) -> dict[str, object]:
    probe = Probe(host, port)
    deadline = time.monotonic() + timeout
    try:
        probe.send_reliable(0, 0)  # Dummy, Server vergibt peer_id
        while probe.peer_id == 0 and time.monotonic() < deadline:
            try:
                data, _ = probe.sock.recvfrom(65535)
            except TimeoutError:
                probe.send_reliable(0, 0)
                continue
            probe._handle(data[6], data[7:])
        if probe.peer_id == 0:
            return {"result": "no_peer_id"}
        init = struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + _str16(name.encode())
        probe.send_original(1, 0x02, init)
        command, data = probe.recv_command(deadline)
        if command == 0x0A:
            return _parse_denied(data)
        if command != 0x02:
            return {"result": "unexpected", "command": command}
        ser, _unused, proto, mechs = struct.unpack(">BHHI", data[:9])
        hello = {"result": "hello", "proto": proto, "auth_mechs": mechs}
        if password is None:
            return hello
        srp = SrpClient(name, password)
        probe.send_reliable(1, 0x51, _str16(srp.bytes_A()) + b"\x01")
        command, data = probe.recv_command(deadline)
        if command == 0x0A:
            return {**hello, **_parse_denied(data), "stage": "A"}
        if command != 0x60:
            return {**hello, "result": "unexpected", "command": command}
        slen = struct.unpack(">H", data[:2])[0]
        salt = data[2 : 2 + slen]
        blen = struct.unpack(">H", data[2 + slen : 4 + slen])[0]
        bytes_b = data[4 + slen : 4 + slen + blen]
        probe.send_reliable(1, 0x52, _str16(srp.process(salt, bytes_b)))
        command, data = probe.recv_command(deadline)
        if command == 0x03:
            return {**hello, "result": "auth_accept"}
        if command == 0x0A:
            return {**hello, **_parse_denied(data), "stage": "M"}
        return {**hello, "result": "unexpected", "command": command}
    finally:
        probe.close()
