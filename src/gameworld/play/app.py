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
    """Bindet die Router des Spikes ein (Plan 06/07 hängen ihre Router hier an)."""
    # Später Import: pages braucht require_play_enabled aus diesem Modul.
    from gameworld.play import pages

    app.include_router(pages.router)
