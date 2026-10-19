# Architecture Research

**Domain:** Kindersicheres Gameserver-Portal als Nextcloud-ExApp (Python/AppAPI), Provisionierung von Luanti-Containern auf dem eigenen Host
**Researched:** 2026-10-19
**Confidence:** HIGH (Provisionierungs-Mechanik, AppAPI, Luanti-Container), MEDIUM (Panel-Reife-Details)

## Provisionierungs-Entscheid (Owner-Entscheid, Kernfrage)

### Empfehlung: Option 1, ExApp spricht Docker Engine API über eine eigene, scoped Docker-Socket-Proxy-Instanz (Sibling-Container)

Gameworld erzeugt Luanti-Welten als **Sibling-Container** neben dem eigenen ExApp-Container, über die Docker Engine HTTP-API, erreichbar durch einen **allowlist-beschränkten docker-socket-proxy** im selben Docker-Netzwerk. Das ist exakt das Muster, mit dem AppAPI selbst ExApps deployt, nur mit eigener, enger gescopter Proxy-Instanz für Gameworld.

**Warum:**
1. **Kein neues Vertrauensmodell.** Der Nextcloud-Admin hat für AppAPI bereits einen Deploy-Daemon mit Docker-Engine-Zugriff eingerichtet (HaRP bzw. Docker Socket Proxy, bei AIO automatisch). Gameworld fügt denselben Zugriffstyp hinzu, keinen neuen.
2. **Geringste Installationslast für Familien.** Ein zusätzlicher Standard-Container (Proxy) per Compose-Snippet, kein eigener Host-Daemon, kein Fremd-Panel mit eigener Datenbank und eigenem Admin-Konto.
3. **Volle Kontrolle über Kindersicherheit.** Ressourcenlimits, Port-Vergabe, Whitelist, Backups laufen alle durch unseren Code; kein Panel-Rollenmodell, das Kindern versehentlich Admin-Funktionen zeigt.
4. **Passt zum Skillset:** Python + `docker` SDK bzw. `httpx` gegen die Engine-API, gleiche Werkzeuge wie Findling/Connector.

### Vergleichstabelle

| Kriterium | 1: ExApp -> Docker-API (Socket-Proxy) | 2: Eigener Host-Daemon (gameworldd) | 3: Engine-Panel (Crafty/Pelican/LuHost) |
|---|---|---|---|
| Luanti-Unterstützung | Voll (eigenes Image-Handling, linuxserver/luanti) | Voll (selbst gebaut) | Crafty: **nein** (Minecraft-only). Pelican: nur via importiertes Community-Egg (Pterodactyl parkervcp), ungepflegt. LuHost: ja, aber verwaltet lokale Luanti-Installation, keine Container |
| Installationslast Familie | 1 Standard-Container (Proxy) + Netzwerk, Compose-Snippet in Docs; bei AIO fast null Zusatzaufwand | Systemd-Service oder privilegierter Container + Secret-Austausch mit ExApp; ungewohnt, fehleranfällig | Panel + Daemon (Pelican: Panel + Wings + DB) + eigenes Admin-Konto; massiv für "Eltern ohne Serverwissen" |
| Sicherheitsfläche | Docker-API-Zugriff = root-äquivalent auf Host; mitigierbar via Allowlist (CONTAINERS, IMAGES, POST, ALLOW_START/STOP) + isoliertes Netz; gleiches Risiko, das der Admin für AppAPI schon akzeptiert hat | Gleiche root-äquivalente Macht, aber hinter semantischer API ("create_world") statt roher Docker-API; theoretisch enger, praktisch mehr eigener Security-Code zu pflegen | Panel ist eigene Angriffsfläche (Web-UI, Auth, oft public Issues); Pelican Beta; Crafty/Wings brauchen selbst Docker-Zugriff |
| Eigener Wartungsaufwand | Niedrig: ~1 Provisioner-Modul (~500-1000 LoC), Standard-Proxy wird upstream gepflegt | Hoch: eigener Daemon = eigenes Release-Artefakt, Update-Pfad, Auth, API-Versionierung | Mittel-hoch: Abhängigkeit von Fremd-Roadmap (Pterodactyl Maintenance-Mode als Warnung), Integrations-Glue |
| Reife/Risiko | Muster produktionserprobt (AppAPI, Portainer, Watchtower nutzen Engine-API via Proxy) | Greenfield | Crafty 4.11 reif aber falsche Engine; Pelican aktiv aber Beta; LuHost jung (MEDLab CU Boulder, "built largely with Claude Code"), Single-Install-Fokus, kein Multi-World-Container-Modell |
| Zeit bis MVP | Kürzeste (direkt loslegen) | +3-5 Tage für Daemon-Gerüst/Protokoll | +5-10 Tage Integration, und Luanti-Lücke bleibt |

### Wie AppAPI es selbst macht (Muster-Vorlage)

- AppAPI (PHP in Nextcloud) spricht die **Docker Engine API** nie direkt über den Socket, sondern über einen Proxy, den der Admin als "Deploy Daemon" registriert:
  - **HaRP** (empfohlen ab NC 32): Docker-Engine-Passthrough unter `/exapps/app_api/v1.xx/...`, authentifiziert per `harp-shared-key`-Header (`HP_SHARED_KEY`); Ziel-Engine via `docker-engine-port`-Header (24000-24099, Remote-Engines über mTLS-FRP-Tunnel). ExApp-HTTP-Verkehr läuft über FRP-Tunnel, ExApp-Container publizieren keine Host-Ports.
  - **DSP** (Legacy, Entfernung geplant mit NC 35): HAProxy vor dem Docker-Socket mit Basic-Auth, nur die von AppAPI genutzten Engine-Endpunkte sind freigeschaltet.
- **Kann Gameworld die AppAPI-Zugänge mitbenutzen?** Technisch teils ja (HaRP-Passthrough mit Shared Key), aber: die Credentials hält der Admin/AppAPI, nicht die ExApp; der Passthrough ist ein **interner AppAPI-Vertrag** ohne Stabilitätszusage; DSP fällt mit NC 35 weg. **Nicht darauf bauen.** Stattdessen: dasselbe Muster mit **eigener Proxy-Instanz** replizieren.
- AppAPI unterstützt keine frei definierbaren Mounts/Devices pro ExApp (nur das Daten-Volume `nc_app_<id>_data`, Compute-Device CPU/CUDA/ROCm). Ein Docker-Socket-Mount in den Gameworld-Container ist über info.xml **nicht** deklarierbar; der Netzwerk-Proxy ist der vorgesehene Weg.

### Scoping der Proxy-Allowlist (Tecnativa docker-socket-proxy)

Minimal nötige Freigaben für Gameworld:

```yaml
# docker-compose Snippet (Doku für Admin / Teil des Install-Guides)
gameworld-docker-proxy:
  image: tecnativa/docker-socket-proxy:latest
  environment:
    CONTAINERS: 1      # list/inspect/create/archive unter /containers/*
    IMAGES: 1          # Pull des Luanti-Images
    POST: 1            # ohne POST=1 ist alles read-only (auch PUT archive braucht es)
    ALLOW_START: 1     # containers/{id}/start
    ALLOW_STOP: 1      # containers/{id}/stop
    ALLOW_RESTARTS: 1  # stop/restart/kill
    # bewusst 0: AUTH, SECRETS, BUILD, EXEC, SWARM, SYSTEM, VOLUMES*, NETWORKS*
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
  networks: [gameworld-net]   # NUR dieses Netz, nie Host-Port publizieren
```

(*VOLUMES/NETWORKS nur freigeben, falls benannte Volumes statt Container-interner Daten genutzt werden, siehe State unten.*)

**Ehrliche Grenze:** Die Allowlist filtert Pfade/Methoden, nicht Request-Bodies. Wer `POST /containers/create` darf, kann theoretisch beliebige Container mit Host-Mounts erzeugen, also root-äquivalent. Das ist dieselbe Machtklasse, die der AppAPI-Deploy-Daemon bereits hat. Mitigation: Proxy ausschließlich im privaten `gameworld-net` (nur ExApp-Container + Proxy), kein Host-Port, Secret/Netz-Isolation statt Illusion von Feingranularität. Für eine spätere Härtung (v2) bleibt Option 2 als "gameworldd mit semantischer API" der dokumentierte Upgrade-Pfad.

### Warum nicht Option 2 (eigener Host-Daemon)

- Löst kein Problem, das der scoped Proxy nicht löst, erzeugt aber: zweites Release-Artefakt, eigener Update-/Auth-/Versionierungs-Pfad, ungewohnter Installationsschritt (systemd oder privilegierter Container) für genau die Zielgruppe "Eltern ohne Serverwissen".
- Der einzige echte Gewinn (semantische statt roher API = engere Angriffsfläche) lohnt erst, wenn ein Security-Review es fordert. Als MVP-Entscheid: nein, als dokumentierter v2-Pfad: ja.

### Warum nicht Option 3 (Engine-Panel)

- **Crafty Controller 4.x:** Minecraft-only (Java/Bedrock), keine Luanti-Unterstützung auffindbar. Relevanz erst für MVP 2 (Minecraft) als Option, aber auch dort: Panel-Admin-Modell kollidiert mit Elternkontroll-UX.
- **Pelican:** aktiver Pterodactyl-Fork, aber Beta; Architektur verlangt Panel + Wings-Daemon pro Node + DB; Luanti nur über altes Community-Egg (parkervcp, Pterodactyl-Ära) importierbar, ungepflegt. Installationslast für Familien disqualifizierend.
- **LuHost (MEDLab, CU Boulder, git.medlab.host/Modpol/LuHost):** Web-Dashboard für eine **lokal installierte** Luanti-Instanz (Node/REST, ContentDB-Integration, Start/Stop/Backup-Endpunkte). Jung, Single-Install-Modell, keine Container-Provisionierung, kein Mandanten-/Multi-World-Modell. Gute **Referenz** für Feature-Scope (Konsole, ContentDB, Backups), keine Basis.

## Standard Architecture

### System Overview

```
┌────────────────────────────────────────────────────────────────────┐
│ Nextcloud Core (PHP)                                               │
│  Users/Groups · Files (WebDAV) · AppAPI · Top-Menü-Eintrag         │
└───────┬──────────────────────────────▲─────────────────────────────┘
        │ deployt via Deploy Daemon    │ OCS/nc_py_api (Users, Files,
        │ (HaRP/DSP, Admin-Sache)      │ UI-Auslieferung /exapps/)
┌───────▼──────────────────────────────┴─────────────────────────────┐
│ Gameworld ExApp-Container (Python, FastAPI + nc_py_api)            │
│  ┌──────────┐ ┌───────────────┐ ┌───────────┐ ┌────────────────┐   │
│  │ UI/API   │ │ World Manager │ │ Invites   │ │ Backup Service │   │
│  │ (Vue/    │ │ (Lifecycle,   │ │ (NC-User->│ │ (Archiv -> NC  │   │
│  │ exapps)  │ │  Reconciler)  │ │ whitelist)│ │  Files)        │   │
│  └──────────┘ └──────┬────────┘ └─────┬─────┘ └───────┬────────┘   │
│  State: SQLite auf nc_app_gameworld_data (Welt-Metadaten)          │
└───────────────────────┼───────────────┼───────────────┼────────────┘
                        │ Docker Engine HTTP-API (nur gameworld-net)
                 ┌──────▼──────────────────────────────┐
                 │ gameworld-docker-proxy              │
                 │ (tecnativa/docker-socket-proxy,     │
                 │  Allowlist, kein Host-Port)         │
                 └──────┬──────────────────────────────┘
                        │ /var/run/docker.sock (ro)
┌───────────────────────▼────────────────────────────────────────────┐
│ Docker Host (Heimserver)                                           │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐       │
│  │ Welt "kinder1"  │ │ Welt "freunde"  │ │ ...             │       │
│  │ linuxserver/    │ │ linuxserver/    │ │ (1 Container    │       │
│  │ luanti          │ │ luanti          │ │  pro Welt)      │       │
│  │ UDP 30000 pub.  │ │ UDP 30001 pub.  │ │ Label           │       │
│  │ mem/cpu-Limits  │ │ mem/cpu-Limits  │ │ gameworld.world │       │
│  └─────────────────┘ └─────────────────┘ └─────────────────┘       │
└────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Nextcloud Core | Identität (Users/Groups), Dateiablage (Backups), App-Einstieg, deployt die ExApp | Bestehende NC-Instanz, AppAPI aktiviert |
| Gameworld ExApp Backend | Gesamte Logik: Welt-Lifecycle, Einladungen, Backups, Elternkontroll-Regeln, Admin-Settings (Proxy-URL) | Python, FastAPI, nc_py_api (wie Findling) |
| Gameworld UI | Eltern-Dashboard (Welt anlegen/starten/stoppen, einladen, Backup), Kinder-Sicht (nur "deine Welten", Verbindungsinfo) | Vue/Statik, ausgeliefert über `/exapps/gameworld/` (HaRP-Route) |
| Provisioner (Modul im Backend) | Einzige Stelle, die Docker spricht: create/start/stop/remove, Image-Pull, Port-Vergabe, Limits, Archive-I/O | `docker`-SDK oder httpx gegen Proxy-URL; Container-Labels `gameworld.world_id` |
| gameworld-docker-proxy | Scoped Zugang zur Engine-API, Netz-isoliert | tecnativa/docker-socket-proxy, Allowlist s. o. |
| Luanti-Welt-Container | Eine Spielwelt, eigener UDP-Port, eigene Limits, Whitelist-Mod aktiv | lscr.io/linuxserver/luanti, Daten in `/config/.minetest` |

## Recommended Project Structure

```
gameworld/
├── appinfo/info.xml          # ExApp-Manifest (external-app, docker-install)
├── ex_app/
│   ├── main.py               # FastAPI-App, AppAPI-Lifecycle (enabled-Handler)
│   ├── settings.py           # Admin-Settings: Proxy-URL, Port-Range, Defaults
│   ├── provisioner/
│   │   ├── docker_client.py  # Engine-API-Wrapper (create/start/stop/rm/archive)
│   │   ├── luanti.py         # Image, CLI_ARGS, minetest.conf-Rendering
│   │   └── reconciler.py     # DB-Sollzustand vs. Docker-Istzustand
│   ├── worlds/               # Lifecycle-Service + SQLite-Modelle (Welt, Mitglied)
│   ├── invites/              # NC-Users/Groups -> whitelist.txt-Erzeugung
│   ├── backups/              # tar-Stream <-> NC Files (nc_py_api)
│   └── ui_api/               # REST fuer Frontend, Rollen-Checks (Eltern/Kind)
├── src/ (Frontend)           # Vue-Dashboard
└── docs/install.md           # Compose-Snippet fuer gameworld-docker-proxy
```

### Structure Rationale

- **provisioner/ als einzige Docker-Grenze:** Alles, was später durch "gameworldd" (Option 2, v2-Härtung) oder eine zweite Engine (Crafty für Minecraft, MVP 2) ersetzt werden könnte, liegt hinter einem Interface. Das hält den Owner-Entscheid reversibel.
- **invites/ und backups/ getrennt von worlds/:** Beide hängen an Nextcloud-APIs (OCS, WebDAV), nicht an Docker; eigene Testbarkeit ohne Docker-Host.

## Architectural Patterns

### Pattern 1: Sibling-Container über Engine-API (nicht DinD)

**What:** Die ExApp erzeugt Welt-Container als Geschwister auf dem Host-Docker, via HTTP-API durch den Proxy, identifiziert über Labels (`gameworld.world_id=<uuid>`).
**When to use:** Immer; Docker-in-Docker ist für diesen Fall falsch (privilegiert, doppelte Storage-Treiber, Ressourcen-Chaos auf Heimservern).
**Trade-offs:** Host-weite Sichtbarkeit nötig (Labels filtern), dafür normale Host-Ressourcenverwaltung und Ports.

```python
client.containers.create(
    image="lscr.io/linuxserver/luanti:latest",
    labels={"gameworld.world_id": world.id},
    environment={"CLI_ARGS": f"--port {world.port}"},
    ports={f"{world.port}/udp": world.port},
    mem_limit="512m", nano_cpus=1_000_000_000, pids_limit=256,
    restart_policy={"Name": "unless-stopped"},
    security_opt=["no-new-privileges:true"], cap_drop=["ALL"],
)
```

### Pattern 2: Datei-I/O in Welt-Container über die Archive-API (statt Shared Mounts)

**What:** Die ExApp kann nachträglich keine Volumes in den eigenen Container mounten (AppAPI-Grenze). Whitelist schreiben und Welt-Daten für Backups lesen läuft daher über `PUT/GET /containers/{id}/archive` (docker-cp-Semantik, Teil der CONTAINERS-Sektion des Proxy).
**When to use:** whitelist.txt-Updates, minetest.conf-Updates, Backup-tar-Streams.
**Trade-offs:** Kein Live-File-Watch; dafür keine Volume-Verwaltung, kein VOLUMES-Scope im Proxy nötig, Welt-Daten bleiben im Container-Volume des Luanti-Images.

### Pattern 3: Desired-State-Reconciliation

**What:** SQLite (auf `nc_app_gameworld_data`) hält den Sollzustand (Welt existiert, soll laufen, Limits, Mitglieder). Ein Reconciler gleicht beim Start und periodisch gegen `GET /containers/json?filters={label:gameworld.world_id}` ab: verwaiste Container stoppen, fehlende neu erzeugen, Status-Anzeige aus Ist-Daten.
**When to use:** Ab der ersten Welt; Heimserver rebooten, Container sterben, die DB darf nie blind der Wahrheit letzte Instanz für "läuft" sein.
**Trade-offs:** Etwas Mehrcode früh, erspart die gesamte Klasse "UI zeigt laufend, Container ist tot".

## Data Flow

### Key Data Flows

1. **Welt anlegen/starten:** Eltern-UI -> ExApp `POST /worlds` -> World Manager legt DB-Eintrag an, vergibt nächsten freien UDP-Port (Range z. B. 30000-30019, Admin-Setting) -> Provisioner pullt Image, rendert minetest.conf + Whitelist-Mod, erzeugt Container mit Limits -> Status zurück ans UI.
2. **Einladung (NC-Konten -> Luanti-Whitelist):** Eltern wählen NC-User/Gruppe -> ExApp löst Mitglieder via nc_py_api/OCS auf -> Mapping NC-Username -> Luanti-Spielername in DB -> `whitelist.txt` via Archive-API in den Welt-Container geschrieben -> Whitelist-Mod (ContentDB, z. B. "Whiter List": Datei wird bei jedem Login-Versuch neu gelesen, kein Restart nötig) weist alle Nicht-Gelisteten ab. Kinder registrieren sich beim ersten Join mit Passwort; Fremde scheitern an der Whitelist. Gruppenänderungen: periodischer Sync oder NC-Event-Listener.
3. **Backup (Welt -> NC Files):** Zeitplan oder Button -> ExApp pausiert/stoppt Welt kurz (konsistentes sqlite) -> `GET /containers/{id}/archive?path=/config/.minetest/worlds/<welt>` -> tar-Stream -> Upload via nc_py_api in `Gameworld/Backups/<welt>/<datum>.tar` im Files-Bereich der Eltern -> Welt wieder starten. Restore = umgekehrt mit PUT archive.
4. **Spielen (Netzwerk):** Luanti-Client (Kind, LAN) -> Host-IP:UDP-Port der Welt -> direkt in den Welt-Container (publizierter Port). Wichtig: HaRP/FRP trägt nur ExApp-HTTP, **nicht** den UDP-Spielverkehr; Welt-Container publizieren ihre UDP-Ports selbst. Default = nur LAN; Internet-Zugriff erfordert bewusstes Router-Port-Forwarding (dokumentieren, nicht automatisieren: kindersicher per Default).
5. **UI-Auslieferung:** Browser -> NC-Reverse-Proxy -> `/exapps/gameworld/` -> HaRP -> ExApp (Standard-AppAPI-Weg, kein eigener Host-Port für die ExApp).

### State Management

| State | Wo | Warum |
|---|---|---|
| Welt-Metadaten (Name, Owner, Mitglieder, Port, Limits, Soll-Status, Backup-Plan) | SQLite auf `nc_app_gameworld_data` (persistentes AppAPI-Volume) | Überlebt Container-Updates der ExApp; AppAPI-Standard |
| Welt-Daten (Map, auth.sqlite, whitelist.txt, Mods) | Im Welt-Container unter `/config/.minetest` (Image-Konvention) | Luanti-Image-Standard; via Archive-API erreichbar |
| Runtime-Status (läuft/gestoppt, RAM-Nutzung) | Docker (Quelle der Wahrheit), via Reconciler gespiegelt | Nie nur DB vertrauen |
| Backups | Nextcloud Files (WebDAV, Eltern-Konto) | Produkt-Versprechen "Daten zuhause, in Nextcloud sichtbar" |

## Suggested Build Order

Abhängigkeiten diktieren die Reihenfolge; jede Stufe ist ein nutzbarer Vertical Slice:

1. **ExApp-Gerüst + UI-Hülle** (bekanntes Terrain aus Findling): Registrierung, Top-Menü, leeres Dashboard, Admin-Setting "Docker-Proxy-URL". Kein Docker nötig.
2. **Provisioner-Kern:** Proxy per Compose aufsetzen, eine Luanti-Welt hart kodiert erzeugen/starten/stoppen/löschen, Limits + Labels + Port-Publish. *Riskantestes Stück zuerst, validiert den Owner-Entscheid praktisch.*
3. **World Manager + State:** SQLite-Modelle, Port-Vergabe, Reconciler, UI-CRUD. Ab hier: One-Click-Welt.
4. **Invites:** NC-User/Gruppen-Picker, whitelist.txt via Archive-API, Whitelist-Mod ins Welt-Setup einbacken. Ab hier: privat per Default erfüllt.
5. **Backups:** Archive-Export -> NC Files, Restore, Zeitplan.
6. **Elternkontrolle + Härtung:** Kind-Rolle (nur Ansicht/Verbindungsinfo), Limits-UI, Doku Router/LAN, Store-Submit-Polish.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1-3 Welten (typische Familie) | Monolith wie beschrieben; 512 MB RAM-Limit je Welt als Default |
| 5-10 Welten (Verein, später) | Port-Range erweitern, Backup-Scheduling serialisieren (IO), evtl. Welt-Idle-Autostopp |
| Mehr-Host / Mandanten (v2+) | Dann Option-2-Daemon pro Host oder Pelican-artige Node-Architektur; Provisioner-Interface ist die Sollbruchstelle |

### Scaling Priorities

1. **Erster Engpass: RAM des Heimservers.** Luanti-Server brauchen grob 200-500 MB je nach Welt/Mods; deshalb sind mem_limit-Defaults und ein "Welt schlafen legen"-Feature wichtiger als jede Performance-Optimierung im Backend.
2. **Zweiter Engpass: Backup-IO** bei großen Welten; tar-Streaming statt Zwischenpuffern, Backups nachts.

## Anti-Patterns

### Anti-Pattern 1: Docker-Socket direkt in den ExApp-Container mounten

**What people do:** `/var/run/docker.sock` in die App mounten, weil es einfach ist.
**Why it's wrong:** AppAPI unterstützt keine deklarierten Mounts pro ExApp (nicht Store-fähig), und die Web-erreichbare App hätte ungefilterten root-äquivalenten Host-Zugriff.
**Do this instead:** Scoped Socket-Proxy im privaten Netz, Zugriff nur aus dem ExApp-Container.

### Anti-Pattern 2: AppAPI-interne Docker-Zugänge (HaRP-Passthrough/DSP-Credentials) mitbenutzen

**What people do:** Den vorhandenen Deploy-Daemon-Endpunkt der AppAPI anzapfen.
**Why it's wrong:** Interner Vertrag ohne Stabilitätszusage, Credentials gehören dem Admin/AppAPI, DSP wird mit NC 35 entfernt.
**Do this instead:** Eigene Proxy-Instanz, eigenes Secret, eigenes Netz; Muster kopieren, nicht Infrastruktur teilen.

### Anti-Pattern 3: Panel unter der Haube verstecken

**What people do:** Pelican/Crafty installieren und die ExApp als dünnes Frontend davor setzen.
**Why it's wrong:** Familien müssen dann zwei Systeme installieren und patchen; Panel-Rollenmodelle (Server-Admin-Konten) widersprechen "keine Admin-Zugänge für Kinder"; Crafty kann ohnehin kein Luanti.
**Do this instead:** Schmalen eigenen Provisioner bauen (der MVP braucht nur create/start/stop/archive); Panels erst für MVP 2 (Minecraft) neu bewerten.

### Anti-Pattern 4: Welt-Status nur in der eigenen DB führen

**What people do:** "running"-Flag in SQLite setzen und glauben.
**Why it's wrong:** Heimserver rebooten, OOM-Killer trifft Welt-Container, Admin räumt per `docker rm` auf; UI lügt dann.
**Do this instead:** Reconciler-Pattern, Docker-Labels als Join-Schlüssel, Ist-Zustand aus der Engine-API.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Docker Engine | HTTP-API via tecnativa/docker-socket-proxy, nur `gameworld-net` | Allowlist s. o.; Proxy-URL als Admin-Setting; AIO-Nutzer: zusätzlicher Container neben AIOs eigenem Proxy |
| Nextcloud Users/Groups | OCS via nc_py_api | Gruppen-Sync periodisch; Kind-Erkennung über dedizierte NC-Gruppe (z. B. `gameworld-kids`) |
| Nextcloud Files | WebDAV via nc_py_api, Eltern-Kontext | Backup-Ordnerstruktur versionieren; große tars streamen |
| Luanti-Image | lscr.io/linuxserver/luanti | UDP-only (30000/udp Default), Port via `CLI_ARGS --port`, Daten in `/config/.minetest`; Image bündelt kein Spiel mehr: Game (z. B. VoxeLibre/Minetest Game) beim Welt-Setup via ContentDB/Archive-API einspielen; Client- und Server-Version müssen zusammenpassen (Image-Tag pinnen) |
| ContentDB | HTTPS-Download kuratierter Games/Mods | Nur kuratierte Liste, Kinder installieren nichts selbst (Produkt-Constraint) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| UI <-> ExApp-Backend | REST unter `/exapps/gameworld/api/`, NC-Session-Auth via AppAPI | Rollen-Check (Eltern vs. Kind) serverseitig, nie nur UI |
| Backend <-> Provisioner | Python-Interface (`WorldProvisioner`-Protokoll) | Sollbruchstelle für Option 2 / zweite Engine |
| Provisioner <-> Welt-Container | Engine-API (create/start/stop/archive), KEIN exec im MVP | EXEC im Proxy auslassen = kleinere Fläche |
| Backend <-> Nextcloud | nc_py_api | Gleiches Muster wie Findling |

## Sources

- Nextcloud Admin Manual, [AppAPI and External Apps](https://docs.nextcloud.com/server/stable/admin_manual/exapps_management/AppAPIAndExternalApps.html) und [Managing Deploy Daemons](https://docs.nextcloud.com/server/31/admin_manual/exapps_management/ManagingDeployDaemons.html), HIGH
- Nextcloud Developer Manual, [Docker Socket Proxy FAQ](https://docs.nextcloud.com/server/stable/developer_manual/exapp_development/faq/DockerSocketProxy.html) (Tecnativa-Proxy mit IMAGES/CONTAINERS/POST explizit als Alternative genannt) und [Deployment](https://docs.nextcloud.com/server/stable/developer_manual/exapp_development/tech_details/Deployment.html), HIGH
- [nextcloud/app_api](https://github.com/nextcloud/app_api) README (HaRP empfohlen, DSP deprecated, Entfernung NC 35; FRP-Tunnel, keine Host-Ports für ExApps), HIGH
- [nextcloud/HaRP](https://github.com/nextcloud/HaRP) README (Docker-Engine-Passthrough `/exapps/app_api/v1.xx/`, `harp-shared-key`, `HP_DOCKER_ENGINE_PORTS` 24000-24099, mTLS-FRP), HIGH
- [Tecnativa/docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) README (Allowlist-Umgebungsvariablen, "never expose to public network", POST=0 = read-only), HIGH
- [linuxserver.io docker-luanti Docs](https://docs.linuxserver.io/images/docker-luanti/) (30000/udp, `/config/.minetest`, CLI_ARGS, kein gebündeltes Spiel mehr, Versions-Matching Client/Server), HIGH
- Luanti ContentDB Whitelist-Mods: [Whiter List (AntumDeluge)](https://content.luanti.org/packages/AntumDeluge/whitelist) (whitelist.txt wird bei jedem Login-Versuch neu geladen), [ct_whitelist](https://content.luanti.org/packages/GreatBigDiamond/ct_whitelist), MEDIUM
- [LuHost README (MEDLab, CU Boulder)](https://git.medlab.host/Modpol/LuHost/raw/branch/main/README.md) (Node-Dashboard für lokale Luanti-Installation, REST, ContentDB), MEDIUM
- Crafty Controller: Minecraft-only laut [TrueNAS-Katalog](https://apps.truenas.com/catalog/crafty-4_community/) u. a.; keine Luanti-Referenz auffindbar, MEDIUM (Negativbefund, gegen craftycontrol.com-Doku final prüfbar)
- Pelican: Pterodactyl-Fork, Wings-Daemon-Architektur, Egg-Import ([ramnode-Guide](https://ramnode.com/guides/series/game-servers/pelican-panel-setup), [pelican-eggs Org](https://github.com/orgs/pelican-eggs/repositories)); Minetest-Egg nur in Pterodactyl-Community-Sammlung (parkervcp), MEDIUM

---
*Architecture research for: Gameworld (Nextcloud ExApp Gameserver-Portal)*
*Researched: 2026-10-19*
