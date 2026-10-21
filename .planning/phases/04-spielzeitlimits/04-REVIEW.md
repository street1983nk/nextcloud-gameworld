---
phase: 04-spielzeitlimits
reviewed: 2026-10-21T13:36:22Z
depth: standard
files_reviewed: 54
files_reviewed_list:
  - src/gameworld/playtime/engine.py
  - src/gameworld/playtime/ledger.py
  - src/gameworld/playtime/plan.py
  - src/gameworld/playtime/service.py
  - src/gameworld/playtime/ticker.py
  - src/gameworld/playtime/__init__.py
  - src/gameworld/provisioner/time_mod.py
  - src/gameworld/provisioner/access_mod.py
  - src/gameworld/provisioner/archive.py
  - src/gameworld/provisioner/client.py
  - src/gameworld/api/playtime.py
  - src/gameworld/api/me.py
  - src/gameworld/api/worlds.py
  - src/gameworld/main.py
  - src/gameworld/access/service.py
  - src/gameworld/worlds/service.py
  - src/gameworld/worlds/store.py
  - appinfo/info.xml
  - pyproject.toml
  - frontend/src/api.js
  - frontend/src/playtime.js
  - frontend/src/views/ParentView.vue
  - frontend/src/views/PlayerView.vue
  - frontend/src/components/ConnectionCard.vue
  - frontend/src/components/DayTiles.vue
  - frontend/src/components/HolidayList.vue
  - frontend/src/components/PlaytimeCard.vue
  - frontend/src/components/PlaytimeDialog.vue
  - frontend/src/components/PlaytimeSection.vue
  - frontend/src/components/TimeZoneSetting.vue
  - frontend/src/components/WorldWindowDialog.vue
  - scripts/dev/acceptance-phase4.sh
  - tests/conftest.py
  - tests/e2e/luanti_probe.py
  - tests/e2e/time_helpers.py
  - tests/e2e/test_holidays_e2e.py
  - tests/e2e/test_playtime_e2e.py
  - tests/e2e/test_rejoin_guard_e2e.py
  - tests/e2e/test_time_mod_e2e.py
  - tests/e2e/test_world_window_e2e.py
  - tests/test_access_mod.py
  - tests/test_access_service.py
  - tests/test_archive.py
  - tests/test_my_playtime.py
  - tests/test_my_worlds.py
  - tests/test_playtime_api.py
  - tests/test_playtime_engine.py
  - tests/test_playtime_ledger.py
  - tests/test_playtime_plan.py
  - tests/test_service_lifecycle.py
  - tests/test_service_unavailable.py
  - tests/test_store.py
  - tests/test_time_mod.py
  - frontend/tests/playtime.check.mjs
findings:
  critical: 1
  warning: 8
  info: 3
  total: 12
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-10-21T13:36:22Z
**Depth:** standard
**Files Reviewed:** 54 (Produktionscode vollständig, Tests stichprobenartig auf Lücken)
**Status:** issues_found

## Summary

Geprüft wurde die Spielzeit-Durchsetzung von Phase 4 samt Quick 261021-481 (Kindertexte mit `@tage`/`@start`). Die Grundarchitektur ist solide: Autorisierung (info.xml `^/api/my/.*` USER, `^/api/.*` ADMIN plus `require_verwalter` routerweit), Eingabeprüfung (Pydantic plus `DayRule`/`WeekPlan`, IANA-Zeitzonen per Allowlist), Zeileninjektion in der Regeldatei (ValueError statt Überspringen), Rückwärtskompatibilität der `@`-Zeilen mit alten Mods und die exakte Namensbindung zwischen Zugangs- und Zeit-Mod halten der Prüfung stand. Kinder erreichen keine Verwalter-Routen und sehen nur eigene Daten.

Kritisch ist ein Fail-open im Schreibpfad: Der Render-Cache merkt sich den neuen Stand, bevor er in der Welt liegt. Scheitert das Schreiben einmal, holt der 15-s-Takt es nie nach, solange sich der Regelteil nicht von selbst ändert, und die Eltern-UI ignoriert `applied: false`. Dazu kommen fehlerhafte Kindertexte an Ferien- und Tagesgrenzen, ein Fensterbeginn, den der Mod nicht selbst öffnen kann, ein stilles Abschalten der Verbuchung bei großem Zählbuch und ein Quota-Reset über "Regeln entfernen".

## Critical Issues

### CR-01: Gescheitertes Schreiben der Regeldatei wird nie nachgeholt (Fail-open)

**File:** `src/gameworld/playtime/engine.py:206-221`, `src/gameworld/worlds/service.py:335-352`, `src/gameworld/worlds/service.py:376-382`
**Issue:** `_render_cached` legt Schlüssel, Generation und Bytes in `self._cache` ab, bevor der Aufrufer die Datei schreibt. `push_time` fängt `ProvisionerError` ab und gibt `False` zurück, `tick_time` schreibt nur bei `changed == True`. Nach einem einzigen vorübergehenden Docker-Fehler (Proxy-Keep-Alive, kurzer Ausfall) liefert jeder weitere Takt `changed=False`, und die Welt behält die alte Regeldatei, bis sich der Regelteil zufällig ändert.

Konkreter Fail-open: Ein Kind ohne Tageslimit (`cap -1`) spielt, ein Elternteil setzt ein Welt-Zeitfenster "jetzt zu" oder sperrt den heutigen Tag. Der Push scheitert, die Zeile des Kindes ändert sich nicht (kein Deckel, also kein wachsender `seen`-Bezug), der Schlüssel bleibt gleich, und das Kind spielt bis zum Tagesende weiter. Bei einem offline Kind gilt die alte, großzügigere Regel beim nächsten Beitritt. Die Eltern merken es nicht: `PlaytimeDialog.vue:127-136`, `WorldWindowDialog.vue:76-81` und `HolidayList.vue:142-159` werten `applied` überhaupt nicht aus (nur `TimeZoneSetting.vue:93` tut es). Kein Test deckt den Wiederholungsfall ab (`test_service_lifecycle.py` hat nur Sperre, Rendern und Lesefehler).
**Fix:** Den Cache erst nach erfolgreichem Schreiben festschreiben bzw. bei Fehlschlag verwerfen, damit der nächste Takt erneut schreibt:
```python
# engine.py
def forget(self, world_id: str) -> None:
    """Nach einem gescheiterten Schreiben: Der nächste Takt schreibt sicher neu."""
    self._cache.pop(world_id, None)

# worlds/service.py, push_time und tick_time
try:
    self._provisioner.write_world_files(world_id, build_time_tar(data))
except ProvisionerError:
    self._time.forget(world_id)
    raise  # bzw. bisherige Behandlung
```
Zusätzlich im Takt einen "zuletzt erfolgreich geschrieben"-Schlüssel getrennt vom Render-Schlüssel führen, einen Test "Schreiben scheitert, nächster Takt schreibt" ergänzen und in den drei Dialogen bei `applied === false` einen Hinweis wie in `TimeZoneSetting.vue` zeigen.

## Warnings

### WR-01: Kind-Ansicht sagt "Heute", obwohl der nächste Start eine Woche entfernt ist

**File:** `src/gameworld/playtime/service.py:212-225`, `src/gameworld/playtime/service.py:254`
**Issue:** `parse_hint` rekonstruiert `days_ahead` aus dem verlustbehafteten Token `Mi-17:00` und vergleicht nur die Uhrzeit mit jetzt. Liegt der nächste Start auf demselben Wochentag eine Woche später, aber später am Tag als jetzt, kommt `days_ahead=0` heraus. Nachgestellt: Ferien nur am Mittwoch 21.10. (Ferienplan sperrt alles), Normalplan Mittwoch 17 bis 18 Uhr, jetzt 10:00. Ergebnis `state='tag'`, `next=NextTime(weekday=3, minute=1020, days_ahead=0)`, das Frontend zeigt "Heute ist kein Spieltag. Heute ab 17 Uhr kannst du spielen." Der Welt-Mod rechnet richtig (absolute `@start`-Epoch), nur die Web-Ansicht widerspricht ihm.
**Fix:** `ChildState.next_start` (bzw. `WorldState.next_start`) direkt verwenden statt das Token zu parsen:
```python
def _next_time(start: NextStart | None, now: int, tz: ZoneInfo) -> NextTime | None:
    if start is None:
        return None
    days_ahead = (local_day(start.at, tz) - local_day(now, tz)).days
    return NextTime(weekday=start.weekday, minute=start.minute, days_ahead=days_ahead)
```

### WR-02: Fensterbeginn öffnet der Mod nicht selbst, Kind bekommt "Spielzeit vorbei"

**File:** `src/gameworld/playtime/plan.py:251-252`, `src/gameworld/playtime/engine.py:158`, `src/gameworld/provisioner/time_mod.py:329-338`
**Issue:** Vor dem Fenster liefert `evaluate_child` `reason="fenster", rest_s=0`, also rendert die Engine `cap = seen + 0`. Erreicht die Mod-Uhr `from`, ist `t` im Fenster, aber `rest = cap - used <= 0`, und `left()` liefert `0, "limit"`. Das gilt auch für Tage ohne Limit (`rest_s` ist 0, nicht None). Folgen: (a) Das Fenster öffnet erst, wenn die ExApp neu rendert. Der Takt nimmt nur `try_mutation`; während einer langen Elternaktion (VoxeLibre-Welt erzeugen, Neustart) oder bei gestoppter ExApp bleibt das Kind ausgesperrt, obwohl die absoluten Grenzen in der Datei stehen. (b) Der Text lautet in diesem Zeitraum "Deine Spielzeit für heute ist vorbei. Heute ab 15 Uhr kannst du spielen.", widersprüchlich und genau die Art Kindertext, die Quick 261021-481 vermeiden soll.
**Fix:** Für "fenster vor dem Fenster" den Deckel des kommenden Fensters rendern (`cap = seen + limit*60 - used` bzw. `-1` ohne Limit) und den Grund `fenster` nur über `from`/`until` wirken lassen; dann sperrt der Mod vor `from` und öffnet selbst ab `from`. Alternativ im Lua bei `r.reason == "fenster"` und `t` im Fenster mit `why = "fenster"` statt `"limit"` antworten.

### WR-03: Großes Zählbuch schaltet die Verbuchung still ab

**File:** `src/gameworld/provisioner/client.py:41`, `src/gameworld/provisioner/client.py:146-158`, `src/gameworld/provisioner/time_mod.py:614-629`, `src/gameworld/playtime/engine.py:116-117`
**Issue:** `read_time_ledger` kappt den Inhalt auf `STATUS_FILE_MAX = 4096` Bytes ohne Fehler. Der Mod löscht nie Namen aus `used` (jeder je Eingeladene, auch umbenannte), eine Zeile kostet bis zu 32 Bytes. Ab rund 125 Namen fehlt die Schlusszeile `end`, `parse_ledger` gibt None zurück und `book` kehrt kommentarlos zurück. Für diese Welt wird dann nie wieder verbucht: Das Kontingent über alle Welten (O-03) bricht, die Eltern sehen `used_today_s` 0, und es gibt keine Logzeile. Der Store-Text erwähnt Schulen, dort ist die Größe realistisch.
**Fix:** Für das Zählbuch eine eigene, größere Kappung (etwa 64 KiB) verwenden und bei `parse_ledger(...) is None` trotz vorhandener Datei eine Warnung loggen. Im Mod nur Namen der aktuellen Regeldatei bzw. Zugangsdatei schreiben oder alte Namen nach Rücksprung verwerfen.

### WR-04: "Regeln entfernen" löscht den heutigen Verbrauch, erneutes Setzen gibt volles Kontingent

**File:** `src/gameworld/worlds/store.py:441-446`, `src/gameworld/playtime/service.py:476-479`
**Issue:** `clear_child` löscht `time_usage` des Kindes mit. Wechselt ein Elternteil im Dialog auf "keine" und gleich wieder auf eine Voreinstellung (etwa um den Plan neu aufzubauen), hat das Kind heute wieder die volle Zeit. Das ist ein stiller Datenverlust, der dem Elternwillen widerspricht.
**Fix:** Beim Entfernen nur `time_children`/`time_plans` löschen; Verbrauch läuft über `prune_usage` ohnehin nach 7 Tagen aus. Ist das Löschen aus Datensparsamkeit gewollt, nur Tage vor heute löschen.

### WR-05: Verbuchung nicht atomar, Doppelzählung nach Fehler zwischen den Schritten

**File:** `src/gameworld/playtime/engine.py:118-128`
**Issue:** `book` schreibt `add_usage` je Name und danach `set_ledger_seen` in getrennten Verbindungen und Transaktionen. Scheitert der letzte Schritt (`sqlite3.OperationalError: database is locked` nach 10 s Timeout, Prozessabbruch), bleibt `seen` alt, und der nächste Takt verbucht denselben Zuwachs ein zweites Mal. Das Kind verliert Spielzeit, ohne dass jemand es sieht.
**Fix:** Eine Store-Methode `book_usage(world_id, day, deltas, new_seen)` anlegen, die beides in einer Verbindung und einer Transaktion schreibt.

### WR-06: Deckel hängt am ExApp-seitigen `seen`, nicht am Mod-Stand

**File:** `src/gameworld/playtime/engine.py:158`, `src/gameworld/provisioner/time_mod.py:238-252`
**Issue:** `cap = seen + rest_s` setzt voraus, dass der Mod-Zähler `used[name]` mindestens `seen` ist. Startet der Mod mit leerem oder kleinerem Zählbuch (Datei gelöscht, Restore einer Sicherung, künftige Backup-Phase), gilt bis zum nächsten erfolgreichen Takt `rest = seen_alt + rest - used_neu`, also eventuell Stunden zu viel. Ein Takt heilt es (Rücksprung verankert neu), aber nur wenn die ExApp läuft und die Sperre frei ist. Fällt sie aus, ist das ein Fail-open bis zum Fensterende.
**Fix:** Den Deckel relativ zum Mod machen, etwa zusätzlich die Generation des Zählbuchs prüfen: Weicht `ledger.generation` bzw. der Kopf von der erwarteten Generation ab, im Mod `rest = min(rest, r.cap - used)` gegen einen Wert `rest_s` aus der Datei rechnen (z. B. Feld "Rest beim Ausstellen" plus `issued_at`), sodass der Mod nie mehr als `rest_s` seit `issued_at` gewährt.

### WR-07: Mitternachtstrennung mit widersprüchlichem Text

**File:** `src/gameworld/playtime/plan.py:176-190`, `src/gameworld/provisioner/time_mod.py:331-332`, `src/gameworld/provisioner/time_mod.py:353-376`
**Issue:** Für einen ganzen Tag ohne Limit ist `until` der Folgetag 00:00. Ist auch der Folgetag erlaubt, trennt der Mod um 00:00 trotzdem (`t >= until`, Grund `fenster`). `starts[name]` zeigt auf genau diesen Tagesanfang, `day_phrase` ergibt `ahead 0, minute 0`, also "Jetzt ist noch keine Spielzeit. Heute kannst du spielen." Das widerspricht sich (es ist jetzt erlaubt), und bis zum nächsten Takt wird auch der erneute Beitritt mit diesem Satz abgelehnt. Fail-closed ist gewollt (O-04), der Text aber nicht.
**Fix:** In `day_phrase`/`text()` den Fall `st.at <= now()` als "gleich wieder" behandeln (etwa `TEXT_START`) oder in `render` für direkt anschließende erlaubte Tage `until` auf das Ende des Folgefensters ziehen. Gleiches in `kid_text` spiegeln.

### WR-08: Eltern-Dialoge ignorieren `applied`

**File:** `frontend/src/components/PlaytimeDialog.vue:127-136`, `frontend/src/components/WorldWindowDialog.vue:76-81`, `frontend/src/components/HolidayList.vue:142-159`
**Issue:** Die API meldet mit `applied: false`, dass eine Welt den neuen Stand noch nicht trägt. Die drei Dialoge schließen kommentarlos. Zusammen mit CR-01 glauben Eltern, eine Sperre wirke, obwohl sie nicht in der Welt liegt.
**Fix:** Ergebnis auswerten und wie `TimeZoneSetting.vue:93` einen Hinweis zeigen ("Die Regel wirkt, sobald die Welt erreichbar ist").

## Info

### IN-01: Kind-Ansicht zeigt bei Abruffehlern die alte Restzeit weiter

**File:** `frontend/src/views/PlayerView.vue:63-70`
**Issue:** Scheitert `/api/my/playtime`, bleibt `playtime.value` auf dem letzten Stand ("Heute noch 30 Minuten"), während die Zeit weiterläuft. Nur Anzeige, durchgesetzt wird im Mod.
**Fix:** Bei `own.status === 'rejected'` `playtime.value = null` setzen oder den Stand als veraltet kennzeichnen.

### IN-02: Verwalter-Schnappschuss bleibt nach Herabstufung bestehen

**File:** `src/gameworld/playtime/service.py:298-325`
**Issue:** `time_admins` wird nur bei Verwalterbesuchen erneuert. Ein aus der Gruppe admin entferntes Konto bleibt in allen Welten `frei`, bis ein Verwalter das Dashboard öffnet. Kein Kinderbypass (Kinder kommen nicht in den Schnappschuss), aber ein veralteter Freistellungsstand.
**Fix:** Im Hilfetext dokumentieren oder den Schnappschuss mit Zeitstempel versehen und nach z. B. 24 h ohne Erneuerung verwerfen (fail closed).

### IN-03: Render-Cache behält gelöschte Welten

**File:** `src/gameworld/playtime/engine.py:96`, `src/gameworld/worlds/service.py:868-882`
**Issue:** `_delete_world_sync` räumt `TimeEngine._cache` nicht auf. Folgenlos (zufällige IDs), aber unnötiger Zustand.
**Fix:** Beim Löschen `self._time.forget(world_id)` aufrufen (dieselbe Methode wie im Fix zu CR-01).

---

_Reviewed: 2026-10-21T13:36:22Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
