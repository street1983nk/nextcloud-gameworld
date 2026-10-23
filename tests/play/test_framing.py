"""Binärkopf der Proxy-Nachrichten: Golden Vector, Gegenprobe und manipulierte Frames."""

import pytest

from gameworld.play.framing import EP_HEADER, EP_MAGIC, MAX_PAYLOAD, FrameError, pack, unpack

# Von Hand nach webshims proxy.js (encapsulate) ausgeschrieben, nicht mit pack erzeugt:
# Magic | ::ffff:10.77.0.1 | Port 30000 | Länge 3 | "abc"
GOLDEN = bytes.fromhex("778b4cf6" + "00" * 10 + "ffff" + "0a4d0001" + "7530" + "0003" + "616263")


def _frame(magic: str = "778b4cf6", ip: str = "00" * 10 + "ffff0a4d0001", port: int = 30000, length: int = 3) -> bytes:
    return bytes.fromhex(magic + ip) + port.to_bytes(2, "big") + length.to_bytes(2, "big")


def test_header_layout() -> None:
    assert EP_MAGIC == 0x778B4CF6
    assert EP_HEADER.size == 24


def test_golden_vector_pack() -> None:
    frame = pack("10.77.0.1", 30000, b"abc")
    assert len(frame) == 27
    assert frame == GOLDEN


def test_golden_vector_unpack() -> None:
    assert unpack(GOLDEN) == ("10.77.0.1", 30000, b"abc")


@pytest.mark.parametrize(
    ("host", "port", "payload"),
    [
        ("10.77.0.1", 30000, b"abc"),
        ("10.77.0.2", 1, b""),
        ("127.0.0.1", 65535, b"\x00" * MAX_PAYLOAD),
        ("::1", 30000, b"x"),
        ("2001:db8::7", 4242, b"\xff\xfe"),
    ],
)
def test_pack_unpack_are_inverse(host: str, port: int, payload: bytes) -> None:
    assert unpack(pack(host, port, payload)) == (host, port, payload)


def test_ipv4_mapped_is_normalized() -> None:
    """Ein Kopf mit ::ffff:10.77.0.1 kommt als 10.77.0.1 heraus (Grundlage für target_allowed)."""
    assert unpack(_frame() + b"abc")[0] == "10.77.0.1"


@pytest.mark.parametrize(
    "frame",
    [
        # Positivkontrolle steht in test_golden_vector_unpack; hier nur Manipulationen.
        GOLDEN[:23],  # 23 Byte, Kopf unvollständig
        b"",
        _frame(magic="778b4cf7") + b"abc",  # falsche Magic
        _frame(length=3) + b"ab",  # Längenfeld 3, nur 2 Nutzbytes
        _frame(length=3) + b"abcd",  # Längenfeld 3, 4 Nutzbytes
        _frame(length=MAX_PAYLOAD + 1) + b"\x00" * (MAX_PAYLOAD + 1),  # zu groß
    ],
)
def test_unpack_rejects_manipulated_frames(frame: bytes) -> None:
    with pytest.raises(FrameError):
        unpack(frame)


def test_unpack_accepts_max_payload() -> None:
    frame = _frame(length=MAX_PAYLOAD) + b"\x01" * MAX_PAYLOAD
    assert unpack(frame) == ("10.77.0.1", 30000, b"\x01" * MAX_PAYLOAD)


def test_pack_rejects_oversized_payload() -> None:
    with pytest.raises(FrameError):
        pack("10.77.0.1", 30000, b"\x00" * (MAX_PAYLOAD + 1))


@pytest.mark.parametrize(("host", "port"), [("10.77.0.1", 0), ("10.77.0.1", 65536), ("kein-host", 30000)])
def test_pack_rejects_bad_source(host: str, port: int) -> None:
    with pytest.raises(FrameError):
        pack(host, port, b"")


def test_frame_error_is_value_error() -> None:
    assert issubclass(FrameError, ValueError)
