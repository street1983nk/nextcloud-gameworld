"""MTP-Parser und ClientGuard: Spielername gegen Ticket, FIRST_SRP, SPLIT vor der Anmeldung.

Die Testpakete werden hier von Hand nach dem Layout aus tests/e2e/luanti_probe.py gebaut (gegen einen
echten 5.17.0-Server bewährt), nie mit mtp.py selbst: Gegenprobe nie mit dem Muster der Umsetzung.
"""

import struct
from collections.abc import Callable

import pytest

from gameworld.play.mtp import (
    PROTO_ID,
    PT_CONTROL,
    PT_ORIGINAL,
    PT_RELIABLE,
    PT_SPLIT,
    TOCLIENT_AUTH_ACCEPT,
    TOCLIENT_HELLO,
    TOSERVER_FIRST_SRP,
    TOSERVER_INIT,
    TOSERVER_SRP_BYTES_A,
    TOSERVER_SRP_BYTES_M,
    ClientGuard,
    MtpError,
    Verdict,
    init_player_name,
    parse,
)

PROTO = 0x4F457403
TOSERVER_REQUEST_MEDIA = 0x40
TOSERVER_PLAYERPOS = 0x23


def head(channel: int = 1, peer: int = 2) -> bytes:
    return struct.pack(">IHB", PROTO, peer, channel)


def original_body(command: int, payload: bytes = b"") -> bytes:
    return b"\x01" + struct.pack(">H", command) + payload


def original(command: int, payload: bytes = b"", channel: int = 1) -> bytes:
    return head(channel) + original_body(command, payload)


def reliable(channel: int, seq: int, command: int, payload: bytes = b"") -> bytes:
    return head(channel) + b"\x03" + struct.pack(">H", seq) + original_body(command, payload)


def split_body(split_seq: int, count: int, num: int, data: bytes) -> bytes:
    return b"\x02" + struct.pack(">HHH", split_seq, count, num) + data


def split(split_seq: int, count: int, num: int, data: bytes, channel: int = 1) -> bytes:
    return head(channel) + split_body(split_seq, count, num, data)


def reliable_split(channel: int, seq: int, split_seq: int, count: int, num: int, data: bytes) -> bytes:
    return head(channel) + b"\x03" + struct.pack(">H", seq) + split_body(split_seq, count, num, data)


def control_ack(channel: int, seq: int) -> bytes:
    return head(channel) + struct.pack(">BBH", 0, 0, seq)


def control_ping(channel: int = 0) -> bytes:
    return head(channel) + struct.pack(">BB", 0, 2)


def control_disco(channel: int = 0) -> bytes:
    return head(channel) + struct.pack(">BB", 0, 3)


def init_payload(name: bytes) -> bytes:
    """INIT-Nutzlast wie luanti_probe.join: ser_ver, compression, proto min/max, Name als str16."""
    return struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + struct.pack(">H", len(name)) + name


def init(name: str) -> bytes:
    return original(0x02, init_payload(name.encode("utf-8")))


def srp_a() -> bytes:
    return reliable(1, 65501, 0x51, struct.pack(">H", 4) + b"\x01\x02\x03\x04" + b"\x01")


def srp_m() -> bytes:
    return reliable(1, 65502, 0x52, struct.pack(">H", 4) + b"\x05\x06\x07\x08")


def server_auth_accept() -> bytes:
    """Echtes AUTH_ACCEPT vom Server: RELIABLE auf Kanal 0 mit ORIGINAL 0x03 und Nutzdaten."""
    return head(0, peer=1) + b"\x03" + struct.pack(">H", 65500) + original_body(0x03, b"\x00" * 21)


def server_hello() -> bytes:
    return head(0, peer=1) + b"\x03" + struct.pack(">H", 65500) + original_body(0x02, b"\x1d\x00\x00\x00\x35")


def authed_guard() -> ClientGuard:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    guard.observe_server(server_auth_accept())
    return guard


# ---------------------------------------------------------------- Konstanten und parse


def test_constants_match_luanti_probe() -> None:
    assert PROTO_ID == PROTO
    assert (PT_CONTROL, PT_ORIGINAL, PT_SPLIT, PT_RELIABLE) == (0, 1, 2, 3)
    assert (TOSERVER_INIT, TOSERVER_FIRST_SRP, TOSERVER_SRP_BYTES_A, TOSERVER_SRP_BYTES_M) == (0x02, 0x50, 0x51, 0x52)
    assert (TOCLIENT_HELLO, TOCLIENT_AUTH_ACCEPT) == (0x02, 0x03)


def test_parse_original() -> None:
    parsed = parse(original(0x02, b"xyz", channel=1))
    assert (parsed.channel, parsed.peer_id, parsed.ptype, parsed.inner_ptype) == (1, 2, PT_ORIGINAL, PT_ORIGINAL)
    assert parsed.reliable_seq is None
    assert parsed.command == 0x02
    assert parsed.split_chunk is None
    assert parsed.payload == b"xyz"


def test_parse_reliable_original() -> None:
    parsed = parse(reliable(1, 65501, 0x51, b"ab"))
    assert (parsed.ptype, parsed.inner_ptype, parsed.reliable_seq, parsed.command) == (
        PT_RELIABLE,
        PT_ORIGINAL,
        65501,
        0x51,
    )
    assert parsed.payload == b"ab"


def test_parse_reliable_split_chunk_0() -> None:
    parsed = parse(reliable_split(1, 7, 9, 3, 0, struct.pack(">H", 0x40) + b"rest"))
    assert (parsed.ptype, parsed.inner_ptype, parsed.reliable_seq) == (PT_RELIABLE, PT_SPLIT, 7)
    assert parsed.command is None
    assert parsed.split_chunk == (9, 3, 0)
    assert parsed.split_command == 0x40


def test_parse_reliable_split_chunk_1_has_no_command() -> None:
    parsed = parse(reliable_split(1, 8, 9, 3, 1, struct.pack(">H", 0x50) + b"x"))
    assert parsed.inner_ptype == PT_SPLIT
    assert parsed.command is None
    assert parsed.split_chunk == (9, 3, 1)
    assert parsed.split_command is None


def test_parse_bare_split() -> None:
    parsed = parse(split(4, 2, 1, b"tail"))
    assert (parsed.ptype, parsed.inner_ptype, parsed.reliable_seq) == (PT_SPLIT, PT_SPLIT, None)
    assert parsed.split_chunk == (4, 2, 1)
    assert parsed.payload == b"tail"


@pytest.mark.parametrize("datagram", [control_ack(0, 65500), control_ping(), control_disco()])
def test_parse_control_has_no_command(datagram: bytes) -> None:
    parsed = parse(datagram)
    assert parsed.ptype == PT_CONTROL
    assert parsed.inner_ptype == PT_CONTROL
    assert parsed.command is None


def test_parse_empty_reliable_original_is_connect_dummy() -> None:
    """Der echte Client sendet beim Verbinden ein leeres RELIABLE(ORIGINAL) ohne Kommando."""
    parsed = parse(head(0, peer=0) + b"\x03" + struct.pack(">H", 65500) + b"\x01")
    assert parsed.inner_ptype == PT_ORIGINAL
    assert parsed.command is None
    assert parsed.payload == b""


@pytest.mark.parametrize(
    "datagram",
    [
        b"",
        b"\x4f\x45\x74\x03\x00",  # 5 Byte
        head(),  # Kopf ohne Typ
        struct.pack(">IHB", 0x4F457404, 2, 1) + original_body(0x02),  # falsche PROTO-ID
        head() + b"\x04",  # unbekannter Typ
        head() + b"\x01\x02",  # ORIGINAL mit halbem Kommando
        head() + b"\x03\x00",  # RELIABLE ohne vollständige Sequenznummer
        head() + b"\x03\x00\x01",  # RELIABLE ohne inneres Paket
        head() + b"\x03\x00\x01\x03\x00\x02" + original_body(0x02),  # RELIABLE im RELIABLE
        head() + b"\x02\x00\x01\x00\x02",  # SPLIT mit halbem Kopf
        split(1, 0, 0, b"ab"),  # chunk_count 0
        split(1, 2, 2, b"ab"),  # chunk_num == chunk_count
        reliable_split(1, 1, 1, 2, 5, b"ab"),  # chunk_num > chunk_count
        split(1, 2, 0, b"\x50"),  # Chunk 0 mit nur einem Kommandobyte
        reliable_split(1, 1, 1, 2, 0, b""),  # Chunk 0 ohne Kommando
        head() + b"\x00",  # CONTROL ohne Untertyp
    ],
)
def test_parse_rejects_unreadable(datagram: bytes) -> None:
    with pytest.raises(MtpError):
        parse(datagram)


# ---------------------------------------------------------------- init_player_name


def test_init_player_name() -> None:
    assert init_player_name(init_payload(b"Mia")) == "Mia"


@pytest.mark.parametrize(
    "payload",
    [
        init_payload(b"Mia")[:-1],  # Längenfeld über Restlänge
        struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + struct.pack(">H", 200) + b"Mia",
        struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53),  # kein Längenfeld
        b"",
        init_payload(b"\xff\xfe"),  # kein UTF-8
    ],
)
def test_init_player_name_rejects_bad_payload(payload: bytes) -> None:
    with pytest.raises(MtpError):
        init_player_name(payload)


# ---------------------------------------------------------------- ClientGuard: Spielername


@pytest.mark.parametrize(
    ("datagram", "verdict", "reason"),
    [
        # Positivkontrollen: eigener Name, unzuverlässig und zuverlässig gesendet.
        (init("Mia"), Verdict.FORWARD, "ok"),
        (reliable(1, 65500, 0x02, init_payload(b"Mia")), Verdict.FORWARD, "ok"),
        # Manipulierte Eingaben: Geschwistername und andere Schreibweisen.
        (init("Leo"), Verdict.END, "name_mismatch"),
        (init("mia"), Verdict.END, "name_mismatch"),
        (init("MIA"), Verdict.END, "name_mismatch"),
        (init("Mia "), Verdict.END, "name_mismatch"),
        (init(""), Verdict.END, "name_mismatch"),
        (reliable(1, 65500, 0x02, init_payload(b"Leo")), Verdict.END, "name_mismatch"),
        (original(0x02, init_payload(b"Mia")[:-1]), Verdict.END, "unreadable"),
    ],
)
def test_guard_init_name(datagram: bytes, verdict: Verdict, reason: str) -> None:
    result = ClientGuard("Mia").check(datagram)
    assert result.verdict is verdict
    assert result.reason == reason


def test_second_init_with_same_name_is_resend() -> None:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD


def test_second_init_with_other_name_ends() -> None:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    result = guard.check(init("Leo"))
    assert result.verdict is Verdict.END
    assert result.reason == "name_mismatch"


def test_guard_stays_ended() -> None:
    """Nach einem END wird nichts mehr weitergeleitet, auch kein gültiges Paket."""
    guard = ClientGuard("Mia")
    assert guard.check(init("Leo")).verdict is Verdict.END
    assert guard.check(init("Mia")).verdict is Verdict.END
    assert guard.check(control_ping()).verdict is Verdict.END


# ---------------------------------------------------------------- ClientGuard: SRP-Kommandos


def _fresh() -> ClientGuard:
    return ClientGuard("Mia")


def _after_init() -> ClientGuard:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    return guard


@pytest.mark.parametrize("make_guard", [_fresh, _after_init, authed_guard])
@pytest.mark.parametrize("datagram", [reliable(1, 65503, 0x50, b"\x00" * 10), original(0x50, b"\x00" * 10)])
def test_first_srp_always_ends(make_guard: Callable[[], ClientGuard], datagram: bytes) -> None:
    result = make_guard().check(datagram)
    assert (result.verdict, result.reason) == (Verdict.END, "first_srp")


def test_connect_dummy_before_init_is_forwarded() -> None:
    """Positivkontrolle: das leere RELIABLE(ORIGINAL) beim Verbinden muss vor dem INIT durch."""
    datagram = head(0, peer=0) + b"\x03" + struct.pack(">H", 65500) + b"\x01"
    result = ClientGuard("Mia").check(datagram)
    assert (result.verdict, result.reason) == (Verdict.FORWARD, "ok")


@pytest.mark.parametrize(
    ("with_init", "datagram", "verdict", "reason"),
    [
        # Positivkontrollen: SRP nach geprüftem Namen.
        (True, srp_a(), Verdict.FORWARD, "ok"),
        (True, srp_m(), Verdict.FORWARD, "ok"),
        # Anmeldung ohne geprüften Namen.
        (False, srp_a(), Verdict.END, "auth_before_init"),
        (False, srp_m(), Verdict.END, "auth_before_init"),
    ],
)
def test_srp_needs_checked_name(with_init: bool, datagram: bytes, verdict: Verdict, reason: str) -> None:
    guard = ClientGuard("Mia")
    if with_init:
        assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    result = guard.check(datagram)
    assert (result.verdict, result.reason) == (verdict, reason)


# ---------------------------------------------------------------- ClientGuard: SPLIT


def test_bare_split_before_auth_ends() -> None:
    result = ClientGuard("Mia").check(split(1, 2, 0, struct.pack(">H", 0x02) + init_payload(b"Mia")))
    assert (result.verdict, result.reason) == (Verdict.END, "split_before_auth")


@pytest.mark.parametrize(
    ("with_init", "datagram", "verdict", "reason"),
    [
        # Positivkontrolle in derselben Tabelle: RELIABLE(ORIGINAL INIT "Mia").
        (False, reliable(1, 65500, 0x02, init_payload(b"Mia")), Verdict.FORWARD, "ok"),
        # RELIABLE(SPLIT) vor AUTH_ACCEPT, vor dem INIT.
        (
            False,
            reliable_split(1, 1, 1, 2, 0, struct.pack(">H", 0x02) + init_payload(b"Leo")),
            Verdict.END,
            "split_before_auth",
        ),
        (False, reliable_split(1, 1, 1, 2, 0, struct.pack(">H", 0x50) + b"\x00" * 8), Verdict.END, "split_before_auth"),
        (False, reliable_split(1, 1, 1, 2, 1, b"\x00" * 8), Verdict.END, "split_before_auth"),
        # RELIABLE(SPLIT) vor AUTH_ACCEPT, nach gültigem INIT.
        (
            True,
            reliable_split(1, 1, 1, 2, 0, struct.pack(">H", 0x02) + init_payload(b"Leo")),
            Verdict.END,
            "split_before_auth",
        ),
        (True, reliable_split(1, 1, 1, 2, 0, struct.pack(">H", 0x50) + b"\x00" * 8), Verdict.END, "split_before_auth"),
        (True, reliable_split(1, 1, 1, 2, 1, b"\x00" * 8), Verdict.END, "split_before_auth"),
        (True, reliable_split(1, 1, 1, 2, 0, struct.pack(">H", 0x40) + b"\x00" * 8), Verdict.END, "split_before_auth"),
    ],
)
def test_reliable_split_before_auth(with_init: bool, datagram: bytes, verdict: Verdict, reason: str) -> None:
    guard = ClientGuard("Mia")
    if with_init:
        assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    result = guard.check(datagram)
    assert (result.verdict, result.reason) == (verdict, reason)


@pytest.mark.parametrize(
    ("datagram", "verdict", "reason"),
    [
        # Positivkontrollen nach AUTH_ACCEPT: große Pakete des Spiels gehen durch.
        (reliable_split(1, 2, 3, 2, 1, b"\x00" * 8), Verdict.FORWARD, "ok"),
        (reliable_split(1, 2, 3, 2, 0, struct.pack(">H", TOSERVER_REQUEST_MEDIA) + b"\x00" * 8), Verdict.FORWARD, "ok"),
        (split(3, 2, 1, b"\x00" * 8), Verdict.FORWARD, "ok"),
        (split(3, 2, 0, struct.pack(">H", TOSERVER_REQUEST_MEDIA) + b"\x00"), Verdict.FORWARD, "ok"),
        # Passwortänderung oder Anmeldung versteckt im Split.
        (reliable_split(1, 2, 3, 2, 0, struct.pack(">H", 0x50) + b"\x00" * 8), Verdict.END, "srp_in_split"),
        (reliable_split(1, 2, 3, 2, 0, struct.pack(">H", 0x51) + b"\x00" * 8), Verdict.END, "srp_in_split"),
        (reliable_split(1, 2, 3, 2, 0, struct.pack(">H", 0x52) + b"\x00" * 8), Verdict.END, "srp_in_split"),
        (split(3, 2, 0, struct.pack(">H", 0x50) + b"\x00"), Verdict.END, "srp_in_split"),
        (reliable_split(1, 2, 3, 2, 0, b"\x50"), Verdict.END, "unreadable"),
    ],
)
def test_reliable_split_after_auth(datagram: bytes, verdict: Verdict, reason: str) -> None:
    result = authed_guard().check(datagram)
    assert (result.verdict, result.reason) == (verdict, reason)


@pytest.mark.parametrize(
    "server_packet",
    [
        server_hello(),
        server_auth_accept()[:-25],  # zerstört, Kommando fehlt
        b"\x00\x01",
        struct.pack(">IHB", 0x4F457404, 1, 0) + b"\x03" + struct.pack(">H", 1) + original_body(0x03),  # falsche PROTO
        head(0, peer=1) + split_body(1, 2, 0, struct.pack(">H", 0x03) + b"\x00"),  # 0x03 nur im Split-Teil
        head(0, peer=1) + b"\x03" + struct.pack(">H", 1) + original_body(0x0A, b"\x00"),  # ACCESS_DENIED
    ],
)
def test_non_auth_accept_does_not_unlock(server_packet: bytes) -> None:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    guard.observe_server(server_packet)
    result = guard.check(reliable_split(1, 2, 3, 2, 1, b"\x00" * 8))
    assert (result.verdict, result.reason) == (Verdict.END, "split_before_auth")


def test_auth_accept_unlocks_split() -> None:
    """Positivkontrolle zu test_non_auth_accept_does_not_unlock: echtes AUTH_ACCEPT schaltet frei."""
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    guard.observe_server(server_auth_accept())
    assert guard.check(reliable_split(1, 2, 3, 2, 1, b"\x00" * 8)).verdict is Verdict.FORWARD


def test_auth_accept_without_checked_name_does_not_unlock() -> None:
    guard = ClientGuard("Mia")
    guard.observe_server(server_auth_accept())
    result = guard.check(reliable_split(1, 2, 3, 2, 1, b"\x00" * 8))
    assert (result.verdict, result.reason) == (Verdict.END, "split_before_auth")


def test_split_never_reaches_command_branches() -> None:
    """Ein RELIABLE(SPLIT), dessen Chunk-Daten wie INIT mit fremdem Namen aussehen, wird nach Split-Regel
    entschieden: nach AUTH_ACCEPT FORWARD (kein name_mismatch), weil der Kommando-Zweig nie erreicht wird."""
    guard = authed_guard()
    datagram = reliable_split(1, 2, 3, 2, 0, struct.pack(">H", 0x02) + init_payload(b"Leo"))
    assert parse(datagram).inner_ptype == PT_SPLIT
    assert parse(datagram).command is None
    result = guard.check(datagram)
    assert (result.verdict, result.reason) == (Verdict.FORWARD, "ok")


# ---------------------------------------------------------------- ClientGuard: Rest


@pytest.mark.parametrize(
    "datagram",
    [
        b"\x4f\x45\x74\x03\x00",  # 5 Byte
        struct.pack(">IHB", 0x4F457404, 2, 1) + original_body(0x02, init_payload(b"Mia")),
        b"",
        head() + b"\x07",
    ],
)
def test_unreadable_ends(datagram: bytes) -> None:
    result = ClientGuard("Mia").check(datagram)
    assert (result.verdict, result.reason) == (Verdict.END, "unreadable")


@pytest.mark.parametrize(
    "datagram",
    [
        control_ack(1, 65500),
        control_ping(),
        control_disco(),
        reliable(0, 65501, TOSERVER_PLAYERPOS, b"\x00" * 12),
        original(TOSERVER_PLAYERPOS, b"\x00" * 12),
        head(0, peer=0) + b"\x03" + struct.pack(">H", 65500) + b"\x01",  # Verbindungs-Dummy
    ],
)
def test_other_packets_after_init_are_forwarded(datagram: bytes) -> None:
    guard = ClientGuard("Mia")
    assert guard.check(init("Mia")).verdict is Verdict.FORWARD
    result = guard.check(datagram)
    assert (result.verdict, result.reason) == (Verdict.FORWARD, "ok")


def test_reasons_are_ascii() -> None:
    guard = ClientGuard("Mia")
    result = guard.check(init("Leo"))
    assert result.reason.isascii()
    assert "Leo" not in result.reason
