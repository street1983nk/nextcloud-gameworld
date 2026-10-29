"""The tar for the world volume: owner, modes, game per preset, status mod, hash check."""

import hashlib
import io
import pathlib
import tarfile
import zipfile
from dataclasses import replace

import pytest

from gameworld.provisioner import access_mod, archive, status_mod, time_mod
from gameworld.provisioner.client import ProvisionerError
from gameworld.provisioner.presets import MTG_KREATIV, PRESETS, Preset
from gameworld.provisioner.spec import WorldPayload
from gameworld.provisioner.status_mod import MOD_CONF, MOD_DIR, MOD_INIT_LUA

# Directories owned by Luanti (everything except the world directory and worldmods).
DIRS = [
    ".minetest",
    ".minetest/worlds",
    ".minetest/games",
]
WORLD = ".minetest/worlds/world"
# AR-23: world directory root:30000 with sticky bit, worldmods including mods root-owned.
WORLD_DIR_RIGHTS = (0, 30000, 0o1775)
ROOT_DIR_RIGHTS = (0, 0, 0o755)
ROOT_FILE_RIGHTS = (0, 0, 0o644)


def _members(payload: WorldPayload) -> dict[str, tarfile.TarInfo]:
    try:
        with tarfile.open(fileobj=payload.archive, mode="r:") as tar:
            return {member.name: member for member in tar.getmembers()}
    finally:
        payload.archive.close()


def _read(payload: WorldPayload, name: str) -> bytes:
    try:
        with tarfile.open(fileobj=payload.archive, mode="r:") as tar:
            handle = tar.extractfile(name)
            assert handle is not None
            return handle.read()
    finally:
        payload.archive.close()


ACCESS = b"gameworld-access 1 0\nend\n"


def _kreativ() -> WorldPayload:
    return archive.build_world_payload(MTG_KREATIV, "server_announce = false\n", "gameid = minetest\n", ACCESS)


def _test_game(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Preset:
    """Small game zip with a root directory, as ContentDB delivers it."""
    path = tmp_path / "testspiel-1.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("testspiel/game.conf", "title = Testspiel\n")
        zipped.writestr("testspiel/mods/a/init.lua", "-- a\n")
        zipped.writestr("testspiel/mods/a/sub/game.conf", "title = verschachtelt\n")
        zipped.writestr("../ausbruch.txt", "nein\n")
    monkeypatch.setattr(archive, "GAMES_DIR", tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return replace(MTG_KREATIV, id="testspiel", game_zip=path.name, game_sha256=digest, game_dir="testspiel")


def test_payload_carries_preset() -> None:
    payload = _kreativ()
    assert payload.preset is MTG_KREATIV
    payload.archive.close()


def test_conf_belongs_to_root_and_is_read_only() -> None:
    conf = _members(_kreativ())["minetest.conf"]
    assert conf.uid == 0
    assert conf.gid == 0
    assert conf.mode == 0o444


def test_world_and_game_belong_to_luanti() -> None:
    members = _members(_kreativ())
    assert members[".minetest/worlds/world/world.mt"].uid == 30000
    assert members[".minetest/games/minetest_game/game.conf"].uid == 30000
    assert members[".minetest/games/minetest_game"].uid == 30000
    for name in DIRS:
        member = members[name]
        assert member.isdir(), name
        assert member.uid == 30000, name
        assert member.mode == 0o755, name


def test_status_mod_is_in_every_world() -> None:
    members = _members(_kreativ())
    for name in ("init.lua", "mod.conf"):
        member = members[f"{MOD_DIR}/{name}"]
        assert member.isfile(), name
        assert (member.uid, member.gid, member.mode) == ROOT_FILE_RIGHTS, name
    assert _read(_kreativ(), f"{MOD_DIR}/init.lua") == MOD_INIT_LUA.encode("utf-8")
    assert _read(_kreativ(), f"{MOD_DIR}/mod.conf") == MOD_CONF.encode("utf-8")
    assert "name = gameworld_status" in MOD_CONF.splitlines()


def test_status_file_is_never_in_the_payload() -> None:
    assert not any(name.endswith("gameworld_players.txt") for name in _members(_kreativ()))


def test_no_path_escapes() -> None:
    for name in _members(_kreativ()):
        assert ".." not in name.split("/"), name
        assert not name.startswith("/"), name


def test_game_follows_preset(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preset = _test_game(tmp_path, monkeypatch)
    payload = archive.build_world_payload(preset, "x\n", "gameid = testspiel\n", ACCESS)
    members = _members(payload)
    assert ".minetest/games/testspiel/game.conf" in members
    assert ".minetest/games/testspiel/mods/a/init.lua" in members
    assert ".minetest/games/testspiel/mods/a/sub/game.conf" in members
    assert not any("minetest_game" in name for name in members)
    for name in members:
        assert ".." not in name.split("/"), name
        assert not name.startswith("/"), name


def test_tampered_zip_is_rejected(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preset = replace(_test_game(tmp_path, monkeypatch), game_sha256="0" * 64)
    with pytest.raises(ProvisionerError, match="beschädigt oder verändert"):
        archive.build_world_payload(preset, "x", "y", ACCESS)


def test_missing_zip_is_rejected(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preset = replace(_test_game(tmp_path, monkeypatch), game_zip="fehlt-1.zip")
    with pytest.raises(ProvisionerError, match=r"Die mitgelieferte Spieldatei fehlt: fehlt-1\.zip"):
        archive.build_world_payload(preset, "x", "y", ACCESS)


@pytest.mark.parametrize("preset", list(PRESETS.values()), ids=list(PRESETS))
def test_preset_hash_matches_sha256sums(preset: Preset) -> None:
    sums = (archive.GAMES_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert f"{preset.game_sha256}  {preset.game_zip}" in sums


# Access mod and access file (03-01)


def _tar_members(raw: bytes) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        return {member.name: member for member in tar.getmembers()}


def _tar_read(raw: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        handle = tar.extractfile(name)
        assert handle is not None
        return handle.read()


def test_access_mod_and_file_are_in_every_world() -> None:
    members = _members(_kreativ())
    access_dir = members[access_mod.MOD_DIR]
    assert access_dir.isdir()
    assert (access_dir.uid, access_dir.gid, access_dir.mode) == ROOT_DIR_RIGHTS
    for name in ("init.lua", "mod.conf"):
        member = members[f"{access_mod.MOD_DIR}/{name}"]
        assert member.isfile(), name
        assert (member.uid, member.gid, member.mode) == ROOT_FILE_RIGHTS, name
    access = members[f".minetest/worlds/world/{access_mod.ACCESS_FILE_NAME}"]
    assert (access.uid, access.gid, access.mode) == (0, 0, 0o444)
    assert _read(_kreativ(), f".minetest/worlds/world/{access_mod.ACCESS_FILE_NAME}") == ACCESS
    assert _read(_kreativ(), f"{access_mod.MOD_DIR}/init.lua") == access_mod.MOD_INIT_LUA.encode("utf-8")


def test_state_files_are_never_in_the_payload() -> None:
    names = _members(_kreativ())
    assert not any(name.endswith(access_mod.STATE_FILE_NAME) for name in names)
    assert not any(name.endswith("gameworld_players.txt") for name in names)


def test_world_files_tar_carries_both_mods_and_access_file() -> None:
    raw = archive.build_world_files(ACCESS)
    members = _tar_members(raw)
    for directory in ("worldmods", "worldmods/gameworld_status", "worldmods/gameworld_access"):
        member = members[directory]
        assert member.isdir(), directory
        assert (member.uid, member.gid, member.mode) == ROOT_DIR_RIGHTS, directory
    for mod in ("gameworld_status", "gameworld_access"):
        for name in ("init.lua", "mod.conf"):
            member = members[f"worldmods/{mod}/{name}"]
            assert member.isfile()
            assert (member.uid, member.gid, member.mode) == ROOT_FILE_RIGHTS
    assert _tar_read(raw, "worldmods/gameworld_status/init.lua") == MOD_INIT_LUA.encode("utf-8")
    assert _tar_read(raw, "worldmods/gameworld_access/init.lua") == access_mod.MOD_INIT_LUA.encode("utf-8")
    access = members[access_mod.ACCESS_FILE_NAME]
    assert (access.uid, access.gid, access.mode) == (0, 0, 0o444)
    assert access.mtime > 0
    assert _tar_read(raw, access_mod.ACCESS_FILE_NAME) == ACCESS
    assert not any(name.endswith(access_mod.STATE_FILE_NAME) for name in members)
    for name in members:
        assert archive._safe_relative(name) == name, name


RULES = b"gameworld-time 1 0 1792792800\nend\n"


def test_time_mod_and_rules_are_in_every_world() -> None:
    payload = archive.build_world_payload(MTG_KREATIV, "x\n", "gameid = minetest\n", ACCESS, RULES)
    raw = payload.archive.read()
    payload.archive.close()
    members = _tar_members(raw)
    time_dir = members[time_mod.MOD_DIR]
    assert time_dir.isdir()
    assert (time_dir.uid, time_dir.gid, time_dir.mode) == ROOT_DIR_RIGHTS
    for name in ("init.lua", "mod.conf"):
        member = members[f"{time_mod.MOD_DIR}/{name}"]
        assert (member.uid, member.gid, member.mode) == ROOT_FILE_RIGHTS, name
    assert _tar_read(raw, f"{time_mod.MOD_DIR}/init.lua") == time_mod.MOD_INIT_LUA.encode("utf-8")
    rules = members[f".minetest/worlds/world/{time_mod.RULES_FILE_NAME}"]
    assert (rules.uid, rules.gid, rules.mode) == (0, 0, 0o444)
    assert _tar_read(raw, f".minetest/worlds/world/{time_mod.RULES_FILE_NAME}") == RULES
    # The ledger belongs to the mod and is never in the tar.
    assert not any(name.endswith(time_mod.LEDGER_FILE_NAME) for name in members)


def test_payload_without_time_file_has_mod_but_no_rules() -> None:
    names = _members(_kreativ())
    assert f"{time_mod.MOD_DIR}/init.lua" in names
    assert not any(name.endswith(time_mod.RULES_FILE_NAME) for name in names)


def test_world_files_tar_carries_time_mod_and_rules() -> None:
    raw = archive.build_world_files(ACCESS, RULES)
    members = _tar_members(raw)
    assert [mod_dir for mod_dir, _, _ in archive.WORLD_MODS] == [
        status_mod.MOD_DIR,
        access_mod.MOD_DIR,
        time_mod.MOD_DIR,
    ]
    directory = members["worldmods/gameworld_time"]
    assert directory.isdir()
    assert (directory.uid, directory.gid, directory.mode) == ROOT_DIR_RIGHTS
    for name in ("init.lua", "mod.conf"):
        member = members[f"worldmods/gameworld_time/{name}"]
        assert (member.uid, member.gid, member.mode) == ROOT_FILE_RIGHTS, name
    assert _tar_read(raw, "worldmods/gameworld_time/mod.conf") == time_mod.MOD_CONF.encode("utf-8")
    rules = members[time_mod.RULES_FILE_NAME]
    assert (rules.uid, rules.gid, rules.mode) == (0, 0, 0o444)
    assert rules.mtime > 0
    assert _tar_read(raw, time_mod.RULES_FILE_NAME) == RULES
    assert not any(name.endswith(time_mod.LEDGER_FILE_NAME) for name in members)
    for name in members:
        assert archive._safe_relative(name) == name, name


def test_world_files_without_time_file_has_no_rules() -> None:
    members = _tar_members(archive.build_world_files(ACCESS))
    assert "worldmods/gameworld_time/init.lua" in members
    assert time_mod.RULES_FILE_NAME not in members


def test_time_tar_has_exactly_the_rules_file() -> None:
    raw = archive.build_time_tar(RULES)
    members = _tar_members(raw)
    assert list(members) == [time_mod.RULES_FILE_NAME]
    member = members[time_mod.RULES_FILE_NAME]
    assert (member.uid, member.gid, member.mode) == (0, 0, 0o444)
    assert archive._safe_relative(member.name) == member.name
    assert _tar_read(raw, time_mod.RULES_FILE_NAME) == RULES


def test_access_tar_has_exactly_the_access_file() -> None:
    raw = archive.build_access_tar(ACCESS)
    members = _tar_members(raw)
    assert list(members) == [access_mod.ACCESS_FILE_NAME]
    member = members[access_mod.ACCESS_FILE_NAME]
    assert (member.uid, member.gid, member.mode) == (0, 0, 0o444)
    assert _tar_read(raw, access_mod.ACCESS_FILE_NAME) == ACCESS


# AR-23 (06-07): world directory and worldmods belong to root, the save game stays with Luanti.


def _rights(member: tarfile.TarInfo) -> tuple[int, int, int]:
    return member.uid, member.gid, member.mode


def test_payload_hardens_world_dir_and_worldmods() -> None:
    """New and restored worlds (both via build_world_payload)."""
    payload = archive.build_world_payload(MTG_KREATIV, "x\n", "gameid = minetest\n", ACCESS, RULES)
    raw = payload.archive.read()
    payload.archive.close()
    members = _tar_members(raw)
    world = members[WORLD]
    assert world.isdir()
    assert _rights(world) == WORLD_DIR_RIGHTS
    mod_dirs = [name for name in members if name.startswith(f"{WORLD}/worldmods") and members[name].isdir()]
    assert sorted(mod_dirs) == sorted([f"{WORLD}/worldmods", *(mod_dir for mod_dir, _, _ in archive.WORLD_MODS)])
    for name in mod_dirs:
        assert _rights(members[name]) == ROOT_DIR_RIGHTS, name
    mod_files = [name for name in members if name.startswith(f"{WORLD}/worldmods/") and members[name].isfile()]
    assert len(mod_files) == 2 * len(archive.WORLD_MODS)
    for name in mod_files:
        assert _rights(members[name]) == ROOT_FILE_RIGHTS, name
    for name in (access_mod.ACCESS_FILE_NAME, time_mod.RULES_FILE_NAME):
        assert _rights(members[f"{WORLD}/{name}"]) == (0, 0, 0o444), name
    # What Luanti rewrites itself stays with Luanti (otherwise its rename fails).
    assert _rights(members[f"{WORLD}/world.mt"]) == (30000, 30000, 0o644)
    for name in DIRS:
        assert _rights(members[name]) == (30000, 30000, 0o755), name


def test_world_files_harden_worldmods_but_not_the_world_dir() -> None:
    """Before every start: worldmods root-owned; an entry for "." would be skipped by Docker anyway."""
    members = _tar_members(archive.build_world_files(ACCESS, RULES))
    assert "." not in members
    directories = [name for name, member in members.items() if member.isdir()]
    expected = ["worldmods", *(mod_dir.removeprefix(f"{WORLD}/") for mod_dir, _, _ in archive.WORLD_MODS)]
    assert sorted(directories) == sorted(expected)
    for name, member in members.items():
        if member.isdir():
            assert _rights(member) == ROOT_DIR_RIGHTS, name
        elif name.startswith("worldmods/"):
            assert _rights(member) == ROOT_FILE_RIGHTS, name
        else:
            assert _rights(member) == (0, 0, 0o444), name
