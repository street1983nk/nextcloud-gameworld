# Walking Skeleton: Gameworld

**Phase:** 1
**Generated:** 2026-10-19

## Capability Proven End-to-End

Ein Nextcloud-Admin öffnet Gameworld über das Top-Menü der Dev-Nextcloud, klickt "Welt erstellen" und sieht eine laufende, gehärtete, private Luanti-5.17.0-Welt in der Liste, deren Container über den gescopten Docker-Proxy erzeugt wurde.

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Plattform | Nextcloud-ExApp über AppAPI, nc_py_api 0.30.3 mit `AsyncNextcloudApp`, Ziel NC 32 bis 34 | Einziger Store-fähiger Weg für Python-Apps; Findling-Skillset; Sync-API wird in 0.31 entfernt |
| Backend | Python 3.13, FastAPI 0.143.2, `run_app`/`set_handlers`, `AppAPIAuthMiddleware` | nc_py_api-Standardmuster, keine eigene Auth |
| Container-Provisionierung | docker-py 7.2.0 (sync, gekapselt mit `anyio.to_thread.run_sync`) gegen tecnativa/docker-socket-proxy v0.5.0 (Digest gepinnt), Flags CONTAINERS, IMAGES, POST, VOLUMES = 1, Rest 0 | Im Spike verifiziert; nie roher Socket; einzige docker-py-Stelle ist `src/gameworld/provisioner/` |
| Welt-Laufzeit | Ein Sibling-Container pro Welt, Image `ghcr.io/luanti-org/luanti@sha256:db682cae...` (= 5.17.0), intern 30000/udp, extern ein Port aus `GAMEWORLD_PORT_RANGE` (Default 30000-30019) | Saubere Limits und Isolation pro Welt; Version-Pin ist zugleich Client-Vorgabe |
| Container-Härtung (fest, nicht einstellbar) | User 30000:30000, cap_drop ALL, no-new-privileges, read_only, mem = memswap 512m, pids 128, 1 CPU, Log-Rotation 5m x 2, restart_policy no, keine Host-Binds | WELT-05 und Kindersicherheit ab Welt Nummer eins; Restart-Entscheid gehört dem Reconciler (Phase 2) |
| Welt-Daten | Ein benanntes Volume `gameworld-<instanz>-<welt-id>` pro Welt, befüllt per `put_archive` auf dem nie gestarteten Container; `/etc/minetest` und `/tmp` als tmpfs | Kein ExApp-Mount möglich; Volume überlebt Container-Neuerzeugung; keine anonymen Volumes |
| Luanti-Konfiguration | `minetest.conf` root-eigen 0444 im Volume, `server_announce = false`, `disallow_empty_password = true`, zufälliger `default_password` als Weltschlüssel, `default_privs = interact, shout`, kein `name`; `world.mt` erzwingt sqlite3-Backends | ZUGANG-01; Luanti erzwingt den Weltschlüssel per SRP serverseitig bis zur Whitelist in Phase 3 |
| Spiele | minetest_game Release 38214 im Repo vendort (`vendor/games/`), SHA256 im Code geprüft | Keine externen Calls zur Laufzeit; Lizenz mitgeführt |
| Data layer (Soll-Zustand) | SQLite `$APP_PERSISTENT_STORAGE/gameworld.sqlite3`, Tabellen `meta` (schema_version, instance_id) und `worlds`; Dev-Fallback `.dev/storage` | Überlebt ExApp-Updates; idempotente Migration |
| Ist-Zustand | Immer aus Docker (label-gefilterte Container-Liste), nie aus der DB | Quelle der Wahrheit; Basis für den Reconciler in Phase 2 |
| Label-Schema | `gameworld.managed=true`, `gameworld.instance=<8 hex>`, `gameworld.world_id=<12 hex>`, `gameworld.schema=1`, `gameworld.engine=luanti`, `gameworld.engine_version=5.17.0`, `gameworld.port` | Welten ohne DB wiederfindbar; Instanz-ID trennt mehrere Nextclouds auf einem Host; `gameworld.engine` hält Platz für Minecraft (MVP 2) |
| Mutations-Schutz | Jede Stop/Start/Remove-Operation löst den Container über `_owned(world_id)` (managed + eigene Instanz + world_id) auf | Proxy filtert nur Pfade, nicht Inhalte; fremde Container bleiben unantastbar |
| Auth und Zugriff | Alle Routen in info.xml `access_level` ADMIN, Top-Menü `admin_required=True` | Phase 3 öffnet gezielt USER-Routen mit Rollen aus Nextcloud-Gruppen |
| Frontend | Vue 3.5.44, @nextcloud/vue 9.13.1, Vite 7.3.7 mit @nextcloud/vite-config 2.5.4, Bundle `js/gameworld-main.js`, Mount auf `#content`, API-Basis per Initial State `gameworld_config.apiBase` | Aktuelle NC-Linie; Initial State kapselt den Pfadwechsel manual-install vs. HaRP |
| API-Form | REST unter `/api`: `GET/POST /api/worlds`, `POST /api/worlds/{id}/start|stop`, `DELETE /api/worlds/{id}`, `GET /api/setup-check`; Fehler als `{"detail": "<deutsche Meldung>"}` | Ein Muster für alle späteren Slices |
| Deployment target (Phase 1) | Dev: Nextcloud 34.0.3 + Proxy in Compose-Projekt `gameworld-dev` (NC 8091, Proxy nur 127.0.0.1:23750), ExApp als Host-Prozess auf 10040 über manual-install-Daemon | Findling-Muster; HaRP- und Store-Image erst Phase 6 |
| Qualitätsgates | ruff (Vollsatz), ruff format, pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture, pytest mit Marker `docker` und `GAMEWORLD_REQUIRE_DOCKER=1` für Pflichtläufe | Owner-Standard; Docker-Tests dürfen nicht still überspringen |
| Directory layout | `appinfo/`, `src/gameworld/{api,provisioner,worlds}/`, `frontend/` (Build nach `js/`), `img/`, `vendor/games/`, `scripts/dev/`, `docs/`, `tests/` (+ `tests/e2e/`) | Trennung Docker-Zugriff (provisioner) vs. Fachlogik (worlds) vs. HTTP (api) |

## Stack Touched in Phase 1

- [ ] Project scaffold (uv-Projekt, ruff/pyright/vulture/pytest, Vite-Frontend) : Plan 01-01, 01-02
- [ ] Routing: `POST /api/worlds`, `GET /api/worlds` plus Top-Menü-Seite : Plan 01-01, 01-02
- [ ] Database: SQLite-Write (insert world, instance_id) und Read (list worlds) : Plan 01-01
- [ ] UI: Button "Welt erstellen" mit API-Aufruf, Liste mit Docker-Status : Plan 01-02
- [ ] Deployment: dokumentierter Dev-Lauf `docker compose -f scripts/dev/compose.yaml up -d` + `sh scripts/dev/register-exapp.sh` + `sh scripts/dev/smoke.sh` : Plan 01-02

## Out of Scope (Deferred to Later Slices)

- Presets (Minetest Game kreativ, VoxeLibre), One-Click ohne Namenseingabe, Dashboard-Design (Phase 2)
- Reconciler, Label-Re-Adoption nach ExApp-Update/Host-Reboot, Restart-Policy-Entscheid, Spielerliste, RAM-Anzeige (Phase 2)
- Einladungen, Whitelist-Mod, Luanti-Spieleraccounts, Verbindungsinfo, Eltern/Kind-Rollen, USER-Routen (Phase 3)
- Spielzeitlimits (Phase 4), Backup/Restore nach Nextcloud Files (Phase 5)
- HaRP-kompatibles Store-Image (start.sh/FRP), Orphan-Kommando, privacy.md, Proxy-Härtung im Deploy-Netz (Phase 6)
- Öffentliche Serverliste, UPnP, Live-Konsole, Raw-Config-Editor: dauerhaft ausgeschlossen

## Subsequent Slice Plan

- Phase 2: Elternteil erstellt Welten per One-Click-Preset im Dashboard, sieht Status, Spieler online und RAM; Welten überleben ExApp-Updates und Reboots
- Phase 3: Elternteil lädt Nextcloud-Nutzer ein, Nicht-Eingeladene scheitern serverseitig am Join, Kinder sehen nur eigene Welten und Verbindungsinfo
- Phase 4: Elternteil setzt Tageslimit und Zeitfenster pro Kind, der Server trennt und sperrt den Rejoin
- Phase 5: Elternteil sichert eine Welt nach Nextcloud Files und stellt sie nachweislich wieder her
- Phase 6: Jede Familie installiert Gameworld aus dem App Store mit ehrlicher Erklärung der Zusatz-Privilegien
