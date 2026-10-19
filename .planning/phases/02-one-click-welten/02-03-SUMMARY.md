---
phase: 02-one-click-welten
plan: 03
subsystem: provisioner
tags: [voxelibre, presets, payload, status-mod, mem-limit]
requires:
  - phase: 02-01
    provides: Preset-Registry, preset in DB-Zeile und API, render_minetest_conf/render_world_mt pro Preset
  - phase: 02-02
    provides: VoxeLibre-Zip per scripts/fetch-games.sh, SHA256SUMS
provides:
  - Preset VOXELIBRE_SANFT ("Abenteuer (sanft)", mineclone2, 1 GiB)
  - Welt-Mod gameworld_status in jeder neuen Welt (status_mod.py, PLAYERS_FILE)
  - WorldPayload(preset, archive) als Vertrag zwischen Service, Archive und Client
  - Container-Labels gameworld.schema "2" und gameworld.preset
affects: [02-04, 02-05, 02-07]
tech-stack:
  added: []
  patterns:
    - Spiel-Zip pro Preset hash-geprüft (hashlib.file_digest), Einträge einzeln ins Tar gestreamt
    - Tar in SpooledTemporaryFile (8 MiB), Service schließt es per contextmanager im finally
    - Spec und Payload aus derselben WorldPayload, Neuerzeugung behält Spiel und Limit
key-files:
  created:
    - src/gameworld/provisioner/status_mod.py
    - tests/e2e/test_presets_e2e.py
  modified:
    - src/gameworld/provisioner/presets.py
    - src/gameworld/provisioner/spec.py
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - tests/test_spec.py
    - tests/test_archive.py
    - tests/test_provisioner_errors.py
    - tests/test_luanti_conf.py
    - tests/test_api_contract.py
    - tests/test_service_lifecycle.py
    - vendor/games/README.md
key-decisions:
  - "02-03: put_archive nimmt das Tar als Datei-Objekt (SpooledTemporaryFile) durch den Proxy an (Assumption A5 live bestätigt), kein bytes-Fallback nötig"
  - "02-03: Label gameworld.schema 2 = Preset gesetzt und Welt-Mod vorhanden; 02-04 wertet Bereitschaft nur ab Schema 2 aus"
  - "02-03: WorldPayload lebt in spec.py (Importzyklus client.py/archive.py)"
requirements-completed: []
duration: 10min
completed: 2026-10-19
---

# Phase 2 Plan 03: VoxeLibre-Preset, Status-Mod und gestreamter Payload Summary

**Zweites Preset "Abenteuer (sanft)" mit VoxeLibre (mineclone2, 1 GiB ohne Swap, Sanft-Schalter) läuft Ende zu Ende über die API; jede neue Welt bringt den Welt-Mod gameworld_status mit, der die Spielerliste auch unter Mod-Security schreibt.**

## Performance

- **Duration:** ca. 10 min (21:03 bis 21:13)
- **Tasks:** 2 von 2
- **Files modified:** 14 (2 neu)

## Accomplishments

- `VOXELIBRE_SANFT` in der Registry (nach `MTG_KREATIV`): gameid `mineclone2`, `mem_limit` 1g, `default_privs = interact, shout`, neun Sanft-Schalter (friedliche Mobs, Inventar behalten, kein Feuer, keine Explosionsschäden, keine Befehlsblöcke); Hunger bleibt an (A8, Owner bestätigt in 02-07).
- `status_mod.py`: Lua-Quelltext aus RESEARCH Pattern 2 (`core.safe_file_write`, `core.after(0)` in Join/Leave/ModsLoaded), `mod.conf`, `PLAYERS_FILE`. Schreibt nur Spielernamen.
- `world_spec(..., preset)`: Speicher und Swap aus dem Preset, Labels `gameworld.schema = "2"` und `gameworld.preset`; übrige Härtung unverändert.
- `build_world_payload(preset, conf, world_mt) -> WorldPayload`: Zip per `hashlib.file_digest` gegen `preset.game_sha256` geprüft, fehlend mit Hinweis auf `scripts/fetch-games.sh`, Einträge einzeln gestreamt (`_safe_relative` bleibt Pflicht), Tar in `SpooledTemporaryFile(8 MiB)`, `worldmods/gameworld_status` mit uid 30000 / 0644, nie `gameworld_players.txt`.
- `create_world_container` baut die Spec aus `payload.preset` und reicht `payload.archive` an `put_archive`; `service._payload` ist ein contextmanager, der das Tar im finally schließt (Erzeugen und beide Neuerzeugungspfade in `_launch`).
- Live-Nachweis (`tests/e2e/test_presets_e2e.py`, 3 Tests, seriell): VoxeLibre mit 1073741824 Byte Memory/MemorySwap, Sanft-Zeilen, `gameid = mineclone2`, Status-Datei, kein ModError; Kreativwelt mit 512 MiB und Status-Datei; Neuerzeugung nach `docker rm` behält VoxeLibre, 1 GiB und `gameid = mineclone2`.

## Messwerte (live, Dev-Proxy)

- **Assumption A5:** `put_archive` hat den Datei-Stream (SpooledTemporaryFile) durch den tecnativa-Proxy angenommen. Kein Fallback auf `read()`.
- VoxeLibre-Welt erzeugen (POST bis 201, inkl. Hash-Prüfung 84 MB, Einspielen, Start): **6,8 s**; Status-Datei danach nach **2,1 s** da.
- VoxeLibre-Neuerzeugung über `/start` nach `docker rm`: **6,6 s**.
- Kreativwelt erzeugen: **1,3 s**.

## Task Commits

1. **Task 1 RED: failing tests** - `45e5834` (test)
2. **Task 1 GREEN: Preset, Status-Mod, gestreamter Payload** - `25c1ecd` (feat)
3. **Task 2: Live-Nachweis beider Presets** - `1bd329b` (test)

## Decisions Made

- WorldPayload in `spec.py` (wie im Plan vorgesehen, wegen Importzyklus).
- Kein bytes-Fallback: Stream-Upload funktioniert live.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test-Erwartung] `/api/presets` listet jetzt zwei Presets**
- **Found during:** Task 1 (GREEN, Volllauf)
- **Issue:** `tests/test_api_contract.py` erwartete genau `["mtg_kreativ"]`.
- **Fix:** Erwartung auf beide Presets erweitert, Schlüsselprüfung (`id`, `title`, `description`) für jedes Preset.
- **Commit:** `25c1ecd`

**2. [Rule 3 - Typprüfung] Wrapper in `test_service_lifecycle.py`**
- **Issue:** pyright: Rückgabetyp `bytes` des monkeypatch-Wrappers passt nicht mehr zu `WorldPayload`.
- **Fix:** Annotation auf `WorldPayload`; Fakes unverändert (prüfen nur den Wahrheitswert).
- **Commit:** `25c1ecd`

**3. [Rule 2 - Doku] `vendor/games/README.md`**
- Verweis auf die Hash-Konstante zeigt jetzt auf `presets.py` (Prüfung in `archive.py`), wie in der Übergabe erwähnt.
- **Commit:** `25c1ecd`

Zusätzlich: Unit-Test `test_create_uses_payload_preset_and_stream` (Spec aus payload.preset, Stream unverändert an put_archive) und `test_get_preset_voxelibre_sanft`.

## Verification

- `uv run ruff check .`, `ruff format --check .`, `pyright` (latest, 0 Fehler), `vulture`: grün.
- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 158 passed, keine SKIPPED.
- Danach `docker ps -a --filter label=gameworld.managed=true -q` leer; `docker volume ls -q --filter name=gameworld-` nur `gameworld-dev_nextcloud` (vorbestehend).
- Akzeptanz-greps: `"gameworld.schema": "2"` in spec.py, `SpooledTemporaryFile` in archive.py, kein `gameworld_players.txt` in archive.py, `core.safe_file_write` genau 1x in status_mod.py, kein `content.luanti.org` unter src/gameworld; `1073741824` 4x im e2e-Test.
- Dev-Stack: `scripts/dev/register-exapp.sh` hat das Backend (Port 10040) auf den neuen Code neu gestartet und die ExApp neu registriert; Heartbeat 200, NC 8091 200.

## Known Stubs

Keine. Das Dashboard bietet die Preset-Auswahl erst ab 02-04 an (geplant), bis dahin erzeugt es Kreativwelten; per API ist VoxeLibre voll nutzbar. `PLAYERS_FILE` wird in 02-04/02-05 von der ExApp gelesen.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus (T-02-10 bis T-02-16 umgesetzt).

## Next Phase Readiness

- 02-04 kann Bereitschaft (Status-Datei mtime vs. StartedAt, nur Schema 2) und Preset-Auswahl im Dashboard bauen.
- WELT-01 bleibt bis zum Phasenende offen.

## Self-Check: PASSED

- FOUND: src/gameworld/provisioner/status_mod.py, tests/e2e/test_presets_e2e.py
- FOUND commits: 45e5834, 25c1ecd, 1bd329b
