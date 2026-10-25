---
phase: 06-store-release
plan: 24
subsystem: frontend, i18n, acceptance
tags: [i18n, d-25, d-27, structure-gate, umlaut-audit, leftover-german-audit, k8, docker]
requires: ["06-19", "06-20", "06-21", "06-22", "06-23"]
provides:
  - "WorldLanguageSetting.vue: Spielsprache je Welt (Deutsch, English, Français) in der Weltzeile, Neustart-Hinweis bei language_restart_needed, Rücksprung bei Fehler"
  - "setWorldLanguage(worldId, language) in api.js (POST /api/worlds/{id}/language)"
  - "Bereich world in de/en/fr (3 Schlüssel)"
  - "tests/test_frontend_i18n.py: Strukturtest (kein deutscher Harttext außerhalb frontend/src/i18n), Umlaut-Audit, Rest-Deutsch-Audit en/fr (Wörterbücher, Kataloge, Mod-, Benachrichtigungs- und Bot-Bündel, EN/FR-Doku), Typografie; je mit Positivkontrolle"
  - "tests/frontend_i18n_exceptions.tsv (12 Einträge) und tests/i18n_foreign_exceptions.tsv (8 Einträge), beide in beide Richtungen abgeglichen"
  - "K8 Sprache in scripts/dev/acceptance-phase6.sh"
affects: [06-13, 06-27]
tech-stack:
  added: []
  patterns:
    - "Eigener JS/Vue-Literal-Scanner ohne neue Abhängigkeit: Kommentare und Regex-Literale übersprungen, Template-Literale mit ${} gefaltet, Ausdrücke in {{ }} und gebundenen Attributen mitgelesen"
    - "Rest-Deutsch-Funde je (Datei, Schlüssel, Token); Doku-Dateien mit Schlüssel doc, Store-Listing nach Abschnitt en/fr"
    - "Abnahme-Fixtures mit Präfix gw6- neben einer laufenden Demo-Umgebung; Wegwerfkonten ausdrücklich core lang de"
key_files:
  created:
    - frontend/src/components/WorldLanguageSetting.vue
    - tests/test_frontend_i18n.py
    - tests/frontend_i18n_exceptions.tsv
    - tests/i18n_foreign_exceptions.tsv
  modified:
    - frontend/src/api.js
    - frontend/src/views/ParentView.vue
    - frontend/src/i18n/de/world.js
    - frontend/src/i18n/en/world.js
    - frontend/src/i18n/fr/world.js
    - frontend/tests/api.check.mjs
    - docs/install.md
    - docs/privacy.md
    - docs/dev-setup.md
    - scripts/dev/acceptance-phase6.sh
    - scripts/dev/acceptance-phase5.sh
    - scripts/dev/acceptance-phase4_1.sh
    - scripts/dev/acceptance-phase4.sh
    - scripts/dev/acceptance-phase3.sh
    - .planning/phases/06-store-release/deferred-items.md
decisions:
  - "Sprachnamen als Konstante in der Komponente (Deutsch, English, Français), nicht im Wörterbuch"
  - "Bundle js/gameworld-main.js gebaut und geprüft, aber NICHT committet: js/ ist gitignored und das Dockerfile baut es selbst (Kommentar 'nicht im Git'); Erzwingen per git add -f hätte die Repo-Regel gebrochen"
  - "Ausnahmen nur für Nicht-Anzeige-Werte (Seiten-IDs, API-Pfade, Preset-ID, Backend-Vergleichsmarken) und Eigennamen/Artefakte (Pfad Gameworld/Sicherungen, Sprachname Deutsch)"
  - "Phase-6-Abnahme auf gw6-* umbenannt: die alten Namen gw-lehrer, lehrkraefte, klasse gehören jetzt der Demo aus 06-13 (reset_fixtures hätte sie gelöscht und lehrkraefte als Verwalter-Gruppe entfernt)"
metrics:
  duration: "135 min"
  completed: "2026-10-25"
  tasks: 3
  files: 19
---

# Phase 6 Plan 24: Weltsprache in der Oberfläche, i18n-Strukturtest und K8 Summary

Verwalter wählen die Spielsprache je Welt in der Weltzeile; ein neuer Strukturtest belegt, dass außerhalb der Wörterbücher kein deutscher Harttext mehr steht, dass deutsche Werte echte Umlaute haben und dass in keinem en/fr-Wert und keiner EN/FR-Doku deutsche Reste stehen; K8 belegt D-25/D-27 am echten Dev-Stack.

**Basis-ID:** 89e4835057f0a27a1e8f509591ec53cae18c160b

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | cb7929f | WorldLanguageSetting.vue, setWorldLanguage, world-Wörterbücher, api.check-Fall |
| 2 RED | d15f7e1 | test_frontend_i18n.py mit leeren Ausnahmen-Tabellen (3 Tests rot) |
| 2 GREEN | d566ace | EN-Doku übersetzt, Ausnahmen-Tabellen |
| 3 | 87153b7 | K8, gw6-Fixtures, core lang de für Abnahmekonten (Phase 3 bis 6), dev-setup.md |
| 3 fix | 8f5eb1d | K8-Gegenprobe mit eigenem Literal (TEXT_HALT gab es nur in Phase 5, set -u brach ab) |
| 3 fix | ec5577c | K7 wartet auch beim ersten Raum auf den Mitglieder-Abgleich |
| 3 fix | 2d40ff3 | K8-Rückfall bei Tagesdrosselung, deferred-items |

## Audit-Ergebnisse

**Strukturtest (frontend/src außerhalb i18n):** 12 Funde, alle Nicht-Anzeige-Werte und in tests/frontend_i18n_exceptions.tsv mit Zeile und Grund: Seiten-ID `pause` (App.vue 30, route.js 16, ParentView.vue 17), Query-Parameter `welt` (route.js 66), API-Pfade `/api/pause`, `/api/pause/end`, `/api/pause/schluss` (api.js 258 bis 276), Preset-ID `keine` (PlaytimeDialog.vue 102, 110), Backend-Vergleichsmarken `noch von einem Container benutzt` (OrphanSection.vue 148) und `gibt es in Nextcloud nicht` (VerwalterGroupsSection.vue 125). Kein sichtbarer deutscher Harttext mehr in Komponenten.

**Umlaut-Audit:** ohne Fund (de-Wörterbücher, alle MSG_/TEXT_-Konstanten per AST, de-Bündel MOD_TEXTS, NOTIFY_TEXTS, BOT_TEXTS).

**Rest-Deutsch-Audit en/fr-Werte:** einziger Fund `Gameworld/Sicherungen` in parent.backup.hint (en und fr), Files-Pfad, Ausnahme mit Grund. Kataloge, Mod-, Benachrichtigungs- und Bot-Bündel ohne Fund.

**Rest-Deutsch-Audit EN/FR-Doku (Owner-Pflicht):** docs/install.md zitierte rund 60 deutsche Oberflächen-, Spiel-, Bot- und Setup-Check-Texte mit englischer Klammer (Stand vor D-25), dazu den Satz "The Gameworld interface is in German". Alles sofort übersetzt (Rule 1), Wortlaut aus den en-Wörterbüchern und catalog_en.py/MOD_TEXTS/BOT_TEXTS/NOTIFY_TEXTS übernommen (z. B. "Create world", "Check again", "Break for all children", "You are not invited to this world. Ask your parents.", "Build (creative)", "Adventure (gentle)"); Setup-Check-Tabelle jetzt "Message (as shown in English)". docs/privacy.md: "Reste früherer Installationen" -> "Leftovers from earlier installations". "Deutsche Fassung:" -> "Deutsch:" (Sprachname). Verbleibende Ausnahmen: Sprachname `Deutsch` (README.md, README.fr.md, install.md, privacy.md) und der Pfad `Gameworld/Sicherungen/...` (install.md, privacy.md). README.fr.md und die EN/FR-Abschnitte von store-listing.md ohne Fund.

**Positivkontrollen:** Scanner meldet "Bitte warten" (Template-Text), 'Welt gelöscht' (Skript-Literal), `Noch ${} Minuten` (Template-Literal), liest label="Speichern", ignoriert Kommentare und Wörterbuch-Schlüssel; Umlaut-Audit meldet fuer/Spaeter/loeschen/Zugaenge/ueber; Rest-Deutsch meldet je einen eingeschleusten Satz in en und fr, nicht aber "des joueurs", "Français"; Typografie meldet Gedankenstrich und Emoji; Sammler finden je Quelle bekannte Werte.

Der Scanner ist bewusst strenger als die Planliste (zusätzliche Wörter wie oder, sich, nur, mit, ein, auf, Raum, gibt und Stämme wie Beitritt, Ferien, Zeitzone, Schluss, Antwort, Fassung), weil die Planliste "Beitrittsversuche", "Neues Passwort", "Raum neu anlegen" oder "Proxy gibt Systeminformationen preis" in install.md nicht gefunden hätte.

## Bundle

`cd frontend && npm run build` grün (nur die bekannte Chunk-Größen-Warnung). `grep -c` in js/gameworld-main.js: "Language in the game" 1, "Langue dans le jeu" 1, "Sprache im Spiel" 1. Der Dev-Stack liefert genau dieses Bundle aus (GET .../proxy/gameworld/js/gameworld-main.js enthält "Langue dans le jeu"). Nicht committet, siehe Abweichungen.

## Gates

- `uv run ruff check`, `ruff format --check`, `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright` (0 errors), `uv run vulture`: grün
- alle zehn `node frontend/tests/*.check.mjs` grün (i18n.check: world 3 Schlüssel in de, en, fr)
- `uv run pytest -q tests/test_frontend_i18n.py tests/test_frontend_privacy.py tests/test_docs.py`: 109 passed
- `uv run pytest -m "not docker" -q`: 2867 passed, 44 deselected (7:05 min)

## K8 und Abnahmeläufe am Dev-Stack

Backend vorher per `sh scripts/dev/register-exapp.sh` auf den aktuellen Stand gebracht (lief seit 17:51 mit Code vor 06-22, ohne `language`); neues Secret, die Owner-Welten blieben laufen.

| Lauf | Umfang | Ergebnis |
|------|--------|----------|
| 1 | Phase 6 mit Regression | Abbruch in K8 (Skriptfehler TEXT_HALT unbound, 8f5eb1d); K7 zweiter Raum rot |
| 2 | Phase 6 mit Regression | **165 von 171**; K8 vollständig grün inkl. Einzelhinweis en/de; K7 erster Raum rot (Wettlauf, ec5577c); Regression: Phase 5 96/96, 4 103/103, 3, 2 und 1 grün, Phase 4.1 119 von 128 (Demo-Konflikt, siehe unten) |
| 3 | Phase 6 ohne Regression | 160 von 165; K7 zweiter Raum (bekannter Befund 06-12), K8 Punkt 8 Rückfall griff zu kurz (2d40ff3) |
| 4 | Phase 6 ohne Regression | **165 von 165, "Phasenabnahme Phase 6 erfolgreich (Modus manual)", Exit 0** |

Vorher 130 Prüfungen (06-12), jetzt 165 in Phase 6 selbst (36 davon K8 in Lauf 4, 39 in Lauf 2 mit Einzelhinweisen).

**K8 im Einzelnen (alle acht Punkte bestanden, Lauf 2 und 4):** 1. /api/me gw6-en `en`, gw6-lehrer `de`. 2. gw6-kind-en 403 "Only parents can manage worlds.", deutsches Kind exakt "Nur Eltern können Welten verwalten.". 3. Welt von gw6-en `en`, von gw6-lehrer `de`. 4. language xx 422, Spieler 403, Sprache danach unverändert. 5. Fremder8 an der en-Welt "You are not invited to this world. Ask your parents.", an der de-Welt "nicht eingeladen", Gegenprobe ohne englischen Satz. 6. Sicherung mit gehaltener Sitzung: Chat "The world is taking a short break soon.", Trennung "The world is taking a short break. It will be back in a moment.", kein deutscher Pausentext. 7. Umschalten auf fr: 200, `language_restart_needed` true, ohne Neustart weiter englisch (Negativkontrolle), Neustart, danach false und "Tu n’as pas d’invitation pour ce monde. Demande à tes parents."; de-Welt blieb de. 8. Lauf 2: gw6-en "Unknown player name in Abnahme Sprache EN", gw6-lehrer "Unbekannter Spielername in Abnahme Sprache EN", gw6-en ohne deutschen Betreff. Lauf 4 (Tageslimit durch Lauf 2/3 schon verbraucht): Hinweiszeile, Positivkontrolle über GET /api/attempts (Fremder8 erfasst), Hinweiszeile zur Sammelnachricht, Gegenprobe kein deutscher Betreff bei gw6-en.

**Owner-Schutz:** StartedAt der vier Owner-Welten vor dem Backend-Neustart, nach jedem Lauf und am Ende gleich (`.dev/k8-owner-startedat-before.txt`):
- gameworld-788fff30-b6c185c2bb70 2026-10-24T16:18:20.453932153Z
- gameworld-788fff30-6fad6914c3be 2026-10-24T16:19:10.135512128Z
- gameworld-788fff30-ff2295234c42 2026-10-24T05:46:46.708685698Z
- gameworld-788fff30-e032336f9b6d 2026-10-24T05:46:46.96135967Z

Demo unverändert: Konten admin, gw-lehrer, gw-kind, leo, mama, mia, oma; Gruppen familie, eltern, lehrkraefte, klasse wie vorher; Verwalter-Gruppen eltern, lehrkraefte; Welten Baumhaus und Inselabenteuer laufen. Nach jedem Lauf keine gw6-Konten, keine Abnahme-Welten, keine neuen Welt-Container. Logs in `.dev/acceptance-phase6-0624*.log`.

**Tageszeit:** Lauf 2 startete 00:11, Phase 4.1 lief ab 00:34 ohne Wartezeit (Sperre greift nur 23:00 bis 0:16).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Deutsche Texte in der englischen Doku**
- **Found during:** Task 2 (Rest-Deutsch-Audit)
- **Issue:** docs/install.md zitierte die Oberfläche auf Deutsch und behauptete "The Gameworld interface is in German"; privacy.md nannte den deutschen Abschnittsnamen.
- **Fix:** alle Zitate durch die englischen Texte der Wörterbücher/Kataloge ersetzt, Hinweis auf Konto- und Weltsprache; Sprach-Verweis "Deutsch:".
- **Files modified:** docs/install.md, docs/privacy.md
- **Commit:** d566ace

**2. [Rule 3 - Blocking] Abnahme hätte die Demo-Umgebung gelöscht**
- **Found during:** Task 3 (vor dem Lauf)
- **Issue:** acceptance-phase6.sh nutzte gw-lehrer, lehrkraefte, klasse; reset_fixtures löscht diese Konten/Gruppen und entfernt lehrkraefte als Verwalter-Gruppe. Genau diese Namen hat die Demo aus 06-13 (Frau Weber, Verwalter-Gruppe lehrkraefte).
- **Fix:** alle Fixtures mit Präfix gw6-, K8-Konten gw6-en und gw6-kind-en.
- **Commit:** 87153b7

**3. [Rule 3 - Blocking] Wegwerfkonten ohne Sprache melden en**
- **Issue:** Ohne `core lang` meldet die Dev-Nextcloud `en` (geprüft per OCS für gw-lehrer); seit 06-18 bekämen frische Abnahmekonten englische Texte, die deutschen Soll-Texte von K1 bis K7 und der Regression wären falsch.
- **Fix:** add_user setzt `occ user:setting <uid> core lang de` in acceptance-phase3/4/4_1/5/6.sh; nur Konto-Einstellung, kein Soll-Text geändert.
- **Commit:** 87153b7

**4. [Rule 1 - Bug im Skript] TEXT_HALT unbound in K8** (8f5eb1d), **K7 Wettlauf beim ersten Raum** (ec5577c, gleiche Ursache wie der 06-12-Befund), **K8-Rückfall bei Tagesdrosselung** (2d40ff3: die Sammelnachricht geht einmal je Haushalt und Tag hinaus, ein frisches Konto kann sie verpassen; jetzt Positivkontrolle über die Versuchsliste und ausdrückliche Hinweiszeile).

**5. [Abweichung] Bundle nicht committet**
- js/ ist gitignored, das Dockerfile baut js/gameworld-main.js selbst ("nicht im Git"). Gebaut, im Dev-Stack aktiv und per grep belegt; ein `git add -f` hätte die Repo-Regel gebrochen. key_files nennt darum kein js/.

**6. [Abweichung] Zweite Ausnahmen-Tabelle**
- Plan nennt eine eigene Tabelle für das Rest-Deutsch-Audit: tests/i18n_foreign_exceptions.tsv (Datei, Schlüssel, Literal, Grund), gleiche Zwei-Wege-Prüfung wie tests/frontend_i18n_exceptions.tsv.

### Nicht erreicht: Exit 0 mit Regression im selben Lauf

- Lauf 2 (mit Regression) endete 165 von 171. Phase-6-eigen nur der K7-Wettlauf (seither behoben, Lauf 4 grün). Die übrigen 5 Fehlschläge sind die Regressionszeilen von Phase 4.1 (9 von 128 rot): smoke-talk.sh erwartet als Raum-Teilnehmer genau admin und gw-kind und findet zusätzlich mama und gw-lehrer, K2 erwartet Sammelnachricht und Zählung nur für admin/gw-admin2. Ursache ist die Demo aus 06-13 (Verwalter-Gruppen eltern und lehrkraefte seit 18:30, nach dem letzten grünen Lauf 18:02), die laut Owner nicht verändert werden darf. Phasen 5, 4, 3, 2 und 1 grün. In deferred-items.md mit Lösungsweg (fremde Verwalter als Grundlinie oder Stack ohne Demo).
- K7 zweiter Raum war in Lauf 1 und 3 rot (Anleger noch nicht im Verwalter-Schnappschuss, Raum bleibt allein, Sperrfall statt Übernahme). Bekannter Produktbefund aus 06-12 (CR-01-relevant, Fix nur mit deep Review), nicht in 06-24 angefasst.

## Known Stubs

Keine.

## Threat Flags

Keine neue Oberfläche: die Komponente ruft nur die bestehende Route aus 06-22 (T-06-95: Auswahl nur in der Verwalter-Ansicht, Server-Sperre per K8 Punkt 4 am echten Stack belegt). T-06-92: Ausnahmen nur in Repo-Dateien mit Zeile/Schlüssel, Literal und Grund, beidseitig abgeglichen, Positivkontrollen. T-06-93: Passwörter der gw6-Konten nur im Skript, nie in der Ausgabe (nur Längen). T-06-94: kein Deaktivieren der Dev-Registrierung, StartedAt vorher gleich nachher.

## Self-Check: PASSED

- FOUND: frontend/src/components/WorldLanguageSetting.vue, tests/test_frontend_i18n.py, tests/frontend_i18n_exceptions.tsv, tests/i18n_foreign_exceptions.tsv, scripts/dev/acceptance-phase6.sh (K8)
- FOUND: cb7929f, d15f7e1, d566ace, 87153b7, 8f5eb1d, ec5577c, 2d40ff3
