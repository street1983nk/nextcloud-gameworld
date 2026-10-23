---
phase: 05-backup-und-restore
plan: 08
subsystem: backup
tags: [e2e, roundtrip, docker, negative-tests, independent-check, halt]
requires:
  - "05-05: BackupService.start_backup/drain, recover_jobs, Job-Zustände"
  - "05-06: start_restore mit Phasen A/B/C, mark_swap, restore_swap, RESTORE_INTERRUPTED"
  - "05-03/05-04: set_halt/clear_halt, announce_halt, players_online"
provides:
  - "tests/e2e/backup_helpers.py: LocalFolderFiles (BackupFiles-Attrappe), copy_out/put_files über eigenen Docker-Client, players_in/integrity_ok/block_count (sqlite3 mode=ro), forged_backup"
  - "tests/e2e/test_backup_restore_e2e.py: Roundtrip, 4 Negativfälle, Lua-Verwurf, Absturz im Tausch"
  - "tests/e2e/test_halt_e2e.py: Chat-Hinweis, Kick, Prejoin-Sperre und Positivkontrolle gegen echtes Luanti"
affects:
  - "05-09 echter Nextcloud-Files-Weg (ersetzt LocalFolderFiles durch NcBackupFiles)"
tech-stack:
  added: []
  patterns:
    - "Gegenprobe über unabhängiges Muster: eigener docker.DockerClient (get_archive, put_archive, events), sqlite3 nur lesend, eigene Literale statt Konstanten der Umsetzung"
    - "Prozesstod per BaseException-Unterklasse plus stillgelegtem mark_restore_interrupted simuliert"
key-files:
  created:
    - tests/e2e/backup_helpers.py
    - tests/e2e/test_backup_restore_e2e.py
    - tests/e2e/test_halt_e2e.py
  modified: []
decisions:
  - "Lua in worldmods/ ist ein eigener Test (Job ok, Code nie eingespielt), nicht Teil des Ablehnungs-Parametrisierung, passend zur 05-06-Entscheidung 'verwerfen statt ablehnen'"
  - "Gegenprobe nach dem Restore vor dem ersten Start (Welt war gestoppt, was_running False): so bleiben Blockzahl und Zählbuch unberührt vom laufenden Server; danach Start und Mia-Beitritt als Funktionsbeleg"
  - "Snapshot am gestoppten Container doppelt belegt: Zustand über eigenen Client im Moment des snapshot_to-Aufrufs (exited) und Docker-Ereignisfolge die -> archive-path -> start"
  - "Getauschte Datei mit gleicher Größe (ein Byte gekippt), damit der SHA-256 und nicht die Größe entscheidet"
metrics:
  duration: "ca. 45 min"
  completed: 2026-10-23
  tasks: 3
  files: 3
---

# Phase 5 Plan 08: Backup-Restore-Roundtrip gegen echtes Docker Summary

Ein automatisierter Roundtrip-Test gegen den echten Docker-Proxy: Mia vor der Sicherung, Leo danach, kaputte map.sqlite plus heißes Journal, Restore, danach Mia da und Leo weg. Geprüft wird über ein unabhängiges Muster (eigener Docker-Client, sqlite3 nur lesend). Dazu kommen Negativtests mit manipulierten Sicherungen, eine Absturzsimulation im Tausch und der @halt-Ablauf gegen echtes Luanti.

## Was gebaut wurde

**Task 1 (backup_helpers.py):** `LocalFolderFiles` erfüllt das BackupFiles-Protocol auf `tmp_path/files/<uid>/...` (file_id fortlaufend, Größe aus dem Dateisystem, Suffix-Kollisionen, `uploads`-Protokoll, `replace_bytes`, `put`). `copy_out` holt Dateien oder Ordner über das rohe `api.api.get_archive` und entpackt sie mit dem data-Filter, `put_files` legt Dateien per `put_archive` ab. `players_in`, `integrity_ok` und `block_count` öffnen SQLite nur über `file:...?mode=ro`. `forged_backup` baut Manifest und Tar selbst (traversal, symlink, lua, foreign_preset), jeweils mit gültiger `world/map.sqlite`. Kein `DockerProvisioner` im Modul.

**Task 2 (test_backup_restore_e2e.py, 7 Tests):**
- Roundtrip: Einladungen für Mia und Leo über die API (Anzeigenamen in FakeDirectory), Mia spielt, Sicherung mit Bestätigung. Der eigene Client sah den Container beim Snapshot `exited`, und die Ereignisfolge zeigt `archive-path` zwischen `die` und `start`. Im Archiv liegen Manifest und `world/map.sqlite`, aber keine `gameworld_*`-Datei und kein `worldmods/`. Dann spielt Leo, die Welt wird gestoppt und mit Zufallsbytes plus `map.sqlite-journal` zerstört (Positivkontrolle: `integrity_ok` False). Nach dem Restore: Mia vorhanden, Leo nicht, `integrity_check` ok, Blockzahl gleich der im Archiv und größer 0, kein Journal, Zählbuch-Bytes identisch, die vor-restore-Sicherung enthält Leo. Danach Start und erneuter Beitritt von Mia.
- Negativ (parametrisiert: traversal, symlink, foreign_preset, swapped): Job failed (bei swapped mit dem Text "Die Sicherung wurde verändert ..."). Container-ID, Volume-Name und StartedAt bleiben gleich, der Container läuft, es gibt keinen neuen Upload, und die Welt steht auf ready/running, nicht delete-only.
- Lua: Job ok, `worldmods/x/init.lua` landet nie in der Welt, und die eigenen Mods sind frisch provisioniert.
- Absturz: `create_world_container` wirft `SimulatedCrash(BaseException)` nach `mark_swap` und `remove_world`, `mark_restore_interrupted` ist stillgelegt (ein toter Prozess schreibt nichts mehr). Danach gilt: op_state `restoring_swap`, Job running, kein Container. `fresh_service().boot_reconcile()` und `recover_jobs()` eines frischen BackupService (== 1) ergeben failed mit `RESTORE_INTERRUPTED`, `delete_only` False und den Job failed. Ein erneuter Restore gelingt, und Mia ist in players.sqlite.

**Task 3 (test_halt_e2e.py):** Mia hält eine Sitzung, `players_online` meldet 1 (echter Lesepfad), `announce_halt` setzt den Halt. Das Ergebnis ist `kicked` mit "Die Welt macht kurz Pause. Gleich geht es weiter.", davor kam der Chat "Die Welt macht gleich eine kurze Pause.", und der Kick lag nicht früher als ab minus 2 s. Während des Halts wird ein Beitritt abgelehnt. Nach `clear_halt` plus `push_time` gelingt `held`. Die Texte stehen als Literale im Test.

## Commits

| Task | Commit | Nachricht |
|------|--------|-----------|
| 1 | 1959f77 | test(05-08): backup e2e helpers with local files fake and independent checks |
| 2 | 97624c4 | test(05-08): backup restore roundtrip, manipulation and crash e2e against real docker |
| 3 | 38a6cb3 | test(05-08): halt chat notice, kick and prejoin lock against real luanti |

## Verifikation

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q tests/e2e/test_backup_restore_e2e.py`: 7 passed (Roundtrip 26 s, Rest 48 s)
- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q tests/e2e/test_halt_e2e.py`: 1 passed (29 s)
- Gegenprobe mit Mutation: Mit abgeschalteter Größen- und SHA-Prüfung in `_check_integrity` scheitert der Fall `swapped` (der Restore spielte die gekippte Datei sonst ein). Danach wurde die Quelle per `git checkout` zurückgesetzt.
- ruff check, ruff format --check, pyright (latest, 0 Fehler), vulture: grün
- Greps: `class LocalFolderFiles` trifft, `DockerProvisioner` in backup_helpers.py ohne Treffer, `mode=ro` trifft, das Halt-Literal trifft in test_halt_e2e.py
- Nach den Läufen keine gameworld-*-Reste der Test-Instanzen. Die zwei `gameworld-788fff30-*` laufen seit 12:11 und sind fremd, sie blieben unangetastet.

## Deviations from Plan

**1. [Plan-Abweichung] Lua-Fall nicht als Ablehnung.** Der Plan nennt `worldmods/x/init.lua` unter "abgelehnt, Container-ID unverändert". Der Archiv-Kern verwirft Code aber bewusst (05-06, T-05-30), der Restore läuft also durch. Deshalb gibt es einen eigenen Test: Job ok, und der Code ist nachweislich nicht in der Welt.

**2. [Plan-Abweichung, klein] Gegenprobe vor dem ersten Start statt "Welt stoppen".** Die Welt war für die Zerstörung gestoppt, also startet `finish_swap` nicht (was_running False). Geprüft wird darum am frisch erzeugten, noch nicht gestarteten Container. Danach folgen `start_world`, Status running und Mias Beitritt.

**3. [Plan-Abweichung, klein] Auftragstext nach dem Absturz.** Der Plan nennt `JOB_INTERRUPTED`. Für kind restore setzt `recover_jobs` aber `RESTORE_JOB_INTERRUPTED` ("Das Wiederherstellen wurde durch einen Neustart des Servers unterbrochen."). Der Test prüft diesen richtigen Text als Literal.

**4. [Ergänzung] `forged_backup` nimmt `map_bytes`.** Die Negativfälle nutzen die echte map.sqlite der Welt aus der ersten Sicherung, damit der Lua-Fall nach dem Restore wirklich startet. `minimal_map()` bleibt als Vorgabe.

## Deferred Issues

- **Volle Suite `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q tests` nicht zu Ende gelaufen.** Claude Code hat den Hintergrundlauf wegen Speichermangel abgebrochen (etwa 1,9 GB frei). Bis zum Abbruch kam kein Fehler. Gemäß Hinweis wurde er nicht neu gestartet. Die zwei verwaisten Test-Container dieses Laufs (Instanz bc480696, Ports im Testbereich) habe ich samt Volumes entfernt. Offen: die volle Suite bei genug freiem RAM einmal laufen lassen. Die neuen Tests ändern keinen Produktcode, und alle Gates sind grün.

## Known Stubs

Keine. `LocalFolderFiles` ist bewusst eine Testattrappe, den echten Files-Weg belegt Plan 09.

## Self-Check: PASSED

- Alle drei Dateien vorhanden, die Commits 1959f77, 97624c4 und 38a6cb3 stehen im Log, keine Dateilöschungen.
