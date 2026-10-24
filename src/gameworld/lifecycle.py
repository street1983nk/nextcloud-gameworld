"""Lifecycle der ExApp: Top-Menü, Skript und Initial State beim Aktivieren registrieren."""

from __future__ import annotations

import asyncio
import logging
import os

import anyio
from nc_py_api import AsyncNextcloudApp

from gameworld.api.worlds import get_service
from gameworld.talk import bot as talk_bot

APP_ID = "gameworld"
MENU_NAME = "gameworld"
SCRIPT_PATH = "js/gameworld-main"
CONFIG_KEY = "gameworld_config"

LOG = logging.getLogger(__name__)

# Starke Referenzen auf angestoßene Boot-Abgleiche, sonst sammelt der GC die Task ein.
_BACKGROUND: set[asyncio.Task[bool]] = set()


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
            # Verwaltung bleibt durch require_verwalter gesperrt (keine AppAPI-ADMIN-Stufe mehr).
            await nc.ui.top_menu.register(MENU_NAME, "Gameworld", "img/app.svg", admin_required=False)
        else:
            await nc.ui.top_menu.unregister(MENU_NAME)
            await nc.ui.resources.delete_script("top_menu", MENU_NAME, SCRIPT_PATH)
    except Exception:
        LOG.exception("Registrierung im Nextcloud-Menü fehlgeschlagen")
        action = "aktivieren" if enabled else "deaktivieren"
        return f"Gameworld konnte das Menü nicht {action}. Details stehen im Log der ExApp."
    # Talk-Bot in eigenem try (Pitfall 8): ohne Talk darf das Aktivieren nicht
    # scheitern, der 5-min-Abgleich holt die Registrierung nach. Ins Log nur der
    # Typname, nie eine Meldung mit möglichem Geheimnis (T-04.1-32).
    try:
        if enabled:
            await talk_bot.register(nc)
        else:
            await talk_bot.unregister(nc)
    except Exception as exc:
        LOG.warning("Talk-Bot nicht %s: %s", "registriert" if enabled else "abgemeldet", type(exc).__name__)
    # Welten in eigenem try (D-17 Option A): AppAPI unterscheidet Deaktivieren,
    # Update und Deinstallation nicht (RESEARCH F-02), darum räumt jedes
    # Deaktivieren alle eigenen Welt-Container ab; Volumes, Sicherungen und
    # Soll-Zustand bleiben. Beim Aktivieren baut der Boot-Abgleich jede
    # Soll-laufende Welt neu. Kinder werden bei einem Update kurz getrennt, das
    # ist bewusst akzeptiert. Nie ein Fehlertext an AppAPI, ins Log nur der Typname.
    try:
        if enabled:
            _schedule_boot_reconcile()
        else:
            # AppAPI wartet 60 s auf /enabled (P-07), teardown_all selbst hat 45 s Gesamtfrist.
            with anyio.fail_after(50):
                errors = await get_service().teardown()
            if errors:
                LOG.warning("Welten beim Deaktivieren nicht vollständig entfernt: %d Fehler", errors)
    except Exception as exc:
        LOG.warning("Welten nicht %s: %s", "abgeglichen" if enabled else "aufgeräumt", type(exc).__name__)
    return ""


def _schedule_boot_reconcile() -> None:
    """Stößt den Boot-Abgleich an, ohne auf ihn zu warten (Aktivieren ohne Prozessneustart).

    Nach einem Update ruft der Prozessstart ihn ohnehin; ein gleichzeitiger
    zweiter Lauf scheitert nur an der nicht blockierenden Sperre.
    """
    task = asyncio.get_running_loop().create_task(get_service().boot_reconcile())
    _BACKGROUND.add(task)
    task.add_done_callback(_boot_done)


def _boot_done(task: asyncio.Task[bool]) -> None:
    _BACKGROUND.discard(task)
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        LOG.warning("Boot-Abgleich nach dem Aktivieren gescheitert: %s", type(exc).__name__)
