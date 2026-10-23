"""Lebenszyklus der Welten: Erzeugen, Auflisten, Starten, Stoppen, Löschen.

docker-py ist synchron; jeder Docker-Aufruf läuft deshalb über
``anyio.to_thread.run_sync``. Alle verändernden Abläufe laufen unter einem
Lock, damit Port-Vergabe und Neuerzeugung nie verschränkt laufen. Der
Weltschlüssel wird nie protokolliert.
"""

from __future__ import annotations

import contextlib
import io
import logging
import secrets
import sqlite3
import tarfile
import threading
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from time import monotonic
from typing import BinaryIO

import anyio.to_thread

from gameworld.backup.archive import ledger_tar
from gameworld.config import Settings
from gameworld.events.parse import new_events, parse_events, plausible
from gameworld.playtime.engine import TimeEngine
from gameworld.playtime.pause import (
    OUTBOX_PAUSE_START,
    PauseDecision,
    PauseResult,
    PauseWorldResult,
    is_active,
)
from gameworld.playtime.plan import WindowDay, window_days
from gameworld.provisioner.access_mod import render_access_file
from gameworld.provisioner.archive import build_access_tar, build_time_tar, build_world_files, build_world_payload
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
from gameworld.provisioner.time_mod import parse_ledger
from gameworld.worlds.ports import NoFreePortError, allocate_port
from gameworld.worlds.reconciler import (
    BUSY_OP_STATES,
    ReconcileAction,
    decide_boot,
    decide_periodic,
    needs_volume_check,
)
from gameworld.worlds.status import (
    ERROR,
    RUNNING,
    STATUS_MOD_SCHEMA,
    WorldStatus,
    derive_status,
    parse_docker_time,
    schema_version,
)
from gameworld.worlds.store import BACKUP_JOB_RUNNING, BackupJobRow, WorldRow, WorldStore

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
# Prozess starb mitten im Tausch der Weltdaten (op_state restoring_swap, RESEARCH Pitfall 2).
# Bewusst NICHT in DELETE_ONLY_ERRORS: Wiederherstellen bleibt im Zustand failed erlaubt (D-15),
# und die Sicherung vor dem Wiederherstellen liegt in Files.
RESTORE_INTERRUPTED = (
    "Das Wiederherstellen wurde unterbrochen. Bitte erneut wiederherstellen; "
    "die Sicherung vor dem Wiederherstellen liegt in Files."
)
# Elternaktion auf einer Welt, die gerade gesichert oder wiederhergestellt wird (HTTP 409).
WORLD_BUSY = "Die Welt wird gerade gesichert oder wiederhergestellt."
# Globaler Ein-Job-Schutz (RESEARCH Pattern 7): höchstens ein Auftrag im ganzen Haushalt.
JOB_RUNNING = "Es läuft schon eine Sicherung oder Wiederherstellung. Bitte kurz warten."
# Unerwarteter Fehler beim Wiederanlaufen nach dem Offline-Abschnitt; Details nur im Log.
OFFLINE_RESTART_FAILED = "Die Welt konnte danach nicht wieder gestartet werden. Bitte die Welt starten."
# So lange kündigt der Zeit-Mod den Halt im Chat an, bevor er alle trennt (D-09).
HALT_LEAD_SECONDS = 15
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
# Fehler, die im Zeittakt nur die betroffene Welt treffen (WR-06): gesperrte oder kaputte
# Datenbank, ungültige Zeile beim Rendern. Programmfehler anderer Art bleiben sichtbar.
_TICK_ERRORS: tuple[type[Exception], ...] = (sqlite3.Error, ValueError, KeyError)

UNKNOWN = "unknown"
MISSING = "missing"


class DeleteOnlyError(ProvisionerError):
    """Die Welt lässt sich nicht mehr starten, nur noch löschen (HTTP 409)."""


class WorldBusyError(ProvisionerError):
    """Die Welt wird gerade gesichert oder wiederhergestellt (HTTP 409)."""


def delete_only(row: WorldRow) -> bool:
    """Darf diese Welt nur noch gelöscht werden? Steht fest an der Zeile, nicht im Text der Oberfläche."""
    return row.op_state == "failed" and row.last_error in DELETE_ONLY_ERRORS


@dataclass(frozen=True)
class OfflineTicket:
    """Ergebnis von begin_offline: was der Auftrag zum Wiederanlaufen oder Zurücksetzen braucht.

    previous_op_state und previous_error erlauben es, eine vor der Zerstörung
    abgelehnte Wiederherstellung einer kaputten Welt in ihren alten Zustand
    zurückzusetzen (Plan 06).
    """

    world_id: str
    was_running: bool
    preset: str
    name: str
    previous_op_state: str
    previous_error: str | None


@dataclass(frozen=True)
class BackupJobView:
    """Letzter Sicherungs- oder Wiederherstellungsauftrag einer Welt (D-11), nur für Verwalter."""

    kind: str
    state: str
    message: str | None
    file_name: str | None
    finished_at: str | None


def _job_view(job: BackupJobRow | None) -> BackupJobView | None:
    if job is None:
        return None
    return BackupJobView(
        kind=job.kind, state=job.state, message=job.message, file_name=job.file_name, finished_at=job.finished_at
    )


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
    # Läuft die Welt ohne geladenen Zeit-Mod (kein Zählbuch)? Dann braucht sie einen Neustart.
    time_restart_needed: bool
    # Läuft die Welt mit altem Zugangs-Mod ohne Ereignisdatei? Dann kommen keine Hinweise, Neustart nötig.
    events_restart_needed: bool
    # Welt-Zeitfenster (ZEIT-05): sieben Wochentage oder None (immer offen).
    time_window: list[WindowDay] | None = None
    # Letzter Auftrag (D-11): Fehler bleiben nach Neuladen sichtbar. Nie an Kinder (AR-24).
    backup_job: BackupJobView | None = None


def _view(
    row: WorldRow,
    docker_status: str,
    status: WorldStatus,
    players: list[str] | None = None,
    memory: MemoryUsage | None = None,
    *,
    invited_players: list[str],
    access_restart_needed: bool = False,
    time_restart_needed: bool = False,
    events_restart_needed: bool = False,
    time_window: list[WindowDay] | None = None,
    backup_job: BackupJobView | None = None,
) -> WorldView:
    preset = PRESETS.get(row.preset)
    # UNKNOWN (Docker nicht erreichbar) behält Vorrang vor dem Preset-Fehler.
    if preset is None and status.code != UNKNOWN:
        # Nur diese eine Welt zeigt den Fehler; die Liste aller Welten bleibt lesbar (WR-02).
        status = WorldStatus(ERROR, TEXT_UNKNOWN_PRESET)
        players = None
        access_restart_needed = False
        time_restart_needed = False
        events_restart_needed = False
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
        time_restart_needed=time_restart_needed,
        events_restart_needed=events_restart_needed,
        time_window=time_window,
        backup_job=backup_job,
    )


def _copy(view: WorldView) -> WorldView:
    """Unabhängige Kopie, damit Aufrufer den Cache nie verändern."""
    return replace(
        view,
        players=list(view.players),
        invited_players=list(view.invited_players),
        time_window=None if view.time_window is None else list(view.time_window),
    )


class WorldService:
    def __init__(self, store: WorldStore, provisioner: DockerProvisioner, settings: Settings) -> None:
        self._store = store
        self._provisioner = provisioner
        self._settings = settings
        # Rechnet Regeldateien aus Schema 4 und verbucht das Zählbuch (synchron, nur Store).
        self._time = TimeEngine(store)
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

    @property
    def time(self) -> TimeEngine:
        """Spielzeit-Rechnung für den Spielzeit-Dienst (playtime/service.py): nur lesend genutzt."""
        return self._time

    @property
    def provisioner(self) -> DockerProvisioner:
        """Docker-Zugang für den Sicherungsdienst (backup/service.py): nur snapshot_to, ohne Sperre.

        Der Snapshot liest einen gestoppten Container (snapshot_to prüft das selbst);
        Stopp und Neustart laufen über stop_for_snapshot und end_offline.
        """
        return self._provisioner

    def _access_file(self, row: WorldRow) -> bytes:
        """Zugangsdatei der Welt, frisch aus Schema 3 (Generation und Verifier je Spielername).

        Gleicher Soll-Zustand ergibt dieselben Bytes: Die Verifier liegen mit
        ihrem Salz in der Datenbank und werden nicht bei jedem Rendern neu gesalzen.
        """
        fresh = self._store.get_world(row.id)
        generation = row.access_generation if fresh is None else fresh.access_generation
        return render_access_file(generation, self._store.access_entries(row.id))

    def _time_file(self, row: WorldRow) -> bytes:
        """Regeldatei des Zeit-Mods für diese Welt, frisch aus Schema 4.

        Vor dem Rendern wird das Zählbuch der Welt gelesen und verbucht (Pitfall
        7: auch bei gestopptem Container, bevor der neue Start das Volume anfasst).
        Ohne Regeln bleibt es bei Kopf und Schlusszeile (Opt-in, O-10).
        """
        try:
            self._book_ledger(row.id)
        except ProvisionerError as exc:
            # Ein unlesbares Zählbuch darf den Start nicht verhindern; der Rest kommt aus der DB.
            LOG.warning("Welt %s: Zählbuch vor dem Rendern nicht lesbar: %s", row.id, exc)
        data, _changed = self._time.render(row.id)
        return data

    def _book_ledger(self, world_id: str) -> None:
        """Liest das Zählbuch der Welt und verbucht die Zuwächse; fehlt es, passiert nichts.

        Ein fehlender Container (WorldNotFoundError) heißt: nichts verbuchen.
        Andere Lesefehler (ProvisionerError) reicht der Aufrufer weiter und
        isoliert sie pro Welt (tick_time); der Dateiinhalt wird nie protokolliert.
        """
        try:
            status_file = self._provisioner.read_time_ledger(world_id)
        except WorldNotFoundError:
            return
        if status_file is None:
            return
        ledger = parse_ledger(status_file.content)
        if ledger is None and status_file.content:
            # Vorhanden, aber ohne Kopf oder Schlusszeile: nie still übergehen (WR-03).
            # Meist halb geschrieben (der nächste Takt heilt es), dauerhaft heißt: zu groß oder kaputt.
            LOG.warning(
                "Welt %s: Zählbuch unvollständig (%d Bytes), in diesem Takt nicht verbucht",
                world_id,
                len(status_file.content),
            )
        self._time.book(world_id, ledger)

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
        """Schreibt die aktuelle Zugangs- und Regeldatei in die laufende oder gestoppte Welt.

        Nur innerhalb von mutation() aufrufen. False heißt: Die Dateien liegen noch
        nicht in der Welt; die Datenbank bleibt maßgeblich, und der nächste Start
        schreibt sie (_launch). Im selben Sperrblock folgt push_time: Ein frisch
        eingeladenes Kind mit Regeln steht sofort in der Regeldatei, nicht erst nach
        dem nächsten Takt. Inhalte der Dateien werden nie protokolliert.
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
        return self.push_time(world_id)

    def push_time(self, world_id: str) -> bool:
        """Schreibt die aktuelle Regeldatei in die laufende oder gestoppte Welt.

        Nur innerhalb von mutation() (oder try_mutation) aufrufen. Rendert immer
        frisch aus der Datenbank (bei einer Änderung zählt die Generation hoch) und
        schreibt sie. False heißt: kein Container oder Docker weg, der nächste Start
        schreibt sie. Inhalte der Datei werden nie protokolliert.
        """
        data, _changed = self._time.render(world_id)
        try:
            self._write_time(world_id, data)
        except WorldNotFoundError:
            LOG.info("Welt %s: kein Container, die Regeldatei kommt beim nächsten Start", world_id)
            return False
        except ProvisionerError as exc:
            LOG.warning("Welt %s: Regeldatei nicht geschrieben, sie kommt beim nächsten Start: %s", world_id, exc)
            return False
        return True

    def _write_time(self, world_id: str, data: bytes) -> None:
        """Schreibt die Regeldatei; scheitert es, wird der gerenderte Stand verworfen (CR-01).

        Ohne den Verwurf hielte der Render-Cache den nie angekommenen Stand für
        geschrieben, und der 15-s-Takt (nur bei ``geändert``) holte ihn nie nach.
        """
        try:
            self._provisioner.write_world_files(world_id, build_time_tar(data))
        except BaseException:
            self._time.forget(world_id)
            raise

    def _collect_events(self, world_id: str, now: int) -> None:
        """Neue Zeilen der Ereignisdatei in die SQLite-Outbox legen (kein Netzaufruf).

        Cursor und Outbox-Zeilen landen in einer Transaktion (store.take_events);
        Erstkontakt mit alter Datei und Rücksprung verankern nur (new_events).
        Fehlt die Datei (alter Mod) oder der Container, passiert nichts. Eine
        unvollständige Datei wird mit Größe gemeldet, nie mit Inhalt.
        """
        try:
            events_file = self._provisioner.read_events(world_id)
        except WorldNotFoundError:
            return
        if events_file is None:
            return
        parsed = parse_events(events_file.content)
        if parsed is None:
            if events_file.content:
                LOG.warning(
                    "Welt %s: Ereignisdatei unvollständig (%d Bytes), in diesem Takt übergangen",
                    world_id,
                    len(events_file.content),
                )
            return
        last_seq, events = parsed
        cursor = self._store.event_cursor(world_id)
        fresh, new_cursor = new_events(cursor, last_seq, events, now=now)
        if not fresh and new_cursor == cursor:
            return
        # Unglaubhafte Zeitpunkte fallen weg, der Cursor rückt trotzdem vor (IN-10).
        kept = plausible(fresh, now=now)
        self._store.take_events(world_id, new_cursor, [(event.kind, event.name, event.at, "") for event in kept])

    def _track_run_state(self, rows: list[WorldRow], managed: dict[str, ContainerInfo], now: int) -> None:
        """Start und Stopp aus dem beobachteten Docker-Zustand (Pitfall 10), nie aus Requests.

        Erste Beobachtung einer Welt verankert nur. Ein Neustart zwischen zwei
        Takten erscheint nicht (gewollt ruhig). Welten im Löschen zählen nicht.
        """
        for row in rows:
            # Busy Welten stoppen gewollt (Sicherung, Wiederherstellung): kein "Welt aus/an" an Talk
            # (Pitfall 9). Der Laufzustand bleibt stehen; danach meldet nur eine echte Änderung.
            if row.desired_state == "deleted" or row.op_state in BUSY_OP_STATES:
                continue
            info = managed.get(row.id)
            running = info is not None and info.status == RUNNING
            before = self._store.run_state(row.id)
            if before is running:
                continue
            if before is not None:
                self._store.add_outbox(row.id, "start" if running else "stop", "", now)
            self._store.set_run_state(row.id, running=running)

    def tick_time(self) -> None:
        """15-s-Zeittakt: Zählbuch aller laufenden Welten verbuchen, geänderte Regeldateien schreiben.

        Nimmt nur try_mutation() (nie blockierend, Pitfall 6): Läuft gerade eine
        Elternaktion, wird der Takt übersprungen. Erst werden alle Welten verbucht,
        dann gerendert: So sieht Welt B den Verbrauch aus Welt A (ein Kontingent über
        alle Welten, O-03). Ein Fehler einer Welt betrifft nur diese Welt. Daneben
        landen Start/Stopp-Übergänge und neue Ereignisse in der SQLite-Outbox;
        versendet wird erst im Event-Loop (Phase 4.1), der Takt ruft kein Netz.
        """
        with self.try_mutation() as acquired:
            if not acquired:
                return
            managed = self._provisioner.list_managed()
            rows = self._store.list_worlds()
            running = [row for row in rows if (info := managed.get(row.id)) is not None and info.status == RUNNING]
            now = self._time.now()
            try:
                self._track_run_state(rows, managed, now)
            except _TICK_ERRORS as exc:
                # Start/Stopp-Meldungen holt der nächste Takt nach; die Regeldateien gehen vor.
                LOG.warning("Laufzustand im Takt nicht festgehalten (%s)", type(exc).__name__)
            for row in running:
                try:
                    self._book_ledger(row.id)
                except ProvisionerError as exc:
                    LOG.warning("Welt %s: Zählbuch im Takt nicht verbucht: %s", row.id, exc)
                except _TICK_ERRORS as exc:
                    # WR-06: Datenbank gesperrt oder kaputte Zeile trifft nur diese Welt.
                    LOG.warning("Welt %s: Zählbuch im Takt nicht verbucht (%s)", row.id, type(exc).__name__)
                try:
                    self._collect_events(row.id, now)
                except (ProvisionerError, *_TICK_ERRORS) as exc:
                    # Nur Welt-ID und Fehlertyp, nie Dateiinhalt oder Spielernamen (T-04.1-08).
                    LOG.warning("Welt %s: Ereignisse im Takt nicht gelesen (%s)", row.id, type(exc).__name__)
            for row in running:
                try:
                    data, changed = self._time.render(row.id)
                    if changed:
                        self._write_time(row.id, data)
                except ProvisionerError as exc:
                    LOG.warning("Welt %s: Regeldatei im Takt nicht geschrieben: %s", row.id, exc)
                except _TICK_ERRORS as exc:
                    # WR-06: Der nächste Takt rendert neu; die übrigen Welten bekommen ihre Datei trotzdem.
                    self._time.forget(row.id)
                    LOG.warning("Welt %s: Regeldatei im Takt nicht geschrieben (%s)", row.id, type(exc).__name__)

    def apply_pause_sync(self, decide: PauseDecision, outbox_kind: str) -> PauseResult:
        """Pause setzen oder beenden und sofort an alle Welten ausrollen (ELTERN-01, D-01, D-25).

        Alles unter mutation() in einem Worker-Thread (nie im Event-Loop):
        ``decide`` bekommt die laufende Pause (oder None) und jetzt und liefert den
        neuen Zustand (None = keine Pause). Danach bekommt jede Welt die Regeldatei
        (push_time, Ergebnis ``applied``). Läuft eine Welt beim Setzen noch mit
        altem Mod (keine Ereignisdatei aus diesem Lauf), wird sie ohne Vorwarnung
        neu gestartet (stop plus _launch, nie _restart_world_sync: _LOCK ist nicht
        reentrant). Je Welt entsteht eine Outbox-Zeile für den Bot (04.1-06), bei
        ``pause_start`` mit dem Ende als Zusatz. Beenden ohne laufende Pause
        ändert nichts und legt keine Zeile an. Fehler bleiben je Welt isoliert.
        """
        with self._mutating():
            now = self._time.now()
            current = self._store.get_pause()
            if not is_active(current, now):
                current = None
            state = decide(current, now)
            if state is None:
                self._store.clear_pause()
            else:
                self._store.set_pause(state)
            try:
                managed = self._provisioner.list_managed()
            except ProvisionerError as exc:
                # Ohne Docker-Liste kein Neustart; push_time meldet je Welt selbst.
                LOG.warning("Pause: Docker-Liste nicht abrufbar (%s)", type(exc).__name__)
                managed = {}
            detail = str(state.bis) if state is not None and outbox_kind == OUTBOX_PAUSE_START else ""
            # Nur eine echte Änderung meldet der Bot (WR-01): Ein Pause-Knopf während
            # "Für heute Schluss" oder ohne späteres Ende ändert nichts und meldet nichts.
            announce = (state is not None or current is not None) and state != current
            results: list[PauseWorldResult] = []
            for row in self._store.list_worlds():
                if row.desired_state == "deleted":
                    continue
                results.append(self._pause_world(row, managed.get(row.id), restart=state is not None))
                if announce:
                    self._store.add_outbox(row.id, outbox_kind, "", now, detail)
            return PauseResult(state=state, worlds=results)

    def _pause_world(self, row: WorldRow, container: ContainerInfo | None, *, restart: bool) -> PauseWorldResult:
        """Regeldatei mit dem neuen Pause-Stand in eine Welt; alte Mods laufender Welten neu starten (D-25).

        Busy Welten (Sicherung, Wiederherstellung) bekommen nur die Regeldatei: Den
        Container besitzt gerade der Auftrag, er startet die Welt danach selbst.
        """
        if (
            restart
            and row.op_state not in BUSY_OP_STATES
            and not delete_only(row)
            and container is not None
            and container.status == RUNNING
            # Fail-closed (AR-41-09): Ist der Mod-Stand unklar, startet die Welt neu.
            # Die Pause trennt ohnehin alle, nur so ist @pause sicher wirksam.
            and self._events_restart_needed(row, container, WorldStatus(RUNNING, ""), unknown=True)
        ):
            try:
                try:
                    self._provisioner.stop(row.id)
                except WorldNotFoundError:
                    LOG.info("Welt %s: Container fehlt, der Neustart für die Pause erzeugt ihn neu", row.id)
                self._launch(row)
            except ProvisionerError as exc:
                # Nur Welt-ID und Fehlertyp (T-04.1-08); die Welt zeigt den Fehler wie beim Neustart.
                LOG.warning("Welt %s: Neustart für die Pause gescheitert (%s)", row.id, type(exc).__name__)
                self._fail(row.id, exc)
                return PauseWorldResult(world_id=row.id, name=row.name, applied=False, restarted=False)
            self._store.update_world(row.id, op_state="ready", last_error=None)
            return PauseWorldResult(world_id=row.id, name=row.name, applied=True, restarted=True)
        return PauseWorldResult(world_id=row.id, name=row.name, applied=self.push_time(row.id), restarted=False)

    # Offline-Abschnitte für Sicherung und Wiederherstellung (Plan 05/06).
    #
    # Synchron, aus Worker-Threads per anyio.to_thread aufgerufen und nie
    # verschachtelt (_LOCK ist nicht reentrant). Jeder Abschnitt hält _LOCK nur
    # für seine eigene Dauer: Zwischen zwei Abschnitten (Snapshot, Upload,
    # Wartezeit des Chat-Hinweises) laufen Pause, Einladungen und Zeittakt
    # weiter (RESEARCH Pitfall 3). Den Busy-Zustand trägt die Datenbank.

    def begin_offline(self, world_id: str, op_state: str, *, allow_failed: bool = False) -> OfflineTicket:
        """Setzt die Welt in einen Busy-Zustand und liefert das Ticket für den Auftrag.

        Wirft WorldBusyError, wenn diese Welt schon busy ist (WORLD_BUSY) oder
        irgendwo ein anderer Auftrag läuft (JOB_RUNNING, auch in der Upload-Phase).
        Eine Welt, die nur noch gelöscht werden kann, lässt sich nicht sichern
        (DeleteOnlyError); allow_failed=True (Wiederherstellen, D-15) erlaubt sie.
        """
        if op_state not in BUSY_OP_STATES:
            msg = f"Kein Busy-Zustand als op_state: {op_state}"
            raise ValueError(msg)
        with self._mutating():
            row = self._row(world_id)
            self._refuse_busy(row)
            if not allow_failed:
                self._refuse_delete_only(row)
            others_busy = any(other.op_state in BUSY_OP_STATES for other in self._store.list_worlds())
            if others_busy or self._store.running_backup_jobs():
                raise WorldBusyError(JOB_RUNNING)
            self._store.update_world(world_id, op_state=op_state)
            return OfflineTicket(
                world_id=world_id,
                was_running=row.desired_state == "running",
                preset=row.preset,
                name=row.name,
                previous_op_state=row.op_state,
                previous_error=row.last_error,
            )

    def players_online(self, world_id: str) -> int:
        """Spieler laut Status-Datei dieses Laufs, unabhängig von op_state (D-09, T-05-46).

        Liest bewusst nicht über _status_file oder _view: Die liefern bei
        Busy-Zuständen nichts, announce_halt läuft aber erst nach begin_offline.
        Ohne _LOCK (nur Lesen). Gestoppter oder fehlender Container, Welt ohne
        Status-Mod, Datei aus einem früheren Lauf und jeder Docker-Fehler ergeben 0.
        """
        try:
            container = self._provisioner.list_managed().get(world_id)
            if container is None or container.status != RUNNING or schema_version(container.schema) < STATUS_MOD_SCHEMA:
                return 0
            status_file = self._provisioner.read_status_file(world_id)
        except ProvisionerError as exc:
            LOG.warning("Welt %s: Spieler vor dem Halt nicht zählbar (%s)", world_id, type(exc).__name__)
            return 0
        if status_file is None:
            return 0
        written = parse_docker_time(status_file.mtime)
        started = parse_docker_time(container.started_at)
        # Namen aus einem früheren Lauf zählen nie (Pitfall 3 aus Phase 2).
        if written is None or started is None or written < started:
            return 0
        return len(parse_players(status_file.content))

    def announce_halt(self, world_id: str, now: int) -> int | None:
        """Kündigt den Halt im Chat an, wenn jemand spielt; liefert den Zeitpunkt ``ab`` oder None.

        Setzt den flüchtigen Halt in der Zeit-Rechnung und schreibt die Regeldatei
        sofort (push_time); der Zeit-Mod warnt, sperrt Beitritte und trennt ab ``ab``.
        """
        if self.players_online(world_id) == 0:
            return None
        ab = now + HALT_LEAD_SECONDS
        with self._mutating():
            self._time.set_halt(world_id, ab)
            if not self.push_time(world_id):
                LOG.warning("Welt %s: Halt-Hinweis nicht in die Welt geschrieben", world_id)
        return ab

    def stop_for_snapshot(self, world_id: str) -> None:
        """Stoppt den Container für den Snapshot; verbucht nichts und ändert keinen Elternwunsch.

        Ein fehlender Container ist kein Fehler (der Snapshot meldet ihn dann selbst).
        """
        with self._mutating():
            try:
                self._provisioner.stop(world_id)
            except WorldNotFoundError:
                LOG.info("Welt %s: Container fehlt, Stoppen vor dem Snapshot ist ein No-op", world_id)

    def end_offline(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """Beendet den Offline-Abschnitt: Halt weg, bei was_running neu starten, Zustand zurück.

        Muster _restart_world_sync ohne Stopp. Der Zustand kehrt IMMER auf ready
        oder failed zurück (D-11, Pitfall 7); ein Startfehler wird nicht geworfen,
        sondern zurückgegeben, damit der Auftrag ihn als Job-Fehler meldet.
        """
        with self._mutating():
            self._time.clear_halt(world_id)
            return self._relaunch(world_id, was_running)

    def abort_offline(self, ticket: OfflineTicket) -> None:
        """Bricht einen Auftrag vor dem Stopp ab: Zustand wie vorher, Halt weg, kein Docker-Aufruf.

        Setzt op_state und last_error auf previous_op_state und previous_error aus
        dem Ticket zurück (eine vorher fehlgeschlagene Welt bleibt fehlgeschlagen).
        Die Welt läuft noch: Die Regeldatei wird sofort ohne ``@halt`` geschrieben,
        sonst trennte der Zeit-Mod die Kinder trotzdem. Fehlt die Welt inzwischen,
        passiert nichts.
        """
        with self._mutating():
            self._time.clear_halt(ticket.world_id)
            if self._store.get_world(ticket.world_id) is None:
                return
            self._store.update_world(
                ticket.world_id, op_state=ticket.previous_op_state, last_error=ticket.previous_error
            )
            if not self.push_time(ticket.world_id):
                LOG.warning("Welt %s: Regeldatei ohne Halt nicht geschrieben, der Takt holt es nach", ticket.world_id)

    def book_ledger(self, world_id: str) -> None:
        """Öffentlicher Einstieg für _book_ledger (Wiederherstellen, D-06), unter der Sperre."""
        with self._mutating():
            self._book_ledger(world_id)

    # Tausch der Weltdaten beim Wiederherstellen (Plan 06, RESEARCH Pattern 5).

    def mark_swap(self, world_id: str) -> None:
        """Persistiert restoring_swap, bevor irgendetwas zerstört wird (T-05-33).

        Stirbt der Prozess danach, macht der Boot-Abgleich daraus RESTORE_INTERRUPTED
        (wiederholbar, nicht delete-only) statt die Welt mit halbem Volume zu starten.
        """
        with self._mutating():
            self._row(world_id)
            self._store.update_world(world_id, op_state="restoring_swap")

    def restore_swap(self, world_id: str, restore_tar: BinaryIO, ledger: bytes | None) -> None:
        """Baut die Welt über ein frisches Volume neu auf und spielt den Weltinhalt ein.

        Der Phase-1-Erzeugungspfad (_payload) liefert Preset-world.mt, Mods und
        frische Zugangs- und Regeldatei mit den Einladungen und Regeln von heute
        (D-06); darüber kommt der gefilterte Weltinhalt, danach das bewahrte
        Zählbuch. Das alte Volume samt heißem SQLite-Journal fällt weg (T-05-32).
        Die Docker-Schritte laufen ohne _LOCK, den Busy-Zustand trägt die
        Datenbank. Fehler gehen an den Aufrufer, der den Tausch wiederholt.
        """
        # Vor _payload: Sonst rendert die neue Regeldatei den Halt mit (T-05-50).
        self._time.clear_halt(world_id)
        row = self._row(world_id)
        try:
            self._provisioner.remove_world(world_id, keep_volume=False)
        except WorldNotFoundError:
            LOG.info("Welt %s: kein Container vor dem Tausch", world_id)
        self._provisioner.ensure_image()
        with self._payload(row) as payload:
            self._provisioner.create_world_container(row.id, row.port, payload, reuse_volume=False)
        restore_tar.seek(0)
        self._provisioner.put_world_archive(world_id, restore_tar)
        if ledger is not None:
            self._provisioner.put_world_archive(world_id, io.BytesIO(ledger_tar(ledger)))
        # Neue Ereignisdatei im frischen Volume: Erstkontakt verankert neu, keine Altmeldungen.
        self._store.reset_event_cursor(world_id)
        self._time.forget(world_id)
        self._invalidate_cache()

    def finish_swap(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """Schluss des Tauschs: Halt weg, bei was_running starten, Zustand ready (Muster end_offline).

        Der Elternwunsch (desired_state) bleibt unverändert. Ein Startfehler wird
        zurückgegeben, nicht geworfen; die Welt steht dann auf failed.
        """
        with self._mutating():
            self._time.clear_halt(world_id)
            return self._relaunch(world_id, was_running)

    def mark_restore_interrupted(self, world_id: str) -> None:
        """Tausch endgültig gescheitert: failed mit RESTORE_INTERRUPTED, wiederholbar (D-15)."""
        with self._mutating():
            self._time.clear_halt(world_id)
            self._time.forget(world_id)
            if self._store.get_world(world_id) is None:
                return
            self._store.update_world(world_id, op_state="failed", last_error=RESTORE_INTERRUPTED)

    def _relaunch(self, world_id: str, was_running: bool) -> ProvisionerError | None:
        """Gemeinsamer Wiederanlauf; nur unter _mutating(), nachdem der Halt entfernt wurde."""
        self._time.forget(world_id)
        try:
            row = self._row(world_id)
            if was_running:
                self._launch(row)
        except ProvisionerError as exc:
            LOG.warning("Welt %s: Wiederanlauf nach dem Offline-Abschnitt gescheitert (%s)", world_id, exc)
            self._fail(world_id, exc)
            return exc
        except Exception:
            LOG.exception("Welt %s: Wiederanlauf nach dem Offline-Abschnitt scheiterte unerwartet", world_id)
            failure = ProvisionerError(OFFLINE_RESTART_FAILED)
            self._fail(world_id, failure)
            return failure
        self._store.update_world(world_id, op_state="ready", last_error=None)
        return None

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
                self._time_file(row),
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
                    time_window=self._time_window(row),
                    backup_job=self._backup_job(row),
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
            # Busy: Status und Text kommen allein aus op_state (D-10); die Spielerzählung
            # für den Chat-Hinweis liest direkt (players_online).
            or row.op_state in BUSY_OP_STATES
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

    def _time_window(self, row: WorldRow) -> list[WindowDay] | None:
        """Welt-Zeitfenster aus der Datenbank (ZEIT-05); None heißt: immer offen."""
        return window_days(self._store.world_window(row.id))

    def _backup_job(self, row: WorldRow) -> BackupJobView | None:
        """Letzter Auftrag der Welt aus der Datenbank (D-11), unabhängig von Docker."""
        return _job_view(self._store.get_backup_job(row.id))

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

    def _time_restart_needed(self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus) -> bool:
        """Läuft die Welt noch ohne geladenen Zeit-Mod (vor dem Update gestartet)?

        Nur bei status running: Der Zeit-Mod schreibt sein Zählbuch bei mods_loaded.
        Fehlt es oder ist es älter als der Start des Containers, trägt die Welt den
        Zeit-Mod noch nicht und braucht einen Neustart. Gleiche Regel und Isolierung
        wie _access_restart_needed; ein Lesefehler betrifft nur diese Welt.
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            ledger = self._provisioner.read_time_ledger(row.id)
        except ProvisionerError as exc:
            LOG.warning("Spielzeitstand von Welt %s nicht lesbar: %s", row.id, exc)
            return False
        if ledger is None:
            return True
        written = parse_docker_time(ledger.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            return False
        return written is None or written < started

    def _events_restart_needed(
        self, row: WorldRow, container: ContainerInfo | None, status: WorldStatus, *, unknown: bool = False
    ) -> bool:
        """Läuft die Welt noch mit altem Zugangs-Mod ohne Ereignisdatei (Pattern 3)?

        Nur bei status running: Der neue Mod schreibt die Ereignisdatei bei
        mods_loaded. Fehlt sie oder ist sie älter als der Start des Containers,
        kommen aus dieser Welt keine Hinweise, bis sie neu startet. Gleiche Regel
        und Isolierung wie _time_restart_needed; ein Lesefehler oder ein fehlendes
        StartedAt ergibt ``unknown`` (Anzeige: False, Pause: True).
        """
        if container is None or status.code != RUNNING:
            return False
        try:
            events_file = self._provisioner.read_events(row.id)
        except ProvisionerError as exc:
            LOG.warning("Ereignisdatei von Welt %s nicht lesbar: %s", row.id, exc)
            return unknown
        if events_file is None:
            return True
        written = parse_docker_time(events_file.mtime)
        started = parse_docker_time(container.started_at)
        if started is None:
            return unknown
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
            time_restart_needed=self._time_restart_needed(row, container, status),
            events_restart_needed=self._events_restart_needed(row, container, status),
            time_window=self._time_window(row),
            backup_job=self._backup_job(row),
        )

    def _launch(self, row: WorldRow) -> None:
        """Startet den Container; bei belegtem Port Neuerzeugung mit dem nächsten freien Port.

        Vor jedem Startversuch schreibt er alle drei Welt-Mods, die aktuelle
        Zugangsdatei und die Regeldatei des Zeit-Mods in den Weltordner
        (put_archive, kein exec): So bekommen auch ältere Welten Zugangs- und
        Zeit-Mod, und der Mod-Code folgt App-Updates. Das Zählbuch im Volume
        bleibt unberührt.
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
                world_files = build_world_files(self._access_file(row), self._time_file(row))
                try:
                    self._provisioner.write_world_files(row.id, world_files)
                except BaseException:
                    # Regeldatei nicht angekommen: Der nächste Takt schreibt sie erneut (CR-01).
                    self._time.forget(row.id)
                    raise
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

    @staticmethod
    def _refuse_busy(row: WorldRow) -> None:
        """Während Sicherung oder Wiederherstellung gehört der Container dem Auftrag (T-05-15)."""
        if row.op_state in BUSY_OP_STATES:
            raise WorldBusyError(WORLD_BUSY)

    def _refuse_job_running(self, world_id: str) -> None:
        """Löschen während der Upload-Phase sperren (T-05-45).

        Nach end_offline steht op_state wieder auf ready, der Auftrag läuft aber
        noch. Ohne diese Sperre entfernte das Löschen die Auftragszeile, der
        Ein-Job-Schutz fiele weg und der Abschluss schriebe eine verwaiste Zeile.
        """
        job = self._store.get_backup_job(world_id)
        if job is not None and job.state == BACKUP_JOB_RUNNING:
            raise WorldBusyError(WORLD_BUSY)

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
            self._refuse_busy(row)
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
            row = self._row(world_id)
            self._refuse_busy(row)
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
            self._refuse_busy(row)
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
            if action is ReconcileAction.CLEAR_BUSY:
                # Abgebrochene Sicherung oder Wiederherstellung vor dem Tausch: Die Weltdaten
                # sind unverändert. Zurück auf ready, dann die frische Zeile wie jede andere
                # behandeln (D-11: Die Welt startet wieder, wenn sie laufen soll).
                LOG.info("Abgleich Welt %s: %s", row.id, action.value)
                self._apply(row, action)
                row = self._row(row.id)
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
                self._store.delete_time_data(row.id)
                self._store.delete_notify_data(row.id)
                self._store.delete_backup_job(row.id)
            case ReconcileAction.CLEAR_BUSY:
                # Danach wertet _reconcile_row die frische Zeile nach den normalen Regeln aus.
                self._store.update_world(row.id, op_state="ready")
            case ReconcileAction.MARK_RESTORE_INTERRUPTED:
                self._store.update_world(row.id, op_state="failed", last_error=RESTORE_INTERRUPTED)
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
            row = self._row(world_id)
            self._refuse_busy(row)
            self._refuse_job_running(world_id)
            self._store.update_world(world_id, desired_state="deleted")
            try:
                self._provisioner.remove_world(world_id, keep_volume=False)
            except ProvisionerError as exc:
                self._fail(world_id, exc)
                raise
            # Erst nach erfolgreichem Aufräumen: kein Volume ohne Eintrag (T-01-21).
            self._store.delete_world(world_id)
            # Kein PRAGMA foreign_keys: Einladungen, Zugang, Welt-Fenster und
            # gesehene Zählbuchstände der Welt explizit löschen, dazu Cursor,
            # Outbox, Laufzustand, Fremdversuche und Bot-Drossel (Schema 5). Die
            # Tagesspielzeit (play_daily) bleibt bis zur normalen Frist, damit der
            # Rückblick am Abend auch eine heute gelöschte Welt zählt.
            self._store.delete_access_data(world_id)
            self._store.delete_time_data(world_id)
            self._store.delete_notify_data(world_id)
            # Nur der Auftragszustand; die Sicherungsnachweise (backups) bleiben (D-08, Plan 02).
            self._store.delete_backup_job(world_id)
