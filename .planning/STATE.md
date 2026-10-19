---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Completed 03-02-PLAN.md
last_updated: "2026-10-20T08:00:00.000Z"
last_activity: 2026-10-20
progress:
  total_phases: 6
  completed_phases: 2
  total_plans: 19
  completed_plans: 14
  percent: 33
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-10-19)

**Core value:** Ein Elternteil ohne Serverwissen startet in Minuten eine private, sichere Luanti-Welt, auf der nur Eingeladene spielen und deren Daten zuhause bleiben.
**Current focus:** Phase 3, Zugang und Rollen (Ausführung, 2 von 7 Plänen)

## Current Position

Phase: 3 (Zugang und Rollen), In Progress
Plan: 03-02 complete, nächster 03-03
Status: Executing Phase 3
Last activity: 2026-10-20

Progress: [███░░░░░░░] 33% (2 von 6 Phasen)

## Performance Metrics

**Velocity:**

- Total plans completed: 5
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 01 P01 | 11 min | 3 tasks | 34 files |
| Phase 01 P02 | 32 min | 2 tasks | 16 files |
| Phase 01-fundament P03 | 9 min | 3 tasks | 11 files |
| Phase 01 P04 | 12 min | 2 tasks | 9 files |
| Phase 01 P05 | 45 min | 2 tasks | 2 files |
| Phase 02 P02 | 10 min | 2 tasks | 6 files |
| Phase 02 P01 | 25 min | 2 tasks | 11 files |
| Phase 02 P03 | 10 min | 2 tasks | 14 files |
| Phase 02 P04 | 14 min | 2 tasks | 12 files |
| Phase 02 P05 | 15 min | 2 tasks | 9 files |
| Phase 02 P06 | 25 min | 2 tasks | 7 files |
| Phase 02 P07 | 60 min | 2 tasks | 4 files |
| Phase 03 P01 | 30 min | 3 tasks | 13 files |
| Phase 03 P02 | 25 min | 3 tasks | 16 files |

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
- [Phase 01]: 01-04: Setup-Check unterdrückt Folgefehler: fehlt POST, werden DELETE-Volumes- und Exec-Probe nicht gesendet, nur Warnung 'Nicht geprüft'
- [Phase 01]: 01-04: 'Welt erstellen' bleibt gesperrt, bis der Setup-Check ok meldet; /api/setup-check antwortet immer 200
- [Phase 01]: 01-05: Phase 1 vom Owner am 19.10.2026 per gemeinsamer Playwright-Abnahme freigegeben, Abnahmeskript 81/81
- [Phase 01]: 01-05: Offene Produktfrage fürs Phasen-Audit: failed-Zeile nach gescheiterter Anlage belegt einen UDP-Port bis zum Löschen
- [Phase 01]: 01-05: 'Erneut prüfen' aktualisiert Statusspalte nicht, Kandidat für Phase 2 (Status-UI)
- [Phase 02]: 02-02: VoxeLibre-Zip (84 MB) nicht im Git, Abruf per scripts/fetch-games.sh gegen SHA256SUMS; register-exapp.sh ruft es vor Frontend-Build und Backend-Start
- [Phase 02]: 02-02: Offline-Variante über GAMEWORLD_GAME_SOURCE_DIR, Prüfsumme wird auch dann geprüft
- [Phase 02]: 02-01: preset im POST /api/worlds optional, Vorgabe mtg_kreativ (Phase-1-Vertrag kompatibel, Dashboard wählt ab 02-04 sichtbar)
- [Phase 02]: 02-01: failed-Zeile auch nach erfolgreichem Aufräumen gelöscht (über RESEARCH-Empfehlung 5 hinaus), bleibt nur bei gescheitertem Aufräumen; Owner sieht es in 02-07 K2
- [Phase 02]: 02-01: Schema 2 mit Spalte preset, Migration idempotent über PRAGMA table_info; _payload baut immer aus get_preset(row.preset)
- [Phase 02]: 02-03: put_archive nimmt das Tar als Datei-Objekt (SpooledTemporaryFile) durch den Proxy an (A5 live bestätigt), VoxeLibre-Erzeugen 6,8 s
- [Phase 02]: 02-03: Label gameworld.schema 2 = Preset gesetzt und Welt-Mod gameworld_status vorhanden; 02-04 wertet Bereitschaft nur ab Schema 2 aus
- [Phase 02]: 02-03: WorldPayload(preset, archive) in spec.py; Spec und Payload kommen aus derselben WorldPayload, Neuerzeugung behält Spiel und Limit
- [Phase 02]: 02-04: Status nur aus Docker (derive_status in worlds/status.py), DB nur für creating/failed; Neustart = stop plus _launch, nie container.restart
- [Phase 02]: 02-04: Lese-Retry genau einmal nur bei ConnectionError/ProtocolError (Keep-Alive), Timeouts und Mutationen nie wiederholt
- [Phase 02]: 02-04: Status-Datei gekappt (64 KiB Tar-Strom, 4096 Bytes Inhalt); Privacy-Grep nimmt nur die DOM-Page-Visibility-API aus
- [Phase 02]: 02-05: Listen-Cache 2 s mit Generationszähler, Mutationen verwerfen ihn davor und danach (auch bei Fehlern); unknown wird nie gecacht
- [Phase 02]: 02-05: Spieler nur bei abgeleitetem Status running (Datei dieses Laufs), RAM bei jedem laufenden eigenen Container über stats one_shot
- [Phase 02]: 02-05: Dashboard wendet nur die Antwort des zuletzt gestarteten Listenabrufs an (überholende Abrufe bei totem Proxy)
- [Phase 02]: 02-06: Reconciler als Lifespan-Task: Boot-Abgleich (5 s bis Docker antwortet) startet Soll-laufende exited Welten und erzeugt fehlende aus dem Volume, periodisch (30 s) nur ADOPT_RUNNING, nie Neustart
- [Phase 02]: 02-06: op_state failed fasst der Abgleich nie an; DockerUnavailableError bricht den Boot-Abgleich ab statt Welten als failed zu markieren
- [Phase 02]: 02-06: Abgleich-Aufrufe mit abandon_on_cancel, Herunterfahren wartet nie auf Docker; Dev-Proxy restart unless-stopped
- [Phase 02]: 02-07: Owner-Abnahme 19.10.2026 erteilt; A1 (fly, fast im Kreativ-Preset), A2 (Sanft-Schalter), A8 (Hunger an) und failed-Zeilen-Regel bestätigt; acceptance-phase2.sh 104/104
- [Phase 02]: 02-07: Live-Join mit echtem Luanti-Client offen (kein Client vorhanden), Nachholung bei nächster Gelegenheit
- [Phase 03]: 03-01: Eigener Welt-Mod gameworld_access (Prejoin-Whitelist, set_player_password, Sperre 5 Fehlversuche/10 min, Kick-Takt 5 s, State-Datei mit Generation); Label gameworld.schema bleibt 2
- [Phase 03]: 03-01: Lua-Quelltext reines ASCII, Kindertexte als Python-Konstanten mit Umlauten, im Mod als Lua-Dezimal-Escapes (UTF-8)
- [Phase 03]: 03-01: _launch schreibt vor jedem start_world beide Mods und die Zugangsdatei per put_archive; WorldNotFoundError beim Schreiben nimmt den Neuerzeugungspfad
- [Phase 03]: 03-01: Deutscher Groß-/Kleinschreibungs-Hinweis greift nur, solange das Konto in richtiger Schreibweise noch nicht existiert; danach gewinnt Luantis englischer Builtin-Text
- [Phase 03]: 03-02: Rolle allein aus NC-Gruppe admin per Selbstauskunft (/cloud/user), Cache 30 s nur für Erfolge; Störung -> 503, nie Verwalter
- [Phase 03]: 03-02: require_verwalter routerweit (dependencies=[...]) auf worlds und setup_check; jede künftige Verwaltungsroute dort erbt die Sperre, neue Spielerrouten gehören in einen eigenen Router unter /api/my/
- [Phase 03]: 03-02: info.xml USER ^/js, ^/img, ^/api/me$, ^/api/my/.* vor ADMIN ^/api/.*; Top-Menü admin_required=False; AppAPI liefert Kindern an ADMIN-Routen 404 (nicht 403)

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

Last session: 2026-10-20T08:00:00.000Z
Stopped at: Completed 03-02-PLAN.md
Resume file: None
