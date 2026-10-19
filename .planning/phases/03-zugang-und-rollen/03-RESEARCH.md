# Phase 3: Zugang und Rollen - Research

**Researched:** 2026-10-19
**Domain:** Luanti-Zugangskontrolle ohne exec (Whitelist plus Auth-Provisionierung per Welt-Mod und Archive-API), SRP-6a-Verifier in Python, Nextcloud-Rollen und Nutzer-/Gruppenauflösung über AppAPI, Verbindungsinfo und Eltern-/Kind-Ansicht mit @nextcloud/vue 9
**Confidence:** HIGH für Durchsetzung und Auth (Live-Spike mit echtem Luanti 5.17.0 über den Dev-Proxy, Negativ- und Positiv-Join per eigenem UDP-Prober inklusive vollständigem SRP-Login), HIGH für AppAPI-Zugriffsebenen und Nextcloud-APIs (Quellcode im Dev-Container plus Live-Proben), MEDIUM für Client-UX-Texte und Kick laufender Spieler (kein Luanti-Client auf der Maschine)

## Summary

Die serverseitige Durchsetzung lässt sich vollständig ohne exec bauen, und zwar mit genau der Technik, die in Phase 2 schon trägt: ein mitgelieferter Welt-Mod liest eine Datei, die die ExApp per `put_archive` in den Weltordner schreibt. Der Spike hat das live bewiesen: `put_archive` schreibt in einen **laufenden** Container mit read-only Root-Dateisystem (Ziel liegt im Volume) in 0,01 s und auch in einen gestoppten (`exited`) Container. Ein Mod `gameworld_access` mit `core.register_on_prejoinplayer` liest die Datei bei jedem Join-Versuch neu, lehnt nicht eingeladene Namen **vor der Authentifizierung** ab (`handleCommand_Init`, Prejoin läuft vor `getAuth`, Quelle `serverpackethandler.cpp` Z. 183 vs. 209) und setzt im selben Callback per `core.set_player_password(name, verifier)` das von der App vorgegebene Passwort. Damit braucht es weder Fremd-Mods noch direktes Schreiben der `auth.sqlite` noch einen Neustart bei Einladungsänderungen [VERIFIED: Live-Spike 2026-10-19].

Den Passwort-Verifier berechnet die ExApp selbst in reinem Python (stdlib, rund 25 Zeilen): Luanti speichert `#1#<base64 salt>#<base64 v>` mit SRP-6a, SHA-256, RFC-5054-Gruppe 2048 Bit, `g = 2`, `x = SHA256(salt || SHA256(lower(name) ":" password))`, `v = g^x mod N` als Big-Endian ohne Auffüllen [VERIFIED: src/util/auth.cpp + src/util/srp.cpp, Tag 5.17.0]. Der Spike hat mit einem selbst geschriebenen Luanti-Prober (UDP, MTP-Protokoll, SRP-Client) gegen den echten Server bewiesen: richtiges Passwort ergibt `TOCLIENT_AUTH_ACCEPT`, falsches `WRONG_PASSWORD`, nicht eingeladener Name `ACCESS_DENIED` mit eigenem Text, unvollständige Zugangsdatei lässt den alten Stand stehen, Widerruf wirkt beim nächsten Join, der alte Weltschlüssel (`default_password`) öffnet provisionierte Konten nicht mehr. Derselbe Prober liefert den automatisierten Negativ-Join-Test für Success Criterion 2, ganz ohne Luanti-Client.

Auf Nextcloud-Seite: AppAPI kennt pro Route `PUBLIC`/`USER`/`ADMIN`, die erste passende Route (Pfad plus Verb) gewinnt [VERIFIED: ExAppProxyController.php im Dev-Container]. Die ExApp bekommt die Nutzer-ID signiert im Header `AUTHORIZATION-APP-API`; `AppAPIAuthMiddleware` legt sie in `scope["username"]` ab. Ein Nicht-Admin darf seine eigenen Gruppen lesen (`/ocs/v1.php/cloud/user`), aber keine Gruppenmitglieder auflösen (`403 ... must be at least a sub admin`) und keine fremden Konten abfragen (998) [VERIFIED: Live-Probe per ExApp-Impersonation]. Daraus folgt die Empfehlung: **Verwalter (Eltern) = Mitglieder der Nextcloud-Admin-Gruppe**, Spieler = alle eingeladenen Konten. Verwaltungsrouten bleiben in info.xml `ADMIN` (Durchsetzung durch Nextcloud) und prüfen zusätzlich in Python; nur `/js`, `/img`, `/api/me` und `/api/my/...` werden `USER`.

**Primary recommendation:** Eigener Welt-Mod `gameworld_access` (Prejoin-Whitelist, Passwort-Setzen beim Prejoin, Fehlversuch-Sperre, 5-s-Takt für Kick nach Widerruf) plus Zugangsdatei `gameworld_access.txt` (Kopf mit Generation, Zeilen `Name Verifier`, Schlusszeile `end`), geschrieben per `put_archive` beim Erzeugen, vor jedem Start und bei jeder Einladungsänderung; SRP-Verifier in `provisioner/luanti_auth.py` (stdlib); Rollen aus der Admin-Gruppe per Selbstauskunft; Schema 3 mit `players`, `invites`, `world_access`; Verbindungsinfo mit konfigurierbarer Spieler-Adresse (Vorgabe: Hostname des Browsers); Negativ-Join-Test per mitgeliefertem Test-Prober.

<user_constraints>
## User Constraints (kein CONTEXT.md vorhanden)

Für Phase 3 existiert kein `03-CONTEXT.md`. Die Vorgaben stammen aus ROADMAP.md, REQUIREMENTS.md, STATE.md, CLAUDE.md, den Phase-1/2-Entscheiden und dem Auftrag des Orchestrators; sie gelten als gesetzt.

### Locked Decisions
- Nur Eingeladene spielen; Durchsetzung serverseitig im Luanti-Server (Whitelist), nicht nur im UI; Negativ-Join-Test ist Abnahmekriterium (ZUGANG-03, SC 2)
- Einladen von Nextcloud-Benutzern **und** -Gruppen; Gameworld provisioniert Luanti-Konten (Name und Passwort) automatisch (ZUGANG-02, SC 1)
- Verbindungsinfo pro eingeladenem Spieler: Adresse, Port, Spielername, Schritt-für-Schritt-Anleitung für den Luanti-Client (ZUGANG-04, SC 3)
- Kind-Ansicht: nur eigene Welten und Verbindungsinfo; Verwaltung serverseitig gesperrt, nicht nur ausgeblendet (ROLLE-01, SC 4)
- Rollen aus Nextcloud-Gruppen, keine eigene Benutzerverwaltung (ROLLE-02, SC 5; Out of Scope: eigene Account-Verwaltung)
- Jede Durchsetzung ohne exec (Proxy: `/exec` = 403); Proxy-Flags bleiben `CONTAINERS=1 IMAGES=1 POST=1 VOLUMES=1`, keine neue Freigabe
- Kinder bekommen nie Admin-Zugänge (weder in Nextcloud noch im Spiel: kein `name`-Admin in der conf, keine Rechtevergabe an Kinder)
- Privatheit ist Produktkern: keine öffentliche Sichtbarkeit, keine externen Aufrufe zur Laufzeit, keine IP-Adressen im Dashboard, keine Chat-Protokolle
- Bestehende Architektur: docker-py nur unter `provisioner/`, Mutationen nur über `world_id` und `_owned()`, SQLite-Migration per `PRAGMA table_info` (idempotent), Status aus Docker, Reconciler nie mit periodischen Neustarts
- Owner-Regeln: ruff-Vollsatz, pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture lokal grün vor Commit; deutsche Prosa mit Umlauten, Umlaute nie in Code-Bezeichnern/URLs/Keys; keine Gedankenstriche (U+2013/U+2014); keine Emojis; Commits als `street1983nk <k.cherif@outlook.de>` ohne Trailer; UI-Abnahme gemeinsam per Playwright; Python immer über `uv run`/`.venv` (globale Installation kaputt)

### Claude's Discretion (in dieser Research empfohlen)
- Mod-Wahl (Fremd-Mod vs. eigener Mod) und Dateiformat der Zugangsliste
- Weg der Auth-Provisionierung (Mod mit `set_player_password` vs. `auth.sqlite` schreiben)
- Rollenmodell im Detail (welche Gruppe ist Verwalter), Routen-Zugriffsebenen
- Datenmodell (Schema 3), Gruppenauflösung (einmalig vs. dynamisch)
- Spielernamen- und Passwortregeln, Spieler-Adresse, UI-Aufteilung und Komponenten

### Deferred Ideas (OUT OF SCOPE für Phase 3)
- Spielzeitlimits (Phase 4; Datenmodell und Mod dieser Phase sind die Grundlage)
- Backup/Restore (Phase 5), Store-Release/HaRP-Installation (Phase 6)
- Eigene Verwalter-Gruppe für Nicht-Admin-Eltern (siehe Open Question 1)
- Öffentliche Erreichbarkeit, UPnP, Freunde über das Internet (Out of Scope; VPN nur dokumentiert)
- Aktivitäts-Benachrichtigungen (v2), Vereins-/Gruppenbetrieb mit Mandanten (v2)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ZUGANG-02 | Eltern laden NC-Benutzer und -Gruppen ein; Gameworld provisioniert Luanti-Konten (Name, Passwort) | Pattern 2 (SRP-Verifier in Python, live gegen Luanti verifiziert, Golden Vector), Pattern 1 (Mod setzt Passwort beim Prejoin), Pattern 5 (Schema 3, Gruppenauflösung als Admin, Selbstauskunft), Pattern 6 (Namens- und Passwortregeln) |
| ZUGANG-03 | Nicht Eingeladene serverseitig am Join gehindert | Pattern 1 (Prejoin vor Auth, Live-Spike A0 bis A9), Pattern 3 (Zugangsdatei mit Kopf/Schluss, Schreibzeitpunkte), Code-Beispiel Join-Prober für den automatisierten Negativ-Join-Test |
| ZUGANG-04 | Verbindungsinfo (Adresse, Port, Spielername, Anleitung) | Pattern 7 (Spieler-Adresse: Einstellung plus Browser-Hostname, Warnhinweise), Anleitungstext, `/api/my/worlds` |
| ROLLE-01 | Kind-Ansicht nur eigene Welten und Verbindungsinfo; Verwaltung serverseitig gesperrt | Pattern 4 (Routen USER/ADMIN in info.xml, erste Route gewinnt, Python-Prüfung pro Request), Pattern 8 (eine Vue-App, Rolle aus `/api/me`) |
| ROLLE-02 | Rollen aus NC-Gruppen, keine eigene Benutzerverwaltung | Pattern 4 (Verwalter = Admin-Gruppe per Selbstauskunft `/cloud/user`), Pattern 5 (Spieler nur über NC-Konten/-Gruppen; die App speichert nur die Zuordnung NC-Konto zu Spielername) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Stack: nc_py_api 0.30.3 async (`AsyncNextcloudApp`), Python 3.13, FastAPI/uvicorn, docker-py 7.2.0 sync über `anyio.to_thread`, Luanti `ghcr.io/luanti-org/luanti:5.17.0` per Digest, Vue 3.5.44 + @nextcloud/vue 9.13.1 + Vite 7.3.7, IIFE-Bundle
- What NOT to use: Sync-`NextcloudApp`, roher Docker-Socket, Luanti `latest`/`master`, ui_example-Skeleton, DSP für Neuinstallationen
- Sicherheit: Kindersicher als Produktkern, private Welten per Default, keine Admin-Zugänge für Kinder
- CLAUDE.md nennt noch `ct_whitelist` als Supporting Library: Diese Research ersetzt die Empfehlung (Paket auf ContentDB nicht mehr auffindbar, siehe Standard Stack); CLAUDE.md-Abschnitt beim nächsten Doku-Lauf anpassen
- GSD-Workflow: Änderungen nur über GSD-Kommandos

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Join-Sperre für nicht Eingeladene | Luanti-Prozess (Welt-Mod, Prejoin) | ExApp schreibt Zugangsdatei | Nur der Spielserver sieht Join-Versuche; UI-Sperre allein erfüllt ZUGANG-03 nicht |
| Passwort-Verifier berechnen | API / Backend (`provisioner/luanti_auth.py`) | - | Klartextpasswort verlässt die ExApp nie Richtung Volume, nur der Verifier |
| Passwort im Spiel setzen | Luanti-Prozess (`core.set_player_password` beim Prejoin) | - | Kein exec, kein Schreiben in `auth.sqlite` bei laufendem Server |
| Einladungen, Spielernamen, Passwörter | SQLite (Schema 3) im AppAPI-Volume | Zugangsdatei im Welt-Volume | DB ist Soll, Datei ist das, was der Server durchsetzt |
| Rollenentscheid (Verwalter/Spieler) | API / Backend pro Request | Nextcloud AppAPI (Route ADMIN) | Doppelt: Nextcloud lehnt Nicht-Admins an Verwaltungsrouten ab, Python prüft erneut |
| Nutzer-/Gruppensuche im Einladungsdialog | Browser (NC-OCS `core/autocomplete/get`) | API validiert Auswahl | Nextcloud-eigene Sichtbarkeitsregeln gelten; Backend vertraut der Auswahl nicht |
| Gruppenauflösung | API / Backend als einladender Admin (`users_groups.get_members`) | Selbstauskunft des Spielers | Nicht-Admins dürfen Mitglieder nicht lesen (403, live) |
| Verbindungsinfo | API (`/api/my/worlds`) | Browser (Hostname-Vorgabe) | Port und Name aus DB, Adresse aus Einstellung oder Browser |
| Kick nach Widerruf | Luanti-Prozess (Mod-Takt 5 s) | - | Kein Konsolenzugriff nötig |

## Standard Stack

Keine neuen Python- oder npm-Pakete. Alles läuft mit dem Phase-1/2-Stack plus stdlib (`hashlib`, `secrets`, `base64`, `unicodedata`).

### Core (unverändert)
| Library | Version | Phase-3-Nutzung |
|---------|---------|-----------------|
| docker (docker-py) | 7.2.0 | `Container.put_archive` in laufende und gestoppte Welten (live), `get_archive` für den Mod-Statusdatei-Rücklauf |
| nc-py-api[app] | 0.30.3 | `AppAPIAuthMiddleware` (`scope["username"]`), `AsyncNextcloudApp.set_user`, `users.get_user()` (Selbstauskunft, `/ocs/v1.php/cloud/user`, Feld `groups`), `users.get_user(uid)` (als Admin, `display_name`, `enabled`), `users_groups.get_members(gid)` (als Admin) [VERIFIED: .venv-Quellen + Live-Probe] |
| @nextcloud/vue | 9.13.1 | `NcSelectUsers` (Optionen extern, Event `search`, Modell `{id, displayName, user?, isNoUser?, iconSvg?}`), `NcDialog`, `NcFormBoxCopyButton`, `NcNoteCard`, `NcEmptyContent`, `NcPasswordField`, `NcTextField`, `NcChip` [VERIFIED: node_modules/@nextcloud/vue/dist/components] |
| @nextcloud/axios, @nextcloud/router | 2.6.0 / 3.2.0 | Browser ruft `generateOcsUrl('core/autocomplete/get')` direkt (Session + requesttoken) |

### Whitelist-Kandidaten (Bewertung, Empfehlung: keiner davon)
| Kandidat | Stand | Mechanik | Bewertung |
|----------|-------|----------|-----------|
| **Whiter List** (ContentDB `AntumDeluge/whitelist`, MIT, Repo codeberg.org/AntumLuanti/mod-whitelist) | letzte Release v1.3 vom 29.09.2022, min. Luanti 5.0, 1.636 Downloads | Prejoin liest `whitelist.txt` (ein Name pro Zeile) bei jedem Join neu; Chat-Befehl `/whitelist` (Recht `ban`); lässt `name`-Admin immer durch | Gleiche Technik wie der eigene Mod, aber: keine Integritätsprüfung (halbe Datei = halbe Liste), kein Passwort-Setzen, kein Kick bei Widerruf, kein Rückkanal; seit 4 Jahren ohne Release [VERIFIED: ContentDB-API + init.lua gelesen] |
| **Whitelist** (ContentDB `Zughy/whitelist`, AGPL-3.0) | 1.3.0 vom 08.03.2026, min. Luanti 5.10 | Liste in Mod-Storage (SQLite), Pflege nur per Chat-Befehl, standardmäßig aus, Recht `server` umgeht die Liste | Ungeeignet: Die ExApp kann Mod-Storage im laufenden Server nicht ändern [VERIFIED: src/api.lua, src/player_manager.lua] |
| **ct_whitelist** (`GreatBigDiamond/ct_whitelist`) | ContentDB liefert 404 für Paketseite und API, Suche nach `ct_whitelist` leer (geprüft 19.10.2026) | unbekannt | Nicht verfügbar; die STACK.md-Empfehlung ist damit hinfällig [VERIFIED: content.luanti.org] |
| **Eigener Mod `gameworld_access`** | im Spike gebaut und live getestet | Prejoin-Whitelist + Passwort-Setzen + Integritätsprüfung + Fehlversuch-Sperre + Kick-Takt | **Empfohlen**: gleiche Technik wie `gameworld_status`, rund 70 Zeilen Lua, keine Fremdpflege, keine Lizenzfragen, Grundlage für Phase 4 |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Passwort-Setzen per Mod beim Prejoin | `auth.sqlite` direkt schreiben (get_archive, ändern, put_archive) | Nur bei gestopptem Server konsistent, Einladung erfordert Neustart, SQLite-Datei aus dem Volume laden und zurückspielen; keine Vorteile |
| Verifier in Python | Klartextpasswort in die Datei, Mod hasht | Klartext läge im Welt-Volume; `core.get_password_hash` erzeugt nur das alte SHA1-Format |
| Eigene SRP-Rechnung (stdlib) | PyPI `srp` 1.0.22 (cocagne/pysrp, Upload 01.11.2024) | Gleiche Mathematik (Luantis srp.cpp stammt von csrp desselben Autors), aber neue Abhängigkeit für 25 Zeilen; Luanti-Eigenheiten (Name kleinschreiben, kein Padding) muss man trotzdem selbst wissen. Eigene Implementierung ist per Golden Vector und Live-Login gegen Luanti abgesichert |
| Verwalter = Admin-Gruppe | eigene Gruppe `gameworld-eltern` mit Nicht-Admins | Nicht-Admins dürfen Gruppenmitglieder nicht auflösen (403 live), Verwaltungsrouten müssten USER werden und hingen allein an der Python-Prüfung. Siehe Open Question 1 |
| Gruppen dynamisch auflösen | einmalig bei Einladung in Einzelnutzer auflösen | Einfacher, aber neue Gruppenmitglieder bekämen nie Zugang und Ausgetretene behielten ihn |

**Installation:** keine neuen Pakete.

## Package Legitimacy Audit

Diese Phase installiert keine neuen npm-, PyPI- oder ContentDB-Pakete. Die bewerteten Whitelist-Mods werden ausdrücklich nicht übernommen; `srp` (PyPI) wird nicht empfohlen.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| (keine) | - | - | - | - | n/a | - |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Browser (Nextcloud-Sitzung)
  | Kind:      GET /api/me -> GET /api/my/worlds  (Verbindungsinfo, eigenes Passwort)
  | Verwalter: + /api/worlds..., /api/worlds/{id}/invites, /api/settings
  | Verwalter-Suche: GET /ocs/v2.php/core/autocomplete/get (direkt an Nextcloud)
  v
[Nextcloud AppAPI-Proxy]  Route-Check: erste passende Route (Pfad+Verb) gewinnt
  |  USER : ^/js/.*, ^/img/.*, ^/api/me$, ^/api/my/.*
  |  ADMIN: ^/api/.*   (Nicht-Admin -> AppAPI lehnt ab, ExApp sieht den Request nie)
  v  Header AUTHORIZATION-APP-API = base64(uid:secret)
[Gameworld ExApp (FastAPI)]  AppAPIAuthMiddleware -> scope["username"]
  |-- RoleService: Selbstauskunft als uid (/cloud/user, groups) -> "admin" in groups? (Cache 30 s)
  |     Verwalter-Endpunkte: require_verwalter (403 sonst, zweite Schicht)
  |-- AccessService (unter Service-Lock)
  |     Einladung -> NC prüfen (als Verwalter: get_user / get_members)
  |     -> players (Name, Passwort), world_access (Verifier je Welt) -> Generation + 1
  |     -> render_access_file -> put_archive (laufend oder gestoppt; fehlt Container: beim Start)
  |-- Spieler-Selbstbesuch: eigene Gruppen (Selbstauskunft) ∩ eingeladene Gruppen -> lazy provisionieren
  v
DockerProvisioner.write_access(world_id, bytes)  (put_archive nach .../worlds/world, root 0444)
  v  tecnativa-Proxy (PUT /containers/{id}/archive, POST=1)
[Luanti 5.17.0 Container]
   worldmods/gameworld_access:  Prejoin: Datei laden (nur bei Kopf+Schluss gültig)
                                 Name fehlt -> ACCESS_DENIED "nicht eingeladen"
                                 Name da -> Passwort-Verifier setzen, falls abweichend
                                 Fehlversuche (on_authplayer) -> Sperre
                                 alle 5 s: Datei laden, Nicht-mehr-Eingeladene kicken,
                                           gameworld_access_state.txt (geladene Generation)
   danach normale SRP-Anmeldung des Clients gegen den gesetzten Verifier
```

### Recommended Project Structure (Änderungen)
```
src/gameworld/
├── provisioner/
│   ├── luanti_auth.py     # NEU (pure): make_verifier(name, password, salt=None), N/G-Konstanten
│   ├── access_mod.py      # NEU: Lua-Quelltext gameworld_access, mod.conf, ACCESS_FILE, STATE_FILE,
│   │                      #      render_access_file(generation, entries) -> bytes, parse_access_state
│   ├── archive.py         # Payload um worldmods/gameworld_access und leere Zugangsdatei erweitern
│   ├── spec.py            # Label gameworld.schema "3" für neue Container
│   └── client.py          # + write_world_files(world_id, files) (put_archive, auch laufend), read_access_state
├── access/                # NEU
│   ├── names.py           # pure: suggest_player_name(display_name, uid, taken), PLAYER_NAME_RE
│   ├── passwords.py       # pure: generate_password() aus Wortliste (ASCII) + secrets
│   ├── words.py           # kuratierte Wortliste (ASCII, kindgerecht)
│   ├── roles.py           # Role-Enum, RoleService (Selbstauskunft, Cache), Abhängigkeiten current_user/require_verwalter
│   └── service.py         # AccessService: invite/revoke/sync/regenerate, effektive Spieler je Welt
├── worlds/store.py        # Schema 3: players, invites, world_access, worlds.access_generation, meta.join_host
├── api/
│   ├── me.py              # NEU: GET /api/me, GET /api/my/worlds (USER)
│   ├── invites.py         # NEU: Einladungen, Passwort neu, Einstellungen (Verwalter)
│   └── worlds.py          # require_verwalter an allen Routen, world_key aus CreatedWorldOut entfernen
├── lifecycle.py           # top_menu.register(..., admin_required=False)
appinfo/info.xml           # Routen USER/ADMIN in der Reihenfolge unten
frontend/src/
├── App.vue                # lädt /api/me, schaltet ParentView / PlayerView
├── views/ParentView.vue   # bisheriges Dashboard + Spieler-Spalte + Einladen-Dialog + Einstellungen
├── views/PlayerView.vue   # Karten "Meine Welten" mit Verbindungsinfo und Anleitung
└── components/InviteDialog.vue, ConnectionCard.vue, JoinGuide.vue
tests/e2e/luanti_probe.py  # NEU (nur Test): UDP-Prober für Negativ-/Positiv-Join
scripts/dev/acceptance-phase3.sh
```

### Pattern 1: Welt-Mod `gameworld_access` (live verifiziert)
**What:** Whitelist und Passwort-Provisionierung in einem Mod, gespeist aus einer Datei, die nur die ExApp schreibt.
**Warum eigener Mod statt Whiter List:** gleiche Technik wie `gameworld_status` (bewährt unter `secure.enable_security = true`), Integritätsprüfung gegen halb geschriebene Dateien, Passwort-Setzen im selben Callback, Kick bei Widerruf, Rückmeldung der geladenen Generation an die ExApp, Fehlversuch-Sperre, Wiederverwendung in Phase 4 (Spielzeit: Kick-Takt und Prejoin-Sperre sind genau die Durchsetzungspunkte).

```lua
-- worldmods/gameworld_access/init.lua (Spike-Version, live getestet; Texte final mit Umlauten)
local world = core.get_worldpath()
local access_path = world .. "/gameworld_access.txt"
local state_path = world .. "/gameworld_access_state.txt"
local DENY = "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
local KICK = "Deine Einladung für diese Welt wurde beendet."
local LOCKED = "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen."

local allowed, last, generation = {}, nil, "0"

local function load()
  local f = io.open(access_path, "rb")
  if not f then return end                 -- fehlt (z. B. mitten im put_archive): alter Stand bleibt
  local content = f:read("*a")
  f:close()
  if content == last then return end
  local lines = content:split("\n")        -- leere Zeilen fallen weg
  local gen = (lines[1] or ""):match("^gameworld%-access 1 (%d+)$")
  if not gen or lines[#lines] ~= "end" then return end   -- unvollständig: alter Stand bleibt
  local new = {}
  for i = 2, #lines - 1 do
    local name, hash = lines[i]:match("^([%w_%-]+) (#1#[%w%+/=]+#[%w%+/=]+)$")
    if name and #name <= 20 then new[name] = hash end
  end
  allowed, last, generation = new, content, gen
  core.safe_file_write(state_path, generation)
end

local fails = {}                           -- Fehlversuch-Sperre, nur im Speicher
core.register_on_authplayer(function(name, _ip, ok)
  if ok then fails[name] = nil return end
  local now = core.get_us_time() / 1e6
  local f = fails[name]
  if not f or now - f.t > 600 then f = { n = 0, t = now } end
  f.n = f.n + 1
  fails[name] = f
end)

core.register_on_prejoinplayer(function(name)
  local f = fails[name]
  if f and f.n >= 5 and core.get_us_time() / 1e6 - f.t <= 600 then return LOCKED end
  load()
  local hash = allowed[name]
  if not hash then return DENY end
  local auth = core.get_auth_handler().get_auth(name)
  if not auth or auth.password ~= hash then
    core.set_player_password(name, hash)   -- legt das Konto an oder setzt das Passwort zurück
  end
end)

local function tick()
  load()
  for _, player in ipairs(core.get_connected_players()) do
    local name = player:get_player_name()
    if not allowed[name] then core.kick_player(name, KICK) end
  end
  core.after(5, tick)
end
core.register_on_mods_loaded(function() core.after(0, tick) end)
```
- Prejoin läuft vor der Auth-Ermittlung (`serverpackethandler.cpp` 5.17.0, Z. 183 `on_prejoinplayer`, Z. 209 `getAuth`), daher wirkt das Passwort-Setzen schon für genau diesen Join [VERIFIED: Quelle + Spike A2/A3: HELLO mit `auth_mechs = 2` (SRP), danach AUTH_ACCEPT].
- `core.set_player_password` des Builtin-Handlers legt ein fehlendes Konto mit `default_privs` an (`builtin/game/auth.lua`, `set_password` ruft `create_auth`) [VERIFIED: Quelle].
- Passwort-Rücksetzen bei jedem Prejoin macht das App-Passwort maßgeblich: Ändert ein Kind sein Passwort im Spiel (ESC-Menü), gilt beim nächsten Join wieder das angezeigte [VERIFIED: Mechanik aus Quelle; Kind-seitige Änderung nicht live getestet].
- Keine Datei beim Start = niemand darf rein (fail closed, Spike A0). Halbe Datei = alter Stand (Spike A6). Widerruf wirkt beim nächsten Join sofort (A7), laufende Spieler werden im 5-s-Takt gekickt (Kick dokumentierte API `core.kick_player`, mit echtem Client nicht getestet).
- Die Builtin-Prejoin-Prüfung (läuft vor Mods) lehnt neue Konten ab, deren Name sich nur in Groß-/Kleinschreibung von einem bestehenden unterscheidet (Spike A5, englischer Text). Die ExApp vergibt Namen deshalb case-insensitiv eindeutig.
- Weder Minetest Game 38214 noch VoxeLibre 0.92.4 registrieren Auth-Handler oder Prejoin-Callbacks [VERIFIED: grep über alle .lua in beiden Zips]; der Builtin-Handler bleibt zuständig. Der Live-Spike lief mit Minetest Game; ein e2e-Test mit VoxeLibre gehört in den Plan.
- Fehlversuch-Sperre live: 5 falsche Passwörter in 0,12 s, danach auch das richtige Passwort abgelehnt mit Sperrtext [VERIFIED: Spike 3]. Ohne Sperre begrenzt nur Luantis Neu-Peer-Limit (30 pro Sekunde, `threads.cpp` `MAX_NEW_PEERS_PER_SEC`) das Raten.

### Pattern 2: SRP-Verifier in Python (live gegen Luanti verifiziert)
```python
# provisioner/luanti_auth.py (pure, stdlib). Quelle: luanti 5.17.0 src/util/auth.cpp gen_srp_v,
# src/util/srp.cpp calculate_x / srp_create_salted_verification_key, NG_2048 aus srp.cpp.
import base64, hashlib, secrets

N = int("AC6BDB41324A9A9BF166DE5E1389582FAF72B6651987EE07FC3192943DB56050A37329CBB4A099ED8193E0757767A13DD52312AB4B03310D"
        "CD7F48A9DA04FD50E8083969EDB767B0CF6095179A163AB3661A05FBD5FAAAE82918A9962F0B93B855F97993EC975EEAA80D740ADBF4FF74"
        "7359D041D5C33EA71D281E446B14773BCA97B43A23FB801676BD207A436C6481F1D2B9078717461A5B9D32E688F87748544523B524B0D57D"
        "5EA77A2775D2ECFA032CFBDBF52FB3786160279004E57AE6AF874E7303CE53299CCC041C7BC308D82A5698F3A8D0C38271AE35F8E9DBFBB6"
        "94B5C803D89F7AE435DE236D525F54759B65E372FCD68EF20FA7111F9E4AFF73", 16)
G = 2

def _bin(n: int) -> bytes:                      # mpz_to_bin: Big-Endian, ohne führende Nullen
    return n.to_bytes((n.bit_length() + 7) // 8, "big")

def make_verifier(name: str, password: str, salt: bytes | None = None) -> str:
    salt = secrets.token_bytes(16) if salt is None else salt          # Luanti: 16 Byte Zufall
    inner = hashlib.sha256(name.lower().encode() + b":" + password.encode()).digest()
    x = int.from_bytes(hashlib.sha256(salt + inner).digest(), "big")
    v = pow(G, x, N)
    return f"#1#{base64.b64encode(salt).decode()}#{base64.b64encode(_bin(v)).decode()}"
```
**Golden Vector** (von Luanti 5.17.0 im Spike 3 per echtem SRP-Login akzeptiert): `make_verifier("Mia", "Sonne-Baum-42", bytes(range(16)))` ergibt
`#1#AAECAwQFBgcICQoLDA0ODw==#pCyNep+1Ug3he9xjpqMCK1MBx7OOe2SLVkX1lvyHmIf8bATbrA6zgiJ/+xEmx+MaV+IllHKn1rqJHViRuv9ysMGPSDxm5xWmTyhasxEQtfWJI1EiyABU/v15UncRaqWEr+OvrPXxcsb3QCsQrZ8cYd1vgRaJByW7QmW75Le8VriHfR+/xNSE2hHnmFd60n0eOlufj7UBtmfTmFOIO/uHbnvA74UHr3LnoeimBaOXvo4OR9NorNAjcVYraZ0i9HvO98VoRCKxvFsYXrbnfHJGE+3VWpsAPqmcGXzfFTkrzrfPY78b7lOjUMReiUf2zchmlwcNc12S46iQOEHkiFsdhw==`
Derselbe Verifier für den Namen `Leo` wird abgelehnt (Name steckt in x), `mia` und `Mia` ergeben denselben Verifier (Kleinschreibung) [VERIFIED: Spike].
- Rechenzeit: eine 2048-Bit-Potenz, Millisekunden. Kein Thread nötig, aber unschädlich.
- Der Klartext verlässt die ExApp nur Richtung Browser (Verbindungsinfo), nie Richtung Volume.

### Pattern 3: Zugangsdatei und Schreibzeitpunkte
**Format** (`.minetest/worlds/world/gameworld_access.txt`, root, 0444, UTF-8/ASCII):
```
gameworld-access 1 <generation>
Mia #1#...#...
Leo #1#...#...
end
```
- `generation` ist eine pro Welt hochgezählte Zahl (`worlds.access_generation`). Der Mod schreibt die zuletzt geladene Generation nach `gameworld_access_state.txt`; die ExApp liest sie per `get_archive` und zeigt "Zugangsschutz aktiv" bzw. erkennt, dass eine laufende Welt den Mod noch nicht geladen hat (Datei fehlt oder `mtime < State.StartedAt`). Gleiches Muster wie die Bereitschaftsprüfung in Phase 2.
- Zeilen sortiert, deterministisch: gleicher Soll-Zustand ergibt identische Bytes (Verifier mit gespeichertem Salz, nicht bei jedem Rendern neu).
- **Schreibzeitpunkte:** (1) im Erzeugungs-Payload (Kopf + `end`, keine Namen: neue Welt ist zu, bis jemand eingeladen ist); (2) in `_launch` vor jedem `start` zusammen mit beiden Welt-Mods (aktualisiert Mod-Code bei App-Updates und rüstet Schema-2-Welten nach); (3) nach jeder Änderung an Einladungen, Namen oder Passwörtern sofort per `put_archive` in den laufenden oder gestoppten Container. Fehlt der Container, nichts tun (Start schreibt).
- `put_archive` durch den Proxy: laufend 0,01 s, gestoppt ebenso; der `PUT /containers/{id}/archive` fällt unter `CONTAINERS=1` + `POST=1` [VERIFIED: Spike 1 und 2]. Docker ersetzt eine vorhandene Datei beim Entpacken, der Mod sieht dabei kurz "fehlt" oder "unvollständig" und behält den alten Stand.
- Mod-Code wird nur beim Serverstart geladen: Neue Mod-Version wirkt erst nach Neustart der Welt; die Zugangsdatei wirkt sofort.

### Pattern 4: Rollen und Routen
**Rollenmodell (Empfehlung):** Verwalter = Nextcloud-Konten in der Gruppe `admin`; Spieler = jedes Nextcloud-Konto, das direkt oder über eine Gruppe in mindestens eine Welt eingeladen ist; alle anderen sehen eine leere Ansicht ("Du bist noch zu keiner Welt eingeladen"). Verwalter können sich selbst einladen und sehen dann zusätzlich ihre eigene Verbindungsinfo.

**info.xml (Reihenfolge ist Semantik: erste passende Route aus Pfad und Verb gewinnt, kein Weiterfallen):**
```xml
<route><url>^/js/.*</url><verb>GET</verb><access_level>USER</access_level><headers_to_exclude>[]</headers_to_exclude></route>
<route><url>^/img/.*</url><verb>GET</verb><access_level>USER</access_level><headers_to_exclude>[]</headers_to_exclude></route>
<route><url>^/api/me$</url><verb>GET</verb><access_level>USER</access_level><headers_to_exclude>[]</headers_to_exclude></route>
<route><url>^/api/my/.*</url><verb>GET</verb><access_level>USER</access_level><headers_to_exclude>[]</headers_to_exclude></route>
<route><url>^/api/.*</url><verb>GET,POST,DELETE</verb><access_level>ADMIN</access_level><headers_to_exclude>[]</headers_to_exclude></route>
```
- AppAPI baut das Muster als `~^(?:<url>)~i` gegen den Pfad mit führendem Schrägstrich, ohne End-Anker: darum `^/api/me$` (sonst träfe `^/api/me` auch `/api/members`) [VERIFIED: ExAppProxyController.php `passesExAppProxyRoutesChecks`, Dev-Container NC 34.0.3]. Werte `PUBLIC`/`USER`/`ADMIN` werden auf 0/1/2 abgebildet (`ExAppService::mapExAppRouteAccessLevelNameToNumber`), HaRP nutzt dieselben Ebenen (`HarpController`).
- `lifecycle.py`: `top_menu.register(..., admin_required=False)`, sonst liefert `TopMenuController.php:65` Nicht-Admins weiter 404 für die Seite.
- **Python-Prüfung bleibt Pflicht** (zweite Schicht): Jede Verwaltungsroute hängt an `require_verwalter`. Grund: Route-Regex, Pfadnormalisierung in Zwischenschichten (AppAPI, HaRP, Guzzle) und spätere Routenänderungen sind keine Garantie; ROLLE-01 verlangt serverseitige Sperre.

```python
# access/roles.py (Skizze)
from fastapi import Depends, HTTPException, Request, status
from nc_py_api import AsyncNextcloudApp

ADMIN_GROUP = "admin"

def current_user(request: Request) -> str:
    uid = request.scope.get("username") or ""          # gesetzt von AppAPIAuthMiddleware
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nicht angemeldet.")
    return uid

async def own_groups(uid: str) -> list[str]:
    nc = AsyncNextcloudApp()
    await nc.set_user(uid)
    return (await nc.users.get_user()).groups          # /ocs/v1.php/cloud/user, Selbstauskunft

async def require_verwalter(uid: str = Depends(current_user)) -> str:
    if ADMIN_GROUP not in await role_cache.groups(uid):  # TTL 30 s; Nextcloud-Fehler -> 503, nie "Verwalter"
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nur Eltern können Welten verwalten.")
    return uid
```
Live-Belege (ExApp-Impersonation mit dem Dev-Secret): Selbstauskunft liefert `groups` für Kind, Nicht-Admin und Admin; `users_groups.get_members` als Nicht-Admin: `NextcloudException [403] Logged in account must be at least a sub admin`; als Admin: Mitgliederliste; `core/autocomplete/get` als Nicht-Admin: Nutzer und Gruppen gemäß Sharing-Regeln [VERIFIED: Live-Probe 19.10.2026, Wegwerfkonten danach gelöscht]. Ohne Nutzer-Kontext (leere uid) sind Provisioning-Endpunkte nicht erreichbar; `AppApiAdminAccessWithoutUser` tragen in NC 34 nur die webhook_listeners-Endpunkte [VERIFIED: grep im Dev-Container].

### Pattern 5: Datenmodell (Schema 3) und Gruppenauflösung
```sql
-- Migration idempotent wie Schema 2: CREATE TABLE IF NOT EXISTS + ALTER nur bei fehlender Spalte
CREATE TABLE IF NOT EXISTS players (
  nc_user TEXT PRIMARY KEY,                       -- Nextcloud-Konto-ID, einzige Identität (ROLLE-02)
  player_name TEXT NOT NULL UNIQUE COLLATE NOCASE,-- Luanti-Name, global je Instanz, case-insensitiv eindeutig
  password TEXT NOT NULL,                         -- Klartext (Spielpasswort, nie das NC-Passwort), siehe A3
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invites (
  world_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('user', 'group')),
  target TEXT NOT NULL, invited_by TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (world_id, kind, target)
);
CREATE TABLE IF NOT EXISTS world_access (          -- effektive Spieler je Welt (Ergebnis der Auflösung)
  world_id TEXT NOT NULL, nc_user TEXT NOT NULL, verifier TEXT NOT NULL,
  PRIMARY KEY (world_id, nc_user)
);
-- ALTER TABLE worlds ADD COLUMN access_generation INTEGER NOT NULL DEFAULT 0
-- meta: join_host (Spieler-Adresse, leer = Browser-Hostname)
```
- Spielername und Passwort **pro Nextcloud-Konto**, gleich in allen Welten: Ein Kind merkt sich einen Namen und ein Passwort; nur Adresse und Port unterscheiden sich. Verifier pro Welt mit eigenem Salz.
- Löschen einer Welt löscht `invites` und `world_access` explizit im Dienst (die Store-Verbindungen setzen kein `PRAGMA foreign_keys`).
- **Auflösung (dynamisch):** `world_access(W) = direkte Nutzer ∪ Mitglieder eingeladener Gruppen`, ohne deaktivierte oder gelöschte Konten. Synchronisiert wird (a) bei jeder Einladungsänderung (als handelnder Verwalter: `get_user(uid)` prüft Existenz/`enabled`, `get_members(gid)` löst auf), (b) wenn ein Verwalter die Weltliste lädt (gedrosselt, höchstens alle 60 s), (c) beim Besuch eines Spielers: eigene Gruppen per Selbstauskunft gegen eingeladene Gruppen, fehlender Zugang wird nachprovisioniert (nur Hinzufügen; Entfernen braucht Verwalter-Kontext). Ein periodischer Hintergrundabgleich ist nicht nötig (DEFERRED, Open Question 4).
- Validierung der Auswahl im Backend: Der Browser liefert nur IDs; das Backend akzeptiert nur Konten/Gruppen, die Nextcloud dem Verwalter bestätigt (Existenz, aktiv). `target` begrenzt auf 64 Zeichen, keine Steuerzeichen.

### Pattern 6: Spielernamen und Passwörter
- **Luanti-Regeln:** 1 bis 20 Zeichen aus `[A-Za-z0-9_-]` (`PLAYERNAME_SIZE 20`, `PLAYERNAME_ALLOWED_CHARS` in `src/player.h`), `singleplayer` (beliebige Schreibweise) verboten (`serverpackethandler.cpp`), neue Konten dürfen sich nicht nur in Groß-/Kleinschreibung von bestehenden unterscheiden (Builtin-Prejoin) [VERIFIED: Quelle 5.17.0].
- **Vorschlag:** erster Teil des Nextcloud-Anzeigenamens, transliteriert (ä zu ae, ö zu oe, ü zu ue, ß zu ss, Rest per NFKD auf ASCII), unerlaubte Zeichen entfernt, auf 18 Zeichen gekürzt, leer wird `Spieler`; bei Kollision (NOCASE) Ziffer anhängen (`Mia2`). In Python die Umlaute in der Umschreibtabelle als Escapes (`"\u00e4"`) schreiben (Owner-Regel: keine Umlaute im Code).
- **Datensparsamkeit (Pitfall 9 der Projekt-Research):** Der Spielername ist nur für Eingeladene derselben Welt sichtbar. Vorschlag aus dem Vornamen ist kindgerecht; Eltern dürfen den Namen ändern (validiert). Umbenennen erzeugt in Luanti ein neues Konto (Inventar des alten Namens bleibt verwaist): in der UI warnen.
- **Passwort:** `Wort-Wort-Zahl` (z. B. `Tiger-Wolke-42`), Wörter aus einer kuratierten ASCII-Liste kindgerechter Nomen ohne Umlaute, Zahl 10 bis 99, Zufall nur über `secrets`. Mit 256 Wörtern rund 22,6 Bit; zusammen mit der Mod-Sperre (5 Fehlversuche, 10 min) ist Online-Raten praktisch ausgeschlossen. Ohne Sperre wären bei 30 Versuchen pro Sekunde rund 30 Stunden für die Hälfte des Raums nötig, darum Sperre Pflicht. "Neues Passwort" für Verwalter (rechnet alle Verifier des Kontos neu und schreibt alle betroffenen Welten).
- **Weltschlüssel:** `default_password = world_key` bleibt als zweite Sperre in der conf, wird aber nicht mehr angezeigt (Spike A9: öffnet provisionierte Konten nicht). `CreatedWorldOut.world_key` und die Erfolgskarte im Dashboard entfallen; stattdessen Hinweis "Lade jetzt Spieler ein".

### Pattern 7: Verbindungsinfo und Spieler-Adresse
- **Port:** `worlds.port` (Host-UDP-Port, Bindung `0.0.0.0`, Phase 1).
- **Adresse:** Die ExApp kann die LAN-Adresse des Docker-Hosts nicht zuverlässig selbst ermitteln (unter HaRP läuft sie in einem Container mit Bridge-IP, im Dev als Host-Prozess). Empfehlung: Einstellung `join_host` (Verwalter, gespeichert in `meta`), Vorgabe leer = `window.location.hostname` des Browsers. Das passt zum Normalfall "Nextcloud und Docker auf demselben Heimserver". Validierung: Hostname oder IP-Literal, max. 253 Zeichen, keine Schemata/Pfade.
- **Warnhinweise im UI** (NcNoteCard, nur Verwalter): Hostname `localhost`/`127.*`/`::1` ("Andere Geräte erreichen diese Adresse nicht"), Hostname eines Tunnels oder Reverse-Proxys ("UDP läuft nicht durch einen Web-Tunnel; trag die Adresse des Heimservers im Heimnetz ein"). Erreichbarkeit aus dem Internet bleibt Out of Scope (VPN dokumentiert).
- **Anleitung (Kind, Deutsch, Vorschlag):**
  1. Luanti installieren: luanti.org/downloads (Windows, macOS, Linux; Android über Google Play oder F-Droid). Für iPhone/iPad gibt es keine offizielle Version [VERIFIED: luanti.org/en/downloads, Version 5.17.0].
  2. Luanti öffnen und den Reiter zum Beitreten eines Servers wählen.
  3. Adresse `<host>` und Port `<port>` eintragen.
  4. Name `<player_name>` und Passwort `<password>` genau so eintragen (Groß- und Kleinschreibung zählt).
  5. Auf "Beitreten" tippen. Beim ersten Mal lädt Luanti die Spieldateien vom Server, das kann bei "Abenteuer (sanft)" etwas dauern.
  Genaue Beschriftungen des deutschen Luanti-Menüs sind nicht geprüft (A6); Abnahme mit echtem Client.
- Kopieren per `NcFormBoxCopyButton` für Adresse, Port, Name, Passwort; Passwort standardmäßig verdeckt mit "Anzeigen".

### Pattern 8: UI-Struktur (eine Vue-App, zwei Ansichten)
- `App.vue` lädt zuerst `GET /api/me` (`{user_id, display_name, role: "verwalter" | "spieler"}`). Der Initial State eignet sich nicht: er wird beim Aktivieren global gesetzt (`lifecycle.py`), nicht pro Nutzer.
- `role === "verwalter"`: bisheriges Dashboard plus Spalte "Spieler" (Anzahl, Namen), Knopf "Einladen" pro Welt (`NcDialog` mit `NcSelectUsers`, mehrfach, Optionen aus `core/autocomplete/get` mit `shareTypes[]=0` und `shareTypes[]=1`, Gruppen mit `isNoUser: true` und Gruppen-Icon), Liste der Spieler mit Name, Passwort (verdeckt, kopierbar), "Neues Passwort", "Entfernen"; Einstellungen (`join_host`). Wenn selbst eingeladen: zusätzlich "Meine Verbindungsinfo".
- `role === "spieler"`: nur Karten "Meine Welten" aus `GET /api/my/worlds` mit Status (läuft/gestoppt, ohne Steuerknöpfe), Verbindungsinfo und Anleitung; leer: `NcEmptyContent` "Du bist noch zu keiner Welt eingeladen".
- Spielerantwort enthält ausschließlich eigene Daten (eigener Name, eigenes Passwort, Adresse, Port, Weltname, Status); keine Liste anderer Spieler, keine Container-Details, kein RAM.
- Polling wie Phase 2 (5 s bei sichtbarem Tab) auch in der Spieleransicht, damit "läuft" sichtbar wird.

### Anti-Patterns to Avoid
- **Whitelist nur in der DB oder im UI:** erfüllt ZUGANG-03 nicht; Durchsetzung gehört in den Prejoin des Servers.
- **Zugangsdatei ohne Kopf/Schluss oder "fehlt = alle raus":** `put_archive` ersetzt Dateien nicht atomar; Leser muss halbe und fehlende Dateien als "unverändert" behandeln.
- **Klartextpasswörter ins Welt-Volume:** nur Verifier; Klartext bleibt in der ExApp-DB.
- **`auth.sqlite` bei laufendem Server schreiben:** Inkonsistenz, Neustartpflicht.
- **Rollenprüfung nur über AppAPI-Routen oder nur im Frontend:** zweite Schicht in Python ist Pflicht.
- **Spielername aus der NC-Konto-ID oder E-Mail:** IDs können Punkte, @, Leerzeichen enthalten und verraten Kontodaten.
- **Verifier bei jedem Rendern neu salzen:** ändert die Datei ohne Soll-Änderung, Mod setzt bei jedem Join das Passwort neu, Generation verliert ihre Aussagekraft.
- **Admin-`name` in der conf setzen, um Eltern im Spiel Rechte zu geben:** gibt automatisch alle Privilegien; bleibt verboten.
- **Gruppenmitglieder als Nicht-Admin auflösen wollen:** 403; nur im Verwalter-Kontext.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Whitelist-Durchsetzung | Proxy-/Firewall-Filter vor dem UDP-Port | Luanti-Prejoin-Callback im Welt-Mod | Spielername steht erst im TOSERVER_INIT; Engine liefert Ablehnung mit Text |
| Konto anlegen/Passwort setzen | Schreiben in `auth.sqlite` | `core.set_player_password` (Builtin-Handler) | Konsistent im laufenden Server, legt Konto mit `default_privs` an |
| Passwortprüfung im Mod | eigener Vergleich | Luantis SRP-Anmeldung gegen den gesetzten Verifier | Der Server prüft selbst; Mod setzt nur den Verifier |
| Zufall für Passwörter/Salz | `random` | `secrets.choice`, `secrets.token_bytes` | Kryptographisch sicher |
| Nutzer-/Gruppensuche | eigene Nutzerliste in der App | `core/autocomplete/get` (Nextcloud) + `NcSelectUsers` | Nextcloud-Sichtbarkeitsregeln, keine eigene Benutzerverwaltung (ROLLE-02) |
| Rollen | eigene Rollentabelle | Gruppenmitgliedschaft aus Nextcloud | ROLLE-02 |
| Join-Test | manueller Test mit Client | `tests/e2e/luanti_probe.py` (MTP + SRP, Code unten) | Automatisierter Negativ- und Positiv-Join, kein Client auf der Maschine |

**Bewusste Ausnahme:** Der SRP-Verifier wird selbst gerechnet (25 Zeilen stdlib), weil es keine Luanti-spezifische Bibliothek gibt und die einzige Kandidatin (`srp`) nur dieselbe Formel kapselt. Abgesichert durch Golden Vector und Live-Login gegen Luanti.

## Runtime State Inventory

Phase 3 ändert Schema, Routen, Container-Inhalt und Abnahmeskripte.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `.dev/storage/gameworld.sqlite3`: Schema 2, `instance_id 788fff30`, 0 Welten (geprüft 19.10.); bestehende Welten bei Owner/Tests haben keine Zugangsdatei | Code: Migration auf Schema 3 (neue Tabellen, Spalte `access_generation`); Datenmigration: keine Zeilen nötig. Schema-2-Welten bekommen Mod + leere Zugangsdatei beim nächsten Start (`_launch`) und sind danach zu, bis jemand eingeladen ist |
| Live service config | AppAPI-Routen in der Nextcloud-DB, registriert aus info.xml durch `register-exapp.sh` (liest Routen inkl. Ebene aus info.xml) | Nach info.xml-Änderung `register-exapp.sh` erneut laufen lassen; Top-Menü wird beim Aktivieren neu registriert (`admin_required=False`) |
| OS-registered state | Keine | Keine |
| Secrets/env vars | Keine neuen; `world_key` bleibt in DB und conf | Keine; Anzeige des Weltschlüssels entfällt |
| Build artifacts | `js/gameworld-main.js` (gitignored) | Bundle neu bauen |
| Tests/Abnahmen | `tests/test_info_xml.py` prüft "alle Routen ADMIN"; `scripts/dev/acceptance-phase1.sh` K1 erwartet 404 für Nicht-Admin auf Seite/Bundle/API (Variante A); Dev-Nutzer `gw-kind` / `gw-kind-dev-pass-1` existiert | Test und Phase-1-Abnahme an das neue Verhalten anpassen (Seite und Bundle 200, `/api/worlds` weiter abgelehnt, `/api/me` 200 mit Rolle spieler); `gw-kind` als Kind-Konto in Phase-3-Abnahme nutzen |

## Common Pitfalls

### Pitfall 1: Route-Reihenfolge und fehlender End-Anker
**What goes wrong:** `^/api/.*` (ADMIN) vor `^/api/me` gelistet macht `/api/me` für Kinder unerreichbar; `^/api/me` ohne `$` öffnet jede Route, die mit `/api/me` beginnt.
**How to avoid:** USER-Routen zuerst, End-Anker, Test in `test_info_xml.py` auf Reihenfolge und Anker; Python-Prüfung bleibt.
**Warning signs:** Kind bekommt 404 auf `/api/me`; neue Route `/api/members...` ist für Kinder erreichbar.

### Pitfall 2: Halb geschriebene Zugangsdatei sperrt alle aus oder lässt alle rein
**What goes wrong:** Docker entpackt beim `put_archive` über die bestehende Datei; ein Mod-Leser im falschen Moment sieht nichts oder eine halbe Liste.
**How to avoid:** Kopf mit Generation plus Schlusszeile `end`; fehlend oder unvollständig = alter Stand (Spike A6). Start ohne Datei = niemand.

### Pitfall 3: Groß-/Kleinschreibung bei Spielernamen
**What goes wrong:** `Mia` und `mia` als zwei Kinder: Luanti lehnt das zweite neue Konto ab (Builtin-Prejoin, englischer Text, Spike A5); oder Kind tippt `mia` statt `Mia` und bekommt eine verwirrende Meldung.
**How to avoid:** `UNIQUE COLLATE NOCASE`; in der Anleitung "genau so eintragen"; optional im Mod: Prejoin mit Namen, der nur in der Schreibweise abweicht, mit deutschem Hinweis "Achte auf Groß- und Kleinschreibung: <Name>" ablehnen.

### Pitfall 4: Mod-Änderung wirkt nicht auf laufende Welten
**What goes wrong:** `put_archive` des neuen Mod-Codes in eine laufende Welt ändert nichts, Luanti lädt Mods nur beim Start. Schema-2-Welten, die beim Update laufen, setzen keine Whitelist durch (nur Weltschlüssel).
**How to avoid:** Dashboard zeigt bei laufenden Welten ohne aktuelle `gameworld_access_state.txt` (fehlt oder `mtime < StartedAt`) "Neustart nötig, damit nur Eingeladene spielen können"; Mods und Datei in `_launch` immer neu schreiben. Kein automatischer Neustart (Reconciler-Regel aus Phase 2).

### Pitfall 5: Rollenprüfung schlägt bei Nextcloud-Fehler "offen" fehl
**What goes wrong:** Selbstauskunft wirft (Nextcloud kurz weg), Code behandelt das als "kein Fehler" und lässt durch, oder als "Spieler" und zeigt einem Verwalter die Kinderansicht.
**How to avoid:** Fehler = 503 mit verständlicher Meldung, nie Verwalter-Rechte ableiten; Cache nur für erfolgreiche Antworten.

### Pitfall 6: Gruppen-Einladung durch Nicht-Admin
**What goes wrong:** Bei einer späteren Verwalter-Gruppe ohne Admin-Rechte schlägt `get_members` mit 403 fehl.
**How to avoid:** In Phase 3 Verwalter = Admins; Erweiterung erst mit eigener Lösung (Open Question 1).

### Pitfall 7: Kind sieht fremde Passwörter
**What goes wrong:** `/api/my/worlds` liefert die Spielerliste der Welt mit.
**How to avoid:** Spielerantwort nur aus der eigenen `players`-Zeile; Test als `gw-kind`, dass keine fremden Namen/Passwörter in der Antwort stehen.

### Pitfall 8: Passwort-Änderung im Spiel
**What goes wrong:** Kind ändert im Spielmenü das Passwort, die Verbindungsinfo stimmt nicht mehr.
**How to avoid:** Mod setzt beim nächsten Prejoin den App-Verifier zurück (Pattern 1); Hinweis in der Anleitung "Passwort nicht im Spiel ändern".

### Pitfall 9: IP-Adressen in Container-Logs
**What goes wrong:** Luanti loggt abgelehnte Joins mit IP (`tried to connect from ::ffff:172.17.0.1`, Spike-Log).
**How to avoid:** Logs nie ins Dashboard; Rotation 5 MB x 2 bleibt; in privacy.md (Phase 6) erwähnen.

### Pitfall 10: Abnahmeskripte aus Phase 1 brechen
**What goes wrong:** `acceptance-phase1.sh` erwartet 404 für Nicht-Admins auf Seite und Bundle.
**How to avoid:** Erwartung im selben Plan anpassen, der die Routen ändert; Gegenprobe: `/api/worlds` bleibt für `gw-kind` gesperrt.

## Code Examples

### Zugangsdatei rendern (pure)
```python
# provisioner/access_mod.py
ACCESS_FILE = f"{DATA_DIR}/.minetest/worlds/world/gameworld_access.txt"
ACCESS_HEADER = "gameworld-access 1"
_NAME = re.compile(r"[A-Za-z0-9_-]{1,20}")
_VERIFIER = re.compile(r"#1#[A-Za-z0-9+/=]+#[A-Za-z0-9+/=]+")

def render_access_file(generation: int, entries: dict[str, str]) -> bytes:
    lines = [f"{ACCESS_HEADER} {generation}"]
    for name, verifier in sorted(entries.items()):
        if not (_NAME.fullmatch(name) and _VERIFIER.fullmatch(verifier)):
            raise ValueError("ungültiger Zugangseintrag")      # nie still überspringen
        lines.append(f"{name} {verifier}")
    lines.append("end")
    return ("\n".join(lines) + "\n").encode("ascii")
```

### Datei in laufende oder gestoppte Welt schreiben (Provisioner)
```python
def write_world_files(self, world_id: str, files: dict[str, tuple[bytes, int, int]]) -> None:
    """files: Pfad relativ zum Weltordner -> (Inhalt, uid, mode). Kein exec, nur put_archive."""
    with self._guarded():
        container = self._owned(world_id)
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for name, (data, uid, mode) in files.items():
                info = _file_info(name, len(data), uid=uid, mode=mode)   # _safe_relative vorher prüfen
                tar.addfile(info, io.BytesIO(data))
        if not container.put_archive(f"{DATA_DIR}/.minetest/worlds/world", buffer.getvalue()):
            raise ProvisionerError("Docker hat die Zugangsliste nicht angenommen.")
```

### Join-Prober für den Negativ-Join-Test (Kern, live verifiziert)
```python
# tests/e2e/luanti_probe.py (nur Test). Protokoll: src/network/mtp/internal.h, threads.cpp,
# client.cpp sendInit/startAuth, serverpackethandler.cpp handleCommand_Init/SrpBytesA/SrpBytesM.
PROTO = 0x4F457403          # Header: u32 protocol_id, u16 sender_peer_id, u8 channel
# 1. Dummy zuverlässig, peer_id 0, Kanal 0:  header + b"\x03" + seq(65500) + b"\x01" + u16(0)
#    -> Server: CONTROL SET_PEER_ID (zuverlässig, mit ACK [0x00 0x00 seq] quittieren)
# 2. TOSERVER_INIT (0x02) unzuverlässig auf Kanal 1: b"\x01" + u16(0x02)
#    + u8(29) + u16(0) + u16(37) + u16(53) + u16(len(name)) + name
#    -> TOCLIENT_HELLO (0x02): u8 ser, u16 0, u16 proto, u32 auth_mechs  (2 = SRP-Konto vorhanden)
#    -> TOCLIENT_ACCESS_DENIED (0x0A): u8 code (10 = CUSTOM_STRING), u16-String reason, u8 reconnect
# 3. optional SRP: TOSERVER_SRP_BYTES_A (0x51) zuverlässig Kanal 1: str16(A) + u8(1)
#    -> TOCLIENT_SRP_BYTES_S_B (0x60): str16(salt) + str16(B)
#    TOSERVER_SRP_BYTES_M (0x52): str16(M) -> TOCLIENT_AUTH_ACCEPT (0x03) oder ACCESS_DENIED code 0
# SRP-Client: u = H(pad(A)|pad(B)), k = H(N|pad(g)), S = (B - k*g^x)^(a + u*x) mod N, K = H(S),
#             M = H(H(N) xor H(g), H(name), salt, A, B, K)   (name in Originalschreibweise)
# Vollständige, getestete Fassung: .planning/phases/03-zugang-und-rollen/spike/luanti_probe.py + luanti_srp.py
```
Erwartete Ergebnisse (Spike 1, MTG-Welt, Port 30091 über Docker Desktop):
| Fall | Ergebnis |
|------|----------|
| keine Zugangsdatei, `Mia` | `denied CUSTOM_STRING "Du bist in diese Welt nicht eingeladen..."` |
| nicht eingeladen, `Fremder` | dito |
| eingeladen, nur HELLO | `hello proto 53 auth_mechs 2` |
| eingeladen, richtiges Passwort | `auth_accept` |
| eingeladen, falsches Passwort | `denied WRONG_PASSWORD` (Stufe M) |
| `mia` statt `Mia` | `denied CUSTOM_STRING "Cannot create new player called 'mia'..."` |
| halbe Datei geschrieben, `Mia` | `auth_accept` (alter Stand) |
| nach Widerruf `Mia` | `denied` |
| neuer Spieler `Leo` | `auth_accept` |
| `Leo` mit Weltschlüssel | `denied WRONG_PASSWORD` |

### Spieleransicht-Antwort
```python
class MyWorldOut(BaseModel):
    id: str
    name: str
    status: str            # running | starting | stopped | error | unknown (aus Docker)
    status_text: str
    host: str | None       # join_host oder None -> Browser-Hostname
    port: int
    player_name: str
    password: str          # nur das eigene
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Passwort-Hash `base64(sha1(name+pw))` (LEGACY_PASSWORD) | SRP-6a-Verifier `#1#salt#v` | Luanti/Minetest 0.4.13 (2015, est31) | `core.get_password_hash` liefert noch das Altformat; App schreibt direkt SRP |
| `core.register_on_auth_fail` | `core.register_on_authplayer(name, ip, is_success)` | dokumentiert als deprecated in 5.17.0 lua_api.md | Sperre über `on_authplayer` |
| ct_whitelist als empfohlene Lösung (Projekt-Research) | eigener Mod | ContentDB-Paket nicht mehr auffindbar (19.10.2026) | STACK.md/CLAUDE.md-Zeile veraltet |
| AppAPI-Routen-URL ohne Schrägstrich | kanonisch `^/pfad` | AppAPI 34 (Rückfall als veraltet markiert) | schon in Phase 1 umgesetzt |
| Variante A (Nicht-Admin 404 auf alles) | USER für Bundle/eigene Daten, ADMIN für Verwaltung | Phase 3 | Phase-1-Abnahme anpassen |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Verwalter = Nextcloud-Admin-Gruppe genügt für v1 (Familien-Normalfall: wer Nextcloud betreibt, ist Elternteil) | Pattern 4 | Zweites Elternteil ohne Admin-Rechte kann nicht verwalten; Owner bestätigen (Open Question 1) |
| A2 | Ein Spielername und ein Passwort pro Kind für alle Welten (statt pro Welt) | Pattern 5 | Ein Leck betrifft alle Welten des Kindes; dafür deutlich einfacher für Kinder. Owner bestätigen |
| A3 | Spielpasswort im Klartext in der ExApp-SQLite (nötig für die Verbindungsinfo) | Pattern 5 | DB-Leck zeigt Spielpasswörter (kein NC-Passwort, nur Spielzugang im LAN); Alternative: nur einmal anzeigen. Owner bestätigen, privacy.md in Phase 6 |
| A4 | Vorschlag Spielername aus Vorname des Anzeigenamens, änderbar durch Eltern | Pattern 6 | Datenschutzwunsch nach Pseudonymen; reine Default-Frage |
| A5 | Passwortformat `Wort-Wort-Zahl` mit ≥ 256 Wörtern plus Mod-Sperre reicht | Pattern 6 | Bei Verzicht auf die Sperre zu schwach; Sperre ist darum Pflichtteil des Mods |
| A6 | Deutsche Menübeschriftungen im Luanti-Client ("Spiel beitreten", "Beitreten") | Pattern 7 | Nur Anleitungstext; Abnahme mit echtem Client korrigiert |
| A7 | `core.kick_player` im 5-s-Takt trennt laufende Spieler nach Widerruf | Pattern 1 | Ohne Kick bliebe ein widerrufener Spieler bis zum Verlassen drin; Join danach ist live gesperrt. Abnahme mit Client |
| A8 | Browser-Hostname ist im Normalfall eine gute Vorgabe für die Spieler-Adresse | Pattern 7 | Bei Tunnel/Reverse-Proxy falsch; Einstellung und Warnhinweis fangen das ab |
| A9 | UTF-8-Umlaute in Ablehnungs-/Kicktexten werden im Luanti-Client korrekt angezeigt | Pattern 1 | Kosmetisch; Fallback ae/oe/ue |
| A10 | Fehlversuch-Sperre (5 in 10 min) ist als LAN-DoS-Risiko akzeptabel (jemand im Heimnetz kann ein Kind 10 min aussperren) | Pattern 1 | Familien-LAN, geringes Risiko; Werte konfigurierbar im Code |

## Open Questions (RESOLVED oder bewusst DEFERRED)

1. **Eltern ohne Nextcloud-Admin-Rechte als Verwalter?** (DEFERRED; für v1 durch Owner-Entscheid A1 vom 19.10.2026 gedeckt: Verwalter = Gruppe admin)
   - What we know: Nicht-Admins dürfen Gruppenmitglieder nicht auflösen (403 live) und keine fremden Konten lesen; Verwaltungsrouten müssten auf USER und hingen allein an Python.
   - Recommendation: v1 Verwalter = Admin-Gruppe (A1). Erweiterung "Gruppe gameworld-eltern" nur mit Gruppen-Einladung als Admin-Funktion oder Subadmin-Modell; erst bei Nachfrage echter Familien. Owner-Bestätigung im discuss/plan-Schritt.
2. **Welche Whitelist-Lösung?** (RESOLVED) Eigener Mod `gameworld_access`; Whiter List technisch gleichwertig für die reine Liste, aber ohne Integritätsprüfung, Passwort, Kick, Rückkanal und seit 2022 ohne Release; Zughy/whitelist nicht von außen steuerbar; ct_whitelist nicht auffindbar.
3. **Zusammenspiel Whitelist und Auth-Provisionierung, Rolle von `default_password`?** (RESOLVED) Ein Prejoin-Callback erledigt beides in der richtigen Reihenfolge (vor `getAuth`); `default_password` bleibt als unsichtbare zweite Sperre, öffnet provisionierte Konten nicht (Spike A9).
4. **Periodische Gruppen-Synchronisierung im Hintergrund?** (DEFERRED; Restrisiko als T-03-27 und T-03-44 in 03-04/03-06 akzeptiert) Ohne Nutzer-Kontext sind Provisioning-Endpunkte gesperrt; ein Hintergrundlauf müsste als gespeicherter Admin handeln. Die Synchronisierung bei Einladungsänderung, Verwalter-Besuch (gedrosselt) und Spieler-Besuch deckt den Familienalltag ab. Wiedervorlage, falls Austritte aus Gruppen spät wirken.
5. **Reload ohne Neustart?** (RESOLVED) Zugangsdatei: ja, sofort beim nächsten Join und im 5-s-Takt. Mod-Code: nur beim Start (Pitfall 4).
6. **Wie wird SC 2 ohne Luanti-Client getestet?** (RESOLVED) `tests/e2e/luanti_probe.py` (MTP + SRP) gegen eine echte Welt; zusätzlich Client-Abnahme durch den Owner (offen seit Phase 2) für Join, Kick und Anleitungstexte.
7. **Spieler-Adresse automatisch ermitteln?** (RESOLVED) Nicht zuverlässig möglich; Einstellung plus Browser-Hostname plus Warnhinweise.
8. **Darf ein Kind seine Welt starten?** (DEFERRED; Kind-Ansicht ohne Steuerknöpfe, 03-06) Nicht gefordert; Kinderansicht zeigt nur Status. Kandidat für Rückmeldungen echter Familien.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Desktop (WSL2) | Welten, Spike | ✓ | Engine 29.5.2 | - |
| Dev-Proxy `gameworld-dev-gameworld-docker-proxy-1` | Provisioner, `put_archive` | ✓ läuft, 127.0.0.1:23750 | tecnativa v0.5.0 | - |
| Dev-Nextcloud `gameworld-dev-app-1` | Rollen, Suche, UI | ✓ 127.0.0.1:8091, Admin `admin`, Kind `gw-kind` | 34.0.3, AppAPI 34.0.0 | - |
| Dev-ExApp | API | ✓ Heartbeat 200 auf 10040 | 0.1.0 | - |
| Luanti-Image | Welten | ✓ | 5.17.0 (Digest) | - |
| UDP-Erreichbarkeit veröffentlichter Ports vom Windows-Host | Join-Prober | ✓ (Spike, 127.0.0.1:30091/udp) | - | - |
| uv / Python / Node | Build, Tests | ✓ | 3.13 (.venv) / Node 22 | - |
| Luanti-Client | Kick-, Anleitungs-, UX-Abnahme | ✗ | - | Join-Prober für Durchsetzung; Owner-Rechner oder Client-Installation für die Abnahme |

RAM: rund 3,2 GB frei bei laufenden Findling-Stacks; Spike-Welten (MTG) passen, VoxeLibre-e2e seriell fahren.
Aufgeräumt: Spike-Container/-Volumes (`gameworld-spike3-*`) entfernt, Wegwerfkonten `spike_kind1`/`spike_eltern1` und Gruppen gelöscht; `gw-kind` unangetastet; keine Welt-Container übrig.

## Validation Architecture

Übersprungen: `workflow.nyquist_validation` ist in `.planning/config.json` auf `false` gesetzt. Testhinweise für den Planer stehen in Pitfalls, Code Examples (Prober-Erwartungstabelle) und Runtime State Inventory.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Nextcloud-Login + `AppAPIAuthMiddleware`; Spielzugang per SRP-6a (Luanti), Verifier aus App-generiertem Passwort, Fehlversuch-Sperre im Mod |
| V3 Session Management | no (Nextcloud-Sitzung, Luanti-Verbindung) | - |
| V4 Access Control | yes | AppAPI-Routen USER/ADMIN (erste Route gewinnt) plus `require_verwalter` in Python; Spielerantworten nur eigene Daten; Whitelist im Spielserver |
| V5 Input Validation | yes | Pydantic `extra="forbid"`, Spielername `[A-Za-z0-9_-]{1,20}` und NOCASE-eindeutig, NC-IDs nur nach Bestätigung durch Nextcloud, `join_host` als Hostname/IP validiert, Zugangsdatei nur aus validierten Einträgen |
| V6 Cryptography | yes | `secrets` für Passwort und Salz; SRP-Verifier nach Luanti-Spezifikation, Golden-Vector-Test |
| V8 Data Protection | yes | Klartext-Spielpasswort nur in ExApp-DB (A3), nur Verifier im Welt-Volume, keine IPs im UI |
| V12 Files | yes | Zugangsdatei root 0444, Pfade fest, `_safe_relative`, keine Nutzereingabe im Pfad |
| V14 Config | yes | Proxy-Flags unverändert; kein `name`-Admin, `default_privs` fest pro Preset |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Fremder im LAN joint mit beliebigem Namen | Spoofing | Prejoin-Whitelist vor Auth (Spike A1) |
| Fremder kapert eingeladenen Namen vor dem ersten Login | Spoofing | Passwort wird im selben Prejoin vor `getAuth` gesetzt, keine Erstregistrierung mit eigenem Passwort möglich (Spike A2/A3) |
| Passwort raten | Spoofing | 22+ Bit Passwort, Sperre nach 5 Fehlversuchen (Spike 3), Neu-Peer-Limit 30/s |
| Kind ruft Verwaltungs-API auf | Elevation of Privilege | AppAPI ADMIN-Route + `require_verwalter` (403) |
| Kind liest Passwörter anderer Kinder | Information Disclosure | `/api/my/*` nur eigene Zeile, Test mit `gw-kind` |
| Manipulierte Einladung (fremde/unsichtbare Konten, Injection in die Zugangsdatei) | Tampering | Backend bestätigt IDs bei Nextcloud; Datei nur aus validierten Namen/Verifiern, Zeilenformat strikt |
| Halbe Zugangsdatei öffnet/sperrt Welt | Tampering / DoS | Kopf + Schluss, alter Stand bei Fehler |
| Widerrufener Spieler bleibt verbunden | Elevation of Privilege | Kick im 5-s-Takt (A7) |
| Aussperren eines Kindes durch absichtliche Fehlversuche | DoS | Sperre nur 10 min (A10) |
| Rollenprüfung bei Nextcloud-Ausfall | Elevation of Privilege | Fehler = 503, nie Verwalter annehmen |
| Spieler-IPs | Information Disclosure | Keine Logs im UI; Mod schreibt nur Namen/Generation |

## Sources

### Primary (HIGH confidence)
- Live-Spike 2026-10-19 auf dieser Maschine, docker-py 7.2.0 gegen tecnativa v0.5.0, Luanti 5.17.0 (Digest-Pin): `put_archive` in laufende und gestoppte Welt, Mod `gameworld_access`, eigener MTP/SRP-Join-Prober, Fälle A0 bis A9, Golden Vector, Fehlversuch-Sperre. Getestete Spike-Dateien committet unter `.planning/phases/03-zugang-und-rollen/spike/` (`luanti_probe.py`, `luanti_srp.py`, `access_mod.lua`, `access_mod_lock.lua`, `spike.py`, `spike3.py`; Aufruf aus dem Spike-Ordner mit `.venv/Scripts/python.exe -I`); alle Spike-Container, Volumes und Wegwerfkonten entfernt
- Luanti 5.17.0 Quellen (raw.githubusercontent.com/luanti-org/luanti/5.17.0): `src/util/auth.cpp`, `src/util/srp.cpp`, `src/network/serverpackethandler.cpp`, `src/network/mtp/internal.h`, `src/network/mtp/threads.cpp`, `src/network/clientopcodes.cpp`, `src/network/networkprotocol.{h,cpp}`, `src/client/client.cpp`, `src/server.cpp`, `src/serialization.h`, `src/player.h`, `builtin/game/auth.lua`, `doc/lua_api.md` (Z. 6647, 6658, 6836, 6843, 7920)
- Nextcloud 34.0.3 / AppAPI 34.0.0 im Dev-Container: `apps/app_api/lib/Controller/ExAppProxyController.php` (Routenprüfung, erste Route gewinnt, Ebenen), `Service/ExAppService.php` (Ebenen-Mapping), `Service/AppAPIService.php` (`finalizeRequestToNC`, Impersonation), `Controller/TopMenuController.php:65`, `lib/private/AppFramework/Middleware/Security/SecurityMiddleware.php` (`AppApiAdminAccessWithoutUser`)
- nc_py_api 0.30.3 (.venv): `ex_app/integration_fastapi.py` (`AppAPIAuthMiddleware`, `scope["username"]`), `_session.py`, `users.py`, `users_groups.py`, `nextcloud.py`
- Live-Proben gegen Dev-Nextcloud (Basic-Auth und ExApp-Impersonation): `/ocs/v1.php/cloud/user`, `/cloud/users/{uid}`, `/cloud/groups/{gid}`, `/ocs/v2.php/core/autocomplete/get`
- ContentDB-API: `AntumDeluge/whitelist` (Release-Liste, Lizenz, Repo), `Zughy/whitelist`, `GreatBigDiamond/ct_whitelist` (404); Quelltexte codeberg.org/AntumLuanti/mod-whitelist `init.lua`, gitlab.com/zughy-friends-minetest/whitelist `src/api.lua`, `src/player_manager.lua`
- @nextcloud/vue 9.13.1 `dist/components` (`NcSelectUsers.vue.d.ts`, `NcSettingsSelectGroup`, `NcFormBoxCopyButton`)
- https://www.luanti.org/en/downloads/ (5.17.0, Plattformen, kein iOS)

### Secondary (MEDIUM confidence)
- PyPI `srp` 1.0.22 (Metadaten, nicht genutzt)

### Tertiary (LOW confidence)
- Deutsche Beschriftungen im Luanti-Hauptmenü (A6), nicht geprüft

## Metadata

**Confidence breakdown:**
- Whitelist-Durchsetzung und Auth-Provisionierung: HIGH (live, inklusive vollständigem SRP-Login gegen echten Server)
- Rollen und Routen: HIGH (Quellcode im Dev-Container, Live-Proben)
- Datenmodell und Gruppenauflösung: MEDIUM-HIGH (APIs live geprüft, Sync-Strategie ist Entwurf)
- Verbindungsinfo/Anleitung: MEDIUM (Adresse ist Heuristik plus Einstellung, Client-Texte ungeprüft)
- Kick laufender Spieler: MEDIUM (dokumentierte API, kein echter Client)

**Research date:** 2026-10-19
**Valid until:** 2026-11-18 (Luanti-Pin 5.17.0 stabil; bei Engine-Upgrade Protokollversion 53 und SRP-Code erneut prüfen)
