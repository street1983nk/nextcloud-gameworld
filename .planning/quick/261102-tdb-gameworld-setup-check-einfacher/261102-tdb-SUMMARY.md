---
phase: quick-261102-tdb
plan: 01
subsystem: setup-check
tags: [setup-check, docker-proxy, network-detection, firewall, i18n, polling]
requires: []
provides:
  - "network_probe.detect_docker_network: PTR lookup of the own IPv4 at Docker DNS 127.0.0.11"
  - "proxy_setup: compose_file, commands_wanted, firewall_commands, NETWORK_PLACEHOLDER, LAN_PLACEHOLDER"
  - "GET /api/setup-check: proxy_commands[].compose, firewall {port_range, commands}"
  - "SetupCheck.vue: detected/fallback commands, Compose download, firewall details, self re-check"
affects: [docs/install.md, docs/install.de.md]
tech-stack:
  added: []
  patterns: ["stdlib-only DNS PTR query/parser", "setTimeout chain polling with tab/unmount stop"]
key-files:
  created:
    - src/gameworld/provisioner/network_probe.py
    - tests/test_network_probe.py
    - frontend/tests/setupcheck.check.mjs
  modified:
    - src/gameworld/provisioner/proxy_setup.py
    - src/gameworld/api/setup_check.py
    - tests/test_proxy_setup.py
    - tests/test_roles.py
    - frontend/src/components/SetupCheck.vue
    - frontend/src/i18n/de/admin.js
    - frontend/src/i18n/en/admin.js
    - frontend/src/i18n/fr/admin.js
    - docs/install.md
    - docs/install.de.md
decisions:
  - "Docker network via PTR query of the own IPv4 at 127.0.0.11 (no rights, no socket); exactly one network or fallback"
  - "Reserved networks host/bridge/none rejected for commands (host would expose the proxy on the host)"
  - "YAML-ambiguous network names (1234, true, yes, ...) are double-quoted in the Compose file"
  - "Access unchanged: require_verwalter (managers incl. admin), children 403"
metrics:
  completed: 2026-11-02
  tasks: 3
---

# Quick 261102-tdb: Gameworld Setup-Check einfacher Summary

Der Setup-Check ermittelt das echte Docker-Netz von `nc_app_gameworld` per PTR-Abfrage (nur stdlib) beim eingebetteten Docker-DNS und zeigt genau einen Proxy-Befehl plus inhaltsgleichen Compose-Download (Fallback: gameworld, nextcloud-aio, `<docker-network>`). Er prüft sich selbst erneut, bis er grün ist (15 s, nach 20 Läufen 60 s), und bietet LAN-only-Befehle für ufw/firewalld für `GAMEWORLD_PORT_RANGE`.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 RED | Tests: Netzerkennung, netzabhängige Befehle, Compose, Firewall, KID 403 | 95bb7b2 |
| 1 GREEN | Backend: network_probe.py, proxy_setup.py, api/setup_check.py | 9f3607f |
| 2 | Frontend: SetupCheck.vue, i18n DE/EN/FR, setupcheck.check.mjs | ab6d03f |
| 3 | Doku Abschnitt 7 (EN + DE) | 621c9ac |
| Fix | Handler-Name ohne "visibility" (Datenschutz-Test ZUGANG-01) | 263126d |

Alle Commits mit Autor street1983nk <k.cherif@outlook.de>, ohne Claude- oder Co-Author-Zeilen, nicht gepusht. SUMMARY, STATE und PLAN nicht committet; ROADMAP und .planning/config.json nicht angefasst.

## Umsetzung

- **Punkt 2, Netz:** `network_probe.py` (nur stdlib: ipaddress, re, secrets, socket, struct). Setzt `nameserver 127.0.0.11` in /etc/resolv.conf voraus und schickt pro eigener privater IPv4 eine UDP-PTR-Abfrage an 127.0.0.11:53 (zufällige 16-Bit-ID, 1 s Timeout, Empfangspuffer 512 Byte). Angenommen werden nur Datagramme von 127.0.0.11:53. Der Parser ist strikt: ID, QR=1, RCODE=0, rdlength innerhalb des Pakets, der Name füllt rdata exakt, Zeiger nur rückwärts und höchstens 16 Sprünge, Labels <= 63, Name <= 255, nur druckbares ASCII ohne Punkt im Label. Danach Präfix `nc_app_gameworld.` und `NETWORK_RE = ^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$`. Ergebnis: genau ein Netz oder None, die Funktion wirft nie.
- `proxy_setup.py`: `NETWORK_PLACEHOLDER = "<docker-network>"`, `LAN_PLACEHOLDER = "<lan-network>"`, `_valid_network` (dokumentierte Netze, Platzhalter oder NETWORK_RE, nie host/bridge/none), `compose_file`, `commands_wanted`, `proxy_commands(failed, url, detected)` (erkannt: ein Eintrag `detected`, sonst `compose`, `aio`, `other`) und `firewall_commands((low, high))`.
- API: `proxy_commands[]` jetzt mit `compose`, neu ist `firewall {port_range, commands}`. Das Feld kommt auch bei ok und ist bei einem Konfigurationsfehler null. Die Netzerkennung läuft nur, wenn `commands_wanted` gilt (über `anyio.to_thread.run_sync`). Die Router-Abhängigkeit `require_verwalter` ist unverändert.
- **Punkt 3:** setTimeout-Kette: 15 s für 20 automatische Läufe, danach 60 s. Sie stoppt bei grün, bei verborgenem Tab (wieder sichtbar: sofortige Prüfung) und beim Verlassen. Ein `stopped`-Flag verhindert, dass eine laufende Anfrage den Timer neu setzt. Der `checking`-Guard verhindert Überlappung, "Erneut prüfen" setzt den Zähler zurück. `checked` wird bei Erst- und Handläufen ausgelöst, bei automatischen Läufen nur, wenn sich der ok-Zustand ändert.
- **Punkt 4:** `<details>`-Abschnitt mit den Befehlen für ufw und firewalld und Kopier-Knöpfen. Er ist auch bei grünem Check sichtbar.

## Exakte Befehle und Dateien (im Backend gebaut)

Proxy-Befehl (Beispiel nextcloud-aio):

```
docker run -d --name gameworld-docker-proxy --restart unless-stopped --network nextcloud-aio -v /var/run/docker.sock:/var/run/docker.sock:ro -e CONTAINERS=1 -e IMAGES=1 -e POST=1 -e VOLUMES=1 -e EXEC=0 -e INFO=0 -e NETWORKS=0 -e BUILD=0 -e SYSTEM=0 -e SECRETS=0 -e SWARM=0 -e NODES=0 -e SERVICES=0 -e TASKS=0 -e PLUGINS=0 -e CONFIGS=0 -e DISTRIBUTION=0 -e AUTH=0 tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
```

Compose-Datei (Download-Name `gameworld-docker-proxy.yaml`, Beispiel nextcloud-aio):

```yaml
services:
  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
    restart: unless-stopped
    environment:
      CONTAINERS: 1
      IMAGES: 1
      POST: 1
      VOLUMES: 1
      EXEC: 0
      INFO: 0
      NETWORKS: 0
      BUILD: 0
      SYSTEM: 0
      SECRETS: 0
      SWARM: 0
      NODES: 0
      SERVICES: 0
      TASKS: 0
      PLUGINS: 0
      CONFIGS: 0
      DISTRIBUTION: 0
      AUTH: 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - nextcloud-aio
networks:
  nextcloud-aio:
    external: true
```

Firewall (Standardbereich 30000-30019; ein einzelner Port ergibt `port 30000` bzw. `port="30000"`):

```
sudo ufw allow proto udp from <lan-network> to any port 30000:30019
sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<lan-network>" port port="30000-30019" protocol="udp" accept' && sudo firewall-cmd --reload
```

## Neue nutzersichtbare Texte (wörtlich)

### DE (frontend/src/i18n/de/admin.js)

- `admin.setup.commandDetected`: Netz {network} (aus der laufenden Gameworld ermittelt)
- `admin.setup.commandOther`: Anderes Netz: ersetze <docker-network> durch den Netznamen deines Deploy-Daemons
- `admin.setup.networkNotDetected`: Das Docker-Netz von Gameworld ließ sich nicht automatisch ermitteln. Nimm den Befehl für deine Installation. Läuft dein Deploy-Daemon in einem anderen Netz, nimm den letzten Befehl und ersetze den Platzhalter <docker-network>.
- `admin.setup.downloadCompose`: Compose-Datei herunterladen
- `admin.setup.composeHint`: Statt des Befehls geht auch die Compose-Datei: speichern und auf dem Server mit docker compose -f gameworld-docker-proxy.yaml up -d starten. Sie enthält dieselben Einstellungen, ohne Host-Port.
- `admin.setup.autoRecheck`: Gameworld prüft von selbst regelmäßig erneut und wird grün, sobald der Docker-Proxy antwortet.
- `admin.setup.firewallHeading`: Firewall: UDP-Ports {range} nur im Heimnetz freigeben
- `admin.setup.firewallHint`: Führe auf dem Server den Befehl für deine Firewall aus und ersetze vorher <lan-network> durch dein Heimnetz in der Form Netzadresse/Präfixlänge, wie es dein Router anzeigt. Keine Portweiterleitung im Router und kein UPnP: Welten sind nur fürs Heimnetz gedacht.
- `admin.setup.firewallUfw`: ufw (zum Beispiel Ubuntu, Debian)
- `admin.setup.firewallFirewalld`: firewalld (zum Beispiel Fedora, RHEL, openSUSE)

### EN (frontend/src/i18n/en/admin.js)

- `admin.setup.commandDetected`: Network {network} (detected from the running Gameworld)
- `admin.setup.commandOther`: Other network: replace <docker-network> with the network name of your deploy daemon
- `admin.setup.networkNotDetected`: The Docker network of Gameworld could not be detected automatically. Use the command for your installation. If your deploy daemon runs in another network, use the last command and replace the placeholder <docker-network>.
- `admin.setup.downloadCompose`: Download Compose file
- `admin.setup.composeHint`: Instead of the command you can also use the Compose file: save it and start it on the server with docker compose -f gameworld-docker-proxy.yaml up -d. It contains the same settings, without a host port.
- `admin.setup.autoRecheck`: Gameworld checks again on its own at regular intervals and turns green as soon as the Docker proxy answers.
- `admin.setup.firewallHeading`: Firewall: open UDP ports {range} in the home network only
- `admin.setup.firewallHint`: Run the command for your firewall on the server and first replace <lan-network> with your home network in the form network address/prefix length, as your router shows it. No port forwarding in the router and no UPnP: worlds are meant for the home network only.
- `admin.setup.firewallUfw`: ufw (for example Ubuntu, Debian)
- `admin.setup.firewallFirewalld`: firewalld (for example Fedora, RHEL, openSUSE)

### FR (frontend/src/i18n/fr/admin.js; " " = geschütztes Leerzeichen vor dem Doppelpunkt)

- `admin.setup.commandDetected`: Réseau {network} (détecté à partir de Gameworld en cours d’exécution)
- `admin.setup.commandOther`: Autre réseau : remplace <docker-network> par le nom du réseau de ton démon de déploiement
- `admin.setup.networkNotDetected`: Le réseau Docker de Gameworld n’a pas pu être détecté automatiquement. Prends la commande qui correspond à ton installation. Si ton démon de déploiement tourne dans un autre réseau, prends la dernière commande et remplace l’espace réservé <docker-network>.
- `admin.setup.downloadCompose`: Télécharger le fichier Compose
- `admin.setup.composeHint`: Au lieu de la commande, tu peux aussi utiliser le fichier Compose : enregistre-le et démarre-le sur le serveur avec docker compose -f gameworld-docker-proxy.yaml up -d. Il contient les mêmes réglages, sans port sur l’hôte.
- `admin.setup.autoRecheck`: Gameworld vérifie à nouveau de lui-même à intervalles réguliers et passe au vert dès que le proxy Docker répond.
- `admin.setup.firewallHeading`: Pare-feu : ouvrir les ports UDP {range} uniquement dans le réseau domestique
- `admin.setup.firewallHint`: Exécute sur le serveur la commande de ton pare-feu et remplace d’abord <lan-network> par ton réseau domestique sous la forme adresse réseau/longueur de préfixe, comme l’affiche ton routeur. Pas de redirection de port dans le routeur et pas d’UPnP : les mondes sont prévus uniquement pour le réseau domestique.
- `admin.setup.firewallUfw`: ufw (par exemple Ubuntu, Debian)
- `admin.setup.firewallFirewalld`: firewalld (par exemple Fedora, RHEL, openSUSE)

### Geänderte bestehende Texte

- `admin.setup.commandsHint` (DE/EN/FR): **unverändert**. Er spricht von "den passenden Befehl" bzw. "the matching command" und hat nie behauptet, dass immer beide Netze erscheinen. Eine Änderung war deshalb nicht nötig (Plan: "nur soweit nötig").

### Doku Abschnitt 7, EN (docs/install.md; ersetzt den Absatz "If the proxy is missing ...")

If the proxy is missing or unreachable (`proxy_dns`, `proxy_refused`, `proxy_timeout`) and `GAMEWORLD_DOCKER_URL` is the default address, the Gameworld page additionally shows a ready-to-copy `docker run` command with a copy button. Gameworld determines its Docker network itself: it asks Docker's internal name service about its own container `nc_app_gameworld`, without extra rights. It then shows one command for exactly this network. If that fails, it shows the commands for your own Compose file (`gameworld`) and AIO (`nextcloud-aio`) plus one with the placeholder `<docker-network>`, which you replace with the network of your deploy daemon. Every command can also be downloaded as Compose file `gameworld-docker-proxy.yaml` (start it with `docker compose -f gameworld-docker-proxy.yaml up -d`). Command and file create the container `gameworld-docker-proxy` with the same settings as section 3a and 3b and no host port.

While something is missing, the Gameworld page checks again by itself every 15 seconds (later every minute) and turns green without a reload. It stops as soon as everything is green or you leave the page.

The page also shows firewall commands for ufw and firewalld that open the configured `GAMEWORLD_PORT_RANGE` (UDP) for the home network only. Replace `<lan-network>` with your home network in the form network address/prefix length, as your router shows it. No port forwarding in the router and no UPnP (section 5).

### Doku Abschnitt 7, DE (docs/install.de.md; ersetzt den Absatz "Fehlt der Proxy ...")

Fehlt der Proxy oder ist er nicht erreichbar (`proxy_dns`, `proxy_refused`, `proxy_timeout`) und steht `GAMEWORLD_DOCKER_URL` auf der Standardadresse, zeigt die Gameworld-Seite zusätzlich einen fertigen `docker run`-Befehl mit Kopier-Knopf. Gameworld ermittelt sein Docker-Netz selbst: Es fragt den internen Namensdienst von Docker nach dem eigenen Container `nc_app_gameworld`, ohne zusätzliche Rechte. Dann zeigt es einen Befehl für genau dieses Netz. Klappt das nicht, zeigt es die Befehle für das eigene Compose (`gameworld`) und AIO (`nextcloud-aio`) und einen mit dem Platzhalter `<docker-network>`, den du durch das Netz deines Deploy-Daemons ersetzt. Jeden Befehl gibt es auch als Compose-Datei `gameworld-docker-proxy.yaml` zum Herunterladen (Start mit `docker compose -f gameworld-docker-proxy.yaml up -d`). Befehl und Datei legen den Container `gameworld-docker-proxy` mit denselben Einstellungen wie in Abschnitt 3a und 3b an, ohne Host-Port.

Solange etwas fehlt, prüft die Gameworld-Seite von selbst alle 15 Sekunden erneut (später jede Minute) und wird ohne Neuladen grün. Sie hört auf, sobald alles grün ist oder du die Seite verlässt.

Außerdem zeigt die Seite Firewall-Befehle für ufw und firewalld, die den eingestellten `GAMEWORLD_PORT_RANGE` (UDP) nur fürs Heimnetz freigeben. Ersetze `<lan-network>` durch dein Heimnetz in der Form Netzadresse/Präfixlänge, wie es dein Router anzeigt. Keine Portweiterleitung im Router und kein UPnP (Abschnitt 5).

Doku FR: Im Repo gibt es keine französische Installationsanleitung; das ist unverändert so.

## Zugriffsentscheidung

Unverändert gilt `require_verwalter` (Verwalter einschließlich Admin). Der Check war nie admin-only, Verwalter ohne NC-Admin sehen die Befehle also weiter wie bisher. Kinder bekommen 403, `run_setup_check` und `detect_docker_network` werden für sie nie aufgerufen. tests/test_roles.py prüft das und zusätzlich, dass der 403-Body keines dieser Wörter enthält: "docker run", "docker-socket-proxy", "ufw", "firewall-cmd", "compose". Die Befehle werden nur angezeigt, nie ausgeführt.

## Tests

- tests/test_network_probe.py (73 Fälle), Pflicht-Negativtests des Orchestrators alle enthalten, jeweils mit None und ohne Ausnahme:
  - abgeschnittene Pakete in jeder Länge 0..len-1 (plain und komprimiert)
  - falsche ID, QR=0, RCODE 1/2/3/5/15, ANCOUNT 0
  - Zeiger auf sich selbst, Zyklus über zwei Zeiger, Rückwärtszyklus
  - Zeiger hinter das Paketende
  - Label > 63 (0x40 und reservierter Typ 0x80), Name > 255
  - Nicht-ASCII-, Steuer-, Leer- und Punkt-Bytes im Label
  - Antwort vom falschen Absender (10.0.0.1:53, 127.0.0.11:5353, 127.0.0.1:53)
  - Zufallstest mit festem Seed 261102: 2000 zufällige Pakete plus 2000 mutierte gültige Pakete, nie eine Ausnahme
  - außerdem: resolv.conf-Gate (es wird nichts gesendet), Präfix-Mismatch, Injection-Netznamen, zwei IPs mit zwei Netzen ergibt None, Socket-Fehler, nur-stdlib-Importprüfung
- Positivkontrollen per Mutation:
  - ohne Absenderprüfung schlagen 3 Tests fehl
  - ohne RCODE-Prüfung schlagen 5 Tests fehl
  - ohne `clearTimeout(copiedTimer)` bzw. mit `checked` bei jedem Lauf schlägt setupcheck.check.mjs fehl
  - alles danach zurückgesetzt
- tests/test_proxy_setup.py:
  - angenommene und abgelehnte Netze (`$(id)`, `` `id` ``, `a b`, `""`, `-x`, `--privileged`, Zeilenumbruch, 129 Zeichen, `<other>`, host, bridge, none)
  - Compose-Drift über den bestehenden Doku-Drift-Helfer: keine Drift; Positivkontrolle mit EXEC: 1
  - exakte Compose-Form, YAML-mehrdeutige Namen werden gequotet
  - Fallback, erkanntes und ungültiges erkanntes Netz
  - Firewall für Bereich, Einzelport und ungültige Bereiche
  - API-Felder mit Spion auf die Netzerkennung: nur bei Trigger-Befund und Standardadresse, nicht bei Konfigurationsfehler

## Live-Prüfungen (Dev-Stack)

**a) Echter Docker-DNS** (Wegwerf-Container `python:3.13-slim-trixie`, Modul read-only gemountet, `python -I`):
- `--name nc_app_gameworld --network gameworld-dev_default` ergibt `gameworld-dev_default` (eigene IP 172.21.0.4)
- Negativkontrolle ohne `--name` ergibt `None`
- Negativkontrolle `--network bridge` (kein eingebetteter DNS) ergibt `None`
- Zusätzlich lehnt `docker compose config --quiet` die heruntergeladenen Compose-Dateien (nextcloud-aio, gameworld) nicht ab: beide gültig.

**b) Selbstprüfung** (Playwright headless, Admin, DE; Proxy-Neustart im finally):
- Proxy gestoppt: Fehlerkarte und autoRecheck-Zeile werden angezeigt
- nach 3 s wieder gestartet: ohne Neuladen nach 15 s grün (1 automatische Abfrage); "Welt erstellen" ist aktiv, wenn ein Name eingetragen ist (nicht geklickt, keine Welt angelegt)
- `docker ps`: Proxy "Up"
- grüne Seite: 0 Abfragen in 40 s
- neu geladene grüne Seite: 1 Abfrage in 40 s (nur die erste)
- rote Seite (gemockt): 3 Abfragen in ~32 s (Start, 15 s, 30 s)
- verborgener Tab: 0 Abfragen in 40 s; wieder sichtbar: sofort 1 Abfrage
- Wechsel in die Files-App: 0 Abfragen in 40 s

**c) UI-Varianten** (page.route mit Strings aus dem Backend, gebaut in Python über proxy_commands/firewall_commands/run_setup_check), DE/EN/FR je bei 1280 und 390 px, je Variante "erkannt" und "Fallback". Alle 12 Läufe ok:
- Labels richtig; networkNotDetected erscheint nur im Fallback
- Befehle und Hinweise sichtbar
- der Compose-Download ist identisch mit dem Feld `compose` (Dateiname gameworld-docker-proxy.yaml)
- Firewall-Überschrift mit dem echten Bereich; aufgeklappt sind beide Befehle, der Hinweis und die Labels zu sehen
- kein horizontales Scrollen
- Screenshots: .dev/audit/261102-tdb/c-*.png, b-proxy-down-de.png, d-kid.png

**d) Kind** (mia):
- GET /api/setup-check über den AppAPI-Proxy gibt 403 ("Seuls les parents peuvent gérer les mondes."), ohne Befehlswörter im Body
- kein SetupCheck- und kein Firewall-Abschnitt auf der Seite
- Admin-Sprache danach wieder auf `de` gesetzt

## Gates

- ruff check: grün
- ruff format --check: grün
- pyright basic (PYRIGHT_PYTHON_FORCE_VERSION=latest): 0 Fehler
- vulture: grün
- npm run build: grün
- setupcheck.check.mjs und i18n.check: grün
- scripts/audit/selftest.mjs: PASSED
- dump_catalog.py: ok
- pytest -m "not docker" (voller Lauf): 3201 passed, 1 failed. Der Fehlschlag war `test_frontend_privacy[visibility]`: Der Funktionsname `onVisibilityChange` enthielt das gesperrte Wort. Behoben mit 263126d (Umbenennung in `onTabChange` wie in ParentView/PlayerView). Danach liefen die betroffenen Suiten (privacy, frontend_checks, frontend_i18n, i18n: 132 passed) und Build/Selftest grün. Den vollen 7-Minuten-Lauf habe ich nach dieser reinen Umbenennung nicht wiederholt.
- Umlaut-, Dash- und Emoji-Audit über den gesamten Diff: keine U+2013/U+2014, keine Emojis, keine ASCII-Ersatzumlaute in deutscher Prosa.

## Deviations from Plan

1. **[Rule 2 - Security] Reservierte Netze host/bridge/none abgelehnt.** Die Regex des Plans hätte `host` akzeptiert, und ein Proxy im Host-Netz lauscht auf dem Host (root-äquivalente Docker-API). Die Erkennung kann diese Netze nie liefern, `_valid_network` lehnt sie trotzdem ausdrücklich ab. (9f3607f)
2. **[Rule 1 - Bug] YAML-mehrdeutige Netznamen werden im Compose gequotet** (`1234`, `true`, `yes`, `on`, `null` ...), sonst würden sie zu Zahl oder Bool. (9f3607f)
3. **Strengerer Parser als im Plan:** Kompressionszeiger müssen vor den Beginn des aktuellen Label-Laufs zeigen, damit sind Schleifen strukturell ausgeschlossen (das Hop-Limit 16 bleibt als zweite Sperre). Der Name muss exakt am rdata-Ende enden, Punkte im Label werden abgelehnt.
4. **[Rule 1 - Bug] Handler-Name `onVisibilityChange` verletzte den Datenschutz-Test ZUGANG-01** und wurde in `onTabChange` umbenannt. (263126d)
5. setupcheck.check.mjs normalisiert CRLF, weil der Arbeitsbaum mit core.autocrlf CRLF haben kann.
6. Der Kopierfehler-Hinweis erscheint jetzt im Abschnitt des betroffenen Befehls (Schlüssel-Präfix `proxy-` bzw. `fw-`).
7. Das Werkzeug hat zwei lange Vordergrundläufe (Live-Lauf b, voller pytest) nach 180 s selbst in den Hintergrund verschoben. Ich habe mit einer begrenzten Dateiprüfung gewartet und keine eigenen Hintergrund-Warteschleifen gestartet.
8. In tests/conftest.py habe ich nichts geändert: Die übrigen API-Tests nutzen eine Nicht-Standardadresse und lösen die Netzerkennung deshalb nicht aus.

## Nicht erreicht / ehrliche Hinweise

- Keine echte AIO-/HaRP-Installation verfügbar. Die Positivkontrolle lief mit einem Wegwerf-Container namens `nc_app_gameworld` im Dev-Netz, nicht mit einem von AppAPI deployten Container. Die Dev-ExApp läuft als manual-install auf dem Host und zeigt weiter keine Befehle (so gewollt).
- Platzhalter `<docker-network>` in der Compose-Datei: `docker compose config` akzeptiert ihn (externe Netze prüft es nicht). `up` würde scheitern, weil das Netz fehlt. Das habe ich bewusst nicht live ausgeführt. Im `docker run`-Befehl führt das `<` in bash zu einem Umleitungsfehler und in PowerShell zu einem Parse-Fehler, bevor Docker startet.

## Threat Flags

Keine über das Bedrohungsmodell hinaus. Die einzige neue Netzaktivität ist eine UDP-Abfrage an 127.0.0.11:53 im Fehlerpfad, abgedeckt durch T-tdb-01 und T-tdb-04.

## Self-Check: PASSED

Dateien vorhanden: network_probe.py, test_network_probe.py, setupcheck.check.mjs. Commits 95bb7b2, 9f3607f, ab6d03f, 621c9ac und 263126d sind im Log.
