---
phase: 04-spielzeitlimits
fixed_at: 2026-10-21T14:19:46Z
review_path: .planning/phases/04-spielzeitlimits/04-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 9
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-10-21T14:19:46Z
**Source review:** .planning/phases/04-spielzeitlimits/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (CR-01, WR-01 bis WR-08; IN-01 bis IN-03 bleiben offen)
- Fixed: 9
- Skipped: 0

Gates vor jedem Commit grün: ruff (Vollsatz), ruff format, pyright basic (latest), vulture; Frontend: `node frontend/tests/playtime.check.mjs`, `npm run build`, `tests/test_frontend_privacy.py`. Python-Suite ohne Docker am Ende: 889 passed. Docker-e2e seriell: `test_time_mod_e2e`, `test_playtime_e2e`, `test_world_window_e2e`, `test_holidays_e2e` grün. Dev-Backend neu gestartet und registriert (`scripts/dev/register-exapp.sh`, vorher PID-Kommandozeile geprüft: `uv run python -m gameworld.main` aus diesem Repo).

## Fixed Issues

### CR-01: Gescheitertes Schreiben der Regeldatei wird nie nachgeholt (Fail-open)

**Files modified:** `src/gameworld/playtime/engine.py`, `src/gameworld/worlds/service.py`, `tests/test_service_lifecycle.py`
**Commit:** 1c2b06f
**Applied fix:** `TimeEngine.forget(world_id)` verwirft den Render-Cache. Neuer Helfer `WorldService._write_time` schreibt die Regeldatei und ruft bei jedem Fehler `forget` auf; genutzt in `push_time` und `tick_time`. Auch `_launch` verwirft den Cache, wenn das Schreiben der Weltdateien scheitert. Der nächste Takt liefert dadurch `geändert` True und schreibt erneut. Zwei Regressionstests: gescheiterter `push_time` bzw. gescheitertes Schreiben im Takt wird vom folgenden Takt nachgeholt, danach wieder kein unnötiges Schreiben. Der UI-Teil (Hinweis bei `applied: false`) steckt in WR-08.

### WR-01: Kind-Ansicht sagt "Heute", obwohl der nächste Start eine Woche entfernt ist

**Files modified:** `src/gameworld/playtime/service.py`, `tests/test_my_playtime.py`
**Commit:** 395cc4a
**Applied fix:** `parse_hint` (Token-Rekonstruktion) ersetzt durch `next_time(NextStart, now, tz)`, das `days_ahead` aus dem absoluten Epoch des Starts rechnet; genutzt in `kid_playtime` und `world_window_status`. Regressionstest mit dem Szenario aus dem Review (Ferien nur heute, Normalplan Mi 17 bis 18 Uhr, jetzt 10 Uhr) erwartet `days_ahead` 7.

### WR-02: Fensterbeginn öffnet der Mod nicht selbst, Kind bekommt "Spielzeit vorbei"

**Files modified:** `src/gameworld/playtime/plan.py`, `src/gameworld/playtime/engine.py`, `tests/test_playtime_engine.py`, `tests/test_playtime_plan.py`
**Commit:** 458f654
**Applied fix:** `ChildState` hat das neue Feld `cap_rest_s`. Vor dem heutigen Fenster trägt es schon den Rest des kommenden Fensters (`limit*60 - used`, mindestens 0) bzw. None ohne Limit; sonst gleicht es `rest_s`. Die Engine rechnet den Deckel aus `cap_rest_s`. Grund bleibt `fenster`, die Grenzen sperren bis `from`, ab `from` öffnet der Mod selbst. `rest_s` (API, Kind-Ansicht) bleibt unverändert. Status: fixed: requires human verification (Logikänderung am Deckel).

### WR-03: Großes Zählbuch schaltet die Verbuchung still ab

**Files modified:** `src/gameworld/provisioner/client.py`, `src/gameworld/worlds/service.py`, `tests/test_provisioner_errors.py`, `tests/test_service_lifecycle.py`
**Commit:** 2ffaf83
**Applied fix:** Eigene Kappung für das Zählbuch: `LEDGER_FILE_MAX` 256 KiB (rund 8000 Namen statt rund 125), Tar-Strom entsprechend größer. Ist das Zählbuch trotzdem größer, steht eine Warnung ohne Inhalt im Log. `_book_ledger` loggt zusätzlich, wenn ein vorhandenes Zählbuch keinen Kopf oder keine Schlusszeile hat. Status-Datei und Zugangsstand behalten 4096 Bytes und bleiben stumm. Dateiformate unverändert. Den Vorschlag, im Mod alte Namen zu verwerfen, habe ich bewusst nicht umgesetzt (würde das Format- und Rücksprungverhalten ändern).

### WR-04: "Regeln entfernen" löscht den heutigen Verbrauch, erneutes Setzen gibt volles Kontingent

**Files modified:** `src/gameworld/worlds/store.py`, `src/gameworld/playtime/service.py`, `tests/test_store.py`, `tests/test_playtime_api.py`, `tests/e2e/test_playtime_e2e.py`, `scripts/dev/acceptance-phase4.sh`
**Commit:** 937267d, 7fc1033
**Applied fix:** Nach Owner-Entscheid: `clear_child(nc_user, keep_from=heute)` löscht Regeln und nur Verbrauch vor dem heutigen lokalen Tag (Datensparsamkeit). Heute bleibt der Verbrauch stehen, erneutes Setzen gibt kein frisches Kontingent. Der API-Test prüft Entfernen und erneutes Setzen am selben Tag (`used_today_s` bleibt). Folgeanpassung 7fc1033: Schritt (3) von `test_playtime_e2e` hatte sich auf das alte Zurücksetzen verlassen und nutzt jetzt 5 statt 3 Minuten Limit (prüft dabei, dass der Verbrauch das Entfernen übersteht). `acceptance-phase4.sh` setzt den Verbrauch von gw-kind über einen neuen Helfer `reset_usage` gezielt zurück (in `reset_fixtures` und vor K5), damit K5 weiter ab null misst und die Abnahme an einem Tag wiederholbar bleibt. Das Abnahmeskript selbst habe ich nicht laufen lassen (nur `sh -n`).

### WR-05: Verbuchung nicht atomar, Doppelzählung nach Fehler zwischen den Schritten

**Files modified:** `src/gameworld/worlds/store.py`, `src/gameworld/playtime/engine.py`, `tests/test_playtime_engine.py`
**Commit:** e932318
**Applied fix:** Neue Store-Methode `book_usage(world_id, day, usage, seen)` schreibt Verbrauch und neuen gesehenen Stand in einer Verbindung und einer Transaktion. `TimeEngine.book` sammelt die Sekunden je Kind und ruft sie einmal auf. Regressionstest: Ein sqlite-Trigger lässt das Verankern scheitern, danach sind Verbrauch und gesehener Stand unverändert. Nach dem Entfernen des Triggers zählt derselbe Zuwachs genau einmal.

### WR-06: Deckel hängt am ExApp-seitigen `seen`, nicht am Mod-Stand

**Files modified:** `src/gameworld/provisioner/time_mod.py`, `src/gameworld/playtime/engine.py`, `tests/test_time_mod.py`, `tests/test_playtime_engine.py`, `tests/e2e/test_time_mod_e2e.py`
**Commit:** b316f1c
**Applied fix:** Neue, rückwärtskompatible Zeile `@base <Spielername> <Sekunden>` nach jeder Spielerzeile mit Deckel: Zählbuch-Stand, gegen den die ExApp den Deckel gerechnet hat. Der Mod rechnet beim Laden je Name den Rückstand `base - used` und zieht ihn vom Deckel ab. So gewährt er nach gelöschtem oder zurückgespieltem Zählbuch nie mehr als den Rest beim Ausstellen, auch ohne laufende ExApp. Im Normalfall ist `used >= base`, es ändert sich nichts. Die Engine behält den Anker, solange der Deckel gleich bleibt: Die Bytes wechseln nicht in jedem Takt (Pitfall 6, Test prüft `geändert` False beim Spielen in derselben Welt). Alte Mods überspringen `@`-Zeilen. Live belegt mit e2e-Schritt S12 (Anker 580 s über dem Stand: abgelehnt; Anker auf dem Stand: Beitritt klappt). Status: fixed: requires human verification (neue Durchsetzungslogik im Mod).

### WR-07: Mitternachtstrennung mit widersprüchlichem Text

**Files modified:** `src/gameworld/provisioner/time_mod.py`, `tests/test_time_mod.py`, `tests/e2e/test_time_mod_e2e.py`
**Commit:** 01b636f
**Applied fix:** `text()` im Lua-Mod und `kid_text(..., reached=True)` in Python prüfen vor dem Tagesbezug, ob der nächste Start schon erreicht ist (Regeldatei älter als der Tageswechsel). Dann kommt "Gameworld startet gleich. Bitte gleich nochmal versuchen." statt "Jetzt ist noch keine Spielzeit. Heute kannst du spielen.". Trennen am Tagesende bleibt fail closed (O-04), die ExApp schreibt binnen 15 s neu. Kein Kindertext enthält "0 Uhr" oder "Mitternacht". Live belegt mit e2e-Schritt S13.

### WR-08: Eltern-Dialoge ignorieren `applied`

**Files modified:** `frontend/src/playtime.js`, `frontend/src/components/PlaytimeDialog.vue`, `frontend/src/components/WorldWindowDialog.vue`, `frontend/src/components/HolidayList.vue`, `frontend/tests/playtime.check.mjs`
**Commit:** 60254fe
**Applied fix:** `notAppliedText(result)` liefert bei `applied === false` den Hinweis "Gespeichert, aber noch nicht in jeder Welt angekommen. Gameworld versucht es alle 15 Sekunden erneut, bis die Welt erreichbar ist. Eine gestoppte Welt übernimmt die Änderung beim nächsten Start." Spielzeit- und Zeitfenster-Dialog schließen dann nicht still. Sie bleiben mit einer Warnkarte und nur dem Knopf "Schließen" offen (die Liste lädt trotzdem neu). Die Ferienliste zeigt dieselbe Warnkarte nach Hinzufügen und Entfernen. Der Text stimmt dank CR-01 (Takt holt laufende Welten nach, Start schreibt gestoppte). Prüfskript deckt die Abbildung und echte Umlaute ab.

---

_Fixed: 2026-10-21T14:19:46Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
