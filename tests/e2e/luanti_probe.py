"""Minimaler Luanti-Join-Prober (MTP über UDP) mit SRP-Client, nur für Tests.

Belegt Negativ- und Positiv-Join gegen echte Welten ohne Luanti-Client
(Success Criterion 2 der Phase 3). Übernommen aus dem getesteten Spike unter
``.planning/phases/03-zugang-und-rollen/spike/``.

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

import hashlib
import secrets
import socket
import struct
import time

from gameworld.provisioner.luanti_auth import G, N

PROTO = 0x4F457403
SEQ_INITIAL = 65500
N_LEN = (N.bit_length() + 7) // 8
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


def _bin(n: int) -> bytes:
    """Big-Endian ohne führende Nullen (mpz_to_bin)."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _h(*parts: bytes) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def _x(salt: bytes, name: str, password: str) -> int:
    inner = _h(name.lower().encode("utf-8"), b":", password.encode("utf-8"))
    return int.from_bytes(_h(salt, inner), "big")


def _h_nn(a: int, b: int) -> int:
    return int.from_bytes(_h(_bin(a).rjust(N_LEN, b"\0"), _bin(b).rjust(N_LEN, b"\0")), "big")


class SrpClient:
    """Client-Seite von SRP-6a, wie Luanti sie erwartet."""

    def __init__(self, name: str, password: str) -> None:
        self.name = name  # Originalschreibweise für M, kleingeschrieben nur in x
        self.password = password
        self.secret = secrets.randbits(256)
        self.public = pow(G, self.secret, N)

    def bytes_a(self) -> bytes:
        return _bin(self.public)

    def process(self, salt: bytes, bytes_b: bytes) -> bytes:
        server_public = int.from_bytes(bytes_b, "big")
        u = _h_nn(self.public, server_public)
        x = _x(salt, self.name, self.password)
        k = _h_nn(N, G)
        shared = pow((server_public - k * pow(G, x, N)) % N, self.secret + u * x, N)
        key = _h(_bin(shared))
        h_xor = bytes(i ^ j for i, j in zip(_h(_bin(N)), _h(_bin(G)), strict=True))
        return _h(h_xor, _h(self.name.encode("utf-8")), salt, _bin(self.public), _bin(server_public), key)


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


class Probe:
    """Eine UDP-Verbindung im MTP-Protokoll, gerade genug für Init und SRP."""

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
            result = self.handle(channel, data[7:])
            if result is not None:
                return result
        raise TimeoutError("keine Antwort vom Server")

    def handle(self, channel: int, body: bytes) -> tuple[int, bytes] | None:
        """Verarbeitet ein Paket; liefert (Kommando, Daten) bei einem Nutzpaket."""
        ptype = body[0]
        if ptype == 3:  # RELIABLE
            seq = struct.unpack(">H", body[1:3])[0]
            self._send(channel, struct.pack(">BBH", 0, 0, seq))  # ACK
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
    """Ein Join-Versuch; ``result`` ist denied, hello, auth_accept, no_peer_id oder unexpected.

    Ohne Passwort endet der Versuch nach HELLO (``auth_mechs`` 2 heißt: SRP-Konto vorhanden).
    """
    probe = Probe(host, port)
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
