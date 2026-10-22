# HaRP-Kompatibilität für Gameworld (Grundlage Phase 6)

Stand: 22.10.2026. Recherche nur lesend (Code von HaRP main, app_api main/stable34/stable35, AIO main, nc_py_api 0.30.3 im venv, Connector-Repo des Owners). Keine Container gestartet.

Vertrauensgrade: HIGH = im Quellcode oder offizieller Doku gelesen, MEDIUM = aus Code abgeleitet oder Erfahrung aus dem Connector, LOW = Schätzung.

## Kurzfassung

- Gameworld braucht für HaRP nur Image-Arbeit, keinen App-Code-Umbau: nc_py_api 0.30.3 lauscht bei gesetztem `HP_SHARED_KEY` schon auf dem Unix-Socket `/tmp/exapp.sock` (HIGH).
- Es gibt noch kein Dockerfile im Repo. Das ist der eigentliche Hauptposten.
- Der Docker-Zugang für die Welten bleibt der eigene socket-proxy. HaRPs Docker-Engine-Proxy ist für ExApps gesperrt und kein API-Vertrag (HIGH).
- UDP ist unabhängig von HaRP: Die Welt-Container veröffentlichen ihre Ports direkt am Docker-Host, FRP trägt nur das HTTP der ExApp (HIGH).
- Hauptrisiko ist das Docker-Netz: Der socket-proxy muss im selben benutzerdefinierten Netz hängen wie die ExApp (`--net` des Daemons). Auf `bridge` gibt es keine Namensauflösung, auf `host` müsste der Proxy auf Loopback veröffentlicht werden (MEDIUM bis HIGH).
- Talk-Bot und Frontend-Proxy laufen unter HaRP über AppAPI-signierte Anfragen; HaRP prüft dabei keine Routen (HIGH).
- DSP ist auch in NC 35 (stable35, app_api 35.0.0) noch drin, nur als veraltet markiert (HIGH für den Code-Stand 22.10.2026).
- Aufwand gesamt: ca. 25 bis 37 Stunden inklusive Spike und AIO-Test, ohne AIO ca. 21 bis 31 Stunden.

## 1. Was ins ExApp-Image muss

Quellen: HaRP README Abschnitt "Adapting ExApps to use HaRP" (github.com/nextcloud/HaRP, main, gelesen 22.10.2026, HIGH); `exapps_dev/start.sh` (HIGH); nextcloud/app-skeleton-python `Dockerfile`, `healthcheck.sh`, `start.sh` (HIGH); Nextcloud Developer Manual 36, "Adapting ExApps to HaRP" (HIGH); Connector-Repo `Dockerfile`, `healthcheck.sh`, `docs/exapp-install.md` (MEDIUM, eigene gemessene Erfahrung).

Pflicht:

- `start.sh` wörtlich aus `HaRP/exapps_dev/start.sh` übernehmen. Das Skeleton benutzt dieselbe Datei (per diff geprüft). Ablauf:
  - Ist `HP_SHARED_KEY` gesetzt, schreibt es `/frpc.toml`: `serverAddr=$HP_FRP_ADDRESS`, `serverPort=$HP_FRP_PORT`, `remotePort=$APP_PORT`, Name `$APP_ID`, Plugin `unix_domain_socket` auf `/tmp/exapp.sock`, TLS mit `/certs/frp/{client.crt,client.key,ca.crt}`, Servername `harp.nc`.
  - Fehlt `/certs/frp`, schreibt es eine Konfiguration ohne TLS (Klartext-Fallback).
  - Danach `frpc -c /frpc.toml &` und `exec "$@"`.
  - Ohne `HP_SHARED_KEY` (DSP, manual-install, AIO mit `exapp_direct`) startet nur die App. Ein Image passt also für alle Daemons.
- `ENTRYPOINT ["/start.sh", "python", "-m", "gameworld.main"]` (oder ein eigenes `entrypoint.sh` davor, das dann `start.sh` mit exec aufruft, wie im Connector).
- `frpc` ins Image, Version und SHA-256 aus dem HaRP-README (Stand 22.10.2026):
  - `FRP_VERSION=0.71.1`
  - amd64: `1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803`
  - arm64: `8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019`
  - Der Connector pinnt noch 0.61.1; die Doku-Seite zeigt ebenfalls noch 0.61.1 ohne Prüfsumme. Für Gameworld 0.71.1 mit Prüfsumme nehmen.
- `curl` im Image (HaRP-Doku verlangt es, Healthcheck nutzt es).
- Keine `EXPOSE`, kein Host-Port: Unter HaRP gibt es nur Socket plus Tunnel.

Umgebungsvariablen, die AppAPI setzt (app_api `DockerActions::buildDeployEnvs`, HIGH):

- Immer: `AA_VERSION`, `APP_SECRET`, `APP_ID`, `APP_DISPLAY_NAME`, `APP_VERSION`, `APP_HOST`, `APP_PORT`, `APP_PERSISTENT_STORAGE=/nc_app_gameworld_data`, `NEXTCLOUD_URL` (die `nextcloud_url` des Daemons), `COMPUTE_DEVICE`.
- Aus info.xml `<environment-variables>`: `GAMEWORLD_DOCKER_URL`, `GAMEWORLD_PORT_RANGE` (Admin kann sie im Installationsdialog ändern).
- Nur HaRP mit FRP (nicht `exapp_direct`): `HP_FRP_ADDRESS`, `HP_FRP_PORT`, `HP_SHARED_KEY`. Seit HaRP 0.4.6 ist `HP_SHARED_KEY` im ExApp-Container nur ein abgeleitetes Token, das HaRP ausschließlich für den FRP-Login annimmt (README, HIGH). Ein kompromittierter Gameworld-Container hat damit keinen Zugriff auf HaRPs Steuer-API.
- `APP_PORT` liegt unter HaRP im FRP-Bereich 23000 bis 23999; AppAPI wählt ihn selbst, wenn info.xml keinen Port nennt (Connector, Falle 3, MEDIUM). Gameworld nennt keinen Port, passt.

Healthcheck:

- Skeleton prüft nur, ob `frpc` läuft. Besser die Connector-Variante (gemessen): bei `HP_SHARED_KEY` erst `frpc` in `/proc/*/comm` suchen, dann `curl --unix-socket /tmp/exapp.sock http://localhost/heartbeat`, sonst `curl http://127.0.0.1:$APP_PORT/heartbeat`.
- `HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6`. AppAPI wartet auf "healthy", bevor es den Heartbeat schickt.

Nicht-root-Betrieb (Doku-Abschnitt "Running your ExApp with a non-root user" plus Connector-Falle 2):

- HaRP installiert die FRP-Zertifikate per exec im laufenden Container mit dessen Identität. Als Nicht-root scheitert `mkdir -p /certs/frp`, frpc fällt auf Klartext zurück, HaRP lehnt ab, jeder Heartbeat endet in 503 (im Connector gemessen).
- Darum im Image vorbereiten: `/certs` (0700), `/frpc.toml` (0600, leer) und `/nc_app_gameworld_data` (0700), alle dem App-Nutzer gehörend. Der benannte Volume übernimmt Eigentümer und Rechte des Verzeichnisses beim ersten Mount.
- Empfehlung: wie im Connector ein kleines `entrypoint.sh` vor `start.sh`, das bis zu 60 s auf die drei Zertifikatsdateien wartet und den Klartext-Fallback nur mit `ALLOW_PLAINTEXT_FRP=1` zulässt.
- `update-ca-certificates` scheitert ohne root; harmlos, solange keine private CA im Spiel ist.

Gameworld-spezifisch:

- `set_handlers` mountet `js/` und `img/` relativ zum Arbeitsverzeichnis: `WORKDIR` muss das Verzeichnis mit `js/` und `img/` sein (gebautes Vue-Bundle ins Image kopieren).
- Spieldateien (`scripts/fetch-games.sh`, hash-geprüft) beim Image-Bau laden, nicht zur Laufzeit.
- SQLite liegt unter `APP_PERSISTENT_STORAGE`; `config.load_settings` liest das schon.
- `HP_EXAPP_SOCK` wird von nc_py_api respektiert (Default `/tmp/exapp.sock`), start.sh nutzt fest `/tmp/exapp.sock`: nicht ändern.

Skizze (nicht final, Vorlage Connector-Dockerfile):

```dockerfile
FROM python:3.13-slim@sha256:<digest> AS build
COPY --from=ghcr.io/astral-sh/uv:<version> /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim@sha256:<digest>
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
ARG TARGETARCH
RUN set -eux; FRP_VERSION=0.71.1; \
    case "${TARGETARCH:-amd64}" in \
      arm64) A=arm64; S=8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019 ;; \
      amd64) A=amd64; S=1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803 ;; \
    esac; \
    curl -fsSL -o /tmp/frp.tgz "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${A}.tar.gz"; \
    echo "${S}  /tmp/frp.tgz" | sha256sum -c -; \
    tar -C /tmp -xzf /tmp/frp.tgz; \
    install -m 0755 "/tmp/frp_${FRP_VERSION}_linux_${A}/frpc" /usr/local/bin/frpc; rm -rf /tmp/frp*
RUN groupadd -g 10001 exapp && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin exapp
COPY start.sh entrypoint.sh healthcheck.sh /
RUN chmod 0755 /start.sh /entrypoint.sh /healthcheck.sh \
    && install -o 10001 -g 10001 -m 0600 /dev/null /frpc.toml \
    && install -d -o 10001 -g 10001 -m 0700 /certs /nc_app_gameworld_data
COPY --from=build /app/.venv /app/.venv
COPY js /app/js
COPY img /app/img
COPY vendor /app/vendor
ENV PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
USER 10001:10001
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 CMD ["/healthcheck.sh"]
ENTRYPOINT ["/entrypoint.sh", "python", "-m", "gameworld.main"]
```

## 2. Docker-Zugang für Sibling-Container unter HaRP

HaRPs eigener Docker-Engine-Proxy (HIGH, README und `haproxy_agent.py`):

- Erreichbar unter `/exapps/app_api/...` nur mit Header `harp-shared-key` plus `docker-engine-port` (24000 bis 24099).
- ExApps bekommen seit HaRP 0.4.6 den Schlüssel nicht mehr, nur ein FRP-Login-Token. Damit ist der Weg für Gameworld technisch zu.
- Sonderfall HaRP mit `--network host`: `127.0.0.1:24000` steuert die Docker-Engine ohne Schlüssel und ist von ExApps mit Host-Netz erreichbar. Das README nennt das ausdrücklich als Sicherheitswarnung, nicht als Schnittstelle. Nie darauf bauen.
- Ergebnis: Eigener socket-proxy bleibt richtig (bestätigt die Entscheidung aus ARCHITECTURE.md und PITFALLS.md).

Wie die ExApp den eigenen Proxy erreicht (HIGH aus `docker_exapp_create`, Bewertung MEDIUM):

- HaRP legt den ExApp-Container mit `NetworkMode = --net des Daemons` an, Container-Name `nc_app_gameworld`, Hostname `gameworld`, im benutzerdefinierten Netz zusätzlich Alias `gameworld`. Keine veröffentlichten Ports.
- Benutzerdefiniertes Netz (z. B. Compose-Netz, AIO `nextcloud-aio`): Proxy-Service `gameworld-docker-proxy` ins selbe Netz hängen, dann trägt der Default `tcp://gameworld-docker-proxy:2375`. Das ist der empfohlene Weg.
- `bridge` (README-Beispiel "Advanced", Daemon-Template oft so ausgefüllt): Docker löst dort keine Containernamen auf. Der Default scheitert. Abhilfe: Daemon mit eigenem Netz registrieren oder Proxy-IP in `GAMEWORLD_DOCKER_URL` (brüchig).
- `host` (Default von `occ app_api:daemon:register` ohne `--net`): Proxy müsste auf `127.0.0.1:2375` veröffentlicht werden. Dann kann jeder Prozess des Hosts Container erzeugen. Nur mit klarer Warnung dokumentieren.
- Der Admin muss den Proxy selbst starten (Compose-Snippet wie in `docs/install.md`). AppAPI und info.xml können keinen Zusatz-Container mitliefern (HIGH, info.xml-Schema kennt nur Image, Routen, Umgebung).
- Restrisiko bleibt: Alle ExApps im selben Netz erreichen den Proxy. Härtungsoption für später: `wollomatic/socket-proxy` (1.13.1, 15.08.2026) mit `-allowfrom=gameworld` (Hostname-Allowlist) und Methoden-Regex pro Pfad (README, HIGH für die Funktion, MEDIUM für das Zusammenspiel mit dem HaRP-Alias). Der Setup-Check prüft heute Tecnativa-Flags und müsste dafür angepasst werden.

Offizielle ExApps, die Container starten:

- Keine gefunden. Flow (windmill) und andere offizielle ExApps laufen in ihrem eigenen Container (LOW, keine vollständige Suche).

## 3. UDP, Remote-Docker, Heimserver, AIO

UDP (HIGH):

- Gameworld erzeugt Welt-Container über den eigenen Proxy direkt an der Docker-Engine, mit `ports={"30000/udp": ("0.0.0.0", host_port)}` (`provisioner/spec.py`). HaRP und FRP sind daran nicht beteiligt; FRP tunnelt nur das TCP/HTTP der ExApp.
- Damit funktioniert UDP unter HaRP genauso wie heute, solange der Proxy an der Engine hängt, deren Host die Spieler erreichen.

Remote-Docker-Host (HaRP auf Host A, Docker-Engine auf Host B über frpc, README Abschnitt "Connecting External Docker Engines", HIGH für den Mechanismus, MEDIUM für die Folgen):

- Der ExApp-Container läuft auf B. Er braucht von B aus Zugang zu `HP_FRP_ADDRESS` (A:8782) und zu `NEXTCLOUD_URL`.
- Der gameworld-docker-proxy muss auf B laufen, mit dem Socket von B, im Netz `--net` auf B.
- Welten laufen auf B, die UDP-Ports öffnen sich auf B. Die "Adresse für Spieler" muss B sein; der Rückfall auf den Browser-Hostnamen zeigt dann fälschlich auf A. In der Doku und im Setup-Check deutlich machen.

Heimserver und Standard-Compose:

- Ein Host, HaRP mit Socket gemountet, ExApps im Compose-Netz: der einfachste Fall. Firewall muss den UDP-Bereich im LAN erlauben (wie heute).
- Reverse Proxy muss `/exapps/` an HaRP:8780 leiten, sonst scheitert schon die Registrierung beim Heartbeat (Connector-Falle 1, MEDIUM). Nextcloud muss die eigene öffentliche URL selbst erreichen (Hairpin), weil AppAPI jede Anfrage an `<nextcloud_url>/exapps/gameworld/...` schickt (HIGH aus `DockerActions::resolveExAppUrl`).

AIO (HIGH aus `all-in-one/php/containers.json` und app_api `AIODockerActions.php`):

- AIO bringt einen eigenen HaRP-Container mit (`nextcloud-aio-harp`, Image `ghcr.io/nextcloud-releases/aio-harp`, Profil `harp`), kein Community-Container. Der alte AIO-DSP heißt dort "Docker Socket Proxy (deprecated)".
- AppAPI registriert den Daemon `harp_aio` automatisch: Netz `nextcloud-aio`, `exapp_direct = true`. Folge: kein FRP, kein `HP_SHARED_KEY` im Container, die ExApp lauscht per TCP auf `APP_HOST:APP_PORT` (nc_py_api erledigt das). Das Image muss also beide Wege können (tut es mit start.sh und dem Doppel-Healthcheck).
- Gameworld-Proxy unter AIO: eigener Container im externen Netz `nextcloud-aio`, Name `gameworld-docker-proxy` (MEDIUM, nicht getestet). Alternative für später: ein AIO-Community-Container (Format erlaubt Socket-Mount, Beispiel `container-management`) per PR an nextcloud/all-in-one (MEDIUM).
- AIO-Stand: v14.4.1 vom 21.10.2026.

Kubernetes-Backend von HaRP: Gameworld läuft dort nicht (kein Docker-Socket für Welten). In info.xml/Doku ausschließen.

## 4. Routen und Webhooks unter HaRP

Request-Wege (HIGH, Code app_api main und HaRP main):

- Browser direkt: `https://cloud/exapps/gameworld/<pfad>` -> Reverse Proxy -> HaRP:8780 -> SPOE-Agent prüft Cookie/Session bei Nextcloud und Routen -> HAProxy -> FRP-Tunnel (Port 23xxx) -> frpc im Container -> `/tmp/exapp.sock` -> uvicorn.
- AppAPI-signiert (Heartbeat, `/init`, `/enabled`, ExAppProxyController, TalkBotController): Nextcloud-PHP -> `<nextcloud_url>/exapps/gameworld/<route>` mit `AUTHORIZATION-APP-API`, `harp-shared-key`, `ex-app-host`, `ex-app-port` -> Reverse Proxy -> HaRP -> Tunnel -> ExApp. HaRP überspringt bei diesen Anfragen die Routenprüfung (`route_allowed = True  # We skip routes checking for AppAPI signed requests`).
- AIO (`exapp_direct`): HaRP verbindet direkt zu `gameworld:<APP_PORT>` im Netz `nextcloud-aio`, ohne Tunnel.

Folgen für Gameworld:

- Frontend über `/index.php/apps/app_api/proxy/gameworld/...` bleibt gültig. AppAPI prüft dort Route, Verb und Stufe selbst (`ExAppProxyController::passesExAppProxyRoutesChecks`) und reicht signiert an HaRP weiter. Auch offizielle Apps nutzen den Weg unter HaRP (Flow-Dockerfile setzt `/index.php/apps/app_api/proxy/flow/api`, HIGH).
- Eingebettete Seiten `/index.php/apps/app_api/embedded/gameworld/gameworld/<seite>` laufen über denselben Proxy (MEDIUM, nicht unter HaRP getestet).
- Talk-Bot: Talk ruft `.../ocs/v2.php/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot` auf, AppAPI prüft HMAC und Drossel, dann `requestToExApp` signiert (mit leerem Nutzer). HaRP prüft keine Route. Der Webhook funktioniert also unter HaRP ohne den Routeneintrag `^/talk/bot$`.
  - Der Kommentar in info.xml ("damit ein strengerer Proxy (HaRP) sie kennt") stimmt nicht: HaRP braucht die Route nicht. Die Route öffnet im Gegenteil den direkten Weg `/exapps/gameworld/talk/bot` für jeden angemeldeten Nutzer (der Handler verwirft zwar alles, aber die Fläche ist unnötig). Empfehlung: Route entfernen, Handler behalten.
  - Warum es im Dev nicht beweisbar war (MEDIUM): Die Bot-URL wird absolut erzeugt (`linkToOCSRouteAbsolute`) aus der Adresse, über die die ExApp Nextcloud anspricht, im Dev `http://localhost:8091`. Talk sendet aus dem Nextcloud-Container, dort ist `localhost:8091` nicht erreichbar. Im HaRP-Teststapel eine URL wählen, die Browser und Container gleich auflösen (siehe Abschnitt 5).
- Unterschiede HaRP gegenüber AppAPI-Proxy bei direkten `/exapps/`-Anfragen (HIGH aus `ExAppRoute` und `_exapps_msg`):
  - HaRP ignoriert das Verb. Die erste Route, deren Regex zum Pfad passt, entscheidet. `POST /api/my/x` träfe unter HaRP `^/api/my/.*` (USER), unter AppAPI fiele es auf `^/api/.*` (ADMIN) durch. Python-Seite muss daher jede Methode selbst absichern (heute: FastAPI antwortet 405, wenn kein Handler existiert).
  - Eine von HaRP abgelehnte Route (403/404) zählt als Fehlversuch der Client-IP. 10 Fehlversuche in 5 Minuten sperren die IP für 300 s. Ohne `HP_TRUSTED_PROXY_IPS` ist das die IP des Reverse Proxys, über den auch Nextcloud selbst die ExApp anspricht. Darum: Kinder-UI nie über `/exapps/` gegen ADMIN-Routen laufen lassen; beim AppAPI-Proxy-Pfad bleiben.
  - Antwortcodes der ExApp selbst (z. B. 403 aus `require_verwalter`) zählen nur bei Routen mit `bruteforce_protection`. Gameworld setzt keine, passt.
- ROLLE-03 (Verwalter-Gruppen ohne NC-Admin): ADMIN heißt bei AppAPI und HaRP "NC-Admin". `^/api/.*` muss für ROLLE-03 auf USER, die Python-Prüfung wird die einzige Grenze. Das gilt unabhängig von HaRP, gehört aber in dieselbe info.xml-Änderung.
- Bekannte Bugs: HaRP-Issue #61 (offen seit 02.11.2025, 401 auf direkten `/exapps/`-Links von Flow) betrifft direkte Browser-Links ohne Session, nicht Gameworlds Proxy-Weg (MEDIUM). Kein offenes Issue zu Talk-Bots unter HaRP gefunden (Suche HaRP und app_api, 22.10.2026).

## 5. Lokaler HaRP-Teststapel

Vorlage: `C:\Users\Student\nextcloud-mcp-connector\compose.exapp.yml` plus `deploy/Caddyfile` plus `scripts/bootstrap_exapp.sh` (dort bewiesen, inklusive lokaler Registry). Für Gameworld als eigenes Projekt `gameworld-harp`, neben `gameworld-dev`, aber nicht gleichzeitig laufen lassen (RAM).

Bausteine:

- `caddy:2`: `/exapps/*` an `appapi-harp:8780` (read_timeout 1800s), Rest an `nextcloud:80`.
- `nextcloud:34.0.3-apache` (danach `35.0.2-apache` als Kanarienvogel), `OVERWRITEHOST`, `OVERWRITEPROTOCOL`, `OVERWRITECLIURL`, `TRUSTED_PROXIES` auf die feste Caddy-IP.
- `ghcr.io/nextcloud/nextcloud-appapi-harp:release` (0.4.6), `HP_SHARED_KEY` aus `openssl rand -hex 32`, `NC_INSTANCE_URL=http://caddy`, `HP_TRUSTED_PROXY_IPS=<Caddy-IP>`, Socket-Mount, `./.harp-certs:/certs`. Keine Ports veröffentlichen.
- `gameworld-docker-proxy` (gleiche Flags wie heute) im selben Netz, ohne Host-Port.
- `registry:2` auf `127.0.0.1:5000`, damit HaRP das lokal gebaute Image ziehen kann.
- Netz mit Namen und fester Subnetz-/ip_range-Aufteilung wie im Connector.

URL-Wahl wegen Talk-Bot (MEDIUM): Nextcloud-URL so wählen, dass Browser und Container sie gleich erreichen, z. B. `http://host.docker.internal:8092` (Docker Desktop trägt den Namen auch auf Windows ein; `extra_hosts: host-gateway` im Nextcloud-Container; bestehende Trusted-Domain-Liste kennt den Namen schon). Mit `127.0.0.1:8081` wie im Connector bleibt die Bot-URL im Container unerreichbar.

Registrierung (Muster aus dem Connector):

```sh
occ app_api:daemon:register harp_proxy_docker "Harp Proxy (Docker)" docker-install http \
  "appapi-harp:8780" "http://host.docker.internal:8092" \
  --net gameworld-harp-net --harp \
  --harp_frp_address "appapi-harp:8782" \
  --harp_shared_key "$HP_SHARED_KEY" --set-default
occ app_api:app:register gameworld harp_proxy_docker \
  --info-xml /tmp/info.xml --wait-finish   # info.xml mit registry 127.0.0.1:5000
```

- Den Schlüssel per stdin in den Container geben, nicht über argv des Hosts (Connector WR-06).
- Ports: 8780 (ExApp-HTTP), 8781 (HTTPS, nur mit `/certs/cert.pem`), 8782 (FRP). Im Teststapel nichts davon veröffentlichen, Caddy spricht 8780 im Netz an, die ExApp 8782.
- Fallen aus dem Connector: HaRP cacht den App-Eintrag nach einer fehlgeschlagenen Registrierung, dann `up -d --no-deps --force-recreate appapi-harp`; `HP_LOG_LEVEL=info` zeigt das Routing; Schlüssel-Drift zwischen HaRP und Daemon ergibt 503 überall.
- Testdeploy im Daemon-Menü ("Test deploy") vorher einmal laufen lassen.

RAM-Bedarf (LOW, Schätzung, im Spike mit `docker stats --no-stream` messen):

- Nextcloud Apache mit SQLite: ca. 150 bis 300 MB
- HaRP (HAProxy, Python-Agent, frps, frpc): ca. 50 bis 120 MB
- Caddy: ca. 15 bis 40 MB
- Registry: ca. 10 bis 30 MB
- gameworld-docker-proxy: ca. 10 bis 20 MB
- Gameworld-ExApp (Python, FastAPI, docker-py): ca. 100 bis 180 MB
- Eine Kreativwelt: gemessen 18 MiB im Leerlauf (02-07-SUMMARY), Limit 512 MiB; Abenteuer bis 1 GiB Limit
- Summe ohne Welt: ca. 0,35 bis 0,7 GB, mit einer Kreativwelt unter 1 GB. Bei ca. 4 GB frei machbar, aber nur seriell: `gameworld-dev` und andere Nextcloud-Stapel vorher stoppen (Owner-Regel).
- AIO lokal ist deutlich schwerer (Mastercontainer, Nextcloud, Postgres, Redis, Apache, HaRP, ca. 1,5 bis 2,5 GB, LOW). AIO-Test besser auf einer separaten Maschine oder einem kleinen VPS.

## 6. Versionen und Status (22.10.2026)

- HaRP: v0.4.6 vom 20.10.2026 (davor 0.4.5 vom 02.09.2026). Tag `release` im Image. 0.4.6 bringt Bind-Mount-Regeln, Prüfung von `--net`, abgeleitetes Token statt Schlüssel im ExApp-Container (GitHub Releases, HIGH). Gameworld nutzt keine Bind-Mounts, ist nicht betroffen.
- DSP-Entfernung in NC 35: nicht passiert. NC 35.0.0 erschien am 15.09.2026 (aktuell 35.0.2 vom 15.10.2026). In `app_api` stable35 (35.0.0) und sogar main (36.0.0-dev) steht weiter nur die Warnung "deprecated and will be removed in Nextcloud 35" (HIGH für den Code-Stand). Für Gameworld egal, solange HaRP primär dokumentiert ist; DSP würde mit demselben Image funktionieren.
- Mindest-NC-Version für HaRP: 32 (README, HIGH). Gameworld bleibt bei `min-version="32"`.
- `max-version="34"` in info.xml ist veraltet: NC 35 ist stabil. Vor dem Store-Release gegen 35.0.2 testen und auf 35 anheben (Connector hat bereits einen NC-35-Kanarienvogel, `compose.nc35.yml`).
- nc_py_api: HaRP-Unterstützung (Unix-Socket statt host:port) seit 0.19.1 vom 07.03.2025 (CHANGELOG, HIGH). 0.30.3 vom 11.08.2026 ist aktuell und enthält sie (im venv geprüft: `uvicorn_fastapi.run_app`).
- AppAPI hat einen eigenen Setup-Check `HarpVersionCheck` (app_api `lib/SetupChecks`, HIGH); in der Doku darauf verweisen.

## 7. Änderungsliste für Gameworld

Reihenfolge, Aufwand, Risiko:

1. Spike (siehe unten), 4 bis 6 h. Risiko: Windows/Docker-Desktop-Eigenheiten, sonst gering.
2. `Dockerfile` (neu), `start.sh` (wörtlich), `entrypoint.sh` (Zertifikats-Wartezeit, kein Klartext-Fallback), `healthcheck.sh` (Socket und TCP), `.dockerignore`: 3 bis 4 h. Vorlage Connector. Risiko: Rechte von `/certs`, `/nc_app_gameworld_data`, Arbeitsverzeichnis für `js/` und `img/`.
3. Test im Stil von `tests/test_info_xml.py`: Image-Tag, Version, frpc-Pin, start.sh-Prüfsumme gegen Upstream im Lockstep: 1 h.
4. CI: Multi-Arch-Build (amd64, arm64) und Push nach `ghcr.io/street1983nk/gameworld:<version>`, Image öffentlich: 2 bis 3 h (Vorlage Findling/Connector). Risiko: arm64-Build der Abhängigkeiten.
5. `scripts/dev/compose.harp.yaml` plus `scripts/dev/register-exapp-harp.sh` (Caddy, HaRP, Registry, Proxy, Bootstrap): 3 bis 4 h. Bestehendes `register-exapp.sh` bleibt für schnelle manual-install-Runden.
6. `appinfo/info.xml`: `max-version` 35, Beschreibung "Nextcloud 32 to 35", Route `^/talk/bot$` entfernen und Kommentar korrigieren, für ROLLE-03 `^/api/.*` auf USER (Python prüft): 1 bis 2 h inklusive Tests. Risiko: ROLLE-03-Umstellung macht Python zur einzigen Grenze, Tests für jede Verwalter-Route nötig.
7. Setup-Check: Bei DNS-Fehler auf `gameworld-docker-proxy` eigene Meldung "Proxy nicht im Netz des Deploy-Daemons (bridge-Netz hat keine Namensauflösung)": 1 bis 2 h.
8. Abnahme auf HaRP (Skript `acceptance-phase6.sh`): Installation vom Registry-Tag, Welt anlegen, UDP-Beitritt mit dem vorhandenen UDP-Prober, Kinder-Sicht, Talk-Bot-Webhook kommt an, Deinstallation und Orphan-Kommando: 4 bis 6 h.
9. AIO-Test (getrennte Maschine): Proxy im Netz `nextcloud-aio`, Installation aus dem Store-Pfad: 4 bis 6 h. Risiko: höchster RAM-Bedarf, AIO-Eigenheiten (`exapp_direct`).
10. Doku: `docs/install.md` für HaRP-Compose, AIO und Remote-Docker, `privacy.md`, Store-Listing (Socket-Proxy, UDP-Ports): 2 bis 3 h.

Summe: ca. 25 bis 37 h mit Spike und AIO; ohne AIO ca. 21 bis 31 h.

Risiken:

- Netzwerk des Daemons (`bridge`/`host`) bricht den Proxy-Default. Mitigation: Doku, Setup-Check-Meldung, Snippet mit externem Netz.
- Proxy im gemeinsamen ExApp-Netz bleibt für andere ExApps erreichbar (root-gleich). Mitigation jetzt: ehrlich dokumentieren; später: `wollomatic/socket-proxy` mit `-allowfrom=gameworld`.
- Hairpin: Nextcloud muss die eigene öffentliche URL erreichen. Bei Heimservern ohne Hairpin-NAT schlägt die Registrierung fehl. Mitigation: Doku-Hinweis (lokaler DNS-Eintrag oder `extra_hosts`).
- HaRP-IP-Sperre bei vielen 4xx auf direkten `/exapps/`-Pfaden. Mitigation: Frontend bleibt beim AppAPI-Proxy, `HP_TRUSTED_PROXY_IPS` dokumentieren.
- Remote-Docker: falsche Spieler-Adresse. Mitigation: Hinweis im Dashboard, wenn die Adresse leer ist.
- HaRP bewegt sich schnell (0.4.x, Bind-Mount- und Netz-Regeln mit Breaking Changes in Patch-Versionen). Mitigation: bei jedem HaRP-Release die Abnahme laufen lassen.

## Vorgeschlagener Spike (zuerst beweisen, 4 bis 6 h)

Ziel: Der Weg Store-Image unter HaRP trägt Gameworld komplett, bevor Doku und CI entstehen.

1. Minimales Dockerfile bauen, Image in die lokale Registry schieben.
2. HaRP-Stapel starten (`gameworld-dev` vorher stoppen), Daemon mit `--net gameworld-harp-net` registrieren, Test deploy grün.
3. Gameworld aus der Registry registrieren: Heartbeat, `/init`, `/enabled` grün; im Container prüfen, dass `/frpc.toml` TLS nutzt und `/tmp/exapp.sock` existiert.
4. Setup-Check grün: ExApp erreicht `tcp://gameworld-docker-proxy:2375` per Name.
5. Kreativwelt anlegen, UDP-Port vom Windows-Host mit dem UDP-Prober erreichen.
6. Kinder-Konto: eingebettete Seite und `/api/me`, `/api/my/...` über den AppAPI-Proxy; Verwalter-Route liefert 403 ohne HaRP-Sperre.
7. Talk installieren, Welt-Raum anlegen, Nachricht schreiben, Ankunft auf `/talk/bot` im ExApp-Log belegen (Statuscode, nicht Inhalt). Danach Route aus info.xml entfernen und Ankunft erneut belegen (Beweis, dass HaRP sie nicht braucht).
8. `docker stats --no-stream` für alle Container notieren (RAM-Zahlen für install.md).

Abbruchkriterium: Schritt 3 oder 4 scheitert nach 2 h, dann HaRP-Logs mit `HP_LOG_LEVEL=info` und Connector-Fallen 1 bis 4 abarbeiten, bevor weitergebaut wird.

## Offene Fragen

- Netz in der Praxis: Welche `--net`-Werte setzen Admins mit dem UI-Template "HaRP Proxy (Docker)" typischerweise? Falls oft `bridge`: Default `GAMEWORLD_DOCKER_URL` überdenken.
- AIO: Ist ein fremder Container im Netz `nextcloud-aio` dauerhaft stabil (AIO-Updates, Netz-Neuanlage)? Lohnt ein AIO-Community-Container `gameworld-docker-proxy`?
- Talk-Bot: Kommt der Webhook unter HaRP wirklich an (Spike Schritt 7)? Code sagt ja, Beleg fehlt.
- Eingebettete Seiten unter HaRP: Kein Code-Hinweis auf Probleme, aber ungetestet.
- RAM von HaRP und AIO: nur geschätzt.
- NC 35: läuft Gameworld mit nc_py_api 0.30.3 auf 35.0.2 ohne Änderung?
- Soll der socket-proxy auf `wollomatic/socket-proxy` wechseln (Hostname-Allowlist) und ab wann? Setup-Check prüft heute Tecnativa-Verhalten.
- Rootless Docker und Podman als Engine hinter HaRP: UDP-Port-Veröffentlichung nicht untersucht.

## Empfehlung

- HaRP als primären, einzigen dokumentierten Deploy-Weg festlegen; DSP und manual-install funktionieren mit demselben Image nebenbei.
- Zuerst den Spike (4 bis 6 h) fahren, dann Dockerfile, CI und Dev-Stapel nach Connector-Vorlage.
- Den eigenen socket-proxy beibehalten; HaRPs Engine-Proxy nie nutzen.
- Frontend beim AppAPI-Proxy-Pfad lassen, nicht auf `/exapps/` umstellen.
- info.xml in einem Schritt anpassen: max-version 35, Talk-Route raus, ROLLE-03-Routen auf USER mit Python-Prüfung.
- AIO-Abnahme auf getrennter Hardware einplanen, nicht auf dem RAM-knappen Entwicklungsrechner.

## Quellen

- https://github.com/nextcloud/HaRP (README, `exapps_dev/start.sh`, `haproxy_agent.py`, main, gelesen 22.10.2026), HIGH
- https://github.com/nextcloud/HaRP/releases/tag/v0.4.6 (20.10.2026), HIGH
- https://github.com/nextcloud/HaRP/issues/61, MEDIUM
- https://github.com/nextcloud/app_api (main Commit 779255b vom 22.10.2026: `AppAPICommonService`, `HarpService`, `DockerActions`, `ManualActions`, `AIODockerActions`, `ExAppProxyController`, `TalkBotController`, `TalkBotsService`, `Command/Daemon/RegisterDaemon`; stable34/stable35 RegisterDaemon und info.xml), HIGH
- https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/development_overview/ExAppHarpIntegration.html (Version 36, gelesen 22.10.2026), HIGH
- https://github.com/nextcloud/app-skeleton-python (Dockerfile, healthcheck.sh, start.sh, info.xml), HIGH
- https://github.com/nextcloud/flow (Dockerfile, AppAPI-Proxy-Pfad), HIGH
- https://github.com/nextcloud/all-in-one (`php/containers.json`, `Containers/nextcloud/entrypoint.sh`, `community-containers`, Release v14.4.1), HIGH
- https://github.com/cloud-py-api/nc_py_api (CHANGELOG 0.19.1, Release 0.30.3), plus lokales venv `nc_py_api/ex_app/uvicorn_fastapi.py`, HIGH
- https://github.com/nextcloud/server/releases (35.0.0 vom 15.09.2026, 35.0.2 vom 15.10.2026), HIGH
- https://github.com/wollomatic/socket-proxy (README, Release 1.13.1), HIGH für Funktionsumfang
- Lokal: `C:\Users\Student\nextcloud-mcp-connector\Dockerfile`, `healthcheck.sh`, `compose.exapp.yml`, `deploy/Caddyfile`, `scripts/bootstrap_exapp.sh`, `docs/exapp-install.md`, MEDIUM (eigene Messungen)
