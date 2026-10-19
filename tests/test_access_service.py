"""AccessService ohne Docker: Einladen, Entfernen, Abgleich und Schreiben der Zugangsdatei."""

from __future__ import annotations

import base64
import io
import logging
import tarfile
from pathlib import Path
from typing import cast

import pytest

from gameworld.access.accounts import derive_password
from gameworld.access.directory import DirectoryUnavailableError
from gameworld.access.secret import SecretUnavailableError
from gameworld.access.service import AccessService, InviteTargetError
from gameworld.config import load_settings
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME
from gameworld.provisioner.client import DockerProvisioner, DockerUnavailableError, WorldNotFoundError
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests.conftest import TEST_SECRET, FakeDirectory, StaticSecret
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
PASSWORD = derive_password(TEST_SECRET, "gw-kind", 0)


def _world(world_id: str, port: int) -> WorldRow:
    return WorldRow(
        id=world_id,
        name=f"Welt {world_id}",
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-20T10:00:00+00:00",
    )


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "exited")
    return provisioner


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_world(W1, 30015))
    world_store.insert_world(_world(W2, 30016))
    return world_store


@pytest.fixture
def worlds(store: WorldStore, fake: FakeProvisioner) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, fake), load_settings())


@pytest.fixture
def access(
    store: WorldStore, worlds: WorldService, fake_directory: FakeDirectory, fake_secret: StaticSecret
) -> AccessService:
    return AccessService(store, worlds, fake_directory, fake_secret)


def _generation(store: WorldStore, world_id: str) -> int:
    row = store.get_world(world_id)
    assert row is not None
    return row.access_generation


def _written_access_file(archive: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        member = tar.extractfile(ACCESS_FILE_NAME)
        assert member is not None
        return member.read().decode("ascii")


def _salt(verifier: str) -> bytes:
    return base64.b64decode(verifier.split("#")[2])


async def test_invite_provisions_name_password_and_pushes(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    result = await access.invite_user(W1, "admin", "gw-kind")
    assert result.applied is True
    assert ("admin", "gw-kind") in fake_directory.calls
    player = store.get_player("gw-kind")
    assert player is not None
    assert (player.player_name, player.rotation) == ("Kind", 0)
    verifier = store.world_access(W1)["gw-kind"]
    assert verifier == make_verifier("Kind", PASSWORD, _salt(verifier))
    assert _generation(store, W1) == 1
    assert len(fake.written) == 1
    content = _written_access_file(fake.written[0][1])
    assert content == f"gameworld-access 1 1\nKind {verifier}\nend\n"


async def test_second_world_same_login_other_verifier(access: AccessService, store: WorldStore) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W2, "admin", "gw-kind")
    first = await access.list_players(W1, "admin")
    second = await access.list_players(W2, "admin")
    assert [(p.player_name, p.password) for p in first] == [(p.player_name, p.password) for p in second]
    assert first[0].password == PASSWORD
    assert store.world_access(W1)["gw-kind"] != store.world_access(W2)["gw-kind"]


async def test_reinvite_changes_nothing(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    before = store.world_access(W1)
    result = await access.invite_user(W1, "admin", "gw-kind")
    assert result.applied is True
    assert store.world_access(W1) == before
    assert _generation(store, W1) == 1
    assert len(fake.written) == 1


async def test_rebuild_without_change_keeps_file(
    access: AccessService, worlds: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    row = store.get_world(W1)
    assert row is not None
    first = worlds._access_file(row)  # pyright: ignore[reportPrivateUsage]
    # Entfernen von etwas, das nie eingeladen war: Abgleich ohne Soll-Änderung.
    await access.revoke(W1, "admin", "user", "niemand")
    assert worlds._access_file(row) == first  # pyright: ignore[reportPrivateUsage]
    assert _generation(store, W1) == 1
    assert len(fake.written) == 1


async def test_revoke_removes_access_but_keeps_player(
    access: AccessService, store: WorldStore, fake: FakeProvisioner
) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    result = await access.revoke(W1, "admin", "user", "gw-kind")
    assert result.applied is True
    assert store.list_invites(W1) == []
    assert store.world_access(W1) == {}
    assert _generation(store, W1) == 2
    assert len(fake.written) == 2
    assert _written_access_file(fake.written[1][1]) == "gameworld-access 1 2\nend\n"
    player = store.get_player("gw-kind")
    assert player is not None
    assert (player.player_name, player.rotation) == ("Kind", 0)


@pytest.mark.parametrize("uid", ["gw-aus", "fremd"])
async def test_unknown_or_disabled_account_is_refused(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, uid: str
) -> None:
    with pytest.raises(InviteTargetError):
        await access.invite_user(W1, "admin", uid)
    assert store.list_invites(W1) == []
    assert store.world_access(W1) == {}
    assert store.player_names() == set()
    assert _generation(store, W1) == 0
    assert fake.written == []


async def test_directory_or_secret_failure_writes_nothing(
    access: AccessService,
    store: WorldStore,
    fake: FakeProvisioner,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
) -> None:
    fake_directory.error = DirectoryUnavailableError("weg")
    with pytest.raises(DirectoryUnavailableError):
        await access.invite_user(W1, "admin", "gw-kind")
    fake_directory.error = None
    fake_secret.error = SecretUnavailableError("weg")
    with pytest.raises(SecretUnavailableError):
        await access.invite_user(W1, "admin", "gw-kind")
    assert store.list_invites(W1) == []
    assert store.player_names() == set()
    assert fake.written == []


async def test_list_players(access: AccessService) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    players = await access.list_players(W1, "admin")
    assert len(players) == 1
    player = players[0]
    assert (player.nc_user, player.display_name, player.player_name, player.password, player.via) == (
        "gw-kind",
        "Kind (Dev)",
        "Kind",
        PASSWORD,
        "user",
    )


async def test_list_players_falls_back_to_account_id(access: AccessService, fake_directory: FakeDirectory) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    fake_directory.error = DirectoryUnavailableError("weg")
    players = await access.list_players(W1, "admin")
    assert players[0].display_name == "gw-kind"


async def test_missing_container_is_not_an_error(
    access: AccessService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del fake.containers[W1]
    result = await access.invite_user(W1, "admin", "gw-kind")
    assert result.applied is False
    assert "gw-kind" in store.world_access(W1)
    assert _generation(store, W1) == 1


async def test_docker_gone_keeps_db_and_logs_without_secrets(
    access: AccessService,
    store: WorldStore,
    fake: FakeProvisioner,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(world_id: str, archive: bytes) -> None:
        del world_id, archive
        raise DockerUnavailableError("Der Docker-Proxy ist nicht erreichbar.")

    monkeypatch.setattr(fake, "write_world_files", broken)
    caplog.set_level(logging.DEBUG)
    result = await access.invite_user(W1, "admin", "gw-kind")
    assert result.applied is False
    verifier = store.world_access(W1)["gw-kind"]
    assert _generation(store, W1) == 1
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert PASSWORD not in caplog.text
    assert verifier not in caplog.text


async def test_unknown_world(access: AccessService) -> None:
    with pytest.raises(WorldNotFoundError):
        await access.invite_user("bbbbbbbbbbbb", "admin", "gw-kind")


async def test_delete_world_removes_invites_and_access(
    access: AccessService, worlds: WorldService, store: WorldStore
) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W2, "admin", "gw-kind")
    await worlds.delete_world(W1)
    assert store.list_invites(W1) == []
    assert store.world_access(W1) == {}
    assert len(store.list_invites(W2)) == 1
    assert store.get_player("gw-kind") is not None


async def test_disabled_later_is_dropped_on_next_change(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    await access.invite_user(W1, "admin", "gw-kind")
    fake_directory.users["gw-kind"] = ("Kind (Dev)", False)
    await access.invite_user(W1, "admin", "gw-mia")
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert store.access_entries(W1).keys() == {"Mia"}
