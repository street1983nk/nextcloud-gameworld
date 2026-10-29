---
phase: 06-store-release
plan: 27
subsystem: frontend, tooling, config
tags: [d-26, comments, english, frontend, shell, ci, config, repo-sweep, nextcloud-33]
requires: ["06-24", "06-25", "06-26", "06-28"]
provides:
  - "Kommentare in frontend/src, frontend/tests, vite.config.js, scripts/, Dockerfile, Workflows, Compose-/nginx-Dateien, pyproject.toml, .gitattributes, .dockerignore, webplay und info.xml Englisch"
  - "vendor/games/README.md Englisch (Tabellenzellen zeichengleich)"
  - "Repo-weite Abschluss-Suche (D-26/D-29): 278 Dateien, kein Treffer in Log-Aufrufen, jeder Kommentar-Treffer in einer der vier Restlisten, Abgleich in beide Richtungen"
  - "Nextcloud-Minimum 33 (info.xml, drei READMEs, zwei Installationsanleitungen, Store-Listing) mit neuem Konsistenztest"
affects: []
tech-stack:
  added: []
  patterns:
    - "Scratchpad-Werkzeuge (nicht committet): Übersetzungstabelle Datei:Zeile -> neuer Kommentartext mit Prüfung des Zeilenmusters, Zeilen-Diff-Beleg gegen BASE, Token-Vergleich der Bundles, Abschluss-Suche per tokenize/ast"
key_files:
  created:
    - .planning/phases/06-store-release/06-27-residuals.tsv
  modified:
    - "37 Dateien unter frontend/src, frontend/tests, frontend/vite.config.js"
    - "30 Dateien unter scripts/, Dockerfile, .github/workflows"
    - pyproject.toml
    - .gitattributes
    - .dockerignore
    - vendor/games/README.md
    - webplay/play.js
    - webplay/play.html
    - appinfo/info.xml
    - src/gameworld/play/__init__.py
    - README.md
    - README.de.md
    - README.fr.md
    - docs/install.md
    - docs/install.de.md
    - docs/store-listing.md
    - tests/test_docs.py
    - tests/test_info_xml.py
    - .planning/phases/06-store-release/06-26-residuals.tsv
    - .planning/phases/06-store-release/deferred-items.md
decisions:
  - "Bundle-Beleg als Token-Vergleich statt Hash: scoped-CSS-Kennungen und Minifier-Kurznamen ändern sich bei Kommentaränderungen in .vue-Dateien zwangsläufig (siehe Abweichungen)"
  - "info.xml-Store-Beschreibungen wurden beim NC-33-Wechsel mitgeändert, weil test_store_listing_matches_info_xml sie wortgleich an docs/store-listing.md bindet"
  - "PLATT-01 nicht abgehakt: Store-Eintrag und Store-Installation (06-13 bis 06-16) haben noch kein SUMMARY"
metrics:
  duration: "ca. 1 Stunde 10 Minuten (davon ca. 7 Minuten Volltest, 4 Minuten Docker-E2E)"
  completed: "2026-10-29"
  tasks: 3
  files: 83
---

# Phase 6 Plan 27: Übersetzungs-Pass Frontend, Tooling und Projektdateien Summary

Alle Kommentare in Oberfläche, Prüfskripten, Shell- und Abnahmeskripten, Compose-, nginx-, Docker- und Workflow-Dateien, Projekt- und Ignore-Dateien, Browser-Spike-Seite und info.xml sind Englisch; Code und Ausgaben sind nachweislich unverändert, die repo-weite Abschluss-Suche belegt den vollständigen D-26-Pass. Zusätzlich hebt ein eigener Commit das Nextcloud-Minimum von 32 auf 33.

**Basis-ID:** 81dad7b114966365771bd966f41df80f1e1754db (Kopf vor dem Plan)

## Commits

| Schritt | Commit | Inhalt |
|---------|--------|--------|
| Task 1 | e5cb623 | refactor(06-27): Frontend-Kommentare (src, tests, vite.config), 37 Dateien, 392 Zeilen 1:1 ersetzt |
| Task 2 | 2e48fad | refactor(06-27): Kommentare in scripts, Compose, Dockerfile, Workflows, 30 Dateien, 972 Zeilen 1:1 ersetzt |
| Task 3 | 76c2419 | refactor(06-27): Projekt-/Ignore-Dateien, webplay, info.xml-Kommentare, vendor-README, Restlisten |
| Zusatz | eca26b0 | chore(06-27): Nextcloud-Minimum auf 33 (Owner-Entscheid 29.10.2026) |

## Belege

**Bundle (Task 1).** `js/` steht in `.gitignore`, Bundle und Source-Map sind nicht im Git (der Plan ging von getrackten Dateien aus).

| | sha256 js/gameworld-main.js | sha256 js/gameworld-main.js.map |
|---|---|---|
| vorher (Basisstand, in-place gebaut) | b6d3d66af511d26253b4f02abd7cc161214605223fb7d36ed991c6412e9306cc | dd5abce6780e4c41a465aae315849e64c677352857c6f014c7ad9e3da9af538f |
| nachher | f5db5a40c2c5f5339a40d8079869cf61aa2b9a37ccb822e3f1f5eb0518e108ca | a3e571bb67e44413454af55fb4e8807d00f7be54a3ef665a138408272680625c |

Die Hashes sind verschieden. Token-Vergleich der beiden Bundles (gleiche Länge 1235354 Bytes, je 610002 Token):

- 216 abweichende Token, alle sind Bezeichner von höchstens 3 Zeichen, die in 108 Paaren konsistent umbenannt sind (Minifier-Kurznamen, etwa `eL` zu `e7`); kein Nicht-Bezeichner weicht ab.
- Die 56 verschiedenen scoped-CSS-Kennungen (`data-v-xxxxxxxx`, 948 Vorkommen) bleiben 56; 24 davon haben einen neuen Wert (die Komponenten mit geänderten Kommentaren). Die Zuordnung alt zu neu ist über alle Vorkommen konsistent.
- Ursache: Vue leitet die Kennung im Produktionsbuild aus Pfad plus Quelltext der .vue-Datei ab; jede Kommentaränderung in einer SFC ändert sie. Byte-Gleichheit ist damit bei Kommentarübersetzung in .vue-Dateien nicht erreichbar.
- Baseline-Reproduzierbarkeit: Zwei Builds des Basisstands in place ergaben denselben Hash (b6d3...). Ein Build aus einem anderen Verzeichnis oder nach einem `git checkout` (autocrlf, alle Dateien CRLF) ergibt einen anderen Hash, siehe deferred-items.md.

Zeilenzahl: `git diff --numstat` zeigt für jede Frontend-Datei gleich viele Einfügungen wie Löschungen (392/392); `tests/test_frontend_i18n.py` und `tests/test_frontend_privacy.py` zusammen 74 grün. Alle 9 Node-Prüfskripte (`frontend/tests/*.check.mjs`) grün.

**Zeilen-Diff-Beleg gegen 81dad7b** (Scratchpad-Skript, jede geänderte Zeile alt und neu ist reine Kommentarzeile, Zeile innerhalb eines Kommentarblocks oder hat ein byte-gleiches Präfix vor dem Kommentarteil; Zeilenzahl je Datei gleich):

- scripts/, Dockerfile, .github/workflows (30 Dateien): 972 geänderte Zeilen, 0 Verstöße.
- pyproject.toml 3, .gitattributes 2, .dockerignore 2, webplay/play.js 28, webplay/play.html 1, appinfo/info.xml 34 geänderte Zeilen, 0 Verstöße.
- appinfo/info.xml zusätzlich: Elementbaum ohne Kommentare vorher gleich nachher (True). pyproject.toml: `tomllib`-Ergebnis vorher gleich nachher (True).
- vendor/games/README.md: 4 Tabellenzeilen (Kopf plus Trennzeile plus 2 Zeilen), Zeilen 2 bis 4 zeichengleich zur Basis, Gesamtzeilenzahl 15 gleich.

**Syntaxchecks:** `sh -n` für alle 20 .sh unter scripts/; `node --check` für scripts/dev/*.mjs und webplay/play.js; `docker compose config -q` für compose.yaml, harp.compose.yaml (mit Dummy-Schlüssel), devfront.compose.yaml, harp-probe.compose.yaml (mit Dummy-Werten): alle ok; `docker buildx build --check .`: keine Warnungen; tomllib-Parse und XML-Parse ok.

**Repo-weite Abschluss-Suche** (Scratchpad `sweep.py`: tokenize/ast für Python, `//` und `/* */` für JS/Vue, `<!-- -->` für XML/HTML/Vue, `#` für Shell/YAML/TOML/Dockerfile/Ignore-Dateien, `--` in Lua-Konstanten; Zitate in Anführungszeichen ausgenommen; Merkmale: Umlaute, ß, ASCII-Umschriften, Funktionswortliste aus 06-25 Schritt 8; Positivkontrolle: auf den Basisständen von api.js 55, ParentView.vue 51, Dockerfile 29, info.xml 29, play.js 23 Treffer, backup/service.py (Erststand) 43 Treffer inklusive Log-Konstanten):

- 278 Dateien geprüft, 6 Treffer, davon 0 in Log-Aufrufen.
- Zuordnung: 06-25-residuals.tsv 1, 06-26-residuals.tsv 3, 06-27-residuals.tsv 1, 06-28-residuals.tsv 1. Treffer ohne Eintrag 0, Eintrag ohne Treffer 0.
- Zwei Funde der Suche wurden behoben (Rule 1, siehe unten).

**Tests und Gates:** `ruff check` und `ruff format --check` (207 Dateien) grün, `pyright` (latest) 0 Fehler, `vulture` ohne Funde, `pytest -m "not docker" -q`: 2868 bestanden, 52 abgewählt, 0 Fehler (6 Min 48 s).

**Docker-Tests (Engine 29.5.2):** `pytest -m docker` für `tests/e2e/test_play_proxy_e2e.py`, `test_play_srp_e2e.py`: 7 bestanden. `tests/e2e/test_mod_syntax_e2e.py`: 8 übersprungen (das gepinnte Luanti-Image hat keinen Lua-Compiler, die Tests springen mit Begründung an). Ersatz `tests/e2e/test_time_mod_e2e.py` und `test_access_e2e.py` (Welt-Start parst init.lua): 5 bestanden. Damit ist der offene Punkt aus 06-26 nachgeholt (Eintrag in deferred-items.md).

## Nextcloud-Minimum 33 (Zusatzauftrag, Commit eca26b0)

Geänderte Stellen (alle Zeilennummern wie im Commit; alt zu neu):

| Datei:Zeile | alt | neu |
|-------------|-----|-----|
| appinfo/info.xml:177 | `<nextcloud min-version="32" max-version="35"/>` | `<nextcloud min-version="33" max-version="35"/>` |
| appinfo/info.xml:76 | `- Nextcloud 32 to 35 with AppAPI and a HaRP deploy daemon` | `- Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon` |
| appinfo/info.xml:110 | `- Nextcloud 32 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` | `- Nextcloud 33 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` |
| appinfo/info.xml:144 | `- Nextcloud 32 à 35 avec AppAPI et un démon de déploiement HaRP` | `- Nextcloud 33 à 35 avec AppAPI et un démon de déploiement HaRP` |
| README.md:8 | Badge `Nextcloud-32--35` | `Nextcloud-33--35` |
| README.md:80 | `- Nextcloud 32 to 35 with AppAPI and a HaRP deploy daemon` | `- Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon` |
| README.de.md:8 | Badge `Nextcloud-32--35` | `Nextcloud-33--35` |
| README.de.md:79 | `- Nextcloud 32 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` | `- Nextcloud 33 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` |
| README.fr.md:8 | Badge `Nextcloud-32--35` | `Nextcloud-33--35` |
| README.fr.md:81 | `- Nextcloud 32 à 35 avec AppAPI et un démon de déploiement HaRP` | `- Nextcloud 33 à 35 avec AppAPI et un démon de déploiement HaRP` |
| docs/install.md:23 | `- Nextcloud 32 to 35 with the AppAPI app and a HaRP deploy daemon. ...` | `- Nextcloud 33 to 35 with the AppAPI app and a HaRP deploy daemon. ...` |
| docs/install.de.md:23 | `- Nextcloud 32 bis 35 mit der App AppAPI und einem HaRP-Deploy-Daemon. ...` | `- Nextcloud 33 bis 35 mit der App AppAPI und einem HaRP-Deploy-Daemon. ...` |
| docs/store-listing.md:83 | `- Nextcloud 32 to 35 with AppAPI and a HaRP deploy daemon` | `- Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon` |
| docs/store-listing.md:130 | `- Nextcloud 32 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` | `- Nextcloud 33 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon` |
| docs/store-listing.md:177 | `- Nextcloud 32 à 35 avec AppAPI et un démon de déploiement HaRP` | `- Nextcloud 33 à 35 avec AppAPI et un démon de déploiement HaRP` |
| tests/test_docs.py:191 (vorher 190) | `assert "Nextcloud-32--35" in text` | `assert "Nextcloud-33--35" in text` |
| tests/test_info_xml.py:114 | `assert nextcloud.get("min-version") == "32"` | `assert nextcloud.get("min-version") == "33"` |

Neu: `tests/test_docs.py::test_minimum_nextcloud_version_matches_info_xml` liest min- und max-version aus info.xml und prüft, dass jede README genau ein Badge `Nextcloud-<min>--<max>` und genau eine Voraussetzungszeile, die Installationsanleitungen genau eine Zeile und das Store-Listing eine je Sprache mit `Nextcloud <min> to|bis|à <max>` tragen. Negativkontrolle: README.de.md Zeile 79 kurz auf 32 gesetzt, Test schlug fehl, zurückgesetzt, Test grün.

Bewusst nicht angefasst (Begründung, Details in deferred-items.md): HaRP-Aussagen "NC 32+" in CLAUDE.md (Zeilen 28, 59, 76, 96, 104), `.planning/REQUIREMENTS.md` Zeile 56 (PLATT-01 "Ziel NC 32+", Planungsdokument), die ignorierte, von `harp-install.sh` erzeugte `.dev/info-harp.xml`.

CI-Matrix mit NC-Versionen: bestätigt, es gibt keine. Die einzige `matrix` steht in `.github/workflows/luanti-wasm.yml` (Build-Varianten a und b, keine NC-Version), `image.yml` hat keine. Die Dev-Compose-Dateien (`scripts/dev/compose.yaml`, `scripts/dev/harp.compose.yaml`) nutzen beide `nextcloud:34.0.3-apache`, das liegt im Fenster 33 bis 35.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Docstring in src/gameworld/play/__init__.py war noch Deutsch**
- **Found during:** Task 3, repo-weite Abschluss-Suche
- **Issue:** `"""Browser-Spike 04.2: Spielseite, Ticket und WebSocket-zu-UDP-Proxy ..."""` war in 06-26 übersehen worden.
- **Fix:** Übersetzt (`Browser spike 04.2: play page, ticket and WebSocket-to-UDP proxy ...`), nur Docstring.
- **Files modified:** src/gameworld/play/__init__.py
- **Commit:** 76c2419

**2. [Rule 1 - Bug] Drei veraltete Einträge in 06-26-residuals.tsv**
- **Found during:** Task 3, Abgleich in beide Richtungen
- **Issue:** `engine.py:139`, `pause.py:93`, `pause.py:173` waren laut ihrem eigenen Grund Falschtreffer der damaligen Anführungszeichen-Filterung und treffen unter der Filterung dieser Suche nicht (Eintrag ohne Treffer = Fehler).
- **Fix:** Die drei Zeilen entfernt; die drei time_mod.py-Einträge bleiben.
- **Files modified:** .planning/phases/06-store-release/06-26-residuals.tsv
- **Commit:** 76c2419

### Abweichungen von Planannahmen

**3. Bundle nicht byte-gleich und nicht im Git.** Siehe Abschnitt Belege: Die Annahme "sha256 vorher gleich nachher" und `git diff --quiet BASE -- js/gameworld-main.js` ist für .vue-Kommentarübersetzung strukturell nicht erfüllbar (data-v-Kennung hängt am Quelltext) und ohne Aussage (js/ ist ignoriert). Ersatzbeleg: Token-Vergleich mit konsistenter Umbenennung, 0 Nicht-Bezeichner-Abweichungen. Die Source-Map wurde nicht committet, weil sie nicht im Git liegt.

**4. info.xml-Store-Beschreibungen mitgeändert.** Der Zusatzauftrag nannte nur `min-version` in info.xml. Die drei `<description>`-Zeilen mit "Nextcloud 32 to 35" sind wortgleich an docs/store-listing.md gebunden (`test_store_listing_matches_info_xml`); eine Änderung nur im Listing hätte den Test gebrochen und die Store-Texte auseinanderlaufen lassen. Beide Seiten wurden gemeinsam geändert.

**5. vendor/games/README.md: Tabellenzellen bleiben teils deutsch.** Der Plan verlangt zeichengleiche Tabellenzellen. Dadurch stehen "Paket", "Medien" und "vom" in den Zellen der Zeilen 5 und 6 weiterhin deutsch (Überschriften, Spaltenköpfe und Fließtext sind Englisch). Ein Wechsel auf "package", "media", "from" ist ein Zwei-Wort-Eingriff, wenn der Owner ihn will.

## Offene Punkte

- `.planning/REQUIREMENTS.md` Zeile 56 nennt "Ziel NC 32+" (nicht geändert, Planungsdokument).
- PLATT-01 nicht abgehakt: 06-25 bis 06-28 sind durch, aber der Requirement-Text verlangt Installierbarkeit über den Store; 06-13 (Store-Texte und Screenshots), 06-14, 06-15 (Store-Installation) und 06-16 haben noch kein SUMMARY.
- `.planning/config.json` hat weiter die fremde, nicht committete Änderung (nicht angefasst).
- Lua-Syntaxtest bleibt ohne Lua-Compiler im Image inaktiv (Ersatz grün).
- Nicht gepusht.

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche. T-06-99 und T-06-105: Zeilen-Diff, Syntaxchecks, TOML- und XML-Parse, `ruff check`, `test_image_build.py` und `test_orphans_script.py` (32 bestanden) belegen die Minderung.

## Self-Check: PASSED

- Commits vorhanden: e5cb623, 2e48fad, 76c2419, eca26b0 (`git log`).
- Dateien vorhanden: 06-27-residuals.tsv, 06-27-SUMMARY.md, vendor/games/README.md, tests/test_docs.py (neuer Test).
- Volle Suite grün (2868 bestanden), Gates grün.
