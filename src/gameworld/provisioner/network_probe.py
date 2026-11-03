"""Find the Docker network Gameworld runs in, without any extra rights.

Why: the setup check offers a ready-to-copy command that creates the Docker proxy. It
only works in the Docker network of the deploy daemon, and AppAPI does not tell an ExApp
which network that is (its OCS ExApp info has no daemon data, the daemon routes are
admin settings routes). Gameworld must not get the Docker socket for this either.

How: in a user-defined Docker network every container uses Docker's embedded DNS at
127.0.0.11. A reverse (PTR) lookup of a container IP there answers
``<container name>.<network name>``. AppAPI names the ExApp container
``nc_app_<appid>``, so Gameworld asks for the PTR record of its own IPv4 addresses and
takes the part behind ``nc_app_gameworld.``.

The lookup is read-only and changes nothing. The answer is external data that ends up
in a shell command shown to an admin, so the parser is strict (query id, sender,
bounded name decoding, ASCII only) and the network name must match ``NETWORK_RE``;
any anomaly gives None and the setup check falls back to the documented commands.
Stdlib only, no caching, no background thread: it only runs when the proxy is missing.
"""

from __future__ import annotations

import ipaddress
import re
import secrets
import socket
import struct

DOCKER_DNS = "127.0.0.11"
DNS_PORT = 53
TIMEOUT_S = 1.0
RESOLV_CONF = "/etc/resolv.conf"
# AppAPI container prefix "nc_app_" plus the app id (lifecycle.APP_ID; not imported to
# keep this module free of the nc_py_api import chain).
CONTAINER_NAME = "nc_app_gameworld"
# Docker network names: alphanumeric start, then [A-Za-z0-9_.-]; at most 128 characters.
NETWORK_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$"

_TYPE_PTR = 12
_CLASS_IN = 1
_HEADER = struct.Struct("!HHHHHH")
_RR_FIXED = struct.Struct("!HHIH")
_MAX_NAME = 255
_MAX_LABEL = 63
_MAX_POINTER_HOPS = 16
_RECV_SIZE = 512
_NAMESERVER_LINE = re.compile(r"^\s*nameserver\s+127\.0\.0\.11\s*$", re.MULTILINE)


class _MalformedError(Exception):
    """Internal: the packet is not a well-formed answer."""


def build_ptr_query(ip: str, qid: int) -> bytes:
    """Standard recursive DNS query for the PTR record of an IPv4 address."""
    try:
        address = ipaddress.IPv4Address(ip)
    except ValueError as exc:
        raise ValueError(f"not an IPv4 address: {ip!r}") from exc
    labels = [*reversed(str(address).split(".")), "in-addr", "arpa"]
    qname = b"".join(bytes([len(label)]) + label.encode("ascii") for label in labels) + b"\x00"
    # Flags 0x0100: standard query, recursion desired.
    return _HEADER.pack(qid & 0xFFFF, 0x0100, 1, 0, 0, 0) + qname + struct.pack("!HH", _TYPE_PTR, _CLASS_IN)


def _read_name(packet: bytes, offset: int) -> tuple[str, int]:
    """Decode a (possibly compressed) name; returns it and the offset behind it.

    Every compression pointer must point before the start of the label run it came
    from, which rules out loops; the hop limit is a second guard.
    """
    labels: list[str] = []
    wire_length = 1
    position = offset
    run_start = offset
    end: int | None = None
    hops = 0
    while True:
        if position >= len(packet):
            raise _MalformedError("name runs past the end")
        length = packet[position]
        kind = length & 0xC0
        if kind == 0xC0:
            if position + 1 >= len(packet):
                raise _MalformedError("cut pointer")
            target = ((length & 0x3F) << 8) | packet[position + 1]
            hops += 1
            if hops > _MAX_POINTER_HOPS or target >= run_start:
                raise _MalformedError("pointer loop or forward pointer")
            if end is None:
                end = position + 2
            position = target
            run_start = target
            continue
        if kind != 0:
            raise _MalformedError("reserved label type or label over 63")
        if length == 0:
            break
        if length > _MAX_LABEL:
            raise _MalformedError("label over 63")
        raw = packet[position + 1 : position + 1 + length]
        if len(raw) != length:
            raise _MalformedError("cut label")
        # Printable ASCII only, and no dot inside a label (it would change the split).
        if any(byte < 0x21 or byte > 0x7E or byte == 0x2E for byte in raw):
            raise _MalformedError("unexpected byte in label")
        wire_length += length + 1
        if wire_length > _MAX_NAME:
            raise _MalformedError("name over 255")
        labels.append(raw.decode("ascii"))
        position += 1 + length
    if end is None:
        end = position + 1
    return ".".join(labels), end


def _parse(packet: bytes, qid: int) -> str | None:
    if len(packet) < _HEADER.size:
        return None
    pid, flags, qdcount, ancount, _nscount, _arcount = _HEADER.unpack_from(packet, 0)
    # ID, QR=1 (answer), RCODE=0 (no error).
    if pid != qid or not flags & 0x8000 or flags & 0x000F:
        return None
    offset = _HEADER.size
    for _ in range(qdcount):
        _name, offset = _read_name(packet, offset)
        offset += 4
        if offset > len(packet):
            return None
    for _ in range(ancount):
        _owner, offset = _read_name(packet, offset)
        if offset + _RR_FIXED.size > len(packet):
            return None
        rtype, rclass, _ttl, rdlength = _RR_FIXED.unpack_from(packet, offset)
        offset += _RR_FIXED.size
        rdata_end = offset + rdlength
        if rdata_end > len(packet):
            return None
        if rtype == _TYPE_PTR and rclass == _CLASS_IN:
            name, name_end = _read_name(packet, offset)
            return name if name_end == rdata_end and name else None
        offset = rdata_end
    return None


def parse_ptr_response(packet: bytes, qid: int) -> str | None:
    """Name from the first PTR answer of ``packet``, or None on any anomaly. Never raises."""
    try:
        return _parse(packet, qid)
    except (_MalformedError, IndexError, struct.error, UnicodeError):
        return None


def _read_resolv_conf() -> str | None:
    try:
        with open(RESOLV_CONF, encoding="utf-8", errors="replace") as handle:
            return handle.read(65536)
    except OSError:
        return None


def _own_ipv4() -> list[str]:
    """Private, non-loopback IPv4 addresses of this host name, sorted and deduplicated."""
    try:
        infos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except OSError:
        return []
    addresses: set[str] = set()
    for info in infos:
        try:
            address = ipaddress.IPv4Address(info[4][0])
        except (ValueError, IndexError, TypeError):
            continue
        if address.is_private and not address.is_loopback:
            addresses.add(str(address))
    return sorted(addresses, key=ipaddress.IPv4Address)


def _open_socket() -> socket.socket:
    return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


def _lookup_ptr(ip: str) -> str | None:
    qid = secrets.randbits(16)
    sock = _open_socket()
    try:
        sock.settimeout(TIMEOUT_S)
        sock.sendto(build_ptr_query(ip, qid), (DOCKER_DNS, DNS_PORT))
        packet, sender = sock.recvfrom(_RECV_SIZE)
    finally:
        sock.close()
    if tuple(sender[:2]) != (DOCKER_DNS, DNS_PORT):
        return None
    return parse_ptr_response(packet, qid)


def _network_from_name(name: str) -> str | None:
    prefix = CONTAINER_NAME + "."
    if not name.startswith(prefix):
        return None
    network = name[len(prefix) :].rstrip(".")
    return network if re.fullmatch(NETWORK_RE, network) else None


def detect_docker_network() -> str | None:
    """Docker network of the running ExApp container, or None when it cannot be told for sure."""
    try:
        resolv = _read_resolv_conf()
        if resolv is None or not _NAMESERVER_LINE.search(resolv):
            return None
        networks: set[str] = set()
        for ip in _own_ipv4():
            name = _lookup_ptr(ip)
            network = _network_from_name(name) if name is not None else None
            if network is not None:
                networks.add(network)
    except (OSError, struct.error, UnicodeError, ValueError):
        # TimeoutError is an OSError.
        return None
    return networks.pop() if len(networks) == 1 else None
