"""SRP-Uebernahme durch den Proxy (Variante A, 04.2-09, D-10 bevorzugt).

Der Proxy ist selbst SRP-Client gegenueber der Welt: In ``TOSERVER_SRP_BYTES_A`` ersetzt er
das A des Browsers durch sein eigenes A_p, reicht ``TOCLIENT_SRP_BYTES_S_B`` unveraendert
durch und rechnet dabei mit dem echten Passwort des Ticket-Kontos den Beweis M_p, den er in
``TOSERVER_SRP_BYTES_M`` einsetzt. Der Browser kennt nur ein wertloses Platzhalter-Passwort;
das echte Spielpasswort verlaesst den Server nie.

Die SRP-Rechnung (``SrpClient``, N und G) ist eine Wahrheit: ``N`` und ``G`` kommen aus
``gameworld.provisioner.luanti_auth``, ``SrpClient`` wurde aus ``tests/e2e/luanti_probe.py``
hierher verschoben (dort nur noch importiert).

Pflichtregeln (sonst Kontouebernahme, RESEARCH Pattern 4 und Threat-Register):

- Der Namensvergleich steht im ``ClientGuard`` vor jedem Ersatz (relay.py), das Passwort
  stammt nur aus ``check_play_access(ticket.uid)``.
- ``TOSERVER_SRP_BYTES_M`` vor gesehenem ``S_B`` und ein zweites ``TOSERVER_SRP_BYTES_A``
  mit anderer Sequenznummer nach ``S_B`` beenden die Sitzung.
- Jedes SPLIT vor ``AUTH_ACCEPT`` und jedes SPLIT mit SRP-Kommando in Chunk 0 beenden die
  Sitzung (Tiefenverteidigung, Entscheid nach ``inner_ptype`` und ``split_command``).
- Ein Parse-Fehler beendet die Sitzung, nie wird ein Paket ungeprueft durchgereicht.
- Resend derselben Sequenznummer liefert byte-gleich denselben Ersatz (Cache je seq).
"""

from __future__ import annotations

import hashlib
import secrets
import struct

from gameworld.play import mtp
from gameworld.provisioner.luanti_auth import G, N

# Wertloses Platzhalter-Passwort fuer den Browser; der Server kennt es nicht.
PLACEHOLDER_PASSWORD = "gameworld"  # noqa: S105

N_LEN = (N.bit_length() + 7) // 8


def _bin(n: int) -> bytes:
    """Big-Endian ohne fuehrende Nullen (mpz_to_bin)."""
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _h(*parts: bytes) -> bytes:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part)
    return digest.digest()


def _x(salt: bytes, name: str, password: str) -> int:
    inner = _h(name.lower().encode("utf-8"), b":", password.encode("utf-8"))
    return int.from_bytes(_h(salt, inner), "big")


def _h_nn(a: int, b: int) -> int:
    return int.from_bytes(_h(_bin(a).rjust(N_LEN, b"\0"), _bin(b).rjust(N_LEN, b"\0")), "big")


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


class SrpClient:
    """Client-Seite von SRP-6a, wie Luanti sie erwartet (aus luanti_probe hierher verschoben).

    ``secret`` ist fuer Tests injizierbar; ohne Angabe ein frischer 256-Bit-Zufallswert.
    """

    def __init__(self, name: str, password: str, secret: int | None = None) -> None:
        self.name = name  # Originalschreibweise fuer M, kleingeschrieben nur in x
        self.password = password
        self.secret = secrets.randbits(256) if secret is None else secret
        self.public = pow(G, self.secret, N)

    def bytes_a(self) -> bytes:
        return _bin(self.public)

    def process(self, salt: bytes, bytes_b: bytes) -> bytes:
        server_public = int.from_bytes(bytes_b, "big")
        u = _h_nn(self.public, server_public)
        x = _x(salt, self.name, self.password)
        k = _h_nn(N, G)
        shared = pow((server_public - k * pow(G, x, N)) % N, self.secret + u * x, N)
        key = _h(_bin(shared))
        h_xor = bytes(i ^ j for i, j in zip(_h(_bin(N)), _h(_bin(G)), strict=True))
        return _h(h_xor, _h(self.name.encode("utf-8")), salt, _bin(self.public), _bin(server_public), key)


class SrpTakeoverError(Exception):
    """Die SRP-Sitzung ist zu beenden; ``reason`` ist eine feste ASCII-Konstante, nie ein Wert."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SrpTakeover:
    """Uebernimmt die SRP-Anmeldung fuer genau einen Spielernamen und sein echtes Passwort.

    ``client_packet`` entscheidet ueber ein Datagramm vom Browser (ersetzen, unveraendert
    durchreichen oder Sitzung beenden), ``server_packet`` liest S_B und AUTH_ACCEPT der Welt.
    Das Passwort lebt nur im ``SrpClient`` im Speicher; ``__repr__`` nennt keine Werte.
    """

    def __init__(self, player_name: str, password: str, secret: int | None = None) -> None:
        self._player_name = player_name
        self._srp = SrpClient(player_name, password, secret=secret)
        self._a_cache: dict[int, bytes] = {}
        self._m_cache: dict[int, bytes] = {}
        self._s_b_seen = False
        self._m_proof: bytes | None = None
        self._authed = False

    def __repr__(self) -> str:
        return "SrpTakeover()"

    def client_packet(self, datagram: bytes) -> bytes:
        """Datagramm vom Browser: SRP ersetzen, sonst unveraendert; Verstoesse werfen SrpTakeoverError."""
        try:
            parsed = mtp.parse(datagram)
        except mtp.MtpError as exc:
            raise SrpTakeoverError("client_unreadable") from exc
        if parsed.inner_ptype == mtp.PT_SPLIT:
            if not self._authed:
                raise SrpTakeoverError("split_before_auth")
            if parsed.split_command in mtp.SRP_COMMANDS:
                raise SrpTakeoverError("srp_in_split")
            return datagram
        if parsed.command == mtp.TOSERVER_SRP_BYTES_A:
            return self._replace_a(datagram, parsed)
        if parsed.command == mtp.TOSERVER_SRP_BYTES_M:
            return self._replace_m(datagram, parsed)
        return datagram

    def _replace_a(self, datagram: bytes, parsed: mtp.Parsed) -> bytes:
        seq = parsed.reliable_seq
        if seq is None:
            raise SrpTakeoverError("a_not_reliable")
        cached = self._a_cache.get(seq)
        if cached is not None:
            return cached
        if self._s_b_seen:
            # Neue A-Sequenz nach S_B hiesse Auth-Neustart: nicht erlaubt.
            raise SrpTakeoverError("second_a")
        packet = mtp.rewrite_payload(datagram, _str16(self._srp.bytes_a()) + b"\x01")
        self._a_cache[seq] = packet
        return packet

    def _replace_m(self, datagram: bytes, parsed: mtp.Parsed) -> bytes:
        seq = parsed.reliable_seq
        if seq is None:
            raise SrpTakeoverError("m_not_reliable")
        cached = self._m_cache.get(seq)
        if cached is not None:
            return cached
        if not self._s_b_seen or self._m_proof is None:
            raise SrpTakeoverError("m_before_s_b")
        packet = mtp.rewrite_payload(datagram, _str16(self._m_proof))
        self._m_cache[seq] = packet
        return packet

    def server_packet(self, datagram: bytes) -> None:
        """Datagramm der Welt: S_B rechnet M_p, AUTH_ACCEPT schaltet die Split-Regel frei."""
        try:
            parsed = mtp.parse(datagram)
        except mtp.MtpError as exc:
            raise SrpTakeoverError("server_unreadable") from exc
        if parsed.command == mtp.TOCLIENT_SRP_BYTES_S_B:
            salt, bytes_b = self._read_s_b(parsed.payload)
            self._m_proof = self._srp.process(salt, bytes_b)
            self._s_b_seen = True
        elif parsed.command == mtp.TOCLIENT_AUTH_ACCEPT:
            self._authed = True

    @staticmethod
    def _read_s_b(payload: bytes) -> tuple[bytes, bytes]:
        """Liest u16 Salzlaenge + Salz + u16 B-Laenge + B; jede falsche Laenge beendet die Sitzung."""
        try:
            salt_len = struct.unpack_from(">H", payload, 0)[0]
            salt = payload[2 : 2 + salt_len]
            b_len = struct.unpack_from(">H", payload, 2 + salt_len)[0]
            bytes_b = payload[4 + salt_len : 4 + salt_len + b_len]
        except struct.error as exc:
            raise SrpTakeoverError("s_b_malformed") from exc
        if len(salt) != salt_len or len(bytes_b) != b_len or b_len == 0:
            raise SrpTakeoverError("s_b_malformed")
        return salt, bytes_b
