# Steam-Spiele-Server über Gameworld: Lohnt sich das?

**Frage des Owners:** Lohnt sich ein Server für Steam-Spiele über Gameworld (Dedicated Server von Steam-Spielen, die die Familie selbst hostet)?
**Recherchiert:** 22.10.2026, Primärquellen live abgerufen (Firecrawl maxAge 0, WebFetch, Steam-/SteamCMD-/GitHub-APIs); kein Server gestartet, kein Docker
**Ergänzt:** `MINECRAFT-LIZENZ.md` (Struktur-Vorlage), `MINECRAFT-V2.md`, `WEITERE-SPIELE.md` (Engine-Abstraktion, Durchsetzungs-Muster)
**Keine Rechtsberatung.**

Konfidenz: **HIGH** = Wortlaut der Primärquelle trägt die Aussage direkt. **MEDIUM** = Primärquelle plus Auslegung, gelebte Praxis oder gute Sekundärquelle. **LOW** = Einzelquelle, Hoster-Blog, Schätzung oder unverifiziert.

Hinweis zu Altersfreigaben: "Steam-DE 12/16/18" ist keine USK-Prüfung, sondern die Steam-eigene Selbsteinstufung für Deutschland ("A game can have a rating issued by German self-rating body USK or it can have one issued by Valve through its own self-rating process.", https://partner.steamgames.com/doc/gettingstarted/contentsurvey/germany). USK-Werte aus IARC-Verfahren (Xbox/MS Store) stehen meist nicht in der USK-Titeldatenbank.

---

## Gesamturteil

| Teilfrage | Antwort | Konfidenz |
|---|---|---|
| Darf Gameworld SteamCMD beim Betreiber automatisch laden und Server anonym installieren? | **ja, mit Auflagen** (zur Laufzeit von Valves CDN, nur anonymer Login, nicht mitliefern) | MEDIUM (keine eigene SteamCMD-Lizenz, gelebte Praxis bei Pterodactyl/Pelican, LinuxGSM, AMP) |
| SteamCMD oder Server-Dateien ins Gameworld-Image packen | **nein** (SSA-Verbreitungsverbot, Spiel-EULAs, terraria.org-Bedingungen "mirror") | HIGH für Wortlaut, MEDIUM für SteamCMD selbst |
| Passt die Zielgruppe (Kinder, oft unter 13)? | **schlecht**: Steam-Konten erst ab 13; fast jedes Spiel verlangt ein gekauftes Exemplar pro Kind | HIGH |
| Passt die Heimserver-Hardware (4 bis 16 GB, x86 oder ARM)? | **nur für kleine Spiele** (Terraria, Factorio, Core Keeper, DST); Valheim knapp; Satisfactory, Palworld, Enshrouded zu schwer; SteamCMD nur x86-64 | HIGH (RAM-Angaben der Entwickler), MEDIUM (ARM) |
| Spielzeit-Kontrolle generisch per RCON-Kick? | **nein, kein generischer Weg**: RCON nur bei wenigen Spielen; je Spiel eigener Adapter (stdin, RCON, REST, Mod) | HIGH |
| Gibt es das schon in Nextcloud? | **nein** (0 von 897 Store-Apps) | HIGH |
| Lohnt sich das für einen Solo-Entwickler jetzt? | **lohnt sich nicht als nächster Schritt; höchstens später mit Auflagen und für 1 bis 2 ausgewählte Spiele, die gar kein SteamCMD brauchen** | MEDIUM (Bewertung) |

**Kurz:** Rechtlich machbar nach dem bekannten Muster (Laufzeit-Download beim Betreiber, nichts bündeln). Aber der Produktkern von Gameworld (Kinder unter 13, Eltern ohne Serverwissen, Spielzeit pro Kind, kleine Heimserver) kollidiert mit drei harten Fakten: Steam ab 13, Kaufpflicht pro Kind und uneinheitliche, oft fehlende Steuerbarkeit der Server. Valve liefert für Kinder ab 13 zudem selbst eine Spielzeit-Begrenzung (Steam Families), das nimmt Gameworld den Alleinstellungswert. Die zwei besten Kandidaten (Terraria, Factorio) laden ihren Linux-Server gar nicht über SteamCMD, sondern direkt vom Hersteller. "Steam-Server" ist daher der falsche Rahmen; richtig wäre "kaufpflichtige PC-Spiele mit Linux-Server", und auch das erst nach Minecraft.

---

## 1. SteamCMD: Lizenz, anonymer Login, Download, Bündeln

### Befund

**Steam Subscriber Agreement (SSA), Stand "last updated on September 10, 2026"** (HIGH)
https://store.steampowered.com/subscriber_agreement/
> "Except as otherwise permitted under this Agreement ..., you may not, in whole or in part, copy, photocopy, reproduce, publish, distribute, translate, reverse engineer, ... the Content and Services or any software accessed via Steam without the prior consent, in writing, of Valve."

> "You are entitled to use the Content and Services for your own personal use, but you are not entitled to: (i) sell, grant a security interest in or transfer reproductions of the Content and Services to other parties in any way, nor to rent, lease or license the Content and Services to others without the prior written consent of Valve, ... (ii) host or provide matchmaking services for the Content and Services or emulate or redirect the communication protocols used by Valve ... (iii) exploit the Content and Services or any of its parts for any commercial purpose"

**Server-Lizenz im SSA gilt nur für Valve-Spiele** (HIGH)
> "License to Use Valve Dedicated Server Software. Your Subscription(s) may contain access to the Valve Dedicated Server Software. If so, you may use the Valve Dedicated Server Software on an unlimited number of computers for the purpose of hosting online multiplayer games of Valve products."

Für Server von Fremdspielen (Valheim, Terraria, DST usw.) gilt also die EULA des jeweiligen Herstellers, nicht diese Klausel. (MEDIUM, Auslegung)

**SSA: Automation** (HIGH)
> "You may not use any form of scripts, bots, macros, or other non-human-controlled systems ("Automation") to interact with Content and Services on Steam in any manner, including but not limited to: Automating the Steam account creation process, Faking gameplay statistics ..., Earning rewards or progress without genuine user input, ..."

Die Beispiele zielen auf Konten, Statistiken und Belohnungen. Ein Skript, das per SteamCMD einen Server installiert, ist genau der Zweck von SteamCMD (siehe nächster Punkt). Dass die Automation-Klausel SteamCMD-Skripte nicht trifft, ist Auslegung. (MEDIUM)

**SteamCMD-Doku von Valve** (HIGH)
https://developer.valvesoftware.com/wiki/SteamCMD
> "To download most game servers, you can login anonymously using login anonymous"
> "Some servers require you to login with a Steam Account. Note: For security reasons, it is recommended that you create a new Steam account just for your dedicated servers."
> "If you get the "No subscription" error, the game/server you are trying to download either requires a login or that you have purchased the game."

Die Valve-Wiki-Seite verweist selbst auf das Docker-Image cm2network/steamcmd: "This image can be used as a base image for Steam-based dedicated servers." (HIGH, Wiki ist Community-bearbeitbar, steht aber auf Valves Domain)

**Steamworks-Doku für Entwickler: anonymer Server-Download ist ein bewusster Schalter des Herstellers** (HIGH)
https://partner.steamgames.com/doc/sdk/uploading/distributing_gs
Der Hersteller legt eine eigene App-ID vom Typ TOOL an, aktiviert "Include this tool in Dedicated Server package", damit der Server "to be downloadable using SteamCMD in anonymous mode" ist, "so that you don't need the Steam Client or a specific Steam user to be signed in to run it." Zu Drittanbieter-Hostern und Lizenzen sagt die Seite nichts.

**SteamCMD hat keine eigene Lizenzdatei.** Das Archiv `https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz` enthält nur `steamcmd.sh`, `linux32/steamcmd`, `steamerrorreporter`, `libstdc++.so.6`, `crashhandler.so` (geprüft 22.10.2026, Dateien von 2018, 2,4 MB). Eine gesonderte SteamCMD-Lizenz oder Weitergabeerlaubnis habe ich bei Valve nicht gefunden. (HIGH für den Befund, Folgerung: es gilt das SSA)

**Architektur:** SteamCMD gibt es nur für x86 (32-bit-Binary, braucht `lib32gcc-s1`, laut Valve-Wiki). Für ARM64 gibt es nur Community-Images mit Box86/Box64-Emulation (https://hub.docker.com/r/sonroyaalmerol/steamcmd-arm64); eine offizielle ARM-Version habe ich nicht gefunden. (HIGH für x86-Paket, MEDIUM für "kein ARM")

### Gelebte Praxis

| Projekt | Muster | Quelle | Konfidenz |
|---|---|---|---|
| Pterodactyl/Pelican-Eggs (`pelican-eggs/games-steamcmd`, über 100 Spiele) | Install-Container `ghcr.io/parkervcp/installers:debian` lädt SteamCMD zur Installationszeit von Valves CDN und installiert anonym: `curl -sSL -o steamcmd.tar.gz https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz` ... `./steamcmd.sh +force_install_dir /mnt/server +login ${STEAM_USER} ...`; Kommentar im Skript: "Leave blank for anon install." Laufzeit-Image enthält keine Spieldateien. | https://github.com/pelican-eggs/games-steamcmd , Egg `valheim/valheim_vanilla/egg-pterodactyl-valheim.json` (gelesen 22.10.2026) | HIGH |
| LinuxGSM | MIT, Bash, "143 game servers are supported"; "LinuxGSM integrates seamlessly with SteamCMD leaving no requirement for you to manage it." | https://linuxgsm.com/ | HIGH |
| cm2network/steamcmd | "Minimal image containing Valve's SteamCMD binary", MIT (für das Dockerfile), 1,51 Mio. Pulls, letztes Update 08.06.2026. Bündelt also SteamCMD selbst im Image, ohne schriftliche Valve-Erlaubnis gefunden zu haben. | https://github.com/CM2Walki/steamcmd , https://hub.docker.com/v2/repositories/cm2network/steamcmd/ | HIGH für Inhalt, MEDIUM für "geduldet" |
| CubeCoders AMP (kommerziell) | Lizenz 20 bzw. 40 USD einmalig, "supports dozens of game servers", "generic module" | https://cubecoders.com/AMP | HIGH |
| Community-Images Valheim, Satisfactory, DST, Core Keeper | laden die Server-Dateien zur Laufzeit per SteamCMD; Valheim-Image: "the container will download the Valheim dedicated server from Steam" | https://github.com/community-valheim-tools/valheim-server-docker | HIGH |
| Ausnahmen, die Server-Dateien ins Image backen | ryansheehan/terraria (`ADD $DL_LINK`), factoriotools/factorio (curl im Dockerfile) | GitHub-Repos | HIGH für Befund |

### Auslegung

- **Laufzeit-Download beim Betreiber** ist das etablierte Muster und vermeidet eigene Weitergabe: SteamCMD kommt von Valves CDN, die Server-Dateien vom Steam-Content-System, beides auf der Maschine der Familie. Keine Valve-Quelle erlaubt Drittpanels das ausdrücklich; die jahrelange Praxis (Pterodactyl, LinuxGSM, AMP, Nitrado) ist ein Indiz, kein Recht. (MEDIUM)
- **Nicht ins Image:** weder SteamCMD noch Server-Dateien in Gameworld-Images, Registries oder zentrale Backups. Das cm2network-Image als Basis zu ziehen hieße, ein Image zu nutzen, das SteamCMD bündelt; sauberer ist das Pelican-Muster (eigenes schlankes Image, SteamCMD-Download im Installationsschritt). (HIGH Verbot für Spieldateien, MEDIUM für SteamCMD)
- **Nur anonymer Login.** Gameworld darf nie Steam-Zugangsdaten der Eltern abfragen oder speichern: Steam Guard/2FA bricht die Automatik (Egg-Kommentar: "If a user has 2fa enabled it will most likely fail due to timeout"), ein Konto ist nur einmal gleichzeitig angemeldet (Valve-Wiki: "A user can only be logged in once at any time"), und gespeicherte Passwörter wären ein Kontoübernahme-Risiko. Folge: alle Spiele ohne anonymen Server-Download (Stardew Valley, Terraria über Steam, tModLoader über SteamCMD, Unturned laut Valve-Liste) fallen für SteamCMD weg. (HIGH Fakten, MEDIUM Folgerung)
- **Kein Matchmaking-Dienst:** Gameworld betreibt keinen eigenen Master-Server und emuliert keine Valve-Protokolle (SSA (ii)). Ein Familienserver, der über Steams eigene Infrastruktur läuft, ist davon nicht betroffen. (MEDIUM)

## 2. Kandidaten-Spiele

### Vergleichstabelle

Spielerzahlen: steamcharts.com, 24h-Peak / All-Time-Peak, abgerufen 22.10.2026. "anonym" = SteamCMD `+login anonymous` (FreeToDownload laut steamdb.info bzw. api.steamcmd.net). RAM = Entwicklerangabe, sonst markiert.

| Spiel | Linux-Server | Download | RAM Server | Plattenbedarf | USK / PEGI | Zugangsschutz | Steuerung für Spielzeit | Spieler-Kauf nötig | Steam 24h / All-Time | Kinder-Fit |
|---|---|---|---|---|---|---|---|---|---|---|
| **Terraria** | ja | Direkt-Zip von terraria.org, ohne Login (Steam-App nicht anonym) | k. A. (nicht verifiziert) | Spiel-Depot 792 MiB (Server kleiner, n. v.) | USK 6 (Konsolen), PEGI 12 | Passwort, Banliste; keine Whitelist | stdin `kick`; TShock-REST mit Spielerliste und Kick | ja (Steam oder GOG, GOG-Crossplay n. v.) | 45.681 / 486.918 | **gut** |
| **Factorio** | ja | Direkt von factorio.com, ohne Login | k. A. | k. A. | keine DE/EU-Freigabe gefunden | Passwort, **Whitelist**, Ban-/Adminliste | **natives RCON**, `/kick`, `/players`, Lua-Mods | ja, aber kein Steam nötig (factorio.com-Konto) | 18.220 / 118.166 | gut ab ca. 10 (Bewertung, LOW) |
| **Don't Starve Together** | ja | SteamCMD 343050, anonym | k. A. | 4,08 GiB | USK 12, PEGI 12 | Cluster-Token des Betreibers, **Whitelist** (Klei-IDs, Bug laut Wiki) | Lua über stdin (`-console`): Spielerliste, `TheNet:Kick` | ja (Steam/Humble) | 46.006 / 121.538 | mittel (Grusel-Optik) |
| **Core Keeper** | ja | SteamCMD 1963720, anonym (README-Zitat, MEDIUM-HIGH) | k. A. | ca. 1 GiB | USK 12 (Switch 2), PEGI 7 | Game-ID bzw. Passwort; keine Whitelist | keine Konsole, kein RCON (LOW-MEDIUM) | ja (Steam/Epic/GOG/MS Store) | 10.997 / 46.355 | **gut**, aber nicht steuerbar |
| **Valheim** | ja (Valve-Liste falsch) | SteamCMD 896660, anonym | k. A.; Community: 4 GB min., 8 GB empf., 2,8 GB RSS idle (MEDIUM) | 1,93 GiB | **USK 16** (IARC), PEGI 12 | Passwort, `permittedlist.txt` (Platform-IDs) | Kick nur in-game; kein RCON; nur per BepInEx-Mod | ja | 100.234 / 498.478 | eingeschränkt (USK 16) |
| **Satisfactory** | ja | SteamCMD 1690800, anonym | **8 GB min., 16 GB** bei großen Saves/>4 Spielern | ca. 8 GB | USK 12, PEGI 12 | Admin-Claim, optional Passwort; keine Whitelist | HTTPS-API ohne Kick und ohne Spielerliste | ja (Steam/Epic) | 20.864 / 185.957 | gut, aber zu schwer |
| **Palworld** | ja, offizielles Docker-Image | SteamCMD 2394010, anonym | **16 GB** ("8GB is also bootable, but increases the possibility of server crashes") | ca. 4,8 GB | keine USK/PEGI gefunden, Steam-DE 12 | Server-Passwort; keine Whitelist gefunden | **REST-API** mit `/players` und `/kick`; RCON deprecated | ja | 53.487 / 2.101.535 | mittel, zu schwer |
| **Enshrouded** | **nein**, nur Windows (Wine) | SteamCMD 2278520, anonym | 4,4 GB idle, bis 6 GB | ca. 13 GB, 30 GB frei | USK 12, PEGI 12 | Gruppen-Passwörter (MEDIUM) | kein RCON/REST gefunden | ja | 84.316 / 160.361 | gut, technisch aus |
| **Stardew Valley** | **kein Dedicated Server** | nur Vollspiel mit Steam-Login (JunimoServer) | k. A. | k. A. | USK 6, PEGI 12 | Vanilla nichts | nur SMAPI-Mods | ja (Steam oder GOG) | 83.456 / 236.614 | sehr gut, technisch aus |
| **Astroneer** | nein, nur Windows | SteamCMD 728470, anonym | k. A. | ca. 2,6 GB | USK 0 (Switch), PEGI 7 | offiziell nur Owner | nicht dokumentiert | ja | 1.678 / 17.891 | sehr gut, technisch aus |
| **V Rising** | nein, nur Windows | SteamCMD 1829350, anonym | k. A. | ca. 2 GB | USK 16 (Store-Feld), PEGI 12 | Passwort, Admin-/Banliste | RCON ohne Kick | ja | 3.802 / 150.645 | nein |
| **Raft** | kein offizieller Server | entfällt | entfällt | entfällt | Steam-DE 12 | entfällt | entfällt | ja | 9.500 / 100.474 | aus |
| **7 Days to Die** | ja | SteamCMD 294420 | k. A. | ca. 17,7 GB | USK 16 (Konsole), PEGI 18, Steam-DE 18 | Passwort, Whitelist | Telnet: Kick, Spielerliste | ja | 29.052 / 124.449 | **nein** (Zombie-Horror) |
| **Unturned** | ja | SteamCMD 1110390 (anonym laut steamcmd-API; Valve-Liste sagt nein) | k. A. | ca. 1,8 GB | Steam-DE 16 | Passwort, Owner, `/permit` | Konsole, Plugins (RocketMod/OpenMod) | nein (Free-to-Play, In-App-Käufe) | 13.176 / 112.648 | nein |
| **Garry's Mod** | ja | SteamCMD 4020, anonym | k. A. | ca. 7 GB | Steam-DE 16 | `sv_password` | Source-RCON, Lua | ja | 28.267 / 73.750 | nein (unmoderierter Workshop) |
| **Sons of the Forest** | nein, nur Windows | SteamCMD 2465200 | k. A. | ca. 3,4 GB | Steam-DE 18 | Passwort | nur in-game | ja | 10.354 / 411.804 | **nein** |
| Vintage Story (kein Steam) | ja, auch ARM | Direkt-CDN ohne Login | 1 GB + 300 MB/Spieler | 51 MB Archiv | keine Freigabe; ToS "13 or older" | Passwort, **Whitelist ab Werk** | `/kick`, C#-Mods | ja (eigener Account) | nicht auf Steam | mittel (Horror-Elemente) |
| Hytale (kein Steam, Early Access seit 13.01.2026) | ja, Java 25, auch ARM | Downloader mit OAuth2-Login | min. 4 GB | k. A. | keine Freigabe gefunden | `whitelist.json` | Java-Plugins | Kauf über hytale.com | nicht auf Steam | offen |

### Quellen je Spiel (Auswahl, alle abgerufen 22.10.2026)

**Terraria**
- Server-Download: https://terraria.org/api/download/pc-dedicated-server/terraria-server-1458.zip (Version 1.4.5.8), Namensliste https://terraria.org/api/get/dedicated-servers-names (HIGH)
- Wiki: "For running on a Linux distribution, you must download the server files." https://terraria.wiki.gg/wiki/Server (HIGH); Konsolenbefehle `kick`, `ban`, `password` ebd.
- **Lizenz** (Website-Bedingungen, gelten für den Server-Download), https://terraria.org/terms (HIGH):
  > "Permission is granted to temporarily download one copy of the materials (information or software) on Terraria's web site for personal, non-commercial transitory viewing only. ... you may not: modify or copy the materials; use the materials for any commercial purpose ... or transfer the materials to another person or "mirror" the materials on any other server."
  Folge: privat hosten unkritisch; Zip ins Gameworld-Image oder einen Spiegel packen widerspricht dem Wortlaut. Laufzeit-Download beim Betreiber ist der einzige saubere Weg. Eine eigene Spiel-EULA von Re-Logic habe ich nicht gefunden. (HIGH Wortlaut, MEDIUM Folgerung)
- tModLoader: MIT, SteamCMD-Weg laut offiziellem Wiki nur mit Steam-Login, Alternative `install --github` ohne Login (https://github.com/tModLoader/tModLoader/wiki/Starting-a-modded-server) (HIGH)
- TShock: REST-API mit Token, Spielerliste, Kick (https://tshock.readme.io/reference/rest-api-endpoints; Doku älterer Version, für 6.x nicht neu geprüft) (MEDIUM)
- Freigaben: https://usk.de/?s=Terraria (USK 6, Konsolen), https://pegi.info/search-pegi?q=Terraria (PEGI 12) (HIGH); PC-Freigabe nicht verifiziert

**Factorio**
- Download: https://www.factorio.com/download ("it is free to download", stable 2.0.77), `https://www.factorio.com/get-download/<version>/headless/linux64` (HIGH)
- **Lizenz**, https://www.factorio.com/terms-of-service (HIGH):
  > "You may use the free Factorio headless server to run and operate a commercial service providing servers to players. However we reserve the right to request the cessation of the service should an issue with the service provider arise."
  > "You are not allowed to copy, transfer or distribute the game, its hacked or otherwise altered versions, any of its parts or any of the paid content."
  Hosten ist ausdrücklich erlaubt, sogar kommerziell. Ob der kostenlose Headless-Server zu "any of its parts" zählt, ist offen; daher auch hier nur Laufzeit-Download. (MEDIUM)
- Whitelist, RCON, Kick: https://wiki.factorio.com/Command_line_parameters , https://wiki.factorio.com/Console (HIGH)
- Versionskopplung: "All game instances need the installation of exactly the same game-versions and mods." https://wiki.factorio.com/Multiplayer (HIGH)

**Don't Starve Together**
- "Klei ... only provides builds of dedicated server for Windows and Linux, both x86 and x86_64" https://dontstarve.wiki.gg/wiki/Guides/Don%E2%80%99t_Starve_Together_Dedicated_Servers (HIGH); Cluster-Token: "A cluster token proves ownership of Don't Starve Together" (ebd.)
- **Lizenz**, https://store.steampowered.com/eula/322330_eula_0 (HIGH):
  > "you must not otherwise copy, reproduce, republish, post, transmit ... distribute ... any other portion of the Game without our prior written approval"
  > "you must have a Steam or Humble account to access, download, and play the Game"
- Freigaben: https://usk.de/?s=Don%27t+Starve (USK 12, Xbox One) (HIGH)

**Valheim**
- Linux-Server laut offiziellem Guide (`start_server.sh`), `permittedlist.txt`: "adding a person on the permitted list will ban everyone else" https://www.valheim.com/support/a-guide-to-dedicated-servers/ (HIGH)
- Depot 896661 Linux, FreeToDownload: https://steamdb.info/app/896660/depots/ (HIGH). Die Valve-Liste ("nur Windows") ist hier falsch.
- **Lizenz**, Coffee Stain EULA vom 11.06.2025, https://valheim.com/eula/ (HIGH):
  > "license to use one copy of the Game for your personal, non-commercial use for gameplay"
  > 5.2.1 "do not share, rent, resell, or make available copies of the Game ..."
- USK 16 (IARC): https://apps.microsoft.com/detail/9ncbl78cg9n7?hl=de-DE&gl=DE ; PEGI 12: https://www.xbox.com/en-GB/games/store/valheim/9ncbl78cg9n7 (HIGH)

**Satisfactory**: RAM, Platte, Linux x64 ohne ARM: https://satisfactory.wiki.gg/wiki/Dedicated_servers (HIGH); API ohne Kick/Spielerliste: https://github.com/wolveix/satisfactory-server/wiki/Official-API-Docs (HIGH); Konsolen können nicht auf Dedicated Server: https://satisfactory.wiki.gg/wiki/Console_release (HIGH)

**Palworld**: https://docs.palworldgame.com/getting-started/requirements (RAM), https://docs.palworldgame.com/api/rest-api/palwold-rest-api ("not designed to be exposed directly to the Internet"), https://docs.palworldgame.com/api/rcon/ ("RCON is now deprecated"), offizielles Image https://github.com/pocketpairjp/palworld-dedicated-server-docker (HIGH)

**Enshrouded**: "In idle state the server process uses ~4.4GB of physical RAM ... The uncompressed server files are currently ~13GB" https://enshrouded.zendesk.com/hc/en-us/articles/16056312924957-Dedicated-Server-FAQ (HIGH)

**Core Keeper**: https://steamdb.info/app/1963720/depots/ (Linux-Depot) (HIGH); anonymer Login per README-Zitat https://steamcommunity.com/app/1621690/discussions/0/3275817873363439916/ (MEDIUM-HIGH); https://usk.de/?s=Core+Keeper , https://pegi.info/search-pegi?q=Core+Keeper (HIGH)

**Stardew Valley**: "If the host isn't online ... farmhands can't access the world" https://stardewvalleywiki.com/Multiplayer (HIGH); JunimoServer braucht "A Steam account that owns Stardew Valley" https://github.com/stardew-valley-dedicated-server/server (HIGH)

**Übrige**: V Rising "At the moment there is only a Windows version of the server available." https://github.com/StunlockStudios/vrising-dedicated-server-instructions/blob/master/1.1.x-pc/INSTRUCTIONS.md ; Astroneer https://astroneer.space/dedicatedserver/ ; 7 Days to Die https://7daystodie.com/crossplay-server-requirements/ , EULA https://store.steampowered.com/eula/251570_eula_0 ; Unturned https://docs.smartlydressedgames.com/en/stable/servers/server-hosting.html ; Garry's Mod https://wiki.facepunch.com/gmod/Downloading_a_Dedicated_Server ; Vintage Story https://wiki.vintagestory.at/Guide:Dedicated_Server ; Hytale https://support.hytale.com/hc/en-us/articles/45326769420827-Hytale-Server-Manual , https://hytale.com/eula (alle HIGH für die zitierten Fakten; Einzelheiten siehe Tabelle)

## 3. Kindersicherheit

### Befund

**Steam ab 13** (HIGH)
https://store.steampowered.com/subscriber_agreement/ und https://store.steampowered.com/join/
> "You may not become a Subscriber if you are under the age of 13."
> "Steam is not intended for children under 13 and Valve will not knowingly collect personal information" (Satz geht weiter)
Checkbox bei der Registrierung: "I am 13 years of age or older and agree to the terms of the Steam Subscriber Agreement". Für Nutzer unter 16 verlangt Steam in Deutschland die Zustimmung der Eltern: "requires parental consent for users within your country under the age of 16." (HIGH)

**Steam Families liefert eigene Spielzeit-Kontrolle** (HIGH)
https://store.steampowered.com/news/app/593110/view/4605582245626919823 (Ankündigung 11.09.2024)
> "Parental control features let adults: Allow access to appropriate games; Restrict access to the Steam Store, Community or Friends Chat; Set playtime limits (hourly/daily); View playtime reports; Approve or deny requests from child accounts for additional playtime or feature access"
https://help.steampowered.com/en/faqs/view/054C-3167-DD7F-49D4
> "Steam Families can contain up to 6 family members."
> "Child accounts in Steam Families are meant for accounts that parents or guardians create for their children to use."

**Kinder unter 13:** Valve hat dafür keinen Weg. Ein Community-Beitrag in der offiziellen Steam-Families-Gruppe: "Children under 13 can't have their own account." (https://steamcommunity.com/groups/steamfamilies/discussions/0/4290314417248495532/, LOW, keine Valve-Aussage). In der Praxis spielen jüngere Kinder auf dem Konto eines Elternteils; dann gelten weder Kinderkonto-Kontrollen noch eine Zuordnung Kind zu Steam-ID. (MEDIUM, Auslegung)

**Was Steam nicht steuert:** Die Familien-Kontrollen beschränken Steam-Chat, Store und Community, nicht den Chat innerhalb eines Spiels auf einem fremden oder eigenen Server. In-Game-Chat hängt vom Spiel ab; keines der Top-Kandidaten hat eine eingebaute Chat-Moderation, die ich verifizieren konnte (nicht verifiziert). (MEDIUM)

**Zugangsschutz der Server** (aus Abschnitt 2): echte Allowlist pro Spieler nur bei Factorio (Benutzername), DST (Klei-ID), Valheim (`permittedlist.txt`, Platform-ID), 7 Days to Die, Vintage Story, Hytale. Terraria, Core Keeper, Satisfactory, Palworld, Enshrouded kennen nur ein gemeinsames Passwort. (HIGH je Quelle)

**Mitspieler von außerhalb:** Viele Spiele melden sich standardmäßig in Steams öffentlicher Serverliste an (Pelican-Egg Valheim: `PUBLIC_SERVER=1`, `PASSWORD=secret` als Vorgabe) und bieten Relay/Join-Codes (Valheim Crossplay, Core Keeper Game-ID). Crossplay öffnet den Server für Xbox-/PS-Konten (Palworld, Valheim, 7DTD). Gameworld müsste Listung und Crossplay pro Spiel fest abschalten. (HIGH für Egg-Vorgaben, MEDIUM für Folgerung)

### Auslegung
- Gameworlds Kernversprechen "nur eingeladene Nextcloud-Konten spielen" lässt sich bei Spielen ohne Allowlist nur über ein gemeinsames Passwort annähern; Passwörter wandern unter Kindern weiter. Für Terraria wäre TShock (eigene Konten/Whitelist) der Weg, das ist aber Modding mit eigener Pflege. (MEDIUM)
- Zuordnung Nextcloud-Konto zu Spieler braucht wie bei Mindustry/OpenTTD einen Kopplungscode-Flow (Steam-ID, Klei-ID, Factorio-Name). Steam-IDs sind personenbezogene Daten; privacy.md müsste das nennen. (MEDIUM)
- Für Kinder ab 13 mit Steam-Kinderkonto bietet Valve bereits Spielzeit-Limits über alle Steam-Spiele. Gameworlds Spielzeit-Kontrolle wäre dort doppelt und schwächer (nur auf dem eigenen Server). (HIGH Fakten, MEDIUM Bewertung)

## 4. Technische Hürden in Gameworld

| Hürde | Befund | Folge für Gameworld | Konfidenz |
|---|---|---|---|
| Architektur | SteamCMD nur x86 (32-bit-Binary); ARM nur per Box86/Box64-Emulation | Raspberry Pi und ARM-Boxen ausgeschlossen (Luanti läuft dort) | HIGH / MEDIUM |
| RAM | Valheim 2,8 GB idle (Community), Enshrouded 4,4 bis 6 GB, Satisfactory 8 bis 16 GB, Palworld 16 GB | Auf 4 bis 8 GB neben Nextcloud nur Terraria, Factorio, Core Keeper, DST realistisch (deren RAM ungeprüft, Spike nötig) | HIGH (Entwicklerwerte) |
| Platte | 0,5 GB (Core Keeper) bis 17,7 GB (7DTD), Enshrouded 30 GB frei | Eigenes Volume pro Spiel, Plattenprüfung vor Installation, Fortschrittsanzeige (Download dauert Minuten) | HIGH |
| Ports | je Spiel verschieden, oft mehrere UDP plus Query-Port (z. B. Valheim Port bis Port+2), teils TCP (Factorio RCON, Palworld REST); RCON/REST darf nie nach außen | Portmodell muss von "1 UDP-Port pro Welt" (heute `30000-30019`) auf Port-Sets je Spiel wachsen; Admin-Ports nur im internen Docker-Netz | MEDIUM |
| Updates | Steam-Clients aktualisieren automatisch; Factorio verlangt "exactly the same game-versions"; Community-Images updaten bei jedem Start (Satisfactory `SKIPUPDATE`, Valheim alle 15 min ohne Spieler) | Widerspricht Gameworlds Versions-Pin-Strategie: Server muss Client-Updates zeitnah folgen, also `app_update` beim Start bzw. regelmäßig. Updates kommen damit ungeprüft vom Hersteller | HIGH |
| Docker-Socket-Proxy | Heute CONTAINERS, IMAGES, VOLUMES, POST. Ein schlankes Basis-Image plus Install-Container reicht | keine neuen Proxy-Rechte nötig (Bewertung); Install-Container braucht Internet, Laufzeit-Container für Steam-Auth ebenfalls | MEDIUM |
| Windows-only-Server | Enshrouded, V Rising, Astroneer, Sons of the Forest, Abiotic Factor nur per Wine/Proton | nicht unterstützen: fragil, RAM-hungrig, schwer zu debuggen | HIGH Befund, MEDIUM Bewertung |
| Spielzeit-Durchsetzung ohne eigenen Mod | RCON nur Factorio, Garry's Mod, V Rising (ohne Kick); REST Palworld, Satisfactory (ohne Kick); stdin Terraria, DST; gar nichts von außen Valheim (ohne BepInEx), Core Keeper | **Kein generischer RCON-Weg.** Je Spiel ein Adapter (Agent im Container, der stdin/RCON/REST bedient), wie in WEITERE-SPIELE.md B.3 beschrieben. Warnungen 10/5/1 min nur, wo das Spiel Servernachrichten kann (Factorio, DST `c_announce`, Terraria `say` n. v., Palworld `announce`). Notlösung für nicht steuerbare Spiele: Server zur Zeitgrenze stoppen (trifft alle Spieler, nicht nur ein Kind) | HIGH Fakten, MEDIUM Folgerung |
| Datenfluss | Steam-Server sprechen mit Valve (Download, Auth, Serverliste); DST mit Klei; Factorio optional mit factorio.com | Store-Text und privacy.md müssen das nennen (Nextcloud-Regel "Respect the users", siehe MINECRAFT-LIZENZ.md 8) | MEDIUM |
| Betreiber-Schritte | DST braucht ein Cluster-Token vom Klei-Konto des Betreibers; Satisfactory muss im Spiel "geclaimt" werden; Palworld-Konsolen-Crossplay nur als "Community Server" | Jedes Spiel bringt eigene Handgriffe mit, die Eltern ohne Serverwissen überfordern können | HIGH |

## 5. Konkurrenz und Nachfrage

### Befund

| Produkt | Stand 22.10.2026 | Quelle | Konfidenz |
|---|---|---|---|
| Pterodactyl | **aktiv**: v1.15.2 vom 21.10.2026, v2.0.0-beta.2 vom 14.10.2026, MIT; Docker pro Server, Eggs für Steam-Spiele | https://api.github.com/repos/pterodactyl/panel/releases , https://github.com/pterodactyl/panel | HIGH |
| Pelican (Pterodactyl-Fork) | v1.0.0-rc.1 vom 10.10.2026, noch kein Stable | https://api.github.com/repos/pelican-dev/panel/releases | HIGH |
| CubeCoders AMP | 20 USD (15 Instanzen) bzw. 40 USD (50 Instanzen) einmalig, Windows und Linux | https://cubecoders.com/AMP | HIGH |
| LinuxGSM | 143 Spiele, MIT, CLI | https://linuxgsm.com/ | HIGH |
| Crafty Controller, Kubek | nur Minecraft (Kubek: "A self-hosted control panel for Minecraft servers", GPL-3.0) | https://github.com/Seeroy/kubek-minecraft-dashboard | HIGH |
| Games on Whales (Wolf) | Spiele-Streaming ("Stream multiple virtual desktops and games running in Docker!"), keine Dedicated Server | https://games-on-whales.github.io/ | HIGH |
| Nitrado (Miete) | Valheim-Server "Starting from $4.09", Laufzeit/Konditionen auf der Seite nicht eindeutig | https://server.nitrado.net/en-US/offers/valheim | LOW |
| Nextcloud App Store | **keine** Gameserver-App unter 897 Apps (API-Abzug, Suche nach game server, dedicated server, steam, minecraft, luanti, valheim, terraria, pterodactyl) | https://apps.nextcloud.com/api/v1/apps.json | HIGH |

**Nachfrage-Signale** (LOW bis MEDIUM): r/selfhosted und r/HomeServer haben wiederkehrende Fragen nach einer Verwaltung für mehrere Spieleserver ("I plan to use it to host servers for games like Minecraft, Valheim, Terraria", https://www.reddit.com/r/selfhosted/comments/1q92qn1/games_server/; https://www.reddit.com/r/HomeServer/comments/1h9psgh/is_there_a_program_that_allows_you_to_manage_all/; https://www.reddit.com/r/selfhosted/comments/1s8zprs/guide_for_hosting_game_servers/). Diese Fragen kommen von technisch versierten Erwachsenen, die Pterodactyl, AMP oder LinuxGSM empfohlen bekommen; einen Thread, der ausdrücklich Kinder plus Steam-Server plus Elternkontrolle sucht, habe ich nicht gefunden (Suche nicht erschöpfend).

### Auslegung
- Für Erwachsene mit Homelab ist der Markt mit Pterodactyl/Pelican, AMP (20 USD) und LinuxGSM gut bedient; Gameworld hätte dort keinen Vorteil außer "läuft in Nextcloud". (MEDIUM)
- Gameworlds Nische ist Kindersicherheit plus Elternbedienung. Genau diese Nische passt zu Steam schlecht (ab 13, eigene Familien-Kontrollen von Valve). (MEDIUM)
- Korrektur für `CLAUDE.md`/STACK.md: Dort steht "Pterodactyl: Maintenance-Mode". Das stimmt nicht mehr; das Projekt veröffentlicht wieder (v1.15.2, v2-Beta). An der Entscheidung gegen Pterodactyl als Abhängigkeit ändert das nichts. (HIGH Befund)

## 6. Passung zu Gameworld und zum Solo-Entwickler

### Bewertung

| Kriterium | Steam-Spiele allgemein | Luanti (heute) | Minecraft (v2-Plan) |
|---|---|---|---|
| Kinder unter 13 | Steam-Konto verboten, meist Kauf je Kind | frei, kein Konto | Microsoft-Kinderkonto möglich, Kauf je Kind |
| Kosten für Familie | 10 bis 44 EUR pro Kind und Spiel | 0 | Java-Lizenz je Kind |
| Zugang pro Kind | nur bei wenigen Spielen | eigener Mod, voll | Whitelist + Plugin |
| Spielzeit pro Kind | je Spiel eigener Adapter, teils unmöglich | eigener Mod, voll | Paper-Plugin |
| Heimserver 4 bis 8 GB | nur kleine Spiele | ja | ja mit Limits |
| Versionspin | nicht durchhaltbar (Auto-Update-Clients) | ja | ja |
| ARM | nein (SteamCMD) | ja | ja |

### Beste Kandidaten, falls es doch kommt

1. **Terraria (Vanilla, später optional TShock)**: USK 6 / PEGI 12, gewaltarm im Vergleich, sehr beliebt (45.681 Spieler im 24h-Peak), Linux-Server als kleines Zip ohne Login, Kick über stdin. Schwächen: keine Whitelist (nur Passwort), Lizenz verbietet Spiegeln (nur Laufzeit-Download), RAM ungeprüft, Kauf pro Kind. (MEDIUM)
2. **Factorio**: technisch der beste Fall (Whitelist, RCON, `/kick`, `/players`, Servernachrichten, Lua), Hosting in den ToS ausdrücklich erlaubt, kein Steam-Konto nötig, also auch für Kinder unter 13 über ein factorio.com-Konto der Eltern denkbar. Schwächen: komplex, eher ab 10, keine deutsche Freigabe gefunden, exakte Versionsgleichheit. (MEDIUM)
3. **Don't Starve Together** (alternativ Core Keeper): DST hat Whitelist und Lua-Konsole über stdin, USK 12; Schwäche: Cluster-Token vom Klei-Konto der Eltern, Grusel-Optik, Steam/Humble-Pflicht. Core Keeper ist kindgerechter (PEGI 7) und klein, aber ohne Whitelist und ohne Fernsteuerung, verletzt damit Gameworlds Kernversprechen. (MEDIUM)

Bemerkenswert: Kandidat 1 und 2 brauchen **kein SteamCMD**. Ein SteamCMD-Unterbau lohnt sich erst ab Kandidat 3.

**Nicht empfohlen:** Valheim (USK 16, keine Fernsteuerung ohne Mod, 4 bis 8 GB), Satisfactory und Palworld (8 bis 16 GB), alle Windows-only-Server, Stardew Valley (kein Server, Steam-Login nötig), 7 Days to Die, Sons of the Forest, V Rising, Garry's Mod, Unturned (Freigabe 16/18 bzw. Inhalte).

### Generischer Unterbau (Entwurf)

- **Spiel-Profil** (deklarativ, z. B. YAML im Code): Quelle (`steamcmd` mit App-ID und anonym, oder `http` mit URL plus Prüfsumme bzw. Versions-API), Startbefehl, Ports (Protokoll, Anzahl, intern/extern), Datenpfade, RAM-Vorgabe und Mindest-RAM, Plattenbedarf, Altersfreigabe-Hinweis, Pflicht-Einstellungen (Listung aus, Crossplay aus, Passwort an).
- **Installer-Container** nach Pelican-Muster: schlankes eigenes Image ohne Spieldateien, lädt zur Laufzeit SteamCMD bzw. den Hersteller-Download ins Welt-Volume; Laufzeit-Container startet aus dem Volume.
- **Update-Dienst**: `app_update` vor jedem Start und nachts, nur wenn niemand spielt; Eltern sehen Version und Datum.
- **Steuer-Adapter je Spiel** (Agent im Container): einheitliche Schnittstelle `players()`, `kick(spieler, grund)`, `say(text)`, `allow(id)`, `deny(id)`, angebunden an stdin (Terraria, DST), RCON (Factorio) oder REST (Palworld). Die bestehende Logik aus `gameworld_time` (Zählbuch, Tagesbudget, Warnungen) bleibt in der ExApp und nutzt den Adapter.
- **Kopplungscode-Flow** für Spieler-IDs (wie bei Mindustry/Minecraft geplant).
- **Engine-Abstraktion** teilen mit Minecraft v2 (MINECRAFT-V2.md 4, WEITERE-SPIELE.md B.3).

### Aufwand grob (LOW, ohne Spike)

| Baustein | Aufwand |
|---|---|
| Engine-Abstraktion (falls nicht schon durch Minecraft da) | 2 bis 3 Tage |
| Spiel-Profile, Installer-Container, Download mit Fortschritt, Plattenprüfung | 3 bis 5 Tage |
| SteamCMD-Pfad (anonym, Fehlerbilder "No subscription", Update-Dienst) | 2 bis 4 Tage, entfällt für Terraria/Factorio |
| Portmodell mit Port-Sets und internen Admin-Ports | 2 bis 3 Tage |
| Steuer-Adapter plus Spielzeit-Anbindung plus E2E je Spiel | 4 bis 8 Tage je Spiel |
| Kopplungscode, Eltern-Texte, privacy.md, Store-Text je Spiel | 1 bis 2 Tage je Spiel |
| **Erstes Spiel (Factorio oder Terraria) gesamt** | **ca. 3 bis 4 Wochen**, jedes weitere 1 bis 2 Wochen |
| Laufende Pflege | Server-Updates und Adapter-Brüche je Spiel, nicht pinbar; Supportanfragen zu Kauf, Steam-Konten, Crossplay |

## Empfehlung

**Lohnt sich nicht** als nächster Schritt und nicht als "Steam-Unterstützung" allgemein.

Begründung, nach Gewicht:
1. **Zielgruppe:** Steam ist erst ab 13 (HIGH). Gameworlds Kern sind jüngere Kinder ohne Konten. Ab 13 bietet Valve selbst Spielzeit-Limits (HIGH), Gameworlds Mehrwert schrumpft.
2. **Kindersicherheit:** Nur wenige Spiele erlauben eine Allowlist pro Spieler und eine Steuerung von außen; ein generischer RCON-Kick existiert nicht (HIGH). Gameworlds Versprechen "nur Eingeladene, Zeit pro Kind" wäre pro Spiel unterschiedlich gut oder gar nicht einlösbar.
3. **Hardware:** Die beliebtesten Titel brauchen 8 bis 16 GB oder einen Windows-Server; SteamCMD läuft nicht auf ARM (HIGH/MEDIUM).
4. **Pflege:** Auto-Update-Clients zwingen zu ungepinnten Server-Updates und je Spiel eigenen Adaptern; das sprengt ein Soloprojekt neben Findling (MEDIUM).
5. **Markt:** Für Erwachsene gibt es Pterodactyl, AMP (20 USD), LinuxGSM; kein Bedarfssignal für "Steam-Server für Kinder" gefunden (LOW bis MEDIUM).

**Mit Auflagen denkbar, frühestens nach Minecraft v2 und nur bei klarer Nachfrage in der Bedarfsumfrage:** Factorio und Terraria als einzelne Spiel-Profile auf derselben Engine-Abstraktion, ausdrücklich ohne SteamCMD. Erst wenn ein drittes Spiel mit echter Nachfrage SteamCMD braucht (DST), den SteamCMD-Pfad bauen.

**Auflagen, falls gebaut wird**
1. Keine Server-Dateien und kein SteamCMD in Gameworld-Images, Registries oder zentralen Backups; Download nur zur Laufzeit auf der Maschine des Betreibers, von Valves CDN bzw. vom Hersteller.
2. Nur anonymer SteamCMD-Login; nie Steam-Zugangsdaten abfragen oder speichern. Spiele ohne anonymen Server-Download nicht anbieten.
3. Pro Spiel vor Aufnahme: EULA/ToS lesen und zitieren (wie in diesem Bericht), Hinweis im Create-Dialog mit Link; Betreiber stimmt aktiv zu (Muster MINECRAFT-LIZENZ.md 2).
4. Öffentliche Serverliste, Relay-/Join-Codes und Crossplay fest aus; Passwort Pflicht; RCON/REST/Telnet nur im internen Netz mit Zufallspasswort.
5. Nur Spiele mit Allowlist pro Spieler oder fernsteuerbarem Kick; sonst kein Kindermodus. Altersfreigabe im UI anzeigen; nichts ab 16.
6. Klarer Hinweis vor dem Anlegen: Steam ab 13, Kauf pro Kind, Steam Families für Kinderkonten.
7. privacy.md und Store-Text nennen Datenaustausch mit Valve bzw. Hersteller und die Verarbeitung von Steam-IDs.
8. Keine Herstellernamen, Logos oder Screenshots im Branding; App-Name bleibt "Gameworld".
9. Nur x86-64 unterstützen und das im Setup-Check prüfen.

## Offen / nicht verifiziert

- RAM-Bedarf der Server von Terraria, Factorio, DST, Core Keeper unter Gameworld-Limits: keine Entwicklerangaben gefunden, Spike nötig (seriell, nur bei genug freiem RAM).
- Ob Valve die Automation-Klausel des SSA je auf SteamCMD-Installationsskripte anwendet: keine Aussage gefunden; Praxis spricht dagegen.
- Keine schriftliche Valve-Erlaubnis für das Bündeln von SteamCMD in Images (cm2network); Duldung ist Praxis, kein Recht.
- Re-Logic-Spiel-EULA für Terraria nicht gefunden (Steam-EULA-Seite lädt nicht); nur Website-Bedingungen geprüft.
- Factorio: ob der kostenlose Headless-Server unter "any of its parts" fällt, offen; deutsche/europäische Altersfreigabe nicht gefunden.
- Satisfactory, Core Keeper, Unturned: keine spielspezifische EULA gefunden.
- Terraria: TShock-Funktionen für Version 6.x (Whitelist, REST) nicht neu geprüft; GOG/Steam-Crossplay am Dedicated Server nicht geprüft.
- Core Keeper: Kick/Konsole nur laut Hoster-Quelle nicht vorhanden.
- Ob Steam-Kinderkonten (13 bis 15) in Steam Families Mehrspieler auf privaten Servern sperren können: nicht gefunden.
- Nachfrage: keine eigene Umfrage; Reddit-Suche nicht erschöpfend.

## Quellen (alle abgerufen 22.10.2026)

**Valve/Steam**
- Steam Subscriber Agreement (Stand 10.09.2026): https://store.steampowered.com/subscriber_agreement/ (HIGH)
- Steam-Registrierung: https://store.steampowered.com/join/ (HIGH)
- SteamCMD: https://developer.valvesoftware.com/wiki/SteamCMD (HIGH, Wiki)
- Dedicated Servers List: https://developer.valvesoftware.com/wiki/Dedicated_Servers_List (MEDIUM, nachweislich teils veraltet)
- Steamworks Distributing Game Servers: https://partner.steamgames.com/doc/sdk/uploading/distributing_gs (HIGH)
- Steamworks Deutschland-Einstufung: https://partner.steamgames.com/doc/gettingstarted/contentsurvey/germany (HIGH)
- SteamCMD-Archiv: https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz (HIGH, Inhalt geprüft)
- Steam Families Ankündigung: https://store.steampowered.com/news/app/593110/view/4605582245626919823 (HIGH)
- Steam Families FAQ: https://help.steampowered.com/en/faqs/view/054C-3167-DD7F-49D4 (HIGH)
- Steam-Families-Community unter 13: https://steamcommunity.com/groups/steamfamilies/discussions/0/4290314417248495532/ (LOW)
- SteamDB Depots: https://steamdb.info/app/105600/depots/ , https://steamdb.info/app/896660/depots/ , https://steamdb.info/app/1690800/depots/ , https://steamdb.info/app/1963720/depots/ , https://steamdb.info/app/343050/depots/ , https://steamdb.info/app/2394010/ , https://steamdb.info/app/1281930/depots/ (HIGH)
- App-Info-API: https://api.steamcmd.net/v1/info/<appid> (HIGH)
- Spielerzahlen: https://steamcharts.com/app/<appid> (HIGH)

**Spiele** (siehe Abschnitt 2 für die vollständige Zuordnung)
- Terraria: https://terraria.org/terms , https://terraria.wiki.gg/wiki/Server , https://terraria.org/api/get/dedicated-servers-names , https://github.com/tModLoader/tModLoader/wiki/Starting-a-modded-server , https://tshock.readme.io/reference/rest-api-endpoints
- Factorio: https://www.factorio.com/terms-of-service , https://www.factorio.com/download , https://wiki.factorio.com/Multiplayer , https://wiki.factorio.com/Command_line_parameters , https://wiki.factorio.com/Console
- DST: https://dontstarve.wiki.gg/wiki/Guides/Don%E2%80%99t_Starve_Together_Dedicated_Servers , https://store.steampowered.com/eula/322330_eula_0
- Valheim: https://www.valheim.com/support/a-guide-to-dedicated-servers/ , https://valheim.com/eula/ , https://github.com/community-valheim-tools/valheim-server-docker
- Satisfactory: https://satisfactory.wiki.gg/wiki/Dedicated_servers , https://satisfactory.wiki.gg/wiki/Console_release , https://github.com/wolveix/satisfactory-server/wiki/Official-API-Docs
- Palworld: https://docs.palworldgame.com/getting-started/deploy-dedicated-server , https://docs.palworldgame.com/getting-started/requirements , https://docs.palworldgame.com/api/rest-api/palwold-rest-api , https://docs.palworldgame.com/api/rcon/ , https://github.com/pocketpairjp/palworld-dedicated-server-docker
- Enshrouded: https://enshrouded.zendesk.com/hc/en-us/articles/16056312924957-Dedicated-Server-FAQ , https://store.steampowered.com/eula/1203620_eula_0
- Core Keeper: https://steamcommunity.com/app/1621690/discussions/0/3275817873363439916/
- Stardew Valley: https://stardewvalleywiki.com/Multiplayer , https://github.com/stardew-valley-dedicated-server/server
- V Rising: https://github.com/StunlockStudios/vrising-dedicated-server-instructions/blob/master/1.1.x-pc/INSTRUCTIONS.md , https://store.steampowered.com/eula/1604030_eula_0
- Astroneer: https://astroneer.space/dedicatedserver/ , https://store.steampowered.com/eula/361420_eula_0
- 7 Days to Die: https://7daystodie.com/crossplay-server-requirements/ , https://store.steampowered.com/eula/251570_eula_0 , https://7daystodie.fandom.com/wiki/Server (MEDIUM)
- Unturned: https://docs.smartlydressedgames.com/en/stable/servers/server-hosting.html , https://docs.smartlydressedgames.com/en/stable/servers/command-io.html
- Garry's Mod: https://wiki.facepunch.com/gmod/Downloading_a_Dedicated_Server , https://store.steampowered.com/eula/4000_eula_0
- Vintage Story: https://wiki.vintagestory.at/Guide:Dedicated_Server , https://www.vintagestory.at/tos.html/
- Hytale: https://support.hytale.com/hc/en-us/articles/45326769420827-Hytale-Server-Manual , https://hytale.com/eula
- Freigaben: https://usk.de/?s=<Titel>&post_type=usktitle , https://pegi.info/search-pegi?q=<Titel> , Xbox/MS-Store-Seiten wie oben

**Panels und Praxis**
- Pelican-Eggs SteamCMD: https://github.com/pelican-eggs/games-steamcmd (HIGH)
- cm2network/steamcmd: https://github.com/CM2Walki/steamcmd , https://hub.docker.com/r/cm2network/steamcmd/ (HIGH)
- LinuxGSM: https://linuxgsm.com/ (HIGH)
- Pterodactyl: https://github.com/pterodactyl/panel , https://api.github.com/repos/pterodactyl/panel/releases (HIGH)
- Pelican: https://api.github.com/repos/pelican-dev/panel/releases (HIGH)
- AMP: https://cubecoders.com/AMP (HIGH)
- Kubek: https://github.com/Seeroy/kubek-minecraft-dashboard (HIGH)
- Games on Whales: https://games-on-whales.github.io/ (HIGH)
- Nitrado: https://server.nitrado.net/en-US/offers/valheim (LOW)
- Nextcloud App Store API: https://apps.nextcloud.com/api/v1/apps.json (HIGH)
- ARM-SteamCMD (Community): https://hub.docker.com/r/sonroyaalmerol/steamcmd-arm64 (MEDIUM)
- Reddit: https://www.reddit.com/r/selfhosted/comments/1q92qn1/games_server/ , https://www.reddit.com/r/HomeServer/comments/1h9psgh/is_there_a_program_that_allows_you_to_manage_all/ , https://www.reddit.com/r/selfhosted/comments/1s8zprs/guide_for_hosting_game_servers/ (LOW)
