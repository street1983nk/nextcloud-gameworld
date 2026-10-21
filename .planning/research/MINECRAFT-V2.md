# Machbarkeit: Minecraft in Gameworld v2

**Modus:** Feasibility
**Recherchiert:** 21.10.2026 (nur Web-Recherche, kein Docker, kein Server-Download)
**Urteil:** BEDINGTES GO für Minecraft Java (Paper) als v2 nach dem Store-Release von v1; NO-GO (vorerst) für Bedrock/Geyser und für Minecraft Education
**Konfidenz gesamt:** MEDIUM-HIGH (Rechtstexte und Engine-Doku im Original gelesen; RAM-Werte und Härtungsdetails brauchen den Spike)

Konfidenz-Markierung: [H] = Originalquelle gelesen, [M] = mehrere Quellen bzw. Doku plus Ableitung, [L] = Einzelquelle/Training, unverifiziert.

---

## 1. Recht

### 1.1 EULA (minecraft.net/en-us/eula, abgerufen 21.10.2026, Seite ohne Datum)

- Server ausdrücklich erlaubt: "For the server version of Minecraft: Java Edition, you can install it on a server and host online play." [H]
- Tools erlaubt: "You may develop tools, plug-ins and services as long as they do not seem official or approved by us, such as by using our logos." [H]
- Verboten ist "distribute anything we've made": Kopien weitergeben, kommerzielle Nutzung, Geld verdienen, unfairer Zugang. [H]
- Downloads nur aus autorisierter Quelle: "we need all game downloads and updates to come from a source that we authorize". [H]
- Mods: eigene Mods/Plugins verteilen ist ok, "Modded Versions of the game client or server software are not okay to distribute". [H]
- Minderjährige: "your parent or legal guardian is responsible for the creation of your Microsoft account and the acceptance all terms on your behalf." [H]
- Minecraft Education fällt NICHT unter diese EULA, sondern unter den Gruppenvertrag der Schule. [H]
- Die Java-Server-Downloadseite: "by downloading any of the software on this page, you agree to the Minecraft End User License Agreement and Privacy Policy." Die BDS-Downloadseite hat eine Zustimmungs-Checkbox mit demselben Text (EULA + Privacy Policy). [H]

**Folgerung für Gameworld:**
- Automatischer Download zur Laufzeit vom Mojang-/Paper-Server auf der Maschine des Betreibers ist das etablierte, zulässige Muster (Gameworld verteilt nichts). server.jar oder Paper-Jar NIE ins ExApp-Image oder in eine Gameworld-Registry. [M]
- Paper ist eine "Modded Version": Paperclip erzeugt das Paper-Jar erst beim ersten Start per bsdiff-Patch gegen das Vanilla-Jar (Paperclip-README), d. h. Gameworld darf das gepatchte Jar ebenfalls nicht cachen und weitergeben, nur die Welt-Container laden es selbst. [H für Paperclip-Mechanik, M für Rechtsfolge]
- EULA-Zustimmung durch die Person, die den Server betreibt: das Nextcloud-Verwalterkonto, per eigenem Klick im Create-Flow mit Link zur EULA, gespeichert mit Konto und Zeitstempel. Erst dann setzt der Provisioner `EULA=TRUE`. Kein Default, keine Vorbelegung. Für Kinder akzeptieren Eltern die Bedingungen ohnehin bei Kontoerstellung. [M]

### 1.2 Usage Guidelines (minecraft.net/en-us/usage-guidelines, abgerufen 21.10.2026, ohne Datum, "may change ... at any time")

- Server: "You may host a server for Minecraft." Zugang "Must only be granted to users who have a genuine paid-for version of Minecraft". [H] Das schließt offline-mode praktisch aus (siehe 2).
- Begriff "commercial use" umfasst laut Guidelines auch kostenlos geteilte Server ("regardless of whether you receive payment or provide it for free"); für Gameworld relevant sind daher die allgemeinen Regeln, Monetarisierung gibt es keine. [H]
- Pflichten für alle Nutzungen [H]:
  - nichts, was offiziell/genehmigt/verbunden wirkt; keine Logos, Schriften, Texturen als Branding
  - klar machen, wer verantwortlich ist und wie man ihn kontaktiert (Chat/Forum zählen nicht)
  - Disclaimer prominent auf Produkt, Listing, Beschreibung, Website: "NOT AN OFFICIAL MINECRAFT [PRODUCT]. NOT APPROVED BY OR ASSOCIATED WITH MOJANG OR MICROSOFT"
  - Spiel oder Spieldateien nicht weiterverteilen
- Naming: "Minecraft" nur als Zweitname/Beschreibung, nie dominanter Teil des Titels. Beispiel der Guidelines: "Kotoba Miners: A Minecraft server for Redstone builds" ok, "Minecraft - the ultimate Kotoba server" nicht ok. [H]
- Bei Servern mit Einnahmen zusätzlich: Datenschutzverantwortung klarstellen, EULA- und Warndialoge nicht verstecken. Für uns als Grundsatz übernehmen. [H]
- Zielgruppe: Die Erlaubnisse gelten für die Community; sie autorisieren nicht "commercial companies ... non-profits ... governments", Minecraft für eigene Produkte/Agenden zu nutzen. Für ein freies Open-Source-Tool unkritisch, aber ein Grund, Gameworld nie mit Minecraft zu bewerben. [H, Auslegung M]
- Keine Einzelfallberatung durch Mojang ("If you are unsure, you should speak to an attorney"). [H]

**Regeln für Gameworld (Store, README, UI):**
- App-Name bleibt "Gameworld"; Beschreibung z. B. "Private Spielwelten für Luanti und Minecraft: Java Edition".
- Kein Creeper, kein Grasblock, keine Minecraft-Schrift im Icon oder in Screenshots; Store-Screenshots nur Gameworld-UI, kein Gameplay. [M]
- Disclaimer in Store-Beschreibung, README und im Minecraft-Create-Dialog.
- Kostenlos, AGPL, keine Pro-Variante mit Minecraft-Bezug (ISV-Ideen nicht mit Minecraft koppeln).
- Kein Keyword-Spamming mit "Minecraft" im Store.

### 1.3 Minecraft Education und Schulen

- Lizenzen (education.minecraft.net/en-us/licensing, 21.10.2026): Schulen 5,04 USD pro Nutzer und Jahr, Camps/Clubs/Vereine 36 USD pro Nutzer und Jahr; Voraussetzung Microsoft-365-Konto. [H]
- Es gibt einen offiziellen **Minecraft Education Dedicated Server** (edusupport.minecraft.net, "Dedicated Server FAQ", aktualisiert 21.10.2026): self-hosted on-prem oder VPS, Windows und Ubuntu, Allow-List und Passcode optional, Cross-Tenant-Play verfügbar. [H]
- Bedingungen [H]: Global Admin des M365-Tenants muss das Feature freischalten; Server werden im Admin-Portal (aka.ms/dedicatedservers) registriert und heruntergeladen; der Server authentifiziert sich beim Start per Admin-Anmeldung; Clients brauchen eine Education-Lizenz und den Education-Client; IPv6 nicht unterstützt.
- Folgerung: Ein Education-Server ist an einen Microsoft-Tenant gebunden, der Download liegt hinter einem Login und der Server braucht eine interaktive Tenant-Anmeldung. Gameworld kann das nicht sauber automatisieren und würde die Nextcloud-Identität ohnehin nicht nutzen (Identität = Entra ID). **Kein Ziel für Gameworld.** [M]
- Consumer-Java in Schulen hieße: jedes Kind braucht eine gekaufte Java-Lizenz auf einem privaten Microsoft-Konto. Für Schulen unrealistisch. **Schulen bleiben bei Luanti** (VoxeLibre/Mineclonia), das ist ein Verkaufsargument, kein Mangel. [M]

---

## 2. Konten und Geräte

### Java
- online-mode=true verlangt pro Kind ein eigenes Microsoft-Konto mit gekaufter Java Edition (heute als Paket "Java & Bedrock Edition für PC"). Preis ca. 30 EUR. [M für Kontopflicht, L für Preis]
- Kinderkonten in der Microsoft-Familie: Multiplayer in Java ist gesperrt, bis die organisierende Person in den Xbox-Datenschutzeinstellungen des Kindes (account.xbox.com/settings) "Du kannst an Multiplayer-Spielen teilnehmen" erlaubt; Wirkung teils erst nach Stunden bis 24 h, Ab- und Anmelden im Launcher nötig. Quellen sind Microsoft-Q&A-Moderatorantworten, keine offizielle Hilfeseite gefunden. [M]
  - Gameworld braucht dafür eine Eltern-Anleitung im UI und eine klare Fehlerhilfe ("Mehrspielermodus deaktiviert" = Microsoft-Einstellung, nicht Gameworld).
- Whitelist-Namen sind Java-Profilnamen, nicht Xbox-Gamertags; beide können sich beim selben Konto unterscheiden (itzg-Doku). [H]
- **offline-mode: NO-GO.** Rechtlich: Guidelines verlangen Zugang nur für "genuine paid-for version", offline-mode prüft das nicht. Sicherheit: offline-UUIDs werden aus dem Namen abgeleitet, jeder kann jeden Namen annehmen, Whitelist und Zeitkonto wären per Namenswechsel umgehbar. [H Rechtstext, M Technik]

### Bedrock
- BDS ist kostenlos, Download mit EULA-Zustimmung, offiziell nur Ubuntu 22.04+ und Windows. Systemanforderung laut Downloadseite 4 GB RAM, "At least 1 GB of RAM for small servers". [H]
- Bedrock-Spieler brauchen ein Microsoft-Konto (Xbox-Profil); auf Konsolen zusätzlich die Plattform-Regeln, vermutlich Online-Abo für Multiplayer (Xbox Game Pass Core/Essential, PS Plus, Nintendo Switch Online). [L, nicht offiziell geprüft]
- **Konsolen (Xbox, PlayStation, Switch) können keine eigene Server-Adresse eintragen**; nur "Featured Servers". Workaround ist DNS-Umleitung über BedrockConnect (Fremd-DNS auf der Konsole). Für ein Kindersicherheitsprodukt nicht vertretbar. Im selben LAN zeigt BDS sich unter "Freunde / LAN-Spiele" (itzg-README; Konsolen-Sichtbarkeit nicht verifiziert). [M]
- **Netzwerk-Umbruch genau jetzt:** BDS 1.26.50+ nutzt standardmäßig NetherNet (WebRTC): TCP-Port für Signalisierung plus ein UDP-Port pro Spieler aus einem festen Bereich, UDP 7551 für LAN-Discovery; die Server-IP muss für Clients erreichbar in `SERVER_UDP_PORTS` stehen (itzg-bedrock-README). [H] Laut GeyserMC-Blog (08.10.2026) verbinden sich Bedrock-Clients ab Bedrock 26.60, geplant 27.10.2026, nicht mehr per RakNet. [H]

---

## 3. Java vs. Bedrock vs. beides

| Kriterium | Java (Paper) | Bedrock (BDS) | Java + Geyser/Floodgate |
|---|---|---|---|
| Server-Erweiterbarkeit | Paper-Plugin-API, voll | keine Plugin-API, nur Script-API-Addons [L] | Paper-Plugin, Bedrock-Spieler laufen durch denselben Plugin-Pfad |
| Unsere Features (Whitelist, Zeit, Pause, Kick) | eigenes Plugin, gleiches Muster wie Luanti-Mods | nur Allowlist nativ; Zeitlimit nur über Script-API mit HTTP zur ExApp [L] | wie Java |
| Ports pro Welt | 1 TCP | 1 TCP + UDP-Bereich pro Spieler (NetherNet) | 1 TCP Java + Geyser TCP + UDP |
| Geräte der Kinder | PC/Mac/Linux | Tablet, Handy, Windows, Konsole (Konsole nur mit DNS-Trick) | beide, Konsole wie Bedrock |
| Pflege | moderat, Paper-Updates je Minecraft-Version | Updates erzwingen Server-Update sofort (Clients updaten automatisch) | hoch: Geyser muss jedem Bedrock-Update folgen, NetherNet-Umbau läuft (Geyser-Commits 15.09. bis 20.10.2026, offene Issues zu Handshake-Timeouts, Alpine/musl, EL9) [H] |
| Aufwand | Basis | hoch | Basis + 6 bis 10 Tage |

**Entscheid:** Java (Paper) zuerst. Bedrock-Reichweite (Tablets) ist real, aber der Weg dahin ist im Oktober 2026 instabil (NetherNet-Umstellung), Konsolen sind ohne Fremd-DNS ausgeschlossen, und BDS kann unsere Spielzeitlogik nicht sauber tragen. Geyser frühestens nach Stabilisierung neu bewerten (Q1/2027), dann nur als Option "Tablets und Handys im Heimnetz", Konsolen ausdrücklich nicht unterstützt.

---

## 4. Engine

### itzg/docker-minecraft-server (Empfehlung)
- Apache-2.0, sehr aktiv (Release 2026.10.0 am 10.10.2026, 14,4k Sterne). [H]
- Lädt Server zur Laufzeit; `EULA=TRUE` ist Pflicht ("Mojang/Microsoft requires EULA acceptance"). `TYPE=PAPER`, `VERSION` (Default LATEST, also pinnen), Fabric, Forge u. a. [H]
- Versionen: Minecraft 26.3 (15.09.2026) ist aktuell, Paper 26.3 stable (fill.papermc.io); Paper braucht Java 25 ab 26.1. Image-Tag pinnen: `itzg/minecraft-server:2026.10.0-java25` plus Digest, analog zu unserem Luanti-Digest-Pin. [H]
- Speicher: Default-Heap 1 GB (`MEMORY=1G`); Doku empfiehlt Container-Limit +25 % über Heap; mit `MEMORY=""` nimmt die JVM 25 % des Container-Limits. [H]
- Nutzer: Dockerfile setzt `UID=1000 GID=1000`; das Start-Skript wechselt nur dann per gosu, wenn es als root läuft, sonst startet es direkt. Also `user: "1000:1000"` funktioniert ohne CHOWN/SETUID-Capabilities, wenn das Volume vorher 1000 gehört. [H Skript gelesen, M Folgerung]
- Konsole: RCON ist Default AN (Zufallspasswort, Port 25575); alternativ `CREATE_CONSOLE_IN_PIPE` mit `mc-send-to-console`. [H]
- Whitelist-Variablen (`WHITELIST`, `EXISTING_WHITELIST_FILE`, `ENFORCE_WHITELIST`), Namen werden über PlayerDB oder Mojang-API aufgelöst (externer Dienst). [H] Wir brauchen das nicht, siehe 5.
- Pausieren: seit 1.21.2 pausiert der Server nativ bei leerer Welt (`PAUSE_WHEN_EMPTY_SECONDS`), itzg rät von eigenem Autopause ab. RAM bleibt dabei belegt. [H]
- Härtung, unverifiziert, Spike-Thema [M/L]:
  - `read_only: true` mit tmpfs `/tmp`: Start-Skripte und mc-image-helper schreiben primär nach `/data`; im root-Pfad schreibt das Skript `/etc/nsswitch.conf`, im Nicht-root-Pfad nicht. Plausibel, aber testen.
  - `cap_drop: ALL`, `no-new-privileges`: sollte als Nicht-root gehen.
  - `pids_limit` 128 (Luanti-Wert) ist für die JVM zu knapp, 512 ansetzen; `nano_cpus` 2 statt 1 (Chunk-Generierung).
  - Ausgehendes Netz ist Pflicht: Download (Mojang piston, PaperMC fill) und bei online-mode die Mojang-Session-Server bei jedem Login.

### Crafty Controller 4.11.0 (16.09.2026)
- Ein Container mit Web-Panel, alle Server laufen darin, Portbereich 25500-25600 plus Bedrock/Hytale-Ports (offizielles docker-compose.yml). [H] Eigene Nutzerdatenbank, eigenes Panel. Widerspricht unserem Muster (ein gehärteter Container pro Welt, Limits pro Welt, Nextcloud als Identität). **Nicht verwenden.**

### itzg/docker-minecraft-bedrock-server (nur falls Bedrock später)
- MIT, Release 2026.10.1 (16.10.2026). `EULA=TRUE` Pflicht, `VERSION=LATEST` aktualisiert bei jedem Start. Allowlist seit neueren BDS-Versionen standardmäßig an, Rechte per XUID oder Gamertag (Auflösung über mcprofile.io, externer Dienst). Nicht-root nur mit vorher per chown vorbereitetem Volume. NetherNet-Portbereich wie oben. [H]

### Passung zum Sibling-Container-Muster
- Gut: ein Container pro Welt, benanntes Volume auf `/data`, Labels, put_archive/get_archive, Limits über docker-py, Socket-Proxy-Rechte unverändert (CONTAINERS, IMAGES, VOLUMES, POST). [M]
- Neu: TCP statt UDP pro Welt (eigener Portbereich, z. B. 25565-25599/tcp); Spec-Funktion `world_spec` ist heute Luanti-fest kodiert (Image, Command, DATA_DIR, Port, Label `gameworld.engine`), muss zu einer Engine-Abstraktion werden.

---

## 5. Unsere Funktionen serverseitig durchsetzen

**Empfehlung: eigenes Paper-Plugin `gameworld-paper` (Java 25, Gradle), Spiegel der Luanti-Mods gameworld_access, gameworld_time, gameworld_status.** Vorhandene Playtime-Plugins auf Modrinth haben nur Hunderte Downloads und decken unser Datenmodell (Wochenplan, Ferien, Welt-Fenster, Tageskonto über alle Welten) nicht ab. [H für Downloadzahlen]

- **Whitelist:** Nicht die native whitelist.json als Quelle nutzen, sondern wie bei Luanti eine root-eigene Regeldatei (`/data/gameworld/access.json`, 0444, per put_archive). Plugin prüft in `AsyncPlayerPreLoginEvent` die UUID und lehnt mit `disallow(Result, Component)` ab; die Klasse existiert in paper-api 26.3 build 211 stable. [H] Datei alle paar Sekunden neu laden, kein Neustart.
- **Konto-Zuordnung Nextcloud zu Minecraft:** UUID statt Name (Namen sind änderbar). Vorschlag Kopplungscode: unbekannte UUID wird beim Join mit einem kurzen Code abgewiesen ("Gib 7F3K in Gameworld ein"), das Kind trägt den Code in seiner Nextcloud-Kind-Ansicht ein, die ExApp bindet UUID an das Konto und schreibt die Regeldatei neu. Vorteil: kein Tippfehler, kein Aufruf externer Namens-APIs, ein Fremder mit Code hat ohne Nextcloud-Konto nichts davon. Alternative: Eltern geben den Java-Profilnamen ein, ExApp löst einmalig über api.mojang.com auf (externer Datenabfluss, in privacy.md nennen). [M, Entwurf]
- **Spielzeit, Pause, Warnungen, Kick:** zweite Regeldatei mit absoluten Epoch-Grenzen wie `gameworld_time.txt`; Plugin sperrt im Prelogin, warnt per Chat/Titel bei 10/5/1 min, kickt per `Player#kick`, schreibt ein neustartfestes Zählbuch ins Volume. Pause = Grenze "jetzt". Gleiche Logik wie Luanti, nur andere Sprache. [M]
- **Ereignisse ohne neue Ports:** Plugin schreibt JSON-Lines (join, leave, denied, kicked) und eine Statusdatei nach `/data/gameworld/`; ExApp liest per get_archive wie bisher. Alternative: strukturierte Zeile in stdout, ExApp liest Docker-Logs. Kein HTTP, kein offener Port. [M]
- **RCON: AUS** (`ENABLE_RCON=false`). Gründe: Klartext-TCP-Protokoll, nur Passwortschutz, im Docker-Netz von anderen Containern erreichbar, Default an. Steuerung ausschließlich über Regeldateien plus Container stop (itzg sendet beim Stopp `stop` über Konsole). [H für Default, M für Risiko]
- **Weitere server.properties:** `online-mode=true`, `enable-query=false`, `enable-rcon=false`, `max-players` klein, `difficulty=peaceful`/`easy` je Preset, keine OPs für Kinder, `enforce-secure-profile=true`. Zum Abschalten der öffentlichen Sichtbarkeit: Java-Server tauchen in keiner Liste auf, solange niemand die Adresse veröffentlicht; `enable-status` lässt Ping/MOTD zu, ggf. aus. [M]
- **Plugin-Auslieferung:** eigenes Werk, darf ins ExApp-Image und per put_archive nach `/data/plugins/`. Kein fremdes Plugin, keine Downloads aus Plugin-Märkten. [M]

---

## 6. Ressourcen

| Engine | RAM pro Welt (realistisch, 2 bis 5 Kinder) | CPU | Quelle |
|---|---|---|---|
| Luanti | ca. 100 MB, Presets 512 MB / 1 GB Limit | 1 Kern | Owner-Messung, spec.py |
| Paper (Java) | Heap 1,5 bis 2 GB, Container-Limit 2 bis 2,5 GB | 2 Kerne für Chunk-Generierung, idle gering | itzg-Doku (1G Default, +25 %) [H], Rest [L] |
| BDS | ca. 0,5 bis 1 GB | 1 bis 2 Kerne | BDS-Seite "at least 1 GB" [H] |
| Paper + Geyser | +0,3 bis 0,5 GB | etwas mehr | [L] |

- Folge für Heimserver mit 8 GB inkl. Nextcloud: realistisch 1, höchstens 2 Minecraft-Welten gleichzeitig; mit 16 GB 3 bis 4. Luanti-Welten bleiben daneben möglich. [L]
- Der bestehende Ressourcen-Check vor Welt-Start muss engine-spezifische Bedarfe kennen; Minecraft-Preset fest bei z. B. 2,5 GB Limit, Heap 2 GB.
- Erster Start lädt Vanilla- und Paper-Jar (je Dutzende MB) und patcht; Plattenbedarf pro Welt 0,5 bis mehrere GB je nach Erkundung. Backups werden größer als bei Luanti. [L]

---

## 7. Aufwand, Risiken, Empfehlung

### Aufwand MVP Java (Paper), Solo-Entwickler, in Arbeitstagen

| Paket | Tage |
|---|---|
| Spike (siehe unten) | 2 |
| Engine-Abstraktion im Provisioner (Image, Command, Ports, Datenpfad, Labels, Presets, Ressourcen-Check) | 2 bis 3 |
| Paper-Plugin: Zugang, Zeit/Pause/Warnung/Kick, Status/Events, Unit-Tests (z. B. MockBukkit) inkl. Gradle/CI für Java 25 | 5 bis 7 |
| Konto-Kopplung (Code-Flow), Kind-Ansicht mit Java-Anleitung, Eltern-Hilfe Xbox-Datenschutz | 2 bis 3 |
| EULA-Zustimmungs-Flow, Disclaimer, Store-/README-Texte, privacy.md | 1 |
| Backup/Restore für Java-Weltstruktur, Talk-Raum, Reconciler-Fälle | 1 bis 2 |
| E2E-Tests: echter Join-Test braucht einen Client; online-mode im Test nur mit echtem Konto, daher Testserver im offline-mode mit Bot (z. B. mineflayer) ausschließlich in CI, nie im Produkt | 2 bis 3 |
| **Summe** | **15 bis 21** |

Die alte Schätzung "+8 bis 12 Tage via Crafty" ist zu niedrig, weil sie die Durchsetzung unserer Kernfunktionen (Plugin) nicht enthält.

**Bedrock/Geyser-Add-on:** Geyser+Floodgate ins Paper-Setup, NetherNet-Ports (TCP + UDP-Bereich pro Welt), Floodgate-UUID/XUID-Kopplung, Geräteanleitungen: 6 bis 10 Tage, danach laufende Pflege bei jedem Bedrock-Update. Reines BDS mit Script-API-Zeitlogik: 10 bis 14 Tage, LOW confidence.

### Hauptrisiken
1. **Guidelines sind widerruflich** ("may be revoked at any time"): Restrisiko bleibt, ist aber für ein freies Self-Hosting-Tool ohne Branding gering; Luanti bleibt das Kernprodukt. [H]
2. **Kosten und Kontohürde für Familien:** jedes Kind braucht eine gekaufte Java-Lizenz und freigegebene Xbox-Einstellungen; Support-Anfragen landen bei Gameworld. [M]
3. **Ressourcen:** 20-fach mehr RAM als Luanti; auf kleinen Heimservern frustrierend. [M]
4. **Neue Sprache Java** im Soloprojekt neben Findling; Plugin muss jeder Paper-Version folgen. [M]
5. **Härtung des itzg-Images unter read_only/cap_drop ungetestet.** [L]
6. **Runtime-Abhängigkeit von Mojang/PaperMC/Session-Servern:** ohne Internet kein Start, kein Login. [H]
7. Bedrock: NetherNet-Umbruch (27.10.2026), Konsolen nur per Fremd-DNS. [H]

### Empfehlung
- **Java (Paper): bedingtes GO als v2**, Bedingungen:
  1. v1 (Luanti) ist im Store und stabil; Minecraft verdrängt keine v1-Phase.
  2. Der Spike bestätigt gehärteten Betrieb (Nicht-root, read_only oder begründete Ausnahme, cap_drop ALL) und RAM unter 2,5 GB für 3 Spieler.
  3. online-mode fest an, RCON fest aus, EULA-Klick durch den Verwalter, Disclaimer und Naming wie in 1.2.
  4. Kein Bezahlmodell mit Minecraft-Bezug.
- **Bedrock/Geyser: NO-GO bis mindestens Q1/2027**, dann neu prüfen (NetherNet-Stabilität in Geyser, LAN-Discovery für Tablets). Konsolen dauerhaft "nicht unterstützt".
- **Minecraft Education: NO-GO** für Gameworld; Schulen über Luanti bedienen, Education-Server bleibt Sache des Schul-Tenants.

### Erster Schritt: Spike (2 Tage, erst wenn RAM frei ist, nie neben Findling-Containern)
1. `itzg/minecraft-server:2026.10.0-java25` per Digest, `TYPE=PAPER`, `VERSION=26.3`, `EULA=TRUE`, `ENABLE_RCON=false`, `ONLINE_MODE=true`, `user 1000:1000`, `read_only` + tmpfs `/tmp`, `cap_drop ALL`, `no-new-privileges`, `mem_limit=2.5g`, `pids_limit=512`, über den bestehenden Socket-Proxy mit docker-py erzeugen. Messen: Startzeit erster/zweiter Start, RAM idle und mit 1 Spieler.
2. Minimal-Plugin: Prelogin liest `/data/gameworld/access.json`, lehnt fremde UUID mit Code ab, schreibt `events.jsonl`. Datei per put_archive tauschen, Wirkung ohne Neustart prüfen.
3. Join mit echtem Konto (Owner) und Abweisung mit zweitem Konto.
4. Ergebnis: Go/No-Go-Notiz plus konkrete Spec-Werte für die Engine-Abstraktion.

---

## Quellen

- Minecraft EULA: https://www.minecraft.net/en-us/eula (abgerufen 21.10.2026, kein Datum auf der Seite) [H]
- Minecraft Usage Guidelines: https://www.minecraft.net/en-us/usage-guidelines (abgerufen 21.10.2026, kein Datum) [H]
- Java-Server-Download: https://www.minecraft.net/en-us/download/server (EULA-Satz) [H]
- Bedrock Dedicated Server: https://www.minecraft.net/en-us/download/server/bedrock (Systemanforderungen, Zustimmungs-Checkbox, Plattformliste) [H]
- Minecraft Education Licensing: https://education.minecraft.net/en-us/licensing (5,04 / 36 USD) [H]
- Education Dedicated Server FAQ: https://edusupport.minecraft.net/hc/en-us/articles/41758309283348-Dedicated-Server-FAQ (aktualisiert 21.10.2026) [H]
- Education IT Admin Create Servers: https://edusupport.minecraft.net/hc/en-us/articles/46370720373908-IT-Admin-Create-Dedicated-Servers (21.10.2026) [H]
- Education Alternate Configuration: https://edusupport.minecraft.net/hc/en-us/articles/41757415076884-Dedicated-Server-Alternate-Configuration (13.10.2026) [H]
- itzg/docker-minecraft-server: https://github.com/itzg/docker-minecraft-server (Docs unter docs/, Dockerfile, scripts/start; Release 2026.10.0) [H]
- itzg Docker-Hub-Tags: https://hub.docker.com/r/itzg/minecraft-server/tags (2026.10.0-java25) [H]
- itzg/docker-minecraft-bedrock-server README: https://github.com/itzg/docker-minecraft-bedrock-server (Release 2026.10.1, NetherNet-Ports, Allowlist) [H]
- Mojang Versionsmanifest: https://piston-meta.mojang.com/mc/game/version_manifest_v2.json (26.3 vom 15.09.2026) [H]
- PaperMC Fill API: https://fill.papermc.io/v3/projects/paper ; Getting Started: https://docs.papermc.io/paper/getting-started/ (Java 25, Stand 18.09.2026) [H]
- Paperclip README: https://github.com/PaperMC/Paperclip (bsdiff-Patch beim ersten Start) [H]
- Paper Javadoc AsyncPlayerPreLoginEvent: https://jd.papermc.io/paper/26.3/org/bukkit/event/player/AsyncPlayerPreLoginEvent.html [H]
- GeyserMC Blog "Preparing Your Geyser Server for NetherNet" (08.10.2026): https://geysermc.org/blog [H]
- GeyserMC Commits/Issues zu NetherNet: https://github.com/GeyserMC/Geyser (Commits 15.09. bis 20.10.2026, Issues #6807, #6809, #6810) [H]
- Crafty Controller compose: https://gitlab.com/crafty-controller/crafty-4/-/raw/master/docker/docker-compose.yml ; Release v4.11.0 (16.09.2026) [H]
- Modrinth-Suche Playtime-Plugins: https://api.modrinth.com/v2/search?query=playtime%20limit [H]
- Microsoft Q&A zu Java-Multiplayer bei Kinderkonten: https://learn.microsoft.com/en-us/answers/questions/4220013/minecraft-java-edition-multiplayer-option-disabled , https://learn.microsoft.com/en-us/answers/questions/5831285/minecraft-java-edition-multiplayer-disabled-micros [M, keine offizielle Hilfeseite gefunden]
- Konsolen-Workaround BedrockConnect (Hoster-Anleitungen, mehrere übereinstimmend): https://pingplayers.com/knowledgebase/minecraft-bedrock-edition/how-to-join-a-custom-minecraft-bedrock-server-on-xbox-switch-playstation [M]

## Offene Punkte
- Offizielle Microsoft-Hilfeseite zu Java-Multiplayer und Kinderkonten nicht gefunden (nur Q&A-Antworten).
- Konsolen-Abo-Pflicht für Bedrock-Server nicht offiziell verifiziert.
- read_only-Betrieb des itzg-Images und reale RAM-Werte: nur per Spike klärbar.
- Lizenzverträglichkeit Paper-API (Plugin-Linking) mit AGPL nicht geprüft.
- Ob Bedrock-Konsolen die NetherNet-LAN-Discovery eines Geyser-Servers sehen: unbekannt.
