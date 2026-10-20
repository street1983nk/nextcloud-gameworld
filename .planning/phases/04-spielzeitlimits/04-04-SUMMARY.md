---
phase: 04-spielzeitlimits
plan: 04
subsystem: playtime
tags: [weekplan, holidays, timezone, zoneinfo, api, e2e]
requires:
  - phase: 04-spielzeitlimits
    provides: TimeEngine (render, child_state mit plan_for/evaluate_child), TimeService, api/playtime.py, Store holidays/meta, push_time
provides:
  - ChildPlanIn.holiday (optionaler Ferienplan je Kind), holiday in ChildOut
  - POST /api/playtime/holidays, DELETE /api/playtime/holidays/{holiday_id}
  - POST /api/playtime/time-zone (nur available_timezones())
  - GET /api/playtime liefert holidays (mit active) und time_zone
  - TimeService.add_holiday/remove_holiday/set_time_zone, _refresh_all_worlds unter mutation()
  - WorldStore.holiday_rows (Ferien mit id)
affects: [04-05, 04-06, 04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "Haushaltsweite Änderung (Ferien, Zeitzone) schreibt die Regeldatei aller Welten unter mutation(); applied = alle Welten tragen sie"
    - "Validatoren als Annotated[..., AfterValidator(fn)] statt classmethod (vulture-sauber)"
key-files:
  created:
    - tests/e2e/test_holidays_e2e.py
  modified:
    - src/gameworld/api/playtime.py
    - src/gameworld/playtime/service.py
    - src/gameworld/worlds/store.py
    - tests/test_playtime_api.py
    - tests/test_playtime_engine.py
key-decisions:
  - "holiday null = in den Ferien gilt der Normalplan; Zeitzone über eigene Route /api/playtime/time-zone, /api/settings unverändert"
  - "Obergrenze 50 Ferienzeiträume wird unter derselben Sperre gezählt und angelegt (kein Überschreiten durch parallele Anfragen)"
  - "Ferienlänge inklusive gezählt: höchstens 366 Tage (2026-01-01 bis 2027-01-01 erlaubt)"
  - "Label wird nach der Prüfung (isprintable) getrimmt; DELETE liefert den entfernten Zeitraum samt applied"
requirements-completed: [ZEIT-03, ZEIT-04]
metrics:
  duration: 60 min
  completed: 2026-10-20
  tasks: 2
  files: 6
---

# Phase 4 Plan 04: Wochenplan, Ferien und Zeitzone Summary

Ferienplan je Kind, Haushalts-Ferienliste und einstellbare Zeitzone (Vorgabe Europe/Berlin) per Verwalter-API; jede Ferien- oder Zeitzonenänderung schreibt sofort die Regeldatei aller Welten, die laufende Welt übernimmt den Plan ohne Neustart. Wochentag, Ferienumschaltung am lokalen Datum und Zeitzonenwechsel sind live gegen eine echte MTG-Welt belegt.

## Ergebnis

- **API (Task 1):** `ChildPlanIn.holiday: list[DayIn] | None` mit derselben WeekPlan-Prüfung; `HolidayIn` (extra forbid, ISO-Datum, von <= bis, höchstens 366 Tage, Label höchstens 60 Zeichen ohne Steuerzeichen); `TimeZoneIn` nur mit Namen aus `available_timezones()` (einmal beim Import zwischengespeichert). Routen POST `/holidays`, DELETE `/holidays/{holiday_id}` (404 bei unbekannter id), POST `/time-zone`; alle hinter `require_verwalter` routerweit plus AppAPI ADMIN. GET liefert `holidays` sortiert nach Beginn mit `active` und `time_zone`.
- **Dienst:** `add_holiday`, `remove_holiday`, `set_time_zone` jeweils unter `worlds.mutation()` mit `_refresh_all_worlds()` (push_time für jede Welt der Datenbank; ohne Container False, der nächste Start schreibt). 51. Zeitraum ergibt 422.
- **Engine:** Die Planwahl über `plan_for` mit Ferienliste und Ferienplan je Kind sowie die Zeitzone frisch aus meta waren schon in 04-03 vollständig; neue Tests belegen es (Ferien heute -> ok bis Tagesende, Ferien bis gestern -> tag, Zeitzonenwechsel wirkt im nächsten Rendern ohne Cache).
- **Live (Task 2):** `tests/e2e/test_holidays_e2e.py` (1 Test, 33 s): (1) Normalplan nur morgen -> denied mit "Heute ist kein Spieltag. Nächste Spielzeit: <Token> 10:00"; (2) Ferienplan gesetzt ohne Zeitraum weiter denied, Ferien heute -> auth_accept, Sitzung 15 s held, StartedAt unverändert, Regelzeile `-1 <Tagesanfang> <Tagesende> ok`; (3) Ferien gelöscht -> tag, denied; (4) Ferien vorgestern bis gestern -> active false, denied; (5) Pacific/Kiritimati -> Tagesgrenzen der Regeldatei = lokaler Tag dort (vom Test mit zoneinfo gerechnet), Mars/Base 422, zurück auf Europe/Berlin. Aufräumen: Ferien, Regeln, Welt gelöscht.

### Nachweise

- Nicht-Docker: 762 passed. Gesamtsuite `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 788 passed in 14:18 min. Danach kein Container mit `gameworld.managed=true`.
- Gates grün: ruff check, ruff format --check, pyright (0 errors), vulture (leer).
- `git log --format=%s -- src/gameworld/api/invites.py | grep -c "(04-04)"` = 0 (Vertrag /api/settings unverändert).
- Live-Dev-Stack: altes Backend (PID 10452 auf Port 10040, Kommandozeile `gameworld.main` geprüft) gezielt gestoppt, `sh scripts/dev/register-exapp.sh`: "ExApp gameworld successfully registered". Proxy-GET `/api/playtime` liefert 200 mit `time_zone` Europe/Berlin, `holidays` [] und `holiday` je Kind; POST `/time-zone` mit "../etc" ergibt 422. ExApp-Log ohne ERROR/Traceback.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 16d4329 | Ferienplan je Kind, Haushalts-Ferien, Zeitzone in API und Dienst, Tests |
| 2 | b1e3bb4 | Live-Nachweis Wochentag, Ferienumschaltung und Zeitzone |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - blockierend] WorldStore.holiday_rows ergänzt**
- **Found during:** Task 1
- **Issue:** `list_holidays` liefert keine id; DELETE und die Ausgabe mit id brauchen sie. `store.py` stand nicht in der Dateiliste.
- **Fix:** `holiday_rows()` liefert `(id, Holiday)`, `list_holidays` baut darauf auf (gleiches Verhalten).
- **Commit:** 16d4329

**2. [Gate] Validatoren als AfterValidator**
- **Found during:** Task 1 (vulture meldete unbenutztes `cls` der classmethod-Validatoren)
- **Fix:** Modulfunktionen `_printable_label`, `_known_zone` über `Annotated[str, AfterValidator(...)]`.
- **Commit:** 16d4329

### Hinweise

- **TDD:** RED lokal belegt (24 API-Tests rot, Routen fehlten); die drei neuen Engine-Tests waren sofort grün, weil die Planwahl schon in 04-03 vollständig war (Regressionsschutz, kein Fehltest). Wie in 04-01 bis 04-03 je Task ein Commit.
- Ein versehentlich gestarteter `uv run python -` (stdin) wurde gezielt per PID beendet; keine Auswirkung.

## Known Limitations

- Bedienung (Kacheln, Voreinstellungen, Ferienvorschlag "Jeden Tag 2 Std, 9 bis 20 Uhr") folgt in 04-06; kein Ferien-/Feiertagsimport (Deferred).

## Known Stubs

Keine.

## Threat Flags

Keine neue Fläche außerhalb des Threat-Modells. Umgesetzt und belegt: T-04-22 (nur available_timezones, "../etc", "/etc/passwd", "Mars/Base", "" 422), T-04-23 (Datum, Reihenfolge, 366 Tage, Label, 50 Zeiträume, 422), T-04-24 (gw-kind 403 auf allen neuen Routen, keine Änderung in der DB), T-04-25 (push_time aller Welten unter mutation(), e2e ohne Neustart).

## Self-Check: PASSED

- Dateien vorhanden: tests/e2e/test_holidays_e2e.py, src/gameworld/api/playtime.py, src/gameworld/playtime/service.py
- Commits vorhanden: 16d4329, b1e3bb4
