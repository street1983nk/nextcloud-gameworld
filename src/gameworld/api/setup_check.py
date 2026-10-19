"""Setup-Check-API: meldet fehlenden, zu engen oder zu weiten Docker-Proxy.

Antwortet immer mit HTTP 200; das Ergebnis selbst sagt, ob Gameworld startklar ist.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

import anyio.to_thread
from fastapi import APIRouter
from pydantic import BaseModel

from gameworld.config import load_settings
from gameworld.provisioner.setup_check import run_setup_check

router = APIRouter(prefix="/api")


class CheckItemOut(BaseModel):
    id: str
    ok: bool
    severity: Literal["error", "warning"]
    message: str


class SetupCheckOut(BaseModel):
    ok: bool
    items: list[CheckItemOut]


@router.get("/setup-check")
async def setup_check() -> SetupCheckOut:
    try:
        docker_url = load_settings().docker_url
    except ValueError as exc:
        # Ungültige Umgebung (z. B. GAMEWORLD_PORT_RANGE) als Befund statt 500.
        return SetupCheckOut(ok=False, items=[CheckItemOut(id="config", ok=False, severity="error", message=str(exc))])
    result = await anyio.to_thread.run_sync(run_setup_check, docker_url)
    return SetupCheckOut(ok=result.ok, items=[CheckItemOut(**asdict(item)) for item in result.items])
