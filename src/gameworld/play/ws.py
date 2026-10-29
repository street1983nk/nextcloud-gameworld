"""WebSocket endpoint of the proxy ``/play/ws`` (04.2-07, D-01/D-02, RESEARCH pattern 2).

Check order, each stage closes with 1008 on failure without a reason containing data:

1. Switch: mode off closes before accept.
2. Origin against GAMEWORLD_PLAY_ORIGINS before accept (cross-site WebSocket hijacking).
   JsonOnlyChangesMiddleware does not apply to WebSocket (api/csrf.py), hence here.
3. Mode harp: identity from ``scope["username"]`` (AppAPIAuthMiddleware also checks
   WebSocket scopes), empty closes before accept. Mode dev: ``disable_for`` takes play/*
   out of the middleware, then the one-time ticket alone counts.
4. accept, first command as text within FIRST_COMMAND_SECONDS.
5. ``parse_command``: NEWADDR redeems the WS ticket, checks the invitation again, creates the
   session and answers with ADDR; BIND binds by passcode and starts the relay.
   Everything else closes.

The world comes only from the server-side stored ticket, never from the URL. A
UDP socket only comes into being in the relay, i.e. only after a successful BIND. Logs name only
fixed reasons, never ticket, passcode, player name or header.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from gameworld.access.roles import RolesDep, RoleService
from gameworld.access.service import AccessService
from gameworld.api.invites import AccessDep
from gameworld.api.worlds import ServiceDep
from gameworld.play.commands import Bind, NewAddr, format_addr, parse_command
from gameworld.play.config import allowed_origins, auth_variant, origin_allowed, play_mode, udp_host
from gameworld.play.relay import RelayStats, relay
from gameworld.play.sessions import SessionError, SessionRegistry, SessionRegistryDep
from gameworld.play.srp_proxy import SrpTakeover
from gameworld.play.ticket_api import check_play_access
from gameworld.play.tickets import TicketError, TicketStore, TicketStoreDep
from gameworld.worlds.service import WorldService

LOG = logging.getLogger(__name__)

FIRST_COMMAND_SECONDS = 10.0
POLICY = status.WS_1008_POLICY_VIOLATION
INTERNAL = status.WS_1011_INTERNAL_ERROR

TargetResolver = Callable[[str], Awaitable[tuple[str, int] | None]]


def get_target_resolver(service: ServiceDep) -> TargetResolver:
    """UDP destination of a running world: (udp_host, port from list_worlds); tests inject a fake world."""

    async def resolve(world_id: str) -> tuple[str, int] | None:
        view = next(
            (item for item in await service.list_worlds() if item.id == world_id and item.status == "running"),
            None,
        )
        return None if view is None else (udp_host(), view.port)

    return resolve


TargetResolverDep = Annotated[TargetResolver, Depends(get_target_resolver)]

router = APIRouter(prefix="/play")


async def _refuse(websocket: WebSocket, reason: str, code: int = POLICY) -> None:
    LOG.info("play ws refused: %s", reason)
    await websocket.close(code=code)


async def _newaddr(
    websocket: WebSocket,
    uid: str | None,
    tickets: TicketStore,
    registry: SessionRegistry,
    roles: RoleService,
    access: AccessService,
    service: WorldService,
    resolve: TargetResolver,
) -> None:
    token = websocket.query_params.get("t", "")
    try:
        ticket = tickets.redeem(token, "ws", uid=uid)
    except TicketError as error:
        await _refuse(websocket, f"ticket_{error.reason}")
        return
    # The invitation may be gone since /play/launch; the world comes only from the ticket.
    try:
        granted = await check_play_access(ticket.uid, ticket.world_id, roles, access, service)
    except HTTPException as exc:
        code = INTERNAL if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE else POLICY
        await _refuse(websocket, f"access_{exc.status_code}", code)
        return
    if granted.entry.player_name != ticket.player_name:
        await _refuse(websocket, "renamed")
        return
    target = await resolve(ticket.world_id)
    if target is None:
        await _refuse(websocket, "no_target")
        return
    try:
        session = registry.create(ticket.uid, ticket.world_id, ticket.player_name, target)
    except SessionError as error:
        await _refuse(websocket, f"session_{error.reason}")
        return
    if auth_variant() == "proxy_srp":
        # Variant A: the password comes only from check_play_access(ticket.uid), never from the client.
        session.takeover = SrpTakeover(ticket.player_name, granted.entry.password)
    await websocket.send_text(format_addr(session.passcode))
    # The client closes itself after ADDR; normal completion.
    await websocket.close()


async def _bind(websocket: WebSocket, command: Bind, uid: str | None, registry: SessionRegistry) -> None:
    try:
        session = registry.bind(command.passcode, uid=uid)
    except SessionError as error:
        LOG.info("play ws refused: bind_%s", error.reason)
        await websocket.send_text("BIND FAILED")
        await websocket.close(code=POLICY)
        return
    try:
        await websocket.send_text("BIND OK")
    except BaseException:
        registry.unbind(session.passcode)
        raise
    await relay(websocket, session, RelayStats(), registry)


@router.websocket("/ws")
async def play_ws(
    websocket: WebSocket,
    tickets: TicketStoreDep,
    registry: SessionRegistryDep,
    roles: RolesDep,
    access: AccessDep,
    service: ServiceDep,
    resolve: TargetResolverDep,
) -> None:
    mode = play_mode()
    if mode == "off":
        await websocket.close(code=POLICY)
        return
    if not origin_allowed(websocket.headers.get("origin"), allowed_origins()):
        await _refuse(websocket, "origin")
        return
    uid: str | None = None
    if mode == "harp":
        uid = websocket.scope.get("username") or ""
        if not uid:
            await _refuse(websocket, "no_identity")
            return
    await websocket.accept()
    try:
        try:
            async with asyncio.timeout(FIRST_COMMAND_SECONDS):
                message = await websocket.receive()
        except TimeoutError:
            await _refuse(websocket, "timeout")
            return
        if message["type"] == "websocket.disconnect":
            return
        text = message.get("text")
        if text is None:
            await _refuse(websocket, "binary_first")
            return
        command = parse_command(text)
        if isinstance(command, NewAddr):
            await _newaddr(websocket, uid, tickets, registry, roles, access, service, resolve)
        elif isinstance(command, Bind):
            await _bind(websocket, command, uid, registry)
        else:
            await _refuse(websocket, command.reason)
    except WebSocketDisconnect:
        return
    except Exception as exc:
        LOG.warning("play ws failed: %s", type(exc).__name__)
        with contextlib.suppress(Exception):
            await websocket.close(code=INTERNAL)
