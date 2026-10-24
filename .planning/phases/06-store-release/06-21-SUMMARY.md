---
phase: 06-store-release
plan: 21
subsystem: frontend, i18n
tags: [i18n, frontend, d-25, kids-view, playtime, pause]
requires: ["06-17"]
provides:
  - "Bereich kids gefüllt: frontend/src/i18n/<de|en|fr>/kids.js mit je 109 Schlüsseln"
  - "App.vue, PlayerView, ConnectionCard, JoinGuide, PlaytimeCard, PauseView, ReviewView, AttemptsView, PlaytimeSection, PlaytimeDialog, DayTiles, HolidayList, WorldWindowDialog ohne nutzersichtbaren deutschen Harttext"
affects: [06-22, 06-24, 06-27]
tech-stack:
  added: []
  patterns:
    - "Werte in <strong> innerhalb eines übersetzten Satzes: Satz mit {platzhalter} aus dem Wörterbuch an den Platzhaltern teilen, Teile per Textinterpolation ausgeben (JoinGuide highlight), nie v-html"
    - "Link mitten im Satz: Schablone mit {site}, Text davor und danach getrennt ausgeben"
    - "Gemeinsame Texte unter kids.common.* (Zur Übersicht, Abbrechen, Speichern, Schließen, Ende nicht nach Beginn)"
    - "Beschriftungen nach API-Werten: kids.playtimeDialog.preset.<keine|wochenende|taeglich|schultage>"
key_files:
  created: []
  modified:
    - frontend/src/App.vue
    - frontend/src/views/PlayerView.vue
    - frontend/src/components/ConnectionCard.vue
    - frontend/src/components/JoinGuide.vue
    - frontend/src/components/PlaytimeCard.vue
    - frontend/src/views/PauseView.vue
    - frontend/src/views/ReviewView.vue
    - frontend/src/views/AttemptsView.vue
    - frontend/src/components/PlaytimeSection.vue
    - frontend/src/components/PlaytimeDialog.vue
    - frontend/src/components/DayTiles.vue
    - frontend/src/components/HolidayList.vue
    - frontend/src/components/WorldWindowDialog.vue
    - frontend/src/i18n/de/kids.js
    - frontend/src/i18n/en/kids.js
    - frontend/src/i18n/fr/kids.js
    - frontend/tests/i18n.exceptions.json
decisions:
  - "JoinGuide en/fr nennen die Original-Menünamen des Luanti-Clients (geprüft gegen builtin/mainmenu/tab_online.lua, stable-5 und master): Reiter \"Join Game\", Felder Address, Port, Name, Password, Knopf Login; de bleibt wortgleich (\"Reiter zum Beitreten\", \"Beitreten\")"
  - "Spielart im JoinGuide: en \"Adventure (gentle)\", fr « Aventure (douce) », gleich wie die Backend-Kataloge catalog_en.py/catalog_fr.py für presets.VOXELIBRE_SANFT.title"
  - "Kindertexte en/fr in kurzen Sätzen mit you/tu, französisch geschlechtsneutral (\"Tu n’as encore aucune invitation pour un monde\" statt \"invité(e)\")"
  - "Ferien-Datum über dateLocale() mit UTC auf beiden Seiten: de bleibt 24.12.2026, en-GB und fr-FR 24/12/2026; fr Zeitraum \"du {start} au {end}\""
  - "Pausen-Knöpfe über tn('kids.pause.minutes', n); PAUSE_OPTIONS enthält nur noch die Minuten (die Backend-Werte 15/30/60)"
  - "Uhrzeit der Beitrittsversuche (attempt.clock, H:MM vom Backend) bleibt unverändert; Tagesüberschriften kommen schon sprachabhängig aus route.js dayLabel"
metrics:
  duration: "35 min"
  completed: "2026-10-24"
  tasks: 2
  files: 17
---

# Phase 6 Plan 21: Kinder-Ansicht, Spielzeit und Shell dreisprachig Summary

Kinder-Ansicht (Meine Welten, Verbindungskarte, Beitrittsanleitung, Restzeit), App-Shell mit Link-Adressen-Rückfrage, Pause, Tagesrückblick, Beitrittsversuche sowie Spielzeit-Abschnitt, Spielzeit-Dialog, Tages-Kacheln, Ferien und Zeitfenster lesen alle sichtbaren Texte aus dem kids-Wörterbuch (109 Schlüssel je Sprache); Deutsch nachweislich wortgleich, Englisch und Französisch für Kinder in einfachen Sätzen.

**Basis-Commit (BASE):** `b44048fe018534d7c7dd322e73605b7bcf1cc731` (b44048f). Alle Diff-Nachweise laufen gegen diese ID.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | ea1811e | App.vue, PlayerView, ConnectionCard, JoinGuide, PlaytimeCard, PauseView, ReviewView, AttemptsView; kids.js de/en/fr 57 Schlüssel; vier Ausnahme-Einträge |
| 2 | d59981b | PlaytimeSection, PlaytimeDialog, DayTiles, HolidayList, WorldWindowDialog; kids.js auf 109 Schlüssel |

## Gate-Ergebnisse

- Alle neun `node frontend/tests/*.check.mjs`: grün nach Task 1 und Task 2; i18n.check meldet `kids: 57 keys` (Task 1) bzw. `kids: 109 keys in de, en and fr` (Task 2), Positivkontrolle a bis j weiter vollständig (14 Fehler).
- `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed (nach Task 1 und Task 2).
- Task 1: `npx vite --mode production build --outDir <scratchpad>/gw-build-0621 --emptyOutDir`: exit 0 (built in 8.16s, nur die bekannte Chunk-Größen-Warnung), Bundle enthält "How to get into the world".
- Task 2: `npm run build -- --outDir <scratchpad>/gw-build-0621-npm --emptyOutDir`: exit 0 (built in 6.72s), Bundle enthält "Apply to all school days".
- `git diff --quiet BASE -- js/`: exit 0 (nach beiden Tasks).
- `uv run pytest -m "not docker" -q`: 2675 passed, 44 deselected, 1 warning (6:47 min), seriell, freier RAM vorher 2,3 GB
- Kein v-html, keine U+2013/U+2014, keine Emojis in den 13 Komponenten und drei kids.js; kein "public", "visibility" oder "announce" in kids.js (in PlayerView nur die bestehende DOM-API `document.visibilityState`, vom Privacy-Test nicht erfasst und unverändert).
- Französisch: geschützte Leerzeichen nur als `\u00a0`-Escape, 0 echte U+00A0 in den drei kids.js (`grep -c $'\xc2\xa0'` = 0).

### Wortgleichheit (wordcheck0621.py im Scratchpad, Verfahren wie 06-19/06-20)

Entfernte Zeilen aus `git diff -U0 BASE -- <komponenten>`, Text- und Literal-Bruchstücke normalisiert und wörtlich in den Werten von de/kids.js und de/core.js gesucht.

- Task 1 (acht Dateien): 66 entfernte Zeilen, 58 Bruchstücke, 13 nicht gefunden, alle erklärt: `String(world.port)`, `noopener noreferrer`, `attempt.count >= 2` (Code in geänderten Zeilen); `15 Minuten`, `30 Minuten`, `60 Minuten` (jetzt `tn('kids.pause.minutes', n)` mit `{count} Minuten`, Laufzeitprobe de liefert genau "15 Minuten | 30 Minuten | 60 Minuten"); `Bisher: <span>`, `Neu: <span>` (Text plus Markup, "Bisher:"/"Neu:" stehen wörtlich in de/kids.js, Template rendert `{{ t(...) }} <span>` mit demselben Leerzeichen); fünf JoinGuide-Bruchstücke mit `<strong>` (siehe Render-Probe).
- JoinGuide-Render-Probe (guide0621.mjs): die sieben Textblöcke des Basis-Templates (Tags entfernt, Leerraum zusammengefasst, Werte als Platzhalter) gegen die aus de/kids.js zusammengesetzten Sätze: 7 von 7 gleich, darunter die Sätze mit „Abenteuer (sanft)“ und mit Semikolon, die das Bruchstück-Skript wegen Klammern nicht prüft.
- Task 2 (fünf Dateien): 63 entfernte Zeilen, 54 Bruchstücke, 0 nicht gefunden. Zusätzliche Render-Probe (node): Ferien-Rückfrage, Zeitraum, aria-label, Dialogtitel und formatDate in de gegen die alten Ausdrücke: 0 Abweichungen.
- Positivkontrolle: de/kids.js verfälscht ("Gross- und Kleinschreibung", "Fur heute Schluss"): Render-Probe meldet 1 DIFF, wordcheck für PauseView 5 statt 3 nicht gefunden; danach byte-gleich zurückgeschrieben (cmp).

### Scan (scan0621.py, Kommentare und style entfernt)

Umlaute plus erweiterte Wortliste (06-20-Liste plus Kinder, Pause, Passwort, Spielzeit, Minuten, heute, Hallo, Weiter, einladen, Ferien, Tag, von, bis, offen, Bisher, Neu, Nein, Ja, Kopiert, Anzeigen, Verbergen, Hinzufügen, Entfernen, Schließen, Bearbeiten, Erwachsen): zwölf Dateien 0 Treffer, PlaytimeDialog 2 Treffer, beide API-Wert `'keine'` (Voreinstellungs-Schlüssel). Positivkontrolle: Basisstand PauseView.vue 14, PlaytimeDialog.vue 14, HolidayList.vue 16 Treffer. Unübersetzt bleiben Seiten-IDs (`pause`, `versuch`, `rueckblick`), Pausenart `schluss`, Voreinstellungs-Schlüssel, Zeitzone `Europe/Berlin`, Weltstatus-Werte, `luanti.org`.

### Servertext-Erkennung (MARKS-Muster aus 06-20)

Geprüft mit `grep includes( / startsWith( / indexOf( / .match( / detail ===` über alle 13 Dateien: keine Komponente erkennt Servertexte an deutschen Bruchstücken. App.vue zeigt `detail` nur an (Rückfall jetzt `kids.app.loadFailed`), ConnectionCard zeigt `status_text` und Ticket-Fehler nur an (kommen seit 06-18 übersetzt), unterschieden wird nur nach API-Werten (`world.status`, `pause.art`). Keine Markenliste nötig.

## Begriffe

Nach der 06-17-Tabelle: Spielzeit = playtime / temps de jeu, Zeitfenster = time window / plage horaire, Pause = break / pause, Ferien = holidays / vacances, Tagesrückblick = daily summary / récap du jour, Beitrittsversuch = join attempt / tentative de connexion, Spielername = player name / nom de joueur, Verwalter = manager / gestionnaire, Erwachsen = adult / adulte. Ton: du / you / tu.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] frontend/tests/i18n.exceptions.json ergänzt (nicht in files_modified)**
- **Issue:** i18n.check (i) verlangt für Werte gleich Deutsch einen Ausnahme-Eintrag.
- **Fix:** vier Einträge: en und fr `kids.connection.port` ("Port"), fr `kids.connection.address` ("Adresse"), en `kids.review.worldMinutes` (nur Format `{world}: {minutes}`; fr hat `\u00a0:`). Commit ea1811e.

**2. [Rule 1 - Bug] Französische Zeichensetzung bei "Welt: Minuten" im Rückblick**
- **Issue:** `{{ world.world_name }}: {{ minutesText(...) }}` war fest im Template, ohne geschütztes Leerzeichen für fr.
- **Fix:** Schablone `kids.review.worldMinutes`. Commit ea1811e.

**3. Kleinigkeiten**
- HolidayList.formatDate gibt einen nicht als JJJJ-MM-TT lesbaren Wert unverändert zurück (vorher "undefined.undefined.x"); die API liefert immer ISO-Daten, für gültige Werte ist de byte-gleich (Render-Probe).
- `removeButtons` in HolidayList ist jetzt `computed` statt festes Array (Muster aus 06-19/06-20).
- Probebau-Ziel und Basis-ID-Datei im Scratchpad statt `$TEMP/gw-build-0621` (Session-Vorgabe), Befehl sonst identisch; die Basis-ID liegt zusätzlich in `$TEMP/gw-base-06-21`.

## Known Stubs

Keine. Unberührte deutsche Kommentare in den 13 Komponenten übersetzt Plan 06-27.

## Threat Flags

Keine neue Angriffsfläche. T-06-83: nur bestehende Texte übersetzt, keine neuen Felder; die Kinder-Ansicht zeigt weiter nur eigene Welt, eigenen Port, Spielername und Passwort, Statustexte und Ticket-Fehler kommen fest vom Backend. T-06-84: Welt-, Kinder- und Ferienamen gehen nur als Platzhalter-Parameter in t() oder als Teile der JoinGuide-Segmente (Werte werden erst nach dem Teilen eingesetzt, ein Name mit `{x}` wird nicht ausgewertet) und von dort per Textinterpolation oder gebundenem Attribut ins DOM, kein v-html.

## Self-Check: PASSED

- Dateien vorhanden: frontend/src/i18n/{de,en,fr}/kids.js (je 109 Schlüssel), 13 Komponenten geändert, frontend/tests/i18n.exceptions.json
- Commits vorhanden: ea1811e, d59981b; Basis b44048f
