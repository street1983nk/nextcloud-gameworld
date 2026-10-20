---
phase: 03-zugang-und-rollen
plan: 05
subsystem: ui
tags: [vue, invites-ui, NcSelectUsers, autocomplete, world-key, access-state]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-03/03-04 Invites-API, PlayerChangeOut, Gruppen; 03-01 State-Datei des Zugangs-Mods; 03-02 ParentView/PlayerView
provides:
  - WorldOut.invited_players (sortierte Spielernamen, keine Passwörter) und WorldOut.access_restart_needed
  - DockerProvisioner.read_access_state über gemeinsamen gekappten Leser _read_world_file
  - POST /api/worlds liefert WorldOut ohne world_key (CreatedWorld/CreatedWorldOut entfallen)
  - InviteDialog.vue (NcSelectUsers über core/autocomplete/get, Benutzer und Gruppen)
  - PlayerManager.vue (Spielername, verdecktes Passwort, Herkunft, Passwort neu, Umbenennen, Einladungen entfernen)
  - api.js errorText, listPlayers, invite, removeInvite, rotatePassword, renamePlayer, searchAccounts
affects: [03-06, 03-07]
tech-stack:
  added: []
  patterns:
    - "Zugangsschutz-Status wie Bereitschaft: State-Datei-mtime >= StartedAt, nur bei status running gelesen, Lesefehler pro Welt isoliert"
    - "Dialoge bekommen nur { id, name } der Welt, damit das 5-s-Polling sie nicht neu aufbaut"
    - "Passwort im Frontend nur im Speicher des offenen Dialogs, verdeckt bis Anzeigen; NcFormBoxCopyButton erst nach Anzeigen, weil er den Wert immer sichtbar rendert"
key-files:
  created:
    - frontend/src/components/InviteDialog.vue
    - frontend/src/components/PlayerManager.vue
  modified:
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - tests/test_service_lifecycle.py
    - tests/test_provisioner_errors.py
    - tests/e2e/test_create_world_e2e.py
    - tests/e2e/test_access_e2e.py
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
key-decisions:
  - "access_restart_needed: True nur bei status running und fehlender oder älterer State-Datei; ohne lesbaren StartedAt zählt die bloße Existenz der Datei (False)"
  - "NcFormBoxCopyButton zeigt seinen Wert immer als Beschreibung; das Passwort nutzt ihn deshalb erst nach Anzeigen, verdeckt gibt es einen eigenen Kopierknopf über navigator.clipboard"
  - "OCS-Suche mit Header OCS-APIRequest und format json; nur Einträge mit source users oder groups werden Optionen"
  - "Bei unbekannter Spielart (Status error) ist access_restart_needed immer False, gleiche Regel wie players"
requirements-completed: []
metrics:
  duration: 35 min
  completed: 2026-10-20
  tasks: 2
  files: 11
---

# Phase 3 Plan 05: Eltern-UI für Einladungen und Spieler Summary

Eltern laden jetzt im Dashboard Nextcloud-Benutzer und -Gruppen über Nextclouds eigene Suche ein und verwalten pro Welt Spielernamen, Passwörter und Einladungen. Der Weltschlüssel verlässt die API nicht mehr, und läuft eine Welt noch ohne geladenen Zugangsschutz, steht in ihrer Zeile "Neustart nötig, damit nur Eingeladene spielen können."

## Ergebnis

- **Backend (Task 1)**:
  - `client.py`: `_read_world_file(world_id, path, label)` aus dem Status-Leser herausgelöst (gleiche Kappung 64 KiB/4096 Bytes, gleiche Fehlerabbildung, Meldung je Datei); `read_access_state` liest `access_mod.STATE_FILE`.
  - `service.py`: `WorldView.invited_players` (aus `sorted(store.access_entries(row.id))`, auch bei Docker unknown) und `access_restart_needed` (nur bei `RUNNING`, Vergleich per `parse_docker_time` wie `_ready`). `_copy` kopiert beide Listen. `CreatedWorld` entfällt, `create_world` gibt `WorldView` zurück.
  - `api/worlds.py`: `WorldOut` um beide Felder ergänzt, `CreatedWorldOut` entfernt, POST `/api/worlds` liefert `WorldOut`.
  - Tests: FakeProvisioner mit `access_states`, `access_state_error`, `access_state_reads`; 9 neue Service-/API-Tests (frisch, fehlend, veraltet, nur bei running gelesen, Fehler isoliert, Namen sortiert ohne Verifier, Docker weg, Cache-Kopie, API ohne world_key) und 3 Provisioner-Tests.
  - e2e: `test_create_world_e2e.py` liest den Schlüssel aus `WorldStore(app_env/gameworld.sqlite3)`, prüft seine Abwesenheit in der POST-Antwort und wartet auf `running` mit `access_restart_needed` false. `test_access_e2e.py` (A9-Prüfung) liest den Schlüssel ebenfalls aus dem Store.
- **Frontend (Task 2)**:
  - `api.js`: Funktionen laut Plan; `searchAccounts` ruft `generateOcsUrl('core/autocomplete/get')` mit `shareTypes [0, 1]`, `limit 20` und mappt auf `{kind, id, label}`. `errorText` zentral (ParentView nutzt es jetzt auch).
  - `InviteDialog.vue`: NcDialog "Spieler einladen: <Welt>", NcSelectUsers mehrfach, Entprellung 300 ms, nur die letzte Suche zählt, Gruppen mit `isNoUser` und SVG-Gruppensymbol. "Einladen" lädt nacheinander ein, Fehler je Eintrag als NcNoteCard mit detail, bei `applied: false` "Die Änderung wirkt beim nächsten Start der Welt.", Event `done`.
  - `PlayerManager.vue`: NcDialog "Spieler von <Welt>"; je Spieler Anzeigename, Herkunft ("direkt eingeladen" / "über Gruppe <gid>"), Spielername per NcFormBoxCopyButton, Passwort verdeckt mit Anzeigen/Verbergen und Kopieren; "Neues Passwort" mit Bestätigung, "Name ändern" mit Inventar-Warnung; Einladungsliste mit "Entfernen"; leer "Noch niemand eingeladen."
  - `ParentView.vue`: Weltschlüssel-Karte und `createdKey` entfernt, danach "Welt erstellt. Lade jetzt Spieler ein." mit Knopf; neuer Hinweistext; Spalte "Spieler"; Knöpfe "Einladen" und "Spieler" (nicht bei delete_only); Warnkarte bei `access_restart_needed`.
- **Live gegen die Dev-Nextcloud** (Backend per `register-exapp.sh` mit neuem Code neu gestartet):
  - OCS-Autovervollständigung als admin: `gw-kind` mit `source: users`.
  - Welt über den AppAPI-Proxy erzeugt: Antwort ohne `world_key`, mit `invited_players: []`, `access_restart_needed: false`.
  - gw-kind eingeladen (applied true), Liste: `invited_players ["Kind"]`, `running`, `access_restart_needed false`.
  - State-Datei im Container gelöscht: `access_restart_needed true`. Welt gelöscht (204), 0 Welt-Container, Heartbeat 200.
- **Gates**: `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q` 552 passed; ruff, ruff format, pyright (latest), vulture grün; `npm run build` grün; Privacy-Test 8 passed; alle grep-Kriterien beider Tasks erfüllt (kein world_key in api/ und frontend/src, kein v-html, keine Gedankenstriche).

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 8ba928e | Spielernamen und Zugangsschutz-Status in der Weltenliste, Weltschlüssel aus der API entfernt |
| 2 | 92c471b | Einladen-Dialog und Spielerverwaltung im Eltern-Dashboard |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Zweiter e2e-Test nutzte created["world_key"]**
- **Found during:** Task 1
- **Issue:** `tests/e2e/test_access_e2e.py:127` (A9: Weltschlüssel öffnet kein provisioniertes Konto) las den Schlüssel aus der POST-Antwort; der Plan nannte nur `test_create_world_e2e.py`.
- **Fix:** Schlüssel aus `WorldStore(app_env/gameworld.sqlite3)` gelesen.
- **Commit:** 8ba928e

**2. [Rule 2 - Sicherheit] Passwort nicht über NcFormBoxCopyButton im verdeckten Zustand**
- **Found during:** Task 2
- **Issue:** NcFormBoxCopyButton rendert seinen `value` immer sichtbar als Beschreibung (im Quelltext von @nextcloud/vue 9.13.1 geprüft). Mit dem Passwort als Wert wäre es nie verdeckt (T-03-34).
- **Fix:** Verdeckt: Maske plus eigener Kopierknopf (navigator.clipboard); NcFormBoxCopyButton für das Passwort erst nach "Anzeigen".
- **Commit:** 92c471b

**3. [Hinweis] Provisioner-Tests ergänzt**
- `tests/test_provisioner_errors.py` stand nicht in `files_modified`; drei Tests für `read_access_state` (Pfad, fehlend, kaputt als ProvisionerError).

**4. [Hinweis] errorText nach api.js verschoben**
- Drei Komponenten brauchen dieselbe Fehlerabbildung; ParentView importiert sie jetzt statt einer eigenen Kopie.

## TDD Gate Compliance

- Task 1 ist `tdd="true"`, Implementierung und Tests landeten im selben Commit 8ba928e; ein eigener RED-Commit fehlt (wie 03-03/03-04). Jede Behavior-Zeile hat einen Test, alle grün.

## Known Limitations

- Direkt nach einem Start kann `access_restart_needed` für die Dauer bis zum ersten Mod-Takt kurz true sein, falls die Status-Datei vor der State-Datei geschrieben wird; im Live-Test und e2e trat das nicht auf.
- Die Oberfläche ist per Build, grep-Kriterien und API-Livetest geprüft, nicht per Browser; die gemeinsame Playwright-Abnahme folgt in 03-07.
- Die Hinweiskarte "Welt erstellt" bleibt stehen, bis die nächste Welt erstellt wird, auch wenn die Welt inzwischen gelöscht ist.

## Self-Check: PASSED

- Dateien vorhanden: InviteDialog.vue, PlayerManager.vue und alle geänderten Dateien
- Commits vorhanden: 8ba928e, 92c471b
- Keine Welt-Container übrig (0), Dev-Backend Heartbeat 200
