---
phase: 01-fundament
plan: 02
subsystem: exapp-registration, frontend
tags: [walking-skeleton, exapp, appapi, vue, top-menu]
requires: ["01-01"]
provides:
  - "appinfo/info.xml: ExApp-Manifest, Routen ^/js/.*, ^/img/.*, ^/api/.* alle ADMIN, Env GAMEWORLD_DOCKER_URL/GAMEWORLD_PORT_RANGE, NC 32-34"
  - "gameworld.lifecycle: api_base(), async enabled_handler (Top-Menü admin_required, Script, Initial State)"
  - "frontend/: Vue-3-Hülle (Vite 7.3.7, @nextcloud/vue 9.13.1), ein IIFE-Bundle js/gameworld-main.js"
  - "scripts/dev/register-exapp.sh: ein Befehl vom Compose-Stack zur aktivierten ExApp"
  - "scripts/dev/smoke.sh: automatisierter Durchstich Seite -> POST -> gehärteter Container -> Liste -> Aufräumen"
  - "docs/dev-setup.md"
affects: [01-03, 01-04, 01-05]
tech-stack:
  added: [vue 3.5.44, "@nextcloud/vue 9.13.1", "@nextcloud/axios 2.6.0", "@nextcloud/initial-state 3.0.0", "@nextcloud/router 3.2.0", "@nextcloud/vite-config 2.5.4", vite 7.3.7, typescript 5.9.3 (nur Build)]
  patterns: [Initial State über app_api mit JSON-Text, klassisches IIFE-Bundle statt ES-Modul, Routen-URLs kanonisch ^/pfad]
key-files:
  created:
    - appinfo/info.xml
    - img/app.svg
    - src/gameworld/lifecycle.py
    - frontend/package.json
    - frontend/package-lock.json
    - frontend/vite.config.js
    - frontend/src/main.js
    - frontend/src/App.vue
    - frontend/src/api.js
    - scripts/dev/register-exapp.sh
    - scripts/dev/smoke.sh
    - docs/dev-setup.md
    - tests/test_lifecycle.py
    - tests/test_info_xml.py
    - tests/test_frontend_privacy.py
  modified:
    - src/gameworld/main.py
decisions:
  - "Nicht-Admin-Verhalten: Variante A, TopMenuController.php:65 liefert Nicht-Admins NotFoundResponse (404); empirisch bestätigt, auch Bundle und API 404"
  - "Routen-URLs in kanonischer Form ^/js/.*, ^/img/.*, ^/api/.*; der nackte Pfad js\\/.* läuft in AppAPI 34 nur über einen veralteten Rückfall und in HaRP gar nicht"
  - "Frontend liest den Initial State mit loadState('app_api', 'gameworld_config') und parst den JSON-Text; AppAPI stellt ihn im Namen von app_api und doppelt kodiert bereit"
  - "Bundle als ein IIFE-Skript js/gameworld-main.js mit eingebettetem CSS: AppAPI hängt .js an und Nextcloud setzt type=module nur bei .mjs"
  - "licence AGPL-3.0-or-later statt agpl (SPDX, ab NC 31 erlaubt, agpl ist im Schema als veraltet markiert; gleich wie pyproject.toml)"
  - "typescript 5.9.3 als devDependency gepinnt: sonst zieht npm typescript 7.0.2 (ohne JS-API) als optionalen Peer von vue, und vite-plugin-dts bricht beim Laden der Konfiguration"
metrics:
  duration: "32 min"
  completed: "2026-10-19"
  tasks: 2
  files: 16
---

# Phase 1 Plan 02: ExApp-Registrierung und Vue-Hülle Summary

Gameworld ist in der Dev-Nextcloud (8091) als ExApp registriert und aktiviert, steht für Admins im Top-Menü, und ein Klick auf "Welt erstellen" erzeugt über AppAPI-Proxy, ExApp, SQLite und Docker-Proxy einen laufenden, gehärteten Luanti-Container, der mit Status "läuft" in der Liste erscheint. Der Weltschlüssel wird einmalig nach der Erstellung gezeigt, nie in der Liste.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 (RED) | Tests für Manifest und Lifecycle | 8a154b9 |
| 1 | ExApp-Manifest, Lifecycle-Registrierung, Registrierungsskript, Dev-Doku | e891889 |
| 2 | Vue-Hülle, Smoke-Skript, Privacy-Test | 627860b |
| Nachtrag | Dev-Doku: Node-Engine und abgeschalteter Einrichtungsassistent | dfb72b2 |

## Nicht-Admin-Verhalten

**Variante A gilt.** Der Controller der Route `/embedded/{appId}/{name}` setzt `admin_required` serverseitig durch.

Beleg aus dem Controller-Grep im Dev-Container (AppAPI 34.0.0 in Nextcloud 34.0.3):

```
/var/www/html/apps/app_api/lib/Controller/TopMenuController.php:65:
  if (filter_var($menuEntry->getAdminRequired(), FILTER_VALIDATE_BOOLEAN) && !$this->groupManager->isAdmin($this->userId)) {
      return new NotFoundResponse();
```

Gegenprobe mit einem Wegwerf-Nutzer ohne Adminrechte (danach per occ gelöscht):

| URL | Nicht-Admin |
|-----|-------------|
| `/index.php/apps/app_api/embedded/gameworld/gameworld` | 404 |
| `/index.php/apps/app_api/proxy/gameworld/js/gameworld-main.js` | 404 |
| `/index.php/apps/app_api/proxy/gameworld/api/worlds` | 404 |

Die Proxy-Routen prüft `ExAppProxyController::passesExAppProxyRouteAccessLevelCheck` (ADMIN = `isAdmin`). Plan 01-05 (K1, Playwright-Schritt 8) kann also die strenge Variante A prüfen: weder Seite noch Bundle noch API liefern einem Nicht-Admin 200. Eine eigene Rollenprüfung in Python gibt es nicht (Phase 3).

## Script-Einbindung durch AppAPI

- `ScriptsService.php` registriert jedes per `set_script` gesetzte Skript als `proxy_js/<n>` über `Util::addScript`.
- `ExAppUiMiddleware.php` schreibt das `src` auf `/index.php/apps/app_api/proxy/gameworld/<pfad>.js` um, hängt also `.js` an.
- Nextcloud setzt `type="module"` nur bei `.mjs` (`lib/private/Template/functions.php:87`). Das Skript läuft also klassisch.
- Folge: `vite.config.js` baut genau eine Datei `js/gameworld-main.js` im Format IIFE mit eingebettetem CSS (`inlineCSS`) und ohne Chunks (`inlineDynamicImports`). Der Default von `@nextcloud/vite-config` (`.mjs`, Chunks über `OC.filePath`) würde hier nicht laden.

## Verifikation

- `sh scripts/dev/smoke.sh`: Exit 0. Seite 200 und referenziert gameworld-main, Bundle über den Proxy 200, POST 201, Container `true 536870912 536870912 128 ["ALL"] true`, Liste zeigt `running`, danach aufgeräumt (0 Container mit `gameworld.managed=true`).
- Browserprüfung mit Playwright (headless Chromium, Skript im Scratchpad): Login als Admin, Seite öffnen, Namen eingeben, "Welt erstellen" klicken; Erfolgskarte mit Weltschlüssel, Zeile mit UDP-Port 30000 und Status "läuft", Schlüssel nicht in der Tabelle, keine Seitenfehler. Testwelt danach entfernt.
- `uv run pytest -q`: 55 passed. ruff check, ruff format --check, pyright (0 errors, latest), vulture: alle Exit 0.
- `npm --prefix frontend ls`: vite@7.3.7, @nextcloud/vue@9.13.1.
- grep-Gates: ADMIN-Anzahl = Routen-Anzahl = 3; `announce|public` in info.xml leer; `announce|serverlist|visibility` in frontend/src leer; kein `12345` im Registrierungsskript.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Initial State liegt unter app_api und ist doppelt kodiert**
- **Found during:** Task 2
- **Issue:** `TopMenuController` gibt den Initial State über das `IInitialState` von app_api aus (`initial-state-app_api-gameworld_config`) und der Wert ist ein JSON-Text im JSON. `loadState('gameworld', ...)` aus dem Plan hätte immer den Fallback geliefert.
- **Fix:** `api.js` liest `loadState('app_api', 'gameworld_config', fallback)` und parst einen String-Wert. Der key_link-Pattern `loadState\('gameworld'` aus dem Plan-Frontmatter trifft deshalb bewusst nicht.
- **Commit:** 627860b

**2. [Rule 1 - Bug] Routen-URLs in kanonischer Form**
- **Found during:** Task 1
- **Issue:** `ExAppProxyController::passesExAppProxyRoutesChecks` prüft gegen den Pfad mit führendem Schrägstrich; `js\/.*` greift nur über einen als veraltet markierten Rückfall, HaRP kennt den Rückfall nicht (gleiche Lehre wie Findling 06.1-19).
- **Fix:** `^/js/.*`, `^/img/.*`, `^/api/.*`; test_info_xml prüft diese Form.
- **Commit:** e891889

**3. [Rule 1 - Bug] Bundle-Format passend zur AppAPI-Einbindung**
- **Found during:** Task 2
- **Fix:** IIFE-Einzeldatei statt ES-Modul mit Chunks (siehe "Script-Einbindung").
- **Commit:** 627860b

**4. [Rule 3 - Blocking] typescript 5.9.3 gepinnt**
- **Issue:** npm löste den optionalen Peer typescript von vue auf 7.0.2 auf; vite-plugin-dts (über @nextcloud/vite-config) bricht damit beim Laden der Konfiguration (`useCaseSensitiveFileNames` undefined).
- **Fix:** `typescript@5.9.3` exakt als devDependency (Version stand schon im Baum über @microsoft/api-extractor, Paket per `npm view` geprüft, Maintainer Microsoft).
- **Commit:** 627860b

**5. [Rule 3 - Blocking] REUSE-Lizenz-Plugin abgeschaltet, eigenes Leeren von js/**
- **Issue:** Mit `outDir` außerhalb von frontend/ lief der Build in "JavaScript heap out of memory" (gemessen, Ursache isoliert: ohne das Plugin baut er in 3 s). Das EmptyJSDir-Plugin hätte zudem frontend/js statt js/ geleert.
- **Fix:** `extractLicenseInformation: false`, `emptyOutputDirectory: false`, stattdessen `build.emptyOutDir: true` auf `../js`. Lizenzangaben der Abhängigkeiten folgen mit dem Image in Phase 6.
- **Commit:** 627860b

**6. [Rule 3 - Blocking] Einrichtungsassistent in der Dev-Nextcloud abgeschaltet**
- **Issue:** firstrunwizard legt sich beim ersten Login über jede Seite und fängt alle Klicks ab (Playwright-Klick auf "Welt erstellen" lief in den Timeout).
- **Fix:** register-exapp.sh ruft `occ app:disable firstrunwizard` (nur Dev-Stack). Hilft auch Plan 01-05.
- **Commit:** 627860b

**7. [Rule 2 - Kritisch] Smoke-Skript räumt auch die Datenbankzeile weg**
- **Issue:** Ohne Lösch-API (kommt in 01-03) bliebe pro Lauf eine Welt in der Dev-SQLite und belegte einen der 20 UDP-Ports; nach 20 Läufen wäre jeder POST 503.
- **Fix:** EXIT-Trap entfernt Container, Volume und die Zeile in `.dev/storage/gameworld.sqlite3`, auch nach einem Fehler. Weltname mit Zeitstempel, damit Läufe nicht kollidieren.
- **Commit:** 627860b

**8. [Rule 2 - Kritisch] npm ci ohne Install-Skripte, Stale-Prüfung angepasst**
- `npm ci --ignore-scripts` im Registrierungsskript (T-01-SC).
- Findlings Stale-Prüfung liest die Version über eine /status-Route, die Gameworld nicht hat. Ersatz: Version beim Start in `.dev/exapp.version`, Neustart bei neueren `src/**/*.py` als die PID-Datei und bei einer signierten `api/worlds`-Antwort ungleich 200.
- **Commit:** e891889, 627860b

### Kleinere Abweichungen

- `licence` ist `AGPL-3.0-or-later` statt `agpl` (SPDX, Schema-Hinweis "deprecated" für agpl, ab NC 31 erlaubt, identisch mit pyproject.toml).
- Signatur `enabled_handler(enabled, nc: AsyncNextcloudApp)`; in main.py wird der Handler per `cast` an die Union-Signatur von `set_handlers` angepasst (nc_py_api reicht Coroutine-Funktionen immer AsyncNextcloudApp herein, integration_fastapi.py:125-129).
- Button-Text "Welt erstellen" wurde in der flexiblen Zeile abgeschnitten; `flex-shrink: 0` ergänzt.

## Hinweise

- `npm audit`: 12 Befunde (6 low, 6 moderate), u. a. elliptic und sprintf-js, alle in Build-Abhängigkeiten. Nicht im Bundle relevant geprüft, Bewertung im Phasen-Audit.
- `@nextcloud/files@4.1.0` und `rollup-plugin-node-externals@9.0.1` verlangen laut Engine-Angabe Node 24; der Build läuft mit Node 22.21.0 und warnt nur (in docs/dev-setup.md vermerkt).
- Zeilenenden: Git meldet LF->CRLF für die Shell-Skripte. Für den Image-Bau in Phase 6 eine `.gitattributes` mit `*.sh text eol=lf` vorsehen.
- Die Sourcemap `js/gameworld-main.js.map` (2,2 MB) wird mitgebaut und liegt wie das Bundle hinter der ADMIN-Route.

## TDD Gate Compliance

- RED: 8a154b9 `test(01-02): ...` (ModuleNotFoundError gameworld.lifecycle)
- GREEN: e891889 `feat(01-02): ...`
- REFACTOR: nicht nötig

## Known Stubs

Keine. Die UI ist bewusst eine schlichte Hülle (Dashboard-Design in Phase 2), aber vollständig an die echte API angebunden.

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat Models. T-01-10 ist strenger erfüllt als geplant (Variante A, Seite ebenfalls 404). T-01-11: Secret pro Lauf, kein festes Secret. T-01-12: Aufrufe über @nextcloud/axios mit requesttoken. T-01-14: test_frontend_privacy und grep auf info.xml. T-01-SC: exakte Versionen, package-lock.json committed, Installation mit `--ignore-scripts`.
