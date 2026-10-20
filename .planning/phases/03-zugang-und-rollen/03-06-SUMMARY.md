---
phase: 03-zugang-und-rollen
plan: 06
subsystem: access, ui
tags: [connection-info, player-view, join-host, lazy-sync, vue]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-02 USER-Route ^/api/my/.* und PlayerView-Platzhalter; 03-04 AccessService, _ensure_fingerprint, try_mutation; 03-05 ParentView, Passwort-Verdeckmuster
provides:
  - GET /api/my/worlds (USER) mit MyWorldOut id, name, status, status_text, host, port, player_name, password, nur eigene Daten
  - AccessService.my_worlds(profile) mit lazy, rein hinzufügender Gruppen-Provisionierung aus der signierten Selbstauskunft
  - WorldStore.group_invited_worlds(gids)
  - GET/POST /api/settings (Verwalter) mit validiertem join_host in meta
  - ConnectionCard.vue, JoinGuide.vue, JoinHostSettings.vue; PlayerView mit Karten und 5-s-Polling; ParentView mit "Meine Verbindungsinfo" und Einstellungen
affects: [03-07]
tech-stack:
  added: []
  patterns:
    - "Spielerrouten warten nie auf die Welt-Sperre: Fingerabdruck-Abgleich (blocking=False) und Provisionierung (try_mutation) folgen bei belegter Sperre beim nächsten 5-s-Abruf"
    - "Spielerantwort aus eigener players-/world_access-Zeile plus WorldService.list_worlds gefiltert auf eigene IDs; Felder explizit gemappt, nie WorldView weitergereicht"
key-files:
  created:
    - tests/test_my_worlds.py
    - tests/test_settings_api.py
    - frontend/src/components/ConnectionCard.vue
    - frontend/src/components/JoinGuide.vue
    - frontend/src/components/JoinHostSettings.vue
  modified:
    - src/gameworld/worlds/store.py
    - src/gameworld/access/service.py
    - src/gameworld/api/me.py
    - src/gameworld/api/invites.py
    - tests/e2e/test_invite_join_e2e.py
    - frontend/src/api.js
    - frontend/src/views/PlayerView.vue
    - frontend/src/views/ParentView.vue
key-decisions:
  - "03-06: my_worlds nimmt die Welt-Sperre nie blockierend (try_mutation, _ensure_fingerprint blocking=False); sonst stapeln sich Poll-Anfragen als wartende Worker-Threads hinter einem Erzeugen"
  - "03-06: Lazy Provisionierung nur für Gruppen-Einladungen, deren gid in der Selbstauskunft steht; nur Hinzufügen, Entfernen bleibt beim Verwalter-Abgleich (T-03-44 akzeptiert)"
  - "03-06: join_host leer gespeichert heißt host null in der Spielerantwort; Frontend nimmt dann window.location.hostname"
  - "03-06: join_host-Validator: Hostname-Labels [A-Za-z0-9-] 1 bis 63 ohne Rand-Bindestrich oder IP-Literal (IPv6 ohne Klammern), max. 253, kein ://, /, Port, Steuer- oder Formatzeichen"
  - "03-06: JoinGuide zeigt das Passwort nicht im Fließtext; es steht nur verdeckt und kopierbar in der Karte"
requirements-completed: []
metrics:
  duration: 40 min
  completed: 2026-10-20
---

# Phase 3 Plan 06: Kind-Ansicht mit Verbindungsinfo Summary

**Kinder holen sich über GET /api/my/worlds (USER-Route) nur ihre eigenen Welten mit Adresse, Port, Spielername und Passwort samt 5-Schritte-Anleitung; Gruppen-Eingeladene bekommen beim eigenen Besuch Zugang, Eltern pflegen die Spieler-Adresse mit Warnhinweisen.**

## Performance

- Duration: rund 40 min
- Completed: 2026-10-20
- Tasks: 2
- Files: 13 (5 neu, 8 geändert)

## Accomplishments

- `AccessService.my_worlds(profile)`: Geheimnis laden, Fingerabdruck außerhalb der Sperre, eigene Gruppen aus der Selbstauskunft gegen Gruppen-Einladungen, fehlender Zugang wird unter `try_mutation` ergänzt (Generation +1, Push), danach nur die eigenen `world_access`-Welten mit pro Anfrage abgeleitetem Passwort.
- `GET /api/my/worlds` ohne Verwalter-Sperre, Status/Name/Port aus `list_worlds()` nur für eigene IDs, `host` aus `meta.join_host` oder null; 503 bei Rollen- oder Geheimnisstörung.
- `GET/POST /api/settings` im Verwalter-Router (403 für Kinder, live 404 über AppAPI ADMIN).
- Frontend: Spieleransicht mit Anrede, Karten (Status-Chip ohne Steuerknöpfe, Kopierfelder, Passwort verdeckt bis Anzeigen), Anleitung mit luanti.org als reinem Link; Eltern-Dashboard mit Einstellung "Adresse für Spieler" und Hinweisen für Loopback und Internet-/Tunneladressen sowie "Meine Verbindungsinfo", wenn selbst eingeladen.

## Task Commits

1. Task 1: players fetch their own worlds and connection data, `6c33b59`
2. Task 2: connection info and join guide for players, `47242b5`

## Verification

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`: 590 passed (inklusive Docker-e2e: Gruppe eingeladen, Verzeichnis ohne Mitglied, Kind holt Daten selbst, Join `auth_accept`)
- ruff, ruff format, pyright (latest, 0 Fehler), vulture grün; `npm run build` grün; `tests/test_frontend_privacy.py` 8 passed; keine U+2013/U+2014 in frontend/src
- Akzeptanz-Greps: keine `require_verwalter` in me.py, Route `"/my/worlds"` vorhanden, keine Felder memory/docker_status/players in MyWorldOut; keine Steuer-API in PlayerView/ConnectionCard; kein externer Laufzeitabruf
- Live (Dev-Stack, Backend neu registriert): gw-kind `/api/my/worlds` 200 `[]`, `/api/settings` 404; Admin legt Probewelt an, lädt gw-kind ein, setzt join_host 192.168.178.20; gw-kind sieht genau diese Welt mit host, Port 30000, Name Kind, eigenem Passwort; join_host zurückgesetzt, Welt gelöscht, keine Welt-Container übrig

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Robustheit] my_worlds wartet nie auf die Welt-Sperre**
- Found during: Task 1
- Issue: Der Plan sah die Ergänzung unter `worlds.mutation()` vor. Die Spieleransicht pollt alle 5 s; ein blockierender Lock hinter einem Erzeugen (Sekunden bis Minuten) würde Worker-Threads stapeln und auch Statusabrufe ausbremsen (Pitfall 6 aus Phase 2, Muster sync_all aus 03-04).
- Fix: `_ensure_fingerprint(secret, blocking=False)` und `try_mutation()`; bei belegter Sperre folgt die Ergänzung beim nächsten Abruf. Test `test_busy_lock_never_blocks_my_worlds` (fail_after 5) plus Deadlock-Test bei Geheimniswechsel.
- Files: src/gameworld/access/service.py, tests/test_my_worlds.py
- Commit: 6c33b59

**2. [Plan-Detail] JoinGuide ohne password-Prop**
- Found during: Task 2
- Issue: Das Passwort im Anleitungstext hätte das Verdecken der Karte ausgehebelt; ein ungenutzter Prop wäre toter Code.
- Fix: JoinGuide bekommt host, port, playerName; Schritt 4 verweist auf "dein Passwort", das verdeckt und kopierbar in der Karte steht.
- Commit: 47242b5

**3. [Plan-Detail] store.get_meta/set_meta existierten schon (03-04)**
- Stattdessen kam `group_invited_worlds(gids)` in store.py hinzu.

Sonst wie geplant. Hinweis TDD: Tests und Implementierung von Task 1 entstanden in einem Schritt und sind in einem Commit (Plan-Commitvorgabe), kein separater RED-Commit.

## Known Stubs

Keine.

## Threat Flags

Keine neuen Flächen außerhalb des Threat-Models (T-03-39 bis T-03-44 umgesetzt bzw. akzeptiert).

## Next Phase Readiness

- 03-07 (Phasenabnahme): Kind-Ansicht und Einstellung sind live im Dev-Stack; Anleitungsbeschriftungen (A6) mit echtem Client prüfen.

## Self-Check: PASSED
