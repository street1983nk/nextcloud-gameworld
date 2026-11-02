"""Setup check API: reports a missing, too narrow or too wide Docker proxy.

Always answers with HTTP 200; the result itself says whether Gameworld is ready to start.
Proxy and firewall commands are only shown to managers, Gameworld never runs them.
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
from gameworld.provisioner.network_probe import detect_docker_network
from gameworld.provisioner.proxy_setup import commands_wanted, firewall_commands, proxy_commands
from gameworld.provisioner.setup_check import run_setup_check

# Every route of this router is management: second lock next to the AppAPI route ADMIN.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])


class CheckItemOut(BaseModel):
    id: str
    ok: bool
    severity: Literal["error", "warning"]
    message: str


class ProxyCommandOut(BaseModel):
    id: Literal["detected", "compose", "aio", "other"]
    network: str
    command: str
    compose: str


class FirewallCommandOut(BaseModel):
    id: Literal["ufw", "firewalld"]
    command: str


class FirewallOut(BaseModel):
    port_range: str
    commands: list[FirewallCommandOut]


class SetupCheckOut(BaseModel):
    ok: bool
    items: list[CheckItemOut]
    # Ready-to-copy proxy commands; language-neutral, only for a missing default proxy.
    proxy_commands: list[ProxyCommandOut] = []
    # LAN-only firewall commands for the configured UDP range; shown also when ok,
    # because the host firewall cannot be checked from inside the container.
    firewall: FirewallOut | None = None


@router.get("/setup-check")
async def setup_check(language: LangDep) -> SetupCheckOut:
    try:
        settings = load_settings()
    except ValueError as exc:
        # Invalid environment (e.g. GAMEWORLD_PORT_RANGE) as a finding instead of 500.
        message = translate(str(exc), language)
        return SetupCheckOut(ok=False, items=[CheckItemOut(id="config", ok=False, severity="error", message=message)])
    docker_url = settings.docker_url
    result = await anyio.to_thread.run_sync(run_setup_check, docker_url)
    items = [CheckItemOut(**{**asdict(item), "message": translate(item.message, language)}) for item in result.items]
    failed_ids = [item.id for item in result.items if not item.ok]
    detected: str | None = None
    if commands_wanted(failed_ids, docker_url):
        # Only on the failure path: one UDP lookup at Docker's embedded DNS, 1 s timeout.
        detected = await anyio.to_thread.run_sync(detect_docker_network)
    commands = [ProxyCommandOut(**asdict(command)) for command in proxy_commands(failed_ids, docker_url, detected)]
    low, high = settings.port_range
    firewall = FirewallOut(
        port_range=f"{low}-{high}",
        commands=[FirewallCommandOut(**asdict(command)) for command in firewall_commands(settings.port_range)],
    )
    return SetupCheckOut(ok=result.ok, items=items, proxy_commands=commands, firewall=firewall)
