<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Gameworld installieren

English version: [install.md](install.md)

Anleitung für Nextcloud-Admins. Was Gameworld darf und warum, steht ausführlich in [privacy.de.md](privacy.de.md).

Die Oberfläche von Gameworld folgt der Sprache des Nextcloud-Kontos (Deutsch, Englisch oder Französisch); Texte im Spiel und im Talk-Raum folgen der Sprache der Welt. Meldungen sind unten so zitiert, wie sie auf Deutsch erscheinen.

## 1. Installation aus dem App Store

1. Deploy-Daemon und Docker-Proxy einrichten (Abschnitte 2 und 3). Ohne beides kann AppAPI Gameworld nicht starten.
2. In Nextcloud unter "Apps" die App Gameworld suchen (Kategorie "Spiele") und installieren. AppAPI holt das Image `ghcr.io/street1983nk/gameworld` und startet es über den HaRP-Deploy-Daemon.
3. Die Standardwerte der Umgebungsvariablen passen, wenn der Proxy `gameworld-docker-proxy` heißt und im selben Netz hängt (Abschnitt 4).
4. Gameworld im Menü öffnen. Der Setup-Check (Abschnitt 7) prüft den Proxy; erst wenn er grün ist, lässt sich eine Welt erstellen.

Voraussetzungen:

- Nextcloud 33 bis 35 mit der App AppAPI und einem HaRP-Deploy-Daemon. Der ältere Docker Socket Proxy als Deploy-Daemon ist in AppAPI veraltet und wird nicht unterstützt.
- Docker auf dem Server mit Engine-API 1.44 oder neuer.
- Ein UDP-Portbereich auf dem Server, ein Port pro Welt (Standard 30000 bis 30019).

## 2. Was Gameworld zusätzlich braucht

- Einen eng gescopten Docker-Proxy (`tecnativa/docker-socket-proxy`), über den Gameworld die Welt-Container verwaltet. Gameworld spricht Docker nie direkt über den Socket an.
- Einen UDP-Portbereich auf dem Server, ein Port pro Welt.
- Beides hängt im selben Docker-Netz wie Gameworld. Das ist das Netz, in dem der Deploy-Daemon die ExApps startet.

## 3. Deploy-Daemon und Docker-Proxy

### 3a. Standard: eigenes Compose mit HaRP

HaRP, die ExApps und der Docker-Proxy teilen ein eigenes Docker-Netz `gameworld`. Der Proxy hat keinen Host-Port.

```yaml
services:
  appapi-harp:
    image: ghcr.io/nextcloud/nextcloud-appapi-harp:release
    restart: unless-stopped
    environment:
      # Geheimnis aus einer Datei, nie im Klartext in der Compose-Datei.
      HP_SHARED_KEY_FILE: /run/secrets/harp_shared_key
      NC_INSTANCE_URL: https://cloud.example.org
    secrets:
      - harp_shared_key
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./harp-certs:/certs
    ports:
      # Nur für den Reverse-Proxy von Nextcloud (Weiterleitung /exapps/).
      - "127.0.0.1:8780:8780"
    networks:
      - gameworld

  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
    restart: unless-stopped
    environment:
      # Nur was Gameworld braucht.
      CONTAINERS: 1
      IMAGES: 1
      POST: 1
      VOLUMES: 1
      # Alles andere explizit gesperrt, damit ein geänderter Image-Default nichts öffnet.
      EXEC: 0
      INFO: 0
      NETWORKS: 0
      BUILD: 0
      SYSTEM: 0
      SECRETS: 0
      SWARM: 0
      NODES: 0
      SERVICES: 0
      TASKS: 0
      PLUGINS: 0
      CONFIGS: 0
      DISTRIBUTION: 0
      AUTH: 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    # Bewusst kein Host-Port: der Proxy ist nur im Netz gameworld erreichbar.
    networks:
      - gameworld

networks:
  gameworld:
    name: gameworld

secrets:
  harp_shared_key:
    file: ./harp_shared_key.txt
```

- Das Geheimnis einmal erzeugen, zum Beispiel mit `openssl rand -hex 32 > harp_shared_key.txt`, und die Datei nur für root lesbar machen.
- Den Reverse-Proxy von Nextcloud so einrichten, dass `/exapps/` an `127.0.0.1:8780` geht (Beispiele für nginx, Apache und Caddy im HaRP-README).
- Den Daemon in Nextcloud registrieren: "Verwaltungseinstellungen", "AppAPI", "Deploy-Daemon registrieren", Vorlage HaRP, Netz `gameworld`, FRP-Adresse `appapi-harp:8782`, dasselbe Geheimnis. Oder per occ:
  `occ app_api:daemon:register harp_gameworld "HaRP" docker-install http <harp-adresse>:8780 https://cloud.example.org --net gameworld --harp --harp_frp_address appapi-harp:8782 --harp_shared_key <geheimnis>`
- Das Proxy-Image ist per Digest gepinnt; ein Update ist eine bewusste Entscheidung.

### 3b. Nextcloud All-in-One (AIO)

- Im AIO-Interface den optionalen Container "HaRP" einschalten. AppAPI legt den Daemon `harp_aio` dann automatisch an; ExApps laufen im Netz `nextcloud-aio`.
- Den Docker-Proxy in einer eigenen Compose-Datei neben AIO starten und in das Netz `nextcloud-aio` hängen:

```yaml
services:
  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
    restart: unless-stopped
    environment:
      CONTAINERS: 1
      IMAGES: 1
      POST: 1
      VOLUMES: 1
      EXEC: 0
      INFO: 0
      NETWORKS: 0
      BUILD: 0
      SYSTEM: 0
      SECRETS: 0
      SWARM: 0
      NODES: 0
      SERVICES: 0
      TASKS: 0
      PLUGINS: 0
      CONFIGS: 0
      DISTRIBUTION: 0
      AUTH: 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    # Kein Host-Port.
    networks:
      - nextcloud-aio

networks:
  nextcloud-aio:
    external: true
```

- Restrisiko bei AIO: Jeder Container im Netz `nextcloud-aio`, auch Nextcloud selbst, erreicht dann den Proxy (Abschnitt 6).

### 3c. Host-Netz (nicht empfohlen)

- Die Daemon-Vorlage "HaRP Proxy (Host)" startet ExApps im Host-Netz. Dann erreicht Gameworld den Proxy nur über einen Host-Port.
- Wer das trotzdem nutzt, bindet den Proxy ausschließlich an Loopback (`ports: ["127.0.0.1:2375:2375"]`) und setzt `GAMEWORLD_DOCKER_URL=tcp://127.0.0.1:2375`.
- Warnung: Dann kann jeder Prozess auf dem Server und jeder Container im Host-Netz den Proxy benutzen, also Docker mit root-gleichen Rechten steuern. Besser Abschnitt 3a.

## 4. Gameworld konfigurieren

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `GAMEWORLD_DOCKER_URL` | `tcp://gameworld-docker-proxy:2375` | Adresse des Docker-Proxys, nie ein roher Docker-Socket |
| `GAMEWORLD_PORT_RANGE` | `30000-30019` | UDP-Portbereich für Welten, höchstens 200 Ports |

## 5. UDP-Ports

- Welten sind nur für das Heimnetz gedacht.
- Keine Portfreigabe im Router einrichten, UPnP am Router nicht nutzen.
- Fernzugriff kommt später über VPN.
- Die Firewall des Servers muss den UDP-Bereich im LAN erlauben.

## 6. Restrisiko ehrlich benannt

- Mit `CONTAINERS=1` und `POST=1` kann jeder, der den Proxy erreicht, beliebige Container erzeugen, auch privilegierte und solche mit dem Dateisystem des Hosts. Das ist root-gleich auf dem Server.
- Deshalb: den Proxy nie auf einem Host-Port veröffentlichen, nur im Docker-Netz von Gameworld betreiben.
- Gemeinsames Docker-Netz: Jeder Container in diesem Netz erreicht den Proxy. Das sind andere ExApps desselben Deploy-Daemons und bei AIO alle Container im Netz `nextcloud-aio`, Nextcloud eingeschlossen.
- Gameworld selbst erzeugt ausschließlich fest vorgegebene, gehärtete Welt-Container: Benutzer 30000 (nicht root), alle Capabilities entzogen, schreibgeschütztes Dateisystem, 512 MB RAM (Abenteuer-Welt 1 GB), 1 CPU, 128 Prozesse.
- Der Gameworld-Container selbst läuft als uid 10001, nicht als root.
- Gameworld verändert nur Container mit dem eigenen Instanz-Label.
- Neue und wiederhergestellte Welten haben einen root-eigenen Weltordner mit Sticky-Bit und einen root-eigenen Ordner `worldmods`: Luanti kann Zugangsdatei, Regeldatei und Gameworld-Mods weder ändern noch löschen. Welten aus Versionen vor 1.0.0 bekommen `worldmods` beim nächsten Start root-eigen; den Weltordner härtet erst eine Sicherung mit anschließendem Wiederherstellen (Abschnitt 12).

<a id="setup-check"></a>

## 7. Setup-Check

Die Gameworld-Seite prüft beim Öffnen den Docker-Proxy. Die Prüfung verändert nichts: schreibende Anfragen gehen nur an die nicht existierende Ressource `gameworld-probe-nonexistent`. Solange ein Fehler offen ist, bleibt "Welt erstellen" gesperrt. Jede Meldung endet mit einem Link auf diesen Abschnitt.

| Meldung | Abhilfe |
|---------|---------|
| Gameworld findet den Dienst gameworld-docker-proxy nicht (`proxy_dns`) | Der Proxy hängt in einem anderen Docker-Netz oder heißt anders. In das Netz des Deploy-Daemons hängen (Abschnitt 3a: `gameworld`, bei AIO `nextcloud-aio`) |
| Der Docker-Proxy unter Host:Port antwortet nicht (`proxy_timeout`) | Meist ein anderes Docker-Netz oder eine Firewall vor dem Port. Netz und Firewall prüfen |
| Der Docker-Proxy unter Host:Port nimmt keine Verbindung an (`proxy_refused`) | Container `gameworld-docker-proxy` starten (`docker ps`), Port in `GAMEWORLD_DOCKER_URL` prüfen |
| Gameworld soll nie direkt mit dem Docker-Socket sprechen (Warnung, `docker_url_socket`) | `GAMEWORLD_DOCKER_URL` auf `tcp://gameworld-docker-proxy:2375` setzen, kein `unix://` |
| Der Docker-Proxy liegt auf einer Adresse außerhalb des privaten Netzes (Warnung, `docker_url_exposed`) | Host-Port des Proxys entfernen, Dienstnamen im Docker-Netz verwenden |
| Gameworld erreicht den Docker-Proxy nicht | Dienst `gameworld-docker-proxy` starten, `GAMEWORLD_DOCKER_URL` und Netz prüfen |
| Docker-Engine zu alt, benötigt API 1.44 oder neuer | Docker auf dem Server aktualisieren |
| Kein Zugriff auf Container | `CONTAINERS=1` setzen |
| Keine schreibenden Anfragen erlaubt | `POST=1` setzen |
| Kein Zugriff auf Images | `IMAGES=1` setzen |
| Kein Zugriff auf Volumes | `VOLUMES=1` setzen |
| Nicht geprüft: Erst POST=1 setzen | `POST=1` setzen, dann erneut prüfen |
| Proxy zu weit offen: Befehle in Containern erlaubt (Warnung) | `EXEC=0` setzen |
| Proxy gibt Systeminformationen preis (Warnung) | `INFO=0` setzen |
| Unerwartete Antwort auf Pfad mit HTTP-Code | Proxy-Image und Flags mit Abschnitt 3 vergleichen |
| Gameworld antwortet nicht | ExApp in den Nextcloud-Einstellungen (AppAPI) prüfen |

Fehlt der Proxy oder ist er nicht erreichbar (`proxy_dns`, `proxy_refused`, `proxy_timeout`) und steht `GAMEWORLD_DOCKER_URL` auf der Standardadresse, zeigt die Gameworld-Seite zusätzlich einen fertigen `docker run`-Befehl für AIO und einen für das eigene Compose, jeweils mit Kopier-Knopf. Beide legen den Container `gameworld-docker-proxy` mit denselben Einstellungen wie in Abschnitt 3a und 3b an, ohne Host-Port.

Nach jeder Änderung am Proxy den Dienst neu starten und auf der Gameworld-Seite "Erneut prüfen" wählen.

## 8. Speicherbedarf, Neustarts und Updates

- Jede Welt hat ein festes Speicherlimit ohne Swap: Kreativ-Welt ("Bauen (kreativ)") 512 MB, Abenteuer-Welt ("Abenteuer (sanft)") 1 GB. Einstellen lässt sich das nicht.
- Für den Heimserver grob rechnen: Summe der Limits aller gleichzeitig laufenden Welten plus Nextcloud muss in den Arbeitsspeicher passen.
- Welten haben keine eigene Neustart-Policy in Docker.
- Nach einem Server-Neustart startet Gameworld beim eigenen Start alle Welten, die vorher liefen. Gestoppte Welten bleiben gestoppt.
- Eine Welt, die wegen Speichermangel beendet wurde, startet nicht automatisch. Das Dashboard zeigt den Grund, Starten geht per Klick.

### Deaktivieren und Updates

- Bei jedem Deaktivieren von Gameworld, auch direkt vor einem Update und vor einer Deinstallation, stoppt und entfernt Gameworld alle eigenen Welt-Container. Spielende werden dabei kurz getrennt.
- Volumes mit den Spielständen, Einladungen, Regeln und Sicherungen bleiben unverändert.
- Sobald Gameworld wieder läuft (nach dem Aktivieren oder nach dem Update), baut Gameworld die Container aller Welten neu auf, die vorher liefen. Die Welten kommen von selbst wieder, Kinder treten einfach neu bei.
- Ohne laufendes Gameworld gibt es damit nie unverwaltete Spielserver ohne Pause und Spielzeitregeln.

## 9. Zugang, Rollen und Spielpasswörter

### Rollen

- Verwalter sind die Mitglieder der Nextcloud-Gruppe `admin` und der Verwalter-Gruppen (unten). Nur sie erstellen, starten, stoppen und löschen Welten und laden Spieler ein. Alle Verwalter sehen alle Welten und bedienen Pause, Ferien, Zeitzone und Adresse für Spieler; Sicherungen bleiben je Verwalter getrennt.
- Spieler sind alle eingeladenen Nextcloud-Konten, direkt oder über eine eingeladene Nextcloud-Gruppe. Sie sehen nur ihre eigenen Welten mit der Verbindungsinfo, keine Steuerknöpfe und keine anderen Spieler.
- Gameworld hat keine eigene Benutzerverwaltung. Rollen kommen bei jeder Anfrage aus Nextcloud (bis zu 30 Sekunden zwischengespeichert). Wer aus allen Verwalter-Gruppen entfernt wird, verliert die Verwaltung spätestens nach 30 Sekunden.

### Verwalter-Gruppen

- Standard: Nur die Gruppe `admin` verwaltet Gameworld. Sie bleibt immer Verwalter-Gruppe.
- Nextcloud-Admins tragen im Abschnitt "Verwalter-Gruppen" der Gameworld-Seite weitere Gruppen ein, etwa für Lehrkräfte oder Gruppenleitungen. Den Abschnitt sehen nur Nextcloud-Admins. Mitglieder dieser Gruppen werden dadurch nicht Nextcloud-Admin.
- Einladungsgrenze: Gruppen-Verwalter ohne Nextcloud-Adminrechte laden nur Konten aus Gruppen ein, in denen sie selbst Mitglied oder Gruppenadmin sind. Andere Konten zeigt ihnen Nextcloud nicht; Gameworld umgeht diese Grenze nicht.
- Gelöschte und deaktivierte Konten räumt Gameworld nur auf, wenn ein Nextcloud-Admin Gameworld geöffnet hat. Gruppen-Verwalter lösen das nie aus, weil Nextcloud ihnen nicht alle Konten zeigt.
- Warnung: Keine Gruppe wählen, in der Kinder sind. Jedes Mitglied einer Verwalter-Gruppe kann Kinder einladen und die Pause aufheben. Gameworld kann das nicht prüfen.

### Erwachsen-Schalter

- Verwalter markieren ein Konto im Einladen-Dialog oder später in der Spielerliste als erwachsen. Das gilt global für das Konto, in allen Welten.
- Einschalten verlangt eine Bestätigung mit den Folgen im Klartext. Ausschalten geht ohne Dialog.
- Was er tut: Das Konto spielt sofort ohne Pause, Zeitfenster und Spielzeitregeln, auch mitten im Spiel. Eine vorhandene Spielzeitregel bleibt gespeichert und gilt wieder, sobald der Schalter aus ist. Erwachsene erscheinen nicht im Tagesrückblick.
- Was er nie tut: Erwachsene bekommen keine Verwaltungsrechte in Gameworld und keine Luanti-Adminrechte. Einladung und Spielpasswort brauchen sie wie alle anderen.
- Nur Konten von Erwachsenen markieren, nie das Konto eines Kindes.

### Nur Eingeladene kommen hinein

- Jede Welt bekommt den Welt-Mod `gameworld_access`. Er lehnt jeden Namen ab, der nicht eingeladen ist, noch vor der Anmeldung im Spiel. Die Meldung im Spiel lautet "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
- Einladen, Entfernen und neue Passwörter wirken sofort, ohne Neustart der Welt. Spieler, deren Einladung endet, trennt die Welt binnen weniger Sekunden.
- Fünf falsche Passwörter sperren einen Spielernamen für zehn Minuten.
- Welten, die vor diesem Update schon liefen, bekommen den Zugangsschutz erst mit dem nächsten Neustart der Welt (Stoppen und Starten im Dashboard).

### Spielername und Spielpasswörter

- Jedes Konto hat genau einen Spielernamen und ein Spielpasswort, gültig für alle Welten, in die es eingeladen ist. Das Passwort hat die Form `xxxx-xxxx-xxxx`.
- Gameworld speichert keine Spielpasswörter. Sie werden bei Bedarf aus einem Geheimnis abgeleitet, das in der Nextcloud-Konfiguration der ExApp liegt. Die Welt kennt nur einen SRP-Verifier, nicht das Passwort.
- "Neues Passwort" in der Spielerverwaltung macht das alte sofort ungültig, in allen Welten, ohne Neustart.
- "Name ändern" vergibt einen neuen Spielernamen. Im Spiel ist das ein neuer Spieler mit eigenem Spielstand.
- Updates der ExApp behalten das Geheimnis, alle Spielpasswörter bleiben gleich.
- Randfall Neuinstallation: Wird Gameworld deinstalliert und neu installiert, entsteht ein neues Geheimnis, denn AppAPI löscht beim Deinstallieren die Konfiguration der ExApp, auch wenn die Daten bleiben. Dann ändern sich alle Spielpasswörter einmalig. Gameworld schreibt die neuen Zugänge automatisch in alle Welten; die Kinder brauchen danach das neue Passwort aus ihrer Gameworld-Seite.

### Adresse für Spieler

- In den Einstellungen des Dashboards steht die "Adresse für Spieler": Rechnername oder IP-Adresse des Servers im Heimnetz, ohne `http://` und ohne Port. Die Kinder sehen diese Adresse in ihrer Verbindungsinfo.
- Bleibt das Feld leer, zeigt Gameworld den Rechnernamen aus der Adresszeile des Browsers. Das passt nicht, wenn Nextcloud über `localhost` oder über eine Internetadresse aufgerufen wird; dann die Heimnetz-Adresse eintragen.
- Der Port jeder Welt ist ein UDP-Port aus dem Bereich in Abschnitt 5. Er muss im Heimnetz erreichbar sein.
- Kein Zugang aus dem Internet ohne VPN: keine Portfreigabe im Router, siehe Abschnitt 5.

## 10. Spielzeit

### Grundregeln

- Spielzeit ist Opt-in: Ohne Regel gibt es keine Begrenzung. Jedes Kind startet mit "Keine Begrenzung".
- Ein Kind hat ein einziges Tageskontingent über alle Welten. Wer eine Stunde am Tag darf, kann sie auf mehrere Welten verteilen, aber nicht in jeder Welt eine Stunde spielen. Gameworld gleicht den Verbrauch alle 15 Sekunden zwischen den Welten ab.
- Eingestellt wird im Abschnitt "Spielzeit" unter der Weltenliste, mit "Bearbeiten" je Kind. Vier Voreinstellungen helfen beim Start: "Keine Begrenzung", "Nur am Wochenende" (Sa und So je 2 Stunden, 9 bis 19 Uhr), "Jeden Tag 1 Stunde" (9 bis 19 Uhr) und "Schultage kurz, Wochenende länger" (Mo bis Fr 1 Stunde, 15 bis 19 Uhr; Sa und So 2 Stunden, 9 bis 19 Uhr). Danach lässt sich jeder Tag in seiner Kachel ändern: Spielen erlaubt oder nicht, Tageslimit, Uhrzeit von und bis oder ganzer Tag.
- Der Verbrauch zählt online verbrachte Zeit. Auch wer nur verbunden ist und nichts tut (AFK), verbraucht Spielzeit.
- Verwalter haben nie Zeitregeln und kommen immer hinein. Wird ein Konto aus allen Verwalter-Gruppen entfernt, bemerkt Gameworld das im Hintergrund nach höchstens etwa 60 Sekunden; ab dann gelten für dieses Konto die Regeln wie für alle anderen.

### Ferien

- Der Abschnitt "Ferien" ist eine Liste von Zeiträumen für den ganzen Haushalt (von, bis, Bezeichnung optional). Ein laufender Zeitraum ist mit "läuft gerade" markiert.
- Im Spielzeit-Dialog hat jedes Kind einen eigenen Block "In den Ferien" (Vorschlag: jeden Tag 2 Stunden, 9 bis 20 Uhr). Ohne eigenen Ferienplan gilt in den Ferien die normale Woche.

### Zeitzone

- Alle Uhrzeiten gelten in der Zeitzone des Haushalts, Vorgabe `Europe/Berlin`. Sie steht in den Einstellungen unter der Adresse für Spieler; der Knopf "Zeitzone dieses Browsers übernehmen" setzt die Zone des Browsers. Sommer- und Winterzeit rechnet Gameworld selbst.

### Zeitfenster pro Welt

- Mit "Zeitfenster" in der Welt-Zeile ist eine Welt nur zu bestimmten Zeiten offen, etwa für eine Schul- oder Vereinswelt ("Offen Mi 10 bis 12 Uhr").
- Die Welt läuft außerhalb des Fensters weiter. Kinder kommen nicht hinein und werden am Fensterende getrennt; Verwalter und als erwachsen markierte Konten kommen immer hinein.

### Im Spiel

- Kinder sehen auf ihrer Gameworld-Seite den Block "Deine Spielzeit heute" mit der Restzeit oder der nächsten Spielzeit.
- Im Spiel warnt der Chat bei 10, 5 und 1 Minute Rest. Am Ende trennt die Welt das Kind mit einem Text wie "Deine Spielzeit für heute ist vorbei. Morgen ab 9 Uhr kannst du wieder spielen." Ein Beitritt außerhalb der erlaubten Zeit wird mit einem passenden Text abgelehnt, etwa "Heute ist kein Spieltag. Am Samstag ab 9 Uhr kannst du wieder spielen." oder "Diese Welt ist gerade zu. Heute ab 10 Uhr ist sie wieder offen." Eine Uhrzeit steht nur da, wenn die Eltern eine Startzeit gesetzt haben; bei "ganzer Tag" heißt es zum Beispiel "Morgen kannst du wieder spielen." Dieselben Sätze stehen auf der Gameworld-Seite des Kindes.
- Wer die Welt verlässt, muss etwa 2 Sekunden warten, bevor er wieder beitreten kann ("Bitte einen Moment warten und dann nochmal beitreten."). Das schützt die Welt vor einem Absturz von Luanti 5.17.0 bei sofortigem Wiederbeitritt.
- Welten, die vor diesem Update schon liefen, setzen Spielzeiten erst nach dem nächsten Neustart der Welt durch. Das Dashboard zeigt dann "Neustart nötig, damit Spielzeiten gelten."

### Bekanntes Verhalten

- Tagesgrenze um 00:00: Ein Kind mit Regeln wird um 00:00 getrennt, auch wenn sein Plan den ganzen Tag erlaubt (fail closed an der Tagesgrenze). Nach dem nächsten Zeittakt, höchstens etwa 15 Sekunden später, kann es wieder beitreten.
- Betritt ein Kind eine Welt zum allerersten Mal, bleiben die Sekunden bis zum ersten Zeittakt (höchstens etwa 20) ungezählt. Das passiert einmal je Kind und Welt und schützt vor doppelter Zählung.

### Ausfallverhalten

- Welt-Neustart: ändert nichts. Die Welt führt ihr eigenes Zählbuch im Welt-Volume; nach einem Neustart, einem Absturz oder einem Server-Neustart gelten Verbrauch und Regeln weiter.
- ExApp-Neustart oder Update: Die Welten setzen den zuletzt geschriebenen Stand weiter durch und zählen weiter. Nach dem Start verbucht Gameworld den Verbrauch nach.
- ExApp länger aus, am selben Tag: Das Limit gilt in jeder Welt weiter, aber der Abgleich zwischen den Welten ruht. Wer in zwei Welten gleichzeitig spielt, kann bis zur Rückkehr der ExApp doppelt so lange spielen.
- ExApp aus über Mitternacht: Kinder mit Regeln kommen nach Tagesende nicht mehr hinein, bis die ExApp wieder läuft (fail closed). Kinder ohne Regeln sind nicht betroffen.

### Datensparsamkeit

- Gameworld speichert nur Tagessummen in Sekunden und nur für Kinder mit Regeln. Kinder ohne Regeln werden nicht gezählt.
- Tagessummen werden nach 7 Tagen gelöscht.
- Keine Uhrzeiten einzelner Sitzungen, keine IP-Adressen. Das Zählbuch in der Welt enthält nur Spielernamen und Sekunden.

## 11. Eltern-Handy und Talk

### Pause für alle Welten

- Oben auf der Gameworld-Seite steht die Karte "Pause für alle Kinder". Sie führt zur Pause-Seite, die auch auf dem Handy gut bedienbar ist: 15, 30 oder 60 Minuten.
- Kinder bekommen im Spiel 30 Sekunden vorher die Nachricht "In 30 Sekunden ist Pause." und werden dann mit "Kurze Pause! Deine Eltern brauchen dich gerade. Danach kannst du weiterspielen." getrennt. Bis zum Ende der Pause kommen sie nicht hinein. Das gilt für alle Kinder, auch für Kinder ohne Spielzeitregeln.
- Verwalter und als erwachsen markierte Konten bleiben in der Welt und kommen jederzeit hinein.
- "Weiter" beendet die Pause sofort. "Für heute Schluss" sperrt bis Mitternacht; das Kind liest dann zum Beispiel "Für heute ist Schluss. Morgen ab 9 Uhr kannst du wieder spielen." Ist morgen laut Plan kein Spieltag, steht nur "Für heute ist Schluss." da.
- Die Pausenzeit zählt nicht auf die Spielzeit. Zeitfenster laufen weiter: Endet ein Fenster während der Pause, verlängert die Pause es nicht.
- Welten mit einem älteren Gameworld-Mod werden beim Start einer Pause automatisch neu gestartet, damit die Pause sicher greift.

### Benachrichtigungen aufs Handy

- Gameworld schickt Hinweise als normale Nextcloud-Benachrichtigungen an alle Verwalter. Auf dem Handy kommen sie über die Nextcloud-App an. Voraussetzung: Die App "Notifications" ist aktiv, und die Instanz kann Push senden (Push-Proxy der Nextcloud-App, bei öffentlich erreichbaren Instanzen Standard).
- Ein Tipp auf die Benachrichtigung öffnet die passende Gameworld-Seite im Browser. Wer nicht angemeldet ist, meldet sich an und landet danach direkt auf der Seite.
- Die Adresse der Links merkt sich Gameworld beim ersten Besuch eines Verwalters (auch mit Nextcloud in einem Unterordner, etwa `https://example.org/nextcloud`). Öffnet ein Verwalter Gameworld später über eine andere Adresse, fragt die Seite einmal: "Links in Hinweisen künftig über diese Adresse öffnen?" mit alter und neuer Adresse. Erst nach "Ja, diese Adresse" gilt die neue. Eine https-Adresse ersetzt Gameworld nie durch eine http-Adresse, dann kommt auch keine Frage.

### Hinweis bei fremdem Beitrittsversuch

- Versucht ein nicht eingeladener Spielername einer Welt beizutreten, bekommen alle Verwalter "Unbekannter Spielername in <Welt>" mit Name und Uhrzeit. Die Seite "Beitrittsversuche" zeigt alle Versuche des Tages; mit "Jemanden einladen" lässt sich wie gewohnt einladen. Einen fremden Namen freizugeben gibt es bewusst nicht.
- Gedrosselt: höchstens ein Hinweis je Name, Welt und Tag, insgesamt höchstens 5 am Tag, danach genau eine Sammelnachricht "Weitere Beitrittsversuche".
- Kein Hinweis bei einem falschen Spielpasswort eines eingeladenen Kindes und bei einer anderen Groß- und Kleinschreibung eines eingeladenen Namens.

### Tagesrückblick

- Jeder Verwalter bekommt einmal am Abend den "Tagesrückblick" mit den Spielminuten je Kind, Vorgabe 20 Uhr. Uhrzeit und An/Aus stellt jeder Verwalter selbst in den Einstellungen ein ("Tagesrückblick am Abend").
- Der Rückblick kommt nur in der halben Stunde nach der eingestellten Uhrzeit. Hat bis dahin niemand gespielt, kommt an diesem Tag keiner mehr, auch wenn später noch gespielt wird. Auch nach einem Neustart kommt er höchstens einmal am Tag.
- Im Rückblick (Benachrichtigung und Seite) erscheinen nur Kinder, für die dieser Haushalt Spielzeit-Regeln eingestellt hat. Eingeladene Kinder ohne Regeln, etwa Freundinnen und Freunde aus anderen Familien, erscheinen nirgends mit Minuten.

### Talk-Raum pro Welt

- Ist die App Talk installiert, bekommt jede Welt einen eigenen Raum "Gameworld: <Welt>". Er ist nie öffentlich und nicht auffindbar.
- Mitglieder folgen den Einladungen der Welt: eingeladene Konten und Gruppen plus alle Verwalter. Wer später in eine eingeladene Gruppe kommt, erscheint nach dem nächsten Abgleich (spätestens nach 5 Minuten) im Raum. Wer in Talk von Hand hinzugefügt wird, ohne eingeladen zu sein, wird beim Abgleich wieder entfernt.
- Verwalter sind Moderatoren. Mit "Nur lesen" in der Welt-Zeile lässt sich das Schreiben im Raum sperren. Anrufe folgen den Talk-Standards der Instanz.
- Wird die Welt gelöscht, löscht Gameworld den Raum samt Verlauf; der Lösch-Dialog weist darauf hin.
- Ohne Talk läuft Gameworld unverändert weiter. Wird Talk später installiert oder wieder aktiviert, legt Gameworld die fehlenden Räume beim nächsten Abgleich an.

### Wem der Talk-Raum gehört

- Gameworld führt je Raum ein handelndes Besitzerkonto. Wird dieses Konto gelöscht oder ist es kein Verwalter mehr, übernimmt der dienstälteste Verwalter den Raum beim nächsten Abgleich von selbst.
- Talk selbst erlaubt Gameworld keinen Besitzerwechsel. Ein früherer Verwalter, dessen Konto noch existiert, bleibt darum Besitzer im Sinne von Talk und kann den Raum weiter lesen. Die Weltkarte zeigt dann einen Hinweis und den Knopf "Raum neu anlegen": Der alte Raum wird mit seinem ganzen Verlauf gelöscht, der neue bekommt alle Eingeladenen und Verwalter, den früheren Verwalter nicht mehr. Das passiert nie automatisch.
- Sperrfall: Gehört der alte Raum niemandem mehr, der ihn verwalten kann, legt Gameworld einen neuen Raum an und meldet den alten. Löschen kann ihn dann nur ein Nextcloud-Admin auf dem Server mit `occ talk:room:delete <token>`; den Token zeigt die Gameworld-Seite.

### Gameworld-Bot

- Der Bot "Gameworld" schreibt in den Raum der Welt: "Die Welt ist gestartet." und "Die Welt ist gestoppt.", "<Name> ist jetzt in der Welt." und "<Name> hat die Welt verlassen." (je Person und Welt höchstens alle 10 Minuten), "Pause bis H:MM Uhr.", "Für heute ist Schluss.", "Die Pause ist vorbei." (bei "Weiter" und wenn die Pause von selbst endet) und "Noch 10 Minuten Spielzeit für <Name>." (je Kind und Welt höchstens einmal am Tag, auch wenn es sich neu verbindet).
- Anzeigenamen stehen ohne echtes "@" im Bot-Text, damit ein Name wie "@all" niemanden anpingt.
- Mit Ton kommen nur Pause, "Für heute ist Schluss." und die 10-Minuten-Warnung. Start, Stopp, Beitritt, Verlassen und das Pausenende kommen still.
- Der Bot liest keine Nachrichten der Kinder mit.

### Datensparsamkeit

- Gameworld speichert keine Chatinhalte aus Talk.
- Für Rückblick und Hinweise speichert Gameworld nur Tagessummen der Spielzeit je Kind mit Regeln und Welt sowie Spielernamen und Uhrzeit fremder Beitrittsversuche. Beides wird nach 7 Tagen gelöscht.
- Für die Drossel der Bot-Meldungen merkt sich Gameworld je Welt und Konto den Zeitpunkt der letzten Meldung, ebenfalls höchstens 7 Tage. Die Rückblick-Einstellung eines Kontos, das kein Verwalter mehr ist, wird beim nächsten Abgleich gelöscht. Das handelnde Besitzerkonto eines Talk-Raums bleibt gespeichert, solange es den Raum gibt (Übernahme siehe "Wem der Talk-Raum gehört").

## 12. Sicherungen

### Wo die Sicherungen liegen

- In der Verwaltungsansicht hat jede Welt den Bereich "Sicherungen". "Jetzt sichern" legt eine Datei in den eigenen Nextcloud-Dateien ab: `Gameworld/Sicherungen/<Weltname>/<weltname>-JJJJ-MM-TT-HHMM.tar.gz` (Uhrzeit in der Haushalts-Zeitzone).
- Der Ordnername folgt der Kontosprache des Verwalters: `Gameworld/Sicherungen` (Deutsch), `Gameworld/Backups` (Englisch), `Gameworld/Sauvegardes` (Französisch). Nach einem Sprachwechsel bleiben ältere Sicherungen in ihrem Ordner und weiter in der Liste.
- Die Datei liegt in den Dateien des Verwalters, der gesichert hat. Sie lässt sich wie jede andere Datei herunterladen, teilen oder in eine eigene Datensicherung des Servers aufnehmen.
- Die Liste zeigt je Sicherung Datum und Größe, darunter die Gesamtgröße. Gameworld löscht nie selbst eine Sicherung, auch nicht beim Löschen der Welt. Alte Sicherungen löscht der Verwalter in Nextcloud Files.
- Mehrere Verwalter sehen in der Liste nur ihre eigenen Sicherungen. Wiederherstellen kann jeder nur aus seinen eigenen.

### Was gesichert wird und was nicht

- Gesichert wird die ganze Welt: Karte, Spielerdaten, Inventare und Spielstände (die SQLite-Dateien des Weltordners).
- Nicht gesichert werden die Einladungen, Spielpasswörter, Spielzeitregeln und die Gameworld-Mods. Sie kommen aus Gameworld selbst und werden nach dem Wiederherstellen frisch eingerichtet, ebenso die Welteinstellungen (`world.mt`), die zwar in der Datei stehen, aber nie aus ihr übernommen werden.

### Kurze Pause beim Sichern

- Für eine saubere Sicherung hält Gameworld die Welt kurz an: Kinder lesen im Spiel "Die Welt macht gleich eine kurze Pause." und werden mit "Die Welt macht kurz Pause. Gleich geht es weiter." getrennt. Danach startet die Welt von selbst wieder, meist nach wenigen Sekunden.
- Spielen gerade Kinder, fragt Gameworld vorher nach, zum Beispiel "In der Welt spielt gerade 1 Kind, es wird kurz getrennt." Erst nach der Bestätigung geht es los.
- Während der Sicherung zeigt die Weltkarte "Wird gesichert ...", die anderen Knöpfe der Welt sind so lange gesperrt. Scheitert die Sicherung, etwa weil der Platz in den Nextcloud-Dateien nicht reicht, steht der Grund an der Weltkarte, die Welt läuft weiter, und der Verwalter, der gesichert hat, bekommt eine Benachrichtigung. Dasselbe gilt für ein gescheitertes Wiederherstellen.

### Wiederherstellen

- "Wiederherstellen" an einer Sicherung setzt die Welt auf diesen Stand zurück. Die Sicherheitsabfrage nennt die Datei; ohne Bestätigung passiert nichts.
- Vorher legt Gameworld den aktuellen Stand als eigene Sicherung mit dem Zusatz `vor-restore` daneben ab. Wer sich vertan hat, stellt diese Datei einfach wieder her.
- Gameworld prüft jede Sicherung vor dem Einspielen: Nur Sicherungen dieser Welt, unverändert seit dem Ablegen, werden eingespielt. Eine veränderte oder fremde Datei lehnt Gameworld ab, die Welt bleibt dann wie sie war.
- Platzbedarf auf dem Server: Beim Wiederherstellen braucht Gameworld kurzzeitig bis zum Dreifachen der Sicherungsgröße an freiem Speicher (heruntergeladene Sicherung, Sicherung des aktuellen Stands, entpackte Welt). Beim Sichern reicht etwa die einfache Größe.

<a id="cleanup"></a>

## 13. Deinstallieren und aufräumen

### Was beim Deinstallieren bleibt

- Vor dem Deinstallieren deaktiviert AppAPI Gameworld. Dabei stoppt und entfernt Gameworld alle eigenen Welt-Container (Abschnitt 8).
- AppAPI entfernt den Gameworld-Container. Das Daten-Volume `nc_app_gameworld_data` löscht es nur, wenn "Daten löschen" gewählt wird.
- Die Volumes der Welten (`gameworld-<instanz>-<welt>`) und die Sicherungen in Nextcloud Files bleiben immer stehen, absichtlich: Keine Welt geht still verloren.
- Eine Neuinstallation ohne "Daten löschen" übernimmt die Welten wieder; die Spielpasswörter ändern sich dabei einmalig (Abschnitt 9). Nach "Daten löschen" kennt eine neue Installation die alten Welten nicht mehr; ihre Volumes und Container sind dann Reste.

### Reste in der App entfernen

- Solange Gameworld installiert ist, zeigt der Abschnitt "Reste früherer Installationen" auf der Gameworld-Seite Container und Spielstände anderer, früherer Gameworld-Installationen auf diesem Docker-Host. Den Abschnitt sehen nur Nextcloud-Admins.
- Jeder Eintrag lässt sich einzeln entfernen, jeweils mit eigener Bestätigung. Eigene Welten und Container ohne Gameworld-Label fasst Gameworld dabei nie an.
- Einen Spielstand zu entfernen löscht die Welt endgültig. Vorher eine Sicherung prüfen.

### Reste nach der Deinstallation: gameworld-orphans.sh

Nach der Deinstallation hilft ein Skript auf dem Docker-Host. Es braucht die docker CLI mit Rechten auf den Docker-Daemon (root oder Gruppe docker).

```sh
curl -fsSLO https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/master/scripts/gameworld-orphans.sh
sh gameworld-orphans.sh
```

- Ohne Optionen listet das Skript nur auf: Container mit dem Label `gameworld.managed=true` und Volumes mit Namen nach dem Schema `gameworld-<instanz>-<welt>`. Es ändert nichts.
- `--remove-containers` entfernt die gelisteten Container nach getippter Bestätigung `yes`.
- `--remove-volumes` löscht die gelisteten Volumes und damit die Spielstände darin, immer nach getippter Bestätigung `delete`.
- `--yes` überspringt nur die Frage für Container, nie die für Volumes.
- Nextcloud, AppAPI, HaRP, der Docker-Proxy und andere Projekte werden nie angefasst.
- Warnung zu `--remove-volumes`: Die Welten sind danach unwiederbringlich weg. Vorher die Sicherungen in Nextcloud Files prüfen. Läuft Gameworld noch, stehen die eigenen Welten mit in der Liste; das Skript warnt dann.
