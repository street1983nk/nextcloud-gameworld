"""Ticket path of the browser spike: issuing, switch status and game start (04.2-06).

D-02: the access check "invited" comes before the first forwarded packet
and uses the same chain as GET /api/my/worlds (``roles.profile(uid)`` and
``access.my_worlds(profile)``); there is no new access path. D-11: managers
take the same path with the same rules as with the Luanti program, so a ticket exists
exactly for the worlds that my_worlds returns for them.

- POST /api/my/play-ticket: always runs behind AppAPIAuthMiddleware (UID only from
  the signature) and JsonOnlyChangesMiddleware (CSRF, IN-08).
- GET /api/my/play-status: only reveals whether the switch is on.
- POST /play/launch: in mode dev without AppAPI identity (disable_for play/*), so
  the handler checks Origin, Content-Type and Sec-Fetch-Site itself before it reads the
  body, and afterwards the invitation again.

Logs name only fixed event names and reason constants, never ticket or
password values and no player names.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from gameworld.access.roles import MSG_UNAVAILABLE, RolesDep, RoleService, RoleUnavailableError, UserDep
from gameworld.access.secret import SecretUnavailableError
from gameworld.access.service import AccessService, MyWorld
from gameworld.api.csrf import FOREIGN_FETCH_SITES, JSON_TYPE
from gameworld.api.invites import AccessDep
from gameworld.api.worlds import ServiceDep
from gameworld.play.app import require_play_enabled
from gameworld.play.config import allowed_origins, auth_variant, origin_allowed, play_base, play_mode
from gameworld.play.tickets import TOKEN_MAX, TicketError, TicketStoreDep
from gameworld.worlds.service import WorldService

LOG = logging.getLogger(__name__)

ENV_BUILD = "GAMEWORLD_PLAY_BUILD"
_BUILDS: dict[str, Literal["a", "b"]] = {"a": "a", "b": "b"}

# Larger is not a valid body of these routes. Larger bodies are aborted already at Content-Length or
# while streaming, never buffered completely (CR-01); reading happens only after the origin checks.
MAX_BODY = 1024
# Destination of the game in the browser: the proxy (plan 07) forwards only there.
PLAY_ADDRESS = "10.77.0.1"
PLAY_PORT = 30000

TEXT_NICHT_EINGELADEN = "Für diese Welt hast du keine Einladung."
TEXT_WELT_AUS = "Diese Welt läuft gerade nicht. Sag deinen Eltern Bescheid."
TEXT_TICKET = "Der Spielstart ist abgelaufen. Bitte starte das Spiel noch einmal über Gameworld."
TEXT_FREMD = "Gameworld startet das Spiel nur von der eigenen Seite."
TEXT_NAME_NEU = "Dein Spielername hat sich geändert. Bitte starte das Spiel noch einmal über Gameworld."
MSG_NOT_LOGGED_IN = "Nicht angemeldet."

NO_STORE = {"Cache-Control": "no-store"}


def play_build(environ: Mapping[str, str] = os.environ) -> Literal["a", "b"]:
    """Build of the play page from GAMEWORLD_PLAY_BUILD (only a or b, default b), switchable without a code change."""
    return _BUILDS.get(environ.get(ENV_BUILD, "b"), "b")


class PlayTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: Annotated[str, Field(pattern="^[0-9a-f]{12}$")]


class PlayTicketOut(BaseModel):
    ticket: str
    play_path: str


class PlayStatusOut(BaseModel):
    enabled: bool


class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket: Annotated[str, Field(min_length=1, max_length=TOKEN_MAX)]


class LaunchOut(BaseModel):
    player_name: str
    # Only the own password, derived per request from the secret (variant B); None in variant A.
    password: str | None
    ws_ticket: str
    ws_path: str
    address: str
    port: int


@dataclass(frozen=True)
class PlayAccess:
    """Result of the access check: own entry from my_worlds and UDP port of the running world."""

    entry: MyWorld
    port: int


async def check_play_access(
    uid: str, world_id: str, roles: RoleService, access: AccessService, service: WorldService
) -> PlayAccess:
    """Own, invited, running world or HTTPException (403 uniform, 409 off, 503 disturbance)."""
    try:
        profile = await roles.profile(uid)
        mine = await access.my_worlds(profile)
    except (RoleUnavailableError, SecretUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    entry = next((item for item in mine if item.world_id == world_id), None)
    if entry is None:
        # Foreign and non-existent worlds get the same answer (no enumeration).
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_NICHT_EINGELADEN)
    view = next((item for item in await service.list_worlds() if item.id == world_id), None)
    if view is None or view.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TEXT_WELT_AUS)
    return PlayAccess(entry=entry, port=view.port)


def _declared_too_large(value: str | None) -> bool:
    """True if a valid Content-Length already announces more than MAX_BODY.

    Only plain ASCII digits count; a missing or nonsensical value is no error,
    then the stream path alone decides. More than 9 digits are certainly too large and
    do not even go into int().
    """
    if value is None:
        return False
    value = value.strip()
    if not (value.isascii() and value.isdigit()):
        return False
    return len(value) > 9 or int(value) > MAX_BODY


async def _read_body[T: BaseModel](request: Request, model: type[T]) -> T:
    """Read the body up to MAX_BODY at most and check it as ``model`` (CR-01).

    First an oversized Content-Length is rejected without a byte read; after that
    it streams chunk by chunk and aborts immediately as soon as more than MAX_BODY bytes
    are there. So neither a wrong nor a missing Content-Length buffers the
    whole body. Both cases answer 413 without detail.
    """
    if _declared_too_large(request.headers.get("content-length")):
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_BODY:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        return model.model_validate_json(bytes(raw))
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from None


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _refuse_foreign(request: Request) -> None:
    """Own origin check for /play/launch; the middleware does not apply in mode dev."""
    headers = request.headers
    if not origin_allowed(headers.get("origin"), allowed_origins()):
        LOG.info("play start refused: origin")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_FREMD)
    if _media_type(headers.get("content-type", "")) != JSON_TYPE:
        LOG.info("play start refused: content_type")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_FREMD)
    if headers.get("sec-fetch-site", "").strip().lower() in FOREIGN_FETCH_SITES:
        LOG.info("play start refused: fetch_site")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_FREMD)


api_router = APIRouter(prefix="/api", dependencies=[Depends(require_play_enabled)])
status_router = APIRouter(prefix="/api")
play_router = APIRouter(prefix="/play", dependencies=[Depends(require_play_enabled)])


@api_router.post("/my/play-ticket")
async def play_ticket(
    request: Request,
    response: Response,
    uid: UserDep,
    roles: RolesDep,
    access: AccessDep,
    service: ServiceDep,
    tickets: TicketStoreDep,
) -> PlayTicketOut:
    body = await _read_body(request, PlayTicketRequest)
    granted = await check_play_access(uid, body.world_id, roles, access, service)
    token = tickets.issue("launch", uid=uid, world_id=body.world_id, player_name=granted.entry.player_name)
    LOG.info("play start prepared")
    response.headers.update(NO_STORE)
    return PlayTicketOut(ticket=token, play_path=f"{play_base()}/play/?build={play_build()}")


@status_router.get("/my/play-status")
async def play_status(response: Response) -> PlayStatusOut:
    """Only the switch, no worlds and no accounts (USER route ^/api/my/.*)."""
    response.headers.update(NO_STORE)
    return PlayStatusOut(enabled=play_mode() != "off")


def _launch_uid(request: Request) -> str | None:
    """Mode harp: UID from the HaRP identity (mandatory); mode dev: no UID binding."""
    if play_mode() != "harp":
        return None
    uid = request.scope.get("username") or ""
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=MSG_NOT_LOGGED_IN)
    return uid


@play_router.post("/launch")
async def launch(
    request: Request,
    response: Response,
    roles: RolesDep,
    access: AccessDep,
    service: ServiceDep,
    tickets: TicketStoreDep,
) -> LaunchOut:
    _refuse_foreign(request)
    uid = _launch_uid(request)
    body = await _read_body(request, LaunchRequest)
    try:
        ticket = tickets.redeem(body.ticket, "launch", uid=uid)
    except TicketError as error:
        # Only the reason constant, never the value.
        LOG.info("play start refused: %s", error.reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_TICKET) from None
    # The invitation may be gone since issuing (T-04.2-27).
    granted = await check_play_access(ticket.uid, ticket.world_id, roles, access, service)
    if granted.entry.player_name != ticket.player_name:
        LOG.info("play start refused: renamed")
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TEXT_NAME_NEU)
    ws_token = tickets.issue("ws", uid=ticket.uid, world_id=ticket.world_id, player_name=granted.entry.player_name)
    LOG.info("play start granted")
    response.headers.update({**NO_STORE, "Referrer-Policy": "no-referrer"})
    return LaunchOut(
        player_name=granted.entry.player_name,
        # Only the own password, derived per request from the secret.
        password=granted.entry.password if auth_variant() == "password" else None,
        ws_ticket=ws_token,
        ws_path=f"{play_base()}/play/ws",
        address=PLAY_ADDRESS,
        port=PLAY_PORT,
    )
