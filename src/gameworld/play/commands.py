"""Textkommandos des WebSocket-Proxys und die feste Zielregel, rein.

Der Browser-Client (webshims emsocket) spricht vor den Binärnachrichten zwei Textkommandos:
``NEWADDR`` holt eine Adresse samt Passcode, ``BIND <passcode> UDP <port>`` bindet einen UDP-Socket.
Gameworld erkennt nur diese beiden in genau der Schreibweise, die der Client sendet. Alles andere,
insbesondere das TCP-Weiterleitungskommando des Clients (curl für ContentDB und Serverliste) sowie
JOIN und PING aus lwproxy, ergibt ``Rejected``: Kein Zweig dieses Moduls öffnet ein beliebiges Ziel.
Quellen: paradust7/webshims, Commit 70653a9, ``src/emsocket/proxy.js`` (requestAssignment,
ProxyLink.handleOpen); Semantik nach paradust7/lwproxy ``src/service/commands.rs``.
"""

import re
from dataclasses import dataclass

VIRTUAL_SERVER = ("10.77.0.1", 30000)
VIRTUAL_CLIENT = "10.77.0.2"
MAX_COMMAND = 255
PASSCODE_RE = re.compile(r"[A-Za-z0-9_-]{16,64}")
PORT_RE = re.compile(r"[1-9][0-9]{0,4}")


@dataclass(frozen=True)
class NewAddr:
    """Der Client fragt nach Adresse und Passcode."""


@dataclass(frozen=True)
class Bind:
    """Der Client bindet einen UDP-Socket mit dem Passcode seiner Sitzung."""

    passcode: str
    port: int


@dataclass(frozen=True)
class Rejected:
    """Unbekanntes oder unzulässiges Kommando; ``reason`` ist eine feste ASCII-Konstante."""

    reason: str


def parse_command(text: str) -> NewAddr | Bind | Rejected:
    """Erkennt NEWADDR und BIND, lehnt alles andere ab (Länge und ASCII zuerst)."""
    if len(text) > MAX_COMMAND:
        return Rejected("too_long")
    if not text.isascii():
        return Rejected("not_ascii")
    if text == "NEWADDR":
        return NewAddr()
    parts = text.split(" ")
    if parts[0] != "BIND":
        return Rejected("unknown_command")
    if len(parts) != 4:
        return Rejected("bad_arity")
    _, passcode, proto, port = parts
    if proto != "UDP":
        return Rejected("bad_protocol")
    if not PASSCODE_RE.fullmatch(passcode):
        return Rejected("bad_passcode")
    if not PORT_RE.fullmatch(port) or int(port) > 65535:
        return Rejected("bad_port")
    return Bind(passcode, int(port))


def format_addr(passcode: str) -> str:
    """Antwort auf NEWADDR: ``ADDR <adresse> <passcode> <joincode>``.

    proxy.js (requestAssignment) teilt die Antwort an Leerzeichen und verlangt genau vier Tokens mit
    ``ADDR`` vorn. Der Join-Code wird nur gespeichert und dient Einladungen zwischen Browsern, die
    Gameworld nicht anbietet; ``-`` erfüllt das Format. Der Passcode wird geprüft, damit kein
    Leerzeichen ein fünftes Token erzeugt.
    """
    if not passcode.isascii() or not PASSCODE_RE.fullmatch(passcode):
        raise ValueError("Passcode ungültig")
    return f"ADDR {VIRTUAL_CLIENT} {passcode} -"


def target_allowed(host: str, port: int) -> bool:
    """True nur für das virtuelle Ziel 10.77.0.1:30000.

    Das echte Ziel kommt nie aus dem Kopf eines Frames, sondern aus der Sitzung (Ticket, Welt, Port).
    Der Kopf wird nur geprüft, damit ein Client nichts anderes adressiert; so wird der Proxy weder
    ein offenes UDP-Relais ins Heimnetz (SSRF) noch ein Verstärker (UDP-Amplification).
    """
    return (host, port) == VIRTUAL_SERVER
