"""Fehlervertrag des Provisioners ohne Docker: Transportfehler werden immer zu 503-Kandidaten."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import docker
import docker.errors
import pytest
import requests
import requests.exceptions
import urllib3.exceptions

from gameworld.provisioner.client import (
    DockerProvisioner,
    DockerUnavailableError,
    PortInUseError,
    ProvisionerError,
    WorldNotFoundError,
)

INSTANCE = "ab12cd34"
WORLD = "0123456789ab"
LABELS = {
    "gameworld.managed": "true",
    "gameworld.instance": INSTANCE,
    "gameworld.world_id": WORLD,
    "gameworld.port": "30015",
}


def _raise(exc: BaseException) -> Any:
    def call(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise exc

    return call


def _api_error(explanation: str, status: int = 500) -> docker.errors.APIError:
    response = requests.Response()
    response.status_code = status
    return docker.errors.APIError("docker", response=response, explanation=explanation)


class FakeContainer:
    def __init__(self, *, start_error: BaseException | None = None) -> None:
        self.id = "cid"
        self.name = f"gameworld-{INSTANCE}-{WORLD}"
        self.labels = dict(LABELS)
        self.status = "created"
        self._start_error = start_error
        self.removed = False

    def start(self) -> None:
        if self._start_error is not None:
            raise self._start_error

    def remove(self, **kwargs: object) -> None:
        del kwargs
        self.removed = True


class FakeClient:
    """Steht für docker.DockerClient; die Methoden der Collections setzt jeder Test selbst."""

    def __init__(self) -> None:
        self.containers = SimpleNamespace()
        self.images = SimpleNamespace()
        self.volumes = SimpleNamespace()


@pytest.fixture
def fake() -> FakeClient:
    return FakeClient()


@pytest.fixture
def prov(fake: FakeClient) -> DockerProvisioner:
    provisioner = DockerProvisioner("tcp://127.0.0.1:23750", INSTANCE)
    provisioner._client = cast("docker.DockerClient", fake)  # schon "gecachter" Client
    return provisioner


def test_connection_error_on_list(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _raise(requests.exceptions.ConnectionError("weg"))
    with pytest.raises(DockerUnavailableError, match="gameworld-docker-proxy"):
        prov.list_managed()
    assert prov._client is None


def test_read_timeout_on_start(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _raise(requests.exceptions.ReadTimeout("langsam"))
    with pytest.raises(DockerUnavailableError):
        prov.start_world(WORLD)
    assert prov._client is None


def test_docker_exception_on_ensure_image(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.images.get = _raise(docker.errors.DockerException("x"))
    with pytest.raises(DockerUnavailableError):
        prov.ensure_image()
    assert prov._client is None


def test_protocol_error_on_create(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.create = _raise(urllib3.exceptions.ProtocolError("abgerissen"))
    with pytest.raises(DockerUnavailableError):
        prov.create_world_container(WORLD, 30015, b"")
    assert prov._client is None


def _listing(*containers: FakeContainer) -> Any:
    def call(*args: object, **kwargs: object) -> list[FakeContainer]:
        del args, kwargs
        return list(containers)

    return call


def test_missing_volume_on_remove_is_ignored(prov: DockerProvisioner, fake: FakeClient) -> None:
    container = FakeContainer()
    fake.containers.list = _listing(container)
    fake.volumes.get = _raise(docker.errors.NotFound("kein Volume"))
    prov.remove_world(WORLD, keep_volume=False)
    assert container.removed


def test_port_conflict_on_start(prov: DockerProvisioner, fake: FakeClient) -> None:
    error = _api_error("Bind for 0.0.0.0:30015 failed: port is already allocated")
    container = FakeContainer(start_error=error)
    fake.containers.list = _listing(container)
    with pytest.raises(PortInUseError) as info:
        prov.start_world(WORLD)
    assert info.value.port == 30015
    assert not isinstance(info.value, DockerUnavailableError)
    assert prov._client is not None


def test_other_api_error_on_start(prov: DockerProvisioner, fake: FakeClient) -> None:
    container = FakeContainer(start_error=_api_error("boom"))
    fake.containers.list = _listing(container)
    with pytest.raises(ProvisionerError, match="Docker hat den Start der Welt abgelehnt") as info:
        prov.start_world(WORLD)
    assert not isinstance(info.value, DockerUnavailableError)


@pytest.mark.parametrize(
    ("label", "value"),
    [("gameworld.instance", "fremd000"), ("gameworld.managed", "false"), ("gameworld.world_id", "ffffffffffff")],
)
def test_foreign_container_is_never_touched(prov: DockerProvisioner, fake: FakeClient, label: str, value: str) -> None:
    """Auch wenn der Proxy einen Filter ignorierte, prüft der Provisioner die Labels selbst."""
    container = FakeContainer()
    container.labels[label] = value
    fake.containers.list = _listing(container)
    fake.volumes.get = _raise(docker.errors.NotFound("kein Volume"))
    with pytest.raises(WorldNotFoundError):
        prov.start_world(WORLD)
    with pytest.raises(WorldNotFoundError):
        prov.stop(WORLD)
    prov.remove_world(WORLD, keep_volume=False)
    assert not container.removed


def test_used_host_ports_reads_all_bindings(prov: DockerProvisioner, fake: FakeClient) -> None:
    foreign = SimpleNamespace(
        attrs={
            "HostConfig": {
                "PortBindings": {
                    "30000/udp": [{"HostIp": "0.0.0.0", "HostPort": "30015"}],  # noqa: S104
                    "80/tcp": [{"HostIp": "", "HostPort": "8090"}],
                    "9000/tcp": [{"HostIp": "", "HostPort": "30018-30030"}],
                    "9001/tcp": None,
                }
            }
        }
    )
    plain = SimpleNamespace(attrs={"HostConfig": {"PortBindings": None}})
    fake.containers.list = lambda **_: [foreign, plain]
    assert prov.used_host_ports(30015, 30019) == {30015, 30018, 30019}


def test_unreachable_server_without_cached_client() -> None:
    provisioner = DockerProvisioner("tcp://127.0.0.1:1", INSTANCE)
    with pytest.raises(DockerUnavailableError) as info:
        provisioner.list_managed()
    assert "tcp://127.0.0.1:1" in str(info.value)
    assert "gameworld-docker-proxy" in str(info.value)
