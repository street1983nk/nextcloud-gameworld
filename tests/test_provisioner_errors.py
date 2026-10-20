"""Fehlervertrag des Provisioners ohne Docker: Transportfehler werden immer zu 503-Kandidaten."""

from __future__ import annotations

import io
import tarfile
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import docker
import docker.errors
import pytest
import requests
import requests.exceptions
import urllib3.exceptions

from gameworld.provisioner.client import (
    ContainerInfo,
    DockerProvisioner,
    DockerUnavailableError,
    PortInUseError,
    ProvisionerError,
    StatusFile,
    WorldNotFoundError,
)
from gameworld.provisioner.presets import MTG_KREATIV, VOXELIBRE_SANFT
from gameworld.provisioner.spec import WorldPayload
from gameworld.provisioner.status_mod import PLAYERS_FILE

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
        self.attrs: dict[str, Any] = {}
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
def prov(fake: FakeClient, monkeypatch: pytest.MonkeyPatch) -> DockerProvisioner:
    provisioner = DockerProvisioner("tcp://127.0.0.1:23750", INSTANCE)
    provisioner._client = cast("docker.DockerClient", fake)  # schon "gecachter" Client
    # Auch ein "frischer" Client nach einem Transportfehler ist der Fake, nie der echte Proxy.
    monkeypatch.setattr(provisioner, "_docker", lambda: fake)
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
        prov.create_world_container(WORLD, 30015, WorldPayload(MTG_KREATIV, io.BytesIO(b"")))
    assert prov._client is None


def test_create_uses_payload_preset_and_stream(prov: DockerProvisioner, fake: FakeClient) -> None:
    """Spec aus payload.preset, das Datei-Objekt geht unverändert an put_archive (Pitfall 2, A5)."""
    created: dict[str, Any] = {}
    uploads: list[tuple[str, object]] = []

    class Created:
        id = "cid"

        def put_archive(self, path: str, data: object) -> bool:
            uploads.append((path, data))
            return True

    def create(**kwargs: Any) -> Created:
        created.update(kwargs)
        return Created()

    fake.containers.create = create
    stream = io.BytesIO(b"tar")
    payload = WorldPayload(VOXELIBRE_SANFT, stream)
    assert prov.create_world_container(WORLD, 30015, payload) == "cid"
    assert created["mem_limit"] == created["memswap_limit"] == "1g"
    assert created["labels"]["gameworld.preset"] == "voxelibre_sanft"
    assert uploads == [("/var/lib/minetest", stream)]


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


def test_vanished_container_on_start_is_not_found(prov: DockerProvisioner, fake: FakeClient) -> None:
    """NotFound zwischen _owned() und start() bleibt WorldNotFoundError (404), kein 500 (WR-02)."""
    container = FakeContainer(start_error=docker.errors.NotFound("weg"))
    fake.containers.list = _listing(container)
    with pytest.raises(WorldNotFoundError):
        prov.start_world(WORLD)


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


class Flaky:
    """Liefert erst die Fehler aus ``errors``, danach ``result``; zählt jeden Aufruf."""

    def __init__(self, errors: list[BaseException], result: object) -> None:
        self.errors = errors
        self.result = result
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.result


@pytest.mark.parametrize(
    "error",
    [requests.exceptions.ConnectionError("Remote end closed connection"), urllib3.exceptions.ProtocolError("weg")],
)
def test_read_is_retried_once_after_keep_alive_drop(
    prov: DockerProvisioner, fake: FakeClient, error: BaseException
) -> None:
    """HAProxy schließt Keep-Alive nach 10 s (Pitfall 4): ein zweiter Versuch, dann Erfolg."""
    listing = Flaky([error], [FakeContainer()])
    fake.containers.list = listing
    assert set(prov.list_managed()) == {WORLD}
    assert listing.calls == 2


def test_read_fails_after_second_drop(prov: DockerProvisioner, fake: FakeClient) -> None:
    listing = Flaky([requests.exceptions.ConnectionError("eins"), requests.exceptions.ConnectionError("zwei")], [])
    fake.containers.list = listing
    with pytest.raises(DockerUnavailableError):
        prov.list_managed()
    assert listing.calls == 2


@pytest.mark.parametrize(
    "error",
    [
        requests.exceptions.ReadTimeout("langsam"),
        # MRO-Falle (WR-03): ConnectTimeout ist auch ein ConnectionError.
        requests.exceptions.ConnectTimeout("schwarzes Loch"),
        requests.exceptions.Timeout("allgemein"),
    ],
)
def test_timeout_on_read_is_not_retried(prov: DockerProvisioner, fake: FakeClient, error: BaseException) -> None:
    listing = Flaky([error], [])
    fake.containers.list = listing
    with pytest.raises(DockerUnavailableError):
        prov.list_managed()
    assert listing.calls == 1


def test_connect_timeout_is_a_connection_error() -> None:
    """Gegenprobe zur MRO-Falle: Ohne die Timeout-Prüfung wäre ConnectTimeout wiederholbar."""
    assert issubclass(requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError)
    assert issubclass(requests.exceptions.ConnectTimeout, requests.exceptions.Timeout)


def test_used_host_ports_is_retried(prov: DockerProvisioner, fake: FakeClient) -> None:
    listing = Flaky([requests.exceptions.ConnectionError("weg")], [])
    fake.containers.list = listing
    assert prov.used_host_ports(30015, 30019) == set()
    assert listing.calls == 2


def test_start_is_never_retried(prov: DockerProvisioner, fake: FakeClient) -> None:
    """Schreibende Aufrufe werden nie wiederholt (T-02-21)."""
    listing = Flaky([requests.exceptions.ConnectionError("weg")], [FakeContainer()])
    fake.containers.list = listing
    with pytest.raises(DockerUnavailableError):
        prov.start_world(WORLD)
    assert listing.calls == 1


def test_stop_is_never_retried(prov: DockerProvisioner, fake: FakeClient) -> None:
    listing = Flaky([requests.exceptions.ConnectionError("weg")], [FakeContainer()])
    fake.containers.list = listing
    with pytest.raises(DockerUnavailableError):
        prov.stop(WORLD)
    assert listing.calls == 1


def test_list_managed_reads_state_fields(prov: DockerProvisioner, fake: FakeClient) -> None:
    container = FakeContainer()
    container.status = "exited"
    container.labels["gameworld.schema"] = "2"
    container.attrs = {"State": {"ExitCode": 137, "OOMKilled": True, "StartedAt": "2026-10-19T18:19:46.947430723Z"}}
    fake.containers.list = _listing(container)
    info = prov.list_managed()[WORLD]
    assert info == ContainerInfo(
        "cid",
        f"gameworld-{INSTANCE}-{WORLD}",
        WORLD,
        "exited",
        30015,
        exit_code=137,
        oom_killed=True,
        started_at="2026-10-19T18:19:46.947430723Z",
        schema="2",
    )


def test_list_managed_defaults_for_old_containers(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _listing(FakeContainer())
    info = prov.list_managed()[WORLD]
    assert (info.exit_code, info.oom_killed, info.started_at, info.schema) == (0, False, "", "1")


def _tar(content: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        member = tarfile.TarInfo("gameworld_players.txt")
        member.size = len(content)
        tar.addfile(member, io.BytesIO(content))
    return buffer.getvalue()


class ArchiveContainer(FakeContainer):
    def __init__(self, archive: bytes | None, mtime: str = "2026-10-19T18:19:47.1Z") -> None:
        super().__init__()
        self.archive = archive
        self.mtime = mtime
        self.paths: list[str] = []

    def get_archive(self, path: str, **kwargs: object) -> tuple[Iterator[bytes], dict[str, object]]:
        del kwargs
        self.paths.append(path)
        if self.archive is None:
            raise docker.errors.NotFound("Could not find the file")
        data = self.archive
        chunks = iter([data[index : index + 1000] for index in range(0, len(data), 1000)])
        return chunks, {"name": "gameworld_players.txt", "size": len(data), "mtime": self.mtime}


def test_read_status_file(prov: DockerProvisioner, fake: FakeClient) -> None:
    container = ArchiveContainer(_tar(b"Leo\nMia"))
    fake.containers.list = _listing(container)
    assert prov.read_status_file(WORLD) == StatusFile("2026-10-19T18:19:47.1Z", b"Leo\nMia")
    assert container.paths == [PLAYERS_FILE]


def test_read_status_file_missing_is_none(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _listing(ArchiveContainer(None))
    assert prov.read_status_file(WORLD) is None


def test_read_status_file_is_capped(prov: DockerProvisioner, fake: FakeClient) -> None:
    """Ein fremder Mod könnte eine riesige Datei schreiben: höchstens 4096 Bytes (T-02-18)."""
    fake.containers.list = _listing(ArchiveContainer(_tar(b"x" * 10_240)))
    status = prov.read_status_file(WORLD)
    assert status is not None
    assert status.content == b"x" * 4096


def test_read_status_file_of_foreign_container_is_not_found(prov: DockerProvisioner, fake: FakeClient) -> None:
    container = ArchiveContainer(_tar(b"Leo"))
    container.labels["gameworld.instance"] = "fremd000"
    fake.containers.list = _listing(container)
    with pytest.raises(WorldNotFoundError):
        prov.read_status_file(WORLD)
    assert container.paths == []


def test_read_status_file_is_retried(prov: DockerProvisioner, fake: FakeClient) -> None:
    listing = Flaky([requests.exceptions.ConnectionError("weg")], [ArchiveContainer(_tar(b""))])
    fake.containers.list = listing
    status = prov.read_status_file(WORLD)
    assert status is not None
    assert status.content == b""
    assert listing.calls == 2


def _truncated_tar() -> bytes:
    """Kopf verspricht 2000 Bytes, der Strom bricht nach 700 ab."""
    return _tar(b"x" * 2000)[:700]


def _oversized_pax_head() -> bytes:
    """Riesiger PAX-Kopf: Nach dem Kappen auf 64 KiB fehlt der eigentliche Eintrag."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        member = tarfile.TarInfo("gameworld_players.txt")
        member.pax_headers = {"comment": "x" * 100_000}
        member.size = 3
        tar.addfile(member, io.BytesIO(b"Leo"))
    return buffer.getvalue()


@pytest.mark.parametrize(
    "archive",
    [
        pytest.param(b"kein tar" * 200, id="garbage"),
        pytest.param(b"", id="empty"),
        pytest.param(_truncated_tar(), id="truncated"),
        pytest.param(_oversized_pax_head(), id="pax-capped"),
    ],
)
def test_broken_status_archive_is_provisioner_error(prov: DockerProvisioner, fake: FakeClient, archive: bytes) -> None:
    """WR-04: Tar-Fehler kommen als ProvisionerError an (pro Welt isoliert), nie roh und nie wiederholt."""
    container = ArchiveContainer(archive)
    fake.containers.list = _listing(container)
    with pytest.raises(ProvisionerError, match="Status-Datei") as info:
        prov.read_status_file(WORLD)
    assert not isinstance(info.value, DockerUnavailableError)
    assert container.paths == [PLAYERS_FILE]


def test_read_access_state(prov: DockerProvisioner, fake: FakeClient) -> None:
    """03-05: Die State-Datei des Zugangs-Mods kommt über denselben gekappten Leser."""
    from gameworld.provisioner.access_mod import STATE_FILE

    container = ArchiveContainer(_tar(b"7"))
    fake.containers.list = _listing(container)
    assert prov.read_access_state(WORLD) == StatusFile("2026-10-19T18:19:47.1Z", b"7")
    assert container.paths == [STATE_FILE]


def test_read_access_state_missing_is_none(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _listing(ArchiveContainer(None))
    assert prov.read_access_state(WORLD) is None


def test_broken_access_state_is_provisioner_error(prov: DockerProvisioner, fake: FakeClient) -> None:
    fake.containers.list = _listing(ArchiveContainer(b"kein tar" * 200))
    with pytest.raises(ProvisionerError, match="Zugangsstand") as info:
        prov.read_access_state(WORLD)
    assert not isinstance(info.value, DockerUnavailableError)
