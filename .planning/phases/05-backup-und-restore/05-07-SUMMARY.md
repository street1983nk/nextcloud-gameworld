---
phase: 05-backup-und-restore
plan: 07
subsystem: frontend
tags: [frontend, parent-view, backup-list, confirm-dialogs]
requires:
  - "05-05: POST/GET /api/worlds/{id}/backups, WorldOut.backup_job, Busy-Status backing_up/restoring"
  - "05-06: POST /api/worlds/{id}/restore {file_id, confirm, confirm_disconnect}"
provides:
  - "BackupSection.vue: Sicherungsliste, Gesamtgröße, Jetzt sichern, Wiederherstellen mit Bestätigung"
  - "backup.js: formatBytes, playersWarning, restoreQuestion, jobNote, formatDate, jobFinished"
  - "api.js: listBackups, startBackup, restoreBackup"
affects:
  - frontend/src/views/ParentView.vue
tech-stack:
  added: []
  patterns:
    - "Dialog bekommt nur die Welt-ID; Daten und backup_job reaktiv per computed aus der gepollten Weltenliste"
    - "Bestätigung ersetzt den Bereich (v-if/v-else NcDialog) statt verschachtelter Dialoge"
key-files:
  created:
    - frontend/src/backup.js
    - frontend/tests/backup.check.mjs
    - frontend/src/components/BackupSection.vue
  modified:
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
decisions:
  - "Sicherungen-Knopf bleibt während eines Auftrags offen (nur Ansicht); alle anderen Aktionen der Welt (Starten/Stoppen/Neustarten, Einladen, Spieler, Zeitfenster, Löschen) sind gesperrt (D-10)"
  - "jobFinished liefert nur true, wenn next ok/failed ist; next null gilt nie als Ende"
  - "Spielerzahl für die Warnung kommt live aus dem Polling; kommt ein Kind nach dem Öffnen dazu, zeigt die 409-Antwort des Backends den Text, beim nächsten Klick erscheint die Bestätigung"
metrics:
  duration: "ca. 20 min"
  completed: 2026-10-23
  tasks: 2
  files: 5
---

# Phase 5 Plan 07: Sicherungs-Oberfläche in der Verwaltungsansicht Summary

Sicherungsbereich je Welt (Liste mit Datum/Größe, Gesamtgröße, Jetzt sichern, Wiederherstellen mit Sicherheitsabfrage und Kinder-Warnung), Busy-Chips und Sperren aller Weltaktionen während eines Auftrags, Fehlerkarte aus backup_job, Listen-Neuladen bei Auftragsende über das vorhandene 5-s-Polling.

## Tasks

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | backup.js mit Prüfskript, API-Funktionen, formatBytes verschoben | d67900a |
| 2 | BackupSection.vue und Einbindung in ParentView.vue | 310bef2 |

## Umsetzung

- `backup.js`: reine Hilfen; Texte für Kinder-Warnung identisch mit Backend (`PLAYERS_ONLINE_*`); `jobNote` je kind (backup/restore) für failed/running; `formatDate` in Browser-Ortszeit TT.MM.JJJJ HH:MM.
- `backup.check.mjs`: deckt 1/3 Kinder, failed/running/ok beider kinds, Bytes-Grenzen um 1 GiB, formatDate und zehn jobFinished-Übergänge ab.
- `BackupSection.vue`: lädt beim Öffnen, `watch` auf `{state, finished_at}` des Props `backupJob` lädt bei `jobFinished` neu; Kennzeichnung vor-restore als Chip; Hinweis auf weitere Dateien ohne Knopf (D-12); kein Löschknopf, kein v-html; Knöpfe gesperrt bei saving, laufendem Auftrag oder Busy-Status (T-05-38).
- `ParentView.vue`: `CHIP_VARIANT` um backing_up/restoring, `backupBusy`, `isActive` zeigt bei Busy keinen Starten-Knopf, Sicherungen-Einstieg auch bei delete_only (D-15), Statusspalte mit Fehlerkarte (failed) bzw. neutraler Zeile (running). Polling unverändert.

## Verifikation

- `node frontend/tests/backup.check.mjs` und `playtime.check.mjs`: grün
- `npm run build`: grün (Bundle nach js/, gitignored wie bisher)
- `tests/test_frontend_privacy.py`: 8 passed
- `uv run pytest -q -m "not docker"`: 2236 passed, 35 deselected
- Akzeptanz-Greps (CHIP-Varianten, BackupSection, kein v-html, kein Löschen, jobFinished, backupJob): alle erfüllt

## Deviations from Plan

None - plan executed exactly as written. Kleine Auslegungen siehe decisions (Sicherungen-Knopf bleibt während Auftrag öffnbar; Bestätigung als ersetzender statt verschachtelter Dialog).

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus (T-05-36/37/38/52 umgesetzt).

## Self-Check: PASSED
