---
phase: 04-spielzeitlimits
plan: 02
subsystem: playtime
tags: [zoneinfo, tzdata, golden-vectors, sqlite, schema-4, ledger, tdd]
requires:
  - phase: 04-spielzeitlimits
    provides: time_mod.py (Ledger, parse_ledger, render_time_file, TimeLine), PLAYER_NAME, Zählbuch-Format
  - phase: 03-zugang-und-rollen
    provides: worlds/store.py Schema 3 (players NOCASE, invites, world_access), PRAGMA-Migrationsmuster, access_generation
provides:
  - tzdata==2026.5 als Laufzeitabhängigkeit (zoneinfo unter Windows und im Image)
  - playtime/plan.py (rein): DayRule, WeekPlan, Holiday, ChildState, WorldState, load_zone, local_day, day_bounds, window_bounds, plan_for, next_hint, evaluate_child, evaluate_world
  - playtime/ledger.py (rein): increments(seen, current), attribution_day(written_at, tz)
  - worlds/store.py Schema 4: time_children, time_plans, holidays, world_windows, time_usage, time_ledger_seen, worlds.time_generation, meta time_zone
  - Store-Methoden: set_child_plan, clear_child, child_plans, add_usage, usage, prune_usage, ledger_seen, set_ledger_seen, add_holiday, remove_holiday, list_holidays, set_world_window, clear_world_window, world_window, bump_time_generation, delete_time_data
affects: [04-03, 04-05, 04-06, 04-07, 04-08]
tech-stack:
  added:
    - "tzdata==2026.5 (PyPI, PSF): IANA-Zeitzonendaten für zoneinfo"
  patterns:
    - "Tagesgrenzen und Fenster nur über datetime.combine mit tzinfo (keine feste Tageslänge, keine +86400)"
    - "Absolute Epoch-Grenzen aus der ExApp; der Mod kennt keine Zeitzone (Container sind UTC)"
    - "Schema 4 idempotent per PRAGMA table_info (ALTER ADD COLUMN time_generation), nur CREATE IF NOT EXISTS"
    - "store importiert playtime.plan; playtime importiert nie den Store (saubere Richtung)"
key-files:
  created:
    - src/gameworld/playtime/__init__.py
    - src/gameworld/playtime/plan.py
    - src/gameworld/playtime/ledger.py
    - tests/test_playtime_plan.py
    - tests/test_playtime_ledger.py
  modified:
    - pyproject.toml
    - uv.lock
    - src/gameworld/worlds/store.py
    - tests/test_store.py
key-decisions:
  - "evaluate_child/evaluate_world nehmen now als Epoch-Sekunden (int), wie os.time im Mod; kein datetime-Objekt an der Grenze"
  - "window_end 1440 Minuten und das Fenster None münden beide in das lokale Tagesende (Folgetag 00:00, O-04)"
  - "next_hint liefert die nächste Fensteröffnung strikt nach jetzt, bis 7 Tage voraus, über Ferienwechsel hinweg; sonst Token -"
  - "evaluate_world: geschlossener Tag -> 0 0 welt; außerhalb des Fensters bleiben die Fenstergrenzen stehen (Grund welt), damit die Welt pünktlich wieder öffnet"
  - "clear_world_window entfernt alle Fenster einer Welt (Welt immer offen); set_world_window setzt einen Wochentag"
  - "child_plans liefert je Kind (normal, holiday|None); nur Kinder mit Zeile in time_children (Opt-in, O-10)"
  - "meta time_zone wird bei der Migration nicht geschrieben; leer bedeutet Europe/Berlin (plan.load_zone)"
metrics:
  duration: 30 min
  completed: 2026-10-20
  tasks: 2
  files: 9
---

# Phase 4 Plan 02: Zeitrechnung und Gedächtnis Summary

Die Spielzeit-Logik hat jetzt einen reinen, plattformgleichen Kern und ein idempotent migriertes Zuhause: `playtime/plan.py` rechnet Tagesgrenzen, Fenster und die nächste Spielzeit ausschließlich mit `zoneinfo` (Vorgabe Europe/Berlin, `tzdata==2026.5`), gegen Golden Vectors für die Umstellungstage (23 h und 25 h), Ferienwechsel und Tagesende festgeschrieben. `playtime/ledger.py` verbucht Zählbuch-Zuwächse ohne Doppel- oder Minuszählung. Schema 4 der Welt-Datenbank trägt Wochenpläne, Ferien, Welt-Fenster, Tagesverbrauch und die gesehenen Zählbuchstände und entsteht aus Schema 3 ohne Datenverlust. Dieser Schnitt ist bewusst rein (keine API, kein Docker) und liefert die Verträge, gegen die 04-03 die Durchsetzung aus der Datenbank baut.

## Ergebnis

- **tzdata und reine Plan-Auswertung (Task 1):** `ZoneInfo("Europe/Berlin")` lädt jetzt in der `.venv` unter Windows (vorher `ZoneInfoNotFoundError`), weil `tzdata==2026.5` als Laufzeitabhängigkeit dazukam (Pin aus 04-RESEARCH.md, slopcheck OK, PSF-Repo). `day_bounds` und `window_bounds` rechnen über `datetime.combine(tag, time, tzinfo=tz)` bis zum Folgetag 00:00, nie über eine feste Tageslänge (`grep 86400` in plan.py ist leer). Die Golden Vectors stimmen wörtlich: 24.10. `(1792792800, 1792879200)`, 25.10. `(1792879200, 1792969200)` mit 25 h, 26.10. `(1792969200, 1793055600)`, 29.03. `(1774738800, 1774821600)` mit 23 h; 19:00 lokal am DST-Sonntag `1792951200`. `DayRule`, `WeekPlan` (genau 7 Tage) und `Holiday` validieren im `__post_init__` und werfen sonst `ValueError`. `evaluate_child` liefert die Gründe tag/fenster/limit/ok mit Rest in Sekunden (None ohne Limit), `evaluate_world` None (immer offen), `0 0 welt` (geschlossen) oder ok im Fenster. `next_hint` sucht bis 7 Tage voraus die nächste Öffnung und gibt Token wie `Sa-10:00` oder `-`.
- **Verbuchung und Schema 4 (Task 2):** `increments({"Mia": 40}, {"Mia": 55, "Leo": 7})` ergibt `({"Mia": 15}, {"Mia": 55, "Leo": 7})` (Leo Erstkontakt: nur verankern), `increments({"Mia": 40}, {"Mia": 10})` ergibt `({}, {"Mia": 10})` (Rücksprung: neu verankern, nie negativ); die Zuordnung ist NOCASE wie `players.player_name`. `attribution_day` nimmt den lokalen Tag des Zählbuch-Kopfs. `store.py` ist Schema 4: sechs neue Tabellen (CREATE IF NOT EXISTS, CHECK-Bedingungen wie skizziert, `time_plans.plan IN ('normal','ferien')`, `holidays.label` höchstens 60 Zeichen), `worlds.time_generation` per ALTER nur wenn die Spalte in `PRAGMA table_info(worlds)` fehlt. Die Store-Methoden geben `plan.DayRule/WeekPlan/Holiday` zurück; `store` importiert `playtime.plan`, `playtime` nie den Store (grep leer). `meta time_zone` wird bei der Migration nicht geschrieben (leer = Europe/Berlin).

### Nachweise

- `tests/test_playtime_plan.py`: 24 Tests, enthält die Golden-Vector-Zahlen 1792792800, 1792969200, 1774738800, 1774821600 und 1792951200 wörtlich.
- `tests/test_playtime_ledger.py`: 6 Tests (Zuwachs, Erstkontakt, Rücksprung, NOCASE, keine Mutation der Eingaben, Tageszuordnung).
- `tests/test_store.py`: schema_version-Asserts auf "4" umgestellt, `test_fresh_file_gets_schema_3` -> `test_fresh_file_gets_schema_4` (prüft die sechs Tabellen), neu: Migration Schema 3 auf 4 mit Welt/Spieler/Einladung/Zugang (alle Zeilen erhalten, `time_generation = 0`) und Idempotenz, plus Tests für set_child_plan (7/14 Zeilen), clear_child, child_plans, usage/prune, ledger_seen, Ferien-CRUD, Welt-Fenster, bump_time_generation, delete_time_data.
- Gesamte Nicht-Docker-Suite: `uv run pytest -q -m "not docker"` = 697 passed, 24 deselected (vorher 656 ohne Docker in 04-01, also +41 neue Tests). Gates grün: `ruff check` (All checks passed), `ruff format --check` (83 files already formatted), `pyright` (0 errors), `vulture` (leer).

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 446008c | tzdata==2026.5 und reine Plan-Auswertung mit Golden Vectors (plan.py) |
| 2 | a23aee7 | Verbuchung (ledger.py) und Schema 4 mit Store-Methoden, Migration 3->4 |

## Deviations from Plan

### Auto-fixed Issues

Keine inhaltlichen Abweichungen vom Plan. Zwei kleine, werkzeugbedingte Anpassungen:

**1. [Rule 3 - blockierend] Callable-Import und Zeilenlänge in store.py**
- **Found during:** Task 1 und Task 2 (Gate-Durchlauf)
- **Issue:** `_next_start` braucht `collections.abc.Callable` für die Typ-Annotation; in store.py überschritt die Rückgabe-Annotation von `_plan_rows` 120 Zeichen (ruff E501).
- **Fix:** `Callable` sauber oben importiert (statt nachgelagert mit noqa); Modul-Typalias `_PlanRow` eingeführt, um die Zeile zu kürzen; `TIME_TABLES <= set(...)` in den Tests durch `TIME_TABLES.issubset(...)` ersetzt (ruff-Vorschlag). Danach `ruff format` angewandt.
- **Commit:** 446008c, a23aee7

### Hinweise

- **TDD-Commits zusammengefasst:** Wie in 04-01 je Task ein Commit mit der im Plan genannten Nachricht (Vorgabe "atomar je Task"). RED wurde lokal belegt (Task 1: ModuleNotFoundError vor der Umsetzung; Task 2: Ledger-Tests rot bis increments/attribution_day standen), aber nicht separat committet.
- **Testnamen test_schema_1/2_is_migrated_to_3:** Der Plan verlangt ausdrücklich nur die Umbenennung von `test_fresh_file_gets_schema_3`. Die beiden `migrated_to_3`-Tests behalten ihren Namen, prüfen aber jetzt schema_version "4" (sie belegen, dass eine Altdatei bis zum aktuellen Schema hochmigriert).

## Known Limitations

- `meta time_zone` ist bewusst noch nicht gesetzt (leer bedeutet Europe/Berlin via `plan.load_zone`); das Setzen übernimmt die Einstellungs-Route in einer späteren Welle.
- Die Verträge sind rein: Es gibt noch keinen Lifespan-Takt, keine API und keine Verdrahtung in `render_time_file`. 04-03 verbindet Schema 4, `evaluate_child/evaluate_world` und `increments` mit der Durchsetzung aus der Datenbank. Das ist kein Stub, sondern der geplante nächste Schnitt.
- `clear_world_window` entfernt alle Fenster einer Welt; einen einzelnen Wochentag wieder zu schließen, ist derzeit nicht vorgesehen (die UI setzt den ganzen Wochenplan). Bei Bedarf in 04-05 erweiterbar.

## Known Stubs

Keine. Alle Rückgaben stammen aus den validierten Eingaben bzw. aus der Datenbank; keine hartcodierten Leerwerte oder Platzhalter, die ein Ziel dieses Plans verfehlen.

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Modells. Keine neuen Endpunkte, kein Netzzugriff, kein exec. Umgesetzt und per Unit-Test belegt: T-04-10 (increments verankert bei Rücksprung und Erstkontakt neu, nie negativ), T-04-12 (zoneinfo plus tzdata, Golden Vectors, keine +86400-Rechnung), T-04-13 (nur Tagessummen, nur Kinder mit Regeln, prune_usage), T-04-14 (Migration nur CREATE IF NOT EXISTS und ALTER ADD COLUMN nach PRAGMA table_info, Migrationstest mit Daten), T-04-SC (tzdata exakt 2026.5 gepinnt, in uv.lock mit Hashes, PSF-Repo).

## Self-Check: PASSED

- Dateien vorhanden: playtime/__init__.py, playtime/plan.py, playtime/ledger.py, tests/test_playtime_plan.py, tests/test_playtime_ledger.py
- Commits vorhanden: 446008c, a23aee7
- `grep "tzdata" pyproject.toml` findet 2026.5; `grep "86400" src/gameworld/playtime/plan.py` leer; `grep "PRAGMA table_info" src/gameworld/worlds/store.py` findet die time_generation-Prüfung; playtime importiert den Store nicht.
