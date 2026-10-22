# Recherche: Meilenstein "Gameworld für Schulen und Klassen"

**Modus:** Ecosystem + Feasibility
**Recherchiert:** 22.10.2026 (nur Web-Recherche, ContentDB-API, Nextcloud- und Luanti-Quelltext gelesen; kein Docker, kein Code geändert)
**Urteil:** BEDINGTES GO, als eigener Meilenstein NACH dem v1-Store-Release, Start erst mit einem festen Pilotpartner
**Konfidenz gesamt:** MEDIUM (Technik und Mod-Lage im Original geprüft; Markt in DE und Lastwerte für 30 Spieler nur teilweise belegt)

Konfidenz-Markierung: [H] = HIGH, Originalquelle oder Quelltext gelesen; [M] = MEDIUM, mehrere Quellen oder Doku plus Ableitung; [L] = LOW, Einzelquelle, Training oder Schätzung, unverifiziert.

---

## 1. Kurzfazit und Empfehlung

**Empfehlung: bedingtes Go.**

- Gameworld passt fachlich gut zu Schulen: Luanti ist frei, braucht keine Konten bei Dritten, Daten bleiben auf dem Server der Schule bzw. des Schulträgers. Das ist genau die Lücke neben Minecraft Education (Microsoft-Konto, Lizenzkosten, uneinheitliche Datenschutzlage). [M]
- Viel ist schon gebaut: Einladung über NC-Gruppen, serverseitige Whitelist, Welt-Zeitfenster (ZEIT-05), Pause, Talk-Raum, ROLLE-03/04 geplant. Der Schul-Meilenstein ist zum großen Teil Ausbau, kein Neubau. [H, eigener Code/Requirements]
- Aber: der Zielmarkt ist kleiner als "alle Schulen". Landesplattformen (ByCS Bayern, LOGINEO NRW, Niedersächsische Bildungscloud) sind zentral betrieben; dort installiert keine Schule eine ExApp mit Docker-Zugriff. Realistisch sind Schulträger und Medienzentren mit eigener Nextcloud (Beispiel Medienzentrum Wiesbaden, UCS@school-Träger Chemnitz/Fulda), Privatschulen, Vereine und Jugendarbeit (Teckids, CoderDojo). [M]
- Ein harter technischer Befund: **ROLLE-03 funktioniert in der heutigen Form für Nicht-Admins nicht vollständig.** Gameworld prüft Konten und Gruppen per OCS im Namen des handelnden Verwalters. Nextcloud gibt Kontodaten anderer Nutzer nur an Admins, delegierte Admins und Gruppenadmins (Subadmins) heraus, Gruppenmitglieder nur an Admins, Subadmins der Gruppe oder Mitglieder der Gruppe. Eine Lehrkraft ohne diese Rechte kann also keine Schülerkonten einladen. [H, NC-32-Quelltext]
- Bedingungen für das Go:
  1. v1 ist im Store und stabil (Phase 6 abgeschlossen).
  2. Ein Pilotpartner (Schule, Medienzentrum oder Verein mit eigener Nextcloud) sagt verbindlich zu und testet in echten Stunden.
  3. Ein Lasttest zeigt, dass eine Welt mit 30 Spielern im Ressourcenrahmen eines Schulträger-Servers stabil läuft (heute nicht belegt, max_users ist fest 8).
  4. Lehrkräfte-Rolle wird mit sauberem Einladungs-Umfang gebaut (Subadmin/Mitgliedschaft), nicht nur als Gruppenliste.

---

## 2. Markt und Bedarf

### 2.1 Luanti in Schulen heute

- luanti.org/education nennt Projekte vor allem aus Frankreich (Minestory Dijon seit 2019, über 600 Grundschulkinder in 30 Klassen; Urbanismus-Projekte UNEJ, Maubeuge en Cubes), Kanada (UBC Minetest Classroom) und Südafrika. [H]
- Hosting-Angebot in DE: **BLOCKALOT** des Landesmedienzentrums Baden-Württemberg: "A dashboard to create worlds for future-oriented learning without hosting servers", Support DE/EN/FR, Wiki, Workshops, derzeit kostenlos. [M: nur luanti.org bestätigt, blockalot.de war per TLS nicht abrufbar]
  - Folge: Für Schulen ohne eigenen Server ist BLOCKALOT die naheliegende Wahl. Gameworld zielt auf Schulen und Träger, die ihre Nextcloud schon betreiben und Daten im eigenen Haus wollen. Eher Partner als Gegner. [M]
- Weitere DE-Server: Friedrich-Verlag-Material empfiehlt für dauerhafte Welten die Server der Akademie Wittenberg oder des LMZ BW "auf Anfrage". [M, Suchtreffer-Auszug]
- MinetestEDU/EduLuanti: ursprünglich französisches Projekt (IRI), NLnet-gefördert 2024-02 bis 2025-06, Code auf forge.apps.education.fr. [H] Die deutschsprachige Wiki-Seite MinetestEDU bzw. LuantiEDU ist unvollständig und sagt selbst: "noch keine guten Hosting-Anbieter" für schnelles Aufsetzen, Mods brauchen meist Konsolenzugang. [H]
  - Genau diese Hürde nimmt Gameworld (One-Click, keine Konsole). [M]
- Teckids e.V.: Jugendverband für Freie Software (Projekt schul-frei), lädt bei CCC-Kongressen 2024/2025 Kinder ab 9 zu Luanti und Mods ein. Eigener Teckids-Luanti-Server nicht belegt. [M]
- Bildungs-Community: inoffizieller Luanti-Edu-Discord, Kontakt education@luanti.org, ContentDB-Tag "education" (über 80 Pakete). [H]

### 2.2 Wettbewerber Minecraft Education

- Lizenz 5,04 USD pro Nutzer und Jahr für Schulen, 36 USD für Vereine/Camps; braucht Microsoft-365-Konto; in M365 Education A3/A5 enthalten. Siehe MINECRAFT-V2.md 1.3. [H, Stand 21.10.2026]
- Dedicated Server existiert, ist aber an den M365-Tenant gebunden, Download hinter Admin-Login. Für Gameworld kein Ziel (Entscheid in MINECRAFT-V2.md). [H]
- Datenschutzlage in DE uneinheitlich:
  - DSK-Festlegung 24.11.2022: Nachweis eines datenschutzkonformen Betriebs von Microsoft 365 auf Basis des Datenschutznachtrags vom 15.09.2022 "kann nicht geführt werden". [H]
  - LfDI Baden-Württemberg 2021/2022: rät nach Pilot vom Einsatz an Schulen ab, Schulen sollten Nutzung beenden oder Konformität nachweisen. [M]
  - HBDI Hessen 15.11.2025: Microsoft 365 in Hessen unter Bedingungen datenschutzkonform nutzbar. [M, mehrere Fachmedien]
  - Hannover plant Microsoft-Produkte an 100 Schulen ab 2026/27. [L, Tagesspiegel-Auszug, Paywall]
- Folgerung: Für Schulen in BW und Ländern mit kritischer Linie bleibt ein Microsoft-freies Angebot attraktiv; das Argument "keine Konten bei Dritten" trägt, "Microsoft verboten" darf Gameworld nicht behaupten. [M]
- Lehrkräfte kennen aus Minecraft-Education-Welten Einfrieren, Stummschalten und Herholen (Classroom Mode, frühere MinecraftEdu-Schalter "Freeze Students", "Mute Students"). Das ist die Erwartungslatte für Klassensteuerung. [M]

### 2.3 Nextcloud in Schulen und wie Lehrkräfte dort abgebildet sind

- **Landesplattformen (für Gameworld kaum erreichbar):**
  - ByCS Bayern: zentrale Plattform mit "Drive", seit 2025 im Regelbetrieb, zentrale Benutzerverwaltung. Technische Basis Nextcloud nicht belegt. [M]
  - LOGINEO NRW: Betrieb beim KRZN, "Bildungscloud" mit Quoten 3 GB Lehrkraft / 1 GB Schüler. Nextcloud als Basis nicht belegt. [M]
  - Niedersächsische Bildungscloud: eigenständiges LMS, Nextcloud-Anbindung nicht belegt. [M]
  - openDesk Edu (Bund): Juli 2026 um ILIAS und OpenProject erweitert, Nutzerverwaltung über Nubus. Ob Nextcloud-ExApps dort installierbar sind: nicht gefunden. [L]
  - Folgerung: Zentral betriebene Plattformen erlauben Schulen keine eigenen Apps mit Docker-Zugriff. Kein Zielkanal für v1 des Schul-Meilensteins. [M]
- **Schulträger und Medienzentren mit eigener Nextcloud (Zielgruppe):**
  - Medienzentrum Wiesbaden betreibt Nextcloud "auf eigener Hardware" im Wiesbadener Rechenzentrum für Lehrkräfte und Schüler; neue Funktionen nur auf Antrag einer Schule; Talk optional zuschaltbar; Verwaltungshandlungen für Lehrkräfte ausgeschlossen. [H]
  - UCS@school (Univention): Klassen und Arbeitsgruppen werden als Gruppen nach Nextcloud übernommen, Beispielname "School1-1a"; Einsatz in Chemnitz und Fulda (Blog 2019, alt). [H für Text, L für heutigen Stand]
  - regio iT "ucloud4schools" (Aachen), 3.000 Nutzer (Nextcloud-Referenz, alt). [L]
  - Lehrerfortbildung BW (ZSL) schult "Cloudsysteme für die Schule am Beispiel Nextcloud" inkl. Administration; Material zu Gruppen für Lehrkräfte, Klassenstufen, Fachschaften und Gruppenordnern. [H für Existenz, M für Inhalt]
- **Abbildung der Lehrkräfte:** typischerweise eine Gruppe "Lehrer/Lehrkräfte" aus LDAP (paedML, linuxmuster.net, UCS@school) plus Klassengruppen; Lehrkräfte sind in der Regel KEINE NC-Admins, teils Gruppenadmins. [M]
- **Nextcloud-Gruppenadmins (Subadmins):** dürfen Konten ihrer Gruppen anlegen, ändern, entfernen, aber keine bestehenden Nutzer in ihre Gruppen aufnehmen und keine Systemeinstellungen sehen. Zuweisung in der Benutzerverwaltung, Spalte "Gruppenadmin". [H]

---

## 3. Rollen: Lehrkraft ohne Nextcloud-Admin

### 3.1 Was Nextcloud einem Nicht-Admin erlaubt (NC 32, Quelltext provisioning_api)

| OCS-Aufruf | Erlaubt für | Folge für Gameworld |
|---|---|---|
| `GET /cloud/users/{id}` (fremdes Konto) | Admin, delegierter Admin, Subadmin mit Zugriff auf das Konto; sonst `null` → 404 | Einladung eines Schülers durch eine "nackte" Lehrkraft scheitert als "Konto unbekannt" |
| `GET /cloud/groups/{gid}/users` | Admin, delegierter Admin, Subadmin der Gruppe, **Mitglied der Gruppe** | Klasse einladen geht nur, wenn die Lehrkraft Subadmin oder Mitglied der Klassengruppe ist |
| `GET /cloud/users/{id}/subadmins/details` | das Konto selbst, Admin, delegierter Admin | Gameworld kann die Subadmin-Gruppen der Lehrkraft selbst abfragen (vorhanden in stable30, 31, 32) |
| `GET /cloud/users/{id}/subadmins`, `GET /cloud/groups/{gid}/subadmins` | nur Admin-Einstellung "Users" | nicht nutzbar für Lehrkräfte |

[H, Quelltext stable32; Routen in stable30/31 gegengeprüft]

- Der Kommentar in `src/gameworld/access/directory.py` ("Gruppen löst nur ein Admin auf") ist zu eng: auch Subadmins und Mitglieder der Gruppe dürfen. Das ist die Grundlage für eine saubere Lehrkräfte-Rolle. [H]

### 3.2 Empfohlenes Rollenmodell (passt zu ROLLE-03/04)

- **Wer ist Lehrkraft (Verwalter):** Mitglied einer vom NC-Admin eingestellten Verwalter-Gruppe (ROLLE-03, z. B. "lehrkraefte"). [H, Requirement]
- **Was darf sie einladen (neu, Kern des Schulmodus):** nur Gruppen, in denen sie Subadmin oder Mitglied ist, und nur Konten, die Nextcloud ihr selbst zeigt. Gameworld fragt dafür Nextcloud im Namen der Lehrkraft und übernimmt damit die Rechte, die die Schule in Nextcloud ohnehin gepflegt hat. Keine eigene Rechteverwaltung. [M, Ableitung aus 3.1]
- **Was sieht sie:** nur eigene Welten und Welten, in die sie als Mit-Lehrkraft eingetragen ist (Welt-Besitzer, bisher v2-Mandantenmodell). Ohne das sieht jede Lehrkraft alle Welten aller Kolleginnen. [M]
- **Nicht** der Weg: Gameworld fragt Nextcloud im Namen eines Admin-Kontos und prüft Rechte selbst. Technisch möglich (AppAPI erlaubt der ExApp, im Namen beliebiger Konten zu handeln), aber dann trägt Gameworld die volle Verantwortung für den Umfang, und jeder Fehler legt das ganze Schülerverzeichnis offen. Nur als bewusst begründete Ausnahme für den Hintergrund-Abgleich. [M]
- **Hintergrund-Abgleich der Gruppen** (dynamische Einladungen) muss im Namen der besitzenden Lehrkraft laufen. Verliert sie das Recht (Schuljahreswechsel), meldet der Abgleich eine Störung statt Zugänge stillschweigend zu entfernen; das Verhalten (403 = Störung, nie leere Gruppe) ist schon so gebaut. [H, Code]
- **ROLLE-04 "Erwachsen":** passt direkt für Lehrkräfte und Begleitpersonen im Spiel (frei von Welt-Zeitfenster und Pause, nicht im Rückblick, keine Luanti-Adminrechte). [H, Requirement]
- **Offener Zielkonflikt:** Lehrkräfte wollen im Spiel herholen, fliegen, teleportieren. ROLLE-04 verbietet Luanti-Adminrechte für Erwachsene. Empfehlung: Steuerung über die Gameworld-Oberfläche (Tablet/Lehrer-PC), im Spiel höchstens `fly`, `fast`, `teleport` für markierte Lehrkräfte, niemals `privs`, `server`, `ban`, `give`. Owner-Entscheid nötig. [M]

---

## 4. Unterrichtssteuerung in Luanti

### 4.1 Bordmittel der Engine (Luanti 5.17, lua_api.md gelesen)

- Privilegien: `shout` = Chat; `interact` = bauen, abbauen, mit Spielern interagieren ("Players without the interact privilege can only travel and observe the world"); `fly`, `fast`, `noclip`, `teleport`, `bring`. [H]
  - Stummschalten = `shout` entziehen; Bauen sperren = `interact` entziehen. [H]
- Einfrieren: keine Engine-Funktion, aber `set_physics_override` (speed, jump, gravity) plus `interact` entziehen ergibt Einfrieren. [H für API, M für Rezept]
- Herholen: `set_pos` je Spieler; Blickrichtung mit `set_look_horizontal`. [H]
- Unsichtbarer Beobachter: `set_observers` (Objekt nur an bestimmte Spieler senden) ermöglicht eine unsichtbare Lehrkraft. [H für API, L für Praxistauglichkeit]
- Trennen: `core.disconnect_player` (nutzt Gameworld schon). [H]
- Spielerdaten löschen: `core.remove_player(name)` und `core.remove_player_auth(name)`, nur wenn nicht verbunden. Wichtig für das Löschkonzept. [H]
- **Empfehlung:** eigener Welt-Mod `gameworld_class` im bestehenden Muster (Regeldatei root-eigen 0444 per put_archive, Mod liest alle paar Sekunden, Ereignisdatei zurück). Keine Privilegien an Kinder, keine Lehrkraft-Privilegien nötig. Vorteile: gleiche Sicherheitsarchitektur wie gameworld_access/gameworld_time, Steuerung auch vom Tablet. [M]

### 4.2 Mods auf ContentDB (API abgefragt 22.10.2026)

| Paket | Zweck | Lizenz | Stand | Letztes Release | Min. Engine | Urteil |
|---|---|---|---|---|---|---|
| rubenwardy/classroom | Lehrkraft-Panel: Bring, Look, Mute, Fly, Kick, Ban, Audience, Gruppen | MIT | BETA | 10.03.2026 (0.3.4, "Updated to Luanti 5.15") | 5.1 | Ideengeber, nicht einbauen: braucht Luanti-Priv `teacher` plus Kick/Ban im Spiel; UI nur sfinv/unified_inventory oder `/classroom` [H] |
| zeuner/edutest | GUI für Lehrpersonal | AGPL-3.0 | ohne Angabe | 18.07.2020 | ? | veraltet, nicht nutzen [H] |
| ShadowNinja/areas | Bereichsschutz, Parzellen | LGPL-2.1 | MAINTENANCE_ONLY | 20.09.2026 | ? | Kandidat für Bauzonen pro Gruppe [H] |
| TenPlus1/protector | Schutzblöcke | MIT / CC-BY-3.0 | ACTIVELY_DEVELOPED | 20.09.2026 | 5.0 | erklärt Support für Minetest Game und VoxeLibre; einfacher als areas [H] |
| Jeija/mesecons | Schaltkreise inkl. Luacontroller (programmierbar) | LGPL-3.0 | ACTIVELY_DEVELOPED | 09.09.2026 | 5.7 | Informatik-Unterricht, nur für Minetest-Game-Welten (VoxeLibre hat eigene Redstone-Technik) [H für Daten, L für Spielpassung] |
| BuckarooBanzay/mesecons_lab | Mesecons-Lernspiel mit Tutorials | MIT | WIP | 11.08.2026 | 5.4 | eigenes Spiel, Kandidat als Vorlage [H] |
| sfan5/worldedit | Großflächig bauen | AGPL-3.0 | ACTIVELY_DEVELOPED | 05.09.2026 | 5.0 | nur Lehrkraft, mächtig; eher weglassen [H] |
| mt-mods/lwscratch | Scratch-programmierbare Roboter | LGPL-2.1 / CC-BY-SA-3.0 | ohne Angabe | 03.01.2026 | ? | Grundschule/Unterstufe, prüfen [H] |
| giga-turbo/codeblock | Bauen per Lua-Code | AGPL-3.0 | ACTIVELY_DEVELOPED | 23.09.2026 | 5.4 | Informatik, prüfen [H] |
| Krunegan/luabots | programmierbare Lua-Roboter | MIT | ACTIVELY_DEVELOPED | 20.10.2026 | 5.12 | sehr jung (65 Downloads), beobachten [H] |
| Miney/miney | Python-Schnittstelle zum Server | LGPL-3.0+ | BETA | 26.07.2026 | 5.7 | braucht offenen Zugang zum Server, Sicherheitsprüfung nötig [H Daten, M Risiko] |
| snowyu/quiz | Quizfragen vor dem Weiterspielen | MIT | BETA | 11.07.2023 | 5.3 | Lernpfade, alt, prüfen [H] |
| Sokomine/yl_speak_up | NPC-Dialoge (Quests, Lernstationen) | MIT | BETA | 26.07.2026 | ? | Lernpfade mit NPCs [H] |
| Fhelron/spectate | unsichtbarer Zuschauer | AGPL-3.0+ | ACTIVELY_DEVELOPED | 30.05.2026 | 5.10 | jung (76 Downloads); eher eigene Lösung über set_observers [H] |
| jp/spectator_mode | Zuschauen aus Sicht anderer | WTFPL | LOOKING_FOR_MAINTAINER | 13.09.2022 | ? | nicht nutzen [H] |
| rubenwardy/accountmgr | Massenkonten mit CSV/PDF | MIT | WIP | 25.07.2022 | 5.2 | unnötig, Konten kommen aus Nextcloud [H] |

- "Kompatibel mit 5.17": ContentDB nennt bei keinem dieser Pakete eine Höchstversion; Mindestversionen liegen alle unter 5.17. Echte Funktion mit 5.17 ist damit NICHT bewiesen, nur nicht ausgeschlossen. Jede Aufnahme braucht denselben Prozess wie bei WEITERE-SPIELE.md (Release-Pin, SHA-256, Lua-Scan, Live-Test). [H für Metadaten, M für Folgerung]
- Lizenzen: MIT/LGPL sind mit der AGPL-ExApp problemlos; AGPL-Mods (worldedit, codeblock, spectate) ebenso, sie laufen ohnehin in der Welt. Medienlizenzen CC-BY/CC-BY-SA verlangen Namensnennung in der Doku. [M]

### 4.3 Geodaten (Heimatort nachbauen)

- **Arnis** (louis-e/arnis, Apache-2.0, 18,3k Sterne, Release v3.3.0 am 05.10.2026) erzeugt laut README auch Luanti-Welten aus OpenStreetMap und Höhendaten; Modi u. a. `terrain-only` und `blueprint` (Gebäude nur als Umriss zum Selbstbauen). [H]
  - Für Schulen ideal: "Baut euren Schulweg nach" auf echter Geländeform. [M]
  - Lädt OSM- und Höhendaten aus dem Netz (Overpass, Höhenkacheln); OSM-Daten stehen unter ODbL, Namensnennung "© OpenStreetMap-Mitwirkende" Pflicht. [M]
  - Welche Luanti-Spiele die Blockzuordnung bedient (vermutlich Minetest-Game-Namen über MC2MT): nicht geprüft. [L]
  - Einbau: Arnis nicht in die ExApp, sondern Vorlage einmalig erzeugen und als Welt-Archiv importieren (setzt Phase 5 Restore voraus). [M]
- geo-mapgen (Gael de Sailly, GeoTIFF/SRTM) und realterrain (bobombolo, letzte Änderung 2017) sind auf ContentDB nicht (mehr) gelistet; realterrain veraltet. [H für ContentDB-Abfrage]
- IGN Frankreich betreibt "Minetest à la carte" (minetest.ign.fr) für das französische Bildungsministerium. Vorbild, kein Angebot für DE. [M]

---

## 5. Browser-Spielen an Schulrechnern (Überblick, Details in Phase 4.2)

- **Warum es für Schulen zählt:**
  - iPads sind an deutschen Schulen verbreitet; Luanti gibt es nicht im App Store, laut Luanti-FAQ wegen Lizenzkonflikt App Store vs. (L)GPL. [H für FAQ]
  - Schulrechner: Installation oft gesperrt; Luanti für Windows gibt es aber als portables ZIP (64- und 32-bit), Android über Play und F-Droid. [H]
  - Schul-Firewalls und Jugendschutzfilter lassen oft nur HTTP(S) durch; Gameworld braucht pro Welt einen UDP-Port. Ein WebSocket-Weg über 443 löst das. [L, Erfahrungswert, nicht belegt]
- **Stand luanti-wasm:** paradust7/luanti-wasm, MIT, "experimental", letzte Änderung 17.10.2026, 137 Sterne; Standard-Proxy `wss://luanti.dustlabs.io/proxy` in Kalifornien (für Gameworld tabu, eigener Proxy nötig); Speicher im Browser über OPFS; Build nutzt einen eigenen Luanti-Fork per Commit-Pin, Versionspassung zu 5.17.0 unklar. Proxy-Projekte paradust7/lwproxy (MIT, 09/2026) und Ableger existieren. [H für Repo-Daten, L für Versionspassung und Safari/iPad-Tauglichkeit]
- Folgerung: Phase 4.2 entscheidet mit, ob der Schul-Meilenstein iPad-Klassen erreicht. Ohne Browser-Weg bleibt der Schulmarkt auf Windows/Linux/Android-Räume und offene UDP-Ports beschränkt. [M]

---

## 6. Datenschutz und Recht an Schulen in DE

- **Rechtsgrundlage:** Schulen verarbeiten Schülerdaten auf Basis Art. 6 Abs. 1 lit. e DSGVO plus Landesschulgesetz, für zusätzliche Werkzeuge oft per Einwilligung. Beispiele:
  - NRW: §§ 120 bis 122 SchulG und VO-DV I; bei digitalen Lehr- und Lernmitteln sind Protokolldaten "nur zulässig, soweit dies zum Betrieb technisch erforderlich ist" (§ 1 Abs. 1 VO-DV I). [M, Suchtreffer-Zitat]
  - Bayern: Art. 85 BayEUG plus Anlage zu § 46 BaySchO (inzwischen Anlage 1, umgebaut nach Verfahren); Einwilligung muss aktiv sein; unter 14 willigen Eltern ein, ab 14 zusätzlich das Kind; Schulleitung entscheidet im Einvernehmen mit dem Schulaufwandsträger; bei externem Dienstleister AV-Vertrag nach Art. 28 DSGVO. [H, KM Bayern]
- **Warum On-Premise hilft:**
  - Kein Drittanbieter, kein Drittlandtransfer, kein eigenes Konto bei einem Spielehersteller. [M]
  - Betreibt der Schulträger den Server, ist das meist ein AV-Verhältnis Schule zu Träger, das bei Nextcloud schon besteht; Gameworld erweitert nur die bestehende Verarbeitung. [M]
  - Gameworld selbst sendet nichts an den Entwickler (keine Telemetrie) und muss das so behalten und dokumentieren. [M]
- **Befund im Code und in Luanti:**
  - Luanti protokolliert im Standard-Loglevel `action` jeden Beitritt mit IP ("<name> [<ip>] joins game") und **jede Chatzeile** ("CHAT: ..."). [H, server.cpp 5.17.0]
  - Gameworld begrenzt die Docker-Logs auf 2 x 5 MB (spec.py), schreibt den Chat aber weiter mit. [H]
  - Das offizielle Image startet ohne `--logfile`; vermutlich schreibt der Server zusätzlich `debug.txt` ins Welt-Volume (Standard bis 50 MB). Dann landen Chatprotokolle in Phase-5-Backups in Nextcloud Files. [M, im Spike prüfen]
- **Was Gameworld an Schulen NICHT speichern soll:**
  - kein Chatprotokoll (Loglevel senken oder Chat-Zeilen filtern, debug.txt aus Backups ausschließen)
  - keine IP-Adressen über den Betrieb hinaus
  - keine Spielzeit-Historie je Schüler, keinen Tagesrückblick je Kind (an Schulen Verhaltensdaten ohne Zweck)
  - keine Positions-, Bewegungs- oder Aktivitätsauswertung, keine "Fleißpunkte", keine Bewertung
  - keine Bildschirmfotos von Schülern, keine Sprachfunktion
  - Talk-Bot-Meldungen "X ist beigetreten" in Klassenräumen abschalten (30 Meldungen pro Stunde, Verhaltensdaten im Chat)
  [M, Ableitung aus VO-DV-I-Prinzip "nur technisch erforderlich"]
- **Was Schulen brauchen und selten bekommen:** ein Muster für das Verzeichnis von Verarbeitungstätigkeiten (Datenarten, Zweck, Löschfrist, TOM) und einen Elternbrief-Baustein. Geringer Aufwand, hoher Wert, echter Unterschied zu anderen Angeboten. Rechtlich als "Muster ohne Gewähr" kennzeichnen. [M]

---

## 7. Schuljahreswechsel, Archiv, Löschkonzept, Ressourcen

### 7.1 Schuljahreswechsel

- Klassengruppen ändern sich zum Schuljahr (LDAP-Abgleich aus paedML/linuxmuster/UCS@school). [M]
- **Falle Gruppen-ID-Wiederverwendung:** Ist eine Welt an die Gruppe "5a" gebunden und heißt die neue fünfte Klasse im nächsten Jahr wieder "5a", bekommt die neue Klasse automatisch Zugang zur Welt der alten. Gameworld gleicht Gruppen dynamisch ab, das wirkt hier gegen die Schule. [M, Ableitung aus eigenem Code]
- Empfehlung: jede Schul-Welt hat ein Ablaufdatum (Vorgabe: letzter Schultag vor den Sommerferien aus der vorhandenen Ferienliste). Am Ablauf: Welt stoppen, Archiv in den Files der Lehrkraft (Phase 5), Einladungen lösen, Spielerdaten löschen, Welt löschen oder als Vorlage behalten. Vorwarnung 14 Tage vorher. [M]

### 7.2 Löschkonzept

- Beim Ausladen und am Ablauf: `remove_player` und `remove_player_auth` im Welt-Mod, Zählbuch-Einträge und Ereignisdateien leeren. [H für API]
- Schutzbereiche (areas/protector) und Schilder speichern Spielernamen im Kartenmaterial; beim Archiv auf Wunsch anonymisieren oder bewusst als Werk der Klasse behalten (Owner-Frage). [M]
- Archiv in Nextcloud Files unterliegt dann den Löschregeln der Schule; Gameworld schreibt Ablaufdatum und Hinweis ins Archiv. [M]
- Spielernamen: Luanti erlaubt nur `[a-zA-Z0-9_-]`, max. 20 Zeichen; NC-Konten "vorname.nachname" werden heute schon umgewandelt. Klarnamen als Namensschild sind in der eigenen Klasse meist unkritisch, als Option "Kürzel statt Namen" sinnvoll. [M]

### 7.3 Ressourcen

- Luanti-Doku: Richtwert für "around 10 players" auf einem nicht anspruchsvollen Spiel: 2 Kerne (besser 4), 4 GB RAM als Startpunkt für den Host, 20 Mbps Upload; "Luanti is heavily single-threaded", Takt wichtiger als Kerne. [H]
- Gameworld heute: Presets 512 MB bzw. 1 GB, `nano_cpus` = 1 Kern fest, `max_users = 8` fest, `pids_limit` 128. [H, Code]
- Schätzung Klassenwelt 30 bis 32 Spieler, kreativ, Minetest Game: 1,5 bis 2,5 GB Limit, 2 Kerne, Upload am Server 40 bis 60 Mbps im Spitzenwert (Hochrechnung aus 10-Spieler-Richtwert). [L, Lasttest Pflicht]
- Lasttest-Weg: Bot-Clients (z. B. miney-py/minetest-client-docker; dort ca. 120 MB RAM je Bot-Client auf der Testmaschine) gegen eine Testwelt. Erst wenn RAM frei ist, nie neben Findling-Containern. [M]
- **Schlafmodus:** Klassenwelten laufen heute dauerhaft; das Welt-Zeitfenster sperrt nur den Beitritt. Für Schulträger mit vielen Klassen: Welt 10 Minuten vor dem Fenster automatisch starten, 15 Minuten nach Ende stoppen. Überschneidet sich mit v2 "Auto-Stop bei Inaktivität". [M]
- Rechnung für einen Schulträger-Server: 3 parallele Klassenwelten à 2 GB plus Nextcloud ergeben 8 bis 12 GB RAM; mehr parallel nur mit Schlafmodus. [L]

---

## 8. Wege in die Schulen

- **Pilotpartner zuerst:** Medienzentren und Schulträger mit eigener Nextcloud (Typ Medienzentrum Wiesbaden), Privatschulen mit eigener IT, Teckids (schul-frei), CoderDojo; Kontakt über "Bringing Kids to Nextcloud" (Fabrice Mous) läuft bereits. [M]
- **Landesmedienzentrum BW / BLOCKALOT:** ansprechen als Partner (Gameworld = Selbstbetrieb, BLOCKALOT = gehostet; Erfahrungsaustausch zu Lehrkraft-Bedarf). [M]
- **Luanti-Bildungscommunity:** education@luanti.org, Edu-Discord, Eintrag auf luanti.org/education unter "Hosting" anfragen; EduLuanti (IRI) für Austausch zu Lehrkraft-Werkzeugen. [H für Kanäle]
- **Fortbildung:** ZSL BW hat schon Nextcloud-Fortbildungen; ein Modul "Luanti-Welten in der Schul-Nextcloud" mit Handout wäre anschlussfähig. Medienzentren sind laut hessischem Erlass für medienpädagogische Fortbildung zuständig. [M]
- **Veranstaltungen:** Open Education Day (Bern, April), FOSDEM Education, Chemnitzer Linux-Tage, CCC-Kongress (Teckids-Assembly), didacta. [M]
- **Nextcloud GmbH:** Schulen sind Zielgruppe der Enterprise-Seite (Jugendschutz-Einstellungen, Moodle-Integration). Ein Schul-Fall mit Gameworld stärkt den Store-Eintrag. [M]

---

## 9. Funktionsliste priorisiert

Aufwand in Arbeitstagen, Solo, inkl. Tests und Abnahme. Abhängigkeiten zu bestehenden Phasen.

### Muss (ohne das kein Pilot)

| # | Funktion | Inhalt | Tage | Abhängigkeit |
|---|---|---|---|---|
| M1 | Lehrkräfte-Rolle mit Umfang | ROLLE-03 plus: Einladung nur für Gruppen mit Subadmin- oder Mitgliedschaft der Lehrkraft (Abfrage `subadmins/details` und Gruppenmitgliedschaft), saubere Meldung statt "Konto unbekannt", Welt-Besitzer und Mit-Lehrkräfte, jede Lehrkraft sieht nur ihre Welten; Negativtests (Lehrkraft lädt fremde Klasse ein, Schüler ruft Verwalter-Route) | 5 bis 7 | Phase 6 (ROLLE-03/04); am besten ROLLE-03 gleich so bauen |
| M2 | Klassen-Preset und Lasttest | Kreativ, kein Schaden, kein PvP, `max_users` 32, 2 Kerne, Limit nach Messung; Bot-Lasttest mit 30 Clients | 2 bis 3 | Phase 2 Preset-Registry; Docker-Lauf nötig |
| M3 | Klassenmodus | Welt-Mod `gameworld_class`: Einfrieren (Physik plus `interact`), Chat stumm (`shout`), Bauen sperren, alle zur Lehrkraft holen, Hinweistext auf dem Bildschirm; Steuerung im Dashboard, handytauglich wie die Pause | 4 bis 6 | Muster gameworld_time und Pause (Phase 4/4.1) |
| M4 | Schul-Datenschutz-Grundlage | Schulmodus-Schalter: Tagesrückblick und Bot-Beitrittsmeldungen aus, Chat nicht protokollieren, debug.txt aus Backups, Spielerdaten beim Ausladen löschen; Muster-VVT und Elternbrief-Baustein in docs/ | 3 bis 4 | Phase 4.1, Phase 5 (Backup-Inhalt) |
| M5 | Schuljahresende | Ablaufdatum pro Welt, Vorwarnung, Archiv in Files, Einladungen lösen, Spielerdaten löschen | 3 bis 4 | Phase 5 Backup zwingend |

**Summe Muss: 17 bis 24 Tage** [L, Schätzung]

### Soll (macht es im Alltag gut)

| # | Funktion | Tage | Abhängigkeit |
|---|---|---|---|
| S1 | Browser-Spielen über eigenen WebSocket-Proxy (nur bei Go aus Phase 4.2) | 8 bis 15 | Phase 4.2 [L] |
| S2 | Vorlagen-Welten und Kopie pro Gruppe ("jede Tischgruppe bekommt dieselbe Startwelt") | 3 bis 5 | Phase 5 Restore-Pfad, M1 |
| S3 | Schlafmodus nach Welt-Zeitfenster (Auto-Start/-Stopp) | 2 bis 3 | ZEIT-05 |
| S4 | Beamer-/Handout-Ansicht mit QR-Code (schon v2-Eintrag) | 1 | Phase 3 Verbindungsinfo |
| S5 | Kuratiertes Schul-Mod-Paket (protector oder areas, mesecons für Informatik) mit Pin, SHA-256, Lua-Scan | 3 bis 4 | Pipeline aus WEITERE-SPIELE |

### Kann (später, nach Pilot-Feedback)

| # | Funktion | Tage | Hinweis |
|---|---|---|---|
| K1 | Heimatort-Welten aus OSM (Arnis-Vorlage, Import als Archiv) | 3 bis 5 | ODbL-Hinweis, Spielpassung offen [L] |
| K2 | Lernpfade/Quests (yl_speak_up, quiz) als Vorlagen | 3 bis 5 | Kuratierung kostet Pflege |
| K3 | Unsichtbare Lehrkraft (set_observers) | 2 | eigener Mod statt spectate |
| K4 | Bauzonen pro Gruppe in einer Welt (areas aus dem UI) | 4 bis 6 | Alternative S2 ist einfacher |
| K5 | Mehrere Schulen auf einer Nextcloud (Mandant, RAM-Budget je Schule) | 5 bis 8 | nur für Schulträger-Betrieb |

### Bewusst NICHT bauen

- Bewertung, Punkte, Ranglisten, Lernstandsanalyse, Bewegungsprofile
- Chatprotokoll zum Nachlesen für Lehrkräfte
- Selbstregistrierung von Schülern, Gastzugänge ohne Nextcloud-Konto
- Welten über Schulgrenzen hinweg, öffentliche Schulserver
- Freier Mod-Browser für Lehrkräfte
- Minecraft-Education-Anbindung

### Abhängigkeiten

```
Phase 6 (ROLLE-03/04) -> M1 -> M3, S2
Phase 2 Presets       -> M2 -> M3 (Test mit 30 Spielern)
Phase 5 Backup        -> M4 (Backup-Inhalt), M5, S2, K1
Phase 4.2 Spike       -> S1
ZEIT-05               -> S3
```

---

## 10. Prüfung der Owner-Reihenfolge

Hypothese: (1) Lehrkräfte-Rolle, (2) Browser-Spike, (3) Klassenmodus, (4) Vorlagen-Welten, (5) Schuljahreswechsel.

- (1) **bestätigt, mit Erweiterung:** zuerst, aber mit Einladungs-Umfang über Subadmin/Mitgliedschaft und Welt-Besitzer. Sonst bricht es beim ersten echten Lehrerkonto. [H]
- (2) **bestätigt, aber nicht als Teil des Schul-Meilensteins:** Phase 4.2 ist schon im v1-Meilenstein geplant und soll dort bleiben. Ihr Ergebnis ist Eingangsbedingung für den Schul-Meilenstein (iPads, Firewalls). [M]
- **Neu einschieben vor (3): Klassen-Preset plus Lasttest (M2).** 30 Spieler sind nicht belegt; ohne Messung ist der Klassenmodus nicht testbar. [M]
- (3) **bestätigt.** [M]
- (4) **später schieben:** Vorlagen und Kopien bauen auf dem Restore-Pfad aus Phase 5 auf und sind kein Pilot-Muss. Eine Lehrkraft kann im Pilot auch drei Welten per Klick anlegen. [M]
- (5) **teilen:** Löschen der Spielerdaten beim Ausladen gehört nach vorn (M4, Pilot-Voraussetzung). Das Ablaufdatum mit Archiv bleibt hinten, muss aber vor dem ersten Schuljahresende eines Piloten fertig sein. [M]

**Empfohlene Reihenfolge:** Phase 4.2 (läuft im v1-Meilenstein) → v1-Store → M1 Lehrkräfte-Rolle → M2 Klassen-Preset/Lasttest → M3 Klassenmodus → M4 Datenschutz-Schulmodus → Pilot in echten Stunden → M5 Schuljahresende → S2 Vorlagen → S1 Browser (bei Go) → Rest nach Feedback.

Einordnung gegenüber anderen Plänen: "Weitere Luanti-Spiele" (3 bis 4 Tage) ist fest direkt nach v1 eingeplant und klein; der Schul-Meilenstein danach oder parallel zur Minecraft-Bedarfsumfrage. [M]

---

## 11. Risiken

1. **Kleiner erreichbarer Markt:** Landesplattformen sind zu; viele Schulen haben keine eigene Nextcloud mit Docker. Pilotpartner ist Pflicht, bevor gebaut wird. [M]
2. **Zusatzrechte der ExApp an Schulträger-Servern:** Docker-Socket-Proxy und UDP-Ports müssen von der Träger-IT freigegeben werden; das ist dort ein Sicherheitsantrag, kein Klick. Ehrliche Doku (Phase 6, privacy.md) ist Voraussetzung. [M]
3. **ROLLE-03 ohne Umfang ist unbrauchbar oder gefährlich:** ohne Subadmin-Bezug scheitern Einladungen; mit Admin-Abfragen wäre das Schülerverzeichnis offen. [H]
4. **Last 30 Spieler unbekannt:** Einkern-Limit und 1 GB könnten nicht reichen; Upload am Server 40 bis 60 Mbps geschätzt. [L]
5. **Netz an Schulen:** UDP-Ports nach außen oft gesperrt, keine iPad-App; ohne Browser-Weg viele Räume nicht erreichbar. [M]
6. **Chat und IP im Log:** ohne Schulmodus verarbeitet Gameworld mehr als technisch nötig, im Widerspruch zum VO-DV-I-Prinzip; mögliches Backup-Leck über debug.txt. [H für Logzeilen, M für Backup]
7. **Gruppen-ID-Wiederverwendung im neuen Schuljahr** gibt neuen Klassen Zugriff auf alte Welten. [M]
8. **Support-Last:** Lehrkräfte melden sich in der Stunde mit akuten Problemen; Solo-Projekt neben Findling. Pilot klein halten (eine Schule, zwei Lehrkräfte). [M]
9. **Mod-Pflege:** jede Schul-Mod ist Fremdcode in Kinderwelten und muss pro Luanti-Update geprüft werden; Paket klein halten. [M]
10. **Rechtsrahmen je Land verschieden:** Muster-VVT kann keine Rechtsberatung sein; Haftungshinweis nötig. [M]

---

## 12. Offene Fragen an den Owner

1. Gibt es einen konkreten Pilotpartner (Medienzentrum, Schule, Teckids, CoderDojo)? Ohne ihn: Meilenstein nur vormerken.
2. Lehrkräfte im Spiel: nur Steuerung über die Gameworld-Oberfläche, oder zusätzlich `fly`/`fast`/`teleport` für als Lehrkraft markierte Konten? (ROLLE-04 verbietet Luanti-Adminrechte.)
3. Welt-Besitzer: sieht jede Lehrkraft nur eigene Welten, oder teilen sich alle Lehrkräfte einer Schule die Welten?
4. Soll ROLLE-03 in Phase 6 schon mit Subadmin-Umfang gebaut werden (empfohlen), oder bleibt Phase 6 bei der einfachen Gruppenliste?
5. Mehrere Schulen auf einer Nextcloud (Schulträger-Betrieb) im Scope oder bewusst draußen?
6. Ist das Browser-Spielen für Schulen ein Muss? Wenn Phase 4.2 No-Go ergibt: Schul-Meilenstein trotzdem?
7. Im Schulmodus Spielzeitkonto je Schüler komplett aus (nur Welt-Zeitfenster), oder weiter zählen?
8. Namensschilder: Klarname, Vorname oder Kürzel als Vorgabe?
9. Bauten mit Schülernamen (Schilder, Schutzbereiche) beim Archiv anonymisieren oder als Klassenwerk behalten?
10. Muster-VVT und Elternbrief: selbst erstellen oder mit einem Pilot-Datenschutzbeauftragten gemeinsam?
11. LMZ BW (BLOCKALOT) und luanti.org-Bildungsteam aktiv ansprechen? Entwurf durch Claude, Versand durch Owner.

---

## 13. Quellen (alle abgerufen 22.10.2026, sofern nicht anders angegeben)

**Luanti und Bildung**
- Luanti Education: https://www.luanti.org/en/education/ [H]
- LuantiEDU-Doku: https://docs.luanti.org/about/luanti-edu/ [H]
- NLnet EduLuanti: https://nlnet.nl/project/EduLuanti/ [H]
- BLOCKALOT: https://www.blockalot.de/ (nicht abrufbar, TLS-Fehler; Angaben nur über luanti.org) [M]
- Luanti Downloads: https://www.luanti.org/en/downloads/ [H]
- Luanti FAQ (iOS/App Store): https://docs.luanti.org/faq [M, Suchtreffer-Auszug]
- Luanti Server-Hardware: https://docs.luanti.org/for-server-hosts/setup/ [H]
- Luanti 5.17.0 lua_api.md: https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/doc/lua_api.md [H]
- Luanti 5.17.0 server.cpp (Join-/Chat-Logzeilen): https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/src/server.cpp [H]
- Luanti 5.17.0 Dockerfile: https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/Dockerfile [H]
- Luanti 5.17.0 settingtypes.txt: https://raw.githubusercontent.com/luanti-org/luanti/5.17.0/builtin/settingtypes.txt [H]
- Friedrich Verlag "Auf Jesu Spuren" (Server-Empfehlung LMZ/Wittenberg): https://www.friedrich-verlag.de/friedrich-plus/schule-paedagogik/digitale-schule/digital-unterrichten/auf-jesu-spuren-7725 [M, nur Suchtreffer-Auszug]
- Teckids beim 39C3: https://events.ccc.de/congress/2025/hub/en/assembly/detail/teckids [M]

**ContentDB (API, 22.10.2026)**
- Education-Tag: https://content.luanti.org/api/packages/?tag=education [H]
- Einzelpakete: https://content.luanti.org/packages/rubenwardy/classroom/ , https://content.luanti.org/packages/ShadowNinja/areas/ , https://content.luanti.org/packages/TenPlus1/protector/ , https://content.luanti.org/packages/Jeija/mesecons/ , https://content.luanti.org/packages/BuckarooBanzay/mesecons_lab/ , https://content.luanti.org/packages/sfan5/worldedit/ , https://content.luanti.org/packages/mt-mods/lwscratch/ , https://content.luanti.org/packages/giga-turbo/codeblock/ , https://content.luanti.org/packages/Krunegan/luabots/ , https://content.luanti.org/packages/Miney/miney/ , https://content.luanti.org/packages/snowyu/quiz/ , https://content.luanti.org/packages/Sokomine/yl_speak_up/ , https://content.luanti.org/packages/Fhelron/spectate/ , https://content.luanti.org/packages/jp/spectator_mode/ , https://content.luanti.org/packages/zeuner/edutest/ , https://content.luanti.org/packages/rubenwardy/accountmgr/ [H]
- classroom-README: https://codeberg.org/rubenwardy/classroom [H]

**Geodaten und Browser**
- Arnis: https://github.com/louis-e/arnis (README, Release v3.3.0 vom 05.10.2026) [H]
- realterrain: https://github.com/bobombolo/realterrain (letzte Änderung 09.02.2017) [H]
- IGN Minetest/Minecraft à la carte: https://openig.org/sites/default/files/2024-09/minecraft_0.pdf [M]
- luanti-wasm: https://github.com/paradust7/luanti-wasm (README, fetch_sources.sh) [H]
- lwproxy: https://github.com/paradust7/lwproxy [H]
- Lasttest-Bots: https://github.com/miney-py/minetest-client-docker [M]

**Nextcloud**
- Provisioning-API UsersController stable32: https://raw.githubusercontent.com/nextcloud/server/stable32/apps/provisioning_api/lib/Controller/UsersController.php [H]
- GroupsController stable32: https://raw.githubusercontent.com/nextcloud/server/stable32/apps/provisioning_api/lib/Controller/GroupsController.php [H]
- AUserDataOCSController stable32: https://raw.githubusercontent.com/nextcloud/server/stable32/apps/provisioning_api/lib/Controller/AUserDataOCSController.php [H]
- Routen stable30/31/32: https://raw.githubusercontent.com/nextcloud/server/stable32/apps/provisioning_api/appinfo/routes.php [H]
- Admin-Handbuch Gruppenadmins: https://docs.nextcloud.com/server/latest/admin_manual/configuration_user/user_configuration.html [H]
- Nextcloud Bildungswesen: https://nextcloud.com/de/bildungswesen/ [M, Herstellerseite]
- Medienzentrum Wiesbaden Nutzungsbedingungen Nextcloud: https://www.wiesbaden.de/microsite/medienzentrum/it-support/nb_-NC [H]
- Univention UCS@school und Nextcloud (11/2019): https://www.univention.com/blog-en/2019/11/ucsschool-automatic-integration-of-samba-shares-into-nextcloud/ [H, alt]
- Lehrerfortbildung BW Nextcloud: https://lehrerfortbildung-bw.de/st_digital/nextcloud/ [H]
- ByCS: https://www.km.bayern.de/schule-digital/software-und-hardware-ausstattung/bycs.html [M]
- LOGINEO NRW Speicherplatz: https://www.logineo.schulministerium.nrw.de/_LOGINEO-NRW/Materialien/Info_Beratung/Information-Kontotypspezifisches-Speicherplatzvolumen-in-LOGINEO-NRW.pdf [M]
- openDesk Edu: https://borncity.com/news/opendesk-edu-bund-integriert-open-source-tools-fuer-8-600-schulen/ [L]

**Datenschutz und Recht**
- DSK-Festlegung MS 365 vom 24.11.2022: https://www.datenschutzkonferenz-online.de/media/dskb/2022_24_11_festlegung_MS365.pdf [H]
- LfDI BW Empfehlung 07.05.2021: https://www.baden-wuerttemberg.datenschutz.de/wp-content/uploads/2021/05/20210507_PM_Empfehlung-LfDI_Pilotprojekt_Bildungsplattform.pdf [M]
- HBDI Hessen 2025 (Fachmedien): https://www.computerwoche.de/article/4090992/hessen-erlaubt-microsoft-365-fur-behorden-unter-auflagen.html , https://borncity.com/blog/?p=318222 [M]
- Tagesspiegel Background "Neue Datenschutzdebatte um Microsoft an Schulen": https://background.tagesspiegel.de/digitalisierung-und-ki/briefing/neue-datenschutzdebatte-um-microsoft-an-schulen [L, Paywall]
- KM Bayern Datenschutz an Schulen: https://www.km.bayern.de/recht/datenschutz-an-schulen [H]
- Schulministerium NRW Datenschutz im Schulbereich: https://www.schulministerium.nrw/themen/recht/datenschutz-im-schulbereich [M, Seite nicht erreichbar, nur Suchtreffer-Auszug]
- Minecraft Education Lizenzen und Server: siehe .planning/research/MINECRAFT-V2.md, Abschnitt 1.3 (abgerufen 21.10.2026) [H]
- MinecraftEdu-Schalter Freeze/Mute: https://minecraft.fandom.com/wiki/MinecraftEdu [M]

**Eigener Code (gelesen, nicht geändert)**
- src/gameworld/access/directory.py, src/gameworld/access/roles.py, src/gameworld/provisioner/spec.py, src/gameworld/provisioner/presets.py, src/gameworld/provisioner/luanti_conf.py [H]

## 14. Lücken

- BLOCKALOT-Funktionsumfang und Nutzerzahlen nicht direkt geprüft (Seite per TLS nicht erreichbar).
- Ob ByCS, LOGINEO oder openDesk Edu technisch auf Nextcloud beruhen: nicht belegt; für die Empfehlung unerheblich, weil dort keine ExApps installierbar sein dürften.
- RAM und CPU für 30 Spieler: nur Lasttest klärt das.
- Ob `debug.txt` im Welt-Volume entsteht: im Spike mit laufender Welt prüfen.
- Kompatibilität der Schul-Mods mit 5.17 und VoxeLibre: nur Live-Test klärt das.
- luanti-wasm auf Safari/iPad: Phase 4.2.
- Konkrete Firewall-Lage an Schulen (UDP): keine belastbare Quelle gefunden.
