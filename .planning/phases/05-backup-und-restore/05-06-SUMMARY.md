---
phase: 05-backup-und-restore
plan: 06
subsystem: backup
tags: [restore, fresh-volume, integrity, safety-backup, crash-safety]
requires:
  - "05-01: prepare_restore, sha256_of, ledger_tar, write_snapshot, verify_snapshot, KIND_VOR_RESTORE, put_world_archive"
  - "05-02: store.backup_by_file, reset_event_cursor, add_backup, set_backup_job; BackupFiles.download_to/upload"
  - "05-03: TimeEngine.set_halt/clear_halt"
  - "05-04: begin_offline(allow_failed), announce_halt, stop_for_snapshot, end_offline, book_ledger, RESTORE_INTERRUPTED, MARK_RESTORE_INTERRUPTED"
  - "05-05: BackupService (_spawn, _finish_failed, _shielded), abort_offline, KIND_RESTORE, RESTORE_FAILED_SUBJECT, api/backups.py"
provides:
  - "WorldService.mark_swap / restore_swap / finish_swap / mark_restore_interrupted (worlds/service.py), gemeinsamer _relaunch mit end_offline"
  - "BackupService.start_restore mit Phasen A (holen und prüfen), B (Stopp und vor-restore), C (Tausch, Rückfall)"
  - "RestoreNotConfirmed, BackupNotFound, RestoreTampered, restore_text; Texte RESTORE_NOT_CONFIRMED, BACKUP_NOT_FOUND, RESTORE_TAMPERED, RESTORE_FAILED, RESTORE_FALLBACK, RESTORE_SWAP_FAILED"
  - "POST /api/worlds/{world_id}/restore (202, WorldOut mit status restoring)"
affects:
  - "05-07 Frontend (Wiederherstellen-Dialog: POST mit file_id, confirm, confirm_disconnect; backup_job kind restore)"
  - "05-08 echter Roundtrip gegen Docker (restore_swap mit echtem Volume-Neuaufbau)"
tech-stack:
  added: []
  patterns:
    - "Zerstören erst nach Beweis: Phase A ohne Stopp, Phase B mit end_offline-Rückweg, Phase C mit persistiertem Stufenmarker"
    - "Docker-Schritte des Tauschs ohne _LOCK, Busy-Zustand in der Datenbank"
key-files:
  created:
    - tests/test_restore_service.py
    - tests/test_restore_api.py
  modified:
    - src/gameworld/worlds/service.py
    - src/gameworld/backup/service.py
    - src/gameworld/api/backups.py
    - tests/test_service_lifecycle.py
decisions:
  - "prepare_restore prüft das Manifest gegen die Spielart der Weltzeile (ticket.preset), nicht gegen BackupRow.preset: der Neuaufbau nimmt _payload(row), beides muss zusammenpassen"
  - "Lua, worldmods/ und world.mt aus einer Sicherung werden wie in Plan 01 verworfen (nicht abgelehnt); Tests belegen, dass sie nie ins eingespielte Tar gelangen"
  - "Scheitert nach gelungenem Tausch nur der Start, ist der Auftrag ok (Daten eingespielt); den Startfehler zeigt die Welt selbst (wie beim Sichern)"
  - "Endgültig gescheiterter Tausch: Auftragstext RESTORE_SWAP_FAILED, Weltfehler RESTORE_INTERRUPTED (wiederholbar, nicht delete-only)"
  - "file_id nur als echte JSON-Ganzzahl 1 bis 2^63-1; größere Werte wären in SQLite ein Fehler 500"
  - "Welten mit RESTORE_INTERRUPTED bekommen wie RECONCILE_DATA_MISSING keine vor-restore-Sicherung (D-15)"
metrics:
  duration: "ca. 75 min"
  completed: 2026-10-23
  tasks: 3
  files: 6
---

# Phase 5 Plan 06: Wiederherstellen über frisches Volume Summary

Ein Verwalter stellt per `POST /api/worlds/{id}/restore {file_id, confirm: true}` eine eigene Sicherung dieser Welt wieder her (202); im Hintergrund wird die Datei heruntergeladen, gegen Größe und SHA-256 des eigenen Nachweises geprüft und vollständig gefiltert, bevor die Welt angefasst wird. Danach folgen Halt, Stopp, eine geprüfte vor-restore-Sicherung in Files und der Tausch über ein frisches Volume mit Rückfall auf den lokalen Sicherheits-Snapshot.

## Was gebaut wurde

**Task 1 (Tausch im WorldService):** `mark_swap` persistiert `restoring_swap` unter der Sperre vor jedem Docker-Aufruf. `restore_swap` ruft zuerst `clear_halt` (sonst rendert `_payload` den Halt mit), dann ohne `_LOCK`: `remove_world(keep_volume=False)` (fehlender Container toleriert), `ensure_image`, `create_world_container(reuse_volume=False)` mit `_payload(row)`, `put_world_archive` für das Restore-Tar (zurückgespult) und das bewahrte Zählbuch, `reset_event_cursor`, `time.forget`. `finish_swap` und `end_offline` teilen sich `_relaunch` (Start nur bei was_running, immer ready oder failed, desired_state unverändert). `mark_restore_interrupted` setzt failed mit `RESTORE_INTERRUPTED`, ohne Halt.

**Task 2 (Ablauf):** `start_restore` prüft synchron Bestätigung, eigenen Nachweis mit Welt-Abgleich (vor jedem Docker- oder Files-Aufruf), Spieler und `begin_offline(..., allow_failed=True)`. Phase A ohne Stopp: Platz (3 x Größe), Download in einen Spool, Größe und SHA-256, `prepare_restore`; Fehler ergeben `abort_offline`. Phase B: Halt mit Wartezeit, Stopp, Zählbuch verbuchen und unverändert bewahren, bei Bedarf Sicherheits-Snapshot (`KIND_VOR_RESTORE`), Probelauf, Upload `...-vor-restore.tar.gz` und Nachweis; Fehler ergeben `end_offline` (alte Welt läuft wieder). `MSG_NO_MAP` im Sicherheits-Snapshot heißt: nichts zu bewahren, weiter. Phase C: `mark_swap`, Tausch mit zweitem Versuch, sonst Rückfall über `prepare_restore(Sicherheits-Snapshot)`, sonst `mark_restore_interrupted`. Jeder Fehlerausgang geht über `_finish_failed` mit `RESTORE_FAILED_SUBJECT`; alle Spools werden im `finally` geschlossen.

**Task 3 (API):** `RestoreRequest` streng (`extra="forbid"`, `strict=True`, `file_id` per `_whole_number` und 1 bis 2^63-1), Route unter dem routerweiten `require_verwalter`; 409 für fehlende Bestätigung, Spieler, busy und laufenden Auftrag, 404 für fremde, unbekannte oder andere Welt, 202 mit `status restoring`.

## Commits

| Task | Gate | Commit | Nachricht |
|------|------|--------|-----------|
| 1 | RED | 3e9134f | test(05-06): add failing tests for restore swap on fresh volume |
| 1 | GREEN | 2070432 | feat(05-06): restore swap on fresh volume in WorldService |
| 2 | RED | 7473ebf | test(05-06): add failing tests for restore flow with integrity and fallback |
| 2 | GREEN | 113a38d | feat(05-06): restore job with integrity check, vor-restore backup and fallback |
| 3 | RED | 11f97cd | test(05-06): add failing tests for restore API (202, 403, 404, 409, 422) |
| 3 | GREEN | c594173 | feat(05-06): admin API route for restore |

## Verifikation

- Nicht-Docker-Suite: 2236 passed, 35 deselected
- ruff check, ruff format --check, pyright (latest, 0 Fehler), vulture: grün
- tests/test_service_lifecycle.py: op_state restoring_swap zum Zeitpunkt von remove; Reihenfolge remove < create < put < put(ledger) < start; frisches Volume `(id, False)` bei remove und create; Regeldatei im Payload ohne `@halt` (mit Positivkontrolle); finish_swap mit was_running False ohne start und ohne Halt; mark_restore_interrupted und abort_offline ohne Halt; Pause läuft während des Tauschs unter 1 s durch
- tests/test_restore_service.py (31): SHA- und Größenabweichung, Traversal und Symlink ohne `stop:`/`remove:`; Lua/world.mt nie eingespielt; D-09 `@halt` vor `stop:` im Zustand restoring; D-15 delete-only ohne vor-restore auf ready; Welt ohne Karte ohne vor-restore; einmal wiederholt; Rückfall nach zwei Tauschfehlern spielt den Stand "neu" ein; danach interrupted; Spools geschlossen (ok, manipuliert, Rückfall)
- Gegenprobe mit Mutation: Integritätsprüfung abgeschaltet lässt die Manipulationstests scheitern, Rückfall abgeschaltet den Rückfalltest
- Greps: `clear_halt` 5x in worlds/service.py, `keep_volume=False` in restore_swap, `"/worlds/{world_id}/restore"` in api/backups.py, `backup_by_file` in `_prepare_restore`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Kritisch] Obergrenze für file_id**
- **Found during:** Task 3
- **Issue:** Eine Ganzzahl über 2^63-1 hätte beim SQLite-Binden einen OverflowError (500) statt 422 ergeben.
- **Fix:** `Field(ge=1, le=MAX_FILE_ID)`, Test mit 2^63.
- **Commit:** c594173

**2. [Plan-Abweichung] Lua in worldmods/ wird verworfen, nicht abgelehnt**
- **Found during:** Task 2
- **Issue:** Die Plan-Verhaltensliste nennt für `worldmods/x/init.lua` "Job failed"; der Archiv-Kern aus Plan 01 (`_restore_dropped`, eigene Tests) verwirft Code aber bewusst still (T-05-30 "verwirft").
- **Fix:** Kein Eingriff in Plan 01; der Test belegt stattdessen, dass `.lua`, `worldmods/` und `world.mt` nie im eingespielten Tar landen. Traversal und Symlink werden wie geplant vor dem Stopp abgelehnt.
- **Commit:** 7473ebf, 113a38d

**3. [Plan-Abweichung, klein]** Manifest-Prüfung gegen `ticket.preset` (Weltzeile) statt `BackupRow.preset`; `_abort_start` mit `kind` und `message`, `_snapshot` mit `kind`, `_add_proof` als gemeinsamer Nachweis-Schreiber; `finish_swap`/`end_offline` über `_relaunch`; FakeProvisioner protokolliert `remove:<id>` in `calls` (bestehende Suite unverändert grün).

## TDD Gate Compliance

Alle drei Tasks mit RED-Commit (test) vor GREEN-Commit (feat); keine REFACTOR-Commits nötig.

## Known Stubs

Keine.

## Self-Check: PASSED

- Alle zwei neuen und vier geänderten Dateien vorhanden, alle sechs Commits im Log gefunden, keine Dateilöschungen.
