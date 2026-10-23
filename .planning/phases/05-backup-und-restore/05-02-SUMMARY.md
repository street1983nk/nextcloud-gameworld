---
phase: 05-backup-und-restore
plan: 02
subsystem: backup
tags: [nextcloud-files, webdav, sqlite-schema, integrity]
requires: []
provides:
  - "backup/files.py: BackupFiles-Protocol, NcBackupFiles, get_backup_files(), FilesEntry, FilesError, MSG_QUOTA, MSG_UPLOAD_INCOMPLETE, MSG_FILE_GONE, MSG_FILES_FAILED, MSG_NAME_EXHAUSTED"
  - "nc_as(uid, **options)"
  - "Schema 7: backups, backup_jobs, BACKUP_TABLES, BackupRow, BackupJobRow, add_backup, backups_for, backup_by_file, set/get/delete_backup_job, running_backup_jobs, reset_event_cursor"
  - "tests/conftest.py: FakeBackupFiles (in app_env), Fixture fake_files, NcRecorder.options"
affects: [05-04, 05-05, 05-06]
tech-stack:
  added: []
  patterns: ["Protocol + Nc-Adapter + Singleton wie notify/service.py", "Aufräumen per anyio.move_on_after(shield=True)"]
key-files:
  created:
    - src/gameworld/backup/files.py
    - tests/test_backup_files.py
  modified:
    - src/gameworld/nc.py
    - src/gameworld/worlds/store.py
    - tests/conftest.py
    - tests/test_nc.py
    - tests/test_store.py
    - tests/test_forget_account.py
decisions:
  - "05-02: backups-Zeilen bleiben beim Welt-Löschen (D-08, v2-Import), backup_jobs wird mit der Welt entfernt (Plan 04)"
  - "05-02: file_id im Nachweis ist FsNode.info.fileid (int), nicht FsNode.file_id (gepaddeter Text mit Instanz-ID)"
  - "05-02: by_path wirft bei fehlendem Pfad 404; der Adapter wertet 404 als frei bzw. None"
  - "05-02: Aufräumen der eigenen Zieldatei läuft auch bei Abbruch (shield), höchstens 30 s"
  - "05-02: Sind alle Namen bis -99 belegt, FilesError MSG_NAME_EXHAUSTED (fester Text, zusätzlich zum Plan)"
metrics:
  duration: 35 min
  completed: 2026-10-23
  tasks: 2
  files: 9
---

# Phase 5 Plan 02: Files-Ablage und Sicherungsnachweis Summary

Nextcloud-Files-Adapter im Namen des auslösenden Verwalters (nc_as mit 600 s DAV-Timeout und Upload v1, freier Zielname per by_path, Größennachweis, 507 als fester Text) plus Schema 7 mit owner-gebundenen Integritätsnachweisen (backups) und Job-Zustand je Welt (backup_jobs).

## Tasks

| Task | Name | Commits |
|------|------|---------|
| 1 | Schema 7 mit backups und backup_jobs | 4ba0210 (RED), 2b8226a (GREEN) |
| 2 | nc_as-Optionen und Files-Adapter backup/files.py | c2dc29a (RED), eb7a047 (GREEN) |

## Was entstanden ist

- **store.py**: SCHEMA_VERSION 7, Tabellen `backups` (PK owner_uid, file_id; Index owner_uid, world_id) und `backup_jobs` (eine Zeile je Welt). `backup_by_file` filtert immer auf owner_uid (T-05-10, Test fremder uid ergibt None). `INSERT OR REPLACE` bei gleicher (owner_uid, file_id). ACCOUNT_TABLES-Kommentar ergänzt (backups.owner_uid ist Verwalter).
- **nc.py**: `nc_as(uid, **options)` reicht Optionen an `AsyncNextcloudApp` weiter; Test belegt, dass `cfg.options.timeout_dav == 600` und `upload_chunk_v2 is False` in der echten Session ankommen.
- **backup/files.py**: `NcBackupFiles` mit upload, listdir, stat, download_to, delete_own; je Vorgang eigener Client. Bei Fehler nach Namenswahl wird nur der frisch gewählte Name gelöscht, eine vorhandene Datei mit dem Basisnamen nie. Log nur Aktion, Typ und Statuscode (Test prüft: kein Pfad, kein Konto im Log).
- **conftest.py**: `FakeBackupFiles` (In-Memory je uid, `upload_error`, `size_mismatch`, `download_error`, `calls`, `put()`), in `app_env` gesetzt, Fixture `fake_files`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] test_forget_account.py prüfte Schema-Version hart auf "6"**
- **Found during:** Task 1
- **Fix:** Vergleich auf `SCHEMA_VERSION` umgestellt
- **Commit:** 4ba0210

**2. [Rule 2 - Correctness] by_path wirft 404 statt None**
- **Found during:** Task 2 (Quelltext nc_py_api 0.30.3: PROPFIND auf fehlenden Pfad läuft über check_error)
- **Fix:** Hilfsfunktion `_by_path` wertet 404 als None; sonst wäre jede Namenswahl gescheitert
- **Commit:** eb7a047

**3. [Rule 2 - Correctness] Erschöpfte Suffixe**
- **Fix:** Fester Text MSG_NAME_EXHAUSTED statt rohem Fehler, wenn bis -99 alles belegt ist
- **Commit:** eb7a047

## Verification

- `pytest tests/test_store.py tests/test_nc.py tests/test_backup_files.py`: grün (auch mit `-W error`)
- Nicht-Docker-Suite: 1995 passed, 35 deselected
- ruff check, ruff format --check, pyright (latest, 0 Befunde), vulture: grün

## TDD Gate Compliance

RED vor GREEN je Task: 4ba0210 -> 2b8226a, c2dc29a -> eb7a047.

## Known Stubs

Keine. Der Adapter wird erst vom Ablauf (Plan 05) aufgerufen; das ist geplant.

## Self-Check: PASSED
