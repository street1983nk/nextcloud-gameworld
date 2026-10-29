---
phase: 06-store-release
plan: 26
subsystem: backend, i18n
tags: [d-26, d-29, comments, docstrings, log-messages, lua-comments, english, refactor-free]
requires: ["06-24", "06-25"]
provides:
  - "Kommentare, Docstrings und Log-Meldungen in src/gameworld/{worlds,playtime,play,talk,provisioner} Englisch"
  - "Kommentare im erzeugten Lua-Code der drei Welt-Mods Englisch (Zeilen-Diff-Beleg: nur Kommentarzeilen oder nachgestellte Kommentare)"
  - "Golden-Hashes der deutschen Mods in tests/test_mod_texts.py neu gesetzt"
  - "tests/e2e/test_mod_syntax_e2e.py: docker-markierter Lua-Syntaxtest (8 Tests)"
  - "06-26-residuals.tsv: 6 Zitat-Einträge, in beide Richtungen abgeglichen"
  - "Vorab-Fix: Zeitbombe in tests/test_admin_snapshot.py behoben"
affects: [06-27, 06-28]
tech-stack:
  added: []
  patterns:
    - "Scratchpad-Werkzeug (nicht committet) wie in 06-25: AST-Hash ohne Docstrings mit <LOG>-Platzhaltern und <MOD>-Platzhalter für mehrzeilige Mod-Konstanten, Platzhalterfolge je Log-Aufruf, Tabellen-Anwendung mit Zeilenbereichen, Zeilen-Diff der erzeugten Mod-Dateien"
key_files:
  created:
    - tests/e2e/test_mod_syntax_e2e.py
    - .planning/phases/06-store-release/06-26-residuals.tsv
  modified:
    - "41 Quelldateien unter src/gameworld (worlds 6, playtime 7, play 13, talk 4, provisioner 11)"
    - tests/test_admin_snapshot.py
    - tests/test_service_lifecycle.py
    - tests/test_reconciler.py
    - tests/test_talk_bot.py
    - tests/test_talk_rooms.py
    - tests/test_talk_service.py
    - tests/test_provisioner_errors.py
    - tests/test_mod_texts.py
    - tests/play/test_play_ticket_api.py
    - tests/play/test_play_ws.py
    - tests/play/test_sessions.py
    - tests/e2e/test_play_proxy_e2e.py
    - tests/e2e/test_play_srp_e2e.py
    - .planning/phases/06-store-release/deferred-items.md
decisions:
  - "Vorab-Fix setzt die Engine-Uhr (world_service.time._clock) statt time.time: TimeEngine bindet time.time als Default-Argument beim Import, ein Patch von time.time griffe nur für service.py-Pfade"
  - "Deutsche Aktionsnamen in talk/service.py (_isolated/_spawn: Anlegen, Abgleich, Löschen) bleiben als Code-Argumente stehen (D-29), Eintrag in deferred-items.md"
  - "PLATT-01 nicht abgehakt: 06-27 und 06-28 (Teil 3 und 4) fehlen noch"
metrics:
  duration: "mehrere Stunden (davon ca. 12 min Wartezeit auf Volltest und Teilläufe)"
  completed: "2026-10-29"
  tasks: 3
  files: 59
---

# Phase 6 Plan 26: Übersetzungs-Pass Backend Teil 2 Summary

Kommentare, Docstrings und 90 Log-Aufrufe in worlds, playtime, play, talk und provisioner sind Englisch, dazu die Lua-Kommentare der erzeugten Welt-Mods; Code nachweislich unverändert (AST je Datei gleich, Platzhalterfolge gleich, erzeugte Mod-Dateien nur in Kommentarzeilen verschieden).

**Basis-ID:** 90a7505fb2982821f1133721a907d65a6a305f9b (Kopf nach dem Vorab-Fix; Kopf vor dem Plan war 7db5f3c)

## Commits

| Schritt | Commit | Inhalt |
|---------|--------|--------|
| Vorab-Fix | 90a7505 | test(06-26): Engine-Uhr in den Admin-Snapshot-Tests auf die Test-Epoche setzen, deferred-items erledigt |
| Task 1 | 67acf7f | worlds, playtime, test_service_lifecycle, test_reconciler |
| Task 2 | 2a43932 | play, talk, acht Testdateien |
| Task 3 | c87315a | provisioner inkl. Lua-Kommentare, test_mod_texts, test_provisioner_errors, test_mod_syntax_e2e, Restliste |

## Vorab-Fix: test_ex_admin_gets_no_attempt_or_review_after_check

- **Ursache:** Der Test bucht Nutzung auf das feste DAY = 21.10.2026. `TimeEngine._maybe_prune` (`_RETENTION_DAYS = 7`, `local_day(now)`) rechnet mit `self._clock`, das als Default-Argument `time.time` beim Import bindet. Ab 29.10.2026 liegt DAY mehr als 7 Tage zurück, der erste Render des Laufs löscht die Zeile, der "Tagesrückblick" fehlt.
- **Fix:** In der `service`-Fixture von tests/test_admin_snapshot.py setzt `monkeypatch.setattr(world_service.time, "_clock", lambda: float(_epoch(20, 1)))` die Engine-Uhr auf die Test-Epoche. Produkt und Assertions unverändert (3 Zeilen).
- **Abweichung vom Auftrag:** Ein Patch von `time.time` hätte die Engine nicht erreicht (Default-Argument zur Importzeit), darum die Engine-Uhr direkt.
- **Nachweis:** Datei 26 passed (vorher 1 failed). Positivkontrolle: Mit Uhr `_epoch(20, 1) + 10 Tage` scheitert derselbe Test wieder (1 failed, 25 passed), der Prune greift also weiter.
- **Dieselbe Zeitbombe anderswo:** Dateien mit festem DAY: test_alerts_api, test_forget_account, test_notify_language, test_notify_loop, test_notify_throttle. Probelauf mit einem Plugin, das `time.time` um 40 Tage vorstellt (importzeitig, also auch die Engine): forget_account 13, notify_language 35, notify_loop 26, notify_throttle 16 passed, kein Prune-Befund; test_alerts_api 5 failed, aber durch einen anderen Mechanismus (Review-Fenster gegen heutiges Datum, nicht Prune). Fix daher nur in test_admin_snapshot.py; der alerts_api-Befund steht in deferred-items.md.

## Nachweise

- **AST-Gleichheit:** 54 Dateien (42 Quelldateien mit Docstrings entfernt, `<LOG>`-Platzhaltern in Log-Aufrufen und `<MOD>`-Platzhalter für die mehrzeiligen Lua-Konstanten in access_mod, time_mod, status_mod, luanti_conf; 12 Testdateien mit allen str-Konstanten als Platzhalter), vorher gleich nachher: 54 von 54 gleich, geprüft nach jedem Stapel und am Endstand. Der Vergleich fing zwei Eingabefehler ab (ein fehlgeleiteter Docstring-Schluss in play/framing.py, eine versehentlich gelöschte Zeile `self._time.forget(row.id)` in worlds/service.py); beide behoben, danach gleich.
- **Log-Format:** 90 Log-Aufrufe, Methode, %-Platzhalterfolge, Argumentanzahl und Keywords je Aufruf vorher gleich nachher.
- **Bereits englische Logs und Redaktion:** `git diff <Basis> -U0 -- src/gameworld/play | grep LOG.` zeigt nur die sieben Spielstart-Zeilen in ticket_api.py; play/ws.py, play/sessions.py, play/relay.py behalten ihre Log-Zeilen byte-gleich; play/log_redact.py unterscheidet sich nur in Docstring- und Kommentarzeilen.
- **Zeilenzahl** der Dateien aus tests/i18n_exceptions.tsv: worlds/store.py 1519 zu 1519, provisioner/archive.py 297 zu 297 (jede Zeile durch genau eine ersetzt); tests/test_i18n.py grün.
- **Zeilen-Diff der erzeugten Mod-Dateien** (37 Dateien: init.lua je access_mod/time_mod de, en, fr, status_mod, minetest.conf und world.mt je Preset, Zugangs- und Regeldatei, vollständiges build_world_files-Tar je Sprache mit allen Mod-Dateien): Zeilenanzahl überall gleich; 16 Dateien mit Änderungen, 408 abweichende Zeilen, davon 390 reine Kommentarzeilen (Form a) und 18 nachgestellte Kommentare hinter byte-gleichem Code-Präfix (Form b); 0 Verstöße. Konfigurationsdateien (minetest.conf, world.mt, Zugangs- und Regeldatei, Regeldatei) enthalten keine Kommentare und sind byte-gleich. Code ohne Kommentarzeilen (Lua) für de, en, fr vorher gleich nachher (diff leer). Lua-Quelltext bleibt ASCII, keine Langkommentare (`--[`). Die Vorher-SHA-256 von access und time (de) stimmen mit den alten Golden-Werten überein.
- **Golden-Hashes** (tests/test_mod_texts.py): access de `fc1e5327...` zu `d2aecfe0ca5b60566a215753c420521093f13699291321d76c9d7a53c6b8dca2`, time de `5039a654...` zu `d88731c9485f0cc4cf95ada37dc741adce88a34e286564490ddb93eba27d0eb5`, mit englischem Kommentar zum Grund. Spieltexte (Stringliterale) unverändert: AST gleich, Lua nur in Kommentarzeilen verschieden. test_time_mod.py, test_access_mod.py, test_archive.py unverändert (`git diff --quiet` Exit 0) und grün.
- **Rest-Suche:** Log-Aufrufe 0 Treffer (deutsche Wörter, Umlaute, ß, Umschriften); Lua-Kommentare 0 Treffer (Zitate in Anführungszeichen ausgenommen, ASCII-Umschriften fuer/ueber/koennen/waehrend/Passwoerter/Zaehlbuch/naechste nach dem Pass nicht mehr vorhanden); Kommentare und Docstrings 6 Treffer, alle Zitate von Kindertexten oder Bot-Befehlen in verschachtelten Anführungszeichen, alle 6 in 06-26-residuals.tsv: kein Treffer ohne Eintrag, kein Eintrag ohne Treffer.
- **Kopplung außerhalb von tests/:** alle 89 alten Log-Texte (Fragmente mit mindestens zwei Wörtern) per `grep -rIlF` über scripts/, docs/, README*: keine Treffer.
- **Testanzahl** `pytest -m "not docker" --collect-only`: Basis 2864/2908 (44 abgewählt), jetzt 2867/2919 (52 abgewählt). Der Unterschied von +3 nicht-docker-Tests sind drei `.claude-active`-Dateien unter frontend/src (Umgebungsartefakt, in tests/test_frontend_i18n.py parametrisiert, nicht von diesem Plan); die Knoten-ID-Listen sind sonst identisch. +8 abgewählte sind die neuen docker-Tests.
- **Gates (Endstand):** ruff check All checks passed; ruff format --check 207 files already formatted; pyright (PYRIGHT_PYTHON_FORCE_VERSION=latest, `--pythonpath .venv/Scripts/python.exe`) 0 errors, 0 warnings; vulture Exit 0.
- **Volle Suite** (`pytest -m "not docker" -q`, Endstand vor dem Docs-Commit): 2867 passed, 52 deselected, 1 warning (456 s). Gezielte Läufe vorher: Task 1 313 passed, Task 2 586 passed, Task 3 380 passed (test_mod_texts, test_time_mod, test_access_mod, test_archive, test_provisioner_errors, test_i18n).

## Geänderte Literale in Tests (Datei, Zeile, alt, neu)

| Datei | Zeile | alt | neu | neuer Soll-Text in neuer Log-Meldung |
|-------|-------|-----|-----|---------------------------------------|
| tests/test_service_lifecycle.py | 1599 | `"Zählbuch unvollständig"` | `"ledger incomplete"` | ja: `"World %s: ledger incomplete (%d bytes), not booked in this tick"` (worlds/service.py) |
| tests/test_reconciler.py | 425 | `"verwaiste Welt-Container: 2"` | `"orphaned world containers: 2"` | ja: `"orphaned world containers: %d (%s)"` (worlds/service.py, mit %d = 2) |
| tests/test_provisioner_errors.py | 481, 505, 516 | `"gekappt"` | `"truncated"` | ja: `"World %s: %s is larger than %d bytes and was truncated"` (provisioner/client.py); 516 ist die Negativprobe, Positivkontrollen 481 und 505 im Nachbartest |
| tests/play/test_play_ticket_api.py | 706 | `"Spielstart freigegeben"` | `"play start granted"` | ja: `LOG.info("play start granted")` (play/ticket_api.py) |
| tests/play/test_play_ticket_api.py | 707 | `"Spielstart abgelehnt: used_or_unknown"` | `"play start refused: used_or_unknown"` | ja: Präfix von `"play start refused: %s"` mit dem Grund-Wert |
| tests/test_mod_texts.py | 18, 19 | alte Golden-Hashes | neue Golden-Hashes (siehe oben) | Hash des erzeugten init.lua |

Negativ-Asserts mit Positivkontrolle unverändert: test_service_lifecycle ("Mia", "Geheimname", "geheim-intern" mit `"ledger incomplete"`, `broken.id in caplog.text`, `"ProvisionerError" in caplog.text`), test_provisioner_errors ("Spieler_", "Fremder_geheim" mit `"truncated" in caplog.text`), test_talk_bot ("Lena", "secret-xyz" mit `"Talk bot" in caplog.text`), test_talk_rooms/test_talk_service (Status/Typname als Positiv). test_talk_rooms.py Zeile 137 (`match="Talk antwortet gerade nicht"`) ist eine Nutzermeldung und bleibt. Die vom Plan benannten Soll-Texte "TalkUnavailableError" und "OSError" sind Typnamen und blieben.

## Lua-Syntaxtest (Warnung W1)

- `tests/e2e/test_mod_syntax_e2e.py` angelegt: 8 Tests (status_mod, access_mod und time_mod je de/en/fr, dazu Positivkontrolle mit der kaputten Zeile `if then`). Gewählte Variante: Der Test sucht im gepinnten Image (`LUANTI_IMAGE` aus spec.py, Digest, kein neues Image) zuerst `luac`, `luac5.1`, `luajit` (`command -v`), parst die erzeugte init.lua mit `luac -p` bzw. `luajit -bl` und führt sie nie aus; ohne Compiler überspringt er mit Begründung (Ersatz: test_time_mod_e2e.py und test_access_e2e.py). Zugriff über docker-py auf den Dev-Proxy wie die übrigen e2e-Tests.
- **Nicht gelaufen:** Docker Desktop startet auf diesem Rechner nicht ("Docker Desktop is unable to start", Daemon-Pipe fehlt, Proxy tcp://127.0.0.1:23750 nicht erreichbar). Der Test wird ohne Proxy übersprungen (8 skipped); ob das Image einen Lua-Compiler mitbringt, ist offen. Der Syntaxbeleg beruht bis dahin auf dem Zeilen-Diff: Alle 408 abweichenden Zeilen sind Kommentare, der Code ist byte-gleich, Langkommentare kommen nicht vor; ein neuer Syntaxfehler ist damit ausgeschlossen. Nachholen in deferred-items.md.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Zeitbombe in test_admin_snapshot.py** (Vorab-Fix, siehe oben, Commit 90a7505)

**2. [Rule 3 - Blocking] Docker nicht verfügbar**
- **Found during:** Task 3
- **Issue:** Der Plan verlangt den docker-Lauf der neuen und der beiden Play-e2e-Dateien; Docker Desktop lässt sich nicht starten, der Dev-Proxy fehlt.
- **Fix:** Test trotzdem angelegt, lint-, format- und pyright-sauber, mit Auto-Skip; Beleg ersatzweise per Zeilen-Diff; Nachholen vermerkt. Die e2e-Dateien test_play_proxy_e2e.py und test_play_srp_e2e.py haben nur Kommentar- und Docstring-Änderungen (AST gleich).
- **Files modified:** tests/e2e/test_mod_syntax_e2e.py
- **Commit:** c87315a

### Abweichungen im Vorgehen

- Die volle Suite lief nicht nach jedem der drei Tasks, sondern einmal am Endstand (456 s); nach den Tasks liefen gezielte Läufe, ruff, und nach Task 1 und 2 auch pyright und vulture. Die Gates am Endstand sind grün.
- Ein Vorher-Beleg der Mod-Dateien (37 erzeugte Dateien) wurde vor dem Pass aus dem Arbeitsbaum erzeugt (provisioner war zu dem Zeitpunkt unverändert) und mit dem Stand nach dem Pass verglichen.
- Die Dev-Docker-Probe kostete einen Start-Versuch von Docker Desktop (`Start-Process`), ohne Warteschleife.
- Deutsche Aktionsnamen in talk/service.py (Anlegen, Abgleich, Löschen) bleiben als Code-Argumente (deferred-items.md).
- `requirements mark-complete PLATT-01` nicht ausgeführt: Teil 3 und 4 (06-27, 06-28) fehlen.

## Deferred Issues

Siehe `.planning/phases/06-store-release/deferred-items.md`:
- Deutsche Aktionsnamen in talk/service.py im englischen Log.
- Lua-Syntaxtest und Play-e2e-Läufe mit echtem Docker nachholen.
- tests/test_alerts_api.py: Review-Tests mit anderem Zeitmechanismus (bei 40 Tagen späterer Uhr rot).

## Known Stubs

Keine.

## Threat Flags

Keine neue Angriffsfläche (reine Textänderung; neuer Test greift nur lesend über den vorhandenen Dev-Proxy auf ein Wegwerf-Container ohne Netz zu). T-06-97 (Zeilen-Diff, Golden-Hash begründet, Mod-Tests unverändert grün; Lua-Syntaxlauf offen), T-06-98 (AST gleich), T-06-104 (Argumente und Platzhalterfolge gleich, log_redact nur Kommentare, Negativ-Asserts mit Positivkontrolle) wie im Plan mitigiert.

## Self-Check: PASSED

- 06-26-residuals.tsv, tests/e2e/test_mod_syntax_e2e.py, 06-26-SUMMARY.md vorhanden; Commits 90a7505, 67acf7f, 2a43932, c87315a im Log; Autor street1983nk; nicht gepusht; .planning/config.json unberührt (weiter ` M`).
