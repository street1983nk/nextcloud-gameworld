# Roadmap: Gameworld

## Overview

Gameworld wird in sechs vertikalen MVP-Slices gebaut. Zuerst das riskanteste Stück: ExApp-Gerüst plus Docker-Provisionierung über den gescopten Socket-Proxy, mit gehärteten, privaten Luanti-Containern ab Welt Nummer eins. Darauf folgt die One-Click-Weltverwaltung mit Reconciler (Update- und Reboot-Überlebensfähigkeit), dann das Kernversprechen: Einladungen über Nextcloud-Konten mit serverseitiger Whitelist und Eltern/Kind-Rollen. Anschließend Spielzeitlimits (Owner-Entscheid 19.10.2026: v1-Scope), Backup/Restore nach Nextcloud Files mit Pflicht-Roundtrip-Test, und zum Abschluss Härtung plus Store-Release.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Fundament** - ExApp-Gerüst plus Provisioner-Kern: gehärtete private Luanti-Container über gescopten Socket-Proxy (completed 2026-10-19)
- [x] **Phase 2: One-Click-Welten** - Welt-Verwaltung im UI mit Presets, Status, Reconciler und Update-/Reboot-Überlebensfähigkeit (completed 2026-10-19)
- [x] **Phase 3: Zugang und Rollen** - Einladungen über Nextcloud-Konten, serverseitige Whitelist, Eltern verwalten, Kinder spielen (completed 2026-10-20)
- [ ] **Phase 4: Spielzeitlimits** - Tageslimit und Zeitfenster pro Kind, serverseitig durchgesetzt
- [ ] **Phase 5: Backup und Restore** - Konsistente Weltsicherungen nach Nextcloud Files mit nachgewiesenem Restore-Roundtrip
- [ ] **Phase 6: Store-Release** - Härtung, Setup-Check, Cleanup und Veröffentlichung im Nextcloud App Store

## Phase Details

### Phase 1: Fundament

**Goal**: Gameworld läuft als ExApp auf der eigenen Nextcloud und kann gehärtete, private Luanti-Welten als Sibling-Container sicher erzeugen und steuern
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: WELT-04, WELT-05, ZUGANG-01
**Success Criteria** (what must be TRUE):

  1. Admin installiert Gameworld als ExApp im Dev-Setup (manual-install plus Compose-Stack) und öffnet die App über das Nextcloud-Top-Menü
  2. Eine Luanti-Welt (Pin 5.17.0) kann erzeugt, gestartet, gestoppt und gelöscht werden; mehrere Welten laufen parallel, je Welt ein eigener Container mit eigenem UDP-Port
  3. Jede Welt startet mit konservativen RAM/CPU-Limits (mem_limit = memswap_limit, pids-Limit, cap_drop ALL), ohne dass jemand etwas einstellen muss
  4. Jede neue Welt ist privat per Default: server_announce aus, keine leeren Passwörter, minimale Privilegien; eine Option "öffentlich machen" existiert nirgends
  5. Docker-Zugriff läuft ausschließlich über den eng gescopten tecnativa/docker-socket-proxy (dokumentiertes Compose-Snippet); ein fehlender Proxy wird per Setup-Check verständlich gemeldet

**Plans**: 5 plans
Plans:
**Wave 1**

- [x] 01-01-PLAN.md , Walking Skeleton A: gehärtete private Welt per API erzeugen (Provisioner, SQLite, Dev-Proxy)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 01-02-PLAN.md , Walking Skeleton B: ExApp im Top-Menü, Welt per Klick erstellen (info.xml, Lifecycle, Vue-Hülle, smoke.sh)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 01-03-PLAN.md , Lebenszyklus: parallele Welten starten, stoppen, löschen, Port-Kollision, Instanz-Schutz

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 01-04-PLAN.md , Setup-Check für den Docker-Proxy plus docs/install.md mit gescoptem Snippet und Restrisiko

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 01-05-PLAN.md , Phasenabnahme: Abnahmeskript K1 bis K5 plus gemeinsame Playwright-Abnahme

**UI hint**: yes
**Research flag**: yes (Welt-Daten-Ablage: Named Volume vs. Container-FS plus Archive-API; Image-Wahl ghcr.io/luanti-org vs. linuxserver; Headless-Administration)

### Phase 2: One-Click-Welten

**Goal**: Ein Elternteil ohne Serverwissen erstellt und verwaltet Welten per Klick im Dashboard; der Zustand überlebt ExApp-Updates und Host-Reboots
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: WELT-01, WELT-02, WELT-03, PLATT-02
**Success Criteria** (what must be TRUE):

  1. Elternteil erstellt eine Welt per One-Click mit kindgerechtem Preset (Minetest Game kreativ, VoxeLibre überleben-sanft), ohne Konfigfragen
  2. Elternteil startet, stoppt und startet eine Welt neu im Dashboard und sieht den Status (läuft / gestoppt / startet / Fehler) verständlich; Status kommt aus Docker, nicht aus der DB
  3. Elternteil sieht pro Welt, welche Spieler gerade online sind und wie viel RAM die Welt verbraucht
  4. Nach einem ExApp-Update und nach einem Host-Reboot sind alle Welten wieder korrekt im Dashboard (Label-Reconciliation re-adoptiert Container, Zustand liegt auf persistentem Volume)

**Plans**: 7 plans
Plans:
**Wave 1**

- [x] 02-02-PLAN.md , VoxeLibre 0.92.4 hash-geprüft bereitstellen (Fetch-Skript, SHA256SUMS, Lizenzdoku, Dev-Setup)

**Wave 2** *(blocked on Wave 1 completion; seriell wegen gemeinsamem Live-Dev-Stack)*

- [x] 02-01-PLAN.md , Kreativ-Preset Ende zu Ende: Preset-Registry, Schema 2 mit Migration, preset in API, keine failed-Zeile ohne Docker-Reste

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md , Abenteuer (sanft) mit VoxeLibre und 1 GiB, Welt-Mod gameworld_status, gestreamter Payload, Live-Nachweis

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 02-04-PLAN.md , Status aus Docker (läuft/startet/gestoppt/Fehler), Neustart, Dashboard mit Preset-Auswahl und Polling

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 02-05-PLAN.md , Online-Spieler und RAM pro Welt, 2-s-Cache, Liste nach "Erneut prüfen" aktualisieren

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 02-06-PLAN.md , Reconciler im Lifespan: Reboot- und Update-Überleben per Label-Reconciliation

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 02-07-PLAN.md , Phasenabnahme: acceptance-phase2.sh K1 bis K4 plus gemeinsame Playwright-Abnahme mit Luanti-Client

**UI hint**: yes

### Phase 3: Zugang und Rollen

**Goal**: Nur Eingeladene können spielen; Kinder spielen, Eltern verwalten, und jeder Spieler findet selbst in seine Welt
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: ZUGANG-02, ZUGANG-03, ZUGANG-04, ROLLE-01, ROLLE-02
**Success Criteria** (what must be TRUE):

  1. Elternteil lädt Nextcloud-Benutzer und -Gruppen in eine Welt ein; Gameworld provisioniert Luanti-Spieler-Accounts (Name und Passwort) automatisch
  2. Ein nicht eingeladener Spielername scheitert serverseitig am Join (Negativ-Join-Test besteht, Whitelist-Durchsetzung statt reiner UI-Sperre)
  3. Jeder eingeladene Spieler sieht eine Verbindungsinfo-Ansicht mit Adresse, Port, Spielername und Schritt-für-Schritt-Anleitung für den Luanti-Client
  4. Die Kind-Ansicht zeigt nur eigene Welten und Verbindungsinfo; Verwaltungsfunktionen sind serverseitig für Kinder gesperrt, nicht nur ausgeblendet
  5. Rollen werden aus Nextcloud-Gruppen abgeleitet; Gameworld hat keine eigene Benutzerverwaltung

**Plans**: 7 plans
Plans:
**Wave 1**

- [x] 03-01-PLAN.md , Durchsetzung im Spielserver: Welt-Mod gameworld_access, SRP-Verifier, Zugangsdatei per put_archive, Negativ-Join per UDP-Prober (MTG und VoxeLibre)

**Wave 2** *(blocked on Wave 1 completion; seriell wegen gemeinsamem Live-Dev-Stack)*

- [x] 03-02-PLAN.md , Rollen aus Nextcloud-Gruppen: require_verwalter, Routen USER/ADMIN, /api/me, Rollenweiche im Frontend, Phase-1-Abnahme angepasst

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 03-03-PLAN.md , Nutzer einladen Ende zu Ende: Schema 3 ohne Passwortfeld, HMAC-abgeleitete Spielpasswörter (Geheimnis in appconfig_ex), AccessService, Invites-API, Positiv-Join

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 03-04-PLAN.md , Gruppen-Einladungen mit dynamischem Abgleich, Passwort neu per Rotation, Umbenennen, Neuprovisionierung nach Geheimniswechsel

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 03-05-PLAN.md , Eltern-UI: Einladen-Dialog (Benutzer und Gruppen), Spielerverwaltung, Weltschlüssel-Anzeige entfällt, Hinweis "Neustart nötig"

**Wave 6** *(blocked on Wave 5 completion)*

- [x] 03-06-PLAN.md , Kind-Ansicht: /api/my/worlds, Verbindungsinfo mit Anleitung, Spieler-Adresse als Einstellung, lazy Gruppen-Provisionierung

**Wave 7** *(blocked on Wave 6 completion)*

- [x] 03-07-PLAN.md , Phasenabnahme: acceptance-phase3.sh K1 bis K5 plus gemeinsame Playwright-Abnahme, Doku, ct_whitelist-Korrektur

**UI hint**: yes
**Research flag**: yes (Whitelist-Mod-Wahl: Whiter List vs. ct_whitelist vs. AntumDeluge gegen Luanti 5.17 testen; Zusammenspiel Whitelist-Mod und Auth-Provisionierung)

### Phase 4: Spielzeitlimits

**Goal**: Eltern legen Spielzeit pro Kind fest, mit Wochenplan und Ferienzeiten, und können sich darauf verlassen, dass der Server sie durchsetzt
**Mode:** mvp
**Depends on**: Phase 3
**Requirements**: ZEIT-01, ZEIT-02, ZEIT-03, ZEIT-04, ZEIT-05
**Success Criteria** (what must be TRUE):

  1. Elternteil legt pro Kind ein tägliches Spielzeitlimit und/oder ein Spielzeitfenster fest (z. B. maximal 2 Stunden, nur bis 19 Uhr)
  2. Elternteil legt einen einfachen Wochenplan fest: pro Wochentag erlaubt/nicht erlaubt mit eigenem Limit und Fenster (typischer Fall "nur am Wochenende"); die Eingabe ist kindersicherungs-üblich einfach (Tages-Kacheln/Schalter, sinnvolle Voreinstellungen), keine Konfigsprache (Owner-Anforderung 20.10.2026)
  3. Elternteil legt Ferienzeiträume (von/bis-Datum) mit eigenen Regeln an; am Datum schaltet Gameworld automatisch zwischen Normal- und Ferienregeln um, ohne dass Eltern daran denken müssen (Owner-Anforderung 20.10.2026)
  4. Verwalter kann zusätzlich ein Zeitfenster PRO WELT festlegen (z. B. "Mittwoch 10 bis 12 Uhr" für eine Unterrichtsstunde); außerhalb ist die Welt nicht betretbar; dieselbe Durchsetzungsmechanik wie beim Wochenplan (Owner-Entscheid 20.10.2026, Schul-/Vereins-Nutzung)
  5. Bei Erreichen des Limits oder außerhalb erlaubter Zeiten wird das Kind serverseitig getrennt und am Wieder-Join gehindert, nicht nur per Anzeige informiert
  6. Das Limit hält auch nach Welt-Neustart und Rejoin-Versuch (bekannter Umgehungs-Caveat des Playtime-Limit-Mods ist bewertet und abgefangen oder dokumentiert)

**Plans**: 8 plans
Plans:
**Wave 1**

- [x] 04-01-PLAN.md , Durchsetzung im Spielserver: 2-s-Wiederbeitritts-Sperre in gameworld_access (Live-Nachweis per Session-Prober, MTG und VoxeLibre), Welt-Mod gameworld_time mit Prejoin-Sperre, Vorwarnung 10/5/1 min, Trennen und neustartfestem Zählbuch

**Wave 2** *(blocked on Wave 1 completion; seriell wegen gemeinsamem Live-Dev-Stack)*

- [x] 04-02-PLAN.md , Zeitrechnung und Gedächtnis: tzdata, reine Plan-Auswertung mit Golden Vectors (Sommerzeit, Ferienwechsel, Tagesende), Zählbuch-Verbuchung, Schema 4

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 04-03-PLAN.md , Tageslimit und Zeitfenster pro Kind Ende zu Ende: TimeEngine, Verwalter-API, 15-s-Zeittakt im Lifespan, ein Kontingent über alle Welten, Neustart-Hinweis, Prober-Beweis

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 04-04-PLAN.md , Wochenplan, Ferien und Zeitzone: Ferienplan je Kind, Haushalts-Ferienliste, automatische Umschaltung am Datum, Zeitzonen-Einstellung, Live-Nachweis

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 04-05-PLAN.md , Zeitfenster pro Welt (ZEIT-05): Join-Sperre und Trennen, Welt läuft weiter, Verwalter freigestellt, Live-Nachweis

**Wave 6** *(blocked on Wave 5 completion)*

- [ ] 04-06-PLAN.md , Eltern-UI: Spielzeit-Dialog mit Voreinstellungen und Tages-Kacheln, Ferien, Welt-Zeitfenster, Zeitzone, Hinweis "Neustart nötig"

**Wave 7** *(blocked on Wave 6 completion)*

- [ ] 04-07-PLAN.md , Kind-Ansicht: eigene Restzeit und Öffnungszeiten der Welten, nur eigene Werte

**Wave 8** *(blocked on Wave 7 completion)*

- [ ] 04-08-PLAN.md , Phasenabnahme: acceptance-phase4.sh K1 bis K6 mit Regression Phase 1 bis 3 plus gemeinsame Playwright-Abnahme, Doku Spielzeit

**UI hint**: yes
**Research flag**: yes (Implementierungspfad Mod vs. Scheduler-Stopp; Umgehungs-Caveat des Playtime-Limit-Mods bewerten)

### Phase 5: Backup und Restore

**Goal**: Weltstände liegen sicher in Nextcloud Files und lassen sich nachweislich wiederherstellen
**Mode:** mvp
**Depends on**: Phase 2
**Requirements**: BACKUP-01, BACKUP-02
**Success Criteria** (what must be TRUE):

  1. Elternteil löst pro Welt manuell ein Backup aus; die Welt wird dafür sauber gestoppt (Cold-Backup), gesichert und danach wieder gestartet
  2. Der Snapshot landet als konsistente Datei in Nextcloud Files (SQLite-Backend erzwungen, kein Kopieren laufender map.sqlite)
  3. Elternteil stellt eine Welt aus einem Backup in Nextcloud Files wieder her; ein automatisierter Backup-Restore-Roundtrip-Test besteht als Abschlusskriterium

**Plans**: TBD

### Phase 6: Store-Release

**Goal**: Jede Familie und jede Schule mit Nextcloud kann Gameworld direkt aus dem Nextcloud App Store installieren, mit ehrlicher Erklärung der Zusatz-Privilegien
**Mode:** mvp
**Depends on**: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5
**Requirements**: PLATT-01, ROLLE-03
**Success Criteria** (what must be TRUE):

  1. Gameworld ist über den Nextcloud App Store installierbar (AppAPI/HaRP, Ziel NC 32+); Installation vom Registry-Tag ist auf AIO und Standard-Compose getestet
  2. Der Setup-Check erklärt einen fehlenden oder falsch konfigurierten Docker-Proxy mit einer klaren, handlungsfähigen Fehlermeldung
  3. Deinstallation räumt auf; verwaiste Welt-Container sind per Orphan-Kommando auffindbar und entfernbar
  4. Store-Listing und privacy.md erklären die Zusatz-Privilegien (Socket-Proxy, UDP-Ports) ehrlich und vollständig
  5. Ein NC-Admin kann zusätzliche Verwalter-Gruppen einstellen (z. B. "lehrkraefte" oder "eltern"); Mitglieder dieser Gruppen verwalten Welten, ohne NC-Admins zu sein; Default bleibt die Gruppe admin (Owner-Entscheid 20.10.2026, Schul-/Vereins-Nutzung)

**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Fundament | 5/5 | Complete   | 2026-10-19 |
| 2. One-Click-Welten | 7/7 | Complete | 2026-10-19 |
| 3. Zugang und Rollen | 7/7 | Complete | 2026-10-20 |
| 4. Spielzeitlimits | 5/8 | In Progress|  |
| 5. Backup und Restore | 0/TBD | Not started | - |
| 6. Store-Release | 0/TBD | Not started | - |
