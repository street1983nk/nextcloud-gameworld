"""Binary header of the proxy messages between browser (webshims emsocket) and Gameworld proxy, pure.

After ``BIND OK`` every WebSocket binary message carries exactly one UDP datagram with a 24 byte header:
``u32 BE 0x778B4CF6 | 16 byte IPv6 | u16 BE port | u16 BE length | payload``. IPv4 is stored as
``::ffff:a.b.c.d`` in the header. Towards the proxy the address is the destination, towards the browser the source.
Source: paradust7/webshims, commit 70653a9, ``src/emsocket/proxy.js`` (encapsulate/unencapsulate,
inet6_pton/inet6_ntop). The address in the header is only a claim by the client, the real destination always
comes from the session (see ``commands.target_allowed``).
"""

import ipaddress
import struct

EP_MAGIC = 0x778B4CF6
EP_HEADER = struct.Struct("!I16sHH")  # 24 bytes: magic, IPv6, port, length
MAX_PAYLOAD = 1500


class FrameError(ValueError):
    """A frame does not have the webshims format or is too large."""


def unpack(frame: bytes) -> tuple[str, int, bytes]:
    """Splits a frame into (host, port, payload); IPv4-mapped addresses come out as IPv4."""
    if len(frame) < EP_HEADER.size:
        raise FrameError("Frame zu kurz")
    magic, raw_ip, port, length = EP_HEADER.unpack_from(frame)
    if magic != EP_MAGIC:
        raise FrameError("falsche Magic")
    if length > MAX_PAYLOAD:
        raise FrameError("Nutzlast zu groß")
    if len(frame) != EP_HEADER.size + length:
        raise FrameError("Längenfeld passt nicht")
    ip = ipaddress.IPv6Address(raw_ip)
    host = str(ip.ipv4_mapped or ip)
    return host, port, frame[EP_HEADER.size :]


def pack(src_ip: str, src_port: int, payload: bytes) -> bytes:
    """Builds a frame; IPv4 addresses are entered as ``::ffff:a.b.c.d``."""
    if len(payload) > MAX_PAYLOAD:
        raise FrameError("Nutzlast zu groß")
    if not 1 <= src_port <= 65535:
        raise FrameError("Port ungültig")
    try:
        ip = ipaddress.ip_address(src_ip)
    except ValueError as exc:
        raise FrameError("Adresse ungültig") from exc
    raw = (ipaddress.IPv6Address(f"::ffff:{ip}") if ip.version == 4 else ip).packed
    return EP_HEADER.pack(EP_MAGIC, raw, src_port, len(payload)) + payload
