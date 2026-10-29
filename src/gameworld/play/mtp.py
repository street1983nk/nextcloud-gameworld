"""Read MTP packets of the Luanti client and check them before login, pure and only with struct.

A datagram has a 7 byte header ``u32 0x4F457403 | u16 peer_id | u8 channel``, then a packet:
``u8 type`` with 0 CONTROL (``u8 controltype`` plus data), 1 ORIGINAL (``u16 command`` plus data),
2 SPLIT (``u16 seqnum | u16 chunk_count | u16 chunk_num`` plus chunk data; the command is in the
first two bytes of chunk 0) and 3 RELIABLE (``u16 seqnum`` plus exactly one inner packet, never
RELIABLE again). Sources: luanti-org/luanti, tag 5.17.0, ``src/network/mtp/internal.h`` (layout of the
types) and ``src/network/networkprotocol.h`` (commands); proven in ``tests/e2e/luanti_probe.py``
against a real 5.17.0 server. An empty ORIGINAL without a command is allowed: the client sends
it on connect as a dummy so that the server assigns a peer_id (``Connection::Connect``).

``ClientGuard`` decides per datagram from the browser whether it is forwarded or the session
ends. It always decides by ``inner_ptype``, so that a SPLIT inside RELIABLE never slips through as an ordinary
command. Every read error ends the session, nothing is passed through unchecked.
"""

import enum
import struct
from dataclasses import dataclass

PROTO_ID = 0x4F457403
HEADER = struct.Struct(">IHB")

PT_CONTROL = 0
PT_ORIGINAL = 1
PT_SPLIT = 2
PT_RELIABLE = 3

TOSERVER_INIT = 0x02
TOSERVER_FIRST_SRP = 0x50
TOSERVER_SRP_BYTES_A = 0x51
TOSERVER_SRP_BYTES_M = 0x52
TOCLIENT_HELLO = 0x02
TOCLIENT_AUTH_ACCEPT = 0x03
TOCLIENT_ACCESS_DENIED = 0x0A
TOCLIENT_SRP_BYTES_S_B = 0x60
SRP_COMMANDS = frozenset({TOSERVER_FIRST_SRP, TOSERVER_SRP_BYTES_A, TOSERVER_SRP_BYTES_M})

INIT_NAME_OFFSET = 7  # u8 ser_ver, u16 compression, u16 proto_min, u16 proto_max

REASON_OK = "ok"
REASON_UNREADABLE = "unreadable"
REASON_SPLIT_BEFORE_AUTH = "split_before_auth"
REASON_SRP_IN_SPLIT = "srp_in_split"
REASON_FIRST_SRP = "first_srp"
REASON_NAME_MISMATCH = "name_mismatch"
REASON_AUTH_BEFORE_INIT = "auth_before_init"
REASON_ENDED = "ended"


class MtpError(ValueError):
    """A datagram is not a readable MTP packet."""


@dataclass(frozen=True)
class Parsed:
    """A datagram that was read; ``inner_ptype`` is the type of the inner packet for RELIABLE."""

    channel: int
    peer_id: int
    ptype: int
    inner_ptype: int
    reliable_seq: int | None
    command: int | None
    split_chunk: tuple[int, int, int] | None  # (split_seq, chunk_count, chunk_num)
    split_command: int | None
    payload: bytes


def _u16(data: bytes, offset: int) -> int:
    if len(data) < offset + 2:
        raise MtpError("Paket zu kurz")
    return struct.unpack_from(">H", data, offset)[0]


def parse(datagram: bytes) -> Parsed:
    """Reads head and type; RELIABLE exactly one level deep, otherwise MtpError."""
    if len(datagram) < HEADER.size + 1:
        raise MtpError("Paket zu kurz")
    proto, peer_id, channel = HEADER.unpack_from(datagram)
    if proto != PROTO_ID:
        raise MtpError("falsche Protokoll-ID")
    body = datagram[HEADER.size :]
    ptype = body[0]
    reliable_seq: int | None = None
    if ptype == PT_RELIABLE:
        reliable_seq = _u16(body, 1)
        body = body[3:]
        if not body:
            raise MtpError("RELIABLE ohne inneres Paket")
        if body[0] == PT_RELIABLE:
            raise MtpError("RELIABLE im RELIABLE")
    inner_ptype = body[0]
    command: int | None = None
    split_chunk: tuple[int, int, int] | None = None
    split_command: int | None = None
    if inner_ptype == PT_CONTROL:
        if len(body) < 2:
            raise MtpError("CONTROL ohne Untertyp")
        payload = body[1:]
    elif inner_ptype == PT_ORIGINAL:
        if len(body) == 1:
            payload = b""  # connection dummy without a command
        else:
            command = _u16(body, 1)
            payload = body[3:]
    elif inner_ptype == PT_SPLIT:
        if len(body) < 7:
            raise MtpError("SPLIT-Kopf zu kurz")
        split_seq, chunk_count, chunk_num = struct.unpack_from(">HHH", body, 1)
        if chunk_count == 0 or chunk_num >= chunk_count:
            raise MtpError("SPLIT-Nummern ungültig")
        payload = body[7:]
        if chunk_num == 0:
            # A chunk 0 with fewer than two bytes would spread the command over two chunks.
            split_command = _u16(payload, 0)
        split_chunk = (split_seq, chunk_count, chunk_num)
    else:
        raise MtpError("unbekannter Pakettyp")
    return Parsed(
        channel=channel,
        peer_id=peer_id,
        ptype=ptype,
        inner_ptype=inner_ptype,
        reliable_seq=reliable_seq,
        command=command,
        split_chunk=split_chunk,
        split_command=split_command,
        payload=payload,
    )


def rewrite_payload(datagram: bytes, new_payload: bytes) -> bytes:
    """Replaces only the payload of a RELIABLE(ORIGINAL) command packet.

    Head (7 bytes), RELIABLE type with seqnum, ORIGINAL type and command are kept;
    any other structure (bare ORIGINAL, SPLIT, CONTROL, ORIGINAL without a command) raises MtpError.
    """
    parsed = parse(datagram)
    if parsed.ptype != PT_RELIABLE or parsed.inner_ptype != PT_ORIGINAL or parsed.command is None:
        raise MtpError("rewrite nur fuer RELIABLE(ORIGINAL) mit Kommando")
    head = datagram[: HEADER.size]
    reliable = struct.pack(">BH", PT_RELIABLE, parsed.reliable_seq)
    original = struct.pack(">BH", PT_ORIGINAL, parsed.command)
    return head + reliable + original + new_payload


def init_player_name(payload: bytes) -> str:
    """Player name from the payload of TOSERVER_INIT (after the command): str16 from offset 7."""
    length = _u16(payload, INIT_NAME_OFFSET)
    start = INIT_NAME_OFFSET + 2
    raw = payload[start : start + length]
    if len(raw) != length:
        raise MtpError("Name länger als das Paket")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MtpError("Name ist kein UTF-8") from exc


class Verdict(enum.Enum):
    """Forward or end the session."""

    FORWARD = "forward"
    END = "end"


@dataclass(frozen=True)
class GuardResult:
    """Decision with a fixed ASCII reason (logged as a counter, never with packet content)."""

    verdict: Verdict
    reason: str


_FORWARD = GuardResult(Verdict.FORWARD, REASON_OK)


class ClientGuard:
    """Checks datagrams from the browser before they reach the world server.

    Rules: TOSERVER_INIT only with exactly the ticket name; TOSERVER_FIRST_SRP (registration,
    password change) never; SRP_BYTES_A/M only after a checked INIT; any SPLIT (bare or inside
    RELIABLE) only after a real AUTH_ACCEPT and then never with an SRP command in chunk 0. After the first
    END the guard stays ended.
    """

    def __init__(self, expected_name: str) -> None:
        self.expected_name = expected_name
        self.name_ok = False
        self.authed = False
        self.ended = False

    def _end(self, reason: str) -> GuardResult:
        self.ended = True
        return GuardResult(Verdict.END, reason)

    def check(self, datagram: bytes) -> GuardResult:
        """Decides on a datagram from the browser."""
        if self.ended:
            return GuardResult(Verdict.END, REASON_ENDED)
        try:
            parsed = parse(datagram)
        except MtpError:
            return self._end(REASON_UNREADABLE)
        if parsed.inner_ptype == PT_SPLIT:
            if not self.authed:
                return self._end(REASON_SPLIT_BEFORE_AUTH)
            if parsed.split_command in SRP_COMMANDS:
                return self._end(REASON_SRP_IN_SPLIT)
            return _FORWARD
        command = parsed.command
        if command == TOSERVER_FIRST_SRP:
            return self._end(REASON_FIRST_SRP)
        if command == TOSERVER_INIT:
            try:
                name = init_player_name(parsed.payload)
            except MtpError:
                return self._end(REASON_UNREADABLE)
            if name != self.expected_name:
                return self._end(REASON_NAME_MISMATCH)
            self.name_ok = True
            return _FORWARD
        if command in (TOSERVER_SRP_BYTES_A, TOSERVER_SRP_BYTES_M) and not self.name_ok:
            return self._end(REASON_AUTH_BEFORE_INIT)
        return _FORWARD

    def observe_server(self, datagram: bytes) -> None:
        """Remembers a real AUTH_ACCEPT from the server; everything else releases nothing.

        It is released only after a checked INIT, so that an AUTH_ACCEPT never counts for an
        unchecked name. Read errors on server packets are ignored.
        """
        try:
            parsed = parse(datagram)
        except MtpError:
            return
        if parsed.inner_ptype == PT_ORIGINAL and parsed.command == TOCLIENT_AUTH_ACCEPT and self.name_ok:
            self.authed = True
