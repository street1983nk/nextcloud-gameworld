# Feature Research

**Domain:** Kid-safe game-server portal (Nextcloud ExApp, Luanti-first)
**Researched:** 2026-10-19
**Confidence:** MEDIUM-HIGH (Panel-Features aus mehreren übereinstimmenden Quellen plus LuHost-README direkt; Luanti-Mechaniken aus offiziellen Docs/ContentDB; Kid-Safety-Markt nur über Sekundärquellen)

## Feature Landscape

Referenzprodukte analysiert: Aternos, Minehut (Free-Hosting), Pterodactyl/Pelican (Selfhost-Panels), Crafty Controller (Minecraft-Panel), LuHost (Luanti-Dashboard, CU Boulder), luanti.ch / Supercraft (kommerzielle Luanti-Hosts), ElfHosted-Familienangebot (Parental-Controls-Panel).

Zentrale Erkenntnis: Der Panel-Markt (Pterodactyl, Pelican, Crafty, LuHost) baut für **Server-Admins** (Konsole, Dateimanager, Cron, Eggs). Die Free-Hoster (Aternos, Minehut) bauen für **Spieler ohne Serverwissen** (One-Click, Presets, Auto-Sleep), finanzieren das aber mit Werbung und öffentlicher Infrastruktur. **Niemand baut für Eltern**: Kindersicherheit existiert im Markt fast nur als Whitelist plus externe Microsoft-Family-Safety-Ebene; ElfHosted ist der einzige gefundene Anbieter mit Spielzeit-/Bedtime-Features im Panel. Gameworld sitzt in dieser Lücke.

### Table Stakes (Users Expect These)

Ohne diese wirkt das Produkt kaputt. Maßstab ist das Aternos-Erlebnis ("One-Click, kein Serverwissen"), nicht das Pterodactyl-Erlebnis.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Welt per One-Click erstellen (Spiel-Preset wählen) | Aternos/Minehut-Standard; Kernversprechen aus PROJECT.md | MEDIUM | Preset = Luanti-Game (Minetest Game, VoxeLibre) plus sinnvolle Defaults; keine Konfigfragen beim Anlegen |
| Start / Stop / Neustart mit sichtbarem Status | Jedes Panel und jeder Hoster hat das; Grundinteraktion | LOW | Status: läuft / gestoppt / startet; Fehlerzustand verständlich anzeigen |
| Statusanzeige: Spieler online, RAM-Verbrauch | Crafty/LuHost/Pelican zeigen alle Live-Status; Eltern wollen wissen "spielt da gerade jemand?" | MEDIUM | Spielerliste reicht; keine Grafana-artigen Dashboards nötig |
| Backup und Restore pro Welt | Crafty, LuHost, Supercraft, Pelican: überall vorhanden; Weltverlust ist der schlimmste anzunehmende Fall für Kinder | MEDIUM | In Gameworld nach Nextcloud Files (siehe Differentiators); Restore ist der kritische Teil, nicht das Backup |
| Zugriffskontrolle: nur Eingeladene können joinen | Produktkern laut PROJECT.md; Minecraft-Elternratgeber nennen Whitelist als DIE Schutzmaßnahme | HIGH | Luanti hat KEINE eingebaute Whitelist; Lösung über ContentDB-Whitelist-Mod oder provisionierte Spieler-Accounts (Luanti-Auth-DB) plus `default_privs`. Komplexeste Table-Stakes-Anforderung |
| Verbindungsinfo für Spieler ("So kommst du rein") | Aternos zeigt Adresse prominent; Kinder brauchen Adresse, Port, Spielername kopierfertig | LOW | Pro Kind eine simple Ansicht; idealerweise mit Schritt-für-Schritt-Anleitung für den Luanti-Client |
| Ressourcenlimits pro Welt (RAM/CPU) | Pelican/Pterodactyl-Standard; auf Heimservern Pflicht, sonst legt eine Welt die Nextcloud lahm | MEDIUM | Docker-Limits; Defaults konservativ setzen, Eltern müssen nichts einstellen |
| Einfache Welt-Einstellungen als Schalter | Eltern erwarten "Kreativ/Überleben", "Schaden an/aus", "Chat an/aus" ohne minetest.conf | MEDIUM | Achtung: Creative und Damage sind in Luanti getrennte Settings; PvP/Chat teils mod-abhängig. Wenige validierte Schalter statt Config-Editor |
| Mehrere Welten parallel | Crafty/LuHost können Multi-Server; Geschwister wollen eigene Welten | MEDIUM | Folgt fast gratis aus Container-pro-Welt plus Ressourcenlimits |

### Differentiators (Competitive Advantage)

Hier gewinnt Gameworld. Alle vier zahlen direkt auf den Core Value ein (privat, sicher, Daten zuhause, Eltern ohne Serverwissen).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Einladen über Nextcloud-Konten/-Gruppen | Kein Hoster kann das: keine neuen Accounts, keine E-Mail-Registrierung, Familie existiert schon in Nextcloud | MEDIUM-HIGH | NC-User wird auf Luanti-Spielername plus provisioniertes Passwort gemappt; Gruppe "Kinder" einladen = alle drin. Kernstück der Zugriffskontrolle |
| Eltern/Kind-Rollenmodell | Kinder spielen, verwalten nicht; kein Panel bietet das (alle haben nur Admin/Moderator-Rollen) | MEDIUM | Kind-Ansicht = eigene Welten plus Verbindungsinfo, sonst nichts; Eltern-Ansicht = Verwaltung. Rolle aus NC-Gruppenzugehörigkeit ableiten |
| Privat per Default, unsichtbar nach außen | Gegenentwurf zu Aternos/Minehut; `server_announce` bleibt aus, kein öffentliches Listing, kein Port offen ohne Einladung | LOW | Technisch billig (Config), aber als Garantie formulieren und testen; im UI gar keine "öffentlich machen"-Option anbieten |
| Weltsicherungen in Nextcloud Files | Backups liegen sichtbar im Familien-Cloudspeicher, mit NC-Versionierung, extern sicherbar; kein Panel integriert so | MEDIUM | Ordnerkonvention (z. B. Gameworld/Backups/Weltname); Restore aus Files-Auswahl; Welt vor Snapshot stoppen oder konsistent einfrieren |
| Kindgerechte Welt-Presets | "Kreativ ohne Schaden", "Abenteuer ohne PvP", "Chat aus": Elternentscheidungen statt Serversettings | MEDIUM | Preset = gebündelte, getestete Kombination aus Game, Settings, ggf. Mods; direkt beim Anlegen wählbar |
| Spielzeitlimits / Spielzeitfenster pro Kind | Größte Elternsorge laut allen Elternratgebern; nur ElfHosted bietet das überhaupt (Bedtime-Schedule) | MEDIUM-HIGH | Zwei Wege: ContentDB-Mod "Playtime Limit" (pro Spieler, aber umgehbar bei großem Check-Intervall) oder Serverstopp nach Zeitplan (grob, aber verlässlich). v1.x, nicht MVP |
| Aktivitäts-Benachrichtigungen an Eltern | "Welt gestartet", "Mia ist beigetreten" als NC-Notification; nutzt vorhandene Nextcloud-Kanäle (App, Mail, Handy) | MEDIUM | NC-Notifications-API aus ExApp; Events aus Serverlog/Luanti-Hooks ableiten. Transparenz statt Überwachung |
| Alles im Nextcloud-UI, ein Login | Kein separates Panel, keine zweite Domain, kein zweites Passwort; Familien-SSO inklusive | Inherent | Ergibt sich aus der ExApp-Architektur; im Marketing trotzdem explizit machen |
| Kuratierte Mod-Auswahl (Eltern wählen aus geprüfter Liste) | LuHost bietet rohen ContentDB-Browser; Gameworld bietet geprüfte, altersgerechte Auswahl | MEDIUM | v2; Kuratierung ist Pflegeaufwand. Bis dahin: Mods nur über Presets |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Öffentliche Serverliste / `server_announce` | "Mehr Mitspieler finden" | Zerstört das Kernversprechen; fremde Erwachsene auf dem Kinderserver; Moderationslast | Gar nicht als Option anbieten; Mitspieler kommen über NC-Einladungen |
| Werbung, Queues, Monetarisierung, Upsells | Finanziert Aternos/Minehut | Selfhosted braucht das nicht; genau der Grund, warum Familien zu Gameworld wechseln | Kostenlos und werbefrei als Positionierung festschreiben |
| Freier ContentDB-/Mod-Browser für alle Nutzer | LuHost/Panels haben es; "mehr Inhalte" | Kinder installieren Fremdcode; ungeprüfte Mods brechen Welten und Kindersicherheits-Presets | MVP: Mods nur in Presets; später kuratierte Liste, nur für Eltern sichtbar |
| Live-Konsole, RCON, Chat-Kommandos im UI | Jedes Admin-Panel hat es; Power-User fragen danach | Konsole = Vollzugriff; widerspricht "keine Admin-Zugänge für Kinder" und überfordert Eltern | UI-Schalter für alles Nötige; Notfall-Diagnose über Logs-Download, nicht über Live-Konsole |
| Dateimanager / Raw-Config-Editor im UI | Crafty/Pelican/LuHost-Standard | Fußwaffe für die Zielgruppe "Eltern ohne Serverwissen"; kaputte minetest.conf = Support-Fall | Validierte Formulare/Schalter; Weltdaten liegen ohnehin als Files/Backups greifbar |
| Multi-Node-Betrieb (Wings-artige Daemons) | Pterodactyl/Pelican-Architektur wirkt wie "richtig gemacht" | Massive Komplexität für ein Heimserver-Produkt mit genau einem Host | Ein Host, Container pro Welt, Ressourcenlimits |
| Eigene Benutzer-/Accountverwaltung | Jedes Panel baut eigene User-DB | Doppelte Identitäten, zweites Passwort, DSGVO-Fläche | Nextcloud-Konten sind die einzige Identität |
| Chat-Vollprotokollierung als "Elternfeature" | Klingt nach Kinderschutz | Überwachung statt Schutz; Privacy-Widerspruch zum Produktkern; rechtlich heikel | Chat per Preset abschaltbar; Schutz entsteht durch geschlossene, eingeladene Runde |
| Bedrock/Crossplay (Geyser), Versions-Matrix | Häufigste Hoster-Anfrage bei Minecraft | Anderes Protokoll, großer Testaufwand; laut PROJECT.md out of scope | Luanti-Client ist auf allen Plattformen frei; Minecraft Java erst MVP 2 |

## Feature Dependencies

```
[Container-Provisionierung pro Welt]
    └──requires──> [Ressourcenlimits (RAM/CPU)]
    └──enables───> [Mehrere Welten parallel]

[One-Click-Welt mit Preset]
    └──requires──> [Container-Provisionierung]
    └──requires──> [Welt-Settings-Verwaltung (minetest.conf generieren)]

[Einladen über NC-Konten/-Gruppen]
    └──requires──> [NC-User -> Luanti-Spieler-Mapping (Auth-Provisionierung)]
    └──requires──> [Zugriffskontrolle (Whitelist-Mod oder Account-only-Join)]

[Eltern/Kind-Rollenmodell]
    └──requires──> [NC-Gruppen-Auswertung]
    └──gates─────> [alle Verwaltungsfunktionen (nur Eltern)]

[Backup nach Nextcloud Files]
    └──requires──> [Start/Stop-Lebenszyklus (konsistenter Snapshot)]
    └──requires──> [Files-Zugriff der ExApp]

[Spielzeitlimits pro Kind]
    └──requires──> [NC-User -> Spieler-Mapping (wer ist welches Kind)]
    └──requires──> [Mod-Installations-Pipeline ODER Zeitplan-Scheduler]

[Aktivitäts-Benachrichtigungen]
    └──requires──> [Serverlog-/Event-Auswertung]
    └──enhances──> [Eltern/Kind-Rollenmodell]

[Kuratierte Mod-Auswahl]
    └──requires──> [Mod-Installations-Pipeline (ContentDB)]
    └──conflicts─> [Freier ContentDB-Browser]

[Auto-Stop bei Inaktivität] ──enhances──> [Ressourcenlimits]
```

### Dependency Notes

- **Einladungen benötigen das Auth-Mapping:** Luanti hat keine eingebaute Whitelist. Zugriffskontrolle entsteht erst durch die Kombination "Gameworld legt Luanti-Accounts für Eingeladene an (Auth-DB, Passwort) plus Whitelist-Mod blockt alle anderen". Das Mapping NC-User zu Spielername ist damit Fundament für Einladungen, Rollen UND Spielzeitlimits und gehört früh in die Roadmap.
- **Backups brauchen den Lebenszyklus:** Konsistente Weltsicherung setzt sauberes Stoppen (oder Pausieren) voraus; Backup-Phase nach der Lebenszyklus-Phase planen.
- **Spielzeitlimits haben zwei Implementierungspfade:** Mod-basiert (feingranular, pro Kind, aber mit bekannten Umgehungs-Caveats laut ContentDB-Seite) vs. Scheduler-basiert (Welt stoppt um 19 Uhr, grob aber verlässlich). Entscheidung in Phasen-Research, nicht im MVP.
- **Kuratierte Mods und freier Mod-Browser schließen sich aus:** Wer den rohen ContentDB-Browser einbaut, kann das Kuratierungs-Versprechen nicht mehr halten.

## MVP Definition

### Launch With (v1)

Minimum, um den Core Value zu validieren: "Elternteil ohne Serverwissen startet in Minuten eine private Welt, nur Eingeladene spielen."

- [ ] One-Click-Welt mit Preset (Minetest Game kreativ, VoxeLibre überleben-sanft), Start/Stop/Status, essenziell: das ist das Produkt
- [ ] Privat per Default (kein announce, kein öffentlicher Zugriff ohne Einladung), essenziell: das ist das Versprechen
- [ ] Einladen über NC-Konten/-Gruppen inkl. Auth-Provisionierung und Join-Sperre für Nicht-Eingeladene, essenziell: ohne das ist es nur ein weiteres Panel
- [ ] Eltern/Kind-Rollen (Kinder sehen nur Verbindungsinfo), essenziell: Kindersicherheits-Kern
- [ ] Verbindungsinfo-Ansicht pro Spieler, essenziell: sonst kommt kein Kind auf den Server
- [ ] Backup/Restore nach Nextcloud Files (manuell ausgelöst reicht), essenziell: Weltverlust ist Vertrauensverlust
- [ ] Ressourcenlimits pro Welt mit konservativen Defaults, essenziell: Heimserver-Stabilität
- [ ] ExApp-Installation über App Store (AppAPI, Docker-Deploy), essenziell: Distributionskanal

### Add After Validation (v1.x)

- [ ] Auto-Stop bei Inaktivität, Trigger: erste Rückmeldungen zu RAM-Druck auf Heimservern
- [ ] Zeitgesteuerte/automatische Backups, Trigger: manuelles Backup funktioniert zuverlässig
- [ ] Aktivitäts-Benachrichtigungen (NC Notifications), Trigger: Eltern fragen "spielt da gerade wer?"
- [ ] Spielzeitlimits/Spielzeitfenster, Trigger: explizite Eltern-Nachfrage; Pfad-Entscheid Mod vs. Scheduler per Phasen-Research
- [ ] Weitere Presets und Preset-Feinschalter (PvP, Chat, Schwierigkeitsgrad), Trigger: Feedback aus echten Familien

### Future Consideration (v2+)

- [ ] Kuratierte Mod-Auswahl für Eltern, Grund für Aufschub: Kuratierung ist laufender Pflegeaufwand, erst nach Produktvalidierung
- [ ] Minecraft Java via Crafty (MVP 2 laut PROJECT.md), Grund: EULA-Prüfung plus 8 bis 12 Tage Engine-Aufwand
- [ ] Vereins-/Gruppenbetrieb (Teckids, CoderDojo), Grund: braucht Mandanten-/Rollenmodell jenseits Familie
- [ ] Talk-Integration (Welt-Chat in Nextcloud Talk spiegeln o. ä.), Grund: nice to have, unklare Nachfrage

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| One-Click-Welt + Lebenszyklus | HIGH | MEDIUM | P1 |
| NC-Einladungen + Zugriffskontrolle | HIGH | HIGH | P1 |
| Privat per Default | HIGH | LOW | P1 |
| Eltern/Kind-Rollen | HIGH | MEDIUM | P1 |
| Backup/Restore nach Files | HIGH | MEDIUM | P1 |
| Ressourcenlimits | MEDIUM | MEDIUM | P1 |
| Verbindungsinfo-Ansicht | HIGH | LOW | P1 |
| Auto-Stop bei Inaktivität | MEDIUM | MEDIUM | P2 |
| Benachrichtigungen | MEDIUM | MEDIUM | P2 |
| Spielzeitlimits | HIGH | MEDIUM-HIGH | P2 |
| Kindgerechte Zusatz-Presets | MEDIUM | MEDIUM | P2 |
| Kuratierte Mods | MEDIUM | HIGH | P3 |
| Minecraft via Crafty | HIGH | HIGH | P3 (MVP 2) |

## Competitor Feature Analysis

| Feature | Aternos/Minehut | Pelican/Crafty/LuHost | Our Approach |
|---------|-----------------|------------------------|--------------|
| Welt anlegen | One-Click mit Software-Presets | Formular mit Eggs/Templates, Admin-Wissen nötig | One-Click mit kindgerechten Presets |
| Zugriff | Öffentlich erreichbar, optional Whitelist; Minehut-Lobby | Whitelist/Konfig manuell | Privat per Default, Zugriff nur über NC-Einladungen |
| Identität | Eigene Accounts (plus Mojang) | Eigene Panel-User-DB | Nextcloud-Konten, kein zweiter Login |
| Rollen | Betreiber vs. Spieler | Admin/Sub-User-Permissions (Pelican), Rollen (Crafty, LuHost) | Eltern verwalten, Kinder spielen; abgeleitet aus NC-Gruppen |
| Backups | Eingeschränkt/Cloud des Anbieters | Lokale Backups, Cron (Crafty), One-Click-Zip (LuHost) | Nach Nextcloud Files mit Versionierung, Restore im UI |
| Konsole/Dateien | Teilweise Konsole | Live-Konsole plus Dateimanager überall | Bewusst weggelassen; validierte Schalter statt Raw-Zugriff |
| Mods | Katalog-Installation (Aternos) | ContentDB-Browser (LuHost), Eggs (Pelican) | MVP nur Presets; später kuratierte Elternliste |
| Spielzeit/Elternkontrolle | Nichts | Nichts (nur ElfHosted als Nischen-Hoster mit Bedtime-Panel) | Kernfeature ab v1.x: Limits/Zeitfenster pro Kind |
| Finanzierung | Werbung, Queues, Upsells | Open Source, selfhosted | Kostenlos, werbefrei, Daten zuhause |

## Sources

- Pelican Panel Features: [Hostinger Pelican-Übersicht](https://www.hostinger.com/applications/pelican-panel), [DINAO Pelican](https://dinao.com/en/conteneur/pelican-panel), [selfhostyourself Pelican](https://www.selfhostyourself.com/services/pelican-panel), MEDIUM confidence (mehrere übereinstimmende Sekundärquellen)
- Crafty Controller: [Hostinger Crafty](https://www.hostinger.com/applications/crafty-controller), [selfhostyourself Crafty](https://selfhostyourself.com/services/crafty-controller), [Saltbox-Doku](https://docs.saltbox.dev/sandbox/apps/crafty), MEDIUM confidence
- Aternos/Minehut: [space-node Vergleich 2026](https://space-node.net/blog/aternos-vs-minehut-free-minecraft-hosting-2026), [itechguides Head-to-head](https://www.itechguides.com/best/free-minecraft-server-hosting/compare/aternos-vs-minehut/), [wisehosting Vergleich](https://wisehosting.com/blog/aternos-vs-minehut), MEDIUM confidence (Blogs, Kernaussagen deckungsgleich)
- LuHost: [README direkt gelesen](https://git.medlab.host/Modpol/LuHost/raw/branch/main/README.md), HIGH confidence
- Luanti-Hosting-Markt: [luanti.ch Hosting](https://luanti.ch/pages/hosting), [Supercraft Luanti](https://supercraft.host/luanti-server-hosting/), MEDIUM confidence
- Luanti-Mechaniken: [Offizielle Server-Setup-Doku (server_announce)](https://docs.luanti.org/for-server-hosts/setup/), [Privileges-Doku (default_privs, /grant)](https://docs.luanti.org/for-players/privileges/), [ContentDB Whitelist-Mod](https://content.luanti.org/packages/AntumDeluge/whitelist), [Luanti-Wiki Creative Mode (getrennt von Damage)](https://wiki.luanti.org/Creative_mode), HIGH confidence
- Spielzeitlimit: [ContentDB "Playtime Limit" (Linuxdirk), explizit "servers for kids", mit Umgehungs-Caveat](https://content.luanti.org/packages/Linuxdirk/playtime_limit/), HIGH confidence
- Kid-Safety-Markt: [ElfHosted Minecraft Parental Controls](https://docs.elfhosted.com/guides/families/minecraft-parental-controls/), [ESRB-Elternratgeber](https://esrb.org//blog/what-parents-need-to-know-about-minecraft/), [CodeWizardsHQ Parental Controls](https://www.codewizardshq.com/minecraft-parental-controls-what-every-parent-should-know/), MEDIUM confidence

---
*Feature research for: Kid-safe game-server portal (Gameworld)*
*Researched: 2026-10-19*
