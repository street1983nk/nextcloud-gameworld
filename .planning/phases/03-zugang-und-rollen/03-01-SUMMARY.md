---
phase: 03-zugang-und-rollen
plan: 01
subsystem: provisioner
tags: [luanti, whitelist, srp, world-mod, put_archive, e2e]
requires:
  - phase: 02-one-click-welten
    provides: Welt-Mod-Muster gameworld_status, put_archive-Payload, _launch mit Port-Saga und Neuerzeugung
provides:
  - luanti_auth.make_verifier (SRP-6a wie Luanti 5.17.0, Golden Vector)
  - Welt-Mod gameworld_access mit render_access_file, ACCESS_FILE, STATE_FILE
  - DockerProvisioner.write_world_files (put_archive in laufende und gestoppte Welten)
  - archive.build_world_files und build_access_tar
  - WorldService._access_file (in 03-01 leer, 03-03 füllt es aus Schema 3)
  - tests/e2e/luanti_probe.py (UDP-Join-Prober mit SRP-Client)
affects: [03-03, 03-04, 03-05, 04]
tech-stack:
  added: []
  patterns:
    - "Durchsetzung im Spielserver per Welt-Mod, gespeist aus einer Datei, die nur die ExApp schreibt"
    - "Lua-Quelltext reines ASCII, Kindertexte als Lua-Dezimal-Escapes"
key-files:
  created:
    - src/gameworld/provisioner/luanti_auth.py
    - src/gameworld/provisioner/access_mod.py
    - tests/test_luanti_auth.py
    - tests/test_access_mod.py
    - tests/e2e/luanti_probe.py
    - tests/e2e/test_access_e2e.py
  modified:
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/service.py
    - tests/test_archive.py
    - tests/test_service_lifecycle.py
    - tests/test_service_unavailable.py
key-decisions:
  - "Label gameworld.schema bleibt 2; spec.py, test_spec.py, test_presets_e2e.py, acceptance-phase2.sh unverändert"
  - "Lua-Quelltext reines ASCII; Kindertexte stehen als Python-Konstanten (TEXT_*) mit Umlauten und gehen als Lua-Dezimal-Escapes in den Mod"
  - "Sperre setzt beim 5. Fehlversuch ein festes Ende (jetzt plus 600 s) statt Fenster ab dem ersten Fehlversuch"
  - "_launch schreibt Mods und Zugangsdatei im selben try wie start_world; WorldNotFoundError beim Schreiben nimmt den Neuerzeugungspfad"
requirements-completed: []
metrics:
  duration: 30 min
  completed: 2026-10-20
  tasks: 3
  files: 13
---

# Phase 3 Plan 01: Durchsetzung im Spielserver Summary

Mit dem Welt-Mod `gameworld_access` (Whitelist im Prejoin, Passwort per SRP-Verifier, Sperre nach 5 Fehlversuchen, Kick-Takt, Rückmeldung der Generation) und einer per put_archive geschriebenen Zugangsdatei ist jede Welt für Fremde zu. Belegt ist das mit einem UDP-Prober gegen echte MTG- und VoxeLibre-Welten.

## Ergebnis

- `luanti_auth.make_verifier` ergibt genau den Golden Vector aus dem Live-Spike (wörtlich im Test).
- Neue Welten haben beide Mods und eine leere Zugangsdatei (`gameworld-access 1 0` / `end`, root 0444). Damit ist jede neue Welt zu, bis jemand eingeladen ist.
- Vor jedem `start_world` schreibt `_launch` beide Mods und die aktuelle Zugangsdatei per put_archive. Das gilt für Erzeugen, Start, Neustart, Neuerzeugung und den Boot-Abgleich. Ältere Schema-2-Welten bekommen den Mod so beim nächsten Start. Es gibt kein exec und keine neue Proxy-Freigabe.
- Live nachgewiesen (`tests/e2e/test_access_e2e.py`, 4 Tests, 26 s):
  - Fremder: `denied CUSTOM_STRING` mit "nicht eingeladen", auf MTG und VoxeLibre
  - Eingeladene Mia: nur HELLO mit `auth_mechs 2`, mit richtigem Passwort `auth_accept`, mit falschem `WRONG_PASSWORD`
  - Weltschlüssel als Passwort: `WRONG_PASSWORD`
  - `mia` statt `Mia`: deutscher Schreibweisen-Hinweis
  - Halbe Datei: der alte Stand bleibt
  - Widerruf wirkt beim nächsten Join
  - State-Datei meldet Generation 2, nach Neustart 0
  - Nach Neustart ist Leo draußen (DB kennt noch keine Einladungen)
  - Nach 5 Fehlversuchen: "Zu viele falsche Passwörter"
- Gesamtsuite mit Docker: 408 passed. Danach war kein Welt-Container übrig.

## Commits

| Task | Commit | Beschreibung |
|------|--------|--------------|
| 1 RED | b861862 | failing tests SRP-Verifier und Mod |
| 1 GREEN | 15d1b06 | luanti_auth.py, access_mod.py |
| 2 RED | 87f5bfe | failing tests für Weltdateien beim Start |
| 2 GREEN | 54e1a3d | archive/client/service: Mods und Zugangsdatei vor jedem Start |
| 3 | d0158a4 | Prober und Zugangs-e2e (MTG, VoxeLibre) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Owner-Regel] Lua-Quelltext ohne Umlaute**
- **Found during:** Task 1
- **Issue:** Die Projektregel verbietet Umlaute im Code und in Lua. Der Plan verlangt aber Kindertexte mit Umlauten (A9).
- **Fix:** Die Texte stehen als Python-Konstanten `TEXT_DENY/KICK/LOCKED/CASE_HINT` mit Umlauten. `_lua_string` gibt sie als Lua-Dezimal-Escapes der UTF-8-Bytes aus (`f\195\188r`). `MOD_INIT_LUA` ist reines ASCII (Test), und das Spiel zeigt die echten Umlaute an.
- **Commit:** 15d1b06

**2. [Rule 1 - Bug] Sperrdauer**
- **Found during:** Task 1
- **Issue:** Im Spike lief die Sperre ab dem ersten Fehlversuch. Wer 5 Fehlversuche über mehrere Minuten verteilte, war dadurch weniger als 10 Minuten gesperrt.
- **Fix:** Beim 5. Fehlversuch wird `until_t = jetzt + LOCK_SECONDS` gesetzt. Nach Ablauf wird der Eintrag geleert.
- **Commit:** 15d1b06

**3. [Hinweis] Reconciler-Fake**
- `ReconcileFake` in `tests/test_reconciler.py` erbt vom `FakeProvisioner` aus `test_service_lifecycle.py` und bekommt `write_world_files` dadurch automatisch. Die Datei musste nicht geändert werden (12 statt 13 Dateien).

## Known Limitations

- Der deutsche Hinweis zur Groß- und Kleinschreibung erscheint nur, solange es noch kein Konto in der richtigen Schreibweise gibt. Hat `Mia` schon einmal gespielt, lehnt Luantis eingebaute Prejoin-Prüfung `mia` vorher mit englischem Text ab, weil sie vor den Mods registriert ist. Das ist Spike-Fall A5. Der Join bleibt in beiden Fällen gesperrt.
- Kick laufender Spieler im 5-s-Takt (A7) und die Darstellung der Umlaute im echten Client (A9) sind ohne Luanti-Client nicht live geprüft. Beides gehört zur Owner-Abnahme.
- Der grep auf `/exec` in `src/gameworld` findet nur die bestehende Negativ-Probe des Setup-Checks (`setup_check.py:103`). Die prüft, dass exec gesperrt ist. Neu ist kein exec-Pfad.
- Der Dev-Backend-Prozess (Port 10040) läuft noch mit dem Code von vor diesem Plan. Für Dev-Welten mit Zugangs-Mod muss er neu gestartet werden.

## Self-Check: PASSED

- Dateien vorhanden: luanti_auth.py, access_mod.py, luanti_probe.py, test_access_e2e.py, test_luanti_auth.py, test_access_mod.py
- Commits vorhanden: b861862, 15d1b06, 87f5bfe, 54e1a3d, d0158a4
- `git log ... spec.py test_spec.py test_presets_e2e.py acceptance-phase2.sh | grep -c "(03-01)"` = 0
