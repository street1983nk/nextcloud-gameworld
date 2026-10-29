---
phase: 06-store-release
plan: 28
subsystem: tests, i18n
tags: [d-26, comments, docstrings, tests, english, refactor-free]
requires: ["06-24"]
provides:
  - "Kommentare und Docstrings in 83 Testdateien (tests/*.py, tests/e2e, tests/play) Englisch, ohne die Dateien, die 06-25 und 06-26 besitzen"
  - "06-28-residuals.tsv: 1 Eintrag (Verzeichnispfad), in beide Richtungen abgeglichen"
affects: [06-27]
tech-stack:
  added: []
  patterns:
    - "Scratchpad-Werkzeug (nicht committet): AST-Hash ohne Docstrings je Datei, Extraktion der COMMENT-Tokens und Docstrings, Tabellen-Anwendung mit Zeilenbereichen (CRLF-Arbeitskopie bleibt erhalten), Rest-Suche"
key-files:
  created:
    - .planning/phases/06-store-release/06-28-residuals.tsv
  modified:
    - "83 Testdateien unter tests/ (Teil A, Teil B, tests/e2e und tests/play); 6 Dateien der Liste hatten nichts zu übersetzen"
decisions:
  - "Verwalter heißt in Kommentaren manager (wie 06-25); Bezeichner, Verweise (D-17, T-06-02, WR-05) und zitierte deutsche Soll-Texte bleiben wörtlich"
  - "Die eigenen Regelnamen in Zitaten (etwa Owner-Regel \"Gegenprobe nie mit dem Muster der Umsetzung\") bleiben als Zitat stehen und stehen deshalb nicht in der Restliste (Anführungszeichen-Filter der Rest-Suche)"
metrics:
  duration: "Suite 490 s"
  completed: 2026-10-29
---

# Phase 6 Plan 28: Übersetzungs-Pass Testsuite Summary

Kommentare und Docstrings der Testsuite ohne Log-Bezug sind Englisch (D-26, Teil 4 von 4); kein Code, kein Literal, keine Prüfung hat sich geändert.

## Commits

| Task | Commit | Betreff |
| ---- | ------ | ------- |
| 1 | dca50de | refactor(06-28): comments and docstrings in tests part A to English (D-26) |
| 2 | fb3ed6a | refactor(06-28): comments and docstrings in tests part B to English (D-26) |
| 3 | 851ce96 | refactor(06-28): comments and docstrings in tests/e2e and tests/play to English (D-26) |

Basis-Commit des Passes: 4cc2a18f582af729a4f69f1654f3b50ad891d2e4 (`$TEMP/gw-base-06-28`).

## Verifikation

- AST ohne Docstrings: 89 Dateien der Liste, vorher gleich nachher (`ALL EQUAL 89`), mehrfach während des Passes und nach dem letzten Edit geprüft.
- Testanzahl je Datei vorher gleich nachher (Vergleich der `--collect-only`-Zeilen, alle Dateien): not docker 2867 Tests in 83 Dateien, docker 52 Tests in 20 Dateien; nur die Dateien dieses Plans: not docker 1885 (63 Dateien), docker 37 (17 Dateien).
- Volle Suite `pytest -m "not docker" -q`: 2867 passed, 52 deselected (490 s).
- ruff check: All checks passed; ruff format --check: 207 files already formatted; pyright (latest, `--pythonpath .venv/Scripts/python.exe`): 0 errors, 0 warnings; vulture: ohne Treffer.
- Rest-Suche (Regex aus Plan 06-25 Schritt 8 über Kommentare und Docstrings ohne Anführungszeichen-Zitate): 1 Treffer, in 06-28-residuals.tsv (tests/e2e/luanti_probe.py Zeile 5, Pfad `.planning/phases/03-zugang-und-rollen/spike/`). Abgleich in beide Richtungen ohne Fehler.
- Zusatzprüfung gegen Lücken der Regex: Vergleich aller Kommentare und Docstrings vor und nach dem Pass (unveränderte Stellen einzeln gelesen). Dabei fielen rund 150 deutsche Kurzkommentare auf, die die Wortliste der Rest-Suche nicht trifft ("# Erfolgsfall", "# Dublette", "# Provisioner"); sie sind mit übersetzt.
- `git diff --stat <Basis> -- tests`: 83 Dateien, 1188 Zeilen hinzu, 1188 entfernt; alle in files_modified.
- Keine Em-Dashes oder En-Dashes in den geänderten Testdateien.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Vorab gefundene Zeilenlänge**
- **Found during:** Task 2 (ruff check)
- **Issue:** Die englische Fassung eines Docstrings in tests/test_nc.py war 125 Zeichen lang (E501).
- **Fix:** Kürzer formuliert.
- **Files modified:** tests/test_nc.py
- **Commit:** fb3ed6a

Sonst: Plan wie geschrieben ausgeführt. Der Plan hängt nur von 06-24 ab (`depends_on`), nicht von 06-27; die Reihenfolge 06-28 vor 06-27 ist unproblematisch.

### Hinweise zum Vorgehen

- Die drei Tasks wurden zusammen übersetzt und danach nach Dateigruppen in drei Commits geteilt; die Gates liefen über den gesamten Stand, nicht je Task-Zwischenstand.
- Eine Arbeitskopie-Eigenheit: 42 Testdateien liegen im Arbeitsbaum mit CRLF (Index LF). Das Anwendungswerkzeug erhält die Zeilenenden je Datei, der Diff zeigt nur die geänderten Textzeilen.
- Mehrzeilige Kommentarblöcke wurden zeilenweise neu umbrochen (Zeilenzahl nicht erhalten); das ist erlaubt, weil keine Testdatei in tests/i18n_exceptions.tsv steht.

## Log-Text-Asserts

Nur tests/play/test_log_redact.py enthält caplog-nahe Prüfungen (Redact-Format von /play/ws, schon englisch). Dort wurden ausschließlich Docstrings übersetzt, die Literale sind unverändert (AST gleich). In keiner anderen Datei dieses Plans steht ein Log-Text-Assert.

## Offene Punkte

- **Docker-Tests nicht ausgeführt:** Docker Desktop startet derzeit nicht. Der Plan sieht auch keinen Lauf vor (nur Kommentare); die 52 docker-markierten Tests wurden nur gesammelt (gleiche Zahl wie vorher), nicht bestanden gemeldet.
- **06-27 steht aus:** Damit ist D-26 noch nicht komplett; die Anforderung PLATT-01 wird deshalb nicht als erledigt markiert.
- **Beobachtung (nicht geändert):** In den deutschen Test-Texten blieben bewusst deutsche Zitate in Kommentaren stehen (Kindertexte, Bot-Befehle).

## Known Stubs

Keine.

## Self-Check: PASSED

- 06-28-residuals.tsv vorhanden, Commits dca50de, fb3ed6a, 851ce96 vorhanden.
