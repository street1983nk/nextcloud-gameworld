---
phase: 06-store-release
plan: 17
subsystem: frontend, i18n
tags: [i18n, frontend, d-25, dictionaries, node-checks]
requires: ["06-12"]
provides:
  - "frontend/src/i18n/index.js: t, tn, setLanguage, currentLanguage, normalizeLanguage, compareText, dateLocale, createTranslator, mergeAreas (re-export), SUPPORTED_LANGUAGES, FALLBACK_LANGUAGE"
  - "Wörterbücher frontend/src/i18n/<de|en|fr>/<core|parent|admin|kids|world>.js; core gefüllt (DE wortgleich), die anderen vier leer für 06-19/06-20/06-21/06-24"
  - "frontend/tests/i18n.check.mjs (Strukturprüfung a bis j mit Positivkontrolle) und frontend/tests/i18n.exceptions.json (10 Einträge)"
  - "Sprachwahl aus der Nextcloud-Kontosprache in main.js vor createApp, Rückfall en"
affects: [06-19, 06-20, 06-21, 06-22, 06-24, 06-27]
tech-stack:
  added: []
  patterns:
    - "Texte nie auf Modulebene auflösen: Text-Konstanten sind Funktionen, t/tn lösen beim Aufruf auf"
    - "Sätze mit Werten als Platzhalter-Schablone ({gid}, {when}), nie aus Bruchstücken"
    - "Französisch: \\u00a0 vor ? ! ; : und in « », Uhrzeiten 19\\u00a0h und 19\\u00a0h\\u00a030"
key_files:
  created:
    - frontend/src/i18n/index.js
    - frontend/src/i18n/merge.js
    - frontend/src/i18n/de/index.js
    - frontend/src/i18n/en/index.js
    - frontend/src/i18n/fr/index.js
    - frontend/src/i18n/de/core.js
    - frontend/src/i18n/en/core.js
    - frontend/src/i18n/fr/core.js
    - frontend/src/i18n/de/parent.js
    - frontend/src/i18n/en/parent.js
    - frontend/src/i18n/fr/parent.js
    - frontend/src/i18n/de/admin.js
    - frontend/src/i18n/en/admin.js
    - frontend/src/i18n/fr/admin.js
    - frontend/src/i18n/de/kids.js
    - frontend/src/i18n/en/kids.js
    - frontend/src/i18n/fr/kids.js
    - frontend/src/i18n/de/world.js
    - frontend/src/i18n/en/world.js
    - frontend/src/i18n/fr/world.js
    - frontend/tests/i18n.check.mjs
    - frontend/tests/i18n.exceptions.json
  modified:
    - frontend/src/main.js
    - frontend/src/roles.js
    - frontend/src/adult.js
    - frontend/src/orphans.js
    - frontend/src/backup.js
    - frontend/src/playtime.js
    - frontend/src/route.js
    - frontend/src/api.js
    - frontend/src/components/DayTiles.vue
    - frontend/src/components/InviteDialog.vue
    - frontend/src/components/OrphanSection.vue
    - frontend/src/components/PlayerManager.vue
    - frontend/src/components/TalkRoomStatus.vue
    - frontend/src/components/VerwalterGroupsSection.vue
    - frontend/src/views/ParentView.vue
    - frontend/tests/roles.check.mjs
    - frontend/tests/adult.check.mjs
    - frontend/tests/orphans.check.mjs
    - frontend/tests/backup.check.mjs
    - frontend/tests/playtime.check.mjs
    - frontend/tests/origin.check.mjs
    - frontend/tests/route.check.mjs
    - frontend/tests/api.check.mjs
decisions:
  - "Eigenes i18n-Modul ohne neue Abhängigkeit; @nextcloud/l10n nur in main.js (getLanguage), nie in den reinen Modulen"
  - "mergeAreas liegt in i18n/merge.js und wird aus i18n/index.js re-exportiert, damit die Sprach-Indizes die Laufzeit nicht zirkulär importieren"
  - "createTranslator(dictionaries) zusätzlich exportiert: Laufzeit-Tests mit eigener Testtabelle (nur-en-Schlüssel, Plural) ohne die echten Wörterbücher zu verbiegen"
  - "Zusätzliche Prüfung (j) im i18n.check: französische Zeichensetzung mit geschütztem Leerzeichen vor ? ! ; : und in « », Doppelpunkt zwischen Ziffern/Platzhaltern (Uhrzeit) erlaubt"
  - "Neue Begriffe: Spielstand = world data / données de monde; Container = container / conteneur; Talk-Raum = Talk room / salon Talk; Setup-Check = setup check / vérification de l’installation"
  - "Französische Kurz-Wochentage Lun bis Dim (Kalenderform, groß), Spanne 'Lun au Ven'; lange Wochentage klein (lundi), Überschrift in route.js mit großem Anfangsbuchstaben"
  - "Englisch 24-Stunden-Uhr ohne führende Null ('9:00', '19:30'), Dauer '1 hr 30 min'"
metrics:
  duration: "25 min"
  completed: "2026-10-24"
  tasks: 3
  files: 45
---

# Phase 6 Plan 17: i18n-Fundament Summary

Eigene i18n-Laufzeit (t/tn/normalizeLanguage) mit Wörterbüchern DE/EN/FR je Bereich, Sprachwahl aus der Nextcloud-Kontosprache mit Rückfall Englisch, alle reinen JS-Module samt api.js dreisprachig, deutsche Texte nachweislich wortgleich.

**Basis-Commit (BASE):** `daed2f457e05e878a42c40fc33a4a35925473319` (daed2f4). Alle Diff-Nachweise laufen gegen diese ID.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | 5766c18 | i18n-Laufzeit, leere Bereichsdateien, main.js, i18n.check.mjs mit Positivkontrolle |
| 2 | 81db621 | core-Wörterbücher, acht Module umgestellt, Prüfskripte mit EN/FR-Fällen, Ausnahmenliste |
| 3 | ef39635 | Komponenten auf die umbenannten Text-Funktionen, Probebau |

## Gate-Ergebnisse

- Alle neun `node frontend/tests/*.check.mjs`: grün (i18n.check meldet: Positivkontrolle fand alle Fehlertypen a bis j, 14 Fehler; echte Wörterbücher fehlerfrei; core mit 127 Schlüsseln in de, en, fr).
- `cd frontend && npm run build -- --outDir <scratchpad>/gw-build-0617-npm --emptyOutDir`: grün (built in 6.39s), dazu der Plan-Probebau `npx vite --mode production build --outDir <scratchpad>/gw-build-0617 --emptyOutDir`: exit 0, keine Warnung zu fehlenden Exporten (nur die bekannte Chunk-Größen-Warnung). Das Bundle enthält DE und FR (`Mitglieder dieser Gruppen`, `Les membres de ces groupes`).
- `git diff --quiet BASE -- js/`: exit 0 (js/ ist ohnehin gitignored, das lokale js/ wurde nicht neu gebaut).
- `git diff --quiet BASE -- frontend/package.json frontend/package-lock.json`: exit 0, keine neue Abhängigkeit.
- `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed (FORBIDDEN-Liste auch über die Wörterbücher).
- `uv run pytest -m "not docker" -q`: 2591 passed, 44 deselected.
- `grep -c "setLanguage(normalizeLanguage(getLanguage()))" frontend/src/main.js` = 1; `grep -rn "@nextcloud/" frontend/src/i18n/`: kein Treffer.
- `grep -rnE "SECTION_HINT|NO_SCOPE_TEXT|LIMIT_OPTIONS|NO_LIMIT_OPTION|WEEKDAYS|..." frontend/src`: kein Treffer (alle 24 alten Namen).
- Keine U+2013/U+2014, kein Emoji, kein "public"/"visibility" unter frontend/src (Prüfskript und grep), kein v-html neu.

### Diff-Nachweise gegen BASE (Skripte im Scratchpad)

- Tests (`literal_diff.py`, Kriterium Task 2): `git diff -U0 BASE -- frontend/tests/`: 53 entfernte Zeilen, 9 Literale mit Text geprüft, 0 fehlen (jedes entfernte deutsche Soll-Literal steht wortgleich wieder als `+`-Zeile oder in de/core.js; entfernt wurden sonst nur Konstantennamen).
- Module (`fragments.py`, zusätzliche Gegenprobe): 225 entfernte Codezeilen, 152 Textbruchstücke (Template-Literale an `${...}` geteilt), 7 nicht wörtlich in de/core.js, alle erklärt: zwei Sätze mit fester "1" stehen jetzt als `{count}` in `.one` (Soll-Literal "In der Welt spielt gerade 1 Kind, ..." und "Heute noch 1 Minute" weiter grün), drei Code-Segmente (`gameworld-orphans.sh`, `--remove-containers`, `--remove-volumes`) bleiben Literale in orphans.js, zweimal `'string'` (typeof).
- Komponenten (Task 3): `git diff -U0 BASE -- frontend/src/components frontend/src/views`: 104 geänderte Zeilen (52+/52-), 0 Zeilen ohne alten oder neuen Text-Funktionsnamen, also nur Import- und Aufrufzeilen.

## Umbenennungen (alter Name, neuer Name, importierende Datei)

| Alter Name | Neuer Name | Importierende Datei(en) |
|------------|------------|-------------------------|
| SECTION_HINT | sectionHint() | VerwalterGroupsSection.vue |
| CHILDREN_WARNING | childrenWarning() | VerwalterGroupsSection.vue |
| BOUNDARY_TEXT | boundaryText() | VerwalterGroupsSection.vue |
| ONLY_ADMIN_TEXT | onlyAdminText() | VerwalterGroupsSection.vue |
| NC_ADMIN_ONLY_TEXT | ncAdminOnlyText() | VerwalterGroupsSection.vue, OrphanSection.vue, ParentView.vue |
| SEARCH_DOWN_TEXT | searchDownText() | VerwalterGroupsSection.vue |
| NO_SCOPE_TEXT | noScopeText() | InviteDialog.vue |
| CONFIRM_SCOPE | confirmScope() | InviteDialog.vue, PlayerManager.vue |
| CONFIRM_WARNING | confirmWarning() | InviteDialog.vue, PlayerManager.vue |
| SWITCH_META | switchMeta() | PlayerManager.vue |
| INVITE_SWITCH_META | inviteSwitchMeta() | InviteDialog.vue |
| INTRO_TEXT | introText() | OrphanSection.vue |
| LIFECYCLE_TEXT | lifecycleText() | OrphanSection.vue |
| EMPTY_TEXT | emptyText() | OrphanSection.vue |
| SCRIPT_SEGMENTS | scriptSegments() | OrphanSection.vue |
| SCRIPT_TEXT | scriptText() | nur orphans.check.mjs |
| WEEKDAYS | weekdays() | DayTiles.vue |
| LIMIT_OPTIONS | limitOptions() | DayTiles.vue (Import-Alias buildLimitOptions, weil die lokale Liste limitOptions heißt) |
| NO_LIMIT_OPTION | noLimitOption() | DayTiles.vue |
| TALK_MISSING_TEXT | talkMissingText() | nur playtime.check.mjs (Komponenten nutzen talkHint) |
| RECREATED_TEXT | recreatedText() | TalkRoomStatus.vue |
| ORPHANED_BEFORE | orphanedBefore() | TalkRoomStatus.vue |
| ORPHANED_AFTER | orphanedAfter() | TalkRoomStatus.vue |
| NOT_APPLIED_TEXT | notAppliedMessage() | PlayerManager.vue (notAppliedText(result) gab es schon) |

Unverändert: PLAYTIME_RESTING_TEXT(name) war schon eine Funktion und behält den Namen (PlaytimeDialog.vue bleibt darum unberührt). Reine Daten bleiben Konstanten: CLEANUP_DOCS_URL, DISMISS_KEY, EMBED_STEM, PAGES, ROUTE_EVENT, REVIEW_DEFAULT_MINUTE, PRESETS, HOLIDAY_PRESET, apiBase.

## Nicht übersetzt (API-Werte und Pfade, für die Ausnahmenliste in 06-24)

- Rollen `verwalter`, `spieler` (api.js /api/me)
- Spielzeit-Zustände `aufgebraucht`, `fenster`, `tag`, `ok` (/api/my/playtime; in playtime.js als KID_BLOCKED_STATES und als Schlüsselsegment `core.playtime.kid.blocked.<state>`)
- Voreinstellungs-Schlüssel `keine`, `wochenende`, `taeglich`, `schultage` (PRESETS)
- Seiten-IDs `pause`, `versuch`, `rueckblick` und Parameter `welt`, `tag` (route.js)
- Job-Arten und -Zustände `backup`, `restore`, `running`, `failed`, `ok`; Docker-Zustand `running`
- Dateizusatz `vor-restore` (Backend-Dateiname, steht wörtlich auch in en/fr)
- Befehle und Pfade: `occ talk:room:delete`, `gameworld-orphans.sh`, `--remove-containers`, `--remove-volumes`, alle URL-Pfade
- `Intl.DateTimeFormat('en-US', ...)` in weekdayIn bleibt (dient nur der Wochentagsberechnung)

## Für 06-19/20/21/22

**API** (`import { t, tn, compareText, dateLocale } from '../i18n/index.js'`):

- `t(key, params = {})`: Wert der aktuellen Sprache, sonst en, sonst der Schlüssel; `{name}` wird durch `String(params.name)` ersetzt, fehlende Parameter bleiben als `{name}` stehen; Ergebnis immer reiner Text (nur per `{{ }}` ausgeben, nie v-html).
- `tn(key, count, params = {})`: wählt `key.one` oder `key.other` (de/en: one nur bei 1; fr: one bei 0 und 1), setzt `params.count` selbst. Beide Schlüssel in allen drei Sprachen anlegen.
- `normalizeLanguage(raw)`: Teil vor `_`/`-`, klein; nur de, en, fr, sonst en (`de_DE` wird de, `pt_BR` wird en).
- `setLanguage(lang)` / `currentLanguage()`: main.js setzt einmal vor createApp; Prüfskripte setzen selbst (`setLanguage('de')` am Anfang).
- `compareText(a, b)` für Sortierungen, `dateLocale()` ('de-DE' | 'en-GB' | 'fr-FR') für Intl/toLocaleDateString.
- `createTranslator(dictionaries)` und `mergeAreas(areas)` nur für Tests.

**Regeln für Komponenten:** Texte nie auf Modulebene oder in `const X = t(...)` außerhalb von setup/computed auflösen; im Template `{{ t('parent.x.y') }}` oder eine computed/Funktion. Sätze mit Werten immer als Schablone mit Platzhalter.

**Wörterbuch-Struktur:** `frontend/src/i18n/<lang>/<bereich>.js` mit `export default { 'bereich.komponente.name': 'Text' }`, flach, Schlüssel immer mit Bereichspräfix (mergeAreas wirft sonst, ebenso bei Duplikat). Jeder Plan schreibt nur in seinen Bereich: parent (06-19), admin (06-20), kids (06-21), world (06-24). Französisch im Quelltext mit `\u00a0` vor ? ! ; : und in `«\u00a0…\u00a0»`; Apostroph in fr als `’`, in en ASCII. Bewusst gleiche Werte (de = en oder de = fr) brauchen einen Eintrag `{ "file", "key", "reason" }` in frontend/tests/i18n.exceptions.json; i18n.check prüft beide Richtungen. Achtung Werkzeug: Write/Edit wandeln `\u00a0` im Inhalt in das echte Zeichen um; danach mit einem Skript (String.fromCharCode(92) + 'u00a0') zurückschreiben und `grep -c $'\xc2\xa0'` prüfen.

**Begriffstabelle (verbindlich, plus Ergänzungen dieses Plans):**

| de | en | fr |
|----|----|----|
| Verwalter | manager | gestionnaire |
| Verwalter-Gruppen | manager groups | groupes de gestionnaires |
| Spieler | player | joueur |
| Spielername | player name | nom de joueur |
| Welt | world | monde |
| Spielart | game type | type de jeu |
| Sicherung | backup | sauvegarde |
| Wiederherstellen | restore | restaurer |
| Erwachsen | adult | adulte |
| Spielzeit | playtime | temps de jeu |
| Zeitfenster | time window | plage horaire |
| Pause | break | pause |
| Ferien | holidays | vacances |
| Einladung, einladen | invitation, invite | invitation, inviter |
| Eltern | parents | parents |
| Tagesrückblick | daily summary | récap du jour |
| Beitrittsversuch | join attempt | tentative de connexion |
| Reste früherer Installationen | leftovers from earlier installations | restes d'installations précédentes |
| Spieler-Adresse | player address | adresse de jeu |
| Spielstand (neu) | world data | données de monde |
| Container (neu) | container | conteneur |
| Talk-Raum (neu) | Talk room | salon Talk |
| Nextcloud-Admin (neu) | Nextcloud admin | administrateur Nextcloud |
| Setup-Check (neu) | setup check | vérification de l’installation |
| Spielzeitregel (neu) | playtime rule | règle de temps de jeu |

Uhrzeit und Dauer: de "19 Uhr"/"19:30", "1 Std 30 min"; en "19:00"/"19:30", "1 hr 30 min"; fr "19 h"/"19 h 30", "1 h 30" (jeweils mit `\u00a0`). Ton: de du, en you, fr tu.

## Deviations from Plan

### Auto-fixed Issues / Anpassungen

**1. [Rule 3 - Blocking] mergeAreas in eigener Datei**
- **Issue:** Sprach-Indizes müssten mergeAreas aus i18n/index.js importieren, das die Sprach-Indizes importiert (Zirkelimport, Auswertung vor Initialisierung).
- **Fix:** `frontend/src/i18n/merge.js`, aus index.js re-exportiert (Vertrag `mergeAreas` aus index.js bleibt). Zusätzlich prüft mergeAreas das Bereichspräfix. Commit 5766c18.

**2. [Rule 2 - Correctness] Zusätzliche Prüfung (j) und createTranslator**
- Französische Zeichensetzung (geschütztes Leerzeichen) wird mitgeprüft, Positivkontrolle enthält auch (j); createTranslator für Laufzeittests mit Testtabelle. Commits 5766c18, 81db621.

**3. [Rule 1 - Bug im eigenen Prüfskript] Doppelpunkt in Uhrzeiten**
- `{hour}:{minute}` (fr dateTime) wurde als fehlendes Leerzeichen gemeldet; Doppelpunkt nach Ziffer oder `}` ist jetzt erlaubt, Gegenprobe `10:00` im Prüfskript. Commit 81db621.

**4. Namen:** NOT_APPLIED_TEXT heißt notAppliedMessage(), weil notAppliedText(result) schon existiert; PLAYTIME_RESTING_TEXT bleibt (war schon Funktion), daher PlaytimeDialog.vue ohne Änderung.

**5. origin.js und api.js:** origin.js hat keinen sichtbaren Text und bleibt unverändert; origin.check.mjs belegt die Sprachunabhängigkeit von originQuestion unter en/fr und prüft den gemeinsamen Rückfalltext core.api.requestFailed auf Englisch und Französisch. api.js lässt sich in Node nicht importieren (initial-state braucht document); api.check.mjs prüft darum den Quelltext von errorText (detail unverändert, Rückfall über t) und die drei Wörterbuchwerte.

**6. Kleinigkeiten:** ungenutzte Konstante SCHOOL_DAYS in playtime.js entfernt (war tot); formatBytes nutzt Intl.NumberFormat ohne Gruppierung (de "1,5 GB" und "1024 GB" wie vorher); confirmLead behält die alte Regel (nur mehr als ein Name ist Plural), auch bei leerer Liste; DayTiles fällt auf `limitOptions[0]` statt auf ein neues noLimitOption()-Objekt zurück (gleiche Objektidentität wie vorher).

**7. Probebau-Ziel:** Scratchpad statt `$TEMP/gw-build-0617` (Vorgabe der Session: temporäre Dateien ins Scratchpad); Befehl sonst identisch, zusätzlich `npm run build -- --outDir ...`.

**8. Französisch geschlechtsneutral:** Wo der deutsche Satz mit einem Namen ohne Geschlecht auskommt, steht in fr eine neutrale Form ("Le compte de {name} est marqué comme adulte", "L’invitation de {name} a réussi").

## Known Stubs

- frontend/src/i18n/<de|en|fr>/<parent|admin|kids|world>.js sind bewusst leer (`export default {}`); sie werden von 06-19, 06-20, 06-21 und 06-24 gefüllt. Die Komponenten zeigen bis dahin ihre eigenen deutschen Harttexte, ihre Übersetzung ist nicht Ziel dieses Plans.

## Threat Flags

Keine neue Angriffsfläche. T-06-72 (t liefert reinen Text, `<b>` und `$&$1` bleiben wörtlich, belegt in i18n.check), T-06-73 (normalizeLanguage lässt nur de/en/fr durch, `<script>` wird en, belegt), T-06-74 (FORBIDDEN-Liste in i18n.check (g) und test_frontend_privacy.py über die Wörterbücher) umgesetzt.

## Self-Check: PASSED

- Dateien vorhanden: frontend/src/i18n/index.js, merge.js, 15 Bereichsdateien, 3 Sprach-Indizes, frontend/tests/i18n.check.mjs, frontend/tests/i18n.exceptions.json
- Commits vorhanden: 5766c18, 81db621, ef39635
