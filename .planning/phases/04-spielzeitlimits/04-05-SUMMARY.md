---
phase: 04-spielzeitlimits
plan: 05
subsystem: playtime
tags: [world-window, school, verwalter, frei, api, e2e]
requires:
  - phase: 04-spielzeitlimits
    provides: plan.evaluate_world, TimeEngine.render (Welt-Zeile), TimeService, push_time, Store world_windows/delete_time_data, Mod-Semantik "welt"/"frei" aus 04-01
provides:
  - POST/DELETE /api/playtime/worlds/{world_id}/window (genau 7 Tage, open, Fenster in Minuten)
  - TimeService.refresh_admins (meta time_admins aus Gruppe admin, gedrosselt 60 s, außerhalb der Sperre)
  - TimeService.set_world_window/clear_world_window
  - TimeEngine: frei-Zeilen für eingeladene Verwalter, parse_admins, META_TIME_ADMINS
  - WorldView/WorldOut.time_window (7 Tage oder null), plan.WindowDay/window_days/check_world_window
  - WorldStore.replace_world_window (atomar)
  - Welt löschen (auch RETRY_DELETE) entfernt world_windows und time_ledger_seen
affects: [04-06, 04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "Verwalter-Schnappschuss: Gruppenabfrage vor der Sperre, Vergleich mit meta außerhalb, Schreiben plus Neu-Rendern aller Welten nur bei Änderung unter mutation() bzw. try_mutation() im Dashboard"
    - "FakeDirectory.lock_held belegt die Sperrregel (keine Nextcloud-Abfrage unter _LOCK)"
key-files:
  created:
    - tests/e2e/test_world_window_e2e.py
  modified:
    - src/gameworld/api/playtime.py
    - src/gameworld/api/worlds.py
    - src/gameworld/playtime/engine.py
    - src/gameworld/playtime/plan.py
    - src/gameworld/playtime/service.py
    - src/gameworld/worlds/service.py
    - src/gameworld/worlds/store.py
    - tests/conftest.py
    - tests/test_playtime_api.py
    - tests/test_playtime_engine.py
    - tests/test_service_lifecycle.py
key-decisions:
  - "Alle sieben Tage geschlossen ergibt 422 ('Eine Welt mit Zeitfenster braucht mindestens einen offenen Tag.'): keine Fensterzeilen heißt im Schema immer offen; 'immer offen' ist DELETE"
  - "Ein geschlossener Tag mit Fensterangaben ist 422 (eindeutige Eingabe)"
  - "refresh_admins: GET-Pfade gedrosselt, Änderungen (Kinder-Regeln, Fenster) mit force; Nextcloud-Störung behält den letzten Stand und setzt die Drossel zurück"
  - "frei gewinnt vor alten Kinder-Regeln eines Verwalters; kaputter oder fehlender Schnappschuss = keine Freistellung (fail closed)"
  - "clear_child für ein Verwalter-Konto bleibt erlaubt (Aufräumen alter Regeln); die Einzelsicht zeigt Verwalter, die Liste nicht"
requirements-completed: [ZEIT-05, ZEIT-02]
metrics:
  duration: 75 min
  completed: 2026-10-20
  tasks: 2
  files: 12
---

# Phase 4 Plan 05: Zeitfenster pro Welt mit Verwalter-Freistellung Summary

Welt-Zeitfenster per Verwalter-API (Wochenplan ohne Limit, Zeile "welt" in der Regeldatei), Verwalter-Schnappschuss `time_admins` aus der Gruppe admin mit Zeile `frei` für eingeladene Verwalter; live belegt: Kind außerhalb abgewiesen und am Fensterende mit Vorwarnung getrennt, Verwalter bleibt drin, die Welt läuft weiter.

## Ergebnis

- **API (Task 1):** `WindowDayIn` (extra forbid, weekday 1..7, open, window_start/end), `WorldWindowIn` (genau 7 eindeutige Tage), Prüfung über `check_world_window` (dieselbe Regel wie DayRule). POST ersetzt das Fenster atomar (`replace_world_window`), DELETE entfernt es; beide schreiben die Regeldatei unter `mutation()` per `push_time`. Antwort `{world_id, time_window, applied}`. 404 bei unbekannter Welt, 422 bei ungültigen Eingaben, gw-kind 403.
- **Schnappschuss:** `refresh_admins(acting_uid, force, blocking)` fragt die Gruppe admin vor der Sperre ab, nimmt den handelnden Verwalter immer auf, vergleicht mit meta außerhalb der Sperre und schreibt nur bei Änderung (dann `_refresh_all_worlds`). Aufrufe: GET /api/playtime (gedrosselt), set_child/clear_child/Fenster-Routen (force), GET /api/worlds (gedrosselt, `try_mutation`, Fehler nur als Warnung).
- **Engine:** eingeladene Konten aus `time_admins` bekommen `-1 -1 -1 frei -`, auch ohne Welt-Fenster; Welt-Zeile über `evaluate_world` (Mi 09:00 -> `welt <Mi 10:00> <Mi 12:00> welt Mi-10:00`, Do -> `welt 0 0 welt Mi-10:00`).
- **Kinderliste:** Verwalter erscheinen nicht; POST children für einen Verwalter ergibt 422 "Verwalter haben keine Spielzeitregeln.".
- **Weltenliste:** `time_window` je Welt; Löschen räumt Fenster und gesehene Zählbuchstände (auch im Reconciler-Pfad RETRY_DELETE in worlds/service.py, reconciler.py unverändert).
- **Live (Task 2):** `tests/e2e/test_world_window_e2e.py` (1 Test, 219 s): (1) heute zu, morgen 10 bis 12 -> gw-kind denied "Diese Welt ist gerade geschlossen. Sie öffnet <Token> 10:00", admin auth_accept und 10 s held, "Fremder" denied "nicht eingeladen" ohne Fenstertext; (2) Fenster heute bis jetzt plus 3 min -> gw-kind kicked vor 200 s mit Welt-Text, Chat "Noch 1 Minute." vor dem Kick, admin hält parallel über das Fensterende; (3) Container running, StartedAt unverändert, desired_state "running"; (4) DELETE -> auth_accept ohne Neustart; (5) Positivkontrolle Zeilen vorhanden, nach dem Löschen keine Zeilen in world_windows und time_ledger_seen.

### Nachweise

- Nicht-Docker: 799 passed. Gesamtsuite `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 826 passed in 18:10 min. Danach kein Container mit `gameworld.managed=true`.
- Gates grün: ruff check, ruff format --check, pyright (0 errors), vulture (leer).
- `grep -rn "stop_world\|desired_state" src/gameworld/playtime`: leer. `git log --format=%s -- src/gameworld/worlds/reconciler.py | grep -c "(04-"` = 0.
- Live-Dev-Stack: altes Backend (PID 4416 auf Port 10040, Kommandozeile `gameworld.main` geprüft) gezielt gestoppt, `sh scripts/dev/register-exapp.sh`: "ExApp gameworld successfully registered". Proxy: GET /api/worlds 200, POST window mit `{"days":[]}` 422, DELETE window auf unbekannte Welt 404, GET /api/playtime 200. ExApp-Log ohne ERROR/Traceback.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | ab12761 | Welt-Fenster-API, Verwalter-Schnappschuss, frei-Zeilen, time_window, Löschen räumt auf, Tests |
| 2 | 3894ec1 | Live-Nachweis Welt-Fenster, Freistellung, Weiterlaufen der Welt |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - blockierend] WorldStore.replace_world_window ergänzt**
- **Found during:** Task 1
- **Issue:** Der Store hatte nur `set_world_window` je Wochentag (Interface-Angabe im Plan war ein dict); ein neues Fenster muss geschlossene Tage entfernen, atomar.
- **Fix:** `replace_world_window(world_id, windows)` in einer Transaktion; `store.py` stand nicht in der Dateiliste.
- **Commit:** ab12761

**2. [Rule 2 - Korrektheit] Alle Tage geschlossen ist 422**
- **Issue:** Keine Fensterzeilen bedeuten im Schema "immer offen"; ein Fenster mit sieben geschlossenen Tagen hätte die Welt still geöffnet.
- **Fix:** 422 mit "Eine Welt mit Zeitfenster braucht mindestens einen offenen Tag."; immer offen = DELETE.
- **Commit:** ab12761

**3. [Rule 2 - Korrektheit] RETRY_DELETE räumt Zeitdaten mit auf**
- **Fix:** `_apply` in worlds/service.py ruft nach `delete_access_data` auch `delete_time_data` (reconciler.py unverändert).
- **Commit:** ab12761

### Hinweise

- **TDD:** Implementierung und Tests entstanden in einem Arbeitsgang und wurden wie in 04-01 bis 04-04 in einem Task-Commit festgehalten; ein separater RED-Lauf ist nicht belegt.
- conftest setzt zusätzlich `ADMINS_STATE` je Test zurück (wie `SYNC_STATE`).

## Known Limitations

- Knopf "Zeitfenster" in der Welt-Zeile folgt in 04-06.
- T-04-28 (entfernter Verwalter behält "frei" bis zum nächsten Verwalter-Aufruf, höchstens 60 s Drossel) bleibt bewusst akzeptiert; Doku in 04-08.

## Known Stubs

Keine.

## Threat Flags

Keine neue Fläche außerhalb des Threat-Modells. Umgesetzt und belegt: T-04-27 (frei nur aus time_admins, Unit-Test Kind ohne frei, kaputter Schnappschuss ohne frei), T-04-29 (letzter Stand bleibt, Weltenliste 200 auch bei Fehler), T-04-30 (e2e Fremder), T-04-31 (grep, Reconciler unverändert, e2e Teil 3), T-04-32 (extra forbid, 7 eindeutige Tage, Bereiche, 422).

## Self-Check: PASSED

- Dateien vorhanden: tests/e2e/test_world_window_e2e.py, src/gameworld/api/playtime.py, src/gameworld/playtime/service.py
- Commits vorhanden: ab12761, 3894ec1
