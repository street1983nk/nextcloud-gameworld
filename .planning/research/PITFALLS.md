# Pitfalls Research

**Domain:** Kindgerechtes Gameserver-Portal als Nextcloud-ExApp (Python/AppAPI), Container-Provisionierung von Luanti-Servern, später Minecraft Java via Crafty
**Researched:** 2026-10-19
**Confidence:** HIGH (ExApp-Lifecycle, Docker-Sicherheit, Luanti-Backup), MEDIUM (Luanti-Default-Werte im Detail, Minecraft-Guidelines-Zukunft)

## Critical Pitfalls

### Pitfall 1: Docker-Socket in der ExApp = Root auf dem Heimserver

**What goes wrong:**
Die ExApp bekommt `/var/run/docker.sock` gemountet, um Luanti-Container zu starten. Wer den Docker-Socket hat, ist faktisch Root auf dem Host: `docker run -v /:/host --privileged` genügt. Eine einzige RCE-Lücke in der ExApp (oder ein bösartiges Spiel-Addon, das Pfade beeinflusst) kompromittiert den gesamten Familienserver inklusive Nextcloud-Daten. Das ist bei einem Produkt, dessen Kern "kindersicher, Daten zuhause" ist, der Super-GAU.

**Why it happens:**
Der direkte Socket ist der bequemste Weg (docker-py funktioniert sofort). Entwickler verwechseln "Container-Isolation" mit "Socket-Zugriff ist auch isoliert". Außerdem verleitet AppAPI dazu, weil der Deploy-Daemon selbst Docker-Zugriff hat, und man annimmt, die ExApp dürfe das dann auch.

**How to avoid:**
- Nie den rohen Socket in den ExApp-Container mounten. Stattdessen einen eigenen, minimalen Socket-Proxy (Muster: Tecnativa docker-socket-proxy oder Nextclouds eigener DSP-Ansatz) mit Allowlist nur für die benötigten Endpunkte: `containers` (create/start/stop/remove/inspect), `images` (pull eines fest gepinnten Luanti-Images), `volumes`, `POST`. Kein `exec`, kein `build`, kein Zugriff auf fremde Container.
- Zusätzlich appseitige Härtung der erzeugten Game-Container: niemals `privileged`, keine Host-Bind-Mounts (nur Named Volumes mit Namenspräfix), `cap_drop: ALL`, `no-new-privileges`, non-root-User im Luanti-Image, festes Image-Digest-Pinning (keine frei wählbaren Images).
- Die Provisionierungsschicht als eigenes Modul mit enger API bauen ("create_world", "start", "stop", "destroy"), damit kein Codepfad beliebige Docker-Aufrufe absetzen kann.
- Alternative ernsthaft prüfen (lt. PROJECT.md ohnehin Owner-Entscheid): ein separater, kleiner Host-Agent/Daemon mit fester API, den die ExApp über HTTP anspricht. Nachteil: Installationshürde. Vorteil: ExApp selbst bleibt unprivilegiert, Store-Review-freundlicher.

**Warning signs:**
- `docker.sock` taucht in docker-compose/Deploy-Doku der ExApp auf.
- Code enthält generische Docker-Client-Aufrufe außerhalb des Provisionierungsmoduls.
- Game-Container laufen als root oder mit Host-Pfaden.

**Phase to address:**
Erste Bauphase (Provisionierungs-Kern). Die Entscheidung Socket-Proxy vs. Host-Agent ist die Architektur-Weiche des Projekts und muss vor jedem Feature fallen.

---

### Pitfall 2: AppAPI-Annahmen: Der Deploy-Daemon provisioniert die ExApp, nicht die Spielwelten

**What goes wrong:**
Man plant, die Luanti-Container "über AppAPI" zu starten, weil AppAPI ja einen Docker-Deploy-Daemon hat. AppAPIs Deploy-Daemon ist aber ausschließlich für den Lebenszyklus der ExApp-Container selbst zuständig (deploy, update, enable/disable). Es gibt keine stabile, öffentliche AppAPI-Schnittstelle, mit der eine ExApp beliebige Sibling-Container erzeugen darf. Wer darauf baut, hängt an internen Mechanismen, die sich gerade stark bewegen: der Docker Socket Proxy (DSP) ist deprecated zugunsten von HaRP und soll mit Nextcloud 35 entfernt werden.

**Why it happens:**
Die AppAPI-Doku beschreibt Docker-Zugriff prominent, aber aus Admin-Sicht (Daemon-Konfiguration). Der Unterschied "AppAPI verwaltet ExApps" vs. "meine ExApp verwaltet Game-Container" ist leicht zu übersehen.

**How to avoid:**
- Gameworlds Container-Provisionierung als eigene, von AppAPI unabhängige Schicht bauen (eigener Socket-Proxy-Container oder Host-Agent, siehe Pitfall 1). AppAPI nur für das nutzen, wofür es da ist: ExApp-Deploy, Auth, Nextcloud-API-Zugriff via nc_py_api.
- Nicht gegen DSP-Interna oder HaRP-Interna programmieren. Beide sind Infrastruktur des Admins, nicht API der App.
- In der Install-Doku beide Welten sauber trennen: "AppAPI-Daemon installiert Gameworld" und "Gameworld braucht zusätzlich X für Spielwelten".

**Warning signs:**
- Code importiert oder ruft AppAPI/DSP/HaRP-Endpunkte für Container-Erzeugung auf.
- Setup funktioniert nur mit einer bestimmten Daemon-Konfiguration (z. B. nur AIO, nur DSP).
- Nach einem Nextcloud-Major-Update startet keine Welt mehr.

**Phase to address:**
Erste Bauphase (Provisionierungs-Architektur-Entscheid), erneut prüfen vor Store-Release.

---

### Pitfall 3: ExApp-Update wirft den Container weg: Zustand und Spielwelten driften

**What goes wrong:**
Bei einem ExApp-Update entfernt AppAPI den ExApp-Container und erstellt ihn neu aus dem neuen Image. Alles, was nur im Container-Dateisystem lag (SQLite-Zustands-DB, Welt-Metadaten, Locks, Job-Queues), ist weg. Gleichzeitig laufen die Luanti-Game-Container unbeeindruckt weiter. Ergebnis nach dem ersten Update: Die App kennt ihre eigenen Welten nicht mehr, Container laufen verwaist weiter, Eltern sehen eine leere Weltenliste, obwohl die Kinder gerade spielen.

**Why it happens:**
Im Dev-Setup (manual-install, langer Containerlauf) fällt das nie auf. Der erste Store-Update-Zyklus ist der erste echte Test, und der kommt erst nach Release.

**How to avoid:**
- Sämtlichen App-Zustand ausschließlich in den persistenten AppAPI-Speicher legen (persistentes Volume der ExApp bzw. `APP_PERSISTENT_STORAGE`), nie ins Container-FS. Beim Start prüfen: DB-Schema-Migrationen idempotent, Startup-Reconciliation (siehe Pitfall 4).
- Welten-Quelle der Wahrheit doppelt absichern: Docker-Labels an jedem Game-Container (`gameworld.world_id`, `gameworld.owner`, `gameworld.version`) machen jede Welt auch ohne DB rekonstruierbar.
- Update-Szenario als festen Testfall: Version N installieren, Welt starten, auf N+1 updaten, Welt muss sichtbar und steuerbar bleiben.
- Auch Enable/Disable testen: AppAPI stoppt/startet dabei nur den ExApp-Container; laufende Welten müssen das überleben und danach wieder angebunden sein.

**Warning signs:**
- Zustands-DB-Pfad liegt nicht im persistenten Volume.
- Kein Code-Pfad, der beim App-Start laufende Container entdeckt und adoptiert.
- Testplan enthält kein Update-/Reinstall-Szenario.

**Phase to address:**
Früh (Lifecycle-/State-Phase direkt nach dem Provisionierungs-Kern), Verifikation erneut in der Store-Release-Phase.

---

### Pitfall 4: Verwaiste Container und Volumes, State-Drift zwischen App-DB und Docker-Realität

**What goes wrong:**
Container sterben (OOM, Host-Reboot, Docker-Restart), Nutzer deinstallieren die ExApp, Operationen brechen mitten in "create world" ab. Die App-DB sagt "Welt läuft", Docker sagt "Exited (137)" oder der Container existiert gar nicht mehr. Umgekehrt bleiben nach Deinstallation Luanti-Container und Welt-Volumes für immer liegen und fressen Plattenplatz auf dem Heimserver. Klassiker aller Panel-Projekte (Pterodactyl/Crafty-Issues sind voll davon).

**Why it happens:**
Naive Implementierung behandelt Docker-Aufrufe als transaktional ("create hat geklappt, also läuft es"). Docker ist aber ein externes, eigenständig veränderliches System. Deinstallations-Hooks werden vergessen oder laufen nicht, wenn der Admin die App hart entfernt.

**How to avoid:**
- Reconciliation-Loop als Kernstück: periodisch (und bei jedem App-Start) `docker ps -a --filter label=gameworld.*` gegen die DB abgleichen. Drei Fälle behandeln: DB-Eintrag ohne Container (Status auf "gestoppt/fehlend" setzen, Neuaufbau anbieten), Container ohne DB-Eintrag (adoptieren oder als verwaist markieren), Status-Differenz (Docker gewinnt).
- Alles Erzeugte konsequent labeln und mit Namenspräfix versehen (`gameworld-world-<id>`, Volume `gameworld-data-<id>`), damit Aufräumen und Abgleich deterministisch sind.
- Jede Mehrschritt-Operation (Volume anlegen, Container erzeugen, starten, DB schreiben) als Saga mit Aufräumpfad bei Teilfehlern; Status-Feld mit Zwischenzuständen (creating, running, stopping, failed) statt boolean.
- Deinstallation: dokumentierter Cleanup (Welten-Export anbieten, dann Container und Volumes mit Gameworld-Label entfernen). Zusätzlich ein Admin-Kommando "Waisen anzeigen/aufräumen", weil der Uninstall-Hook nie garantiert läuft.
- Nie `docker volume prune` oder breite Filter verwenden, nur label-gezieltes Löschen.

**Warning signs:**
- UI-Status kommt aus der DB statt aus `container inspect`.
- Nach `docker restart` des Hosts zeigt die App falsche Zustände.
- `docker volume ls` wächst mit jedem Test.

**Phase to address:**
Lifecycle-/State-Phase (direkt nach Provisionierungs-Kern), Reconciliation gehört zum MVP, nicht in "später".

---

### Pitfall 5: OOM-Kill auf dem Heimserver: abgewürgte Welten, korrupte Daten, toter Server

**What goes wrong:**
Ohne Limits zieht eine Spielwelt (viele geladene Mapblocks, Mods, mehrere Kinder gleichzeitig) den Heimserver leer; der Kernel-OOM-Killer trifft wahlweise den Game-Container, die Nextcloud-DB oder den Host. SIGKILL mitten im Map-Write kann die Welt beschädigen (bei Luanti mit SQLite meist durch Journal abgefedert, bei LevelDB-Backend dokumentiert riskant; bei Minecraft in MVP 2 sind halb geschriebene Region-Files ein bekanntes Korruptionsmuster). Zweite Variante: Limits gesetzt, aber falsch, z. B. bei Minecraft JVM-Xmx gleich dem Container-Limit, dann killt cgroup die JVM beim ersten GC-Spike.

**Why it happens:**
Auf dem Dev-Rechner mit 32 GB fällt nichts auf. Heimserver haben oft 4 bis 8 GB, geteilt mit Nextcloud, DB, Redis. "Ressourcenlimits später" ist der Standardfehler.

**How to avoid:**
- Limits sind Pflichtfeld bei Weltenerstellung, nicht Option: `mem_limit` + `memswap_limit` (gleich setzen, sonst swappt der Container den Host tot), `cpus`/`cpu_quota`, `pids_limit`. Konservative Defaults (Luanti-Welt: in der Größenordnung 512 MB bis 1 GB RAM, 1 CPU; vor Release empirisch mit echter Familienlast kalibrieren).
- Vor dem Start einer weiteren Welt freie Host-Ressourcen prüfen und Start verweigern statt blind starten ("Dein Server hat nicht genug freien Speicher für eine zweite Welt").
- Stop immer als SIGTERM mit großzügigem Timeout (Luanti schreibt beim Shutdown), erst dann SIGKILL. `docker stop -t 30` statt Default 10 s.
- OOM-Kills erkennen (Exit-Code 137 / `OOMKilled: true` im Inspect) und den Eltern verständlich melden ("Welt hatte zu wenig Speicher"), inkl. Ein-Klick-Erhöhung im Rahmen des Verfügbaren.
- Restart-Policy bewusst wählen: `on-failure` mit Backoff-Logik in der App, nicht `always` (sonst OOM-Crash-Loop, der den Server dauerlastet).
- Für MVP 2 notieren: JVM-Heap deutlich unter Container-Limit (Faustregel: Xmx etwa 75 % des Limits oder `-XX:MaxRAMPercentage`).

**Warning signs:**
- `docker inspect` zeigt `OOMKilled: true` in Tests.
- Nextcloud-UI wird träge, sobald eine Welt läuft.
- Kein Feld für RAM/CPU im World-Create-Flow.

**Phase to address:**
Ressourcen gehören in die erste Provisionierungsphase (Teil des Container-Spec-Templates), OOM-Erkennung und UX in die Lifecycle-Phase.

---

### Pitfall 6: Backup einer laufenden Welt kopiert korrupte map.sqlite

**What goes wrong:**
Das Backup-Feature kopiert den Weltordner (inkl. `map.sqlite`) per `cp`/tar in Nextcloud Files, während der Server läuft und schreibt. Die Kopie ist mit hoher Wahrscheinlichkeit inkonsistent bis unbrauchbar; gemerkt wird das erst beim Restore nach einem echten Datenverlust, also im schlimstmöglichen Moment. Die Luanti-Doku dokumentiert nur Cold-Backups (Server aus, dann kopieren).

**Why it happens:**
Dateikopie "funktioniert" scheinbar immer, SQLite-WAL/Journal-Semantik ist unsichtbar. Restore wird selten getestet.

**How to avoid:**
- MVP-sicherer Weg: Welt für das Backup kurz sauber stoppen (SIGTERM, auf Shutdown warten), Weltordner archivieren, wieder starten. Bei Familiennutzung (Minuten Downtime nachts) völlig akzeptabel; im UI ehrlich anzeigen ("Welt pausiert kurz für die Sicherung").
- Live-Variante nur mit korrektem Muster: `sqlite3 map.sqlite ".backup /tmp/map-backup.sqlite"` (konsistente Online-Kopie über die SQLite-Backup-API, so macht es z. B. das YunoHost-Minetest-Paket), restliche Weltdateien (world.mt, auth.sqlite, Mod-Storage, player-DB) dazu. Nie rohes Kopieren der .sqlite-Dateien bei laufendem Prozess.
- Restore als Erstklass-Feature mit Test: Jede Backup-Implementierung gilt erst als fertig, wenn ein Restore in eine neue Welt nachweislich spielbar ist (automatisierter Test: Welt erzeugen, Block setzen, Backup, Restore, Block vorhanden).
- Backend fixieren: Welten immer mit SQLite-Backend anlegen (Default, robusteste Option laut Luanti-Doku), kein LevelDB (dokumentierte Korruptionsanfälligkeit bei unsauberem Shutdown).
- Upload nach Nextcloud Files erst nach abgeschlossenem, verifiziertem Archiv (Checksumme), nicht streamend aus dem Live-Verzeichnis.

**Warning signs:**
- Backup-Code enthält keinen Stop/Quiesce-Schritt und kein `.backup`.
- Kein automatisierter Restore-Test in CI/Testplan.
- Backup-Dauer ist verdächtig kurz bei großen Welten (Hinweis auf Kopie während Writes).

**Phase to address:**
Backup/Restore-Phase; der Restore-Test gehört in deren Abschlusskriterien.

---

### Pitfall 7: NAT, CGNAT und UPnP: "Freunde übers Internet einladen" scheitert still

**What goes wrong:**
Die App verspricht "Freunde einladen", der Server ist aber nur im LAN erreichbar. Familien hinter DS-Lite/CGNAT (in Deutschland sehr verbreitet bei Kabel- und Glasfaseranschlüssen) haben keine öffentliche IPv4; Portweiterleitung ist dort unmöglich, egal was die App tut. UPnP-Auto-Portöffnung wiederum ist (a) auf vielen Routern deaktiviert, (b) ein Sicherheits-Antipattern (die Kinder-App öffnet selbstständig Ports nach außen, genau das Gegenteil des Produktversprechens), (c) schlägt still fehl, sodass das Kind "Verbindung fehlgeschlagen" sieht und niemand weiß warum. Zusatzfalle: Luanti ist UDP (Default-Port 30000), viele Weiterleitungs-Anleitungen und Tests prüfen nur TCP.

**Why it happens:**
Im Entwicklernetz funktioniert LAN immer, und ein Entwickleranschluss hat oft echte IPv4. Das NAT-Problem zeigt sich erst bei der ersten fremden Familie.

**How to avoid:**
- MVP-Scope ehrlich schneiden: Stufe 1 ist "zuhause im WLAN spielen" (LAN-Adresse + Port prominent anzeigen, QR/Copy für die Kinder). Internet-Erreichbarkeit als eigene, spätere Stufe, nie stillschweigend versprechen.
- Für "Freunde woanders": VPN-Weg empfehlen und dokumentieren (WireGuard/Tailscale der Eltern), das passt zum Privat-Versprechen und umgeht CGNAT komplett. Kein eigener Relay-Dienst im MVP (widerspricht "Daten zuhause" und ist Betriebsaufwand).
- Erreichbarkeits-Diagnose einbauen statt raten: LAN-IP(s) anzeigen, UDP-Port-Selbsttest, klare Unterscheidung "im Heimnetz erreichbar" vs. "aus dem Internet erreichbar", CGNAT-Erkennung (öffentliche IP des Anschlusses vs. WAN-IP) mit verständlicher Erklärung.
- Kein UPnP/NAT-PMP im MVP. Wenn je, dann opt-in mit Elternbestätigung und sichtbarem Status.
- Port-Vergabe pro Welt deterministisch verwalten (30000 aufwärts, Kollisionstest vor Start), Host-Port nur auf explizite LAN-Freigabe binden; Standard ist "nur eingeladene Nextcloud-Nutzer, keine offene Bindung nach außen".

**Warning signs:**
- UI zeigt nur "Server läuft" ohne Adresse/Erreichbarkeits-Info.
- Testaufbau hat nie zwei getrennte Netze gesehen.
- Doku sagt "einfach Port 30000 weiterleiten" ohne UDP-Hinweis und CGNAT-Abschnitt.

**Phase to address:**
Netzwerk-/Erreichbarkeits-Phase (nach Kern-Lifecycle); der Scope-Schnitt "LAN zuerst, VPN dokumentiert, kein UPnP" gehört schon in die Roadmap-Definition.

---

### Pitfall 8: Default-offene Welt: Luanti hat ab Werk keine Zugangskontrolle, die zum Produkt passt

**What goes wrong:**
Ein nackter Luanti-Server lässt jeden verbinden, der IP und Port kennt: Erstregistrierung ist first-come (Name + selbstgewähltes Passwort), leere Passwörter sind je nach Konfiguration möglich, eine Whitelist gibt es im Core nicht (nur als Mod), und das Standard-Privilegienset enthält Chat (`shout`) und Interaktion. Wird dann noch `server_announce` aktiviert (oder von einem Mod/Preset gesetzt), steht die Kinderwelt in der öffentlichen Serverliste. Damit wäre das Kernversprechen "nur eingeladene Personen" gebrochen, bevor ein einziges Feature gebaut ist.

**Why it happens:**
Man verlässt sich auf "privat, weil niemand die IP kennt" (Security by Obscurity) oder auf die Nextcloud-Einladung als UI-Konzept, ohne sie im Spielserver technisch zu erzwingen.

**How to avoid:**
- Einladungen technisch durchsetzen, nicht nur anzeigen: Gameworld verwaltet die Spielerliste und erzwingt sie im Server, z. B. per mitgeliefertem Whitelist-/Auth-Mod, den die App pro Welt generiert (erlaubte Spielernamen + von der App gesetzte Passwörter), oder per app-verwalteter `auth`-Datenbank. Kein Join ohne App-Eintrag.
- Gehärtete `minetest.conf` als festes Template, von der App generiert und nicht editierbar durch Kinder: `server_announce = false` explizit setzen (nicht auf den Default verlassen), `disallow_empty_password = true`, `default_privs` minimal (interact, ggf. shout nur wenn Eltern Chat erlauben), `max_users` klein, Admin-`name` auf ein App-Systemkonto, nie auf ein Kinderkonto.
- Passwörter generiert die App (pro Kind pro Welt), Kinder wählen keine; Eltern sehen/teilen die Zugangsdaten über Nextcloud.
- Chat als Eltern-Schalter: `shout`-Privileg pro Welt an/aus; Default für Kinderwelten mit nur Familienmitgliedern an, bei eingeladenen Externen bewusste Elternentscheidung.
- Host-Port-Bindung restriktiv (siehe Pitfall 7): Standard LAN-only, keine automatische Exposition.
- Abnahmetest: Verbindungsversuch mit nicht eingeladenem Namen muss scheitern; `server_announce`-Wert im laufenden Container verifizieren.

**Warning signs:**
- Die generierte minetest.conf stammt aus einem Beispiel-Repo statt aus einem eigenen Template.
- Join ist mit beliebigem neuen Spielernamen möglich.
- Whitelist existiert nur in der Gameworld-DB, nicht im Spielserver.

**Phase to address:**
Einladungs-/Zugangskontroll-Phase, aber das conf-Template mit sicheren Defaults gehört schon in die erste Provisionierungsphase (Welt Nummer eins darf nie offen sein).

---

### Pitfall 9: Kinderdaten und DSGVO: zu viel erheben, falsch begründen

**What goes wrong:**
Das Produkt sammelt Alter, Namen oder Spielverhalten von Kindern "für die Elternkontrolle", speichert Chat-Logs unbegrenzt oder funkt Telemetrie nach Hause. Bei einem explizit an Familien gerichteten Produkt zieht das DSGVO Art. 8 (Einwilligung bei Diensten für Kinder; in Deutschland Altersgrenze 16 für eigene Einwilligung) und erhöhte Sorgfaltspflichten. Für ein Open-Source-Projekt mit Store-Listing ist schon der Anschein von Kinder-Datensammelei ein Reputationsrisiko.

**Why it happens:**
Elternkontroll-Features verleiten zu "mehr Daten = mehr Kontrolle". Und man übernimmt Muster kommerzieller Plattformen (Profile, Alter, Statistiken), die hier gar nicht nötig sind.

**How to avoid:**
- Datenminimierung als Designregel: Gameworld braucht kein Geburtsdatum und kein Alter. "Kind" ist eine Rolle, die Eltern einem existierenden Nextcloud-Konto zuweisen, keine eigene Datenerhebung. Die Alters-/Einwilligungsfrage liegt damit beim Betreiber der Nextcloud (den Eltern selbst), nicht bei der App, und genau so soll es bleiben.
- Keine Telemetrie, keine externen Calls im Betrieb (passt zu "Daten zuhause" und ist das stärkste Marketing-Argument). Wenn Update-Checks o. Ä. nötig: dokumentieren.
- Chat-Logs: wenn überhaupt, kurz rotierend, lokal, mit dokumentierter Aufbewahrung; Eltern-Einsicht ist ein Feature-Entscheid, kein Default-Vollprotokoll.
- Spielernamen in der Welt: Pseudonyme statt Klarnamen vorschlagen (Default-Spielername nicht aus displayname der Nextcloud ableiten, ohne es anzuzeigen).
- Kurzes privacy.md im Repo (Muster aus Findling/Connector existiert bereits): was wird wo gespeichert, was verlässt den Server (nichts).

**Warning signs:**
- Datenmodell enthält Geburtsdatum/Alter.
- Irgendein HTTP-Call an eine fremde Domain im Laufzeitcode.
- Chat-/Positions-Logging ohne Rotation und Begründung.

**Phase to address:**
Rollen-/Elternkontroll-Phase (Datenmodell-Entscheid) plus Store-Release-Phase (privacy.md, Listing-Text).

---

### Pitfall 10: ExApp-Release-Mechanik: Store-Review, Image-Tags, Versions-Churn

**What goes wrong:**
Bekannte Fallen aus eigener Findling-/Connector-Erfahrung, hier mit Verschärfung: (a) Das ExApp-Image muss zum Release-Tag exakt passen und öffentlich ziehbar sein, sonst schlägt der Deploy beim Nutzer fehl, nicht beim Entwickler. (b) AppAPI/Nextcloud-Major-Zyklen erzwingen laufende Kompatibilitätspflege (max-version-Anhebung pro NC-Release); die Deploy-Infrastruktur selbst bewegt sich gerade (DSP deprecated, HaRP neu, DSP-Entfernung zu NC 35 angekündigt), Doku und Setup-Anleitung veralten also schnell. (c) Eine App, die zusätzliche Container-Privilegien oder einen extra Infrastruktur-Container braucht (Socket-Proxy/Host-Agent aus Pitfall 1), ist im Store erklärungsbedürftig: Review und Nutzer-Vertrauen hängen daran, dass das Listing den Zugriff ehrlich und knapp erklärt.

**Why it happens:**
ExApp-Deploy testet man als Entwickler mit manual-install; der Store-Pfad (Image-Pull vom Registry-Tag durch fremde Daemons, AIO vs. DSP vs. HaRP) hat mehr Varianten als das Dev-Setup.

**How to avoid:**
- Release-Checkliste von Findling übernehmen und erweitern: Image nach ghcr/Docker Hub pushen mit Tag = App-Version, info.xml-Versionsgrenzen gegen aktuelle NC-Releases, Testinstallation über echten Deploy-Daemon (nicht nur manual-install) vor jedem Submit, einmal pro Setup-Variante (AIO, HaRP).
- Kompatibilitätsmatrix klein halten: eine unterstützte NC-Version rückwärts, nicht mehr; HaRP als primär dokumentierter Weg (DSP nur als Legacy-Hinweis, da Entfernung zu NC 35 angekündigt).
- Den Zusatz-Privilegien-Bedarf (Container-Management) im Listing und README offensiv erklären: was, warum, was nie (keine fremden Container, nur gelabelte eigene). Das entscheidet über Review und Adoption.
- nc_py_api-Version pinnen und Changelog bei NC-Majors lesen (Auth-/Header-Änderungen zwischen AppAPI-Generationen haben schon ExApps gebrochen).

**Warning signs:**
- "Funktioniert bei mir" nur via manual-install.
- Setup-Doku erwähnt DSP als Standardweg.
- Kein Test der Store-Installationsroute vor Submit.

**Phase to address:**
Store-Release-Phase; die HaRP/DSP-Lage zusätzlich beim Architektur-Entscheid in Phase 1 berücksichtigen.

---

### Pitfall 11: Minecraft (MVP 2): Rechts- und Distributionsfallen vorab einplanen

**What goes wrong:**
Für MVP 2 drohen drei vermeidbare Fehler: (1) Das Minecraft-Server-JAR wird ins eigene Docker-Image gebündelt und mitverteilt; die Weiterverteilung von Mojang-Serversoftware ist nicht erlaubt, das Image müsste aus dem Store/Registry zurückgezogen werden. (2) Man verlässt sich auf den EULA-Stand von heute: Mojang/Microsoft hat EULA und Guidelines zuletzt konsolidiert (EULA-Rework, Zusammenführung der Commercial-Usage- und Brand-Guidelines in die "Minecraft Usage Guidelines") und kann Hosting-Regeln jederzeit ändern; privates, nicht-kommerzielles Hosting ist erlaubt, aber Namens-/Branding-Nutzung ("Minecraft" im App-Namen oder Listing-Titel) ist eingeschränkt. (3) Kinder-Accounts: Microsoft-Family-Settings blockieren Multiplayer/Server-Join standardmäßig je nach Alterseinstellung; ohne Doku dafür scheitert der erste Join der Zielgruppe, und der Fehler sieht aus wie ein Gameworld-Bug.

**Why it happens:**
Luanti ist komplett frei, dieselben Muster unbedacht auf Minecraft übertragen erzeugt die Fallen. EULA-Texte liest man einmal und nie wieder.

**How to avoid:**
- Server-JAR zur Laufzeit vom Mojang-CDN laden lassen (etabliertes Muster, z. B. itzg/minecraft-server macht genau das und verlangt explizite EULA-Zustimmung per `EULA=TRUE`), nie ins Image backen. EULA-Zustimmung als bewusster Eltern-Klick im Create-Flow, protokolliert.
- Produkt-/Feature-Naming ohne "Minecraft" im Titel ("Gameworld" bleibt die Marke; Minecraft nur beschreibend nennen). Vor MVP-2-Start die dann aktuellen Minecraft Usage Guidelines im Original lesen, nicht Hoster-Blogs.
- Keinerlei Monetarisierung rund um Minecraft-Welten (ist ohnehin out of scope, aber im Listing-Text sauber halten).
- online-mode=true als Default (echte Accounts, keine Cracked-Clients), plus Eltern-Doku für Microsoft-Family-Multiplayer-Freigabe.
- Crafty Controller als Abhängigkeit prüfen: Lizenz, API-Stabilität, eigener Container = weitere Komponente in der Reconciliation (Pitfall 4 gilt dann doppelt).

**Warning signs:**
- Dockerfile mit `ADD server.jar`.
- "Minecraft" im App-Store-Titel oder Icon.
- Kein EULA-Zustimmungsschritt im Flow.

**Phase to address:**
MVP-2-Planungsphase (eigene Rechts-/Guideline-Recherche als erster Task), Distributionsmuster schon jetzt in der Architektur vorsehen (Engine-Abstraktion: "Image + Startkommando + Ports + Backup-Strategie" pro Engine).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Roher Docker-Socket in der ExApp statt Proxy/Agent | Spart 1 bis 2 Tage Setup | Root-Äquivalenz auf Familienservern, Store-/Vertrauensrisiko, später schwer rückbaubar | Nur lokal in Dev, nie im Release |
| Container-Status aus der DB statt aus Docker | Weniger API-Calls, einfacher Code | Dauerhafter State-Drift, Geister-Welten nach jedem Reboot | Nie; Inspect ist billig |
| Backup = tar des laufenden Weltordners | Backup-Feature "fertig" in Stunden | Unbrauchbare Backups, Entdeckung erst beim Ernstfall-Restore | Nie |
| Kein Ressourcenlimit im MVP ("machen wir konfigurierbar") | Schnellerer World-Create-Flow | OOM-Abstürze beim ersten echten Familienserver, Welt-Korruption | Nie; Defaults reichen, Konfigurierbarkeit kann warten |
| Zugangskontrolle nur in der App-UI, nicht im Gameserver | Einladungs-UI schnell demobar | Jeder mit IP+Port joint; Kernversprechen gebrochen | Nie |
| Welt-Metadaten nur in App-DB, keine Container-Labels | Ein Speicherort weniger | Nach ExApp-Reinstall sind laufende Welten unidentifizierbar | Nie, Labels sind gratis |
| UPnP für Internet-Zugriff | "Es funktioniert einfach" bei manchen Routern | Stille Fehler, Sicherheits-Antipattern, Support-Last | Nie im MVP; später höchstens opt-in |
| Nur manual-install getestet, Store-Route ungetestet | Schnellere Iteration | Deploy-Fehler erst beim Nutzer | In Dev-Phasen ok, vor jedem Store-Submit inakzeptabel |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Docker Engine API | Create/Start als eine atomare Aktion behandeln | Saga mit Zwischenzuständen, Cleanup bei Teilfehlern, Exit-Code-/OOMKilled-Auswertung |
| AppAPI / Deploy-Daemon | Annahme, die ExApp dürfe über AppAPI Sibling-Container erzeugen; gegen DSP-Interna bauen | Eigene Provisionierungsschicht; AppAPI nur für ExApp-Lifecycle und Auth; HaRP als dokumentierter Setup-Weg (DSP deprecated, Entfernung NC 35 angekündigt) |
| Nextcloud Files (Backups) | Upload direkt aus dem Live-Weltverzeichnis streamen | Erst konsistentes Archiv lokal erzeugen (Quiesce oder sqlite .backup), verifizieren, dann via nc_py_api hochladen |
| Luanti-Server-Container | Beliebige Community-Images verwenden | Ein eigenes, gepinntes Luanti-Image pflegen (non-root, SIGTERM-sauber, SQLite-Backend erzwungen, conf aus App-Template) |
| Nextcloud-Konten/Gruppen | Displayname/E-Mail als Spielername in die Welt durchreichen | App-generierte Pseudonyme + generierte Passwörter; Mapping nur in der App-DB |
| Crafty Controller (MVP 2) | Crafty-UI parallel zur Gameworld-UI als zweite Wahrheit zulassen | Crafty nur als API-Backend, Admin-UI nicht an Kinder/Eltern exponieren; Reconciliation deckt Crafty-Container mit ab |
| Mojang-Server-Distribution (MVP 2) | server.jar ins Image bündeln | Laufzeit-Download vom Mojang-CDN + expliziter EULA-Consent-Schritt |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Unbegrenzte Welten pro Host | Nextcloud wird träge, OOM-Kills | Welt-Start gegen freie Host-Ressourcen prüfen; weiches Limit (z. B. 2 bis 3 parallele Welten) | 2. bis 3. Welt auf 4-GB-Server |
| Docker-Inspect-Polling pro UI-Request | UI-Latenz, Docker-API-Last | Status-Cache mit kurzer TTL + Reconciliation-Loop; Events-API statt Dauer-Polling erwägen | Ab ein paar offenen Browser-Tabs |
| Backup blockiert den ExApp-Worker | App friert während Backup ein | Backups als Hintergrund-Job (Queue) mit Status, nicht im Request-Pfad | Erste Welt über ~1 GB |
| memswap nicht gesetzt (nur mem_limit) | Host swappt sich tot statt OOM im Container | memswap_limit = mem_limit setzen | Erste RAM-hungrige Welt auf HDD-Swap-Host |
| Welt-Volumes auf langsamem Storage (NFS/SMB-Mounts mancher NAS-Setups) | Lag, SQLite-Lock-Fehler | Named Volumes auf lokalem Storage; Doku-Hinweis für NAS-Nutzer | SQLite über Netz-FS, sofort |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Docker-Socket ungefiltert in der ExApp | Host-Root bei jeder App-Lücke | Minimal-Proxy mit Endpunkt-Allowlist oder Host-Agent mit enger API |
| Game-Container privileged / mit Host-Bind-Mounts | Container-Escape auf Familiendaten | cap_drop ALL, no-new-privileges, non-root, nur eigene Named Volumes |
| Beliebige Images/Mods durch Nutzer wählbar | Malware auf dem Heimserver | Image-Digest-Pinning, kuratierte Mod-Liste (lt. Scope ohnehin), keine freien Image-Felder |
| server_announce nicht explizit gesetzt | Kinderwelt landet in öffentlicher Serverliste | conf-Template setzt announce=false explizit; Abnahmetest prüft es im Container |
| Leere/kinderfreie Passwörter im Gameserver | Fremde joinen mit geratenem Namen | disallow_empty_password, App-generierte Zugangsdaten, Whitelist-Durchsetzung serverseitig |
| Kinderkonto mit Admin-Privilegien in der Welt (grant all) | Kind (oder Freund) zerstört Welt, ändert Settings | Admin-`name` = App-Systemkonto; Privilegien-Templates pro Rolle, keine grant-Rechte für Kinder |
| Host-Port auf 0.0.0.0 ohne Elternentscheidung | Welt aus dem Internet erreichbar, Produktversprechen gebrochen | Default LAN-Betrieb, Exposition nur als bewusster, dokumentierter Schritt |
| UPnP-Portöffnung durch die App | Dauerhaft offene Ports ohne Wissen der Eltern | Kein UPnP; VPN-Weg dokumentieren |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| "Server läuft" ohne Verbindungsinfo | Eltern wissen nicht, was sie dem Kind ins Spiel eintippen sollen | Adresse+Port+Spielername als Copy-Block/QR, Schritt-für-Schritt "So verbindet sich dein Kind" |
| Stilles Scheitern bei Nicht-Erreichbarkeit (CGNAT, Firewall) | "Kaputte App"-Eindruck, Support-Mails | Eingebaute Erreichbarkeits-Diagnose mit Klartext-Erklärungen |
| OOM/Crash zeigt nur "gestoppt" | Eltern starten neu, Welt crasht wieder, Frust | Exit-Ursache übersetzen ("zu wenig Speicher") + konkreter Fix-Button |
| Backup ohne Fortschritt/Ergebnisprüfung | Falsches Sicherheitsgefühl | Backup-Historie mit Größe, Zeitpunkt, Verifiziert-Status; Restore-Knopf daneben |
| Fachbegriffe (Container, Volume, Port-Binding) in der Eltern-UI | Zielgruppe (Eltern ohne Serverwissen) steigt aus | Weltenmetapher durchziehen: Welt, Spieler, Sicherung; Technik nur in einem Admin-Expertenbereich |
| Löschen einer Welt ohne Backup-Angebot | Unwiederbringlicher Verlust von Kinder-Bauwerken, maximaler Vertrauensschaden | Delete-Flow erzwingt Backup-Angebot + Namenstipp-Bestätigung |

## "Looks Done But Isn't" Checklist

- [ ] **World-Create:** Läuft im Demo, aber ohne RAM/CPU/pids-Limits und memswap im Container-Spec; `docker inspect` auf Limits prüfen
- [ ] **Einladungen:** UI zeigt Spielerliste, aber Join mit fremdem Namen ist serverseitig möglich; Negativ-Test (nicht eingeladener Join) durchführen
- [ ] **Backup:** Datei landet in Nextcloud Files, aber Restore wurde nie in eine frische Welt getestet; automatisierter Backup-Restore-Roundtrip
- [ ] **Stop/Start:** Funktioniert manuell, aber SIGTERM-Timeout zu kurz; mit aktiver Spielsession stoppen und Welt-Integrität prüfen
- [ ] **ExApp-Update:** App v(N) läuft, aber Update auf v(N+1) mit laufender Welt wurde nie durchgespielt; Update-Szenario mit Adoption laufender Container testen
- [ ] **Deinstallation:** App weg, aber `docker ps -a` und `docker volume ls` zeigen Gameworld-Reste; Uninstall-Cleanup + Orphan-Kommando verifizieren
- [ ] **Host-Reboot:** Nach Server-Neustart stimmen App-Status und Container-Realität nicht überein; Reboot-Test mit Reconciliation-Prüfung
- [ ] **Kid-Safety-Defaults:** conf wirkt sicher, aber announce/empty-password/default_privs nie im laufenden Container verifiziert; Werte aus dem Container auslesen und asserten
- [ ] **Store-Route:** manual-install grün, aber Installation über HaRP-Daemon vom Registry-Tag nie getestet; vor Submit einmal den echten Nutzerpfad gehen

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Socket statt Proxy released | HIGH | Architektur-Nacharbeit unter Zeitdruck + Security-Advisory; deshalb Phase-1-Entscheid, nicht nachrüsten |
| State-Drift / Orphans beim Nutzer | MEDIUM | Reconciliation nachliefern + Admin-Kommando "adopt/cleanup"; Labels machen das möglich, darum Labels von Tag 1 |
| Korrupte Backups entdeckt | HIGH | Betroffene Nutzer informieren, Backup-Verfahren ersetzen, alte Archive als unverifiziert markieren; Vertrauensschaden bleibt |
| OOM-korrumpierte Welt | MEDIUM | Letztes verifiziertes Backup einspielen; bei SQLite ggf. `.recover`; ohne Backup-Feature kein Rettungsweg, daher Backup früh |
| Welt versehentlich öffentlich erreichbar | HIGH | Sofort-Hotfix (Bindung/Whitelist), Advisory, betroffene Welten-Passwörter rotieren |
| ExApp-Update verliert App-DB | MEDIUM | Rekonstruktion aus Container-Labels + Welt-Volumes (deshalb beides pflegen); Migration nachliefern |
| Minecraft-Image mit gebündeltem JAR im Umlauf | MEDIUM | Image depublizieren, Laufzeit-Download-Variante nachschieben; vermeidbar durch Muster von Anfang an |

## Pitfall-to-Phase Mapping

Phasennamen als Themen, da die Roadmap noch nicht steht; Reihenfolge-Empfehlung implizit.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1 Docker-Socket/Privilegien | Phase 1: Provisionierungs-Kern (Architektur-Entscheid Proxy vs. Host-Agent, Owner-Entscheid lt. PROJECT.md) | Pen-Check: ExApp-Container kann keine fremden Container/Mounts erzeugen |
| 2 AppAPI-Daemon-Verwechslung | Phase 1: Provisionierungs-Kern | Welten starten unabhängig von Daemon-Typ (HaRP und AIO getestet) |
| 5 Ressourcenlimits/OOM | Phase 1 (Limits im Container-Spec) + Phase 2 (OOM-Erkennung/UX) | inspect zeigt Limits; provozierter OOM wird erkannt und erklärt |
| 8 Sichere Luanti-Defaults | Phase 1 (conf-Template) + Phase 3 (Einladungs-Durchsetzung) | Negativ-Join-Test; announce/empty-password im Container verifiziert |
| 3 ExApp-Update/State | Phase 2: Lifecycle & State | Update-Szenario-Test mit laufender Welt |
| 4 Orphans/Drift | Phase 2: Lifecycle & State (Reconciliation, Labels, Sagas) | Reboot-/Kill-/Uninstall-Tests ohne Drift und ohne Reste |
| 9 Kinderdaten/DSGVO | Phase 3: Rollen & Elternkontrolle (Datenmodell) + Release-Phase (privacy.md) | Datenmodell-Review: kein Alter, keine Telemetrie, Log-Rotation |
| 6 Backup-Korruption | Phase 4: Backup/Restore | Automatisierter Backup-Restore-Roundtrip als Abschlusskriterium |
| 7 NAT/UPnP/Erreichbarkeit | Phase 5: Netzwerk & Erreichbarkeit (Scope-Schnitt schon in der Roadmap) | Zwei-Netze-Test; CGNAT-Diagnose zeigt korrekte Meldung |
| 10 Store-Release-Mechanik | Phase 6: Hardening & Store-Release | Installation vom Store-Tag über HaRP-Daemon auf frischer NC |
| 11 Minecraft-Recht/Distribution | MVP-2-Planungsphase (Research-Task zuerst); Engine-Abstraktion schon in Phase 1 anlegen | Guidelines-Review dokumentiert; Image enthält kein server.jar; EULA-Consent im Flow |

## Sources

- Nextcloud AppAPI / ExApps: [Deployment configurations (Admin Manual)](https://docs.nextcloud.com/server/stable/admin_manual/exapps_management/DeployConfigurations.html), [Docker Socket Proxy FAQ (Developer Manual)](https://docs.nextcloud.com/server/stable/developer_manual/exapp_development/faq/DockerSocketProxy.html), [nextcloud/app_api](https://github.com/nextcloud/app_api) (DSP-Deprecation zugunsten HaRP, Entfernung zu NC 35 angekündigt), [cloud-py-api/docker-socket-proxy](https://github.com/cloud-py-api/docker-socket-proxy) , Confidence: HIGH (offizielle Doku + Repo)
- Luanti: [Backup Solutions (docs.luanti.org)](https://docs.luanti.org/for-server-hosts/backup-solutions/) (Cold-Backup als dokumentierter Weg), [Database backends (docs.luanti.org)](https://docs.luanti.org/for-server-hosts/database-backends/) (SQLite Default/robust, LevelDB korruptionsanfällig), [Server Setup (docs.luanti.org)](https://docs.luanti.org/for-server-hosts/setup/) (Port 30000, Whitelist nur als Mod, server_announce), [YunoHost minetest_ynh](https://git.yunohost.org/YunoHost-Apps/minetest_ynh/commit/b8f3e07594768142a6bd1c592857b9e1a5ebc81b) (sqlite3 .backup-Muster für Live-Kopie) , Confidence: HIGH für Backup/Backend, MEDIUM für einzelne conf-Default-Werte (im Bau gegen minetest.conf.example verifizieren)
- Minecraft: [Minecraft EULA and Commercial Usage Guidelines Updates (minecraft.net)](https://www.minecraft.net/de-de/article/minecraft-eula-and-commercial-usage-guidelines-updates) (EULA-Rework, Konsolidierung zu Minecraft Usage Guidelines) , Confidence: MEDIUM für Detailregeln (vor MVP 2 Originaltexte erneut lesen); Laufzeit-Download-Muster: etabliert u. a. durch itzg/minecraft-server (Training-Wissen, LOW bis MEDIUM, vor MVP 2 verifizieren)
- Container-Sicherheit (Socket = Host-Root, Proxy-Allowlisting, cap_drop): Standard-Sicherheitswissen, deckungsgleich mit Nextclouds eigener DSP-Begründung , Confidence: HIGH
- Eigene Projekterfahrung Findling/Connector (Store-Submit, Image-Tag-Fallen, NC-Versionspflege) , Confidence: HIGH
- DSGVO Art. 8 (Einwilligung Kinder, Deutschland 16): Gesetzestext, Training-Wissen , Confidence: HIGH (stabile Rechtslage)

---
*Pitfalls research for: Gameworld (kindgerechtes Gameserver-Portal als Nextcloud-ExApp)*
*Researched: 2026-10-19*
