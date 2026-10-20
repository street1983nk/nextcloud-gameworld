---
phase: 04-spielzeitlimits
plan: 03
subsystem: playtime
tags: [playtime, api, ticker, lifespan, ledger, time-engine, e2e]
requires:
  - phase: 04-spielzeitlimits
    provides: time_mod (render_time_file, TimeLine, Ledger, parse_ledger), plan.evaluate_child/evaluate_world, ledger.increments/attribution_day, store Schema 4
  - phase: 03-zugang-und-rollen
    provides: WorldService (mutation/try_mutation, push_access, _launch), access/service.py, api/invites.py (_clean_target), Directory, require_verwalter, Session-Prober
provides:
  - playtime/engine.py TimeEngine (book, render mit Generationszähler, child_state)
  - playtime/service.py TimeService (list_children, set_child, clear_child)
  - playtime/ticker.py time_forever (15-s-Lifespan-Task)
  - api/playtime.py GET /api/playtime, POST/DELETE /api/playtime/children/{nc_user}, Verwalter-Sperre routerweit
  - WorldService.push_time, tick_time, time_restart_needed; push_access schreibt jetzt auch die Regeldatei
  - worlds/store.py list_players; WorldView/WorldOut.time_restart_needed
affects: [04-04, 04-05, 04-06, 04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "Ein Kontingent über alle Welten: erst alle Welten verbuchen, dann alle rendern (O-03)"
    - "Regeldatei-Generation nur bei echter Änderung hoch (Byte-Vergleich im Speicher, kein Schreiben in jedem Takt)"
    - "cap = gesehener Zählbuch-Stand der Welt plus Restsekunden; der Mod setzt die globale Restzeit lokal durch"
    - "Zweiter Lifespan-Task time_forever neben reconcile_forever, beide im finally abgebrochen"
key-files:
  created:
    - src/gameworld/playtime/engine.py
    - src/gameworld/playtime/service.py
    - src/gameworld/playtime/ticker.py
    - src/gameworld/api/playtime.py
    - tests/test_playtime_engine.py
    - tests/test_playtime_api.py
    - tests/e2e/test_playtime_e2e.py
  modified:
    - src/gameworld/worlds/service.py
    - src/gameworld/worlds/store.py
    - src/gameworld/api/worlds.py
    - src/gameworld/access/service.py
    - src/gameworld/main.py
    - tests/test_service_lifecycle.py
    - tests/test_service_unavailable.py
    - tests/test_access_service.py
    - tests/test_my_worlds.py
    - tests/conftest.py
key-decisions:
  - "read_time_ledger protokolliert im Fake auf einer eigenen Liste (ledger_reads) wie read_access_state, nicht auf calls; so bleiben die Lebenszyklus-Reihenfolgetests stabil und das Booking vor dem Rendern wird funktional belegt (usage + ledger_seen)"
  - "_time_file rendert ab 04-03 über die Engine; die Generation kommt aus der Datenbank (nicht mehr fest 0), _assert_empty_rules akzeptiert jede Generation"
  - "push_access ruft im selben mutation()-Block push_time; ein frisch eingeladenes Kind mit Regeln steht sofort in der Regeldatei"
  - "TimeService nutzt WorldService.time (neue Property) für child_state; die API serialisiert next_hint '-' als null"
  - "Verbrauch wird höchstens einmal pro Stunde aufgeräumt (prune_usage, heute minus 7 Tage)"
requirements-completed: [ZEIT-01, ZEIT-02]
metrics:
  duration: 95 min
  completed: 2026-10-20
  tasks: 3
  files: 17
---

# Phase 4 Plan 03: Tageslimit und Zeitfenster pro Kind Ende zu Ende Summary

Der Verwalter setzt pro Kind per API ein Tageslimit und/oder ein Zeitfenster; die ExApp rechnet je Welt die Regeldatei aus Schema 4, schreibt sie sofort unter `mutation()` und hält sie im 15-s-Takt aktuell. Der Mod aus 04-01 setzt durch. Ein Kontingent gilt über alle Welten (O-03), überlebt den Welt-Neustart (Regeln aus der Datenbank) und ist Ende zu Ende gegen echte Luanti-Welten belegt, samt Positivkontrolle.

## Ergebnis

- **TimeEngine (Task 1):** `book(world_id, ledger)` verbucht die Zählbuch-Zuwächse (`increments`) auf den lokalen Tag jedes Kindes mit Regeln (`attribution_day`, O-03) und verankert den gesehenen Stand neu; Erstkontakt und Rücksprung zählen nicht (nur verankern). `render(world_id)` rechnet je Welt die Regeldatei: für jedes eingeladene Kind mit Regeln `evaluate_child` mit dem Verbrauch über alle Welten, `cap = gesehen(Welt, Name) + rest_s` bzw. -1 ohne Limit, dazu die Welt-Zeile aus `evaluate_world`. Der Regelteil wird je Welt im Speicher verglichen; nur bei Änderung zählt `bump_time_generation` hoch und der Kopf bekommt ein neues `issued_at` (kein Schreiben in jedem Takt). `child_state(nc_user)` liefert die Auswertung (None = keine Regeln).
- **Einbau in WorldService (Task 1):** `_time_file` liest vor dem Rendern das Zählbuch (`_book_ledger`, Pitfall 7) und rendert aus Schema 4. `push_time(world_id)` schreibt die Regeldatei (Muster `push_access`); `push_access` ruft es im selben `mutation()`-Block. `tick_time()` nimmt nur `try_mutation()` (nie blockierend), verbucht erst alle laufenden Welten und rendert dann alle (O-03), schreibt nur geänderte Bytes; ein Fehler bleibt an einer Welt. `time_restart_needed` (Muster `_access_restart_needed`, Datei = Zählbuch) zeigt Welten ohne geladenen Zeit-Mod. Kein Dateiinhalt im Log.
- **Verwalter-API und Zeittakt (Task 2):** `api/playtime.py` mit `APIRouter(prefix="/api/playtime", dependencies=[Depends(require_verwalter)])`: GET listet Zeitzone und alle Konten mit Spielerzeile (has_rules, normal, used_today_s, state); POST/DELETE setzen bzw. entfernen den Wochenplan (genau 7 Wochentage, `extra="forbid"`, Validierung über `DayRule`/`WeekPlan` -> 422; unbekanntes Konto -> 404). `playtime/ticker.time_forever` ruft `tick_time` alle 15 s (nie exakt 10 s) im zweiten Lifespan-Task neben `reconcile_forever`; beide werden im `finally` abgebrochen. Keine neue HTTP-Methode (kein PUT).
- **Ende-zu-Ende (Task 3):** `tests/e2e/test_playtime_e2e.py` treibt die Regeln über die API und den Takt (per `service.tick_time`, ASGI ohne Lifespan) gegen echte MTG-Welten, mit Mitternachtsschutz (lokal Europe/Berlin).

### Live-Nachweise

`tests/e2e/test_playtime_e2e.py` (1 Test, 396 s, MTG kreativ):

| Teil | Ergebnis |
|------|----------|
| (1) Tageslimit 2 min | gw-kind nach rund 120 s getrennt mit "Deine Spielzeit für heute ist aufgebraucht.", Chat-Vorwarnung "Noch 1 Minute."; zweites Konto gw-kind2 ohne Regeln `held` (Positivkontrolle); verbuchte usage(gw-kind) zwischen 105 und 135 s, gw-kind2 keine usage-Zeile; Rejoin nach 2,5 s `denied` mit demselben Text |
| (2) Neustart | POST /restart, `running` abgewartet, `time_restart_needed` false; Join gw-kind weiter `denied` mit Limit-Text (Regeln aus der Datenbank, Success Criterion 6) |
| (3) Zwei Welten | DELETE, neue Regel 3 min; Welt B angelegt, Kind eingeladen; Regeldatei der Welt B trägt das Kind sofort (Einladungspfad schreibt `push_time` mit, vor jedem Takt); Sitzung in Welt A `held`; Deckel in Welt B = gesehen_B + (180 - usage) mit Toleranz 10 s (ein Kontingent über alle Welten, O-03) |
| (4) Zeitfenster | DELETE, Fenster bis lokale Minute jetzt plus 3; am Fensterende getrennt mit "Gerade ist keine Spielzeit." vor 200 s |
| (5) Opt-in | DELETE, Join gw-kind `auth_accept`, Sitzung 20 s `held` |

Nach jedem Teil keine Welt im Status error; am Ende beide Welten per API gelöscht (Volumes über das Cleanup-Fixture).

Nicht-Docker-Suite: `uv run pytest -q -m "not docker"` = 734 passed, 24 deselected (+37 neue Tests gegenüber 04-02). Gesamtsuite mit Docker (`GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`): 759 passed in 14:44 min (Regression Phasen 1 bis 3, 04-01 und 04-02 grün). Gates grün: ruff check (All checks passed), ruff format --check, pyright (0 errors), vulture (leer). Danach kein Container mit Label `gameworld.managed=true`.

Live-Dev-Stack: Das alte Backend (Port 10040, PID 11308 plus venv-Starter 18724, beide per Kommandozeile als `gameworld.main` geprüft; `.dev/exapp.pid` war veraltet) gezielt per PID gestoppt, dann `sh scripts/dev/register-exapp.sh`: "ExApp gameworld successfully registered". Nach 32 s im ExApp-Log kein ERROR, kein Traceback, kein "Zeittakt übersprungen/fehlgeschlagen"; Boot-Abgleich abgeschlossen. `curl -u admin ... /index.php/apps/app_api/proxy/gameworld/api/playtime` liefert 200 mit `time_zone` "Europe/Berlin" und den Konten gw-abnahme2 und gw-kind (beide ohne Regeln).

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | aa41609 | TimeEngine, Einbau in WorldService (verbuchen, rendern, push_time, tick_time, Neustart-Hinweis) |
| 2 | ad88edf | Verwalter-API /api/playtime und 15-s-Zeittakt im Lifespan |
| 3 | cf21907 | Ende-zu-Ende-Nachweis (Limit, Fenster, Neustart, zwei Welten, Positivkontrolle) |
| Nachtrag | 9079b28 | Echte Umlaute in den Docstrings von playtime/engine.py und playtime/service.py |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - blockierend] test_my_worlds.py an den zusätzlichen Push angepasst**
- **Found during:** Task 1 (Gate-Durchlauf)
- **Issue:** `push_access` schreibt jetzt zusätzlich die Regeldatei (push_time). `test_my_worlds.py` (nicht in der Dateiliste des Plans) zählt `len(fake.written)` und brach dadurch.
- **Fix:** Lokaler Helfer `_access_writes` (filtert die Zugangsdatei-Tars) wie in `test_access_service.py`; die Zählungen bleiben inhaltlich gleich.
- **Commit:** aa41609

**2. [Rule 1 - Testdesign] read_time_ledger im Fake auf eigener Liste**
- **Found during:** Task 1
- **Issue:** Würde `read_time_ledger` im Fake auf `calls` protokollieren, verschmutzte der Lesevorgang beim Bauen der Weltansicht (`time_restart_needed`) die Reihenfolge-Erwartungen der Lebenszyklus-Tests.
- **Fix:** Wie `read_access_state` protokolliert der Fake auf `ledger_reads` (eigene Liste), nicht auf `calls`. Das Booking vor dem Rendern im `_launch` ist funktional belegt (usage und ledger_seen) statt über die Reihenfolge in `calls`.
- **Commit:** aa41609

**3. [Projektregel] Echte Umlaute in den neuen Docstrings**
- **Found during:** Abschlussprüfung
- **Issue:** In playtime/engine.py und playtime/service.py standen in deutscher Prosa ASCII-Ersatzschreibungen (ae, ue, ss); die Projektregel verlangt echte Umlaute (nur Lua bleibt ASCII).
- **Fix:** Nur Prosa-Wörter ersetzt, keine Bezeichner; Gates und betroffene Tests erneut grün.
- **Commit:** 9079b28

### Hinweise

- **Veraltete PID-Datei:** `.dev/exapp.pid` zeigte auf 57234, das Backend lief als 11308 (venv-Starter 18724). Beide PIDs wurden nach Prüfung der Kommandozeile gezielt gestoppt, nie per Prozessname.
- **TDD-Commits zusammengefasst:** Wie in 04-01/04-02 je Task ein Commit mit der im Plan genannten Nachricht (Vorgabe "atomar je Task"). RED wurde lokal belegt (Engine-Tests rot bis engine.py stand; API-Tests rot bis playtime.py/service.py standen), aber nicht separat committet.
- **conftest.py:** `FakeDirectory.users` um `gw-kind2` (Positivkontrolle) und `admin` (für 04-05) ergänzt; kein bestehender Test zählt die Kontoliste auf, keiner brach.
- **_assert_empty_rules:** akzeptiert jetzt jede Generation (die Regeldatei kommt aus der Datenbank, nicht mehr fest 0).

## Known Limitations

- Der API-Körper kennt in diesem Plan nur den Wochenplan "normal" (7 Tage); Ferien (04-04), Welt-Fenster-Bedienung (04-05) und UI (04-06/07) bauen darauf auf. `meta time_zone` ist noch nicht per Einstellung setzbar (leer = Europe/Berlin), das kommt in 04-04.
- Der 15-s-Takt verbucht durch den Erstkontakt die erste Taktspanne nicht (Schutz gegen Doppelzählung); über eine Sitzung gleicht sich das aus (im e2e usage 105 bis 135 bei 120 s Limit).
- Darstellung der Umlaute im echten Client bleibt Owner-Abnahme (04-08).

## Known Stubs

Keine. Alle Rückgaben stammen aus der Datenbank bzw. aus der Live-Auswertung; keine hartcodierten Leerwerte.

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Modells. Umgesetzt und belegt: T-04-15 (AppAPI ADMIN plus require_verwalter routerweit; e2e gw-kind 403), T-04-16 (Pydantic extra forbid, Bereiche, DayRule-Validierung, 422), T-04-17 (Summenverbuchung, Deckel je Welt im Takt, e2e Teil 3), T-04-18 (tick_time nur try_mutation, Regel-API blockierend, verpasste Schreibvorgänge holt der Byte-Vergleich nach), T-04-19 (book verankert neu, _launch liest das Zählbuch vor dem Rendern), T-04-20 (Logs ohne Dateiinhalt, grep leer). Neue Routen `/api/playtime` liegen hinter ADMIN plus require_verwalter, kein neuer Netz- oder exec-Pfad.

## Self-Check: PASSED

- Dateien vorhanden: playtime/engine.py, playtime/service.py, playtime/ticker.py, api/playtime.py, tests/test_playtime_engine.py, tests/test_playtime_api.py, tests/e2e/test_playtime_e2e.py
- Commits vorhanden: aa41609, ad88edf, cf21907, 9079b28
- Greps: `try_mutation` in tick_time, `time_restart_needed` in api/worlds.py, `time_forever` in main.py, `require_verwalter` routerweit in api/playtime.py; leer: `PUT` in api/playtime.py und `LOG.*(.*content` in playtime/ und worlds/service.py
- Nach der Gesamtsuite kein Container mit `gameworld.managed=true`, kein Welt-Volume übrig (nur das Dev-Nextcloud-Volume)
