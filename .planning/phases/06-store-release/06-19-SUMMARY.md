---
phase: 06-store-release
plan: 19
subsystem: frontend, i18n
tags: [i18n, frontend, d-25, parent-view]
requires: ["06-17"]
provides:
  - "Bereich parent gefüllt: frontend/src/i18n/<de|en|fr>/parent.js mit je 96 Schlüsseln"
  - "ParentView, BackupSection, InviteDialog, PlayerManager ohne nutzersichtbaren deutschen Harttext"
affects: [06-13, 06-22, 06-24, 06-27]
tech-stack:
  added: []
  patterns:
    - "Gemeinsame Knopf- und Hinweistexte unter parent.common.* (Abbrechen, Schließen, Einladen, Spieler einladen, Als erwachsen markieren, Änderung wirkt beim nächsten Start)"
    - "NcDialog-Buttons als computed, damit die Beschriftungen beim Rendern aufgelöst werden"
key_files:
  created: []
  modified:
    - frontend/src/views/ParentView.vue
    - frontend/src/components/BackupSection.vue
    - frontend/src/components/InviteDialog.vue
    - frontend/src/components/PlayerManager.vue
    - frontend/src/i18n/de/parent.js
    - frontend/src/i18n/en/parent.js
    - frontend/src/i18n/fr/parent.js
    - frontend/tests/i18n.exceptions.json
decisions:
  - "Ordnerpfad Gameworld/Sicherungen bleibt in en/fr wörtlich, weil der Backend-Ordner so heißt (src/gameworld/backup/naming.py BACKUPS_ROOT)"
  - "en meidet das gesperrte Wort announce: 'Gameworld never advertises a world on the internet.'"
  - "Pause-Knopf en 'Break' (Begriffstabelle), fr 'Pause' (gleich wie de, Ausnahme-Eintrag)"
  - "Spielstand beim Umbenennen meint den Spielerfortschritt: en 'game progress', fr 'progression dans le jeu' (nicht 'world data', das wäre der Weltdatenbestand)"
  - "Bestätigung Erwachsen nutzt weiter die core-Texte aus adult.js (confirmLead, confirmScope, confirmWarning, rulesKept), nichts doppelt im parent-Bereich"
metrics:
  duration: "35 min"
  completed: "2026-10-24"
  tasks: 2
  files: 8
---

# Phase 6 Plan 19: Verwalter-Kernansicht dreisprachig Summary

Weltliste, Welt anlegen, Löschen-Dialog, Sicherungen, Einladen-Dialog und Spielerliste mit Erwachsen-Schalter lesen alle sichtbaren Texte aus dem parent-Wörterbuch (96 Schlüssel je Sprache), Deutsch nachweislich wortgleich zum Stand vor dem Plan.

**Basis-Commit (BASE):** `d090664bff4be2560505377e3c80664e9d08f1c9` (d090664). Alle Diff-Nachweise laufen gegen diese ID.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | b315a66 | ParentView und BackupSection umgestellt, parent.js de/en/fr komplett (auch die Schlüssel für Task 2), drei Ausnahme-Einträge |
| 2 | c9d46df | InviteDialog und PlayerManager umgestellt |

## Gate-Ergebnisse

- Alle neun `node frontend/tests/*.check.mjs`: grün; i18n.check meldet `parent: 96 keys in de, en and fr`, Positivkontrolle weiter mit allen Fehlertypen a bis j.
- `uv run pytest -q tests/test_frontend_privacy.py`: 8 passed (nach Task 1 und Task 2).
- `npx vite --mode production build --outDir <scratchpad>/gw-build-0619 --emptyOutDir`: grün (Task 1); `npm run build -- --outDir <scratchpad>/gw-build-0619-npm --emptyOutDir`: grün (Task 2, built in 7.22s, nur die bekannte Chunk-Größen-Warnung). Bundle enthält "Invite as adult".
- `git diff --quiet BASE -- js/`: exit 0.
- `uv run pytest -m "not docker" -q`: 2675 passed, 44 deselected (Plan-Ende, freier RAM vorher 2,4 GB, seriell).
- `grep -rn "v-html" frontend/src`: nur ein Kommentar in roles.js ("never v-html"), kein Einsatz (T-06-79).
- Keine U+2013/U+2014 in den sieben Dateien, kein "public"/"visibility" in parent.js, keine Emojis (i18n.check d/e/g).
- Französisch: 13 geschützte Leerzeichen als ` `-Escape, 0 echte U+00A0-Zeichen in den drei parent.js (`grep -c $'\xc2\xa0'` = 0).

### Wortgleichheit (Skript wordcheck.py im Scratchpad)

Das Skript nimmt jede entfernte Zeile aus `git diff -U0 BASE -- <komponenten>`, zieht Textknoten und String-/Template-Literale heraus, normalisiert `{{ x }}`, `${x}` und `{name}` zu `{}` und sucht jedes Bruchstück wörtlich in den Werten von de/parent.js und de/core.js.

- ParentView + BackupSection: 57 entfernte Zeilen, 58 Bruchstücke, 2 nicht gefunden: `presets.length > 0` und `selectedPreset` (Vue-Ausdrücke aus v-if/v-model in Zeilen, die wegen `:label` geändert wurden, kein Text).
- InviteDialog + PlayerManager: 52 entfernte Zeilen, 51 Bruchstücke, 0 nicht gefunden.
- Positivkontrolle: zwei absichtlich verfälschte de-Werte ("Trotzdem  sichern", "Spielzeit gilt") wurden beide als NOT FOUND gemeldet, danach Datei byte-gleich zurückgeschrieben (cmp).
- Satzzusammensetzung im Löschen-Dialog: früher `${base} Der Talk-Raum ...`, jetzt `${t(deleteMessage)} ${t(deleteTalk)}`; zwei ganze Sätze, Deutsch zeichengleich.

### Scan der vier Dateien (scan.py, Kommentare und style entfernt)

Suche nach Umlauten und den Wörtern der, die, das, und, nicht, bitte, ist, kein, keine, noch, gerade, Welt, Sicherung(en): 0 Treffer in allen vier Dateien (Positivkontrolle: Basisstand BackupSection.vue liefert 8 Treffer). Übrig bleiben nur Bezeichner und API-Werte: Status-Codes `running`, `starting`, `stopped`, `backing_up`, `restoring`, `failed`, Sicherungsart `vor-restore`, Pausenart `schluss`, Einladungsarten `group`/`group:`, die Überschrift `Gameworld` (Produktname).

## Begriffe

Nach der 06-17-Tabelle: Verwalter = Manager/Gestionnaire (Chip), Erwachsen = Adult/Adulte, Sicherungen = Backups/Sauvegardes, Wiederherstellen = Restore/Restaurer, Spielart = Game type/Type de jeu, Zeitfenster = Time window/Plage horaire, Talk-Raum = Talk room/salon Talk, Spielzeiten = playtimes/temps de jeu, Pause = break/pause. Nirgends "Admin" für Verwalter. Abweichungen siehe decisions (Spielstand beim Umbenennen).

## Deviations from Plan

**1. [Rule 3 - Blocking] frontend/tests/i18n.exceptions.json ergänzt (nicht in files_modified)**
- **Issue:** i18n.check (i) verlangt für Werte gleich Deutsch einen Ausnahme-Eintrag: en "Name", en "Status", fr "Pause".
- **Fix:** drei Einträge mit Begründung angehängt. Commit b315a66.

**2. Wörterbücher in einem Commit**
- Die drei parent.js wurden in Task 1 vollständig geschrieben (auch die Schlüssel für InviteDialog und PlayerManager), Task 2 hat nur noch die beiden Komponenten geändert. Inhaltlich gleich, nur andere Commit-Aufteilung.

**3. Probebau-Ziel Scratchpad statt `$TEMP/gw-build-0619`** (Session-Vorgabe für temporäre Dateien), Befehl sonst identisch.

**4. Kleinigkeit:** `deleteButtons` in ParentView ist jetzt `computed` statt ein festes Array (Beschriftungen beim Rendern aufgelöst); NcDialog bekommt weiterhin ein Array.

## Known Stubs

Keine. Unberührte deutsche Kommentare in den vier Komponenten übersetzt Plan 06-27.

## Threat Flags

Keine neue Angriffsfläche. T-06-79: Anzeigenamen und Gruppen-IDs gehen nur als Platzhalter-Parameter in t() und von dort per Textinterpolation oder gebundenem Attribut ins DOM, kein v-html. T-06-80: Die Bestätigung beim Einschalten von Erwachsen (InviteDialog und PlayerManager) nutzt unverändert die core-Texte confirmLead/confirmScope/confirmWarning/rulesKept, die in de/en/fr dieselben Folgen und die Kinder-Warnung nennen; Löschen nennt in allen drei Sprachen Spielwelt, Gebautes und (mit Talk) Talk-Raum samt Verlauf; Wiederherstellen nutzt restoreQuestion/playersWarning aus core. Platzhalter-Gleichheit belegt i18n.check (b).

## Self-Check: PASSED

- Dateien vorhanden: frontend/src/i18n/{de,en,fr}/parent.js (je 96 Schlüssel), vier Komponenten geändert, frontend/tests/i18n.exceptions.json
- Commits vorhanden: b315a66, c9d46df
