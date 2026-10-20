---
phase: 04-spielzeitlimits
plan: 07
subsystem: kind-ansicht
tags: [kind-ansicht, api-my, restzeit, vue, privacy]
requires:
  - phase: 04-spielzeitlimits
    provides: TimeEngine.child_state und evaluate_world (04-02/04-03), Welt-Fenster (04-05), playtime.js (04-06)
provides:
  - GET /api/my/playtime {limited, state, remaining_minutes, until_minute, next {weekday, minute, days_ahead}}
  - /api/my/worlds je Welt window_open und window_next {weekday, start, end}
  - TimeService.my_playtime / my_world_windows, reine Umrechnung kid_playtime, world_window_status, parse_hint
  - PlaytimeCard "Deine Spielzeit heute", Fenster-Chip in ConnectionCard, kidPlaytimeText/windowText in playtime.js
affects: [04-08]
tech-stack:
  added: []
  patterns:
    - "Kind-API liefert Struktur, der Browser formuliert (reine Funktionen, Node-geprüft)"
    - "Kind-Ansicht rechnet mit derselben TimeEngine (gleiche Uhr per TimeEngine.now()) wie die Regeldatei"
key-files:
  created:
    - tests/test_my_playtime.py
    - frontend/src/components/PlaytimeCard.vue
  modified:
    - src/gameworld/api/me.py
    - src/gameworld/playtime/service.py
    - src/gameworld/playtime/engine.py
    - tests/test_my_worlds.py
    - frontend/src/api.js
    - frontend/src/playtime.js
    - frontend/tests/playtime.check.mjs
    - frontend/src/components/ConnectionCard.vue
    - frontend/src/views/PlayerView.vue
key-decisions:
  - "Kind-API: next trägt zusätzlich days_ahead (0 = heute, 7 = gleicher Wochentag in einer Woche), weil der Browser die Haushalts-Zeitzone nicht kennt und 'heute' sonst bei 'nur mittwochs, heute aufgebraucht' falsch wäre"
  - "remaining_minutes nie über das Fensterende hinaus (min(Rest, Fensterende minus jetzt)); unter 60 s Rest state aufgebraucht, unter 60 s bis Fensterende state fenster (MIN_LEFT)"
  - "Verwalter (Selbstauskunft) und Konten im Verwalter-Schnappschuss time_admins bekommen limited false, wie die frei-Zeile im Mod"
  - "Lesefehler der Zeitregeln (sqlite3.Error, ValueError, KeyError) werden in beiden Kind-Routen 503 mit MSG_UNAVAILABLE"
  - "PlayerView holt Welten und Restzeit per Promise.allSettled im selben 5-s-Takt; eine Störung der einen verdeckt die andere nicht"
requirements-completed: [ZEIT-01, ZEIT-05]
metrics:
  duration: 25 min
  completed: 2026-10-20
  tasks: 2
  files: 11
---

# Phase 4 Plan 07: Kind-Ansicht mit Restzeit und Welt-Öffnungszeiten Summary

Kinder sehen in "Meine Welten" den Block "Deine Spielzeit heute" ("Noch 60 Minuten, bis 23 Uhr", "Gerade ist keine Spielzeit. Nächste Spielzeit: heute 15 Uhr") und je Welt einen Chip "Offen Mittwoch 10 bis 12 Uhr" bzw. "Gerade geschlossen. Offen ..."; die neue Route GET /api/my/playtime liefert dafür nur eigene Werte aus TimeEngine.child_state(uid), ohne Pläne, Verbrauch oder Daten anderer Kinder.

## Ergebnis

- **Backend:** `GET /api/my/playtime` (UID aus UserDep, Rolle aus der Selbstauskunft), `MyWorldOut` um `window_open` und `window_next` erweitert, bestehende Felder und AR-24-Text unverändert; `appinfo/info.xml` unverändert (`^/api/my/.*` ist schon USER).
- **playtime/service.py:** reine Funktionen `kid_playtime`, `world_window_status`, `parse_hint`; dünne Wrapper `my_playtime(uid, exempt=...)` und `my_world_windows(world_ids)` über `anyio.to_thread`; `PlaytimeUnavailableError` für 503.
- **engine.py:** öffentliche `now()`, damit die Anzeige mit derselben Uhr rechnet wie die Regeldatei (im Test fest).
- **Frontend:** `getMyPlaytime`, `PlaytimeCard.vue` (NcNoteCard info bei ok, warning bei aufgebraucht/fenster/tag, nichts bei limited false oder ohne Aussage), `kidPlaytimeText`, `kidPlaytimeBlocked`, `windowText`; internes `windowText(start, end)` aus 04-06 heißt jetzt `rangeText`.

### Nachweise

- RED belegt: `tests/test_my_playtime.py` und erweiterte `tests/test_my_worlds.py` 21 failed (Commit 7effbe8); Node-Prüfskript Exit 1, Export fehlte (Commit f00dd47).
- `uv run pytest -q -m "not docker"`: 818 passed (vor der days_ahead-Ergänzung), danach Kind-Tests 33 passed; ruff, ruff format, pyright (0 errors), vulture grün.
- `node frontend/tests/playtime.check.mjs`: alle Prüfungen bestanden; `npm run build` grün; `tests/test_frontend_privacy.py` 8 passed; Gedankenstrich-Suche in frontend/src leer; `git log --format=%s -- appinfo/info.xml | grep -c "(04-07)"` = 0.
- Datentrennung: Test legt Regeln für gw-freund an (Positivkontrolle 70 Minuten bis 20 Uhr), Antwort für gw-kind hat genau die fünf Schlüssel und weder Konto, Spielername, Werte des zweiten Kindes noch normal/holiday/used_today_s; UID-Parameter im Query wird ignoriert.
- Dev-Stack: altes Backend (PID 20200, Kommandozeile `python.exe -m gameworld.main` geprüft) gezielt gestoppt, `sh scripts/dev/register-exapp.sh`: "ExApp gameworld successfully registered".
- **Playwright-Selbstprüfung** (Skript `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\ui-check-04-07.cjs`, gw-kind mit gw-kind-dev-pass-1, Dienstag ca. 20:14 Uhr Berlin): ohne Regeln kein Block und kein Chip; "Jeden Tag 1 Stunde" (bis 19 Uhr) -> "Gerade ist keine Spielzeit. Nächste Spielzeit: Mittwoch 0 Uhr"; 60 min bis 23 Uhr -> "Noch 60 Minuten, bis 23 Uhr"; Welt-Fenster heute bis 23 Uhr -> Chip "Offen Dienstag bis 23 Uhr"; nur Mi 10 bis 12 -> "Gerade geschlossen. Offen Mittwoch 10 bis 12 Uhr"; nach dem Aufräumen Block und Chip weg, API wieder limited false. Konsolenfehler: 0. Testwelt gelöscht (204). Nachkontrolle SQLite: 0 Welten, 0 Pläne, 0 Welt-Fenster, 0 Ferien, 0 Verbrauch, time_zone Europe/Berlin; kein Container mit `gameworld.managed=true`.
- Screenshots:
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-1-ohne-regeln.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-2-jeden-tag-1-stunde.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-3-noch-minuten.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-4-welt-offen.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-5-welt-geschlossen.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-07-ui-6-nach-aufraeumen.png`

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 (RED) | 7effbe8 | Tests /api/my/playtime und Fensterstatus in /api/my/worlds |
| 1 | d5f77e4 | Route, Modelle, Service-Wrapper, reine Umrechnung |
| 1 (Ergänzung) | 5cce92f | next.days_ahead für "heute" in der Anzeige |
| 2 (RED) | f00dd47 | Node-Prüfungen kidPlaytimeText/windowText |
| 2 | 4e5ceb4 | PlaytimeCard, Fenster-Chip, Abruf im 5-s-Takt |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] "heute" ohne Haushalts-Zeitzone nicht sicher ableitbar**
- **Found during:** Task 2 (Textregel "heute, wenn der nächste Wochentag der aktuelle ist")
- **Issue:** Bei "nur mittwochs, heute aufgebraucht" ist der nächste Wochentag ebenfalls Mittwoch, aber in einer Woche; der Browser hätte "heute" gesagt. Außerdem kennt der Browser die Haushalts-Zeitzone nicht.
- **Fix:** `next.days_ahead` (0..7) im Backend aus dem Hinweis-Token und der Haushalts-Zeitzone; Anzeige "heute ...", "nächsten Mittwoch ...", sonst Wochentag.
- **Files modified:** src/gameworld/playtime/service.py, src/gameworld/api/me.py, tests/test_my_playtime.py
- **Commit:** 5cce92f

**2. [Rule 1 - Korrektheit] Restminuten über das Fensterende hinaus**
- **Issue:** Limit 120 min um 18:30 bei Fenster bis 19 Uhr hätte "Noch 120 Minuten, bis 19 Uhr" gezeigt.
- **Fix:** remaining_minutes = min(Rest, Fensterende minus jetzt) abgerundet; Test `test_remaining_never_exceeds_window_end`.
- **Commit:** d5f77e4

**3. [Rule 2 - Korrektheit] Verwalter-Schnappschuss auch in der Kind-API frei**
- **Fix:** Konten in meta time_admins bekommen limited false (wie die frei-Zeile im Mod), zusätzlich zur Rolle aus der Selbstauskunft.
- **Commit:** d5f77e4

### Hinweise

- Regeln, aber heute ganzer Tag ohne Limit: API state ok mit remaining und until null; der Browser zeigt dann keinen Block (nichts zu sagen).
- Für 04-08 (Owner-Abnahme) zur Entscheidung: Nach Fensterende mit Voreinstellung "Jeden Tag 1 Stunde" (0 bis 19 Uhr) lautet der Text "Nächste Spielzeit: Mittwoch 0 Uhr". Das stimmt mit der Regel überein, wirkt für Kinder aber seltsam; mögliche Varianten: "morgen" statt Wochentag, "Mitternacht" statt "0 Uhr", oder die Voreinstellung mit einem Beginn (etwa 9 Uhr).
- `test_my_worlds.py`: die beiden Tests mit exakter Schlüsselmenge um window_open/window_next ergänzt.

## Known Stubs

Keine.

## Threat Flags

Keine neue Fläche außerhalb des Plans. T-04-37: Antwort nur aus child_state(uid), Test mit zweitem Kind. T-04-38: kein UID-Parameter, Query-Parameter ignoriert (Test). T-04-39: nur heutiger Rest, nächste Zeit und das aktuelle oder nächste Fenster, keine Sitzungszeiten, keine Wochenpläne. T-04-40: Anzeige rechnet mit derselben Engine; Durchsetzung bleibt im Mod.

## Self-Check: PASSED

- Dateien vorhanden: tests/test_my_playtime.py, frontend/src/components/PlaytimeCard.vue, alle geänderten Dateien
- Commits vorhanden: 7effbe8, d5f77e4, 5cce92f, f00dd47, 4e5ceb4
