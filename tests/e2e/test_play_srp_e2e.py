"""Live proof 04.2-09: SRP takeover by the proxy (variant A, D-10) against a real world.

Setup like test_play_proxy_e2e.py (the same fixtures and helpers imported, not copied):
the ExApp runs as a real uvicorn server in mode dev, the path is that of the browser
(ticket, /play/launch, /play/ws with NEWADDR and BIND). The difference: GAMEWORLD_PLAY_AUTH
is set to proxy_srp here, and the child logs in with the worthless placeholder password.

Positive control: login succeeds, /play/launch returns password null. Control: in
password mode the same world rejects the placeholder password (the takeover is the
cause of the success). Negative tests: foreign name, FIRST_SRP and a RELIABLE(SPLIT) with
SRP content end the session before the world. A1: after the login INIT2 and
CLIENT_READY are accepted via the relay (no encryption after SRP).
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
    """RELIABLE(SPLIT) whose chunk 0 starts with the SRP_BYTES_A command."""
    chunk0 = struct.pack(">H", TOSERVER_SRP_BYTES_A) + b"\x00" * 16
    split = struct.pack(">BHHH", 2, 7, 2, 0) + chunk0
    return struct.pack(">IHB", PROTO, peer_id, channel) + struct.pack(">BH", 3, seq) + split


async def _send_raw_until_closed(relay: RelayServer, launch: Launch, packet: bytes) -> WsDatagramSocket:
    """Sends a self-built packet via the relay until the server closes (guard takes effect)."""

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


# The gameworld_access mod blocks an immediate rejoin briefly (phase 3, K6); therefore
# the live joins repeat until the expected state is reached or the window ends.
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

    # Variant A: /play/launch hands out no password (password null).
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

    # Positive control: login with the placeholder password succeeds because the proxy takes over SRP.
    accepted = await _join_retry(
        relay, "gw-kind", world_id, name, PLACEHOLDER_PASSWORD, lambda r: r["result"] == "auth_accept"
    )
    assert accepted["result"] == "auth_accept", accepted

    # Control: in password mode the same world rejects the placeholder password (stage M).
    # The takeover is thus the cause of the success, not a bypass of the password check.
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "password")
    denied = await _join_retry(
        relay, "gw-kind", world_id, name, PLACEHOLDER_PASSWORD, lambda r: r.get("code") == "WRONG_PASSWORD"
    )
    assert denied["result"] == "denied", denied
    assert denied.get("stage") == "M", denied
    assert denied["code"] == "WRONG_PASSWORD", denied

    # A1: after the login INIT2 and CLIENT_READY are accepted via the relay (no
    # encryption after SRP). Last, because the full join triggers the rejoin block.
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

    # Ticket of the child, INIT with the name of the invited sibling: abort before any SRP replacement.
    forged = await _relay_join(relay, "gw-kind", world_id, name=sibling, password=PLACEHOLDER_PASSWORD)
    assert forged["result"] in {"timeout", "no_peer_id"}, forged
    sock = relay.sockets[-1]
    assert sock.closed_by_server, "Relais haette schliessen muessen"
    assert sock.close_code == 1008, sock.close_code
    lines = _wait_relay_end(caplog, 1)
    assert any(line.endswith("reason=guard_name_mismatch") for line in lines), lines
    # The sibling's name never reached the world (no SRP for a foreign account).
    assert re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None


async def test_first_srp_und_split_beenden_sitzung(
    relay: RelayServer, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    await _invite(relay, world_id, "gw-kind")

    # FIRST_SRP (registration/password change) via the relay: the guard ends the session.
    launch_first = await _launch(relay, "gw-kind", world_id)
    first_packet = _reliable(TOSERVER_FIRST_SRP, b"\x00" * 8, seq=65501)
    sock_first = await _send_raw_until_closed(relay, launch_first, first_packet)
    assert sock_first.closed_by_server, "FIRST_SRP haette die Sitzung beenden muessen"
    assert sock_first.close_code == 1008, sock_first.close_code

    # RELIABLE(SPLIT) with SRP_BYTES_A content before AUTH_ACCEPT: the session ends, the world receives nothing.
    launch_split = await _launch(relay, "gw-kind", world_id)
    split_packet = _reliable_split_srp_a(seq=65501)
    sock_split = await _send_raw_until_closed(relay, launch_split, split_packet)
    assert sock_split.closed_by_server, "SPLIT vor AUTH_ACCEPT haette die Sitzung beenden muessen"
    assert sock_split.close_code == 1008, sock_split.close_code

    lines = _wait_relay_end(caplog, 2)
    assert any(line.endswith("reason=guard_first_srp") for line in lines), lines
    assert any(line.endswith("reason=guard_split_before_auth") for line in lines), lines
    # The world received no packet from these sessions: frames_out stayed 0.
    assert all("frames_out=0" in line for line in lines if "guard_" in line), lines
