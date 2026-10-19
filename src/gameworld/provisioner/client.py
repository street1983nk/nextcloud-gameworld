"""Der einzige Docker-Client von Gameworld.

Alle Methoden sind synchron; Aufrufer kapseln sie mit ``anyio.to_thread.run_sync``.
Jede öffentliche Methode läuft durch :meth:`DockerProvisioner._guarded`, damit
Verbindungs- und Transportfehler immer als :class:`DockerUnavailableError`
ankommen, auch wenn der Client schon einmal verbunden war und der Proxy erst
später wegbricht. Aufrufer sehen nie rohe requests- oder urllib3-Ausnahmen.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

import docker
import docker.errors
import requests.exceptions
import urllib3.exceptions
from docker.models.containers import Container

from gameworld.provisioner.spec import DATA_DIR, LUANTI_IMAGE, world_spec

LOG = logging.getLogger(__name__)

PORT_CONFLICT_MARKERS = ("port is already allocated", "Bind for", "address already in use")
CLIENT_TIMEOUT = 60


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


def _explanation(exc: docker.errors.APIError) -> str:
    return str(exc.explanation or exc)


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

    def _owned(self, container: Container) -> Container:
        """Jede Mutation nur an Containern mit eigenem Label und eigener Instanz."""
        labels = container.labels or {}
        if labels.get("gameworld.managed") != "true" or labels.get("gameworld.instance") != self._instance_id:
            raise WorldNotFoundError("Der Container gehört nicht zu dieser Gameworld-Instanz.")
        return container

    # Öffentliche Operationen

    def ensure_image(self) -> None:
        with self._guarded():
            images = self._docker().images
            try:
                images.get(LUANTI_IMAGE)
            except docker.errors.ImageNotFound:
                images.pull(LUANTI_IMAGE)

    def create_world_container(self, world_id: str, host_port: int, payload: bytes) -> str:
        with self._guarded():
            api = self._docker()
            spec = cast(dict[str, Any], world_spec(self._instance_id, world_id, host_port))
            container = api.containers.create(**spec)
            try:
                if not container.put_archive(DATA_DIR, payload):
                    raise ProvisionerError("Docker hat die Weltdaten nicht angenommen.")
            except Exception:
                # Halb erzeugte Welt nicht liegen lassen; der Aufrufer kennt die ID noch nicht.
                with contextlib.suppress(Exception):
                    container.remove(force=True, v=True)
                    api.volumes.get(str(spec["name"])).remove(force=True)
                raise
            return str(container.id)

    def start(self, container_id: str) -> None:
        with self._guarded():
            container = self._owned(self._docker().containers.get(container_id))
            try:
                container.start()
            except docker.errors.APIError as exc:
                explanation = _explanation(exc)
                if exc.status_code == 500 and any(marker in explanation for marker in PORT_CONFLICT_MARKERS):
                    raise PortInUseError(_label_port(container.labels or {})) from exc
                raise ProvisionerError(f"Docker hat den Start der Welt abgelehnt: {explanation}") from exc

    def discard(self, container_id: str, *, keep_volume: bool) -> None:
        with self._guarded():
            api = self._docker()
            try:
                container = self._owned(api.containers.get(container_id))
            except WorldNotFoundError:
                LOG.warning("Container %s gehört nicht zu dieser Instanz, wird nicht entfernt", container_id)
                return
            except docker.errors.NotFound:
                return
            name = container.name
            container.remove(force=True, v=False)
            if not keep_volume and name:
                with contextlib.suppress(docker.errors.NotFound):
                    api.volumes.get(name).remove()

    def list_managed(self) -> dict[str, ContainerInfo]:
        with self._guarded():
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
                result[world_id] = ContainerInfo(
                    container_id=str(container.id),
                    name=str(container.name),
                    world_id=world_id,
                    status=str(container.status),
                    port=_label_port(labels),
                )
            return result
