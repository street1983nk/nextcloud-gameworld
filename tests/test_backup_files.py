"""Files-Adapter der Sicherungen (05-02): eigener Client je Vorgang, eindeutiger Name, Größennachweis."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nc_py_api import NextcloudException

from gameworld.backup import files as files_module
from gameworld.backup.files import (
    DAV_TIMEOUT,
    MSG_FILE_GONE,
    MSG_FILES_FAILED,
    MSG_QUOTA,
    MSG_UPLOAD_INCOMPLETE,
    UPLOAD_CHUNK,
    FilesEntry,
    FilesError,
    NcBackupFiles,
    get_backup_files,
)
from gameworld.backup.naming import with_suffix
from tests.conftest import FakeBackupFiles, NcRecorder, assert_closed, install_fake_nc

FOLDER = "Gameworld/Sicherungen/Burg"
BASE = "Burg-2026-10-23-1405.tar.gz"
WHEN = datetime(2026, 10, 23, 12, 5, tzinfo=UTC)


def _node(path: str, size: int, file_id: int, *, is_dir: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        info=SimpleNamespace(fileid=file_id, size=size, last_modified=WHEN),
        user_path=path + ("/" if is_dir else ""),
        name=path.rsplit("/", 1)[-1],
        is_dir=is_dir,
    )


class FakeDav:
    """files-API von nc_py_api im Speicher: Pfad auf Größe; fehlende Pfade wie Nextcloud als 404."""

    def __init__(self) -> None:
        self.sizes: dict[str, int] = {}
        self.ids: dict[str, int] = {}
        self.deleted: list[str] = []
        self.uploaded: list[tuple[str, int]] = []
        self.short_by = 0
        self.upload_exc: Exception | None = None
        self._next = 500

    def add(self, path: str, size: int) -> None:
        self._next += 1
        self.sizes[path] = size
        self.ids[path] = self._next

    async def makedirs(self, path: str, exist_ok: bool = False) -> None:
        assert exist_ok
        self.sizes.setdefault(path + "/", 0)

    async def by_path(self, path: str) -> Any:
        if path not in self.sizes:
            raise NextcloudException(404, "Not found")
        return _node(path, self.sizes[path], self.ids.get(path, 0))

    async def upload_stream(self, path: str, fp: Any, chunk_size: int) -> None:
        assert chunk_size == UPLOAD_CHUNK
        data = fp.read()
        self.uploaded.append((path, len(data)))
        if self.upload_exc is not None:
            # Wie ein MOVE, der serverseitig trotzdem ankam (Pitfall 6).
            self.add(path, len(data))
            raise self.upload_exc
        self.add(path, len(data) - self.short_by)

    async def delete(self, path: str, not_fail: bool = False) -> None:
        assert not_fail
        self.deleted.append(path)
        self.sizes.pop(path, None)

    async def listdir(self, path: str) -> list[Any]:
        if path + "/" not in self.sizes:
            raise NextcloudException(404, "Not found")
        prefix = path + "/"
        nodes = [
            _node(p, s, self.ids[p]) for p, s in sorted(self.sizes.items()) if p.startswith(prefix) and p in self.ids
        ]
        nodes.append(_node(f"{path}/unterordner", 0, 1, is_dir=True))
        return nodes

    async def download2stream(self, path: str, fp: Any, chunk_size: int) -> None:
        assert chunk_size == UPLOAD_CHUNK
        if path not in self.sizes:
            raise NextcloudException(404, "Not found")
        fp.write(b"x" * self.sizes[path])


@pytest.fixture
def dav(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeDav, NcRecorder, MagicMock]:
    del app_env
    app = MagicMock()
    fake = FakeDav()
    app.files = fake
    recorder = install_fake_nc(monkeypatch, app)
    return fake, recorder, app


def _spool(size: int = 1234) -> io.BytesIO:
    spool = io.BytesIO(b"g" * size)
    spool.seek(size)  # Upload muss selbst zurückspulen.
    return spool


async def test_upload_uses_backup_client_options_and_proves_size(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, recorder, app = dav
    entry = await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert entry == FilesEntry(fake.ids[f"{FOLDER}/{BASE}"], f"{FOLDER}/{BASE}", BASE, 1234, WHEN)
    assert recorder.users == ["admin"]
    assert recorder.options == [{"npa_timeout_dav": DAV_TIMEOUT, "chunked_upload_v2": False}]
    assert DAV_TIMEOUT == 600
    assert fake.deleted == []
    assert_closed(app, times=1)


async def test_upload_picks_free_suffix_and_never_deletes_existing(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, _recorder, _app = dav
    fake.add(f"{FOLDER}/{BASE}", 99)
    entry = await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert entry.name == "Burg-2026-10-23-1405-2.tar.gz"
    assert fake.uploaded == [(f"{FOLDER}/Burg-2026-10-23-1405-2.tar.gz", 1234)]
    assert fake.sizes[f"{FOLDER}/{BASE}"] == 99
    assert fake.deleted == []


async def test_size_mismatch_deletes_only_own_target(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, _recorder, app = dav
    fake.add(f"{FOLDER}/{BASE}", 99)
    fake.short_by = 1
    with pytest.raises(FilesError) as caught:
        await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert str(caught.value) == MSG_UPLOAD_INCOMPLETE
    assert fake.deleted == [f"{FOLDER}/Burg-2026-10-23-1405-2.tar.gz"]
    assert fake.sizes[f"{FOLDER}/{BASE}"] == 99
    assert_closed(app, times=1)


async def test_quota_507_is_fixed_text_and_cleans_target(
    dav: tuple[FakeDav, NcRecorder, MagicMock], caplog: pytest.LogCaptureFixture
) -> None:
    fake, _recorder, app = dav
    fake.upload_exc = NextcloudException(507, "Insufficient Storage", info="/Gameworld/Sicherungen/Burg secret")
    with pytest.raises(FilesError) as caught:
        await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert str(caught.value) == MSG_QUOTA
    assert fake.deleted == [f"{FOLDER}/{BASE}"]
    assert f"{FOLDER}/{BASE}" not in fake.sizes
    assert_closed(app, times=1)
    # T-05-12: keine Pfade, Dateinamen oder Konten im Log.
    assert "Burg" not in caplog.text
    assert "admin" not in caplog.text
    assert "507" in caplog.text


async def test_other_errors_are_fixed_text(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, _recorder, _app = dav
    fake.upload_exc = OSError("Verbindung weg")
    with pytest.raises(FilesError) as caught:
        await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert str(caught.value) == MSG_FILES_FAILED
    assert fake.deleted == [f"{FOLDER}/{BASE}"]


async def test_client_closed_when_makedirs_fails(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, recorder, app = dav
    fake.makedirs = AsyncMock(side_effect=NextcloudException(503, "weg"))  # type: ignore[method-assign]
    with pytest.raises(FilesError) as caught:
        await NcBackupFiles().upload("admin", FOLDER, BASE, _spool(), 1234, with_suffix)
    assert str(caught.value) == MSG_FILES_FAILED
    # Vor der Namenswahl gibt es nichts Eigenes zu löschen.
    assert fake.deleted == []
    assert recorder.options == [{"npa_timeout_dav": DAV_TIMEOUT, "chunked_upload_v2": False}]
    assert_closed(app, times=1)


async def test_listdir_lists_files_and_missing_folder_is_empty(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, recorder, app = dav
    files = NcBackupFiles()
    assert await files.listdir("admin", FOLDER) == []
    await fake.makedirs(FOLDER, exist_ok=True)
    fake.add(f"{FOLDER}/{BASE}", 10)
    entries = await files.listdir("admin", FOLDER)
    assert [(e.name, e.size) for e in entries] == [(BASE, 10)]
    assert recorder.users == ["admin", "admin"]
    assert_closed(app, times=2)


async def test_stat_and_download(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, _recorder, app = dav
    files = NcBackupFiles()
    assert await files.stat("admin", f"{FOLDER}/{BASE}") is None
    fake.add(f"{FOLDER}/{BASE}", 7)
    entry = await files.stat("admin", f"{FOLDER}/{BASE}")
    assert entry is not None
    assert entry.size == 7
    out = io.BytesIO()
    await files.download_to("admin", f"{FOLDER}/{BASE}", out)
    assert out.getvalue() == b"x" * 7
    with pytest.raises(FilesError) as caught:
        await files.download_to("admin", f"{FOLDER}/fehlt.tar.gz", io.BytesIO())
    assert str(caught.value) == MSG_FILE_GONE
    assert_closed(app, times=4)


async def test_delete_own(dav: tuple[FakeDav, NcRecorder, MagicMock]) -> None:
    fake, recorder, _app = dav
    fake.add(f"{FOLDER}/{BASE}", 7)
    await NcBackupFiles().delete_own("papa", f"{FOLDER}/{BASE}")
    assert fake.deleted == [f"{FOLDER}/{BASE}"]
    assert recorder.users == ["papa"]


def test_app_env_installs_fake(app_env: Path) -> None:
    del app_env
    assert isinstance(get_backup_files(), FakeBackupFiles)


def test_singleton_defaults_to_nc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(files_module, "_files", None)
    assert isinstance(get_backup_files(), NcBackupFiles)
    assert get_backup_files() is get_backup_files()


async def test_fake_files_matches_contract(fake_files: FakeBackupFiles) -> None:
    fake_files.put("admin", f"{FOLDER}/{BASE}", b"alt")
    entry = await fake_files.upload("admin", FOLDER, BASE, _spool(5), 5, with_suffix)
    assert entry.name == "Burg-2026-10-23-1405-2.tar.gz"
    assert [e.name for e in await fake_files.listdir("admin", FOLDER)] == [BASE, entry.name]
    assert await fake_files.listdir("papa", FOLDER) == []
    fake_files.size_mismatch = True
    with pytest.raises(FilesError):
        await fake_files.upload("admin", FOLDER, BASE, _spool(5), 5, with_suffix)
