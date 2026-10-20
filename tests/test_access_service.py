"""AccessService ohne Docker: Einladen (Konten und Gruppen), Entfernen, Abgleich, Passwort neu,
Umbenennen, Fingerabdruck des Geheimnisses und Schreiben der Zugangsdatei."""

from __future__ import annotations

import base64
import io
import logging
import tarfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import anyio
import pytest

from gameworld.access.accounts import derive_password
from gameworld.access.directory import DirectoryUnavailableError, DirectoryUser
from gameworld.access.secret import SecretUnavailableError, fingerprint
from gameworld.access.service import (
    AccessResult,
    AccessService,
    InviteKey,
    InviteTargetError,
    PlayerNameTakenError,
    PlayerNotFoundError,
    _Resolution,  # pyright: ignore[reportPrivateUsage]
)
from gameworld.config import load_settings
from gameworld.provisioner.access_mod import ACCESS_FILE_NAME
from gameworld.provisioner.client import DockerProvisioner, DockerUnavailableError, WorldNotFoundError
from gameworld.provisioner.luanti_auth import make_verifier
from gameworld.worlds import service as world_service
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


# 03-04: Gruppen, Abgleich, Passwort neu, Umbenennen, Fingerabdruck


def _verifier_ok(verifier: str, name: str, password: str) -> bool:
    return verifier == make_verifier(name, password, _salt(verifier))


async def test_invite_group_only_active_members(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    result = await access.invite_group(W1, "admin", "familie")
    assert result.applied is True
    assert ("admin", "familie") in fake_directory.group_calls
    assert set(store.world_access(W1)) == {"gw-kind"}
    assert [(i.kind, i.target) for i in store.list_invites(W1)] == [("group", "familie")]
    [player] = await access.list_players(W1, "admin")
    assert (player.nc_user, player.via) == ("gw-kind", "group:familie")
    assert _generation(store, W1) == 1
    assert len(fake.written) == 1


async def test_unknown_group_is_refused(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    with pytest.raises(InviteTargetError, match="Gruppe"):
        await access.invite_group(W1, "admin", "fremde-gruppe")
    assert store.list_invites(W1) == []
    assert fake.written == []


async def test_direct_and_group_invite_give_one_entry(access: AccessService, store: WorldStore) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_group(W1, "admin", "familie")
    assert list(store.world_access(W1)) == ["gw-kind"]
    assert _generation(store, W1) == 1
    [player] = await access.list_players(W1, "admin")
    assert player.via == "user"
    await access.revoke(W1, "admin", "group", "familie")
    assert list(store.world_access(W1)) == ["gw-kind"]
    await access.revoke(W1, "admin", "user", "gw-kind")
    assert store.world_access(W1) == {}


async def test_sync_world_follows_group_membership(
    access: AccessService, store: WorldStore, fake: FakeProvisioner, fake_directory: FakeDirectory
) -> None:
    await access.invite_group(W1, "admin", "familie")
    pushes = len(fake.written)

    # Ohne Änderung: kein Push, keine neue Generation.
    await access.sync_world(W1, "admin")
    assert len(fake.written) == pushes
    assert _generation(store, W1) == 1

    # Neues Mitglied kommt dazu.
    fake_directory.users["gw-mia"] = ("Mia Müller", True)
    fake_directory.groups["familie"].append("gw-mia")
    await access.sync_world(W1, "admin")
    assert set(store.world_access(W1)) == {"gw-kind", "gw-mia"}
    assert _generation(store, W1) == 2

    # gw-kind tritt aus: Zugang weg, Generation +1, Push.
    fake_directory.groups["familie"].remove("gw-kind")
    result = await access.sync_world(W1, "admin")
    assert result.applied is True
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert _generation(store, W1) == 3
    assert len(fake.written) == pushes + 2

    # Ein deaktiviertes Konto verliert den Zugang ebenso.
    fake_directory.users["gw-mia"] = ("Mia Müller", False)
    await access.sync_world(W1, "admin")
    assert store.world_access(W1) == {}


async def test_sync_all_is_throttled_and_isolates_failures(
    access: AccessService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gameworld.access import service as access_service

    await access.invite_group(W1, "admin", "familie")
    await access.invite_group(W2, "admin", "familie")
    clock = [1000.0]
    monkeypatch.setattr(access_service, "monotonic", lambda: clock[0])

    fake_directory.groups["familie"].remove("gw-kind")
    assert await access.sync_all("admin") is True
    assert store.world_access(W1) == {}
    assert store.world_access(W2) == {}

    # Innerhalb von 60 s passiert nichts.
    fake_directory.groups["familie"].append("gw-kind")
    clock[0] += access_service.SYNC_INTERVAL_SECONDS - 1
    assert await access.sync_all("admin") is False
    assert store.world_access(W1) == {}

    # Danach wieder; eine kaputte Welt hält die andere nicht auf.
    clock[0] += 2
    original = access._sync  # pyright: ignore[reportPrivateUsage]

    async def flaky(world_id: str, acting_uid: str, secret: bytes, *, blocking: bool) -> AccessResult | None:
        if world_id == W1:
            raise RuntimeError("kaputt")
        return await original(world_id, acting_uid, secret, blocking=blocking)

    monkeypatch.setattr(access, "_sync", flaky)
    assert await access.sync_all("admin") is True
    assert store.world_access(W1) == {}
    assert set(store.world_access(W2)) == {"gw-kind"}


async def test_sync_all_skips_busy_lock_and_retries(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    from gameworld.access import service as access_service

    await access.invite_group(W1, "admin", "familie")
    fake_directory.groups["familie"].remove("gw-kind")
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    assert lock.acquire(blocking=False)
    try:
        with anyio.fail_after(5):
            assert await access.sync_all("admin") is True
    finally:
        lock.release()
    # Nichts geändert, Drossel nicht verbraucht: Der nächste Besuch gleicht ab.
    assert set(store.world_access(W1)) == {"gw-kind"}
    assert access_service.SYNC_STATE.last is None
    assert await access.sync_all("admin") is True
    assert store.world_access(W1) == {}


async def test_rotate_password(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W2, "admin", "gw-kind")
    before = {world_id: store.world_access(world_id)["gw-kind"] for world_id in (W1, W2)}
    pushes = len(fake.written)

    change = await access.rotate_password("admin", "gw-kind")
    new_password = derive_password(TEST_SECRET, "gw-kind", 1)
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
    assert len(fake.written) == pushes + 2
    [listed] = await access.list_players(W1, "admin")
    assert listed.password == new_password


async def test_rotate_unknown_player(access: AccessService) -> None:
    with pytest.raises(PlayerNotFoundError):
        await access.rotate_password("admin", "niemand")


async def test_rename_player(access: AccessService, store: WorldStore, fake: FakeProvisioner) -> None:
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W2, "admin", "gw-kind")
    pushes = len(fake.written)
    change = await access.rename_player("admin", "gw-kind", "Mia_2")
    assert (change.player_name, change.password, change.applied) == ("Mia_2", PASSWORD, True)
    for world_id in (W1, W2):
        assert store.access_entries(world_id).keys() == {"Mia_2"}
        assert _verifier_ok(store.world_access(world_id)["gw-kind"], "Mia_2", PASSWORD)
        assert _generation(store, world_id) == 2
    assert len(fake.written) == pushes + 2


async def test_rename_collision_and_validation(
    access: AccessService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.users["gw-mia"] = ("Mia", True)
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W1, "admin", "gw-mia")
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
    await access.invite_user(W1, "admin", "gw-kind")
    await access.invite_user(W2, "admin", "gw-kind")
    assert store.get_meta("secret_fingerprint") == fingerprint(TEST_SECRET)

    # Gleicher Fingerabdruck: nichts.
    pushes = len(fake.written)
    await access.sync_world(W1, "admin")
    assert len(fake.written) == pushes

    fake_secret.value = NEW_SECRET
    await access.sync_world(W1, "admin")
    assert store.get_meta("secret_fingerprint") == fingerprint(NEW_SECRET)
    new_password = derive_password(NEW_SECRET, "gw-kind", 0)
    for world_id in (W1, W2):
        assert _verifier_ok(store.world_access(world_id)["gw-kind"], "Kind", new_password)
        assert _generation(store, world_id) == 2
    assert len(fake.written) == pushes + 2
    [listed] = await access.list_players(W1, "admin")
    assert listed.password == new_password


NEW_SECRET = bytes(range(2, 34))


def _lock_free() -> bool:
    lock = world_service._LOCK  # pyright: ignore[reportPrivateUsage]
    if not lock.acquire(blocking=False):
        return False
    lock.release()
    return True


async def _prepare_secret_change(access: AccessService, fake_secret: StaticSecret) -> None:
    await access.invite_user(W2, "admin", "gw-kind")
    fake_secret.value = NEW_SECRET


def _assert_all_verifiers_new(store: WorldStore, rotation: int) -> None:
    password = derive_password(NEW_SECRET, "gw-kind", rotation)
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
        await access.invite_user(W1, "admin", "gw-kind")
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
    assert change.password == derive_password(NEW_SECRET, "gw-kind", 1)
    _assert_all_verifiers_new(store, 1)
    assert _lock_free()


async def test_secret_change_during_sync_all_no_deadlock(
    access: AccessService, store: WorldStore, fake_secret: StaticSecret
) -> None:
    await _prepare_secret_change(access, fake_secret)
    with anyio.fail_after(5):
        assert await access.sync_all("admin") is True
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
        acting_uid: str, invites: set[InviteKey], known: dict[str, DirectoryUser] | None = None
    ) -> _Resolution:
        resolution = await original(acting_uid, invites, known)
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

    await access.invite_user(W1, "admin", "gw-kind")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_group(W1, "admin-b", "familie"))
    access_service.SYNC_STATE.last = 123.0

    result = await access.revoke(W1, "admin", "user", "gw-kind")
    assert result.applied is True
    # Der Widerruf gilt sofort, in der Datenbank und in der Zugangsdatei.
    assert "gw-kind" not in store.world_access(W1)
    assert "Kind" not in _written_access_file(fake.written[-1][1])
    # Veralteter Blick erkannt: Drossel aufgehoben, der nächste Besuch gleicht sofort ab.
    assert access_service.SYNC_STATE.last is None
    # Der Abgleich holt das Gruppen-Mitglied über die parallele Einladung regulär zurück.
    assert await access.sync_all("admin") is True
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
    await access.invite_group(W1, "admin", "familie")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_group(W1, "admin-b", "freunde"))

    result = await access.revoke(W1, "admin", "group", "familie")
    assert result.applied is True
    # Das familie-Mitglied ist raus; die parallel committete Einladung bleibt bestehen.
    assert set(store.world_access(W1)) == {"gw-mia"}
    assert await access.sync_all("admin") is True
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
    await access.invite_group(W1, "admin", "familie")
    parallel = AccessService(store, worlds, fake_directory, fake_secret)
    _resolve_then(access, monkeypatch, lambda: parallel.invite_user(W1, "admin-b", "gw-mia"))

    result = await access.sync_world(W1, "admin")
    assert result.applied is True
    assert set(store.world_access(W1)) == {"gw-kind", "gw-mia"}
