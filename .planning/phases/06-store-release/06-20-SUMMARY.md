---
phase: 06-store-release
plan: 20
subsystem: frontend, i18n
tags: [i18n, frontend, d-25, settings, admin-sections]
requires: ["06-17"]
provides:
  - "Bereich admin gefüllt: frontend/src/i18n/<de|en|fr>/admin.js mit je 52 Schlüsseln"
  - "TalkRoomStatus, OrphanSection, VerwalterGroupsSection, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting ohne nutzersichtbaren deutschen Harttext"
affects: [06-13, 06-22, 06-24, 06-27]
tech-stack:
  added: []
  patterns:
    - "Gemeinsame Knöpfe unter admin.common.* (Abbrechen, Speichern)"
    - "Backend-Erkennungsmarken (422 unbekannte Gruppe, 409 Spielstand in Benutzung) als Liste in allen drei Kontosprachen"
    - "NcDialog-Buttons als computed (TalkRoomStatus), Beschriftungen beim Rendern aufgelöst"
key_files:
  created: []
  modified:
    - frontend/src/components/TalkRoomStatus.vue
    - frontend/src/components/OrphanSection.vue
    - frontend/src/components/VerwalterGroupsSection.vue
    - frontend/src/components/SetupCheck.vue
    - frontend/src/components/JoinHostSettings.vue
    - frontend/src/components/ReviewSetting.vue
    - frontend/src/components/TimeZoneSetting.vue
    - frontend/src/i18n/de/admin.js
    - frontend/src/i18n/en/admin.js
    - frontend/src/i18n/fr/admin.js
    - frontend/tests/i18n.exceptions.json
    - frontend/tests/orphans.check.mjs
decisions:
  - "Doku-Links bleiben für alle Sprachen auf der englischen Hauptfassung docs/install.md: der Setup-Check-Link kommt vom Backend (setup_check.py DOCS_URL, für alle Konten gleich), CLEANUP_DOCS_URL ist eine core-Konstante in orphans.js (nicht in diesem Plan); ein gemischtes Ziel je Abschnitt wäre für de-Konten uneinheitlich. Umschalten auf install.de.md ginge später an einer Stelle pro Link, die Anker sind gleich"
  - "Spieler-Adresse: Feldbeschriftung 'Adresse für Spieler' en 'Player address', fr 'Adresse de jeu' (Begriffstabelle)"
  - "Tagesrückblick: en 'Daily summary in the evening', fr 'Récap du jour le soir'; Uhrzeit-Label kommt unverändert aus reviewSelectOptions (playtime.js, sprachabhängig) als Platzhalter {time}"
  - "Talk: 'Raum neu anlegen' en 'Recreate room', fr 'Recréer le salon', passend zu core.playtime.talk.recreateQuestion"
  - "Reste: Chip 'Spielstand' en 'World data', fr 'Données de monde'; Chip 'Container' en gleich (Ausnahme-Eintrag), fr 'Conteneur'"
  - "Kinder-Warnung, Grenz-Text (D-01) und Lebenszyklus-Text (D-15, Spielstände und Sicherungen bleiben) laufen weiter über die core-Funktionen aus roles.js und orphans.js, nichts doppelt im admin-Bereich"
metrics:
  duration: "40 min"
  completed: "2026-10-24"
  tasks: 2
  files: 12
---

# Phase 6 Plan 20: Einstellungen und Admin-Abschnitte dreisprachig Summary

Verwalter-Gruppen, Reste früherer Installationen, Talk-Raum-Status, Setup-Check, Spieler-Adresse, Tagesrückblick und Zeitzone lesen alle sichtbaren Rahmentexte aus dem admin-Wörterbuch (52 Schlüssel je Sprache), Deutsch nachweislich wortgleich zum Stand vor dem Plan; die Server-Erkennung von "unbekannte Gruppe" und "Spielstand in Benutzung" funktioniert jetzt auch für en/fr-Konten.

**Basis-Commit (BASE):** `94b21abff7988ecb3d2c1da98300dcc10455797f` (94b21ab). Alle Diff-Nachweise laufen gegen diese ID.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | f562800 | VerwalterGroupsSection, OrphanSection, TalkRoomStatus umgestellt, admin.js de/en/fr (27 Schlüssel), Marken dreisprachig, orphans.check auf Wörterbuch, ein Ausnahme-Eintrag |
| 2 | 8b45eb6 | SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting umgestellt, admin.js auf 52 Schlüssel |

## Gate-Ergebnisse

- Alle neun `node frontend/tests/*.check.mjs`: grün (nach Task 1 und Task 2); i18n.check meldet `admin: 52 keys in de, en and fr`, Positivkontrolle a bis j weiter vollständig.
- `uv run pytest -q tests/test_frontend_privacy.py tests/test_orphan_section_gate.py`: 11 passed (nach Task 1 und Task 2).
- Task 1: `npx vite --mode production build --outDir <scratchpad>/gw-build-0620 --emptyOutDir`: exit 0 (built in 7.97s, nur die bekannte Chunk-Größen-Warnung), Bundle enthält "Leftovers from earlier installations".
- Task 2: `npm run build -- --outDir <scratchpad>/gw-build-0620-npm --emptyOutDir`: exit 0 (built in 6.51s), Bundle enthält "Use this browser".
- `git diff --quiet BASE -- js/`: exit 0 (nach beiden Tasks).
- `uv run pytest -m "not docker" -q`: 2675 passed, 44 deselected, 1 warning (51:52 min) (Plan-Ende, freier RAM vorher 2,3 GB, seriell).
- `grep -rn "v-html" frontend/src`: nur der Kommentar in roles.js, kein Einsatz (T-06-82).
- Keine U+2013/U+2014 und keine Emojis in den sieben Komponenten und drei admin.js; kein "public", "visibility" oder "announce" in admin.js und den Komponenten.
- Französisch: 4 geschützte Leerzeichen als `\u00a0`-Escape (vor `:` und `;`), 0 echte U+00A0 in den drei admin.js (`grep -c $'\xc2\xa0'` = 0).

### Wortgleichheit (wordcheck0620.py im Scratchpad, Verfahren wie 06-19)

Entfernte Zeilen aus `git diff -U0 BASE -- <komponenten>`, Text- und Literal-Bruchstücke normalisiert und wörtlich in den Werten von de/admin.js und de/core.js gesucht.

- VerwalterGroupsSection + OrphanSection + TalkRoomStatus: 37 entfernte Zeilen, 34 Bruchstücke, 0 nicht gefunden.
- SetupCheck + JoinHostSettings + ReviewSetting + TimeZoneSetting: 29 entfernte Zeilen, 27 Bruchstücke, 3 nicht gefunden, alle erklärt: `errors.length > 0` und `warnings.length > 0` (Vue-Ausdrücke in Zeilen, die wegen `:heading` geändert wurden), `Spieler sehen als Adresse: <strong>` (Text plus Markup; `'Spieler sehen als Adresse:'` steht wörtlich in de/admin.js, das Template rendert `{{ t(...) }} <strong>` mit demselben Leerzeichen davor).
- Positivkontrolle: zwei verfälschte de-Werte ("Nur  lesen", "Gruppe hinzufugen") wurden beide als NOT FOUND gemeldet, danach Datei byte-gleich zurückgeschrieben (cmp).

### Scan (scan0620.py, Kommentare und style entfernt)

Umlaute plus Wortliste (der, die, das, und, nicht, bitte, ist, kein, keine, noch, gerade, Welt, Gruppe, Raum, Spielstand, Reste, entfernen, Gespeichert, Speichern, Zeitzone, Adresse, Spieler, Einstellungen, erneut, Abbrechen): TalkRoomStatus, SetupCheck, JoinHostSettings, ReviewSetting, TimeZoneSetting 0 Treffer; VerwalterGroupsSection und OrphanSection je 1 Treffer, beide API-Werte: die Markenlisten `UNKNOWN_MARKS` und `IN_USE_MARKS` (Backend-Text in de/en/fr). Positivkontrolle: Basisstand TalkRoomStatus.vue 7 Treffer, JoinHostSettings.vue 8 Treffer. Unübersetzt bleiben außerdem die Gruppen-ID `admin`, die IANA-Zone `Europe/Berlin`, Klassifizierungswerte `loopback`/`internet`, Eintragsarten `container`/`volume`.

## Begriffe

Nach der 06-17-Tabelle: Verwalter-Gruppen = Manager groups / Groupes de gestionnaires, Reste früherer Installationen = Leftovers from earlier installations / Restes d’installations précédentes, Spielstand = world data / données de monde, Container = container / conteneur, Talk-Raum = Talk room / salon Talk, Spieler-Adresse = player address / adresse de jeu, Tagesrückblick = daily summary / récap du jour, Spielzeit = playtime / temps de jeu, Zeitfenster = time window / plage horaire, Ferien = holidays / vacances. Ton: du / you / tu.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Backend-Marken nur auf Deutsch**
- **Found during:** Task 1
- **Issue:** VerwalterGroupsSection erkannte die 422 "unbekannte Gruppe" über `detail.includes('gibt es in Nextcloud nicht')`, OrphanSection die 409 "Spielstand in Benutzung" über `'noch von einem Container benutzt'`. Seit 06-18 liefert das Backend diese Texte in der Kontosprache, für en/fr-Konten fiel die genaue Meldung (mit "Bitte wähle eine Gruppe aus der Liste" bzw. "Entferne zuerst den Container") still auf den nackten Servertext zurück. 422 und 409 sind nicht eindeutig (MSG_ADMIN_FIXED, MSG_ORPHAN_REFUSED), darum bleibt die Marke nötig.
- **Fix:** `UNKNOWN_MARKS` und `IN_USE_MARKS` mit den Bruchstücken aus admin.MSG_UNKNOWN_GROUP / MSG_ORPHAN_IN_USE in de und aus catalog_en.py / catalog_fr.py; Prüfung über `.some(...)`.
- **Files modified:** VerwalterGroupsSection.vue, OrphanSection.vue
- **Commit:** f562800

**2. [Rule 3 - Blocking] frontend/tests/orphans.check.mjs angepasst (nicht in files_modified)**
- **Issue:** Die Prüfung suchte die deutschen aria-label-Schablonen wörtlich im Quelltext von OrphanSection.vue.
- **Fix:** Sie prüft jetzt die Schlüssel-Aufrufe im Quelltext und die Wörterbuchwerte (de wortgleich "Container x entfernen", "Spielstand x endgültig löschen", "Reste erneut suchen", dazu je ein en- und fr-Wert). Commit f562800.

**3. [Rule 3 - Blocking] frontend/tests/i18n.exceptions.json ergänzt**
- en `admin.orphans.chipContainer` = "Container" (gleiches Wort, Begriffstabelle). Commit f562800.

**4. Probebau-Ziel Scratchpad statt `$TEMP/gw-build-0620`** (Session-Vorgabe), Befehl sonst identisch; Basis-ID-Datei ebenfalls im Scratchpad (`gw-base-06-20`).

**5. Kleinigkeit:** `recreateButtons` in TalkRoomStatus ist jetzt `computed` statt festes Array.

## Known Stubs

Keine. Unberührte deutsche Kommentare in den sieben Komponenten übersetzt Plan 06-27; Rahmentexte des Setup-Checks sind übersetzt, die Prüfpunkt-Meldungen kommen übersetzt vom Backend (06-18).

## Threat Flags

Keine neue Angriffsfläche. T-06-81: Kinder-Warnung und Grenz-Text der Verwalter-Gruppen kommen unverändert aus den core-Texten (childrenWarning, boundaryText, sectionHint), die in de/en/fr vollständig sind; nichts gekürzt. Bestätigungsdialoge nennen in allen drei Sprachen dieselben Folgen (core containerQuestion/volumeQuestion, recreateQuestion mit Verlust des Verlaufs). T-06-82: Gruppen-IDs, Container- und Volumenamen sowie Zeitzonen gehen nur als Platzhalter-Parameter in t() und per Textinterpolation oder gebundenem Attribut ins DOM, kein v-html.

## Self-Check: PASSED

- Dateien vorhanden: frontend/src/i18n/{de,en,fr}/admin.js (je 52 Schlüssel), sieben Komponenten geändert, frontend/tests/i18n.exceptions.json, frontend/tests/orphans.check.mjs
- Commits vorhanden: f562800, 8b45eb6
