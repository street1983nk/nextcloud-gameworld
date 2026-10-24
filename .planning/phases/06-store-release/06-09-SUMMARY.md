---
phase: 06-store-release
plan: 09
subsystem: setup-check, admin-ui
tags: [setup-check, orphans, ui-spec-b3, platt-01, security]
requires: ["06-03", "06-06", "06-08"]
provides:
  - "Setup-Check-Ursachen proxy_dns, proxy_timeout, proxy_refused (aus der Ausnahmekette, feste Texte mit Host/Port aus GAMEWORLD_DOCKER_URL)"
  - "check_docker_url(docker_url) -> CheckItem | None: Warnungen docker_url_socket und docker_url_exposed, vorn in der Ergebnisliste"
  - "DOCS_URL https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#setup-check, jede Fehler- und Warnmeldung endet mit \" Anleitung: {DOCS_URL}\""
  - "frontend/src/orphans.js (B3-Texte, CLEANUP_DOCS_URL ...install.md#cleanup), api.js listOrphans/removeOrphanContainer/removeOrphanVolume"
  - "OrphanSection.vue (B3) in ParentView nach VerwalterGroupsSection, nur bei me.nc_admin === true"
affects: [06-11, 06-12]
tech-stack:
  added: []
  patterns:
    - "Ursache aus __cause__/__context__/reason-Kette (höchstens 10 Glieder, zyklenfest), nie Ausnahmetext in der Meldung"
    - "Private Netze als feste Liste statt ipaddress.is_private (das zählt Dokumentationsnetze wie 203.0.113.0/24 als privat)"
    - "Text mit code-Teilen als SCRIPT_SEGMENTS, Prüfskript sichert Gleichheit mit SCRIPT_TEXT"
key_files:
  created:
    - frontend/src/orphans.js
    - frontend/tests/orphans.check.mjs
    - frontend/src/components/OrphanSection.vue
    - tests/test_orphan_section_gate.py
  modified:
    - src/gameworld/provisioner/setup_check.py
    - tests/test_setup_check.py
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
decisions:
  - "Jede requests.Timeout (nicht nur ConnectTimeout) gilt als proxy_timeout; sonstige RequestException beim Ping als proxy_refused; Ping mit Nicht-200 und Programmfehler behalten die allgemeine Meldung id reachable"
  - "Docker-URL-Warnung: privat = 10/8, 172.16/12, 192.168/16, 127/8, ::1, fc00::/7; Hostnamen kein Befund; unix:// und npipe:// = docker_url_socket"
  - "OrphanSection meldet 403 mit NC_ADMIN_ONLY_TEXT und nutzt denselben forbidden-Weg wie VerwalterGroupsSection (/api/me neu laden)"
  - "Einhängepunkt nach dem verwalterForbidden-Hinweis, damit die v-if/v-else-if-Kette von VerwalterGroupsSection intakt bleibt"
metrics:
  duration: "ca. 45 min"
  completed: 2026-10-24
  tasks: 3
  files: 8
---

# Phase 6 Plan 09: Setup-Check-Ursachen und Reste früherer Installationen Summary

Setup-Check unterscheidet DNS-Fehler, Zeitüberschreitung und abgelehnte Verbindung mit festen deutschen Texten und öffentlicher Doku-URL, warnt vor Docker-Socket und öffentlicher Proxy-Adresse; OrphanSection.vue (UI-SPEC B3) zeigt NC-Admins fremde Container und Spielstände mit eigenen Bestätigungen gegen die 06-08-API.

## Tasks

| Task | Name | Commits | Dateien |
|------|------|---------|---------|
| 1 | Setup-Check mit getrennten Ursachen und fester Doku-URL | c0ff87b (RED), d489c82 (GREEN) | setup_check.py, test_setup_check.py |
| 2 | orphans.js-Texte, Prüfskript und API-Aufrufe | a94bce0 (RED), 2127fb7 (GREEN) | orphans.js, orphans.check.mjs, api.js |
| 3 | OrphanSection.vue in ParentView einhängen | 26cccff | OrphanSection.vue, ParentView.vue, orphans.check.mjs, test_orphan_section_gate.py |

## Für 06-11 (Doku)

- install.md braucht `<a id="setup-check"></a>` und `<a id="cleanup"></a>`; beide URLs sind jetzt im Code fest (setup_check.DOCS_URL, orphans.CLEANUP_DOCS_URL).
- Meldungstabelle in install.md Abschnitt 6 um die neuen Meldungen ergänzen: "Gameworld findet den Dienst ... nicht" (falsches Netz), "... antwortet nicht" (anderes Netz/Firewall), "... nimmt keine Verbindung an" (Container läuft nicht), Warnungen Docker-Socket und Adresse außerhalb des privaten Netzes.

## Verifikation

- Gates vor jedem Commit: ruff check, ruff format --check (188 Dateien), pyright latest 0 Fehler, vulture ohne Befund; npm run build grün; alle 8 frontend/tests/*.check.mjs grün.
- `uv run pytest -m "not docker" -q`: 2539 passed, 44 deselected.
- RED belegt: test_setup_check.py gegen die alte setup_check.py (Importfehler), orphans.check.mjs ohne orphans.js (Modul fehlt).
- Echte Netzfehler gegengeprüft (nicht nur nachgebaute Ketten): `tcp://gameworld-probe-nonexistent.invalid:2375` -> proxy_dns; geschlossener Port 127.0.0.1 mit 5 s Frist -> proxy_refused (Windows wiederholt SYN rund 2 s, mit 1 s Frist wird es proxy_timeout); 10.255.255.1 -> proxy_timeout; unix-Socket -> docker_url_socket + proxy_refused; 203.0.113.5 -> docker_url_exposed + proxy_timeout.
- Negativtests unabhängig: tests/test_orphan_section_gate.py mit eigenem Provisioner-Spion: gw-lehrer (Verwalter) und gw-kind bekommen nc_admin false und 403 auf allen drei Routen, Spion unberührt; Positivkontrolle admin nc_admin true und 200 auf allen drei Routen. orphans.check.mjs: genau ein OrphanSection-Einhängepunkt mit `v-if="me?.nc_admin === true"`, kein v-html, kein setInterval.
- Kein Proxy-Störfall-Test gegen den echten Dev-Proxy nötig (Plan sah keinen vor); laufende Container nicht angefasst.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ipaddress.is_private hätte 203.0.113.5 durchgelassen**
- **Found during:** Task 1
- **Issue:** Python zählt Dokumentationsnetze (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) zu is_private; die Planvorgabe "is_private oder is_loopback = ok" hätte den geforderten Fall tcp://203.0.113.5:2375 nicht gewarnt.
- **Fix:** feste Liste privater Netze (_PRIVATE_NETS), Test auch mit 8.8.8.8 und 172.18.0.4/192.168.1.10.
- **Commit:** d489c82

**2. [Rule 1 - Bug] Bestandstests erwarteten id reachable für die abgelehnte Verbindung**
- **Found during:** Task 1
- **Issue:** test_unreachable_proxy_stops_after_one_item und test_api_route_is_200_when_proxy_is_down prüften id reachable und die volle URL im Text; mit 1 s Frist meldet Windows bei geschlossenem Port eine Zeitüberschreitung statt Ablehnung.
- **Fix:** Erwartung proxy_refused, Frist 5 s, Host:Port statt URL im Text.
- **Commit:** c0ff87b

**3. [Rule 2 - Sicherheit] Zusätzlicher unabhängiger Negativtest Backend**
- **Found during:** Task 3
- **Issue:** Auftrag fordert unabhängige Negativtests; 06-08 testet die 403 nur mit der eigenen Docker-Attrappe.
- **Fix:** tests/test_orphan_section_gate.py (nicht im Plan gelistet) koppelt /api/me nc_admin und 403 mit Positivkontrolle.
- **Commit:** 26cccff

**4. [Rule 2] _NOT_CHECKED-Warnung bekommt ebenfalls den Doku-Verweis**
- Damit endet jede nicht bestandene Meldung mit " Anleitung: {DOCS_URL}" (Test test_every_failed_message_links_the_guide). Commit d489c82.

**5. Einhängepunkt OrphanSection nach dem verwalterForbidden-Hinweis statt direkt nach VerwalterGroupsSection**
- Direkt dazwischen hätte die v-if/v-else-if-Kette des Hinweises gebrochen; sichtbar bleibt die Reihenfolge Verwalter-Gruppen, dann Reste. Commit 26cccff.

## Known Stubs

Keine.

## Threat Flags

Keine neuen Angriffsflächen außerhalb des Threat-Registers: T-06-39 (Warnungen docker_url_socket/docker_url_exposed), T-06-40 (Texte fest, Host/Port nur aus urlsplit der eigenen URL, Test "geheimes Detail" nicht in der Meldung), T-06-41 (eigene NcDialog-Bestätigung je Aktion, Knopf error), T-06-42 (nur Textinterpolation, grep v-html = 0) umgesetzt.

## Offen für die Owner-Abnahme

- Sichtprüfung B3 bei 390 px und Desktop gemeinsam per Playwright (Projektregel), sobald 06-12 die Abnahme fährt.

## Self-Check: PASSED

- FOUND: frontend/src/orphans.js, frontend/tests/orphans.check.mjs, frontend/src/components/OrphanSection.vue (385 Zeilen), tests/test_orphan_section_gate.py
- FOUND: c0ff87b, d489c82, a94bce0, 2127fb7, 26cccff
