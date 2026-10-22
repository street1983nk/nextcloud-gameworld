"""Einstieg der ExApp: FastAPI, AppAPI-Handler und Auth-Middleware."""

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

from gameworld.api import alerts, invites, me, pause, playtime, setup_check, talk, talk_bot, worlds
from gameworld.lifecycle import enabled_handler
from gameworld.notify.loop import notify_forever
from gameworld.playtime.ticker import time_forever
from gameworld.worlds.reconciler import reconcile_forever

# nc_py_api tippt den Handler als Union aus Sync- und Async-Client. Eine
# Coroutine-Funktion bekommt aber immer AsyncNextcloudApp (integration_fastapi.py),
# darum der enge Typ in lifecycle.py und hier die Anpassung an die Signatur.
_EnabledHandler = Callable[[bool, AsyncNextcloudApp | NextcloudApp], Awaitable[str]]

LOG = logging.getLogger(__name__)


def _setup_logging() -> None:
    """Hebt den gameworld-Logger auf INFO und haengt einen Handler an.

    uvicorns log_level betrifft nur die uvicorn-Logger. Ohne eigenen Handler
    kaemen Reconciler-Aktionen (T-02-32) nie im Log an, weil der effektive
    Level auf WARNING steht.
    """
    logger = logging.getLogger("gameworld")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)


_setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # map_app_static=True (Default) mountet js/ und img/ relativ zum Arbeitsverzeichnis,
    # deshalb startet der Prozess mit cwd = Repo-Root (scripts/dev/register-exapp.sh).
    set_handlers(app, cast(_EnabledHandler, enabled_handler))
    # Baut den Dienst und migriert dabei das SQLite-Schema. Eine ungültige
    # Umgebung darf den Start nicht verhindern: Nur ein laufender Prozess kann
    # den Befund "config" über /api/setup-check melden (WR-01).
    tasks: list[asyncio.Task[None]] = []
    try:
        service = await anyio.to_thread.run_sync(worlds.get_service)
    except HTTPException:
        LOG.exception("Ungültige Konfiguration; /api/setup-check zeigt den Befund")
    else:
        # Als Tasks, nie synchron: AppAPI wartet auf /heartbeat, und der
        # Docker-Proxy ist nach einem Reboot evtl. noch nicht oben (PLATT-02).
        # Zweiter Task: der 15-s-Zeittakt hält die Regeldateien aktuell (O-03).
        tasks.append(asyncio.create_task(reconcile_forever(service)))
        tasks.append(asyncio.create_task(time_forever(service)))
        # Dritter Task: Outbox an Verwalter senden, Rückblick, 5-min-Wartung (04.1-04).
        tasks.append(asyncio.create_task(notify_forever(service)))
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task


APP = FastAPI(lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)
APP.include_router(me.router)
APP.include_router(worlds.router)
APP.include_router(setup_check.router)
APP.include_router(invites.router)
APP.include_router(playtime.router)
APP.include_router(pause.router)
APP.include_router(alerts.router)
APP.include_router(talk.router)
APP.include_router(talk_bot.router)


def _uvicorn_loop() -> str:
    """Event-Loop für uvicorn: unter Windows der Selector-Loop, sonst uvicorns Vorgabe.

    Betrifft nur den Windows-Dev-Host (manual-install, Host-Prozess). Mit dem
    Proactor-Loop stirbt der Prozess sporadisch: Der GC räumt nicht geschlossene
    niquests-Verbindungen auch in anyio-Worker-Threads ab, StreamWriter.__del__
    cancelt dort die laufende overlapped Recv-Future am Loop vorbei, und
    IocpProactor._poll endet mit InvalidStateError
    (.planning/debug/resolved/backend-windows-invalidstate.md). Der Selector-Loop
    kennt keine overlapped Futures. asyncio-Subprozesse, die er unter Windows nicht
    kann, braucht der Code nicht. Im Linux-Container bleibt es bei "auto" (uvloop).
    """
    return "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"


if __name__ == "__main__":
    run_app("gameworld.main:APP", log_level="info", loop=_uvicorn_loop())
