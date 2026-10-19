# Phase 2: One-Click-Welten - Research

**Researched:** 2026-10-19
**Domain:** Welt-Presets (Minetest Game, VoxeLibre), Live-Status aus Docker über den gescopten tecnativa-Proxy, Online-Spieler ohne exec, Reconciler für ExApp-Update und Host-Reboot, Dashboard-UI mit @nextcloud/vue 9
**Confidence:** HIGH (alle Docker-/Proxy-/Luanti-Mechanismen per Live-Spike auf dieser Maschine verifiziert), MEDIUM für Preset-Feinwerte (kindgerechte Schalter sind Produktentscheid) und Daemon-Neustart-Semantik (aus Docker-Doku, nicht live geprüft)

## Summary

Alle für Phase 2 nötigen Docker-Endpunkte sind unter den bestehenden Proxy-Flags erreichbar, ohne den Proxy aufzuweiten. Die tecnativa-Regel `^(/v[\d\.]+)?/containers` mit `CONTAINERS=1` (plus `POST=1` für schreibende Methoden) deckt `GET /containers/{id}/logs`, `GET /containers/{id}/stats`, `GET /containers/{id}/archive`, `POST /containers/{id}/restart` und `POST /containers/{id}/update` ab; nur `/exec` bleibt gesperrt [VERIFIED: haproxy.cfg.template im laufenden Proxy + Live-Spike 2026-10-19]. Der Live-Spike hat über den Proxy gemessen: One-Shot-Stats in 7 bis 13 ms (ohne `one_shot` 1,01 s), Restart in 0,9 s, Policy-Update, Logs mit `since`, `get_archive` samt Stat-Header (mtime) auf einer laufenden, read-only Welt.

Für die Online-Spieler ist ein kleiner, mitgelieferter Welt-Mod (`worldmods/gameworld_status`) der robuste MVP-Weg: Er schreibt bei Join, Leave und Serverstart die Namen der verbundenen Spieler per `core.safe_file_write` in `gameworld_players.txt` im Weltordner; die ExApp liest die Datei per `get_archive` (CONTAINERS-Scope, kein exec). Der Spike hat bewiesen, dass der Mod unter `secure.enable_security = true` mit Minetest Game und VoxeLibre lädt und schreibt [VERIFIED: Spike]. Log-Parsing ("joins game. List of players:") funktioniert prinzipiell (ACTION-Zeilen landen in `docker logs`), ist aber wegen der Log-Rotation (5 MB x 2) und weil Luanti jedes Graben und Platzieren als ACTION loggt, nach Stunden Spielzeit nicht mehr verlässlich; außerdem enthalten die Join-Zeilen IP-Adressen. Die mtime derselben Datei liefert nebenbei das Bereitschaftssignal für den Status "startet" (Datei neuer als `State.StartedAt` = Server lauscht).

VoxeLibre 0.92.4 (ContentDB-Release 39534, 18.10.2026, GPL-3.0-or-later / CC-BY-SA-4.0, 84,2 MB Zip, 104 MB entpackt, gameid `mineclone2`) läuft unter Luanti 5.17.0 im gehärteten Container: Einspielen per `put_archive` 4,4 s, bereit nach 3,9 s, 246 MiB im Leerlauf, bis 501 MiB beim erzwungenen Generieren von 400 x 400 Blöcken. Mit dem Phase-1-Limit von 512 MiB würde VoxeLibre beim ersten Erkunden per OOM sterben; das Preset braucht 1 GiB. Minetest Game bleibt unter gleicher Last bei 164 MiB, 512 MiB reichen [VERIFIED: Spike]. Für Reboot-Überleben empfiehlt die Research `restart_policy: no` beizubehalten und einen Reconciler beim ExApp-Start alle Soll-laufenden Welten starten zu lassen: Der ExApp-Container selbst trägt unter AppAPI/HaRP `unless-stopped` und sein Datenvolume überlebt Container-Neuerzeugungen [VERIFIED: docker inspect nc_app_findling_backend]. Ein `unless-stopped` an Welten erzeugt bei OOM eine Neustartschleife (11 Neustarts in rund 90 s im Spike) [VERIFIED: Spike].

**Primary recommendation:** Preset als neue Spalte in SQLite (Schema 2), pro Preset fest kodierte conf-Zeilen und Speicherlimit (MTG kreativ 512 MiB, VoxeLibre sanft 1 GiB), Statusmodell aus `inspect` plus Status-Datei des Welt-Mods, RAM per `stats(stream=False, one_shot=True)`, Reconciler als Hintergrund-Task im Lifespan (einmal beim Start mit Start der Soll-laufenden Welten, danach alle 30 s nur Statuspflege und OOM-Erkennung, nie automatische Neustarts), UI mit Polling alle 5 s bei sichtbarem Tab.

<user_constraints>
## User Constraints (kein CONTEXT.md vorhanden)

Für Phase 2 existiert kein `02-CONTEXT.md`. Die Vorgaben stammen aus ROADMAP.md, REQUIREMENTS.md, STATE.md, CLAUDE.md, der Phase-1-Research und den Phase-1-Entscheiden; sie gelten als gesetzt.

### Locked Decisions (aus Roadmap/State/Phase 1/CLAUDE.md)
- Presets genau zwei: "Minetest Game kreativ" und "VoxeLibre überleben-sanft", One-Click ohne Konfigfragen (WELT-01, Success Criterion 1)
- Status läuft / gestoppt / startet / Fehler, verständlich, **aus Docker, nicht aus der DB** (WELT-02, SC 2)
- Pro Welt Online-Spieler und RAM-Verbrauch sichtbar (WELT-03, SC 3)
- Nach ExApp-Update und Host-Reboot alle Welten korrekt im Dashboard; Label-Reconciliation, Zustand auf persistentem Volume (PLATT-02, SC 4)
- Proxy bleibt tecnativa/docker-socket-proxy v0.5.0 mit `CONTAINERS=1 IMAGES=1 POST=1 VOLUMES=1`, `EXEC=0`; keine neue Freigabe
- Luanti-Pin 5.17.0 per Digest; gehärtete Spec (cap_drop ALL, no-new-privileges, read_only, pids 128, 1 CPU, mem = memswap); privat per Default (server_announce aus, Weltschlüssel, keine Öffentlich-Option)
- Alle Container-Mutationen nur über `world_id` und `_owned()` (Label- und Instanzprüfung); docker-py nur unter `provisioner/`
- Keine Laufzeit-Downloads von ContentDB (Privacy, keine externen Calls); Spiele SHA256-gepinnt
- Kein freier Mod-Browser, keine Live-Konsole, kein Raw-Config-Editor (Out of Scope laut REQUIREMENTS.md)
- Owner-Regeln: Python-Gates ruff-Vollsatz + pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`) + vulture lokal grün vor Commit; deutsche Prosa mit Umlauten, Umlaute nie in Code/URLs/Keys; keine Em-/En-Dashes; keine Emojis; Commits als `street1983nk <k.cherif@outlook.de>` ohne Claude-Trailer; UI-Abnahme gemeinsam per Playwright

### Claude's Discretion (in dieser Research empfohlen)
- Konkrete Preset-Schalter, Speicherlimit pro Preset
- Mechanismus für Spielerliste und Bereitschaft (Mod-Datei vs. Log-Parsing)
- Restart-Policy vs. Reconciler-Start, Reconciler-Intervall und Regeln
- Polling-Intervall, Statusmodell, UI-Komponenten
- Ablage von VoxeLibre (Kopie pro Welt vs. geteiltes Volume; Repo vs. Fetch-Skript)
- Umgang mit der failed-Zeile (Port-Belegung) und "Erneut prüfen"

### Deferred Ideas (OUT OF SCOPE für Phase 2)
- Einladungen, Whitelist, Rollen, Verbindungsinfo (Phase 3)
- Spielzeitlimits (Phase 4; der Status-Mod ist aber eine wiederverwendbare Grundlage)
- Backup/Restore (Phase 5), HaRP-Store-Installation und echtes Store-Update (Phase 6)
- Auto-Stop bei Inaktivität, weitere Presets, Feinschalter (v2)
- Host-RAM-Prüfung vor dem Start (`/info` ist im Proxy gesperrt; siehe Open Questions)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WELT-01 | One-Click-Welt mit kindgerechtem Preset (MTG kreativ, VoxeLibre überleben-sanft), ohne Konfigfragen | Pattern 1 (Preset-Registry), VoxeLibre-Pin und Hash, gegen settingtypes.txt beider Spiele geprüfte Schalter, Speicherlimit aus Spike (VoxeLibre 501 MiB Spitze), Schema-Migration |
| WELT-02 | Start, Stop, Neustart; Status läuft/gestoppt/startet/Fehler verständlich | Pattern 3 (Statusmodell aus inspect + Bereitschaftsdatei), Restart als stop + `_launch`, OOM-Erkennung über `State.OOMKilled` (Spike), Statustexte für Eltern |
| WELT-03 | Online-Spieler und RAM pro Welt | Pattern 2 (Welt-Mod `gameworld_status` + `get_archive`), RAM-Formel `usage - inactive_file` mit `one_shot=True` (7 bis 13 ms) |
| PLATT-02 | Welten überleben ExApp-Update und Host-Reboot, Label-Reconciliation | Pattern 4 (Reconciler), AppAPI-Volume `nc_app_<id>_data` überlebt Container-Neuerzeugung, ExApp-Container `unless-stopped`, Proxy-Neustart-Reihenfolge, Dev-Simulation |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Stack: nc_py_api 0.30.3 async (`AsyncNextcloudApp`), Python 3.13, FastAPI/uvicorn, docker-py 7.2.0 sync via `anyio.to_thread`, Luanti `ghcr.io/luanti-org/luanti:5.17.0` (Digest-Pin), Vue 3 + @nextcloud/vue 9.13.1 + Vite 7.3.7
- What NOT to use: Sync-NextcloudApp, roher Docker-Socket, Luanti `latest`/`master`, ui_example-Skeleton, Minecraft-Anteile, DSP für Neuinstallationen
- Sicherheit: Kindersicher als Produktkern, Ressourcenlimits pro Welt Pflicht, keine Admin-Zugänge für Kinder
- GSD-Workflow: Änderungen nur über GSD-Kommandos
- Globale Owner-Regeln: siehe Locked Decisions (Gates, Umlaute, keine Dashes, keine Emojis, Commit-Identität, Playwright-Abnahme gemeinsam, parallel nur bei genug RAM)

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Preset-Auswahl im Formular | Browser (Vue) | API (Validierung per Enum) | Nur zwei feste Werte, kein Freitext; Server lehnt Unbekanntes mit 422 ab |
| Preset-Definition (conf-Zeilen, Spiel, Limit) | API / Backend (`provisioner/presets.py`) | - | Fest kodiert, testbar ohne Docker; kein Nutzerwert erreicht die Spec |
| Soll-Zustand (Preset, desired_state, Port) | SQLite in `APP_PERSISTENT_STORAGE` | Docker-Labels | Überlebt ExApp-Update (Volume `nc_app_gameworld_data`) |
| Ist-Status (läuft/gestoppt/startet/Fehler) | Docker Engine (inspect) | Welt-Mod-Datei (Bereitschaft) | Docker ist Wahrheit; Mod-Datei nur für "lauscht schon" |
| Online-Spieler | Luanti-Prozess (Welt-Mod schreibt Datei) | Backend liest per Archive-API | Kein exec, keine Logs mit IPs |
| RAM-Verbrauch | Docker Engine (cgroup-Stats) | Backend rechnet `usage - inactive_file` | Wie `docker stats` |
| Reconciliation | API / Backend (Lifespan-Task) | Docker-Labels | Einziger Entscheider über Starts nach Reboot |
| Reboot-Neustart der ExApp | Docker Engine (AppAPI-Container `unless-stopped`) | - | Von AppAPI/HaRP so erzeugt, verifiziert |
| Dashboard-Aktualisierung | Browser (Polling) | API (kurzer Cache) | Einfach, ausreichend für MVP |

## Standard Stack

Keine neuen Python- oder npm-Pakete. Alles läuft mit dem Phase-1-Stack.

### Core (unverändert aus Phase 1)
| Library | Version | Purpose | Phase-2-Nutzung |
|---------|---------|---------|-----------------|
| docker (docker-py) | 7.2.0 | Engine-Client | `Container.stats(stream=False, one_shot=True)`, `get_archive` (liefert `(stream, stat)` mit `mtime`), `restart`, `api.update_container(restart_policy=...)`, `logs(since=...)` [VERIFIED: Signaturen in .venv + Spike] |
| nc-py-api[app] | 0.30.3 | AppAPI | Lifespan für Reconciler-Task, sonst unverändert |
| @nextcloud/vue | 9.13.1 | UI | `NcRadioGroup` + `NcRadioGroupButton` (Preset), `NcChip` (Status, Varianten success/warning/error/tertiary), `NcProgressBar` (RAM), `NcEmptyContent` [VERIFIED: node_modules/@nextcloud/vue/dist/components] |

### Neues Spiel-Artefakt
| Artefakt | Version | Hash / Größe | Lizenz |
|----------|---------|--------------|--------|
| VoxeLibre (ContentDB `Wuzzy/mineclone2`) | 0.92.4, Release-ID 39534 vom 18.10.2026, min. Luanti 5.10, kein Max | SHA256 `6215d4da27900874959ff586fb266091be3d4161b9d4f5d27ce0d0cdc49f1af2`, 84.226.154 Bytes, 6692 Einträge, 104 MB entpackt, Wurzelordner `mineclone2/` | GPL-3.0-or-later (Code), CC-BY-SA-4.0 (Medien); `mineclone2/LICENSE.txt` im Zip [VERIFIED: ContentDB API + Download + sha256sum] |
| minetest_game | 38214 (unverändert) | `5b364f6b...19dc` | LGPL-2.1+/CC-BY-SA-3.0 |

Warum 0.92.4 statt 0.92.3 (25.836 Downloads): 0.92.4 ist ein Hotfix ("Fixed the crash happening with Luanti 5.10", "Fixed a few incredibly rare crashes") ohne Inhaltsänderung und lief im Spike fehlerfrei unter 5.17.0 [VERIFIED: releasenotes/0_92-the-undaunted-release.md im Zip + Spike]. 0.92.0/0.92.1 haben `max_minetest_version 5.16` und sind ungeeignet [VERIFIED: ContentDB API].

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Welt-Mod-Datei für Spieler | Log-Parsing `docker logs` | Kein Mod nötig, aber Rotation (10 MB) verliert die letzte Join-Zeile nach langen Sessions; Logs enthalten IPs; mehr Bytes pro Abfrage. Nur als Fallback-Diagnose |
| Spiel pro Welt ins Volume kopieren | geteiltes read-only Volume `gameworld-<inst>-game-<id>-<ver>` | Spart 104 MB Platte und 4,4 s pro VoxeLibre-Welt, braucht aber Hilfscontainer zum Befüllen, verschachtelten Mount, eigenes Aufräumen und koppelt alle Welten an eine Spielversion. Für MVP nicht nötig |
| `restart_policy: no` + Reconciler | `unless-stopped` an Welten | Docker startet Welten auch ohne ExApp nach Reboot, und "manuell gestoppt" spiegelt desired_state. Aber OOM-Schleife (Spike: 11 Neustarts in ~90 s, Status `restarting`) läuft, bis die ExApp eingreift; Reboot-Test braucht echten Daemon-Neustart. Nicht empfohlen |
| Polling | SSE / Docker-Events | Events (`EVENTS=1` ist Image-Default) wären reaktiver, aber Streaming durch AppAPI-Proxy und HaRP ist ungeprüft. MVP: Polling |

**Installation:** keine neuen Pakete. VoxeLibre-Zip per Fetch-Skript mit Hash-Prüfung (siehe Pattern 1, Ablage).

## Package Legitimacy Audit

Diese Phase installiert keine neuen npm- oder PyPI-Pakete. Das einzige neue Artefakt ist ein Spiel-Zip von ContentDB (offizielle Luanti-Paketplattform, Paket `Wuzzy/mineclone2`, Maintainer Wuzzy/ancientmariner/Herowl, Repo git.minetest.land/VoxeLibre/VoxeLibre), per SHA256 gepinnt.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| VoxeLibre 0.92.4 (Zip) | ContentDB | Projekt seit 2017 (MineClone2), Release 1 Tag | 776 (0.92.4), 25.836 (0.92.3) | git.minetest.land/VoxeLibre/VoxeLibre | n/a (kein npm/PyPI) | Approved, Hash-Pin |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Browser (Eltern-Dashboard, Polling 5 s bei sichtbarem Tab)
   | GET /api/worlds            POST /api/worlds {name, preset}
   | POST /api/worlds/{id}/start|stop|restart     DELETE /api/worlds/{id}
   v
[Nextcloud AppAPI-Proxy] --signiert--> [Gameworld ExApp (FastAPI)]
                                          |
          +-------------------------------+------------------------------+
          v                               v                              v
   WorldService (Lock)            StatusReader (TTL 2 s)        Reconciler (Lifespan-Task)
   create/start/stop/restart/     inspect + stats(one_shot) +   Boot: Soll-laufende starten,
   delete, Port-Saga              get_archive(players.txt)      Leichen bereinigen
          |                               |                     alle 30 s: OOM/Absturz -> Fehler
          +---------------+---------------+------------------------------+
                          v
          SQLite ($APP_PERSISTENT_STORAGE/gameworld.sqlite3): worlds(+preset), meta(instance_id)
                          |
                          v
          DockerProvisioner (einzige docker-py-Stelle, _owned, _guarded + 1 Retry bei GET)
                          | tcp (Dev 127.0.0.1:23750)
                          v
          tecnativa-Proxy: /containers/* (logs, stats, archive, restart, update erlaubt), /exec 403
                          v
          Docker Engine --> [gameworld-<inst>-<wid>] Luanti 5.17.0
                               Volume: minetest.conf (root 0444, Preset-Zeilen)
                                       .minetest/games/<minetest_game|mineclone2>
                                       .minetest/worlds/world/worldmods/gameworld_status
                                       .minetest/worlds/world/gameworld_players.txt  <- Mod schreibt
```

### Recommended Project Structure (Änderungen)
```
src/gameworld/
├── provisioner/
│   ├── presets.py        # NEU: Preset-Registry (pure): id, Titel, Spiel-Zip, gameid, conf-Zeilen, mem_limit
│   ├── archive.py        # build_world_payload(preset, conf, world_mt) + Status-Mod, Spiel nach Preset
│   ├── spec.py           # world_spec(..., mem_limit, preset) + Label gameworld.preset
│   ├── luanti_conf.py    # render_minetest_conf(name, key, preset) hängt Preset-Zeilen an; world.mt mit gameid
│   ├── status_mod.py     # NEU (oder Dateien unter vendor/mods/): init.lua + mod.conf als Konstanten
│   └── client.py         # + inspect_world, memory_bytes, read_world_file, restart via stop/start; Retry für GETs
├── worlds/
│   ├── store.py          # Schema 2: Spalte preset, Migration per PRAGMA user_version/meta
│   ├── status.py         # NEU: pures Statusmodell (inspect-Dict + Datei-mtime -> running|starting|stopped|error)
│   ├── reconciler.py     # NEU: boot_reconcile(), periodic_reconcile()
│   └── service.py        # create_world(name, preset), restart_world, Status-View mit players/memory
├── api/worlds.py         # preset im Request (Enum), /restart, erweitertes WorldOut
└── main.py               # Lifespan startet/beendet Reconciler-Task
vendor/games/             # mineclone2-39534.zip per scripts/fetch-games.sh (gitignored) oder committet
frontend/src/App.vue      # Preset-Auswahl, Statuschips, Spieler, RAM-Balken, Polling, Neustart
scripts/dev/acceptance-phase2.sh
```

### Pattern 1: Preset-Registry (fest kodiert, pure)
**What:** Ein Preset bündelt Spiel-Artefakt, gameid, zusätzliche conf-Zeilen, Speicherlimit und Elterntexte. Der Request enthält nur die Preset-ID.
**Example:**
```python
# Quelle der Schalter: settingtypes.txt im jeweiligen Zip (gelesen 2026-10-19) + minetest.conf.example 5.17.0
@dataclass(frozen=True)
class Preset:
    id: str            # "mtg_kreativ" | "voxelibre_sanft"  (ASCII, nie Umlaut im Key)
    title: str         # "Bauen (kreativ)" / "Abenteuer (sanft)"  -- Elterntext, Prosa mit Umlauten erlaubt
    game_zip: str      # "minetest_game-38214.zip" | "mineclone2-39534.zip"
    game_sha256: str
    game_dir: str      # Ordner im Zip und unter .minetest/games/: "minetest_game" | "mineclone2"
    gameid: str        # world.mt: "minetest" (Phase-1-Wert, Alias) | "mineclone2"
    mem_limit: str     # "512m" | "1g"
    conf_lines: tuple[str, ...]

MTG_KREATIV = Preset(..., gameid="minetest", mem_limit="512m", conf_lines=(
    "creative_mode = true", "enable_damage = false", "enable_pvp = false",
    "enable_tnt = false", "enable_fire = false",
    # Empfehlung (Owner bestätigen): Fliegen im Kreativmodus; MTG vergibt fly nicht automatisch
    # "default_privs = interact, shout, fly, fast",
))
VOXELIBRE_SANFT = Preset(..., gameid="mineclone2", mem_limit="1g", conf_lines=(
    "creative_mode = false", "enable_damage = true", "enable_pvp = false",
    "only_peaceful_mobs = true",        # nur friedliche Tiere spawnen natürlich (Spawner in Dungeons ausgenommen)
    "mobs_griefing = false", "mcl_explosions_griefing = false",
    "enable_fire = false",              # Feuer breitet sich nicht aus, zerstört nichts
    "mcl_keepInventory = true",         # Inventar bleibt beim Tod
    "mcl_enable_commandblocks = false",
))
```
- `default_privs` steht heute fest in `render_minetest_conf`; wenn das Kreativ-Preset `fly, fast` bekommt, muss die Basiszeile pro Preset gesetzt werden (nicht doppelt). Luanti nimmt bei doppelten Keys den letzten Wert, sicherer ist eine Zeile [ASSUMED].
- Spike lief mit genau diesen VoxeLibre-Zeilen fehlerfrei; dass VoxeLibre sie aus der Server-conf liest, folgt aus `core.settings` = Hauptkonfigurationsdatei [CITED: lua_api.md 5.17.0, Abschnitt Settings].
- **Ablage VoxeLibre:** 84 MB überschreiten GitHubs 50-MB-Warnschwelle (hart 100 MB). Empfehlung: `scripts/fetch-games.sh` lädt die ContentDB-URL `https://cdn.content.luanti.org/uploads/3e11bd7181.zip`, prüft SHA256 gegen `vendor/games/SHA256SUMS` und legt `mineclone2-39534.zip` ab (Zip gitignored); Code prüft den Hash vor jeder Nutzung wie bei minetest_game. Zur Laufzeit wird nie geladen. Alternative ohne Skript: Zip committen (konsistent mit Phase 1, aber dauerhaft 84 MB Historie).
- **Payload-Speicher:** Zip (84 MB) plus Tar (110 MB) gleichzeitig im ExApp-RAM. Tar in `tempfile.SpooledTemporaryFile(max_size=8 MB)` bauen und als Datei-Objekt an `put_archive` geben (docker-py nimmt bytes oder Stream) [ASSUMED: Stream-Upload gegen Proxy im Plan per Test prüfen]; Spiel-Teil des Tars optional pro Prozess cachen.

### Pattern 2: Online-Spieler per Welt-Mod und Archive-API (verifiziert)
```lua
-- .minetest/worlds/world/worldmods/gameworld_status/init.lua  (uid 30000, im Payload)
-- Spike 2026-10-19: lädt unter secure.enable_security = true mit MTG und VoxeLibre, schreibt die Datei
local path = core.get_worldpath() .. "/gameworld_players.txt"
local function write()
  local names = {}
  for _, p in ipairs(core.get_connected_players()) do
    names[#names + 1] = p:get_player_name()
  end
  table.sort(names)
  core.safe_file_write(path, table.concat(names, "\n"))
end
-- after(0): im Leave-Callback ist der gehende Spieler noch in der Liste
core.register_on_joinplayer(function() core.after(0, write) end)
core.register_on_leaveplayer(function() core.after(0, write) end)
core.register_on_mods_loaded(function() core.after(0, write) end)
-- mod.conf: name = gameworld_status
```
```python
# Provisioner (sync, über to_thread): Datei + Stat in einem Aufruf
PLAYERS_FILE = f"{DATA_DIR}/.minetest/worlds/world/gameworld_players.txt"
def read_status_file(self, world_id: str) -> tuple[list[str], str] | None:
    with self._guarded():
        container = self._owned(world_id)
        try:
            stream, stat = container.get_archive(PLAYERS_FILE)   # stat["mtime"] = "2026-10-19T18:19:46.947430723Z"
        except docker.errors.NotFound:
            return None                                          # Server noch nicht bereit
        raw = b"".join(stream)                                   # winzig; Größe vorher per stat["size"] begrenzen
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            member = tar.getmembers()[0]
            text = tar.extractfile(member).read(4096).decode("utf-8", "replace")
        names = [n for n in text.splitlines() if NAME_RE.fullmatch(n)]   # Luanti: [A-Za-z0-9_-]{1,20}
        return names, stat["mtime"]
```
- Nur anzeigen, wenn der Container läuft **und** `mtime >= State.StartedAt`; sonst ist die Datei ein Rest aus dem letzten Lauf (bei Absturz mit Spielern bleiben Namen stehen).
- Der Mod gehört in den deterministischen Payload; `gameworld_players.txt` darf **nicht** im Payload stehen (sonst ist die Bereitschaftsprüfung falsch).
- Verifiziert ist Laden und Schreiben beim Start (leere Datei). Join/Leave selbst konnte ohne Luanti-Client nicht live ausgelöst werden; die Callbacks sind dokumentierte Kern-API [CITED: lua_api.md 5.17.0 Z. 6119, 6398, 6579, 8084]. Abnahme mit echtem Client (Owner, Phase-Abnahme).

### Pattern 3: Statusmodell aus Docker (pure Funktion)
| Docker `State` | Bedingung | Status (API) | Elterntext |
|----------------|-----------|--------------|------------|
| `running` | Status-Datei mtime >= StartedAt | `running` | "Läuft" |
| `running` | Datei fehlt oder älter | `starting` | "Startet ..." (MTG ~1 s, VoxeLibre ~4 s) |
| `restarting` | - | `error` | "Startet immer wieder neu" (sollte mit Policy `no` nie vorkommen) |
| `exited`/`created` | desired_state = stopped | `stopped` | "Gestoppt" |
| `exited` | `OOMKilled = true` | `error` | "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet." |
| `exited` | desired = running, ExitCode != 0 | `error` | "Die Welt ist unerwartet beendet worden (Code N)." |
| `exited` | desired = running, ExitCode = 0 | `stopped` | "Gestoppt" (Reconciler startet beim nächsten Boot) |
| Container fehlt | Zeile vorhanden | `error` | "Weltdaten vorhanden, Server fehlt. Starten stellt ihn wieder her." (CR-01-Pfad) |
| Docker nicht erreichbar | - | `unknown` | "Docker nicht erreichbar" |
| op_state `creating` | - | `starting` | "Wird erstellt ..." |
| op_state `failed` | - | `error` | `last_error` |

Spike-Belege: Stop liefert `exited`, ExitCode 0, OOMKilled false; OOM liefert ExitCode 137, `OOMKilled: true`; `docker kill` (SIGKILL) liefert 137 ohne OOM-Flag [VERIFIED: Spike].

**RAM:** `stats = container.stats(stream=False, one_shot=True)`; Anzeigewert `memory_stats.usage - memory_stats.stats.inactive_file` (cgroup v2; v1-Fallback `total_inactive_file`), Limit aus `memory_stats.limit` bzw. Preset. Spike: MTG 34,5 MB usage minus 15,3 MB inactive_file = ca. 19 MB; VoxeLibre 257 MB minus 0,2 MB [VERIFIED: Spike; Formel wie docker CLI ASSUMED, Quelle docker/cli stats_helpers]. Nur für laufende Container abfragen.

**Neustart:** im Service als `stop` + `_launch` (dieselbe Port-Saga, kein neuer Codepfad). `container.restart()` funktioniert über den Proxy (0,9 s), umginge aber die Saga bei Port-Kollision.

### Pattern 4: Reconciler (Boot + periodisch)
```python
# main.py lifespan
async def lifespan(app):
    set_handlers(app, ...)
    service = ...                      # wie bisher, tolerant gegen Fehlkonfiguration
    task = asyncio.create_task(reconcile_forever(service))   # blockiert /heartbeat nicht
    yield
    task.cancel()

async def reconcile_forever(service):
    booted = False
    while True:
        try:
            if not booted:
                await service.boot_reconcile()     # einmal pro Prozessstart, sobald Docker erreichbar
                booted = True
            else:
                await service.periodic_reconcile()
        except DockerUnavailableError:
            pass                                   # Proxy evtl. noch nicht oben (Reboot-Reihenfolge)
        await asyncio.sleep(30 if booted else 5)
```
Regeln (alle unter dem Service-Lock, nicht blockierend: `_LOCK.acquire(blocking=False)`, sonst Zyklus überspringen):

| Fall | Boot | Periodisch |
|------|------|-----------|
| desired=running, Container `exited`, nicht OOM | starten (`_launch`) | nur Status, kein Neustart |
| desired=running, OOMKilled | nicht starten; `last_error` setzen | dito |
| desired=running, Container fehlt, Volume da | aus Volume neu erzeugen (bestehender `_launch`-Pfad) | nur Status |
| desired=stopped, Container läuft (manuell gestartet) | Docker gewinnt: desired_state auf running setzen | dito |
| op_state=creating (Prozess starb mitten im Erzeugen, IN-05) | auf failed setzen, Meldung "Erstellen wurde unterbrochen" | - |
| desired=deleted (Löschen brach ab) | Löschen wiederholen | - |
| Container mit eigener Instanz, ohne Zeile | nur loggen und zählen ("verwaist"), nie automatisch löschen | dito |
| Container fremder Instanz | nie anfassen | nie |

Warum das PLATT-02 erfüllt: Die SQLite liegt im AppAPI-Volume `nc_app_gameworld_data` unter `/nc_app_gameworld_data` (`APP_PERSISTENT_STORAGE`); AppAPI löscht es nur bei `unregister --rm-data` [CITED: docs.nextcloud.com admin_manual ManagingExApps]. Empirisch: `nc_app_findling_backend_data` (erstellt 29.09.) überlebte die Neuerzeugung des ExApp-Containers am 12.10. auf 1.4.3 [VERIFIED: docker volume inspect / docker inspect]. Die `instance_id` steht in derselben DB, also findet die neue ExApp-Version ihre Container über `gameworld.instance` wieder. Nach einem Host-Reboot startet Docker den ExApp-Container (`RestartPolicy unless-stopped`, von AppAPI/HaRP gesetzt [VERIFIED: docker inspect]); dessen Lifespan startet die Welten. Bei einem ExApp-Update laufen Welten ohnehin weiter (Update fasst Welt-Container nicht an).

### Anti-Patterns to Avoid
- **Status aus `op_state`/DB anzeigen, solange Docker antwortet:** nur `failed`/`creating` sind Operationszustände, alles andere kommt aus `inspect`.
- **Log-Parsing als einzige Spielerquelle:** Rotation und Datenschutz (IPs in Join-Zeilen, `server.cpp` Z. 1311).
- **`unless-stopped`/`always` an Welten:** OOM-Schleife (Spike), zweiter Entscheider neben dem Reconciler.
- **Reconciler startet periodisch abgestürzte Welten neu:** Crash-Schleife durch die Hintertür. Neustart nur beim Boot und per Elternklick.
- **Reconciler im Lifespan synchron ausführen:** AppAPI wartet auf `/heartbeat`; Docker-Aufrufe (bis 60 s Timeout) dürfen den Start nicht blockieren.
- **`containers.list()` ohne Not in jedem Poll:** docker-py ruft pro Container `inspect` auf (nicht sparse). Für ≤ 20 Welten ok; Ergebnis 2 s cachen, damit mehrere Tabs nicht vervielfachen.
- **Preset-Wert ungeprüft in Spec/conf:** nur Enum-IDs aus der Registry; `extra="forbid"` bleibt.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Spielerliste | Log-Parser mit Zustandsautomat | Welt-Mod mit `core.get_connected_players()` + `get_archive` | Engine kennt die Wahrheit; keine Rotation, keine IPs |
| RAM-Messung | eigenes cgroup-Lesen | `stats(stream=False, one_shot=True)` | 7 bis 13 ms statt 1 s, gleiche Formel wie docker CLI |
| Bereitschaft | UDP-Probe aus der ExApp | mtime der Mod-Datei vs. `StartedAt` | Ein Aufruf liefert Spieler und Bereitschaft; UDP-Probe aus dem ExApp-Netz prüft das falsche Netz |
| Atomares Schreiben im Mod | `io.open` + write | `core.safe_file_write` | Temp-Datei + rename, kein halbes Lesen |
| Migration | Drop/Recreate | `ALTER TABLE ... ADD COLUMN` mit Default, Version in `meta` | Bestehende Welten bleiben |
| Datei-Lesen aus Container | Hilfscontainer / exec | `container.get_archive` | CONTAINERS-Scope, läuft auch auf laufender read-only Welt |

## Runtime State Inventory

Phase 2 ist keine Umbenennung, ändert aber Schema und Container-Spec. Bestandsaufnahme:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | SQLite `.dev/storage/gameworld.sqlite3` (Schema 1, ohne `preset`); im Moment keine Welt-Container (`docker ps -a --filter label=gameworld.managed=true` leer, geprüft 19.10.) | Code: Migration auf Schema 2, Default `preset='mtg_kreativ'` für Altzeilen |
| Live service config | Keine (AppAPI-Registrierung über register-exapp.sh, Routen aus info.xml) | `/api/.*` deckt `restart` schon ab; Verben GET,POST,DELETE reichen |
| OS-registered state | Keine | Keine |
| Secrets/env vars | Keine neuen | Keine |
| Build artifacts | `js/gameworld-main.js` (gitignored), `vendor/games/` | Bundle neu bauen; VoxeLibre-Zip per Fetch-Skript |

Hinweis: Dev-Compose hat für Proxy und Nextcloud keine `restart`-Policy; für einen Docker-Desktop-Neustart-Test `restart: unless-stopped` am Proxy ergänzen (install.md hat es schon).

## Common Pitfalls

### Pitfall 1: VoxeLibre mit 512 MiB stirbt beim Erkunden
**What goes wrong:** Leerlauf 246 MiB, Kartengenerierung bis 501 MiB (Spike, 400 x 160 x 400 Blöcke, ohne Spielerobjekte).
**How to avoid:** Limit pro Preset; VoxeLibre `mem_limit = memswap_limit = 1g`. Abnahmeskript K3 prüft künftig das Preset-Limit statt pauschal 512 MiB. Nach realen Familien-Sessions neu kalibrieren.
**Warning signs:** `OOMKilled: true` im Inspect.

### Pitfall 2: Neuerzeugung spielt das falsche Spiel ein
**What goes wrong:** `_launch` erzeugt bei Port-Kollision oder fehlendem Container aus `_payload(row)` neu. Ohne Preset in der Zeile bekäme eine VoxeLibre-Welt minetest_game und `gameid = minetest` überschrieben (world.mt wird mitgeschrieben).
**How to avoid:** Preset in der DB-Zeile, `_payload` baut aus `row.preset`. Test: Port-Saga-Neuerzeugung einer VoxeLibre-Welt behält `gameid = mineclone2`. Spike-Beleg: world.mt bleibt nach Server-Läufen unverändert, Überschreiben mit identischem Inhalt ist harmlos [VERIFIED].

### Pitfall 3: Status-Datei aus dem letzten Lauf
**What goes wrong:** Nach Absturz mit verbundenen Spielern stehen Namen in der Datei; nach Neustart zeigt das Dashboard sie, bis der Mod neu schreibt.
**How to avoid:** Datei nur werten, wenn `running` und `mtime >= StartedAt`. Spike: `stat.mtime` als ISO mit Nanosekunden, `StartedAt` ebenso.

### Pitfall 4: Sporadischer Verbindungsabbruch zum Proxy nach ~10 s Leerlauf
**What goes wrong:** HAProxy im tecnativa-Image hat `timeout http-keep-alive 10s` und `option http-server-close` [VERIFIED: haproxy.cfg.template]. Im Spike brach ein Request nach genau 10 s Pause mit `ConnectionError: Remote end closed connection without response` ab; der Proxy hat ihn nie gesehen. Ein Wiederholungsversuch mit 10 bis 15 s Pausen (8 Requests) blieb fehlerfrei, die Race ist also selten [VERIFIED: Spike].
**How to avoid:** In `_guarded` lesende Aufrufe (list, inspect, stats, get_archive, logs) bei `ConnectionError` einmal wiederholen, bevor `DockerUnavailableError` geworfen wird; Reconciler-Intervall nicht auf exakt 10 s legen. Sonst blinkt im Dashboard sporadisch "Docker nicht erreichbar".

### Pitfall 5: Reboot-Reihenfolge
**What goes wrong:** Nach Reboot kann der ExApp-Container vor dem Proxy oben sein; ein einmaliger Boot-Abgleich scheitert und kommt nie wieder.
**How to avoid:** Boot-Abgleich in einer Schleife wiederholen, bis Docker erreichbar ist (5 s Takt), erst dann auf 30 s wechseln.

### Pitfall 6: Lock-Konkurrenz Reconciler vs. Elternklick
**What goes wrong:** Der Service-Lock ist ein `threading.Lock`; ein VoxeLibre-Erzeugen hält ihn ca. 10 s (4,4 s Einspielen + Start). Ein blockierender Reconciler staut sich dahinter oder umgekehrt.
**How to avoid:** Reconciler nimmt den Lock nicht blockierend und überspringt den Zyklus; Statuslesen (`list_worlds`) läuft weiterhin ohne Lock.

### Pitfall 7: Migration bleibt aus
**What goes wrong:** `migrate()` macht heute nur `CREATE TABLE IF NOT EXISTS` und überschreibt `schema_version`. Eine bestehende DB bekommt die Spalte `preset` nie, `WorldRow(*row)` bricht.
**How to avoid:** Vor dem Setzen der Version die alte Version lesen; bei 1 `ALTER TABLE worlds ADD COLUMN preset TEXT NOT NULL DEFAULT 'mtg_kreativ'`. Test mit einer Schema-1-Datei als Fixture.

### Pitfall 8: Kein Stream-Timeout bei Logs/Archive
**What goes wrong:** `logs(follow=True)` oder große Archive hängen am 60-s-Client-Timeout.
**How to avoid:** Keine Follow-Streams; Status-Datei per `stat["size"]` begrenzen (z. B. 4 KB).

### Pitfall 9: failed-Zeile belegt Port
**What goes wrong:** Scheitert Erzeugen bei totem Docker, bleibt eine failed-Zeile mit Port (Phase-1-Owner-Befund).
**How to avoid (Empfehlung):** Ist beim Scheitern nachweislich weder Container noch Volume entstanden (Fehler vor/bei `create`), die Zeile löschen und nur die Fehlermeldung zeigen; existiert etwas, failed-Zeile behalten (Löschen räumt auf).

## Code Examples

### Preset im Request
```python
class CreateWorldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, Field(max_length=200), AfterValidator(normalize_world_name)]
    preset: Literal["mtg_kreativ", "voxelibre_sanft"]   # Pflichtfeld, kein Default: UI wählt vor
```

### Spec mit Preset-Limit und Label
```python
def world_spec(instance_id: str, world_id: str, host_port: int, preset: Preset) -> dict[str, object]:
    spec = {... wie Phase 1 ...}
    spec["mem_limit"] = spec["memswap_limit"] = preset.mem_limit
    spec["labels"]["gameworld.preset"] = preset.id      # Diagnose/Adoption, nie Schlüssel in Labels
    spec["labels"]["gameworld.schema"] = "2"
    return spec   # restart_policy bleibt {"Name": "no"}
```

### RAM einer laufenden Welt
```python
def memory_bytes(self, world_id: str) -> tuple[int, int] | None:
    with self._guarded():
        container = self._owned(world_id)
        if container.status != "running":
            return None
        stats = container.stats(stream=False, one_shot=True)          # Spike: 7 bis 13 ms
        mem = stats.get("memory_stats") or {}
        raw = mem.get("stats") or {}
        inactive = raw.get("inactive_file", raw.get("total_inactive_file", 0))
        used = max(int(mem.get("usage", 0)) - int(inactive), 0)
        return used, int(mem.get("limit", 0))
```

### UI-Polling (Vue 3)
```js
// alle 5 s, nur bei sichtbarem Tab; nach jeder Aktion sofort
let timer = null
function schedule() {
	clearTimeout(timer)
	if (document.visibilityState === 'visible') {
		timer = setTimeout(async () => { await refresh(); schedule() }, 5000)
	}
}
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { refresh(); schedule() } })
onMounted(async () => { await refresh(); schedule() })
onUnmounted(() => clearTimeout(timer))
// SetupCheck: nach "Erneut prüfen" ebenfalls refresh() auslösen (Phase-1-Owner-Befund)
```

### Elterntexte (Vorschlag, Prosa)
- Preset-Auswahl: "Bauen (kreativ): Minetest Game, unbegrenzt Blöcke, kein Schaden" und "Abenteuer (sanft): VoxeLibre, Überleben mit friedlichen Tieren, Inventar bleibt beim Tod"
- RAM: "Arbeitsspeicher: 245 MB von 1 GB" (`NcProgressBar`, `error` ab 90 %)
- Spieler: "Gerade online: Mia, Leo" bzw. "Niemand online"; bei gestoppter Welt nichts anzeigen

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| MineClone2 | VoxeLibre (ContentDB-Paketname bleibt `mineclone2`, gameid `mineclone2`) | Umbenennung 2024 | Ordnername und gameid `mineclone2`, Titel "VoxeLibre" |
| `stats(stream=False)` mit CPU-Vorlauf | `one_shot=True` (API >= 1.41) | Docker 20.10 / docker-py 5 | 1 s zu ~10 ms |
| cgroup v1 `total_inactive_file` | cgroup v2 `inactive_file` | Docker Desktop/aktuelle Distros | Formel mit Fallback |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Kreativ-Preset bekommt `fly, fast` als Standardrechte (Produktentscheid, MTG vergibt fly nicht) | Pattern 1 | Kinder können im Kreativmodus nicht fliegen; nur Spielspaß, keine Sicherheit. Owner bestätigen |
| A2 | VoxeLibre-Sanft-Schalter (friedliche Mobs, Inventar behalten, kein Feuer/Explosionsschaden, Hunger an) passen zur Zielgruppe | Pattern 1 | Zu hart/zu weich; reine conf-Zeilen, leicht änderbar. Owner bestätigen |
| A3 | Elterntitel "Bauen (kreativ)" / "Abenteuer (sanft)" | Code Examples | Nur Text |
| A4 | RAM-Formel identisch zu docker CLI (`usage - inactive_file`) | Pattern 3 | Anzeige weicht leicht ab; kein Funktionsrisiko |
| A5 | `put_archive` akzeptiert ein Datei-Objekt als Stream durch den Proxy | Pattern 1 | Fallback bytes (wie Phase 1); RAM-Spitze ~200 MB im ExApp-Prozess |
| A6 | Doppelte conf-Keys: letzter Wert gewinnt | Pattern 1 | Irrelevant, wenn `default_privs` pro Preset nur einmal gerendert wird (empfohlen) |
| A7 | Docker markiert Welten mit Policy `no` nach Reboot als `exited` (Code 0 bei sauberem Shutdown, sonst ungleich 0, ohne OOM-Flag), Reconciler startet sie dann | Pattern 4 | Bei Daemon-Neustart nicht live getestet (würde Findling-Stacks unterbrechen); Dev-Simulation siehe Open Question 3 |
| A8 | Hunger bleibt im Sanft-Preset an | Pattern 1 | Produktentscheid, eine Zeile `mcl_enable_hunger = false` |

## Open Questions (RESOLVED)

1. **Spielerliste ohne exec** (RESOLVED): Welt-Mod `gameworld_status` schreibt `gameworld_players.txt`, Lesen per `get_archive`. Laden/Schreiben unter Mod-Security live verifiziert; Join/Leave mit echtem Luanti-Client in der Phasenabnahme (Owner, Client installieren oder Owner-Rechner). Log-Parsing nur als Diagnose.
2. **Restart-Policy** (RESOLVED): `no` bleibt; Reconciler startet beim ExApp-Start Soll-laufende, nicht OOM-gekillte Welten. ExApp-Container ist `unless-stopped` (verifiziert), Datenvolume überlebt Neuerzeugung (verifiziert). `unless-stopped` an Welten verworfen (OOM-Schleife im Spike).
3. **Wie Update und Reboot im Dev-Setup nachweisen?** (RESOLVED): (a) Update: ExApp-Prozess beenden, Version in info.xml/pyproject im Test hochzählen oder `occ app_api:app:unregister gameworld` ohne `--rm-data` plus `register-exapp.sh`; Welten laufen weiter, Dashboard zeigt sie danach korrekt (`.dev/storage` bleibt). (b) Reboot: Welt-Container von außen mit `docker stop` beenden (entspricht SIGTERM beim Daemon-Shutdown), ExApp neu starten, Reconciler startet sie; zusätzlich OOM-Fall per Testwelt mit kleinem Limit bzw. `docker kill` für "unerwartet beendet". Ein echter Docker-Desktop-Neustart ist optional und nur nach Owner-Freigabe (unterbricht die Findling-Stacks kurz). Der echte HaRP-Store-Update-Test gehört zu Phase 6 (PLATT-01).
4. **VoxeLibre-Ablage** (RESOLVED): Kopie pro Welt ins Volume (4,4 s, 104 MB); Zip per Fetch-Skript mit SHA256-Pin, nicht im Git. Geteiltes Volume erst bei Bedarf (v2).
5. **failed-Zeile belegt Port** (RESOLVED, Empfehlung): Zeile löschen, wenn nachweislich nichts in Docker entstand; sonst behalten. Planner setzt es als eigenen kleinen Task; Owner sieht es in der Abnahme.
6. **"Erneut prüfen" aktualisiert die Statusspalte nicht** (RESOLVED): Polling plus `refresh()` nach jedem Setup-Check-Lauf (Event aus `SetupCheck.vue`).
7. **Host-RAM-Prüfung vor dem Start** (DEFERRED): `/info` (MemTotal) ist im Proxy bewusst gesperrt (`INFO=0`); `/proc/meminfo` im ExApp-Container ginge nur unter HaRP, nicht im Dev-Host-Prozess. Kein Phase-2-Requirement; Kandidat für Phase 6 oder v2 zusammen mit Auto-Stop.
8. **Live-Join-Test der Spielerliste** (DEFERRED in die Phasenabnahme): Kein Luanti-Client auf der Maschine. Die Abnahme braucht einen Client (luanti.org, 5.17.x) oder den Owner-Rechner im LAN; Plan muss einen human-verify-Schritt dafür vorsehen.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Desktop (WSL2) | alles | ✓ | Engine 29.5.2, 8 GB RAM | - |
| Dev-Proxy `gameworld-dev-gameworld-docker-proxy-1` | Provisioner | ✓ läuft, `_ping` 200 | tecnativa v0.5.0 | - |
| Dev-Nextcloud `gameworld-dev-app-1` | UI | ✓ läuft auf 127.0.0.1:8091 | 34.0.3 | - |
| Luanti-Image | Welten | ✓ | 5.17.0 (Digest) | - |
| VoxeLibre-Zip | Preset 2 | ✓ im Scratchpad heruntergeladen, Hash geprüft | 0.92.4 | Fetch-Skript |
| uv / Python / Node | Build, Tests | ✓ | 0.11.7 / 3.13.1 / 22.21.0 | - |
| Luanti-Client | Join-Test Spielerliste | ✗ | - | Owner-Rechner oder Client-Installation in der Abnahme |

RAM-Lage: Findling-Stacks laufen parallel (ca. 600 MB). Eine VoxeLibre-Testwelt (bis 1 GiB) plus MTG-Welt passen; Tests mit mehreren VoxeLibre-Welten seriell fahren.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | unverändert `AppAPIAuthMiddleware` |
| V4 Access Control | yes | Alle Routen weiter ADMIN; `restart` nur über `_owned()` |
| V5 Input Validation | yes | `preset` als `Literal`-Enum, `extra="forbid"`; Spielernamen aus der Datei per Regex `[A-Za-z0-9_-]{1,20}` filtern, Größe begrenzen |
| V6 Cryptography | no (nichts Neues) | - |
| V12 Files | yes | Spiel-Zip SHA256-geprüft; Tar-Pfade über `_safe_relative`; Mod-Dateien als Konstanten |
| V14 Config | yes | Proxy-Flags unverändert; keine neuen Endpunkte freigeschaltet |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Manipulierte Status-Datei (Mod oder Spieler schreibt beliebigen Inhalt) | Tampering / XSS | Nur Namen per Regex übernehmen, max. 4 KB, Vue-Textinterpolation (kein `v-html`) |
| Preset-Injection in conf/Spec | Tampering | Nur Registry-IDs; conf-Zeilen fest kodiert |
| Fremdes Spiel-Zip | Tampering | SHA256-Pin, Prüfung vor jeder Nutzung |
| Ressourcen-Erschöpfung durch VoxeLibre | DoS | 1 GiB fest, mem = memswap, Policy `no`, kein automatischer Neustart nach OOM |
| Polling-Last auf Docker | DoS | 2-s-Cache, Polling nur bei sichtbarem Tab |
| Reconciler fasst fremde Container an | Tampering | Nur eigene Instanz-Labels; verwaiste nur melden |
| Spieler-IPs im Dashboard | Information Disclosure | Keine Logs parsen; Mod schreibt nur Namen |

## Sources

### Primary (HIGH confidence)
- Live-Spike 2026-10-19 auf dieser Maschine (docker-py 7.2.0 gegen tecnativa v0.5.0, Luanti 5.17.0): VoxeLibre- und MTG-Welt mit Status-Mod, put_archive-Zeiten, Bereitschaftszeiten, Speicher im Leerlauf und unter erzwungener Kartengenerierung, stats one_shot vs. ohne, restart, update_container, logs since, get_archive-Stat, OOM-Schleife mit unless-stopped, docker kill, Keep-Alive-Abbruch. Skripte: C:\Users\Student\AppData\Local\Temp\claude\C--Users-Student\26f83d85-f123-49b7-b92a-20e75304acd7\scratchpad\p2spike\spike.py und emerge.py; alle Spike-Container und Volumes wieder entfernt
- `/usr/local/etc/haproxy/haproxy.cfg.template` und Env im laufenden Proxy-Container (Allowlist, Timeouts)
- `docker inspect nc_app_findling_backend` (RestartPolicy unless-stopped, Volume `/nc_app_findling_backend_data`, `APP_PERSISTENT_STORAGE`), `docker volume inspect` (Volume älter als Container)
- ContentDB API `https://content.luanti.org/api/packages/Wuzzy/mineclone2/` und `/releases/`; Zip-Inhalt (game.conf, settingtypes.txt, releasenotes, LICENSE.txt)
- minetest_game 38214 `settingtypes.txt`, `mods/creative/init.lua` (aus dem vendorten Zip)
- luanti 5.17.0: `src/server.cpp` Z. 1311, 3178; `builtin/game/item.lua` (action-Logs bei Platzieren/Graben); `doc/lua_api.md` Z. 6119, 6398, 6579, 8084
- Docker-Doku Restart-Policies: https://docs.docker.com/engine/containers/start-containers-automatically/

### Secondary (MEDIUM confidence)
- https://docs.nextcloud.com/server/latest/admin_manual/exapps_management/ManagingExApps.html (Datenvolume, `--rm-data`)
- https://docs.nextcloud.com/server/stable/developer_manual/exapp_development/development_overview/ExAppOverview.html (Volume `nc_app_<id>_data`, `APP_PERSISTENT_STORAGE`)

### Tertiary (LOW confidence)
- keine

## Metadata

**Confidence breakdown:**
- Proxy-Erreichbarkeit, Stats, Archive, Restart: HIGH (live)
- Presets/VoxeLibre-Betrieb und Speicherbedarf: HIGH für Lauf und Messwerte, MEDIUM für reale Familienlast
- Spielerliste: HIGH für Mod-Laden/Schreiben, MEDIUM für Join/Leave (dokumentierte API, nicht live ausgelöst)
- Reconciler/Reboot: HIGH für AppAPI-Seite (live), MEDIUM für Daemon-Neustart-Semantik (Doku)
- UI-Komponenten: HIGH (im installierten Paket vorhanden)

**Research date:** 2026-10-19
**Valid until:** 2026-11-18 (VoxeLibre veröffentlicht häufig Hotfixes; Pin bleibt 0.92.4 bis zur bewussten Entscheidung)
