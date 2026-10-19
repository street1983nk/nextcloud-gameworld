---
phase: 01-fundament
verified: 2026-10-19T18:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 1: Fundament Verification Report

**Phase Goal:** Gameworld läuft als ExApp auf der eigenen Nextcloud und kann gehärtete, private Luanti-Welten als Sibling-Container sicher erzeugen und steuern.
**Status:** passed. **Re-verification:** Nein.

## Observable Truths

| # | Truth (ROADMAP SC) | Status | Evidence |
|---|---|---|---|
| 1 | Admin installiert ExApp im Dev-Setup, öffnet sie im Top-Menü | VERIFIED | appinfo/info.xml (id gameworld, Image-Tag, Routes), scripts/dev/register-exapp.sh; Acceptance-Skript 81/81 grün (von mir erneut ausgeführt), Owner-Abnahme 19.10. (Playwright 8/8) |
| 2 | Welt (Pin 5.17.0) erzeugen/starten/stoppen/löschen, parallel, je Container eigener UDP-Port | VERIFIED | spec.py LUANTI_VERSION="5.17.0", Port-Mapping 30000/udp auf Host-Port; Service/Port-Saga; CR-01-Rettungspfad (WorldNotFoundError-Handling in worlds/service.py); Acceptance-Skript |
| 3 | Konservative Limits ohne Einstellung | VERIFIED | spec.py: mem_limit=memswap_limit=512m, pids_limit 128, nano_cpus 1 CPU, cap_drop ALL, no-new-privileges, read_only |
| 4 | Privat per Default, kein "öffentlich machen" | VERIFIED | luanti_conf.py: server_announce=false, server_announce_send_players=false; API lehnt public/server_announce mit 422 ab; keine Public-Option in Frontend-Quelle (grep) |
| 5 | Docker nur über gescopten Socket-Proxy, Setup-Check meldet fehlenden Proxy | VERIFIED | scripts/dev/compose.yaml: CONTAINERS/IMAGES/POST/VOLUMES=1, EXEC/NETWORKS/SECRETS=0; provisioner/setup_check.py; Acceptance K5 (docker-py nur unter provisioner/ importiert, mit Positivkontrolle) |

**Score:** 5/5

## Review-Fixes (nach den Summaries)
CR-01 (Neuerzeugung aus Volume, Stop als No-op), WR-01 (tolerante Konfiguration, 503), WR-02 (NotFound -> 404), WR-03 (422-Meldung im Frontend), WR-04 (Dev-NC an 127.0.0.1): alle im Code bzw. in den Tests nachweisbar. Test-Suite von mir ausgeführt: `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q` = 121 passed.

## Requirements Coverage

| Requirement | Plans | Status | Evidence |
|---|---|---|---|
| WELT-04 (parallele Welten, Container pro Welt) | 01-03, 01-05 | SATISFIED | Port-Saga, eigener Container/Port je Welt, Acceptance-Skript |
| WELT-05 (konservative Limits) | 01-01, 01-02, 01-03, 01-05 | SATISFIED | spec.py Limits |
| ZUGANG-01 (privat per Default) | 01-01, 01-02, 01-04, 01-05 | SATISFIED | luanti_conf.py, 422-Ablehnung, keine UI-Option |

Keine verwaisten Requirements: REQUIREMENTS.md ordnet nur diese drei Phase 1 zu, alle sind in Plänen deklariert.

## Anti-Patterns
Keine TBD/FIXME/XXX in src, frontend/src, scripts. Bekannte, akzeptierte Befunde (kein Gap): IN-01..IN-05 (offen für Phasen-Audit), "Erneut prüfen" aktualisiert Statusspalte nicht (Phase-2-Kandidat), fehlgeschlagene Welt belegt UDP-Port bis zum Löschen (offene Produktentscheidung).

## Human Verification
Keine offen; Owner-Abnahme am 19.10.2026 erfolgt.

---
_Verified: 2026-10-19_
_Verifier: Claude (gsd-verifier)_
