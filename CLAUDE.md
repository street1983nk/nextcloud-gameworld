<!-- GSD:project-start source:PROJECT.md -->
## Project

**Gameworld**

Gameworld ist ein kindgerechtes Gameserver-Portal als Nextcloud-ExApp. Familien betreiben damit private Spielwelten (zuerst Luanti, später Minecraft Java) auf dem eigenen Nextcloud-Server: eine Welt per Klick erstellen, Kinder und Freunde über Nextcloud-Konten einladen, Weltsicherungen in Nextcloud Files, Elternkontrolle statt Admin-Zugängen für Kinder.

**Core Value:** Ein Elternteil ohne Serverwissen kann in wenigen Minuten eine private, sichere Luanti-Welt für die eigenen Kinder starten, auf der nur eingeladene Personen spielen und deren Daten zuhause bleiben.

### Constraints

- **Tech stack**: Python-ExApp über AppAPI (passt zu Findling/Connector-Skillset) , kein eigenes Framework-Experiment
- **Plattform**: Muss als ExApp im Nextcloud App Store installierbar sein (Docker-Deploy, AppAPI-Konventionen)
- **Sicherheit**: Kindersicher ist Produktkern , private Welten per Default, keine offenen Ports ohne Einladung, keine Admin-Zugänge für Kinder
- **Ressourcen**: Läuft auf Heimservern , Ressourcenlimits pro Welt sind Pflicht, keine Annahme von Server-Hardware
- **Recht**: Luanti zuerst; Minecraft erst in MVP 2 mit EULA-Prüfung
- **Zeit**: Soloprojekt neben Findling-Pflege; grobe Phasen, wenig Zeremonie
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Nextcloud AppAPI | im Server gebündelt (Releases im app_api-Repo enden 09/2024 bei v3.2.0, seither Teil des Server-Release-Zyklus) | ExApp-Laufzeitumgebung, Deploy, Auth | Einzige Store-faehige Architektur fuer Python-Apps; Skillset aus Findling/Connector vorhanden |
| HaRP (Deploy Daemon) | Image `ghcr.io/nextcloud/nextcloud-appapi-harp:release` | ExApp-Deployment + Reverse Proxy (HAProxy, FRP-Tunnel, Docker-Engine-Proxy) | Offiziell empfohlener Deploy-Weg fuer NC 32+; Docker Socket Proxy (DSP) ist deprecated, Entfernung fuer NC 35 angekuendigt. Gameworld muss HaRP-kompatibel sein (start.sh/FRP-Client im Image) |
| nc_py_api | 0.30.3 (11.08.2026) | Nextcloud-Python-Framework: ExApp-Lifecycle, Files/WebDAV, UI-Registrierung, occ | Offizielles Framework; bringt FastAPI (>=0.133), pydantic, niquests mit. **Async-first: ab 0.30 werden Sync-Wrapper entfernt, daher von Anfang an `AsyncNextcloudApp`** |
| Python | 3.13 (Basis-Image `python:3.13-slim`) | ExApp-Laufzeit | nc_py_api unterstuetzt 3.10 bis 3.13; neuestes Stable nehmen, kein Grund fuer aelter |
| FastAPI + uvicorn | FastAPI >=0.133 (via nc_py_api), uvicorn aktuell | HTTP-Backend der ExApp | nc_py_api-Standardmuster (`set_handlers`, `run_app`); kein Framework-Experiment noetig |
| docker (docker-py) | 7.2.0 | Provisionierung der Luanti-Container (create/start/stop, mem_limit, nano_cpus, Logs, Stats) | Vollstaendigste, am besten dokumentierte Docker-Engine-API fuer Python. Sync, aber Provisionierungs-Calls sind selten; in FastAPI via `anyio.to_thread` kapseln |
| Luanti Server | `ghcr.io/luanti-org/luanti:5.17.0` | Game-Server pro Welt | Offizielles Image aus dem Luanti-Monorepo; Tags `latest`/`<version>`/`master`. 5.17.0 ist Stable (08/2026), 5.18-rc1 existiert. Volumes: `/var/lib/minetest/` (Daten/Welten), `/etc/minetest/` (minetest.conf); Port 30000/udp |
| Vue 3 + @nextcloud/vue | @nextcloud/vue 9.13.1 (Vue ^3.5) | Web-UI der ExApp im Nextcloud-Look | v9 ist die aktuelle Vue-3-Linie fuer NC 30+; UI wird als statisches Bundle aus dem ExApp-Container unter `/exapps/gameworld/` serviert, Top-Menu-Eintrag per nc_py_api `ui.top_menu` |
### Container-Provisionierung (Kern-Entscheid)
### Supporting Libraries
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiodocker | 0.27.0 (05/2026, aio-libs, aktiv) | Async-Docker-Client | Nur falls Live-Log-/Konsolen-Streaming spaeter echte Async-Streams braucht; API-Abdeckung duenner als docker-py |
| tecnativa/docker-socket-proxy | aktuelles Image | Gescopter Docker-API-Zugriff | Pflichtbestandteil des Deployments (siehe oben) |
| gameworld_access (eigener Welt-Mod, von Gameworld mitgeliefert) | im Gameworld-Code, Luanti 5.17.0 | Prejoin-Whitelist pro Welt plus Passwort-Provisionierung per SRP-Verifier | Luanti hat KEINE eingebaute Whitelist. Gameworld schreibt `gameworld_access.txt` per put_archive (root, 0444) aus den Nextcloud-Einladungen; der Mod lädt sie bei jedem Join-Versuch und alle 5 s neu, lehnt nicht Eingeladene im Prejoin ab und setzt für Eingeladene den SRP-Verifier, Einladungen und neue Passwörter wirken ohne Server-Neustart. ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md |
| gameworld_time (eigener Welt-Mod, von Gameworld mitgeliefert) | im Gameworld-Code, Luanti 5.17.0 | Spielzeiten pro Kind und Zeitfenster pro Welt durchsetzen (Phase 4) | Gameworld schreibt `gameworld_time.txt` (root, 0444) mit absoluten Epoch-Grenzen; der Mod sperrt im Prejoin, warnt per Chat bei 10/5/1 min, trennt per `disconnect_player` und zählt Online-Zeit im neustartfesten Zählbuch `gameworld_time_used.txt` im Welt-Volume; die ExApp verbucht es alle 15 s zu einem Tageskontingent über alle Welten |
| tzdata | 2026.5 | IANA-Zeitzonendaten für `zoneinfo` (Haushalts-Zeitzone, Vorgabe Europe/Berlin) | Laufzeitabhängigkeit: Windows und schlanke Images haben keine System-Zeitzonendaten |
| tarfile (stdlib) + nc_py_api Files | stdlib / 0.30.3 | Welt-Backup als tar.gz, Upload nach Nextcloud Files via WebDAV (`files.upload_stream` fuer grosse Archive) | Backup/Restore-Phase; Welt vor dem Tar stoppen oder sqlite-Backup nutzen (map.sqlite ist bei laufendem Server inkonsistent) |
| @nextcloud/initial-state, @nextcloud/l10n, @nextcloud/router, @nextcloud/axios | aktuelle 2026er Linien | Frontend-Integration in Nextcloud | Standard-Begleiter zu @nextcloud/vue 9 |
| Vite + @nextcloud/vite-config | aktuell | Frontend-Build | Aktueller Nextcloud-Standard; NICHT das webpack/Babel-Setup des alten ui_example kopieren |
### Development Tools
| Tool | Purpose | Notes |
|------|---------|-------|
| ruff (Vollsatz) + pyright (basic) + vulture | Python-Qualitaetsgates | Projektstandard des Owners, lokal gruen vor Commit; pyright mit `PYRIGHT_PYTHON_FORCE_VERSION=latest` |
| AppAPI `manual-install`-Daemon | Lokale ExApp-Entwicklung ohne Image-Rebuild | ExApp lokal starten, per `occ app_api:daemon:register ... manual-install` registrieren; bekanntes Muster aus Findling |
| Docker Compose Dev-Stack | NC + HaRP + socket-proxy + ExApp lokal | Nachbau der Zielumgebung; Julius-Haertel-/nextcloud-docker-dev-Setup oder eigenes Compose |
| pytest + nc_py_api `NextcloudApp`-Testmuster | Backend-Tests | wie bei Findling/Connector |
## Installation
# Backend (uv, wie in den anderen Projekten)
# fastapi/uvicorn kommen als nc_py_api-Dependencies mit; uvicorn explizit pinnen
# Frontend
# Deployment-Seite (Admin-Doku, nicht App-Code)
# - HaRP: ghcr.io/nextcloud/nextcloud-appapi-harp:release (NC 32+)
# - Socket-Proxy: tecnativa/docker-socket-proxy (CONTAINERS=1, IMAGES=1, VOLUMES=1, POST=1, Rest=0)
# - Game-Image: ghcr.io/luanti-org/luanti:5.17.0 (wird von Gameworld selbst gepullt)
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Sibling-Container via docker-py + Socket-Proxy | Luanti-Prozesse IM ExApp-Container (supervisord) | Falls der Socket-Proxy-Setupschritt Nutzer nachweislich abschreckt. Nachteile: keine sauberen RAM/CPU-Limits pro Welt, Crash einer Welt gefaehrdet die ExApp, UDP-Ports haengen am ExApp-Netzmodus. Nur als Fallback-Spike |
| docker-py 7.2.0 | aiodocker 0.27.0 | Reines Async gewuenscht oder dauerhaftes Log-Streaming; sonst docker-py wegen API-Abdeckung und Doku |
| docker-py | python-on-whales | Nie hier: shellt zur docker-CLI aus, CLI muesste ins ExApp-Image |
| Eigene Provisionierung | Crafty Controller 4.11.0 (16.09.2026) als Engine | Erst MVP 2 (Minecraft): Crafty ist Minecraft-only, kann kein Luanti. Fuer MVP 2 zusaetzlich pruefen: `itzg/docker-minecraft-server` + dasselbe Sibling-Muster waere konsistenter als ein ganzes Panel |
| Eigene Provisionierung | Pelican Panel | Noch v1.0.0-rc.1 (10.10.2026), kein Stable; PHP-Panel + Wings-Daemon ist fuer einen Heimserver massiv ueberdimensioniert |
| Eigene Provisionierung | LuHost (Modpol / Media Economies Design Lab, CU Boulder, git.medlab.host) | Nicht als Dependency: junges Lab-Projekt ohne stabile API. Aber wertvolle Feature-Referenz (Live-Konsole, World-Auswahl, One-Click-Backup, ContentDB-Browsing) |
| ghcr.io/luanti-org/luanti | lscr.io/linuxserver/luanti | Falls LinuxServer-Komfort (PUID/PGID-Handling) gebraucht wird; offizielle Images bleiben naeher am Upstream-Release |
| Eigener Welt-Mod gameworld_access | Direktes Schreiben der Auth-DB (`auth.sqlite`) | Nur falls der Mod-Ansatz in der Praxis hakt; DB-Schreiben erfordert gestoppten Server, die Zugangsdatei nicht (ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md) |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Docker Socket Proxy (DSP) als AppAPI-Daemon fuer Neuinstallationen | Deprecated, Entfernung fuer NC 35 angekuendigt | HaRP (NC 32+) |
| Sync-API von nc_py_api (`NextcloudApp`) | Sync-Wrapper werden seit 0.30.0 modulweise entfernt | `AsyncNextcloudApp` von Beginn an |
| ui_example-Skeleton (cloud-py-api/ui_example) als Frontend-Vorlage | Veraltet: Vue 2.7, @nextcloud/vue ^8, webpack/Babel | Vue 3 + @nextcloud/vue 9 + Vite; nur die Backend-Registrierungslogik des Beispiels als Referenz |
| Pterodactyl | Kein Luanti, Panel + Wings fuer Heimserver ueberdimensioniert (wieder aktiv: v1.15.2 vom 21.10.2026, v2-Beta) | Eigene Provisionierung (MVP 1), Crafty/itzg pruefen (MVP 2) |
| Roher Docker-Socket im ExApp-/Proxy-Setup ohne Scoping | Root-Aequivalent auf dem Heimserver, Produktkern ist Kindersicherheit | tecnativa/docker-socket-proxy mit minimalen Flags |
| Luanti-Tag `master` oder `latest` in Produktion | `master` = Dev-Build; `latest` springt bei Releases und bricht Client-Kompatibilitaet | Versions-Pin `5.17.0`, Upgrade als bewusste Produktentscheidung |
| Mojang-/Minecraft-Anteile in MVP 1 | EULA-/Guideline-Risiko, Owner-Entscheid Luanti-first | Luanti 5.17 |
## Stack Patterns by Variant
- `minetest.conf` pro Welt von Gameworld generiert: `server_announce = false` (keine oeffentliche Serverliste), `max_users` klein, `disallow_empty_password = true`, `default_privs` ohne Admin-Rechte
- Whitelist und Spielpasswörter via eigenem Welt-Mod gameworld_access: Gameworld schreibt `gameworld_access.txt` (Spielername plus SRP-Verifier) per put_archive aus den Nextcloud-Einladungen, der Mod lädt live nach (ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md)
- Kinder-Konten bekommen nie `privs`-Vergabe; Elternkontrolle laeuft komplett ueber die ExApp-UI
- Konfiguration: ausschliesslich ueber Dateien (`minetest.conf`, `world.mt`, `gameworld_access.txt`) vor Start bzw. mit Live-Reload
- Luanti hat kein RCON und keine eingebaute Admin-HTTP-API; Terminal-Konsole braucht ncurses-Build
- Fuer Live-Kommandos zwei Kandidaten: (a) `docker attach`/stdin an den Server-Prozess, (b) kleiner mitgelieferter Lua-Agent-Mod (Datei-Queue im World-Dir oder HTTP-Polling via `secure.http_mods` gegen die ExApp). LuHost nutzt das Konsolen-Muster erfolgreich. Entscheid in der Konsolen-Phase
- Welt stoppen (Container stop) -> World-Dir aus dem Shared Volume per tarfile packen -> `files.upload_stream` in einen Gameworld-Ordner der Eltern-Nutzerin -> Container wieder starten; Restore umgekehrt
- Shared Volume: ein benanntes Docker-Volume pro Welt, das sowohl der Luanti-Container (unter `/var/lib/minetest/`) als auch die ExApp (lesend fuer Backups) mounted; da info.xml keine ExApp-Mounts kann, laeuft der Backup-Lesezugriff ueber einen kurzlebigen Hilfscontainer (docker-py: Container mit Volume mounten, tar streamen via `get_archive`) statt ueber einen ExApp-Mount
## Version Compatibility
| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| nc_py_api 0.30.3 | Nextcloud 31, 32, 33 | Badges im Repo; Python 3.10-3.13 |
| HaRP | Nextcloud 32+ | DSP-Removal fuer NC 35 angekuendigt |
| @nextcloud/vue 9.13.1 | Vue ^3.5.18, Nextcloud 30+ | v8 = Vue 2, nicht mehr verwenden |
| gameworld_access (eigener Welt-Mod) | Luanti 5.17.0 | ersetzt ct_whitelist; ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md |
| Luanti-Client | Luanti-Server gleicher Minor-Version | Client/Server muessen zusammenpassen; Server-Version-Pin ist gleichzeitig Client-Vorgabe fuer die Familie |
| Luanti 5.16.0 | kaputt | Release Notes: broken, 5.16.1 nutzen; nie 5.16.0 pinnen |
## Sources
- https://pypi.org/pypi/nc_py_api/json , Version 0.30.3, Dependencies, Async-Umstellung (HIGH)
- https://github.com/cloud-py-api/nc_py_api , NC-31-33-Support, Python 3.10-3.13, Skeleton/Examples (HIGH)
- https://github.com/nextcloud/app_api , HaRP empfohlen fuer NC 32+, DSP deprecated/Removal NC 35 (HIGH)
- https://github.com/nextcloud/HaRP , HAProxy/FRP/Docker-Engine-Proxy, HP_SHARED_KEY-Auth, Ports 8780-8782 (HIGH)
- https://nextcloud.github.io/app_api/tech_details/Deployment.html , info.xml-Schema (nur Registry/Image/Tag, keine Mounts), Deploy-Variablen inkl. APP_PERSISTENT_STORAGE (HIGH; Seite teils aelter als HaRP)
- https://docs.nextcloud.com/server/stable/developer_manual/exapp_development/development_overview/ExAppHarpIntegration.html , start.sh/FRP-Client im ExApp-Image (MEDIUM, nur ueber Suchtreffer gesichtet)
- https://api.github.com/repos/luanti-org/luanti/releases , 5.17.0 Stable (20.08.2026), 5.18.0-rc1, 5.16.0 broken (HIGH)
- https://raw.githubusercontent.com/luanti-org/luanti/master/doc/docker_server.md + https://docs.luanti.org/for-server-hosts/setup/containers/ , ghcr.io/luanti-org/luanti, Volumes, Port 30000/udp (HIGH)
- https://content.luanti.org/packages/GreatBigDiamond/ct_whitelist , ct_whitelist auf ContentDB nicht mehr auffindbar (19.10.2026), siehe 03-RESEARCH.md; ersetzt durch den eigenen Welt-Mod gameworld_access
- https://wiki.luanti.org/Console , Terminal-Konsole braucht ncurses-Build (MEDIUM)
- https://pypi.org/pypi/docker/json , docker-py 7.2.0 (HIGH)
- https://pypi.org/pypi/aiodocker/json , 0.27.0 (05/2026), aio-libs, aktiv (HIGH)
- https://gitlab.com/api/v4/projects/crafty-controller%2Fcrafty-4/releases , v4.11.0 (16.09.2026) (HIGH)
- https://api.github.com/repos/pelican-dev/panel/releases , v1.0.0-rc.1 (10.10.2026), kein Stable (HIGH)
- https://git.medlab.host/Modpol/LuHost , LuHost-Featureset, Projektstatus (MEDIUM)
- https://registry.npmjs.org/@nextcloud/vue/latest , 9.13.1, Vue ^3.5.18 (HIGH)
- https://raw.githubusercontent.com/cloud-py-api/ui_example/main/package.json , Beleg, dass das offizielle UI-Skeleton veraltet ist (Vue 2.7) (HIGH)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

- Quellcode-Kommentare und Docstrings IMMER auf Englisch (Owner-Entscheid 24.10.2026); Bestand wird im Zuge der i18n-Arbeit uebersetzt.
- Nutzersichtbare Texte: mehrsprachig DE/EN/FR (Owner-Entscheid 24.10.2026, D-25); deutsche Texte mit echten Umlauten, keine Em-Dashes, keine Emojis. Vor jeder Abnahme Umlaut-Audit ueber alle Texte.
- UI-Sprache folgt der Nextcloud-Kontosprache; Spieltexte (Mods) pro Welt, Standard = Sprache des anlegenden Verwalters (D-27).
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
