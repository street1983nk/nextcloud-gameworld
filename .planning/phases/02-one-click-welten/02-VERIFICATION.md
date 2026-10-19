---
phase: 02-one-click-welten
verified: 2026-10-19T21:30:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 2: One-Click-Welten Verification Report

**Phase Goal:** Ein Elternteil ohne Serverwissen erstellt und verwaltet Welten per Klick im Dashboard; der Zustand überlebt ExApp-Updates und Host-Reboots.
**Status:** passed. **Re-verification:** Nein.

## Observable Truths

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|---|---|---|
| 1 | Welt per One-Click mit kindgerechtem Preset (MTG kreativ, VoxeLibre sanft), ohne Konfigfragen | VERIFIED | `provisioner/presets.py`: feste Registry `mtg_kreativ` (512m, creative, kein Schaden/PvP/TNT/Feuer) und `voxelibre_sanft` (1g, friedliche Mobs, keepInventory), SHA256-gepinnte Spiel-Zips, `vendor/games`. API nimmt nur Registry-IDs (`validate_preset_id`), kein Nutzerwert erreicht conf oder Spec. `frontend/src/App.vue`: Radiogruppe "Spielart" aus `/api/presets`, nur Name plus Preset, keine Konfigfragen. Acceptance K1 (Live-Erzeugung beider Presets, Status-Mod) grün. |
| 2 | Start/Stopp/Neustart im Dashboard, Status verständlich, aus Docker statt DB | VERIFIED | `worlds/status.py::derive_status` leitet running/starting/stopped/error aus `docker inspect` (State, ExitCode, OOMKilled, StartedAt) plus mtime der Status-Datei ab; DB liefert nur creating/failed. `service._collect` ist einziger Pfad für Liste und Einzelansicht. Neustart als Stop plus `_launch` (`_restart_world_sync`). Dashboard hat Status-Chips mit `status_text`, Restart-Button, Polling. Acceptance K2 (inkl. neuer StartedAt nach restart, Status binnen 30 s) grün. |
| 3 | Pro Welt Online-Spieler und RAM sichtbar | VERIFIED | `service._view_from_docker`: Spieler aus Status-Datei nur bei `running` und Datei-mtime >= StartedAt (`parse_players`), RAM per `memory_bytes` nur bei laufendem Container, Fehler pro Welt isoliert. Frontend: `playersText`, `memoryPercent`/`memoryText` mit Fortschrittsbalken. 2-s-Listen-Cache wird bei Mutationen verworfen. Acceptance K3 grün. |
| 4 | Nach ExApp-Update und Host-Reboot sind alle Welten korrekt im Dashboard (Label-Reconciliation, persistentes Volume) | VERIFIED | `main.lifespan` startet `reconcile_forever` als Task (blockiert Heartbeat nicht); `worlds/reconciler.py` Regeltabelle (START/RECREATE/MARK_*/ADOPT_RUNNING/RETRY_DELETE), periodisch nie Start. Acceptance K4a (Update-Simulation: Prozess beendet, neues Backend, gleiche Container-IDs, R1 running, R2 stopped) und K4b (Reboot-Simulation: R1 von außen gestoppt, binnen 40 s wieder running, gleiche Container-ID, R2 bleibt exited, RestartPolicy no, Fremdcontainer unberührt mit Positivkontrolle) grün. |

**Score:** 4/4

## Review-Fixes nach den Summaries (Regressionsprüfung)

Gezielt geprüft, ob CR-01/WR-05 (`volume_exists`, `delete_only`, 409) den Start-Pfad normaler Welten gebrochen haben: Nein.
- `service._launch` prüft `volume_exists` nur im Zweig `WorldNotFoundError` (Container fehlt); der normale Start (`start_world` gelingt) bleibt unverändert. Fehlt das Volume: `DeleteOnlyError` (409), keine leere Welt.
- `_refuse_delete_only` greift nur bei `op_state == failed` und `last_error` in {Weltdaten fehlen, Erstellen unterbrochen}. Gewöhnlich fehlgeschlagene Welten bleiben startbar (Regressionstest vorhanden).
- Live: `smoke.sh` (Erzeugen zweier Welten, Stop, erneuter Start, Löschen ohne Reste) und `acceptance-phase2.sh` (K2 Start/Stopp/Restart, K4 Update/Reboot) laufen nach den Fixes grün.
- WR-01 (Aufräumen bei Nicht-ProvisionerError), WR-02 (Fehlerisolation im Abgleich, unbekanntes Preset nur an dieser Welt), WR-03 (ConnectTimeout nicht wiederholt), WR-04 (Tar-Fehler in Status-Datei) im Code nachgewiesen (`_payload`, `_create_world_sync`, `_reconcile_row`, `_view`).
- Frontend-Bundle `js/gameworld-main.js` enthält `delete_only` (Build nach Fix).

## Behavioral Spot-Checks / Ausgeführt vom Verifier

| Check | Befehl | Ergebnis | Status |
|---|---|---|---|
| Test-Suite | `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs` | 363 passed, nichts übersprungen | PASS |
| Unabhängige Phasenabnahme | `sh scripts/dev/acceptance-phase2.sh` | 104 von 104 Prüfungen (inkl. Regression Phase 1: 81/81) | PASS |
| Durchstich | `sh scripts/dev/smoke.sh` | "Durchstich erfolgreich" | PASS |
| Aufräumen | `docker ps -a` | keine Welt-Container übrig; Dev-Stack (app, docker-proxy) läuft, NC 8091 antwortet 200 | PASS |

Probes: keine `probe-*.sh` für diese Phase deklariert.

## Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| WELT-01 (One-Click, Preset) | SATISFIED | SC 1 |
| WELT-02 (Start/Stopp/Restart, Status) | SATISFIED | SC 2 |
| WELT-03 (Spieler, RAM) | SATISFIED | SC 3 |
| PLATT-02 (Update-/Reboot-Überleben) | SATISFIED | SC 4 |

Keine verwaisten Requirements: REQUIREMENTS.md ordnet nur diese vier Phase 2 zu.

## Anti-Patterns

Keine TBD/FIXME/XXX in src, frontend/src, scripts, docs. Review-Befunde IN-01 bis IN-05 bewusst außerhalb des Fix-Scopes (Info, kein Gap). Bekannt: Test-Isolationshinweis zu `_LOCK` nach Lifespan-Tests (vorbestehend, kein Produktfehler).

## Human Verification

Keine offen. Owner-Abnahme erfolgt. Bekannter, vom Owner akzeptierter Deferred-Punkt (kein Success Criterion): Live-Join mit echtem Luanti-Client auf eine erzeugte Welt; die Server-Seite (Port, Status-Mod, Spielerliste) ist durch K1/K3 belegt. Das Zugangsthema (Join-Pfad für Spieler) gehört zu Phase 3.

---
_Verified: 2026-10-19_
_Verifier: Claude (gsd-verifier)_
