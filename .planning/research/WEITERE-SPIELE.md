# Recherche: Weitere Spiele für Gameworld

**Modus:** Ecosystem plus Machbarkeit
**Recherchiert:** 22.10.2026 (nur Web und Quelltext, kein Docker, kein Server gestartet)
**Urteil:** Billigster und sicherster Hebel sind weitere Luanti-Spiele als Presets (Mineclonia zuerst, dann Repixture). Unter den Fremd-Engines passt Mindustry technisch am besten, OpenTTD hat die beste eingebaute Zugangskontrolle, SuperTuxKart ist bei Kindern am attraktivsten, braucht aber einen C++-Patch für unsere Zugangsregeln.
**Konfidenz gesamt:** MEDIUM-HIGH für Teil A, MEDIUM für Teil B (Aufwand und RAM ohne Spike).

Konfidenz-Markierung: [H] = Originalquelle oder Quelltext gelesen, [M] = mehrere Quellen bzw. Doku plus Ableitung, [L] = Einzelquelle, Suchtreffer oder Schätzung, unverifiziert.

---

## Teil A: Luanti-Spiele als Presets

### A.1 Messwerte (ContentDB-API, abgerufen 22.10.2026)

Score und Downloads aus `content.luanti.org/api/packages/<autor>/<name>/`, Release aus `/releases/`. Mindestversion laut Release-Metadaten, keine Höchstversion gesetzt, also formal mit Luanti 5.17.0 verträglich. [H]

| Spiel (Paket) | Lizenz Code / Medien | Letztes Release | min. Luanti | Größe Zip | Score / Downloads | Kindereignung |
|---|---|---|---|---|---|---|
| Mineclonia (`ryvnf/mineclonia`) | GPL-3.0+ / CC-BY-SA-4.0 | 0.124.0, 11.10.2026 (Rel. 39338) | 5.10 | 29,9 MB | 22648 / 554k (Platz 1 nach Score) | gut mit Schaltern: `only_peaceful_mobs`, `mobs_griefing`, `mcl_explosions_griefing`, `enable_fire`, `mcl_keepInventory`, `mcl_enable_commandblocks`, `mcl_difficulty` (peaceful) |
| VoxeLibre (`Wuzzy/mineclone2`) | GPL-3.0+ / CC-BY-SA-4.0 | 0.92.4, 18.10.2026 (Rel. 39534) | 5.10 | 84,2 MB | 18711 / 784k | bereits Preset "Abenteuer (sanft)" |
| Minetest Game (`Luanti/minetest_game`) | LGPL-2.1+ / CC-BY-SA-3.0 | 17.08.2026 (Rel. 38214) | 5.8 | 3,2 MB | 13684 / 1,16 Mio. | bereits Preset "Bauen (kreativ)" |
| Repixture (`Wuzzy/repixture`) | AGPL-3.0+ / CC-BY-SA-4.0 | 3.21.1, 31.08.2026 (Rel. 38512) | 5.13 | 33,3 MB | 10137 / 102k | sehr gut: Low-Tech-Bauen, eigene Optik, Schalter `only_peaceful_mobs`, `tnt_enable`, `hunger_enable` |
| NodeCore (`Warr1024/nodecore`) | MIT / MIT | 11.10.2026 (Rel. 39354) | 5.8 | 1,4 MB | 4475 / 185k | Knobel-Survival, eher ab 10 bis 12, kein Kreativmodus möglich (`disabled_settings = creative_mode, !enable_damage`) |
| Age of Mending (`Sumianvoice/pmb_core`) | MIT / CC-BY-4.0 | a71.2, 07.09.2026 | 5.10 | 8,0 MB | 2577 / 41k | Bau-Sandbox, Alpha-Stand |
| Skyblock: Zero (`zanderdev/skyblock_zero`) | GPL-3.0 / CC-BY-SA-4.0 | 47, 29.08.2026 | k. A. | 28,6 MB | 3191 / 34k | Technik-Skyblock, ab ca. 10; vergibt bei jedem Join `tp` und `home` (Quelltext `sbz_base/init.lua:222`) |
| Hades Revisited (`Wuzzy/hades_revisited`) | LGPL-2.1+ / CC-BY-SA-3.0 | 0.20.3, 18.09.2026 | 5.10 | 19,2 MB | 2347 / 50k | Terraforming-Survival, nur Mapgen v6 |
| Exile (`Mantar/exile`) | GPL-3.0 / CC-BY-SA-3.0 | v0.4.1c, 14.10.2026 | 5.10 | 33,1 MB | 3014 / 69k | **nicht für Kinder**: "brutal wilderness survival", ContentDB-Warnung `alcohol_tobacco` |
| Asuna (`EmptyStar/asuna`) | GPL-3.0 / CC-BY-SA-4.0 | v1.1.5, 25.06.2025 | k. A. | 91,1 MB | 4459 / 122k | kindgerecht (MTG-Basis, Biome), aber seit 16 Monaten ohne Release |
| Builda City (`Splizard/buildacity`) | "Other (Free/Open)" / CC-BY-3.0 | v0.3.3, 17.04.2026 | 5.4 | 6,4 MB | 1766 / 40k | Stadtbau, Game-Jam-Ursprung, Lizenz unklar benannt |
| MeseCraft | AGPL-3.0 (GitHub `jeremyweston/MeseCraft`) | letzter Push 01.02.2026, 42 Sterne | k. A. | k. A. | nicht auf ContentDB gefunden | ohne ContentDB-Release kein Pin mit Release-ID, nicht empfohlen [H für Suche, M für Folgerung] |
| Backrooms Test, Glitch, Lazarr!, Tutorial | div. | div. | | | hoch | Backrooms ist Horror (ausschließen); Glitch, Lazarr, Tutorial sind laut Tags Einzelspieler |

### A.2 Laufen unsere Server-Mods unverändert?

Quelltext-Scan aller `.lua`-Dateien der Release-Zips (Mineclonia 39338, VoxeLibre 39534, Minetest Game 38214, Repixture 38512, NodeCore 39354, Exile 39408, Skyblock Zero 38447, Hades 38926, Age of Mending 38692) am 22.10.2026 [H]:

- Kein Spiel registriert einen eigenen `register_authentication_handler`. SRP-Provisionierung per `core.set_player_password` und unser Auth-Pfad bleiben gültig.
- Kein Spiel überschreibt `core.disconnect_player`, `core.kick_player`, `core.chat_send_player`, `core.register_on_prejoinplayer` oder `core.set_player_password`. Unsere Prejoin-Sperre, Warnungen und Trennung wirken in allen geprüften Spielen.
- `request_insecure_environment` nutzen Mineclonia (nur Polyfill vor 5.13, fällt sauber zurück), VoxeLibre (`vl_trusted`), Exile (Map-Migration, übergibt bei Ablehnung `nil`) und Skyblock Zero (`modlib`). Bei uns bleibt `secure.trusted_mods` leer, die Aufrufe liefern `nil`. Start ohne Vertrauen muss je Spiel im Spike bestätigt werden, besonders Exile und Skyblock Zero. [H Code, L Laufzeit]
- `request_http_api` nutzt Skyblock Zero (Lua-Controller). Bei leerem `secure.http_mods` bleibt das aus, also kein Netzverkehr aus der Welt. [H]
- Rechtevergabe durch Spiele: Skyblock Zero setzt bei jedem Join `tp` und `home`; Exile und NodeCore ändern Rechte nur im Tutorial bzw. per Admin-Befehl. Für Skyblock Zero heißt das: Kinder können sich zu Mitspielenden teleportieren. In einer privaten Familienwelt vertretbar, im Preset dokumentieren. [H]
- Eigene Kicks der Spiele: NodeCore kickt Clients unter Protokoll 43 (5.8), Mineclonia kickt bei fehlerhaften Modchannel-Nachrichten. Beides kollidiert nicht mit unserer Logik; unser Event-Log sollte "vom Spiel getrennt" als eigenen Grund kennen. [H]

### A.3 Mehrspieler-Stabilität und Größe

- Mineclonia beschreibt sich im README als Fork von VoxeLibre "with focus on stability, multiplayer performance and features". [H] Für Familienwelten ist es damit die naheliegende Ergänzung oder sogar die bessere Wahl als VoxeLibre; ein direkter RAM-Vergleich fehlt (Spike: gleiche Messung wie bei VoxeLibre, dort bis 501 MiB beim Generieren).
- Image-Größe: Alle Presets landen im ExApp-Image. Heute 87 MB (VoxeLibre + MTG). Mit Mineclonia, Repixture und NodeCore plus rund 65 MB, also gut 150 MB Spieldaten. Vertretbar; Asuna (91 MB) und Lazarr (89 MB) wären teuer.
- Repixture setzt Luanti 5.13 voraus, alle anderen 5.8 bis 5.10. Bei einem späteren Luanti-Upgrade zuerst die `max_minetest_version` aller Presets prüfen.

### A.4 Sichere Installation (Empfehlung)

Das vorhandene Muster (`scripts/fetch-games.sh`, `vendor/games/SHA256SUMS`, Konstante `game_sha256` in `presets.py`, Prüfung in `archive.py`) ist richtig und wird nur erweitert:

1. Pin auf **ContentDB-Release-ID plus SHA-256 plus Git-Commit** (die API liefert `commit` je Release, z. B. Mineclonia 0.124.0 = `20d5bbca48ff...`). So lässt sich jedes Zip gegen das Quell-Repo nachbauen.
2. Download nur beim Image-Bau bzw. Dev-Setup, nie zur Laufzeit. Begründung: keine Abhängigkeit von ContentDB, kein Datenabfluss von Heimservern, keine Supply-Chain-Lücke über Updates.
3. Vor Aufnahme jedes Spiels: Lua-Scan wie in A.2 (Skript ins Repo übernehmen und in CI gegen jedes neue Zip laufen lassen), `settingtypes.txt` sichten, Lizenzdateien im Zip vorhanden.
4. Zur Laufzeit: `secure.trusted_mods` und `secure.http_mods` leer, `secure.enable_security = true`, keine ContentDB-Installation durch Nutzer (bleibt Out of Scope).
5. Attribution: CC-BY(-SA)-Medien verlangen Namensnennung. Eine Seite "Mitgelieferte Spiele und Lizenzen" in der ExApp und im README, Lizenzdateien bleiben im Zip.
6. Updates bewusst: neue Release-ID, Prüfsumme und Konstante gemeinsam ändern; Welt-Migration (alte Welt, neues Spiel) im Spike testen.

**Aufwand je Luanti-Preset:** 0,5 bis 1,5 Tage (Pin, Schalter, Prejoin-/Zeit-E2E mit dem UDP-Prober, RAM-Messung, Kinder-Text). [M]

---

## Teil B: Andere Spiele

### B.1 Ausgeschlossen (kurz)

| Spiel | Grund |
|---|---|
| Teeworlds, Xonotic, Red Eclipse, OpenArena | Shooter; Teeworlds zudem letztes Release 0.7.5 von 04/2020 [H] |
| Hedgewars, Battle for Wesnoth, Freeciv, 0 A.D., Unciv | Kriegsthema; Unciv ist rundenbasiert-asynchron (HTTP-Dateiserver mit `authV1`), Spielzeitfenster greifen dort nicht sinnvoll [H Code]; 0 A.D.-GitHub-Spiegel archiviert [H] |
| Space Station 14 | Erwachsenenthemen, große Spielerzahlen |
| Cuberite | letztes Release "1.7EOL" 2019, braucht Minecraft-Client [H] |
| Pixel-Dungeon-Varianten | Einzelspieler, kein Dedicated Server |
| ClassiCube + MCGalaxy | technisch reizvoll (Browser-, iOS-, Android-Client, MCGalaxy GPL-3.0, Release 1.9.5.3 03/2025), aber der Client lädt beim ersten Start Assets von minecraft.net und das Spiel imitiert Minecraft Classic: Markennähe wie bei Minecraft, nur ohne dessen Reichweite. Beobachten, nicht bauen. [H README] |

### B.2 Kandidaten im Detail

#### SuperTuxKart (Rennspiel)

1. **Lizenz:** Code GPL-3.0+, Daten gemischt (GPL, CC-BY, CC-BY-SA, Public Domain, je Ordner `licenses.txt`) laut `COPYING` [H]. Weitergabe im Image zulässig, Attribution nötig. Kein offizielles Docker-Image; nur alte Community-Images (alexbabel 1.3, vor ca. 4 Jahren) [M]. Server-only-Build per `-DSERVER_ONLY=ON` [H]. Aktiv: 1.5 vom 20.10.2025, Commits bis 17.10.2026 [H].
2. **Zugang:** LAN-Modus ohne Konten mit **einem** Serverpasswort (`private-server-password`); WAN-Modus prüft Online-Konten von stk-addons (externer Dienst) und kennt Bann-Tabellen nach `online_id`. Keine Whitelist, keine Passwörter pro Spieler, Spielernamen im LAN frei wählbar [H `NETWORKING.md`, `server_lobby.cpp:2784`]. Sichere Zuordnung Nextcloud-Konto zu Spieler geht nur mit eigenem Patch.
3. **Durchsetzung:** Kein Server-Plugin-API (AngelScript gibt es nur für Strecken). Netzwerkkonsole per stdin mit `kick`, `kickban`, `kickall`, `listpeers` [H `network_console.cpp`], aber kein Befehl für Servernachrichten an Spieler. SQLite-Statistik mit Verbindungszeiten und "Live-Kick" über Bann-Tabelle (Prüfung pro Minute) [H]. Chat abschaltbar (`chat=false`). Warnungen 10/5/1 min nur mit Patch.
4. **Ports/Clients:** UDP 2759, Discovery UDP 2757 [H]. Server laut Doku ca. 60 MB RAM bei 8 Spielern auf Raspberry Pi 3 [H]. Clients: Windows, macOS, Linux, Android, iOS (seit Ende 2025, nicht vom STK-Team gelistet) [M], Switch-Port im Repo. Version: Client und Server sollten zueinander passen; Kompatibilität über Minor-Versionen nicht geprüft [L].
5. **Kinder:** Google Play "USK ab 0", 1 Mio.+ Downloads [H, Abruf 22.10.2026]; App Store 4+ [M]. Sehr beliebt bei Grundschulkindern [L].
6. **Aufwand:** 10 bis 15 Tage (eigenes Image mit Source-Build und Daten, C++-Patch für Allowlist-Datei mit Passwort pro Spieler und Servernachrichten, Konsole-Anbindung, Fork-Pflege). **Risiko:** dauerhafte Fork-Pflege in C++, Image groß (Strecken-Daten), iOS-Client nicht offiziell.

#### Mindustry (Fabrik plus Tower-Defense)

1. **Lizenz:** GPL-3.0, Assets im Repo [H Repo-Lizenz; getrennte Asset-Lizenz nicht gefunden, L]. Release v160.7 vom 08.10.2026 mit `server-release.jar` (19 MB) [H]. Kein offizielles Docker-Image (eigenes aus JRE + Jar trivial) [M].
2. **Zugang:** eingebaute Whitelist auf Client-UUID plus server-spezifische USID; unbekannte Spieler bekommen "You are not whitelisted here." und das Server-Log zeigt die UUID [H `NetServer.java:228`]. UUID sind 8 Zufallsbytes, lokal beim Client gespeichert [H `Platform.java`]. Kopplungscode-Flow wie bei Minecraft-Plan möglich: Plugin weist ab und zeigt Code, Kind trägt ihn in Nextcloud ein, ExApp schreibt UUID in die Regeldatei.
3. **Durchsetzung:** Java-Server-Plugins mit Events (Connect, Join, Leave, Chat) und Dateizugriff, Konsole mit `kick`, `pause`, `say`, `whitelist`, `ban` [H `ServerControl.java`]. Regeldatei-Muster 1:1 übertragbar. Risiko: `socketInput` öffnet einen TCP-Befehlsport (Default aus, muss aus bleiben); Konsolenbefehl `js` führt beliebiges JavaScript aus, darf nie an Kinder durchgereicht werden.
4. **Ports/Clients:** 6567 TCP und UDP [M]. RAM ca. 200 bis 500 MB [L]. Clients: Windows, macOS, Linux (Steam/itch), Android (Play, F-Droid, Flathub), iOS (1,99 USD) [M]. **Client- und Server-Build müssen exakt passen** (`clientOutdated`/`serverOutdated`, `NetServer.java:283`) [H]; mobile Clients aktualisieren automatisch, der Server muss zeitnah folgen.
5. **Kinder:** Google Play "USK ab 6", 5 Mio.+ Downloads [H]; App Store 13+ (Waffen, Fantasy-Gewalt) [M]. Komplex, eher ab 10.
6. **Aufwand:** 8 bis 12 Tage (Engine-Abstraktion geteilt mit Minecraft, Java-Plugin, Pairing, E2E). Synergie: gleiche JVM/Gradle-Kette wie das geplante Paper-Plugin. **Risiko:** Versionskopplung, Waffen-Bewertung im App Store.

#### OpenTTD (Verkehrs-Wirtschaftssimulation)

1. **Lizenz:** GPL-2.0, freie Basissets OpenGFX/OpenSFX/OpenMSX [M]. Stabil 15.3 vom 04.04.2026, 16.0-beta4 vom 20.09.2026 [H]. Docker nur Community (`ropenttd/docker_openttd`, letzter Push 01/2025) [H]; eigenes Image aus offiziellem Linux-Build plus OpenGFX.
2. **Zugang:** beste eingebaute Lösung im Feld: `server_authorized_keys` (X25519-Client-Schlüssel) als Allowlist, zusätzlich Firmen-Allowlists; Konsolenbefehl `authorized_key add server <key>` bzw. `client:<id>` [H `network_server.cpp`, `console_cmds.cpp`, `network_crypto.cpp`]. Pairing: ExApp setzt kurzzeitig ein Einmal-Serverpasswort, Kind verbindet sich einmal, ExApp übernimmt dessen Schlüssel und löscht das Passwort [M, Entwurf].
3. **Durchsetzung:** Dedicated Server (`-D`) liest Konsole von stdin; Befehle `kick`, `pause`, `say` [M]. Admin-Port (TCP 3977, mit `admin_authorized_keys`) liefert Join/Quit-Events und Chat und nimmt Befehle an. GameScript kann nicht kicken. Admin-Port nur im Container bzw. internen Netz, nie veröffentlichen.
4. **Ports/Clients:** 3979 TCP und UDP [M]. RAM ca. 100 bis 300 MB [L]. Clients: Windows, macOS, Linux (auch Steam), Android nur inoffizieller Port, kein iOS [M]. Versionen müssen zusammenpassen [M].
5. **Kinder:** gewaltfrei, aber anspruchsvoll, eher ab 10; Nische ("Eisenbahn-Kinder") [L].
6. **Aufwand:** 7 bis 10 Tage (eigenes Image, Konsolen-/Admin-Brücke als kleiner Agent im Container, Pairing). **Risiko:** stdin-/Admin-Brücke ist neues Muster (bei Luanti reicht ein Mod), keine Tablets.

#### OpenRCT2 (Freizeitpark)

1. **Lizenz:** GPL-3.0, v0.5.6 vom 10.10.2026, offizielles Image `openrct2/openrct2-cli` (Tags 0.5.6, latest) [H]. **Braucht die Originaldateien von RollerCoaster Tycoon 2** auf Server und Client (Steam/GOG) [H README]. Die dürfen nicht ins Image; Eltern müssten sie selbst hochladen, jedes Kind braucht eine Kopie.
2. **Zugang:** `known_keys_only` (Spieler-Schlüssel), Gruppen mit Rechten, Plugin-Hook `network.authenticate` mit `publicKeyHash` und `cancel` [H `Config.cpp`, `openrct2.d.ts`].
3. **Durchsetzung:** Server-Plugins (JS) mit `network.join/leave/chat`, `kickPlayer`, `sendMessage` an einzelne Spieler, `pausetoggle` [H]. Kein Datei-API im Plugin; Regeldatei nur über `plugin.store.json` beim Start oder lokale Sockets, live ungeklärt [M].
4. **Ports/Clients:** 11753 TCP [L]. Clients Windows, macOS, Linux; Android nur inoffiziell [L].
5. **Kinder:** gewaltfrei, sehr kindgerecht [M].
6. **Aufwand:** 6 bis 9 Tage plus Upload-Flow für Originaldaten. **Risiko:** Kauf- und Datenhürde, rechtlich sauber nur bei BYO-Daten.

#### Veloren (Voxel-RPG)

1. **Lizenz:** GPL-3.0, v0.18.0 vom 23.01.2026, Repo aktiv (21.10.2026) [H]. Docker-Compose im Repo, kein ARM [M].
2. **Zugang:** Standard-Auth über `auth.veloren.net` (externes Konto), Whitelist und Banlist als Dateien, `auth_server_address: None` hebt jede Anmeldung auf [H `settings/mod.rs`, M Wiki]. Eigener Auth-Server wäre nötig, um ohne Fremddienst zu bleiben.
3. **Durchsetzung:** Server-CLI mit Admin-Befehlen; WASM-Plugins experimentell [L]. Positiv: `banned_words_files` und `automod` für Chat, `battle_mode` PvE [H].
4. **Ports/Clients:** 14004 TCP/UDP, Query 14006, Metrik 14005 [H/M]. RAM eher 1 bis 3 GB [L]. Nur Desktop-Clients, Version eng gekoppelt [M].
5. **Kinder:** Fantasy-Kampf, Alpha-Spiel [M].
6. **Aufwand:** 10 bis 15 Tage. **Risiko:** RAM, Fremd-Auth, Plugin-API instabil.

#### DDNet (kooperatives Jump-and-Run auf Teeworlds-Basis)

1. **Lizenz:** zlib-artig für Code, Daten CC-BY-SA-3.0 [H `license.txt`]. Sehr aktiv (Commits 21.10.2026) [H].
2. **Zugang:** nur ein Serverpasswort (`password`), Rcon-Stufen per Passwort, keine Allowlist pro Spieler [H `config_variables.h`].
3. **Durchsetzung:** Rcon und Econ (TCP-Telnet mit Passwort, Default aus); keine Plugin-API [H]. Waffen (Hammer, Granate) aus Teeworlds.
4. **Ports:** UDP 8303 [H]. Desktop, Android [L].
5. **Kinder:** Spieler-Communities rau, Mechanik schwer; private Welt ohne Fremde wäre ok.
6. **Aufwand:** 8 bis 12 Tage inkl. Patch für Allowlist. **Fazit:** nicht priorisieren.

### B.3 Querschnitt: was sich gegenüber Luanti ändert

- **Engine-Abstraktion** (einmalig 2 bis 3 Tage, siehe MINECRAFT-V2.md 4): Image, Command, Ports (TCP/UDP gemischt), Datenpfad, Labels, Presets, RAM-Bedarf. Danach kostet jede Engine nur noch ihr Durchsetzungs-Modul.
- **Durchsetzungs-Modul je Engine** nach unserem Muster: root-eigene Regeldatei im Volume, Prüfung beim Join, Warnungen, Kick, Zählbuch, Events als JSON-Lines im Volume. Wo die Engine kein Mod-/Plugin-API mit Dateizugriff hat (STK, OpenTTD, DDNet), braucht es einen Agenten im Container, der Konsole und Datei verbindet. Kein RCON und kein Admin-Port nach außen.
- **Konto-Kopplung:** überall außer Luanti per Kopplungscode, weil die Clients eigene IDs oder Schlüssel mitbringen (Mindustry-UUID, OpenTTD-/OpenRCT2-Schlüssel).
- **Versionskopplung:** Luanti ist tolerant, Mindustry und Veloren verlangen exakt passende Builds. Bei Engines mit Auto-Update-Clients muss Gameworld Server-Updates schnell ausliefern.

---

## Ranking (Fit-Score 0 bis 10)

Gewichtung: Zugangskontrolle pro Spieler und Durchsetzbarkeit 40 %, Kinder-Eignung und Beliebtheit 25 %, Aufwand und Pflege 20 %, Geräte und Ressourcen 15 %. Wertung [M], Aufwand [L].

| Rang | Kandidat | Fit | Aufwand | Kurzbegründung |
|---|---|---|---|---|
| 1 | Luanti: Mineclonia | 9,5 | 1 bis 1,5 T. | höchster ContentDB-Score, Multiplayer-Fokus, alle Mods laufen, kleiner als VoxeLibre |
| 2 | Luanti: Repixture | 8,5 | 1 T. | eigenständig, friedlich, aktiv (Wuzzy), AGPL wie Gameworld |
| 3 | Luanti: NodeCore | 7 | 0,5 bis 1 T. | MIT, winzig, Knobelspiel für Ältere |
| 4 | Mindustry | 7 | 8 bis 12 T. | Whitelist + Plugin-API + Mobil-Clients; Build-Kopplung, App Store 13+ |
| 5 | OpenTTD | 6,5 | 7 bis 10 T. | kryptografische Allowlist eingebaut, gewaltfrei; keine Tablets, Brücke nötig |
| 6 | SuperTuxKart | 6 | 10 bis 15 T. | höchste Kinder-Attraktivität, USK 0; ohne C++-Patch keine sichere Zugangskontrolle |
| 7 | Luanti: Age of Mending, Skyblock Zero, Hades Revisited | 5 bis 6 | je 1 T. | brauchbar, aber Alpha bzw. Rechte-/Mapgen-Eigenheiten |
| 8 | OpenRCT2 | 5,5 | 6 bis 9 T. + Daten-Flow | beste Plugin-API, aber Originaldaten Pflicht |
| 9 | Veloren | 4 | 10 bis 15 T. | RAM, Fremd-Auth, nur Desktop |
| 10 | DDNet | 3,5 | 8 bis 12 T. | nur Serverpasswort, Waffen |
| aus | Exile, Backrooms Test, MeseCraft, Shooter, Kriegsspiele | 0 bis 3 | | siehe oben |

## Empfehlung nach v1

1. **v1.x (direkt nach Store-Release):** Presets Mineclonia (z. B. "Abenteuer (sanft, schneller)" oder Ersatz für VoxeLibre nach RAM-Vergleich) und Repixture ("Bauernhof und Dorf, friedlich"). NodeCore als "Knobeln (ab 10)". Zusammen 3 bis 4 Tage, null neue Angriffsfläche.
2. **Lua-Scan-Skript in CI** für jedes neue Spiel-Zip (A.2) als Qualitätsgate.
3. **v2 Engine-Abstraktion** gemeinsam mit Minecraft (Paper) planen; als zweite Fremd-Engine **Mindustry**, weil sie dieselbe JVM-/Plugin-Kette nutzt und Tablets erreicht.
4. **SuperTuxKart nur bei klarer Nachfrage** in der Umfrage, dann mit Upstream-PR für eine Allowlist-Datei statt dauerhaftem Fork (vorher bei den STK-Entwicklern anfragen).
5. OpenTTD und OpenRCT2 nur auf ausdrücklichen Wunsch (Schul-AG Wirtschaft/Verkehr).

## Fragen für die Bedarfsumfrage (Reddit, Foren, GitHub)

Kurz halten, eine Frage pro Zeile:

1. Wie alt sind die Kinder, die auf eurem Server spielen würden?
2. Auf welchen Geräten spielen sie (PC/Mac, Chromebook, Android-Tablet, iPad, Konsole)?
3. Welche Spiele spielen sie heute gemeinsam online (offene Antwort)?
4. Wenn Gameworld nur ein weiteres Spiel bekäme: Minecraft Java, SuperTuxKart, Mindustry, OpenTTD oder ein weiteres Luanti-Spiel?
5. Würdet ihr für Minecraft pro Kind eine Java-Lizenz kaufen bzw. habt ihr sie schon?
6. Wie wichtig ist, dass nur eingeladene Nextcloud-Konten spielen können (1 bis 5)?
7. Reicht euch ein gemeinsames Weltpasswort, oder wollt ihr pro Kind getrennte Zugänge und Zeitkonten?
8. Wie viel RAM hat euer Nextcloud-Server frei (unter 2 GB, 2 bis 4, 4 bis 8, mehr)?
9. Schule/Verein: Welche Spiele wären im Unterricht oder in der AG erlaubt?
10. Würdet ihr ein Spiel im Browser ohne Installation (z. B. auf Schul-iPads) einem besseren Spiel mit App vorziehen?

## Offene Punkte

- RAM und Startverhalten von Mineclonia, Repixture, NodeCore unter unseren Limits: Spike nötig (je 30 min, erst wenn RAM frei ist, nie neben Findling-Containern).
- Starten Exile und Skyblock Zero ohne `trusted_mods` fehlerfrei? Nicht geprüft.
- Mindustry: getrennte Asset-Lizenz und genaue Ports nur aus Repo-Lizenz bzw. Community abgeleitet.
- SuperTuxKart: Netzwerk-Kompatibilität 1.4/1.5 zwischen Client und Server nicht geprüft; ob STK-Entwickler eine Allowlist upstream annehmen, unbekannt.
- OpenTTD: Verhalten bei gesetzten `server_authorized_keys` ohne Serverpasswort (reine Allowlist) aus Code abgeleitet, nicht getestet.
- Browser-Weg: Spiele ohne eigenen Port, die über den HaRP-HTTP-Pfad laufen könnten (z. B. das Zeichenspiel scribble.rs, BSD-3, v0.9.14 vom 31.05.2026, Docker-Image vorhanden [H README/Release]), wären für Schul-iPads attraktiv; nicht weiter untersucht, Ergebnis der Phase 04.2 (Luanti im Browser) abwarten.

## Quellen

- ContentDB-API: https://content.luanti.org/api/packages/?type=game&sort=score&order=desc sowie `/api/packages/<autor>/<name>/` und `/releases/` je Paket (abgerufen 22.10.2026) [H]
- Release-Zips (Quelltext-Scan): https://cdn.content.luanti.org/uploads/178f406837.zip (Mineclonia 39338), b46a85c18f.zip (Repixture), 1df18de676.zip (NodeCore), 3b928a8a08.zip (Exile), 30fa39838b.zip (Skyblock Zero), ac19ac59d5.zip (Hades), df68834a9c.zip (Age of Mending) [H]
- MeseCraft: https://github.com/jeremyweston/MeseCraft (GitHub-API, Push 01.02.2026) [H]
- SuperTuxKart: https://github.com/supertuxkart/stk-code (COPYING, NETWORKING.md, src/network/network_console.cpp, src/network/protocols/server_lobby.cpp, chat_commands.cpp; Release 1.5 vom 20.10.2025) [H]; Community-Images https://hub.docker.com/r/alexbabel/supertuxkart-server [M]; App Store https://apps.apple.com/us/app/-/id6737858957 [M]; Blog https://blog.supertuxkart.net/2025/11/ [M]
- Mindustry: https://github.com/Anuken/Mindustry (server/src/mindustry/server/ServerControl.java, core/src/mindustry/core/NetServer.java, Platform.java, README; Release v160.7 vom 08.10.2026) [H]; App Store https://apps.apple.com/us/app/mindustry/id1385258906 [M]
- Google Play (USK, Downloads, Abruf 22.10.2026): https://play.google.com/store/apps/details?id=io.anuke.mindustry , https://play.google.com/store/apps/details?id=org.supertuxkart.stk , https://play.google.com/store/apps/details?id=net.minetest.minetest (Luanti Android: USK ab 12) [H]
- OpenTTD: https://github.com/OpenTTD/OpenTTD (src/settings.cpp, src/network/network_server.cpp, network_crypto.cpp, console_cmds.cpp, src/table/settings/network_secrets_settings.ini; Releases 15.3, 16.0-beta4) [H]; https://github.com/ropenttd/docker_openttd [H]
- OpenRCT2: https://github.com/OpenRCT2/OpenRCT2 (readme.md, src/openrct2/config/Config.cpp, distribution/scripting/openrct2.d.ts; Release v0.5.6) [H]; https://hub.docker.com/r/openrct2/openrct2-cli [H]
- Veloren: https://gitlab.com/veloren/veloren (server/src/settings/mod.rs, Releases v0.18.0) [H]; https://book.veloren.net/players/server-hosting/on-docker.html , https://wiki.veloren.net/wiki/Hosting_a_Server [M]
- DDNet: https://github.com/ddnet/ddnet (src/engine/shared/config_variables.h, license.txt) [H]
- Unciv: https://github.com/yairm210/Unciv (server/src/com/unciv/app/server/UncivServer.kt) [H]
- ClassiCube: https://github.com/ClassiCube/ClassiCube (readme.md) ; MCGalaxy: https://github.com/ClassiCube/MCGalaxy [H]
- scribble.rs: https://github.com/scribble-rs/scribble.rs (README, Release v0.9.14) [H]
- Weitere Repo-Metadaten (Lizenz, Push, Releases) per GitHub-API am 22.10.2026: teeworlds/teeworlds, hedgewars/hw, wesnoth/wesnoth, freeciv/freeciv, 0ad/0ad, space-wizards/space-station-14, cuberite/cuberite [H]
