"""Wiring the browser spike into the ExApp: switch dependency and router registration.

The exceptions of the AppAPIAuthMiddleware (``play_disable_for``) must never hit
api/*: the ticket route ``api/my/play-ticket`` needs the child's AppAPI identity,
only /play/* runs without it in mode dev (there the ticket checks).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from gameworld.play.config import allowed_origins, play_mode, security_headers


def require_play_enabled() -> None:
    """404 in mode off; the mode is read per request, not at import."""
    if play_mode() == "off":
        raise HTTPException(status_code=404, headers=security_headers(allowed_origins()))


def install_play(app: FastAPI) -> None:
    """Registers the spike's routers (plan 07 attaches its router here).

    /api/my/play-ticket always runs behind AppAPIAuthMiddleware and
    JsonOnlyChangesMiddleware (CSRF IN-08); only /play/launch checks
    Origin, Content-Type and Sec-Fetch-Site itself in mode dev (ticket_api.py).
    """
    # Late import: pages and ticket_api need require_play_enabled from this module.
    from gameworld.play import pages, ticket_api, ws

    app.include_router(pages.router)
    app.include_router(ticket_api.api_router)
    app.include_router(ticket_api.status_router)
    app.include_router(ticket_api.play_router)
    # WebSocket proxy: checks switch, origin and identity itself before accept.
    app.include_router(ws.router)
