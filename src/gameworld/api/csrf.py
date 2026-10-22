"""Schutz der zustandsändernden Routen gegen Cross-Site-Anfragen (IN-08).

Im Dev-Stack belegt (22.10.2026, Nextcloud 34.0.3, AppAPI-Proxy): Der Proxy
``/apps/app_api/proxy/gameworld/...`` ist ``#[NoCSRFRequired]``; ein POST nur
mit dem Sitzungs-Cookie, ohne requesttoken und mit fremdem ``Origin`` erreicht
den Handler (``POST /api/pause/end`` als admin: 200). Im Browser hält heute vor
allem ``SameSite=Lax`` des Sitzungs-Cookies einen Angriff von einer fremden
Seite ab; eine Seite derselben Site (anderer Host derselben Domain) oder ein
älterer Browser wäre davon nicht gedeckt.

Darum verlangt Gameworld selbst für jede Anfrage mit Nutzer, die etwas ändert
(POST, PUT, PATCH, DELETE):

- ``Content-Type: application/json``: Ein HTML-Formular kann das nicht senden,
  ``fetch`` von einer fremden Seite nur nach einer CORS-Vorabfrage, die der Proxy
  nicht beantwortet.
- kein ``Sec-Fetch-Site: cross-site`` oder ``same-site``: Moderne Browser melden
  so, dass die Anfrage nicht von der Nextcloud-Seite selbst kommt.

Anfragen ohne Nutzer (AppAPI selbst: ``/init``, ``/enabled``, Talk-Webhook) sind
ausgenommen; sie tragen keine Sitzung eines Browsers.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FOREIGN_FETCH_SITES = frozenset({"cross-site", "same-site"})
JSON_TYPE = "application/json"

MSG_NOT_JSON = "Gameworld nimmt Änderungen nur als JSON von der eigenen Seite an."
MSG_FOREIGN = "Gameworld nimmt Änderungen nur von der eigenen Seite an."


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def refusal(scope: Scope) -> str | None:
    """Grund für die Ablehnung oder None; rein, damit die Regel ohne Server prüfbar ist."""
    if scope.get("type") != "http" or scope.get("method", "").upper() not in CHANGING_METHODS:
        return None
    if not scope.get("username"):
        return None
    headers = Headers(scope=scope)
    if headers.get("sec-fetch-site", "").strip().lower() in FOREIGN_FETCH_SITES:
        return MSG_FOREIGN
    if _media_type(headers.get("content-type", "")) != JSON_TYPE:
        return MSG_NOT_JSON
    return None


class JsonOnlyChangesMiddleware:
    """Pure-ASGI-Middleware; muss innerhalb von AppAPIAuthMiddleware laufen (scope["username"])."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        reason = refusal(scope)
        if reason is not None:
            response = JSONResponse({"detail": reason}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
