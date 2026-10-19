"""Das Tar für das Welt-Volume: Eigentümer, Modi, keine Pfadausbrüche."""

import io
import tarfile

import pytest

from gameworld.provisioner import archive
from gameworld.provisioner.client import ProvisionerError

DIRS = [".minetest", ".minetest/worlds", ".minetest/worlds/world", ".minetest/games"]


def _members() -> dict[str, tarfile.TarInfo]:
    payload = archive.build_world_payload("server_announce = false\n", "gameid = minetest\n")
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as tar:
        return {member.name: member for member in tar.getmembers()}


def test_conf_belongs_to_root_and_is_read_only() -> None:
    conf = _members()["minetest.conf"]
    assert conf.uid == 0
    assert conf.gid == 0
    assert conf.mode == 0o444


def test_world_and_game_belong_to_luanti() -> None:
    members = _members()
    assert members[".minetest/worlds/world/world.mt"].uid == 30000
    assert members[".minetest/games/minetest_game/game.conf"].uid == 30000
    for name in DIRS:
        member = members[name]
        assert member.isdir(), name
        assert member.uid == 30000, name
        assert member.mode == 0o755, name


def test_no_path_escapes() -> None:
    for name in _members():
        assert ".." not in name.split("/"), name
        assert not name.startswith("/"), name


def test_tampered_zip_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "GAME_ZIP_SHA256", "0" * 64)
    with pytest.raises(ProvisionerError):
        archive.build_world_payload("x", "y")
