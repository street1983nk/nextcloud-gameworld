---
phase: 04-spielzeitlimits
plan: 06
subsystem: frontend
tags: [vue, nextcloud-vue, ui, presets, day-tiles, holidays, world-window]
requires:
  - phase: 04-spielzeitlimits
    provides: GET/POST/DELETE /api/playtime (04-03, 04-04), Welt-Fenster-API und WorldOut.time_window/time_restart_needed (04-05)
provides:
  - frontend/src/playtime.js (rein, Node-geprüft): PRESETS, HOLIDAY_PRESET, LIMIT_OPTIONS, NO_LIMIT_OPTION, summarize, windowSummary, fromApiDays/toApiDays, fromWindowDays/toWindowDays, validateDays, usageText, formatMinutes, formatClock
  - DayTiles (7 Kacheln, wiederverwendet für Kinder-Woche, Ferienplan, Welt-Fenster)
  - PlaytimeDialog, PlaytimeSection, HolidayList, WorldWindowDialog, TimeZoneSetting
  - api.js: getPlaytime, saveChildPlan, clearChildPlan, addHoliday, removeHoliday, setTimeZone, setWorldWindow, clearWorldWindow
affects: [04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "Reine Logik in playtime.js, geprüft mit node:assert (frontend/tests/playtime.check.mjs), Vue-Komponenten nur Darstellung"
    - "Spielzeitdaten lädt ParentView einmal (GET /api/playtime) und reicht sie an Spielzeit, Ferien und Zeitzone weiter; Neuladen im Dashboard-Takt, höchstens alle 30 s"
key-files:
  created:
    - frontend/src/playtime.js
    - frontend/tests/playtime.check.mjs
    - frontend/src/components/DayTiles.vue
    - frontend/src/components/PlaytimeDialog.vue
    - frontend/src/components/PlaytimeSection.vue
    - frontend/src/components/HolidayList.vue
    - frontend/src/components/WorldWindowDialog.vue
    - frontend/src/components/TimeZoneSetting.vue
  modified:
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
key-decisions:
  - "Kind-Chip höchstens 30 Zeichen: passt das Zeitfenster nicht mehr hinein, entfällt es ('Sa und So, je 2 Std'), sonst steht es dabei ('Jeden Tag 1 Std, bis 19 Uhr'); zwei Regelgruppen ohne Fenster ('Mo bis Fr 1 Std, Sa und So 2 Std'), mehr als zwei 'Eigener Wochenplan'"
  - "'Keine Begrenzung' blendet die Kacheln aus und speichert per DELETE; ein nicht erlaubter Tag geht ohne Limit und Fenster an die API"
  - "Welt-Fenster: 'ganzer Tag' = 0 bis 1440; alle Tage geschlossen sperrt Speichern im Browser (Backend 422), 'Immer offen' = DELETE"
  - "Als Ende heißt 00:00 Mitternacht (1440); Uhrzeiten im 15-Minuten-Raster (step 900)"
  - "Heutige Nutzung 'heute 45 von 60 min' nur bei Limit heute, nicht erlaubter Tag zeigt 'heute kein Spieltag'; Wochentag in der Haushalts-Zeitzone per Intl, Ferienplan wenn Ferien laufen"
requirements-completed: [ZEIT-01, ZEIT-03, ZEIT-04, ZEIT-05]
metrics:
  duration: 35 min
  completed: 2026-10-20
  tasks: 2
  files: 10
---

# Phase 4 Plan 06: Eltern-Oberfläche für Spielzeit, Ferien, Welt-Zeitfenster und Zeitzone Summary

Eltern stellen Spielzeit je Kind mit den vier Voreinstellungen aus O-07 und sieben Tages-Kacheln ein (inklusive eigener Ferienregeln), pflegen die Haushalts-Ferienliste, setzen Zeitfenster je Welt und wählen die Zeitzone, alles ohne Konfigsprache; im Browser per Playwright durchgespielt, 0 Konsolenfehler.

## Ergebnis

- **playtime.js (rein):** Voreinstellungen als eingefrorene API-Tage (wochenende Sa/So 120 min 540 bis 1140, taeglich 60 min 0 bis 1140, schultage Mo bis Fr 60 min 900 bis 1140 plus Sa/So wie Wochenende, Ferien 120 min 540 bis 1200), verlustfreie Umrechnung Kacheln <-> API und Kacheln <-> Welt-Fenster, Kurztexte, Browser-Prüfung "Ende nach Beginn".
- **DayTiles:** je Tag Name, Schalter "Spielen erlaubt" bzw. "Offen", Tageslimit (NcSelect, "ohne Limit" plus 15 min bis 4 Std), "ganzer Tag" oder von/bis (NcDateTimePickerNative type time, step 900), Hinweistext bei Ende vor Beginn, Knopf "Für alle Schultage übernehmen" am Montag.
- **PlaytimeDialog:** "Spielzeit für <Name>", vier Voreinstellungsknöpfe, Block "Normale Woche", Block "In den Ferien" mit Schalter "Eigene Regeln in den Ferien" (vorbelegt mit dem Ferien-Vorschlag), Speichern über saveChildPlan bzw. clearChildPlan, Fehler über errorText.
- **PlaytimeSection:** Abschnitt "Spielzeit" mit Erklärsatz, Zeile je Kind (Anzeigename, Spielername, Chip, Verbrauch heute, "Bearbeiten"), leerer Zustand "Noch keine Kinder eingeladen."
- **HolidayList:** Abschnitt "Ferien", Hinweis, Liste mit Chip "läuft gerade", Formular (Bezeichnung optional, von/bis als type date), Entfernen mit Rückfrage.
- **WorldWindowDialog:** "Zeitfenster für <Weltname>", Kacheln ohne Limit, "Immer offen" und "Speichern", Hinweis zum Weiterlaufen der Welt.
- **TimeZoneSetting:** unter der Spieler-Adresse, NcTimezonePicker, Vorgabe Europe/Berlin, Knopf "Zeitzone dieses Browsers übernehmen" (Intl, kein externer Dienst).
- **ParentView:** Welt-Zeile mit Knopf "Zeitfenster" und Chip ("Offen Mi 10 bis 12 Uhr"); Neustart-Hinweise für Zugang, Spielzeit oder beides gemeinsam ("Neustart nötig, damit Spielzeiten gelten."); Spielzeit und Ferien unter der Weltenliste.

### Nachweise

- `node frontend/tests/playtime.check.mjs`: alle Prüfungen bestanden (RED vorher belegt: Modul fehlte, Exit 1, Commit 0926145).
- `npm run build` grün, `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed.
- `grep -c` der vier Voreinstellungen in PlaytimeDialog.vue: 6; Gedankenstrich-Suche in frontend/src: leer; `time_restart_needed` und `NcTimezonePicker` per grep gefunden.
- Dev-Stack: `sh scripts/dev/register-exapp.sh` ("Backend antwortet schon auf Port 10040 und passt zu den Quellen", "ExApp gameworld successfully registered"); Backend unverändert, nur das Bundle neu.
- **Playwright-Selbstprüfung** (Skript `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\ui-check-04-06.cjs`, admin, Browser-Zeitzone Europe/Vienna): Testwelt "UI Zeit" angelegt und gw-kind eingeladen; "Nur am Wochenende" mit eigenen Ferienregeln gespeichert -> Chip "Sa und So, je 2 Std", "heute kein Spieltag" (Dienstag); zurück auf "Keine Begrenzung" -> Chip "Keine Begrenzung"; Ferien "UI-Test-Ferien" 21.12.2026 bis 06.01.2027 angelegt und mit Rückfrage entfernt; Zeitfenster nur Mi 10:00 bis 12:00 -> Chip "Offen Mi 10 bis 12 Uhr", danach "Immer offen" -> Chip weg; Zeitzone per Browser-Vorschlag auf Europe/Vienna gespeichert, danach über den Picker zurück auf Berlin. Konsolenfehler: 0. Testwelt gelöscht (204). Nachkontrolle in der SQLite-Datei: time_zone Europe/Berlin, 0 Ferien, 0 Pläne, 0 Welt-Fenster; kein Container mit `gameworld.managed=true`.
- Screenshots (Scratchpad `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\`):
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-1-uebersicht.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-2-dialog-wochenende.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-3-dialog-ferienblock.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-4-kind-wochenende.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-5-ferien.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-6-zeitfenster-dialog.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-7-welt-chip.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\a8f4f483-22df-4541-8cb7-650b29ce088b\scratchpad\04-06-ui-8-zeitzone.png`

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 (RED) | 0926145 | Prüfskript playtime.check.mjs (schlug fehl, Modul fehlte) |
| 1 | 0533232 | playtime.js, DayTiles, PlaytimeDialog, PlaytimeSection, api.js, ParentView |
| 2 | 23b0d7e | HolidayList, WorldWindowDialog, TimeZoneSetting, Welt-Chip und Neustart-Hinweis, Kachel-Layout |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Tageslimit-Auswahl und Kopierknopf ragten aus der Kachel**
- **Found during:** Task 2 (Playwright-Selbstprüfung)
- **Issue:** NcSelect bringt eine Mindestbreite mit und überlappte die Nachbarkachel; der Text "Für alle Schultage übernehmen" lief über den Rand.
- **Fix:** `:deep(.v-select.select)` auf Kachelbreite, Knopftext darf umbrechen, Kachel-Mindestbreite 220 px.
- **Files modified:** frontend/src/components/DayTiles.vue
- **Commit:** 23b0d7e

**2. [Rule 1 - Bug] Datumsfelder der Ferienliste über volle Breite**
- **Fix:** Formularfelder flexibel mit höchstens 280 px, Knopf fest.
- **Commit:** 23b0d7e

**3. [Rule 2 - Korrektheit] Welt-Fenster ohne offenen Tag**
- **Issue:** Das Backend weist sieben geschlossene Tage mit 422 ab (04-05).
- **Fix:** Speichern im Dialog gesperrt mit Hinweis auf "Immer offen".
- **Commit:** 23b0d7e

### Hinweise

- Ergänzte Exporte über die Plan-Liste hinaus: NO_LIMIT_OPTION (LIMIT_OPTIONS bleibt die reine Liste 15 bis 240, damit das Kriterium "beginnt bei 15, endet bei 240" gilt), windowSummary, fromWindowDays/toWindowDays, validateDays, minutesToDate/dateToMinutes, weekdayIn, todayRule.
- Die Beschriftungen der Voreinstellungsknöpfe stehen in PlaytimeDialog.vue (Akzeptanzkriterium grep), die Tage in playtime.js.
- Ein Screenshot direkt nach einem Schalterklick zeigt den Schalter noch im alten Zustand (CSS-Übergang); per Skript nachgeprüft: `isChecked` und die gerenderten Kacheln folgen dem Klick sofort, dreimal hintereinander.
- Kein Frontend-Lint-Skript im Projekt (package.json hat nur build); Python unverändert, daher keine Python-Gates nötig.

## Known Stubs

Keine.

## Threat Flags

Keine neue Fläche. T-04-34: Abschnitte nur in ParentView (Verwalteransicht). T-04-35: encodeURIComponent für Konto-ID, Welt-ID und Ferien-ID. T-04-36: keine neuen Pakete, keine externen URLs, Zeitzonen aus @nextcloud/vue, Vorschlag aus Intl.

## Self-Check: PASSED

- Dateien vorhanden: frontend/src/playtime.js, frontend/tests/playtime.check.mjs, alle sechs Komponenten
- Commits vorhanden: 0926145, 0533232, 23b0d7e
