"""Einstieg der ExApp: FastAPI, AppAPI-Handler und Auth-Middleware."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

import anyio.to_thread
from fastapi import FastAPI, HTTPException
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers

from gameworld.api import setup_check, worlds
from gameworld.lifecycle import enabled_handler

# nc_py_api tippt den Handler als Union aus Sync- und Async-Client. Eine
# Coroutine-Funktion bekommt aber immer AsyncNextcloudApp (integration_fastapi.py),
# darum der enge Typ in lifecycle.py und hier die Anpassung an die Signatur.
_EnabledHandler = Callable[[bool, AsyncNextcloudApp | NextcloudApp], Awaitable[str]]

LOG = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # map_app_static=True (Default) mountet js/ und img/ relativ zum Arbeitsverzeichnis,
    # deshalb startet der Prozess mit cwd = Repo-Root (scripts/dev/register-exapp.sh).
    set_handlers(app, cast(_EnabledHandler, enabled_handler))
    # Baut den Dienst und migriert dabei das SQLite-Schema. Eine ungültige
    # Umgebung darf den Start nicht verhindern: Nur ein laufender Prozess kann
    # den Befund "config" über /api/setup-check melden (WR-01).
    try:
        await anyio.to_thread.run_sync(worlds.get_service)
    except HTTPException:
        LOG.exception("Ungültige Konfiguration; /api/setup-check zeigt den Befund")
    yield


APP = FastAPI(lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)
APP.include_router(worlds.router)
APP.include_router(setup_check.router)


if __name__ == "__main__":
    run_app("gameworld.main:APP", log_level="info")
