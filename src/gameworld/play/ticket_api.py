"""Ticket-Weg des Browser-Spikes: Ausgabe, Schalterstatus und Spielstart (04.2-06).

D-02: Die Zugangsprüfung "eingeladen" steht vor dem ersten weitergeleiteten Paket
und nutzt dieselbe Kette wie GET /api/my/worlds (``roles.profile(uid)`` und
``access.my_worlds(profile)``); es gibt keinen neuen Zugriffspfad. D-11: Verwalter
gehen denselben Weg mit denselben Regeln wie beim Luanti-Programm, ein Ticket gibt
es also genau für die Welten, die my_worlds für sie liefert.

- POST /api/my/play-ticket: läuft immer hinter AppAPIAuthMiddleware (UID nur aus
  der Signatur) und JsonOnlyChangesMiddleware (CSRF, IN-08).
- GET /api/my/play-status: verrät nur, ob der Schalter an ist.
- POST /play/launch: im Modus dev ohne AppAPI-Identität (disable_for play/*), darum
  prüft der Handler Origin, Content-Type und Sec-Fetch-Site selbst, bevor er den
  Body liest, und danach die Einladung erneut.

Logs nennen nur feste Ereignisnamen und Grund-Konstanten, nie Ticket- oder
Passwortwerte und keine Spielernamen.
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

# Größer ist kein gültiger Body dieser Routen; gelesen wird erst nach den Herkunftsprüfungen.
MAX_BODY = 1024
# Ziel des Spiels im Browser: der Proxy (Plan 07) leitet nur dorthin weiter.
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
    """Build der Spielseite aus GAMEWORLD_PLAY_BUILD (nur a oder b, Vorgabe b), ohne Codeänderung umstellbar."""
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
    # Nur das eigene Passwort, pro Anfrage aus dem Geheimnis abgeleitet (Variante B); in Variante A None.
    password: str | None
    ws_ticket: str
    ws_path: str
    address: str
    port: int


@dataclass(frozen=True)
class PlayAccess:
    """Ergebnis der Zugangsprüfung: eigener Eintrag aus my_worlds und UDP-Port der laufenden Welt."""

    entry: MyWorld
    port: int


async def check_play_access(
    uid: str, world_id: str, roles: RoleService, access: AccessService, service: WorldService
) -> PlayAccess:
    """Eigene, eingeladene, laufende Welt oder HTTPException (403 einheitlich, 409 aus, 503 Störung)."""
    try:
        profile = await roles.profile(uid)
        mine = await access.my_worlds(profile)
    except (RoleUnavailableError, SecretUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    entry = next((item for item in mine if item.world_id == world_id), None)
    if entry is None:
        # Fremde und nicht vorhandene Welt bekommen dieselbe Antwort (keine Aufzählung).
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_NICHT_EINGELADEN)
    view = next((item for item in await service.list_worlds() if item.id == world_id), None)
    if view is None or view.status != "running":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TEXT_WELT_AUS)
    return PlayAccess(entry=entry, port=view.port)


async def _read_body[T: BaseModel](request: Request, model: type[T]) -> T:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_input=False)) from None


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def _refuse_foreign(request: Request) -> None:
    """Eigene Herkunftsprüfung für /play/launch; die Middleware greift im Modus dev nicht."""
    headers = request.headers
    if not origin_allowed(headers.get("origin"), allowed_origins()):
        LOG.info("Spielstart abgelehnt: origin")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_FREMD)
    if _media_type(headers.get("content-type", "")) != JSON_TYPE:
        LOG.info("Spielstart abgelehnt: content_type")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_FREMD)
    if headers.get("sec-fetch-site", "").strip().lower() in FOREIGN_FETCH_SITES:
        LOG.info("Spielstart abgelehnt: fetch_site")
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
    LOG.info("Spielstart vorbereitet")
    response.headers.update(NO_STORE)
    return PlayTicketOut(ticket=token, play_path=f"{play_base()}/play/?build={play_build()}")


@status_router.get("/my/play-status")
async def play_status(response: Response) -> PlayStatusOut:
    """Nur der Schalter, keine Welten und keine Konten (USER-Route ^/api/my/.*)."""
    response.headers.update(NO_STORE)
    return PlayStatusOut(enabled=play_mode() != "off")


def _launch_uid(request: Request) -> str | None:
    """Modus harp: UID aus der HaRP-Identität (Pflicht); Modus dev: keine UID-Bindung."""
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
        # Nur die Grund-Konstante, nie der Wert.
        LOG.info("Spielstart abgelehnt: %s", error.reason)
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=TEXT_TICKET) from None
    # Die Einladung kann seit der Ausgabe weg sein (T-04.2-27).
    granted = await check_play_access(ticket.uid, ticket.world_id, roles, access, service)
    if granted.entry.player_name != ticket.player_name:
        LOG.info("Spielstart abgelehnt: renamed")
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TEXT_NAME_NEU)
    ws_token = tickets.issue("ws", uid=ticket.uid, world_id=ticket.world_id, player_name=granted.entry.player_name)
    LOG.info("Spielstart freigegeben")
    response.headers.update({**NO_STORE, "Referrer-Policy": "no-referrer"})
    return LaunchOut(
        player_name=granted.entry.player_name,
        # Nur das eigene Passwort, pro Anfrage aus dem Geheimnis abgeleitet.
        password=granted.entry.password if auth_variant() == "password" else None,
        ws_ticket=ws_token,
        ws_path=f"{play_base()}/play/ws",
        address=PLAY_ADDRESS,
        port=PLAY_PORT,
    )
