"""Text commands of the WebSocket proxy and the fixed destination rule, pure.

The browser client (webshims emsocket) speaks two text commands before the binary messages:
``NEWADDR`` fetches an address with a passcode, ``BIND <passcode> UDP <port>`` binds a UDP socket.
Gameworld recognizes only these two in exactly the spelling the client sends. Everything else,
in particular the client's TCP forwarding command (curl for ContentDB and server list) as well as
JOIN and PING from lwproxy, yields ``Rejected``: no branch of this module opens an arbitrary destination.
Sources: paradust7/webshims, commit 70653a9, ``src/emsocket/proxy.js`` (requestAssignment,
ProxyLink.handleOpen); semantics after paradust7/lwproxy ``src/service/commands.rs``.
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
    """The client asks for an address and passcode."""


@dataclass(frozen=True)
class Bind:
    """The client binds a UDP socket with the passcode of its session."""

    passcode: str
    port: int


@dataclass(frozen=True)
class Rejected:
    """Unknown or inadmissible command; ``reason`` is a fixed ASCII constant."""

    reason: str


def parse_command(text: str) -> NewAddr | Bind | Rejected:
    """Recognizes NEWADDR and BIND, rejects everything else (length and ASCII first)."""
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
    """Answer to NEWADDR: ``ADDR <address> <passcode> <joincode>``.

    proxy.js (requestAssignment) splits the answer at spaces and requires exactly four tokens with
    ``ADDR`` first. The join code is only stored and serves invitations between browsers, which
    Gameworld does not offer; ``-`` satisfies the format. The passcode is checked so that no
    space produces a fifth token.
    """
    if not passcode.isascii() or not PASSCODE_RE.fullmatch(passcode):
        raise ValueError("Passcode ungültig")
    return f"ADDR {VIRTUAL_CLIENT} {passcode} -"


def target_allowed(host: str, port: int) -> bool:
    """True only for the virtual destination 10.77.0.1:30000.

    The real destination never comes from the head of a frame, but from the session (ticket, world, port).
    The head is only checked so that a client addresses nothing else; this way the proxy becomes neither
    an open UDP relay into the home network (SSRF) nor an amplifier (UDP amplification).
    """
    return (host, port) == VIRTUAL_SERVER
