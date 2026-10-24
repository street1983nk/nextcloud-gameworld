"""Reste fremder Installationen (06-08, T-06-35, T-06-37, T-06-38): Liste und gezieltes Entfernen.

Ohne Docker: Eine eigene Docker-Attrappe ignoriert bewusst alle Filter (wie ein
Proxy, der Filter verschluckt) und protokolliert jedes Entfernen. So prüfen die
Negativtests die zweite Prüfung am Ergebnis und dass eigene Welten, Container
ohne Label und Compose-Volumes nie angefasst werden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import docker
import docker.errors
import httpx
import pytest
import requests
import requests.exceptions

from gameworld.access import roles
from gameworld.access.roles import ADMIN_GROUP, ROLE_SPIELER, ROLE_VERWALTER, RoleService
from gameworld.api import worlds
from gameworld.config import load_settings
from gameworld.provisioner.client import (
    DockerProvisioner,
    DockerUnavailableError,
    OrphanInUseError,
    OrphanRefusedError,
)
from gameworld.provisioner.spec import resource_name
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore
from tests.conftest import appapi_headers, fake_lookup
from tests.test_pause_api import _row

OWN = "aa11bb22"
FOREIGN = "cc33dd44"
OWN_WORLD = "0123456789ab"
GONE_WORLD = "ba9876543210"
FOREIGN_WORLD = "fedcba987654"


def _api_error(status: int) -> docker.errors.APIError:
    response = requests.Response()
    response.status_code = status
    return docker.errors.APIError("docker", response=response, explanation="interner Docker-Text 4711")


class Box:
    """Container der Attrappe: id, name, labels, status, attrs."""

    def __init__(self, cid: str, name: str, labels: dict[str, str], status: str = "running") -> None:
        self.id = cid
        self.name = name
        self.labels = labels
        self.status = status
        self.attrs: dict[str, Any] = {"Created": "2026-10-01T10:00:00Z"}
        self.log: list[str] | None = None

    def remove(self, **kwargs: object) -> None:
        assert self.log is not None
        self.log.append(f"rm-container:{self.id}:{sorted(kwargs.items())}")


class Vol:
    def __init__(self, name: str, log: list[str], error: BaseException | None = None) -> None:
        self.name = name
        self.attrs: dict[str, Any] = {"CreatedAt": "2026-10-02T10:00:00Z"}
        self._log = log
        self._error = error

    def remove(self, **kwargs: object) -> None:
        del kwargs
        if self._error is not None:
            raise self._error
        self._log.append(f"rm-volume:{self.name}")


def _labels(instance: str, world_id: str) -> dict[str, str]:
    return {"gameworld.managed": "true", "gameworld.instance": instance, "gameworld.world_id": world_id}


class FakeDocker:
    """Ignoriert alle Filter und gibt alles zurück; protokolliert Entfernen in ``log``."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.boxes: list[Box] = []
        self.vols: list[Vol] = []
        self.containers = self
        self.volumes = _Volumes(self)

    def add_box(self, box: Box) -> Box:
        box.log = self.log
        self.boxes.append(box)
        return box

    # containers
    def list(self, **kwargs: object) -> list[Box]:
        del kwargs
        return list(self.boxes)

    def get(self, cid: str) -> Box:
        for box in self.boxes:
            if box.id.startswith(cid) or box.name == cid:
                return box
        raise docker.errors.NotFound("weg")


class _Volumes:
    def __init__(self, owner: FakeDocker) -> None:
        self._owner = owner

    def list(self, **kwargs: object) -> list[Vol]:
        del kwargs
        return list(self._owner.vols)

    def get(self, name: str) -> Vol:
        for vol in self._owner.vols:
            if vol.name == name:
                return vol
        raise docker.errors.NotFound("weg")


OWN_BOX = "a" * 64
FOREIGN_BOX = "b" * 64
UNLABELED_BOX = "c" * 64
FOREIGN_VOLUME = resource_name(FOREIGN, FOREIGN_WORLD)
OWN_VOLUME = resource_name(OWN, OWN_WORLD)
STALE_OWN_VOLUME = resource_name(OWN, GONE_WORLD)


@pytest.fixture
def dock() -> FakeDocker:
    fake = FakeDocker()
    fake.add_box(Box(OWN_BOX, resource_name(OWN, OWN_WORLD), _labels(OWN, OWN_WORLD)))
    fake.add_box(Box(FOREIGN_BOX, resource_name(FOREIGN, FOREIGN_WORLD), _labels(FOREIGN, FOREIGN_WORLD), "exited"))
    # Name wie Gameworld, aber ohne Label: etwa der Dev-Stack oder ein fremdes Projekt.
    fake.add_box(Box(UNLABELED_BOX, "gameworld-dev-app-1", {"com.docker.compose.project": "gameworld-dev"}))
    # Label managed=false zählt nicht als Gameworld-Welt.
    fake.add_box(Box("d" * 64, "gameworld-x-y", {"gameworld.managed": "false", "gameworld.instance": FOREIGN}))
    for name in (
        OWN_VOLUME,
        FOREIGN_VOLUME,
        STALE_OWN_VOLUME,
        "gameworld-dev_nextcloud",
        "gameworldx-fremd",
        "nc_data",
    ):
        fake.vols.append(Vol(name, fake.log))
    return fake


@pytest.fixture
def prov(dock: FakeDocker, monkeypatch: pytest.MonkeyPatch) -> DockerProvisioner:
    provisioner = DockerProvisioner("tcp://127.0.0.1:1", OWN)
    monkeypatch.setattr(provisioner, "_docker", lambda: cast("docker.DockerClient", dock))
    return provisioner


# Provisioner


def test_list_shows_only_foreign_containers_and_unowned_gameworld_volumes(prov: DockerProvisioner) -> None:
    orphans = prov.list_orphans({OWN_VOLUME})
    assert [(item.id, item.instance, item.state) for item in orphans.containers] == [(FOREIGN_BOX, FOREIGN, "exited")]
    assert orphans.containers[0].created == "2026-10-01T10:00:00Z"
    assert [item.name for item in orphans.volumes] == sorted([FOREIGN_VOLUME, STALE_OWN_VOLUME])
    assert orphans.volumes[0].created == "2026-10-02T10:00:00Z"


def test_container_without_managed_label_never_appears(prov: DockerProvisioner) -> None:
    """Container ohne managed-Label erscheint nie, auch mit Namen gameworld-..."""
    names = {item.name for item in prov.list_orphans(set()).containers}
    assert "gameworld-dev-app-1" not in names
    assert "gameworld-x-y" not in names


def test_own_world_container_and_volume_never_appear(prov: DockerProvisioner) -> None:
    orphans = prov.list_orphans({OWN_VOLUME})
    assert OWN_BOX not in {item.id for item in orphans.containers}
    assert OWN_VOLUME not in {item.name for item in orphans.volumes}


def test_compose_and_lookalike_volumes_never_appear(prov: DockerProvisioner) -> None:
    names = {item.name for item in prov.list_orphans(set()).volumes}
    assert not names & {"gameworld-dev_nextcloud", "gameworldx-fremd", "nc_data"}


def test_list_is_read_only(prov: DockerProvisioner, dock: FakeDocker) -> None:
    prov.list_orphans(set())
    assert dock.log == []


def test_remove_foreign_container_keeps_its_volume(prov: DockerProvisioner, dock: FakeDocker) -> None:
    prov.remove_orphan_container(FOREIGN_BOX[:12])
    assert dock.log == [f"rm-container:{FOREIGN_BOX}:[('force', True), ('v', False)]"]


def test_own_container_is_refused(prov: DockerProvisioner, dock: FakeDocker) -> None:
    """Eigener Container wird abgelehnt."""
    with pytest.raises(OrphanRefusedError):
        prov.remove_orphan_container(OWN_BOX)
    assert dock.log == []


@pytest.mark.parametrize("cid", [UNLABELED_BOX, "d" * 64])
def test_container_without_managed_label_is_refused(prov: DockerProvisioner, dock: FakeDocker, cid: str) -> None:
    with pytest.raises(OrphanRefusedError):
        prov.remove_orphan_container(cid)
    assert dock.log == []


@pytest.mark.parametrize("cid", ["gameworld-dev-app-1", "BBBBBBBBBBBB", "bbbb", "b" * 65])
def test_container_id_must_be_hex(prov: DockerProvisioner, dock: FakeDocker, cid: str) -> None:
    """Nie über einen Namen auflösen: Ein Name wäre eine ungeprüfte Auswahl."""
    with pytest.raises(OrphanRefusedError):
        prov.remove_orphan_container(cid)
    assert dock.log == []


def test_missing_container_is_no_error(prov: DockerProvisioner, dock: FakeDocker) -> None:
    prov.remove_orphan_container("e" * 64)
    assert dock.log == []


def test_remove_unowned_volume(prov: DockerProvisioner, dock: FakeDocker) -> None:
    prov.remove_orphan_volume(STALE_OWN_VOLUME, {OWN_VOLUME})
    assert dock.log == [f"rm-volume:{STALE_OWN_VOLUME}"]


def test_volume_of_own_world_is_refused(prov: DockerProvisioner, dock: FakeDocker) -> None:
    """Volume einer eigenen Welt wird abgelehnt, noch bevor Docker gefragt wird."""
    with pytest.raises(OrphanRefusedError):
        prov.remove_orphan_volume(OWN_VOLUME, {OWN_VOLUME})
    assert dock.log == []


@pytest.mark.parametrize(
    "name", ["gameworld-dev_nextcloud", "gameworldx-fremd", "nc_data", "gameworld-", "GAMEWORLD-A"]
)
def test_volume_outside_naming_scheme_is_refused(prov: DockerProvisioner, dock: FakeDocker, name: str) -> None:
    with pytest.raises(OrphanRefusedError):
        prov.remove_orphan_volume(name, set())
    assert dock.log == []


def test_volume_in_use_gives_in_use_error(prov: DockerProvisioner, dock: FakeDocker) -> None:
    dock.vols = [Vol(FOREIGN_VOLUME, dock.log, _api_error(409))]
    with pytest.raises(OrphanInUseError):
        prov.remove_orphan_volume(FOREIGN_VOLUME, set())


def test_proxy_down_gives_unavailable(prov: DockerProvisioner, dock: FakeDocker) -> None:
    def broken(**kwargs: object) -> list[Box]:
        del kwargs
        raise requests.exceptions.ConnectTimeout("weg")

    dock.list = broken  # type: ignore[method-assign]
    with pytest.raises(DockerUnavailableError):
        prov.list_orphans(set())


# Admin-API


@pytest.fixture
def orphan_api(app_env: Path, dock: FakeDocker, monkeypatch: pytest.MonkeyPatch) -> WorldStore:
    """Echter Dienst mit echtem Provisioner über der Docker-Attrappe; eine eigene Welt."""
    from gameworld.main import APP

    store = WorldStore(app_env / "gameworld.sqlite3")
    store.migrate()
    with store._connect() as connection:  # pyright: ignore[reportPrivateUsage]
        connection.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('instance_id', ?)", (OWN,))
    store.insert_world(_row(OWN_WORLD, "Wiese", 30015))
    provisioner = DockerProvisioner("tcp://127.0.0.1:1", store.instance_id())
    monkeypatch.setattr(provisioner, "_docker", lambda: cast("docker.DockerClient", dock))
    service = WorldService(store, provisioner, load_settings())
    monkeypatch.setitem(APP.dependency_overrides, worlds.get_service, lambda: service)
    monkeypatch.setattr(worlds, "_service", service)

    async def teachers() -> frozenset[str]:
        return frozenset({ADMIN_GROUP, "lehrkraefte"})

    # Der Lehrer ist Verwalter (sonst bewiese das 403 nichts), aber kein NC-Admin.
    monkeypatch.setattr(roles, "_role_service", RoleService(fake_lookup, teachers))
    return store


async def _post(client: httpx.AsyncClient, path: str, body: object, user: str = "admin") -> httpx.Response:
    return await client.post(path, json=body, headers=appapi_headers(user))


@pytest.mark.usefixtures("orphan_api")
async def test_api_lists_orphans(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/admin/orphans", headers=appapi_headers())
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body["containers"]] == [FOREIGN_BOX]
    assert set(body["containers"][0]) == {"id", "name", "instance", "state", "created"}
    # Volume der eigenen Welt fehlt, das alte eigene ohne Weltzeile erscheint.
    assert [item["name"] for item in body["volumes"]] == sorted([FOREIGN_VOLUME, STALE_OWN_VOLUME])
    assert set(body["volumes"][0]) == {"name", "created"}


@pytest.mark.usefixtures("orphan_api")
async def test_api_removes_container_and_returns_new_list(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    def gone(**kwargs: object) -> None:
        del kwargs
        dock.log.append("rm")
        dock.boxes = [box for box in dock.boxes if box.id != FOREIGN_BOX]

    dock.boxes[1].remove = gone  # type: ignore[method-assign]
    response = await _post(client, "/api/admin/orphans/container/remove", {"id": FOREIGN_BOX})
    assert response.status_code == 200
    assert response.json()["containers"] == []
    assert dock.log == ["rm"]


@pytest.mark.usefixtures("orphan_api")
async def test_api_removes_volume(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    response = await _post(client, "/api/admin/orphans/volume/remove", {"name": STALE_OWN_VOLUME})
    assert response.status_code == 200
    assert dock.log == [f"rm-volume:{STALE_OWN_VOLUME}"]


@pytest.mark.usefixtures("orphan_api")
async def test_api_refuses_own_container_and_own_volume(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    for path, body in (
        ("/api/admin/orphans/container/remove", {"id": OWN_BOX}),
        ("/api/admin/orphans/container/remove", {"id": UNLABELED_BOX}),
        ("/api/admin/orphans/volume/remove", {"name": OWN_VOLUME}),
    ):
        response = await _post(client, path, body)
        assert response.status_code == 409, path
        assert response.json()["detail"] == "Das gehört zu dieser Installation oder nicht zu Gameworld."
    assert dock.log == []


@pytest.mark.usefixtures("orphan_api")
async def test_api_volume_in_use_is_409_without_docker_text(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    dock.vols = [Vol(FOREIGN_VOLUME, dock.log, _api_error(409))]
    response = await _post(client, "/api/admin/orphans/volume/remove", {"name": FOREIGN_VOLUME})
    assert response.status_code == 409
    assert response.json()["detail"] == "Der Spielstand wird noch von einem Container benutzt."
    assert "4711" not in response.text


@pytest.mark.usefixtures("orphan_api")
async def test_api_other_docker_error_has_fixed_text(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    dock.vols = [Vol(FOREIGN_VOLUME, dock.log, _api_error(500))]
    response = await _post(client, "/api/admin/orphans/volume/remove", {"name": FOREIGN_VOLUME})
    assert response.status_code == 502
    assert "4711" not in response.text


@pytest.mark.usefixtures("orphan_api")
async def test_api_proxy_down_is_503_with_fixed_text(client: httpx.AsyncClient, dock: FakeDocker) -> None:
    def broken(**kwargs: object) -> list[Box]:
        del kwargs
        raise requests.exceptions.ConnectTimeout("geheimer Host 10.0.0.9")

    dock.list = broken  # type: ignore[method-assign]
    response = await client.get("/api/admin/orphans", headers=appapi_headers())
    assert response.status_code == 503
    assert response.json()["detail"] == "Gameworld erreicht Docker gerade nicht. Bitte später erneut versuchen."
    assert "10.0.0.9" not in response.text


@pytest.mark.usefixtures("orphan_api")
@pytest.mark.parametrize(
    "body",
    [
        {"id": "xyz"},
        {"id": FOREIGN_BOX, "force": True},
        {"name": "gameworld-dev_nextcloud"},
        {"name": "gameworld-" + "a" * 130},
    ],
)
async def test_api_invalid_input_is_422(client: httpx.AsyncClient, dock: FakeDocker, body: dict[str, object]) -> None:
    path = "/api/admin/orphans/container/remove" if "id" in body else "/api/admin/orphans/volume/remove"
    response = await _post(client, path, body)
    assert response.status_code == 422
    assert dock.log == []


@pytest.mark.usefixtures("orphan_api")
@pytest.mark.parametrize("user", ["gw-lehrer", "gw-kind"])
async def test_api_teacher_and_child_get_403(client: httpx.AsyncClient, dock: FakeDocker, user: str) -> None:
    # Vorbedingung: Der Lehrer ist Verwalter, das Kind nicht (sonst bewiese das 403 beim Lehrer nichts).
    me = (await client.get("/api/me", headers=appapi_headers(user))).json()
    assert me["role"] == (ROLE_VERWALTER if user == "gw-lehrer" else ROLE_SPIELER)
    assert (await client.get("/api/admin/orphans", headers=appapi_headers(user))).status_code == 403
    for path, body in (
        ("/api/admin/orphans/container/remove", {"id": FOREIGN_BOX}),
        ("/api/admin/orphans/volume/remove", {"name": FOREIGN_VOLUME}),
    ):
        assert (await _post(client, path, body, user)).status_code == 403
    assert dock.log == []
