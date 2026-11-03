---
phase: 06-store-release
plan: 15
subsystem: install-test
tags: [install-test, harp, nc34, nc35, aio, vm, registry]
requires: ["06-14"]
provides:
  - "Installation aus ghcr.io (1.0.0-rc.2) belegt: Compose mit HaRP auf NC 34.0.3 und NC 35.0.2, AIO v14.4.3 mit HaRP (harp_aio) auf NC 34.0.5"
  - "scripts/dev/aio-vm-test.sh: wiederholbarer AIO-Prüflauf (22 Prüfungen) mit --cleanup"
  - "harp-install.sh --source ghcr --tag, parametrisierte Test-Stacks (Projekt, Port, NC-Image, Netz)"
affects: [06-16]
tech-stack:
  added: []
  patterns:
    - "Registry-Test: info.xml-Kopie in .dev/, nur image-tag geändert, Original unverändert"
key-files:
  created:
    - scripts/dev/aio-vm-test.sh
    - .planning/phases/06-store-release/06-15-TASK1-NOTES.md
  modified:
    - scripts/dev/compose.yaml
    - scripts/dev/harp.compose.yaml
    - scripts/dev/harp-install.sh
    - scripts/dev/acceptance-phase6.sh
    - docs/install.md
    - docs/install.de.md
    - docs/dev-setup.md
decisions:
  - "Getestet wurde 1.0.0-rc.2 statt rc.1 (rc.2 aus PR #1 release-prep-rc2 war das aktuelle öffentliche rc)"
  - "Netzerkennung des Setup-Checks mit echtem HaRP auf allen drei Wegen selbst erkannt (detected), auch nextcloud-aio"
  - "Einzige Doku-Abweichung: Cloud-Firewall (Security Group) braucht eine UDP-Regel; AIO-Hinweis zu Port 8443 nicht übernommen (AIO-eigene Doku, keine Abweichung unserer Anleitung)"
  - "Keine Produktfehler, kein neuer rc-Build nötig"
metrics:
  duration: "Task 1 rund 50 min, AIO-Lauf mit Owner, Task 3 rund 10 min"
  completed: 2026-11-03
---

# Phase 6 Plan 15: Installationstests aus der Registry (Compose NC 34/35, AIO) Summary

Gameworld 1.0.0-rc.2 installiert sich aus ghcr.io über HaRP auf Compose mit NC 34 und NC 35 (je 183 von 183 Abnahmeprüfungen) und auf einer frischen AIO mit HaRP (22 von 22, echter Beitritt mit Luanti 5.17.0); die Anleitung brauchte nur einen Firewall-Satz.

- Basis-Commit: `6a0a075f82e72d4f1af35118d37d41879210ce85`
- Getestetes Image: `ghcr.io/street1983nk/gameworld:1.0.0-rc.2`, Index-Digest `sha256:724cdfa07a9bb9125a1f929368613b43dbbf5164069e34535cd97582355854a7` (amd64 + arm64)
- `appinfo/info.xml` gegenüber der Basis unverändert

## Commits

| Task | Commit | Betreff |
| ---- | ------ | ------- |
| 1 | e88daf8 | feat(06-15): install tests from ghcr.io on NC 34 and NC 35, AIO test script |
| 1 | 814b241 | docs(06-15): task 1 notes, install tests NC 34 and NC 35 from ghcr rc.2 |
| 2 | (kein Commit) | AIO-Lauf auf der VM, Owner-Checkpoint |
| 3 | 43185ee | docs(06-15): install guide after AIO and compose tests |

## Task 1: Compose NC 34 und NC 35 aus ghcr.io

Details, Speicherstände und Logs: `06-15-TASK1-NOTES.md`.

- Lauf A, NC 34.0.3, frischer HaRP-Stack: `harp-install.sh --source ghcr --tag 1.0.0-rc.2` Exit 0; Abnahme A3 **183 von 183**, Exit 0 (K1 15, K2 10, K3 25, K4 6, K5 19, K6 31, K7 20, K8 36), Talk 24.0.6. A1/A2 scheiterten an zwei Harness-Fehlern (admin ohne Sprache, veralteter Doku-Anker), Produkt korrekt.
- Lauf B, NC **`nextcloud:35.0.2-apache`** (Digest `sha256:e0b1a2af52c82c07b7a0e8e59878bd8769e704447734d5d238a836982f51b9c8`): volle Abnahme statt Kurzlauf, **183 von 183**, Exit 0, Talk 25.0.6. Danach `docker compose -p gameworld-nc35 ps -q` leer, Dev-Stack wieder gesund.
- Freier Speicher vor den Läufen (available): A 4390 MB, B 4514 MB (Dev-Stack gestoppt). Kein Engpass.
- Setup-Check erkannte in beiden Läufen das Netz selbst (`detected gameworld-dev-harp_default` bzw. `gameworld-nc35_default`).

## Task 2: AIO auf kurzlebiger Cloud-VM (mit Owner, 03.11.2026)

- Umgebung: AWS EC2 eu-central-1, t3.large, Ubuntu 24.04.5, Docker 29.9.2 (get.docker.com), AIO v14.4.3 (Mastercontainer per offiziellem `docker run` aus der AIO-README), Domain gwtest.infranode.dev (Cloudflare, DNS only), Office und Whiteboard aus, Talk an, HaRP an. AppAPI legte den Daemon `harp_aio` selbst an. Nextcloud 34.0.5 (AIO liefert derzeit 34, nicht 35).
- `sh aio-vm-test.sh --info-xml ./info-aio-1.0.0-rc.2.xml --tag 1.0.0-rc.2 --url https://gwtest.infranode.dev`: **22 OK, 0 FAIL** (Log `.dev/aio-run-0615.log`).
- Prüfausgabe (Auszug, ohne Passwörter):

```
OK      Container nextcloud-aio-harp läuft
OK      Netz nextcloud-aio vorhanden
OK      Daemon harp_aio registriert und HaRP
app_api:app:list: gameworld (Gameworld): 1.0.0 [enabled]
OK      ExApp-Container aus ghcr.io/street1983nk/gameworld:1.0.0-rc.2 (ist ghcr.io/street1983nk/gameworld:1.0.0-rc.2)
Image-Digest: ghcr.io/street1983nk/gameworld@sha256:724cdfa07a9bb9125a1f929368613b43dbbf5164069e34535cd97582355854a7
OK      ExApp-Container läuft als 10001:10001
OK      ExApp-Container im Netz nextcloud-aio (ist nextcloud-aio )
OK      ExApp-Container ohne Docker-Socket
Hinweis: kein HP_SHARED_KEY im ExApp-Container (Direktmodus, F-06)
OK      GET /api/me über den AppAPI-Proxy HTTP 200, Rolle verwalter
Befunde: ["proxy_dns"]
Proxy-Befehle: [{"id":"detected","network":"nextcloud-aio"}]
OK      Netz selbst erkannt: proxy_commands[0] = detected nextcloud-aio
OK      angezeigter Befehl ohne Host-Port (-p)
OK      gameworld-docker-proxy läuft
OK      gameworld-docker-proxy ohne Host-Port
OK      Setup-Check ohne Fehler
OK      POST /api/worlds HTTP 201 (ist 201)
OK      Welt running binnen 180 s (ist running)
docker port: 30000/udp -> 0.0.0.0:30000
OK      ss -uln: UDP 30000 lauscht
AIO-Prüflauf erfolgreich (keine Passwörter in dieser Ausgabe)
```

- Echter Beitritt: Owner mit Luanti-Client 5.17.0 als Spieler "AIO" (Konto `gw-aio-spieler`, per API eingeladen, Spielpasswort per `/api/players/password`). Servermeldung "*** AIO ist dem Spiel beigetreten." (Deutsch). Gegenprobe mit falschem Passwort: "Zugriff verweigert. Grund: Falsches Passwort".
- UDP 30000 musste zusätzlich in der AWS Security Group geöffnet werden (nur Owner-IP).
- AIO-Oberfläche: Port 8080 mit selbstsigniertem Zertifikat, `https://<domain>:8443` mit gültigem Let's-Encrypt-Zertifikat.
- Aufgeräumt (Owner bestätigt): Instanz terminiert, EIP freigegeben, Sicherheitsgruppe und Schlüsselpaar gelöscht, DNS-Eintrag gelöscht (NXDOMAIN), lokaler Schlüssel gelöscht; AWS Global View: Speicher 0, keine EIPs.

## Task 3: Doku-Änderungen (wörtlich, zur Owner-Prüfung)

Abgleich von Lauf A, B und AIO mit `docs/install.md` / `install.de.md`: Deploy-Daemon, HaRP-Daemon `harp_aio`, Netz `nextcloud-aio`, Proxy ohne Host-Port, Setup-Check und Spielerzugang liefen wie beschrieben. Einzige echte Abweichung: die Firewall des Cloud-Anbieters.

1. `docs/install.de.md`, Abschnitt 5 "UDP-Ports", neuer Punkt nach "Die Firewall des Servers muss den UDP-Bereich im LAN erlauben.":
   > - Läuft der Server bei einem Cloud-Anbieter, braucht auch dessen Firewall (zum Beispiel eine AWS Security Group) eine Regel für den UDP-Bereich, nur für bekannte Adressen.

   Grund: auf AWS reichte die Server-Firewall nicht, UDP 30000 kam erst nach der Security-Group-Regel an.
2. `docs/install.md`, Abschnitt 5 "UDP ports", gleicher Punkt:
   > - If the server runs at a cloud provider, its firewall (for example an AWS security group) also needs a rule for the UDP range, for known addresses only.
3. `docs/dev-setup.md` (Entwickler-Doku), Abschnitt "Phasenabnahme Phase 6 und der Store-Weg lokal (HaRP)", neuer Absatz vor "Laufzeit ohne Regression ...":
   > Mit `--source ghcr --tag <tag>` (zum Beispiel `--tag 1.0.0-rc.2`) installiert das Skript das veröffentlichte Image aus `ghcr.io/street1983nk/gameworld` statt eines lokalen Builds: kein Registry-Dienst, in der `info.xml`-Kopie ändert sich nur `image-tag`; die Abnahme prüft das Image dann mit `GAMEWORLD_EXPECT_IMAGE=ghcr.io/street1983nk/gameworld:<tag>`. Ein zweiter Stack, etwa mit Nextcloud 35, entsteht über `GAMEWORLD_COMPOSE_PROJECT`, `GAMEWORLD_HARP_PORT` und `GAMEWORLD_NC_IMAGE` (zum Beispiel `gameworld-nc35`, `8095`, `nextcloud:35.0.2-apache`); `--uninstall` mit denselben Variablen räumt ihn ab.
4. `scripts/dev/aio-vm-test.sh`, Ausgabezeile beim Beitritt (Dev-Skript), vorher "UDP ${PORT} in der VM-Firewall öffnen", jetzt:
   > UDP ${PORT} in der VM-Firewall und der Firewall des Anbieters (z. B. Security Group) nur für bekannte Adressen öffnen

Bewusst nicht übernommen: AIO-Port 8443 statt 8080 (Sache der AIO-Doku, unsere Anleitung beschreibt die AIO-Einrichtung nicht), Proxy per `docker run` statt Compose-Datei (beides gleichwertig, der Setup-Check zeigt beides).

Tests: `uv run pytest -q tests/test_docs.py` 43 bestanden; `tests/test_proxy_setup.py` 112 bestanden; `tests/test_orphans_script.py` 18 bestanden. Keine Gedankenstriche (U+2013/U+2014) in den geänderten Dateien.

## Deviations from Plan

1. **[Regel 3] rc.2 statt rc.1:** Plan nennt 1.0.0-rc.1; getestet wurde das aktuelle öffentliche 1.0.0-rc.2 (PR #1 release-prep-rc2).
2. **[Regel 3] HaRP-Teststack eigenständig:** harp.compose.yaml hängt nicht am Dev-Netz, sondern ist seit 06-12 eine eigene Test-Instanz; Variablen entsprechend (siehe Task-1-Notizen).
3. **[Regel 1, Harness] admin-Sprache de und Doku-Anker install.de.md#setup-check** in harp-install.sh bzw. acceptance-phase6.sh (Task 1).
4. **[Regel 3] acceptance-phase6.sh** geändert, nicht in `files_modified`.
5. **Lauf B voll statt Kurzlauf** (Obermenge).
6. **AIO auf NC 34.0.5 statt 35:** AIO v14.4.3 liefert Nextcloud 34; NC 35 ist über Lauf B belegt.
7. **[Regel 1] aio-vm-test.sh Beitrittshinweis** nennt die Anbieter-Firewall (Task 3, Dev-Skript, nicht in `files` von Task 3).
8. `uv run pytest -q -m "not docker"` passt nicht in das 170-s-Fenster eines Aufrufs; Python unverändert seit der Basis, gelaufen sind die Doku-, Proxy- und Orphans-Tests.

## Known Stubs

Keine.

## Self-Check: PASSED
