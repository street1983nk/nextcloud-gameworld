---
phase: 05-backup-und-restore
plan: 01
subsystem: backup
tags: [backup, tarfile, sha256, docker-archive, path-safety]
requires:
  - phase: 04-spielzeitlimits
    provides: Mod-Konstanten (access_mod, time_mod, status_mod), read_time_ledger, Zählbuch-Format
  - phase: 01-fundament
    provides: provisioner/archive.py (_safe_relative, TarInfo-Muster), DockerProvisioner._guarded/_owned
provides:
  - Paket src/gameworld/backup mit archive.py (IterStream, HashingWriter, SnapshotInfo, RestoreInfo, build_manifest, world_relative, write_snapshot, verify_snapshot, prepare_restore, ledger_tar, sha256_of, BackupError, RestoreRejected, MSG_*, Ausschluss- und Verwurflisten)
  - backup/naming.py (BACKUPS_ROOT, folder_name, folder_path, backup_file_name, with_suffix)
  - DockerProvisioner.snapshot_to(world_id, write) und put_world_archive(world_id, archive)
  - provisioner/archive.safe_relative (öffentlich, _safe_relative bleibt Alias), status_mod.PLAYERS_FILE_NAME
affects: [05-02, 05-03, 05-04, 05-05, 05-06]
tech-stack:
  added: []
  patterns:
    - "Docker-Tar-Strom über IterStream + BufferedReader im Modus r| lesen, gefiltert als w:gz in eine Senke schreiben, Größe und SHA-256 beim Schreiben"
    - "Restore-Prüfung und Restore-Tar in einem Durchlauf; unsichere Einträge brechen ab, Code und Laufzeitdateien werden still verworfen"
    - "Snapshot-Lesen und Iterieren in einem einzigen _guarded-Block, nie über _read"
key-files:
  created:
    - src/gameworld/backup/__init__.py
    - src/gameworld/backup/archive.py
    - src/gameworld/backup/naming.py
    - tests/test_backup_archive.py
    - tests/test_backup_naming.py
  modified:
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/status_mod.py
    - src/gameworld/provisioner/client.py
    - tests/test_provisioner_errors.py
key-decisions:
  - "Restore-Tar ist gzip mit Namen relativ zum Weltordner (ohne world/), Ziel put_archive nach WORLD_PATH"
  - "Verhältnisgrenze MAX_RATIO 50 greift erst ab RATIO_FLOOR 256 MiB entpackt, damit kleine, stark packbare Welten (leere SQLite-Seiten) nicht abgelehnt werden"
  - "snapshot_to erlaubt nur die Zustände created, exited und dead (SNAPSHOT_SAFE_STATES); auch paused und restarting gelten als laufend"
  - "write_snapshot liest den Docker-Strom nach der Tar-Endmarke ganz aus und meldet abgerissene Tar-Ströme als BackupError(MSG_BROKEN_STREAM)"
  - "backup_file_name hat ein Keyword zone für die Haushalts-Zeitzone, lehnt naive Zeitpunkte und unbekannte Arten ab; unbrauchbarer Weltname ergibt Dateibasis Welt"
  - "Manifest: fehlend, kaputt oder falsches format ergibt MSG_NO_MANIFEST; fremde world_id oder fremdes preset ergibt MSG_FOREIGN_WORLD"
requirements-completed: []  # BACKUP-01/02 nur Kern-Beitrag; Abhaken erst mit dem End-to-End-Ablauf
metrics:
  duration: 40 min
  completed: 2026-10-23
  tasks: 2
  files: 9
---

# Phase 5 Plan 01: Archiv-Kern und Docker-Zugänge Summary

Reiner Archiv-Kern für Sicherung und Wiederherstellung: Ein Docker-Tar-Strom wird gestreamt in ein gefiltertes tar.gz mit Manifest übersetzt (Größe und SHA-256 beim Schreiben), eine Sicherung aus Nextcloud Files wird in einem Durchlauf geprüft und als Restore-Tar relativ zum Weltordner aufbereitet; manipulierte Sicherungen werden abgelehnt. Dazu sichere Ordner- und Dateinamen nach D-01/D-02 und zwei Provisioner-Methoden, die Snapshots nur von gestoppten Welten lesen.

## Ergebnis

- **write_snapshot (Task 1):** liest den Docker-Strom (Präfix `world/`) über `IterStream` im Modus `r|`, schreibt `w:gz` (compresslevel 6, PAX) mit `gameworld-backup.json` an der Wurzel. Ausgeschlossen: alle sechs Mod-Laufzeitdateien (nur aus Konstanten, kein String-Duplikat) und `worldmods/`; Journale bleiben drin (Pitfall 1). Symlinks, Hardlinks, Geräte und unsichere Namen werden übersprungen und in `SnapshotInfo.skipped` gezählt. Einträge normiert (uid/gid 30000, uname/gname leer, 0644/0755). Ohne reguläre `world/map.sqlite` nach vollständigem Lesen: `BackupError(MSG_NO_MAP)`. ENOSPC: `MSG_NO_SPACE`.
- **prepare_restore / verify_snapshot:** `r:gz`-Durchlauf mit Grenzen (8 GiB, 200 000 Einträge, Verhältnis 50 ab 256 MiB), Typprüfung vor allem anderen (Links und Geräte brechen auch in verworfenen Ordnern ab), Pfadprüfung über `safe_relative`, Manifest-Prüfung (format, world_id, preset). Verworfen: `world.mt`, `worldmods/`, `mods/`, `game/`, `*.lua`, jeder Pfadteil mit `gameworld_`. Tar- und gzip-Fehler werden `RestoreRejected(MSG_BAD_ENTRY)`. `verify_snapshot` ist der Probelauf in eine verwerfende Senke und setzt die Position vorher und nachher auf 0. Ins Log nur Zählwerte, feste Texte und Fehlertypen, nie Eintragsnamen (Test mit GEHEIMNAME).
- **ledger_tar, sha256_of:** Mini-Tar mit genau `gameworld_time_used.txt` (0644, 30000) für D-06; blockweiser SHA-256 mit Rücksprung auf 0.
- **naming.py (Task 2):** `folder_name` entfernt Rand-Punkte und -Leerzeichen, ersetzt Zeichen außer `[\w .-]` durch `-`, ergibt für leer, `.`, `..`, reine Bindestriche und CON/PRN/AUX/NUL/COM1-9/LPT1-9 (auch mit Endung) `Welt-<id6>`. `backup_file_name` nach D-02, Zusatz `-vor-restore` (D-05), Umrechnung in die übergebene Zone. `with_suffix` hängt `-2`, `-3` vor `.tar.gz` an.
- **snapshot_to / put_world_archive:** ein `_guarded`-Block mit `_owned`, `reload`, Zustandsprüfung, `get_archive(WORLD_PATH, chunk_size=2 MiB)` und `write(stream)`; Strom im `finally` geschlossen. Laufende Welt: ProvisionerError, get_archive nie aufgerufen; Abbruch mitten im Strom: DockerUnavailableError, get_archive genau einmal. `put_world_archive` spielt ein Datei-Objekt nach `WORLD_PATH` ein, `False` ergibt "Docker hat die Sicherung nicht angenommen."

## Commits

| Task | Gate | Commit | Inhalt |
|------|------|--------|--------|
| 1 | RED | aa182cd | test(05-01): failing tests für den Archiv-Kern |
| 1 | GREEN | c3aaf5b | feat(05-01): Archiv-Kern mit Restore-Validierung |
| 2 | RED | be30776 | test(05-01): failing tests für naming und snapshot_to |
| 2 | GREEN | adcc350 | feat(05-01): naming, snapshot_to, put_world_archive |

## Verifikation

- `uv run pytest -q tests/test_backup_archive.py tests/test_archive.py tests/test_backup_naming.py tests/test_provisioner_errors.py`: 165 passed; Gesamtsuite ohne e2e: 1974 passed.
- test_backup_archive.py enthält über 30 Negativfälle (14 unsichere Einträge parametrisiert, fehlende map.sqlite, Manifest fehlt/kaputt/fremde Welt/fremdes Preset, drei Grenzen, kaputtes und abgeschnittenes gzip, ENOSPC).
- `grep -v '^\s*#' src/gameworld/backup/archive.py | grep -c '"gameworld_access.txt"'` ergibt 0.
- ruff check, ruff format --check, pyright (latest, 0 errors) und vulture ohne Befund.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docker-Strom nach der Tar-Endmarke ganz lesen**
- **Found during:** Task 1 (GREEN)
- **Issue:** tarfile im Modus `r|` hört an der Endmarke auf; der Rest des Docker-Stroms (Auffüllung) blieb ungelesen, ein Abbruch am Ende wäre unbemerkt geblieben und die Plan-Vorgabe "nachdem der Strom ganz gelesen wurde" nicht erfüllt.
- **Fix:** nach der Schleife den gepufferten Strom bis zum Ende lesen.
- **Commit:** c3aaf5b

**2. [Rule 2 - Kritisch] Untergrenze für die Verhältnisprüfung (RATIO_FLOOR)**
- **Found during:** Task 1
- **Issue:** Leere SQLite-Seiten packen weit über 50:1; eine reine Verhältnisgrenze hätte kleine echte Welten abgelehnt.
- **Fix:** MAX_RATIO greift erst ab 256 MiB entpackt; Test für eine stark packbare kleine Welt (angenommen) und für eine Bombe mit RATIO_FLOOR 0 (abgelehnt).
- **Commit:** c3aaf5b

**3. [Rule 2 - Kritisch] Abgerissener Tar-Strom beim Snapshot als fester Fehler**
- **Found during:** Task 1
- **Issue:** Ein mitten in einem Eintrag abgerissener Strom ergab rohe `tarfile.ReadError`.
- **Fix:** `tarfile.TarError`/`EOFError` in `write_snapshot` werden `BackupError(MSG_BROKEN_STREAM)`; Transportfehler bleiben unverändert für `_guarded`.
- **Commit:** c3aaf5b

**4. [Rule 2 - Kritisch] Auch paused und restarting gelten als laufend**
- **Found during:** Task 2
- **Issue:** Der Plan prüfte nur `status == "running"`; ein eingefrorener oder neu startender Server hat ebenfalls eine inkonsistente map.sqlite.
- **Fix:** Positivliste `SNAPSHOT_SAFE_STATES = {"created", "exited", "dead"}`, parametrisierter Test für running, restarting, paused.
- **Commit:** adcc350

**5. [Rule 2 - Kritisch] backup_file_name mit Zone, Prüfung von Zeitzone und Art**
- **Found during:** Task 2
- **Issue:** Die Behavior-Vorgabe "UTC 12:05 ergibt 1405 in Europe/Berlin" braucht eine Zielzone; ein naiver Zeitpunkt hätte still die Serverzone benutzt.
- **Fix:** Keyword `zone`, ValueError für naive Zeitpunkte und unbekannte Arten.
- **Commit:** adcc350

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche über das Threat Register hinaus; T-05-01 bis T-05-06 und T-05-49 sind auf Codeebene umgesetzt und getestet.

## Self-Check: PASSED

- Dateien vorhanden: src/gameworld/backup/__init__.py, archive.py, naming.py, tests/test_backup_archive.py, tests/test_backup_naming.py
- Commits vorhanden: aa182cd, c3aaf5b, be30776, adcc350
