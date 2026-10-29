"""Shared helpers of the phase 4 e2e tests (play time and rejoin block).

Taken over from test_access_e2e.py (unchanged there): create a running world via the
API, write access and rules file via put_archive, read the ledger,
container state and start time from Docker.
"""

from __future__ import annotations

from pathlib import Path

import docker
import httpx
from docker.models.containers import Container

from gameworld.provisioner.access_mod import render_access_file
from gameworld.provisioner.archive import build_access_tar, build_time_tar
from gameworld.provisioner.client import DockerProvisioner
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.provisioner.time_mod import Ledger, parse_ledger
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers, docker_url
from tests.e2e.test_status_e2e import wait_for_status

HOST = "127.0.0.1"
MTG_READY = 30.0
VOXELIBRE_READY = 90.0


async def create_running_world(client: httpx.AsyncClient, preset: str, ready_seconds: float) -> tuple[str, int]:
    """Create a world via the API and wait until it runs; (world_id, port)."""
    created = await client.post("/api/worlds", json={"name": "Zeitwelt", "preset": preset}, headers=appapi_headers())
    assert created.status_code == 201, created.text
    body = created.json()
    world_id = str(body["id"])
    world = await wait_for_status(client, world_id, "running", ready_seconds)
    return world_id, int(str(world["port"]))


async def delete_world(client: httpx.AsyncClient, world_id: str) -> None:
    deleted = await client.delete(f"/api/worlds/{world_id}", headers=appapi_headers())
    assert deleted.status_code == 204, deleted.text


def provisioner(app_env: Path) -> DockerProvisioner:
    return DockerProvisioner(docker_url(), WorldStore(app_env / "gameworld.sqlite3").instance_id())


def write_access(app_env: Path, world_id: str, generation: int, players: dict[str, str]) -> None:
    """Write an access file with SRP verifiers from player name -> password into the world."""
    entries = {name: make_verifier(name, password) for name, password in players.items()}
    provisioner(app_env).write_world_files(world_id, build_access_tar(render_access_file(generation, entries)))


def write_rules(app_env: Path, world_id: str, content: bytes) -> None:
    """Write the rules file of the time mod directly into the world (as the ExApp does later)."""
    provisioner(app_env).write_world_files(world_id, build_time_tar(content))


def read_ledger_raw(app_env: Path, world_id: str) -> bytes:
    ledger = provisioner(app_env).read_time_ledger(world_id)
    assert ledger is not None, "Zählbuch fehlt"
    return ledger.content


def read_ledger(app_env: Path, world_id: str) -> Ledger:
    parsed = parse_ledger(read_ledger_raw(app_env, world_id))
    assert parsed is not None, "Zählbuch unvollständig"
    return parsed


def docker_api() -> docker.DockerClient:
    return docker.DockerClient(base_url=docker_url(), version="auto", timeout=60)


def _container(api: docker.DockerClient, world_id: str) -> Container:
    matches = api.containers.list(all=True, filters={"label": [f"gameworld.world_id={world_id}"]})
    assert len(matches) == 1, matches
    container = matches[0]
    container.reload()
    return container


def started_at(api: docker.DockerClient, world_id: str) -> str:
    """StartedAt from docker inspect; changes only when the container restarts."""
    return str((_container(api, world_id).attrs.get("State") or {}).get("StartedAt") or "")


def container_status(api: docker.DockerClient, world_id: str) -> str:
    return str(_container(api, world_id).status)
