"""Binärkopf der Proxy-Nachrichten zwischen Browser (webshims emsocket) und Gameworld-Proxy, rein.

Nach ``BIND OK`` trägt jede WebSocket-Binärnachricht genau ein UDP-Datagramm mit 24 Byte Kopf:
``u32 BE 0x778B4CF6 | 16 Byte IPv6 | u16 BE Port | u16 BE Länge | Nutzdaten``. IPv4 steht als
``::ffff:a.b.c.d`` im Kopf. Richtung Proxy ist die Adresse das Ziel, Richtung Browser die Quelle.
Quelle: paradust7/webshims, Commit 70653a9, ``src/emsocket/proxy.js`` (encapsulate/unencapsulate,
inet6_pton/inet6_ntop). Die Adresse im Kopf ist nur eine Angabe des Clients, das echte Ziel kommt
immer aus der Sitzung (siehe ``commands.target_allowed``).
"""

import ipaddress
import struct

EP_MAGIC = 0x778B4CF6
EP_HEADER = struct.Struct("!I16sHH")  # 24 Byte: Magic, IPv6, Port, Länge
MAX_PAYLOAD = 1500


class FrameError(ValueError):
    """Ein Frame hat nicht das Format von webshims oder ist zu groß."""


def unpack(frame: bytes) -> tuple[str, int, bytes]:
    """Zerlegt ein Frame in (Host, Port, Nutzdaten); IPv4-gemappte Adressen kommen als IPv4 heraus."""
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
    """Baut ein Frame; IPv4-Adressen werden als ``::ffff:a.b.c.d`` eingetragen."""
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
