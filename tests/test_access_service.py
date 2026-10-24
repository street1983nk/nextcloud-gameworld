"""AccessService ohne Docker: Einladen (Konten und Gruppen), Entfernen, Abgleich, Passwort neu,
Umbenennen, Fingerabdruck des Geheimnisses und Schreiben der Zugangsdatei."""

from __future__ import annotations

import base64
import io
import json
import logging
import sqlite3
import tarfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import anyio
import pytest

from gameworld.access.accounts import derive_password
from gameworld.access.directory import DirectoryRejectedError, DirectoryUnavailableError, DirectoryUser
from gameworld.access.roles import Profile
from gameworld.access.secret import SecretUnavailableError, fingerprint
from gameworld.access.service import (
    AccessResult,
    AccessService,
    Actor,
    InviteKey,
    InviteScopeError,
    InviteTargetError,
    PlayerNameTakenError,
    PlayerNotFoundError,
    _Resolution,  # pyright: ignore[reportPrivateUsage]
    actor_of,
)
from gameworld.config import load_settings
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME
from gameworld.provisioner.client import DockerProvisioner, DockerUnavailableError, WorldNotFoundError
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds import service as world_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldRow, WorldStore
from tests.conftest import ADMIN_ACTOR, LEHRER_ACTOR, TEST_SALT, TEST_SECRET, FakeDirectory, StaticSecret
from tests.test_service_lifecycle import FakeProvisioner

# Fester Zusatz neuer Spielerzeilen, damit die Passwörter hier vorab berechenbar sind.
pytestmark = pytest.mark.usefixtures("fixed_salt")

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
PASSWORD = derive_password(TEST_SECRET, "gw-kind", 0, TEST_SALT)
# Zweiter NC-Admin für die Wettlauf-Tests (steht im Test in der Gruppe admin).
ADMIN_B = Actor(uid="admin-b", nc_admin=True, groups=frozenset({"admin"}))


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


def _access_writes(fake: FakeProvisioner) -> list[bytes]:
    """Nur die Zugangsdatei-Tars; push_access schreibt seit 04-03 zusätzlich die Regeldatei (push_time)."""
    result: list[bytes] = []
    for _world_id, archive in fake.written:
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            if ACCESS_FILE_NAME in tar.getnames():
                result.append(archive)
    return result


def _salt(verifier: str) -> bytes:
    return base64.b64decode(verifier.split("#")[2])


async def test_invite_provisions_name_password_and_pushes(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    result = await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    assert result.applied is True
    assert ("admin", "gw-kind") in fake_directory.calls
    player = store.get_player("gw-kind")
    assert player is not None
    assert (player.player_name, player.rotation) == ("Kind", 0)
    verifier = store.world_access(W1)["gw-kind"]
    assert verifier == make_verifier("Kind", PASSWORD, _salt(verifier))
    assert _generation(store, W1) == 1
    assert len(_access_writes(fake)) == 1
    content = _written_access_file(_access_writes(fake)[0])
    assert content == f"gameworld-access 1 1\nKind {verifier}\nend\n"


async def test_second_world_same_login_other_verifier(access: AccessService, store: WorldStore) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    first = await access.list_players(W1, ADMIN_ACTOR)
    second = await access.list_players(W2, ADMIN_ACTOR)
    assert [(p.player_name, p.password) for p in first] == [(p.player_name, p.password) for p in second]
    assert first[0].password == PASSWORD
    assert store.world_access(W1)["gw-kind"] != store.world_access(W2)["gw-kind"]


async def test_reinvite_changes_nothing(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    before = store.world_access(W1)
    result = await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    assert result.applied is True
    assert store.world_access(W1) == before
    assert _generation(store, W1) == 1
    assert len(_access_writes(fake)) == 1


async def test_rebuild_without_change_keeps_file(
    access: AccessService, worlds: WorldService, store: WorldStore, fake: FakeProvisioner
) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    row = store.get_world(W1)
    assert row is not None
    first = worlds._access_file(row)  # pyright: ignore[reportPrivateUsage]
    # Entfernen von etwas, das nie eingeladen war: Abgleich ohne Soll-Änderung.
    await access.revoke(W1, ADMIN_ACTOR, "user", "niemand")
    assert worlds._access_file(row) == first  # pyright: ignore[reportPrivateUsage]
    assert _generation(store, W1) == 1
    assert len(_access_writes(fake)) == 1


async def test_revoke_removes_access_but_keeps_player(
    access: AccessService, store: WorldStore, fake: FakeProvisioner
) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    result = await access.revoke(W1, ADMIN_ACTOR, "user", "gw-kind")
    assert result.applied is True
    assert store.list_invites(W1) == []
    assert store.world_access(W1) == {}
    assert _generation(store, W1) == 2
    assert len(_access_writes(fake)) == 2
    assert _written_access_file(_access_writes(fake)[1]) == "gameworld-access 1 2\nend\n"
    player = store.get_player("gw-kind")
    assert player is not None
    assert (player.player_name, player.rotation) == ("Kind", 0)


@pytest.mark.parametrize("uid", ["gw-aus", "fremd"])
async def test_unknown_or_disabled_account_is_refused(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, uid: str
) -> None:
    with pytest.raises(InviteTargetError):
        await access.invite_user(W1, ADMIN_ACTOR, uid)
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
        await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    fake_directory.error = None
    fake_secret.error = SecretUnavailableError("weg")
    with pytest.raises(SecretUnavailableError):
        await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    assert store.list_invites(W1) == []
    assert store.player_names() == set()
    assert fake.written == []


async def test_list_players(access: AccessService) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    players = await access.list_players(W1, ADMIN_ACTOR)
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
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    fake_directory.error = DirectoryUnavailableError("weg")
    players = await access.list_players(W1, ADMIN_ACTOR)
    assert players[0].display_name == "gw-kind"


async def test_missing_container_is_not_an_error(
    access: AccessService, store: WorldStore, fake: FakeProvisioner
) -> None:
    del fake.containers[W1]
    result = await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
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
    result = await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    assert result.applied is False
    verifier = store.world_access(W1)["gw-kind"]
    assert _generation(store, W1) == 1
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert PASSWORD not in caplog.text
    assert verifier not in caplog.text


async def test_unknown_world(access: AccessService) -> None:
    with pytest.raises(WorldNotFoundError):
        await access.invite_user("bbbbbbbbbbbb", ADMIN_ACTOR, "gw-kind")


async def test_delete_world_removes_invites_and_access(
    access: AccessService, worlds: WorldService, store: WorldStore
) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    await worlds.delete_world(W1)
    assert store.list_invites(W1) == []
    assert store.world_access(W1) == {}
    assert len(store.list_invites(W2)) == 1
    assert store.get_player("gw-kind") is not None


async def test_disabled_later_is_dropped_on_next_change(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    fake_directory.users["gw-kind"] = ("Kind (Dev)", False)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-mia")
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert store.access_entries(W1).keys() == {"Mia"}


# 03-04: Gruppen, Abgleich, Passwort neu, Umbenennen, Fingerabdruck


def _verifier_ok(verifier: str, name: str, password: str) -> bool:
    return verifier == make_verifier(name, password, _salt(verifier))


async def test_invite_group_only_active_members(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    result = await access.invite_group(W1, ADMIN_ACTOR, "familie")
    assert result.applied is True
    assert ("admin", "familie") in fake_directory.group_calls
    assert set(store.world_access(W1)) == {"gw-kind"}
    assert [(i.kind, i.target) for i in store.list_invites(W1)] == [("group", "familie")]
    [player] = await access.list_players(W1, ADMIN_ACTOR)
    assert (player.nc_user, player.via) == ("gw-kind", "group:familie")
    assert _generation(store, W1) == 1
    assert len(_access_writes(fake)) == 1


async def test_unknown_group_is_refused(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    with pytest.raises(InviteTargetError, match="Gruppe"):
        await access.invite_group(W1, ADMIN_ACTOR, "fremde-gruppe")
    assert store.list_invites(W1) == []
    assert fake.written == []


async def test_direct_and_group_invite_give_one_entry(access: AccessService, store: WorldStore) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    assert list(store.world_access(W1)) == ["gw-kind"]
    assert _generation(store, W1) == 1
    [player] = await access.list_players(W1, ADMIN_ACTOR)
    assert player.via == "user"
    await access.revoke(W1, ADMIN_ACTOR, "group", "familie")
    assert list(store.world_access(W1)) == ["gw-kind"]
    await access.revoke(W1, ADMIN_ACTOR, "user", "gw-kind")
    assert store.world_access(W1) == {}


async def test_sync_world_follows_group_membership(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    pushes = len(_access_writes(fake))

    # Ohne Änderung: kein Push, keine neue Generation.
    await access.sync_world(W1, ADMIN_ACTOR)
    assert len(_access_writes(fake)) == pushes
    assert _generation(store, W1) == 1

    # Neues Mitglied kommt dazu.
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    fake_directory.groups["familie"].append("gw-mia")
    await access.sync_world(W1, ADMIN_ACTOR)
    assert set(store.world_access(W1)) == {"gw-kind", "gw-mia"}
    assert _generation(store, W1) == 2

    # gw-kind tritt aus: Zugang weg, Generation +1, Push.
    fake_directory.groups["familie"].remove("gw-kind")
    result = await access.sync_world(W1, ADMIN_ACTOR)
    assert result.applied is True
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert _generation(store, W1) == 3
    assert len(_access_writes(fake)) == pushes + 2

    # Ein deaktiviertes Konto verliert den Zugang ebenso.
    fake_directory.users["gw-mia"] = ("Mia Müller", False)
    await access.sync_world(W1, ADMIN_ACTOR)
    assert store.world_access(W1) == {}


async def test_sync_all_is_throttled_and_isolates_failures(
    access: AccessService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gameworld.access import service as access_service

    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    await access.invite_group(W2, ADMIN_ACTOR, "familie")
    clock = [1000.0]
    monkeypatch.setattr(access_service, "monotonic", lambda: clock[0])

    fake_directory.groups["familie"].remove("gw-kind")
    assert await access.sync_all(ADMIN_ACTOR) is True
    assert store.world_access(W1) == {}
    assert store.world_access(W2) == {}

    # Innerhalb von 60 s passiert nichts.
    fake_directory.groups["familie"].append("gw-kind")
    clock[0] += access_service.SYNC_INTERVAL_SECONDS - 1
    assert await access.sync_all(ADMIN_ACTOR) is False
    assert store.world_access(W1) == {}

    # Danach wieder; eine kaputte Welt hält die andere nicht auf.
    clock[0] += 2
    original = access._sync  # pyright: ignore[reportPrivateUsage]

    async def flaky(world_id: str, actor: Actor, secret: bytes, *, blocking: bool) -> AccessResult | None:
        if world_id == W1:
            raise RuntimeError("kaputt")
        return await original(world_id, actor, secret, blocking=blocking)

    monkeypatch.setattr(access, "_sync", flaky)
    assert await access.sync_all(ADMIN_ACTOR) is True
    assert store.world_access(W1) == {}
    assert set(store.world_access(W2)) == {"gw-kind"}


async def test_sync_all_skips_busy_lock_and_retries(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    from gameworld.access import service as access_service

    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    fake_directory.groups["familie"].remove("gw-kind")
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    assert lock.acquire(blocking=False)
    try:
        with anyio.fail_after(5):
            assert await access.sync_all(ADMIN_ACTOR) is True
    finally:
        lock.release()
    # Nichts geändert, Drossel nicht verbraucht: Der nächste Besuch gleicht ab.
    assert set(store.world_access(W1)) == {"gw-kind"}
    assert access_service.SYNC_STATE.last is None
    assert await access.sync_all(ADMIN_ACTOR) is True
    assert store.world_access(W1) == {}


async def test_rotate_password(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    before = {world_id: store.world_access(world_id)["gw-kind"] for world_id in (W1, W2)}
    pushes = len(_access_writes(fake))

    change = await access.rotate_password("admin", "gw-kind")
    new_password = derive_password(TEST_SECRET, "gw-kind", 1, TEST_SALT)
    assert change.password == new_password
    assert new_password != PASSWORD
    assert (change.player_name, change.applied) == ("Kind", True)
    player = store.get_player("gw-kind")
    assert player is not None
    assert player.rotation == 1
    for world_id in (W1, W2):
        verifier = store.world_access(world_id)["gw-kind"]
        assert verifier != before[world_id]
        assert _verifier_ok(verifier, "Kind", new_password)
        assert not _verifier_ok(verifier, "Kind", PASSWORD)
        assert _generation(store, world_id) == 2
    assert len(_access_writes(fake)) == pushes + 2
    [listed] = await access.list_players(W1, ADMIN_ACTOR)
    assert listed.password == new_password


async def test_rotate_unknown_player(access: AccessService) -> None:
    with pytest.raises(PlayerNotFoundError):
        await access.rotate_password("admin", "niemand")


async def test_rename_player(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    pushes = len(_access_writes(fake))
    change = await access.rename_player("admin", "gw-kind", "Mia_2")
    assert (change.player_name, change.password, change.applied) == ("Mia_2", PASSWORD, True)
    for world_id in (W1, W2):
        assert store.access_entries(world_id).keys() == {"Mia_2"}
        assert _verifier_ok(store.world_access(world_id)["gw-kind"], "Mia_2", PASSWORD)
        assert _generation(store, world_id) == 2
    assert len(_access_writes(fake)) == pushes + 2


async def test_rename_collision_and_validation(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.users["gw-mia"] = ("Mia", True)
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W1, ADMIN_ACTOR, "gw-mia")
    with pytest.raises(PlayerNameTakenError):
        await access.rename_player("admin", "gw-kind", "MIA")
    for bad in ("singleplayer", "x" * 21, "Müller", "Mia Neu"):
        with pytest.raises(ValueError, match="1 bis 20 Zeichen"):
            await access.rename_player("admin", "gw-kind", bad)
    with pytest.raises(PlayerNotFoundError):
        await access.rename_player("admin", "niemand", "Neu")
    # Der eigene Name in anderer Schreibweise ist erlaubt.
    change = await access.rename_player("admin", "gw-kind", "KIND")
    assert change.player_name == "KIND"
    player = store.get_player("gw-kind")
    assert player is not None
    assert player.player_name == "KIND"


async def test_fingerprint_stored_then_reprovision_on_new_secret(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_secret: StaticSecret
) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    assert store.get_meta("secret_fingerprint") == fingerprint(TEST_SECRET)

    # Gleicher Fingerabdruck: nichts.
    pushes = len(_access_writes(fake))
    await access.sync_world(W1, ADMIN_ACTOR)
    assert len(_access_writes(fake)) == pushes

    fake_secret.value = NEW_SECRET
    await access.sync_world(W1, ADMIN_ACTOR)
    assert store.get_meta("secret_fingerprint") == fingerprint(NEW_SECRET)
    new_password = derive_password(NEW_SECRET, "gw-kind", 0, TEST_SALT)
    for world_id in (W1, W2):
        assert _verifier_ok(store.world_access(world_id)["gw-kind"], "Kind", new_password)
        assert _generation(store, world_id) == 2
    assert len(_access_writes(fake)) == pushes + 2
    [listed] = await access.list_players(W1, ADMIN_ACTOR)
    assert listed.password == new_password


NEW_SECRET = bytes(range(2, 34))


def _lock_free() -> bool:
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


async def _prepare_secret_change(access: AccessService, fake_secret: StaticSecret) -> None:
    await access.invite_user(W2, ADMIN_ACTOR, "gw-kind")
    fake_secret.value = NEW_SECRET


def _assert_all_verifiers_new(store: WorldStore, rotation: int) -> None:
    password = derive_password(NEW_SECRET, "gw-kind", rotation, TEST_SALT)
    for world_id in (W1, W2):
        access = store.world_access(world_id)
        if "gw-kind" in access:
            assert _verifier_ok(access["gw-kind"], "Kind", password)
    assert store.get_meta("secret_fingerprint") == fingerprint(NEW_SECRET)


async def test_secret_change_during_invite_user_no_deadlock(
    access: AccessService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    await _prepare_secret_change(access, fake_secret)
    with anyio.fail_after(5):
        await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    assert [(i.kind, i.target) for i in store.list_invites(W1)] == [("user", "gw-kind")]
    assert set(store.world_access(W1)) == {"gw-kind"}
    _assert_all_verifiers_new(store, 0)
    assert _lock_free()


async def test_secret_change_during_rotate_password_no_deadlock(
    access: AccessService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    await _prepare_secret_change(access, fake_secret)
    with anyio.fail_after(5):
        change = await access.rotate_password("admin", "gw-kind")
    assert change.password == derive_password(NEW_SECRET, "gw-kind", 1, TEST_SALT)
    _assert_all_verifiers_new(store, 1)
    assert _lock_free()


async def test_secret_change_during_sync_all_no_deadlock(
    access: AccessService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    await _prepare_secret_change(access, fake_secret)
    with anyio.fail_after(5):
        assert await access.sync_all(ADMIN_ACTOR) is True
    _assert_all_verifiers_new(store, 0)
    assert _lock_free()


# WR-01: Ein Widerruf darf nie von der keep-Regel (parallel committete, noch
# nicht aufgelöste Einladung) still rückgängig gemacht werden.


def _resolve_then(
    access: AccessService, monkeypatch: pytest.MonkeyPatch, parallel_commit: Callable[[], Awaitable[object]]
) -> None:
    """Spielt den Wettlauf nach: access löst auf, dann committet eine parallele Aktion, dann wendet access an."""
    original = access._resolve  # pyright: ignore[reportPrivateUsage]

    async def resolve_then_commit(
        actor: Actor, invites: set[InviteKey], known: dict[str, DirectoryUser] | None = None, *, strict: bool = True
    ) -> _Resolution:
        resolution = await original(actor, invites, known, strict=strict)
        monkeypatch.setattr(access, "_resolve", original)  # nur beim ersten Aufruf dazwischenfunken
        await parallel_commit()
        return resolution

    monkeypatch.setattr(access, "_resolve", resolve_then_commit)


async def test_revoke_user_wins_against_parallel_group_invite(
    access: AccessService,
    store: WorldStore,
    worlds: WorldService,
    fake: FakeProvisioner,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """revoke liest die Einladungen, ein zweiter Verwalter committet invite_group, revoke wendet an."""
    from gameworld.access import service as access_service

    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    fake_directory.groups["admin"].append(ADMIN_B.uid)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_group(W1, ADMIN_B, "familie"))
    access_service.SYNC_STATE.last = 123.0

    result = await access.revoke(W1, ADMIN_ACTOR, "user", "gw-kind")
    assert result.applied is True
    # Der Widerruf gilt sofort, in der Datenbank und in der Zugangsdatei.
    assert "gw-kind" not in store.world_access(W1)
    assert "Kind" not in _written_access_file(_access_writes(fake)[-1])
    # Veralteter Blick erkannt: Drossel aufgehoben, der nächste Besuch gleicht sofort ab.
    assert access_service.SYNC_STATE.last is None
    # Der Abgleich holt das Gruppen-Mitglied über die parallele Einladung regulär zurück.
    assert await access.sync_all(ADMIN_ACTOR) is True
    assert set(store.world_access(W1)) == {"gw-kind"}


async def test_revoke_group_wins_but_keeps_parallel_invited(
    access: AccessService,
    store: WorldStore,
    worlds: WorldService,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gruppen-Widerruf entfernt deren Mitglieder auch dann, wenn parallel eine andere Einladung committet."""
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    fake_directory.groups["freunde"] = ["gw-mia"]
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    fake_directory.groups["admin"].append(ADMIN_B.uid)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_group(W1, ADMIN_B, "freunde"))

    result = await access.revoke(W1, ADMIN_ACTOR, "group", "familie")
    assert result.applied is True
    # Das familie-Mitglied ist raus; die parallel committete Einladung bleibt bestehen.
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert await access.sync_all(ADMIN_ACTOR) is True
    assert set(store.world_access(W1)) == {"gw-mia"}


async def test_sync_keeps_parallel_committed_invite(
    access: AccessService,
    store: WorldStore,
    worlds: WorldService,
    fake_directory: FakeDirectory,
    fake_secret: StaticSecret,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Die keep-Regel bleibt für Nicht-Widerrufe: Ein Abgleich wirft parallel Eingeladene nicht raus."""
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    fake_directory.groups["admin"].append(ADMIN_B.uid)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_user(W1, ADMIN_B, "gw-mia"))

    result = await access.sync_world(W1, ADMIN_ACTOR)
    assert result.applied is True
    assert set(store.world_access(W1)) == {"gw-kind", "gw-mia"}


# Einladungs-Umfang und 404-Falle (06-02, D-01, P-01). Gegenprobe unabhängig vom
# Dienst: Vorher und nachher wird die Datenbankdatei roh per sqlite3 gelesen.


@pytest.fixture
def db(app_env: Path) -> Path:
    return app_env / "gameworld.sqlite3"


def _raw_state(db: Path) -> dict[str, list[tuple[object, ...]]]:
    """invites, world_access und players roh aus der Datei, ohne WorldStore-Methoden."""
    connection = sqlite3.connect(db)
    try:
        return {
            "invites": connection.execute(
                "SELECT world_id, kind, target, invited_by FROM invites ORDER BY world_id, kind, target"
            ).fetchall(),
            "access": connection.execute(
                "SELECT world_id, nc_user, verifier FROM world_access ORDER BY world_id, nc_user"
            ).fetchall(),
            "players": connection.execute(
                "SELECT nc_user, player_name, rotation FROM players ORDER BY nc_user"
            ).fetchall(),
        }
    finally:
        connection.close()


def _raw_access(db: Path, world_id: str) -> set[str]:
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("SELECT nc_user FROM world_access WHERE world_id = ?", (world_id,)).fetchall()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


async def _school_world(access: AccessService) -> None:
    """W1 wie vom NC-Admin eingerichtet: Gruppe klasse und das Einzelkonto gw-kind-out."""
    await access.invite_group(W1, ADMIN_ACTOR, "klasse")
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind-out")


def test_actor_of_takes_groups_and_subadmin_groups() -> None:
    profile = Profile(user_id="gw-lehrer", display_name="L", groups=("lehrkraefte",), subadmin=("klasse",))
    assert actor_of(profile) == Actor(uid="gw-lehrer", nc_admin=False, groups=frozenset({"lehrkraefte", "klasse"}))
    admin = Profile(user_id="admin", display_name="A", groups=("admin",))
    assert actor_of(admin).nc_admin is True


async def test_teacher_invites_member_of_own_group_without_account_lookup(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    result = await access.invite_user(W1, LEHRER_ACTOR, "gw-kind-k")
    assert result.applied is True
    # Nie user() im Namen des Lehrers (404-Falle): die Aufrufliste bleibt leer.
    assert fake_directory.calls == []
    assert _raw_access(db, W1) == {"gw-kind-k"}
    players = await access.list_players(W1, LEHRER_ACTOR)
    assert [(p.nc_user, p.display_name, p.via) for p in players] == [("gw-kind-k", "gw-kind-k", "user")]
    assert fake_directory.calls == []


async def test_teacher_invites_member_of_subadmin_group(access: AccessService, db: Path) -> None:
    """Subadmin-Gruppen zählen zum Umfang, auch ohne Mitgliedschaft (D-01)."""
    subadmin = Actor(uid="gw-lehrer", nc_admin=False, groups=frozenset({"familie"}))
    await access.invite_user(W1, subadmin, "gw-kind")
    assert _raw_access(db, W1) == {"gw-kind"}


async def test_teacher_cannot_invite_account_outside_own_groups(
    access: AccessService, db: Path, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    await access.invite_user(W1, ADMIN_ACTOR, "gw-kind")
    before = _raw_state(db)
    written = len(fake.written)
    with pytest.raises(InviteScopeError) as caught:
        await access.invite_user(W1, LEHRER_ACTOR, "gw-kind-out")
    assert str(caught.value) == "Dieses Konto ist in keiner deiner Gruppen."
    assert _raw_state(db) == before
    assert len(fake.written) == written
    assert ("gw-lehrer", "gw-kind-out") not in fake_directory.calls


async def test_teacher_scope_skips_rejected_group_but_passes_outage(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    fake_directory.answers[("gw-lehrer", "klasse")] = DirectoryRejectedError("403")
    before = _raw_state(db)
    with pytest.raises(InviteScopeError):
        await access.invite_user(W1, LEHRER_ACTOR, "gw-kind-k")
    fake_directory.answers[("gw-lehrer", "klasse")] = DirectoryUnavailableError("weg")
    with pytest.raises(DirectoryUnavailableError):
        await access.invite_user(W1, LEHRER_ACTOR, "gw-kind-k")
    assert _raw_state(db) == before


async def test_teacher_invites_only_own_groups(
    access: AccessService, db: Path, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    fake_directory.groups["andere"] = ["gw-kind"]
    before = _raw_state(db)
    with pytest.raises(InviteScopeError) as caught:
        await access.invite_group(W1, LEHRER_ACTOR, "andere")
    assert str(caught.value) == "Diese Gruppe gehört nicht zu deinen Gruppen."
    assert _raw_state(db) == before
    assert fake.written == []
    assert ("gw-lehrer", "andere") not in fake_directory.group_calls

    await access.invite_group(W1, LEHRER_ACTOR, "klasse")
    assert _raw_access(db, W1) == {"gw-lehrer", "gw-kind-k"}
    assert fake_directory.calls == []


async def test_teacher_sync_removes_nothing_when_every_account_is_404(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Kern der 404-Falle: Nextcloud beantwortet dem Lehrer jedes Einzelkonto mit 404."""
    await _school_world(access)
    before = _raw_state(db)
    assert _raw_access(db, W1) == {"gw-lehrer", "gw-kind-k", "gw-kind-out"}
    fake_directory.users.clear()  # user() liefert jetzt None für jedes Konto
    fake_directory.calls.clear()

    await access.sync_world(W1, LEHRER_ACTOR)
    assert await access.sync_all(LEHRER_ACTOR) is True
    assert _raw_state(db) == before
    assert fake_directory.calls == []


async def test_teacher_sync_follows_group_membership(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Die Mitgliederliste ist verlässlich: Wer aus klasse austritt, fällt heraus; gw-kind-out bleibt."""
    await _school_world(access)
    fake_directory.users.clear()
    fake_directory.groups["klasse"].remove("gw-kind-k")
    await access.sync_world(W1, LEHRER_ACTOR)
    assert _raw_access(db, W1) == {"gw-lehrer", "gw-kind-out"}


async def test_teacher_sync_leaves_world_with_unreadable_group_untouched(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    await _school_world(access)
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    await access.invite_group(W2, ADMIN_ACTOR, "klasse")
    w1_before = _raw_access(db, W1)
    assert {"gw-kind", "gw-kind-k"} <= w1_before
    fake_directory.answers[("gw-lehrer", "familie")] = DirectoryRejectedError("403")
    fake_directory.groups["klasse"].remove("gw-kind-k")

    assert await access.sync_all(LEHRER_ACTOR) is True
    # W1 bleibt unverändert (auch gw-kind-k), W2 wird trotzdem abgeglichen.
    assert _raw_access(db, W1) == w1_before
    assert _raw_access(db, W2) == {"gw-lehrer"}
    with pytest.raises(DirectoryUnavailableError):
        await access.sync_world(W1, LEHRER_ACTOR)
    assert _raw_access(db, W1) == w1_before


async def test_teacher_sync_treats_missing_group_as_unreadable(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Auch 404 auf eine Gruppe heißt für den Lehrer nur: nicht lesbar, nie leer."""
    await _school_world(access)
    before = _raw_access(db, W1)
    del fake_directory.groups["klasse"]
    with pytest.raises(DirectoryUnavailableError):
        await access.sync_world(W1, LEHRER_ACTOR)
    assert _raw_access(db, W1) == before


async def test_teacher_invite_keeps_access_of_unreadable_group(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Einladen in eine Welt mit fremder Gruppe: deren Zugänge bleiben, das neue Konto kommt dazu."""
    await access.invite_group(W1, ADMIN_ACTOR, "familie")
    fake_directory.answers[("gw-lehrer", "familie")] = DirectoryRejectedError("403")
    fake_directory.users.clear()
    await access.invite_user(W1, LEHRER_ACTOR, "gw-kind-k")
    assert _raw_access(db, W1) == {"gw-kind", "gw-kind-k"}


async def test_stale_admin_profile_takes_the_safe_path(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Profil sagt noch admin (Cache), Nextcloud nicht mehr: kein Entfernen wegen 404."""
    await _school_world(access)
    before = _raw_state(db)
    fake_directory.users.clear()
    fake_directory.calls.clear()
    stale = Actor(uid="gw-lehrer", nc_admin=True, groups=frozenset({"klasse", "lehrkraefte"}))
    await access.sync_world(W1, stale)
    assert _raw_state(db) == before
    assert fake_directory.calls == []
    assert ("gw-lehrer", "admin") in fake_directory.group_calls


async def test_admin_sync_still_removes_deleted_account(
    access: AccessService, db: Path, fake_directory: FakeDirectory
) -> None:
    """Positivkontrolle: Als NC-Admin heißt 404 weiterhin gelöscht."""
    await _school_world(access)
    del fake_directory.users["gw-kind-out"]
    await access.sync_world(W1, ADMIN_ACTOR)
    assert _raw_access(db, W1) == {"gw-lehrer", "gw-kind-k"}


async def test_admin_invite_of_unknown_account_is_still_rejected(access: AccessService, db: Path) -> None:
    before = _raw_state(db)
    with pytest.raises(InviteTargetError):
        await access.invite_user(W1, ADMIN_ACTOR, "niemand")
    assert _raw_state(db) == before


async def test_purge_refuses_account_without_confirmed_admin_right(
    access: AccessService, store: WorldStore, db: Path, fake_directory: FakeDirectory
) -> None:
    from gameworld.playtime.service import META_NC_ADMINS

    await _school_world(access)
    store.set_meta(META_NC_ADMINS, json.dumps(["admin"]))
    del fake_directory.users["gw-kind-out"]
    before = _raw_state(db)
    fake_directory.calls.clear()
    assert await access.purge_missing_accounts("gw-lehrer") == []
    assert fake_directory.calls == []
    assert _raw_state(db) == before
    # Positivkontrolle: als bestätigter NC-Admin wird das gelöschte Konto vergessen.
    assert await access.purge_missing_accounts("admin") == ["gw-kind-out"]
