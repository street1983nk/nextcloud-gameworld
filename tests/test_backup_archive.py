"""Archive core for backup and restore (BACKUP-01/02, T-05-01..03, T-05-49)."""

from __future__ import annotations

import errno
import hashlib
import io
import json
import re
import tarfile
from collections.abc import Iterator
from typing import BinaryIO

import pytest

from gameworld.backup import archive
from gameworld.backup.archive import (
    KIND_BACKUP,
    MANIFEST_NAME,
    MSG_BAD_ENTRY,
    MSG_FOREIGN_WORLD,
    MSG_NO_MANIFEST,
    MSG_NO_MAP,
    MSG_NO_SPACE,
    MSG_TOO_BIG,
    BackupError,
    IterStream,
    RestoreRejected,
    build_manifest,
    ledger_tar,
    prepare_restore,
    sha256_of,
    verify_snapshot,
    write_snapshot,
)
from gameworld.provisioner import access_mod, status_mod, time_mod

WORLD_ID = "a1b2c3d4e5f6"
PRESET = "mtg-kreativ"
MAP = b"SQLite format 3\x00" + b"karte" * 200

# One entry: (name, type, content, link target)
Entry = tuple[str, bytes, bytes, str]


def _file(name: str, data: bytes = b"x") -> Entry:
    return (name, tarfile.REGTYPE, data, "")


def _dir(name: str) -> Entry:
    return (name, tarfile.DIRTYPE, b"", "")


def _tar_bytes(entries: list[Entry], *, gz: bool = False) -> bytes:
    buffer = io.BytesIO()
    mode = "w:gz" if gz else "w"
    with tarfile.open(fileobj=buffer, mode=mode, format=tarfile.PAX_FORMAT) as tar:
        for name, kind, data, link in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = link
            info.uid = info.gid = 1234
            info.uname = info.gname = "fremd"
            info.mode = 0o777
            info.mtime = 1_700_000_000
            if kind == tarfile.REGTYPE:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                tar.addfile(info)
    return buffer.getvalue()


def _chunks(raw: bytes) -> Iterator[bytes]:
    """Unevenly sized chunks with empty chunks in between, like a network stream."""
    sizes = [1, 0, 7, 513, 0, 4096, 3]
    position = 0
    index = 0
    while position < len(raw):
        size = sizes[index % len(sizes)]
        index += 1
        yield raw[position : position + size]
        position += size
    yield b""


def _manifest(world_id: str = WORLD_ID, preset: str = PRESET) -> bytes:
    return build_manifest(world_id, preset, "5.17.0", "2026-10-23T12:05:00+00:00", KIND_BACKUP)


def _docker_world() -> list[Entry]:
    return [
        _dir("world"),
        _file("world/map.sqlite", MAP),
        _file("world/map.sqlite-journal", b"journal"),
        _file("world/world.mt", b"gameid = minetest\n"),
        _dir("world/mcl_maps"),
        _file("world/mcl_maps/x.dat", b"daten"),
        _file(f"world/{access_mod.ACCESS_FILE_NAME}", b"zugang"),
        _file(f"world/{time_mod.LEDGER_FILE_NAME}", b"zaehlbuch"),
        _file(f"world/{status_mod.PLAYERS_FILE_NAME}", b"spieler"),
        _dir("world/worldmods"),
        _dir("world/worldmods/gameworld_access"),
        _file("world/worldmods/gameworld_access/init.lua", b"-- lua"),
        ("world/link", tarfile.SYMTYPE, b"", "/etc/passwd"),
    ]


def _snapshot(entries: list[Entry] | None = None) -> tuple[bytes, archive.SnapshotInfo]:
    sink = io.BytesIO()
    info = write_snapshot(_chunks(_tar_bytes(entries or _docker_world())), sink, _manifest())
    return sink.getvalue(), info


def _members(raw: bytes) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return {member.name: member for member in tar.getmembers()}


def _restore(raw: bytes, *, world_id: str = WORLD_ID, preset: str = PRESET) -> tuple[archive.RestoreInfo, bytes]:
    sink = io.BytesIO()
    info = prepare_restore(io.BytesIO(raw), world_id=world_id, preset=preset, sink=sink)
    return info, sink.getvalue()


def _backup(entries: list[Entry], manifest: bytes | None = None) -> bytes:
    """A tar.gz as it might lie in Nextcloud Files (also tampered with)."""
    head = [] if manifest is None else [_file(MANIFEST_NAME, manifest)]
    return _tar_bytes(head + entries, gz=True)


VALID = [_dir("world"), _file("world/map.sqlite", MAP)]


# IterStream


def test_iter_stream_reads_everything() -> None:
    raw = bytes(range(256)) * 100
    reader = io.BufferedReader(IterStream(_chunks(raw)), 1000)
    assert reader.read() == raw


# write_snapshot


def test_snapshot_keeps_only_world_data_and_manifest() -> None:
    raw, info = _snapshot()
    assert set(_members(raw)) == {
        MANIFEST_NAME,
        "world/map.sqlite",
        "world/map.sqlite-journal",
        "world/world.mt",
        "world/mcl_maps",
        "world/mcl_maps/x.dat",
    }
    assert info.skipped == 1


def test_snapshot_excludes_every_mod_runtime_file() -> None:
    names = [
        access_mod.ACCESS_FILE_NAME,
        access_mod.STATE_FILE_NAME,
        access_mod.EVENTS_FILE_NAME,
        status_mod.PLAYERS_FILE_NAME,
        time_mod.RULES_FILE_NAME,
        time_mod.LEDGER_FILE_NAME,
    ]
    raw, _ = _snapshot([*VALID, *(_file(f"world/{name}") for name in names)])
    assert set(_members(raw)) == {MANIFEST_NAME, "world/map.sqlite"}


def test_snapshot_size_and_hash_match_written_bytes() -> None:
    raw, info = _snapshot()
    assert info.size == len(raw)
    assert info.sha256 == hashlib.sha256(raw).hexdigest()


def test_snapshot_content_survives_uneven_chunks() -> None:
    raw, _ = _snapshot()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        handle = tar.extractfile("world/map.sqlite")
        assert handle is not None
        assert handle.read() == MAP


def test_snapshot_entries_are_normalized() -> None:
    members = _members(_snapshot()[0])
    for name, member in members.items():
        assert member.uid == member.gid == 30000, name
        assert member.uname == member.gname == "", name
    assert members["world/map.sqlite"].mode == 0o644
    assert members["world/mcl_maps"].mode == 0o755


def test_snapshot_manifest_fields() -> None:
    raw, _ = _snapshot()
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        handle = tar.extractfile(MANIFEST_NAME)
        assert handle is not None
        manifest = json.loads(handle.read())
    assert manifest == {
        "format": 1,
        "world_id": WORLD_ID,
        "preset": PRESET,
        "luanti_version": "5.17.0",
        "created_at": "2026-10-23T12:05:00+00:00",
        "kind": "backup",
    }


def test_snapshot_without_map_is_rejected() -> None:
    consumed: list[bytes] = []

    def chunks() -> Iterator[bytes]:
        for chunk in _chunks(_tar_bytes([_dir("world"), _file("world/world.mt")])):
            consumed.append(chunk)
            yield chunk
        consumed.append(b"ENDE")

    with pytest.raises(BackupError, match=re.escape(MSG_NO_MAP)):
        write_snapshot(chunks(), io.BytesIO(), _manifest())
    assert consumed[-1] == b"ENDE"


def test_snapshot_with_map_as_directory_is_rejected() -> None:
    with pytest.raises(BackupError, match=re.escape(MSG_NO_MAP)):
        _snapshot([_dir("world"), _dir("world/map.sqlite")])


class _FullDisk(io.RawIOBase):
    def writable(self) -> bool:
        return True

    def write(self, b: object, /) -> int:
        del b
        raise OSError(errno.ENOSPC, "No space left on device")


def test_snapshot_enospc_has_fixed_text() -> None:
    sink: BinaryIO = _FullDisk()  # type: ignore[assignment]
    with pytest.raises(BackupError, match=re.escape(MSG_NO_SPACE)):
        write_snapshot(_chunks(_tar_bytes(VALID)), sink, _manifest())
    assert MSG_NO_SPACE == "Nicht genug freier Speicherplatz auf dem Server."


def test_restore_enospc_has_fixed_text() -> None:
    sink: BinaryIO = _FullDisk()  # type: ignore[assignment]
    with pytest.raises(BackupError, match=re.escape(MSG_NO_SPACE)):
        prepare_restore(io.BytesIO(_backup(VALID, _manifest())), world_id=WORLD_ID, preset=PRESET, sink=sink)


# verify_snapshot


def test_verify_own_snapshot() -> None:
    raw, _ = _snapshot()
    source = io.BytesIO(raw)
    source.seek(5)
    info = verify_snapshot(source, world_id=WORLD_ID, preset=PRESET)
    assert info.entries == 4  # map.sqlite, Journal, mcl_maps, mcl_maps/x.dat
    assert source.tell() == 0


def test_verify_rejects_backup_without_map() -> None:
    source = io.BytesIO(_backup([_dir("world"), _file("world/x.dat")], _manifest()))
    with pytest.raises(RestoreRejected, match=re.escape(MSG_NO_MAP)):
        verify_snapshot(source, world_id=WORLD_ID, preset=PRESET)
    assert source.tell() == 0


def test_verify_rejects_foreign_manifest() -> None:
    raw, _ = _snapshot()
    with pytest.raises(RestoreRejected, match=re.escape(MSG_FOREIGN_WORLD)):
        verify_snapshot(io.BytesIO(raw), world_id="ffffffffffff", preset=PRESET)


# prepare_restore: success


def test_restore_tar_is_relative_to_world_folder() -> None:
    entries = [
        *VALID,
        _dir("world/mcl_maps"),
        _file("world/mcl_maps/x.dat", b"daten"),
    ]
    info, raw = _restore(_backup(entries, _manifest()))
    members = _members(raw)
    assert set(members) == {"map.sqlite", "mcl_maps", "mcl_maps/x.dat"}
    assert info.entries == 3
    assert info.unpacked_size == len(MAP) + len(b"daten")
    for member in members.values():
        assert member.uid == member.gid == 30000
        assert member.uname == member.gname == ""
        assert member.mtime == 1_700_000_000
    assert members["map.sqlite"].mode == 0o644
    assert members["mcl_maps"].mode == 0o755


def test_restore_roundtrip_keeps_content() -> None:
    raw, _ = _snapshot()
    _, restored = _restore(raw)
    with tarfile.open(fileobj=io.BytesIO(restored), mode="r:gz") as tar:
        handle = tar.extractfile("map.sqlite")
        assert handle is not None
        assert handle.read() == MAP


@pytest.mark.parametrize(
    "dropped",
    [
        _file("world/world.mt"),
        _dir("world/worldmods"),
        _file("world/worldmods/x/init.lua"),
        _file("world/mods/a.lua"),
        _file("world/mods/b.txt"),
        _file("world/game/x"),
        _file("world/irgendwo/datei.lua"),
        _file(f"world/{access_mod.ACCESS_FILE_NAME}"),
        _file(f"world/{time_mod.LEDGER_FILE_NAME}"),
        _file("world/gameworld_neu.txt"),
    ],
    ids=lambda entry: entry[0],
)
def test_restore_drops_code_and_runtime_files(dropped: Entry) -> None:
    _, raw = _restore(_backup([*VALID, dropped], _manifest()))
    assert set(_members(raw)) == {"map.sqlite"}


def test_restore_ledger_tar() -> None:
    raw = ledger_tar(b"gameworld-time-used 1\nend\n")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as tar:
        members = tar.getmembers()
        assert [member.name for member in members] == [time_mod.LEDGER_FILE_NAME]
        member = members[0]
        assert member.uid == member.gid == 30000
        assert member.mode == 0o644
        handle = tar.extractfile(member)
        assert handle is not None
        assert handle.read() == b"gameworld-time-used 1\nend\n"


def test_sha256_of_reads_whole_file_and_rewinds() -> None:
    data = b"abc" * 500_000
    source = io.BytesIO(data)
    source.seek(10)
    assert sha256_of(source) == hashlib.sha256(data).hexdigest()
    assert source.tell() == 0


# prepare_restore: Negativtests (T-05-01..03)


@pytest.mark.parametrize(
    "bad",
    [
        _file("world/../x"),
        _file("world/mcl_maps/../../x"),
        _file("/etc/x"),
        _file("world\\x"),
        _file("world/mcl_maps\\x.dat"),
        _file("world/c:x"),
        _file("anderswo/x.txt"),
        _file("x.txt"),
        ("world/link", tarfile.SYMTYPE, b"", "/etc/passwd"),
        ("world/hard", tarfile.LNKTYPE, b"", "world/map.sqlite"),
        ("world/fifo", tarfile.FIFOTYPE, b"", ""),
        ("world/zeichen", tarfile.CHRTYPE, b"", ""),
        ("world/block", tarfile.BLKTYPE, b"", ""),
        ("world/worldmods/link", tarfile.SYMTYPE, b"", "/etc"),
    ],
    ids=lambda entry: f"{entry[0]}-{entry[1]!r}",
)
def test_restore_rejects_unsafe_entry(bad: Entry) -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_BAD_ENTRY)):
        _restore(_backup([*VALID, bad], _manifest()))


def test_restore_rejects_missing_map() -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_NO_MAP)):
        _restore(_backup([_dir("world"), _file("world/x.dat")], _manifest()))


def test_restore_rejects_missing_manifest() -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_NO_MANIFEST)):
        _restore(_backup(VALID))


@pytest.mark.parametrize("manifest", [b"kein json", b"[]", json.dumps({"format": 2}).encode()])
def test_restore_rejects_broken_manifest(manifest: bytes) -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_NO_MANIFEST)):
        _restore(_backup(VALID, manifest))


def test_restore_rejects_foreign_world_id() -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_FOREIGN_WORLD)):
        _restore(_backup(VALID, _manifest(world_id="ffffffffffff")))


def test_restore_rejects_foreign_preset() -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_FOREIGN_WORLD)):
        _restore(_backup(VALID, _manifest(preset="voxelibre-sanft")))
    assert MSG_FOREIGN_WORLD == "Diese Sicherung gehört zu einer anderen Welt."


def test_restore_rejects_too_many_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_RESTORE_BYTES", 100)
    with pytest.raises(RestoreRejected, match=re.escape(MSG_TOO_BIG)):
        _restore(_backup(VALID, _manifest()))


def test_restore_rejects_too_many_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "MAX_RESTORE_ENTRIES", 3)
    entries = [*VALID, _file("world/a"), _file("world/b")]
    with pytest.raises(RestoreRejected, match=re.escape(MSG_TOO_BIG)):
        _restore(_backup(entries, _manifest()))


def test_restore_rejects_compression_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive, "RATIO_FLOOR", 0)
    bomb = [_dir("world"), _file("world/map.sqlite", b"\x00" * (4 * 1024 * 1024))]
    with pytest.raises(RestoreRejected, match=re.escape(MSG_TOO_BIG)):
        _restore(_backup(bomb, _manifest()))


def test_small_highly_compressible_world_is_accepted() -> None:
    """Below RATIO_FLOOR the ratio limit does not apply (empty SQLite pages pack heavily)."""
    world = [_dir("world"), _file("world/map.sqlite", b"\x00" * (4 * 1024 * 1024))]
    info, _ = _restore(_backup(world, _manifest()))
    assert info.unpacked_size == 4 * 1024 * 1024


@pytest.mark.parametrize("raw", [b"", b"kein gzip", _tar_bytes(VALID)[:700]])
def test_restore_rejects_broken_archive(raw: bytes) -> None:
    with pytest.raises(RestoreRejected, match=re.escape(MSG_BAD_ENTRY)):
        _restore(raw)


def test_restore_rejects_truncated_gzip() -> None:
    raw = _backup([*VALID, _file("world/gross", bytes(range(256)) * 4000)], _manifest())
    with pytest.raises(RestoreRejected, match=re.escape(MSG_BAD_ENTRY)):
        _restore(raw[: len(raw) // 2])


def test_restore_never_logs_entry_names(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(RestoreRejected):
        _restore(_backup([*VALID, _file("world/../GEHEIMNAME")], _manifest()))
    assert "GEHEIMNAME" not in caplog.text


def test_exclusion_lists_come_from_mod_constants() -> None:
    assert {
        access_mod.ACCESS_FILE_NAME,
        access_mod.STATE_FILE_NAME,
        access_mod.EVENTS_FILE_NAME,
        status_mod.PLAYERS_FILE_NAME,
        time_mod.RULES_FILE_NAME,
        time_mod.LEDGER_FILE_NAME,
    } == archive.BACKUP_EXCLUDED_FILES
    assert status_mod.PLAYERS_FILE.endswith(f"/{status_mod.PLAYERS_FILE_NAME}")
