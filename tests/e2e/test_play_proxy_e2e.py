"""Live proof 04.2-08: WebSocket relay from Gameworld to a real Luanti 5.17.0 world.

Success criterion 2 of the browser spike: the browser path changes nothing about the rules of the
world. The mods (gameworld_access, gameworld_time) keep deciding in the prejoin, the
server checks the password itself, and a foreign player name never reaches the world.

Setup as on the dev path (plan 08): the ExApp runs as a real uvicorn server in a
thread, with its own app in mode dev (disable_for only play and play/*), the flow is
that of the browser: ticket via /api/my/play-ticket (AppAPI-signed), /play/launch with
origin, then /play/ws with NEWADDR and BIND. The join itself is luanti_probe.join, only
the transport is swapped for tests/e2e/ws_datagram.py.

Nextcloud directory and secret are the fakes from tests/conftest.py; world, mods,
relay and join are real. Serial, one MTG creative world per test.
"""

from __future__ import annotations

import logging
import re
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import anyio.to_thread
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from nc_py_api.ex_app import AppAPIAuthMiddleware

from gameworld.api import invites, me, pause, playtime, worlds
from gameworld.api.csrf import JsonOnlyChangesMiddleware
from gameworld.main import _uvicorn_loop  # pyright: ignore[reportPrivateUsage]
from gameworld.play import sessions as sessions_module
from gameworld.play.app import install_play
from gameworld.play.config import play_disable_for
from gameworld.provisioner.time_mod import TEXT_LIMIT, TEXT_PAUSE
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import PROTO, DatagramSocket, join
from tests.e2e.time_helpers import HOST, MTG_READY, create_running_world, docker_api
from tests.e2e.ws_datagram import WsDatagramSocket

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

BERLIN = ZoneInfo("Europe/Berlin")
# Never matches: the alphabet of real passwords has no "0" and no "1".
WRONG_PASSWORD = "0000-1111-0000"  # noqa: S105
VIRTUAL = ("10.77.0.1", 30000)
# The time mod re-reads the rule file at least every 5 s.
MOD_RELOAD = 15.0
SERVER_START = 10.0


@dataclass
class RelayServer:
    """Real HTTP and WebSocket server of the ExApp in mode dev."""

    port: int
    http: httpx.AsyncClient
    sockets: list[WsDatagramSocket] = field(default_factory=list[WsDatagramSocket])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _e2e_app() -> FastAPI:
    """Setup like main.py, but with a fixed mode dev and without lifespan (no Nextcloud)."""
    app = FastAPI()
    app.add_middleware(JsonOnlyChangesMiddleware)
    app.add_middleware(AppAPIAuthMiddleware, disable_for=play_disable_for("dev"))
    for router in (me.router, worlds.router, invites.router, playtime.router, pause.router):
        app.include_router(router)
    install_play(app)
    return app


@pytest.fixture
async def relay(
    app_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> AsyncIterator[RelayServer]:
    del app_env
    port = _free_port()
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    monkeypatch.setenv("GAMEWORLD_PLAY_ORIGINS", origin)
    monkeypatch.setenv("GAMEWORLD_PLAY_UDP_HOST", "127.0.0.1")
    monkeypatch.setenv("GAMEWORLD_PLAY_BASE", "")
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "password")
    monkeypatch.setattr(sessions_module, "_session_registry", None)
    caplog.set_level(logging.INFO, logger="gameworld.play")
    config = uvicorn.Config(
        _e2e_app(), host="127.0.0.1", port=port, lifespan="off", loop=_uvicorn_loop(), log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="gameworld-e2e-relay", daemon=True)
    thread.start()
    deadline = time.monotonic() + SERVER_START
    while not server.started:
        assert time.monotonic() < deadline, "uvicorn startet nicht"
        await anyio.sleep(0.05)
    try:
        async with httpx.AsyncClient(
            base_url=origin, headers={"Content-Type": "application/json"}, timeout=60.0
        ) as http:
            relay_server = RelayServer(port=port, http=http)
            yield relay_server
            for sock in relay_server.sockets:
                sock.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10.0)


async def _invite(relay: RelayServer, world_id: str, target: str) -> tuple[str, str]:
    response = await relay.http.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text
    player = next(p for p in response.json()["players"] if p["nc_user"] == target)
    return str(player["player_name"]), str(player["password"])


async def _session_free(uid: str, world_id: str) -> None:
    """Waits until the previous session of the same UID and world is torn down in the relay."""
    registry = sessions_module.get_session_registry()
    deadline = time.monotonic() + 5.0
    while (uid, world_id) in registry._active:  # pyright: ignore[reportPrivateUsage]
        assert time.monotonic() < deadline, "Sitzung wird nicht abgebaut"
        await anyio.sleep(0.05)


@dataclass(frozen=True)
class Launch:
    player_name: str
    password: str
    url: str
    address: str
    port: int


async def _launch(relay: RelayServer, uid: str, world_id: str) -> Launch:
    """The browser's path up to the WebSocket: ticket (signed), then /play/launch with origin."""
    await _session_free(uid, world_id)
    issued = await relay.http.post("/api/my/play-ticket", json={"world_id": world_id}, headers=appapi_headers(uid))
    assert issued.status_code == 200, issued.text
    ticket = str(issued.json()["ticket"])
    launched = await relay.http.post(
        "/play/launch", json={"ticket": ticket}, headers={"Origin": relay.origin, "Sec-Fetch-Site": "same-origin"}
    )
    assert launched.status_code == 200, launched.text
    body = launched.json()
    assert (body["address"], body["port"]) == VIRTUAL
    url = f"ws://127.0.0.1:{relay.port}{body['ws_path']}?t={quote(str(body['ws_ticket']), safe='')}"
    return Launch(str(body["player_name"]), str(body["password"]), url, str(body["address"]), int(body["port"]))


def _factory(relay: RelayServer, launch: Launch) -> Callable[[], DatagramSocket]:
    def make() -> DatagramSocket:
        sock = WsDatagramSocket(launch.url, relay.origin)
        relay.sockets.append(sock)
        return sock

    return make


async def _relay_join(
    relay: RelayServer, uid: str, world_id: str, name: str | None = None, password: str | None = None
) -> dict[str, object]:
    """A join via the relay; name and password from /play/launch, unless the test sets them."""
    launch = await _launch(relay, uid, world_id)
    try:
        return await anyio.to_thread.run_sync(
            partial(
                join,
                launch.address,
                launch.port,
                name or launch.player_name,
                password or launch.password,
                6.0,
                _factory(relay, launch),
            )
        )
    except TimeoutError:
        return {"result": "timeout"}


async def _relay_join_until(
    relay: RelayServer, uid: str, world_id: str, accept: Callable[[dict[str, object]], bool]
) -> dict[str, object]:
    """Repeats the join via the relay until ``accept`` fits (the mod loads rules every 5 s)."""
    deadline = time.monotonic() + MOD_RELOAD
    while True:
        result = await _relay_join(relay, uid, world_id)
        if accept(result) or time.monotonic() > deadline:
            return result
        await anyio.sleep(1.0)


def _relay_lines(caplog: pytest.LogCaptureFixture, prefix: str) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith(prefix)]


def _world_log(world_id: str) -> str:
    api = docker_api()
    try:
        [container] = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
        return container.logs().decode("utf-8", "replace")
    finally:
        api.close()


def _wait_relay_end(caplog: pytest.LogCaptureFixture, count: int) -> list[str]:
    deadline = time.monotonic() + 5.0
    while len(lines := _relay_lines(caplog, "play relay end")) < count and time.monotonic() < deadline:
        time.sleep(0.05)
    return lines


async def test_auth_accept_ueber_relais_und_falsches_passwort(
    relay: RelayServer, caplog: pytest.LogCaptureFixture
) -> None:
    world_id, port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    name, password = await _invite(relay, world_id, "gw-kind")

    # Positive control: ticket, launch (variant B delivers the own password), relay, AUTH_ACCEPT.
    launch = await _launch(relay, "gw-kind", world_id)
    assert (launch.player_name, launch.password) == (name, password)
    accepted = await _relay_join(relay, "gw-kind", world_id)
    assert accepted["result"] == "auth_accept", accepted
    sock = relay.sockets[-1]
    assert sock.sent >= 4, "Dummy, INIT, SRP A und M gingen über das Relais"
    assert sock.received >= 3, "SET_PEER_ID, HELLO, SRP B und AUTH_ACCEPT kamen über das Relais"

    # Control password: the server keeps checking itself.
    wrong = await _relay_join(relay, "gw-kind", world_id, password=WRONG_PASSWORD)
    assert wrong["result"] == "denied", wrong
    assert wrong["code"] == "WRONG_PASSWORD", wrong
    # The same case directly via UDP (without relay) gives the same answer.
    direct = join(HOST, port, name, WRONG_PASSWORD)
    assert (direct["result"], direct["code"]) == ("denied", "WRONG_PASSWORD"), direct

    # Live question (a): the empty RELIABLE(ORIGINAL) with which the 5.17 client connects
    # passes through guard and relay; the server answers with SET_PEER_ID.
    empty_launch = await _launch(relay, "gw-kind", world_id)
    peer = await anyio.to_thread.run_sync(partial(_empty_reliable_peer_id, relay, empty_launch))
    assert peer > 1, peer

    # Counter lines (open question 2, probe client): exactly one BIND per session. The
    # NEWADDR counter continues per account and world across all sessions (plan 07), so per
    # session the difference to the previous line: here 1 each.
    _wait_relay_end(caplog, 3)
    ends = _relay_lines(caplog, "play session end")
    assert ends == [f"play session end binds=1 newaddr={k}" for k in (1, 2, 3)], ends


def _empty_reliable_peer_id(relay: RelayServer, launch: Launch) -> int:
    """Sends only an empty RELIABLE(ORIGINAL) with peer_id 0 and reads SET_PEER_ID."""
    sock = WsDatagramSocket(launch.url, relay.origin)
    relay.sockets.append(sock)
    sock.settimeout(1.0)
    # Own build of the packet: head, RELIABLE (3) with seq 65500, ORIGINAL (1) without a command.
    packet = PROTO.to_bytes(4, "big") + b"\x00\x00" + b"\x00" + b"\x03" + (65500).to_bytes(2, "big") + b"\x01"
    deadline = time.monotonic() + 6.0
    try:
        while time.monotonic() < deadline:
            sock.sendto(packet, VIRTUAL)
            try:
                data, _ = sock.recvfrom(65535)
            except TimeoutError:
                continue
            body = data[7:]
            if body[:1] == b"\x03":  # RELIABLE
                body = body[3:]
            if body[:2] == b"\x00\x01":  # CONTROL SET_PEER_ID
                return int.from_bytes(body[2:4], "big")
        return 0
    finally:
        sock.close()


async def test_pause_ueber_relais_prejoin_abgelehnt(relay: RelayServer) -> None:
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    await _invite(relay, world_id, "gw-kind")
    assert (await _relay_join(relay, "gw-kind", world_id))["result"] == "auth_accept"

    started = await relay.http.post("/api/pause", json={"minutes": 15}, headers=appapi_headers())
    assert started.status_code == 200, started.text
    try:
        denied = await _relay_join_until(relay, "gw-kind", world_id, lambda r: r["result"] == "denied")
        assert denied["result"] == "denied", denied
        assert TEXT_PAUSE in str(denied["reason"]), denied
    finally:
        ended = await relay.http.post("/api/pause/end", json={}, headers=appapi_headers())
        assert ended.status_code == 200, ended.text

    # Positive control: after "Weiter" the child gets back in via the relay.
    again = await _relay_join_until(relay, "gw-kind", world_id, lambda r: r["result"] == "auth_accept")
    assert again["result"] == "auth_accept", again


async def test_spielzeit_aufgebraucht_ueber_relais_und_verwalter_frei(relay: RelayServer, app_env: Path) -> None:
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    await _invite(relay, world_id, "gw-kind")
    await _invite(relay, world_id, "admin")
    assert (await _relay_join(relay, "gw-kind", world_id))["result"] == "auth_accept"

    # Daily limit 1 min, 2 min already used today; manager snapshot as in the playtime e2e.
    plan = {"normal": [{"weekday": day, "allowed": True, "limit_minutes": 1} for day in range(1, 8)]}
    rules = await relay.http.post("/api/playtime/children/gw-kind", json=plan, headers=appapi_headers())
    assert rules.status_code == 200, rules.text
    WorldStore(app_env / "gameworld.sqlite3").add_usage("gw-kind", datetime.now(BERLIN).date(), 120)
    snapshot = await relay.http.get("/api/playtime", headers=appapi_headers())
    assert snapshot.status_code == 200, snapshot.text
    await anyio.to_thread.run_sync(worlds.get_service().tick_time)

    denied = await _relay_join_until(relay, "gw-kind", world_id, lambda r: r["result"] == "denied")
    assert denied["result"] == "denied", denied
    assert TEXT_LIMIT in str(denied["reason"]), denied

    # D-11: the manager with an own invitation gets in via the relay.
    admin = await _relay_join(relay, "admin", world_id)
    assert admin["result"] == "auth_accept", admin


async def test_fremder_name_beendet_sitzung_vor_der_welt(relay: RelayServer, caplog: pytest.LogCaptureFixture) -> None:
    world_id, port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    name, _ = await _invite(relay, world_id, "gw-kind")
    sibling, sibling_password = await _invite(relay, world_id, "gw-kind2")
    assert sibling != name

    # Ticket of the child, INIT with the name of the invited sibling.
    forged = await _relay_join(relay, "gw-kind", world_id, name=sibling, password=sibling_password)
    assert forged["result"] in {"timeout", "no_peer_id"}, forged
    sock = relay.sockets[-1]
    assert sock.closed_by_server, "Relais hätte schließen müssen"
    assert sock.close_code == 1008, sock.close_code
    lines = _wait_relay_end(caplog, 1)
    assert any(line.endswith("reason=guard_name_mismatch") for line in lines), lines
    # No join attempt with the sibling's name has reached the world.
    assert re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None

    # Positive control of the log proof: directly via UDP with a wrong password the name is in the world log.
    direct = join(HOST, port, sibling, WRONG_PASSWORD)
    assert (direct["result"], direct["code"]) == ("denied", "WRONG_PASSWORD"), direct
    deadline = time.monotonic() + 5.0
    while re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None:
        assert time.monotonic() < deadline, "Welt-Log nennt den Namen auch beim direkten Versuch nicht"
        await anyio.sleep(0.2)

    # Positive control relay: with the own name it goes on.
    own = await _relay_join(relay, "gw-kind", world_id)
    assert own["result"] == "auth_accept", own
