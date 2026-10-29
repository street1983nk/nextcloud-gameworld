"""Negative test matrix WebSocket proxy /play/ws with fake UDP world and positive controls (04.2-07).

Every threat from RESEARCH "Known Threat Patterns" has a test_neg_ test; next to it
stands a positive control (test_pos_ or in the same test) that shows that the
rejection is due to the checked condition and not to a broken setup.

Control independent of the implementation: this test builds frames and MTP packets with
its own struct code after the layout of webshims (proxy.js) and tests/e2e/luanti_probe.py,
never via framing.py or mtp.py. The world is a real UDP socket on 127.0.0.1 that
records every received datagram; "does not arrive" is always checked against a packet sent
afterwards that does arrive, or against the end of the session.

WebSocket via starlette.testclient (httpx cannot do WS). The app for the modes dev and
harp is built like main.py, but with a fixed mode; invitations go through the real
main app (fixture client).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import struct
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from nc_py_api.ex_app import AppAPIAuthMiddleware
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect

from gameworld.api.csrf import JsonOnlyChangesMiddleware
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.play import relay
from gameworld.play import tickets as tickets_module
from gameworld.play.app import install_play
from gameworld.play.config import PlayMode, play_disable_for
from gameworld.play.sessions import SessionRegistry, get_session_registry
from gameworld.play.tickets import TicketStore, get_ticket_store
from gameworld.play.ws import TargetResolver, get_target_resolver
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds import service as world_service_module
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers
from tests.play.test_tickets import FakeClock
from tests.test_my_worlds import W1, W2, _world
from tests.test_service_lifecycle import FakeProvisioner

pytestmark = pytest.mark.usefixtures("fixed_salt")

ORIGIN = "http://localhost:8092"
ORIGIN_HEADERS = {"origin": ORIGIN}
WS = "/play/ws"

# Proxy head after webshims proxy.js: u32 magic | 16 byte IPv6 | u16 port | u16 length.
MAGIC = 0x778B4CF6
# MTP after luanti_probe.py: u32 protocol | u16 peer_id | u8 channel, then packet type.
PROTO = 0x4F457403
SERVER_REPLY = struct.pack(">IHB", PROTO, 1, 0) + b"\x01" + struct.pack(">H", 0x02) + b"hello-from-world"


# --- independent packet builders -------------------------------------------------------------


def _mapped(ip: str) -> bytes:
    """IPv4 as ::ffff:a.b.c.d, 16 bytes."""
    return bytes(10) + b"\xff\xff" + bytes(int(part) for part in ip.split("."))


def _frame(ip: str, port: int, payload: bytes, *, magic: int = MAGIC, length: int | None = None) -> bytes:
    size = len(payload) if length is None else length
    return struct.pack("!I", magic) + _mapped(ip) + struct.pack("!HH", port, size) + payload


def _to_world(payload: bytes) -> bytes:
    return _frame("10.77.0.1", 30000, payload)


def _str16(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


def _init(name: str) -> bytes:
    """TOSERVER_INIT 0x02 as ORIGINAL on channel 1: ser_ver 29, compression 0, protocol 37..53, name."""
    body = struct.pack(">BHHH", 29, 0, 37, 53) + _str16(name.encode())
    return struct.pack(">IHB", PROTO, 0, 1) + b"\x01" + struct.pack(">H", 0x02) + body


def _first_srp() -> bytes:
    """TOSERVER_FIRST_SRP 0x50: salt, verifier, is_empty."""
    body = _str16(b"s" * 16) + _str16(b"v" * 256) + b"\x00"
    return (
        struct.pack(">IHB", PROTO, 0, 1) + b"\x03" + struct.pack(">H", 65500) + b"\x01" + struct.pack(">H", 0x50) + body
    )


def _connect_dummy() -> bytes:
    """Empty RELIABLE(ORIGINAL) without a command, like the client on connect (peer_id assignment)."""
    return struct.pack(">IHB", PROTO, 0, 0) + b"\x03" + struct.pack(">H", 65500) + b"\x01"


def _parse_frame(frame: bytes) -> tuple[str, int, bytes]:
    magic, raw_ip, port, length = struct.unpack("!I16sHH", frame[:24])
    assert magic == MAGIC
    assert raw_ip[:12] == bytes(10) + b"\xff\xff"
    assert len(frame) == 24 + length
    return ".".join(str(b) for b in raw_ip[12:]), port, frame[24:]


# --- fake UDP world --------------------------------------------------------------------------


class FakeWorld:
    """UDP server on 127.0.0.1: records datagrams, optionally answers with SERVER_REPLY."""

    def __init__(self, *, reply: bool = True) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.05)
        self.port: int = self.sock.getsockname()[1]
        self.reply = reply
        self.received: list[bytes] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self.sock.recvfrom(65535)
            except TimeoutError:
                continue
            except ConnectionResetError:
                # Windows reports an ICMP unreachable of an earlier reply at the next recvfrom.
                continue
            except OSError:
                return
            self.received.append(data)
            if self.reply:
                self.sock.sendto(SERVER_REPLY, addr)

    def wait_for(self, count: int, timeout: float = 3.0) -> list[bytes]:
        deadline = time.monotonic() + timeout
        while len(self.received) < count and time.monotonic() < deadline:
            time.sleep(0.01)
        return list(self.received)

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self.sock.close()


# --- Fixtures --------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def play_env(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    monkeypatch.setenv("GAMEWORLD_PLAY_ORIGINS", ORIGIN)
    for name in ("GAMEWORLD_PLAY_AUTH", "GAMEWORLD_PLAY_BASE", "GAMEWORLD_PLAY_BUILD", "GAMEWORLD_PLAY_UDP_HOST"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "running")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_world(W1, "Waldwelt", 30015))
    world_store.insert_world(_world(W2, "Bergwelt", 30016))
    return world_store


@pytest.fixture
def service(store: WorldStore, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service_ = WorldService(store, cast(DockerProvisioner, fake), load_settings())
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service_)
    return world_service_


@pytest.fixture
def ticket_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def session_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tickets(ticket_clock: FakeClock) -> TicketStore:
    return TicketStore(clock=ticket_clock)


@pytest.fixture
def registry(session_clock: FakeClock) -> SessionRegistry:
    return SessionRegistry(clock=session_clock)


@pytest.fixture
def worlds() -> Iterator[dict[str, FakeWorld]]:
    created = {W1: FakeWorld(), W2: FakeWorld()}
    yield created
    for world in created.values():
        world.close()


def _resolver(worlds: dict[str, FakeWorld]) -> TargetResolver:
    async def resolve(world_id: str) -> tuple[str, int] | None:
        world = worlds.get(world_id)
        return None if world is None else ("127.0.0.1", world.port)

    return resolve


def _play_app(
    mode: PlayMode,
    service: WorldService,
    tickets: TicketStore,
    registry: SessionRegistry,
    worlds: dict[str, FakeWorld],
) -> FastAPI:
    """Setup like main.py with a fixed mode and own instances via dependency override."""
    app = FastAPI()
    app.add_middleware(JsonOnlyChangesMiddleware)
    app.add_middleware(AppAPIAuthMiddleware, disable_for=play_disable_for(mode))
    install_play(app)
    app.dependency_overrides[get_service] = lambda: service
    app.dependency_overrides[get_ticket_store] = lambda: tickets
    app.dependency_overrides[get_session_registry] = lambda: registry
    resolver = _resolver(worlds)
    app.dependency_overrides[get_target_resolver] = lambda: resolver
    return app


@pytest.fixture
def play(
    service: WorldService, tickets: TicketStore, registry: SessionRegistry, worlds: dict[str, FakeWorld]
) -> Iterator[TestClient]:
    with TestClient(_play_app("dev", service, tickets, registry, worlds)) as http:
        yield http


@pytest.fixture
def harp(
    service: WorldService,
    tickets: TicketStore,
    registry: SessionRegistry,
    worlds: dict[str, FakeWorld],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "harp")
    with TestClient(_play_app("harp", service, tickets, registry, worlds)) as http:
        yield http


@pytest.fixture
def logs(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.INFO, logger="gameworld.play")
    return caplog


# --- Helpers ---------------------------------------------------------------------------------


async def _invite(client: httpx.AsyncClient, world_id: str, target: str) -> None:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": "user", "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text


async def _player_name(client: httpx.AsyncClient, user: str = "gw-kind", world_id: str = W1) -> str:
    response = await client.get("/api/my/worlds", headers=appapi_headers(user))
    assert response.status_code == 200
    return str(next(w for w in response.json()["worlds"] if w["id"] == world_id)["player_name"])


async def _setup(client: httpx.AsyncClient, user: str = "gw-kind", world_id: str = W1) -> str:
    """Invites ``user`` into the world and returns his player name."""
    await _invite(client, world_id, user)
    return await _player_name(client, user, world_id)


def _ws_ticket(tickets: TicketStore, name: str, user: str = "gw-kind", world_id: str = W1) -> str:
    return tickets.issue("ws", uid=user, world_id=world_id, player_name=name)


def _newaddr(http: TestClient, token: str | None, headers: dict[str, str] | None = None, query: str = "") -> Message:
    """One NEWADDR connection; returns the first message of the server (ADDR or close)."""
    url = WS if token is None else f"{WS}?t={token}{query}"
    with http.websocket_connect(url, headers=ORIGIN_HEADERS if headers is None else headers) as ws:
        ws.send_text("NEWADDR")
        return ws.receive()


def _passcode(message: Message) -> str:
    assert message["type"] == "websocket.send", message
    parts = message["text"].split(" ")
    assert len(parts) == 4
    assert parts[0] == "ADDR"
    assert parts[1] == "10.77.0.2"
    assert parts[3] == "-"
    return parts[2]


def _is_policy_close(message: Message) -> bool:
    return message["type"] == "websocket.close" and message["code"] == 1008


def _closed_before_accept(http: TestClient, url: str, headers: dict[str, str]) -> int:
    with pytest.raises(WebSocketDisconnect) as excinfo, http.websocket_connect(url, headers=headers):
        pass
    return excinfo.value.code


def _bind(
    http: TestClient, stack: ExitStack, passcode: str, headers: dict[str, str] | None = None
) -> tuple[WebSocketTestSession, str]:
    ws = stack.enter_context(http.websocket_connect(WS, headers=ORIGIN_HEADERS if headers is None else headers))
    ws.send_text(f"BIND {passcode} UDP 30000")
    return ws, ws.receive_text()


def _wait_log(caplog: pytest.LogCaptureFixture, text: str, count: int = 1, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while sum(text in record.getMessage() for record in caplog.records) < count:
        assert time.monotonic() < deadline, f"Log fehlt: {text}"
        time.sleep(0.01)


def _refusals(caplog: pytest.LogCaptureFixture) -> list[str]:
    prefix = "play ws refused: "
    return [record.getMessage()[len(prefix) :] for record in caplog.records if record.getMessage().startswith(prefix)]


# --- Positive controls -----------------------------------------------------------------------


async def test_pos_end_to_end(
    client: httpx.AsyncClient, play: TestClient, worlds: dict[str, FakeWorld], logs: pytest.LogCaptureFixture
) -> None:
    """Ticket, launch, NEWADDR, BIND, INIT arrives at the world, its answer comes back wrapped."""
    name = await _setup(client)
    # Via the play app, so that its ticket store (override) knows the launch ticket.
    ticket = play.post("/api/my/play-ticket", json={"world_id": W1}, headers=appapi_headers("gw-kind"))
    assert ticket.status_code == 200
    launch = play.post(
        "/play/launch",
        json={"ticket": ticket.json()["ticket"]},
        headers={"Origin": ORIGIN, "Content-Type": "application/json"},
    )
    assert launch.status_code == 200, launch.text
    passcode = _passcode(_newaddr(play, launch.json()["ws_ticket"]))
    with ExitStack() as stack:
        ws, answer = _bind(play, stack, passcode)
        assert answer == "BIND OK"
        ws.send_bytes(_to_world(_connect_dummy()))
        ws.send_bytes(_to_world(_init(name)))
        assert worlds[W1].wait_for(2) == [_connect_dummy(), _init(name)]
        src, port, payload = _parse_frame(ws.receive_bytes())
        assert (src, port, payload) == ("10.77.0.1", 30000, SERVER_REPLY)
    _wait_log(logs, "play session end")
    assert worlds[W2].received == []
    assert "play session end binds=1 newaddr=1" in logs.text


async def test_pos_allowed_origin_variants(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = await _setup(client)
    monkeypatch.setenv("GAMEWORLD_PLAY_ORIGINS", f"https://other.example,{ORIGIN}")
    _passcode(_newaddr(play, _ws_ticket(tickets, name), {"origin": ORIGIN + "/"}))


async def test_pos_default_resolver(
    service: WorldService, fake: FakeProvisioner, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Without the 2 s list cache, so that the status change is visible immediately.
    monkeypatch.setattr(world_service_module, "LIST_CACHE_SECONDS", 0.0)
    resolve = get_target_resolver(service)
    assert await resolve(W1) == ("127.0.0.1", 30015)
    fake.containers[W1] = (30015, "exited")
    assert await resolve(W1) is None
    assert await resolve("bbbbbbbbbbbb") is None


async def test_pos_four_binds_share_session(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, worlds: dict[str, FakeWorld]
) -> None:
    """Pitfall 8: Several BINDs with the same passcode are allowed and share the guard."""
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        sockets = [_bind(play, stack, passcode) for _ in range(4)]
        assert [answer for _ws, answer in sockets] == ["BIND OK"] * 4
        sockets[0][0].send_bytes(_to_world(_init(name)))
        sockets[3][0].send_bytes(_to_world(_connect_dummy()))
        assert len(worlds[W1].wait_for(2)) == 2


# --- Origin and switch (before accept) -------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [{"origin": "https://evil.example"}, {}, {"origin": "null"}, {"origin": "http://localhost:8092.evil.example"}],
    ids=["fremd", "ohne", "null", "suffix"],
)
async def test_neg_origin_vor_accept(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, headers: dict[str, str]
) -> None:
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    assert _closed_before_accept(play, f"{WS}?t={token}", headers) == 1008
    # Positive control: the same ticket with an allowed origin (nothing was redeemed before accept).
    _passcode(_newaddr(play, token))


async def test_neg_schalter_aus(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "off")
    assert _closed_before_accept(play, f"{WS}?t={token}", ORIGIN_HEADERS) == 1008
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    _passcode(_newaddr(play, token))


# --- Tickets at NEWADDR ----------------------------------------------------------------------


@pytest.mark.parametrize("token", [None, "", "A" * 22, "x" * 65], ids=["ohne", "leer", "unbekannt", "zu_lang"])
async def test_neg_ticket_fehlt_oder_unbekannt(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, token: str | None
) -> None:
    name = await _setup(client)
    assert _is_policy_close(_newaddr(play, token))
    _passcode(_newaddr(play, _ws_ticket(tickets, name)))


async def test_neg_ticket_wiederverwendet(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, logs: pytest.LogCaptureFixture
) -> None:
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    _passcode(_newaddr(play, token))
    assert _is_policy_close(_newaddr(play, token))
    assert _refusals(logs) == ["ticket_used_or_unknown"]


async def test_neg_ticket_abgelaufen(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, ticket_clock: FakeClock
) -> None:
    name = await _setup(client)
    late = _ws_ticket(tickets, name)
    ticket_clock.advance(61)
    assert _is_policy_close(_newaddr(play, late))
    fresh = _ws_ticket(tickets, name)
    ticket_clock.advance(59)
    _passcode(_newaddr(play, fresh))


async def test_neg_launch_ticket_statt_ws(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, logs: pytest.LogCaptureFixture
) -> None:
    name = await _setup(client)
    launch = tickets.issue("launch", uid="gw-kind", world_id=W1, player_name=name)
    assert _is_policy_close(_newaddr(play, launch))
    assert _refusals(logs) == ["ticket_purpose"]
    _passcode(_newaddr(play, _ws_ticket(tickets, name)))


async def test_neg_welt_id_aus_query_ignoriert(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, worlds: dict[str, FakeWorld]
) -> None:
    """The world comes only from the ticket: world_id and w in the URL do not change the destination."""
    name = await _setup(client)
    await _invite(client, W2, "gw-kind")
    token = _ws_ticket(tickets, name, world_id=W1)
    passcode = _passcode(_newaddr(play, token, query=f"&world_id={W2}&w={W2}"))
    with ExitStack() as stack:
        ws, answer = _bind(play, stack, passcode)
        assert answer == "BIND OK"
        ws.send_bytes(_to_world(_init(name)))
        assert worlds[W1].wait_for(1) == [_init(name)]
        assert ws.receive_bytes()
    assert worlds[W2].received == []


async def test_neg_ausgeladen_nach_launch(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    session_clock: FakeClock,
    logs: pytest.LogCaptureFixture,
) -> None:
    name = await _setup(client)
    kept = _ws_ticket(tickets, name)
    revoked = _ws_ticket(tickets, name)
    # Positive control before uninviting; afterwards let the session expire (no busy).
    _passcode(_newaddr(play, kept))
    session_clock.advance(60)
    removed = await client.post(
        f"/api/worlds/{W1}/invites/remove", json={"kind": "user", "target": "gw-kind"}, headers=appapi_headers()
    )
    assert removed.status_code == 200
    assert _is_policy_close(_newaddr(play, revoked))
    assert _refusals(logs) == ["access_403"]


async def test_neg_welt_gestoppt(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    fake: FakeProvisioner,
    logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(world_service_module, "LIST_CACHE_SECONDS", 0.0)
    name = await _setup(client)
    fake.containers[W1] = (30015, "exited")
    assert _is_policy_close(_newaddr(play, _ws_ticket(tickets, name)))
    assert _refusals(logs) == ["access_409"]
    fake.containers[W1] = (30015, "running")
    _passcode(_newaddr(play, _ws_ticket(tickets, name)))


async def test_neg_umbenannt_nach_launch(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, logs: pytest.LogCaptureFixture
) -> None:
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    renamed = await client.post(
        "/api/players/name", json={"nc_user": "gw-kind", "player_name": "Mia2"}, headers=appapi_headers()
    )
    assert renamed.status_code == 200
    assert _is_policy_close(_newaddr(play, token))
    assert _refusals(logs) == ["renamed"]
    _passcode(_newaddr(play, _ws_ticket(tickets, "Mia2")))


# --- Mode harp -------------------------------------------------------------------------------


async def test_neg_harp_fremde_identitaet_newaddr(
    client: httpx.AsyncClient, harp: TestClient, tickets: TicketStore
) -> None:
    name = await _setup(client)
    await _invite(client, W1, "gw-kind2")
    stolen = _ws_ticket(tickets, name)
    foreign = {**ORIGIN_HEADERS, **appapi_headers("gw-kind2")}
    assert _is_policy_close(_newaddr(harp, stolen, foreign))
    # Positive control: fresh ticket, same identity.
    own = {**ORIGIN_HEADERS, **appapi_headers("gw-kind")}
    _passcode(_newaddr(harp, _ws_ticket(tickets, name), own))


async def test_neg_harp_fremde_identitaet_bind(
    client: httpx.AsyncClient, harp: TestClient, tickets: TicketStore
) -> None:
    name = await _setup(client)
    own = {**ORIGIN_HEADERS, **appapi_headers("gw-kind")}
    passcode = _passcode(_newaddr(harp, _ws_ticket(tickets, name), own))
    with ExitStack() as stack:
        _ws, answer = _bind(harp, stack, passcode, {**ORIGIN_HEADERS, **appapi_headers("gw-kind2")})
        assert answer == "BIND FAILED"
    with ExitStack() as stack:
        _ws, answer = _bind(harp, stack, passcode, own)
        assert answer == "BIND OK"


async def test_neg_harp_ohne_identitaet(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mode harp on an app without identity (misconfiguration): abort before accept."""
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "harp")
    assert _closed_before_accept(play, f"{WS}?t={token}", ORIGIN_HEADERS) == 1008
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    _passcode(_newaddr(play, token))


# --- BIND ------------------------------------------------------------------------------------


async def test_neg_bind_unbekannter_passcode(client: httpx.AsyncClient, play: TestClient, tickets: TicketStore) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, answer = _bind(play, stack, "A" * 22)
        assert answer == "BIND FAILED"
        assert _is_policy_close(ws.receive())
    with ExitStack() as stack:
        assert _bind(play, stack, passcode)[1] == "BIND OK"


async def test_neg_fuenfter_bind(client: httpx.AsyncClient, play: TestClient, tickets: TicketStore) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        answers = [_bind(play, stack, passcode)[1] for _ in range(5)]
    assert answers == ["BIND OK"] * 4 + ["BIND FAILED"]


@pytest.mark.parametrize(
    "command",
    ["PROXY IPV4 TCP 1.1.1.1 443", "PROXY IPV4 UDP 10.77.0.1 30000", "JOIN x", "PING", "NEWADDR ", "bind x UDP 1"],
)
async def test_neg_fremde_kommandos(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, command: str
) -> None:
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    with play.websocket_connect(f"{WS}?t={token}", headers=ORIGIN_HEADERS) as ws:
        ws.send_text(command)
        assert _is_policy_close(ws.receive())
    # Positive control: the same ticket is still valid (command was rejected before redeeming).
    _passcode(_newaddr(play, token))


async def test_neg_binaer_als_erstes(client: httpx.AsyncClient, play: TestClient, tickets: TicketStore) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with play.websocket_connect(WS, headers=ORIGIN_HEADERS) as ws:
        ws.send_bytes(_to_world(_init(name)))
        assert _is_policy_close(ws.receive())
    with ExitStack() as stack:
        assert _bind(play, stack, passcode)[1] == "BIND OK"


# --- Relay: destinations, guard, frames ------------------------------------------------------


async def test_neg_fremde_ziele_verworfen(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    worlds: dict[str, FakeWorld],
    logs: pytest.LogCaptureFixture,
) -> None:
    """No open relay: 192.168.0.1:53 and 127.0.0.1:<world port> are discarded, the session stays."""
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        ws.send_bytes(_frame("192.168.0.1", 53, b"dns-probe"))
        ws.send_bytes(_frame("127.0.0.1", worlds[W1].port, _init(name)))
        ws.send_bytes(_frame("10.77.0.1", 30001, _init(name)))
        # Positive control afterwards on the same connection.
        ws.send_bytes(_to_world(_connect_dummy()))
        assert worlds[W1].wait_for(1) == [_connect_dummy()]
        assert ws.receive_bytes()
    _wait_log(logs, "play relay end")
    assert worlds[W1].received == [_connect_dummy()]
    assert "dropped_target=3" in logs.text


async def test_neg_geschwistername(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, worlds: dict[str, FakeWorld]
) -> None:
    name = await _setup(client)
    assert name != "Leo"
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        ws.send_bytes(_to_world(_init("Leo")))
        assert _is_policy_close(ws.receive())
    await asyncio.sleep(0.2)
    assert not any(b"Leo" in datagram for datagram in worlds[W1].received)
    assert worlds[W1].received == []
    # The session is over: the passcode carries no further BIND.
    with ExitStack() as stack:
        assert _bind(play, stack, passcode)[1] == "BIND FAILED"


async def test_neg_first_srp(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, worlds: dict[str, FakeWorld]
) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        ws.send_bytes(_to_world(_init(name)))
        assert worlds[W1].wait_for(1) == [_init(name)]
        assert ws.receive_bytes()
        ws.send_bytes(_to_world(_first_srp()))
        assert _is_policy_close(ws.receive())
    await asyncio.sleep(0.2)
    assert worlds[W1].received == [_init(name)]


@pytest.mark.parametrize(
    "bad",
    [
        _frame("10.77.0.1", 30000, b"x", magic=0x778B4CF7),
        _frame("10.77.0.1", 30000, b"x" * 1501),
        _frame("10.77.0.1", 30000, b"x" * 10, length=11),
        b"\x77\x8b",
    ],
    ids=["magic", "ueber_1524", "laenge", "kurz"],
)
async def test_neg_kaputte_frames(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, worlds: dict[str, FakeWorld], bad: bytes
) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        # Positive control on the same connection before the broken frame.
        ws.send_bytes(_to_world(_connect_dummy()))
        assert worlds[W1].wait_for(1) == [_connect_dummy()]
        assert ws.receive_bytes()
        ws.send_bytes(bad)
        assert _is_policy_close(ws.receive())


async def test_neg_text_nach_bind(client: httpx.AsyncClient, play: TestClient, tickets: TicketStore) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        ws, answer = _bind(play, stack, passcode)
        assert answer == "BIND OK"
        ws.send_text("PROXY IPV4 TCP 1.1.1.1 443")
        assert _is_policy_close(ws.receive())


# --- Limits ----------------------------------------------------------------------------------


async def test_neg_zweite_sitzung_gleiche_welt(
    client: httpx.AsyncClient, play: TestClient, tickets: TicketStore, logs: pytest.LogCaptureFixture
) -> None:
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    with ExitStack() as stack:
        _bind(play, stack, passcode)
        assert _is_policy_close(_newaddr(play, _ws_ticket(tickets, name)))
        assert _refusals(logs) == ["session_busy"]
    # Positive control: after the end of the first session it works again.
    _wait_log(logs, "play session end")
    _passcode(_newaddr(play, _ws_ticket(tickets, name)))


async def test_neg_zwanzig_parallele_newaddr(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """20 simultaneous NEWADDR of one account, each with its own valid WS ticket: at most one session."""
    # The per-account ticket limit would displace older tickets; here all 20 should be valid,
    # so that the session limit alone is checked.
    monkeypatch.setattr(tickets_module, "MAX_OPEN_PER_UID", 20)
    name = await _setup(client)
    tokens = [_ws_ticket(tickets, name) for _ in range(20)]
    with ExitStack() as stack:
        sockets = [
            stack.enter_context(play.websocket_connect(f"{WS}?t={token}", headers=ORIGIN_HEADERS)) for token in tokens
        ]
        for ws in sockets:
            ws.send_text("NEWADDR")
        answers = [ws.receive() for ws in sockets]
    granted = [answer for answer in answers if answer["type"] == "websocket.send"]
    assert len(granted) == 1
    _passcode(granted[0])
    assert all(_is_policy_close(answer) for answer in answers if answer["type"] != "websocket.send")
    # Positive control of the cause: all 19 rejections due to busy, none due to the ticket.
    assert sorted(_refusals(logs)) == ["session_busy"] * 19


async def test_neg_leerlauf(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    worlds: dict[str, FakeWorld],
    logs: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relay, "IDLE_SECONDS", 0.5)
    worlds[W1].reply = False
    name = await _setup(client)
    passcode = _passcode(_newaddr(play, _ws_ticket(tickets, name)))
    started = time.monotonic()
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        ws.send_bytes(_to_world(_init(name)))
        closed = ws.receive()
    assert closed["type"] == "websocket.close"
    assert closed["code"] == 1000
    assert 0.4 <= time.monotonic() - started < 3
    assert "reason=idle" in logs.text
    # Positive control: the session is free, a new NEWADDR works.
    _passcode(_newaddr(play, _ws_ticket(tickets, name)))


def test_neg_paketrate() -> None:
    clock = FakeClock()
    bucket = relay.TokenBucket(rate=10, burst=3, clock=clock)
    assert [bucket.take() for _ in range(4)] == [True, True, True, False]
    # Positive control: after 0.1 s exactly one packet is free again.
    clock.advance(0.1)
    assert [bucket.take() for _ in range(2)] == [True, False]


async def test_neg_log_ohne_geheimnisse(
    client: httpx.AsyncClient,
    play: TestClient,
    tickets: TicketStore,
    worlds: dict[str, FakeWorld],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    name = await _setup(client)
    token = _ws_ticket(tickets, name)
    passcode = _passcode(_newaddr(play, token))
    assert _is_policy_close(_newaddr(play, token))
    with ExitStack() as stack:
        ws, _answer = _bind(play, stack, passcode)
        ws.send_bytes(_to_world(_init(name)))
        assert worlds[W1].wait_for(1)
        assert ws.receive_bytes()
    _wait_log(caplog, "play session end")
    # Positive control: the recording catches the events of the proxy.
    assert "play ws refused: ticket_used_or_unknown" in caplog.text
    assert "play relay end" in caplog.text
    everything = caplog.text + " ".join(repr(record.args) for record in caplog.records)
    for secret in (token, passcode):
        assert secret not in everything
    # Account and player name: no line of the proxy modules names them.
    proxy = [record for record in caplog.records if record.name.startswith("gameworld.play")]
    assert proxy
    proxy_text = " ".join(record.getMessage() + repr(record.args) for record in proxy)
    for personal in (name, "gw-kind"):
        assert personal not in proxy_text
