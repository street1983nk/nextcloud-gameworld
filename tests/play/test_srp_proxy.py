"""SRP takeover by the proxy (variant A, 04.2-09), purely against an independent server side.

The server side is rebuilt here by hand after ``src/util/srp.cpp`` (b random,
B = k*v + g^b, S = (A*v^u)^b, M check), and the MTP packets are built with an own struct,
not with ``mtp.rewrite_payload`` or ``framing.pack`` (counter-check never with the
implementation's own pattern). Positive control: the proxy computes with the real password, the
server side accepts M_p. Counter-check: a different password is rejected.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import struct

import pytest

from gameworld.play import mtp
from gameworld.play.mtp import MtpError
from gameworld.play.srp_proxy import (
    PLACEHOLDER_PASSWORD,
    SrpClient,
    SrpTakeover,
    SrpTakeoverError,
)
from gameworld.provisioner.luanti_auth import G, N, make_verifier

PROTO = 0x4F457403
N_LEN = (N.bit_length() + 7) // 8
SALT = bytes(range(16))
REAL_PW = "Sonne-Baum-42"
PLAYER = "Mia"


# --- independent helpers, deliberately without mtp/framing ---


def _bin(n: int) -> bytes:
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _h(*parts: bytes) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def _h_nn(a: int, b: int) -> int:
    return int.from_bytes(_h(_bin(a).rjust(N_LEN, b"\0"), _bin(b).rjust(N_LEN, b"\0")), "big")


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


def _head(peer_id: int = 1, channel: int = 1) -> bytes:
    return struct.pack(">IHB", PROTO, peer_id, channel)


def _reliable(command: int, payload: bytes, seq: int, channel: int = 1) -> bytes:
    """RELIABLE(ORIGINAL command) with payload, as the real client sends it."""
    return _head(channel=channel) + struct.pack(">BH", 3, seq) + b"\x01" + struct.pack(">H", command) + payload


def _reliable_split(chunk0: bytes, seq: int, chunk_num: int = 0, chunk_count: int = 2, split_seq: int = 7) -> bytes:
    """RELIABLE(SPLIT): the inner packet is a SPLIT whose chunk carries the first bytes."""
    split = struct.pack(">BHHH", 2, split_seq, chunk_count, chunk_num) + chunk0
    return _head() + struct.pack(">BH", 3, seq) + split


def _naked_split(chunk0: bytes, seq: int = 0, chunk_num: int = 0, chunk_count: int = 2, split_seq: int = 7) -> bytes:
    """Bare SPLIT without a RELIABLE wrapper; ``seq`` is ignored (no RELIABLE seqnum)."""
    del seq
    return _head() + struct.pack(">BHHH", 2, split_seq, chunk_count, chunk_num) + chunk0


def _a_payload(bytes_a: bytes) -> bytes:
    """Payload of SRP_BYTES_A: u16 length + A + based_on byte 0x01."""
    return _str16(bytes_a) + b"\x01"


def _extract_srp_value(packet: bytes) -> bytes:
    """Reads the first str16 value from the payload of a RELIABLE(ORIGINAL) packet (A or M)."""
    body = packet[7 + 3 + 3 :]  # Head 7 + RELIABLE 3 + ORIGINAL 3
    length = struct.unpack(">H", body[:2])[0]
    return body[2 : 2 + length]


class SrpServer:
    """Server side of SRP-6a after srp.cpp, built independently of the proxy code."""

    def __init__(self, name: str, verifier: str) -> None:
        self.name = name
        _, _, salt_b64, v_b64 = verifier.split("#")
        self.salt = base64.b64decode(salt_b64)
        self.v = int.from_bytes(base64.b64decode(v_b64), "big")
        self.b = secrets.randbits(256)
        k = _h_nn(N, G)
        self.public = (k * self.v + pow(G, self.b, N)) % N

    def s_b_payload(self) -> bytes:
        """Payload of TOCLIENT_SRP_BYTES_S_B: u16 salt length + salt + u16 B length + B."""
        return _str16(self.salt) + _str16(_bin(self.public))

    def verify(self, bytes_a: bytes, bytes_m: bytes) -> bool:
        a = int.from_bytes(bytes_a, "big")
        u = _h_nn(a, self.public)
        shared = pow(a * pow(self.v, u, N), self.b, N)
        key = _h(_bin(shared))
        h_xor = bytes(i ^ j for i, j in zip(_h(_bin(N)), _h(_bin(G)), strict=True))
        expected = _h(h_xor, _h(self.name.encode("utf-8")), self.salt, _bin(a), _bin(self.public), key)
        return expected == bytes_m


def _run_takeover(
    takeover: SrpTakeover, server: SrpServer, a_seq: int = 65501, m_seq: int = 65502
) -> tuple[bytes, bytes]:
    """Plays through A -> S_B -> M; returns (A_p, M_p) from the replaced packets."""
    a_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"client-A-ignored"), a_seq))
    a_p = _extract_srp_value(a_packet)
    takeover.server_packet(_reliable(mtp.TOCLIENT_SRP_BYTES_S_B, server.s_b_payload(), seq=1))
    m_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_M, _str16(b"client-M-ignored"), m_seq))
    m_p = _extract_srp_value(m_packet)
    return a_p, m_p


# --- SrpClient regression (moved from luanti_probe) ---


def test_srp_client_secret_injectable_and_deterministic() -> None:
    first = SrpClient(PLAYER, REAL_PW, secret=12345)
    second = SrpClient(PLAYER, REAL_PW, secret=12345)
    assert first.bytes_a() == second.bytes_a() == _bin(pow(G, 12345, N))
    salt = bytes(range(16))
    b_side = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, salt))
    assert first.process(salt, _bin(b_side.public)) == second.process(salt, _bin(b_side.public))


def test_srp_client_matches_independent_server() -> None:
    server = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, SALT))
    client = SrpClient(PLAYER, REAL_PW)
    proof = client.process(SALT, _bin(server.public))
    assert server.verify(client.bytes_a(), proof)


# --- SrpTakeover positive control and counter-check ---


def test_takeover_login_succeeds_with_real_password() -> None:
    server = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, SALT))
    takeover = SrpTakeover(PLAYER, REAL_PW)
    a_p, m_p = _run_takeover(takeover, server)
    assert server.verify(a_p, m_p), "Positivkontrolle: Server akzeptiert M_p des Proxys"


def test_takeover_login_fails_with_other_password() -> None:
    # The account on the server has a different password than the proxy derives.
    server = SrpServer(PLAYER, make_verifier(PLAYER, "ein-anderes-pw", SALT))
    takeover = SrpTakeover(PLAYER, REAL_PW)
    a_p, m_p = _run_takeover(takeover, server)
    assert not server.verify(a_p, m_p), "Gegenprobe anderes Passwort: Server lehnt M_p ab"


def test_takeover_keeps_header_seq_and_command() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    original = _reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"X" * 32), seq=65501)
    replaced = takeover.client_packet(original)
    assert replaced[:7] == original[:7], "7-Byte-Kopf bleibt"
    assert replaced[7:10] == original[7:10], "RELIABLE-Typ und seqnum bleiben"
    assert replaced[10:13] == original[10:13], "ORIGINAL-Typ und Kommando bleiben"
    assert replaced != original, "die Nutzlast ist ersetzt"


def test_resend_same_seq_is_byte_identical() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    packet = _reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"Y" * 32), seq=65501)
    first = takeover.client_packet(packet)
    second = takeover.client_packet(packet)
    assert first == second, "Resend derselben seqnum liefert byte-gleich denselben Ersatz"


def test_replacement_never_contains_placeholder_password() -> None:
    server = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, SALT))
    takeover = SrpTakeover(PLAYER, REAL_PW)
    a_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"Z" * 32), seq=65501))
    takeover.server_packet(_reliable(mtp.TOCLIENT_SRP_BYTES_S_B, server.s_b_payload(), seq=1))
    m_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_M, _str16(b"m"), seq=65502))
    placeholder = PLACEHOLDER_PASSWORD.encode("utf-8")
    assert placeholder not in a_packet
    assert placeholder not in m_packet


def test_non_srp_packet_is_returned_unchanged() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    init = _reliable(mtp.TOSERVER_INIT, b"beliebige-init-nutzlast", seq=65500)
    assert takeover.client_packet(init) is init


def test_m_before_s_b_ends_session() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"A" * 32), seq=65501))
    with pytest.raises(SrpTakeoverError):
        takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_M, _str16(b"m"), seq=65502))


def test_second_a_with_other_seq_after_s_b_ends_session() -> None:
    server = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, SALT))
    takeover = SrpTakeover(PLAYER, REAL_PW)
    takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"A" * 32), seq=65501))
    takeover.server_packet(_reliable(mtp.TOCLIENT_SRP_BYTES_S_B, server.s_b_payload(), seq=1))
    with pytest.raises(SrpTakeoverError):
        takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"B" * 32), seq=65503))


def test_server_parse_error_ends_session() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    with pytest.raises(SrpTakeoverError):
        takeover.server_packet(b"\x00\x01")  # no valid MTP head


def test_client_parse_error_ends_session() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    with pytest.raises(SrpTakeoverError):
        takeover.client_packet(b"zu kurz")


def test_repr_hides_password() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    assert REAL_PW not in repr(takeover)
    assert PLACEHOLDER_PASSWORD not in repr(takeover)


# --- Split table (RELIABLE(SPLIT) and bare SPLIT), with a positive control ---

_A = struct.pack(">H", mtp.TOSERVER_SRP_BYTES_A)
_M = struct.pack(">H", mtp.TOSERVER_SRP_BYTES_M)
_FIRST = struct.pack(">H", mtp.TOSERVER_FIRST_SRP)

# Each case: (build function, chunk 0 bytes, after_auth, should_end)
_SPLIT_CASES = [
    # Before AUTH_ACCEPT every SPLIT ends, whatever the content (defense in depth).
    pytest.param(_reliable_split, _A, False, True, id="reliable_split_A_before_auth"),
    pytest.param(_reliable_split, _M, False, True, id="reliable_split_M_before_auth"),
    pytest.param(_reliable_split, _FIRST, False, True, id="reliable_split_first_srp_before_auth"),
    pytest.param(_reliable_split, b"\x00\x2f", False, True, id="reliable_split_harmlos_before_auth"),
    pytest.param(_naked_split, _A, False, True, id="naked_split_A_before_auth"),
    pytest.param(_naked_split, _FIRST, False, True, id="naked_split_first_srp_before_auth"),
    # After AUTH_ACCEPT: SPLIT with an SRP command in chunk 0 stays forbidden.
    pytest.param(_reliable_split, _A, True, True, id="reliable_split_A_after_auth"),
    pytest.param(_naked_split, _M, True, True, id="naked_split_M_after_auth"),
]


@pytest.mark.parametrize(("build", "chunk0", "after_auth", "should_end"), _SPLIT_CASES)
def test_split_rules(build, chunk0: bytes, after_auth: bool, should_end: bool) -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    if after_auth:
        takeover.server_packet(_reliable(mtp.TOCLIENT_AUTH_ACCEPT, b"", seq=2))
    packet = build(chunk0, seq=65510)
    assert should_end
    with pytest.raises(SrpTakeoverError):
        takeover.client_packet(packet)


def test_reliable_split_chunk1_after_auth_passes_unchanged() -> None:
    """Positive control: a harmless RELIABLE(SPLIT) chunk 1 after AUTH_ACCEPT passes unchanged."""
    takeover = SrpTakeover(PLAYER, REAL_PW)
    takeover.server_packet(_reliable(mtp.TOCLIENT_AUTH_ACCEPT, b"", seq=2))
    packet = _reliable_split(b"nutzdaten-chunk-eins", seq=65510, chunk_num=1, chunk_count=2)
    assert takeover.client_packet(packet) is packet


def test_rewrite_payload_rejects_non_reliable_original() -> None:
    # A bare ORIGINAL is not a RELIABLE(ORIGINAL) and must not be rewritten.
    original = _head() + b"\x01" + struct.pack(">H", mtp.TOSERVER_SRP_BYTES_A) + _a_payload(b"A" * 32)
    with pytest.raises(MtpError):
        mtp.rewrite_payload(original, _a_payload(b"B" * 32))


def test_rewrite_payload_keeps_frame_and_replaces_payload() -> None:
    original = _reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"A" * 32), seq=65501)
    new = mtp.rewrite_payload(original, _a_payload(b"B" * 48))
    assert new[:13] == original[:13], "Kopf, RELIABLE und ORIGINAL bleiben"
    assert _extract_srp_value(new) == b"B" * 48
