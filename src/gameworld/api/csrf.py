"""Protection of state-changing routes against cross-site requests (IN-08).

Proven on the dev stack (22.10.2026, Nextcloud 34.0.3, AppAPI proxy): the proxy
``/apps/app_api/proxy/gameworld/...`` is ``#[NoCSRFRequired]``; a POST with only
the session cookie, without requesttoken and with a foreign ``Origin`` reaches
the handler (``POST /api/pause/end`` as admin: 200). In the browser, today it is
mainly ``SameSite=Lax`` of the session cookie that holds off an attack from a foreign
site; a page of the same site (another host of the same domain) or an
older browser would not be covered by it.

Therefore Gameworld itself demands for every request with a user that changes something
(POST, PUT, PATCH, DELETE):

- ``Content-Type: application/json``: an HTML form cannot send that,
  ``fetch`` from a foreign page only after a CORS preflight, which the proxy
  does not answer.
- no ``Sec-Fetch-Site: cross-site`` or ``same-site``: modern browsers report
  this way that the request does not come from the Nextcloud page itself.

Requests without a user (AppAPI itself: ``/init``, ``/enabled``, Talk webhook) are
exempt; they carry no browser session.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from gameworld.access.roles import get_role_service
from gameworld.api.language import language_of
from gameworld.i18n import translate

CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
FOREIGN_FETCH_SITES = frozenset({"cross-site", "same-site"})
JSON_TYPE = "application/json"

MSG_NOT_JSON = "Gameworld nimmt Änderungen nur als JSON von der eigenen Seite an."
MSG_FOREIGN = "Gameworld nimmt Änderungen nur von der eigenen Seite an."


def _media_type(value: str) -> str:
    return value.split(";", 1)[0].strip().lower()


def refusal(scope: Scope) -> str | None:
    """Reason for the refusal or None; pure, so that the rule can be checked without a server."""
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
    """Pure ASGI middleware; must run inside AppAPIAuthMiddleware (scope["username"])."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        reason = refusal(scope)
        if reason is not None:
            # Refusal text in the account language (D-25); the language lookup never raises.
            language = await language_of(scope.get("username"), get_role_service())
            response = JSONResponse({"detail": translate(reason, language)}, status_code=403)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
