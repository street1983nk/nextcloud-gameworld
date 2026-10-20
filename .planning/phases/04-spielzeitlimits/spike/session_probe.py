"""Phase-4-Spike: vollständiger Join ohne Luanti-Client, Verbindung halten, Chat und Kick mitschneiden.

Baut auf tests/e2e/luanti_probe.py auf (MTP + SRP bis AUTH_ACCEPT) und ergänzt
den Rest des Client-Ablaufs aus Luanti 5.17.0:
- TOSERVER_INIT2 (0x11, Kanal 1, zuverlässig, str16 Sprache) -> Server schickt Definitionen
- TOSERVER_CLIENT_READY (0x43, Kanal 1, zuverlässig): u8 major, minor, patch, reserved,
  str16 Versionstext, u16 Formspec-Version -> StageTwoClientInit -> on_joinplayer
- danach: zuverlässige Pakete quittieren, alle 3 s CONTROL PING, Chat (0x2F) und
  ACCESS_DENIED (0x0A) mitschneiden.
"""

from __future__ import annotations

import pathlib
import struct
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from tests.e2e.luanti_probe import Probe, SrpClient, _parse_denied, _str16  # noqa: E402

TOSERVER_INIT2 = 0x11
TOSERVER_CLIENT_READY = 0x43
TOCLIENT_CHAT_MESSAGE = 0x2F
TOCLIENT_ACCESS_DENIED = 0x0A


def _wide(data: bytes, offset: int) -> tuple[str, int]:
    length = struct.unpack(">H", data[offset : offset + 2])[0]
    raw = data[offset + 2 : offset + 2 + 2 * length]
    return raw.decode("utf-16-be", "replace"), offset + 2 + 2 * length


def _chat(data: bytes) -> str:
    try:
        _sender, offset = _wide(data, 2)
        message, _ = _wide(data, offset)
    except (struct.error, IndexError):
        return "<unlesbar>"
    return message


def session(host: str, port: int, name: str, password: str, hold: float, timeout: float = 8.0) -> dict[str, object]:
    """Join bis on_joinplayer, dann bis ``hold`` Sekunden halten oder bis zum Kick."""
    probe = Probe(host, port)
    events: list[tuple[float, str, str]] = []
    start = time.monotonic()
    deadline = start + timeout
    try:
        probe.send_reliable(0, 0)
        while probe.peer_id == 0 and time.monotonic() < deadline:
            try:
                data, _ = probe.sock.recvfrom(65535)
            except TimeoutError:
                probe.send_reliable(0, 0)
                continue
            probe.handle(data[6], data[7:])
        if probe.peer_id == 0:
            return {"result": "no_peer_id"}
        init = struct.pack(">BH", 29, 0) + struct.pack(">HH", 37, 53) + _str16(name.encode())
        probe.send_original(1, 0x02, init)
        command, data = probe.recv_command(deadline)
        if command == TOCLIENT_ACCESS_DENIED:
            return {**_parse_denied(data), "stage": "init"}
        srp = SrpClient(name, password)
        probe.send_reliable(1, 0x51, _str16(srp.bytes_a()) + b"\x01")
        command, data = probe.recv_command(deadline)
        if command != 0x60:
            return {"result": "unexpected", "command": command}
        salt_len = struct.unpack(">H", data[:2])[0]
        salt = data[2 : 2 + salt_len]
        b_len = struct.unpack(">H", data[2 + salt_len : 4 + salt_len])[0]
        probe.send_reliable(1, 0x52, _str16(srp.process(salt, data[4 + salt_len : 4 + salt_len + b_len])))
        command, data = probe.recv_command(deadline)
        if command != 0x03:
            return {**_parse_denied(data), "stage": "auth"} if command == 0x0A else {"result": "unexpected"}
        probe.send_reliable(1, TOSERVER_INIT2, _str16(b"de"))
        version = b"5.17.0-spike"
        probe.send_reliable(1, TOSERVER_CLIENT_READY, struct.pack(">BBBB", 5, 17, 0, 0) + _str16(version)
                            + struct.pack(">H", 10))
        joined_at = time.monotonic()
        last_ping = joined_at
        probe.sock.settimeout(0.5)
        while time.monotonic() - joined_at < hold:
            if time.monotonic() - last_ping > 3:
                probe._send(0, struct.pack(">BB", 0, 2))  # CONTROL PING
                last_ping = time.monotonic()
            try:
                command, data = probe.recv_command(time.monotonic() + 0.5)
            except TimeoutError:
                continue
            t = round(time.monotonic() - joined_at, 1)
            if command == TOCLIENT_CHAT_MESSAGE:
                events.append((t, "chat", _chat(data)))
            elif command == TOCLIENT_ACCESS_DENIED:
                denied = _parse_denied(data)
                events.append((t, "kick", f"{denied['code']}: {denied['reason']}"))
                return {"result": "kicked", "after_s": t, "events": events}
        return {"result": "held", "after_s": round(time.monotonic() - joined_at, 1), "events": events}
    finally:
        probe.close()


if __name__ == "__main__":
    print(session(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], float(sys.argv[5])))
