---
phase: 02-one-click-welten
plan: 05
subsystem: status-dashboard
tags: [players, memory, stats, dashboard, cache]
requires:
  - phase: 02-03
    provides: Welt-Mod gameworld_status (PLAYERS_FILE), Label gameworld.schema 2
  - phase: 02-04
    provides: derive_status, read_status_file (StatusFile mit gekapptem Inhalt), Lese-Retry _read, Dashboard mit Polling
provides:
  - status_mod.parse_players mit Namensfilter [A-Za-z0-9_-]{1,20}, höchstens 64 Namen
  - client.memory_from_stats (cgroup v2 plus v1-Fallback), MemoryUsage, DockerProvisioner.memory_bytes (one_shot)
  - WorldView/WorldOut.players, memory_used_bytes, memory_limit_bytes
  - 2-s-Cache der Weltenliste (LIST_CACHE_SECONDS) mit Invalidierung vor und nach jeder Mutation
  - Dashboard-Spalte Arbeitsspeicher (NcProgressBar), Zeile "Gerade online"/"Niemand online"
  - SetupCheck-Ereignis checked, App aktualisiert die Liste nach jedem Prüflauf
affects: [02-06, 02-07]
tech-stack:
  added: []
  patterns:
    - Spieler nur aus der Status-Datei dieses Laufs (status running setzt mtime >= StartedAt voraus), nie aus Logs
    - RAM nur für laufende eigene Container, Fehler pro Welt isoliert
    - Listen-Cache mit Generationszähler, damit eine vor einer Mutation begonnene Liste nicht nachträglich im Cache landet; unknown wird nie gecacht
    - Frontend wendet nur die Antwort des zuletzt gestarteten Listenabrufs an
key-files:
  created:
    - tests/test_players_memory.py
  modified:
    - src/gameworld/provisioner/status_mod.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - frontend/src/App.vue
    - frontend/src/components/SetupCheck.vue
    - tests/test_service_lifecycle.py
    - tests/e2e/test_status_e2e.py
key-decisions:
  - "02-05: Listen-Cache 2 s mit Generationszähler; Mutationen verwerfen ihn davor und danach (auch bei Fehlern, über _mutating); 'Docker nicht erreichbar' wird nie gecacht"
  - "02-05: Spieler nur bei abgeleitetem Status running, RAM bei jedem laufenden Container (auch während 'Startet gerade')"
  - "02-05: Frontend-Listenabrufe mit Sequenznummer, damit eine langsame ältere Antwort keine neuere überschreibt"
requirements-completed: []
duration: 15min
completed: 2026-10-19
---

# Phase 2 Plan 05: Online-Spieler, Arbeitsspeicher und Listen-Cache Summary

**Das Dashboard zeigt pro laufender Welt die Online-Spieler aus der Status-Datei des Welt-Mods (streng gefiltert, nie aus Logs) und den RAM-Verbrauch aus `docker stats` (one_shot, usage minus inactive_file) als Balken; ein 2-s-Cache schützt Docker vor Mehrfach-Tabs, und "Erneut prüfen" zieht die Weltenliste ohne Reload nach.**

## Performance

- **Duration:** ca. 15 min (21:30 bis 21:45)
- **Tasks:** 2 von 2
- **Files modified:** 9 (1 neu)

## Accomplishments

- `status_mod.parse_players`: UTF-8 mit Ersatzzeichen, `splitlines`, `fullmatch` gegen `[A-Za-z0-9_-]{1,20}`, Dateireihenfolge, Duplikate einmal, höchstens 64 Namen. Leerzeichen, Umlaute, `<script>`, 21 Zeichen und IP-Adressen (auch `::1`) fallen heraus.
- `client.memory_from_stats` (rein): usage minus `inactive_file`, Fallback `total_inactive_file`, nie negativ, fehlende oder nicht ganzzahlige Felder sowie Limit 0 ergeben None. `memory_bytes(world_id)` über `_read` (Lese-Retry) und `_owned`, `stats(stream=False, one_shot=True)` nur bei `container.status == "running"`.
- `service.py`: `_status_file` liefert die bereits gelesene StatusFile, Spieler nur bei abgeleitetem Status running (damit nie aus einem früheren Lauf), `_memory` pro Welt mit eigenem Fehlerfang. Cache in `_list_worlds_sync` mit `_cache_lock`, `LIST_CACHE_SECONDS = 2.0`, Kopien statt geteilter Objekte, Generationszähler; alle fünf Mutationen laufen über `_mutating()` (invalidieren, `_LOCK`, im finally invalidieren).
- API: `WorldOut.players`, `memory_used_bytes`, `memory_limit_bytes`.
- Dashboard: Namenszelle mit "Gerade online: Mia, Leo" bzw. "Niemand online" nur bei status running; Spalte "Arbeitsspeicher" mit `NcProgressBar` (Prozent 0 bis 100, `error` ab 90) und Text "Arbeitsspeicher: 18 MB von 512 MB" (`formatBytes`: unter 1 GiB ganze MB, sonst GB mit deutschem Komma, ",0" entfällt), sonst "nicht aktiv". Nur Textinterpolation.
- `SetupCheck.vue` emittiert `checked` im finally jedes Prüflaufs; `App.vue` hört mit `@checked="refresh"` (der Zusatz-Refresh aus 02-04 in `onSetupOk` entfällt dadurch).

## Live-Belege

- `tests/e2e/test_status_e2e.py`: laufende Kreativwelt mit `0 < memory_used_bytes <= memory_limit_bytes == 536870912`, `players == []`; nach Stop von außen `memory_used_bytes`/`memory_limit_bytes` null, `players` leer. `wait_for_status(client, world_id, expected, timeout=10.0)` nach externem stop und kill (8 Vorkommen). Drei Läufe hintereinander grün: 3 passed (12,8 s / 14,7 s / 15,7 s).
- Playwright headless (Skript `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\ui-check-02-05.cjs`): Kreativwelt erstellt, "Läuft", "Niemand online", RAM-Balken mit "Arbeitsspeicher: 18 MB von 512 MB"; Proxy gestoppt, Chip "Docker nicht erreichbar", RAM "nicht aktiv"; Polling per verborgenem Tab abgeschaltet, Proxy gestartet, 8 s später unverändert "Docker nicht erreichbar"; "Erneut prüfen" -> binnen 1 s "Läuft" ohne Reload; Welt gelöscht; 0 Konsolenfehler, 0 Seitenfehler; Proxy am Ende `running`.
- Screenshots:
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-05-ui-1-laeuft-ram.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-05-ui-2-proxy-weg.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-05-ui-3-erneut-geprueft.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-05-ui-4-geloescht.png`

## Task Commits

1. **Task 1 RED: failing tests** - `d98ab87` (test)
2. **Task 1 GREEN: Spieler, RAM, Listen-Cache** - `0a2691a` (feat)
3. **Task 2: Dashboard mit Spielern und RAM, Refresh nach Setup-Check** - `ba670a5` (feat)

## Decisions Made

- Cache mit Generationszähler statt nur Zeitstempel: Ein Listenabruf ohne `_LOCK` kann parallel zu einer Mutation laufen; ohne Zähler könnte sein Ergebnis nach der Invalidierung noch 2 s lang einen veralteten Stand liefern.
- RAM auch bei "Startet gerade" (Container läuft bereits), Spieler erst bei "Läuft".
- `monotonic` als `from time import monotonic` im Dienst, damit Tests nur die Dienst-Uhr patchen und nicht die Uhr der Event-Loop.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Überholende Listenabrufe im Dashboard**
- **Found during:** Task 2 (Playwright-Lauf)
- **Issue:** Bei gestopptem Proxy dauert ein Listenabruf mehrere Sekunden (Windows wiederholt abgewiesene Verbindungen, dazu der Lese-Retry). Ein älterer, langsamer Abruf kam nach einem neueren an und überschrieb die Tabelle; der "Erneut prüfen"-Nachweis war so nicht eindeutig, und Eltern hätten einen veralteten Stand sehen können.
- **Fix:** `refresh()` zählt Abrufe; nur die Antwort des zuletzt gestarteten Abrufs setzt Liste bzw. Fehlerkarte.
- **Files modified:** frontend/src/App.vue
- **Commit:** `ba670a5`

**2. [Rule 3 - Testinfrastruktur] Bestehender Test mit zwei Listenabrufen**
- `test_stale_status_file_is_starting_fresh_is_running` ruft die Liste zweimal ohne Mutation auf; mit dem Cache steuert er jetzt die Uhr (`clock.advance(LIST_CACHE_SECONDS)`).
- **Commit:** `d98ab87`

**3. [Rule 3 - Lint] ASYNC109 für `wait_for_status`**
- Der Plan verlangt die Signatur mit `timeout=10.0`; ruff ASYNC109 ist für genau diesen Parameter mit Begründungskommentar abgeschaltet.
- **Commit:** `d98ab87`

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 272 passed, keine SKIPPED.
- `ruff check`, `ruff format --check`, `pyright` (latest, 0 Fehler), `vulture`: grün.
- `npm --prefix frontend run build`: Exit 0 (`js/gameworld-main.js` 434 kB); Privacy-Test 8 passed; `register-exapp.sh` und `smoke.sh` grün ("Durchstich erfolgreich", auch nach Task 2 erneut).
- Akzeptanz-greps: `one_shot=True` 1 Zeile in client.py; `def parse_players` 1 Zeile; `logs(` in src/gameworld kein Treffer; `LIST_CACHE_SECONDS = 2.0` 1 Zeile; `wait_for_status` 8 Vorkommen; `emit('checked')` und `@checked="refresh"` je 1; `NcProgressBar`, "Gerade online", "Niemand online" vorhanden; kein `v-html`; keine Gedankenstriche.
- Danach keine Welt-Container übrig, Proxy `running`.

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus (T-02-23 Namensfilter plus Interpolation, T-02-24 keine Log-Auswertung, T-02-25 Cache und one_shot nur für laufende Container, T-02-26 `_owned` in memory_bytes mit Test gegen fremde Instanz).

## Next Phase Readiness

- WELT-03 ist technisch umgesetzt (Abhaken erst am Phasenende), WELT-02-Feinschliff (Cache, "Erneut prüfen") erledigt.
- Mit echten Spielern ist "Gerade online" noch nicht live gesehen (kein Luanti-Client im Test); Kandidat für die Owner-Abnahme in 02-07.

## Self-Check: PASSED

- FOUND: tests/test_players_memory.py, .planning/phases/02-one-click-welten/02-05-SUMMARY.md
- FOUND commits: d98ab87, 0a2691a, ba670a5
