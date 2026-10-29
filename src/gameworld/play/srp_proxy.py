"""SRP takeover by the proxy (variant A, 04.2-09, D-10 preferred).

The proxy is itself an SRP client towards the world: in ``TOSERVER_SRP_BYTES_A`` it replaces
the browser's A with its own A_p, passes ``TOCLIENT_SRP_BYTES_S_B`` through unchanged
and meanwhile computes the proof M_p with the real password of the ticket account, which it inserts into
``TOSERVER_SRP_BYTES_M``. The browser knows only a worthless placeholder password;
the real play password never leaves the server.

The SRP computation (``SrpClient``, N and G) is a single source of truth: ``N`` and ``G`` come from
``gameworld.provisioner.luanti_auth``, ``SrpClient`` was moved here from ``tests/e2e/luanti_probe.py``
(which now only imports it).

Mandatory rules (otherwise account takeover, RESEARCH pattern 4 and threat register):

- The name comparison happens in the ``ClientGuard`` before any replacement (relay.py), the password
  comes only from ``check_play_access(ticket.uid)``.
- ``TOSERVER_SRP_BYTES_M`` before a seen ``S_B`` and a second ``TOSERVER_SRP_BYTES_A``
  with a different sequence number after ``S_B`` end the session.
- Any SPLIT before ``AUTH_ACCEPT`` and any SPLIT with an SRP command in chunk 0 end the
  session (defense in depth, decision by ``inner_ptype`` and ``split_command``).
- A parse error ends the session, a packet is never passed through unchecked.
- A resend of the same sequence number returns the byte-identical replacement (cache per seq).
"""

from __future__ import annotations

import hashlib
import secrets
import struct

from gameworld.play import mtp
from gameworld.provisioner.luanti_auth import G, N

# Worthless placeholder password for the browser; the server does not know it.
PLACEHOLDER_PASSWORD = "gameworld"  # noqa: S105

N_LEN = (N.bit_length() + 7) // 8


def _bin(n: int) -> bytes:
    """Big-endian without leading zeros (mpz_to_bin)."""
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


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


class SrpClient:
    """Client side of SRP-6a as Luanti expects it (moved here from luanti_probe).

    ``secret`` is injectable for tests; without it a fresh 256-bit random value.
    """

    def __init__(self, name: str, password: str, secret: int | None = None) -> None:
        self.name = name  # original spelling for M, lower-cased only in x
        self.password = password
        self.secret = secrets.randbits(256) if secret is None else secret
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


class SrpTakeoverError(Exception):
    """The SRP session must end; ``reason`` is a fixed ASCII constant, never a value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SrpTakeover:
    """Takes over the SRP login for exactly one player name and its real password.

    ``client_packet`` decides on a datagram from the browser (replace, pass through
    unchanged or end the session), ``server_packet`` reads S_B and AUTH_ACCEPT of the world.
    The password lives only in the ``SrpClient`` in memory; ``__repr__`` names no values.
    """

    def __init__(self, player_name: str, password: str, secret: int | None = None) -> None:
        self._player_name = player_name
        self._srp = SrpClient(player_name, password, secret=secret)
        self._a_cache: dict[int, bytes] = {}
        self._m_cache: dict[int, bytes] = {}
        self._s_b_seen = False
        self._m_proof: bytes | None = None
        self._authed = False

    def __repr__(self) -> str:
        return "SrpTakeover()"

    def client_packet(self, datagram: bytes) -> bytes:
        """Datagram from the browser: replace SRP, otherwise unchanged; violations raise SrpTakeoverError."""
        try:
            parsed = mtp.parse(datagram)
        except mtp.MtpError as exc:
            raise SrpTakeoverError("client_unreadable") from exc
        if parsed.inner_ptype == mtp.PT_SPLIT:
            if not self._authed:
                raise SrpTakeoverError("split_before_auth")
            if parsed.split_command in mtp.SRP_COMMANDS:
                raise SrpTakeoverError("srp_in_split")
            return datagram
        if parsed.command == mtp.TOSERVER_SRP_BYTES_A:
            return self._replace_a(datagram, parsed)
        if parsed.command == mtp.TOSERVER_SRP_BYTES_M:
            return self._replace_m(datagram, parsed)
        return datagram

    def _replace_a(self, datagram: bytes, parsed: mtp.Parsed) -> bytes:
        seq = parsed.reliable_seq
        if seq is None:
            raise SrpTakeoverError("a_not_reliable")
        cached = self._a_cache.get(seq)
        if cached is not None:
            return cached
        if self._s_b_seen:
            # A new A sequence after S_B would mean an auth restart: not allowed.
            raise SrpTakeoverError("second_a")
        packet = mtp.rewrite_payload(datagram, _str16(self._srp.bytes_a()) + b"\x01")
        self._a_cache[seq] = packet
        return packet

    def _replace_m(self, datagram: bytes, parsed: mtp.Parsed) -> bytes:
        seq = parsed.reliable_seq
        if seq is None:
            raise SrpTakeoverError("m_not_reliable")
        cached = self._m_cache.get(seq)
        if cached is not None:
            return cached
        if not self._s_b_seen or self._m_proof is None:
            raise SrpTakeoverError("m_before_s_b")
        packet = mtp.rewrite_payload(datagram, _str16(self._m_proof))
        self._m_cache[seq] = packet
        return packet

    def server_packet(self, datagram: bytes) -> None:
        """Datagram from the world: S_B computes M_p, AUTH_ACCEPT releases the split rule."""
        try:
            parsed = mtp.parse(datagram)
        except mtp.MtpError as exc:
            raise SrpTakeoverError("server_unreadable") from exc
        if parsed.command == mtp.TOCLIENT_SRP_BYTES_S_B:
            salt, bytes_b = self._read_s_b(parsed.payload)
            self._m_proof = self._srp.process(salt, bytes_b)
            self._s_b_seen = True
        elif parsed.command == mtp.TOCLIENT_AUTH_ACCEPT:
            self._authed = True

    @staticmethod
    def _read_s_b(payload: bytes) -> tuple[bytes, bytes]:
        """Reads u16 salt length + salt + u16 B length + B; any wrong length ends the session."""
        try:
            salt_len = struct.unpack_from(">H", payload, 0)[0]
            salt = payload[2 : 2 + salt_len]
            b_len = struct.unpack_from(">H", payload, 2 + salt_len)[0]
            bytes_b = payload[4 + salt_len : 4 + salt_len + b_len]
        except struct.error as exc:
            raise SrpTakeoverError("s_b_malformed") from exc
        if len(salt) != salt_len or len(bytes_b) != b_len or b_len == 0:
            raise SrpTakeoverError("s_b_malformed")
        return salt, bytes_b
