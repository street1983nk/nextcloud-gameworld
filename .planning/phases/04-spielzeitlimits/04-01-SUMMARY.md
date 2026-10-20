---
phase: 04-spielzeitlimits
plan: 01
subsystem: provisioner
tags: [luanti, world-mod, gameworld_time, rejoin-guard, ledger, session-prober, e2e]
requires:
  - phase: 03-zugang-und-rollen
    provides: Welt-Mod gameworld_access, _lua_string, build_world_files/build_access_tar, _launch mit put_archive vor jedem Start, Join-Prober
provides:
  - Wiederbeitritts-Sperre 2 s in gameworld_access (TEXT_WAIT), Widerrufs-Kick per disconnect_player
  - Welt-Mod gameworld_time (time_mod.py) mit render_time_file, TimeLine, parse_ledger, Ledger, RULES_FILE, LEDGER_FILE, Kindertexten
  - archive.build_time_tar, build_world_files/build_world_payload mit time_file, WORLD_MODS mit drittem Mod
  - DockerProvisioner.read_time_ledger (get_archive, auch bei gestoppter Welt)
  - WorldService._time_file (in 04-01 leer, ab 04-03 aus Schema 4)
  - tests/e2e/luanti_probe.session() und CLI --hold, tests/e2e/time_helpers.py
affects: [04-03, 04-04, 04-05, 04-08, 05]
tech-stack:
  added: []
  patterns:
    - "Absolute Epoch-Grenzen in der Regeldatei, eigenes Zählbuch des Mods im Welt-Volume (neustartfest)"
    - "Session-Prober bis on_joinplayer: Chat und Trennen live prüfbar ohne Luanti-Client"
key-files:
  created:
    - src/gameworld/provisioner/time_mod.py
    - tests/test_time_mod.py
    - tests/e2e/time_helpers.py
    - tests/e2e/test_rejoin_guard_e2e.py
    - tests/e2e/test_time_mod_e2e.py
  modified:
    - src/gameworld/provisioner/access_mod.py
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - tests/test_access_mod.py
    - tests/test_archive.py
    - tests/test_service_lifecycle.py
    - tests/e2e/luanti_probe.py
key-decisions:
  - "Label gameworld.schema bleibt 2; spec.py unverändert"
  - "Welt-Zeile der Regeldatei kennt die Gründe ok und welt (WORLD_REASONS), Spielerzeilen ok, tag, fenster, limit, frei"
  - "Gutschrift über since[name] (Zeitpunkt, bis zu dem gutgeschrieben ist): ab Beitritt, je Takt, anteilig beim Verlassen und beim Herunterfahren"
  - "Zählbuch wird im Takt nur bei verbundenen Spielern geschrieben, dazu beim Start, beim Verlassen und beim Herunterfahren"
  - "Wiederbeitritts-Sperre steht nach der Einladungsprüfung: Nicht Eingeladene sehen nie den Wartetext"
requirements-completed: [ZEIT-02]
metrics:
  duration: 35 min
  completed: 2026-10-20
  tasks: 3
  files: 13
---

# Phase 4 Plan 01: Durchsetzung im Spielserver Summary

Jede Welt trägt jetzt den Welt-Mod `gameworld_time`: Er lehnt im Prejoin ab, warnt per Chat bei 10/5/1 Minute, trennt per `disconnect_player` mit Kindertext und zählt die Online-Zeit in einem Zählbuch im Welt-Volume, das Neustarts übersteht. Dazu fängt eine 2-s-Wiederbeitritts-Sperre in `gameworld_access` den Rejoin-Absturz von Luanti 5.17.0 ab. Beides ist live per Session-Prober gegen echte Welten belegt.

## Ergebnis

- **Wiederbeitritts-Sperre (O-12, Task 1):** `gameworld_access` merkt sich beim Verlassen den Zeitpunkt (`core.get_us_time`). Ist der Name noch verbunden oder ging er vor weniger als 2 s, lehnt der Prejoin mit "Bitte einen Moment warten und dann nochmal beitreten." ab. Die Sperre greift erst nach der Einladungsprüfung und vor `set_player_password`; alte Einträge werden beim Prüfen gelöscht. Der Widerrufs-Kick läuft jetzt über `core.disconnect_player` (kein "Kicked: " mehr, `kick_player` kommt in access_mod.py nicht mehr vor).
- **Session-Prober:** `luanti_probe.session()` tritt wie ein echter Client bis `on_joinplayer` bei (INIT2, CLIENT_READY, Version `5.17.0-gameworld-test`), sendet alle 3 s PING und schneidet Chat (0x2F) und ACCESS_DENIED (0x0A) als `{t, kind, text}` mit. Die CLI hat `--hold SEKUNDEN`; ohne `--hold` verhält sie sich wie bisher (`acceptance-phase3.sh` kompatibel, `--timeout 1` gegen Port 1 ergibt genau ein JSON-Objekt `{"result": "timeout"}`). Das Passwort erscheint nie in der Ausgabe.
- **Welt-Mod gameworld_time (Task 2):** Regeldatei mit Kopf `gameworld-time 1 <gen> <issued>` und `end`, Welt-Zeile und Spielerzeilen mit absoluten Epoch-Grenzen und Deckel. Halbe Datei: alter Stand. Beim Start nur ungültige Datei: alle zu mit "Gameworld startet gleich" (fail closed, O-04). `frei` hebt Welt-Fenster und eigene Grenzen auf. Vorwarnung sendet nur die kleinste unterschrittene Schwelle und markiert die größeren als gesendet. `depends = gameworld_access`, damit der Zugangstext im Modus OR zuerst gewinnt. Lua reines ASCII, kein `os.date`, kein `kick_player`, kein `http`/`io.popen`/`os.execute`/`require` (Unit-Test).
- **Einspielen (Task 3):** `WORLD_MODS` hat den dritten Mod. `_launch` und `_payload` übergeben immer `_time_file(row)` (in 04-01: `render_time_file(0, jetzt, None, {})`, also ohne Regeln). Die Regeldatei liegt root 0444 im Weltordner, das Zählbuch steht nie im Tar. `read_time_ledger` liest das Zählbuch per get_archive, auch bei gestoppter Welt; kein exec, keine neue Proxy-Freigabe.

### Live-Nachweise

`tests/e2e/test_rejoin_guard_e2e.py` (2 Tests, 64 s):
- MTG kreativ: Sitzung `held`, dann fünf Runden "2 s halten, schließen, nach 0,2 s Join": jedes Mal `denied CUSTOM_STRING` "einen Moment warten". Container nach jeder Runde und 5 s danach `running`, StartedAt unverändert. Gegenprobe nach 2,5 s: `held`.
- VoxeLibre sanft: eine Runde 0,2 s, `denied` mit Wartetext, Container `running`, StartedAt unverändert; Welt danach gelöscht.

`tests/e2e/test_time_mod_e2e.py` (1 Test, rund 150 s, MTG kreativ). Werte aus einem zusätzlichen Lauf mit Ausgabe:

| Fall | Ergebnis |
|------|----------|
| S1 Deckel 75 s, Sitzung gehalten | Chat "Noch 5 Minuten." bei 4,8 s, "Noch 1 Minute." bei 19,9 s, getrennt nach 75,7 s mit "Deine Spielzeit für heute ist aufgebraucht. Nächste Spielzeit: Sa 10:00", ohne "Kicked" |
| S2 Rejoin nach 2,5 s | `denied` mit demselben Text |
| S3 Zählbuch | Mia 75 |
| S4 Neustart per API | Zählbuch Mia unverändert 75; nach erneutem Schreiben der Regeldatei Mia sofort `denied` mit Limit-Text |
| S5 Leo ohne Zeile, 20 s | `held` (Positivkontrolle) |
| S6 Live-Push cap = aktueller Stand | getrennt 0,5 s nach dem Schreiben (Grenze 8 s) |
| S7 Welt zu (`welt 0 0 welt Mi-10:00`) | Mia `denied` "Diese Welt ist gerade geschlossen. Sie öffnet Mi 10:00"; Papa (`frei`) `auth_accept`; "Fremder" `denied` "nicht eingeladen" |
| S8 halbe Regeldatei | alter Stand: Mia weiter `denied` (Welt zu), Papa weiter `auth_accept` |
| S9 Zählbuch-Inhalt | nur Kopf, `<Name> <Zahl>` (Mia, Leo) und `end` |
| S10 4 min Rest | genau ein Chat "Noch 5 Minuten.", keiner mit "Noch 10 Minuten" |
| S11 `Papa -1 -1 -1 frei -` | vom Mod angenommen (siehe S7) |

Gesamtsuite mit Docker (`GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q`): 680 passed in 6:38 min, davon 656 ohne Docker und 24 Docker-e2e. Danach kein Container mit Label `gameworld.managed=true`.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 | 2ec36c0 | Wiederbeitritts-Sperre, disconnect_player, Session-Prober, Rejoin-e2e MTG und VoxeLibre |
| 2 | a70ce88 | gameworld_time-Mod, Regeldatei, Zählbuch (pure, 72 Unit-Tests) |
| 3 | 2e4631f | Zeit-Mod und Regeldatei in jede Welt, read_time_ledger, Durchsetzungs-e2e S1 bis S11 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Welt-Zeile braucht den Grund "welt"**
- **Found during:** Task 2
- **Issue:** Die behavior-Liste erlaubt nur die Gründe ok, tag, fenster, limit, frei. S7 und 04-05 schreiben aber die Welt-Zeile `welt 0 0 welt Mi-10:00`; das hätte `render_time_file` abgelehnt.
- **Fix:** Spielerzeilen prüfen gegen `REASONS` (wie geplant), die Welt-Zeile gegen eigene `WORLD_REASONS = {ok, welt}`. Der Mod wertet bei der Welt-Zeile nur `from`/`until` aus und nennt immer den Welt-Text.
- **Commit:** a70ce88

**2. [Hinweis] TDD-Commits zusammengefasst**
- Je Task ein Commit mit der im Plan genannten Nachricht (Vorgabe "atomar je Task"). RED wurde jeweils lokal belegt (Task 1: 4 rote Tests vor der Umsetzung, Task 2: Sammelfehler wegen fehlendem Modul), aber nicht separat committet.

**3. [Hinweis] Unverändert gebliebene Kandidaten**
- `tests/test_service_unavailable.py`, `test_reconciler.py`, `test_access_service.py`, `test_invites_api.py`, `test_provisioner_errors.py` und `tests/e2e/test_access_e2e.py` brachen durch die neuen Signaturen nicht (`time_file` ist optional, die Fakes nehmen beliebige Tars). Sie blieben unverändert.

**4. [Hinweis] Async-Sleeps in e2e**
- ruff (ASYNC251) verbietet `time.sleep` in async Tests; die Pausen laufen über `anyio.sleep`. Die gehaltene Leo-Sitzung in S6 läuft per `anyio.to_thread.run_sync` parallel zum Live-Push.

## Known Limitations

- Ohne Luanti-Interpreter auf dem Host ist die Lua-Syntax nur live geprüft (Welt startet, alle S-Fälle grün), nicht per Unit-Test.
- Darstellung der Umlaute und das Verhalten nach `disconnect_player` im echten Client bleiben Owner-Abnahme (04-08).
- Zeitregeln aus der Datenbank gibt es noch nicht: `_time_file` liefert in 04-01 eine leere Regeldatei. Laufende Welten bekommen Zugangs-Sperre und Zeit-Mod erst mit dem nächsten Start.
- Der Dev-Backend-Prozess (Port 10040) läuft noch mit dem Code von vor diesem Plan; nicht neu gestartet, weil der Plan es nicht verlangt.
- Der grep auf `/exec` in `src/gameworld` findet nur die bestehende Negativ-Probe des Setup-Checks (`setup_check.py:103`).

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat-Modells: keine neuen Endpunkte, kein exec, keine neuen Proxy-Freigaben. Neu sind nur die im Modell geführten Dateien im Welt-Volume (Regeldatei root 0444, Zählbuch uid 30000) und der Lesepfad `read_time_ledger` (get_archive über `_owned`, gekappt auf 4096 Bytes). T-04-01 bis T-04-09 sind umgesetzt und live bzw. per Unit-Test belegt.

## Self-Check: PASSED

- Dateien vorhanden: time_mod.py, test_time_mod.py, time_helpers.py, test_rejoin_guard_e2e.py, test_time_mod_e2e.py
- Commits vorhanden: 2ec36c0, a70ce88, 2e4631f
- `git diff da6ba79 HEAD -- src/gameworld/provisioner/spec.py` leer (Label bleibt 2), `grep -c kick_player access_mod.py` = 0
