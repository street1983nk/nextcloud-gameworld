"""Docker network detection via PTR lookup at Docker's embedded DNS (Owner-GO 02.11.2026, point 2).

The DNS answer is external data that ends up in a shell command shown to an admin, so the
parser is tested against malformed, hostile and random packets: every anomaly must give
None, never an exception.
"""

from __future__ import annotations

import random
import struct
from collections.abc import Callable

import pytest

from gameworld.provisioner import network_probe
from gameworld.provisioner.network_probe import (
    CONTAINER_NAME,
    DNS_PORT,
    DOCKER_DNS,
    build_ptr_query,
    detect_docker_network,
    parse_ptr_response,
)

QID = 0x4A2F
DOCKER_RESOLV = "search example.org\nnameserver 127.0.0.11\noptions ndots:0\n"


def _name(*labels: bytes) -> bytes:
    return b"".join(bytes([len(label)]) + label for label in labels) + b"\x00"


QNAME = _name(b"5", b"0", b"21", b"172", b"in-addr", b"arpa")
HEADER_LEN = 12
QUESTION = QNAME + struct.pack("!HH", 12, 1)
# Offset right behind header and question: the first answer record starts here.
ANSWER_AT = HEADER_LEN + len(QUESTION)
# Owner name (pointer to the question) + TYPE CLASS TTL RDLENGTH.
RR_FIXED = 2 + 10


def _header(qid: int = QID, flags: int = 0x8180, qdcount: int = 1, ancount: int = 1) -> bytes:
    return struct.pack("!HHHHHH", qid, flags, qdcount, ancount, 0, 0)


def _record(rdata: bytes, rtype: int = 12, rclass: int = 1) -> bytes:
    return b"\xc0\x0c" + struct.pack("!HHIH", rtype, rclass, 600, len(rdata)) + rdata


def _response(rdata: bytes, *, qid: int = QID, flags: int = 0x8180, ancount: int = 1) -> bytes:
    answer = _record(rdata) if ancount else b""
    return _header(qid, flags, 1, ancount) + QUESTION + answer


def _valid() -> bytes:
    return _response(_name(b"nc_app_gameworld", b"nextcloud-aio"))


def _compressed() -> bytes:
    """A record (skipped) holds "nextcloud-aio"; the PTR points into it."""
    first_rdata = _name(b"nextcloud-aio")
    first = _record(first_rdata, rtype=16)
    target = ANSWER_AT + RR_FIXED
    second_rdata = b"\x10nc_app_gameworld" + struct.pack("!H", 0xC000 | target)
    return _header(ancount=2) + QUESTION + first + _record(second_rdata)


# --- Query builder --------------------------------------------------------------------------


def test_build_ptr_query_is_a_standard_ptr_query() -> None:
    query = build_ptr_query("172.21.0.5", QID)
    assert query[:HEADER_LEN] == struct.pack("!HHHHHH", QID, 0x0100, 1, 0, 0, 0)
    assert query[HEADER_LEN:] == QUESTION


@pytest.mark.parametrize("ip", ["::1", "not-an-ip", "300.1.1.1", ""])
def test_build_ptr_query_rejects_non_ipv4(ip: str) -> None:
    with pytest.raises(ValueError, match="not an IPv4 address"):
        build_ptr_query(ip, QID)


# --- Parser: positive -----------------------------------------------------------------------


def test_parse_valid_answer() -> None:
    assert parse_ptr_response(_valid(), QID) == "nc_app_gameworld.nextcloud-aio"


def test_parse_answer_with_compression_pointer() -> None:
    assert parse_ptr_response(_compressed(), QID) == "nc_app_gameworld.nextcloud-aio"


# --- Parser: negative -----------------------------------------------------------------------


@pytest.mark.parametrize("packet_factory", [_valid, _compressed], ids=["plain", "compressed"])
def test_every_truncation_gives_none(packet_factory: Callable[[], bytes]) -> None:
    full = packet_factory()
    for length in range(len(full)):
        assert parse_ptr_response(full[:length], QID) is None, length


def test_wrong_query_id() -> None:
    assert parse_ptr_response(_valid(), QID ^ 1) is None


def test_qr_bit_unset() -> None:
    packet = _response(_name(b"nc_app_gameworld", b"gameworld"), flags=0x0180)
    assert parse_ptr_response(packet, QID) is None


@pytest.mark.parametrize("rcode", [1, 2, 3, 5, 15])
def test_rcode_not_zero(rcode: int) -> None:
    packet = _response(_name(b"nc_app_gameworld", b"gameworld"), flags=0x8180 | rcode)
    assert parse_ptr_response(packet, QID) is None


def test_no_answer() -> None:
    assert parse_ptr_response(_response(b"", ancount=0), QID) is None


def test_only_non_ptr_records() -> None:
    packet = _header() + QUESTION + _record(b"\xac\x15\x00\x05", rtype=1)
    assert parse_ptr_response(packet, QID) is None


def test_pointer_to_itself() -> None:
    at = ANSWER_AT + RR_FIXED
    assert parse_ptr_response(_response(struct.pack("!H", 0xC000 | at)), QID) is None


def test_pointer_cycle_over_two_pointers() -> None:
    at = ANSWER_AT + RR_FIXED
    rdata = struct.pack("!H", 0xC000 | (at + 2)) + struct.pack("!H", 0xC000 | at)
    assert parse_ptr_response(_response(rdata), QID) is None


def test_backward_pointer_cycle() -> None:
    """Pointer at the end of the rdata points back to a label that leads to itself again."""
    at = ANSWER_AT + RR_FIXED
    rdata = b"\x01a" + struct.pack("!H", 0xC000 | at)
    assert parse_ptr_response(_response(rdata), QID) is None


def test_pointer_behind_packet_end() -> None:
    assert parse_ptr_response(_response(b"\xff\xff"), QID) is None
    assert parse_ptr_response(_response(b"\x10nc_app_gameworld\xc3\x00"), QID) is None


def test_label_longer_than_63() -> None:
    rdata = bytes([64]) + b"a" * 64 + b"\x00"
    assert parse_ptr_response(_response(rdata), QID) is None
    rdata = bytes([0x80 | 5]) + b"abcde\x00"
    assert parse_ptr_response(_response(rdata), QID) is None


def test_name_longer_than_255() -> None:
    rdata = _name(*([b"a" * 63] * 5))
    assert parse_ptr_response(_response(rdata), QID) is None


@pytest.mark.parametrize("label", [b"caf\xc3\xa9", b"\x00abc", b"a b", b"a.b", b"\x7f", b"\xff"])
def test_non_ascii_or_control_bytes_in_name(label: bytes) -> None:
    rdata = _name(b"nc_app_gameworld", label)
    assert parse_ptr_response(_response(rdata), QID) is None


def test_rdlength_beyond_packet() -> None:
    packet = _valid()
    rdlength_at = ANSWER_AT + RR_FIXED - 2
    broken = packet[:rdlength_at] + struct.pack("!H", 500) + packet[rdlength_at + 2 :]
    assert parse_ptr_response(broken, QID) is None


def test_name_not_filling_rdata() -> None:
    assert parse_ptr_response(_response(_name(b"nc_app_gameworld", b"gameworld") + b"x"), QID) is None


@pytest.mark.parametrize("packet", [b"", b"\x00", b"\xff" * 11, b"\xff" * 12, b"\x00" * 512])
def test_garbage_gives_none(packet: bytes) -> None:
    assert parse_ptr_response(packet, QID) is None


def test_random_packets_never_raise() -> None:
    rng = random.Random(261102)  # noqa: S311 - fixed seed for a reproducible fuzz run, no crypto
    valid = _valid()
    for _ in range(2000):
        packet = rng.randbytes(rng.randint(0, 600))
        result = parse_ptr_response(packet, rng.randint(0, 0xFFFF))
        assert result is None or isinstance(result, str)
        mutated = bytearray(valid)
        for _ in range(rng.randint(1, 6)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        result = parse_ptr_response(bytes(mutated), QID)
        assert result is None or isinstance(result, str)


# --- detect_docker_network ------------------------------------------------------------------


class FakeSocket:
    """UDP socket double: answers every query with the PTR name for the queried IP."""

    def __init__(
        self,
        answers: dict[str, str],
        sent: list[tuple[bytes, tuple[str, int]]],
        sender: tuple[str, int] = (DOCKER_DNS, DNS_PORT),
        error: type[BaseException] | None = None,
    ) -> None:
        self.answers = answers
        self.sent = sent
        self.sender = sender
        self.error = error
        self.timeout: float | None = None
        self.closed = False
        self._last: tuple[int, str] | None = None

    def settimeout(self, value: float) -> None:
        self.timeout = value

    def sendto(self, data: bytes, address: tuple[str, int]) -> int:
        self.sent.append((data, address))
        qid = struct.unpack("!H", data[:2])[0]
        labels: list[str] = []
        at = HEADER_LEN
        while data[at]:
            labels.append(data[at + 1 : at + 1 + data[at]].decode())
            at += 1 + data[at]
        ip = ".".join(reversed(labels[:4]))
        self._last = (qid, ip)
        return len(data)

    def recvfrom(self, size: int) -> tuple[bytes, tuple[str, int]]:
        assert size >= 512
        if self.error is not None:
            raise self.error("simulated")
        assert self._last is not None
        qid, ip = self._last
        name = self.answers[ip]
        rdata = _name(*(label.encode() for label in name.split(".")))
        question = build_ptr_query(ip, qid)[HEADER_LEN:]
        packet = _header(qid) + question + _record(rdata)
        return packet, self.sender

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[str | None, list[tuple[bytes, tuple[str, int]]]]]:
    def run(
        answers: dict[str, str],
        *,
        resolv: str | None = DOCKER_RESOLV,
        sender: tuple[str, int] = (DOCKER_DNS, DNS_PORT),
        error: type[BaseException] | None = None,
    ) -> tuple[str | None, list[tuple[bytes, tuple[str, int]]]]:
        sent: list[tuple[bytes, tuple[str, int]]] = []
        sockets: list[FakeSocket] = []

        def open_socket() -> FakeSocket:
            sock = FakeSocket(answers, sent, sender, error)
            sockets.append(sock)
            return sock

        monkeypatch.setattr(network_probe, "_read_resolv_conf", lambda: resolv)
        monkeypatch.setattr(network_probe, "_own_ipv4", lambda: list(answers))
        monkeypatch.setattr(network_probe, "_open_socket", open_socket)
        result = detect_docker_network()
        assert all(sock.closed for sock in sockets)
        assert all(sock.timeout == network_probe.TIMEOUT_S for sock in sockets)
        return result, sent

    return run


def test_container_name_follows_appapi_prefix() -> None:
    assert CONTAINER_NAME == "nc_app_gameworld"


@pytest.mark.parametrize("network", ["nextcloud-aio", "gameworld", "gameworld-dev_default", "my.net"])
def test_detects_network(probe: Callable[..., tuple[str | None, list[object]]], network: str) -> None:
    result, sent = probe({"172.21.0.5": f"nc_app_gameworld.{network}"})
    assert result == network
    assert len(sent) == 1
    _data, address = sent[0]  # type: ignore[misc]
    assert address == (DOCKER_DNS, DNS_PORT)


@pytest.mark.parametrize(
    "resolv",
    [None, "", "nameserver 8.8.8.8\n", "# nameserver 127.0.0.11\n", "nameserver 127.0.0.110\n"],
)
def test_no_docker_dns_sends_nothing(probe: Callable[..., tuple[str | None, list[object]]], resolv: str | None) -> None:
    result, sent = probe({"172.21.0.5": "nc_app_gameworld.gameworld"}, resolv=resolv)
    assert result is None
    assert sent == []


@pytest.mark.parametrize(
    "name",
    [
        "other_container.gameworld",
        "nc_app_gameworldx.gameworld",
        "x.nc_app_gameworld.gameworld",
        "nc_app_gameworld",
        "nc_app_gameworld.x;rm -rf /",
        "nc_app_gameworld.$(id)",
        "nc_app_gameworld.-evil",
        "nc_app_gameworld.`id`",
        "nc_app_gameworld.a|b",
        "nc_app_gameworld." + ".".join(["a" * 60] * 3),
        "NC_APP_GAMEWORLD.gameworld",
    ],
)
def test_rejected_names(probe: Callable[..., tuple[str | None, list[object]]], name: str) -> None:
    result, _ = probe({"172.21.0.5": name})
    assert result is None


def test_two_ips_two_networks_is_ambiguous(probe: Callable[..., tuple[str | None, list[object]]]) -> None:
    result, sent = probe({"172.21.0.5": "nc_app_gameworld.gameworld", "172.22.0.7": "nc_app_gameworld.nextcloud-aio"})
    assert result is None
    assert len(sent) == 2


def test_two_ips_same_network(probe: Callable[..., tuple[str | None, list[object]]]) -> None:
    result, _ = probe({"172.21.0.5": "nc_app_gameworld.gameworld", "172.21.0.6": "nc_app_gameworld.gameworld"})
    assert result == "gameworld"


@pytest.mark.parametrize("sender", [("10.0.0.1", 53), (DOCKER_DNS, 5353), ("127.0.0.1", 53)])
def test_answer_from_wrong_sender(
    probe: Callable[..., tuple[str | None, list[object]]], sender: tuple[str, int]
) -> None:
    result, _ = probe({"172.21.0.5": "nc_app_gameworld.gameworld"}, sender=sender)
    assert result is None


@pytest.mark.parametrize("error", [TimeoutError, OSError, ConnectionRefusedError])
def test_socket_errors_give_none(
    probe: Callable[..., tuple[str | None, list[object]]], error: type[BaseException]
) -> None:
    result, _ = probe({"172.21.0.5": "nc_app_gameworld.gameworld"}, error=error)
    assert result is None


def test_no_own_ip(probe: Callable[..., tuple[str | None, list[object]]]) -> None:
    result, sent = probe({})
    assert result is None
    assert sent == []


def test_open_socket_failure_gives_none(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> object:
        raise OSError("no sockets")

    monkeypatch.setattr(network_probe, "_read_resolv_conf", lambda: DOCKER_RESOLV)
    monkeypatch.setattr(network_probe, "_own_ipv4", lambda: ["172.21.0.5"])
    monkeypatch.setattr(network_probe, "_open_socket", broken)
    assert detect_docker_network() is None


def test_own_ipv4_keeps_private_addresses_only(monkeypatch: pytest.MonkeyPatch) -> None:
    infos = [
        (2, 2, 17, "", ("172.21.0.5", 0)),
        (2, 1, 6, "", ("172.21.0.5", 0)),
        (2, 2, 17, "", ("127.0.1.1", 0)),
        (2, 2, 17, "", ("8.8.8.8", 0)),
        (2, 2, 17, "", ("10.0.3.4", 0)),
    ]
    monkeypatch.setattr(network_probe.socket, "gethostname", lambda: "1ac2f7726a31")
    monkeypatch.setattr(network_probe.socket, "getaddrinfo", lambda *args, **kwargs: infos)
    assert network_probe._own_ipv4() == ["10.0.3.4", "172.21.0.5"]


def test_own_ipv4_survives_lookup_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise OSError("no name")

    monkeypatch.setattr(network_probe.socket, "getaddrinfo", fail)
    assert network_probe._own_ipv4() == []


def test_read_resolv_conf_missing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    monkeypatch.setattr(network_probe, "RESOLV_CONF", str(tmp_path) + "/missing/resolv.conf")
    assert network_probe._read_resolv_conf() is None


def test_module_is_stdlib_only() -> None:
    source = network_probe.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        imports = [line.split()[1] for line in handle if line.startswith(("import ", "from "))]
    allowed = {"__future__", "ipaddress", "re", "secrets", "socket", "struct", "collections.abc", "typing"}
    assert set(imports) <= allowed, imports
