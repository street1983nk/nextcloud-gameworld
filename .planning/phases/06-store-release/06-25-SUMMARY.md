---
phase: 06-store-release
plan: 25
subsystem: backend, i18n
tags: [d-26, d-29, comments, docstrings, log-messages, english, refactor-free]
requires: ["06-24"]
provides:
  - "Kommentare, Docstrings und Log-Meldungen in src/gameworld/{__init__,config,lifecycle,main,nc}.py und in access, api, backup, events, notify Englisch (i18n/* war schon Englisch)"
  - "Log-Tests (test_lifecycle, test_logging_setup, test_invites_api) und gekoppelter Soll-Text in test_talk_bot auf die englischen Meldungen umgestellt"
  - "06-25-residuals.tsv: ein Eintrag (Bezeichner), in beide Richtungen abgeglichen"
affects: [06-26, 06-27, 06-28]
tech-stack:
  added: []
  patterns:
    - "Scratchpad-Werkzeug (nicht committet): AST-Hash je Datei ohne Docstrings und mit <LOG>-Platzhaltern in Log-Aufrufen, Platzhalterfolge und Argumentanzahl je Log-Aufruf, Tabellen-Anwendung (Datei, Zeilenbereich, neuer Text) mit CRLF-Erhalt"
key_files:
  created:
    - .planning/phases/06-store-release/06-25-residuals.tsv
  modified:
    - "42 Quelldateien unter src/gameworld (Wurzelmodule, access, api, backup, events, notify; i18n/* unverändert)"
    - tests/test_access_service.py
    - tests/test_verwalter_groups.py
    - tests/test_lifecycle.py
    - tests/test_logging_setup.py
    - tests/test_invites_api.py
    - tests/test_backup_archive.py
    - tests/test_backup_files.py
    - tests/test_notify_loop.py
    - tests/test_bot_events.py
    - tests/test_talk_bot.py
    - .planning/phases/06-store-release/deferred-items.md
decisions:
  - "Aktionsnamen in backup/files.py (_map_error(exc, \"Upload\"|\"Auflisten\"|...)) bleiben deutsch: Code-Argumente außerhalb des Log-Aufrufs, D-29 verbietet Code-Änderungen; als Rest in deferred-items.md"
  - "Verwalter heißt in Kommentaren manager, Lehrer teacher; Bezeichner (ROLE_VERWALTER, require_verwalter, verwalter_groups) und Verweise (D-17, T-06-02, WR-05) bleiben wörtlich"
  - "Welt-<id6> und Gameworld/Sicherungen in naming.py/files.py bleiben als Literale des Codes stehen (Restliste bzw. kein Treffer)"
metrics:
  duration: "ca. 75 min (davon ca. 22 min Wartezeit auf drei Volltestläufe)"
  completed: "2026-10-29"
  tasks: 3
  files: 49
---

# Phase 6 Plan 25: Übersetzungs-Pass Backend Teil 1 Summary

Kommentare, Docstrings und 81 Log-Aufrufe im ersten Backend-Teil sind Englisch; Code nachweislich unverändert (AST je Datei gleich, %-Platzhalter und Argumentanzahl je Log-Aufruf gleich).

**Basis-ID:** 579a1624c05923f71f7e38dc8154928d023ceaad

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | ebee59f | Wurzelmodule, access, 4 Log-Tests, Soll-Text in test_talk_bot |
| 2 | fb3af1d | api, test_invites_api |
| 3 | 516424a | backup, events, notify, 3 Testdateien mit Kommentaren, Restliste |

## Nachweise

- **AST-Gleichheit:** 52 Dateien (42 Quelldateien mit Docstrings entfernt und `<LOG>`-Platzhaltern in Log-Aufrufen, 10 Testdateien mit allen str-Konstanten als Platzhalter), vorher gleich nachher: 52 von 52 gleich. Prüfung nach jedem Stapel und zuletzt am Endstand.
- **Log-Format:** 81 Log-Aufrufe, Methode, %-Platzhalterfolge, Argumentanzahl und Keywords je Aufruf vorher gleich nachher (log-format-before/after).
- **Zeilenzahl** der Dateien aus tests/i18n_exceptions.tsv: api/alerts.py 266 zu 266, backup/files.py 253 zu 253, backup/naming.py 78 zu 78; tests/test_i18n.py grün.
- **Rest-Suche:** in Log-Aufrufen 0 Treffer (deutsche Wörter, Umlaute, ß, Umschriften); Kommentare und Docstrings 1 Treffer (`Welt-<id6>` in backup/naming.py:7), ein Eintrag in 06-25-residuals.tsv: kein Treffer ohne Eintrag, kein Eintrag ohne Treffer. Zusätzlich breitere Wortliste (Endungen -ung, -keit, Konto, Gruppe, ...) ohne weiteren Fund.
- **Kopplung außerhalb von tests/:** alle 81 alten Log-Texte (Fragmente mit mindestens zwei Wörtern) per `grep -F` über scripts/, docs/, README*: keine Treffer. Die Treffer von "registriert" in Skripten sind eigene Skript-Meldungen.
- **Testanzahl** `pytest -m "not docker" --collect-only`: vorher 2867/2911 (44 abgewählt), nachher 2867/2911.
- **Gates (Endstand):** ruff check All checks passed; ruff format --check 206 files already formatted; pyright (PYRIGHT_PYTHON_FORCE_VERSION=latest) 0 errors, 0 warnings; vulture ohne Befund (Exit 0).
- **Volle Suite** (`uv run pytest -m "not docker" -q`): 2866 passed, 1 failed, 44 deselected (405 s). Der eine Fehlschlag, `tests/test_admin_snapshot.py::test_ex_admin_gets_no_attempt_or_review_after_check`, schlägt auch an der Basis 579a162 fehl (Gegenprobe in einer `git archive`-Kopie mit PYTHONPATH auf die Kopie: 1 failed, der zweite Probetest passed) und ist nicht von 06-25 verursacht, siehe deferred-items.md. Erster Lauf (nach Task-1-Stand): 2865 passed, 2 failed (derselbe plus test_talk_bot, dort behoben).
- Gezielt: `tests/test_access_service.py tests/test_verwalter_groups.py tests/test_lifecycle.py tests/test_logging_setup.py` 136 passed.

## Geänderte Literale in Tests (Datei, Zeile, alt, neu)

| Datei | Zeile | alt | neu | neuer Soll-Text in neuer Log-Meldung |
|-------|-------|-----|-----|---------------------------------------|
| tests/test_lifecycle.py | 143 | `"2 Fehler"` | `"2 errors"` | ja: `"Worlds not fully removed on deactivation: %d errors"` (lifecycle.py:81, mit %d = 2) |
| tests/test_logging_setup.py | 37 | `"Abgleich Welt %s: %s"` | `"Reconciliation world %s: %s"` | Text wird im Test selbst erzeugt |
| tests/test_logging_setup.py | 40 | `"Abgleich Welt"` | `"Reconciliation world"` | siehe Zeile 37 |
| tests/test_invites_api.py | 426 | `"Abgleich"` | `"Invitation reconciliation"` | ja: Teilstring von `"Invitation reconciliation on manager visit failed: %s"` (api/worlds.py:207), Skriptprüfung True |
| tests/test_invites_api.py | 281, 502 | `"Ohne Log-Einträge wäre der Test wertlos"` | `"Without log entries the test would be worthless"` | Assert-Meldung |
| tests/test_talk_bot.py | 315 | `"Talk-Bot"` | `"Talk bot"` | ja: Teilstring von `"Talk bot not %s: %s"` (lifecycle.py:66), Skriptprüfung True |

Negativ-Asserts mit Positivkontrolle unverändert: test_lifecycle ("geheime Docker-Meldung"/"geheim" mit `"RuntimeError" in caplog.text`), test_verwalter_groups ("geheimer Fehlertext" mit `"RuntimeError" in caplog.text`), test_access_service (Passwort/Verifier mit WARNING-Record-Assert), test_invites_api (beide `assert caplog.records, ...`), test_backup_files ("Burg"/"admin" mit `"507" in caplog.text`), test_notify_language (`role_lookup_error` als Positivkontrolle).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Kopplung außerhalb der genannten Testdateien: tests/test_talk_bot.py**
- **Found during:** Task 1, erster Volltestlauf
- **Issue:** `test_enable_with_talk_error_still_succeeds` erwartet `"Talk-Bot" in caplog.text`; die Quelle ist die Log-Zeile in lifecycle.py (Datei dieses Plans), die Meldung wurde englisch. Der Kopplungscheck des Plans deckte nur die genannten Testdateien ab, nicht die ganze Suite.
- **Fix:** Soll-Text auf `"Talk bot"` umgestellt (eine Zeile, sonst keine Änderung an test_talk_bot.py; die Datei gehört sonst zu 06-26/06-28). Der Negativ-Assert `"secret-xyz" not in caplog.text` direkt davor bleibt.
- **Files modified:** tests/test_talk_bot.py
- **Commit:** ebee59f

**2. [Rule 1 - Format] ruff format fasste einen Log-Aufruf zusammen**
- **Found during:** Task 3
- **Issue:** Der mehrzeilige `LOG.warning(...)` in notify/loop.py passte nach der Kürzung in eine Zeile; `ruff format --check` schlug an.
- **Fix:** `ruff format` auf die Datei (nur Umbruch, AST gleich).
- **Commit:** 516424a

### Abweichungen im Vorgehen

- Alle drei Tasks wurden in einem Arbeitsgang übersetzt und geprüft (ein Stapel pro Dateigruppe, AST-Vergleich nach jedem Stapel), danach in drei Task-Commits getrennt nach Dateien. Die Gates liefen auf dem Gesamtstand und vor den Commits.
- Aktionsnamen in backup/files.py (`"Upload"`, `"Auflisten"`, `"Abfrage"`, `"Download"`, `"Löschen"`) fließen als Argument in die englische Log-Zeile `"Nextcloud files: %s failed ..."`. Sie bleiben deutsch, weil es Code-Argumente außerhalb des Log-Aufrufs sind (deferred-items.md).
- Nicht übersetzt, weil nutzersichtbar oder Literale des Codes: i18n/* (schon Englisch), MSG_-Konstanten, Texttabellen NOTIFY_TEXTS/BOT_TEXTS, uvicorn-Logfilter (nur Kommentare angefasst), `Welt-`, `Gameworld/Sicherungen`, Zitate wie `"Heute gespielt: Lena 1 Min."`, `"Weiter"`, `"Für heute Schluss"`.

## Deferred Issues

Siehe `.planning/phases/06-store-release/deferred-items.md`:
- tests/test_admin_snapshot.py::test_ex_admin_gets_no_attempt_or_review_after_check schlägt schon an der Basis fehl.
- Deutsche Aktionsnamen in backup/files.py im englischen Log.
- Bestand: Negativ-Log-Asserts ohne Positivkontrolle in test_backup_archive, test_notify_loop, test_bot_events.

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche (reine Textänderung). T-06-96 (AST gleich), T-06-102 (keine neuen Log-Werte, Argumente und Platzhalterfolge gleich), T-06-103 (Platzhalterfolge gleich) wie im Plan mitigiert.

## Self-Check: PASSED

- 06-25-residuals.tsv vorhanden; Commits ebee59f, fb3af1d, 516424a im Log; Autor street1983nk; nicht gepusht; .planning/config.json unberührt (weiter ` M`).
