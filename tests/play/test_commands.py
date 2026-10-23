"""Textkommandos des Proxys und die feste Zielregel, jeweils mit Positivkontrolle."""

import secrets

import pytest

from gameworld.play.commands import (
    MAX_COMMAND,
    VIRTUAL_CLIENT,
    VIRTUAL_SERVER,
    Bind,
    NewAddr,
    Rejected,
    format_addr,
    parse_command,
    target_allowed,
)
from gameworld.play.framing import pack, unpack

PASSCODE = "abcdEFGH_-12345678901"  # 21 Zeichen aus [A-Za-z0-9_-]


def test_virtual_addresses() -> None:
    assert VIRTUAL_SERVER == ("10.77.0.1", 30000)
    assert VIRTUAL_CLIENT == "10.77.0.2"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Positivkontrollen: genau das, was webshims proxy.js sendet.
        ("NEWADDR", NewAddr()),
        (f"BIND {PASSCODE} UDP 30000", Bind(PASSCODE, 30000)),
        (f"BIND {PASSCODE} UDP 1", Bind(PASSCODE, 1)),
        (f"BIND {PASSCODE} UDP 65535", Bind(PASSCODE, 65535)),
        (f"BIND {'a' * 64} UDP 4242", Bind("a" * 64, 4242)),
        (f"BIND {'a' * 16} UDP 4242", Bind("a" * 16, 4242)),
    ],
)
def test_accepted_commands(text: str, expected: NewAddr | Bind) -> None:
    assert parse_command(text) == expected


def test_real_token_urlsafe_passcode_is_accepted() -> None:
    """Plan 07 erzeugt Passcodes mit secrets.token_urlsafe(16); die Regel muss sie tragen."""
    for _ in range(50):
        passcode = secrets.token_urlsafe(16)
        assert parse_command(f"BIND {passcode} UDP 30000") == Bind(passcode, 30000)


@pytest.mark.parametrize(
    "text",
    [
        # Positivkontrollen stehen in test_accepted_commands; hier alles, was abgelehnt werden muss.
        "PROXY IPV4 TCP 1.1.1.1 443",
        "PROXY IPV4 UDP 10.77.0.1 30000",
        "PROXY IPV6 TCP ::1 80",
        "JOIN x",
        "PING",
        "",
        " ",
        "NEWADDR ",
        " NEWADDR",
        "newaddr",
        "NEWADDR\n",
        "NEWADDR x",
        "BIND x UDP",
        "BIND x TCP 30000",
        "BIND x UDP 0",
        "BIND x UDP 65536",
        "BIND x UDP 3e4",
        f"BIND {PASSCODE} TCP 30000",
        f"BIND {PASSCODE} udp 30000",
        f"bind {PASSCODE} UDP 30000",
        f"BIND {PASSCODE} UDP 0",
        f"BIND {PASSCODE} UDP 65536",
        f"BIND {PASSCODE} UDP 3e4",
        f"BIND {PASSCODE} UDP 030000",
        f"BIND {PASSCODE} UDP -1",
        f"BIND {PASSCODE} UDP +5",
        f"BIND {PASSCODE} UDP ",
        f"BIND {PASSCODE}  UDP 30000",
        f"BIND {PASSCODE} UDP 30000 extra",
        f"BIND {PASSCODE}\tUDP 30000",
        "BIND " + "a" * 15 + " UDP 30000",  # Passcode zu kurz
        "BIND " + "a" * 65 + " UDP 30000",  # Passcode zu lang
        "BIND abcdEFGH.12345678901 UDP 30000",  # Zeichen außerhalb [A-Za-z0-9_-]
        "BIND abcdEFGH/12345678901 UDP 30000",
        "BIND abcdEFGH=12345678901 UDP 30000",
        "BIND ä UDP 1",
        f"BIND {PASSCODE} UDP 3" + chr(0x0660),  # arabisch-indische Ziffer Null
        "N" * (MAX_COMMAND + 1),
        "BIND " + "a" * 250,
    ],
)
def test_rejected_commands(text: str) -> None:
    assert isinstance(parse_command(text), Rejected)


def test_length_limit_boundary() -> None:
    assert MAX_COMMAND == 255
    assert len("N" * 256) == 256
    assert isinstance(parse_command("N" * 256), Rejected)
    assert parse_command("N" * 255) == Rejected("unknown_command")


def test_rejected_reason_is_ascii_constant_without_input() -> None:
    result = parse_command("PROXY IPV4 TCP 1.1.1.1 443")
    assert isinstance(result, Rejected)
    assert result.reason.isascii()
    assert "1.1.1.1" not in result.reason


def test_format_addr_has_four_tokens() -> None:
    """proxy.js teilt die Antwort an Leerzeichen und verlangt genau vier Tokens mit ADDR vorn.

    Der Join-Code (viertes Token) wird nur gespeichert und für Einladungen zwischen Browsern
    genutzt, die Gameworld nicht anbietet; ein "-" erfüllt das Format.
    """
    line = format_addr(PASSCODE)
    assert line == f"ADDR 10.77.0.2 {PASSCODE} -"
    parts = line.split(" ")
    assert len(parts) == 4
    assert parts[0] == "ADDR"
    assert parts[1] == VIRTUAL_CLIENT
    assert parts[2] == PASSCODE


@pytest.mark.parametrize("passcode", ["", "kurz", "a b" + "c" * 20, "a" * 65, "ä" * 20])
def test_format_addr_rejects_bad_passcode(passcode: str) -> None:
    with pytest.raises(ValueError, match="Passcode"):
        format_addr(passcode)


@pytest.mark.parametrize(
    ("host", "port", "allowed"),
    [
        # Positivkontrolle: das virtuelle Ziel.
        ("10.77.0.1", 30000, True),
        # Manipulierte Ziele.
        ("10.77.0.1", 30001, False),
        ("10.77.0.1", 0, False),
        ("10.77.0.2", 30000, False),
        ("127.0.0.1", 30000, False),
        ("192.168.0.1", 53, False),
        ("::1", 30000, False),
        ("::ffff:10.77.0.1", 30000, False),  # nur unpack normalisiert, siehe unten
        ("10.077.0.1", 30000, False),
        ("", 30000, False),
    ],
)
def test_target_allowed(host: str, port: int, allowed: bool) -> None:
    assert target_allowed(host, port) is allowed


def test_mapped_target_is_allowed_after_unpack() -> None:
    """Der Client schickt das Ziel als ::ffff:10.77.0.1; unpack macht daraus 10.77.0.1."""
    frame = bytes.fromhex("778b4cf6" + "00" * 10 + "ffff0a4d0001" + "7530" + "0000")
    host, port, _ = unpack(frame)
    assert target_allowed(host, port) is True


def test_other_target_after_unpack_is_refused() -> None:
    host, port, _ = unpack(pack("192.168.0.1", 30000, b""))
    assert target_allowed(host, port) is False
