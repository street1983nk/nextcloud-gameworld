"""Lebenszyklus der Welten: Erzeugen, Auflisten, Starten, Stoppen, Löschen.

docker-py ist synchron; jeder Docker-Aufruf läuft deshalb über
``anyio.to_thread.run_sync``. Alle verändernden Abläufe laufen unter einem
Lock, damit Port-Vergabe und Neuerzeugung nie verschränkt laufen. Der
Weltschlüssel wird nie protokolliert.
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
from gameworld.provisioner.client import DockerProvisioner, PortInUseError, ProvisionerError, WorldNotFoundError
from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.spec import LUANTI_VERSION, resource_name
from gameworld.worlds.ports import NoFreePortError, allocate_port
from gameworld.worlds.store import WorldRow, WorldStore

LOG = logging.getLogger(__name__)

# Ein Lock pro Prozess: Port-Vergabe, Neuerzeugung und Löschen dürfen nicht verschränkt laufen.
_LOCK = threading.Lock()

# Höchstens so viele Startversuche bei belegtem Host-Port (T-01-20).
MAX_START_ATTEMPTS = 3
PORTS_EXHAUSTED = "Kein freier UDP-Port gefunden. Bitte den Portbereich GAMEWORLD_PORT_RANGE prüfen."
NOT_FOUND = "Diese Welt gibt es nicht (mehr)."

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


def _payload(row: WorldRow) -> bytes:
    return build_world_payload(render_minetest_conf(row.name, row.world_key), render_world_mt())


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

    async def start_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._start_world_sync, world_id)

    async def stop_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._stop_world_sync, world_id)

    async def delete_world(self, world_id: str) -> None:
        await anyio.to_thread.run_sync(self._delete_world_sync, world_id)

    # Hilfen

    def _row(self, world_id: str) -> WorldRow:
        row = self._store.get_world(world_id)
        if row is None:
            raise WorldNotFoundError(NOT_FOUND)
        return row

    def _used_ports(self) -> set[int]:
        """Ports aus der Datenbank und alle von Containern des Hosts gebundenen Ports."""
        low, high = self._settings.port_range
        used = self._store.used_ports()
        try:
            used |= self._provisioner.used_host_ports(low, high)
        except ProvisionerError as exc:
            # Der nächste Docker-Aufruf scheitert dann ohnehin mit einer klaren Meldung.
            LOG.warning("Gebundene Host-Ports nicht abrufbar, nur Datenbank-Ports: %s", exc)
        return used

    def _status(self, world_id: str) -> str:
        try:
            managed = self._provisioner.list_managed()
        except ProvisionerError as exc:
            LOG.warning("Docker-Status nicht abrufbar, zeige unknown: %s", exc)
            return UNKNOWN
        return managed[world_id].status if world_id in managed else MISSING

    def _launch(self, row: WorldRow) -> None:
        """Startet den Container; bei belegtem Port Neuerzeugung mit dem nächsten freien Port.

        Das Volume mit den Weltdaten bleibt dabei erhalten; nur minetest.conf,
        world.mt und das Spiel werden neu eingespielt (deterministischer Inhalt).
        Höchstens MAX_START_ATTEMPTS Startversuche insgesamt, danach NoFreePortError.
        """
        tried = {row.port}
        for attempt in range(1, MAX_START_ATTEMPTS + 1):
            try:
                self._provisioner.start_world(row.id)
                return
            except PortInUseError as exc:
                LOG.warning("Welt %s: Startversuch %d gescheitert: %s", row.id, attempt, exc)
                if attempt == MAX_START_ATTEMPTS:
                    break
            self._provisioner.remove_world(row.id, keep_volume=True)
            try:
                port = allocate_port(self._settings.port_range, self._used_ports() | tried)
            except NoFreePortError:
                break
            tried.add(port)
            self._provisioner.ensure_image()
            self._provisioner.create_world_container(row.id, port, _payload(row), reuse_volume=True)
            self._store.update_world(row.id, port=port)
            row.port = port
        raise NoFreePortError(PORTS_EXHAUSTED)

    def _fail(self, world_id: str, exc: ProvisionerError) -> None:
        self._store.update_world(world_id, op_state="failed", last_error=str(exc))

    def _current(self, world_id: str) -> WorldView:
        return _view(self._row(world_id), self._status(world_id))

    # Abläufe

    def _create_world_sync(self, name: str) -> CreatedWorld:
        with _LOCK:
            instance = self._store.instance_id()
            world_id = uuid.uuid4().hex[:12]
            secret = secrets.token_urlsafe(9)
            port = allocate_port(self._settings.port_range, self._used_ports())
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

            created = False
            try:
                self._provisioner.ensure_image()
                self._provisioner.create_world_container(world_id, port, _payload(row))
                created = True
                self._launch(row)
            except ProvisionerError as exc:
                if created:
                    try:
                        self._provisioner.remove_world(world_id, keep_volume=False)
                    except ProvisionerError as cleanup:
                        LOG.warning(
                            "Aufräumen nach fehlgeschlagenem Erzeugen von Welt %s scheiterte: %s", world_id, cleanup
                        )
                self._fail(world_id, exc)
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

    def _start_world_sync(self, world_id: str) -> WorldView:
        with _LOCK:
            row = self._row(world_id)
            self._store.update_world(world_id, desired_state="running")
            try:
                self._launch(row)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _stop_world_sync(self, world_id: str) -> WorldView:
        with _LOCK:
            self._row(world_id)
            self._store.update_world(world_id, desired_state="stopped")
            try:
                self._provisioner.stop(world_id)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _delete_world_sync(self, world_id: str) -> None:
        with _LOCK:
            self._row(world_id)
            self._store.update_world(world_id, desired_state="deleted")
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            # Erst nach erfolgreichem Aufräumen: kein Volume ohne Eintrag (T-01-21).
            self._store.delete_world(world_id)
