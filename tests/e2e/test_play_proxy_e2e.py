"""Live-Beleg 04.2-08: WebSocket-Relais von Gameworld zu einer echten Luanti-5.17.0-Welt.

Erfolgskriterium 2 des Browser-Spikes: Der Browser-Weg ändert nichts an den Regeln der
Welt. Die Mods (gameworld_access, gameworld_time) entscheiden weiter im Prejoin, der
Server prüft das Passwort selbst, und ein fremder Spielername kommt nie bis zur Welt.

Aufbau wie im Dev-Weg (Plan 08): Die ExApp läuft als echter uvicorn-Server in einem
Thread, mit eigener App im Modus dev (disable_for nur play und play/*), der Ablauf ist
der des Browsers: Ticket über /api/my/play-ticket (AppAPI-signiert), /play/launch mit
Origin, dann /play/ws mit NEWADDR und BIND. Der Join selbst ist luanti_probe.join, nur
der Transport ist gegen tests/e2e/ws_datagram.py getauscht.

Nextcloud-Verzeichnis und Geheimnis sind die Fakes aus tests/conftest.py; Welt, Mods,
Relais und Join sind echt. Seriell, je Test eine MTG-kreativ-Welt.
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
# Passt nie: Das Alphabet der echten Passwörter kennt kein "0" und kein "1".
WRONG_PASSWORD = "0000-1111-0000"  # noqa: S105
VIRTUAL = ("10.77.0.1", 30000)
# Der Zeit-Mod liest die Regeldatei spätestens alle 5 s neu.
MOD_RELOAD = 15.0
SERVER_START = 10.0


@dataclass
class RelayServer:
    """Echter HTTP- und WebSocket-Server der ExApp im Modus dev."""

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
    """Aufbau wie main.py, aber mit festem Modus dev und ohne Lifespan (kein Nextcloud)."""
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
    """Wartet, bis die vorige Sitzung derselben UID und Welt im Relais abgebaut ist."""
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
    """Weg des Browsers bis vor den WebSocket: Ticket (signiert), dann /play/launch mit Origin."""
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
    """Ein Join über das Relais; Name und Passwort aus /play/launch, außer der Test setzt sie."""
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
    """Wiederholt den Join über das Relais, bis ``accept`` passt (Mod lädt Regeln alle 5 s)."""
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

    # Positivkontrolle: Ticket, Launch (Variante B liefert das eigene Passwort), Relais, AUTH_ACCEPT.
    launch = await _launch(relay, "gw-kind", world_id)
    assert (launch.player_name, launch.password) == (name, password)
    accepted = await _relay_join(relay, "gw-kind", world_id)
    assert accepted["result"] == "auth_accept", accepted
    sock = relay.sockets[-1]
    assert sock.sent >= 4, "Dummy, INIT, SRP A und M gingen über das Relais"
    assert sock.received >= 3, "SET_PEER_ID, HELLO, SRP B und AUTH_ACCEPT kamen über das Relais"

    # Gegenprobe Passwort: Der Server prüft weiter selbst.
    wrong = await _relay_join(relay, "gw-kind", world_id, password=WRONG_PASSWORD)
    assert wrong["result"] == "denied", wrong
    assert wrong["code"] == "WRONG_PASSWORD", wrong
    # Derselbe Fall direkt per UDP (ohne Relais) gibt dieselbe Antwort.
    direct = join(HOST, port, name, WRONG_PASSWORD)
    assert (direct["result"], direct["code"]) == ("denied", "WRONG_PASSWORD"), direct

    # Live-Frage (a): Das leere RELIABLE(ORIGINAL), mit dem der 5.17-Client verbindet,
    # geht durch Wächter und Relais; der Server antwortet mit SET_PEER_ID.
    empty_launch = await _launch(relay, "gw-kind", world_id)
    peer = await anyio.to_thread.run_sync(partial(_empty_reliable_peer_id, relay, empty_launch))
    assert peer > 1, peer

    # Zählerzeilen (Open Question 2, Probe-Client): je Sitzung genau ein BIND. Der
    # NEWADDR-Zähler läuft je Konto und Welt über alle Sitzungen weiter (Plan 07), je
    # Sitzung also die Differenz zur vorigen Zeile: hier jeweils 1.
    _wait_relay_end(caplog, 3)
    ends = _relay_lines(caplog, "play session end")
    assert ends == [f"play session end binds=1 newaddr={k}" for k in (1, 2, 3)], ends


def _empty_reliable_peer_id(relay: RelayServer, launch: Launch) -> int:
    """Sendet nur ein leeres RELIABLE(ORIGINAL) mit peer_id 0 und liest SET_PEER_ID."""
    sock = WsDatagramSocket(launch.url, relay.origin)
    relay.sockets.append(sock)
    sock.settimeout(1.0)
    # Eigener Bau des Pakets: Kopf, RELIABLE (3) mit Seq 65500, ORIGINAL (1) ohne Kommando.
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

    # Positivkontrolle: Nach "Weiter" kommt das Kind über das Relais wieder hinein.
    again = await _relay_join_until(relay, "gw-kind", world_id, lambda r: r["result"] == "auth_accept")
    assert again["result"] == "auth_accept", again


async def test_spielzeit_aufgebraucht_ueber_relais_und_verwalter_frei(relay: RelayServer, app_env: Path) -> None:
    world_id, _port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    await _invite(relay, world_id, "gw-kind")
    await _invite(relay, world_id, "admin")
    assert (await _relay_join(relay, "gw-kind", world_id))["result"] == "auth_accept"

    # Tageslimit 1 min, heute schon 2 min verbraucht; Verwalter-Schnappschuss wie im Spielzeit-e2e.
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

    # D-11: Der Verwalter mit eigener Einladung kommt über das Relais hinein.
    admin = await _relay_join(relay, "admin", world_id)
    assert admin["result"] == "auth_accept", admin


async def test_fremder_name_beendet_sitzung_vor_der_welt(relay: RelayServer, caplog: pytest.LogCaptureFixture) -> None:
    world_id, port = await create_running_world(relay.http, "mtg_kreativ", MTG_READY)
    name, _ = await _invite(relay, world_id, "gw-kind")
    sibling, sibling_password = await _invite(relay, world_id, "gw-kind2")
    assert sibling != name

    # Ticket des Kindes, INIT mit dem Namen des eingeladenen Geschwisters.
    forged = await _relay_join(relay, "gw-kind", world_id, name=sibling, password=sibling_password)
    assert forged["result"] in {"timeout", "no_peer_id"}, forged
    sock = relay.sockets[-1]
    assert sock.closed_by_server, "Relais hätte schließen müssen"
    assert sock.close_code == 1008, sock.close_code
    lines = _wait_relay_end(caplog, 1)
    assert any(line.endswith("reason=guard_name_mismatch") for line in lines), lines
    # Kein Join-Versuch mit dem Geschwisternamen hat die Welt erreicht.
    assert re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None

    # Positivkontrolle des Log-Belegs: direkt per UDP mit falschem Passwort steht der Name im Welt-Log.
    direct = join(HOST, port, sibling, WRONG_PASSWORD)
    assert (direct["result"], direct["code"]) == ("denied", "WRONG_PASSWORD"), direct
    deadline = time.monotonic() + 5.0
    while re.search(rf"\b{re.escape(sibling)}\b", _world_log(world_id)) is None:
        assert time.monotonic() < deadline, "Welt-Log nennt den Namen auch beim direkten Versuch nicht"
        await anyio.sleep(0.2)

    # Positivkontrolle Relais: Mit dem eigenen Namen geht es weiter.
    own = await _relay_join(relay, "gw-kind", world_id)
    assert own["result"] == "auth_accept", own
