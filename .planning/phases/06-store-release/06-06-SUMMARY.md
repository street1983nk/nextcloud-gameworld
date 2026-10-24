---
phase: 06-store-release
plan: 06
subsystem: talk
tags: [talk, reconciler, ui-spec-b4, d-16, d-19]
requires: ["06-01", "06-04", "06-05"]
provides:
  - "TalkService._take_over_locked: owner_uid geht an den dienstältesten bestätigten Verwalter (verwalter_seniority), der den Raum sieht; Beförderung zum Moderator; former_owner = Ex-Verwalter als Talk-Owner"
  - "Sperrfall: kein Verwalter sieht den Raum -> neuer Raum (replace_talk_token), altes Token als orphaned_token, nie gelöscht"
  - "TalkService.recreate_room(world_id, acting): alter Raum gelöscht, neuer ohne Ex-Verwalter, Nur-lesen bleibt"
  - "store: set_talk_owner, set_talk_orphaned, replace_talk_token"
  - "POST /api/worlds/{world_id}/talk/recreate (404/409/503), GET /api/talk mit orphaned_token"
  - "TalkRoomStatus.vue B4: Warn-NoteCard mit Fokus, Knopf Raum neu anlegen, NcDialog-Bestätigung, Sperrfall-Hinweis mit occ-Befehl als code"
  - "playtime.js: formerOwnerText, recreateQuestion, RECREATED_TEXT, ORPHANED_BEFORE/AFTER, orphanedCommand, orphanedText; talkHint ohne Besitz-Versprechen"
  - "api.js recreateTalkRoom(worldId)"
affects: [06-12]
tech-stack:
  added: []
  patterns:
    - "Übernahme nur im Abgleich mit bestätigtem acting (take_over=acting is not None), CR-01"
    - "Neuer Raum für bestehende Zeile per UPDATE (replace_talk_token): Nur-lesen und orphaned_token bleiben, scheitert create bleibt alles beim Alten"
    - "Fokus-Wrapper div tabindex=-1 um NcNoteCard, Muster VerwalterGroupsSection"
key_files:
  created: []
  modified:
    - src/gameworld/talk/service.py
    - src/gameworld/worlds/store.py
    - src/gameworld/api/talk.py
    - tests/test_talk_service.py
    - tests/test_talk_api.py
    - frontend/src/components/TalkRoomStatus.vue
    - frontend/src/playtime.js
    - frontend/tests/playtime.check.mjs
    - frontend/src/api.js
decisions:
  - "Gameworld-Besitzer (talk_rooms.owner_uid) und Talk-Owner sind getrennt: owner_uid ist immer ein Verwalter nach Übernahme, former_owner hält den Ex-Verwalter fest, solange Talk ihn als Typ 1 führt"
  - "Kandidaten = verwalter_seniority gefiltert auf die bestätigte Vereinigung, danach noch nicht gesehene Verwalter nach Konto-ID (kein Sperrfall nur weil verwalter_seen noch leer ist)"
  - "Sperrfall nur, wenn der bisherige Besitzer kein Verwalter mehr ist; ist er noch Verwalter und sieht niemand den Raum, bleibt das alte Verhalten (Zeile löschen, Backfill legt neu an)"
  - "Neuer Raum im Sperrfall: Ersteller = dienstältester Verwalter (Plan), Ersteller bei Raum neu anlegen = handelnder Verwalter"
  - "recreate_room löscht zuerst; scheitert das Löschen, bleibt alles unverändert (503), Hinweis und Knopf bleiben"
  - "Status: owner_display = former_owner, sonst owner_uid solange noch nicht übernommen (Übergang bis zum nächsten Abgleich)"
  - "recreateQuestion ohne owner_display: 'der frühere Verwalter' als Platzhalter (UI-SPEC nennt nur die Variante mit Namen)"
metrics:
  duration: "ca. 45 min"
  completed: 2026-10-24
  tasks: 3
  files: 9
requirements: [ROLLE-03]
---

# Phase 6 Plan 06: Talk-Raum-Übernahme (D-16/D-19, UI-SPEC B4) Summary

Der 5-min-Abgleich gibt jedem Talk-Raum einen handlungsfähigen Gameworld-Besitzer (dienstältester bestätigter Verwalter, der den Raum sieht), meldet Ex-Verwalter, die in Talk Owner bleiben, und legt im Sperrfall einen neuen Raum an; Verwalter können den Raum nach Bestätigung neu anlegen, das falsche "Besitz übertragen"-Versprechen ist weg.

## Tasks

| Task | Name | Commit | Dateien |
|------|------|--------|---------|
| 1 | Übernahme im Abgleich, Sperrfall, recreate_room | 6d8752d | talk/service.py, worlds/store.py, tests/test_talk_service.py |
| 2 | Route Raum neu anlegen, orphaned_token im Status | cdee714 | api/talk.py, tests/test_talk_api.py |
| 3 | B4 in TalkRoomStatus.vue, talkHint ohne Besitz-Versprechen | 57e9829 | TalkRoomStatus.vue, playtime.js, playtime.check.mjs, api.js |

## Verifikation

- `uv run ruff check .`, `ruff format --check .`, pyright basic (latest, 0 errors), vulture: ohne Befund
- `uv run pytest -m "not docker" -q`: 2502 passed (nach Task 3)
- Neue Service-Tests (rohes SQLite als Gegenprobe): Ex-Verwalter bleibt Talk-Owner, Dienstalter statt Konto-ID, gelöschter Owner, Dienstältester blind -> zweiter wird Besitzer und befördert, Sperrfall (altes Token bleibt, kein delete, kein Token im Log), ohne bestätigtes acting keine Änderung (None, Ex-Verwalter, Kind; auch im Sperrfall kein create/delete), aktiver Verwalter-Besitzer bleibt, recreate_room (alter Raum weg, gw-alt nicht im neuen, Nur-lesen bleibt), recreate verweigert Nicht-Verwalter und lässt den Raum bei Talk-Fehler stehen
- Positivkontrolle: Übernahme testweise abgeschaltet -> 5 der neuen Tests rot, danach zurückgesetzt
- API-Tests: 200 mit neuer Statuszeile, 404, 409 (kein create), 503 mit festem Text (Raum bleibt), Kind 403 ohne Talk-Aufruf; Kind-Sperre der neuen Route im parametrisierten Test
- Frontend: `npm run build` grün, alle 7 `frontend/tests/*.check.mjs` grün, `tests/test_frontend_privacy.py` grün; `grep -c Besitz playtime.js` = 0, kein v-html, kein public/visibility neu

## Deviations from Plan

- **[Rule 2] Ergänzung store.replace_talk_token:** Neuer Raum für die bestehende Zeile per UPDATE statt delete_talk_room + ensure_room. Sonst gingen beim Sperrfall das alte Token und bei "Raum neu anlegen" der Nur-lesen-Stand verloren, wenn create scheitert. Commit 6d8752d.
- **[Rule 2] recreate_room nur für Konten der Verwalter-Vereinigung:** zweite Prüfung neben der routerweiten Sperre (T-06-25). Commit 6d8752d.
- **tests/conftest.py nicht geändert:** FakeTalkRooms reichte; "blinde" Konten simuliert der Test per eigener participants-Hülle.
- **TDD-Reihenfolge:** Tests und Umsetzung je Task in einem Commit; die Aussagekraft der Tests ist per Positivkontrolle belegt (siehe oben).

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Registers: die neue Route liegt hinter der routerweiten Verwalter-Sperre (T-06-25), löscht nur nach Bestätigung in der Oberfläche (T-06-24), Tokens nur per Textinterpolation (T-06-28), keine Log-Zeile mit Token (T-06-27, grep leer).

## TDD Gate Compliance

Plan-Typ execute (keine Plan-TDD); Task-TDD ohne separaten RED-Commit, siehe Abweichungen.

## Self-Check: PASSED

- Dateien vorhanden: alle 9 key_files geändert und committet
- Commits vorhanden: 6d8752d, cdee714, 57e9829
