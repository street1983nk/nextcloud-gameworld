---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 01-01-PLAN.md
last_updated: "2026-10-19T10:40:30.973Z"
last_activity: 2026-10-19
progress:
  total_phases: 6
  completed_phases: 0
  total_plans: 5
  completed_plans: 3
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-19)

**Core value:** Ein Elternteil ohne Serverwissen startet in Minuten eine private, sichere Luanti-Welt, auf der nur Eingeladene spielen und deren Daten zuhause bleiben.
**Current focus:** Phase 01 — Fundament

## Current Position

Phase: 01 (Fundament) — EXECUTING
Plan: 4 of 5
Status: Ready to execute
Last activity: 2026-10-19

Progress: [██████░░░░] 60%

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 01 P01 | 11 min | 3 tasks | 34 files |
| Phase 01 P02 | 32 min | 2 tasks | 16 files |
| Phase 01-fundament P03 | 9 min | 3 tasks | 11 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Init]: Luanti-first, Minecraft erst MVP 2 (EULA-Risiko)
- [Init]: Spielzeitlimits in v1 statt v1.x (Owner 19.10.2026, größte Elternsorge)
- [Init]: Container-Provisionierung via gescopten Socket-Proxy; finaler Entscheid wird in Phase 1 praktisch validiert (Phasen-Research: Daten-Ablage, Image-Wahl)
- [Init]: MVP-Scope Erreichbarkeit: LAN zuerst, VPN dokumentiert, kein UPnP
- [Phase 01]: Provisioner-Guard bildet auch APIError ab (NotFound -> WorldNotFoundError, sonst ProvisionerError), nie roher docker-Fehler in der API
- [Phase 01]: start/discard prüfen gameworld.managed und eigene gameworld.instance vor jeder Mutation
- [Phase 01]: uvicorn[standard]==0.54.0 direkt gepinnt (mit nc-py-api 0.30.3 auflösbar)
- [Phase 01]: 01-02: Nicht-Admin Variante A, TopMenuController.php:65 liefert 404; Seite, Bundle und API 404 für Nicht-Admins
- [Phase 01]: 01-02: Initial State via loadState('app_api', ...) als JSON-Text; Bundle als IIFE js/gameworld-main.js; Routen kanonisch ^/pfad
- [Phase 01]: 01-03: Alle Container-Mutationen nur über world_id und _owned() (Label-Filter plus Nachprüfung), start/discard per container_id entfallen
- [Phase 01]: 01-03: Port-Saga erzeugt bei belegtem Port neu mit nächstem freien Port, Volume bleibt (reuse_volume), max. 3 Startversuche, danach 409
- [Phase 01]: 01-03: remove_world toleriert fehlenden Container und entfernt trotzdem das Volume mit eigenem Instanz-Präfix

### Pending Todos

None yet.

### Blockers/Concerns

- [Phase 1] Research nötig: Welt-Daten-Ablage (Named Volume vs. Container-FS + Archive-API), Luanti-Image-Wahl, Headless-Administration
- [Phase 3] Research nötig: Whitelist-Mod-Wahl (Whiter List vs. ct_whitelist vs. AntumDeluge) gegen Luanti 5.17 verifizieren
- [Phase 4] Research nötig: Spielzeit-Durchsetzungspfad Mod vs. Scheduler-Stopp, Umgehungs-Caveat bewerten

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-10-19T10:40:24.244Z
Stopped at: Completed 01-01-PLAN.md
Resume file: None
