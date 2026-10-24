"""Der einzige Docker-Client von Gameworld.

Alle Methoden sind synchron; Aufrufer kapseln sie mit ``anyio.to_thread.run_sync``.
Jede öffentliche Methode läuft durch :meth:`DockerProvisioner._guarded`, damit
Verbindungs- und Transportfehler immer als :class:`DockerUnavailableError`
ankommen, auch wenn der Client schon einmal verbunden war und der Proxy erst
später wegbricht. Aufrufer sehen nie rohe requests- oder urllib3-Ausnahmen.
"""

from __future__ import annotations

import contextlib
import io
import logging
import tarfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, BinaryIO, cast

import docker
import docker.errors
import requests.exceptions
import urllib3.exceptions
from docker.models.containers import Container

from gameworld.provisioner.access_mod import EVENTS_FILE, STATE_FILE
from gameworld.provisioner.spec import DATA_DIR, LUANTI_IMAGE, WorldPayload, resource_name, world_spec
from gameworld.provisioner.status_mod import PLAYERS_FILE
from gameworld.provisioner.time_mod import LEDGER_FILE

LOG = logging.getLogger(__name__)

PORT_CONFLICT_MARKERS = ("port is already allocated", "Bind for", "address already in use")
CLIENT_TIMEOUT = 60
STOP_TIMEOUT = 30
NOT_FOUND_MESSAGE = "Diese Welt gibt es nicht (mehr)."
# Weltordner im Container; Ziel für Mods und Zugangsdatei (write_world_files).
WORLD_PATH = f"{DATA_DIR}/.minetest/worlds/world"
# Höchstens so viele Bytes Inhalt aus der Status-Datei (T-02-18); der Welt-Mod
# schreibt nur Spielernamen, fremder Lua-Code könnte aber beliebig viel schreiben.
STATUS_FILE_MAX = 4096
# Höchstens so viele Bytes Tar-Strom (Kopfblöcke, auch PAX, plus gekappter Inhalt).
STATUS_ARCHIVE_MAX = 64 * 1024
# Das Zählbuch wächst mit jedem je eingeladenen Namen (bis 32 Bytes je Zeile) und
# verliert nie einen: 4 KiB reichten nur für rund 125 Namen, danach fehlte die
# Schlusszeile und die Verbuchung stand still (WR-03). 256 KiB tragen rund 8000.
LEDGER_FILE_MAX = 256 * 1024
LEDGER_ARCHIVE_MAX = LEDGER_FILE_MAX + STATUS_ARCHIVE_MAX
# Die Ereignisdatei ist ein Ringpuffer mit 200 Zeilen (je bis rund 50 Bytes);
# 16 KiB reichen mit Reserve, mehr schreibt nur fremder Lua-Code (T-04.1-07).
EVENTS_FILE_MAX = 16 * 1024
EVENTS_ARCHIVE_MAX = EVENTS_FILE_MAX + STATUS_ARCHIVE_MAX
# Docker-Strom des Weltordners in Stücken dieser Größe (Speicher bleibt konstant).
SNAPSHOT_CHUNK = 2 * 1024 * 1024
# Nur in diesen Zuständen ist map.sqlite konsistent: Der Server-Prozess läuft
# nicht und ist auch nicht eingefroren oder im Neustart (Erfolgskriterium 2).
SNAPSHOT_SAFE_STATES = frozenset({"created", "exited", "dead"})
SNAPSHOT_RUNNING = "Die Welt läuft noch; eine Sicherung braucht eine gestoppte Welt."
# Nur diese Transportfehler sind der seltene Keep-Alive-Abbruch, den ein zweiter
# Leseversuch heilt (Pitfall 4). Timeouts werden nie wiederholt; Achtung:
# ConnectTimeout erbt von ConnectionError UND Timeout, deshalb prüft _read
# Timeout zusätzlich (WR-03), sonst verdoppelte ein schwarzes Loch die Wartezeit.
RETRYABLE_ERRORS = (requests.exceptions.ConnectionError, urllib3.exceptions.ProtocolError)


class ProvisionerError(Exception):
    """Docker hat eine Operation abgelehnt oder sie ist gescheitert."""


class DockerUnavailableError(ProvisionerError):
    """Der Docker-Proxy ist nicht erreichbar."""


class PortInUseError(ProvisionerError):
    """Der Host-Port der Welt ist schon belegt."""

    def __init__(self, port: int) -> None:
        super().__init__(f"Der UDP-Port {port} ist auf dem Server schon belegt.")
        self.port = port


class WorldNotFoundError(ProvisionerError):
    """Der Container existiert nicht oder gehört nicht zu dieser Instanz."""


@dataclass(frozen=True)
class ContainerInfo:
    container_id: str
    name: str
    world_id: str
    status: str
    port: int
    # Aus docker inspect (State) und dem Label gameworld.schema; die Defaults
    # halten positionale Konstruktionen (Fakes, ältere Aufrufer) gültig.
    exit_code: int = 0
    oom_killed: bool = False
    started_at: str = ""
    schema: str = "1"


@dataclass(frozen=True)
class StatusFile:
    """Status-Datei des Welt-Mods: mtime aus dem Archiv-Stat, Inhalt gekappt."""

    mtime: str
    content: bytes


@dataclass(frozen=True)
class MemoryUsage:
    """Arbeitsspeicher einer laufenden Welt in Bytes, wie docker stats ihn zeigt."""

    used: int
    limit: int


def _int_field(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def memory_from_stats(stats: dict[str, Any]) -> tuple[int, int] | None:
    """(belegt, Limit) aus ``container.stats``; fehlende Felder ergeben None.

    Formel wie die docker CLI: usage minus inactive_file (cgroup v2), Fallback
    total_inactive_file (cgroup v1). Nie negativ.
    """
    memory = stats.get("memory_stats")
    if not isinstance(memory, dict):
        return None
    memory = cast(dict[str, Any], memory)
    usage = _int_field(memory, "usage")
    limit = _int_field(memory, "limit")
    if usage is None or limit is None or limit <= 0:
        return None
    raw = memory.get("stats")
    details = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    inactive = _int_field(details, "inactive_file")
    if inactive is None:
        inactive = _int_field(details, "total_inactive_file") or 0
    return max(usage - inactive, 0), limit


def _read_capped(stream: Iterator[bytes], limit: int = STATUS_ARCHIVE_MAX) -> bytes:
    """Liest höchstens ``limit`` Bytes und gibt den Rest des Stroms auf."""
    raw = bytearray()
    try:
        for chunk in stream:
            raw += chunk
            if len(raw) >= limit:
                break
    finally:
        close = getattr(stream, "close", None)
        if callable(close):
            close()
    return bytes(raw[:limit])


def _first_member_content(raw: bytes, limit: int = STATUS_FILE_MAX) -> tuple[bytes, bool]:
    """Inhalt des ersten Tar-Eintrags, höchstens ``limit`` Bytes, und ob er gekappt ist.

    Strom-Modus ("r|"), damit ein gekapptes Archiv beim Öffnen nicht scheitert.
    """
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as tar:
        member = tar.next()
        if member is None or not member.isfile():
            return b"", False
        extracted = tar.extractfile(member)
        if extracted is None:
            return b"", False
        return extracted.read(limit), member.size > limit


def _explanation(exc: docker.errors.APIError) -> str:
    return str(exc.explanation or exc)


def _host_ports(raw: str, lo: int, hi: int) -> set[int]:
    """HostPort-Wert ("30015" oder "30015-30017") als Ports im Bereich."""
    first, _, last = raw.partition("-")
    try:
        start = int(first)
        end = int(last) if last else start
    except ValueError:
        return set()
    return set(range(max(start, lo), min(end, hi) + 1))


def _label_port(labels: dict[str, str]) -> int:
    try:
        return int(labels.get("gameworld.port", "0"))
    except ValueError:
        return 0


class DockerProvisioner:
    def __init__(self, docker_url: str, instance_id: str) -> None:
        self._docker_url = docker_url
        self._instance_id = instance_id
        self._client: docker.DockerClient | None = None

    # Interne Helfer

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self._docker_url, version="auto", timeout=CLIENT_TIMEOUT)
        return self._client

    @contextlib.contextmanager
    def _guarded(self) -> Iterator[None]:
        """Bildet jeden Transportfehler auf DockerUnavailableError ab.

        Antworten des Docker-Daemons (APIError) sind keine Verbindungsfehler: Sie
        werden zu WorldNotFoundError bzw. ProvisionerError mit deutscher Meldung,
        nie zu DockerUnavailableError. Die Reihenfolge der Zweige ist deshalb
        wichtig: APIError erbt selbst von DockerException.
        """
        try:
            yield
        except ProvisionerError:
            raise
        except docker.errors.NotFound as exc:
            raise WorldNotFoundError(f"Docker kennt das Objekt nicht: {_explanation(exc)}") from exc
        except docker.errors.APIError as exc:
            raise ProvisionerError(f"Docker hat die Anfrage abgelehnt: {_explanation(exc)}") from exc
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            urllib3.exceptions.ProtocolError,
            docker.errors.DockerException,
        ) as exc:
            self._client = None
            raise DockerUnavailableError(
                f"Gameworld erreicht den Docker-Proxy unter {self._docker_url} nicht. "
                "Bitte prüfen, ob der Dienst gameworld-docker-proxy läuft."
            ) from exc

    def _read[T](self, operation: Callable[[], T]) -> T:
        """Lesender Aufruf mit genau einem zweiten Versuch nach einem Verbindungsabbruch.

        Der HAProxy im tecnativa-Proxy schließt Keep-Alive-Verbindungen nach
        ``timeout http-keep-alive 10s``; trifft ein Request genau diese Lücke,
        endet er mit "Remote end closed connection" (Pitfall 4). _guarded hat den
        Client dann schon verworfen, der zweite Versuch läuft mit frischer
        Verbindung. Nur für lesende Aufrufe: Mutationen werden nie wiederholt.
        """
        try:
            with self._guarded():
                return operation()
        except DockerUnavailableError as exc:
            cause = exc.__cause__
            if not isinstance(cause, RETRYABLE_ERRORS) or isinstance(cause, requests.exceptions.Timeout):
                raise
            LOG.info("Verbindung zum Docker-Proxy abgebrochen, zweiter Leseversuch")
        with self._guarded():
            return operation()

    def _is_owned(self, container: Container, world_id: str) -> bool:
        """Zweite Prüfung am Ergebnis, falls ein Filter des Proxys ignoriert würde."""
        labels = container.labels or {}
        return (
            labels.get("gameworld.managed") == "true"
            and labels.get("gameworld.instance") == self._instance_id
            and labels.get("gameworld.world_id") == world_id
        )

    def _owned(self, world_id: str) -> Container:
        """Der Container dieser Welt, nur mit eigenem Label und eigener Instanz.

        Jede Mutation löst den Container hierüber auf, nie über einen Namen oder
        eine ID von außen: Über den pfadbasierten Proxy dürfen nie fremde
        Container (Nextcloud, Findling, andere Gameworld-Instanzen) angefasst werden.
        """
        containers = self._docker().containers.list(
            all=True,
            filters={
                "label": [
                    "gameworld.managed=true",
                    f"gameworld.instance={self._instance_id}",
                    f"gameworld.world_id={world_id}",
                ]
            },
        )
        owned = [container for container in containers if self._is_owned(container, world_id)]
        if not owned:
            raise WorldNotFoundError(NOT_FOUND_MESSAGE)
        return owned[0]

    # Öffentliche Operationen

    def ensure_image(self) -> None:
        with self._guarded():
            images = self._docker().images
            try:
                images.get(LUANTI_IMAGE)
            except docker.errors.ImageNotFound:
                images.pull(LUANTI_IMAGE)

    def create_world_container(
        self, world_id: str, host_port: int, payload: WorldPayload, *, reuse_volume: bool = False
    ) -> str:
        """Erzeugt den Container der Welt und spielt die Weltdateien ein.

        Spec (Speicherlimit, Labels) und Inhalt kommen beide aus ``payload``,
        damit eine Neuerzeugung nie ein anderes Spiel oder Limit bekommt. Das
        Tar geht als Datei-Objekt an ``put_archive``; schließen muss es der Aufrufer.

        ``reuse_volume`` steht für eine Neuerzeugung mit vorhandenem Volume (etwa
        nach einer Port-Kollision): Scheitert dann das Einspielen, bleibt das
        Volume mit den Weltdaten erhalten und nur der Container wird entfernt.
        """
        with self._guarded():
            api = self._docker()
            spec = cast(dict[str, Any], world_spec(self._instance_id, world_id, host_port, payload.preset))
            container = api.containers.create(**spec)
            try:
                if not container.put_archive(DATA_DIR, payload.archive):
                    raise ProvisionerError("Docker hat die Weltdaten nicht angenommen.")
            except Exception:
                # Halb erzeugte Welt nicht liegen lassen; der Aufrufer kennt die ID noch nicht.
                with contextlib.suppress(Exception):
                    container.remove(force=True, v=False)
                if not reuse_volume:
                    with contextlib.suppress(Exception):
                        api.volumes.get(str(spec["name"])).remove(force=True)
                raise
            return str(container.id)

    def start_world(self, world_id: str) -> None:
        with self._guarded():
            container = self._owned(world_id)
            try:
                container.start()
            except docker.errors.NotFound:
                # Container zwischen _owned() und start() verschwunden (Race mit
                # Löschen/Prune): _guarded bildet das auf WorldNotFoundError ab,
                # nicht auf einen 500er. NotFound erbt von APIError, der Zweig
                # muss deshalb vor dem APIError-Zweig stehen.
                raise
            except docker.errors.APIError as exc:
                explanation = _explanation(exc)
                if exc.status_code == 500 and any(marker in explanation for marker in PORT_CONFLICT_MARKERS):
                    raise PortInUseError(_label_port(container.labels or {})) from exc
                raise ProvisionerError(f"Docker hat den Start der Welt abgelehnt: {explanation}") from exc

    def write_world_files(self, world_id: str, archive: bytes) -> None:
        """Spielt ein Tar (Pfade relativ zum Weltordner) in die Welt ein, laufend oder gestoppt.

        Für Welt-Mods und Zugangsdatei. Nur ``put_archive`` über _owned, kein
        exec: ``PUT /containers/{id}/archive`` fällt beim tecnativa-Proxy unter
        CONTAINERS=1 und POST=1, eine neue Freigabe braucht es nicht. Das Ziel
        liegt im Volume, das read-only Root-Dateisystem stört deshalb nicht.
        """
        with self._guarded():
            container = self._owned(world_id)
            if not container.put_archive(WORLD_PATH, archive):
                raise ProvisionerError("Docker hat die Zugangsliste der Welt nicht angenommen.")

    def snapshot_to[T](self, world_id: str, write: Callable[[Iterator[bytes]], T]) -> T:
        """Reicht den Tar-Strom des Weltordners an ``write`` und gibt dessen Ergebnis zurück.

        Nur bei gestopptem Container (nach ``reload``): Aus einer laufenden Welt
        wäre map.sqlite inkonsistent (T-05-04), get_archive wird dann nie
        aufgerufen. Gelesen wird innerhalb desselben _guarded-Blocks, damit auch
        ein Abbruch mitten im Strom als DockerUnavailableError ankommt
        (Pitfall 8); kein _read und kein zweiter Versuch, ein halb gelesener
        Strom darf nie still neu beginnen. Der Strom wird immer geschlossen.
        """
        with self._guarded():
            container = self._owned(world_id)
            container.reload()
            if container.status not in SNAPSHOT_SAFE_STATES:
                raise ProvisionerError(SNAPSHOT_RUNNING)
            stream, _stat = container.get_archive(WORLD_PATH, chunk_size=SNAPSHOT_CHUNK)
            try:
                return write(stream)
            finally:
                close = getattr(stream, "close", None)
                if callable(close):
                    close()

    def put_world_archive(self, world_id: str, archive: BinaryIO) -> None:
        """Spielt ein Restore-Tar (Datei-Objekt, auch gzip) in den Weltordner ein.

        Namen im Tar sind relativ zum Weltordner. Schließen muss der Aufrufer.
        """
        with self._guarded():
            container = self._owned(world_id)
            if not container.put_archive(WORLD_PATH, archive):
                raise ProvisionerError("Docker hat die Sicherung nicht angenommen.")

    def stop(self, world_id: str, *, timeout: int = STOP_TIMEOUT) -> None:
        """Stoppt die Welt; ``timeout`` kürzer nur beim Aufräumen unter Frist (teardown_all)."""
        with self._guarded():
            # Client-Timeout (60 s) liegt über dem Stop-Timeout, Luanti speichert vorher.
            self._owned(world_id).stop(timeout=timeout)

    def remove_world(self, world_id: str, *, keep_volume: bool) -> None:
        """Entfernt den Container der Welt und auf Wunsch ihr Volume.

        Fehlt der Container schon, ist das kein Fehler: Löschen soll auch eine
        Welt mit verschwundenem Container aufräumen. Das Volume trägt immer das
        Präfix der eigenen Instanz, ein fremdes Volume kann so nicht getroffen werden.
        """
        with self._guarded():
            api = self._docker()
            try:
                self._owned(world_id).remove(force=True, v=False)
            except (WorldNotFoundError, docker.errors.NotFound):
                LOG.info("Welt %s hat keinen eigenen Container mehr", world_id)
            if not keep_volume:
                with contextlib.suppress(docker.errors.NotFound):
                    api.volumes.get(resource_name(self._instance_id, world_id)).remove()

    def volume_exists(self, world_id: str) -> bool:
        """Gibt es das Volume der Welt (Weltdaten) noch? Name immer mit eigenem Instanz-Präfix."""
        return self._read(lambda: self._volume_exists(world_id))

    def _volume_exists(self, world_id: str) -> bool:
        try:
            self._docker().volumes.get(resource_name(self._instance_id, world_id))
        except docker.errors.NotFound:
            return False
        return True

    def used_host_ports(self, lo: int, hi: int) -> set[int]:
        """Host-Ports im Bereich, die irgendein Container des Hosts bindet (auch fremde)."""
        return self._read(lambda: self._used_host_ports(lo, hi))

    def _used_host_ports(self, lo: int, hi: int) -> set[int]:
        used: set[int] = set()
        for container in self._docker().containers.list(all=True, ignore_removed=True):
            bindings = (container.attrs.get("HostConfig") or {}).get("PortBindings") or {}
            for entries in bindings.values():
                for entry in entries or []:
                    used.update(_host_ports(str(entry.get("HostPort") or ""), lo, hi))
        return used

    def list_managed(self) -> dict[str, ContainerInfo]:
        """Eigene Welt-Container mit Zustand aus docker inspect.

        docker-py liefert bei ``containers.list`` (nicht sparse) volle
        Inspect-Daten in ``container.attrs``; daraus kommen ExitCode, OOMKilled
        und StartedAt für das Statusmodell.
        """
        return self._read(self._list_managed)

    def _list_managed(self) -> dict[str, ContainerInfo]:
        containers = self._docker().containers.list(
            all=True,
            filters={"label": ["gameworld.managed=true", f"gameworld.instance={self._instance_id}"]},
        )
        result: dict[str, ContainerInfo] = {}
        for container in containers:
            labels = container.labels or {}
            world_id = labels.get("gameworld.world_id")
            if not world_id:
                continue
            state = (container.attrs or {}).get("State") or {}
            result[world_id] = ContainerInfo(
                container_id=str(container.id),
                name=str(container.name),
                world_id=world_id,
                status=str(container.status),
                port=_label_port(labels),
                exit_code=int(state.get("ExitCode") or 0),
                oom_killed=bool(state.get("OOMKilled")),
                started_at=str(state.get("StartedAt") or ""),
                schema=str(labels.get("gameworld.schema", "1")),
            )
        return result

    def read_status_file(self, world_id: str) -> StatusFile | None:
        """Status-Datei des Welt-Mods (mtime und gekappter Inhalt) oder None.

        None heißt: Docker kennt die Datei nicht, der Server hat sie in diesem
        Volume noch nie geschrieben. Den Container löst _owned auf, fremde
        Container sind ausgeschlossen. Kein Follow-Stream (Pitfall 8).
        """
        return self._read(lambda: self._read_world_file(world_id, PLAYERS_FILE, "Die Status-Datei der Welt"))

    def read_access_state(self, world_id: str) -> StatusFile | None:
        """State-Datei des Zugangs-Mods (mtime und gekappter Inhalt) oder None.

        Der Mod schreibt sie, sobald er eine Zugangsdatei geladen hat. Fehlt sie
        oder ist sie älter als der Start des Containers, läuft die Welt noch ohne
        geladenen Zugangsschutz (03-RESEARCH.md Pitfall 4). Gleiche Kappung und
        Fehlerabbildung wie bei der Status-Datei.
        """
        return self._read(lambda: self._read_world_file(world_id, STATE_FILE, "Der Zugangsstand der Welt"))

    def read_time_ledger(self, world_id: str) -> StatusFile | None:
        """Zählbuch des Zeit-Mods (mtime und gekappter Inhalt) oder None.

        Der Mod schreibt es beim Start, im Takt bei verbundenen Spielern und beim
        Verlassen. Über get_archive, deshalb auch bei gestoppter Welt lesbar; kein
        exec. Gleiche Fehlerabbildung wie bei der Status-Datei, aber eine eigene,
        größere Kappung (LEDGER_FILE_MAX, WR-03); wird sie trotzdem erreicht, steht
        eine Warnung im Log statt eines stillen Stillstands der Verbuchung.
        """
        return self._read(
            lambda: self._read_world_file(
                world_id,
                LEDGER_FILE,
                "Das Spielzeit-Zählbuch der Welt",
                file_max=LEDGER_FILE_MAX,
                archive_max=LEDGER_ARCHIVE_MAX,
                warn_truncated=True,
            )
        )

    def read_events(self, world_id: str) -> StatusFile | None:
        """Ereignisdatei des Zugangs-Mods (mtime und gekappter Inhalt) oder None.

        None heißt: Der Mod hat die Datei in diesem Volume noch nie geschrieben
        (alter Mod ohne Ereignisse). Eigene Kappung EVENTS_FILE_MAX (T-04.1-07);
        der Inhalt kommt nie ins Log, nur Welt-ID und Größe.
        """
        return self._read(
            lambda: self._read_world_file(
                world_id,
                EVENTS_FILE,
                "Die Ereignisdatei der Welt",
                file_max=EVENTS_FILE_MAX,
                archive_max=EVENTS_ARCHIVE_MAX,
                warn_truncated=True,
            )
        )

    def _read_world_file(
        self,
        world_id: str,
        path: str,
        label: str,
        *,
        file_max: int = STATUS_FILE_MAX,
        archive_max: int = STATUS_ARCHIVE_MAX,
        warn_truncated: bool = False,
    ) -> StatusFile | None:
        container = self._owned(world_id)
        try:
            stream, stat = container.get_archive(path)
        except docker.errors.NotFound:
            return None
        try:
            content, truncated = _first_member_content(_read_capped(stream, archive_max), file_max)
        except (tarfile.TarError, EOFError) as exc:
            # Gekappter oder abgebrochener Strom, Datei mitten im Umbenennen: Der
            # Inhalt stammt aus von Lua beschreibbarer Datei. Als ProvisionerError
            # bleibt der Fehler an dieser einen Welt (WR-04), ohne zweiten Versuch.
            raise ProvisionerError(f"{label} ist nicht lesbar.") from exc
        if truncated and warn_truncated:
            # Nur Größe und Grenze ins Log, nie den Inhalt.
            LOG.warning("Welt %s: %s ist größer als %d Bytes und wurde gekappt", world_id, label, file_max)
        return StatusFile(mtime=str((stat or {}).get("mtime") or ""), content=content)

    def memory_bytes(self, world_id: str) -> MemoryUsage | None:
        """RAM der Welt oder None, wenn der Container nicht läuft.

        ``one_shot`` liefert die Werte ohne die Sekunde Wartezeit für die
        CPU-Vorwerte (7 bis 13 ms laut Spike). Den Container löst _owned auf,
        fremde Container sind ausgeschlossen (T-02-26).
        """
        return self._read(lambda: self._memory_bytes(world_id))

    def _memory_bytes(self, world_id: str) -> MemoryUsage | None:
        container = self._owned(world_id)
        if container.status != "running":
            return None
        stats = cast(dict[str, Any], container.stats(stream=False, one_shot=True))
        values = memory_from_stats(stats)
        return None if values is None else MemoryUsage(used=values[0], limit=values[1])
