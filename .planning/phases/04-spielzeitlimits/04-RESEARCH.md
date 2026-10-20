# Phase 4: Spielzeitlimits - Research

**Researched:** 2026-10-20
**Domain:** Serverseitige Spielzeit-Durchsetzung in Luanti ohne exec (eigener Welt-Mod plus Regeldatei per Archive-API), Zeitrechnung mit Zeitzonen und Sommerzeit, Verbrauchszählung über mehrere Welten, Wochenplan- und Ferien-UI mit @nextcloud/vue 9
**Confidence:** HIGH für die Durchsetzung (Live-Spike mit echtem Luanti 5.17.0, vollständiger Join bis `on_joinplayer` per erweitertem Prober, Kick, Vorwarnung, Neustart-Festigkeit, Live-Push), HIGH für Zeitzonen (Golden Vectors aus zoneinfo, Container-Uhr gemessen), MEDIUM für Zählung über Welten und ExApp-Ausfall (Entwurf auf Basis der live verifizierten Bausteine, nicht als Ganzes gebaut), MEDIUM für UI-Muster (Komponenten vorhanden, Bedienung nicht geprüft)

## Summary

Die Durchsetzung gehört wieder in einen eigenen Welt-Mod, genau wie in Phase 3: `gameworld_time` liest eine Regeldatei, die nur die ExApp per `put_archive` schreibt, lehnt im Prejoin ab, warnt per Chat und trennt im 5-s-Takt per `core.disconnect_player`. Neu ist ein **Zählbuch im Welt-Volume** (`gameworld_time_used.txt`), das der Mod fortlaufend schreibt und beim Start wieder einliest. Der Spike hat live gezeigt: Kontingent 40 s, Kick nach 37,1 s mit kindgerechtem Text, Vorwarnungen kommen als Chat beim Client an, sofortiger Rejoin wird mit demselben Text abgelehnt, **Welt-Neustart ändert nichts** (Zählbuch 40 s vorher und nachher, Rejoin weiter abgelehnt), ein Live-Push neuer Regeln wirkt binnen 2,6 s auf einen verbundenen Spieler, Fensterende als absolute Uhrzeit trennt pünktlich, Welt-Zeitfenster sperrt Kinder und lässt freigestellte Verwalter durch, halbe Regeldatei lässt den alten Stand stehen, 30 s Spielzeit ergeben exakt 30 s im Zählbuch [VERIFIED: Live-Spike 2026-10-20, Szenarien S0 bis S9].

Die ExApp ist das Gehirn: Sie kennt Wochenplan, Ferien, Zeitzone und den Verbrauch über **alle** Welten (nur sie sieht alle Welten), liest in einem eigenen 15-s-Takt die Zählbücher der laufenden Welten, verbucht die Zuwächse pro Kind und Kalendertag in SQLite (Schema 4) und schreibt pro Welt eine Regeldatei mit absoluten Epoch-Grenzen und einem "Deckel" im Zählbuch-Maß. Weil die Grenzen absolut sind und der Mod selbst zählt, setzt die Welt die Regeln auch dann weiter durch, wenn die ExApp ausfällt oder die Welt neu startet; nach dem Ende des aktuellen Tages schließt sie ohne neue Regeln (fail closed für Kinder mit Regeln). Container laufen in UTC (`os.date` liefert `+0000`, gemessen), darum rechnet nur die ExApp lokale Zeit, mit `zoneinfo` und Einstellung `time_zone` (Vorgabe `Europe/Berlin`). Unter Windows fehlt dafür die Zeitzonendatenbank: `tzdata` muss als Abhängigkeit dazu [VERIFIED: ZoneInfoNotFoundError in .venv, slopcheck OK].

Fremd-Mods scheiden aus. `playtime_limit` (Linuxdirk, MIT, Release 05.09.2026, 668 Downloads) zählt nur im globalen 60-s-Schritt und nur für Spieler, die genau in diesem Moment verbunden sind; wer vorher geht, spielt ungezählt (vom Autor selbst als "cheating" dokumentiert). Dazu: rollierendes Intervall statt Kalendertag, keine Fenster, keine Wochentage, Steuerung nur per Chat-Befehl mit Recht `server` und nur für verbundene Spieler, Zähler in Player-Meta pro Welt (keine Aggregation, von außen nicht änderbar) [VERIFIED: Quelltext des ContentDB-Release gelesen]. Nebenbefund mit Gewicht: **Ein Wieder-Beitritt innerhalb von etwa 0,2 s nach dem Verlassen bringt Luanti 5.17.0 mit Minetest Game und VoxeLibre zum Absturz** (Engine-Wettlauf in `ServerEnvironment::getPlayer`, Spiel-Callbacks in `on_joinplayer` bekommen `nil`); die Welt bleibt danach gestoppt. Eine Wiederbeitritts-Sperre von 2 s im Prejoin verhindert das vollständig (0 Abstürze, live) und gehört in Phase 4.

**Primary recommendation:** Hybrid aus ExApp-Regelwerk und eigenem Welt-Mod `gameworld_time` (Prejoin-Sperre, Chat-Vorwarnung 10/5/1 min, Trennen per `disconnect_player`, persistentes Zählbuch, Wiederbeitritts-Sperre 2 s); Regeldatei `gameworld_time.txt` mit absoluten Grenzen und Deckel; ExApp-Zeittakt 15 s mit Verbuchung pro Kind und lokalem Kalendertag; ein Tageskontingent pro Kind über alle Welten (Summe); Ferien als globale Datumsliste mit Ferienplan pro Kind; Welt-Zeitfenster sperrt nur den Zugang, stoppt die Welt nicht.

<user_constraints>
## User Constraints (kein CONTEXT.md vorhanden)

Für Phase 4 existiert kein `04-CONTEXT.md`. Die Vorgaben stammen aus ROADMAP.md, REQUIREMENTS.md, STATE.md, CLAUDE.md, den Entscheiden der Phasen 1 bis 3 und dem Auftrag des Orchestrators; sie gelten als gesetzt.

### Locked Decisions
- Eltern legen pro Kind ein Tageslimit und/oder ein Zeitfenster fest (ZEIT-01), mit Wochenplan pro Wochentag (ZEIT-03, Owner 20.10.2026: Voreinstellungen statt Konfigsprache, Tages-Kacheln/Schalter)
- Ferienzeiträume von/bis mit eigenen Regeln, automatische Umschaltung am Datum (ZEIT-04, Owner 20.10.2026)
- Zeitfenster pro Welt für Schule/Verein, außerhalb nicht betretbar, Durchsetzung serverseitig wie beim Wochenplan (ZEIT-05, Owner 20.10.2026)
- Durchsetzung serverseitig: Trennen und Join-Sperre, nicht nur Anzeige; Limit hält nach Welt-Neustart und Rejoin (ZEIT-02, SC 5 und 6); Implementierungspfad entscheidet diese Research
- Jede Durchsetzung ohne exec (Proxy `/exec` = 403); Proxy-Flags bleiben `CONTAINERS=1 IMAGES=1 POST=1 VOLUMES=1`
- Privatheit ist Produktkern: keine externen Aufrufe zur Laufzeit, keine IP-Adressen, keine Chat-Protokolle, Datensparsamkeit
- Bestehende Architektur: docker-py nur unter `provisioner/`, Mutationen über `world_id` und `_owned()`, SQLite-Migration per `PRAGMA table_info` (idempotent), Status aus Docker, Reconciler startet periodisch nie (nur beim Boot)
- Rollen: Verwalter = Gruppe `admin` (Phase 3, A1); Kinder bekommen nie Admin-Rechte oder Privilegien
- Owner-Regeln: ruff-Vollsatz, pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture lokal grün vor Commit; deutsche Prosa mit Umlauten, Umlaute nie in Code-Bezeichnern/URLs/Keys; keine Gedankenstriche (U+2013/U+2014); keine Emojis; Commits als `street1983nk <k.cherif@outlook.de>` ohne Trailer; UI-Abnahme gemeinsam per Playwright; Python immer über `uv run`/`.venv`

### Claude's Discretion (in dieser Research empfohlen)
- Durchsetzungspfad (Mod, Scheduler, Fremd-Mod), Dateiformate, Takt
- Zeitzonenmodell, Zählmodell über Welten, Ausfallverhalten
- Datenmodell (Schema 4), API-Form, UI-Aufteilung, Voreinstellungen, Kindertexte

### Deferred Ideas (OUT OF SCOPE für Phase 4)
- Auto-Stop von Welten (v2, "Auto-Stop bei Inaktivität"); Welt-Zeitfenster stoppt deshalb keine Welten
- Aktivitäts-Benachrichtigungen (v2), Klassen-Preset, Handout-Ansicht, Mandantenmodell (v2)
- ROLLE-03 eigene Verwalter-Gruppen (Phase 6); Backup/Restore (Phase 5, berührt aber das Zählbuch, siehe Pitfall 7)
- Feiertags- oder Ferienimport aus dem Internet (externe Aufrufe zur Laufzeit widersprechen dem Produktkern)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ZEIT-01 | Tageslimit und/oder Zeitfenster pro Kind | Pattern 4 (Plan-Auswertung, pure Funktion, Golden Vectors), Pattern 2 (Regeldatei: Deckel `cap` und Fenster `from`/`until`), Spike S1/S5 |
| ZEIT-02 | Serverseitige Durchsetzung, hält nach Neustart und Rejoin | Pattern 1 (Mod `gameworld_time`, live S1 bis S9), Pattern 3 (Zählbuch im Volume, Neustart S4), Bewertung Fremd-Mods (Standard Stack), Pitfall 1 (Wiederbeitritts-Absturz) |
| ZEIT-03 | Wochenplan pro Wochentag, einfache Eingabe | Pattern 4 (Plan-Modell 7 Tage), Pattern 8 (Tages-Kacheln, Voreinstellungen), Schema 4 `time_plans` |
| ZEIT-04 | Ferienzeiträume mit eigenen Regeln, automatische Umschaltung | Pattern 4 (Planwahl je lokalem Datum), Schema 4 `holidays`, Pattern 8 (Ferienliste) |
| ZEIT-05 | Zeitfenster pro Welt | Pattern 2 (Zeile `welt`, Freistellung `frei`, live S7/S8), Pattern 6 (Reconciler bleibt unberührt, keine Stopps) |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Stack: nc_py_api 0.30.3 async, Python 3.13, FastAPI/uvicorn, docker-py 7.2.0 sync über `anyio.to_thread`, Luanti `ghcr.io/luanti-org/luanti:5.17.0` per Digest, Vue 3.5.44 + @nextcloud/vue 9.13.1 + Vite 7.3.7
- What NOT to use: Sync-`NextcloudApp`, roher Docker-Socket, Luanti `latest`/`master`, ui_example-Skeleton, DSP für Neuinstallationen
- Sicherheit: kindersicher als Produktkern, keine Admin-Zugänge für Kinder; Ressourcen: Heimserver, keine Annahme von Server-Hardware
- Welt-Mods werden von Gameworld mitgeliefert und per `put_archive` eingespielt (Muster `gameworld_status`, `gameworld_access`); Konfiguration nur über Dateien
- GSD-Workflow: Änderungen nur über GSD-Kommandos
- CLAUDE.md-Abschnitt "Supporting Libraries" bekommt mit dieser Phase eine Zeile `gameworld_time` und `tzdata` (beim nächsten Doku-Lauf)

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Join-Sperre außerhalb erlaubter Zeiten | Luanti-Prozess (Mod, Prejoin) | ExApp schreibt Regeldatei | Nur der Spielserver sieht Join-Versuche; UI-Sperre allein erfüllt ZEIT-02 nicht |
| Trennen bei Ablauf, Vorwarnung | Luanti-Prozess (Mod, 5-s-Takt) | - | Kein Konsolenzugriff, kein exec; Chat-Hinweis geht nur aus dem Spiel |
| Sekundengenaue Zählung je Welt | Luanti-Prozess (Zählbuch im Welt-Volume) | ExApp liest per `get_archive` | Zählt auch bei ExApp-Ausfall, überlebt Welt-Neustart |
| Wochenplan, Ferien, Zeitzone, Tagesgrenzen | API / Backend (pure Funktionen) | - | Container laufen in UTC; nur die ExApp kennt Zeitzone und alle Regeln |
| Tageskontingent über alle Welten | API / Backend (Verbuchung pro Kind und Tag) | SQLite | Nur die ExApp sieht alle Welten |
| Regeln, Verbrauch, gesehene Zählbuchstände | SQLite (Schema 4) | Regeldatei im Welt-Volume | DB ist Soll und Gedächtnis, Datei ist, was der Server durchsetzt |
| Eingabe Wochenplan/Ferien/Welt-Fenster | Browser (Verwalter-UI) | API validiert | Kindersicherungs-übliche Kacheln, Backend vertraut der Eingabe nicht |
| Restzeit-Anzeige für das Kind | API (`/api/my/...`) | Browser | Nur eigene Werte, keine Daten anderer Kinder |

## Standard Stack

### Core (unverändert)
| Library | Version | Phase-4-Nutzung |
|---------|---------|-----------------|
| docker (docker-py) | 7.2.0 | `put_archive` für Regeldatei und Mod (laufend und gestoppt), `get_archive` für das Zählbuch, wie Phase 3 |
| nc-py-api[app] | 0.30.3 | unverändert (Rollen, Verwalter-Prüfung) |
| @nextcloud/vue | 9.13.1 | `NcCheckboxRadioSwitch` (Tag erlaubt), `NcSelect` (Limit-Auswahl), `NcDateTimePickerNative` (`type` `time` und `date`), `NcTimezonePicker`, `NcDialog`, `NcChip`, `NcNoteCard`, `NcEmptyContent` [VERIFIED: frontend/node_modules/@nextcloud/vue/dist/components] |
| Python `zoneinfo` (stdlib) | 3.13 | Lokale Zeit, Tagesgrenzen, Sommerzeit [CITED: docs.python.org/3/library/zoneinfo.html] |

### Neu
| Library | Version | Purpose | Why |
|---------|---------|---------|-----|
| tzdata (PyPI) | 2026.5 (python/tzdata, PSF) | IANA-Zeitzonendaten für `zoneinfo` ohne System-Datenbank | Unter Windows (Dev, Tests) wirft `zoneinfo.ZoneInfo("Europe/Berlin")` `ZoneInfoNotFoundError` [VERIFIED: .venv 2026-10-20]; die Python-Doku nennt `tzdata` als offiziellen Rückfall [CITED: docs.python.org/3/library/zoneinfo.html]. Im Produktiv-Image `python:3.13-slim-trixie` ist System-tzdata 2026b vorhanden [VERIFIED: docker run], `tzdata` schadet dort nicht und macht Tests plattformgleich |

### Spielzeit-Kandidaten (Bewertung, Empfehlung: keiner davon)
| Kandidat | Stand | Mechanik | Bewertung |
|----------|-------|----------|-----------|
| **Playtime Limit** (ContentDB `Linuxdirk/playtime_limit`, MIT, Repo git.0x7be.net/dirk/playtime_limit) | Release 2026-09-05, min. Luanti 5.17, 668 Downloads, gepflegt (Weblate-Übersetzungen) | `register_globalstep` addiert alle 60 s (`step_size`) pauschal 60 s auf alle gerade Verbundenen; Limit-Prüfung in `on_joinplayer` (nach dem Betreten) und im Schritt; Reset rollierend `start + interval` ab erster Sitzung; Werte in Player-Meta; Steuerung `/playtime_limit_set` (Recht `server`, nur für verbundene Spieler) | **Umgehungs-Caveat bestätigt:** Wer vor dem 60-s-Schritt trennt, spielt ungezählt; der Autor schreibt selbst "too high step sizes allow cheating the playtime limit by disconnecting before the validity check". Dazu: keine Fenster, Wochentage, Ferien; kein Kalendertag; keine Aggregation über Welten; ExApp kann Player-Meta nicht ändern; Standardlimit gilt für alle inklusive Eltern; Bug `return` in der Spielerschleife des Globalsteps; Join-Prüfung erst in `on_joinplayer` [VERIFIED: init.lua, system/*.lua des Release 38620 gelesen]. Server-Neustart setzt nur den globalen Schrittzähler zurück (bis 60 s ungezählt) |
| **Opening Hours** (ContentDB `texmex/opening_hours`, GPL-2.0, Repo github.com/minetest-mods/opening_hours) | Release 2026-06-25, 1.598 Downloads | Prejoin-Ablehnung und Kick im 10-s-Takt nach fest im Code stehender Tages-/Stundentabelle, Countdown 15/10/5/1 min per `chat_send_all` | Bestätigt nur die Technik. Ungeeignet: Tabelle in `init.lua` hart kodiert, Stundenraster, `os.date` liefert im Container UTC, Recht `server` umgeht alles, undefinierte globale `admin`, GPL [VERIFIED: init.lua gelesen] |
| Advanced Playtime, Playtime Recorder, Playtimes | diverse | nur Anzeige/Statistik | keine Durchsetzung |
| **Eigener Mod `gameworld_time`** | im Spike gebaut und live getestet | Prejoin + Takt + Chat-Vorwarnung + Zählbuch im Volume + absolute Grenzen aus der ExApp + Wiederbeitritts-Sperre | **Empfohlen**: gleiche Technik wie `gameworld_access`, rund 150 Zeilen Lua, keine Fremdpflege, keine Lizenzfragen |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hybrid ExApp + Mod | Nur ExApp-Scheduler (zählt aus `gameworld_players.txt`, sperrt per Zugangsdatei) | Bei ExApp-Ausfall keine Durchsetzung (fail open), Zählung nur im Abfragetakt, kein Chat-Hinweis, falscher Ablehnungstext ("nicht eingeladen") oder Umbau der Zugangsdatei; abgelehnt |
| Hybrid | Scheduler stoppt Container | Trifft alle Spieler der Welt statt eines Kindes, kollidiert mit Eltern-Soll und Boot-Abgleich, kein Vorwarnen; abgelehnt |
| Hybrid | Mod allein (Regeln komplett im Mod, inkl. Wochenplan) | Mod müsste Zeitzone, Sommerzeit, Ferien und andere Welten kennen; Container sind UTC, Lua hat keine Zeitzonendatenbank; abgelehnt |
| Eigener Mod `gameworld_time` | Erweiterung von `gameworld_access` | Ein Callback weniger, aber Zugangs- und Zeitlogik vermischt, gemeinsame Datei würde bei jedem Zeittakt die Zugangs-Generation ändern; getrennt bleibt jede Datei klein und einzeln prüfbar |
| Chat-Vorwarnung | HUD-Anzeige mit Restzeit (`hud_add`/`hud_change`) | Schöner, aber spielabhängige Platzierung und mehr Code; als spätere Verbesserung möglich |

**Installation:**
```bash
uv add "tzdata==2026.5"
```

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| tzdata | PyPI | seit 2020 (PEP 615), Version 2026.5 | sehr hoch (Abhängigkeit von pandas u. a.) [ASSUMED] | github.com/python/tzdata (PSF) | [OK] | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
Die bewerteten ContentDB-Mods werden ausdrücklich nicht übernommen. `npm`: keine neuen Pakete.

## Architecture Patterns

### System Architecture Diagram

```
Browser (Verwalter)                                Browser (Kind)
  | Wochenplan/Ferien/Welt-Fenster speichern         | GET /api/my/worlds (+ Spielzeit: heute noch, nächste Zeit)
  v                                                  v
[ExApp FastAPI]  require_verwalter ---> TimeService.update_rules -> SQLite (Schema 4)
  |                                          |
  |                                          v  sofortige Neuberechnung (unter mutation())
  |                       +---------- render_time_file(world) -> put_archive gameworld_time.txt
  |                       |
  | Lifespan-Tasks:  reconcile_forever (30 s, unverändert)
  |                  time_forever (15 s, neu):
  |                     1. für jede laufende Welt: get_archive gameworld_time_used.txt (Zählbuch)
  |                     2. Zuwachs = Zählbuch - zuletzt gesehen  -> time_usage(nc_user, lokaler Tag) += Zuwachs
  |                     3. Plan auswerten (Zeitzone, Wochentag, Ferien, Welt-Fenster) -> je Kind: Rest, Fenster
  |                     4. je Welt Regeldatei rendern; nur bei geänderten Bytes put_archive (try_mutation)
  v
tecnativa-Proxy (PUT/GET /containers/{id}/archive)
  v
[Luanti 5.17.0, Welt-Container, UTC]
   worldmods/gameworld_access  (Phase 3: Whitelist, Passwort, Fehlversuche, Kick bei Widerruf)
   worldmods/gameworld_time    depends = gameworld_access
      Prejoin:  Regeln laden -> Welt zu? Fenster vorbei? Deckel erreicht? -> Ablehnung mit Kindertext
                sonst: Wiederbeitritts-Sperre (Name noch verbunden oder < 2 s seit Verlassen)
      alle 5 s: Zählbuch += Online-Zeit; Rest = min(Fensterende - jetzt, Deckel - Zählbuch)
                Rest <= 10/5/1 min -> chat_send_player; Rest <= 0 -> disconnect_player(Kindertext)
                Zählbuch schreiben (safe_file_write), beim Verlassen und beim Herunterfahren ebenso
```

### Recommended Project Structure (Änderungen)
```
src/gameworld/
├── provisioner/
│   ├── time_mod.py        # NEU: Lua-Quelltext gameworld_time, mod.conf, Dateinamen,
│   │                      #      render_time_file(...) -> bytes, parse_ledger(bytes)
│   ├── archive.py         # WORLD_MODS um gameworld_time erweitern; build_world_files nimmt time_file mit
│   └── client.py          # + read_time_ledger(world_id) (get_archive, gekappt wie read_status_file)
├── playtime/              # NEU
│   ├── plan.py            # pure: WeekPlan, DayRule, Holiday, evaluate(...) -> ChildState / WorldState
│   ├── ledger.py          # pure: Zuwachs je Welt, Regression, Tageszuordnung
│   └── service.py         # TimeService: Regeln CRUD, tick(), refresh(world_ids), my_playtime(uid)
├── worlds/store.py        # Schema 4 (Tabellen unten), worlds.time_generation, meta.time_zone
├── worlds/service.py      # _launch schreibt gameworld_time.txt mit; push_time(world_id)
├── api/playtime.py        # NEU: Verwalter-Routen (Regeln, Ferien, Welt-Fenster, Zeitzone)
├── api/me.py              # MyWorldOut + Spielzeit (eigene Werte)
└── main.py                # Lifespan: zweiter Task time_forever
frontend/src/
├── views/ParentView.vue   # Abschnitt "Spielzeit" (Kinderliste) + "Ferien"; Welt-Zeile: Knopf "Zeitfenster"
├── views/PlayerView.vue   # Restzeit-Chip, Hinweis "Heute keine Spielzeit mehr"
└── components/WeekPlanEditor.vue, PlaytimeDialog.vue, HolidayList.vue, WorldWindowDialog.vue
tests/e2e/luanti_probe.py  # + session(): vollständiger Join, halten, Chat und Kick mitschneiden
scripts/dev/acceptance-phase4.sh
```

### Pattern 1: Welt-Mod `gameworld_time` (live verifiziert)
**What:** Durchsetzung im Spielserver nach absoluten Grenzen, die die ExApp vorgibt; eigenes, neustartfestes Zählbuch.
**Getestete Spike-Fassung:** `.planning/phases/04-spielzeitlimits/spike/time_mod.lua` (Regelzeile dort mit `remaining basis` statt `cap`, rechnerisch identisch: `cap = basis + remaining`).

Kernablauf (Produktfassung, aus dem Spike abgeleitet):
```lua
-- worldmods/gameworld_time/init.lua (Skizze; Texte wie in Phase 3 als Python-Konstanten mit
-- Umlauten, die als Lua-Dezimal-Escapes in den Mod gehen, _lua_string aus access_mod.py)
local world = core.get_worldpath()
local RULES = world .. "/gameworld_time.txt"      -- root 0444, nur die ExApp schreibt
local LEDGER = world .. "/gameworld_time_used.txt" -- uid 30000, nur der Mod schreibt
local TICK, MIN_LEFT, COOLDOWN = 5, 60, 2
local WARN = { 600, 300, 60 }

-- 1. Zählbuch vom letzten Lauf einlesen (Kopf + "end" prüfen), Sekunden je Name
-- 2. load(): Regeldatei nur bei Kopf "gameworld-time 1 <gen> <issued>" und Schlusszeile "end" übernehmen;
--    fehlt die Datei: keine Regeln; beim Start unvollständig: alle mit Regeln zu ("start")
-- 3. left(name) = min(Welt-Fensterende - jetzt, Fensterende - jetzt, cap - used[name]); nil = unbegrenzt;
--    jetzt = os.time() (Epoch, UTC-unabhängig); vor Fensterbeginn oder Tag nicht erlaubt: 0 mit Grund
core.register_on_prejoinplayer(function(name)
  load()
  local l, why, nxt = left(name)
  if l and l < MIN_LEFT then return text(why, nxt) end            -- Regeltext hat Vorrang
  local t = left_at[name]
  if core.get_player_by_name(name) or (t and (core.get_us_time() - t) / 1e6 < COOLDOWN) then
    return WAIT                                                   -- Schutz vor Pitfall 1
  end
end)
-- on_joinplayer: joined[name] = get_us_time(); on_leaveplayer: anteilig gutschreiben, left_at setzen,
-- Zählbuch schreiben; Takt: used[name] += min(dt, seit Beitritt); Vorwarnung je Schwelle einmal;
-- l <= 0 -> core.disconnect_player(name, text(why, nxt)); register_on_shutdown: Zählbuch schreiben
```
- Prejoin-Callbacks laufen im Modus `RUN_CALLBACKS_MODE_OR`: **alle** Callbacks laufen, der erste Text gewinnt [VERIFIED: s_player.cpp `on_prejoinplayer`, c_internal.h Enum, builtin/common/register.lua `run_callbacks` Modus 4]. Mit `depends = gameworld_access` lädt der Zugangs-Mod zuerst; ein nicht eingeladenes Kind sieht darum "nicht eingeladen", nie einen Zeittext. Der Zugangs-Mod setzt das Passwort auch dann, wenn der Zeit-Mod ablehnt (unschädlich).
- `core.disconnect_player` statt `core.kick_player`: Letzteres stellt "Kicked: " voran [VERIFIED: lua_api.md Z. 7920 bis 7925; live in Spike B: "Kicked: Deine Einladung für diese Welt wurde beendet."]. Phase-3-Kicktext kann bei der Gelegenheit ebenfalls auf `disconnect_player` wechseln.
- `os.time` ist im abgesicherten Mod-Umfeld erlaubt (Whitelist `clock`, `date`, `difftime`, `getenv`, `time`) [VERIFIED: s_security.cpp Z. 173 bis 178, 5.17.0]. Nie `os.date` ohne `!` für Regeln nutzen: Container-Zeitzone ist UTC.
- `core.after(5, tick)` statt `register_globalstep`: Der Globalstep läuft jeden Server-Schritt (Log: `steplen=0.09`), der Takt alle 5 s genügt und kostet praktisch nichts.
- Chat-Vorwarnungen kommen als `TOCLIENT_CHAT_MESSAGE` beim Client an [VERIFIED: Spike S1, Ereignisse bei 6,7 s und 21,9 s]. Umlaute kommen als UTF-8 korrekt im Protokoll an [VERIFIED: Spike B, "für" im Ablehnungstext]; Darstellung im echten Client bleibt A9 aus Phase 3.

**Live-Ergebnisse (Spike `spike4.py`, MTG kreativ, Port 30094):**
| Fall | Ergebnis |
|------|----------|
| S0 Uhr: Container `os.time` vs. Host, `os.date` | gleiche Uhr (Abweichung erklärt sich aus 3,5 s Startzeit zwischen Schreiben und Lesen), `os.date` = `+0000` (UTC) |
| S1 Kontingent 40 s, Sitzung gehalten | Vorwarnung "Noch 30" bei 6,7 s und "Noch 15" bei 21,9 s, getrennt nach 37,1 s mit "Deine Spielzeit für heute ist aufgebraucht. Nächste Spielzeit: Morgen 14:00" (Spike-Texte ASCII) |
| S2 sofortiger Rejoin | abgelehnt im Prejoin mit demselben Text |
| S3 Zählbuch | `Mia 40` |
| S4 Welt stop/start, dann Rejoin | Zählbuch weiter 40, Rejoin abgelehnt; Papa ohne Regeln `auth_accept` |
| S5 neues Kontingent, Fensterende in 20 s | getrennt nach 21,8 s mit "Gerade ist keine Spielzeit. Nächste Spielzeit: Sa 10:00" |
| S6 Live-Push "Kontingent 0" nach 10 s online | getrennt 2,6 s nach dem Push (Takt 5 s) |
| S7 Welt-Fenster zu | Mia abgelehnt "Diese Welt ist gerade geschlossen. Nächste Spielzeit: Mi 10:00", Papa (`frei`) `auth_accept` |
| S8 halbe Regeldatei (ohne `end`) | alter Stand bleibt: Mia weiter abgelehnt, Papa weiter `auth_accept` |
| S9 leere Regeldatei, 30 s Sitzung | keine Trennung, Zählbuch +30 s |
| Server-Log | keine Fehler |

Die S1-Abweichung (37,1 statt 40 s) entsteht, weil der Spike einem mitten im Takt beitretenden Spieler den vollen Takt gutschreibt; die Produktfassung rechnet ab Beitrittszeit und schreibt beim Verlassen anteilig gut (siehe Pitfall 3).

### Pattern 2: Regeldatei und Zählbuch (Formate)
**Regeldatei** `.minetest/worlds/world/gameworld_time.txt` (root, 0444, ASCII, Zeilen sortiert, deterministisch):
```
gameworld-time 1 <generation> <issued_at>
welt <from> <until> <grund> <naechste>                  (nur wenn die Welt ein Zeitfenster hat)
<Spielername> <cap> <from> <until> <grund> <naechste>
end
```
- `cap`: Zählbuch-Stand dieser Welt in Sekunden, ab dem der Spieler getrennt wird (`-1` = kein Tageslimit). Die ExApp rechnet `cap = gesehen(Welt, Name) + Rest_heute(Kind)`. Spielt das Kind nur in dieser Welt, wachsen Zählbuch und Verbrauch gleich schnell, `cap` bleibt stabil, und die Datei ändert sich nicht in jedem Takt. Spielt es parallel in einer zweiten Welt, sinkt `cap` hier mit dem nächsten ExApp-Takt.
- `from`, `until`: Epoch-Sekunden des aktuellen oder nächsten erlaubten Fensters **heute**, nie über das lokale Tagesende hinaus. Tag nicht erlaubt: `0 0`. Kinder mit Regeln stehen immer mit endlichem `until` in der Datei: Ohne neuen Regelstand ist nach Mitternacht Schluss (fail closed).
- `grund`: `ok`, `tag`, `fenster`, `limit`, `frei`. `frei` (für Verwalter) heißt: Welt-Fenster gilt nicht, eigene Grenzen ebenso nicht (`-1 -1 -1 frei -`).
- `naechste`: ASCII-Token für den Kindertext, z. B. `Sa-10:00`, `-` wenn unbekannt. Wochentag statt "morgen", weil ein relativer Text bei ExApp-Ausfall veralten kann.
- Spieler ohne Zeile haben keine persönlichen Regeln (Welt-Fenster gilt trotzdem). Fehlt die Datei, gibt es keine Regeln (alle Welten ohne Zeitregeln brauchen keine Datei; `_launch` schreibt sie trotzdem immer). Unvollständige Datei: alter Stand; beim Start ohne gültigen Stand: alle mit Regeln zu ("Gameworld startet gleich").
- Strenge wie `render_access_file`: Jeder ungültige Eintrag wirft `ValueError`, Namen nur `[A-Za-z0-9_-]{1,20}`, Zahlen ganzzahlig, Token `[A-Za-z0-9:-]{1,16}`.

**Zählbuch** `.minetest/worlds/world/gameworld_time_used.txt` (uid 30000, vom Mod per `core.safe_file_write`):
```
gameworld-time-used 1 <os_time_beim_schreiben> <geladene_generation>
<Spielername> <sekunden_gesamt>
end
```
- Monoton pro Welt und Name über alle Neustarts (Mod liest es beim Start ein) [VERIFIED: Spike S4].
- Die geladene Generation im Kopf ersetzt eine eigene State-Datei: Die ExApp sieht, ob die laufende Welt den Mod und den aktuellen Regelstand hat (Muster `access_restart_needed`, Phase-3-Pitfall 4).
- `os_time_beim_schreiben` dient der Tageszuordnung nach ExApp-Pausen (Pattern 5) und einer Uhren-Plausibilitätsprüfung.

### Pattern 3: Zählgenauigkeit und Umgehungsfestigkeit
- Gutschrift im Takt nur `min(dt, jetzt - Beitritt)`; beim Verlassen anteilig seit dem letzten Takt gutschreiben und Zählbuch sofort schreiben. Damit zählt jede Sekunde, auch bei Rein-Raus-Wechseln (genau die Lücke von `playtime_limit`).
- Zusätzlich verhindert die Wiederbeitritts-Sperre (2 s) schnelle Wechsel, und ein echter Join dauert mehrere Sekunden (Definitionen, Medien).
- Absturz des Servers: höchstens ein Takt (5 s) ungezählt; regulärer Stopp schreibt per `register_on_shutdown` [CITED: lua_api.md Z. 6582 bis 6586, Warnung zu Abstürzen].
- AFK zählt als Spielzeit (verbunden = spielt), wie bei üblichen Kindersicherungen [ASSUMED].
- Join nur mit mindestens `MIN_LEFT` = 60 s Rest: Ein Kind mit 20 s Rest wird nicht hereingelassen, um sofort wieder getrennt zu werden.

### Pattern 4: Plan-Auswertung in der ExApp (pure, mit Golden Vectors)
**Modell (kindersicherungs-üblich, ein Fenster pro Tag):**
```python
# playtime/plan.py (Skizze)
@dataclass(frozen=True)
class DayRule:
    allowed: bool
    limit_minutes: int | None      # None = ohne Tageslimit
    window_start: int | None       # Minuten ab 00:00 lokal, None = ganzer Tag
    window_end: int | None         # exklusiv, 1..1440

@dataclass(frozen=True)
class WeekPlan:                    # Schlüssel 1..7 = ISO-Wochentag (Mo = 1)
    days: dict[int, DayRule]

def plan_for(day: date, normal: WeekPlan, holiday: WeekPlan | None, holidays: list[tuple[date, date]]) -> WeekPlan:
    """Ferienplan, wenn day in einem Zeitraum liegt (von und bis inklusive), sonst Normalplan."""

def evaluate(now: datetime, tz: ZoneInfo, rule_day: DayRule, used_today_s: int) -> ChildState:
    """from/until (Epoch) des aktuellen oder nächsten Fensters heute, Rest in Sekunden, Grund, nächste Zeit."""
```
- Lokaler Tag = `now.astimezone(tz).date()`; Tagesgrenzen `datetime.combine(tag, time(0), tzinfo=tz)` bis Folgetag 00:00, Fenster ebenso mit `combine`. Damit stimmen Wochentag und "19 Uhr" auch über die Zeitumstellung.
- "Nächste Spielzeit" sucht bis zu 7 Tage voraus (Ferienwechsel eingeschlossen) und liefert z. B. `Sa-10:00`.
- Granularität: API in Minuten (1 bis 1440), UI in 15-Minuten-Schritten. Die Minutenauflösung der API erlaubt eine Abnahme ohne Stundenwartezeit (Limit 1 min), ganz ohne Test-Hintertür.

**Golden Vectors** (`zoneinfo`, `Europe/Berlin`, `spike/golden_tz.py`, in `python:3.13-slim-trixie` gerechnet) [VERIFIED: 2026-10-20]:
| Fall | Lokaler Tag | Tag als Epoch `[start, end)` | Länge | 19:00 lokal |
|------|-------------|------------------------------|-------|-------------|
| Sa vor Umstellung | 2026-10-24, ISO 6 | `[1792792800, 1792879200)` | 24 h | `1792861200` = 17:00Z |
| So Umstellung | 2026-10-25, ISO 7 | `[1792879200, 1792969200)` | 25 h | `1792951200` = 18:00Z |
| Mo danach | 2026-10-26, ISO 1 | `[1792969200, 1793055600)` | 24 h | `1793037600` = 18:00Z |
| So Sommerzeit-Beginn | 2026-03-29, ISO 7 | `[1774738800, 1774821600)` | 23 h | `1774803600` = 17:00Z |
| Lücke 02:30 am 29.03. | nicht existent | `1774747800` = 01:30Z (PEP-495-Verhalten, fold 0) | | |
| doppelte 02:30 am 25.10. | zweimal vorhanden | `1792888200` = 00:30Z (erste Stunde, fold 0) | | |

Fenster in der Nachtlücke sind für Kinder praxisfern; die Validierung muss nur `window_start < window_end` prüfen.

### Pattern 5: Verbrauch über alle Welten (ExApp-Zeittakt)
- **Ein Tageskontingent pro Kind über alle Welten** (Analogie A2: ein Konto, ein Name, ein Passwort überall). Spielt ein Kind gleichzeitig in zwei Welten, zählt die **Summe** (strenger, einfach, ohne Überlappungsrechnung) [ASSUMED, Owner bestätigen].
- Takt `time_forever` als eigener Lifespan-Task, 15 s (nie exakt 10 s wegen des HAProxy-Keep-Alive, Phase-2-Pitfall 4). Je laufender Welt ein `get_archive` des Zählbuchs (gekappt wie `read_status_file`), danach je Name: `zuwachs = stand - gesehen(Welt, Name)`; `stand < gesehen` heißt Zählbuch zurückgesetzt (Restore, neues Volume): nur neu ankern, nichts abziehen.
- Zuordnung zum lokalen Tag: Zuwachs gehört dem Tag von `os_time_beim_schreiben` aus dem Zählbuch-Kopf (nicht dem Lesezeitpunkt). Nach einer ExApp-Pause über Mitternacht landet die Zeit so beim richtigen Tag; ein Zuwachs über eine Mitternacht hinweg wird dem späteren Tag zugeschlagen (Kinder mit Regeln werden um Mitternacht ohnehin getrennt).
- Danach je Kind `Rest_heute` neu, je Welt Regeldatei rendern, nur bei geänderten Bytes schreiben (Cache der zuletzt geschriebenen Bytes pro Welt). Schreiben per `try_mutation()` (nie warten, nächster Takt holt nach); Regeländerungen in der API schreiben sofort unter `mutation()`.
- Spieler-Zuordnung: Zählbuch-Namen über `players.player_name` (NOCASE) auf `nc_user`. Umbenennen beginnt in Luanti ein neues Konto und damit eine neue Zählbuch-Zeile; der Verbrauch pro `nc_user` bleibt.
- Gezählt wird nur für Kinder mit aktiven Regeln (Datensparsamkeit) [ASSUMED].

### Pattern 6: Welt-Zeitfenster (ZEIT-05) und Reconciler
- Welt-Fenster = Wochenplan der Welt (pro Wochentag ein Fenster oder geschlossen), ohne Limit. Ergebnis landet als Zeile `welt` in der Regeldatei; außerhalb lehnt der Mod ab und trennt nach dem gleichen Takt mit Vorwarnung [VERIFIED: Spike S7].
- **Die Welt wird nicht gestoppt.** Der Reconciler startet nur beim Boot, periodisch nie (Phase-2-Regel); ein automatisches Stoppen außerhalb des Fensters würde entweder `desired_state` ändern (Eltern-Soll überschrieben, Lehrkraft muss neu starten) oder einen periodischen Start einführen, den Phase 2 bewusst verbietet. Auto-Stop ist v2. Eine laufende, gesperrte Welt kostet nur RAM.
- Boot-Abgleich unverändert: Eine Welt mit Soll "läuft" startet nach Reboot auch außerhalb ihres Fensters, bleibt aber für Kinder zu (der Mod liest beim Start die von `_launch` frisch geschriebene Regeldatei).
- Freistellung: Verwalter (Gruppe `admin`, später ROLLE-03-Gruppen) stehen mit `frei` in der Datei und können außerhalb des Fensters vorbereiten [ASSUMED, Owner bestätigen]. Die ExApp kennt die Verwalter-Konten über die Gruppenauflösung als Verwalter (Phase-3-Muster); fällt die Auflösung aus, fehlt die Freistellung (fail closed).

### Pattern 7: Ausfall- und Neustartverhalten (ehrlich dokumentiert)
| Ereignis | Verhalten | Beleg |
|----------|-----------|-------|
| Welt-Neustart (Eltern, Absturz, Reboot) | Zählbuch bleibt, Regeln bleiben, Limit hält | Spike S4 |
| ExApp-Neustart/-Update | Welten setzen den letzten Regelstand weiter durch; Mod zählt weiter; ExApp verbucht nach dem Start die Zuwächse | Pattern 2/5 |
| ExApp länger aus, gleicher Tag | Limit pro Welt gilt weiter; Kontingent über Welten wird nicht abgeglichen: Wer in zwei Welten spielt, kann bis zur Ausfallzeit doppelt so lange | Entwurf, dokumentieren |
| ExApp aus über Mitternacht | Kinder mit Regeln kommen nach Tagesende nicht mehr hinein (fail closed), bis die ExApp wieder schreibt; Kinder ohne Regeln unberührt | Entwurf |
| Nextcloud aus, ExApp an | Zeittakt läuft (kein NC-Aufruf nötig); Freistellungsauflösung ruht, letzter Stand bleibt | Entwurf |
| Welt gelöscht und neu | Verbrauch pro Kind liegt in SQLite, nicht in der Welt; neues Zählbuch startet bei 0 und wird neu verankert | Pattern 5 |
| Restore einer Welt (Phase 5) | Zählbuch springt zurück; ExApp erkennt `stand < gesehen` und verankert neu; `_launch` liest das Zählbuch vor dem Schreiben der Regeldatei | Pitfall 7 |
| Uhr des Docker-Hosts falsch | Grenzen sind absolute Epoch-Werte aus der ExApp-Uhr; auf einem Linux-Host teilen ExApp-Container und Welten dieselbe Kernel-Uhr. Docker Desktop (Dev) hat eine eigene VM-Uhr: Plausibilitätsprüfung `|Zählbuch-Kopf - jetzt| > 120 s` bei Online-Spielern als Warnung im Dashboard | Spike S0 |

### Pattern 8: UI (Verwalter und Kind)
**Verwalter, ParentView** (bisher weltzentriert; Spielzeit gilt pro Kind über alle Welten):
- Neuer Abschnitt **"Spielzeit"** unter der Weltenliste: eine Zeile pro Kind (alle `nc_user` mit Zugang zu mindestens einer Welt, ohne Verwalter), Anzeigename, Zusammenfassung als `NcChip` ("Sa und So, je 2 Std", "Keine Begrenzung"), heute verbraucht ("heute 45 von 60 min"), Knopf "Bearbeiten".
- **Dialog "Spielzeit für Mia"** (`NcDialog`): oben Voreinstellungen als Knöpfe (setzen die Kacheln, danach frei änderbar):
  - "Keine Begrenzung" (Standard für neue Kinder, Opt-in)
  - "Nur am Wochenende": Sa und So je 2 Std, 9 bis 19 Uhr
  - "Jeden Tag 1 Stunde": bis 19 Uhr
  - "Schultage kurz, Wochenende länger": Mo bis Fr 1 Std 15 bis 19 Uhr, Sa und So 2 Std 9 bis 19 Uhr
  darunter **7 Tages-Kacheln** Mo bis So: Schalter "Spielen erlaubt" (`NcCheckboxRadioSwitch`), Auswahl Tageslimit (`NcSelect`: 15 min bis 4 Std, "ohne Limit"), Zeitfenster von/bis (`NcDateTimePickerNative type="time"`, `step` 900) oder "ganzer Tag". Knopf "Für alle Schultage übernehmen" spart Klicks.
  Reiter oder zweiter Block **"In den Ferien"** mit denselben Kacheln, Voreinstellung "Jeden Tag 2 Std, 9 bis 20 Uhr".
- Abschnitt **"Ferien"** (für den ganzen Haushalt): Liste von Zeiträumen (Name optional, von/bis mit `NcDateTimePickerNative type="date"`), Hinzufügen/Entfernen, Hinweis "Gilt für alle Kinder, Ferienplan je Kind im Spielzeit-Dialog". Aktiver Zeitraum hervorgehoben ("läuft gerade").
- **Welt-Zeile:** Knopf "Zeitfenster" öffnet dieselbe Kachel-Komponente ohne Limit-Auswahl ("Diese Welt ist nur zu diesen Zeiten offen"); Chip "Offen Mi 10 bis 12 Uhr" in der Zeile.
- **Einstellungen:** Zeitzone (`NcTimezonePicker`, Vorgabe `Europe/Berlin`, Vorschlag aus `Intl.DateTimeFormat().resolvedOptions().timeZone` des Browsers) neben `join_host`.
- Hinweis bei laufenden Welten ohne aktuellen Zeit-Mod: "Neustart nötig, damit Spielzeiten gelten" (wie Zugangsschutz).

**Kind, PlayerView / `/api/my/worlds`:**
- Ein Block "Deine Spielzeit heute": "Noch 45 Minuten, bis 19 Uhr" oder "Heute ist keine Spielzeit mehr. Nächste Spielzeit: Samstag 10 Uhr" oder nichts (keine Regeln).
- Pro Welt bei Welt-Fenster: "Offen Mittwoch 10 bis 12 Uhr", außerhalb "Gerade geschlossen".
- Nur eigene Werte; keine Pläne, keine Verbrauchshistorie, keine Daten anderer Kinder.

**Kindertexte im Spiel (Vorschlag, final mit Umlauten über `_lua_string`):**
| Grund | Text |
|-------|------|
| limit | "Deine Spielzeit für heute ist aufgebraucht. Nächste Spielzeit: Sa 10:00" |
| fenster | "Gerade ist keine Spielzeit. Nächste Spielzeit: heute 15:00" (ExApp liefert Wochentag) |
| tag | "Heute ist kein Spieltag. Nächste Spielzeit: Sa 10:00" |
| welt | "Diese Welt ist gerade geschlossen. Sie öffnet Mi 10:00" |
| Vorwarnung | "Noch 10 Minuten Spielzeit. Denk ans Speichern und Verabschieden." / "Noch 5 Minuten." / "Noch 1 Minute." |
| Wiederbeitritt | "Bitte einen Moment warten und dann nochmal beitreten." |

### Anti-Patterns to Avoid
- **Regeln mit lokaler Zeit im Mod rechnen (`os.date("%H")`):** Container ist UTC; opening_hours macht genau diesen Fehler.
- **Relative Fristen in der Regeldatei ("noch 600 s ab Laden"):** Ein Welt-Neustart lädt die Datei neu und schenkt die Zeit erneut. Nur absolute Epoch-Grenzen und ein persistentes Zählbuch sind neustartfest.
- **Zählung nur im Abfragetakt der ExApp aus `gameworld_players.txt`:** fail open bei ExApp-Ausfall, Lücken bei Rein-Raus-Wechseln.
- **Welt außerhalb des Fensters stoppen:** kollidiert mit Eltern-Soll und Reconciler-Regel; Auto-Stop ist v2.
- **Kick per `kick_player`:** "Kicked: " vor dem Kindertext.
- **Regeldatei in jedem Takt neu schreiben:** unnötige `put_archive`-Last; Deckel-Kodierung und Byte-Vergleich verhindern das.
- **Zeitregeln für Verwalter:** Eltern und Lehrkräfte sperren sich nicht selbst aus; Freistellung `frei`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Zeitzonen und Sommerzeit | eigene Offset-Tabellen, UTC+1/+2 fest | `zoneinfo` + `tzdata` | Umstellungstage (23 h / 25 h), Lücken und Doppelstunden, Regeländerungen der IANA-Datenbank |
| Join-Sperre und Trennen | Firewall/Proxy-Regeln, Container-Stopp | Prejoin-Callback und `core.disconnect_player` im Mod | Name erst im Init bekannt; Stopp trifft alle Spieler |
| Spielzeitmessung | Abfrage der Spielerliste im ExApp-Takt | Zählbuch im Mod | sekundengenau, neustartfest, zählt bei ExApp-Ausfall |
| Atomare Dateien im Mod | `io.open(...,"w")` | `core.safe_file_write` | kein halbes Zählbuch beim Absturz |
| Zufall/IDs | nicht nötig | - | - |
| Ferien-/Feiertagsdaten | Import aus Web-APIs | manuelle Liste der Eltern | keine externen Aufrufe zur Laufzeit |

**Key insight:** Die ExApp liefert Bedeutung (Zeitzone, Pläne, Ferien, Summen über Welten), der Mod liefert Wirkung (Sperre, Zählung, Trennen). Jede Seite bleibt allein funktionsfähig genug, dass weder ein ExApp-Ausfall noch ein Welt-Neustart das Limit aushebelt.

## Runtime State Inventory

Phase 4 ändert Schema, Welt-Mods, Container-Inhalt, Lifespan und Abnahmen.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `.dev/storage/gameworld.sqlite3` Schema 3 (players, invites, world_access) | Code: Migration auf Schema 4 (neue Tabellen, `worlds.time_generation`, `meta.time_zone`), idempotent per `PRAGMA table_info`; Datenmigration: keine (alle Kinder starten ohne Regeln) |
| Live service config | AppAPI-Routen aus info.xml (`^/api/.*` ADMIN, Verben `GET,POST,DELETE`) | Neue Verwalter-Routen unter `/api/...` mit POST/DELETE brauchen keine info.xml-Änderung; neue Kinderdaten nur unter `/api/my/...` (USER). Kein PUT einführen oder info.xml-Verben anpassen und `register-exapp.sh` neu laufen lassen |
| OS-registered state | Keine | Keine |
| Secrets/env vars | Keine neuen Geheimnisse; optional `GAMEWORLD_TIME_TICK_SECONDS` nur falls Tests den Takt verkürzen müssen | Bevorzugt ohne neue Variable (Minuten-Limit in der API reicht für Abnahmen) |
| Build artifacts | `js/gameworld-main.js` (gitignored), `.venv` ohne `tzdata` | Bundle neu bauen; `uv sync` nach `uv add tzdata` |
| Laufende Welten | bestehende Welten haben `gameworld_time` noch nicht; Mod-Code wirkt erst nach Neustart (Phase-3-Pitfall 4) | `_launch` spielt Mod und Regeldatei vor jedem Start ein; Dashboard-Hinweis "Neustart nötig" für laufende Welten ohne Zählbuch-Kopf mit aktueller Generation; nie automatisch neu starten |

## Common Pitfalls

### Pitfall 1: Server-Absturz bei sofortigem Wieder-Beitritt (Engine-Wettlauf, live gefunden)
**What goes wrong:** Verlässt ein Spieler die Welt und tritt binnen etwa 0,2 s unter demselben Namen wieder bei, stürzt Luanti 5.17.0 ab: in Minetest Game `creative/inventory.lua:24 attempt to index local 'player' (a nil value)`, in VoxeLibre `vl_legacy/init.lua:38 attempt to index local 'inv'`. Der Container endet (`exited`), wegen `restart_policy "no"` und der Reconciler-Regel bleibt die Welt aus, bis Eltern sie starten. Jedes eingeladene Kind mit einem Skript könnte so die Welt für alle abschießen.
**Why it happens:** `ServerEnvironment::getPlayer(name)` bricht beim ersten gleichnamigen Eintrag ab; steht dort noch der gehende Spieler (peer ungültig), liefert `core.get_player_by_name` für den neuen `nil`, und die Spiel-Callbacks in `on_joinplayer` prüfen das nicht [VERIFIED: serverenvironment.cpp Z. 334 bis 345 und l_env.cpp Z. 643 bis 657, 5.17.0; live reproduziert mit Positiv- und Negativkontrolle, Spike B und C, MTG und VoxeLibre; ab 0,5 s Abstand kein Absturz]. Kein passendes Upstream-Issue gefunden.
**How to avoid:** Prejoin-Sperre "Name noch verbunden oder weniger als 2 s seit Verlassen" (Spike C mit Sperre: 0 Abstürze bei 0,2 bis 5 s). Gehört in `gameworld_access` (gilt dann für alle Welten, auch ohne Zeitregeln) oder in `gameworld_time`; Empfehlung `gameworld_access`, weil es eine Zugangsfrage ist. Upstream-Meldung an luanti-org als Owner-Entscheid.
**Warning signs:** Welt plötzlich "gestoppt" mit Log `ServerError: AsyncErr ... on_joinplayer`.

### Pitfall 2: Container-Zeitzone UTC
**What goes wrong:** "Nur bis 19 Uhr" wird im Winter um 19 Uhr UTC = 20 Uhr Berlin durchgesetzt.
**How to avoid:** Mod rechnet nur mit Epoch (`os.time`); alle lokalen Zeiten rechnet die ExApp mit `zoneinfo` und Einstellung `time_zone` [VERIFIED: `os.date("%z")` = `+0000` im Spike].

### Pitfall 3: Takt-Gutschrift statt Sitzungszeit
**What goes wrong:** Pauschale Gutschrift pro Takt (wie `playtime_limit` mit 60 s) lässt Rein-Raus-Wechsel ungezählt oder zählt Beitritte doppelt (Spike S1: 37 statt 40 s).
**How to avoid:** Beitrittszeit merken, anteilig gutschreiben, beim Verlassen nachbuchen und Zählbuch schreiben.

### Pitfall 4: `zoneinfo` ohne Zeitzonendaten
**What goes wrong:** Tests und Dev-Backend unter Windows werfen `ZoneInfoNotFoundError` [VERIFIED].
**How to avoid:** `tzdata` als Laufzeitabhängigkeit; Test, der `ZoneInfo("Europe/Berlin")` lädt.

### Pitfall 5: Mod-Ladereihenfolge und Ablehnungstexte
**What goes wrong:** Ein nicht eingeladener Fremder liest "Spielzeit aufgebraucht" statt "nicht eingeladen" und erfährt, dass es den Namen gibt.
**How to avoid:** `depends = gameworld_access` in `mod.conf` von `gameworld_time`; im Modus OR gewinnt der erste Text. e2e-Test: nicht eingeladener Name bei geschlossener Welt bekommt den Zugangstext.

### Pitfall 6: Regeländerung erreicht laufende Welt nicht
**What goes wrong:** Eltern kürzen die Zeit, Welt ist gerade in einer Elternaktion gesperrt, `try_mutation` schlägt fehl, Datei bleibt alt.
**How to avoid:** Regel-API schreibt blockierend unter `mutation()`; der Takt prüft per Byte-Vergleich und holt verpasste Schreibvorgänge nach; die Generation im Zählbuch-Kopf zeigt den geladenen Stand.

### Pitfall 7: Zählbuch-Rücksprung bei Restore (Phase 5)
**What goes wrong:** Ein Restore bringt ein älteres Zählbuch; `cap` aus der alten Rechnung schenkt Zeit oder ein negativer Zuwachs zieht Verbrauch ab.
**How to avoid:** `stand < gesehen` = neu ankern, nie negativ verbuchen; `_launch` liest vorhandenes Zählbuch per `get_archive` (geht auch bei gestopptem Container) vor dem Rendern.

### Pitfall 8: Kind mit wenigen Sekunden Rest
**What goes wrong:** Join mit 5 s Rest, Laden dauert 10 s, Kind wird beim Ankommen getrennt.
**How to avoid:** `MIN_LEFT` 60 s im Prejoin; Kinderansicht zeigt "weniger als 1 Minute" als aufgebraucht.

### Pitfall 9: Datensparsamkeit bei Verbrauchsdaten
**What goes wrong:** Spielzeit pro Tag und Kind ist ein Verhaltensprofil.
**How to avoid:** Nur Kinder mit Regeln zählen, Aufbewahrung kurz (heute plus 7 Tage, ältere Zeilen beim Takt löschen) [ASSUMED], keine Uhrzeiten einzelner Sitzungen speichern, nur Tagessummen; in privacy.md (Phase 6) aufnehmen.

### Pitfall 10: Abnahme braucht keine Stunde
**What goes wrong:** Abnahme mit realen Limits (15 min Raster) dauert zu lange oder führt zu Test-Hintertüren.
**How to avoid:** API akzeptiert Minuten (Limit 1 min, Fensterende = jetzt + 2 min), UI zeigt 15-min-Raster; Abnahme per Session-Prober (halten, Kick-Text prüfen), Negativ- und Positivkontrolle (Kind ohne Regeln bleibt verbunden).

## Code Examples

### Regeldatei rendern (pure)
```python
# provisioner/time_mod.py
TIME_HEADER = "gameworld-time 1"
_TOKEN = re.compile(r"[A-Za-z0-9:-]{1,16}")
REASONS = frozenset({"ok", "tag", "fenster", "limit", "frei"})

@dataclass(frozen=True)
class TimeLine:
    cap: int            # -1 = kein Limit
    start: int          # Epoch, 0 = heute nicht, -1 = frei
    until: int
    reason: str
    next_hint: str      # z. B. "Sa-10:00" oder "-"

def render_time_file(generation: int, issued_at: int, world: TimeLine | None, players: dict[str, TimeLine]) -> bytes:
    lines = [f"{TIME_HEADER} {generation} {issued_at}"]
    if world is not None:
        lines.append(_line("welt", world, with_cap=False))
    for name, line in sorted(players.items()):
        if not PLAYER_NAME.fullmatch(name):
            raise ValueError("Ungültiger Spielername in der Regeldatei.")
        lines.append(_line(name, line, with_cap=True))
    lines.append("end")
    return ("\n".join(lines) + "\n").encode("ascii")
# _line prüft reason in REASONS, next_hint gegen _TOKEN, Zahlen als int (bool ausgeschlossen)
```

### Zählbuch-Zuwachs (pure)
```python
# playtime/ledger.py
def increments(seen: dict[str, int], current: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
    """(Zuwachs je Name, neuer gesehener Stand). Rücksprung = neu ankern, nie negativ."""
    delta: dict[str, int] = {}
    for name, value in current.items():
        before = seen.get(name)
        if before is not None and value >= before:
            if value > before:
                delta[name] = value - before
        # before None (neu) oder value < before (Restore): nur ankern
    return delta, dict(current)
```
Achtung: Ein Name, der zum ersten Mal auftaucht, wurde womöglich schon gespielt (Zählbuch vor Einführung der Verbuchung, ExApp-Neuinstallation). Erstkontakt nur ankern ist die sichere Wahl gegen Doppelzählung; dadurch geht höchstens die Zeit vor dem ersten ExApp-Blick verloren.

### Schema 4 (Skizze)
```sql
CREATE TABLE IF NOT EXISTS time_plans (            -- Wochenpläne je Kind
  nc_user TEXT NOT NULL,
  plan TEXT NOT NULL CHECK (plan IN ('normal', 'ferien')),
  weekday INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  allowed INTEGER NOT NULL CHECK (allowed IN (0, 1)),
  limit_minutes INTEGER CHECK (limit_minutes IS NULL OR limit_minutes BETWEEN 1 AND 1440),
  window_start INTEGER CHECK (window_start IS NULL OR window_start BETWEEN 0 AND 1439),
  window_end INTEGER CHECK (window_end IS NULL OR window_end BETWEEN 1 AND 1440),
  PRIMARY KEY (nc_user, plan, weekday)
);
CREATE TABLE IF NOT EXISTS time_children (nc_user TEXT PRIMARY KEY, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS holidays (
  id INTEGER PRIMARY KEY, label TEXT NOT NULL DEFAULT '', start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  CHECK (start_date <= end_date)
);
CREATE TABLE IF NOT EXISTS world_windows (
  world_id TEXT NOT NULL, weekday INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
  window_start INTEGER NOT NULL, window_end INTEGER NOT NULL, PRIMARY KEY (world_id, weekday)
);
CREATE TABLE IF NOT EXISTS time_usage (nc_user TEXT NOT NULL, day TEXT NOT NULL, seconds INTEGER NOT NULL,
  PRIMARY KEY (nc_user, day));
CREATE TABLE IF NOT EXISTS time_ledger_seen (world_id TEXT NOT NULL, player_name TEXT NOT NULL,
  seconds INTEGER NOT NULL, PRIMARY KEY (world_id, player_name));
-- ALTER TABLE worlds ADD COLUMN time_generation INTEGER NOT NULL DEFAULT 0
-- meta: time_zone (leer = Europe/Berlin)
-- Welt löschen: world_windows und time_ledger_seen der Welt explizit löschen (kein PRAGMA foreign_keys)
```
Eine Zeile `time_children` heißt "Kind hat Regeln"; ohne Zeile keine Begrenzung (Opt-in). Welten ohne Zeilen in `world_windows` sind immer offen.

### Session-Prober (Test, live verifiziert)
Vollständige Fassung: `.planning/phases/04-spielzeitlimits/spike/session_probe.py`. Nach `TOCLIENT_AUTH_ACCEPT`: `TOSERVER_INIT2` (0x11, Kanal 1, zuverlässig, `str16("de")`), `TOSERVER_CLIENT_READY` (0x43, Kanal 1, zuverlässig: `u8 5, u8 17, u8 0, u8 0, str16(Version), u16 Formspec-Version`), danach zuverlässige Pakete quittieren, alle 3 s CONTROL PING (`0x00 0x02`), `TOCLIENT_CHAT_MESSAGE` (0x2F: `u8 Version, u8 Typ, wstring Absender, wstring Text, u64 Zeit`, wstring = u16 Länge + UTF-16BE) und `TOCLIENT_ACCESS_DENIED` (0x0A) mitschneiden [VERIFIED: serverpackethandler.cpp `handleCommand_Init2`/`handleCommand_ClientReady`, clientopcodes.cpp, client.cpp `sendReady`, server.cpp `SendChatMessage`; live: `on_joinplayer` läuft, Chat und Kick kommen an]. In `tests/e2e/luanti_probe.py` als `session()` übernehmen; damit wird auch der Phase-3-Punkt A7 (Kick laufender Spieler) automatisiert prüfbar (Spike B: Kick nach Widerruf live).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `core.kick_player` für Kindertexte | `core.disconnect_player` (ohne "Kicked: ") | in 5.17.0 dokumentiert | Phase-3-Kicktext optional umstellen |
| `playtime_limit` als Kandidat (Roadmap-Hinweis) | eigener Mod mit Zählbuch | Phase-4-Research | Umgehungs-Caveat bestätigt, Fremd-Mod verworfen |
| Join-Prober bis AUTH_ACCEPT (Phase 3) | Session-Prober bis `on_joinplayer` mit Kick/Chat | Phase-4-Spike | Kick, Vorwarnung und Absturzfälle automatisiert testbar |

**Deprecated/outdated:**
- CLAUDE.md nennt noch keine Spielzeit-Komponente; Zeile `gameworld_time` und `tzdata` beim nächsten Doku-Lauf ergänzen.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Ein Tageskontingent pro Kind über alle Welten, parallele Sitzungen zählen als Summe | Pattern 5 | Bei "pro Welt" müsste der Deckel je Welt aus eigenem Verbrauch kommen (einfacher); Owner bestätigen |
| A2 | Ferienzeiträume gelten global für den Haushalt, Ferienplan je Kind | Pattern 8, Schema | Kinder an verschiedenen Schulen bräuchten Zeiträume je Kind; Erweiterung um `nc_user` an `holidays` möglich |
| A3 | Ein Zeitfenster pro Tag (Kind und Welt) genügt | Pattern 4 | Zwei Unterrichtsstunden am selben Tag nicht abbildbar; Owner/Schulpilot prüfen |
| A4 | Verwalter sind von Welt-Fenstern und Kinderregeln freigestellt | Pattern 6 | Lehrkraft könnte sonst nicht vorbereiten; umgekehrt will ein Elternteil evtl. sich selbst begrenzen (dann UI-Option) |
| A5 | Fail closed nach Tagesende bei ExApp-Ausfall | Pattern 7 | Kinder kommen bei längerem ExApp-Ausfall nicht in die Welt; Alternative "letzter Plan weiter" ist umgehungsanfälliger |
| A6 | Welt-Zeitfenster stoppt die Welt nicht | Pattern 6 | RAM bleibt belegt; Auto-Stop ist v2 |
| A7 | AFK zählt als Spielzeit | Pattern 3 | Eltern könnten "aktive" Zeit erwarten; marktüblich ist Online-Zeit |
| A8 | Verbrauch nur für Kinder mit Regeln, Aufbewahrung heute plus 7 Tage | Pitfall 9 | Wochenstatistik später nicht möglich; Datenschutz-Default |
| A9 | Vorwarnungen 10/5/1 min als Chat reichen (kein HUD) | Pattern 1 | Kinder übersehen Chat; HUD als Verbesserung |
| A10 | Wiederbeitritts-Sperre 2 s ist für Kinder unauffällig | Pitfall 1 | Echte Clients brauchen ohnehin Sekunden für einen Neu-Join; Text erklärt es |
| A11 | Standard für neue Kinder: keine Begrenzung (Opt-in) | Pattern 8 | Alternative "Voreinstellung Wochenende" wäre restriktiver; Owner entscheidet |
| A12 | Downloadzahl von `tzdata` sehr hoch | Package Audit | rein informativ |

## Open Questions (RESOLVED)

1. **Kontingent über Welten: Summe oder Uhrzeit-Überlappung?**
   - What we know: Summe ist einfach und strenger; Überlappung bräuchte Zeitstempel je Sitzung.
   - Recommendation: Summe (A1), Owner bestätigt im discuss/plan-Schritt.
   - RESOLVED: Summe über alle Welten (Owner-Entscheid O-03 vom 20.10.2026, A1 bestätigt durch O-11); umgesetzt in 04-02/04-03.
2. **Wiederbeitritts-Sperre in `gameworld_access` oder `gameworld_time`?**
   - What we know: Absturz betrifft alle Welten unabhängig von Zeitregeln; Sperre live wirksam.
   - Recommendation: in `gameworld_access` (Phase 4, weil hier gefunden und Mods ohnehin neu ausgerollt werden); Owner entscheidet über eine Upstream-Meldung bei luanti-org.
   - RESOLVED: in `gameworld_access`, Welle 1 mit Live-Nachweis (Owner-Entscheid O-12); umgesetzt in 04-01 Task 1. Upstream-Meldung läuft separat, nicht Planbestandteil.
3. **"Bonuszeit heute" (Eltern geben spontan 30 min dazu)?**
   - What we know: marktüblich (Family Link, Microsoft Family), nicht in den Requirements.
   - Recommendation: nicht in Phase 4; mit dem Datenmodell leicht nachrüstbar (Tageszuschlag je Kind). Owner fragen.
   - DEFERRED: Bonuszeit ist nicht Teil von Phase 4; Owner-Frage im Checkpoint 04-08 Task 2 Schritt 8.
4. **Freistellung der Verwalter, wenn die Gruppenauflösung ausfällt?**
   - Recommendation: fail closed (Verwalter vorübergehend wie Kinder), Hinweis im Dashboard.
   - RESOLVED: fail closed in 04-05 (Schnappschuss meta time_admins, letzter Stand bleibt, ohne Stand keine Freistellung).
5. **Echter Client:** Darstellung der Umlaute in Kick-/Chattexten (A9 aus Phase 3) und Verhalten des Clients nach `disconnect_player` (Reconnect-Knopf) bleiben Owner-Abnahme mit echtem Luanti-Client.
   - DEFERRED: Owner-offen, in 04-08 Task 2 Schritt 9 und im 04-08-SUMMARY ausdrücklich als offen fürs Phasen-Audit geführt.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Desktop (WSL2) | Welten, Spike | ✓ | Engine 29.5.2 | - |
| Dev-Proxy `gameworld-dev-gameworld-docker-proxy-1` | `put_archive`/`get_archive` | ✓ 127.0.0.1:23750 (HTTP 200) | tecnativa | - |
| Dev-Nextcloud | Rollen, UI | ✓ 127.0.0.1:8091 (200) | 34.0.3 | - |
| Dev-ExApp | API | ✓ Heartbeat 200 auf 10040 | 0.1.0 | - |
| Luanti-Image | Welten | ✓ | 5.17.0 (Digest), Alpine, `TZ` leer, UTC | - |
| Spieldateien | Welten | ✓ `vendor/games` (MTG 38214, VoxeLibre 39534) | - | `scripts/fetch-games.sh` |
| Zeitzonendaten in `.venv` (Windows) | `zoneinfo` | ✗ | - | `uv add tzdata` (Pflicht) |
| Zeitzonendaten im Image `python:3.13-slim-trixie` | Produktiv | ✓ | Debian tzdata 2026b | - |
| Luanti-Client | UX-Abnahme (Texte, Reconnect) | ✗ | - | Session-Prober für Durchsetzung; Owner-Rechner für die Abnahme |

RAM: rund 2,6 GB frei bei laufenden Findling-Stacks; MTG-Spikes und ein VoxeLibre-Lauf passten seriell.
Aufgeräumt: alle Spike-Welten (`spike4/w1`) samt Volumes entfernt (`docker ps -a` und `docker volume ls` ohne `spike`). Hinweis: Ein versehentlich gestarteter, untätiger `python -`-Prozess (PID 9452/17588, wartet auf stdin, kein Bezug zur ExApp) läuft noch; Beenden wurde vom Berechtigungssystem abgelehnt, er belegt nur wenige MB.

## Validation Architecture

Übersprungen: `workflow.nyquist_validation` ist in `.planning/config.json` auf `false` gesetzt. Testhinweise für den Planer:
- Unit (pure): `plan.evaluate` mit den Golden Vectors (Umstellungstage, Fenster vor/in/nach, Tag nicht erlaubt, Ferienwechsel am Datum, "nächste Spielzeit" über Wochenende und Ferienende), `render_time_file` (Strenge, Injektion per Zeilenumbruch, deterministische Bytes), `parse_ledger` (halbe Datei, Fremdzeilen, Kappung), `increments` (Rücksprung, Erstkontakt), Tageszuordnung über den Zählbuch-Kopf, Migration Schema 3 auf 4 (idempotent).
- API: Verwalter-Routen 403 für `gw-kind`; `/api/my/worlds` liefert nur eigene Spielzeit; Validierung (Fenster leer, Ende vor Beginn, Limit 0, Ferien von > bis).
- e2e (`docker`-Marker): Session-Prober gegen echte Welt: Limit 1 min (Kick-Text, Vorwarnung), Rejoin abgelehnt, Neustart hält, Welt-Fenster zu mit Verwalter `frei`, Kind ohne Regeln bleibt verbunden (Positivkontrolle), Wiederbeitritt nach 0,2 s stürzt nicht ab (Regression zu Pitfall 1), nicht eingeladener Name bei geschlossener Welt bekommt den Zugangstext.
- Abnahme `scripts/dev/acceptance-phase4.sh` analog Phase 3 mit Regression der Phasen 1 bis 3.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (unverändert aus Phase 3) | - |
| V3 Session Management | no | - |
| V4 Access Control | yes | Regel-Routen nur Verwalter (AppAPI ADMIN + `require_verwalter`); Kinderdaten nur unter `/api/my/...` mit eigener UID; Durchsetzung im Spielserver, nicht im UI |
| V5 Input Validation | yes | Pydantic `extra="forbid"`, Minutenbereiche, Datumsformat ISO, `start <= end`, Zeitzone nur aus `zoneinfo.available_timezones()`, Regeldatei nur aus validierten Werten, Token-Regex |
| V6 Cryptography | no | - |
| V8 Data Protection | yes | Nur Tagessummen, nur für Kinder mit Regeln, kurze Aufbewahrung; keine Sitzungszeitpunkte, keine IPs |
| V11 Business Logic | yes | Neustart-, Rejoin- und Ausfallfestigkeit (Pattern 7), fail closed nach Tagesende |
| V12 Files | yes | Regeldatei root 0444 im Volume, Zählbuch nur vom Mod, Pfade fest, Leser kappt Größe |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Kind tritt nach Kick sofort wieder bei | Elevation of Privilege | Prejoin prüft Rest gegen Zählbuch (Spike S2) |
| Kind lässt Eltern die Welt neu starten, um Zeit zurückzusetzen | Tampering | Zählbuch im Volume, beim Start eingelesen (Spike S4) |
| Rein-Raus-Wechsel unter der Taktgrenze | Tampering | Gutschrift ab Beitritt und beim Verlassen, Wiederbeitritts-Sperre |
| Skriptierter Sofort-Rejoin bringt Welt zum Absturz | Denial of Service | Wiederbeitritts-Sperre 2 s (Spike C, 0 Abstürze) |
| Zwei Welten gleichzeitig | Elevation of Privilege | Summenverbuchung, Deckel je Welt im 15-s-Takt; Restrisiko nur bei ExApp-Ausfall (dokumentiert) |
| Uhr verstellen | Tampering | Kinder haben keinen Zugriff auf Server-/Host-Uhr; Client-Uhr irrelevant |
| Halbe Regeldatei | Tampering / DoS | Kopf + `end`, alter Stand (Spike S8) |
| Fremder erfährt über Zeittext, dass ein Name existiert | Information Disclosure | `depends = gameworld_access`, Zugangstext gewinnt |
| Kind liest Pläne/Verbrauch anderer Kinder | Information Disclosure | `/api/my/...` nur eigene Zeile, Test mit `gw-kind` |
| Verhaltensprofil durch Spielzeitdaten | Information Disclosure | Datensparsamkeit (Pitfall 9) |

## Sources

### Primary (HIGH confidence)
- Live-Spike 2026-10-20 auf dieser Maschine gegen den Dev-Proxy (docker-py 7.2.0, tecnativa), Luanti 5.17.0 (Digest-Pin), Minetest Game und VoxeLibre: `spike4.py` (S0 bis S9), `spike4b.py` (Kontrolle Zugangs-Kick und Absturz ohne Pause), `spike4c.py` (Abstandsreihe 0,2 bis 5 s, mit und ohne Sperre), `golden_tz.py`, `session_probe.py`, `time_mod.lua`; alle unter `.planning/phases/04-spielzeitlimits/spike/`, Aufruf aus dem Repo-Root mit `.venv/Scripts/python.exe -I` (bzw. `-I -X utf8` für Umlaute in der Ausgabe)
- Luanti 5.17.0 Quellen (raw.githubusercontent.com/luanti-org/luanti/5.17.0): `src/script/cpp_api/s_player.cpp` (`on_prejoinplayer`, Modus OR), `src/script/common/c_internal.h` (Enum), `builtin/common/register.lua` (`run_callbacks`), `src/script/cpp_api/s_security.cpp` (os-Whitelist), `src/network/serverpackethandler.cpp` (`handleCommand_Init2`, `handleCommand_ClientReady`), `src/network/clientopcodes.cpp`, `src/network/networkprotocol.h`, `src/client/client.cpp` (`sendReady`), `src/server.cpp` (`SendChatMessage`), `src/serverenvironment.cpp` (`getPlayer`), `src/script/lua_api/l_env.cpp` (`get_player_by_name`), `doc/lua_api.md` (Z. 4652, 6582, 6647, 6890, 7634, 7920 bis 7925)
- ContentDB-API und Release-Zips: `Linuxdirk/playtime_limit` (Metadaten, Releases, Quelltext Release 38620), `texmex/opening_hours` (Metadaten, Quelltext Release 2026-06-25), Suche `playtime`, `time limit`, `curfew`, `kick`, `afk`, `parental`, `schedule`, `opening hours`
- Python-Doku `zoneinfo` (Rückfall auf PyPI `tzdata`); PyPI-JSON `tzdata` 2026.5 (PSF, github.com/python/tzdata); slopcheck `scan tzdata --pkg pypi` = OK
- Gameworld-Code: `provisioner/access_mod.py`, `status_mod.py`, `archive.py`, `client.py`, `worlds/reconciler.py`, `worlds/store.py`, `worlds/service.py`, `api/me.py`, `main.py`, `appinfo/info.xml`, `frontend/node_modules/@nextcloud/vue/dist/components`

### Secondary (MEDIUM confidence)
- GitHub-Issue-Suche luanti-org/luanti und minetest_game zum Rejoin-Absturz (kein Treffer; nahe: #12271 "Guarantee that player object references don't change during the session")
- WebSearch zum Rejoin-Absturz: nur verwandter Hinweis im Mineclonia-`wieldview`-README zu ungültigen Spielerobjekten nach schnellem Verlassen

### Tertiary (LOW confidence)
- Marktübliche Kindersicherungs-Muster (Bonuszeit, AFK zählt, Voreinstellungen) aus Trainingswissen, als Annahmen markiert

## Metadata

**Confidence breakdown:**
- Durchsetzung im Mod, Neustart- und Rejoin-Festigkeit: HIGH (live, vollständiger Join, Kick und Chat empfangen)
- Rejoin-Absturz und Gegenmittel: HIGH (reproduziert mit Kontrollen in zwei Spielen, Ursache im Quelltext)
- Zeitzonen: HIGH (Golden Vectors, Container-Uhr gemessen)
- Verbuchung über Welten und Ausfallverhalten: MEDIUM (aus verifizierten Bausteinen entworfen, nicht als Ganzes gebaut)
- UI: MEDIUM (Komponenten geprüft, Bedienung nicht)

**Research date:** 2026-10-20
**Valid until:** 2026-11-19 (Luanti-Pin 5.17.0; bei Engine-Upgrade Rejoin-Absturz, Protokoll des Session-Probers und Callback-Modus erneut prüfen)
