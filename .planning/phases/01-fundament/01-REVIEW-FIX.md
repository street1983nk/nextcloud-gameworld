---
phase: 01-fundament
fixed_at: 2026-10-19T17:05:00Z
review_path: .planning/phases/01-fundament/01-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 01: Code Review Fix Report

**Fixed at:** 2026-10-19T17:05:00Z
**Source review:** .planning/phases/01-fundament/01-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (CR-01, WR-01, WR-02, WR-03, WR-04; Info-Befunde IN-01 bis IN-05 bewusst außerhalb des Scopes)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: Welt ohne Container ist unrettbar

**Files modified:** `src/gameworld/worlds/service.py`, `tests/test_service_lifecycle.py`
**Commit:** 12c49a3
**Applied fix:** `_launch` fängt `WorldNotFoundError` und erzeugt den Container aus dem vorhandenen Volume neu (`create_world_container(..., reuse_volume=True)`, höchstens einmal pro Start, Neuerzeugung durchläuft weiter die Port-Saga). `_stop_world_sync` behandelt einen fehlenden Container als bereits gestoppt (No-op-Erfolg). Fünf neue Tests: Start erzeugt neu, Saga-Fehlerpfad hinterlässt rettbaren Zustand, Neuerzeugung durchläuft die Saga, Stop ist No-op, API antwortet 200 statt 404 (Start und Stop).

### WR-01: Ungültige Umgebung verhindert den App-Start

**Files modified:** `src/gameworld/main.py`, `src/gameworld/api/worlds.py`, `src/gameworld/config.py`, `tests/test_startup_config.py` (neu)
**Commit:** 3e95c87
**Applied fix:** Lifespan toleriert Konfigurationsfehler und loggt sie; `get_service` bildet `ValueError` aus `load_settings` auf 503 mit deutscher Meldung ab; nicht anlegbares `APP_PERSISTENT_STORAGE` (OSError bei mkdir) wird in `load_settings` zum `ValueError` mit deutscher Meldung, damit `/api/setup-check` auch diesen Fall als Befund "config" meldet. Vier neue Tests, darunter der Lifespan selbst mit ungültigem `GAMEWORLD_PORT_RANGE`.

### WR-02: start_world verschluckt NotFound und macht daraus 500 statt 404

**Files modified:** `src/gameworld/provisioner/client.py`, `tests/test_provisioner_errors.py`
**Commit:** 201e67a
**Applied fix:** Eigener `except docker.errors.NotFound: raise`-Zweig vor dem `APIError`-Zweig in `start_world`; `_guarded` bildet NotFound auf `WorldNotFoundError` ab (404; seit CR-01 greift bei Start zusätzlich die Neuerzeugung). Neuer Test für den Race-Fall.

### WR-03: Frontend verliert die deutsche Validierungsmeldung bei ungültigem Weltnamen

**Files modified:** `frontend/src/App.vue`, `src/gameworld/api/worlds.py`, `tests/test_api_contract.py`
**Commit:** 70cb094
**Applied fix:** `errorText` wertet FastAPI-422-Detail-Listen aus und zeigt `detail[0].msg` ohne das Präfix "Value error, "; der tote `except ValueError`-Zweig in `create_world` ist entfernt (Pydantic-Modell weist ungültige Namen bereits ab). Backend-Test sichert zu, dass die Detail-Liste die deutsche Namensmeldung trägt. Bundle neu gebaut (`npm run build`).

### WR-04: Dev-Nextcloud mit festem Admin-Passwort auf allen Interfaces erreichbar

**Files modified:** `scripts/dev/compose.yaml`
**Commit:** e5c560a
**Applied fix:** Port-Bindung auf `127.0.0.1:${GAMEWORLD_NC_PORT:-8091}:80` geändert (mit Begründungskommentar), Stack per `docker compose up -d` neu erstellt, Bindung live verifiziert (`127.0.0.1:8091->80/tcp`), Registrierung und Smoke-Test danach grün.

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 121 passed (vorher 109; 12 neue Tests, nichts geskippt)
- `uv run ruff check .`: All checks passed
- `uv run ruff format --check .`: 40 files already formatted
- `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`: 0 errors, 0 warnings
- `uv run vulture`: keine Funde
- `cd frontend && npm run build`: Bundle neu erzeugt (gameworld-main.js, 407 kB)
- Backend neu gestartet (`sh scripts/dev/register-exapp.sh`), `sh scripts/dev/smoke.sh`: Exit 0, alle Schritte ok

---

_Fixed: 2026-10-19T17:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
