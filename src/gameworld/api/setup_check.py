"""Setup check API: reports a missing, too narrow or too wide Docker proxy.

Always answers with HTTP 200; the result itself says whether Gameworld is ready to start.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

import anyio.to_thread
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from gameworld.access.roles import require_verwalter
from gameworld.api.language import LangDep
from gameworld.config import load_settings
from gameworld.i18n import translate
from gameworld.provisioner.proxy_setup import proxy_commands
from gameworld.provisioner.setup_check import run_setup_check

# Every route of this router is management: second lock next to the AppAPI route ADMIN.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])


class CheckItemOut(BaseModel):
    id: str
    ok: bool
    severity: Literal["error", "warning"]
    message: str


class ProxyCommandOut(BaseModel):
    id: Literal["compose", "aio"]
    network: str
    command: str


class SetupCheckOut(BaseModel):
    ok: bool
    items: list[CheckItemOut]
    # Ready-to-copy proxy commands; language-neutral, only for a missing default proxy.
    proxy_commands: list[ProxyCommandOut] = []


@router.get("/setup-check")
async def setup_check(language: LangDep) -> SetupCheckOut:
    try:
        docker_url = load_settings().docker_url
    except ValueError as exc:
        # Invalid environment (e.g. GAMEWORLD_PORT_RANGE) as a finding instead of 500.
        message = translate(str(exc), language)
        return SetupCheckOut(ok=False, items=[CheckItemOut(id="config", ok=False, severity="error", message=message)])
    result = await anyio.to_thread.run_sync(run_setup_check, docker_url)
    items = [CheckItemOut(**{**asdict(item), "message": translate(item.message, language)}) for item in result.items]
    failed_ids = [item.id for item in result.items if not item.ok]
    commands = [ProxyCommandOut(**asdict(command)) for command in proxy_commands(failed_ids, docker_url)]
    return SetupCheckOut(ok=result.ok, items=items, proxy_commands=commands)
