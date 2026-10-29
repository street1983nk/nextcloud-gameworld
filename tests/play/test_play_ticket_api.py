"""Negative test matrix ticket and game start with positive controls (04.2-06, D-02/D-09/D-10/D-11).

Every threat from the owner list has its own test_neg_ test; next to it stands
a positive control (test_pos_ or in the same test) that shows that the
rejection is due to the checked condition and not to a broken setup.

/play/launch is checked via a purpose-built app with
``AppAPIAuthMiddleware(disable_for=play_disable_for("dev"))``: this way the
real dev path runs without AppAPI identity, and the origin checks in the handler stand
alone without the JSON middleware in front.
"""

from __future__ import annotations

import json
import logging
from base64 import b64encode
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from nc_py_api.ex_app import AppAPIAuthMiddleware

from gameworld.access import roles
from gameworld.access import service as access_service
from gameworld.access.roles import Profile
from gameworld.api.csrf import JsonOnlyChangesMiddleware
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.play import tickets
from gameworld.play.app import install_play
from gameworld.play.config import PlayMode, play_disable_for
from gameworld.play.ticket_api import MAX_BODY, TEXT_NICHT_EINGELADEN
from gameworld.play.tickets import TicketStore
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import APP_ID, APP_VERSION, FAKE_PROFILES, FakeDirectory, appapi_headers
from tests.play.test_tickets import FakeClock
from tests.test_my_worlds import W1, W2, _world
from tests.test_service_lifecycle import FakeProvisioner

pytestmark = pytest.mark.usefixtures("fixed_salt")

ORIGIN = "http://localhost:8092"
GOOD = {"Origin": ORIGIN, "Content-Type": "application/json"}
PAPA = "gw-papa"


@pytest.fixture(autouse=True)
def play_env(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del app_env
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    monkeypatch.setenv("GAMEWORLD_PLAY_ORIGINS", ORIGIN)
    for name in ("GAMEWORLD_PLAY_AUTH", "GAMEWORLD_PLAY_BASE", "GAMEWORLD_PLAY_BUILD"):
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


def _play_app(service: WorldService, mode: PlayMode) -> FastAPI:
    """Setup like main.py, but with a fixed mode; the test APP depends on the mode at first import."""
    app = FastAPI()
    app.add_middleware(JsonOnlyChangesMiddleware)
    app.add_middleware(AppAPIAuthMiddleware, disable_for=play_disable_for(mode))
    install_play(app)
    app.dependency_overrides[get_service] = lambda: service
    return app


@pytest.fixture
async def dev_client(service: WorldService) -> AsyncIterator[httpx.AsyncClient]:
    """Real dev path: auth middleware exempts play and play/*, api/* stays protected."""
    transport = httpx.ASGITransport(app=_play_app(service, "dev"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def harp_client(service: WorldService, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    """HaRP path: auth middleware on everywhere, /play/launch binds to the UID of the signature."""
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "harp")
    transport = httpx.ASGITransport(app=_play_app(service, "harp"))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake_clock = FakeClock()
    monkeypatch.setattr(tickets, "_ticket_store", TicketStore(clock=fake_clock))
    return fake_clock


@pytest.fixture
def profiles(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[str, ...]]:
    """Changeable groups of the self-report; gw-papa is a manager at first."""
    del app_env
    groups: dict[str, tuple[str, ...]] = {PAPA: ("admin",)}

    async def lookup(uid: str) -> Profile:
        display_name, default = FAKE_PROFILES.get(uid, (uid, ()))
        return Profile(user_id=uid, display_name=display_name, groups=groups.get(uid, default))

    monkeypatch.setattr(roles, "_role_service", roles.RoleService(lookup))
    return groups


async def _invite(client: httpx.AsyncClient, world_id: str, target: str, kind: str = "user") -> None:
    response = await client.post(
        f"/api/worlds/{world_id}/invites", json={"kind": kind, "target": target}, headers=appapi_headers()
    )
    assert response.status_code == 200, response.text


async def _ticket(client: httpx.AsyncClient, world_id: str = W1, user: str = "gw-kind") -> httpx.Response:
    return await client.post("/api/my/play-ticket", json={"world_id": world_id}, headers=appapi_headers(user))


async def _token(client: httpx.AsyncClient, world_id: str = W1, user: str = "gw-kind") -> str:
    response = await _ticket(client, world_id, user)
    assert response.status_code == 200, response.text
    return str(response.json()["ticket"])


async def _launch(
    http: httpx.AsyncClient, token: str, headers: dict[str, str] | None = None, body: Any = None
) -> httpx.Response:
    content = json.dumps({"ticket": token} if body is None else body)
    return await http.post("/play/launch", content=content, headers=GOOD if headers is None else headers)


async def _my_world(client: httpx.AsyncClient, user: str = "gw-kind", world_id: str = W1) -> dict[str, Any]:
    response = await client.get("/api/my/worlds", headers=appapi_headers(user))
    assert response.status_code == 200
    return next(w for w in response.json()["worlds"] if w["id"] == world_id)


# --- POST /api/my/play-ticket ---------------------------------------------------------------


async def test_pos_child_gets_ticket(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    response = await _ticket(client)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ticket", "play_path"}
    assert len(body["ticket"]) == 22
    assert body["play_path"] == "/exapps/gameworld/play/?build=b"
    assert response.headers["cache-control"] == "no-store"


async def test_pos_build_from_env(
    client: httpx.AsyncClient, service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    monkeypatch.setenv("GAMEWORLD_PLAY_BUILD", "a")
    assert (await _ticket(client)).json()["play_path"] == "/exapps/gameworld/play/?build=a"
    # Unknown build falls back to b.
    monkeypatch.setenv("GAMEWORLD_PLAY_BUILD", "../x")
    assert (await _ticket(client)).json()["play_path"] == "/exapps/gameworld/play/?build=b"


async def test_neg_kind_fremde_welt(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    await _invite(client, W2, "gw-kind2")
    denied = await _ticket(client, W1, "gw-kind2")
    assert denied.status_code == 403
    assert denied.json() == {"detail": TEXT_NICHT_EINGELADEN}
    assert "ticket" not in denied.json()
    # Positive control: the same account for the own world.
    assert (await _ticket(client, W2, "gw-kind2")).status_code == 200


async def test_neg_nicht_vorhandene_welt_gleich_wie_fremde(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W2, "gw-kind")
    foreign = await _ticket(client, W1)
    missing = await _ticket(client, "bbbbbbbbbbbb")
    assert foreign.status_code == missing.status_code == 403
    assert foreign.json() == missing.json() == {"detail": TEXT_NICHT_EINGELADEN}


async def test_neg_ex_verwalter(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    profiles: dict[str, tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manager via the group admin in W1, then removed from the group: no ticket anymore."""
    del service
    fake_directory.users[PAPA] = ("Papa", True)
    fake_directory.groups["admin"].append(PAPA)
    await _invite(client, W1, "admin", kind="group")
    # Positive control: as an active manager via my_worlds in W1.
    assert (await _ticket(client, W1, PAPA)).status_code == 200

    fake_directory.groups["admin"].remove(PAPA)
    profiles[PAPA] = ()
    # Role cache (CACHE_SECONDS) has expired: fresh service with the same self-report.
    lookup = roles.get_role_service()._lookup  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(roles, "_role_service", roles.RoleService(lookup))
    # Manager visit reconciles (throttle fresh) and removes gw-papa from W1.
    monkeypatch.setattr(access_service, "SYNC_STATE", access_service.SyncState())
    assert (await client.get("/api/worlds", headers=appapi_headers())).status_code == 200
    assert PAPA not in store.world_access(W1)

    denied = await _ticket(client, W1, PAPA)
    assert denied.status_code == 403
    assert denied.json() == {"detail": TEXT_NICHT_EINGELADEN}


async def test_neg_verwalter_ohne_einladung(client: httpx.AsyncClient, service: WorldService) -> None:
    """D-11: Even an active manager gets tickets only for worlds from my_worlds."""
    del service
    await _invite(client, W1, "gw-kind")
    assert (await _ticket(client, W1, "admin")).status_code == 403
    # Positive control: invited, then 200.
    await _invite(client, W1, "admin")
    assert (await _ticket(client, W1, "admin")).status_code == 200


async def test_neg_ohne_konto(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    response = await client.post("/api/my/play-ticket", json={"world_id": W1})
    assert response.status_code == 401
    assert "ticket" not in response.text


async def test_neg_gefaelschte_signatur(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    forged = {
        "EX-APP-ID": APP_ID,
        "EX-APP-VERSION": APP_VERSION,
        "AUTHORIZATION-APP-API": b64encode(b"gw-kind:falsches-geheimnis").decode(),
        "AA-VERSION": "32.0.0",
    }
    response = await client.post("/api/my/play-ticket", json={"world_id": W1}, headers=forged)
    assert response.status_code == 401
    # Positive control: real signature.
    assert (await _ticket(client)).status_code == 200


async def test_neg_ohne_konto_im_dev_modus(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    """In mode dev api/* stays protected: without a signature 401, with a signature 200."""
    del service
    await _invite(client, W1, "gw-kind")
    response = await dev_client.post("/api/my/play-ticket", json={"world_id": W1})
    assert response.status_code == 401
    signed = await dev_client.post("/api/my/play-ticket", json={"world_id": W1}, headers=appapi_headers("gw-kind"))
    assert signed.status_code == 200


async def test_neg_deaktiviertes_konto(
    client: httpx.AsyncClient, service: WorldService, fake_directory: FakeDirectory
) -> None:
    del service
    assert fake_directory.users["gw-aus"][1] is False
    await _invite(client, W1, "familie", kind="group")
    assert (await _ticket(client, W1, "gw-aus")).status_code == 403
    # Positive control: active member of the same group.
    assert (await _ticket(client, W1, "gw-kind")).status_code == 200


@pytest.mark.parametrize("world_id", ["AAAAAAAAAAA1", "aaaaaaaaaaa", "../aaaaaaaa", "aaaaaaaaaaa1a", "", 12])
async def test_neg_manipulierte_welt_id(client: httpx.AsyncClient, service: WorldService, world_id: object) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    response = await client.post("/api/my/play-ticket", json={"world_id": world_id}, headers=appapi_headers("gw-kind"))
    assert response.status_code == 422
    assert "ticket" not in response.json()


@pytest.mark.parametrize("extra", [{"uid": "gw-kind2"}, {"player_name": "Leo"}])
async def test_neg_zusatzfelder(client: httpx.AsyncClient, service: WorldService, extra: dict[str, str]) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    response = await client.post(
        "/api/my/play-ticket", json={"world_id": W1, **extra}, headers=appapi_headers("gw-kind")
    )
    assert response.status_code == 422


async def test_neg_welt_gestoppt(client: httpx.AsyncClient, service: WorldService, fake: FakeProvisioner) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    await _invite(client, W2, "gw-kind")
    fake.containers[W1] = (30015, "exited")
    assert (await _ticket(client, W1)).status_code == 409
    # Positive control: the running second world.
    assert (await _ticket(client, W2)).status_code == 200


async def test_neg_csrf_formular(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    headers = {**appapi_headers("gw-kind"), "Content-Type": "application/x-www-form-urlencoded"}
    response = await client.post("/api/my/play-ticket", content=f"world_id={W1}", headers=headers)
    assert response.status_code == 403


async def test_neg_csrf_cross_site(client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    for site in ("cross-site", "same-site"):
        headers = {**appapi_headers("gw-kind"), "Sec-Fetch-Site": site}
        response = await client.post("/api/my/play-ticket", json={"world_id": W1}, headers=headers)
        assert response.status_code == 403
    # Positive control: same-origin.
    headers = {**appapi_headers("gw-kind"), "Sec-Fetch-Site": "same-origin"}
    assert (await client.post("/api/my/play-ticket", json={"world_id": W1}, headers=headers)).status_code == 200


async def test_neg_schalter_aus(
    client: httpx.AsyncClient, service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "off")
    assert (await _ticket(client)).status_code == 404
    launch = await client.post("/play/launch", json={"ticket": token}, headers={**GOOD, **appapi_headers("gw-kind")})
    assert launch.status_code == 404
    status = await client.get("/api/my/play-status", headers=appapi_headers("gw-kind"))
    assert status.status_code == 200
    assert status.json() == {"enabled": False}


async def test_pos_play_status_dev(client: httpx.AsyncClient) -> None:
    status = await client.get("/api/my/play-status", headers=appapi_headers("gw-kind"))
    assert status.json() == {"enabled": True}
    assert status.headers["cache-control"] == "no-store"


# --- POST /play/launch ------------------------------------------------------------------------


async def test_pos_launch_dev(client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    mine = await _my_world(client)
    response = await _launch(dev_client, await _token(client))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["player_name"] == mine["player_name"]
    assert body["password"] == mine["password"]
    assert len(body["ws_ticket"]) == 22
    assert body["ws_path"] == "/exapps/gameworld/play/ws"
    assert (body["address"], body["port"]) == ("10.77.0.1", 30000)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_pos_launch_variante_a_ohne_passwort(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    del service
    monkeypatch.setenv("GAMEWORLD_PLAY_AUTH", "proxy_srp")
    await _invite(client, W1, "gw-kind")
    mine = await _my_world(client)
    response = await _launch(dev_client, await _token(client))
    assert response.status_code == 200
    assert response.json()["password"] is None
    assert mine["password"] not in response.text


async def test_neg_launch_wiederverwendet(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    assert (await _launch(dev_client, token)).status_code == 200
    again = await _launch(dev_client, token)
    assert again.status_code == 403
    assert "password" not in again.json()


async def test_neg_launch_abgelaufen(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService, clock: FakeClock
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    late = await _token(client)
    clock.advance(61)
    assert (await _launch(dev_client, late)).status_code == 403
    # Positive control: fresh ticket after 59 s.
    fresh = await _token(client)
    clock.advance(59)
    assert (await _launch(dev_client, fresh)).status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example", "Content-Type": "application/json"},
        {"Content-Type": "application/json"},
        {"Origin": "null", "Content-Type": "application/json"},
        {"Origin": ORIGIN, "Content-Type": "text/plain"},
        {"Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded"},
        {"Origin": ORIGIN},
        {"Origin": ORIGIN, "Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
        {"Origin": ORIGIN, "Content-Type": "application/json", "Sec-Fetch-Site": "same-site"},
    ],
    ids=[
        "fremder_origin",
        "ohne_origin",
        "origin_null",
        "text_plain",
        "formular",
        "ohne_typ",
        "cross_site",
        "same_site",
    ],
)
async def test_neg_launch_herkunft(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService, headers: dict[str, str]
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    refused = await _launch(dev_client, token, headers)
    assert refused.status_code == 403
    assert "password" not in refused.text
    # Positive control: the rejection was due to the header; the ticket was not consumed before reading.
    assert (await _launch(dev_client, token)).status_code == 200


async def test_neg_launch_ws_ticket_statt_launch(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    first = await _launch(dev_client, await _token(client))
    assert first.status_code == 200
    assert (await _launch(dev_client, first.json()["ws_ticket"])).status_code == 403


@pytest.mark.parametrize(
    "body",
    [{"ticket": ""}, {"ticket": "x" * 65}, {"ticket": 5}, {}, {"ticket": "abc", "uid": "gw-kind"}, ["abc"]],
)
async def test_neg_launch_body(dev_client: httpx.AsyncClient, service: WorldService, body: object) -> None:
    del service
    response = await _launch(dev_client, "", body=body)
    assert response.status_code == 422
    assert "x" * 65 not in response.text


async def test_neg_launch_zu_grosser_body(dev_client: httpx.AsyncClient, service: WorldService) -> None:
    del service
    response = await dev_client.post("/play/launch", content=b'{"ticket": "' + b"a" * 4000 + b'"}', headers=GOOD)
    assert response.status_code == 413


class _CountingBody:
    """Streamed body that counts how many chunks the server actually pulled."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.chunks = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.chunks += 1
            yield chunk


def _huge_body() -> _CountingBody:
    # 1000 chunks of 1024 bytes each: read completely it would be 1000 pulled chunks.
    return _CountingBody([b"a" * 1024] * 1000)


@pytest.mark.parametrize("length", [str(MAX_BODY + 1), "100000000"])
async def test_neg_launch_content_length_zu_gross(
    dev_client: httpx.AsyncClient, service: WorldService, length: str
) -> None:
    """CR-01: An oversized Content-Length is rejected before a byte of the body is read."""
    del service
    body = _CountingBody([b'{"ticket": "x"}'])
    response = await dev_client.post("/play/launch", content=body, headers={**GOOD, "Content-Length": length})
    assert response.status_code == 413
    assert body.chunks == 0


@pytest.mark.parametrize(
    "extra",
    [None, b"10", b"abc", b"\xb2"],
    # Starlette (latin-1) receives the byte 0xB2 as "²": a Unicode digit that isdigit() accepts.
    ids=["chunked", "zu_klein", "nicht_numerisch", "unicode_ziffer"],
)
async def test_neg_launch_stream_zu_gross(
    dev_client: httpx.AsyncClient, service: WorldService, extra: bytes | None
) -> None:
    """CR-01: Without a reliable Content-Length the stream aborts after a few chunks instead of buffering everything."""
    del service
    body = _huge_body()
    headers = [(name.encode(), value.encode()) for name, value in GOOD.items()]
    if extra is not None:
        headers.append((b"Content-Length", extra))
    response = await dev_client.post("/play/launch", content=body, headers=headers)
    assert response.status_code == 413
    assert body.chunks <= 3


async def test_neg_play_ticket_stream_zu_gross(client: httpx.AsyncClient, service: WorldService) -> None:
    """CR-01: The same abort applies to ticket issuing behind the AppAPI signature."""
    del service
    await _invite(client, W1, "gw-kind")
    body = _huge_body()
    headers = {**appapi_headers("gw-kind"), "Content-Type": "application/json"}
    response = await client.post("/api/my/play-ticket", content=body, headers=headers)
    assert response.status_code == 413
    assert body.chunks <= 3


def _padded(token: str, size: int) -> bytes:
    raw = json.dumps({"ticket": token}).encode()
    return b" " * (size - len(raw)) + raw


async def test_pos_launch_body_genau_max(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    """Limit inclusive: exactly MAX_BODY bytes start, one byte more does not, and the ticket then stays unconsumed."""
    del service
    await _invite(client, W1, "gw-kind")
    exact = await _token(client)
    ok = await dev_client.post("/play/launch", content=_padded(exact, MAX_BODY), headers=GOOD)
    assert ok.status_code == 200, ok.text
    kept = await _token(client)
    too_big = await dev_client.post("/play/launch", content=_padded(kept, MAX_BODY + 1), headers=GOOD)
    assert too_big.status_code == 413
    # Positive control: the abort came before redeem, the ticket is still redeemable.
    assert (await _launch(dev_client, kept)).status_code == 200


async def test_neg_launch_nach_ausladen(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    kept = await _token(client)
    revoked = await _token(client)
    # Positive control without uninviting.
    assert (await _launch(dev_client, kept)).status_code == 200
    removed = await client.post(
        f"/api/worlds/{W1}/invites/remove", json={"kind": "user", "target": "gw-kind"}, headers=appapi_headers()
    )
    assert removed.status_code == 200
    response = await _launch(dev_client, revoked)
    assert response.status_code == 403
    assert "password" not in response.text


async def test_neg_launch_nach_umbenennen(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    renamed = await client.post(
        "/api/players/name", json={"nc_user": "gw-kind", "player_name": "Mia2"}, headers=appapi_headers()
    )
    assert renamed.status_code == 200
    assert (await _launch(dev_client, token)).status_code == 409
    # Positive control: new ticket with the new name.
    response = await _launch(dev_client, await _token(client))
    assert response.status_code == 200
    assert response.json()["player_name"] == "Mia2"


async def test_neg_launch_welt_inzwischen_gestoppt(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    kept = await _token(client)
    token = await _token(client)
    # Positive control: before stopping, the start works.
    assert (await _launch(dev_client, kept)).status_code == 200
    stopped = await client.post(f"/api/worlds/{W1}/stop", headers=appapi_headers())
    assert stopped.status_code == 200, stopped.text
    response = await _launch(dev_client, token)
    assert response.status_code == 409
    assert "password" not in response.text


async def test_neg_launch_harp_fremde_uid(
    client: httpx.AsyncClient, harp_client: httpx.AsyncClient, service: WorldService
) -> None:
    """Mode harp: The ticket applies only to the account that fetched it (uid_mismatch, burnt)."""
    del service
    await _invite(client, W1, "gw-kind")
    await _invite(client, W1, "gw-kind2")
    stolen = await _token(client)
    foreign = await _launch(harp_client, stolen, {**GOOD, **appapi_headers("gw-kind2")})
    assert foreign.status_code == 403, foreign.text
    # Burnt: even the right account cannot redeem it afterwards.
    owner = await _launch(harp_client, stolen, {**GOOD, **appapi_headers("gw-kind")})
    assert owner.status_code == 403
    # Positive control: new ticket, right account.
    fresh = await _token(client)
    ok = await _launch(harp_client, fresh, {**GOOD, **appapi_headers("gw-kind")})
    assert ok.status_code == 200, ok.text


async def test_neg_launch_harp_ohne_signatur(
    client: httpx.AsyncClient, harp_client: httpx.AsyncClient, service: WorldService
) -> None:
    """Mode harp: /play/launch without a signature already fails at the middleware."""
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    assert (await _launch(harp_client, token)).status_code == 401
    # Positive control: the same ticket with the signature of the own account.
    assert (await _launch(harp_client, token, {**GOOD, **appapi_headers("gw-kind")})).status_code == 200


async def test_neg_launch_harp_ohne_identitaet(
    dev_client: httpx.AsyncClient, client: httpx.AsyncClient, service: WorldService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mode harp on an app without identity (misconfiguration): 401 instead of an unbound ticket."""
    del service
    await _invite(client, W1, "gw-kind")
    token = await _token(client)
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "harp")
    assert (await _launch(dev_client, token)).status_code == 401
    # Positive control: mode dev, the same ticket (401 came before redeeming).
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    assert (await _launch(dev_client, token)).status_code == 200


async def test_neg_launch_keine_fremden_daten(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    await _invite(client, W1, "gw-kind2")
    # Positive control: the manager sees both in the player list.
    players = (await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())).json()["players"]
    other = next(p for p in players if p["nc_user"] == "gw-kind2")
    own = next(p for p in players if p["nc_user"] == "gw-kind")
    assert other["player_name"] != own["player_name"]
    assert other["password"] != own["password"]

    response = await _launch(dev_client, await _token(client))
    assert response.status_code == 200
    assert response.json()["player_name"] == own["player_name"]
    assert other["player_name"] not in response.text
    assert other["password"] not in response.text
    assert "gw-kind2" not in response.text


async def test_neg_log_ohne_geheimnisse(
    client: httpx.AsyncClient, dev_client: httpx.AsyncClient, service: WorldService, caplog: pytest.LogCaptureFixture
) -> None:
    del service
    await _invite(client, W1, "gw-kind")
    password = (await _my_world(client))["password"]
    caplog.set_level(logging.DEBUG)
    token = await _token(client)
    response = await _launch(dev_client, token)
    assert response.status_code == 200
    ws_ticket = response.json()["ws_ticket"]
    # Rejected paths log as well.
    assert (await _launch(dev_client, token)).status_code == 403
    assert (await _launch(dev_client, ws_ticket)).status_code == 403
    # Positive control: the recording catches the events of this module.
    assert "play start granted" in caplog.text
    assert "play start refused: used_or_unknown" in caplog.text
    everything = caplog.text + " ".join(repr(record.args) for record in caplog.records)
    for secret in (token, ws_ticket, password):
        assert secret not in everything
