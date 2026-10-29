"""The only Docker client of Gameworld.

All methods are synchronous; callers wrap them with ``anyio.to_thread.run_sync``.
Every public method runs through :meth:`DockerProvisioner._guarded`, so that
connection and transport errors always arrive as :class:`DockerUnavailableError`,
even if the client was connected once and the proxy only breaks away
later. Callers never see raw requests or urllib3 exceptions.
"""

from __future__ import annotations

import contextlib
import io
import logging
import re
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
# World folder in the container; target for mods and access file (write_world_files).
WORLD_PATH = f"{DATA_DIR}/.minetest/worlds/world"
# At most this many bytes of content from the status file (T-02-18); the world mod
# writes only player names, but foreign Lua code could write arbitrarily much.
STATUS_FILE_MAX = 4096
# At most this many bytes of tar stream (head blocks, also PAX, plus truncated content).
STATUS_ARCHIVE_MAX = 64 * 1024
# The ledger grows with every name ever invited (up to 32 bytes per line) and
# never loses one: 4 KiB sufficed for only about 125 names, after that the
# closing line was missing and booking stood still (WR-03). 256 KiB carry about 8000.
LEDGER_FILE_MAX = 256 * 1024
LEDGER_ARCHIVE_MAX = LEDGER_FILE_MAX + STATUS_ARCHIVE_MAX
# The event file is a ring buffer with 200 lines (each up to about 50 bytes);
# 16 KiB suffice with reserve, more is written only by foreign Lua code (T-04.1-07).
EVENTS_FILE_MAX = 16 * 1024
EVENTS_ARCHIVE_MAX = EVENTS_FILE_MAX + STATUS_ARCHIVE_MAX
# Docker stream of the world folder in chunks of this size (memory stays constant).
SNAPSHOT_CHUNK = 2 * 1024 * 1024
# Only in these states is map.sqlite consistent: the server process does
# not run and is neither frozen nor restarting (success criterion 2).
SNAPSHOT_SAFE_STATES = frozenset({"created", "exited", "dead"})
SNAPSHOT_RUNNING = "Die Welt läuft noch; eine Sicherung braucht eine gestoppte Welt."
# Templates of Docker errors (D-25). Docker's own explanation, the proxy URL and the
# port are inserted unchanged; only the German frame is translated.
TEXT_DOCKER_NOT_FOUND = "Docker kennt das Objekt nicht: {explanation}"
TEXT_DOCKER_REJECTED = "Docker hat die Anfrage abgelehnt: {explanation}"
TEXT_DOCKER_UNREACHABLE = (
    "Gameworld erreicht den Docker-Proxy unter {docker_url} nicht. "
    "Bitte prüfen, ob der Dienst gameworld-docker-proxy läuft."
)
TEXT_START_REJECTED = "Docker hat den Start der Welt abgelehnt: {explanation}"
TEXT_PORT_IN_USE = "Der UDP-Port {port} ist auf dem Server schon belegt."
# Fixed Docker refusals (D-25); they can reach logs, last_error and answers via str(exc).
MSG_PAYLOAD_REJECTED = "Docker hat die Weltdaten nicht angenommen."
MSG_ACCESS_LIST_REJECTED = "Docker hat die Zugangsliste der Welt nicht angenommen."
MSG_BACKUP_REJECTED = "Docker hat die Sicherung nicht angenommen."
MSG_ORPHAN_BAD_ID = "Ungültige Container-ID."
MSG_ORPHAN_CONTAINER_REFUSED = "Der Container gehört zu dieser Installation oder nicht zu Gameworld."
MSG_ORPHAN_VOLUME_REFUSED = "Das Volume gehört zu dieser Installation oder nicht zu Gameworld."
MSG_VOLUME_IN_USE = "Das Volume wird noch benutzt."
MSG_STATUS_FILE_UNREADABLE = "Die Status-Datei der Welt ist nicht lesbar."
MSG_ACCESS_STATE_UNREADABLE = "Der Zugangsstand der Welt ist nicht lesbar."
MSG_LEDGER_UNREADABLE = "Das Spielzeit-Zählbuch der Welt ist nicht lesbar."
MSG_EVENTS_UNREADABLE = "Die Ereignisdatei der Welt ist nicht lesbar."
# Only these transport errors are the rare keep-alive abort that a second
# read attempt heals (pitfall 4). Timeouts are never repeated; note:
# ConnectTimeout inherits from ConnectionError AND Timeout, therefore _read
# additionally checks Timeout (WR-03), otherwise a black hole would double the wait.
RETRYABLE_ERRORS = (requests.exceptions.ConnectionError, urllib3.exceptions.ProtocolError)
# Leftovers of foreign or earlier installations (06-08, ROADMAP criterion 3): only
# volumes by the naming scheme resource_name, never compose volumes with an underscore
# (e.g. those of the dev stack) and never names that merely begin with "gameworld".
ORPHAN_VOLUME_PATTERN = re.compile(r"^gameworld-[a-z0-9-]{1,120}$")
ORPHAN_ID_PATTERN = re.compile(r"^[0-9a-f]{12,64}$")


class ProvisionerError(Exception):
    """Docker refused an operation or it failed."""


class DockerUnavailableError(ProvisionerError):
    """The Docker proxy is not reachable."""


class PortInUseError(ProvisionerError):
    """The host port of the world is already taken."""

    def __init__(self, port: int) -> None:
        super().__init__(TEXT_PORT_IN_USE.format(port=port))
        self.port = port


class WorldNotFoundError(ProvisionerError):
    """The container does not exist or does not belong to this instance."""


class OrphanRefusedError(ProvisionerError):
    """The object belongs to this installation or not to Gameworld; it is never removed."""


class OrphanInUseError(ProvisionerError):
    """The volume is still used by a container (Docker 409)."""


@dataclass(frozen=True)
class OrphanContainer:
    """World container of a foreign or earlier Gameworld instance."""

    id: str
    name: str
    instance: str
    state: str
    created: str


@dataclass(frozen=True)
class OrphanVolume:
    """Volume following the Gameworld naming scheme without a world row of its own."""

    name: str
    created: str


@dataclass(frozen=True)
class Orphans:
    containers: list[OrphanContainer]
    volumes: list[OrphanVolume]


@dataclass(frozen=True)
class ContainerInfo:
    container_id: str
    name: str
    world_id: str
    status: str
    port: int
    # From docker inspect (State) and the label gameworld.schema; the defaults
    # keep positional constructions (fakes, older callers) valid.
    exit_code: int = 0
    oom_killed: bool = False
    started_at: str = ""
    schema: str = "1"


@dataclass(frozen=True)
class StatusFile:
    """Status file of the world mod: mtime from the archive stat, content truncated."""

    mtime: str
    content: bytes


@dataclass(frozen=True)
class MemoryUsage:
    """Memory of a running world in bytes, as docker stats shows it."""

    used: int
    limit: int


def _int_field(source: dict[str, Any], key: str) -> int | None:
    value = source.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def memory_from_stats(stats: dict[str, Any]) -> tuple[int, int] | None:
    """(used, limit) from ``container.stats``; missing fields yield None.

    Formula like the docker CLI: usage minus inactive_file (cgroup v2), fallback
    total_inactive_file (cgroup v1). Never negative.
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
    """Reads at most ``limit`` bytes and gives up the rest of the stream."""
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
    """Content of the first tar entry, at most ``limit`` bytes, and whether it is truncated.

    Stream mode ("r|"), so that a truncated archive does not fail on opening.
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
    """HostPort value ("30015" or "30015-30017") as ports in the range."""
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

    # Internal helpers

    def _docker(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.DockerClient(base_url=self._docker_url, version="auto", timeout=CLIENT_TIMEOUT)
        return self._client

    @contextlib.contextmanager
    def _guarded(self) -> Iterator[None]:
        """Map every transport error to DockerUnavailableError.

        Answers of the Docker daemon (APIError) are no connection errors: they
        become WorldNotFoundError or ProvisionerError with a German message,
        never DockerUnavailableError. The order of the branches is therefore
        important: APIError itself inherits from DockerException.
        """
        try:
            yield
        except ProvisionerError:
            raise
        except docker.errors.NotFound as exc:
            raise WorldNotFoundError(TEXT_DOCKER_NOT_FOUND.format(explanation=_explanation(exc))) from exc
        except docker.errors.APIError as exc:
            raise ProvisionerError(TEXT_DOCKER_REJECTED.format(explanation=_explanation(exc))) from exc
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            urllib3.exceptions.ProtocolError,
            docker.errors.DockerException,
        ) as exc:
            self._client = None
            raise DockerUnavailableError(TEXT_DOCKER_UNREACHABLE.format(docker_url=self._docker_url)) from exc

    def _read[T](self, operation: Callable[[], T]) -> T:
        """Reading call with exactly one second attempt after a connection abort.

        The HAProxy in the tecnativa proxy closes keep-alive connections after
        ``timeout http-keep-alive 10s``; if a request hits exactly this gap,
        it ends with "Remote end closed connection" (pitfall 4). _guarded has
        discarded the client by then, the second attempt runs with a fresh
        connection. Only for reading calls: mutations are never repeated.
        """
        try:
            with self._guarded():
                return operation()
        except DockerUnavailableError as exc:
            cause = exc.__cause__
            if not isinstance(cause, RETRYABLE_ERRORS) or isinstance(cause, requests.exceptions.Timeout):
                raise
            LOG.info("Connection to the Docker proxy aborted, second read attempt")
        with self._guarded():
            return operation()

    def _is_owned(self, container: Container, world_id: str) -> bool:
        """Second check on the result, in case a filter of the proxy were ignored."""
        labels = container.labels or {}
        return (
            labels.get("gameworld.managed") == "true"
            and labels.get("gameworld.instance") == self._instance_id
            and labels.get("gameworld.world_id") == world_id
        )

    def _owned(self, world_id: str) -> Container:
        """The container of this world, only with the own label and own instance.

        Every mutation resolves the container through this, never via a name or
        an ID from outside: through the path-based proxy, foreign containers
        (Nextcloud, Findling, other Gameworld instances) must never be touched.
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

    # Public operations

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
        """Create the container of the world and install the world files.

        Spec (memory limit, labels) and content both come from ``payload``,
        so that a re-creation never gets a different game or limit. The
        tar goes to ``put_archive`` as a file object; the caller must close it.

        ``reuse_volume`` stands for a re-creation with an existing volume (e.g.
        after a port collision): if installing then fails, the volume
        with the world data is kept and only the container is removed.
        """
        with self._guarded():
            api = self._docker()
            spec = cast(dict[str, Any], world_spec(self._instance_id, world_id, host_port, payload.preset))
            container = api.containers.create(**spec)
            try:
                if not container.put_archive(DATA_DIR, payload.archive):
                    raise ProvisionerError(MSG_PAYLOAD_REJECTED)
            except Exception:
                # Do not leave a half-created world behind; the caller does not know the ID yet.
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
                # Container vanished between _owned() and start() (race with
                # delete/prune): _guarded maps that to WorldNotFoundError,
                # not to a 500. NotFound inherits from APIError, so the branch
                # must come before the APIError branch.
                raise
            except docker.errors.APIError as exc:
                explanation = _explanation(exc)
                if exc.status_code == 500 and any(marker in explanation for marker in PORT_CONFLICT_MARKERS):
                    raise PortInUseError(_label_port(container.labels or {})) from exc
                raise ProvisionerError(TEXT_START_REJECTED.format(explanation=explanation)) from exc

    def write_world_files(self, world_id: str, archive: bytes) -> None:
        """Install a tar (paths relative to the world folder) into the world, running or stopped.

        For world mods and access file. Only ``put_archive`` via _owned, no
        exec: ``PUT /containers/{id}/archive`` falls under CONTAINERS=1 and
        POST=1 of the tecnativa proxy, a new permission is not needed. The target
        is in the volume, so the read-only root file system does not interfere.
        """
        with self._guarded():
            container = self._owned(world_id)
            if not container.put_archive(WORLD_PATH, archive):
                raise ProvisionerError(MSG_ACCESS_LIST_REJECTED)

    def snapshot_to[T](self, world_id: str, write: Callable[[Iterator[bytes]], T]) -> T:
        """Hand the tar stream of the world folder to ``write`` and return its result.

        Only with a stopped container (after ``reload``): from a running world
        map.sqlite would be inconsistent (T-05-04), get_archive is then never
        called. Reading happens inside the same _guarded block, so that even
        an abort in the middle of the stream arrives as DockerUnavailableError
        (pitfall 8); no _read and no second attempt, a half-read
        stream must never silently start over. The stream is always closed.
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
        """Install a restore tar (file object, also gzip) into the world folder.

        Names in the tar are relative to the world folder. The caller must close it.
        """
        with self._guarded():
            container = self._owned(world_id)
            if not container.put_archive(WORLD_PATH, archive):
                raise ProvisionerError(MSG_BACKUP_REJECTED)

    def stop(self, world_id: str, *, timeout: int = STOP_TIMEOUT) -> None:
        """Stops the world; ``timeout`` shorter only for cleanup under a deadline (teardown_all)."""
        with self._guarded():
            # Client timeout (60 s) is above the stop timeout, Luanti saves beforehand.
            self._owned(world_id).stop(timeout=timeout)

    def remove_world(self, world_id: str, *, keep_volume: bool) -> None:
        """Remove the container of the world and, on request, its volume.

        If the container is already missing, that is no error: deleting should also clean up
        a world with a vanished container. The volume always carries the
        prefix of the own instance, so a foreign volume cannot be hit.
        """
        with self._guarded():
            api = self._docker()
            try:
                self._owned(world_id).remove(force=True, v=False)
            except (WorldNotFoundError, docker.errors.NotFound):
                LOG.info("World %s has no own container anymore", world_id)
            if not keep_volume:
                with contextlib.suppress(docker.errors.NotFound):
                    api.volumes.get(resource_name(self._instance_id, world_id)).remove()

    def volume_exists(self, world_id: str) -> bool:
        """Does the volume of the world (world data) still exist? Name always with the own instance prefix."""
        return self._read(lambda: self._volume_exists(world_id))

    def _volume_exists(self, world_id: str) -> bool:
        try:
            self._docker().volumes.get(resource_name(self._instance_id, world_id))
        except docker.errors.NotFound:
            return False
        return True

    def used_host_ports(self, lo: int, hi: int) -> set[int]:
        """Host ports in the range that any container of the host binds (also foreign ones)."""
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
        """Own world containers with state from docker inspect.

        docker-py returns full inspect data in ``container.attrs`` for
        ``containers.list`` (not sparse); ExitCode, OOMKilled
        and StartedAt for the status model come from there.
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

    def _is_foreign(self, container: Container) -> bool:
        """Gameworld world containers (label managed), but not from this instance."""
        labels = container.labels or {}
        return labels.get("gameworld.managed") == "true" and labels.get("gameworld.instance") != self._instance_id

    def list_orphans(self, owned_volumes: set[str]) -> Orphans:
        """Leftovers of other installations: foreign world containers and volumes without a world.

        Read only. ``owned_volumes`` are the volume names of all own
        world rows (the provisioner does not know the database); they never
        appear. Containers without the label gameworld.managed=true never appear, even
        if their name begins with gameworld. Filters of the proxy are checked
        a second time on the result.
        """
        return self._read(lambda: self._list_orphans(owned_volumes))

    def _list_orphans(self, owned_volumes: set[str]) -> Orphans:
        api = self._docker()
        containers = [
            OrphanContainer(
                id=str(container.id),
                name=str(container.name),
                instance=str((container.labels or {}).get("gameworld.instance", "")),
                state=str(container.status),
                created=str((container.attrs or {}).get("Created") or ""),
            )
            for container in api.containers.list(all=True, filters={"label": ["gameworld.managed=true"]})
            if self._is_foreign(container)
        ]
        volumes = [
            OrphanVolume(name=str(volume.name), created=str((volume.attrs or {}).get("CreatedAt") or ""))
            for volume in api.volumes.list(filters={"name": "gameworld-"})
            if ORPHAN_VOLUME_PATTERN.fullmatch(str(volume.name)) and str(volume.name) not in owned_volumes
        ]
        containers.sort(key=lambda item: item.name)
        volumes.sort(key=lambda item: item.name)
        return Orphans(containers=containers, volumes=volumes)

    def remove_orphan_container(self, container_id: str) -> None:
        """Remove a foreign world container; the volume stays (v=False).

        The container is fetched fresh and checked on the object (label managed,
        foreign instance, ID matches), never removed via an unchecked ID. If
        it is already missing, that is no error.
        """
        if not ORPHAN_ID_PATTERN.fullmatch(container_id):
            raise OrphanRefusedError(MSG_ORPHAN_BAD_ID)
        with self._guarded():
            try:
                container = self._docker().containers.get(container_id)
            except docker.errors.NotFound:
                return
            if not str(container.id).startswith(container_id) or not self._is_foreign(container):
                raise OrphanRefusedError(MSG_ORPHAN_CONTAINER_REFUSED)
            try:
                container.remove(force=True, v=False)
            except docker.errors.NotFound:
                return

    def remove_orphan_volume(self, name: str, owned_volumes: set[str]) -> None:
        """Remove a Gameworld volume without a world of its own; in use -> OrphanInUseError.

        Name per ORPHAN_VOLUME_PATTERN and not in ``owned_volumes``, otherwise
        OrphanRefusedError, before Docker is even asked. If it is already
        missing, that is no error.
        """
        if not ORPHAN_VOLUME_PATTERN.fullmatch(name) or name in owned_volumes:
            raise OrphanRefusedError(MSG_ORPHAN_VOLUME_REFUSED)
        with self._guarded():
            try:
                volume = self._docker().volumes.get(name)
            except docker.errors.NotFound:
                return
            if str(volume.name) != name:
                raise OrphanRefusedError(MSG_ORPHAN_VOLUME_REFUSED)
            try:
                volume.remove()
            except docker.errors.NotFound:
                return
            except docker.errors.APIError as exc:
                if exc.status_code == 409:
                    raise OrphanInUseError(MSG_VOLUME_IN_USE) from exc
                raise

    def read_status_file(self, world_id: str) -> StatusFile | None:
        """Status file of the world mod (mtime and truncated content) or None.

        None means: Docker does not know the file, the server has never written it
        in this volume. _owned resolves the container, foreign containers
        are excluded. No follow stream (pitfall 8).
        """
        return self._read(lambda: self._read_world_file(world_id, PLAYERS_FILE, MSG_STATUS_FILE_UNREADABLE))

    def read_access_state(self, world_id: str) -> StatusFile | None:
        """State file of the access mod (mtime and truncated content) or None.

        The mod writes it as soon as it has loaded an access file. If it is missing
        or older than the start of the container, the world still runs without
        loaded access protection (03-RESEARCH.md pitfall 4). Same truncation and
        error mapping as for the status file.
        """
        return self._read(lambda: self._read_world_file(world_id, STATE_FILE, MSG_ACCESS_STATE_UNREADABLE))

    def read_time_ledger(self, world_id: str) -> StatusFile | None:
        """Ledger of the time mod (mtime and truncated content) or None.

        The mod writes it at start, in the tick with connected players and on
        leaving. Via get_archive, therefore readable even with a stopped world; no
        exec. Same error mapping as for the status file, but its own,
        larger truncation (LEDGER_FILE_MAX, WR-03); if it is reached anyway, there is
        a warning in the log instead of a silent standstill of booking.
        """
        return self._read(
            lambda: self._read_world_file(
                world_id,
                LEDGER_FILE,
                MSG_LEDGER_UNREADABLE,
                file_max=LEDGER_FILE_MAX,
                archive_max=LEDGER_ARCHIVE_MAX,
                warn_truncated=True,
            )
        )

    def read_events(self, world_id: str) -> StatusFile | None:
        """Event file of the access mod (mtime and truncated content) or None.

        None means: the mod has never written the file in this volume
        (old mod without events). Own truncation EVENTS_FILE_MAX (T-04.1-07);
        the content never goes into the log, only world ID and size.
        """
        return self._read(
            lambda: self._read_world_file(
                world_id,
                EVENTS_FILE,
                MSG_EVENTS_UNREADABLE,
                file_max=EVENTS_FILE_MAX,
                archive_max=EVENTS_ARCHIVE_MAX,
                warn_truncated=True,
            )
        )

    def _read_world_file(
        self,
        world_id: str,
        path: str,
        unreadable: str,
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
            # Truncated or aborted stream, file in the middle of a rename: the
            # content comes from a file writable by Lua. As a ProvisionerError
            # the error stays with this one world (WR-04), without a second attempt.
            raise ProvisionerError(unreadable) from exc
        if truncated and warn_truncated:
            # Only size and limit into the log, never the content.
            LOG.warning("World %s: %s is larger than %d bytes and was truncated", world_id, path, file_max)
        return StatusFile(mtime=str((stat or {}).get("mtime") or ""), content=content)

    def memory_bytes(self, world_id: str) -> MemoryUsage | None:
        """RAM of the world or None if the container is not running.

        ``one_shot`` returns the values without the second of waiting for the
        CPU previous values (7 to 13 ms per the spike). _owned resolves the container,
        foreign containers are excluded (T-02-26).
        """
        return self._read(lambda: self._memory_bytes(world_id))

    def _memory_bytes(self, world_id: str) -> MemoryUsage | None:
        container = self._owned(world_id)
        if container.status != "running":
            return None
        stats = cast(dict[str, Any], container.stats(stream=False, one_shot=True))
        values = memory_from_stats(stats)
        return None if values is None else MemoryUsage(used=values[0], limit=values[1])
