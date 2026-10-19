"""Lebenszyklus der Welten: Erzeugen, Auflisten, Starten, Stoppen, Löschen.

docker-py ist synchron; jeder Docker-Aufruf läuft deshalb über
``anyio.to_thread.run_sync``. Alle verändernden Abläufe laufen unter einem
Lock, damit Port-Vergabe und Neuerzeugung nie verschränkt laufen. Der
Weltschlüssel wird nie protokolliert.
"""

from __future__ import annotations

import contextlib
import logging
import secrets
import threading
import uuid
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import anyio.to_thread

from gameworld.config import Settings
from gameworld.provisioner.archive import build_world_payload
from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    PortInUseError,
    ProvisionerError,
    WorldNotFoundError,
)
from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.presets import DEFAULT_PRESET_ID, get_preset
from gameworld.provisioner.spec import LUANTI_VERSION, WorldPayload, resource_name
from gameworld.worlds.ports import NoFreePortError, allocate_port
from gameworld.worlds.status import STATUS_MOD_SCHEMA, WorldStatus, derive_status, schema_version
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
    preset: str
    preset_title: str
    # Aus Docker abgeleitet (worlds/status.py); docker_status bleibt für Phase-1-Skripte.
    status: str
    status_text: str


@dataclass
class CreatedWorld(WorldView):
    world_key: str


def _view(row: WorldRow, docker_status: str, status: WorldStatus) -> WorldView:
    return WorldView(
        id=row.id,
        name=row.name,
        port=row.port,
        docker_status=docker_status,
        op_state=row.op_state,
        desired_state=row.desired_state,
        last_error=row.last_error,
        created_at=row.created_at,
        preset=row.preset,
        preset_title=get_preset(row.preset).title,
        status=status.code,
        status_text=status.text,
    )


@contextlib.contextmanager
def _payload(row: WorldRow) -> Iterator[WorldPayload]:
    """Inhalt aus dem Preset der DB-Zeile, auch bei Neuerzeugung (Pitfall 2).

    Schließt das Tar (temporäre Datei) nach dem Einspielen, auch im Fehlerfall.
    """
    preset = get_preset(row.preset)
    payload = build_world_payload(
        preset, render_minetest_conf(row.name, row.world_key, preset), render_world_mt(preset)
    )
    try:
        yield payload
    finally:
        payload.archive.close()


class WorldService:
    def __init__(self, store: WorldStore, provisioner: DockerProvisioner, settings: Settings) -> None:
        self._store = store
        self._provisioner = provisioner
        self._settings = settings

    async def create_world(self, name: str, preset_id: str = DEFAULT_PRESET_ID) -> CreatedWorld:
        clean = normalize_world_name(name)
        # Unbekannte Presets scheitern vor Lock, Port-Vergabe und Datenbank.
        get_preset(preset_id)
        return await anyio.to_thread.run_sync(self._create_world_sync, clean, preset_id)

    async def list_worlds(self) -> list[WorldView]:
        return await anyio.to_thread.run_sync(self._list_worlds_sync)

    async def start_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._start_world_sync, world_id)

    async def stop_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._stop_world_sync, world_id)

    async def restart_world(self, world_id: str) -> WorldView:
        return await anyio.to_thread.run_sync(self._restart_world_sync, world_id)

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

    def _views(self, rows: list[WorldRow]) -> list[WorldView]:
        """Ansichten mit Status aus Docker: einmal list_managed, Status-Datei nur wo nötig.

        Einziger Codepfad für Liste und Einzelansicht. Die Datenbank liefert nur
        creating/failed und den Elternwunsch, alles andere kommt aus Docker.
        """
        try:
            managed = self._provisioner.list_managed()
        except ProvisionerError as exc:
            LOG.warning("Docker-Status nicht abrufbar, zeige unknown: %s", exc)
            return [
                _view(
                    row,
                    UNKNOWN,
                    derive_status(
                        op_state=row.op_state,
                        desired_state=row.desired_state,
                        last_error=row.last_error,
                        container=None,
                        reachable=False,
                        status_mtime=None,
                    ),
                )
                for row in rows
            ]
        return [self._view_from_docker(row, managed.get(row.id)) for row in rows]

    def _status_mtime(self, row: WorldRow, container: ContainerInfo | None) -> str | None:
        """mtime der Status-Datei, nur für laufende Welten mit Status-Mod (Schema 2)."""
        if (
            container is None
            or container.status != "running"
            or row.op_state in {"creating", "failed"}
            or schema_version(container.schema) < STATUS_MOD_SCHEMA
        ):
            return None
        try:
            status_file = self._provisioner.read_status_file(row.id)
        except ProvisionerError as exc:
            # Pro Welt isoliert: Die Welt zeigt dann "Startet gerade", die Liste bleibt.
            LOG.warning("Status-Datei von Welt %s nicht lesbar: %s", row.id, exc)
            return None
        return None if status_file is None else status_file.mtime

    def _view_from_docker(self, row: WorldRow, container: ContainerInfo | None) -> WorldView:
        status = derive_status(
            op_state=row.op_state,
            desired_state=row.desired_state,
            last_error=row.last_error,
            container=container,
            reachable=True,
            status_mtime=self._status_mtime(row, container),
        )
        return _view(row, MISSING if container is None else container.status, status)

    def _launch(self, row: WorldRow) -> None:
        """Startet den Container; bei belegtem Port Neuerzeugung mit dem nächsten freien Port.

        Das Volume mit den Weltdaten bleibt dabei erhalten; nur minetest.conf,
        world.mt und das Spiel werden neu eingespielt (deterministischer Inhalt).
        Fehlt der Container ganz (Fehlerpfad der Port-Saga oder docker rm von
        außen), wird er aus dem vorhandenen Volume neu erzeugt statt die Welt
        als verschwunden zu melden. Höchstens MAX_START_ATTEMPTS Startversuche
        bei belegtem Port, danach NoFreePortError.
        """
        tried = {row.port}
        recreated = False
        attempt = 0
        while True:
            try:
                self._provisioner.start_world(row.id)
                return
            except WorldNotFoundError:
                # Volume vorhanden, Container weg: aus dem Volume neu erzeugen.
                # Höchstens einmal pro Start; die Neuerzeugung durchläuft beim
                # nächsten Schleifendurchlauf weiter die Port-Saga.
                if recreated:
                    raise
                recreated = True
                LOG.warning("Welt %s: Container fehlt, erzeuge ihn aus dem Volume neu", row.id)
                self._provisioner.ensure_image()
                with _payload(row) as payload:
                    self._provisioner.create_world_container(row.id, row.port, payload, reuse_volume=True)
                continue
            except PortInUseError as exc:
                attempt += 1
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
            with _payload(row) as payload:
                self._provisioner.create_world_container(row.id, port, payload, reuse_volume=True)
            self._store.update_world(row.id, port=port)
            row.port = port
        raise NoFreePortError(PORTS_EXHAUSTED)

    def _fail(self, world_id: str, exc: ProvisionerError) -> None:
        self._store.update_world(world_id, op_state="failed", last_error=str(exc))

    def _discard_failed_create(self, world_id: str, exc: ProvisionerError, *, touched_docker: bool) -> None:
        """Räumt nach gescheitertem Erzeugen auf, damit keine failed-Zeile einen UDP-Port belegt.

        Ist nachweislich nichts in Docker entstanden (Fehler schon bei
        ensure_image), wird die Zeile ohne Docker-Aufruf gelöscht. Sonst wird
        aufgeräumt; gelingt das, verschwindet die Zeile ebenfalls. Nur wenn das
        Aufräumen scheitert, bleibt die Zeile als failed mit der ursprünglichen
        Meldung stehen, damit Löschen später Container und Volume entfernt.
        """
        if touched_docker:
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as cleanup:
                LOG.warning("Aufräumen nach fehlgeschlagenem Erzeugen von Welt %s scheiterte: %s", world_id, cleanup)
                self._fail(world_id, exc)
                return
        self._store.delete_world(world_id)

    def _current(self, world_id: str) -> WorldView:
        return self._views([self._row(world_id)])[0]

    # Abläufe

    def _create_world_sync(self, name: str, preset_id: str) -> CreatedWorld:
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
                preset=preset_id,
            )
            self._store.insert_world(row)

            # Ab create_world_container kann ein Volume oder Container entstanden sein.
            touched_docker = False
            try:
                self._provisioner.ensure_image()
                touched_docker = True
                with _payload(row) as payload:
                    self._provisioner.create_world_container(world_id, port, payload)
                self._launch(row)
            except ProvisionerError as exc:
                self._discard_failed_create(world_id, exc, touched_docker=touched_docker)
                raise

            self._store.update_world(world_id, op_state="ready")
            return CreatedWorld(**asdict(self._current(world_id)), world_key=secret)

    def _list_worlds_sync(self) -> list[WorldView]:
        # Ohne Lock (Pitfall 6): Statuslesen darf nie hinter einem Erzeugen warten.
        return self._views(self._store.list_worlds())

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
            except WorldNotFoundError:
                # Die DB-Zeile existiert (oben geprüft): Ein fehlender Container
                # ist bereits gestoppt, Stoppen ist dann ein No-op.
                LOG.info("Welt %s: Container fehlt, Stoppen ist ein No-op", world_id)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _restart_world_sync(self, world_id: str) -> WorldView:
        """Neustart als Stop plus _launch, nie container.restart (RESEARCH Pattern 3).

        So greifen Port-Saga und Neuerzeugung aus dem Volume wie beim Start.
        """
        with _LOCK:
            row = self._row(world_id)
            self._store.update_world(world_id, desired_state="running")
            try:
                try:
                    self._provisioner.stop(world_id)
                except WorldNotFoundError:
                    LOG.info("Welt %s: Container fehlt, Neustart erzeugt ihn neu", world_id)
                self._launch(row)
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
