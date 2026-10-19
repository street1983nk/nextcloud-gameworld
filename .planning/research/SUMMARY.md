# Project Research Summary

**Project:** Gameworld
**Domain:** Kindgerechtes Gameserver-Portal als Nextcloud-ExApp (Python/AppAPI), Luanti-first, Docker-provisionierte Spielwelten
**Researched:** 2026-10-19
**Confidence:** MEDIUM-HIGH

## Executive Summary

Gameworld ist ein Elternkontroll-Produkt, kein Server-Admin-Panel. Der Markt baut entweder für Admins (Pterodactyl/Pelican/Crafty/LuHost: Konsole, Dateimanager, eigene User-DB) oder für Spieler mit Werbung und öffentlicher Infrastruktur (Aternos/Minehut). Niemand baut für Eltern: Spielzeit, Einladungen über existierende Familienkonten, privat per Default. Genau diese Lücke besetzt Gameworld als Nextcloud-ExApp. Die Identität kommt aus Nextcloud (Konten/Gruppen), Backups landen in Nextcloud Files, und die ganze Verwaltung läuft über ein Login im vertrauten UI.

Der empfohlene Bauweg: Python-ExApp (nc_py_api 0.30.x async-first, FastAPI, Vue 3 + @nextcloud/vue 9, min. Nextcloud 32 mit HaRP), die Luanti-Welten (Versions-Pin 5.17.0) als Sibling-Container über einen eigenen, eng gescopten tecnativa/docker-socket-proxy erzeugt. Dieser Provisionierungs-Entscheid ist die Architektur-Weiche des gesamten Projekts: AppAPI kann keine Sibling-Container für ExApps erzeugen, und der rohe Docker-Socket wäre Root-Äquivalenz auf dem Familienserver. Beide Researcher (Stack, Architektur) kommen unabhängig auf dasselbe Muster. Konsequenz: Die Installation ist nicht reine One-Click-Store-Installation, der Admin braucht einen zusätzlichen Proxy-Container per dokumentiertem Compose-Snippet; das ist ehrlich zu dokumentieren und per Setup-Check in der App abzufangen.

Die drei größten Risiken: (1) Sicherheits-GAU durch Docker-Socket-Fehler oder unsichere Luanti-Defaults (Luanti hat ab Werk KEINE Whitelist, offene Erstregistrierung, optionale Serverlisten-Ankündigung), (2) State-Drift zwischen App-DB und Docker-Realität (ExApp-Updates werfen den Container weg, Heimserver rebooten), (3) kaputte Backups durch Kopieren laufender SQLite-Welten. Alle drei sind mit bekannten Mustern vermeidbar (gescopter Proxy + gehärtetes conf-Template von Welt Nummer eins an, Reconciler + Container-Labels von Tag 1, Cold-Backup mit verpflichtendem Restore-Roundtrip-Test), aber nur, wenn sie von Anfang an eingeplant und nicht nachgerüstet werden.

## Key Findings

### Recommended Stack

Kernstack ist das bewährte Findling/Connector-Muster plus Docker-Provisionierung: Python 3.13, nc_py_api 0.30.3 (zwingend AsyncNextcloudApp, Sync-Wrapper werden entfernt), FastAPI/uvicorn, docker-py 7.2.0 (sync, in anyio.to_thread kapseln), Vue 3 + @nextcloud/vue 9.13 mit Vite (NICHT das veraltete ui_example-Skeleton). Ziel: Nextcloud min-version 32, HaRP als einziger dokumentierter Deploy-Weg (DSP ist deprecated, Entfernung zu NC 35 angekündigt).

**Core technologies:**
- nc_py_api 0.30.3 (async): ExApp-Lifecycle, Files, UI-Registrierung; offizielles Framework, bekanntes Terrain
- docker-py 7.2.0 gegen tecnativa/docker-socket-proxy: Welt-Provisionierung; vollständigste Docker-API für Python, Proxy minimiert die Angriffsfläche
- Luanti-Server-Image, Pin 5.17.0: eine Welt = ein Container, UDP-Port pro Welt; nie latest/master, nie 5.16.0 (broken)
- Vue 3 + @nextcloud/vue 9 + Vite: Nextcloud-Look, ausgeliefert über /exapps/gameworld/
- Whitelist-Mod von ContentDB: Luanti hat keine eingebaute Whitelist; Mod lädt whitelist.txt live nach (genaue Mod-Wahl offen, siehe Gaps)

**Kritische Netzwerk-Erkenntnis:** HaRP/FRP tunnelt nur HTTP der ExApp. Luanti-Spieltraffic ist UDP und muss pro Welt direkt als Host-Port publiziert werden (konfigurierbarer Bereich, z. B. 30000-30099/udp).

### Expected Features

Maßstab ist das Aternos-Erlebnis ("One-Click, kein Serverwissen"), nicht das Pterodactyl-Erlebnis. Kernvalidierung des MVP: "Elternteil ohne Serverwissen startet in Minuten eine private Welt, nur Eingeladene spielen."

**Must have (table stakes, MVP v1):**
- One-Click-Welt mit kindgerechtem Preset (Minetest Game kreativ, VoxeLibre sanft) + Start/Stop/Status
- Privat per Default: server_announce = false, keine "öffentlich machen"-Option im UI
- Einladen über NC-Konten/-Gruppen inkl. Auth-Provisionierung und serverseitiger Join-Sperre (komplexeste Table-Stakes-Anforderung)
- Eltern/Kind-Rollen aus NC-Gruppen: Kinder sehen nur Verbindungsinfo, Eltern verwalten
- Verbindungsinfo-Ansicht pro Spieler (Adresse, Port, Name kopierfertig, Schritt-für-Schritt)
- Backup/Restore nach Nextcloud Files (manuell reicht; Restore ist der kritische Teil)
- Ressourcenlimits pro Welt mit konservativen Defaults (Heimserver-Pflicht)

**Should have (Differentiatoren, v1.x):**
- Spielzeitlimits/Zeitfenster pro Kind (größte Elternsorge, nur ElfHosted bietet das überhaupt; Pfad-Entscheid Mod vs. Scheduler per Phasen-Research)
- Aktivitäts-Benachrichtigungen über NC Notifications ("Mia ist beigetreten")
- Auto-Stop bei Inaktivität, zeitgesteuerte Backups, weitere Presets

**Defer (v2+):**
- Kuratierte Mod-Auswahl (Pflegeaufwand; schließt freien ContentDB-Browser dauerhaft aus)
- Minecraft Java (MVP 2, eigene Rechts-/Engine-Research)
- Vereins-/Gruppenbetrieb, Talk-Integration

**Bewusste Anti-Features:** keine öffentliche Serverliste, keine Live-Konsole/RCON im UI, kein Dateimanager/Raw-Config-Editor, keine eigene User-DB, keine Chat-Vollprotokollierung, kein UPnP.

### Architecture Approach

Monolithische ExApp mit klaren Modulgrenzen; der Provisioner ist die einzige Stelle, die Docker spricht (Sollbruchstelle für spätere Härtung per Host-Daemon oder zweite Engine für Minecraft). Welt-Container tragen Labels (gameworld.world_id), ein Reconciler gleicht App-DB (SQLite auf dem persistenten AppAPI-Volume nc_app_gameworld_data) periodisch gegen die Docker-Realität ab; Docker ist Quelle der Wahrheit für "läuft". Datei-I/O in Welt-Container (whitelist.txt, minetest.conf, Backup-tars) über die Docker-Archive-API (docker-cp-Semantik), da AppAPI keine Mounts für ExApps erlaubt.

**Major components:**
1. World Manager + Reconciler: Lifecycle, Port-Vergabe, Soll/Ist-Abgleich, Saga-Muster für Mehrschritt-Operationen
2. Provisioner: einziges Docker-Modul (create/start/stop/remove/archive), gehärtete Container-Specs (cap_drop ALL, no-new-privileges, mem/memswap/pids-Limits)
3. Invites: NC-User/Gruppen zu Luanti-Spielername-Mapping, whitelist.txt-Erzeugung, app-generierte Passwörter
4. Backup Service: Welt stoppen, tar via Archive-API, Upload nach NC Files, Restore
5. UI/API: Vue-Dashboard mit serverseitigem Rollen-Check (Eltern vs. Kind)

### Critical Pitfalls

1. **Docker-Socket = Root auf dem Heimserver:** nie roh mounten; eigener gescopter Proxy im privaten Netz, Provisioner als enges Modul, gehärtete Game-Container. Phase-1-Entscheid, nicht nachrüstbar ohne Security-Advisory.
2. **Default-offene Luanti-Welt:** Whitelist nur als Mod, Erstregistrierung first-come, server_announce muss explizit aus. Gehärtetes conf-Template ab der allerersten Welt; Abnahmetest = Join mit nicht eingeladenem Namen muss scheitern.
3. **ExApp-Update/State-Drift:** Update wirft ExApp-Container weg; Zustand nur auf persistentes Volume, Container-Labels machen Welten auch ohne DB rekonstruierbar, Reconciliation gehört zum MVP. Update-Szenario mit laufender Welt als fester Testfall.
4. **Backup laufender Welten kopiert korrupte map.sqlite:** Cold-Backup (Stop, tar, Start) als MVP-Weg; automatisierter Backup-Restore-Roundtrip als Abschlusskriterium der Backup-Phase; SQLite-Backend erzwingen, nie LevelDB.
5. **OOM auf 4-8-GB-Heimservern:** Limits sind Pflichtfeld ab Welt eins (mem_limit = memswap_limit), Ressourcen-Check vor Welt-Start, OOM-Erkennung mit verständlicher Eltern-Meldung, restart-Policy nicht always.
6. **NAT/CGNAT:** "Freunde übers Internet" scheitert bei DS-Lite still. MVP-Scope ehrlich: LAN zuerst, VPN dokumentieren, kein UPnP. Dieser Scope-Schnitt gehört schon in die Roadmap-Definition.

## Implications for Roadmap

Based on research, suggested phase structure (die Build-Order aus ARCHITECTURE.md und das Pitfall-Phase-Mapping aus PITFALLS.md decken sich fast vollständig):

### Phase 1: ExApp-Gerüst + UI-Hülle
**Rationale:** Bekanntes Terrain aus Findling; schafft Deploy-Pfad, Top-Menü, Admin-Setting "Docker-Proxy-URL" ohne Docker-Abhängigkeit.
**Delivers:** Installierbare ExApp mit leerem Dashboard, Dev-Setup (manual-install + Compose-Stack).
**Addresses:** ExApp-Installation als Distributionskanal.
**Avoids:** Pitfall 10 (Store-Mechanik) wird früh angelegt: HaRP-kompatibles Image, async-first.

### Phase 2: Provisioner-Kern (riskantestes Stück zuerst)
**Rationale:** Validiert den zentralen Owner-Entscheid (Sibling-Container via Socket-Proxy) praktisch, bevor Features darauf bauen.
**Delivers:** Proxy per Compose dokumentiert, eine Luanti-Welt hart kodiert erzeugen/starten/stoppen/löschen; Limits, Labels, UDP-Port-Publish, gehärtetes minetest.conf-Template (announce aus, keine leeren Passwörter, minimale privs).
**Uses:** docker-py + tecnativa/docker-socket-proxy, Luanti-Image Pin 5.17.0.
**Avoids:** Pitfalls 1, 2, 5, 8 (conf-Template-Teil). Sichere Defaults ab Welt Nummer eins, nicht erst in der Einladungs-Phase.

### Phase 3: World Manager + State (One-Click-Welt)
**Rationale:** Erst mit Reconciler und SQLite-Sollzustand wird aus dem Provisioner ein Produkt; Reconciliation gehört zum MVP, nicht in "später".
**Delivers:** Welt-CRUD im UI, Port-Vergabe, Status aus Docker (nicht DB), Saga-Muster, Update-/Reboot-Überlebensfähigkeit.
**Implements:** World Manager + Reconciler, persistentes AppAPI-Volume.
**Avoids:** Pitfalls 3, 4 (State-Drift, Orphans, ExApp-Update).

### Phase 4: Invites + Zugangskontrolle
**Rationale:** Kernversprechen "nur Eingeladene"; braucht laufende Welten (Phase 3) und das conf-Template (Phase 2). Das NC-User-zu-Spielername-Mapping ist Fundament für Rollen UND spätere Spielzeitlimits.
**Delivers:** NC-User/Gruppen-Picker, Auth-Provisionierung, whitelist.txt via Archive-API, Whitelist-Mod im Welt-Setup, Negativ-Join-Test.
**Addresses:** Einladen über NC-Konten (P1-Differentiator), privat per Default technisch erzwungen.
**Avoids:** Pitfall 8 (Durchsetzungs-Teil), Pitfall 9 (Pseudonyme statt Klarnamen, Datenminimierung im Datenmodell).

### Phase 5: Backup/Restore nach Nextcloud Files
**Rationale:** Braucht sauberen Stop-Lebenszyklus aus Phase 3; Weltverlust ist Vertrauensverlust, daher vor Rollen-Polish.
**Delivers:** Cold-Backup (Stop, tar via Archive-API, Upload via nc_py_api), Restore im UI, automatisierter Backup-Restore-Roundtrip als Abschlusskriterium, Backups als Hintergrund-Job.
**Avoids:** Pitfall 6 (korrupte Backups).

### Phase 6: Eltern/Kind-Rollen + Verbindungsinfo + Erreichbarkeit
**Rationale:** Rollen gaten alle Verwaltungsfunktionen; Verbindungsinfo und Erreichbarkeits-Diagnose machen das Produkt für Kinder nutzbar.
**Delivers:** Kind-Ansicht (nur eigene Welten + Verbindungsinfo), serverseitige Rollen-Checks, LAN-Adresse/Port/QR, UDP-Erreichbarkeits-Diagnose mit CGNAT-Erkennung, VPN-Doku.
**Avoids:** Pitfall 7 (NAT/UPnP; Scope: LAN zuerst, kein UPnP).

### Phase 7: Härtung + Store-Release
**Rationale:** Store-Pfad hat mehr Varianten als das Dev-Setup; Zusatz-Privilegien (Proxy) müssen im Listing ehrlich erklärt sein.
**Delivers:** Installation vom Registry-Tag über echten HaRP-Daemon (AIO + Standard-Compose getestet), Uninstall-Cleanup + Orphan-Kommando, privacy.md, Setup-Check mit klarer Fehlermeldung, Listing-Texte.
**Avoids:** Pitfalls 9 (privacy.md), 10 (Release-Mechanik).

### Phase Ordering Rationale

- **Risiko zuerst:** Der Provisionierungs-Entscheid (Phase 2) ist die Architektur-Weiche; scheitert er, ändert sich alles Weitere. Darum direkt nach dem Gerüst validieren.
- **Abhängigkeiten diktieren:** Einladungen brauchen laufende Welten und das Auth-Mapping; Backups brauchen den Stop-Lebenszyklus; Rollen gaten die fertige Verwaltung. Deckt sich 1:1 mit dem Feature-Dependency-Graph aus FEATURES.md.
- **Sicherheit nicht nachrüstbar:** Gehärtete conf-Defaults, gescopter Proxy, Labels und Reconciler sind ab Tag 1 billig und später teuer (PITFALLS Recovery: Socket-Nachrüstung = Security-Advisory).
- **Jede Phase ist ein nutzbarer Vertical Slice:** ab Phase 3 One-Click-Welt, ab Phase 4 das Kernversprechen erfüllt.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 2 (Provisioner):** Welt-Daten-Ablage ist zwischen den Researchern uneinheitlich (benanntes Volume pro Welt vs. Daten im Container + Archive-API; betrifft auch VOLUMES-Scope des Proxy und die Image-Wahl ghcr.io/luanti-org vs. linuxserver). Außerdem Headless-Administration nur MEDIUM confidence (kein RCON, Konsolen-Zugriff via attach oder Lua-Agent-Mod offen).
- **Phase 4 (Invites):** Whitelist-Mod-Wahl ist offen: ARCHITECTURE empfiehlt "Whiter List" (AntumDeluge), STACK empfiehlt ct_whitelist (GreatBigDiamond), FEATURES nennt AntumDeluge/whitelist. Reload-Verhalten, Luanti-5.17-Kompatibilität und Pflege-Status der Kandidaten praktisch verifizieren, nicht blind wählen. Ebenso: Zusammenspiel Whitelist-Mod + Auth-Provisionierung (Passwort-Setzen vor erstem Join).
- **MVP 2 (Minecraft, später):** eigene Rechts-/Guideline-Recherche (EULA, Usage Guidelines, kein JAR im Image) plus Engine-Entscheid Crafty vs. itzg-Image als erster Task.

Phases with standard patterns (skip research-phase):
- **Phase 1 (ExApp-Gerüst):** bekanntes Findling/Connector-Muster, offizielle nc_py_api-Doku.
- **Phase 3 (State/Reconciler):** etabliertes Muster (Desired-State-Reconciliation), docker-py gut dokumentiert.
- **Phase 5 (Backup):** Cold-Backup + nc_py_api-Upload sind dokumentierte Standardwege; der Restore-Test ist Disziplin, keine Recherche.
- **Phase 7 (Store-Release):** eigene Release-Checkliste aus Findling existiert.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Kernstack über PyPI, GitHub Releases, offizielle Doku verifiziert; nur Luanti-Headless-Admin MEDIUM |
| Features | MEDIUM-HIGH | Panel-Features aus mehreren übereinstimmenden Quellen + LuHost-README direkt; Kid-Safety-Markt nur Sekundärquellen |
| Architecture | HIGH | Provisionierungs-Mechanik, AppAPI-Grenzen, Luanti-Container offiziell belegt; Panel-Reife-Details MEDIUM |
| Pitfalls | HIGH | ExApp-Lifecycle, Docker-Sicherheit, Luanti-Backup offiziell belegt; Luanti-conf-Defaults im Detail MEDIUM |

**Overall confidence:** MEDIUM-HIGH

### Gaps to Address

- **Whitelist-Mod-Diskrepanz (Whiter List vs. ct_whitelist vs. AntumDeluge/whitelist):** nicht blind entscheiden; in der Phasen-Research zu Phase 4 die Kandidaten gegen Luanti 5.17 testen (Live-Reload-Verhalten, Pflege-Status). Fallback laut STACK: direktes Schreiben der auth.sqlite (erfordert gestoppten Server).
- **Luanti-Image-Wahl (ghcr.io/luanti-org/luanti 5.17.0 vs. lscr.io/linuxserver/luanti):** STACK empfiehlt das offizielle Image, ARCHITECTURE nutzt linuxserver (anderes Daten-Layout /config/.minetest, kein gebündeltes Spiel). Entscheid in Phase 2 zusammen mit der Daten-Ablage-Frage.
- **Welt-Daten-Ablage (Named Volume + Hilfscontainer vs. Container-FS + Archive-API):** beeinflusst Proxy-Scope (VOLUMES), Backup-Pfad und Orphan-Cleanup. Spike in Phase 2.
- **Headless-Live-Kommandos (Konsole/attach vs. Lua-Agent-Mod):** MEDIUM confidence; für MVP vermutlich verzichtbar (Anti-Feature Live-Konsole), aber für Spielzeitlimits/Kick später relevant.
- **conf-Default-Werte im Detail:** beim Bau gegen minetest.conf.example verifizieren und im laufenden Container asserten (Abnahmetest).
- **Spielzeitlimit-Pfad (Mod vs. Scheduler):** bewusst auf v1.x vertagt; Entscheid per Phasen-Research bei Bedarf.

## Sources

### Primary (HIGH confidence)
- nc_py_api (PyPI + GitHub): 0.30.3, Async-Umstellung, NC-31-33-Support
- nextcloud/app_api + nextcloud/HaRP (GitHub) + Nextcloud Admin/Developer Manual: HaRP empfohlen ab NC 32, DSP deprecated (Entfernung NC 35), info.xml-Grenzen (keine Mounts), Docker Socket Proxy FAQ
- luanti-org/luanti Releases + docs.luanti.org: 5.17.0 Stable, 5.16.0 broken, Container-Setup, Backup-Doku (Cold-Backup), DB-Backends (SQLite robust, LevelDB riskant), Privileges, server_announce
- Tecnativa/docker-socket-proxy README: Allowlist-Mechanik
- docker-py 7.2.0, aiodocker 0.27.0 (PyPI), @nextcloud/vue 9.13.1 (npm)
- ContentDB Playtime Limit (Linuxdirk): explizit "servers for kids", Umgehungs-Caveat
- LuHost README (direkt gelesen): Feature-Referenz
- Eigene Findling/Connector-Erfahrung: Store-Submit, Image-Tag-Fallen, NC-Versionspflege

### Secondary (MEDIUM confidence)
- ContentDB-Whitelist-Mods (ct_whitelist, Whiter List): Live-Reload-Verhalten, Kompatibilität; praktisch zu verifizieren
- Panel-Features Pelican/Crafty (Hostinger, selfhostyourself, Saltbox, TrueNAS): übereinstimmende Sekundärquellen; Crafty = Minecraft-only (Negativbefund)
- Aternos/Minehut-Vergleiche (Blogs, deckungsgleich), luanti.ch/Supercraft (Luanti-Hosting-Markt)
- Kid-Safety-Markt: ElfHosted Parental Controls, ESRB-/CodeWizardsHQ-Elternratgeber
- Luanti-Wiki (Console braucht ncurses, Creative getrennt von Damage), linuxserver docker-luanti Docs
- Minecraft EULA/Usage-Guidelines-Konsolidierung (minecraft.net): vor MVP 2 Originaltexte erneut lesen

### Tertiary (LOW confidence)
- itzg/minecraft-server-Laufzeit-Download-Muster: Training-Wissen, vor MVP 2 verifizieren

---
*Research completed: 2026-10-19*
*Ready for roadmap: yes*
