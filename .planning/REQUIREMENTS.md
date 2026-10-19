# Requirements: Gameworld

**Defined:** 2026-10-19
**Core Value:** Ein Elternteil ohne Serverwissen startet in Minuten eine private, sichere Luanti-Welt, auf der nur Eingeladene spielen und deren Daten zuhause bleiben.

## v1 Requirements

### Welt-Lebenszyklus

- [ ] **WELT-01**: Elternteil kann eine Luanti-Welt per One-Click mit kindgerechtem Preset erstellen (Minetest Game kreativ, VoxeLibre überleben-sanft), ohne Konfigfragen
- [ ] **WELT-02**: Elternteil kann eine Welt starten, stoppen und neu starten und sieht den Status (läuft / gestoppt / startet / Fehler) verständlich im UI
- [ ] **WELT-03**: Elternteil sieht pro Welt, welche Spieler gerade online sind und den RAM-Verbrauch
- [ ] **WELT-04**: Mehrere Welten können parallel laufen (ein Container pro Welt)
- [ ] **WELT-05**: Jede Welt läuft mit konservativen Ressourcenlimits (RAM/CPU), ohne dass Eltern etwas einstellen müssen

### Zugang & Sicherheit

- [ ] **ZUGANG-01**: Welten sind privat per Default: kein `server_announce`, keine öffentliche Sichtbarkeit, keine "öffentlich machen"-Option im UI
- [ ] **ZUGANG-02**: Elternteil kann Nextcloud-Benutzer und -Gruppen in eine Welt einladen; Gameworld provisioniert dafür Luanti-Spieler-Accounts (Name und Passwort)
- [ ] **ZUGANG-03**: Nicht eingeladene Spieler werden serverseitig am Join gehindert (Whitelist-Durchsetzung, nicht nur UI)
- [ ] **ZUGANG-04**: Jeder eingeladene Spieler sieht eine Verbindungsinfo-Ansicht (Adresse, Port, Spielername, Schritt-für-Schritt-Anleitung für den Luanti-Client)

### Rollen

- [ ] **ROLLE-01**: Eltern verwalten, Kinder spielen: die Kind-Ansicht zeigt nur eigene Welten und Verbindungsinfo, keine Verwaltungsfunktionen
- [ ] **ROLLE-02**: Rollen werden aus Nextcloud-Gruppen abgeleitet; Gameworld hat keine eigene Benutzerverwaltung

### Spielzeit

- [ ] **ZEIT-01**: Elternteil kann pro Kind ein tägliches Spielzeitlimit und/oder ein Spielzeitfenster festlegen (z. B. maximal 2 Stunden, nur bis 19 Uhr)
- [ ] **ZEIT-02**: Das Limit wird serverseitig durchgesetzt, nicht nur angezeigt (Implementierungspfad Mod vs. Scheduler-Stopp wird per Phasen-Research entschieden; bekannter Umgehungs-Caveat des Playtime-Limit-Mods ist zu bewerten)

### Backup

- [ ] **BACKUP-01**: Elternteil kann pro Welt manuell ein Backup nach Nextcloud Files auslösen; der Snapshot ist konsistent (Welt wird sauber gestoppt oder eingefroren)
- [ ] **BACKUP-02**: Elternteil kann eine Welt aus einem Backup in Nextcloud Files wiederherstellen (Restore-Roundtrip funktioniert nachweislich)

### Plattform

- [ ] **PLATT-01**: Gameworld ist als ExApp über den Nextcloud App Store installierbar (AppAPI/HaRP, Ziel NC 32+)
- [ ] **PLATT-02**: Laufende Welten überleben ExApp-Updates und Host-Reboots: Zustand liegt in persistentem Storage, Container werden per Label-Reconciliation re-adoptiert

## v2 Requirements (deferred)

- **Auto-Stop bei Inaktivität** , erst bei Rückmeldungen zu RAM-Druck auf Heimservern
- **Zeitgesteuerte/automatische Backups** , erst wenn manuelles Backup zuverlässig läuft
- **Aktivitäts-Benachrichtigungen** (NC Notifications: "Welt gestartet", "Mia ist beigetreten") , Transparenz statt Überwachung
- **Weitere Presets und Feinschalter** (PvP, Chat, Schwierigkeitsgrad) , nach Feedback echter Familien
- **Kuratierte Mod-Auswahl für Eltern** , Kuratierung ist Pflegeaufwand, erst nach Produktvalidierung
- **Minecraft Java via Crafty oder itzg-Image (MVP 2)** , eigener Rechts-Research-Task zuerst (EULA/Guidelines)
- **Vereins-/Gruppenbetrieb (Teckids, CoderDojo)** , braucht Mandanten-/Rollenmodell jenseits Familie

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
| Chat-Vollprotokollierung | Überwachung statt Schutz; Privacy-Widerspruch zum Produktkern |
| Bedrock/Crossplay (Geyser) | Anderes Protokoll, großer Testaufwand; Luanti-Client ist überall frei |
| UPnP-Portöffnung | Sicherheitsrisiko; MVP ist LAN-first mit dokumentiertem VPN-Weg |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| WELT-01 | Phase 2 | Pending |
| WELT-02 | Phase 2 | Pending |
| WELT-03 | Phase 2 | Pending |
| WELT-04 | Phase 1 | Pending |
| WELT-05 | Phase 1 | Pending |
| ZUGANG-01 | Phase 1 | Pending |
| ZUGANG-02 | Phase 3 | Pending |
| ZUGANG-03 | Phase 3 | Pending |
| ZUGANG-04 | Phase 3 | Pending |
| ROLLE-01 | Phase 3 | Pending |
| ROLLE-02 | Phase 3 | Pending |
| ZEIT-01 | Phase 4 | Pending |
| ZEIT-02 | Phase 4 | Pending |
| BACKUP-01 | Phase 5 | Pending |
| BACKUP-02 | Phase 5 | Pending |
| PLATT-01 | Phase 6 | Pending |
| PLATT-02 | Phase 2 | Pending |

**Coverage:** 17/17 v1-Requirements gemappt (2026-10-19)

---
*Requirements for: Gameworld v1 (MVP 1, Luanti, Familien)*
*Defined: 2026-10-19*
