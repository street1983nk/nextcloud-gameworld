---
phase: 02-one-click-welten
plan: 06
subsystem: reconciler
tags: [reconciler, reboot, exapp-update, lifespan, label-reconciliation]
requires:
  - phase: 02-05
    provides: desired_state in der DB, derive_status, Lese-Retry, Listen-Cache mit _invalidate_cache, _LOCK, _launch mit Neuerzeugung aus dem Volume
provides:
  - worlds/reconciler.py mit ReconcileAction (8 Werte), decide_boot, decide_periodic, needs_volume_check, reconcile_forever
  - WorldService.boot_reconcile() -> bool und periodic_reconcile() (nicht blockierender _LOCK)
  - DockerProvisioner.volume_exists(world_id)
  - Lifespan startet reconcile_forever als asyncio-Task und bricht ihn beim Herunterfahren ab
  - Dev-Proxy mit restart unless-stopped
affects: [02-07]
tech-stack:
  added: []
  patterns:
    - Reine Entscheidungsfunktionen plus Ausführung im Dienst; periodisch nie START oder RECREATE
    - DockerUnavailableError bricht den ganzen Boot-Abgleich ab (Wiederholung in 5 s), andere ProvisionerError bleiben an der einzelnen Welt
    - to_thread mit abandon_on_cancel für Abgleich-Aufrufe, damit das Herunterfahren nie auf Docker wartet
key-files:
  created:
    - src/gameworld/worlds/reconciler.py
    - tests/test_reconciler.py
    - tests/e2e/test_reconcile_e2e.py
  modified:
    - src/gameworld/worlds/service.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/main.py
    - scripts/dev/compose.yaml
key-decisions:
  - "02-06: Welten mit op_state failed fasst der Abgleich nie an (auch nicht beim Boot); Starten oder Löschen bleibt Elternklick. Verhindert, dass eine unterbrochene Anlage beim nächsten Boot gestartet wird"
  - "02-06: DockerUnavailableError während des Boot-Abgleichs markiert keine Welt als failed, sondern bricht den Zyklus ab; reconcile_forever wiederholt nach 5 s"
  - "02-06: Abgleich-Aufrufe über anyio.to_thread mit abandon_on_cancel=True; der Thread gibt _LOCK im finally frei"
  - "02-06: Verwaiste eigene Container nur beim Boot gemeldet (sonst Log alle 30 s)"
requirements-completed: []
duration: 25min
completed: 2026-10-19
---

# Phase 2 Plan 06: Reconciler für Reboot und ExApp-Update Summary

**Ein Lifespan-Task gleicht beim Start Soll-Zustand (SQLite) und per Label gefundene Container ab, startet nach einem Reboot exited Welten mit Soll "läuft" wieder (gleiche Container-ID), erzeugt fehlende Container aus dem Volume neu und pflegt danach alle 30 s nur Zustände, ohne je periodisch neu zu starten.**

## Performance

- **Duration:** ca. 25 min
- **Tasks:** 2 von 2
- **Files modified:** 7 (3 neu)

## Accomplishments

- `reconciler.py`: `ReconcileAction` (NONE, START, RECREATE, MARK_OOM, ADOPT_RUNNING, MARK_INTERRUPTED, RETRY_DELETE, MARK_DATA_MISSING), `decide_boot`, `decide_periodic` (nur ADOPT_RUNNING oder NONE), `needs_volume_check`, `reconcile_forever` (5 s bis der Boot-Abgleich gelingt, danach 30 s; jeder Fehler geloggt, nur CancelledError beendet). Kopfkommentar mit Regeltabelle und Begründung gegen periodische Neustarts.
- `service.py`: `boot_reconcile`/`periodic_reconcile` über `_LOCK.acquire(blocking=False)`; START und RECREATE über `_launch(row)` (Neuerzeugungspfad mit `row.preset`), danach op_state ready; Meldungstexte `RECONCILE_OOM`, `RECONCILE_DATA_MISSING`, `RECONCILE_INTERRUPTED`; RETRY_DELETE entfernt Container und Volume, dann die Zeile; verwaiste Container nur `LOG.warning("verwaiste Welt-Container: N ...")`; jede Aktion mit Welt-ID geloggt (T-02-32); Cache danach verworfen.
- `client.py`: `volume_exists(world_id)` über `_read`, Name aus `resource_name` (eigenes Instanz-Präfix).
- `main.py`: `asyncio.create_task(reconcile_forever(service))` nur nach erfolgreichem `get_service`, `cancel` plus `suppress(CancelledError)` im finally.
- `scripts/dev/compose.yaml`: Proxy mit `restart: unless-stopped` (live: `docker inspect` liefert unless-stopped).

## Live-Belege (tests/e2e/test_reconcile_e2e.py, 4 passed in 30,7 s)

- (a) Reboot-Simulation: A von außen gestoppt, neuer WorldService, `boot_reconcile` -> A binnen 30 s "running" mit derselben Container-ID, B bleibt exited/"stopped".
- (b) Update-Simulation: neuer Dienst auf derselben DB liefert dieselben IDs, Presets und Status; Container-IDs unverändert.
- (c) `remove(force=True, v=False)` von außen: Boot erzeugt einen neuen Container, Label `gameworld.preset` und Volume-Name unverändert.
- (d) `kill()` (137, kein OOM): zwei `periodic_reconcile` starten nichts, Status error "unerwartet beendet"; Boot eines neuen Dienstes startet denselben Container.

## Task Commits

1. **Task 1 RED: failing tests** - `3c909ac` (test)
2. **Task 1 GREEN: Abgleich im Dienst und Lifespan-Task** - `2f6e471` (feat)
3. **Task 2: Live-Reboot- und Update-Simulation, Dev-Proxy unless-stopped** - `aa927a4` (test)

## Decisions Made

- op_state failed bleibt unangetastet: Sonst würde eine per MARK_INTERRUPTED markierte, halb erzeugte Welt beim nächsten Boot gestartet. Der Plan nannte failed nicht ausdrücklich; die Tabelle hat dafür eigene Zeilen (`failed-exited`, `failed-missing` -> NONE).
- Volume-Abfrage nur, wenn sie die Entscheidung trägt (Container fehlt, Soll running, nicht creating/failed); strenger als "nur für Zeilen ohne Container".

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Proxy-Ausfall mitten im Boot hätte Welten als failed markiert**
- **Found during:** Task 1
- **Issue:** Wörtlich umgesetzt ("ProvisionerError per _fail an der Welt") hätte ein DockerUnavailableError jede noch abzugleichende Welt dauerhaft als failed markiert, und der Boot-Abgleich hätte trotzdem True geliefert, also nie wiederholt.
- **Fix:** DockerUnavailableError bricht den Zyklus ab (reconcile_forever wiederholt in 5 s); nur andere ProvisionerError landen per `_fail` an der Welt. Test `test_boot_aborts_when_docker_disappears`.
- **Commit:** `2f6e471`

**2. [Rule 2 - Kritisch] Herunterfahren darf nicht auf Docker warten**
- **Found during:** Task 1 (Lifespan-Test mit unerreichbarem Proxy)
- **Issue:** `anyio.to_thread.run_sync` wartet beim Abbruch standardmäßig auf den Thread; ein Verbindungsversuch gegen einen toten Proxy (Windows: Sekunden, Client-Timeout bis 60 s) hätte das Beenden der ExApp blockiert.
- **Fix:** `abandon_on_cancel=True` für beide Abgleich-Aufrufe; `_LOCK` wird im finally des Threads freigegeben. Lifespan-Test unter 2 s grün.
- **Commit:** `2f6e471`

**3. [Rule 3 - Lint] ASYNC109 im Live-Test**
- Wartehelfer-Parameter `within` statt `timeout`, statt die Regel abzuschalten.
- **Commit:** `aa927a4`

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 335 passed, keine SKIPPED.
- `ruff check`, `ruff format --check`, `pyright` (latest, 0 Fehler), `vulture`: grün.
- Akzeptanz-greps: `create_task(reconcile_forever` 1 Zeile in main.py; `acquire(blocking=False)` 2 Zeilen in service.py; `unless-stopped`/`"always"` in src/gameworld kein Treffer; `def decide_periodic` 1 Zeile; `boot_reconcile` 3 Vorkommen im Live-Test; keine Gedankenstriche.
- Nach dem Lauf keine Welt-Container (`docker ps -a --filter label=gameworld.managed=true -q` leer); Proxy `unless-stopped`, läuft.
- Dev-ExApp per `register-exapp.sh` mit neuem Code neu gestartet ("Application startup complete"), `smoke.sh`: "Durchstich erfolgreich".

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus: T-02-27 (nur list_managed/_owned, Waisen nur gemeldet, Unit-Test), T-02-28 (decide_periodic nie START/RECREATE, Tabellentest plus Live-Test d), T-02-29 (Task plus abandon_on_cancel, Lifespan-Test), T-02-30 (acquire(blocking=False), Unit-Test), T-02-31 (volume_exists vor RECREATE, MARK_DATA_MISSING), T-02-32 (Log pro Aktion mit Welt-ID, ohne Weltschlüssel).

## Next Phase Readiness

- PLATT-02 technisch umgesetzt (Abhaken erst am Phasenende). Ein echter Docker-Desktop-Neustart wurde bewusst nicht ausgeführt (Findling-Stacks); Kandidat für die Owner-Abnahme in 02-07, falls gewünscht.
- Logger der gameworld-Module sind im Dev-Prozess nicht auf INFO konfiguriert; Reconciler-Logs erscheinen dort nur ab WARNING.

## Self-Check: PASSED

- FOUND: src/gameworld/worlds/reconciler.py, tests/test_reconciler.py, tests/e2e/test_reconcile_e2e.py, .planning/phases/02-one-click-welten/02-06-SUMMARY.md
- FOUND commits: 3c909ac, 2f6e471, aa927a4
