"""Ablauf beim Erzeugen und Auflisten von Welten.

docker-py ist synchron; jeder Docker-Aufruf läuft deshalb über
``anyio.to_thread.run_sync``. Der Weltschlüssel wird nie protokolliert.
"""

from __future__ import annotations

import logging
import secrets
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import anyio.to_thread

from gameworld.config import Settings
from gameworld.provisioner.archive import build_world_payload
from gameworld.provisioner.client import DockerProvisioner, ProvisionerError
from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.spec import LUANTI_VERSION, resource_name
from gameworld.worlds.ports import allocate_port
from gameworld.worlds.store import WorldRow, WorldStore

LOG = logging.getLogger(__name__)

# Ein Lock pro Prozess: Port-Vergabe und Einfügen dürfen nicht verschränkt laufen.
_CREATE_LOCK = threading.Lock()

UNKNOWN = "unknown"
MISSING = "missing"


@dataclass
class WorldView:
    id: str
    name: str
    port: int
    docker_status: str
    op_state: str
    desired_state: str
    last_error: str | None
    created_at: str


@dataclass
class CreatedWorld(WorldView):
    world_key: str


def _view(row: WorldRow, docker_status: str) -> WorldView:
    return WorldView(
        id=row.id,
        name=row.name,
        port=row.port,
        docker_status=docker_status,
        op_state=row.op_state,
        desired_state=row.desired_state,
        last_error=row.last_error,
        created_at=row.created_at,
    )


class WorldService:
    def __init__(self, store: WorldStore, provisioner: DockerProvisioner, settings: Settings) -> None:
        self._store = store
        self._provisioner = provisioner
        self._settings = settings

    async def create_world(self, name: str) -> CreatedWorld:
        clean = normalize_world_name(name)
        return await anyio.to_thread.run_sync(self._create_world_sync, clean)

    async def list_worlds(self) -> list[WorldView]:
        return await anyio.to_thread.run_sync(self._list_worlds_sync)

    def _create_world_sync(self, name: str) -> CreatedWorld:
        with _CREATE_LOCK:
            instance = self._store.instance_id()
            world_id = uuid.uuid4().hex[:12]
            secret = secrets.token_urlsafe(9)
            port = allocate_port(self._settings.port_range, self._store.used_ports())
            resource = resource_name(instance, world_id)
            row = WorldRow(
                id=world_id,
                name=name,
                port=port,
                container_name=resource,
                volume_name=resource,
                world_key=secret,
                engine_version=LUANTI_VERSION,
                desired_state="running",
                op_state="creating",
                last_error=None,
                created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            self._store.insert_world(row)

        container_id: str | None = None
        try:
            self._provisioner.ensure_image()
            payload = build_world_payload(render_minetest_conf(name, secret), render_world_mt())
            container_id = self._provisioner.create_world_container(world_id, port, payload)
            self._provisioner.start(container_id)
        except ProvisionerError as exc:
            if container_id is not None:
                try:
                    self._provisioner.discard(container_id, keep_volume=False)
                except ProvisionerError as cleanup:
                    LOG.warning(
                        "Aufräumen nach fehlgeschlagenem Erzeugen von Welt %s scheiterte: %s", world_id, cleanup
                    )
            self._store.update_world(world_id, op_state="failed", last_error=str(exc))
            raise

        self._store.update_world(world_id, op_state="ready")
        row.op_state = "ready"
        return CreatedWorld(**asdict(_view(row, "running")), world_key=secret)

    def _list_worlds_sync(self) -> list[WorldView]:
        rows = self._store.list_worlds()
        try:
            managed = self._provisioner.list_managed()
        except ProvisionerError as exc:
            LOG.warning("Docker-Status nicht abrufbar, zeige unknown: %s", exc)
            return [_view(row, UNKNOWN) for row in rows]
        return [_view(row, managed[row.id].status if row.id in managed else MISSING) for row in rows]
