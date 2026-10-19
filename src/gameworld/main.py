"""Einstieg der ExApp: FastAPI, AppAPI-Handler und Auth-Middleware."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio.to_thread
from fastapi import FastAPI
from nc_py_api import AsyncNextcloudApp, NextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers

from gameworld.api import worlds


async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp | NextcloudApp) -> str:
    """Leerer String heißt Erfolg. Das Top-Menü registriert erst Plan 01-02."""
    del enabled, nc
    return ""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    set_handlers(app, enabled_handler)
    # Baut den Dienst und migriert dabei das SQLite-Schema.
    await anyio.to_thread.run_sync(worlds.get_service)
    yield


APP = FastAPI(lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)
APP.include_router(worlds.router)


if __name__ == "__main__":
    run_app("gameworld.main:APP", log_level="info")
