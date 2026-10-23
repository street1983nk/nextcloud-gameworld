"""SRP-Uebernahme durch den Proxy (Variante A, 04.2-09), rein gegen eine unabhaengige Server-Seite.

Die Server-Seite ist hier von Hand nach ``src/util/srp.cpp`` nachgebaut (b zufaellig,
B = k*v + g^b, S = (A*v^u)^b, M-Pruefung), und die MTP-Pakete werden mit eigenem struct
gebaut, nicht mit ``mtp.rewrite_payload`` oder ``framing.pack`` (Gegenprobe nie mit dem
Muster der Umsetzung). Positivkontrolle: der Proxy rechnet mit dem echten Passwort, die
Server-Seite akzeptiert M_p. Gegenprobe: ein anderes Passwort wird abgelehnt.
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


# --- unabhaengige Hilfen, bewusst ohne mtp/framing ---


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
    """RELIABLE(ORIGINAL command) mit Nutzlast, so wie der echte Client sendet."""
    return _head(channel=channel) + struct.pack(">BH", 3, seq) + b"\x01" + struct.pack(">H", command) + payload


def _reliable_split(chunk0: bytes, seq: int, chunk_num: int = 0, chunk_count: int = 2, split_seq: int = 7) -> bytes:
    """RELIABLE(SPLIT): inneres Paket ist ein SPLIT, dessen Chunk die ersten Bytes traegt."""
    split = struct.pack(">BHHH", 2, split_seq, chunk_count, chunk_num) + chunk0
    return _head() + struct.pack(">BH", 3, seq) + split


def _naked_split(chunk0: bytes, chunk_num: int = 0, chunk_count: int = 2, split_seq: int = 7) -> bytes:
    """Nacktes SPLIT ohne RELIABLE-Huelle."""
    return _head() + struct.pack(">BHHH", 2, split_seq, chunk_count, chunk_num) + chunk0


def _a_payload(bytes_a: bytes) -> bytes:
    """Nutzlast von SRP_BYTES_A: u16 Laenge + A + based_on-Byte 0x01."""
    return _str16(bytes_a) + b"\x01"


def _extract_srp_value(packet: bytes) -> bytes:
    """Liest den ersten str16-Wert aus der Nutzlast eines RELIABLE(ORIGINAL)-Pakets (A oder M)."""
    body = packet[7 + 3 + 3 :]  # Kopf 7 + RELIABLE 3 + ORIGINAL 3
    length = struct.unpack(">H", body[:2])[0]
    return body[2 : 2 + length]


class SrpServer:
    """Server-Seite von SRP-6a nach srp.cpp, unabhaengig vom Proxy-Code gebaut."""

    def __init__(self, name: str, verifier: str) -> None:
        self.name = name
        _, _, salt_b64, v_b64 = verifier.split("#")
        self.salt = base64.b64decode(salt_b64)
        self.v = int.from_bytes(base64.b64decode(v_b64), "big")
        self.b = secrets.randbits(256)
        k = _h_nn(N, G)
        self.public = (k * self.v + pow(G, self.b, N)) % N

    def s_b_payload(self) -> bytes:
        """Nutzlast von TOCLIENT_SRP_BYTES_S_B: u16 Salzlaenge + Salz + u16 B-Laenge + B."""
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
    """Spielt A -> S_B -> M durch; liefert (A_p, M_p) aus den ersetzten Paketen."""
    a_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"client-A-ignored"), a_seq))
    a_p = _extract_srp_value(a_packet)
    takeover.server_packet(_reliable(mtp.TOCLIENT_SRP_BYTES_S_B, server.s_b_payload(), seq=1))
    m_packet = takeover.client_packet(_reliable(mtp.TOSERVER_SRP_BYTES_M, _str16(b"client-M-ignored"), m_seq))
    m_p = _extract_srp_value(m_packet)
    return a_p, m_p


# --- SrpClient Regression (verschoben aus luanti_probe) ---


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


# --- SrpTakeover Positivkontrolle und Gegenprobe ---


def test_takeover_login_succeeds_with_real_password() -> None:
    server = SrpServer(PLAYER, make_verifier(PLAYER, REAL_PW, SALT))
    takeover = SrpTakeover(PLAYER, REAL_PW)
    a_p, m_p = _run_takeover(takeover, server)
    assert server.verify(a_p, m_p), "Positivkontrolle: Server akzeptiert M_p des Proxys"


def test_takeover_login_fails_with_other_password() -> None:
    # Das Konto am Server hat ein anderes Passwort als der Proxy ableitet.
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
        takeover.server_packet(b"\x00\x01")  # kein gueltiger MTP-Kopf


def test_client_parse_error_ends_session() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    with pytest.raises(SrpTakeoverError):
        takeover.client_packet(b"zu kurz")


def test_repr_hides_password() -> None:
    takeover = SrpTakeover(PLAYER, REAL_PW)
    assert REAL_PW not in repr(takeover)
    assert PLACEHOLDER_PASSWORD not in repr(takeover)


# --- Split-Tabelle (RELIABLE(SPLIT) und nacktes SPLIT), mit Positivkontrolle ---

_A = struct.pack(">H", mtp.TOSERVER_SRP_BYTES_A)
_M = struct.pack(">H", mtp.TOSERVER_SRP_BYTES_M)
_FIRST = struct.pack(">H", mtp.TOSERVER_FIRST_SRP)

# Jeder Fall: (Baufunktion, Chunk-0-Bytes, nach_auth, soll_enden)
_SPLIT_CASES = [
    # Vor AUTH_ACCEPT endet jedes SPLIT, egal welcher Inhalt (Tiefenverteidigung).
    pytest.param(_reliable_split, _A, False, True, id="reliable_split_A_before_auth"),
    pytest.param(_reliable_split, _M, False, True, id="reliable_split_M_before_auth"),
    pytest.param(_reliable_split, _FIRST, False, True, id="reliable_split_first_srp_before_auth"),
    pytest.param(_reliable_split, b"\x00\x2f", False, True, id="reliable_split_harmlos_before_auth"),
    pytest.param(_naked_split, _A, False, True, id="naked_split_A_before_auth"),
    pytest.param(_naked_split, _FIRST, False, True, id="naked_split_first_srp_before_auth"),
    # Nach AUTH_ACCEPT: SPLIT mit SRP-Kommando in Chunk 0 bleibt verboten.
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
    """Positivkontrolle: ein harmloser RELIABLE(SPLIT) Chunk 1 nach AUTH_ACCEPT geht unveraendert durch."""
    takeover = SrpTakeover(PLAYER, REAL_PW)
    takeover.server_packet(_reliable(mtp.TOCLIENT_AUTH_ACCEPT, b"", seq=2))
    packet = _reliable_split(b"nutzdaten-chunk-eins", seq=65510, chunk_num=1, chunk_count=2)
    assert takeover.client_packet(packet) is packet


def test_rewrite_payload_rejects_non_reliable_original() -> None:
    # Ein nacktes ORIGINAL ist kein RELIABLE(ORIGINAL) und darf nicht umgeschrieben werden.
    original = _head() + b"\x01" + struct.pack(">H", mtp.TOSERVER_SRP_BYTES_A) + _a_payload(b"A" * 32)
    with pytest.raises(MtpError):
        mtp.rewrite_payload(original, _a_payload(b"B" * 32))


def test_rewrite_payload_keeps_frame_and_replaces_payload() -> None:
    original = _reliable(mtp.TOSERVER_SRP_BYTES_A, _a_payload(b"A" * 32), seq=65501)
    new = mtp.rewrite_payload(original, _a_payload(b"B" * 48))
    assert new[:13] == original[:13], "Kopf, RELIABLE und ORIGINAL bleiben"
    assert _extract_srp_value(new) == b"B" * 48
