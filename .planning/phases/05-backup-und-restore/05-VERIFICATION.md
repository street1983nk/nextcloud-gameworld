---
phase: 05-backup-und-restore
verified: 2026-10-24T00:00:00Z
status: passed
score: 3/3 Success Criteria verifiziert (BACKUP-01, BACKUP-02 erfüllt)
overrides_applied: 0
human_verification: []
---

# Phase 5: Backup und Restore, Verifikationsbericht

**Phasenziel:** Weltstände liegen sicher in Nextcloud Files und lassen sich nachweislich wiederherstellen
**Status:** passed
**Re-Verifikation:** Nein, Erstverifikation

## Beobachtbare Wahrheiten

| # | Wahrheit | Status | Beleg im Code |
|---|----------|--------|---------------|
| 1 | Manuelles Backup pro Welt, Welt wird sauber gestoppt, gesichert, wieder gestartet (Cold-Backup) | VERIFIZIERT | `backup/service.py`: `start_backup`, `_prepare` (begin_offline), `_offline_snapshot`, `_finish_ok`; Endpunkt `POST /api/worlds/{id}/backups` (202) in `api/backups.py`; Busy-Zustand `backing_up` in `worlds/status.py` |
| 2 | Snapshot landet als konsistente Datei in Files (Gameworld/Sicherungen/<Welt>/), kein Kopieren laufender map.sqlite | VERIFIZIERT | `backup/naming.py` BACKUPS_ROOT = "Gameworld/Sicherungen"; `backup/files.py` Upload per Temp-Datei plus MOVE, Größenprüfung, `_verify` nach Snapshot; Snapshot nur bei gestoppter Welt (`snapshot_to` im Offline-Abschnitt) |
| 3 | Restore aus Backup in Files, Roundtrip nachgewiesen | VERIFIZIERT | `start_restore` mit Bestätigung, Hash-Prüfung (`_check_integrity`), `restore_swap` baut Volume neu auf (`remove_world(keep_volume=False)`, `create_world_container(reuse_volume=False)`, `put_world_archive`); Roundtrip-Test in `tests/e2e/test_backup_restore_e2e.py`; Abnahmeskript 103/103 (laut deferred-items.md) |

**Score:** 3/3

## Entscheide (Stichprobe, eigene Gegenproben)

| Entscheid | Befund |
|-----------|--------|
| D-09 Halt spielender Kinder mit Vorwarnung und Pausentext | `provisioner/time_mod.py`: `@halt <ab>`, TEXT_HALT_SOON "Die Welt macht gleich eine kurze Pause.", TEXT_HALT "Die Welt macht kurz Pause. Gleich geht es weiter."; `playtime/engine.py` set_halt/clear_halt, nur im Speicher; `restore_swap` ruft `clear_halt` vor `_payload` |
| D-15 Restore auch für kaputte Welten | `_prepare_restore` ruft `begin_offline(..., allow_failed=True)`; Docstring und Test `test_restore_service.py` |
| vor-restore-Sicherung | `_safety_backup` mit `KIND_VOR_RESTORE`, eigener Nachweis; Rückfall `_fallback` auf lokalen Snapshot, sonst `RESTORE_INTERRUPTED` |
| D-12 nur DB-gelistete Sicherungen | `list_backups` zeigt nur Dateien mit passendem (file_id, Größe) aus der Nachweis-Tabelle; Rest zählt `other_files`; `_prepare_restore` verlangt `backup_by_file` und `proof.world_id == world_id` vor jedem Docker-/Files-Aufruf |
| D-13 Verwalter-Scoping | `backups_for(owner_uid, world_id)` und `backup_by_file(owner_uid, file_id)` filtern nach `owner_uid`; Router mit `Depends(require_verwalter)` routerweit; Konto kommt aus Auth, nicht aus dem Body |
| D-08 App löscht nie | Einzige `files.delete`-Stellen in `backup/files.py` (Zeile 181 und 239): 181 entfernt nur die eigene Temp- bzw. frisch verschobene Datei im Fehlerpfad; `delete_own` (239) hat keine produktiven Aufrufer (IN-01, toter Code, harmlos) |
| D-16 Notify nur bei Fehlern | Einziger `notify`-Aufruf in `_finish_failed` (service.py:419), nur an den auslösenden `uid`; Erfolgspfade `_finish_ok`/`_finish_restore_ok` benachrichtigen nicht |
| Frontend | `frontend/src/components/BackupSection.vue` (Verwalter, in `ParentView.vue` eingebunden, BUSY_STATUS backing_up/restoring); Kind-Sicht: `api/me.py` führt Status backing_up/restoring, Kindertext aus `worlds/status.py` (TEXT_BACKING_UP, TEXT_RESTORING) |

## Gegenproben

| Prüfung | Ergebnis |
|---------|----------|
| `pytest tests/test_backup_archive.py tests/test_restore_service.py tests/test_backups_api.py tests/test_restore_api.py tests/test_backup_files.py` (seriell) | 158 passed in 53,8 s |
| Alle 9 Pläne mit SUMMARY vorhanden, ROADMAP zeigt 9/9 | bestätigt |
| BACKUP-01, BACKUP-02 in REQUIREMENTS.md auf Complete, durch Code gedeckt | bestätigt |
| Owner-Playwright-Abnahme (7 Schritte approved, 05-09-SUMMARY.md) | Beleg dokumentiert; nicht erneut ausgeführt |

## Anti-Patterns

Keine Blocker. Die 7 offenen Info-Findings (IN-01 bis IN-07, 05-REVIEW.md) sind nicht fixpflichtig und blockieren das Ziel nicht. Hinweis: IN-03 (D-09-Race Spielerprüfung) und IN-05 (recover_jobs-Fehler beim Start blockiert Ein-Job-Schutz bis zum Neustart) sind Randfälle, kein Zielverstoß.

## Nicht erneut ausgeführt

Die 40-minütige Abnahme (103/103) und die Playwright-Abnahme wurden wie angewiesen nicht wiederholt; ihre Belege stammen aus deferred-items.md und 05-09-SUMMARY.md. Die Gesamttestsuite (2245 Tests) wurde nicht komplett laufen gelassen, nur die gezielten 158 Tests.

## Lücken

Keine.

_Verifiziert: 2026-10-24, Verifier: Claude (gsd-verifier)_
