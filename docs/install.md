# Gameworld installieren

Anleitung für Nextcloud-Admins. Gilt für die Entwicklungsphase; die Store-Installation folgt mit dem Store-Release.

## 1. Was Gameworld zusätzlich braucht

- Einen eng gescopten Docker-Proxy (`tecnativa/docker-socket-proxy`), über den Gameworld die Welt-Container verwaltet. Gameworld spricht Docker nie direkt über den Socket an.
- Einen UDP-Portbereich auf dem Server, ein Port pro Welt (Default 30000 bis 30019).

## 2. Docker-Proxy einrichten

Den Dienst neben dem AppAPI-Deploy-Daemon (z. B. HaRP) in dessen Compose-Datei ergänzen:

```yaml
services:
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
    # Bewusst kein Host-Port: der Proxy ist nur im Deploy-Netz erreichbar.
    networks:
      - <netz-des-appapi-deploy-daemons>

networks:
  <netz-des-appapi-deploy-daemons>:
    external: true
```

- `<netz-des-appapi-deploy-daemons>` durch das Docker-Netz ersetzen, in dem der Deploy-Daemon die ExApps startet (`docker network ls`, bei HaRP meist `<projekt>_default`).
- Der Proxy darf nur in diesem Netz hängen. Keinen Port veröffentlichen, auch nicht auf `127.0.0.1`.
- Image per Digest gepinnt; ein Update ist eine bewusste Entscheidung.

## 3. Gameworld konfigurieren

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `GAMEWORLD_DOCKER_URL` | `tcp://gameworld-docker-proxy:2375` | Adresse des Docker-Proxys |
| `GAMEWORLD_PORT_RANGE` | `30000-30019` | UDP-Portbereich für Welten, höchstens 200 Ports |

## 4. UDP-Ports

- Welten sind nur für das Heimnetz gedacht.
- Keine Portfreigabe im Router einrichten, UPnP am Router nicht nutzen.
- Fernzugriff kommt später über VPN.
- Die Firewall des Servers muss den UDP-Bereich im LAN erlauben.

## 5. Restrisiko ehrlich benannt

- Mit `CONTAINERS=1` und `POST=1` kann jeder, der den Proxy erreicht, beliebige Container erzeugen, auch privilegierte. Das ist root-gleich auf dem Server.
- Deshalb: den Proxy nie auf einem Host-Port veröffentlichen, nur im Deploy-Netz betreiben.
- Gameworld selbst erzeugt ausschließlich fest vorgegebene, gehärtete Welt-Container: Benutzer 30000 (nicht root), alle Capabilities entzogen, schreibgeschütztes Dateisystem, 512 MB RAM (Abenteuer-Welt 1 GB), 1 CPU, 128 Prozesse.
- Gameworld verändert nur Container mit dem eigenen Instanz-Label.
- Andere ExApps im selben Deploy-Netz könnten den Proxy ebenfalls erreichen. Eine weitere Härtung ist für das Store-Release geplant.

## 6. Setup-Check

Die Gameworld-Seite prüft beim Öffnen den Docker-Proxy. Die Prüfung verändert nichts: schreibende Anfragen gehen nur an die nicht existierende Ressource `gameworld-probe-nonexistent`. Solange ein Fehler offen ist, bleibt "Welt erstellen" gesperrt.

| Meldung | Abhilfe |
|---------|---------|
| Gameworld erreicht den Docker-Proxy nicht | Dienst `gameworld-docker-proxy` starten, `GAMEWORLD_DOCKER_URL` und Netz prüfen |
| Docker-Engine zu alt, benötigt API 1.44 oder neuer | Docker auf dem Server aktualisieren |
| Kein Zugriff auf Container | `CONTAINERS=1` setzen |
| Keine schreibenden Anfragen erlaubt | `POST=1` setzen |
| Kein Zugriff auf Images | `IMAGES=1` setzen |
| Kein Zugriff auf Volumes | `VOLUMES=1` setzen |
| Nicht geprüft: Erst POST=1 setzen | `POST=1` setzen, dann erneut prüfen |
| Proxy zu weit offen: Befehle in Containern erlaubt (Warnung) | `EXEC=0` setzen |
| Proxy gibt Systeminformationen preis (Warnung) | `INFO=0` setzen |
| Unerwartete Antwort auf Pfad mit HTTP-Code | Proxy-Image und Flags mit Abschnitt 2 vergleichen |
| Gameworld antwortet nicht | ExApp in den Nextcloud-Einstellungen (AppAPI) prüfen |

Nach jeder Änderung am Proxy den Dienst neu starten und auf der Gameworld-Seite "Erneut prüfen" wählen.

## 7. Speicherbedarf und Neustarts

- Jede Welt hat ein festes Speicherlimit ohne Swap: Kreativ-Welt ("Bauen (kreativ)") 512 MB, Abenteuer-Welt ("Abenteuer (sanft)") 1 GB. Einstellen lässt sich das nicht.
- Für den Heimserver grob rechnen: Summe der Limits aller gleichzeitig laufenden Welten plus Nextcloud muss in den Arbeitsspeicher passen.
- Welten haben keine eigene Neustart-Policy in Docker.
- Nach einem Server-Neustart startet Gameworld beim eigenen Start alle Welten, die vorher liefen. Gestoppte Welten bleiben gestoppt.
- Eine Welt, die wegen Speichermangel beendet wurde, startet nicht automatisch. Das Dashboard zeigt den Grund, Starten geht per Klick.
- Nach einem Update von Gameworld bleiben alle Welten samt Daten erhalten; Gameworld übernimmt die vorhandenen Container wieder.

## 8. Zugang, Rollen und Spielpasswörter

### Rollen

- Verwalter sind die Mitglieder der Nextcloud-Gruppe `admin`. Nur sie erstellen, starten, stoppen und löschen Welten und laden Spieler ein.
- Spieler sind alle eingeladenen Nextcloud-Konten, direkt oder über eine eingeladene Nextcloud-Gruppe. Sie sehen nur ihre eigenen Welten mit der Verbindungsinfo, keine Steuerknöpfe und keine anderen Spieler.
- Gameworld hat keine eigene Benutzerverwaltung. Rollen kommen bei jeder Anfrage aus Nextcloud (bis zu 30 Sekunden zwischengespeichert). Wer aus der Gruppe `admin` entfernt wird, verliert die Verwaltung spätestens nach 30 Sekunden.

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
- Randfall Neuinstallation: Wird Gameworld komplett entfernt (mit Daten) und neu installiert, entsteht ein neues Geheimnis. Dann ändern sich alle Spielpasswörter einmalig. Gameworld schreibt die neuen Zugänge automatisch in alle Welten; die Kinder brauchen danach das neue Passwort aus ihrer Gameworld-Seite.

### Adresse für Spieler

- In den Einstellungen des Dashboards steht die "Adresse für Spieler": Rechnername oder IP-Adresse des Servers im Heimnetz, ohne `http://` und ohne Port. Die Kinder sehen diese Adresse in ihrer Verbindungsinfo.
- Bleibt das Feld leer, zeigt Gameworld den Rechnernamen aus der Adresszeile des Browsers. Das passt nicht, wenn Nextcloud über `localhost` oder über eine Internetadresse aufgerufen wird; dann die Heimnetz-Adresse eintragen.
- Der Port jeder Welt ist ein UDP-Port aus dem Bereich in Abschnitt 4. Er muss im Heimnetz erreichbar sein.
- Kein Zugang aus dem Internet ohne VPN: keine Portfreigabe im Router, siehe Abschnitt 4.

## 9. Spielzeit

### Grundregeln

- Spielzeit ist Opt-in: Ohne Regel gibt es keine Begrenzung. Jedes Kind startet mit "Keine Begrenzung".
- Ein Kind hat ein einziges Tageskontingent über alle Welten. Wer eine Stunde am Tag darf, kann sie auf mehrere Welten verteilen, aber nicht in jeder Welt eine Stunde spielen. Gameworld gleicht den Verbrauch alle 15 Sekunden zwischen den Welten ab.
- Eingestellt wird im Abschnitt "Spielzeit" unter der Weltenliste, mit "Bearbeiten" je Kind. Vier Voreinstellungen helfen beim Start: "Keine Begrenzung", "Nur am Wochenende" (Sa und So je 2 Stunden, 9 bis 19 Uhr), "Jeden Tag 1 Stunde" (bis 19 Uhr) und "Schultage kurz, Wochenende länger" (Mo bis Fr 1 Stunde, 15 bis 19 Uhr; Sa und So 2 Stunden, 9 bis 19 Uhr). Danach lässt sich jeder Tag in seiner Kachel ändern: Spielen erlaubt oder nicht, Tageslimit, Uhrzeit von und bis oder ganzer Tag.
- Der Verbrauch zählt online verbrachte Zeit. Auch wer nur verbunden ist und nichts tut (AFK), verbraucht Spielzeit.
- Verwalter (Gruppe `admin`) haben nie Zeitregeln und kommen immer hinein. Wird jemand aus `admin` entfernt, bleibt er im Spiel frei, bis ein Verwalter das Dashboard öffnet; danach gelten seine Regeln nach höchstens etwa 60 Sekunden.

### Ferien

- Der Abschnitt "Ferien" ist eine Liste von Zeiträumen für den ganzen Haushalt (von, bis, Bezeichnung optional). Ein laufender Zeitraum ist mit "läuft gerade" markiert.
- Im Spielzeit-Dialog hat jedes Kind einen eigenen Block "In den Ferien" (Vorschlag: jeden Tag 2 Stunden, 9 bis 20 Uhr). Ohne eigenen Ferienplan gilt in den Ferien die normale Woche.

### Zeitzone

- Alle Uhrzeiten gelten in der Zeitzone des Haushalts, Vorgabe `Europe/Berlin`. Sie steht in den Einstellungen unter der Adresse für Spieler; der Knopf "Zeitzone dieses Browsers übernehmen" setzt die Zone des Browsers. Sommer- und Winterzeit rechnet Gameworld selbst.

### Zeitfenster pro Welt

- Mit "Zeitfenster" in der Welt-Zeile ist eine Welt nur zu bestimmten Zeiten offen, etwa für eine Schul- oder Vereinswelt ("Offen Mi 10 bis 12 Uhr").
- Die Welt läuft außerhalb des Fensters weiter. Kinder kommen nicht hinein und werden am Fensterende getrennt; Verwalter kommen immer hinein.

### Im Spiel

- Kinder sehen auf ihrer Gameworld-Seite den Block "Deine Spielzeit heute" mit der Restzeit oder der nächsten Spielzeit.
- Im Spiel warnt der Chat bei 10, 5 und 1 Minute Rest. Am Ende trennt die Welt das Kind mit einem Text wie "Deine Spielzeit für heute ist aufgebraucht. Nächste Spielzeit: Sa 09:00". Ein Beitritt außerhalb der erlaubten Zeit wird mit einem passenden Text abgelehnt.
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
