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
import tarfile
import threading
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic

import anyio.to_thread

from gameworld.config import Settings
from gameworld.provisioner.access_mod import render_access_file
from gameworld.provisioner.archive import build_access_tar, build_world_files, build_world_payload
from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    DockerUnavailableError,
    MemoryUsage,
    PortInUseError,
    ProvisionerError,
    StatusFile,
    WorldNotFoundError,
)
from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.presets import DEFAULT_PRESET_ID, PRESETS, get_preset
from gameworld.provisioner.spec import LUANTI_VERSION, WorldPayload, resource_name
from gameworld.provisioner.status_mod import parse_players
from gameworld.worlds.ports import NoFreePortError, allocate_port
from gameworld.worlds.reconciler import ReconcileAction, decide_boot, decide_periodic, needs_volume_check
from gameworld.worlds.status import (
    ERROR,
    RUNNING,
    STATUS_MOD_SCHEMA,
    WorldStatus,
    derive_status,
    parse_docker_time,
    schema_version,
)
from gameworld.worlds.store import WorldRow, WorldStore

LOG = logging.getLogger(__name__)

# Ein Lock pro Prozess: Port-Vergabe, Neuerzeugung und Löschen dürfen nicht verschränkt laufen.
_LOCK = threading.Lock()

# Höchstens so viele Startversuche bei belegtem Host-Port (T-01-20).
MAX_START_ATTEMPTS = 3
# So lange gilt die Weltenliste als frisch: Mehrere offene Tabs (je ein Poll alle
# 5 s) vervielfachen so die Docker-Abfragen nicht (T-02-25). Jede Mutation
# verwirft den Cache, Änderungen von außen erscheinen höchstens 2 s später.
LIST_CACHE_SECONDS = 2.0
PORTS_EXHAUSTED = "Kein freier UDP-Port gefunden. Bitte den Portbereich GAMEWORLD_PORT_RANGE prüfen."
NOT_FOUND = "Diese Welt gibt es nicht (mehr)."
# Payload-Bau scheiterte am Dateisystem (VoxeLibre spoolt rund 110 MB nach /tmp) oder am Spiel-Zip (WR-01).
PAYLOAD_FAILED = (
    "Die Weltdaten konnten nicht vorbereitet werden. Bitte freien Speicherplatz auf dem Server prüfen "
    "und es erneut versuchen."
)
# Unerwarteter Fehler beim Erzeugen; Details stehen nur im Log (WR-01).
CREATE_FAILED = "Die Welt konnte nicht erstellt werden. Bitte es später erneut versuchen."
# Meldungen des Abgleichs (worlds/reconciler.py) an der Welt.
RECONCILE_OOM = "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet."
RECONCILE_DATA_MISSING = "Die Weltdaten fehlen. Die Welt kann nur gelöscht werden."
RECONCILE_INTERRUPTED = "Das Erstellen wurde unterbrochen. Bitte die Welt löschen und neu erstellen."
# Unerwarteter Fehler im Boot-Abgleich einer Welt; Details nur im Log (WR-02).
RECONCILE_FAILED = "Die Welt konnte nach dem Neustart des Servers nicht wiederhergestellt werden."
# Zeile mit einer Spielart, die diese Version nicht kennt (Preset entfernt oder umbenannt, WR-02).
UNKNOWN_PRESET_TITLE = "Unbekannte Spielart"
TEXT_UNKNOWN_PRESET = (
    "Die Spielart dieser Welt kennt Gameworld nicht. Bitte Gameworld aktualisieren oder die Welt löschen."
)
# In diesen Zuständen würde Starten eine leere Welt unter altem Namen erzeugen
# (CR-01) oder ein nur teilweise eingespieltes Spiel starten und die
# Abbruchmeldung löschen (WR-05); es bleibt nur Löschen.
DELETE_ONLY_ERRORS = frozenset({RECONCILE_DATA_MISSING, RECONCILE_INTERRUPTED})

UNKNOWN = "unknown"
MISSING = "missing"


class DeleteOnlyError(ProvisionerError):
    """Die Welt lässt sich nicht mehr starten, nur noch löschen (HTTP 409)."""


def delete_only(row: WorldRow) -> bool:
    """Darf diese Welt nur noch gelöscht werden? Steht fest an der Zeile, nicht im Text der Oberfläche."""
    return row.op_state == "failed" and row.last_error in DELETE_ONLY_ERRORS


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
    # WELT-03: Spieler nur bei status running, RAM nur bei laufendem Container.
    players: list[str]
    memory_used_bytes: int | None
    memory_limit_bytes: int | None
    # Weltdaten fehlen oder Erstellen brach ab: Die Oberfläche bietet nur Löschen an, Starten gibt 409.
    delete_only: bool
    # Spielernamen aller Eingeladenen (aus der Datenbank, nie Passwörter oder Verifier).
    invited_players: list[str]
    # Läuft die Welt ohne geladenen Zugangsschutz (vor dem Update gestartet)? Nur bei status running.
    access_restart_needed: bool


def _view(
    row: WorldRow,
    docker_status: str,
    status: WorldStatus,
    players: list[str] | None = None,
    memory: MemoryUsage | None = None,
    *,
    invited_players: list[str],
    access_restart_needed: bool = False,
) -> WorldView:
    preset = PRESETS.get(row.preset)
    # UNKNOWN (Docker nicht erreichbar) behält Vorrang vor dem Preset-Fehler.
    if preset is None and status.code != UNKNOWN:
        # Nur diese eine Welt zeigt den Fehler; die Liste aller Welten bleibt lesbar (WR-02).
        status = WorldStatus(ERROR, TEXT_UNKNOWN_PRESET)
        players = None
        access_restart_needed = False
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
        preset_title=UNKNOWN_PRESET_TITLE if preset is None else preset.title,
        status=status.code,
        status_text=status.text,
        players=players or [],
        memory_used_bytes=None if memory is None else memory.used,
        memory_limit_bytes=None if memory is None else memory.limit,
        delete_only=delete_only(row),
        invited_players=invited_players,
        access_restart_needed=access_restart_needed,
    )


def _copy(view: WorldView) -> WorldView:
    """Unabhängige Kopie, damit Aufrufer den Cache nie verändern."""
    return replace(view, players=list(view.players), invited_players=list(view.invited_players))


class WorldService:
    def __init__(self, store: WorldStore, provisioner: DockerProvisioner, settings: Settings) -> None:
        self._store = store
        self._provisioner = provisioner
        self._settings = settings
        # Cache der Weltenliste: (Zeitpunkt aus monotonic, Ansichten). Die
        # Generation verhindert, dass eine vor einer Mutation begonnene Liste
        # danach noch im Cache landet.
        self._cache_lock = threading.Lock()
        self._list_cache: tuple[float, list[WorldView]] | None = None
        self._cache_generation = 0

    async def create_world(self, name: str, preset_id: str = DEFAULT_PRESET_ID) -> WorldView:
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

    # Abgleich (worlds/reconciler.py). abandon_on_cancel: Beim Herunterfahren
    # wartet der Lifespan nicht auf einen hängenden Docker-Aufruf (bis 60 s);
    # der Thread gibt _LOCK im finally trotzdem frei.

    async def boot_reconcile(self) -> bool:
        """Abgleich beim Prozessstart; False, wenn gerade eine Elternaktion läuft."""
        return await anyio.to_thread.run_sync(self._boot_reconcile_sync, abandon_on_cancel=True)

    async def periodic_reconcile(self) -> None:
        """Zustandspflege ohne Start oder Neuerzeugung; übersprungen, wenn _LOCK belegt ist."""
        await anyio.to_thread.run_sync(self._periodic_reconcile_sync, abandon_on_cancel=True)

    # Hilfen

    @property
    def store(self) -> WorldStore:
        """Gemeinsame Ablage für den Zugangsdienst (access/service.py)."""
        return self._store

    def _access_file(self, row: WorldRow) -> bytes:
        """Zugangsdatei der Welt, frisch aus Schema 3 (Generation und Verifier je Spielername).

        Gleicher Soll-Zustand ergibt dieselben Bytes: Die Verifier liegen mit
        ihrem Salz in der Datenbank und werden nicht bei jedem Rendern neu gesalzen.
        """
        fresh = self._store.get_world(row.id)
        generation = row.access_generation if fresh is None else fresh.access_generation
        return render_access_file(generation, self._store.access_entries(row.id))

    def mutation(self) -> contextlib.AbstractContextManager[None]:
        """Dieselbe Sperre wie Welt-Mutationen, mit Cache-Verwurf (für den Zugangsdienst).

        Nur aus einem Worker-Thread betreten (anyio.to_thread), nie im Event-Loop.
        """
        return self._mutating()

    @contextlib.contextmanager
    def try_mutation(self) -> Iterator[bool]:
        """Wie mutation(), aber ohne Warten: liefert False, wenn gerade eine Aktion läuft.

        Für Abgleiche beim Auflisten: Statuslesen darf nie hinter einem Erzeugen
        warten (Pitfall 6 aus Phase 2). Nur aus einem Worker-Thread betreten.
        """
        if not _LOCK.acquire(blocking=False):
            yield False
            return
        self._invalidate_cache()
        try:
            yield True
        finally:
            _LOCK.release()
            self._invalidate_cache()

    def push_access(self, world_id: str) -> bool:
        """Schreibt die aktuelle Zugangsdatei in die laufende oder gestoppte Welt.

        Nur innerhalb von mutation() aufrufen. False heißt: Die Datei liegt noch
        nicht in der Welt; die Datenbank bleibt maßgeblich, und der nächste Start
        schreibt sie (_launch). Inhalte der Datei werden nie protokolliert.
        """
        access_file = self._access_file(self._row(world_id))
        try:
            self._provisioner.write_world_files(world_id, build_access_tar(access_file))
        except WorldNotFoundError:
            LOG.info("Welt %s: kein Container, die Zugangsdatei kommt beim nächsten Start", world_id)
            return False
        except ProvisionerError as exc:
            LOG.warning("Welt %s: Zugangsdatei nicht geschrieben, sie kommt beim nächsten Start: %s", world_id, exc)
            return False
        return True

    @contextlib.contextmanager
    def _payload(self, row: WorldRow) -> Iterator[WorldPayload]:
        """Inhalt aus dem Preset der DB-Zeile, auch bei Neuerzeugung (Pitfall 2).

        Schließt das Tar (temporäre Datei) nach dem Einspielen, auch im Fehlerfall.
        Dateisystem- und Archivfehler (voller Datenträger, kaputtes Zip) kommen als
        ProvisionerError an, damit jeder Aufrufer seinen Aufräumpfad nimmt (WR-01).
        """
        preset = get_preset(row.preset)
        try:
            payload = build_world_payload(
                preset,
                render_minetest_conf(row.name, row.world_key, preset),
                render_world_mt(preset),
                self._access_file(row),
            )
        except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
            LOG.warning("Weltdaten für Welt %s nicht vorbereitet: %r", row.id, exc)
            raise ProvisionerError(PAYLOAD_FAILED) from exc
        try:
            yield payload
        finally:
            payload.archive.close()

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

    def _invalidate_cache(self) -> None:
        with self._cache_lock:
            self._list_cache = None
            self._cache_generation += 1

    @contextlib.contextmanager
    def _mutating(self) -> Iterator[None]:
        """Mutation unter _LOCK; der Listen-Cache wird davor und danach verworfen, auch bei Fehlern."""
        self._invalidate_cache()
        try:
            with _LOCK:
                yield
        finally:
            self._invalidate_cache()

    def _views(self, rows: list[WorldRow]) -> list[WorldView]:
        return self._collect(rows)[0]

    def _collect(self, rows: list[WorldRow]) -> tuple[list[WorldView], bool]:
        """Ansichten mit Status aus Docker: einmal list_managed, Status-Datei nur wo nötig.

        Einziger Codepfad für Liste und Einzelansicht. Die Datenbank liefert nur
        creating/failed und den Elternwunsch, alles andere kommt aus Docker.
        Der zweite Wert sagt, ob Docker erreichbar war (nur dann wird gecacht).
        """
        try:
            managed = self._provisioner.list_managed()
        except ProvisionerError as exc:
            LOG.warning("Docker-Status nicht abrufbar, zeige unknown: %s", exc)
            unknown = [
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
                    invited_players=self._invited(row),
                )
                for row in rows
            ]
            return unknown, False
        return [self._view_from_docker(row, managed.get(row.id)) for row in rows], True

    def _status_file(self, row: WorldRow, container: ContainerInfo | None) -> StatusFile | None:
        """Status-Datei (mtime und Inhalt), nur für laufende Welten mit Status-Mod (Schema 2)."""
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
        return status_file

    def _invited(self, row: WorldRow) -> list[str]:
        """Spielernamen der Eingeladenen, sortiert; nur die Namen, nie die Verifier."""
        return sorted(self._store.access_entries(row.id))

    def _access_restart_needed(self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus) -> bool:
        """Läuft die Welt noch ohne geladenen Zugangsschutz (03-RESEARCH.md Pitfall 4)?

        Nur bei status running: Der Zugangs-Mod schreibt seine State-Datei, sobald
        er eine Zugangsdatei geladen hat. Fehlt sie oder ist sie älter als der
        Start des Containers, wurde die Welt vor dem Update gestartet und braucht
        einen Neustart. Gleiche Regel wie die Bereitschaft (mtime >= StartedAt).
        Ein Lesefehler betrifft nur diese Welt: False plus Warnung.
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            state = self._provisioner.read_access_state(row.id)
        except ProvisionerError as exc:
            LOG.warning("Zugangsstand von Welt %s nicht lesbar: %s", row.id, exc)
            return False
        if state is None:
            return True
        written = parse_docker_time(state.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            # Ohne lesbaren Startzeitpunkt zählt nur, dass die Datei da ist.
            return False
        return written is None or written < started

    def _memory(self, row: WorldRow, container: ContainerInfo | None) -> MemoryUsage | None:
        """RAM nur für laufende Container; ein Fehler betrifft nur diese Welt."""
        if container is None or container.status != "running":
            return None
        try:
            return self._provisioner.memory_bytes(row.id)
        except ProvisionerError as exc:
            LOG.warning("Arbeitsspeicher von Welt %s nicht abrufbar: %s", row.id, exc)
            return None

    def _view_from_docker(self, row: WorldRow, container: ContainerInfo | None) -> WorldView:
        status_file = self._status_file(row, container)
        status = derive_status(
            op_state=row.op_state,
            desired_state=row.desired_state,
            last_error=row.last_error,
            container=container,
            reachable=True,
            status_mtime=None if status_file is None else status_file.mtime,
        )
        # Spieler nur aus einer Datei dieses Laufs: running setzt mtime >= StartedAt voraus (Pitfall 3).
        players = parse_players(status_file.content) if status.code == RUNNING and status_file is not None else []
        docker_status = MISSING if container is None else container.status
        return _view(
            row,
            docker_status,
            status,
            players,
            self._memory(row, container),
            invited_players=self._invited(row),
            access_restart_needed=self._access_restart_needed(row, container, status),
        )

    def _launch(self, row: WorldRow) -> None:
        """Startet den Container; bei belegtem Port Neuerzeugung mit dem nächsten freien Port.

        Vor jedem Startversuch schreibt er beide Welt-Mods und die aktuelle
        Zugangsdatei in den Weltordner (put_archive, kein exec): So bekommen auch
        ältere Welten den Zugangs-Mod, und der Mod-Code folgt App-Updates.
        Das Volume mit den Weltdaten bleibt dabei erhalten; nur minetest.conf,
        world.mt und das Spiel werden neu eingespielt (deterministischer Inhalt).
        Fehlt der Container ganz (Fehlerpfad der Port-Saga oder docker rm von
        außen), wird er aus dem vorhandenen Volume neu erzeugt statt die Welt
        als verschwunden zu melden. Fehlt auch das Volume, endet der Start mit
        DeleteOnlyError statt einer leeren Welt. Höchstens MAX_START_ATTEMPTS
        Startversuche bei belegtem Port, danach NoFreePortError.
        """
        tried = {row.port}
        recreated = False
        attempt = 0
        while True:
            try:
                # Im selben try: Fehlt der Container schon beim Schreiben, greift die Neuerzeugung.
                self._provisioner.write_world_files(row.id, build_world_files(self._access_file(row)))
                self._provisioner.start_world(row.id)
                return
            except WorldNotFoundError:
                # Volume vorhanden, Container weg: aus dem Volume neu erzeugen.
                # Höchstens einmal pro Start; die Neuerzeugung durchläuft beim
                # nächsten Schleifendurchlauf weiter die Port-Saga.
                if recreated:
                    raise
                if not self._provisioner.volume_exists(row.id):
                    # Nie eine leere Welt unter altem Namen anlegen: Docker
                    # legte ein fehlendes Volume beim Mount still leer an (CR-01).
                    raise DeleteOnlyError(RECONCILE_DATA_MISSING) from None
                recreated = True
                LOG.warning("Welt %s: Container fehlt, erzeuge ihn aus dem Volume neu", row.id)
                self._provisioner.ensure_image()
                with self._payload(row) as payload:
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
            with self._payload(row) as payload:
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

    @staticmethod
    def _refuse_delete_only(row: WorldRow) -> None:
        """Start und Neustart einer Welt, die nur noch gelöscht werden kann, ändern nichts."""
        if delete_only(row):
            raise DeleteOnlyError(row.last_error or RECONCILE_DATA_MISSING)

    # Abläufe

    def _create_world_sync(self, name: str, preset_id: str) -> WorldView:
        with self._mutating():
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
                with self._payload(row) as payload:
                    self._provisioner.create_world_container(world_id, port, payload)
                self._launch(row)
            except ProvisionerError as exc:
                self._discard_failed_create(world_id, exc, touched_docker=touched_docker)
                raise
            except Exception as exc:
                # Jeder andere Fehler nimmt denselben Aufräumpfad: Sonst bliebe die
                # Zeile bis zum Prozessneustart auf creating und belegte ihren Port (WR-01).
                LOG.exception("Erzeugen von Welt %s scheiterte unerwartet", world_id)
                failure = ProvisionerError(CREATE_FAILED)
                self._discard_failed_create(world_id, failure, touched_docker=touched_docker)
                raise failure from exc

            self._store.update_world(world_id, op_state="ready")
            # Der Weltschlüssel wird seit 03-05 nicht mehr angezeigt; Zugang über
            # provisionierte Konten. Er bleibt als default_password in der conf.
            return self._current(world_id)

    def _list_worlds_sync(self) -> list[WorldView]:
        # Ohne _LOCK (Pitfall 6): Statuslesen darf nie hinter einem Erzeugen warten.
        with self._cache_lock:
            cached = self._list_cache
            generation = self._cache_generation
        if cached is not None and monotonic() - cached[0] < LIST_CACHE_SECONDS:
            return [_copy(view) for view in cached[1]]
        taken = monotonic()
        views, reachable = self._collect(self._store.list_worlds())
        # "Docker nicht erreichbar" wird nie gecacht: Die nächste Abfrage prüft neu.
        if reachable:
            with self._cache_lock:
                if self._cache_generation == generation:
                    self._list_cache = (taken, [_copy(view) for view in views])
        return views

    def _start_world_sync(self, world_id: str) -> WorldView:
        with self._mutating():
            row = self._row(world_id)
            self._refuse_delete_only(row)
            self._store.update_world(world_id, desired_state="running")
            try:
                self._launch(row)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            self._store.update_world(world_id, op_state="ready", last_error=None)
            return self._current(world_id)

    def _stop_world_sync(self, world_id: str) -> WorldView:
        with self._mutating():
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
        with self._mutating():
            row = self._row(world_id)
            self._refuse_delete_only(row)
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

    def _boot_reconcile_sync(self) -> bool:
        # Nicht blockierend (Pitfall 6): Läuft eine Elternaktion, kommt der Abgleich später wieder.
        if not _LOCK.acquire(blocking=False):
            LOG.info("Boot-Abgleich verschoben: Eine Elternaktion läuft")
            return False
        try:
            managed = self._provisioner.list_managed()
            rows = self._store.list_worlds()
            known = {row.id for row in rows}
            orphans = [world_id for world_id in managed if world_id not in known]
            if orphans:
                # Nie anfassen: Ohne Zeile fehlen Weltschlüssel und Elternwunsch.
                LOG.warning("verwaiste Welt-Container: %d (%s)", len(orphans), ", ".join(sorted(orphans)))
            for row in rows:
                self._reconcile_row(row, managed.get(row.id))
            return True
        finally:
            _LOCK.release()
            self._invalidate_cache()

    def _reconcile_row(self, row: WorldRow, container: ContainerInfo | None) -> None:
        """Eine Welt abgleichen; Fehler bleiben an dieser Welt, außer Docker ist ganz weg."""
        action = ReconcileAction.NONE
        try:
            volume = needs_volume_check(row, container) and self._provisioner.volume_exists(row.id)
            action = decide_boot(row, container, volume)
            if action is ReconcileAction.NONE:
                return
            LOG.info("Abgleich Welt %s: %s", row.id, action.value)
            self._apply(row, action)
        except DockerUnavailableError:
            # Proxy weg: keine Welt als kaputt markieren, der ganze Abgleich wiederholt sich.
            raise
        except ProvisionerError as exc:
            LOG.warning("Abgleich Welt %s (%s) gescheitert: %s", row.id, action.value, exc)
            self._fail(row.id, exc)
        except Exception:
            # Etwa ValueError aus get_preset (unbekannte Spielart): Sonst bräche der
            # ganze Boot-Abgleich ab, alle 5 s erneut, und keine Welt dahinter startete (WR-02).
            LOG.exception("Abgleich Welt %s (%s) scheiterte unerwartet", row.id, action.value)
            self._fail(row.id, ProvisionerError(RECONCILE_FAILED))

    def _apply(self, row: WorldRow, action: ReconcileAction) -> None:
        match action:
            case ReconcileAction.START | ReconcileAction.RECREATE:
                # RECREATE läuft über den Neuerzeugungspfad in _launch (Volume, row.preset).
                self._launch(row)
                self._store.update_world(row.id, op_state="ready", last_error=None)
            case ReconcileAction.MARK_OOM:
                self._store.update_world(row.id, last_error=RECONCILE_OOM)
            case ReconcileAction.MARK_DATA_MISSING:
                self._store.update_world(row.id, op_state="failed", last_error=RECONCILE_DATA_MISSING)
            case ReconcileAction.MARK_INTERRUPTED:
                self._store.update_world(row.id, op_state="failed", last_error=RECONCILE_INTERRUPTED)
            case ReconcileAction.RETRY_DELETE:
                self._provisioner.remove_world(row.id, keep_volume=False)
                self._store.delete_world(row.id)
                self._store.delete_access_data(row.id)
            case ReconcileAction.ADOPT_RUNNING:
                self._store.update_world(row.id, desired_state="running")
            case ReconcileAction.NONE:
                pass

    def _periodic_reconcile_sync(self) -> None:
        if not _LOCK.acquire(blocking=False):
            return
        changed = False
        try:
            managed = self._provisioner.list_managed()
            for row in self._store.list_worlds():
                if decide_periodic(row, managed.get(row.id)) is ReconcileAction.ADOPT_RUNNING:
                    LOG.info("Abgleich Welt %s: von Hand gestartet, Soll-Zustand jetzt running", row.id)
                    self._store.update_world(row.id, desired_state="running")
                    changed = True
        finally:
            _LOCK.release()
        if changed:
            self._invalidate_cache()

    def _delete_world_sync(self, world_id: str) -> None:
        with self._mutating():
            self._row(world_id)
            self._store.update_world(world_id, desired_state="deleted")
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            # Erst nach erfolgreichem Aufräumen: kein Volume ohne Eintrag (T-01-21).
            self._store.delete_world(world_id)
            # Kein PRAGMA foreign_keys: Einladungen und Zugang der Welt explizit löschen.
            self._store.delete_access_data(world_id)
