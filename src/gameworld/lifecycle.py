"""Lifecycle der ExApp: Top-Menü, Skript und Initial State beim Aktivieren registrieren."""

from __future__ import annotations

import logging
import os

from nc_py_api import AsyncNextcloudApp

APP_ID = "gameworld"
MENU_NAME = "gameworld"
SCRIPT_PATH = "js/gameworld-main"
CONFIG_KEY = "gameworld_config"

LOG = logging.getLogger(__name__)


def api_base() -> str:
    """Basis-URL der ExApp-API aus Sicht des Browsers.

    Unter manual-install läuft alles über den AppAPI-Proxy von Nextcloud, unter HaRP
    (erkennbar an HP_SHARED_KEY) über den Pfad /exapps/.
    """
    if os.environ.get("HP_SHARED_KEY"):
        return f"/exapps/{APP_ID}"
    return f"/index.php/apps/app_api/proxy/{APP_ID}"


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    """Leerer String heißt Erfolg, jeder andere Text wird von AppAPI als Fehler angezeigt.

    Als Coroutine-Funktion bekommt der Handler von nc_py_api immer AsyncNextcloudApp
    (Pitfall 7: keine Sync-Handler mehr).
    """
    try:
        if enabled:
            await nc.ui.resources.set_initial_state("top_menu", MENU_NAME, CONFIG_KEY, {"apiBase": api_base()})
            await nc.ui.resources.set_script("top_menu", MENU_NAME, SCRIPT_PATH)
            # Kinder brauchen die Seite (sonst 404 aus TopMenuController). Die
            # Verwaltung bleibt durch die ADMIN-Routen und require_verwalter gesperrt.
            await nc.ui.top_menu.register(MENU_NAME, "Gameworld", "img/app.svg", admin_required=False)
        else:
            await nc.ui.top_menu.unregister(MENU_NAME)
            await nc.ui.resources.delete_script("top_menu", MENU_NAME, SCRIPT_PATH)
    except Exception:
        LOG.exception("Registrierung im Nextcloud-Menü fehlgeschlagen")
        action = "aktivieren" if enabled else "deaktivieren"
        return f"Gameworld konnte das Menü nicht {action}. Details stehen im Log der ExApp."
    return ""
