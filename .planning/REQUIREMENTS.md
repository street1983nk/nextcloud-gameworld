# Requirements: Gameworld

**Defined:** 2026-10-19
**Core Value:** Ein Elternteil ohne Serverwissen startet in Minuten eine private, sichere Luanti-Welt, auf der nur Eingeladene spielen und deren Daten zuhause bleiben.

## v1 Requirements

### Welt-Lebenszyklus

- [x] **WELT-01**: Elternteil kann eine Luanti-Welt per One-Click mit kindgerechtem Preset erstellen (Minetest Game kreativ, VoxeLibre überleben-sanft), ohne Konfigfragen
- [x] **WELT-02**: Elternteil kann eine Welt starten, stoppen und neu starten und sieht den Status (läuft / gestoppt / startet / Fehler) verständlich im UI
- [x] **WELT-03**: Elternteil sieht pro Welt, welche Spieler gerade online sind und den RAM-Verbrauch
- [x] **WELT-04**: Mehrere Welten können parallel laufen (ein Container pro Welt)
- [x] **WELT-05**: Jede Welt läuft mit konservativen Ressourcenlimits (RAM/CPU), ohne dass Eltern etwas einstellen müssen

### Zugang & Sicherheit

- [x] **ZUGANG-01**: Welten sind privat per Default: kein `server_announce`, keine öffentliche Sichtbarkeit, keine "öffentlich machen"-Option im UI
- [x] **ZUGANG-02**: Elternteil kann Nextcloud-Benutzer und -Gruppen in eine Welt einladen; Gameworld provisioniert dafür Luanti-Spieler-Accounts (Name und Passwort)
- [x] **ZUGANG-03**: Nicht eingeladene Spieler werden serverseitig am Join gehindert (Whitelist-Durchsetzung, nicht nur UI)
- [x] **ZUGANG-04**: Jeder eingeladene Spieler sieht eine Verbindungsinfo-Ansicht (Adresse, Port, Spielername, Schritt-für-Schritt-Anleitung für den Luanti-Client)

### Rollen

- [x] **ROLLE-01**: Eltern verwalten, Kinder spielen: die Kind-Ansicht zeigt nur eigene Welten und Verbindungsinfo, keine Verwaltungsfunktionen
- [x] **ROLLE-02**: Rollen werden aus Nextcloud-Gruppen abgeleitet; Gameworld hat keine eigene Benutzerverwaltung
- [ ] **ROLLE-03**: NC-Admin kann zusätzliche Verwalter-Gruppen einstellen (z. B. "lehrkraefte"); deren Mitglieder verwalten Welten ohne NC-Admin zu sein; Default bleibt Gruppe admin (Owner-Entscheid 20.10.2026 für Schulen/Vereine mit Nextcloud)

### Spielzeit

- [x] **ZEIT-01**: Elternteil kann pro Kind ein tägliches Spielzeitlimit und/oder ein Spielzeitfenster festlegen (z. B. maximal 2 Stunden, nur bis 19 Uhr)
- [x] **ZEIT-02**: Das Limit wird serverseitig durchgesetzt, nicht nur angezeigt (Implementierungspfad Mod vs. Scheduler-Stopp wird per Phasen-Research entschieden; bekannter Umgehungs-Caveat des Playtime-Limit-Mods ist zu bewerten)
- [x] **ZEIT-03**: Elternteil kann einen einfachen Wochenplan festlegen: pro Wochentag erlaubt/nicht erlaubt mit eigenem Limit und Zeitfenster (z. B. "nur Samstag und Sonntag, je 2 Stunden"); Voreinstellungen statt Konfigsprache (Owner-Anforderung 20.10.2026)
- [x] **ZEIT-04**: Elternteil kann Ferienzeiträume anlegen (von/bis-Datum), in denen eigene Regeln gelten (z. B. täglich statt nur Wochenende); die Umschaltung passiert automatisch am Datum, ohne dass Eltern daran denken müssen (Owner-Anforderung 20.10.2026)
- [x] **ZEIT-05**: Verwalter kann ein Zeitfenster pro Welt festlegen (z. B. "Mittwoch 10 bis 12 Uhr" als Unterrichtsstunde); außerhalb ist die Welt nicht betretbar, Durchsetzung serverseitig wie beim Wochenplan (Owner-Entscheid 20.10.2026 für Schulen/Vereine)

### Eltern-Handy

- [ ] **ELTERN-01**: Verwalter kann vom Handy eine Pause auslösen ("Essen ist fertig"): alle Kinder werden sanft getrennt, Beitritt bis zum Ende der Pause gesperrt, Pausenzeit zählt nicht; danach "weiter" oder "für heute Schluss" (Owner-Entscheid 21.10.2026)
- [ ] **ELTERN-02**: Verwalter bekommen eine Push-Benachrichtigung, wenn ein nicht eingeladener Spielername eine Welt betreten will (gedrosselt) (Owner-Entscheid 21.10.2026)
- [ ] **ELTERN-03**: Verwalter bekommen abends einen Tagesrückblick mit der Spielzeit je Kind, höchstens eine Benachrichtigung pro Tag, abschaltbar (Owner-Entscheid 21.10.2026)

### Talk

- [ ] **TALK-01**: Zu jeder Welt legt Gameworld einen Nextcloud-Talk-Raum an; Mitglieder folgen automatisch den Einladungen (inkl. Gruppen) plus Verwalter, Ausladen entfernt aus dem Raum, Löschen der Welt räumt den Raum ab; ohne Talk-App läuft Gameworld unverändert (Owner-Entscheid 21.10.2026)
- [ ] **TALK-02**: Ein Gameworld-Talk-Bot meldet im Raum der Welt Start/Stopp, Beitritte und das nahende Ende der Spielzeit (Owner-Entscheid 21.10.2026)

### Backup

- [ ] **BACKUP-01**: Elternteil kann pro Welt manuell ein Backup nach Nextcloud Files auslösen; der Snapshot ist konsistent (Welt wird sauber gestoppt oder eingefroren)
- [ ] **BACKUP-02**: Elternteil kann eine Welt aus einem Backup in Nextcloud Files wiederherstellen (Restore-Roundtrip funktioniert nachweislich)

### Plattform

- [ ] **PLATT-01**: Gameworld ist als ExApp über den Nextcloud App Store installierbar (AppAPI/HaRP, Ziel NC 32+)
- [x] **PLATT-02**: Laufende Welten überleben ExApp-Updates und Host-Reboots: Zustand liegt in persistentem Storage, Container werden per Label-Reconciliation re-adoptiert

## v2 Requirements (deferred)

- **Auto-Stop bei Inaktivität** , erst bei Rückmeldungen zu RAM-Druck auf Heimservern
- **Zeitgesteuerte/automatische Backups** , erst wenn manuelles Backup zuverlässig läuft
- **Aktivitäts-Benachrichtigungen** (NC Notifications: "Welt gestartet", "Mia ist beigetreten") , Transparenz statt Überwachung
- **Weitere Presets und Feinschalter** (PvP, Chat, Schwierigkeitsgrad) , nach Feedback echter Familien
- **Klassen-Preset für Unterricht** (kreativ, höheres max_users für ~30 Schüler, Chat-Schalter) , Schul-Brainstorm 20.10.2026, nur ein weiterer Registry-Eintrag, aber erst nach Pilot-Feedback
- **Handout-/Beamer-Ansicht** (Verbindungsinfo einer Welt druckfreundlich bzw. als QR-Code für die Klasse) , Schul-Brainstorm 20.10.2026
- **Kuratierte Mod-Auswahl für Eltern** , Kuratierung ist Pflegeaufwand, erst nach Produktvalidierung
- **Weitere Luanti-Spiele als Vorlagen: Mineclonia, Repixture, NodeCore** (fest eingeplant direkt nach v1-Store-Release, ca. 3 bis 4 Tage; Release-Pin plus SHA-256 und Git-Commit aus der ContentDB-API, Laden nur beim Image-Bau, trusted_mods/http_mods leer, Lua-Scan je Spiel-Zip als CI-Gate; vorher RAM-Spike) , Owner 22.10.2026, siehe .planning/research/WEITERE-SPIELE.md
- **Minecraft Java via itzg-Image + eigenes Paper-Plugin (MVP 2)** , erst nach Bedarfsumfrage (Reddit, Foren, GitHub) nach v1-Store-Release, Owner 21.10.2026, siehe .planning/research/MINECRAFT-V2.md
- **Mindustry als zweite fremde Engine** , zusammen mit der Engine-Abstraktion für Minecraft, erst nach Bedarfsumfrage; SuperTuxKart nur bei klarer Nachfrage und dann über einen Upstream-PR (Zugangskontrolle), siehe .planning/research/WEITERE-SPIELE.md
- **Vereins-/Schul-Mandantenmodell (Teckids, CoderDojo, Schulen)** , Welt-Besitzer (jede Lehrkraft sieht nur eigene Welten), Ressourcen-Budgets pro Verwalter, Schuljahres-Archivierung via Backup; Einstieg in v1 über ROLLE-03 + ZEIT-05
- **Bonuszeit heute** (Eltern geben +15/+30/+60 Minuten nur für heute frei, wie "Für heute ändern" bei Family Link) , Owner 21.10.2026 "find ich toll"
- **Mehr Zeit anfragen** (Kind bittet im Spiel per Chatbefehl oder in der Kind-Ansicht um mehr Zeit; Mod schreibt die Bitte ins Welt-Volume, ExApp liest sie im 15-s-Takt; Eltern bekommen eine Push-Benachrichtigung in der Nextcloud-Handy-App mit Link auf eine mobile Freigabeseite: +15, +30, Ablehnen; höchstens eine offene Bitte, wenige pro Tag) , Owner 21.10.2026; ExApp-Benachrichtigungen können nur Text und Link, keine Knöpfe
- **Brücke Spielchat zu Talk-Raum** (Luanti-Chat erscheint im Talk-Raum der Welt und umgekehrt, abschaltbar) , erst wenn Nutzer danach fragen (Moderation, Aufwand); Talk-Raum und Bot selbst sind seit 21.10.2026 v1 (TALK-01/02)
- **Discord-Webhook, nur ausgehend und optional** (Eltern schalten ein; "Welt läuft", "Mia spielt gerade"; verschickt die ExApp, kein Mod in der Welt, kein secure.http_mods) , nur auf Nachfrage aus der Community, eher für ältere Kinder ab 13 und Freundesgruppen (MVP 2), keine eigene App

## Out of Scope

| Exclusion | Reasoning |
|-----------|-----------|
| Öffentliche Serverliste / `server_announce`-Option | Zerstört das Kernversprechen; fremde Erwachsene auf dem Kinderserver |
| Werbung, Queues, Monetarisierung | Selfhosted braucht das nicht; genau der Wechselgrund zu Gameworld |
| Freier ContentDB-/Mod-Browser | Kinder installieren Fremdcode; bricht Kindersicherheits-Presets |
| Live-Konsole / RCON im UI | Konsole = Vollzugriff; widerspricht "keine Admin-Zugänge für Kinder" |
| Dateimanager / Raw-Config-Editor | Fußwaffe für die Zielgruppe "Eltern ohne Serverwissen" |
| Multi-Node-Betrieb | Massive Komplexität für ein Ein-Host-Heimserver-Produkt |
| Eigene Benutzer-/Accountverwaltung | Nextcloud-Konten sind die einzige Identität; DSGVO-Fläche |
| Zwei-Wege-Chatbrücke zu Discord oder anderen externen Diensten (Nextcloud Talk ist kein externer Dienst) | Umgeht das Einladungsmodell (Fremde schreiben mit Kindern), Chat verlässt den Heimserver, Discord erst ab 13; Owner-Entscheid 21.10.2026 |
| Chat-Vollprotokollierung | Überwachung statt Schutz; Privacy-Widerspruch zum Produktkern |
| Bedrock/Crossplay (Geyser) | Anderes Protokoll, großer Testaufwand; Luanti-Client ist überall frei |
| UPnP-Portöffnung | Sicherheitsrisiko; MVP ist LAN-first mit dokumentiertem VPN-Weg |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WELT-01 | Phase 2 | Complete |
| WELT-02 | Phase 2 | Complete |
| WELT-03 | Phase 2 | Complete |
| WELT-04 | Phase 1 | Complete |
| WELT-05 | Phase 1 | Complete |
| ZUGANG-01 | Phase 1 | Complete |
| ZUGANG-02 | Phase 3 | Complete |
| ZUGANG-03 | Phase 3 | Complete |
| ZUGANG-04 | Phase 3 | Complete |
| ROLLE-01 | Phase 3 | Complete |
| ROLLE-02 | Phase 3 | Complete |
| ZEIT-01 | Phase 4 | Complete |
| ZEIT-02 | Phase 4 | Complete |
| ZEIT-03 | Phase 4 | Complete |
| ZEIT-04 | Phase 4 | Complete |
| ZEIT-05 | Phase 4 | Complete |
| ELTERN-01 | Phase 4.1 | Pending |
| ELTERN-02 | Phase 4.1 | Pending |
| ELTERN-03 | Phase 4.1 | Pending |
| TALK-01 | Phase 4.1 | Pending |
| TALK-02 | Phase 4.1 | Pending |
| ROLLE-03 | Phase 6 | Pending |
| BACKUP-01 | Phase 5 | Pending |
| BACKUP-02 | Phase 5 | Pending |
| PLATT-01 | Phase 6 | Pending |
| PLATT-02 | Phase 2 | Complete |

**Coverage:** 26/26 v1-Requirements gemappt (Stand 2026-10-21; ZEIT-03/04/05 und ROLLE-03 am 20.10.2026, ELTERN-01..03 und TALK-01/02 am 21.10.2026 auf Owner-Wunsch ergänzt)

---
*Requirements for: Gameworld v1 (MVP 1, Luanti, Familien)*
*Defined: 2026-10-19*
