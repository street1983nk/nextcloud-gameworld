---
phase: 06-store-release
plan: 08
subsystem: lifecycle
tags: [lifecycle, uninstall, orphans, d-15, d-17, security]
requires: ["06-02"]
provides:
  - "WorldService.teardown_all() -> int und async teardown(): alle eigenen Welt-Container stoppen (5 s) und entfernen, keep_volume=True, parallel (8 Worker), Gesamtfrist 45 s, Soll-Zustand bleibt"
  - "enabled_handler: dritter isolierter Block, enabled=0 -> teardown unter anyio.fail_after(50), enabled=1 -> Boot-Abgleich als Hintergrund-Task; immer \"\""
  - "DockerProvisioner.stop(world_id, *, timeout=STOP_TIMEOUT)"
  - "DockerProvisioner.list_orphans(owned_volumes) -> Orphans, remove_orphan_container(id), remove_orphan_volume(name, owned_volumes); OrphanRefusedError, OrphanInUseError"
  - "GET /api/admin/orphans, POST /api/admin/orphans/container/remove, POST /api/admin/orphans/volume/remove (require_nc_admin)"
  - "scripts/gameworld-orphans.sh (Host-Kommando, Standard nur Auflisten)"
affects: [06-09, 06-12]
tech-stack:
  added: []
  patterns:
    - "Aufräumen unter Frist: ThreadPoolExecutor + concurrent.futures.wait(timeout), shutdown(wait=False, cancel_futures=True)"
    - "Sperre mit acquire(timeout) und Weiterlaufen ohne Sperre, wenn der Prozess ohnehin endet"
    - "Orphan-Entfernen nur am frisch geholten Objekt geprüft (Label managed, fremde Instanz, ID-Präfix), Volume-Namen per Regex vor jedem Docker-Aufruf"
    - "Skript-Test mit protokollierender docker-Attrappe und PATH ohne echtes docker (Probe vor jedem Test)"
key_files:
  created:
    - scripts/gameworld-orphans.sh
    - tests/test_orphans.py
    - tests/test_orphans_script.py
  modified:
    - src/gameworld/worlds/service.py
    - src/gameworld/lifecycle.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/api/admin.py
    - tests/test_lifecycle.py
    - tests/test_service_lifecycle.py
    - tests/test_talk_bot.py
    - tests/test_route_guards.py
decisions:
  - "teardown_all zählt eine Welt als Fehler, sobald Stoppen oder Entfernen scheitert; nach gescheitertem Stopp wird trotzdem mit force entfernt"
  - "Nur nicht gestoppte Container (Status nicht created/exited/dead) werden vor dem Entfernen gestoppt"
  - "Scheitert schon das Menü-Abmelden, meldet der Handler wie bisher einen Fehlertext und räumt keine Welten ab (Bestandsverhalten unverändert)"
  - "Fehlender Container bzw. fehlendes Volume beim Orphan-Entfernen ist kein Fehler (idempotent, 200 mit neuer Liste)"
  - "Eigene Volumes = resource_name(instance, row.id) vereinigt mit dem gespeicherten row.volume_name aller Weltzeilen"
  - "Sonstige Docker-Ablehnung beim Orphan-Entfernen -> 502 mit festem Text (Plan nannte nur 409/503)"
  - "Host-Skript warnt, wenn der ExApp-Container nc_app_gameworld noch existiert (dann stehen eigene Welten mit in der Liste)"
metrics:
  duration: "ca. 55 min"
  completed: 2026-10-24
  tasks: 3
  files: 11
---

# Phase 6 Plan 08: Deaktivieren räumt auf, Orphan-API und Host-Skript Summary

Jedes Deaktivieren (auch vor Update und Deinstallation) stoppt und entfernt alle eigenen Welt-Container parallel unter 45 s Frist, Volumes und Soll-Zustand bleiben, Aktivieren stößt den Boot-Abgleich an, der jede Soll-laufende Welt per RECREATE neu baut; Reste fremder Installationen listet und entfernt ein NC-Admin über /api/admin/orphans, nach der Deinstallation hilft scripts/gameworld-orphans.sh.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | teardown_all beim Deaktivieren, Neuaufbau beim Aktivieren | 205c3f7 |
| 2 | Orphan-Suche und gezieltes Entfernen (Provisioner und Admin-API) | 289cf23 |
| 3 | Host-Skript scripts/gameworld-orphans.sh | 23c96c7 |

## Was gebaut wurde

- `WorldService.teardown_all`: `_LOCK.acquire(timeout=10)`, bei Misserfolg Warnung und Weiterlaufen; `list_managed()` (nur eigene Instanz); je Welt im Pool `stop(timeout=5)` (nur laufende) und `remove_world(keep_volume=True)`; `wait(timeout=45)`, hängende Welten zählen als Fehler; Log nur Welt-ID und Typname; finally Sperre frei und `_invalidate_cache()`. Weltzeilen und desired_state unverändert.
- `lifecycle.enabled_handler`: nach Menü- und Talk-Block ein dritter try-Block. enabled=0: `anyio.fail_after(50)` um `get_service().teardown()`; enabled=1: Boot-Abgleich als Task mit starker Referenz (`_BACKGROUND`), Ausnahmen nur als Typname. Kommentar zu D-17 Option A, F-02 und der bewusst akzeptierten kurzen Trennung beim Update.
- `DockerProvisioner`: `list_orphans` über `_read` (Label-Filter plus zweite Prüfung `_is_foreign` am Ergebnis, Volume-Filter plus `ORPHAN_VOLUME_PATTERN`), `remove_orphan_container` (ID-Regex `^[0-9a-f]{12,64}$`, frisch geholt, ID-Präfix und Label geprüft, `remove(force=True, v=False)`), `remove_orphan_volume` (Regex und Eigen-Ausschluss vor Docker, 409 -> `OrphanInUseError`).
- `api/admin.py`: drei Routen im bestehenden `require_nc_admin`-Router, Pydantic mit `extra="forbid"`, Docker per `anyio.to_thread.run_sync`, eigene Volumes je Aufruf frisch aus der DB.
- `scripts/gameworld-orphans.sh`: POSIX sh, `set -eu`, Kopfkommentar, englische Ausgaben, Modus 100755.

## Für 06-09

Alle Routen nur für NC-Admins (Gruppe admin), sonst 403; Antworten der drei Routen haben dieselbe Form:

```
GET  /api/admin/orphans
POST /api/admin/orphans/container/remove   Body {"id": "<12 bis 64 Hex-Zeichen>"}
POST /api/admin/orphans/volume/remove      Body {"name": "gameworld-<a-z0-9->"} (max 128)

200 {
  "containers": [{"id", "name", "instance", "state", "created"}],   // nach name sortiert
  "volumes":    [{"name", "created"}]                               // nach name sortiert
}
```

- `state` ist der Docker-Status (running, exited, ...), `created` der Docker-Zeitstempel als String (kann leer sein), `instance` die Instanz-ID der fremden Installation.
- Fehler (Feld `detail`, feste deutsche Texte):
  - 409 "Das gehört zu dieser Installation oder nicht zu Gameworld." (eigene Welt, ohne Label, fremdes Schema)
  - 409 "Der Spielstand wird noch von einem Container benutzt." (Volume in Benutzung: erst den Container entfernen)
  - 503 "Gameworld erreicht Docker gerade nicht. Bitte später erneut versuchen."
  - 502 "Docker hat das Entfernen abgelehnt. Details stehen im Log der ExApp."
  - 422 bei ungültigem Body (falsches Format, unbekanntes Feld)
- Bereits verschwundene Objekte: 200 mit neuer Liste (kein Fehler).
- Hinweis für die Oberfläche: Volume-Löschen vernichtet Spielstände endgültig; eine Bestätigung mit Tippen (wie im Skript "delete") ist angemessen.

## Verifikation

- Gates vor jedem Commit: `ruff check`, `ruff format --check`, `pyright` (latest, 0 Fehler), `vulture`, `sh -n scripts/gameworld-orphans.sh`: ohne Befund.
- `uv run pytest -m "not docker" -q`: 2486 passed, 44 deselected.
- Gezielte Suiten: test_lifecycle 14, test_service_lifecycle (teardown) 7, test_orphans plus test_route_guards 88, test_orphans_script 18 grün.
- Unabhängige Live-Gegenprobe (roher docker CLI, nur Wegwerf-Objekte, Instanz f00dcafe/deadbeef über den Dev-Proxy): teardown_all entfernte den eigenen Wegwerf-Container, das Volume blieb (docker volume ls), desired_state blieb running; Ablehnung für unbeschrifteten Container, Volume `gameworld-zz_devstack` und eigenes Volume; fremdes Volume in Benutzung -> OrphanInUseError; danach fremder Container und Volume entfernt. `docker ps -a` und `docker volume ls` vorher/nachher identisch, Owner-Welten gameworld-788fff30-* und Dev-Stack unberührt und laufend, alle Wegwerf-Reste entfernt.
- Host-Skript lesend gegen den echten Docker: listet nur die 788fff30- und a60510fd-Objekte, nie gameworld-dev-* oder gameworld-dev_nextcloud.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Sicherheit] Lifecycle-Tests und Talk-Bot-Tests nie gegen den echten Dienst**
- **Found during:** Task 1
- **Issue:** `enabled_handler` holt jetzt `get_service()`; die Bestandstests in tests/test_talk_bot.py riefen den Handler ohne Attrappe und hätten einen echten DockerProvisioner gegen den Dev-Proxy gebaut.
- **Fix:** autouse-Fixture mit FakeWorlds in tests/test_lifecycle.py und tests/test_talk_bot.py (nicht im Plan gelistet).
- **Commit:** 205c3f7

**2. [Rule 3 - Blockierend] DockerProvisioner.stop mit Timeout-Parameter**
- **Found during:** Task 1
- **Issue:** Der Plan verlangt 5 s Stopp-Timeout, `stop` hatte fest 30 s.
- **Fix:** keyword-only `timeout` mit Vorgabe STOP_TIMEOUT (client.py schon in Task 1 geändert).
- **Commit:** 205c3f7

**3. [Rule 3 - Blockierend] Strukturtest auf 7 Admin-Routen**
- **Found during:** Task 2
- **Issue:** tests/test_route_guards.py zählte fest 4 Admin-Routen.
- **Fix:** Zählung auf 7, die drei Orphan-Pfade in die Mindestmenge.
- **Commit:** 289cf23

**4. [Rule 2 - Korrektheit] Ergänzungen über den Plan hinaus**
- 502 mit festem Text für sonstige Docker-Ablehnungen beim Entfernen; Container-ID-Präfix-Prüfung am frisch geholten Objekt; eigene Volumes zusätzlich über row.volume_name; Warnung im Skript bei noch vorhandenem nc_app_gameworld.
- **Commits:** 289cf23, 23c96c7

## TDD Gate Compliance

Tests und Umsetzung je Task in einem gemeinsamen feat-Commit (keine getrennten test-Commits). Die Negativtests wurden mit filterignorierender Docker-Attrappe bzw. rohem docker CLI als unabhängige Gegenprobe geprüft.

## Known Stubs

Keine.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: docker-mutation | src/gameworld/provisioner/client.py | Neue Mutationen auf Objekte FREMDER Instanzen (Container rm -f, volume rm) über den Proxy; abgesichert durch Label-, ID- und Regex-Prüfung am frisch geholten Objekt, nur NC-Admin (T-06-35, T-06-37) |
| threat_flag: lifecycle-mutation | src/gameworld/lifecycle.py | /enabled mit 0 entfernt jetzt alle eigenen Welt-Container (Daten bleiben); wer /enabled aufrufen kann, kann Welten trennen. Der Aufruf ist AppAPI-signiert wie bisher |
| threat_flag: host-script | scripts/gameworld-orphans.sh | Läuft mit vollen Docker-Rechten auf dem Host; Standard nur lesend, Volume-Löschen nur nach getipptem delete (T-06-36) |

## Self-Check: PASSED

- FOUND: scripts/gameworld-orphans.sh (100755), tests/test_orphans.py, tests/test_orphans_script.py
- FOUND: 205c3f7, 289cf23, 23c96c7
