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
- Gameworld selbst erzeugt ausschließlich fest vorgegebene, gehärtete Welt-Container: Benutzer 30000 (nicht root), alle Capabilities entzogen, schreibgeschütztes Dateisystem, 512 MB RAM, 1 CPU, 128 Prozesse.
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
