# Gameworld

## What This Is

Gameworld ist ein kindgerechtes Gameserver-Portal als Nextcloud-ExApp. Familien betreiben damit private Spielwelten (zuerst Luanti, später Minecraft Java) auf dem eigenen Nextcloud-Server: eine Welt per Klick erstellen, Kinder und Freunde über Nextcloud-Konten einladen, Weltsicherungen in Nextcloud Files, Elternkontrolle statt Admin-Zugängen für Kinder.

## Core Value

Ein Elternteil ohne Serverwissen kann in wenigen Minuten eine private, sichere Luanti-Welt für die eigenen Kinder starten, auf der nur eingeladene Personen spielen und deren Daten zuhause bleiben.

## Requirements

### Validated

(None yet , ship to validate)

### Active

- [ ] Luanti-Welt per One-Click erstellen, starten, stoppen
- [ ] Spieler einladen über Nextcloud-Konten/-Gruppen, keine fremden Spieler
- [ ] Weltsicherung (Backup/Restore) in Nextcloud Files
- [ ] Elternkontrolle: Kinder spielen, verwalten aber nicht (keine Admin-Zugänge für Kinder)
- [ ] Spielzeitlimits/Spielzeitfenster pro Kind, serverseitig durchgesetzt
- [ ] Ressourcenlimits pro Welt (RAM/CPU), damit der Heimserver stabil bleibt
- [ ] Installation als ExApp über den Nextcloud App Store (AppAPI, Docker-Deploy)

### Out of Scope

- Minecraft Java (MVP 2) , erst nach Luanti-MVP; EULA-/Guideline-Risiko, zusätzlicher Engine-Aufwand (+8 bis 12 Tage via Crafty)
- Vereine/Gruppen-Betrieb (Teckids, CoderDojo) , Pilot nach Familien-MVP; braucht Rollen-/Mandantenmodell
- Öffentliche Server, Serverlisten, Monetarisierung , Gegenentwurf zu Aternos/Minehut ist gerade die Privatheit
- Bedrock/Konsolen-Crossplay , anderes Protokoll (raknet/geyser), nicht MVP
- Eigene Mod-/Plugin-Marktplätze , Kinder installieren nichts selbst; kuratierte Inhalte später

## Context

- Owner-Entscheid 16.10.2026: Gameworld wird gebaut, Start jetzt (Findling 1.6 läuft in paralleler Session).
- Marktlücke bestätigt: Nextcloud App Store Kategorie Games hat nur Minispiele, kein Gameserver-Portal. Aternos/Minehut sind öffentlich/werbefinanziert; "privat, nur Familie, Daten zuhause" bedient fast niemand.
- Luanti-first reduziert Rechtsrisiko (völlig frei) gegenüber Minecraft (EULA erlaubt privates Hosting, Guidelines jederzeit änderbar).
- Engine-Lage: Pterodactyl im Maintenance-Mode; Pelican aktiv aber Beta; Crafty Controller 4.11 leichter, Minecraft-only, REST-API; Luanti-Ökosystem: LuHost (CU Boulder), luanti.ch-Panel, MinetestEDU.
- Vorarbeit/Skillset: Findling (ExApp im Store) und Nextcloud MCP Connector , Python, AppAPI, Store-Submit-Prozess sind bekannt.
- Pilot-Kandidaten für später: Teckids, CoderDojo (Kontaktanbahnung läuft über "Bringing Kids to Nextcloud", Fabrice Mous).
- Aufwandsschätzung 16.10.: MVP 1 Luanti ca. 15 bis 22 Arbeitstage.

## Constraints

- **Tech stack**: Python-ExApp über AppAPI (passt zu Findling/Connector-Skillset) , kein eigenes Framework-Experiment
- **Plattform**: Muss als ExApp im Nextcloud App Store installierbar sein (Docker-Deploy, AppAPI-Konventionen)
- **Sicherheit**: Kindersicher ist Produktkern , private Welten per Default, keine offenen Ports ohne Einladung, keine Admin-Zugänge für Kinder
- **Ressourcen**: Läuft auf Heimservern , Ressourcenlimits pro Welt sind Pflicht, keine Annahme von Server-Hardware
- **Recht**: Luanti zuerst; Minecraft erst in MVP 2 mit EULA-Prüfung
- **Zeit**: Soloprojekt neben Findling-Pflege; grobe Phasen, wenig Zeremonie

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Luanti-first, Minecraft als MVP 2 | Kein EULA-Risiko, freies Ökosystem, gleiche Produktmechanik | Pending |
| Scope: Familien zuerst, Vereine später | Differenzierung "privat, Daten zuhause"; einfacheres Rollenmodell im MVP (Owner 19.10.2026) | Pending |
| Container-Provisionierung: Entscheid nach Research | AppAPI-Docker-Socket vs. Host-Daemon vs. Engine-Panel-API wird in der Projekt-Research konkret geprüft, Empfehlung geht an Owner (Owner 19.10.2026) | Pending |
| ExApp in Python (AppAPI) | Vorhandenes Skillset aus Findling/Connector, Store-Prozess bekannt | Pending |
| Vertical-MVP-Slices statt Schichten | Jede Phase liefert eine nutzbare Fähigkeit, frühes Testen mit echter Welt | Pending |
| Spielzeitlimits in v1 statt v1.x | Owner-Entscheid 19.10.2026: größte Elternsorge laut Research, gehört ins Kernversprechen | Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check , still the right priority?
3. Audit Out of Scope , reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-10-19 after initialization*
