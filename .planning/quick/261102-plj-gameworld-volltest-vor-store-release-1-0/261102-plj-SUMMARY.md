---
phase: quick-261102-plj
plan: 01
subsystem: testing
tags: [audit, i18n, playwright, release, volltest]
requires: []
provides:
  - "scripts/audit/: wiederholbarer Sprach-, Darstellungs-, Funktions-, Rechte- und Ladezeittest"
  - "261102-plj-BEFUNDE.md: Befundliste vor dem Store-Release 1.0.0"
affects: [store-release]
tech-stack:
  added: []
  patterns: ["Playwright aus npx-Cache via NODE_PATH", "Fremdwort-Detektor aus Frontend-Wörterbüchern plus Server-Katalog"]
key-files:
  created:
    - scripts/audit/README.md
    - scripts/audit/dump_catalog.py
    - scripts/audit/lang_detector.mjs
    - scripts/audit/selftest.mjs
    - scripts/audit/common.mjs
    - scripts/audit/audit.mjs
    - scripts/audit/functional.mjs
    - scripts/audit/cleanup.mjs
    - scripts/audit/layout_probe.mjs
    - scripts/audit/layout_selftest.mjs
    - scripts/audit/loadtimes.mjs
    - .planning/quick/261102-plj-gameworld-volltest-vor-store-release-1-0/261102-plj-BEFUNDE.md
  modified: []
decisions:
  - "Wegwerf-Welt der Dialogprüfung legt der NC-Admin an: gw-lehrer darf mia nicht einladen (nicht in seinen Gruppen), mia wird für die Spieler-Dialoge gebraucht"
  - "Kopierbefehle des Setup-Checks über proxy_commands() mit Standardadresse geprüft, weil der Dev-Stack 127.0.0.1:23750 nutzt und die UI sie dort absichtlich nicht zeigt"
  - "eltern nach Prüfung als Gruppen-ID in die Datenliste des Detektors aufgenommen"
metrics:
  duration: "ca. 100 min"
  completed: 2026-11-02
---

# Quick 261102-plj: Gameworld-Volltest vor Store-Release 1.0.0 Summary

Wiederholbares Prüfwerkzeug unter scripts/audit/ (Fremdwort-Detektor mit Positiv- und Negativkontrolle, Playwright-Lauf über 3 Rollen x 3 Sprachen x 1280/390 px, Funktions- und Rechtetests an Wegwerf-Welten, Ladezeiten) plus Befundbericht: kein blockierender Befund, kein Sprachfehler, 3 Punkte "sollte vor Release", 7 kosmetisch.

## Ergebnisse

- Detektor-Selbstprüfung: PASSED (exklusive Wörter de 673, en 460, fr 669); Layout-Selbstprüfung 4/4.
- Sprach- und Darstellungslauf: 228 Ansichten/Dialoge plus 114 im Zusatzlauf (Ferien-Dialog), 0 echte Sprachtreffer, 0 waagerechtes Scrollen, 0 abgeschnittene Texte.
- Funktions-, Fehlerpfad-, Rechte- und Proxy-Tests: 347 Ergebnisse, 0 Fehlschläge.
- pytest: 2970 passed (unit), e2e 44 passed, 8 skipped (kein Lua-Compiler im Image).
- Ladezeiten: admin Median 3,06 s (knapp über Schwelle), gw-lehrer 2,41 s, mia 1,75 s.
- Befunde "sollte vor Release": Erwachsen-Marke hinkt 11 bis 13 s (bekannt waren 1 bis 2 s), Admin-Hauptansicht über 3 s, Escape schließt Einladen/Zeitfenster/Spieler-Dialog in bestimmten Fokuslagen nicht.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | 984b12c | test(audit): add language audit tooling with detector self-test |
| 2 | eaccdf5 | test(audit): cover all actions, roles, languages and 390 px |
| 2 (Nachtrag) | 815176d | test(audit): open the holiday remove dialog with a temporary future holiday |
| 3 | d5dad19 | test(audit): measure main view load times |

## Deviations from Plan

1. [Rule 3] Playwright-Cache 9833c18b2d85bc59 (1.64-alpha) fand seinen Browser nicht; der im Plan genannte Ausweich-Cache e41f203b7505f1fb (1.63.0) wurde genutzt.
2. [Rule 1] Quellskript schickte Änderungen ohne JSON-Content-Type (CSRF-Regel 403) und nutzte falsche Pfade (/api/holidays, Feldnamen start/end); in common.mjs korrigiert.
3. [Rule 3] gw-lehrer kann mia nicht einladen (403, richtiges Verhalten). Wegwerf-Welt der UI-Dialoge vom NC-Admin angelegt; in functional.mjs Einladung/Spielzeit von mia als admin, die Ablehnung für gw-lehrer als Negativtest protokolliert.
4. Planvorlage nannte attempts/review/origin unter /api/admin; tatsächlich unter /api (Verwalter). Rechtetest entsprechend.
5. Starten/Stoppen/Neustarten haben keinen Bestätigungsdialog (direkte Aktionen) und wurden deshalb nie geklickt; nur der Löschen-Dialog wurde geöffnet und abgebrochen.
6. Sicherungsordner tragen den Weltnamen, nicht die ID; Aufräumen daher über das Präfix audit261102- im Ordnernamen.
7. Zusätzliche Werkzeuge: common.mjs, cleanup.mjs, layout_probe.mjs, layout_selftest.mjs (Positivkontrolle der Darstellungsprüfung, Fehlalarm der versteckten Tabellenkopfzeile behoben).
8. e2e-Suite in einem Aufruf (20:47 min) statt zwei Gruppen, weil das Werkzeug lange Läufe ohnehin im Hintergrund weiterführt; 8 von der Suite hinterlassene anonyme Volumes nach Prüfung entfernt (Befund 10).
9. functional.mjs wurde in Abschnitten (SECTIONS) gelaufen; functional.json ist die Zusammenführung der Teilergebnisse.

## Nicht geprüft

Talk-Raum-neu-anlegen- und Reste-Dialog (Zustand nicht herstellbar), Kopierbefehle in der Oberfläche (nur Standardadresse), Spieltexte live im Client, echte Telefone. Details im Bericht.

## Self-Check: PASSED

- Alle Dateien unter scripts/audit/ und BEFUNDE.md vorhanden; Commits 984b12c, eaccdf5, 815176d, d5dad19 im Log.
- Baseline-Vergleich identisch, keine audit261102-Reste, lang-Settings im Ausgangszustand, keine Änderung unter src/, frontend/, appinfo/.
