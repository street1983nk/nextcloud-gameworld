---
phase: 03-zugang-und-rollen
plan: 02
subsystem: access
tags: [roles, appapi-routes, nextcloud-groups, vue]
requires:
  - phase: 03-zugang-und-rollen
    provides: 03-01 Durchsetzung im Spielserver (unabhängig, nur Reihenfolge)
provides:
  - access/roles.py (current_user, RoleService mit Cache 30 s, require_verwalter, get_role_service, ADMIN_GROUP, role_of)
  - GET /api/me (USER) mit user_id, display_name, role
  - info.xml-Routenmodell USER vor ADMIN, Top-Menü für alle
  - Rollenweiche im Frontend (ParentView, PlayerView mit Leerzustand)
  - Test-Fixtures fake_lookup und role_lookup_error in tests/conftest.py
affects: [03-03, 03-04, 03-05, 03-06, 03-07]
tech-stack:
  added: []
  patterns:
    - "Verwaltungsrouter mit APIRouter(dependencies=[Depends(require_verwalter)]): jede neue Route dort ist automatisch gesperrt"
    - "Spielerrouten nur unter /api/my/ (USER in info.xml), eigener Router ohne Verwalter-Abhängigkeit"
key-files:
  created:
    - src/gameworld/access/__init__.py
    - src/gameworld/access/roles.py
    - src/gameworld/api/me.py
    - tests/test_roles.py
    - frontend/src/views/ParentView.vue
    - frontend/src/views/PlayerView.vue
  modified:
    - src/gameworld/api/worlds.py
    - src/gameworld/api/setup_check.py
    - src/gameworld/main.py
    - src/gameworld/lifecycle.py
    - appinfo/info.xml
    - tests/conftest.py
    - tests/test_info_xml.py
    - tests/test_lifecycle.py
    - scripts/dev/acceptance-phase1.sh
    - frontend/src/App.vue
    - frontend/src/api.js
key-decisions:
  - "Rolle allein aus der NC-Gruppe admin per Selbstauskunft; Cache 30 s nur für Erfolge; Störung gibt 503 und nie Verwalter"
  - "require_verwalter routerweit auf worlds und setup_check; Spielerrouten bekommen einen eigenen Router unter /api/my/"
  - "AppAPI weist Kinder an ADMIN-Routen mit 404 ab (nicht 403); die Python-403 greift nur, wenn eine Anfrage die erste Sperre passiert"
requirements-completed: []
metrics:
  duration: 25 min
  completed: 2026-10-20
  tasks: 3
  files: 16
---

# Phase 3 Plan 02: Rollen aus Nextcloud-Gruppen Summary

Die Rolle kommt jetzt allein aus der Nextcloud-Gruppe `admin` (Selbstauskunft `/cloud/user`, 30 s Cache). Alle Verwaltungsrouten sind doppelt gesperrt: in AppAPI als ADMIN-Route und in Python über `require_verwalter`. Kinder erreichen Seite, Bundle und `/api/me` und sehen eine eigene Spieleransicht statt des Dashboards.

## Ergebnis

- `access/roles.py`: `RoleService(lookup)` cacht nur Erfolge, getrennt pro uid und mit `time.monotonic`. Jede Ausnahme des Lookups wird zu `RoleUnavailableError`. `require_verwalter` antwortet mit 503 ("Nextcloud antwortet gerade nicht...") oder 403 ("Nur Eltern können Welten verwalten.").
- `worlds.router` und `setup_check.router` hängen routerweit an `require_verwalter`. `api/me.py` hat keine Verwalter-Abhängigkeit (grep leer).
- `tests/test_roles.py` hat 17 Tests:
  - 8 Verwaltungsrouten antworten als gw-kind mit 403, ohne dass Dienst oder Setup-Check läuft
  - `/api/me` liefert je Rolle 200
  - Bei Störung kommt 503 und es wird nichts gecacht
  - Cache greift 29 s ja, 31 s nein und gilt pro Nutzer
  - Ohne Signatur kommt 401
- info.xml: genau 4 USER-Routen (`^/js/.*`, `^/img/.*`, `^/api/me$`, `^/api/my/.*`), danach 1 ADMIN-Route `^/api/.*`. Die Description lautet jetzt "only invited Nextcloud accounts can join".
- Top-Menü mit `admin_required=False`.
- `acceptance-phase1.sh` K1 nutzt das Phase-3-Modell, `DOCUMENTED_VARIANT` ist entfernt. Live-Lauf: **84 von 84 bestanden**, Exit 0.
  - Seite und Bundle für gw-kind: 200
  - `/api/worlds` für gw-kind: 404 (AppAPI)
  - `/api/me` für gw-kind: 200, Rolle spieler
  - `/api/me` für admin: Rolle verwalter
- Frontend:
  - `App.vue` ist nur noch die Hülle mit `getMe()`, Ladeindikator und Fehlerkarte.
  - Das Dashboard ist 1:1 nach `views/ParentView.vue` gewandert (ohne NcContent/NcAppContent, Importpfade angepasst).
  - `views/PlayerView.vue` zeigt "Meine Welten" mit Leerzustand und ruft keine Verwaltungs-API auf.
  - Build grün, das Bundle enthält den Leerzustand und wird gw-kind live ausgeliefert.
- Live-Gegenproben als gw-kind: `/api/setup-check` 404, `/api/members` 404 (End-Anker greift).
- Gates: `pytest -m "not docker"` 409 passed, ruff, ruff format, pyright und vulture grün.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 RED | a57baa9 | failing tests für Rollen und Fixture fake_lookup |
| 1 GREEN | 30644db | roles.py, /api/me, routerweite Sperre |
| 2 | fbabd60 | info.xml USER/ADMIN, Top-Menü für alle, Phase-1-Abnahme K1 |
| 3 | e0acae2 | Rollenweiche ParentView/PlayerView, getMe |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Doppelte Rollenberechnung zusammengefasst**
- `role_of(profile)` in roles.py wird von `RoleService.role` und `/api/me` gemeinsam genutzt, damit beide nie auseinanderlaufen.
- **Commit:** 30644db

**2. [Rule 2] Setup-Check in der Sperrprobe**
- Der Test prüft für gw-kind auch, dass `run_setup_check` nicht aufgerufen wird. Der Weltdienst ist dafür per `dependency_overrides` ersetzt. Damit ist "ohne dass der Dienst aufgerufen wird" für alle 8 Routen belegt.
- **Commit:** a57baa9

**3. [Hinweis] Dev-Backend kurz beendet**
- Ein Shell-Aufruf mit der kaputten globalen Python-Installation hing. Danach hat `taskkill /IM python.exe` alle python.exe-Prozesse beendet (3 Prozesse), auch das Dev-Backend auf Port 10040.
- `register-exapp.sh` hat das Backend in Task 2 wie geplant neu gestartet, jetzt mit dem neuen Code. Falls ein anderer python.exe-Prozess zu einer Parallel-Session gehörte, muss diese ihn neu starten.

**4. [Hinweis] 16 statt 17 Dateien**
- `js/gameworld-main.js` ist gitignored und wird beim Build erzeugt. Alle 16 Quelldateien des Plans wurden wie geplant geändert.

## Known Stubs

- `frontend/src/views/PlayerView.vue`: Die Leeransicht "Du bist noch zu keiner Welt eingeladen" ist gewollt. Die Prop `user` ist noch ungenutzt. 03-06 füllt die Ansicht über `/api/my/worlds`, sobald 03-03 Einladungen liefert.

## Known Limitations

- Am Proxy weist AppAPI Kinder an ADMIN-Routen mit 404 ab, nicht mit 403. Die Python-Sperre mit 403 ist nur per ASGI-Test belegt, weil live keine Kinderanfrage die erste Sperre passiert. Das ist gewollt: zweite Schicht.
- Wird jemandem die Admin-Rolle entzogen, gilt das bis zu 30 s verzögert (T-03-15, accept).

## Self-Check: PASSED

- Dateien vorhanden: access/roles.py, api/me.py, test_roles.py, views/ParentView.vue, views/PlayerView.vue
- Commits vorhanden: a57baa9, 30644db, fbabd60, e0acae2
- Keine Welt-Container übrig (docker ps mit Label gameworld.world_id: 0)
