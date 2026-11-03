# 06-15 Task 1: Zwischenergebnisse (Checkpoint vor Task 2)

Stand 03.11.2026, 04:07 bis 04:55 UTC. Getestetes Image: `ghcr.io/street1983nk/gameworld:1.0.0-rc.2`
(Index-Digest `sha256:724cdfa07a9bb9125a1f929368613b43dbbf5164069e34535cd97582355854a7`, amd64 + arm64).

- Basis-Commit (`$TEMP/gw-base-06-15`): `6a0a075f82e72d4f1af35118d37d41879210ce85`
- Task-1-Commit: `e88daf8` feat(06-15): install tests from ghcr.io on NC 34 and NC 35, AIO test script
- `appinfo/info.xml` gegenüber der Basis unverändert (`git diff --quiet <basis> -- appinfo/info.xml` Exit 0); nur die Kopie `.dev/info-harp.xml` bzw. `.dev/info-aio-1.0.0-rc.2.xml` trägt image-tag 1.0.0-rc.2 (sonst identisch)

## Wichtig zur Ausgangslage

- Der Dev-Stack (gameworld-dev, NC 34 auf 8091) läuft mit `manual_install`, nicht mit HaRP. `harp-install.sh` arbeitet seit 06-12 auf einer **eigenen Test-Instanz** (harp.compose.yaml: eigene Nextcloud, eigener Proxy, eigenes Netz). Ein Umregistrieren der Dev-Instanz war deshalb nie nötig; Lauf A lief auf einem frischen HaRP-Stack mit NC 34.0.3.
- Ausgangszustand protokolliert und am Ende identisch wiederhergestellt: `gameworld (Gameworld): 1.0.0 [enabled]` auf `manual_install`, 4 laufende Welt-Container `gameworld-788fff30-*` (ff2295234c42, e032336f9b6d, ad44ba45e4b7, 7e6b1a1882ce running; 4 weitere stopped wie vorher), 10 Welt-Volumes 788fff30/a60510fd vorhanden, `/api/me` 200, ExApp-Heartbeat 10040 200.

## Freier Speicher (Docker-VM, `free -m`, total 5925 MB)

| Zeitpunkt (UTC) | used | free | available |
|---|---|---|---|
| 04:12 vor Lauf A (Install) | 1286 | 3797 | 4390 |
| 04:24 vor Lauf A2 | 1629 | 663 | 3966 |
| 04:28 vor Lauf A3 | 1617 | 530 | 3978 |
| 04:38 vor Lauf B, Dev-Stack gestoppt | 1224 | 2379 | 4514 |
| 04:42 vor Abnahme B | 1426 | 356 | 4258 |
| 04:52 Endzustand, Dev-Stack wieder an | 1207 | 1683 | 4508 |

Windows: 5,0 GB von 16,4 GB frei beim Start. Kein Speicherengpass, alle Läufe seriell.

## Lauf A: NC 34.0.3, frischer HaRP-Stack, Image aus ghcr.io

- `sh scripts/dev/harp-install.sh --source ghcr --tag 1.0.0-rc.2`: Exit 0 in 1:25 min. "ExApp gameworld deployed successfully", Image-Digest `ghcr.io/street1983nk/gameworld@sha256:724cdfa0...` (= veröffentlichter Index), Container `nc_app_gameworld` als 10001:10001.
- Abnahme `GAMEWORLD_DEPLOY=harp GAMEWORLD_SKIP_REGRESSION=1 GAMEWORLD_EXPECT_IMAGE=ghcr.io/street1983nk/gameworld:1.0.0-rc.2 sh scripts/dev/acceptance-phase6.sh`:
  - A1: 182 von 183, einziger Fehler K1 "Fremder6 abgewiesen mit 'nicht eingeladen'": Ablehnungstext kam englisch. Ursache Harness: Der admin einer frischen Instanz hat keine Spracheinstellung (Nextcloud-Standard en), die Welt wird von admin angelegt, Spieltexte folgen laut D-27 der Sprache des anlegenden Verwalters. Produkt korrekt. Fix: `harp-install.sh` setzt `admin core lang de` (wie der Dev-Stack, dort ist admin bereits de).
  - A2: K2 "Befund verweist auf den Doku-Anker install.md#setup-check" fehlgeschlagen: Mit deutschem admin verlinkt der Befund seit quick-261102-s2p (8040b50) korrekt `install.de.md#setup-check`. Harness-Erwartung war veraltet und hätte auch im Modus manual versagt. Fix: Erwartung `install.de.md#setup-check`. Lauf A2 danach per TERM abgebrochen (Skript während des Laufs geändert, Trap hat aufgeräumt, keine Reste).
  - **A3: 183 von 183 bestanden, Exit 0, "Phasenabnahme Phase 6 erfolgreich (Modus harp)"**. Je Kriterium bestanden: K1 15, K2 10, K3 25, K4 6, K5 19, K6 31, K7 20, K8 36. Nextcloud 34.0.3, Talk 24.0.6.
- Auszug K1 und K2 (A3):
  - `bestanden: K1 ExApp-Container nc_app_gameworld aus ghcr.io/street1983nk/gameworld:1.0.0-rc.2`
  - `bestanden: K1 ExApp-Container läuft als 10001:10001`, Healthcheck healthy, Netz gameworld-dev-harp_default ohne Docker-Socket
  - `Setup-Check ohne Proxy: ["proxy_dns"]`
  - `Setup-Check Proxy-Befehle: [{"id":"detected","network":"gameworld-dev-harp_default"}]`
  - `bestanden: K2 Setup-Check erkennt das Netz gameworld-dev-harp_default (proxy_commands[0] detected)`
  - `bestanden: K2 docker-run-Befehl und Compose-Datei nennen gameworld-dev-harp_default (external)`
- Logs: `.dev/acceptance-phase6-0615-A1.log`, `-A2.log`, `-A3.log`, `.dev/harp-install-0615-A.log`.
- Danach `harp-install.sh --uninstall`: Stack samt Volumes weg, keine Welt-Reste.

## Lauf B: NC 35.0.2, frischer HaRP-Stack, Image aus ghcr.io

- Aktuellstes 35er-Apache-Tag laut Docker Hub am 03.11.2026: `35.0.2-apache` (35.0.0, 35.0.1, 35.0.2). Gepinnt: **`nextcloud:35.0.2-apache`**, Digest `nextcloud@sha256:e0b1a2af52c82c07b7a0e8e59878bd8769e704447734d5d238a836982f51b9c8`.
- Dev-Stack vorher gestoppt (`docker compose -p gameworld-dev stop`); die vier laufenden Dev-Welt-Container (nicht Teil des Compose-Projekts) liefen weiter.
- `GAMEWORLD_COMPOSE_PROJECT=gameworld-nc35 GAMEWORLD_HARP_PORT=8095 GAMEWORLD_NC_IMAGE=nextcloud:35.0.2-apache sh scripts/dev/harp-install.sh --source ghcr --tag 1.0.0-rc.2`: Exit 0, gleicher Image-Digest, 10001:10001. AppAPI auf NC 35 per `app:enable app_api` aktiviert (im Skript).
- Statt des geplanten Kurzlaufs (K1, K2, K5, K6) lief die **volle Abnahme** (Obermenge), da das Skript keinen Teilauswahl-Schalter hat: **183 von 183 bestanden, Exit 0**. Je Kriterium: K1 15, K2 10, K3 25, K4 6, K5 19, K6 31, K7 20, K8 36. Nextcloud 35.0.2, Talk 25.0.6.
- Netzerkennung: `Setup-Check Proxy-Befehle: [{"id":"detected","network":"gameworld-nc35_default"}]`, beide K2-Netzprüfungen bestanden. Angezeigter Befehl (Beleg `.dev/setup-check-no-proxy-0615-B.json`): `docker run -d --name gameworld-docker-proxy --restart unless-stopped --network gameworld-nc35_default -v /var/run/docker.sock:/var/run/docker.sock:ro -e CONTAINERS=1 ... -e AUTH=0 tecnativa/docker-socket-proxy:v0.5.0@sha256:1f50...`, kein Host-Port; Compose-Datei mit `networks: gameworld-nc35_default: external: true`. Passt zum tatsächlichen Netz.
- Danach `--uninstall` mit denselben Variablen: `docker compose -p gameworld-nc35 ps -q` leer, Netz und Volumes entfernt. Dev-Stack wieder gestartet und gesund (siehe Ausgangslage).

## Netzerkennung mit echtem HaRP (Auftrag Orchestrator)

- Erster Test mit echtem HaRP: In beiden Läufen hat der Setup-Check das Netz **selbst erkannt** (id `detected`, keine Ersatzbefehle), jeweils das richtige Compose-Netz des Stacks (`gameworld-dev-harp_default`, `gameworld-nc35_default`). docker-run-Zeile und Compose-Datei nennen genau dieses Netz.
- Auf AIO noch offen (Task 2): `aio-vm-test.sh` prüft dort, dass `detected nextcloud-aio` kommt.

## Geänderte Dateien (Commit e88daf8)

- `scripts/dev/compose.yaml`: `image: ${GAMEWORLD_NC_IMAGE:-nextcloud:34.0.3-apache}`.
- `scripts/dev/harp.compose.yaml`: Projektname und Containerpräfix `${GAMEWORLD_COMPOSE_PROJECT:-gameworld-dev-harp}`, Netzname `${GAMEWORLD_DEV_NETWORK:-gameworld-dev-harp_default}`, NC-Image `${GAMEWORLD_NC_IMAGE}`, Front-Port `${GAMEWORLD_HARP_PORT:-8093}`. Standardwerte wie 06-12 (Container gameworld-dev-harp-nc und -docker-proxy unverändert; HaRP, Registry, Front heißen jetzt `<projekt>-appapi-harp`, `-registry`, `-front`).
- `scripts/dev/harp-install.sh`: `--source local|ghcr`, `--tag <tag>` (striktes Tag-Format), ghcr: `docker manifest inspect` vorab, info.xml-Kopie behält Registry ghcr.io und Image, nur image-tag wird gesetzt, Registry-Dienst wird nicht gestartet; nach der Installation Prüfung der Image-Referenz und Ausgabe des Digests; admin der Test-Instanz auf de.
- `scripts/dev/acceptance-phase6.sh` (nicht in `files_modified` des Plans, Regel 3): harp-Modus nutzt dieselben Variablen, `GAMEWORLD_EXPECT_IMAGE`, zwei neue K2-Prüfungen zur Netzerkennung, Belegkopie der Setup-Check-Antwort, Doku-Anker `install.de.md#setup-check`.
- `scripts/dev/aio-vm-test.sh` (neu, 330 Zeilen, POSIX sh, `sh -n` und shellcheck ohne Befund).

## Abweichungen vom Plan

1. **[Regel 3] Planannahme falsch:** Der Plan beschreibt harp.compose.yaml als Anhang an das Dev-Netz (`${GAMEWORLD_DEV_NETWORK:-gameworld-dev_default}`) und Lauf B als Dev-Stack-Kopie mit `GAMEWORLD_NC_PORT=8095`. Tatsächlich ist der HaRP-Stack seit 06-12 eine eigenständige Test-Instanz. Umgesetzt: `GAMEWORLD_DEV_NETWORK` benennt das Netz dieses Stacks (Standard `<projekt>_default`), Port über das bestehende `GAMEWORLD_HARP_PORT` (die Abnahme nutzt `GAMEWORLD_NC_PORT` bereits für den Dev-Stack im Modus manual).
2. **[Regel 1, Harness] admin-Sprache** auf frischer Test-Instanz, siehe A1.
3. **[Regel 1, Harness] veralteter Doku-Anker** in K2, siehe A2.
4. **[Regel 3] acceptance-phase6.sh** angepasst (Image aus ghcr statt localhost:5000, parametrisierte Namen).
5. **Lauf B voll statt Kurzlauf** (stärkerer Beleg).
6. **Lange Läufe:** Die Bash-Werkzeugaufrufe werden nach 180 s automatisch in den Hintergrund verschoben. Die Abnahmen liefen deshalb per `nohup ... &` und wurden im Vordergrund in Abschnitten von höchstens 170 s abgefragt (keine run_in_background-Warteschleife). Die zwei ersten Warteaufrufe (Lauf A1) hat das Werkzeug selbst in den Hintergrund verschoben, beide liefen sauber durch.
7. `uv run pytest -q -m "not docker"` passt nicht in das 170-s-Fenster und wurde abgebrochen; Python ist unverändert. Gelaufen: `tests/test_proxy_setup.py` und `tests/test_docs.py`, 155 bestanden.

## aio-vm-test.sh (für Task 2)

- Aufruf auf der VM als root: `sh aio-vm-test.sh --info-xml ./info-aio-1.0.0-rc.2.xml [--tag 1.0.0-rc.2] [--url https://<domain>]`; Aufräumen: `sh aio-vm-test.sh --cleanup`.
- Mitnehmen auf die VM: `scripts/dev/aio-vm-test.sh` und `.dev/info-aio-1.0.0-rc.2.xml` (gitignored, sonst per `harp-install.sh --source ghcr --tag 1.0.0-rc.2` neu erzeugen oder aus info.xml mit image-tag 1.0.0-rc.2).
- occ: `docker exec --user www-data nextcloud-aio-nextcloud php occ ...` (so ruft die AIO-Doku occ auf; kein `sudo -u www-data` im Container nötig).
- Ablauf: AIO-Container, Netz nextcloud-aio und Daemon harp_aio prüfen; Gameworld per `app_api:app:register gameworld harp_aio --info-xml ... --env GAMEWORLD_DOCKER_URL=tcp://gameworld-docker-proxy:2375 --wait-finish` **vor** dem Proxy registrieren (Zustand einer frischen Store-Installation); Image-Referenz, Digest, 10001:10001, Netz nextcloud-aio, kein Docker-Socket, HP_SHARED_KEY nur ja/nein (F-06); Testkonto `gw-aio-test` in admin, Zufallspasswort per stdin an occ und nur in einer 0600-netrc unter `/root/.gameworld-aio-test`; Setup-Check ohne Proxy (erwartet Proxy-Befund und `detected nextcloud-aio`, Befehl ohne `-p`); Proxy per `docker run` im Netz nextcloud-aio ohne Host-Port; Setup-Check ohne Fehler; Welt anlegen, running, UDP-Port per `docker port` und `ss -uln`; Zusammenfassung ohne Passwörter.
- `--cleanup`: Welt per API und Docker-Reste nach Label, Testkonto, App (`--rm-data`), Proxy, Zustandsordner.
- **Nicht lokal ausgeführt** (kein AIO verfügbar): nur Syntax und shellcheck geprüft. Auf der VM erst gegen echtes AIO belegt.

## Offen für Task 2 und 3

- Task 2 (Checkpoint): VM, Domain, AIO mit HaRP durch den Owner, gemeinsam per Playwright.
- Task 3: Doku-Befunde. Aus Task 1 bisher keine Abweichung der Nutzer-Anleitung gefunden (install.md/install.de.md nicht geändert). Hinweis für docs/dev-setup.md (Entwickler-Doku): neue Optionen `--source ghcr --tag` und Variablen könnten dort ergänzt werden.
