"""Das Tar für das Welt-Volume: Eigentümer, Modi, Spiel pro Preset, Status-Mod, Hash-Prüfung."""

import hashlib
import pathlib
import tarfile
import zipfile
from dataclasses import replace

import pytest

from gameworld.provisioner import archive
from gameworld.provisioner.client import ProvisionerError
from gameworld.provisioner.presets import MTG_KREATIV, PRESETS, Preset
from gameworld.provisioner.spec import WorldPayload
from gameworld.provisioner.status_mod import MOD_CONF, MOD_DIR, MOD_INIT_LUA

DIRS = [
    ".minetest",
    ".minetest/worlds",
    ".minetest/worlds/world",
    ".minetest/worlds/world/worldmods",
    MOD_DIR,
    ".minetest/games",
]


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


def _kreativ() -> WorldPayload:
    return archive.build_world_payload(MTG_KREATIV, "server_announce = false\n", "gameid = minetest\n")


def _test_game(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> Preset:
    """Kleines Spiel-Zip mit Wurzelordner, wie es ContentDB ausliefert."""
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
        assert member.uid == 30000, name
        assert member.mode == 0o644, name
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
    payload = archive.build_world_payload(preset, "x\n", "gameid = testspiel\n")
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
        archive.build_world_payload(preset, "x", "y")


def test_missing_zip_is_rejected(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    preset = replace(_test_game(tmp_path, monkeypatch), game_zip="fehlt-1.zip")
    with pytest.raises(ProvisionerError, match=r"Die mitgelieferte Spieldatei fehlt: fehlt-1\.zip"):
        archive.build_world_payload(preset, "x", "y")


@pytest.mark.parametrize("preset", list(PRESETS.values()), ids=list(PRESETS))
def test_preset_hash_matches_sha256sums(preset: Preset) -> None:
    sums = (archive.GAMES_DIR / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
    assert f"{preset.game_sha256}  {preset.game_zip}" in sums
