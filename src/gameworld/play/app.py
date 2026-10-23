"""Einbindung des Browser-Spikes in die ExApp: Schalter-Dependency und Router-Registrierung.

Die Ausnahmen der AppAPIAuthMiddleware (``play_disable_for``) dürfen nie api/*
treffen: Die Ticket-Route ``api/my/play-ticket`` braucht die AppAPI-Identität des
Kindes, nur /play/* läuft im Modus dev ohne sie (dort prüft das Ticket).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from gameworld.play.config import allowed_origins, play_mode, security_headers


def require_play_enabled() -> None:
    """404 im Modus off; der Modus wird je Anfrage gelesen, nicht beim Import."""
    if play_mode() == "off":
        raise HTTPException(status_code=404, headers=security_headers(allowed_origins()))


def install_play(app: FastAPI) -> None:
    """Bindet die Router des Spikes ein (Plan 07 hängt seinen Router hier an).

    /api/my/play-ticket läuft immer hinter AppAPIAuthMiddleware und
    JsonOnlyChangesMiddleware (CSRF IN-08); nur /play/launch prüft im Modus dev
    Origin, Content-Type und Sec-Fetch-Site selbst (ticket_api.py).
    """
    # Später Import: pages und ticket_api brauchen require_play_enabled aus diesem Modul.
    from gameworld.play import pages, ticket_api, ws

    app.include_router(pages.router)
    app.include_router(ticket_api.api_router)
    app.include_router(ticket_api.status_router)
    app.include_router(ticket_api.play_router)
    # WebSocket-Proxy: prüft Schalter, Origin und Identität selbst vor accept.
    app.include_router(ws.router)
