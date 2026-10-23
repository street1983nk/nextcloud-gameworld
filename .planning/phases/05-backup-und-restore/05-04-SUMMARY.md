---
phase: 05-backup-und-restore
plan: 04
subsystem: worlds
tags: [status-model, reconciler, guards, busy-op-state, kid-texts, offline-sections]
requires:
  - "05-01: DockerProvisioner.snapshot_to / put_world_archive"
  - "05-02: store.get_backup_job / delete_backup_job / running_backup_jobs, BackupRow"
  - "05-03: TimeEngine.set_halt / clear_halt"
provides:
  - "BUSY_OP_STATES, ReconcileAction.CLEAR_BUSY, ReconcileAction.MARK_RESTORE_INTERRUPTED (reconciler.py)"
  - "BACKING_UP, RESTORING, TEXT_BACKING_UP, TEXT_RESTORING (status.py)"
  - "WorldBusyError, WORLD_BUSY, JOB_RUNNING, RESTORE_INTERRUPTED, HALT_LEAD_SECONDS, OfflineTicket, BackupJobView (service.py)"
  - "WorldService.begin_offline / players_online / announce_halt / stop_for_snapshot / end_offline / book_ledger"
  - "WorldOut.backup_job (BackupJobOut), TEXT_WELT_PAUSE in /api/my/worlds"
  - "FakeProvisioner.snapshot_to / put_world_archive, snapshots, snapshot_errors, put_archives"
affects:
  - "05-05 BackupService (reiht die Offline-Abschnitte aneinander)"
  - "05-06 Restore (abort_offline, mark_swap, restore_swap bauen auf OfflineTicket auf)"
tech-stack:
  added: []
  patterns:
    - "Busy-Zustand persistiert in op_state, Sperre nur je kurzem Abschnitt"
    - "Boot-Abgleich: CLEAR_BUSY, dann erneute Auswertung der frischen Zeile"
key-files:
  created: []
  modified:
    - src/gameworld/worlds/status.py
    - src/gameworld/worlds/reconciler.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - src/gameworld/api/me.py
    - tests/test_status.py
    - tests/test_reconciler.py
    - tests/test_service_lifecycle.py
    - tests/test_my_worlds.py
decisions:
  - "players_online prüft zusätzlich Container running, Schema >= 2 und mtime >= StartedAt: Eine Status-Datei überdauert den Stopp, sonst zählten alte Namen"
  - "begin_offline ohne allow_failed lehnt nur delete-only ab; eine gewöhnlich fehlgeschlagene Welt (etwa Proxy weg) bleibt sicherbar"
  - "_refuse_job_running ist Instanzmethode statt staticmethod, weil sie den Store braucht"
  - "end_offline fängt auch unerwartete Ausnahmen (z. B. ValueError aus unbekanntem Preset) und setzt failed mit OFFLINE_RESTART_FAILED, damit keine Welt in backing_up hängen bleibt"
  - "RETRY_DELETE im Boot-Abgleich entfernt wie das normale Löschen auch die backup_jobs-Zeile"
metrics:
  duration: "ca. 45 min"
  completed: 2026-10-23
  tasks: 3
  files: 9
---

# Phase 5 Plan 04: Busy-Zustände, Sperren und Offline-Abschnitte im Welt-Dienst Summary

Der Welt-Dienst kennt jetzt backing_up, restoring und restoring_swap als persistierte Busy-Zustände: Status mit festen Elterntexten (D-10), 409 für alle Elternaktionen, Pause und Talk-Takt ohne Neustart bzw. Meldung, Boot-Abgleich ohne delete-only für einen unterbrochenen Tausch, backup_job in der Weltenliste und kurze Offline-Abschnitte für den Hintergrund-Job aus Plan 05/06.

## Was gebaut wurde

**Task 1 (Status und Regeln):** `derive_status` liefert nach `unreachable` und vor `creating` die Codes `backing_up` ("Wird gesichert ...") und `restoring` ("Wird wiederhergestellt ...", auch für restoring_swap). `BUSY_OP_STATES` liegt einmalig in reconciler.py. `decide_boot` gibt für restoring_swap immer `MARK_RESTORE_INTERRUPTED` (vor jeder Volume-Logik), für backing_up/restoring `CLEAR_BUSY`; `needs_volume_check` und `decide_periodic` schließen Busy-Zeilen aus.

**Task 2 (Guards und Ansicht):** `_refuse_busy(row)` in Start, Stopp, Neustart und Löschen; `_refuse_job_running` sperrt das Löschen während der Upload-Phase (op_state ready, Job running). `WorldBusyError` wird in `_http_error` zu 409. `_pause_world` schreibt bei busy Welten nur die Regeldatei, `_track_run_state` überspringt sie, `_status_file` liest nichts. Boot: CLEAR_BUSY setzt ready und wertet die frische Zeile neu aus (Welt startet wieder, D-11); restoring_swap wird failed mit `RESTORE_INTERRUPTED`, das bewusst nicht in `DELETE_ONLY_ERRORS` steht. `WorldView.backup_job` (frozen `BackupJobView`) in beiden Zweigen von `_collect`, auch bei "Docker nicht erreichbar"; `WorldOut.backup_job` als `BackupJobOut`. Löschen entfernt die backup_jobs-Zeile, backups-Zeilen bleiben. `/api/my/worlds` zeigt bei Busy-Status "Die Welt macht kurz Pause" und kein backup_job-Feld.

**Task 3 (Offline-Abschnitte):** `begin_offline` (Ein-Job-Schutz global über Busy-Zeilen und laufende Jobs, `JOB_RUNNING`; DeleteOnlyError ohne `allow_failed`), `players_online` (direkt `read_status_file` + `parse_players`, unabhängig von op_state), `announce_halt` (`set_halt(now + 15)` + `push_time`), `stop_for_snapshot`, `end_offline` (clear_halt, forget, ggf. `_launch`, immer ready oder failed, Fehler als Rückgabewert), `book_ledger`. Jeder Abschnitt nimmt `_mutating()` nur für sich; der Nebenläufigkeitstest belegt `apply_pause_sync` unter 1 s während der Offline-Phase. FakeProvisioner: `snapshot_to` (Chunks in SNAPSHOT_CHUNK, Fehlerinjektion, verweigert laufende Container), `put_world_archive`.

## Commits

| Task | Gate | Commit | Nachricht |
|------|------|--------|-----------|
| 1 | RED | 95ed477 | test(05-04): add failing tests for busy op states in status and reconciler |
| 1 | GREEN | 1611ddc | feat(05-04): busy op states in status model and reconciler rules |
| 2 | RED | e950bab | test(05-04): add failing tests for busy guards, pause/tick exceptions and backup_job view |
| 2 | GREEN | e43546c | feat(05-04): busy guards, pause/tick exceptions, backup_job view and kid pause text |
| 3 | RED | 7d40aa8 | test(05-04): add failing tests for offline sections and extended FakeProvisioner |
| 3 | GREEN | b9cbeee | feat(05-04): short offline sections in WorldService for backup and restore jobs |

## Verifikation

- Nicht-Docker-Suite: 2114 passed, 35 deselected
- ruff check, ruff format --check, pyright (latest, 0 Fehler), vulture: grün
- Akzeptanz-Greps: `BUSY_OP_STATES = ` genau einmal (reconciler.py); `_refuse_busy(row)` 4x; `_refuse_job_running` in `_delete_world_sync`; `DELETE_ONLY_ERRORS` ohne RESTORE_INTERRUPTED; kein backup_job in api/me.py; sechs öffentliche Offline-Methoden; `parse_players` in players_online

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] players_online zählte sonst Namen eines gestoppten Containers**
- **Found during:** Task 3
- **Issue:** Die Status-Datei bleibt nach dem Stopp im Volume; ein reines `read_status_file` hätte bei gestoppter Welt alte Spieler gezählt (Plan verlangt 0).
- **Fix:** Vorher `list_managed` (Container running, Schema >= 2) und Frische-Prüfung mtime >= StartedAt wie in der Ansicht.
- **Files modified:** src/gameworld/worlds/service.py
- **Commit:** b9cbeee

**2. [Rule 2 - Kritisch] end_offline fängt auch unerwartete Fehler**
- **Found during:** Task 3
- **Issue:** Nur ProvisionerError zu fangen hätte eine Welt bei z. B. ValueError aus `_payload` in backing_up hängen lassen (Pitfall 7).
- **Fix:** Zusätzlicher `except Exception` mit `LOG.exception` und `OFFLINE_RESTART_FAILED`, Zustand failed, Rückgabe statt Wurf.
- **Commit:** b9cbeee

**3. [Rule 2 - Kritisch] RETRY_DELETE räumt backup_jobs mit auf**
- **Found during:** Task 2
- **Issue:** Ein beim Boot nachgeholtes Löschen hätte eine verwaiste Job-Zeile hinterlassen.
- **Fix:** `delete_backup_job` auch im RETRY_DELETE-Zweig.
- **Commit:** e43546c

**4. [Plan-Abweichung, klein] `_refuse_job_running` als Instanzmethode**, weil sie `self._store` braucht; `status_files` im Fake blieb `dict[str, StatusFile]` (bestehendes Feld, nicht bytes).

## TDD Gate Compliance

Alle drei Tasks mit RED-Commit (test) vor GREEN-Commit (feat); keine REFACTOR-Commits nötig.

## Known Stubs

Keine.

## Self-Check: PASSED

- Alle neun geänderten Dateien vorhanden, alle sechs Commits im Log gefunden, keine Dateilöschungen.
