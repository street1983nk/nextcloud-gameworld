---
phase: 05-backup-und-restore
plan: 03
subsystem: playtime / provisioner (Zeit-Mod)
tags: [lua-mod, chat-hint, halt, kid-texts]
requires: []
provides:
  - "Regeldatei-Zeile @halt <ab> (render_time_file(..., halt=None))"
  - "Lua-Zeit-Mod: Chat-Hinweis einmal je Halt, Beitrittssperre, Trennen ab ab"
  - "TimeEngine.set_halt(world_id, ab) / clear_halt(world_id), Halt im Render-Cache-Schlüssel"
affects:
  - "Plan 05-05 (Backup-Ablauf): setzt Halt vor dem Stopp, clear_halt vor _launch"
tech-stack:
  added: []
  patterns:
    - "additive @-Zeile in gameworld_time.txt nach dem @pause-Muster"
    - "flüchtiger Ablaufzustand im Speicher, Teil des Cache-Schlüssels"
key-files:
  created: []
  modified:
    - src/gameworld/provisioner/time_mod.py
    - src/gameworld/playtime/engine.py
    - tests/test_time_mod.py
    - tests/test_playtime_engine.py
decisions:
  - "05-03: @halt ist die letzte @-Zeile direkt vor end; ohne halt sind die Bytes unverändert"
  - "05-03: Halt sperrt im Prejoin jeden Namen (auch frei) vor Pause und Regeln; im Takt trennt cut = halt and now() >= halt vor Pause und Restzeit"
  - "05-03: Chat-Hinweis per core.chat_send_all genau einmal je halt-Wert (halt_warned), unabhängig davon, ob ab schon erreicht ist"
  - "05-03: Halt nur im Speicher der TimeEngine; forget lässt ihn stehen, nur clear_halt nimmt ihn weg"
metrics:
  duration: "20 min"
  completed: 2026-10-23
  tasks: 2
  files: 4
---

# Phase 5 Plan 03: Chat-Hinweis vor dem Cold-Backup (@halt) Summary

Neue Regeldatei-Zeile `@halt <ab>` plus flüchtiger Halt je Welt in der TimeEngine: Der Zeit-Mod schreibt einmal "Die Welt macht gleich eine kurze Pause." an alle, lässt niemanden mehr hinein und trennt ab `ab` alle Spieler (auch frei) mit "Die Welt macht kurz Pause. Gleich geht es weiter." (D-09).

## Was gebaut wurde

**Task 1 (time_mod.py):**
- `TEXT_HALT_SOON`, `TEXT_HALT` in `TEXTS` und als `_lua_string`-Escape im Lua (`HALT_SOON_TEXT`, `HALT_TEXT`).
- `_halt_line(ab)`: nur nichtnegative Ganzzahlen ohne bool (T-05-13), sonst ValueError mit "Halt".
- `render_time_file(..., halt=None)`: Zeile als letzte vor `end`; ohne Halt byte-gleich.
- Lua: Parser `^@halt (%d+)$`, Zuweisung `halt = new_halt` am Ende von `load()` (fehlende Zeile hebt den Halt auf), Prejoin `if halt then return HALT_TEXT end` vor Pause und Regeln, im Takt einmal `core.chat_send_all(HALT_SOON_TEXT)` je `halt`, ab `now() >= halt` `core.disconnect_player(name, HALT_TEXT)` für alle.
- Modul-Docstring um `@halt` ergänzt (alte Mods überspringen die Zeile still).

**Task 2 (engine.py):**
- `self._halts: dict[str, int]`, `set_halt`, `clear_halt`; `render` reicht `halt=self._halts.get(world_id)` durch, `_render_cached` nimmt den Halt in den Schlüssel.

## Belege

- `tests/test_time_mod.py` 166 grün, `tests/test_playtime_engine.py` 44 grün, gesamt ohne Docker 2012 grün.
- ruff, ruff format, pyright (latest, 0 Fehler), vulture ohne Befund.
- Zusätzlich echter Lua-Lauf (Lua 5.1 in Wegwerf-Container `alpine` per `apk add lua5.1`, nur Scratchpad): `luac -p` syntaxfrei; Stub-Harness mit `@halt 200`: Prejoin bei T=150 liefert HALT_TEXT, zwei Takte senden genau einmal `ALL Die Welt macht gleich eine kurze Pause.`, bei T=200 `DC Mia`/`DC Papa` mit HALT_TEXT, nach Datei ohne `@halt` Prejoin wieder frei.

## Deviations from Plan

### Angepasst

**1. [Rule 1 - eigener RED-Test] Reihenfolge-Prüfung im Takt**
- **Found during:** Task 1 GREEN
- **Issue:** Der erste RED-Test verlangte `disconnect_player(name, HALT_TEXT)` textlich vor `paused(name)`; ein verschachteltes `else` ohne Einrückung wäre nötig gewesen.
- **Fix:** Lesbare Struktur `local cut = halt and now() >= halt`, `local p = not cut and paused(name)`, `if cut then ... elseif p and now() >= pause.ab then ...`; Test prüft jetzt `if cut then` vor dem Pausen-Zweig und vor `left(name)`.
- **Commit:** 1fee4e6

**2. Commit-Trailer entfernt**
- Der erste RED-Commit trug kurz eine `Claude-Session`-Zeile; per `--amend` (lokal, ungepusht) entfernt, Owner-Regel "keine Claude-Trailer" geht vor. Alle vier Commits als street1983nk.

Sonst wie geplant.

## Known Stubs

Keine. `set_halt`/`clear_halt` haben noch keinen Produktionsaufrufer, das ist Plan 05-05 (Backup-Ablauf) vorbehalten.

## Threat Flags

Keine neue Angriffsfläche über das Threat-Register hinaus (T-05-13 per `_halt_line` und Lua-Muster `%d+`, T-05-14 per Halt nur im Speicher).

## Commits

- a462180 test(05-03): add failing tests for @halt line in time mod
- 1fee4e6 feat(05-03): @halt line in rules file and time mod chat hint
- b29b70f test(05-03): add failing tests for volatile halt in TimeEngine
- 176fae0 feat(05-03): volatile per-world halt in TimeEngine

## TDD Gate Compliance

RED (test) vor GREEN (feat) für beide Tasks im git log vorhanden.
