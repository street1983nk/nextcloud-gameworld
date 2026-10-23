"""MTP-Pakete des Luanti-Clients lesen und vor der Anmeldung prüfen, rein und nur mit struct.

Ein Datagramm hat einen 7-Byte-Kopf ``u32 0x4F457403 | u16 peer_id | u8 channel``, dann ein Paket:
``u8 type`` mit 0 CONTROL (``u8 controltype`` plus Daten), 1 ORIGINAL (``u16 command`` plus Daten),
2 SPLIT (``u16 seqnum | u16 chunk_count | u16 chunk_num`` plus Chunk-Daten; das Kommando steht in den
ersten zwei Byte von Chunk 0) und 3 RELIABLE (``u16 seqnum`` plus genau ein inneres Paket, nie
wieder RELIABLE). Quellen: luanti-org/luanti, Tag 5.17.0, ``src/network/mtp/internal.h`` (Layout der
Typen) und ``src/network/networkprotocol.h`` (Kommandos); bewährt in ``tests/e2e/luanti_probe.py``
gegen einen echten 5.17.0-Server. Ein leeres ORIGINAL ohne Kommando ist erlaubt: Der Client sendet
es beim Verbinden als Dummy, damit der Server eine peer_id vergibt (``Connection::Connect``).

``ClientGuard`` entscheidet je Datagramm vom Browser, ob es weitergeleitet wird oder die Sitzung
endet. Er entscheidet immer nach ``inner_ptype``, damit ein SPLIT im RELIABLE nie als gewöhnliches
Kommando durchrutscht. Jeder Lesefehler beendet die Sitzung, nichts wird ungeprüft durchgereicht.
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
    """Ein Datagramm ist kein lesbares MTP-Paket."""


@dataclass(frozen=True)
class Parsed:
    """Ein gelesenes Datagramm; ``inner_ptype`` ist bei RELIABLE der Typ des inneren Pakets."""

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
    """Liest Kopf und Typ; RELIABLE genau eine Ebene tief, sonst MtpError."""
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
            payload = b""  # Verbindungs-Dummy ohne Kommando
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
            # Ein Chunk 0 mit weniger als zwei Byte würde das Kommando über zwei Chunks verteilen.
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


def init_player_name(payload: bytes) -> str:
    """Spielername aus der Nutzlast von TOSERVER_INIT (nach dem Kommando): str16 ab Offset 7."""
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
    """Weiterleiten oder Sitzung beenden."""

    FORWARD = "forward"
    END = "end"


@dataclass(frozen=True)
class GuardResult:
    """Entscheidung mit festem ASCII-Grund (wird als Zähler geloggt, nie mit Paketinhalt)."""

    verdict: Verdict
    reason: str


_FORWARD = GuardResult(Verdict.FORWARD, REASON_OK)


class ClientGuard:
    """Prüft Datagramme vom Browser, bevor sie den Welt-Server erreichen.

    Regeln: TOSERVER_INIT nur mit exakt dem Ticket-Namen; TOSERVER_FIRST_SRP (Registrierung,
    Passwortänderung) nie; SRP_BYTES_A/M erst nach geprüftem INIT; jedes SPLIT (nackt oder im
    RELIABLE) erst nach echtem AUTH_ACCEPT und dann nie mit SRP-Kommando in Chunk 0. Nach dem ersten
    END bleibt der Wächter beendet.
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
        """Entscheidet über ein Datagramm vom Browser."""
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
        """Merkt sich ein echtes AUTH_ACCEPT vom Server; alles andere schaltet nichts frei.

        Freigeschaltet wird nur nach geprüftem INIT, damit ein AUTH_ACCEPT nie für einen
        ungeprüften Namen gilt. Lesefehler bei Server-Paketen werden ignoriert.
        """
        try:
            parsed = parse(datagram)
        except MtpError:
            return
        if parsed.inner_ptype == PT_ORIGINAL and parsed.command == TOCLIENT_AUTH_ACCEPT and self.name_ok:
            self.authed = True
