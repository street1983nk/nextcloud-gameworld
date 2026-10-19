---
phase: 01-fundament
plan: 04
subsystem: provisioner, setup-check-api, frontend, docs
tags: [setup-check, docker-proxy, install-docs, security]
requires: ["01-03"]
provides:
  - "run_setup_check(docker_url, timeout=3.0) -> SetupCheckResult(ok, items[CheckItem(id, ok, severity, message)]) mit den 8 Probes aus RESEARCH Pattern 5"
  - "GET /api/setup-check, immer HTTP 200 (auch bei ungültiger Umgebung: item 'config')"
  - "SetupCheck.vue: Fehler- und Warnkarten, 'Erneut prüfen', emittiert update:ok; 'Welt erstellen' gesperrt bis ok"
  - "docs/install.md: gepinntes Proxy-Snippet ohne ports:, Env-Variablen, UDP LAN-only, Restrisiko, Meldungstabelle"
affects: [01-05]
tech-stack:
  added: []
  patterns: [Probes nur gegen gameworld-probe-nonexistent, Folgefehler-Unterdrückung bei fehlendem POST (Probes gar nicht senden, Warnung 'Nicht geprüft'), ok hängt nur an error-items, requests nur im provisioner-Paket]
key-files:
  created:
    - src/gameworld/provisioner/setup_check.py
    - src/gameworld/api/setup_check.py
    - frontend/src/components/SetupCheck.vue
    - docs/install.md
    - tests/test_setup_check.py
    - tests/e2e/test_setup_check_e2e.py
  modified:
    - src/gameworld/main.py
    - frontend/src/api.js
    - frontend/src/App.vue
decisions:
  - "Ok-items tragen die Severity, die ein Fehlschlag hätte (reachable..volumes error, exec/info warning); ok hängt nur an fehlgeschlagenen error-items"
  - "Unerwarteter Statuscode und Transportfehler nach erfolgreichem _ping ergeben ein error-item mit Methode, Pfad und Code; ein Nicht-200 auf _ping zählt als 'nicht erreichbar' und bricht ab"
  - "API-Versionsvergleich als Int-Tupel (1.100 > 1.44); fehlende oder unlesbare ApiVersion gilt als zu alt"
  - "requests.Session mit trust_env=False, damit HTTP(S)_PROXY-Variablen die Probes nicht umleiten"
  - "'Welt erstellen' startet gesperrt und wird erst nach bestandenem Setup-Check frei; die Weltenliste lädt unabhängig davon"
metrics:
  duration: "12 min"
  completed: "2026-10-19"
  tasks: 2
  files: 9
---

# Phase 01 Plan 04: Setup-Check und Installationsdoku Summary

Nebenwirkungsfreier Setup-Check mit acht Probes gegen den tecnativa-Proxy (deutsche, handlungsfähige Meldungen, genau ein Fehler bei fehlendem POST), UI-Karten mit gesperrtem "Welt erstellen" und docs/install.md mit digest-gepinntem, portlosem Proxy-Snippet und ehrlichem Restrisiko.

## Erledigt

| Task | Name | Commit |
|------|------|--------|
| 1 (RED) | Failing tests Setup-Check | 33a40bd |
| 1 (GREEN) | Setup-Check-Modul und GET /api/setup-check | 6b49b3d |
| 2 | SetupCheck.vue, App.vue-Sperre, docs/install.md | e3ad0d3 |

## Verifikation

- Dev-Proxy vorab live gemessen: alle 8 Statuscodes wie in RESEARCH Pattern 5 (ApiVersion 1.54).
- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 109 passed; ruff check, ruff format --check, pyright (latest), vulture: grün.
- Fake-Server-Tests: alle Szenarien des Plans; Fixture prüft nach jedem Test, dass POST/DELETE nur Pfade mit `gameworld-probe-nonexistent` trafen; POST-fehlt-Test prüft, dass kein DELETE und kein /exec gesendet wurde.
- Frontend-Build, Privacy-Test, register-exapp.sh, smoke.sh grün; `/api/setup-check` über den Nextcloud-Proxy liefert `"ok":true`.
- Akzeptanz-Greps: Digest 1x, `EXEC: 0` vorhanden, kein `ports:`, root- und UPnP-Passage vorhanden, keine Em-/En-Dashes, `setup-check` in api.js, `gameworld-probe-nonexistent` 4x im Modul, kein requests/docker-Import außerhalb provisioner/.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Robustheit] Ungültige Umgebung als Befund statt 500**
- **Found during:** Task 1
- **Issue:** `load_settings()` wirft bei ungültigem `GAMEWORLD_PORT_RANGE` ValueError; die Route hätte dann 500 geliefert, obwohl sie "immer 200" sein soll.
- **Fix:** Route fängt ValueError und liefert `ok: false` mit item `config` (Meldung aus config.py).
- **Files modified:** src/gameworld/api/setup_check.py
- **Commit:** 6b49b3d

**2. [Rule 3 - Akzeptanz] Probe-Pfade als Literale**
- **Found during:** Task 1
- **Issue:** Mit Konstante plus f-String ergab `grep -c gameworld-probe-nonexistent` nur 2 (gefordert >= 3).
- **Fix:** Pfade als feste Literale, Konstante entfernt. Keine Verhaltensänderung.
- **Commit:** 6b49b3d

## Known Stubs

Keine.

## Hinweise für 01-05

- Gegenprobe mit gestopptem Proxy (UI-Karte "Gameworld ist noch nicht startklar", Button gesperrt) steht gesammelt in 01-05 an; visuell noch nicht im Browser abgenommen.

## Self-Check: PASSED

- Dateien vorhanden: src/gameworld/provisioner/setup_check.py, src/gameworld/api/setup_check.py, frontend/src/components/SetupCheck.vue, docs/install.md, tests/test_setup_check.py, tests/e2e/test_setup_check_e2e.py
- Commits vorhanden: 33a40bd, 6b49b3d, e3ad0d3
