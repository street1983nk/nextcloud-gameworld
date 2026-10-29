"""ExApp lifecycle: register the top menu entry, script and initial state on activation."""

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

# Strong references to kicked-off boot reconciliations, otherwise the GC collects the task.
_BACKGROUND: set[asyncio.Task[bool]] = set()


def api_base() -> str:
    """Base URL of the ExApp API as seen from the browser.

    Under manual-install everything goes through the Nextcloud AppAPI proxy, under HaRP
    (recognizable by HP_SHARED_KEY) through the /exapps/ path.
    """
    if os.environ.get("HP_SHARED_KEY"):
        return f"/exapps/{APP_ID}"
    return f"/index.php/apps/app_api/proxy/{APP_ID}"


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    """An empty string means success, any other text is shown by AppAPI as an error.

    As a coroutine function, the handler always gets AsyncNextcloudApp from nc_py_api
    (pitfall 7: no more sync handlers).
    """
    try:
        if enabled:
            await nc.ui.resources.set_initial_state("top_menu", MENU_NAME, CONFIG_KEY, {"apiBase": api_base()})
            await nc.ui.resources.set_script("top_menu", MENU_NAME, SCRIPT_PATH)
            # Children need the page (otherwise 404 from TopMenuController). The
            # administration stays locked by require_verwalter (no AppAPI ADMIN level any more).
            await nc.ui.top_menu.register(MENU_NAME, "Gameworld", "img/app.svg", admin_required=False)
        else:
            await nc.ui.top_menu.unregister(MENU_NAME)
            await nc.ui.resources.delete_script("top_menu", MENU_NAME, SCRIPT_PATH)
    except Exception:
        LOG.exception("Registration in the Nextcloud menu failed")
        action = "aktivieren" if enabled else "deaktivieren"
        return f"Gameworld konnte das Menü nicht {action}. Details stehen im Log der ExApp."
    # Talk bot in its own try (pitfall 8): without Talk, activation must not
    # fail, the 5-minute reconciliation catches up on the registration. Only the
    # type name goes into the log, never a message that may contain a secret (T-04.1-32).
    try:
        if enabled:
            await talk_bot.register(nc)
        else:
            await talk_bot.unregister(nc)
    except Exception as exc:
        LOG.warning("Talk bot not %s: %s", "registered" if enabled else "unregistered", type(exc).__name__)
    # Worlds in their own try (D-17 option A): AppAPI does not distinguish deactivation,
    # update and uninstall (RESEARCH F-02), so every
    # deactivation removes all own world containers; volumes, backups and
    # desired state stay. On activation the boot reconciliation rebuilds every
    # world that should be running. Children are briefly disconnected during an update,
    # this is accepted on purpose. Never an error text to AppAPI, only the type name in the log.
    try:
        if enabled:
            _schedule_boot_reconcile()
        else:
            # AppAPI waits 60 s for /enabled (P-07), teardown_all itself has a 45 s total deadline.
            with anyio.fail_after(50):
                errors = await get_service().teardown()
            if errors:
                LOG.warning("Worlds not fully removed on deactivation: %d errors", errors)
    except Exception as exc:
        LOG.warning("Worlds not %s: %s", "reconciled" if enabled else "cleaned up", type(exc).__name__)
    return ""


def _schedule_boot_reconcile() -> None:
    """Kick off the boot reconciliation without waiting for it (activation without process restart).

    After an update the process start calls it anyway; a concurrent
    second run only fails on the non-blocking lock.
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
        LOG.warning("Boot reconciliation after activation failed: %s", type(exc).__name__)
