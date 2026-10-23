---
phase: 05-backup-und-restore
plan: 05
subsystem: backup
tags: [backup, cold-snapshot, background-job, http-202, verwalter-api]
requires:
  - "05-01: write_snapshot, verify_snapshot, build_manifest, BackupError/RestoreRejected, naming"
  - "05-02: BackupFiles (upload, listdir), store backups/backup_jobs, FakeBackupFiles"
  - "05-03: TimeEngine.set_halt/clear_halt"
  - "05-04: begin_offline, players_online, announce_halt, stop_for_snapshot, end_offline, WorldBusyError, _refuse_job_running"
provides:
  - "BackupService (start_backup, list_backups, recover_jobs, drain, shutdown), get_backup_service(worlds), shutdown_backups (backup/service.py)"
  - "PlayersOnline, JOB_FAILED, JOB_UNUSABLE, JOB_INTERRUPTED, RESTORE_JOB_INTERRUPTED, KIND_RESTORE, FAILED_SUBJECTS, HALT_GRACE_SECONDS, disk_free, BackupItem, BackupList"
  - "_finish_failed(world_id, uid, kind, message, started_at): einziger failed-Ausgang inkl. Benachrichtigung (Plan 06 nutzt ihn mit kind restore)"
  - "WorldService.abort_offline(ticket) und WorldService.provisioner"
  - "notify/texts.py: BACKUP_FAILED_SUBJECT, RESTORE_FAILED_SUBJECT, MAX_REASON, job_failed_message; notify/links.py: app_link"
  - "POST /api/worlds/{id}/backups (202, WorldOut), GET /api/worlds/{id}/backups (BackupListOut)"
affects:
  - "05-06 Restore (start_restore hängt sich an BackupService, _spawn, _finish_failed, abort_offline)"
  - "05-07 Frontend (BackupSection: POST mit confirm_disconnect, GET-Liste, backup_job-Polling)"
tech-stack:
  added: []
  patterns:
    - "Hintergrund-Auftrag als verfolgter asyncio-Task (Muster talk/service.py)"
    - "Zurücksetzen im finally per anyio.CancelScope(shield=True), auch beim Herunterfahren"
    - "Uhr und sleep injizierbar (Tests ohne echte 17 s Wartezeit)"
key-files:
  created:
    - src/gameworld/backup/service.py
    - src/gameworld/api/backups.py
    - tests/test_backup_service.py
    - tests/test_backups_api.py
  modified:
    - src/gameworld/worlds/service.py
    - src/gameworld/notify/texts.py
    - src/gameworld/notify/links.py
    - src/gameworld/main.py
    - tests/conftest.py
decisions:
  - "abort_offline(ticket) schon in diesem Plan (Plan 06 sah es vor): setzt previous_op_state/previous_error zurück, clear_halt und schreibt die Regeldatei sofort ohne @halt (die Welt läuft noch)"
  - "Platzprüfung, Chat-Hinweis und Wartezeit laufen vor dem Stopp; scheitern sie, gilt abort_offline (Welt unverändert, auch failed bleibt failed), ab dem Stopp immer end_offline im finally"
  - "Scheitert der Neustart nach einem gültigen Snapshot, läuft der Upload trotzdem (die Daten sind sicher); der Weltfehler steht an der Welt selbst"
  - "Unerwartete Fehler nur mit Welt-ID und Typ ins Log (LOG.error statt LOG.exception), damit kein Traceback mit Pfaden im Log landet"
  - "recover_jobs läuft im Lifespan vor yield (nicht im Reconciler-Task): so kann kein neuer Auftrag eines Requests fälschlich als unterbrochen markiert werden; den Busy-op_state räumt weiter der Boot-Abgleich"
  - "Benachrichtigung verlinkt die Übersicht (app_link, EMBED_PATH ohne Seite) statt einer neuen Seite 'welten', weil das Frontend unbekannte Seiten ohnehin auf die Übersicht leitet; ohne Link-Basis wird mit leerem Link gesendet"
  - "Grund in der Benachrichtigung per clean_value bereinigt (Docker-Meldungen könnten % oder | enthalten, AppAPI-Pitfall)"
  - "POST-Körper optional (fehlend = {}), Liste nennt den Dateinamen aus Files, Größe und Datum aus dem Nachweis, nie einen Pfad"
metrics:
  duration: "ca. 70 min"
  completed: 2026-10-23
  tasks: 3
  files: 9
---

# Phase 5 Plan 05: Sichern als Hintergrund-Job mit Verwalter-API Summary

Ein Verwalter löst per `POST /api/worlds/{id}/backups` eine Cold-Sicherung aus und bekommt sofort 202; im Hintergrund warnt die Welt spielende Kinder per `@halt`, stoppt kurz, wird gesnapshottet, startet sofort wieder, der Snapshot besteht den Restore-Probelauf und landet mit SHA-256-Nachweis in den Files des Verwalters; `GET` listet nur eigene, nachgewiesene Sicherungen.

## Was gebaut wurde

**Task 1 (Ablauf):** `BackupService.start_backup` prüft in einem Worker-Thread Spieler (ohne `confirm_disconnect` `PlayersOnline` mit D-09-Text, Einzahl/Mehrzahl), `begin_offline` und trägt den Auftrag als running ein; scheitert die Job-Zeile oder das Starten des Tasks, stellt `abort_offline` den alten Zustand her. Der Task: Spool `tempfile.TemporaryFile` unter `storage_dir/tmp`, Platzprüfung (2 x letzte eigene Sicherung, sonst `MSG_NO_SPACE`), `announce_halt` plus Warten bis `ab + 2 s`, `stop_for_snapshot`, `snapshot_to` mit `write_snapshot` ohne Sperre, `end_offline` im `finally` (abgeschirmt), `verify_snapshot`, Upload mit D-02-Namen in der Haushalts-Zeitzone und `with_suffix`, `add_backup` und Job ok. Fehler: `RestoreRejected`/`MSG_NO_MAP` ergeben `JOB_UNUSABLE`, `BackupError`/`FilesError`/`ProvisionerError` ihren festen Text, alles andere `JOB_FAILED`.

**Task 2 (Melden, Wiederanlauf, Liste):** `_finish_failed` setzt die Zeile failed und benachrichtigt nur den auslösenden Verwalter (`BACKUP_FAILED_SUBJECT`, Weltname als highlight-Parameter, Link auf die Übersicht); Erfolg bleibt still, ein Benachrichtigungsfehler wird nur geloggt. `recover_jobs` setzt running-Aufträge auf failed mit `JOB_INTERRUPTED` (Restore-Variante für Plan 06). `list_backups` bildet die Schnittmenge aus `listdir(uid, Ordner)` und `backups_for(uid, world_id)` über `(file_id, size)`; abweichende Größe oder fremde Dateien zählen zu `other_files`.

**Task 3 (API):** `api/backups.py` mit routerweitem `require_verwalter`, strengem `BackupRequest`, 202 mit aktueller `WorldOut` (backup_job running), 409 für Spieler/busy/Job läuft/delete-only, 404, 422, `FilesError` beim Auflisten als 503. `main.py`: Router eingebunden, `recover_jobs` vor `yield`, `shutdown_backups` beim Beenden. `conftest.py` setzt das Singleton zurück und wartet im `client`-Fixture auf offene Aufträge.

## Commits

| Task | Gate | Commit | Nachricht |
|------|------|--------|-----------|
| 1 | RED | 7eb0ae3 | test(05-05): add failing tests for backup job flow and error paths |
| 1 | GREEN | 31c41a9 | feat(05-05): backup job in background with offline sections and dry-run check |
| 2 | RED | 9225082 | test(05-05): add failing tests for failure notification, job recovery and backup list |
| 2 | GREEN | a1229ef | feat(05-05): failure notification, job recovery after restart and backup list |
| 3 | RED | 4cbf112 | test(05-05): add failing tests for backup API (202, 403, 404, 409, 422, list) |
| 3 | GREEN | de665a7 | feat(05-05): admin API for backup and list, lifespan wiring |

## Verifikation

- Nicht-Docker-Suite: 2167 passed, 35 deselected
- ruff check, ruff format --check, pyright (latest, 0 Fehler), vulture: grün
- tests/test_backup_service.py (31) belegt u. a.: Reihenfolge stop < snapshot < start < Upload; `@halt`-Schreibvorgang vor `stop:<id>` bei op_state backing_up (D-09, T-05-47); ohne Spieler kein Halt und kein Warten; Snapshot ohne map.sqlite und gescheiterter Probelauf ergeben `JOB_UNUSABLE` ohne Upload und ohne Nachweis; Snapshot-Fehler startet die Welt wieder; Löschen während des Uploads wirft `WorldBusyError` (T-05-48); Spool unter `storage_dir/tmp` und danach geschlossen; jeder failed-Ausgang genau eine Benachrichtigung, Erfolg keine
- tests/test_backups_api.py (22) belegt 202, 403 (Kind), 404, 409 (Spieler, busy, Job läuft, delete-only, Löschen im Upload), 422 (Zusatzfeld, String-Bool, Zahl, Liste), Pause antwortet während des Uploads unter 2 s, D-13 zweiter Verwalter sieht nichts
- Greps: `end_offline` im `finally` (Zeile in `_offline_snapshot`), `verify_snapshot` vorhanden, `LOG.` nur mit Welt-ID, Typ und Zahlen; `dependencies=[Depends(require_verwalter)]`, `backups.router` und `shutdown_backups` treffen; info.xml unverändert (nur `^/api/.*`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blockierend] `abort_offline` fehlte noch im Welt-Dienst**
- **Found during:** Task 1
- **Issue:** Der Plan verlangt `abort_offline` beim Scheitern nach `begin_offline`; die Methode war erst für Plan 06 vorgesehen.
- **Fix:** `WorldService.abort_offline(ticket)` nach der Spezifikation aus 05-06 (previous_op_state/previous_error, `clear_halt`, kein Docker-Stopp) plus sofortiges `push_time`, damit ein schon angekündigter Halt die Kinder nicht trotzdem trennt. Zusätzlich die Eigenschaft `WorldService.provisioner` für `snapshot_to` ohne Sperre.
- **Files modified:** src/gameworld/worlds/service.py (nicht in files_modified)
- **Commit:** 31c41a9

**2. [Rule 2 - Kritisch] Abbruch vor dem Stopp auch für Platzprüfung und Halt-Phase**
- **Found during:** Task 1
- **Issue:** Scheitert die Platzprüfung oder wird der Task in der Wartezeit abgebrochen, hinge die Welt sonst bis zum nächsten Boot in backing_up.
- **Fix:** `_offline_snapshot` nimmt vor dem Stopp `abort_offline`, ab dem Stopp `end_offline`; beides abgeschirmt gegen Abbruch. Test: eine fehlgeschlagene Welt bleibt nach dem Abbruch failed mit ihrem Fehlertext.
- **Commit:** 31c41a9

**3. [Plan-Abweichung, klein]** `_finish_failed` trägt zusätzlich `started_at` (die Job-Zeile braucht es); Konstruktor `BackupService(worlds, spool_dir, *, files, notifier, clock, sleep)` statt `(world_service, files_getter, notifier_getter, clock)`; `get_backup_service(worlds)` nimmt den Welt-Dienst wie `get_talk_service(store)`. Unerwartete Fehler loggen nur den Typ (`LOG.error`) statt `LOG.exception`, damit kein Traceback mit Pfaden ins Log geht (T-05-26).

## TDD Gate Compliance

Alle drei Tasks mit RED-Commit (test) vor GREEN-Commit (feat); keine REFACTOR-Commits nötig.

## Known Stubs

Keine. `RESTORE_FAILED_SUBJECT`, `KIND_RESTORE` und `RESTORE_JOB_INTERRUPTED` sind bewusst für Plan 06 angelegt.

## Self-Check: PASSED

- Alle vier neuen und fünf geänderten Dateien vorhanden, alle sechs Commits im Log gefunden, keine Dateilöschungen.
