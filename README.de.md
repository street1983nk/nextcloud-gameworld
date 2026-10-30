[English](README.md) | **Deutsch** | [Français](README.fr.md)

![Gameworld: private Spielwelten für Familien, auf der eigenen Nextcloud](docs/images/gameworld-banner-v1.jpg)

# Gameworld für Nextcloud

[![Image build](https://img.shields.io/github/actions/workflow/status/street1983nk/nextcloud-gameworld/image.yml?label=image%20build)](https://github.com/street1983nk/nextcloud-gameworld/actions/workflows/image.yml)
[![Release](https://img.shields.io/github/v/release/street1983nk/nextcloud-gameworld)](https://github.com/street1983nk/nextcloud-gameworld/releases)
[![Licence](https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue)](LICENSE)
[![Nextcloud](https://img.shields.io/badge/Nextcloud-33--35-0082c9)](https://apps.nextcloud.com/apps/gameworld)

Private Luanti-Spielwelten für Familien und Schulen, auf dem eigenen Nextcloud-Server als
External App (ExApp). Eltern erstellen eine Welt per Klick, laden Kinder und Freunde über ihre
Nextcloud-Konten ein und legen Weltsicherungen in Nextcloud Files ab.

## Was Gameworld kann

- Private Luanti-Welten (kreativ oder sanftes Abenteuer), jede in einem eigenen Container mit
  festen Grenzen für Arbeitsspeicher, CPU und Prozesse
- Nur eingeladene Nextcloud-Konten oder Gruppen kommen hinein; jeder andere Spielername wird
  vor der Anmeldung abgelehnt
- Ein Spielpasswort je Konto, nie gespeichert; Welten bekommen nur einen SRP-Verifier
- Spielzeit je Kind über alle Welten, Ferien, Zeitfenster je Welt, Pause für alle Kinder vom
  Handy aus
- Erwachsen-Schalter: markierte Erwachsene spielen ohne Pause und Spielzeitregeln, nie mit
  Verwaltungs- oder Luanti-Adminrechten
- Verwalter-Gruppen für Schulen und Vereine, eingestellt von Nextcloud-Admins;
  Gruppen-Verwalter laden nur Konten aus den eigenen Gruppen ein
- Sicherungen und Wiederherstellen über Nextcloud Files, geprüft vor jedem Wiederherstellen
- Ein Talk-Raum je Welt mit Gameworld-Bot (optional, wenn Talk installiert ist)
- Welten nur im Heimnetz, nie in einer Serverliste
- Keine Telemetrie, kein Nach-Hause-Telefonieren
- Oberfläche: Deutsch, Englisch, Französisch (folgt der Nextcloud-Kontosprache); Spieltexte je Welt

## Was Gameworld braucht und warum

Gameworld braucht Privilegien, die eine normale Nextcloud-App nicht braucht:

- Docker-Zugriff über einen gescopten `tecnativa/docker-socket-proxy` (Container, Images,
  Volumes, ändernde Anfragen; alles andere zu). Wer diesen Proxy erreicht, hat root-gleiche
  Rechte auf dem Host. Er darf nur im Docker-Netz von Gameworld hängen, nie an einem Host-Port.
- Ein UDP-Port je Welt (Standard 30000 bis 30019), nur im Heimnetz.

Einzelheiten und Restrisiko: [docs/privacy.de.md](docs/privacy.de.md).

## Architektur

```mermaid
flowchart LR
    client["Browser and Luanti client"]
    subgraph nc["Nextcloud"]
        appapi["AppAPI"]
        files["Nextcloud Files: backups"]
    end
    harp["HaRP deploy daemon"]
    subgraph net["Docker network of Gameworld"]
        exapp["Gameworld ExApp, uid 10001"]
        proxy["docker-socket-proxy, scoped"]
    end
    engine[("Docker engine")]
    world1["World container 1: Luanti"]
    world2["World container 2: Luanti"]
    client -->|"HTTPS"| nc
    appapi --> harp
    harp -->|"/exapps/"| exapp
    exapp -->|"Docker API"| proxy
    proxy --> engine
    engine --> world1
    engine --> world2
    client -->|"UDP, home network"| world1
    exapp -->|"WebDAV"| files
```

## Screenshots

![Weltliste](docs/screenshots/worlds-v1.png)
![Einladen](docs/screenshots/invite-v1.png)
![Kinder-Ansicht](docs/screenshots/kids-view-v1.png)
![Sicherungen](docs/screenshots/backups-v1.png)
![Spielzeit](docs/screenshots/playtime-v1.png)
![Handy-Ansicht](docs/screenshots/mobile-v1.png)

## Voraussetzungen

- Nextcloud 33 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon
- Docker-Engine-API 1.44 oder neuer
- Ein gescopter `tecnativa/docker-socket-proxy` im selben Docker-Netz wie Gameworld

## Installation

1. HaRP und den Docker-Proxy einrichten, siehe [docs/install.de.md](docs/install.de.md)
   (Standard-Compose und Nextcloud All-in-One).
2. Gameworld aus dem Nextcloud App Store installieren (Kategorie Spiele).
3. Gameworld öffnen; der Setup-Check prüft den Proxy vor der ersten Welt. Fehlt der Proxy,
   zeigt er je einen fertigen `docker run`-Befehl für All-in-One und für das eigene Compose
   zum Kopieren.

Deaktivieren und Aktualisieren stoppt und entfernt die Welt-Container; Volumes und Sicherungen
bleiben, die Welten kommen von selbst wieder. Das Deinstallieren lässt Welt-Volumes und
Sicherungen absichtlich stehen; `scripts/gameworld-orphans.sh` listet Reste auf und entfernt
sie, siehe [docs/install.de.md#cleanup](docs/install.de.md#cleanup).

## Dokumentation

- [Installationsanleitung](docs/install.de.md) ([English](docs/install.md))
- [Datenschutz, Privilegien und Datenfluss](docs/privacy.de.md) ([English](docs/privacy.md))
- [Entwicklungsumgebung](docs/dev-setup.md)
- [Mitwirken](CONTRIBUTING.md) und [Sicherheitsrichtlinie](SECURITY.md) (Englisch)

## Lizenz

[AGPL-3.0-or-later](LICENSE)
