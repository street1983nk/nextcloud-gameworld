# Phase 1: Fundament - Research

**Researched:** 2026-10-19
**Domain:** Nextcloud-ExApp-Gerüst (nc_py_api async, AppAPI manual-install) plus Docker-Provisionierung gehärteter Luanti-5.17.0-Container über tecnativa/docker-socket-proxy
**Confidence:** HIGH (Provisioner-Kern empirisch auf dieser Maschine verifiziert), MEDIUM-HIGH (ExApp-UI-Registrierung, aus Quellcode und Findling-Muster)

## Summary

Der riskanteste Teil der Phase ist in dieser Research-Sitzung praktisch durchgespielt worden. Gegen einen lokal gestarteten `tecnativa/docker-socket-proxy:v0.5.0` mit nur `CONTAINERS=1 IMAGES=1 POST=1` (plus `VOLUMES=1` für das Löschen) hat docker-py 7.2.0 das offizielle Image `ghcr.io/luanti-org/luanti:5.17.0` gezogen, zwei Welten parallel auf eigenen UDP-Ports (30101, 30102) erzeugt, mit `cap_drop ALL`, `no-new-privileges`, `read_only`, `mem_limit = memswap_limit = 512m`, `pids_limit 128`, `nano_cpus 1e9` gestartet, per Archive-API Konfiguration und Spiel in ein benanntes Volume geschrieben, zurückgelesen, sauber gestoppt (SIGTERM, unter 1 s), neu gestartet und rückstandsfrei gelöscht. `exec` war durch den Proxy blockiert (403), eine Port-Kollision lieferte einen erkennbaren HTTP-500 mit "Bind for 0.0.0.0:... failed". [VERIFIED: Spike-Lauf 2026-10-19, Skripte im Scratchpad]

Die drei offenen Research-Flags aus der Roadmap sind damit entscheidbar: (1) **Daten-Ablage:** ein benanntes Volume pro Welt, beschrieben und gelesen über die Archive-API des (gestoppten oder nie gestarteten) Welt-Containers selbst. Ein Hilfscontainer ist nicht nötig, `put_archive` funktioniert auf einem frisch erzeugten, nie gestarteten Container und schreibt ins gemountete Volume. (2) **Image:** offizielles `ghcr.io/luanti-org/luanti:5.17.0` (alpine, User `minetest` UID 30000, amd64 und arm64, 27 MB, kein Spiel enthalten). Spiele kommen als im ExApp-Image mitgelieferte, gepinnte ContentDB-Zips per `put_archive` mit `uid=gid=30000` in `/var/lib/minetest/.minetest/games/`. (3) **Headless-Status:** Luanti schreibt bei jedem Join/Leave eine Zeile `... joins game. List of players: ...` bzw. `... leaves game. List of players: ...` ins Log; für Phase 2 reicht Log-Parsing über die Docker-Logs-API (CONTAINERS-Scope). Phase 1 braucht davon nichts außer einer Log-Rotation am Container.

Ein wichtiger Zusatzbefund für ZUGANG-01: Luanti erzwingt `default_password` serverseitig. Ist es gesetzt, muss sich jeder neue Spielername mit genau diesem Passwort per SRP anmelden, sonst entsteht kein Account [VERIFIED: luanti 5.17.0 src/network/serverpackethandler.cpp Z. 237-246]. Ein zufälliger "Weltschlüssel" pro Welt schließt damit schon in Phase 1 die LAN-Lücke bis zur Whitelist in Phase 3.

**Primary recommendation:** ExApp als Host-Prozess (Findling-Muster) gegen eine eigene Dev-Nextcloud 34.0.3 in Docker Desktop; Proxy im selben Compose-Projekt, nur auf `127.0.0.1:23750` publiziert; Provisioner als einziges Docker-Modul mit fest kodierter, gehärteter Container-Spec, benanntem Volume pro Welt, root-eigener schreibgeschützter `minetest.conf` und Labels `gameworld.*` inklusive Instanz-ID.

<user_constraints>
## User Constraints (kein CONTEXT.md vorhanden)

Für Phase 1 existiert kein `01-CONTEXT.md` (discuss-phase wurde nicht ausgeführt). Die folgenden Vorgaben stammen aus ROADMAP.md, STATE.md, REQUIREMENTS.md und CLAUDE.md und sind als gesetzt zu behandeln.

### Locked Decisions (aus Roadmap/State/CLAUDE.md)
- Luanti-first, Version-Pin 5.17.0 (nie `latest`/`master`, nie 5.16.0)
- Python-ExApp über AppAPI, nc_py_api 0.30.3 mit `AsyncNextcloudApp` (keine Sync-API)
- Sibling-Container über **tecnativa/docker-socket-proxy**, eng gescopt, dokumentiertes Compose-Snippet; nie roher Docker-Socket in der ExApp
- Je Welt ein Container mit eigenem UDP-Port; konservative Limits ohne Eltern-Einstellung (mem_limit = memswap_limit, pids-Limit, cap_drop ALL)
- Privat per Default: `server_announce` aus, keine leeren Passwörter, minimale Privilegien, keine "öffentlich machen"-Option irgendwo
- Fehlender Proxy wird per Setup-Check verständlich gemeldet
- Dev-Setup: manual-install plus Compose-Stack
- Frontend Vue 3 + @nextcloud/vue 9 + Vite, nicht das veraltete ui_example-Skeleton
- LAN zuerst, kein UPnP
- Owner-Regeln: Python-Gates ruff-Vollsatz + pyright basic + vulture lokal grün vor Commit; Commits nur als Owner, keine Claude-Trailer

### Claude's Discretion (in dieser Research entschieden, siehe unten)
- Welt-Daten-Ablage, Image-Wahl, Headless-Status (Research-Flags)
- Port-Range und Kollisionsstrategie, Label-Schema, SQLite-Schema, Dev-Topologie

### Deferred Ideas (OUT OF SCOPE für Phase 1)
- Presets/One-Click-UI, Reconciler, Status-Anzeige aus Docker (Phase 2)
- Whitelist-Mod, Einladungen, Rollen, Verbindungsinfo (Phase 3)
- Spielzeit (Phase 4), Backup/Restore (Phase 5), HaRP-Store-Installation (Phase 6)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WELT-04 | Mehrere Welten parallel (ein Container pro Welt) | Spike: zwei Container gleichzeitig `running` auf 30101/udp und 30102/udp; Port-Allokator + Kollisionsbehandlung (Abschnitt Pattern 4) |
| WELT-05 | Konservative Ressourcenlimits ohne Eltern-Einstellung | Spike: `Memory=MemorySwap=536870912`, `PidsLimit=128`, `NanoCpus=1e9`, `CapDrop=[ALL]`, `ReadonlyRootfs=true` im Inspect; Server startet damit (Leerlauf ca. 19 MB) |
| ZUGANG-01 | Privat per Default, kein server_announce, keine Öffentlich-Option | Gehärtetes conf-Template mit gegen 5.17.0 `minetest.conf.example` verifizierten Keys; root-eigene 0444-conf (Server kann sie nicht umschreiben); `default_password` als serverseitiger Weltschlüssel; Abnahme durch Zurücklesen per `get_archive` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Stack laut CLAUDE.md: nc_py_api 0.30.3 async, Python 3.13, FastAPI/uvicorn, docker-py 7.2.0 (sync, via `anyio.to_thread`), Luanti `ghcr.io/luanti-org/luanti:5.17.0`, @nextcloud/vue 9.13.1, Vite
- What NOT to use: DSP als Daemon für Neuinstallationen, Sync-`NextcloudApp`, ui_example als Frontend-Vorlage, roher Socket, Luanti `master`/`latest`, Minecraft-Anteile
- GSD-Workflow: Änderungen nur über GSD-Kommandos
- Globale Owner-Regeln (aus User-CLAUDE.md und Memory): deutsche Prosa mit echten Umlauten, Umlaute NIE in Code/URLs/YAML-Keys; keine Em-/En-Dashes; keine Emojis; Python-Qualitätsgates (ruff-Vollsatz, pyright basic mit `PYRIGHT_PYTHON_FORCE_VERSION=latest`, vulture) lokal grün vor Commit; Commits als `street1983nk <k.cherif@outlook.de>` ohne Claude-Trailer; parallel nur bei genug RAM

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| ExApp-Lifecycle (enabled, heartbeat, init) | API / Backend (ExApp, nc_py_api) | Nextcloud AppAPI | AppAPI ruft `/enabled`, `/heartbeat`, `/init`; nc_py_api `set_handlers` liefert sie |
| Top-Menü-Eintrag + UI-Script | Nextcloud AppAPI (TopMenuController) | Browser (Vue-Bundle) | AppAPI rendert `embedded.php` mit `<div id="content">`, lädt das per `set_script` registrierte JS über den Proxy |
| Welt-API (create/start/stop/delete) | API / Backend (FastAPI-Router) | - | Serverseitige Admin-Prüfung über Route-`access_level` ADMIN |
| Docker-Zugriff | Provisioner-Modul im Backend | tecnativa-Proxy | Einzige Stelle mit docker-py; Proxy filtert Pfade/Methoden |
| Welt-Daten (Map, Konfig, Spiel) | Docker-Volume pro Welt | Archive-API | Kein ExApp-Mount möglich; Volume überlebt Container-Neuerzeugung |
| Soll-Zustand (Welten, Ports, Schlüssel) | SQLite in `APP_PERSISTENT_STORAGE` | Docker-Labels | Überlebt ExApp-Updates; Labels machen Welten ohne DB wiederfindbar |
| Ist-Zustand (läuft/gestoppt) | Docker Engine | - | Quelle der Wahrheit, nie DB-Flag |
| Setup-Check Proxy | API / Backend | Browser (Anzeige) | Nebenwirkungsfreie Probe-Requests gegen den Proxy |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| nc-py-api[app] | 0.30.3 (11.08.2026) | AppAPI-Lifecycle, UI-Registrierung, Auth-Middleware | Offizielles Framework; bei Findling in Produktion [VERIFIED: PyPI + Findling uv.lock] |
| fastapi | 0.143.2 | HTTP-Backend | Findling-bewährter Pin; 0.146.0 ist erst seit 18.10.2026 draußen, nicht nötig [VERIFIED: PyPI] |
| uvicorn[standard] | 0.52.3 (Findling-Lock) bzw. 0.54.0 aktuell | ASGI-Server, von `run_app` genutzt | Kommt über `nc-py-api[app]` [VERIFIED: PyPI requires_dist] |
| docker | 7.2.0 (09.07.2026) | Engine-API-Client gegen den Proxy | Im Spike gegen API 1.54 / Engine 29.5.2 verifiziert [VERIFIED: Spike] |
| anyio | 4.14.x (transitiv) | `anyio.to_thread.run_sync` um sync docker-py | Kommt mit starlette |
| Python | 3.13 | Laufzeit | lokal 3.13.1 vorhanden |
| ghcr.io/luanti-org/luanti | 5.17.0, Digest `sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947` | Welt-Server | Offiziell, amd64 + arm64, non-root UID 30000 [VERIFIED: docker pull + manifest inspect] |
| tecnativa/docker-socket-proxy | v0.5.0 (27.07.2026), Digest `sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459` | Gescopter Engine-Zugang | Roadmap-Vorgabe; HAProxy 3.4.2-alpine [VERIFIED: Docker Hub API + Spike] |
| minetest_game (ContentDB Luanti/minetest_game) | Release 38214 vom 17.08.2026, Zip 3,16 MB | Spiel für die Phase-1-Welt | LGPL-2.1-or-later / CC-BY-SA-3.0; im ExApp-Image vendoren, per SHA256 pinnen [VERIFIED: ContentDB API] |

### Supporting (Frontend)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| vue | 3.5.44 | UI | immer |
| @nextcloud/vue | 9.13.1 | NC-Komponenten | immer; Peer-Deps: `@nextcloud/files ^4.1.0` (4.1.0), `@nextcloud/dialogs ^7.4.0` (7.5.0) mitinstallieren |
| vite | **7.3.7** (nicht 8.x) | Build | `@nextcloud/vite-config 2.5.4` verlangt Peer `vite ^7.3.6` [VERIFIED: npm view] |
| @nextcloud/vite-config | 2.5.4 | Build-Preset | bringt `@vitejs/plugin-vue ^6.0.7` mit |
| @nextcloud/axios / router / initial-state / l10n | 2.6.0 / 3.2.0 / 3.0.0 / 3.4.1 | NC-Integration | API-Calls, Initial State (API-Basis-URL) |

### Dev
| Tool | Version | Zweck |
|------|---------|-------|
| ruff / pyright / vulture | 0.17.1 / 1.1.414 / 2.16 (Findling-Pins) | Owner-Gates |
| pytest / pytest-asyncio | 9.1.1 / 1.4.0 | Tests |
| nextcloud Image | `nextcloud:34.0.3-apache` (lokal schon gezogen) | Dev-Instanz, gleiche Linie wie Findling |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| offizielles Luanti-Image | lscr.io/linuxserver/luanti | PUID/PGID-Komfort, aber s6-Init als root im Container (passt schlecht zu cap_drop ALL), anderes Layout `/config/.minetest`; offizielles Image läuft im Spike ohne jede Capability. Nicht nehmen |
| Spiel per put_archive pro Welt | eigenes abgeleitetes Image mit Spielen | Ein zweites Release-Artefakt; lohnt erst, wenn VoxeLibre (84 MB Zip) das Kopieren pro Welt zu langsam macht. Alternative für Phase 2: ein geteiltes, read-only gemountetes Volume `gameworld-games` |
| docker-py | aiodocker 0.27.0 | Nur für echtes Async-Log-Streaming; nicht in Phase 1 |

**Installation:**
```bash
uv add "nc-py-api[app]==0.30.3" "fastapi==0.143.2" "docker==7.2.0"
uv add --dev "ruff==0.17.1" "pyright==1.1.414" "vulture==2.16" "pytest==9.1.1" "pytest-asyncio==1.4.0"
npm install vue@3.5.44 @nextcloud/vue@9.13.1 @nextcloud/files@4.1.0 @nextcloud/dialogs@7.5.0 \
  @nextcloud/axios@2.6.0 @nextcloud/router@3.2.0 @nextcloud/initial-state@3.0.0 @nextcloud/l10n@3.4.1
npm install -D vite@7.3.7 @nextcloud/vite-config@2.5.4
```

## Package Legitimacy Audit

slopcheck 0.x (`slopcheck scan <pkg> --pkg <eco> --json`) lief für alle Pakete.

| Package | Registry | Age | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-------------|-----------|-------------|
| docker | PyPI | >10 J. | github.com/docker/docker-py | [OK] | Approved |
| nc-py-api | PyPI | ~3 J. | github.com/cloud-py-api/nc_py_api | [OK] (Info: Name endet auf "-api", etabliert) | Approved |
| fastapi | PyPI | >6 J. | github.com/fastapi/fastapi | [OK] | Approved |
| uvicorn | PyPI | >6 J. | github.com/encode/uvicorn | [OK] | Approved |
| vue, vite, @vitejs/plugin-vue | npm | >5 J. | vuejs / vitejs | [OK] | Approved |
| @nextcloud/vue, vite-config, axios, router, initial-state, l10n | npm | mehrjährig | github.com/nextcloud-libraries | [OK] | Approved |

Kein npm-Paket hat ein `postinstall`-Script [VERIFIED: npm view scripts.postinstall]. Container-Images: Luanti offiziell (luanti-org), tecnativa (Tecnativa GmbH, Docker Hub, aktive Releases).

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram (Dev-Topologie Phase 1)

```
Browser (Admin)
   |  http://localhost:8091/index.php/apps/app_api/embedded/gameworld/gameworld
   v
[Nextcloud 34.0.3 Container]  --AppAPI proxy /apps/app_api/proxy/gameworld/*-->  
   |  (manual-install Daemon, host.docker.internal:10040)                        |
   |                                                                            v
   |                                         [Gameworld ExApp, Host-Prozess Windows, uv run]
   |  <--- OCS (top-menu, scripts, init-state) ----  |  FastAPI: /enabled /heartbeat /init
   |                                                 |  /api/setup-check /api/worlds...
   |                                                 |  SQLite in APP_PERSISTENT_STORAGE (.dev/storage)
   |                                                 v
   |                                   Provisioner (docker-py, anyio.to_thread)
   |                                                 |  tcp://127.0.0.1:23750 (nur Loopback!)
   |                                                 v
   |                               [gameworld-docker-proxy (tecnativa v0.5.0)]
   |                                 Allowlist: CONTAINERS IMAGES POST VOLUMES (+PING VERSION EVENTS)
   |                                                 |  /var/run/docker.sock
   |                                                 v
   |                                       Docker Desktop Engine (WSL2)
   |                     +---------------------------+---------------------------+
   |                     v                                                       v
   |      [gameworld-<inst>-<world1>]  Vol gameworld-<inst>-<world1>   [gameworld-<inst>-<world2>] ...
   |       0.0.0.0:30000/udp -> 30000/udp                               0.0.0.0:30001/udp
   v
Luanti-Client (LAN) ----UDP----> Host-IP:3000x
```

### Recommended Project Structure
```
gameworld/
├── appinfo/info.xml            # ExApp-Manifest: routes (js/css/img USER, api ADMIN), env vars, min 32 max 34
├── pyproject.toml / uv.lock
├── src/gameworld/
│   ├── main.py                 # FastAPI + lifespan(set_handlers) + AppAPIAuthMiddleware + run_app
│   ├── lifecycle.py            # async enabled_handler: top_menu + set_script + initial state
│   ├── config.py               # env: GAMEWORLD_DOCKER_URL, Port-Range, Storage-Root
│   ├── api/                    # Router: setup_check.py, worlds.py
│   ├── provisioner/
│   │   ├── client.py           # einzige docker-py-Stelle, alle Calls über to_thread
│   │   ├── spec.py             # gehärtete Container-Spec (pure Funktion, testbar ohne Docker)
│   │   ├── luanti_conf.py      # minetest.conf + world.mt Rendering (pure)
│   │   ├── archive.py          # tar-Bau mit uid/gid 30000, Spiel-Zip -> tar
│   │   └── setup_check.py      # Proxy-Probes
│   └── worlds/
│       ├── store.py            # sqlite3, Schema-Migration idempotent
│       ├── ports.py            # Allokator
│       └── service.py          # Saga create/start/stop/delete
├── vendor/games/minetest_game-38214.zip (+ SHA256SUMS, LICENSE-Hinweis)
├── frontend/                   # Vite-Projekt, Build-Output nach ../js/
├── js/ img/                    # von map_app_static gemountet (cwd oder eine Ebene höher)
├── scripts/dev/compose.yaml    # NC 34.0.3 + gameworld-docker-proxy
├── scripts/dev/register-exapp.sh
├── docs/install.md             # Proxy-Compose-Snippet für Admins
└── tests/
```

### Pattern 1: AsyncNextcloudApp-Skelett mit Top-Menü
**What:** `set_handlers` im Lifespan, async `enabled_handler`, Top-Menü und Script registrieren, beim Disable wieder abmelden.
```python
# Source: nc_py_api 0.30.3 ex_app/integration_fastapi.py + ui/top_menu.py (lokal gelesen),
#         cloud-py-api/ui_example lib/main.py Z. 199-258
from contextlib import asynccontextmanager
from fastapi import FastAPI
from nc_py_api import AsyncNextcloudApp
from nc_py_api.ex_app import AppAPIAuthMiddleware, run_app, set_handlers

@asynccontextmanager
async def lifespan(app: FastAPI):
    set_handlers(app, enabled_handler)   # registriert PUT /enabled, GET /heartbeat, POST /init, mountet js/css/img/l10n
    yield

APP = FastAPI(lifespan=lifespan)
APP.add_middleware(AppAPIAuthMiddleware)  # prüft AUTHORIZATION-APP-API; /heartbeat ist ausgenommen

async def enabled_handler(enabled: bool, nc: AsyncNextcloudApp) -> str:
    if enabled:
        await nc.ui.resources.set_initial_state("top_menu", "gameworld", "gameworld_config", {"apiBase": api_base()})
        await nc.ui.resources.set_script("top_menu", "gameworld", "js/gameworld-main")  # ohne .js
        await nc.ui.top_menu.register("gameworld", "Gameworld", "img/app.svg", admin_required=True)
    else:
        await nc.ui.top_menu.unregister("gameworld")
        await nc.ui.resources.delete_script("top_menu", "gameworld", "js/gameworld-main")
    return ""   # leerer String = Erfolg; Fehlertext sonst

if __name__ == "__main__":
    run_app("gameworld.main:APP", log_level="info")  # TCP APP_HOST:APP_PORT, unter HaRP Unix-Socket
```
Frontend-Einstieg: `createApp(App).mount('#content')`, denn AppAPIs `templates/embedded.php` besteht nur aus `<div id="content"></div>` [VERIFIED: github.com/nextcloud/app_api templates/embedded.php]. Seiten-URL: `/index.php/apps/app_api/embedded/gameworld/gameworld`. `admin_required=True` versteckt nur die Seite (TopMenuController liefert Nicht-Admins 404); die API-Routen brauchen zusätzlich `access_level` ADMIN in info.xml.

### Pattern 2: Gehärtete Welt-Container-Spec (empirisch verifiziert)
```python
# Source: Spike 2026-10-19 gegen Docker 29.5.2 via tecnativa v0.5.0, alle Werte im Inspect bestätigt
from docker.types import Mount

LUANTI_IMAGE = "ghcr.io/luanti-org/luanti@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"  # = 5.17.0

def world_spec(inst: str, wid: str, host_port: int) -> dict:
    name = f"gameworld-{inst}-{wid}"
    return dict(
        image=LUANTI_IMAGE,
        name=name,
        command=["--config", "/var/lib/minetest/minetest.conf",
                 "--world", "/var/lib/minetest/.minetest/worlds/world"],
        user="30000:30000",
        labels={"gameworld.managed": "true", "gameworld.instance": inst, "gameworld.world_id": wid,
                "gameworld.schema": "1", "gameworld.engine": "luanti", "gameworld.engine_version": "5.17.0",
                "gameworld.port": str(host_port)},
        mounts=[Mount(target="/var/lib/minetest", source=name, type="volume")],
        tmpfs={"/etc/minetest": "size=1m", "/tmp": "size=16m"},   # verhindert anonyme Volumes aus VOLUME-Direktive
        ports={"30000/udp": ("0.0.0.0", host_port)},              # intern immer 30000, extern variabel
        mem_limit="512m", memswap_limit="512m", pids_limit=128, nano_cpus=1_000_000_000,
        cap_drop=["ALL"], security_opt=["no-new-privileges:true"], read_only=True,
        restart_policy={"Name": "no"},                             # Phase 2: Reconciler startet Soll-laufende Welten
        log_config={"Type": "json-file", "Config": {"max-size": "5m", "max-file": "2"}},
    )
```
Ablauf: `containers.create(**spec)` (legt benanntes Volume implizit an, kein VOLUMES-Scope nötig), dann `put_archive("/var/lib/minetest", tar)` auf dem nie gestarteten Container, dann `start()`. Stop mit `stop(timeout=30)`; Löschen `remove(v=True)` plus `volumes.get(name).remove()` (braucht VOLUMES=1).

### Pattern 3: Archive-Tar mit Luanti-UID
```python
# Source: Spike; Tar-Header-UID/GID werden von PUT /containers/{id}/archive übernommen (geprüft: uid 30000 bzw. 0 kamen so an)
def entry(tf, name, data=None, uid=30000, mode=0o644):
    ti = tarfile.TarInfo(name); ti.uid = ti.gid = uid
    if data is None:
        ti.type, ti.mode = tarfile.DIRTYPE, 0o755; tf.addfile(ti)
    else:
        ti.size, ti.mode = len(data), mode; tf.addfile(ti, io.BytesIO(data))
# Inhalt: .minetest/, .minetest/worlds/world/world.mt (uid 30000),
#         .minetest/games/minetest_game/... (uid 30000, aus vendor-Zip),
#         minetest.conf (uid 0, mode 0o444: Server liest, kann nicht umschreiben)
```

### Pattern 4: UDP-Port-Allokation
- Range als Konfiguration mit Default **30000-30019** (Luanti-Standardport zuerst; 20 Welten reichen für Familien, deutlich über dem RAM-Limit eines Heimservers). Als env var `GAMEWORLD_PORT_RANGE` in info.xml, Admin-änderbar.
- Vergabe: kleinster freier Port, der weder in der DB (`worlds.port` UNIQUE) noch als `gameworld.port`-Label/`HostConfig.PortBindings` an einem Container mit `gameworld.managed=true` hängt.
- Belegung durch Fremdprozesse ist aus dem Container heraus nicht prüfbar. Deshalb: Port wird erst beim **Start** gebunden; `APIError` mit Status 500 und Text "port is already allocated" bzw. "Bind for 0.0.0.0:<port> failed" [VERIFIED: Spike] führt zu: Container + Volume des Versuchs **nicht** löschen, sondern Container mit nächstem Port neu erzeugen (Volume bleibt, Daten bleiben), maximal 3 Versuche, dann verständlicher Fehler. Der Port ist Teil der Container-Spec und nur durch Neuerzeugung änderbar.
- Host-Adresse für Spieler (Phase 3): aus dem Container nicht ermittelbar. Default = Hostname aus `NEXTCLOUD_URL`/`overwrite.cli.url`, plus Admin-Override-Setting. In Phase 1 nur das Setting anlegen, nicht anzeigen. [ASSUMED]

### Pattern 5: Setup-Check ohne Nebenwirkungen
Probes gegen `GAMEWORLD_DOCKER_URL`, alle im Spike gemessen [VERIFIED]:

| Probe | Erwartet | Bedeutung bei Abweichung |
|-------|----------|--------------------------|
| `GET /_ping` | 200 | Verbindungsfehler/DNS: "Docker-Proxy nicht erreichbar" |
| `GET /version` | 200, `ApiVersion >= 1.44` | docker-py `version="auto"` braucht das |
| `GET /containers/json?filters={"label":["gameworld.managed=true"]}` | 200 | 403: `CONTAINERS=1` fehlt |
| `POST /containers/gameworld-probe-nonexistent/stop` | 404 | 403: `POST=1` fehlt |
| `GET /images/json` | 200 | 403: `IMAGES=1` fehlt |
| `DELETE /volumes/gameworld-probe-nonexistent` | 404 | 403: `VOLUMES=1` fehlt (Löschen unmöglich) |
| `POST /exec/gameworld-probe-nonexistent/start` | **403** | 404: `EXEC` ist offen, Warnung "Proxy zu weit offen" |
| `GET /info` | **403** | 200: `INFO`/`SYSTEM` offen, Hinweis |

### Anti-Patterns to Avoid
- **Konfiguration nach `/etc/minetest` legen:** Das Image deklariert `VOLUME /etc/minetest/`; ohne tmpfs-Overlay entsteht pro Container ein anonymes Volume, das beim Löschen ohne `v=True` verwaist. Config ins Welt-Volume, `/etc/minetest` als tmpfs.
- **`restart_policy: always`/`unless-stopped` in Phase 1:** OOM-Crash-Loop auf dem Heimserver; Start-Entscheid gehört dem Reconciler (Phase 2).
- **Container-Namen ohne Instanz-Präfix:** Auf einem Docker-Host laufen oft mehrere Nextclouds (auf dieser Maschine schon zwei). Findling-Lehre DI-06.1-22: Namen und Filter immer mit Instanz-ID.
- **Port-Prüfung durch Bind-Versuch im ExApp-Prozess:** prüft das Netz des ExApp-Containers, nicht den Host.
- **Status aus SQLite anzeigen:** immer `container.reload()`/`inspect`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Docker-API-Zugriffskontrolle | eigener HTTP-Filter | tecnativa/docker-socket-proxy v0.5.0 | Gepflegte HAProxy-Allowlist |
| Docker-HTTP-Client | httpx-Wrapper um Engine-API | docker-py 7.2.0 | put/get_archive, stats, logs, Fehlerobjekte fertig |
| AppAPI-Auth | eigene Header-Prüfung | `AppAPIAuthMiddleware` | Signatur-/Versionslogik ist nc_py_api-Sache |
| Uvicorn-Bind-Logik TCP vs. HaRP-Socket | eigener Start | `run_app` | wechselt bei `HP_SHARED_KEY` auf Unix-Socket |
| Static-Mount js/css/img | eigene StaticFiles | `set_handlers(map_app_static=True)` | sucht in cwd und eine Ebene höher |
| Zufallsschlüssel | eigene RNG | `secrets.token_urlsafe` | kryptografisch |
| Weltzugangssperre Phase 1 | eigener Join-Mod | Luanti `default_password` | im Kern serverseitig per SRP erzwungen |

## Runtime State Inventory

Nicht zutreffend (Greenfield-Phase, kein Rename/Refactor). Hinweis für die Dev-Maschine: auf Docker Desktop laufen bereits `findling-nextcloud` (8090), `findling-harp-nextcloud` (8096), `findling-harp-proxy` (8780/8782) und `nc_app_findling_backend`. Gameworld-Dev darf diese nicht berühren: eigener Compose-Projektname `gameworld-dev`, eigene Ports, Labels mit Instanz-ID.

## Common Pitfalls

### Pitfall 1: Proxy-Allowlist ist pfadbasiert, nicht inhaltsbasiert
**What goes wrong:** Mit `CONTAINERS=1` + `POST=1` erlaubt die Regel `^/containers` jeden Container-Pfad, also auch `create` mit `Privileged`/Host-Binds und Stop/Remove fremder Container (auch Nextcloud). `ALLOW_START/STOP/RESTARTS` sind bei `CONTAINERS=1` wirkungslos, weil die Containers-Regel schon greift [VERIFIED: haproxy.cfg + Spike: start/stop ohne ALLOW_* erfolgreich]. `POST /containers/{id}/exec` (Exec anlegen) geht durch (400 vom Daemon), nur `POST /exec/{id}/start` ist mit `EXEC=0` blockiert (403).
**How to avoid:** Proxy nie auf einem Host-Port außer Loopback (Dev) publizieren; Provisioner als einzige Docker-Stelle mit fest kodierter Spec, keine durchgereichten Nutzerwerte; jede Operation vor Ausführung auf `gameworld.managed=true` + eigene `gameworld.instance` prüfen. In privacy.md/Store-Listing (Phase 6) ehrlich benennen.
**Warning signs:** docker-py-Aufrufe außerhalb `provisioner/`; Operationen per Name statt per Label-geprüfter ID.

### Pitfall 2: Proxy-Netz in der Store-Topologie
**What goes wrong:** Unter HaRP hängt AppAPI den ExApp-Container in das Netz des Deploy-Daemons (`--net`, lokal belegt: `nc_app_findling_backend` in `findling-harp_default`) [VERIFIED: docker inspect]. Ein privates `gameworld-net` nur für ExApp + Proxy ist damit nicht deklarierbar; der Proxy muss ins Daemon-Netz, wo auch Nextcloud und andere ExApps ihn erreichen.
**How to avoid:** Phase 1 (manual-install, Host-Prozess) ist davon nicht betroffen. Für das Compose-Snippet in `docs/install.md` jetzt schon das Daemon-Netz als Platzhalter vorsehen und das Restrisiko dokumentieren; Entscheid über Härtung in Phase 6 (siehe Open Questions).

### Pitfall 3: Spiel fehlt im Image
**What goes wrong:** Das offizielle Image enthält kein Spiel; ohne `games/` startet der Server nicht mit `gameid=minetest`.
**How to avoid:** minetest_game-Zip im ExApp-Repo vendoren (Lizenz LGPL-2.1+/CC-BY-SA-3.0 im Repo mitführen), SHA256 im Code prüfen, beim Erzeugen per Tar in `.minetest/games/` legen. Keine ContentDB-Downloads zur Laufzeit (Privacy: keine externen Calls).

### Pitfall 4: Port-Kollision erst beim Start
**What goes wrong:** `create` mit belegtem Host-Port gelingt, erst `start` scheitert mit 500 [VERIFIED: Spike].
**How to avoid:** Saga: Status `creating -> starting -> running | failed`; bei Bind-Fehler Container neu mit nächstem Port, Volume behalten.

### Pitfall 5: Windows-Host-Prozess plus Docker-Engine in WSL2
**What goes wrong:** Die ExApp läuft auf Windows, Docker in WSL2. Nextcloud im Container erreicht die ExApp nur über `host.docker.internal` und nur, wenn sie auf `0.0.0.0` bindet (Findling-Lehre); `localhost` im NC-Container ist der Container selbst.
**How to avoid:** Findlings `register-exapp.sh` 1:1 übernehmen (Secret pro Lauf in `.dev/exapp.secret`, Routen aus info.xml parsen, `--wait-finish`), nur IDs/Ports tauschen. Git-Bash: bei `docker run -v /var/run/docker.sock:...` `MSYS_NO_PATHCONV=1` setzen, sonst verbiegt MSYS den Pfad [VERIFIED: in dieser Sitzung genutzt]. In compose.yaml ist das kein Problem.

### Pitfall 6: Vite-Major-Mismatch
**What goes wrong:** `npm install vite` holt 8.3.4, `@nextcloud/vite-config 2.5.4` verlangt `vite ^7.3.6` [VERIFIED: npm view peerDependencies].
**How to avoid:** `vite@7.3.7` exakt pinnen.

### Pitfall 7: Sync-Handler-Deprecation
`set_handlers` warnt bei sync `enabled_handler` und entfernt das in 0.31.0 [VERIFIED: nc_py_api 0.30.3 Quelltext]. Handler immer `async def`.

### Pitfall 8: Docker-Logs ohne Rotation
Ohne `log_config` wächst das json-file-Log einer langen Welt unbegrenzt auf dem Heimserver. `max-size 5m, max-file 2` setzen (im Spike akzeptiert). Phase-2-Log-Parsing liest über `container.logs(since=...)`.

## Code Examples

### Gehärtetes minetest.conf-Template (Keys gegen 5.17.0 minetest.conf.example verifiziert)
```ini
# Source: github.com/luanti-org/luanti/blob/5.17.0/minetest.conf.example (Zeilen 1181-1281, 3017-3042)
server_name = <Weltname, nur ASCII-sicher escapen>
server_announce = false            # Default false, trotzdem explizit
server_announce_send_players = false
serverlist_url =                   # leer: keine Serverliste ansprechbar
disallow_empty_password = true     # Default false!
default_password = <secrets.token_urlsafe(9), pro Welt>   # Weltschlüssel, serverseitig per SRP erzwungen
default_privs = interact, shout    # Default; kein fly/fast/teleport/give
basic_privs = interact, shout
max_users = 8                      # Default 15
enable_rollback_recording = false
secure.enable_security = true
secure.trusted_mods =
secure.http_mods =
enable_client_modding = false
update_information_url =           # keine externen Calls
port = 30000                       # intern fest; extern via Port-Mapping
```
Bewusst **nicht** gesetzt: `name` (leer = kein Spieler erhält automatisch alle Privilegien). In Phase 1 bleiben `creative_mode`/`enable_damage` Spiel-Defaults; Presets sind Phase 2. Wert-Escaping: Luanti-conf ist `key = value` zeilenweise, Weltnamen daher auf eine Zeile ohne Steuerzeichen normalisieren (sonst Key-Injection wie `\nserver_announce = true`).

### world.mt (SQLite erzwungen)
```ini
# Source: Spike; world.mt nach Server-Stop unverändert, map.sqlite + mod_storage.sqlite entstanden
gameid = minetest
backend = sqlite3
player_backend = sqlite3
auth_backend = sqlite3
mod_storage_backend = sqlite3
```

### SQLite-Schema Phase 1 (in `$APP_PERSISTENT_STORAGE/gameworld.sqlite3`)
```sql
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- schema_version, instance_id
CREATE TABLE IF NOT EXISTS worlds (
  id TEXT PRIMARY KEY,                 -- uuid4 hex, 12 Zeichen reichen für Namen
  name TEXT NOT NULL,
  port INTEGER NOT NULL UNIQUE,
  container_name TEXT NOT NULL UNIQUE,
  volume_name TEXT NOT NULL UNIQUE,
  world_key TEXT NOT NULL,             -- default_password
  engine_version TEXT NOT NULL,        -- '5.17.0'
  desired_state TEXT NOT NULL,         -- 'running' | 'stopped' | 'deleted'
  op_state TEXT NOT NULL,              -- 'creating' | 'ready' | 'failed' (Saga)
  last_error TEXT,
  created_at TEXT NOT NULL
);
```
`instance_id`: beim ersten Start zufällig erzeugt und in `meta` gespeichert (8 Hex-Zeichen), geht in Container-/Volume-Namen und Label `gameworld.instance`. Dev-Fallback ohne `APP_PERSISTENT_STORAGE`: `.dev/storage` wie bei Findling.

### docker-py sync in FastAPI
```python
import anyio, docker
_client = docker.DockerClient(base_url=settings.docker_url, version="auto", timeout=30)
async def start_world(cid: str) -> None:
    await anyio.to_thread.run_sync(lambda: _client.containers.get(cid).start())
# stop(timeout=30): docker-py addiert den Stop-Timeout zum HTTP-Timeout selbst [ASSUMED, Training-Wissen]
```

### Dev-Compose (scripts/dev/compose.yaml)
```yaml
name: gameworld-dev
services:
  app:
    image: nextcloud:34.0.3-apache
    ports: ["${GAMEWORLD_NC_PORT:-8091}:80"]
    environment:
      SQLITE_DATABASE: nextcloud
      NEXTCLOUD_ADMIN_USER: admin
      NEXTCLOUD_ADMIN_PASSWORD: gameworld-dev-admin
      NEXTCLOUD_TRUSTED_DOMAINS: "localhost host.docker.internal"
    extra_hosts: ["host.docker.internal:host-gateway"]
    volumes: [nextcloud:/var/www/html]
  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0
    environment: {CONTAINERS: 1, IMAGES: 1, POST: 1, VOLUMES: 1}   # alles andere bleibt 0; PING/VERSION/EVENTS sind Image-Default 1
    volumes: ["/var/run/docker.sock:/var/run/docker.sock:ro"]
    ports: ["127.0.0.1:23750:2375"]   # NUR Dev und nur Loopback, weil die ExApp als Windows-Prozess läuft
volumes: {nextcloud: {}}
```
Der Proxy lief im Spike auf Docker Desktop ohne `--privileged`. `:ro` am Socket verhindert keine API-Schreibzugriffe (nur das Löschen/Ersetzen der Socket-Datei), ist aber übliche Praxis. Freie Ports auf dieser Maschine geprüft: 8091, 10040 (ExApp), 23750, 30000-30019.

Registrierung (Findling-Muster, `register-exapp.sh` adaptiert): `occ app_api:daemon:register --net host manual_install "Manual Install" manual-install http host.docker.internal http://localhost:8091`, dann `occ app_api:app:register gameworld manual_install --json-info '{"id":"gameworld",...,"port":10040,"routes":[...aus info.xml...]}' --force-scopes --wait-finish`. ExApp-Prozess mit `APP_ID=gameworld APP_SECRET=<zufall> APP_PORT=10040 APP_HOST=0.0.0.0 APP_VERSION=<info.xml> APP_PERSISTENT_STORAGE=.dev/storage NEXTCLOUD_URL=http://localhost:8091 GAMEWORLD_DOCKER_URL=tcp://127.0.0.1:23750`.

### info.xml-Kern
```xml
<dependencies><nextcloud min-version="32" max-version="34"/></dependencies>
<external-app>
  <docker-install><registry>ghcr.io</registry><image>street1983nk/gameworld</image><image-tag>0.1.0</image-tag></docker-install>
  <routes>
    <route><url>js\/.*</url><verb>GET</verb><access_level>ADMIN</access_level><headers_to_exclude>[]</headers_to_exclude></route>
    <route><url>img\/.*</url><verb>GET</verb><access_level>ADMIN</access_level><headers_to_exclude>[]</headers_to_exclude></route>
    <route><url>api\/.*</url><verb>GET,POST,DELETE</verb><access_level>ADMIN</access_level><headers_to_exclude>[]</headers_to_exclude></route>
  </routes>
  <environment-variables>
    <variable><name>GAMEWORLD_DOCKER_URL</name><display-name>Docker proxy URL</display-name>
      <description>tcp://gameworld-docker-proxy:2375</description><default>tcp://gameworld-docker-proxy:2375</default></variable>
    <variable><name>GAMEWORLD_PORT_RANGE</name><display-name>UDP port range</display-name><default>30000-30019</default></variable>
  </environment-variables>
</external-app>
```
`<environment-variables>` ist in Findlings info.xml produktiv im Einsatz [VERIFIED: nextcloud-search/backend/appinfo/info.xml]; das genaue `<default>`-Element vor dem Schreiben gegen Findlings Datei bzw. info.xsd prüfen [ASSUMED]. Phase 1: alles ADMIN; Phase 3 öffnet einzelne Routen für USER mit Rollenprüfung.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ghcr.io/minetest/minetest` | `ghcr.io/luanti-org/luanti` | Umbenennung 2024 | neuer Image-Pfad |
| Image mit minetest_game | Image ohne Spiel | seit 5.8 | Spiel selbst einspielen |
| Sync `NextcloudApp` | `AsyncNextcloudApp` | nc_py_api 0.30, Entfernung 0.31 | nur async |
| DSP als Deploy-Daemon | HaRP | NC 32, DSP-Entfernung NC 35 | Phase 6 relevant |
| ui_example (Vue 2, webpack) | Vue 3 + @nextcloud/vue 9 + Vite 7 | 2025/2026 | eigenes Frontend-Gerüst |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Default-Hostadresse für Spieler aus `NEXTCLOUD_URL` ableitbar, plus Admin-Override | Pattern 4 | Phase 3 zeigt falsche Adresse; nur Setting-Default betroffen |
| A2 | docker-py addiert Stop-Timeout zum HTTP-Timeout | Code Examples | Stop bricht clientseitig ab; mit `timeout=60` am Client absichern |
| A3 | `<default>` in info.xml `<environment-variables>` | info.xml-Kern | Registrierung lehnt Datei ab; gegen info.xsd/Findling prüfen |
| A4 | Speicher-Default 512 MB reicht für minetest_game mit 2 bis 4 Kindern | Pattern 2 | OOM bei großer Map; empirisch mit Spielern kalibrieren, VoxeLibre in Phase 2 eher 1 GB |
| A5 | API-Basis-URL des Frontends: unter manual-install `/apps/app_api/proxy/gameworld`, unter HaRP `/exapps/gameworld`; per Initial State vom Backend übergeben | Pattern 1 | Frontend-Calls 404 nach Phase-6-Umstieg; Initial-State-Lösung kapselt es |
| A6 | Docker Desktop leitet publizierte UDP-Ports an das LAN weiter, sofern die Windows-Firewall es zulässt | Environment | LAN-Join-Test auf der Dev-Maschine scheitert; Join auf 127.0.0.1 testen |

## Open Questions (RESOLVED)

1. **Proxy-Netz unter HaRP (Phase 6, aber Snippet-Platzhalter jetzt)** (RESOLVED für Phase 1: Snippet mit Daemon-Netz-Platzhalter und Restrisiko-Hinweis in docs/install.md, Plan 01-04; Alternativen wie eine Quell-Allowlist sind in die Phase-6-Research verschoben)
   - What we know: ExApp-Container landen im Daemon-Netz; tecnativa hat weder Auth noch Quell-IP-Filter.
   - What's unclear: ob ein Admin-freundlicher Weg existiert, den Proxy nur für `nc_app_gameworld` erreichbar zu machen.
   - Recommendation: Phase 1 dokumentiert das Snippet mit Daemon-Netz und Restrisiko-Hinweis; Phase-6-Research prüft Alternativen (z. B. Proxy mit Quell-Allowlist) gegen die Roadmap-Vorgabe tecnativa.
2. **Spiele-Ablage ab VoxeLibre (84 MB)** (RESOLVED für Phase 1: minetest_game wird pro Welt ins Volume kopiert, Plan 01-01 archive.py; Entscheid Kopie vs. geteiltes read-only-Volume in Phase 2 verschoben)
   - Recommendation: Phase 1 kopiert minetest_game (3 MB) pro Welt; Phase 2 entscheidet zwischen Kopie und geteiltem read-only `gameworld-games`-Volume.
3. **Spielerliste (Phase 2)** (RESOLVED: nicht Phase-1-Umfang, in Phase 2 verschoben; Empfehlung unten bleibt Ausgangspunkt)
   - What we know: Log-Zeilen "joins game. List of players:" / "leaves game." / "times out." [VERIFIED: server.cpp Z. 1311, 3178]; Prometheus-Gauge `minetest_core_player_number` existiert, lauscht aber nur auf `127.0.0.1:30000/tcp` im Container.
   - Recommendation: Log-Parsing der letzten "List of players"-Zeile seit Containerstart; falls zu fragil, kleiner Lua-Mod, der `players.json` ins Welt-Dir schreibt (lesbar per `get_archive`, ohne EXEC).
4. **Restart-Policy nach Host-Reboot (Phase 2)** (RESOLVED für Phase 1: restart_policy `no` in world_spec, Plan 01-01; Reconciler und AppAPI-Reboot-Bestätigung in Phase 2 verschoben): Empfehlung `no` plus Reconciler-Start beim ExApp-Start; bestätigen, dass AppAPI den ExApp-Container selbst nach Reboot hochfährt.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Desktop (WSL2) | alles | ✓ | Engine 29.5.2, API 1.54, 8 GB RAM, 12 CPUs | - |
| Python | ExApp | ✓ | 3.13.1 | - |
| uv | Python-Deps | ✓ | 0.11.7 | - |
| Node | Frontend-Build | ✓ | 22.21.0 | - |
| nextcloud:34.0.3-apache | Dev-NC | ✓ (lokal gezogen) | 34.0.3 | - |
| ghcr.io/luanti-org/luanti:5.17.0 | Welten | ✓ (gezogen) | 5.17.0 | - |
| tecnativa/docker-socket-proxy:v0.5.0 | Proxy | ✓ (gezogen) | v0.5.0 | - |
| Luanti-Client | manueller Join-Test | ✗ | - | Client installieren (luanti.org) oder Abnahme per Log "listening on" + Inspect |
| PHP/composer auf Host | - | ✗ | - | nicht nötig, occ läuft im Container |

**Missing dependencies with no fallback:** keine.
**Missing dependencies with fallback:** Luanti-Client (für echten UDP-Join, optional in Phase 1).

RAM-Lage: die laufenden Findling-Container belegen ca. 600 MB; eine Gameworld-Dev-NC plus zwei Welten (je ca. 20 MB Leerlauf, Limit 512 MB) passen.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | AppAPI-Signatur via `AppAPIAuthMiddleware`; Nextcloud-Login |
| V3 Session Management | no | Nextcloud-Session, keine eigene |
| V4 Access Control | yes | info.xml `access_level` ADMIN für alle Phase-1-Routen; Top-Menü `admin_required=True`; Provisioner prüft `gameworld.instance` vor jeder Operation |
| V5 Input Validation | yes | pydantic-Modelle; Weltname: Länge begrenzen, Steuerzeichen/Zeilenumbrüche entfernen (conf-Injection); IDs nur aus App erzeugt |
| V6 Cryptography | yes | `secrets` für APP-Secret (Dev-Skript) und Weltschlüssel; nichts selbst gebaut |
| V12 Files | yes | Tar nur aus App-Inhalten; keine Nutzerpfade im Tar |
| V14 Config | yes | Image per Digest gepinnt; Proxy-Flags minimal; Proxy nie öffentlich |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Docker-API-Missbrauch (privilegierter Container über Proxy) | Elevation of Privilege | Proxy nur Loopback/privates Netz; fest kodierte Spec; keine Nutzerwerte in Spec außer validiertem Namen |
| conf-Key-Injection über Weltnamen | Tampering | Einzeilig normalisieren, Whitelist-Zeichen, Länge <= 40 |
| Fremd-Join im LAN vor Phase 3 | Spoofing | `default_password` als Weltschlüssel, `disallow_empty_password = true` |
| Serverlisten-Exposition | Information Disclosure | `server_announce = false`, `serverlist_url =` leer, conf root-eigen 0444 |
| Container-Ausbruch | Elevation of Privilege | non-root UID 30000, `cap_drop ALL`, `no-new-privileges`, `read_only`, keine Host-Binds |
| Ressourcen-Erschöpfung | Denial of Service | mem = memswap 512 MB, pids 128, 1 CPU, Log-Rotation, Restart-Policy `no` |
| Fremde Container stoppen/löschen | Tampering | Label- und Instanz-Prüfung vor jeder Mutation |

## Sources

### Primary (HIGH confidence)
- Empirischer Spike 2026-10-19 auf dieser Maschine (docker-py 7.2.0, tecnativa v0.5.0, Luanti 5.17.0, Docker 29.5.2): Pull, Create, put_archive, Limits, parallele Welten, Exec-Sperre, Port-Kollision, Stop/Restart, conf-Rücklesen, Proxy-Probe-Codes
- https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/Dockerfile (UID 30000, VOLUMEs, kein Spiel, Prometheus-Build)
- https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/minetest.conf.example (alle Keys)
- luanti 5.17.0 `src/server.cpp` (Join/Leave-Logzeilen, Metriken), `src/network/serverpackethandler.cpp` (default_password, disallow_empty_password)
- https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/doc/docker_server.md
- Tecnativa/docker-socket-proxy README, haproxy.cfg, Dockerfile (master) + Docker-Hub-Tags-API
- nc_py_api 0.30.3 Quelltext (lokal in Findling-venv): `set_handlers`, `run_app`, `_AsyncUiTopMenuAPI`, `_AsyncUiResources`
- github.com/nextcloud/app_api: `templates/embedded.php`, `lib/Controller/TopMenuController.php`, `appinfo/routes.php`
- github.com/cloud-py-api/ui_example: `lib/main.py`, `appinfo/info.xml`
- ContentDB API (minetest_game Release 38214, VoxeLibre 0.92.4 Größe, Lizenzen)
- Findling-Repo lokal: `scripts/dev/compose.yaml`, `register-exapp.sh`, `compose-harp.yaml`, `docs/dev-setup.md`, `backend/appinfo/info.xml`, `docker inspect nc_app_findling_backend`
- PyPI JSON API, npm registry (Versionen, Peer-Deps, postinstall)

### Secondary (MEDIUM confidence)
- https://docs.nextcloud.com/server/latest/developer_manual/exapp_development/tech_details/Deployment.html (Env-Variablen-Liste, `--net`)

### Tertiary (LOW confidence)
- keine

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH, Versionen per Registry, Images per Pull/Digest
- Provisioner/Hardening/Daten-Ablage: HIGH, empirisch verifiziert
- ExApp-UI-Registrierung: MEDIUM-HIGH, aus Quelltext und Beispiel, nicht end-to-end in dieser Sitzung registriert
- Pitfalls: HIGH für Proxy/Ports/Image, MEDIUM für Store-Netztopologie

**Research date:** 2026-10-19
**Valid until:** 2026-11-18 (Luanti 5.18 steht als rc1 bereit; Pin bleibt 5.17.0)
