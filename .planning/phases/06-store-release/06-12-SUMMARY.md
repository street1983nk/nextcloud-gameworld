---
phase: 06-store-release
plan: 12
subsystem: acceptance, harp, local-registry, regression
tags: [acceptance, harp, local-registry, regression, phase-gate, platt-01, rolle-03, rolle-04]
requires: ["06-10", "06-11"]
provides:
  - "scripts/dev/harp.compose.yaml: eigene Test-Instanz (Nextcloud 34.0.3, gescopter Proxy, HaRP release, registry:2, nginx-Front) im eigenen Netz, Images per Index-Digest, Ports nur 127.0.0.1"
  - "scripts/dev/harp-install.sh: Image bauen, nach localhost:5000, Kopie der info.xml mit lokaler Registry, Daemon harp_dev, app_api:app:register --info-xml --wait-finish, uid-10001-Prüfung; --uninstall baut alles ab"
  - "scripts/dev/acceptance-phase6.sh: K1 bis K7 mit Negativ- und Positivkontrollen, Modi manual und harp, Regression über acceptance-phase5.sh"
  - "Produkt-Fixes: info.xml mit genau einem <name>; Gruppen-Verwalter lesen Mitglieder über /cloud/groups/{gid}/users; Talk-Abgleich fragt Verfügbarkeit frisch"
affects: [06-13, 06-14, 06-15, 06-16]
tech-stack:
  added: []
  patterns:
    - "Store-Installation vor Push und Zertifikat: echter HaRP-Daemon zieht aus localhost:5000, Registrierung per --info-xml einer Kopie"
    - "Abnahmen, die D-17 (Deaktivieren) oder einen gestoppten Proxy brauchen, laufen gegen eine eigene Test-Instanz statt gegen die Dev-Registrierung"
    - "Git Bash: MSYS_NO_PATHCONV=1 für Containerpfade, Host-Pfade für docker compose/build per cygpath -m"
key_files:
  created:
    - scripts/dev/harp.compose.yaml
    - scripts/dev/harp-front.nginx.conf
    - scripts/dev/harp-install.sh
    - scripts/dev/acceptance-phase6.sh
    - .planning/phases/06-store-release/deferred-items.md
  modified:
    - scripts/dev/register-exapp.sh
    - scripts/dev/acceptance-phase1.sh
    - scripts/dev/acceptance-phase3.sh
    - scripts/dev/acceptance-phase4.sh
    - scripts/dev/acceptance-phase4_1.sh
    - appinfo/info.xml
    - docs/store-listing.md
    - docs/dev-setup.md
    - src/gameworld/access/directory.py
    - src/gameworld/access/service.py
    - src/gameworld/talk/service.py
    - tests/test_info_xml.py
    - tests/test_nc.py
    - tests/test_admin_snapshot.py
    - tests/test_talk_service.py
decisions:
  - "HaRP-Abnahme auf eigener Test-Nextcloud (harp.compose.yaml) statt im Dev-Stack: Das Umhängen der Dev-Registrierung auf HaRP wurde vom Auto-Mode-Klassifikator als Eingriff in geteilte Ressourcen abgelehnt, und D-17 hätte die Owner-Welten abgeräumt; Owner-Weisung erlaubt ausdrücklich die Probe über eine Test-Stack-Instanz"
  - "K3 Deaktivieren/Aktivieren nur im Modus harp; im Modus manual gehören der Instanz die laufenden Owner-Welten (Hinweiszeile statt Prüfung)"
  - "register-exapp.sh lässt eine passende Registrierung stehen bzw. startet das Backend mit neuem Secret neu, bevor es neu registriert: /enabled?enabled=0 mit gültigem Secret hätte über D-17 alle Welten der Dev-Instanz abgeräumt"
  - "info.xml trägt <name> nur einmal ohne lang (AppAPI machte aus drei Namen ein Array, App hieß \"Array\")"
  - "Gruppen-Verwalter-Mitgliedschaft über /cloud/groups/{gid}/users (Mitglieder erlaubt, Nicht-Mitglieder 403), nicht über den Subadmin-Endpunkt /cloud/groups/{gid}"
  - "reconcile_all ruft is_available(fresh=True); GET /api/talk und das Anlegen nutzen weiter den 300-s-Cache"
  - "K6 Pausentext ist TEXT_PAUSE (\"Kurze Pause!\"), nicht TEXT_HALT; der Plan nannte TEXT_HALT nur als Muster"
  - "gameworld-orphans.sh-Gegenprobe: Mit laufenden Owner-Welten ist \"No Gameworld leftovers found.\" nicht erreichbar; geprüft wird: Skript ändert nichts (docker ps -a und volume ls gleich), nennt den entfernten Orphan nicht mehr, listet vorhandene Welten (Positivkontrolle), \"Nothing was changed.\"; die Leer-Meldung nur, wenn der Host keine Gameworld-Objekte hat"
metrics:
  duration: "ca. 6 h (davon gut 4 h Abnahmeläufe)"
  completed: "2026-10-24"
  tasks: 2
  files: 20
---

# Phase 6 Plan 12: Dev-HaRP mit lokaler Registry und Phasenabnahme Summary

Gameworld installiert sich über einen echten HaRP-Daemon aus `localhost:5000` per `occ app_api:app:register --info-xml` als Container mit uid 10001; acceptance-phase6.sh belegt K1 bis K7 in beiden Modi (manual 130 von 130 inklusive Regression Phase 5 bis 1, harp 140 von 140) und hat drei echte Produktfehler aufgedeckt und mit Fix-Commits behoben.

## Tasks

| Task | Name | Commits | Dateien |
|------|------|---------|---------|
| 1 | Dev-HaRP mit lokaler Registry und harp-install.sh | bcb90f6 | scripts/dev/harp.compose.yaml, harp-front.nginx.conf, harp-install.sh, register-exapp.sh |
| 2 | acceptance-phase6.sh K1 bis K7 plus Regression, Läufe manual und harp | 4c5b9a4 (Skript), 99a900d und d3ad410 (Regression an den Produktstand), Fixes siehe unten | scripts/dev/acceptance-phase6.sh, acceptance-phase1/3/4/4_1.sh, docs/dev-setup.md |

## Lauf-Ergebnisse (Endstand, Code b83ab5f)

- **manual** (`sh scripts/dev/acceptance-phase6.sh`, Dev-Stack 8091): **130 von 130 Prüfungen bestanden**, Exit 0, "Phasenabnahme Phase 6 erfolgreich (Modus manual)", 16:50 bis 17:54.
  - Regression: Phase 5 103 von 103, Phase 4.1 133 von 133, Phase 4 109 von 109, Phase 3 75 von 75, Phase 2 104 von 104, Phase 1 84 von 84. Keine Tageszeit-Sperre berührt (Lauf vor 23 Uhr).
- **harp** (`GAMEWORLD_DEPLOY=harp GAMEWORLD_SKIP_REGRESSION=1`, Test-Instanz 8093): **140 von 140 Prüfungen bestanden**, Exit 0, "Phasenabnahme Phase 6 erfolgreich (Modus harp)", nach Neubau des Images mit dem Endstand.
- Logs liegen in `.dev/acceptance-phase6-manual.log`, `.dev/acceptance-phase6-harp.log`, `.dev/acceptance-phase5-regression.log` (gitignored).
- Frühere Läufe (Belege der Fixes): harp 1 (K5/K6 rot: 403/503 beim Einladen, Abbruch K7 durch Subshell-Fehler im Skript), harp 2 (K6 Wiederbeitritts-Sperre im Skript, K7 Sperrfall), manual 1 (Regression rot: Phase-1-Statikprüfung gegen Store-Text), manual 2 (126 von 130: Phase 4.1 K6 Raum nach 332 s statt höchstens 330 s).

## Akzeptanzkriterien Task 1

- `sh scripts/dev/harp-install.sh` Exit 0; `occ app_api:app:list` (Test-Nextcloud) zeigt `gameworld (Gameworld): 1.0.0 [enabled]`, Daemon `harp_dev` (docker-install, Is HaRP yes).
- `docker inspect --format '{{.Config.User}}' nc_app_gameworld` = `10001:10001`, Image `localhost:5000/street1983nk/gameworld:1.0.0`, healthy.
- `git diff -- appinfo/info.xml` leer gegenüber dem Commit (nur `.dev/info-harp.xml` umgeschrieben); `git status --porcelain .dev` leer.
- `docker compose -f scripts/dev/harp.compose.yaml config -q` gelingt nur mit gesetztem `GAMEWORLD_HARP_KEY` (gewollt, `${VAR:?}`, T-06-52); ohne Variable bricht compose mit klarer Meldung ab.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] App hieß nach der Installation über info.xml "Array"**
- **Found during:** Task 1 (erste HaRP-Registrierung)
- **Issue:** Drei `<name>`-Elemente (en/de/fr) aus 06-11; AppAPI wandelt info.xml per simplexml/json, `setName()` bekam ein Array. Derselbe Pfad gilt für die Store-Installation.
- **Fix:** Genau ein `<name>Gameworld</name>`, store-listing.md nachgezogen, Strukturtest.
- **Files modified:** appinfo/info.xml, docs/store-listing.md, tests/test_info_xml.py
- **Commits:** 78e013e (RED), c3351f5 (GREEN)

**2. [Rule 1 - Bug] Gruppen-Verwalter als reines Mitglied konnte niemanden einladen (ROLLE-03, Kriterium 5)**
- **Found during:** Task 2, harp-Lauf 1 (K5: gw-lehrer lädt gw-kind-k ein 403, Gruppe klasse 503)
- **Issue:** `NcDirectory.group_members` nutzte nc_py_api `users_groups.get_members`, also `/cloud/groups/{gid}`; Nextcloud verlangt dort Subadmin-Rechte ("must be at least a sub admin"). Die Unit-Tests mit Fake-Directory konnten das nicht sehen.
- **Fix:** `/ocs/v1.php/cloud/groups/{gid}/users` (NC-Quelle: `getGroupUsers` mit `@NoSubAdminRequired`, erlaubt Mitgliedern); Nicht-Mitglieder bekommen weiter 403 (live gegengeprüft: Gruppe admin als gw-lehrer 403). Admin-Gegenprobe (verify) unverändert.
- **Files modified:** src/gameworld/access/directory.py, src/gameworld/access/service.py (Docstring), tests/test_nc.py, tests/test_admin_snapshot.py
- **Commits:** a875e1b (RED), 034bc4b (GREEN)

**3. [Rule 1 - Bug] Nachlegen eines Talk-Raums konnte zehn Minuten dauern**
- **Found during:** Task 2, manual-Lauf 2 (Regression Phase 4.1 K6: 332 s statt höchstens 330 s)
- **Issue:** `is_available`-Cache (300 s) und Wartung (300 s) im gleichen Takt; traf die Wartung den Cache kurz vor Ablauf, galt "Talk aus" einen ganzen Takt weiter.
- **Fix:** `reconcile_all` fragt mit `fresh=True`; GET /api/talk und Anlegen bleiben gecacht. Danach 317 s.
- **Files modified:** src/gameworld/talk/service.py, tests/test_talk_service.py
- **Commits:** c5e54a1 (RED), b83ab5f (GREEN)

**4. [Rule 2 - Schutz] register-exapp.sh hätte Owner-Welten über D-17 abgeräumt**
- **Found during:** Task 1 (Analyse vor dem ersten Lauf)
- **Issue:** Seit 06-08 räumt `/enabled?enabled=0` alle eigenen Welt-Container ab. register-exapp.sh entfernte jede Registrierung; bei wiederverwendetem Backend (gleiches Secret) kommt der Aufruf an.
- **Fix:** Passende Registrierung (Version und Routen-Prüfsumme in `.dev/exapp.registered`) bleibt stehen; sonst Neustart mit neuem Secret vor dem Neu-Registrieren (alter Aufruf scheitert mit 401).
- **Commit:** bcb90f6

**5. [Rule 3 - Blocker] Regression erwartete den Produktstand vor Phase 6**
- 404 von AppAPI auf Kinder-Verwaltungsrouten ist seit 06-02 (alle Routen USER, `require_verwalter`) ein 403 vom Backend: 12 Prüfungen in Phase 1, 3, 4, 4.1 angepasst, gleiche Anzahl (99a900d).
- Phase-1-Statikprüfung fand "Serverliste" im deutschen Store-Text von 06-11 ("keine Welt steht jemals in einer Serverliste"); sie liest info.xml jetzt ohne `<description>`-Blöcke, gleiche Anzahl 84 (d3ad410).

**6. [Rule 3 - Blocker] HaRP-Weg auf eigener Test-Instanz statt im Dev-Stack**
- Der Plan sah HaRP im Netz `gameworld-dev_default` mit Umhängen der Dev-Registrierung vor. Das Entfernen der manual_install-Registrierung des Owners lehnte der Auto-Mode-Klassifikator ab ("Modify Shared Resources"); die Dev-Registrierung wurde sofort per register-exapp.sh wiederhergestellt (Owner-Welten liefen durch). Umgesetzt wie in der Owner-Weisung vorgesehen: eigene Test-Nextcloud, eigener Proxy, eigenes Netz `gameworld-dev-harp_default`. Die Front zeigt deshalb auf `harp-nc` statt `app`, Talk wird in der Test-Instanz per `occ app:install spreed` installiert (wie docs/dev-setup.md).

**7. Plan-Präzisierungen in acceptance-phase6.sh**
- K1 "Heartbeat über den AppAPI-Proxy" ist nicht möglich (keine Route in info.xml, 404); belegt stattdessen per Docker-Healthcheck (Heartbeat im Image, healthy) und `/exapps/gameworld/api/me` über HaRP (ohne Anmeldung 403, mit 200).
- "Spielzeitregel 0 Minuten" = Wochenplan ohne Spieltag (Limit muss 1 bis 1440 sein), Kindertext "Heute ist kein Spieltag".
- 404-Falle mit einem von admin direkt eingeladenen Konto außerhalb der Gruppen von gw-lehrer (sonst prüfte die Falle nichts), Positivkontrolle durch echtes Entfernen.
- K7: vor dem Löschen von gw-alt wartet die Abnahme, bis admin Moderator ist (siehe deferred-items.md), und prüft dann Übernahme ohne neuen Raum (Token unverändert).
- Regression im Modus harp nur mit `GAMEWORLD_SKIP_REGRESSION=1` (sonst fail); der Übersprung selbst ist eine Hinweiszeile, damit der harp-Lauf wie im Plan mit Exit 0 endet.

## Deferred Issues

- Talk-Raum eines frisch (wieder) ernannten Verwalters ist bis zum nächsten Verwalter-Schnappschuss allein (Sperrfall greift korrekt, kein Leck). Sicherheitsrelevant, darum mit deep Review statt nebenbei: `.planning/phases/06-store-release/deferred-items.md`.

## Umgebung und Schutz der Owner-Welten

- Owner-Welten `gameworld-788fff30-ff2295234c42` und `-e032336f9b6d`: StartedAt vor und nach allen Läufen `2026-10-24T05:46:46Z`, durchgehend running; kein Deaktivieren der Dev-Registrierung (die K3-Probe lief nur gegen die Test-Instanz `c3dd0c96`).
- Fremde Volumes `gameworld-a60510fd-*` unberührt. Test-Stack nach den Läufen mit `harp-install.sh --uninstall` restlos entfernt (Registrierung, nc_app_gameworld samt Datenvolume, Daemon, Container, Volumes); das lokal gebaute Image `localhost:5000/street1983nk/gameworld:1.0.0` bleibt als Build-Cache.
- RAM: Docker-VM 6,2 GB; frei auf dem Host zu Beginn 4,0 GB, während der Läufe 0,7 bis 2,2 GB (vmmemWSL hält den Page-Cache der Builds). Alles strikt seriell, nichts parallel.
- Gates am Planende: ruff check und format, pyright latest 0 Fehler, vulture sauber, `sh -n` für alle Skripte, `uv run pytest -m "not docker" -q` 2591 passed.
- Nichts gepusht (lokale Registry zählt nicht), keine Claude-Trailer, .planning/config.json und REQUIREMENTS.md unangetastet.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: T-06-52 mitigiert | scripts/dev/harp.compose.yaml, harp-install.sh | HP_SHARED_KEY nur in .dev/harp.key (umask 077, gitignored), compose per `${GAMEWORLD_HARP_KEY:?}`; Restrisiko: der Schlüssel steht kurz in der Prozessliste des Nextcloud-Containers (occ-Argument `--harp_shared_key`) |
| threat_flag: T-06-53 mitigiert | scripts/dev/harp.compose.yaml | Registry 127.0.0.1:5000, Front 127.0.0.1:8093; HaRP, Test-Nextcloud und Test-Proxy ohne Host-Port |
| threat_flag: Docker-Socket im Dev-HaRP | scripts/dev/harp.compose.yaml | HaRP hält den Socket (root-äquivalent, nur Dev), der ExApp-Container bekommt ihn nie (K1 prüft Mounts) |
| threat_flag: Fest kodierte Dev-Passwörter | scripts/dev/harp.compose.yaml, acceptance-phase6.sh | admin der Test-Instanz und Wegwerfkonten mit bekannten Passwörtern, nur Loopback und nur Dev; Spielpasswörter erscheinen nie in der Ausgabe, nur ihre Länge |
| threat_flag: Zugriffsänderung Gruppen | src/gameworld/access/directory.py | Gruppen-Verwalter lesen jetzt Mitglieder ihrer eigenen Gruppen (Nextcloud-Regel, keine App-Systemrechte, D-01); fremde Gruppen weiter 403; für die Sicherheitsabnahme der Phase (secure-phase) vormerken |

## Known Stubs

Keine.

## Self-Check: PASSED

- Dateien vorhanden: scripts/dev/harp.compose.yaml, scripts/dev/harp-front.nginx.conf, scripts/dev/harp-install.sh, scripts/dev/acceptance-phase6.sh (1037 Zeilen), .planning/phases/06-store-release/deferred-items.md
- Commits vorhanden: 78e013e, c3351f5, bcb90f6, a875e1b, 034bc4b, 99a900d, 4c5b9a4, d3ad410, c5e54a1, b83ab5f
- `grep -n "exec_run\|DockerProvisioner\|from gameworld" scripts/dev/acceptance-phase6.sh` ohne Treffer; `grep -n GAMEWORLD_SKIP_TALK` findet den Schalter; Pfad ohne Talk ist eine fail-Zeile
- Nach den Läufen: kein Container mit Label gameworld.instance=acceptance-orphan, alle Wegwerfkonten und Gruppen entfernt, keine neuen Welt-Container
