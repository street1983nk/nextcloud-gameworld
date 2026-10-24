---
phase: 06-store-release
plan: 07
subsystem: provisioner
tags: [ar-23, spike, hardening, luanti, docker, e2e]
requires: []
provides:
  - "archive.py: WORLD_DIR_MODE 0o1775, ROOT_DIR_MODE 0o755, LUANTI_DIR_MODE, FILE_MODE; _add_dir(uid, gid, mode), _add_root_dir, _add_mod_files"
  - "build_world_payload (neue und wiederhergestellte Welten): Weltordner root:30000 1775, worldmods samt Mods root 0755/0644"
  - "build_world_files (vor jedem Start): worldmods samt Mods root-eigen, Weltordner unberührt"
  - "tests/e2e/test_world_dir_hardening_e2e.py: dauerhafter e2e-Beleg (Rechte per stat, 7 Schreibversuche, Positivkontrolle, Luanti schreibt)"
affects: [06-11]
tech-stack:
  added: []
  patterns:
    - "Rechte-Gegenprobe über kurzlebigen Hilfscontainer (gepinntes Luanti-Image, User 30000:30000, cap_drop ALL, network none, read-only), nie exec"
key-files:
  created:
    - tests/e2e/test_world_dir_hardening_e2e.py
  modified:
    - src/gameworld/provisioner/archive.py
    - tests/test_archive.py
decisions:
  - "AR-23-Spike grün: Luanti 5.17.0 läuft mit Weltordner root:30000 1775 und root-eigenem worldmods; Härtung umgesetzt"
  - "Docker übergeht beim put_archive einen Tar-Eintrag für '.' (gemessen); der Weltordner wird darum nur über build_world_payload gesetzt (Erzeugung und Restore), bestehende Welten werden nicht migriert, bekommen aber beim nächsten Start root-eigenes worldmods"
  - "world.mt bleibt uid 30000 (Luanti schreibt sie im Lauf nicht neu, mtime bleibt 0)"
metrics:
  duration: "25 min"
  completed: "2026-10-24"
  tasks: 2
  files: 3
---

# Phase 6 Plan 07: AR-23 Weltordner-Härtung Summary

Spike gegen echtes Luanti 5.17.0 grün; neue und wiederhergestellte Welten haben jetzt den Weltordner root:30000 mit Sticky-Bit (1775) und ein root-eigenes worldmods (0755/0644), Luanti (uid 30000) kann Zugangsdatei, Regeldatei und Welt-Mods weder löschen noch umbenennen noch überschreiben.

## Spike-Ergebnis (Task 1, D-21): GRÜN

Lauf gegen den Dev-Docker-Proxy, Welt `mtg_kreativ` über den echten WorldService erzeugt, gestoppt, Rechte per put_archive über eigenen DockerClient gesetzt, Container direkt gestartet (am Provisioner vorbei, weil `_launch` damals worldmods wieder Luanti übergeben hätte), eingeladener Spieler 10 s gehalten, gestoppt. Prüfung über Hilfscontainer.

| Prüfung | Ergebnis |
|---|---|
| Luanti startet, Spieler `held` 10 s | ja |
| Containerlog ohne "Permission denied" und "ERROR[Main]" | ja |
| map.sqlite neu geschrieben (mtime) | ja (1792828873 auf 1792828881) |
| env_meta.txt neu geschrieben | ja (1792828874 auf 1792828887) |
| Zählbuch gameworld_time_used.txt neu geschrieben | ja (1792828874 auf 1792828887) |
| players.sqlite / auth.sqlite angelegt | ja, beide neu |
| Rechte nach dem Spiel unverändert (stat) | Weltordner `0:30000 1775`, worldmods und 3 Mod-Ordner `0:0 755`, 6 Mod-Dateien `0:0 644`, Zugangs- und Regeldatei `0:0 444` |
| rm gameworld_access.txt als 30000 | scheitert (Exit 1) |
| mv gameworld_access.txt als 30000 | scheitert (Exit 1) |
| gameworld_time.txt überschreiben | scheitert (Exit 1) |
| gameworld_time.txt per mv -f ersetzen (zusätzlich) | scheitert (Exit 1) |
| rm -rf worldmods | scheitert (Exit 1) |
| Datei in worldmods anlegen | scheitert (Exit 1) |
| Mod-Datei init.lua überschreiben (zusätzlich) | scheitert (Exit 1) |
| Positivkontrolle: eigene Datei anlegen und umbenennen | gelingt (Exit 0) |

Spike-Commit: 7032359.

## Task 2: Härtung

- `_add_dir` mit `uid`, `gid`, `mode`; Konstanten `WORLD_DIR_MODE = 0o1775`, `ROOT_DIR_MODE = 0o755`.
- `build_world_payload`: Weltordner root:30000 1775, worldmods und alle Mod-Ordner root 0755, Mod-Dateien root 0644, Zugangs- und Regeldatei root 0444 (wie bisher); world.mt, Spiel, `.minetest`, `.minetest/worlds`, `.minetest/games` bleiben 30000. Restore baut über diesen Pfad ein frisches Volume und spielt danach nur Luanti-Dateien (30000) ein; worldmods, `gameworld_*` und der Welt-Wurzeleintrag werden dabei verworfen, die Härtung bleibt also erhalten.
- `build_world_files`: worldmods samt Mods root-eigen; vor jedem Start eingespielt.
- e2e-Test prüft jetzt die echte Erzeugung über den normalen Start-Pfad (POST /start, `_launch`): Werte identisch zum Spike (Weltordner `0:30000 1775`, worldmods `0:0 755`, world.mt `30000:30000 644`), alle Schreibversuche Exit 1, Positivkontrolle Exit 0, Luanti schreibt map/env_meta/Zählbuch/players/auth.
- world.mt-Frage aus dem Plan: Luanti schreibt world.mt beim Start nicht neu (mtime bleibt 0 vor und nach dem Lauf); sie bleibt trotzdem Luanti-eigen wie bisher.

**Für install.md (06-11):** Die Härtung gilt für neue und wiederhergestellte Welten. Bestehende Welten werden nicht migriert: Ihr Weltordner bleibt 30000:30000 0755, worldmods wird aber beim nächsten Start root-eigen. Wer eine bestehende Welt voll härten will, sichert sie und stellt sie wieder her.

## Gates und Tests

- ruff check, ruff format --check, pyright basic (latest), vulture: ohne Befund vor jedem Commit.
- `uv run pytest -q tests/test_archive.py tests/test_backup_archive.py`: 81 passed.
- e2e seriell (freier RAM vor jedem Lauf 3,7 bis 3,9 GB): test_world_dir_hardening_e2e 1 passed, test_create_world_e2e 1 passed, test_invite_join_e2e 3 passed, test_backup_restore_e2e 7 passed.
- `uv run pytest -m "not docker" -q`: 2293 passed, 44 deselected.
- `grep -c exec_run tests/e2e/test_world_dir_hardening_e2e.py`: 0.
- Aufräumen: keine Container mit Label `gameworld.spike`, keine Volumes der Testinstanzen übrig; Dev-Stack und Owner-Welten (gameworld-788fff30-*) liefen durchgehend. Die Volumes `gameworld-a60510fd-*` stammen vom 23.10. (nicht aus diesem Plan) und wurden nicht angefasst.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug im Plan] build_world_files kann den Weltordner nicht setzen**
- **Found during:** Task 2
- **Issue:** Die behavior-Zeile verlangt den Weltordner-Eintrag (uid 0, gid 30000, 1775) auch in `build_world_files`. Gemessen (Wegwerf-Volume, docker-py über den Proxy): Docker übergeht einen Tar-Eintrag `.` und `./` beim put_archive ohne Wirkung auf Besitzer und Modus.
- **Fix:** Weltordner nur in `build_world_payload` (Erzeugung und Restore); `build_world_files` härtet worldmods und hat bewusst keinen `.`-Eintrag. Unit-Test belegt beides. Deckt sich mit "Bestehende Welten werden nicht migriert".
- **Commit:** 2031eac

**2. [Rule 2 - Strenger] Zwei zusätzliche Schreibversuche und world.mt-Prüfung**
- Zusätzlich zu den fünf geplanten Versuchen: Ersetzen der Regeldatei per `mv -f` und Überschreiben einer Mod-Datei; dazu stat von world.mt (muss 30000 bleiben).

**3. [Plan-Rahmen] Spike startete den Container direkt**
- Im Spike startete der Test den Container über den eigenen Client, weil `_launch` mit dem alten Code worldmods vor dem Start wieder auf 30000 gesetzt hätte. Der dauerhafte Test nach Task 2 nutzt den normalen Startpfad.

**4. TDD-RED ohne Konstanten-Test**
- Ein RED-Test auf `archive.WORLD_DIR_MODE` hätte pyright (Gate vor jedem Commit) rot gemacht; die Konstante belegt das Akzeptanzkriterium per grep, die Rechte belegen die Unit-Tests.

## TDD Gate Compliance

RED 0b9b913 (`test(06-07)`, 7 Tests rot), GREEN 2031eac (`feat(06-07)`, 22 passed). Kein REFACTOR nötig.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: residual | src/gameworld/provisioner/archive.py | Eltern des Weltordners (`/var/lib/minetest` als Volume-Wurzel 30000:30000 2755 aus dem Image, `.minetest`, `.minetest/worlds`) gehören weiter Luanti. Ein kompromittierter Luanti-Prozess kann darum den ganzen Weltordner umbenennen und einen eigenen anlegen. Die Volume-Wurzel lässt sich per put_archive nicht ändern (`.`-Eintrag wird übergangen, `/var/lib` liegt im read-only Root-Dateisystem). Owner-Entscheid für später, nicht Teil von AR-23 |
| threat_flag: residual | src/gameworld/provisioner/archive.py | Spiel unter `.minetest/games/<spiel>` und world.mt bleiben 30000-eigen; ein kompromittierter Luanti-Prozess könnte Spiel-Lua dauerhaft ändern (wird erst bei Neuerzeugung oder Restore ersetzt). Vorher schon so, unverändert |
| threat_flag: migration | src/gameworld/provisioner/archive.py | Bestehende Welten behalten den Luanti-eigenen Weltordner bis zu Sicherung und Wiederherstellung (in install.md, 06-11, vermerken) |

T-06-29, T-06-30, T-06-31, T-06-32: mitigiert wie im Plan (e2e-Belege oben).

## Known Stubs

Keine.

## Self-Check: PASSED

- FOUND: tests/e2e/test_world_dir_hardening_e2e.py (230 Zeilen)
- FOUND: src/gameworld/provisioner/archive.py mit `WORLD_DIR_MODE = 0o1775`
- FOUND: tests/test_archive.py
- FOUND: 7032359, 0b9b913, 2031eac
