---
phase: 01-fundament
plan: 03
subsystem: provisioner, worlds-api, frontend
tags: [lifecycle, parallel-worlds, ports, instance-guard]
requires: ["01-02"]
provides:
  - "DockerProvisioner._owned(world_id): Label-Filter (managed, eigene instance, world_id) plus Nachprüfung am Ergebnis"
  - "DockerProvisioner.start_world/stop/remove_world/used_host_ports"
  - "WorldService.start_world/stop_world/delete_world mit Port-Kollisions-Saga _launch (max. 3 Startversuche)"
  - "POST /api/worlds/{id}/start, POST /api/worlds/{id}/stop, DELETE /api/worlds/{id} (204), id-Pattern ^[0-9a-f]{12}$"
  - "UI: Starten/Stoppen/Löschen pro Welt, NcDialog-Bestätigung"
  - "smoke.sh: zwei parallele Welten, Stop/Start/Löschen über die API, keine Reste"
affects: [01-04, 01-05]
tech-stack:
  added: []
  patterns: [Mutationen nur über Label-Auflösung pro world_id, Saga mit Neuerzeugung bei Port-Kollision unter erhaltenem Volume, DB-Zeile erst nach erfolgreichem Docker-Aufräumen löschen, ein Service-Lock für alle verändernden Abläufe]
key-files:
  created:
    - tests/test_ports.py
    - tests/test_service_lifecycle.py
    - tests/e2e/test_world_lifecycle_e2e.py
  modified:
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - frontend/src/api.js
    - frontend/src/App.vue
    - scripts/dev/smoke.sh
    - tests/test_provisioner_errors.py
    - tests/test_service_unavailable.py
decisions:
  - "start(container_id) und discard(container_id) entfallen; alle Mutationen laufen über world_id und _owned(), nie über eine ID oder einen Namen von außen"
  - "remove_world ist bei fehlendem Container kein Fehler und entfernt trotzdem das Volume (Name immer mit eigenem Instanz-Präfix), damit Löschen auch Welten mit verschwundenem Container aufräumt"
  - "create_world_container(reuse_volume=True) entfernt bei gescheitertem Einspielen nur den Container, nie das Volume mit den Weltdaten"
  - "Erschöpfte Port-Saga wirft NoFreePortError mit fester Meldung, API antwortet 409 (wie NoFreePortError beim Erzeugen)"
  - "used_host_ports scheitert beim Erzeugen weich (Warnung, nur DB-Ports): der folgende Docker-Aufruf liefert dann die klare 503-Meldung, die fehlgeschlagene Zeile bleibt wie in 01-01"
  - "Ein Lock für Erzeugen, Starten, Stoppen und Löschen; Erzeugen läuft jetzt vollständig unter dem Lock, weil die Saga neu allokieren kann"
metrics:
  duration: "9 min"
  completed: "2026-10-19"
  tasks: 3
  files: 11
---

# Phase 1 Plan 03: Welt-Lebenszyklus und parallele Welten Summary

Admins starten, stoppen und löschen Welten in der Gameworld-Seite, mehrere Welten laufen gleichzeitig mit eigenen UDP-Ports. Jede Mutation löst den Container über die Labels `gameworld.managed=true`, die eigene `gameworld.instance` und die `gameworld.world_id` auf und prüft die Labels am Ergebnis nach. Ein belegter Port beim Start führt zu einer Neuerzeugung mit dem nächsten freien Port unter erhaltenem Volume, höchstens drei Startversuche.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 (RED) | Rote Tests für Lebenszyklus, Parallelität, Port-Kollision, Instanz-Schutz | 1abe091 |
| 2 | Backend: _owned, Port-Saga, Start/Stop/Löschen-API | 0a6c104 |
| 3 | UI-Buttons mit Bestätigungsdialog, smoke.sh mit zwei Welten | 0d9e29a |

## Verifikation

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 92 passed, nichts übersprungen (beide e2e-Dateien gegen den echten Proxy)
- ruff check, ruff format --check, pyright (0 errors, latest), vulture: Exit 0
- `sh scripts/dev/register-exapp.sh && sh scripts/dev/smoke.sh`: Exit 0. Zwei Welten gehärtet auf 30000 und 30001, A gestoppt, B läuft weiter, A wieder gestartet, beide mit 204 gelöscht, keine Container und Volumes übrig
- `tests/test_frontend_privacy.py`: 7 passed
- Browserprüfung (Playwright, headless, Skript im Scratchpad): Welt erstellen, "läuft", Stoppen ("gestoppt", Button wechselt auf "Starten"), Starten ("läuft"), Löschen öffnet den Dialog mit "Welt »…« endgültig löschen?", Abbrechen lässt die Welt stehen, "Endgültig löschen" entfernt die Zeile; keine Seitenfehler
- Nach allen Läufen: `docker ps -a --filter label=gameworld.managed=true` leer, `docker volume ls --filter name=gameworld-` zeigt nur `gameworld-dev_nextcloud` (Volume der Dev-Nextcloud aus Compose, keine Welt)
- grep-Gates: `_owned(` 6 Treffer in client.py (Definition, start_world, stop, remove_world, plus `_is_owned`), Pfad-Pattern in api/worlds.py Zeile 98, `startWorld|stopWorld|deleteWorld` in App.vue 4, "Endgültig löschen" in App.vue vorhanden

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Neuerzeugung hätte bei Fehler das Volume mit den Weltdaten gelöscht**
- **Found during:** Task 2
- **Issue:** `create_world_container` entfernt aus 01-01 bei gescheitertem `put_archive` Container und Volume. In der Port-Saga wird ein Container mit vorhandenem Volume neu erzeugt; ein Fehler beim Einspielen hätte die gebaute Welt vernichtet.
- **Fix:** Schlüsselwortargument `reuse_volume`; ist es gesetzt, wird nur der Container entfernt.
- **Commit:** 0a6c104

**2. [Rule 2 - Kritisch] Löschen einer Welt ohne Container**
- **Issue:** Mit `_owned` als harter Voraussetzung wäre eine Welt mit Status "Container fehlt" nie löschbar gewesen (404), ihr Volume bliebe liegen.
- **Fix:** `remove_world` toleriert einen fehlenden eigenen Container und entfernt trotzdem das Volume mit eigenem Instanz-Präfix. Fremde Container bleiben unberührt (Unit-Test mit drei abweichenden Labels, e2e mit `fremd0000`).
- **Commit:** 0a6c104

**3. [Rule 2 - Kritisch] Nachprüfung filtert statt zu werfen**
- **Issue:** Würde die Nachprüfung beim ersten fremden Container werfen, machte ein ignorierter Proxy-Filter jede eigene Welt unerreichbar.
- **Fix:** `_is_owned` filtert die Trefferliste; ohne eigenen Treffer `WorldNotFoundError`.
- **Commit:** 0a6c104

**4. [Rule 3 - Blocking] Bestehende Fakes an die neue Schnittstelle angepasst**
- **Issue:** `test_provisioner_errors.py` und `test_service_unavailable.py` nutzten `start(container_id)`/`discard`, die entfallen sind.
- **Fix:** Fakes auf `start_world`/`remove_world`/`used_host_ports` umgestellt, Fremd-Container-Test auf drei Label-Varianten erweitert, neuer Test für `used_host_ports` (udp, tcp, Bereichsangabe, None).
- **Commit:** 0a6c104

### Kleinere Abweichungen

- Pfadinjektion: `"../etc"` kommt nie bis zur Route, weil Starlette den Pfad vor dem Routing auflöst; der Test prüft `..%2Fetc` auf 404/405/422 und die Varianten `xyz`, `..etc`, Großbuchstaben, 13 Zeichen auf 422.
- Die e2e-Prüfung des Instanz-Schutzes ruft zusätzlich den Provisioner der Test-Instanz direkt mit der fremden world_id auf, weil die API ohne DB-Zeile schon vor Docker mit 404 antwortet.
- `ports.py` blieb unverändert (Signatur passte); die Zusammenführung von DB-Ports, gebundenen Host-Ports und versuchten Ports liegt in `WorldService._used_ports`/`_launch`.
- smoke.sh räumt im EXIT-Trap jetzt über die Lösch-API auf statt über `docker rm` und die SQLite-Zeile.

## TDD Gate Compliance

- RED: 1abe091 `test(01-03): ...` (29 failed, 5 passed: Port-Tests und Traversal-Test bestanden schon, weil `allocate_port` existierte bzw. Starlette den Pfad nie routet)
- GREEN: 0a6c104 `feat(01-03): ...`
- REFACTOR: nicht nötig

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat Models. T-01-16 (`_owned` plus Nachprüfung, e2e `fremd0000`), T-01-17 (Pattern, 422), T-01-18 (Neuerzeugung mit derselben `world_spec`), T-01-19 (Ports nur aus dem Bereich, Löschen gibt frei), T-01-20 (3 Versuche), T-01-21 (Dialog mit Namen, Zeile erst nach Aufräumen) sind umgesetzt und per Test belegt.

## Self-Check: PASSED

- Dateien vorhanden: tests/test_ports.py, tests/test_service_lifecycle.py, tests/e2e/test_world_lifecycle_e2e.py, alle geänderten Quellen
- Commits vorhanden: 1abe091, 0a6c104, 0d9e29a
