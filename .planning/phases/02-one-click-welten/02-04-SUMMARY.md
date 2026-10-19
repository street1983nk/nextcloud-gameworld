---
phase: 02-one-click-welten
plan: 04
subsystem: status-dashboard
tags: [status, restart, dashboard, polling, preset-choice]
requires:
  - phase: 02-01
    provides: Preset-Registry, /api/presets, preset in DB-Zeile und WorldOut
  - phase: 02-03
    provides: Welt-Mod gameworld_status (PLAYERS_FILE), Label gameworld.schema 2, WorldPayload
provides:
  - worlds/status.py mit derive_status, WorldStatus, parse_docker_time, schema_version
  - ContainerInfo mit exit_code, oom_killed, started_at, schema
  - DockerProvisioner.read_status_file -> StatusFile(mtime, content) und Lese-Retry _read
  - WorldService.restart_world und POST /api/worlds/{id}/restart
  - WorldOut.status und WorldOut.status_text
  - Dashboard mit Spielart-Auswahl, Statuschips, Neustart, 5-s-Polling
affects: [02-05, 02-06, 02-07]
tech-stack:
  added: []
  patterns:
    - Status rein aus Docker (inspect plus mtime der Status-Datei), DB nur für creating/failed
    - Ein Codepfad _views für Liste und Einzelansicht, Status-Datei nur für laufende Schema-2-Welten
    - Lesende Docker-Aufrufe genau einmal wiederholt (Keep-Alive-Abbruch), Mutationen nie
    - Neustart = stop plus _launch (Port-Saga, Neuerzeugung aus Volume)
key-files:
  created:
    - src/gameworld/worlds/status.py
    - tests/test_status.py
    - tests/e2e/test_status_e2e.py
  modified:
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - frontend/src/api.js
    - frontend/src/App.vue
    - tests/test_provisioner_errors.py
    - tests/test_service_lifecycle.py
    - tests/test_service_unavailable.py
    - tests/test_frontend_privacy.py
key-decisions:
  - "02-04: Lese-Retry nur bei requests ConnectionError oder urllib3 ProtocolError als __cause__, Timeouts werden nicht wiederholt"
  - "02-04: Status-Datei gekappt in zwei Stufen: höchstens 64 KiB Tar-Strom, daraus höchstens 4096 Bytes Inhalt (Tar im Strom-Modus r|)"
  - "02-04: Docker-Zustände paused/dead/removing ergeben error mit Klartext statt eines stillen Fallbacks"
  - "02-04: create_world antwortet mit dem echten abgeleiteten Status (meist starting) statt fest running"
  - "02-04: Privacy-Grep-Gate nimmt nur die DOM-API document.visibilityState und 'visibilitychange' aus, mit Gegenprobe"
requirements-completed: []
duration: 14min
completed: 2026-10-19
---

# Phase 2 Plan 04: Status aus Docker, Neustart und Dashboard mit Spielart Summary

**Jede Welt zeigt jetzt einen Elternstatus aus Docker (Läuft, Startet gerade, Gestoppt, Fehler mit Klartext, Docker nicht erreichbar), lässt sich per Klick neu starten, und das Dashboard wählt die Spielart vor dem Erstellen per Klick (Kreativ vorausgewählt) und aktualisiert sich alle 5 s bei sichtbarem Tab.**

## Performance

- **Duration:** ca. 14 min (21:15 bis 21:29)
- **Tasks:** 2 von 2
- **Files modified:** 12 (3 neu)

## Accomplishments

- `worlds/status.py` (ohne Docker-Import): `derive_status` nach RESEARCH Pattern 3, alle Elterntexte als Konstanten; `parse_docker_time` verträgt Nanosekunden und wertet `0001-01-01T00:00:00Z` sowie Unlesbares als "noch nicht bereit"; `schema_version` liest das Label als Ganzzahl (unlesbar = 1).
- `client.py`: `ContainerInfo` um `exit_code`, `oom_killed`, `started_at`, `schema` erweitert (Defaults, Fakes bleiben gültig); `read_status_file` über `get_archive(PLAYERS_FILE)`, NotFound -> None, fremde Container über `_owned` ausgeschlossen, kein Follow-Stream; `_read` wiederholt `list_managed`, `used_host_ports`, `read_status_file` genau einmal nach Keep-Alive-Abbruch (Kommentar mit HAProxy `timeout http-keep-alive 10s`).
- `service.py`: `_views` als einziger Statuspfad für Liste und `_current`; Status-Datei nur für laufende Welten mit Schema >= 2, Fehler pro Welt isoliert (geloggt, Welt zeigt "Startet gerade"); `restart_world` unter `_LOCK` als stop (fehlender Container = No-op) plus `_launch`, Fehler -> `_fail`.
- API: `WorldOut.status`, `WorldOut.status_text` (docker_status bleibt), `POST /api/worlds/{id}/restart` mit 200/404/422/503 über `_http_error`.
- Dashboard: `NcRadioGroup` "Spielart" aus `listPresets()`, Beschreibung als Hinweiszeile, "Welt erstellen" gesperrt ohne Presets (Fehlerkarte); Tabelle mit Spalte Spielart und `NcChip` (success/warning/tertiary/error/warning); Stoppen + Neustarten bei running/starting, Starten bei stopped/error, alles außer Löschen gesperrt bei unknown; Polling 5 s nur bei sichtbarem Tab, `visibilitychange` löst sofort aus, Abbau in `onUnmounted`; Pollfehler als eigene Warnkarte, Aktionsfehler bleiben bis zur nächsten Aktion; "Erneut prüfen" im Setup-Check aktualisiert jetzt auch die Liste (Phase-1-Befund 01-05).

## Live-Belege

- `tests/e2e/test_status_e2e.py` (3 Tests, 8 s): Welt wird binnen 30 s `running`; `container.stop()` von außen -> `stopped`/"Gestoppt", SQLite `desired_state` bleibt `running`; Start -> `running`; `container.kill()` -> `error`, Text enthält "unerwartet beendet" und "137"; Restart -> 200, wieder `running`, `State.StartedAt` neuer. Zweiter Test: Neustart einer laufenden Welt mit neuem StartedAt; dritter: 404 für unbekannte Welt.
- Playwright headless (Skript `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\ui-check-02-04.cjs`): Kreativ vorausgewählt, "Abenteuer (sanft)" gewählt, Welt "UI Abenteuer" erstellt; Verlauf "Startet gerade" -> "Läuft" nach 4 s; Neustarten: "Läuft" -> "Startet gerade" -> "Läuft", StartedAt 19:29:07.21Z -> 19:29:14.18Z; Stoppen -> "Gestoppt" mit Button "Starten"; Löschen über den Dialog; 0 Konsolenfehler, 0 Seitenfehler.
- Screenshots:
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-04-ui-1-start.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-04-ui-2-laeuft.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-04-ui-3-neustart.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-04-ui-4-gestoppt.png`
  - `C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\02-04-ui-5-geloescht.png`

## Task Commits

1. **Task 1 RED: failing tests** - `257f1bc` (test)
2. **Task 1 GREEN: Status aus Docker, Status-Datei, Lese-Retry, Neustart** - `f4379ea` (feat)
3. **Task 2: Dashboard mit Spielart, Statuschips, Neustart, Polling** - `a2e9374` (feat)

## Decisions Made

- Retry nur für Verbindungsabbrüche (ConnectionError, ProtocolError), nicht für Timeouts: Ein Timeout ist kein Keep-Alive-Rennen, ein zweiter 60-s-Versuch würde nur die Liste verzögern.
- Status-Datei: höchstens 64 KiB Tar-Strom (Platz für PAX-Kopfblöcke), daraus höchstens 4096 Bytes Inhalt; Tar im Strom-Modus, damit ein gekapptes Archiv nicht scheitert.
- Unerwartete Docker-Zustände (paused, dead, removing) ergeben `error` mit Klartext.
- `create_world` liefert den echten abgeleiteten Status (in der Praxis `starting`) statt fest `running`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blockierend] Privacy-Grep-Gate gegen Page-Visibility-API**
- **Found during:** Task 2
- **Issue:** `tests/test_frontend_privacy.py` verbietet den Begriff "visibility" in `frontend/src`; das vom Plan verlangte Polling braucht aber `document.visibilityState` und `'visibilitychange'` (Akzeptanzkriterium).
- **Fix:** Nur genau diese zwei DOM-Bezeichner werden vor der Suche entfernt (`DOM_ALLOWED`), plus Gegenprobe-Test, dass ein Feld `visibility` weiterhin auffällt; der Handler heißt `onTabChange` statt `onVisibility`.
- **Files modified:** tests/test_frontend_privacy.py, frontend/src/App.vue
- **Commit:** `a2e9374`

**2. [Rule 3 - Testinfrastruktur] Fixture `prov` in test_provisioner_errors.py**
- **Issue:** Mit dem Lese-Retry hätte der zweite Versuch nach `_client = None` einen echten Client gegen den Dev-Proxy gebaut (Test `test_connection_error_on_list` wäre gegen den echten Proxy gelaufen).
- **Fix:** Fixture patcht `_docker` auf den Fake; Assertions zu `_client is None` bleiben gültig.
- **Commit:** `257f1bc`

**3. [Rule 2 - Zusatz] "Erneut prüfen" aktualisiert die Liste**
- Offener Phase-1-Befund (01-05) und RESEARCH-Code-Example: `@update:ok` löst jetzt zusätzlich `refresh()` aus.
- **Commit:** `a2e9374`

Zusätzlich: `tests/test_service_unavailable.py` prüft `status`/`status_text` bei totem Proxy; `ruff` ASYNC109 im e2e-Test durch feste Wartezeit-Konstante gelöst.

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 224 passed, keine SKIPPED (nach Task 1); Privacy-Test nach Task 2: 8 passed.
- `ruff check`, `ruff format --check`, `pyright` (latest, 0 Fehler), `vulture`: grün.
- `npm --prefix frontend run build`: Exit 0, `js/gameworld-main.js` 428 kB.
- `scripts/dev/register-exapp.sh`: Backend neu gestartet, ExApp registriert. Erster `smoke.sh`-Lauf direkt danach: Seite 404 (Zeitfenster direkt nach dem Handshake), Sekunden später 200; zweiter `smoke.sh`-Lauf komplett grün ("Durchstich erfolgreich").
- Akzeptanz-greps: Restart-Route 1 Treffer; `derive_status(` 2x in service.py; kein docker-Import in status.py; kein `.restart(` in client.py/service.py; OOM-Text in status.py; `restartWorld|listPresets` 4x in App.vue; kein `v-html`, kein `STATUS_TEXT`; `visibilitychange` vorhanden; keine Gedankenstriche.
- Danach keine Welt-Container übrig, Heartbeat 200.

## Known Stubs

Keine. Die Spielerliste aus `StatusFile.content` wird noch nicht angezeigt; das ist Umfang von 02-05 (Inhalt wird bereits gelesen und gekappt).

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus (T-02-17 bis T-02-22 umgesetzt: Route unter `^/api/.*` ADMIN, ID-Pattern, `_owned`; 4096-Byte-Kappe ohne Follow-Stream; Retry nur für Leseaufrufe mit Test; Polling nur bei sichtbarem Tab; Texte nur per Interpolation).

## Next Phase Readiness

- 02-05 kann Spielerliste (Inhalt der Status-Datei) und RAM anzeigen sowie den 2-s-Cache für `list_managed` ergänzen.
- WELT-01/WELT-02 bleiben bis zum Phasenende offen.

## Self-Check: PASSED

- FOUND: src/gameworld/worlds/status.py, tests/test_status.py, tests/e2e/test_status_e2e.py
- FOUND commits: 257f1bc, f4379ea, a2e9374
