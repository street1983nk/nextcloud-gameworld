"""Live-Beleg 04.2-09: SRP-Uebernahme durch den Proxy (Variante A, D-10) gegen eine echte Welt.

Aufbau wie test_play_proxy_e2e.py (dieselben Fixtures und Helfer importiert, nicht kopiert):
Die ExApp laeuft als echter uvicorn-Server im Modus dev, der Weg ist der des Browsers
(Ticket, /play/launch, /play/ws mit NEWADDR und BIND). Der Unterschied: GAMEWORLD_PLAY_AUTH
steht hier auf proxy_srp, und das Kind meldet sich mit dem wertlosen Platzhalter-Passwort an.

Positivkontrolle: Login gelingt, /play/launch liefert password null. Gegenprobe: im
password-Modus lehnt dieselbe Welt das Platzhalter-Passwort ab (die Uebernahme ist die
Ursache des Erfolgs). Negativtests: fremder Name, FIRST_SRP und ein RELIABLE(SPLIT) mit
SRP-Inhalt beenden die Sitzung vor der Welt. A1: nach dem Login werden INIT2 und
CLIENT_READY ueber das Relais angenommen (keine Verschluesselung nach SRP).
"""

from __future__ import annotations

import re
import struct
import time
from collections.abc import Callable
from functools import partial

import anyio.to_thread
import pytest

from gameworld.play.srp_proxy import PLACEHOLDER_PASSWORD
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import PROTO, session
from tests.e2e.test_play_proxy_e2e import (
    VIRTUAL,
    Launch,
    RelayServer,
    _factory,
    _invite,
    _launch,
    _relay_join,
    _wait_relay_end,
    _world_log,
)
from tests.e2e.time_helpers import MTG_READY, create_running_world
from tests.e2e.ws_datagram import WsDatagramSocket

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

TOSERVER_FIRST_SRP = 0x50
TOSERVER_SRP_BYTES_A = 0x51


def _reliable(command: int, payload: bytes, seq: int, peer_id: int = 1, channel: int = 1) -> bytes:
    head = struct.pack(">IHB", PROTO, peer_id, channel)
    return head + struct.pack(">BH", 3, seq) + b"\x01" + struct.pack(">H", command) + payload


def _reliable_split_srp_a(seq: int, peer_id: int = 1, channel: int = 1) -> bytes:
    """RELIABLE(SPLIT), dessen Chunk 0 mit dem SRP_BYTES_A-Kommando beginnt."""
    chunk0 = struct.pack(">H", TOSERVER_SRP_BYTES_A) + b"\x00" * 16
    split = struct.pack(">BHHH", 2, 7, 2, 0) + chunk0
    return struct.pack(">IHB", PROTO, peer_id, channel) + struct.pack(">BH", 3, seq) + split


async def _send_raw_until_closed(relay: RelayServer, launch: Launch, packet: bytes) -> WsDatagramSocket:
    """Sendet ein selbst gebautes Paket ueber das Relais, bis der Server schliesst (Waechter greift)."""

    def run() -> WsDatagramSocket:
        sock = WsDatagramSocket(launch.url, relay.origin)
        relay.sockets.append(sock)
        sock.settimeout(0.5)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not sock.closed_by_server:
            sock.sendto(packet, VIRTUAL)
            try:
                sock.recvfrom(65535)
            except TimeoutError:
                continue
        return sock

    return await anyio.to_thread.run_sync(run)


# Der gameworld_access-Mod sperrt den sofortigen Wiederbeitritt kurz (Phase 3, K6); darum
# wiederholen die Live-Joins, bis der erwartete Zustand erreicht ist oder das Fenster endet.
REJOIN_WINDOW = 20.0


async def _join_retry(
    relay: RelayServer,
    uid: str,
    world_id: str,
    name: str,
    password: str,
    accept: Callable[[dict[str, object]], bool],
) -> dict[str, object]:
    deadline = time.monotonic() + REJOIN_WINDOW
    result = await _relay_join(relay, uid, world_id, name=name, password=password)
    while not accept(result) and time.monotonic() < deadline:
        await anyio.sleep(1.0)
        result = await _relay_join(relay, uid, world_id, name=name, password=password)
    return result


async def _session_retry(
    relay: RelayServer, uid: str, world_id: str, name: str, password: str, hold: float
) -> dict[str, object]:
    deadline = time.monotonic() + REJOIN_WINDOW
    while True:
        launch = await _launch(relay, uid, world_id)
        held = await anyio.to_thread.run_sync(
            partial(session, launch.address, launch.port, name, password, hold, 8.0, _factory(relay, launch))
        )
        if held["result"] in {"held", "kicked"} or time.monotonic() > deadline:
            return held
        await anyio.sleep(1.0)


async def test_variante_a_positiv_gegenprobe_und_a1(
    relay: RelayServer, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    world_id, port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    del port
    name, real_password = await _invite(relay, world_id, "gw-kind")
    assert real_password != PLACEHOLDER_PASSWORD

    # Variante A: /play/launch gibt kein Passwort heraus (password null).
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    issued = await relay.http.post(
        "/api/my/play-ticket", json={"world_id": world_id}, headers=appapi_headers("gw-kind")
    )
    assert issued.status_code == 200, issued.text
    launched = await relay.http.post(
        "/play/launch",
        json={"ticket": str(issued.json()["ticket"])},
        headers={"Origin": relay.origin, "Sec-Fetch-Site": "same-origin"},
    )
    assert launched.status_code == 200, launched.text
    assert launched.json()["password"] is None, "Variante A liefert kein Passwort an den Browser"

    # Positivkontrolle: Login mit dem Platzhalter-Passwort gelingt, weil der Proxy SRP uebernimmt.
    accepted = await _join_retry(
        relay, "gw-kind", world_id, name, PLACEHOLDER_PASSWORD, lambda r: r["result"] == "auth_accept"
    )
    assert accepted["result"] == "auth_accept", accepted

    # Gegenprobe: im password-Modus lehnt dieselbe Welt das Platzhalter-Passwort ab (Stage M).
    # Die Uebernahme ist also die Ursache des Erfolgs, kein Umgehen der Passwortpruefung.
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "password")
    denied = await _join_retry(
        relay, "gw-kind", world_id, name, PLACEHOLDER_PASSWORD, lambda r: r.get("code") == "WRONG_PASSWORD"
    )
    assert denied["result"] == "denied", denied
    assert denied.get("stage") == "M", denied
    assert denied["code"] == "WRONG_PASSWORD", denied

    # A1: nach dem Login werden INIT2 und CLIENT_READY ueber das Relais angenommen (keine
    # Verschluesselung nach SRP). Zuletzt, weil der volle Beitritt die Rejoin-Sperre ausloest.
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    held = await _session_retry(relay, "gw-kind", world_id, name, PLACEHOLDER_PASSWORD, 2.0)
    assert held["result"] in {"held", "kicked"}, held
    assert "after_s" in held, held

    lines = _wait_relay_end(caplog, 1)
    assert any("srp_replaced=2" in line for line in lines), lines


async def test_fremder_name_beendet_vor_srp_ersatz(
    relay: RelayServer, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    name, _ = await _invite(relay, world_id, "gw-kind")
    sibling, _sibling_pw = await _invite(relay, world_id, "gw-kind2")
    assert sibling != name

    # Ticket des Kindes, INIT mit dem Namen des eingeladenen Geschwisters: Abbruch vor jedem SRP-Ersatz.
    forged = await _relay_join(relay, "gw-kind", world_id, name=sibling, password=PLACEHOLDER_PASSWORD)
    assert forged["result"] in {"timeout", "no_peer_id"}, forged
    sock = relay.sockets[-1]
    assert sock.closed_by_server, "Relais haette schliessen muessen"
    assert sock.close_code == 1008, sock.close_code
    lines = _wait_relay_end(caplog, 1)
    assert any(line.endswith("reason=guard_name_mismatch") for line in lines), lines
    # Der Geschwistername hat die Welt nie erreicht (kein SRP fuer ein fremdes Konto).
    assert re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None


async def test_first_srp_und_split_beenden_sitzung(
    relay: RelayServer, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    await _invite(relay, world_id, "gw-kind")

    # FIRST_SRP (Registrierung/Passwortaenderung) ueber das Relais: der Waechter beendet die Sitzung.
    launch_first = await _launch(relay, "gw-kind", world_id)
    first_packet = _reliable(TOSERVER_FIRST_SRP, b"\x00" * 8, seq=65501)
    sock_first = await _send_raw_until_closed(relay, launch_first, first_packet)
    assert sock_first.closed_by_server, "FIRST_SRP haette die Sitzung beenden muessen"
    assert sock_first.close_code == 1008, sock_first.close_code

    # RELIABLE(SPLIT) mit SRP_BYTES_A-Inhalt vor AUTH_ACCEPT: die Sitzung endet, die Welt erhaelt nichts.
    launch_split = await _launch(relay, "gw-kind", world_id)
    split_packet = _reliable_split_srp_a(seq=65501)
    sock_split = await _send_raw_until_closed(relay, launch_split, split_packet)
    assert sock_split.closed_by_server, "SPLIT vor AUTH_ACCEPT haette die Sitzung beenden muessen"
    assert sock_split.close_code == 1008, sock_split.close_code

    lines = _wait_relay_end(caplog, 2)
    assert any(line.endswith("reason=guard_first_srp") for line in lines), lines
    assert any(line.endswith("reason=guard_split_before_auth") for line in lines), lines
    # Die Welt hat kein Paket aus diesen Sitzungen bekommen: frames_out blieb 0.
    assert all("frames_out=0" in line for line in lines if "guard_" in line), lines
