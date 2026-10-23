"""WebSocket-Endpunkt des Proxys ``/play/ws`` (04.2-07, D-01/D-02, RESEARCH Pattern 2).

Prüfreihenfolge, jede Stufe schließt bei Fehler mit 1008 ohne Begründung mit Daten:

1. Schalter: Modus off schließt vor accept.
2. Origin gegen GAMEWORLD_PLAY_ORIGINS vor accept (Cross-Site-WebSocket-Hijacking).
   JsonOnlyChangesMiddleware greift bei WebSocket nicht (api/csrf.py), darum hier.
3. Modus harp: Identität aus ``scope["username"]`` (AppAPIAuthMiddleware prüft auch
   WebSocket-Scopes), leer schließt vor accept. Modus dev: ``disable_for`` nimmt play/*
   aus der Middleware, dann trägt allein das Ein-Mal-Ticket.
4. accept, erstes Kommando als Text binnen FIRST_COMMAND_SECONDS.
5. ``parse_command``: NEWADDR löst das WS-Ticket ein, prüft die Einladung erneut, legt die
   Sitzung an und antwortet mit ADDR; BIND bindet per Passcode und startet das Relais.
   Alles andere schließt.

Die Welt kommt nur aus dem serverseitig gespeicherten Ticket, nie aus der URL. Ein
UDP-Socket entsteht erst im Relais, also nur nach erfolgreichem BIND. Logs nennen nur
feste Gründe, nie Ticket, Passcode, Spielername oder Header.
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
from gameworld.play.config import allowed_origins, origin_allowed, play_mode, udp_host
from gameworld.play.relay import RelayStats, relay
from gameworld.play.sessions import SessionError, SessionRegistry, SessionRegistryDep
from gameworld.play.ticket_api import check_play_access
from gameworld.play.tickets import TicketError, TicketStore, TicketStoreDep
from gameworld.worlds.service import WorldService

LOG = logging.getLogger(__name__)

FIRST_COMMAND_SECONDS = 10.0
POLICY = status.WS_1008_POLICY_VIOLATION
INTERNAL = status.WS_1011_INTERNAL_ERROR

TargetResolver = Callable[[str], Awaitable[tuple[str, int] | None]]


def get_target_resolver(service: ServiceDep) -> TargetResolver:
    """UDP-Ziel einer laufenden Welt: (udp_host, Port aus list_worlds); Tests setzen eine Fake-Welt ein."""

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
    # Die Einladung kann seit /play/launch weg sein; die Welt kommt nur aus dem Ticket.
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
    await websocket.send_text(format_addr(session.passcode))
    # Der Client schließt nach ADDR selbst; normaler Abschluss.
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
