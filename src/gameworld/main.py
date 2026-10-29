"""ExApp entry point: FastAPI, AppAPI handlers and auth middleware."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import anyio.to_thread
from fastapi import FastAPI, HTTPException
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers

from gameworld.api import admin, alerts, backups, invites, me, pause, playtime, setup_check, talk, talk_bot, worlds
from gameworld.api.csrf import JsonOnlyChangesMiddleware
from gameworld.api.language import install_language_handlers
from gameworld.backup.service import get_backup_service, shutdown_backups
from gameworld.lifecycle import enabled_handler
from gameworld.notify.loop import notify_forever
from gameworld.play.app import install_play
from gameworld.play.config import play_disable_for, play_mode
from gameworld.play.log_redact import install_ws_query_redaction
from gameworld.playtime.ticker import time_forever
from gameworld.talk.service import shutdown_talk
from gameworld.worlds.reconciler import reconcile_forever

# nc_py_api types the handler as a union of sync and async client. A
# coroutine function always gets AsyncNextcloudApp though (integration_fastapi.py),
# hence the narrow type in lifecycle.py and the adaptation to the signature here.
_EnabledHandler = Callable[[bool, AsyncNextcloudApp | NextcloudApp], Awaitable[str]]

LOG = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Raise the gameworld logger to INFO and attach a handler.

    The uvicorn log_level only affects the uvicorn loggers. Without its own handler,
    reconciler actions (T-02-32) would never show up in the log, because the effective
    level is WARNING.
    """
    logger = logging.getLogger("gameworld")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)


_setup_logging()
# T-04.2-36: no WebSocket ticket from /play/ws?t=... in the uvicorn log lines.
install_ws_query_redaction()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # map_app_static=True (default) mounts js/ and img/ relative to the working directory,
    # which is why the process starts with cwd = repo root (scripts/dev/register-exapp.sh).
    set_handlers(app, cast(_EnabledHandler, enabled_handler))
    # Builds the service and migrates the SQLite schema along the way. An invalid
    # environment must not prevent the start: only a running process can
    # report the finding "config" via /api/setup-check (WR-01).
    tasks: list[asyncio.Task[None]] = []
    try:
        service = await anyio.to_thread.run_sync(worlds.get_service)
    except HTTPException:
        LOG.exception("Invalid configuration; /api/setup-check shows the finding")
    else:
        # Make jobs that ended midway in the last run visibly finished (D-11). Before
        # yield, i.e. before a request can start a new job; the busy state
        # of the world is cleared by the boot reconciliation in the task (CLEAR_BUSY).
        try:
            await anyio.to_thread.run_sync(get_backup_service(service).recover_jobs)
        except Exception as exc:
            LOG.warning("Interrupted backup jobs not finished: %s", type(exc).__name__)
        # As tasks, never synchronously: AppAPI waits for /heartbeat, and the
        # Docker proxy may not be up yet after a reboot (PLATT-02).
        # Second task: the 15 s time tick keeps the rule files current (O-03).
        tasks.append(asyncio.create_task(reconcile_forever(service)))
        tasks.append(asyncio.create_task(time_forever(service)))
        # Third task: send outbox to administrators, review, 5-minute maintenance (04.1-04).
        tasks.append(asyncio.create_task(notify_forever(service)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        # Do not orphan the Talk hooks of the parent requests (create, reconcile, delete) (IN-06).
        try:
            cancelled = await shutdown_talk()
        except Exception as exc:
            LOG.warning("Talk hooks not finished on shutdown: %s", type(exc).__name__)
        else:
            if cancelled:
                LOG.info("%d open Talk hooks cancelled on shutdown", cancelled)
        # Running backups: wait briefly, otherwise cancel (the world restarts shielded).
        try:
            cancelled = await shutdown_backups()
        except Exception as exc:
            LOG.warning("Backup jobs not finished on shutdown: %s", type(exc).__name__)
        else:
            if cancelled:
                LOG.info("%d running backup jobs cancelled on shutdown", cancelled)


APP = FastAPI(lifespan=lifespan)
# Error texts in the account language (D-25): German stays the source, en/fr are translated.
install_language_handlers(APP)
# Order matters: added first means innermost. The JSON requirement for changes
# (IN-08) thus runs after AppAPIAuthMiddleware, which sets scope["username"].
APP.add_middleware(JsonOnlyChangesMiddleware)
# Browser spike 04.2: the mode is read at start. Only dev (dev stack, PHP proxy
# without WebSocket upgrade) exempts play and play/*; api/* always stays protected.
APP.add_middleware(AppAPIAuthMiddleware, disable_for=play_disable_for(play_mode()))
APP.include_router(me.router)
APP.include_router(worlds.router)
APP.include_router(backups.router)
APP.include_router(setup_check.router)
APP.include_router(invites.router)
APP.include_router(playtime.router)
APP.include_router(pause.router)
APP.include_router(alerts.router)
APP.include_router(talk.router)
APP.include_router(admin.router)
APP.include_router(talk_bot.router)
install_play(APP)


def _uvicorn_loop() -> str:
    """Event loop for uvicorn: the selector loop on Windows, otherwise the uvicorn default.

    Concerns only the Windows dev host (manual-install, host process). With the
    proactor loop the process dies sporadically: the GC cleans up unclosed
    niquests connections also in anyio worker threads, StreamWriter.__del__
    cancels the running overlapped recv future there bypassing the loop, and
    IocpProactor._poll ends with InvalidStateError
    (.planning/debug/resolved/backend-windows-invalidstate.md). The selector loop
    knows no overlapped futures. The code does not need asyncio subprocesses, which it
    cannot do on Windows. In the Linux container it stays at "auto" (uvloop).
    """
    return "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"


if __name__ == "__main__":
    run_app("gameworld.main:APP", log_level="info", loop=_uvicorn_loop())
