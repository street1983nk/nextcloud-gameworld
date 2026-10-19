---
phase: 02-one-click-welten
plan: 01
subsystem: presets
tags: [presets, schema-migration, kreativ, failed-row]
requires:
  - phase: 02-02
    provides: "vendor/games/SHA256SUMS und fetch-games.sh im Dev-Setup"
provides:
  - "src/gameworld/provisioner/presets.py: Preset-Registry mit MTG_KREATIV, get_preset, validate_preset_id"
  - "Schema 2 mit Spalte preset, Migration aus Schema 1 über Spaltenprüfung"
  - "preset und preset_title in WorldView/WorldOut, GET /api/presets"
  - "Kein failed-Eintrag nach gescheitertem Erzeugen, wenn nichts entstand oder Aufräumen gelang"
affects: [02-03, 02-04, 02-07]
tech-stack:
  added: []
  patterns:
    - "Preset als Soll-Zustand in der DB-Zeile; _payload baut immer aus get_preset(row.preset)"
    - "Migration idempotent über PRAGMA table_info, nicht über die Versionsnummer"
    - "Test-Wrapper um build_world_payload prüft conf-Argumente unabhängig vom Payload-Typ"
key-files:
  created:
    - src/gameworld/provisioner/presets.py
    - tests/test_store.py
  modified:
    - src/gameworld/provisioner/luanti_conf.py
    - src/gameworld/worlds/store.py
    - src/gameworld/worlds/service.py
    - src/gameworld/api/worlds.py
    - tests/test_luanti_conf.py
    - tests/test_api_contract.py
    - tests/test_service_lifecycle.py
    - tests/test_service_unavailable.py
    - scripts/dev/acceptance-phase1.sh
key-decisions:
  - "02-01: Feld preset im POST /api/worlds optional mit Vorgabe mtg_kreativ (sicherstes Preset), hält den Phase-1-Vertrag {name} kompatibel; Abweichung von RESEARCH-Empfehlung Pflichtfeld"
  - "02-01: failed-Zeile wird auch nach ERFOLGREICHEM Aufräumen gelöscht, nicht nur wenn nachweislich nichts entstand (geht über RESEARCH-Empfehlung 5 hinaus); nur bei gescheitertem Aufräumen bleibt sie als failed stehen; Owner sieht das in 02-07 (K2)"
  - "02-01: Ab create_world_container gilt Docker als berührt (ein Volume kann entstanden sein), davor wird ohne Docker-Aufruf gelöscht"
patterns-established:
  - "Neue Presets nur als Konstante in presets.py; parametrisierte Tests über PRESETS.values() prüfen Härtung automatisch"
requirements-completed: []
duration: 25min
completed: 2026-10-19
---

# Phase 02 Plan 01: Preset-Registry, Schema 2 und Kreativ-Preset Ende zu Ende Summary

Jede Welt trägt ihr Preset als Spalte in SQLite (Schema 2, verlustfreie Migration aus Schema 1); das Kreativ-Preset "Bauen (kreativ)" (creative_mode, kein Schaden, default_privs interact, shout, fly, fast) ist Vorgabe im POST /api/worlds und landet nachweislich in der minetest.conf des laufenden Containers; gescheiterte Anlagen hinterlassen keine Port-belegenden failed-Zeilen mehr.

## Performance

- Duration: ca. 25 min
- Completed: 2026-10-19
- Tasks: 2
- Files: 11 (2 neu, 9 geändert)

## Tasks

| Task | Name | Commits | Files |
|------|------|---------|-------|
| 1 | Preset-Registry, preset-abhängige conf/world.mt, Schema-2-Migration | bdee8e8 (RED), 9874814 (GREEN) | presets.py, luanti_conf.py, store.py, service.py (_payload), test_luanti_conf.py, test_store.py |
| 2 | Preset durch Service und API, GET /api/presets, failed-Zeilen-Regel | 31829e1 (RED), 8d4a35c (GREEN) | service.py, api/worlds.py, test_api_contract.py, test_service_lifecycle.py, test_service_unavailable.py, acceptance-phase1.sh |

## Verifikation

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 139 passed, keine SKIPPED-Zeile
- ruff check, ruff format --check, pyright (latest, 0 Fehler), vulture: grün
- `sh scripts/dev/register-exapp.sh`: Backend mit neuem Code neu gestartet, ExApp registriert
- `sh scripts/dev/acceptance-phase1.sh`: 80 von 80 Prüfungen bestanden; K5-GHOST jetzt leer (die failed-Zeile nach dem POST bei gestopptem Proxy verschwindet live)
- Live-Gegenprobe "Preset Probe": Antwort preset mtg_kreativ / preset_title "Bauen (kreativ)", per docker cp gelesene conf enthält `creative_mode = true`, `enable_damage = false`, `default_privs = interact, shout, fly, fast`; GET /api/presets liefert nur id/title/description; unbekanntes Preset 422; Probewelt per DELETE 204 entfernt, kein Container übrig
- Live-Migration: Dev-Datenbank .dev/storage/gameworld.sqlite3 steht nach Neustart auf schema_version 2 mit Spalte preset

## Decisions Made

- **preset optional mit Vorgabe mtg_kreativ** (Claude's Discretion laut Plan): Das bestehende Dashboard und alle Skripte erzeugen ohne Änderung Kreativwelten; das Dashboard wählt ab 02-04 sichtbar vor.
- **failed-Zeile auch nach erfolgreichem Aufräumen löschen:** Bewusste Entscheidung über RESEARCH-Empfehlung 5 hinaus. Die Empfehlung sah das Löschen nur vor, wenn nachweislich nichts in Docker entstanden ist. Umgesetzt ist: Zeile weg, wenn (a) der Fehler schon bei ensure_image auftrat (ohne Docker-Aufruf) oder (b) remove_world(keep_volume=False) nach dem Fehler gelingt. Nur wenn das Aufräumen selbst scheitert, bleibt die Zeile als op_state failed mit der ursprünglichen Meldung, damit Löschen später Container und Volume entfernt. Der Owner sieht dieses Verhalten in der Phasenabnahme 02-07 (K2).
- **Grenze "Docker berührt":** ab dem Aufruf create_world_container (nicht erst nach Erfolg), weil ein gescheitertes create ein Volume hinterlassen kann; dann wird immer aufgeräumt.

## Deviations from Plan

None - plan executed exactly as written. Ergänzungen im Rahmen des Plans:
- CreateWorldRequest.preset zusätzlich mit `Field(max_length=64)` begrenzt (wie name), damit kein beliebig langer Rohwert den Validator erreicht.
- Saga-Test nutzt ein per monkeypatch registriertes Marker-Preset (creative_mode = false) und setzt row.preset darauf; so ist belegt, dass die Neuerzeugung aus row.preset baut und nicht aus der Vorgabe. Dieser Test war im RED-Commit bereits grün, weil Task 1 _payload schon umgestellt hatte.

## TDD Gate Compliance

- Task 1: test(02-01) bdee8e8 vor feat(02-01) 9874814
- Task 2: test(02-01) 31829e1 vor feat(02-01) 8d4a35c

## Issues Encountered

None.

## Known Stubs

None.

## Next Phase Readiness

- 02-03 kann Presets mit eigenem Spiel (VoxeLibre) ergänzen: Preset-Felder game_zip, game_sha256, game_dir und mem_limit stehen bereit, werden aber von build_world_payload und der Container-Spec noch nicht ausgewertet (bewusst, Spielwahl folgt in 02-03).
- WELT-01 bleibt in REQUIREMENTS.md offen bis zum Phasenende.

## Self-Check: PASSED

- FOUND: src/gameworld/provisioner/presets.py, tests/test_store.py
- FOUND: bdee8e8, 9874814, 31829e1, 8d4a35c
