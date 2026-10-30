<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Datenschutz, Privilegien und Datenfluss

English version: [privacy.md](privacy.md)

**Umfang:** welche zusätzlichen Privilegien Gameworld auf dem Server braucht und warum,
welche personenbezogenen Daten Gameworld speichert, wo, was Gameworld nie tut und was
beim Deaktivieren, Aktualisieren und Deinstallieren passiert. Das ist eine technische
Beschreibung für Admins und Eltern, keine rechtliche Datenschutzerklärung. Verantwortlich
bleibt, wer die Nextcloud betreibt.

## Kurz gesagt

Gameworld betreibt private Luanti-Spielwelten auf dem eigenen Nextcloud-Server. Es sendet
keine Telemetrie, ruft keine Dritten auf und trägt keine Welt in eine Serverliste ein. Nur
eingeladene Nextcloud-Konten kommen in eine Welt.

Dafür braucht Gameworld zwei Dinge, die eine normale Nextcloud-App nicht braucht: Zugriff
auf Docker über einen gescopten Proxy und einen UDP-Port je Welt. Beides steht unten samt
Restrisiko. Bitte vor der Installation
[Was diese App darf und warum](#was-diese-app-darf-und-warum) lesen.

## Was diese App darf und warum

### 1. Docker-Zugriff über einen gescopten docker-socket-proxy

Jede Welt ist ein eigener Container. Gameworld erstellt, startet, stoppt und entfernt
diese Container über `tecnativa/docker-socket-proxy` (v0.5.0, per Digest gepinnt in
[install.de.md](install.de.md)). Gameworld spricht nie direkt mit dem Docker-Socket.

Der Proxy erlaubt genau diese Teile der Docker-API:

| Flag | Wert | Wofür Gameworld es braucht |
|------|------|----------------------------|
| `CONTAINERS` | 1 | Welt-Container erstellen, starten, stoppen, entfernen, Zustand und Logs lesen |
| `IMAGES` | 1 | das gepinnte Luanti-Image `ghcr.io/luanti-org/luanti:5.17.0` holen |
| `POST` | 1 | jede ändernde Anfrage (erstellen, starten, stoppen, entfernen, Dateien in eine Welt kopieren) |
| `VOLUMES` | 1 | das Volume einer Welt anlegen und löschen |
| alles andere | 0 | `EXEC`, `INFO`, `NETWORKS`, `BUILD`, `SYSTEM`, `SECRETS`, `SWARM`, `NODES`, `SERVICES`, `TASKS`, `PLUGINS`, `CONFIGS`, `DISTRIBUTION`, `AUTH` bleiben zu |

Ehrlich gesagt: Mit `CONTAINERS=1` und `POST=1` kann jeder, der den Proxy erreicht, einen
Container mit beliebigen Volumes anlegen, auch mit dem Dateisystem des Hosts. Das ist
praktisch root auf dem Host. Der Proxy kann nicht einschränken, welche Container
entstehen.

So bleibt das Risiko eingegrenzt:

- Der Proxy hängt nur im Docker-Netz von Gameworld, nie mit Host-Port, auch nicht auf
  `127.0.0.1`.
- Der Setup-Check von Gameworld warnt, wenn `GAMEWORLD_DOCKER_URL` auf einen rohen
  Docker-Socket oder auf eine Adresse außerhalb privater Netze zeigt.
- Gameworld selbst erzeugt nur fest vorgegebene, gehärtete Welt-Container (siehe Punkt 4)
  und fasst nur Container mit dem eigenen Instanz-Label an.

Das Restrisiko: Jeder Container im selben Docker-Netz erreicht den Proxy. Bei Nextcloud
All-in-One hängt der Proxy im Netz `nextcloud-aio`, damit erreicht ihn jeder
AIO-Container, auch Nextcloud selbst. Andere ExApps im selben Deploy-Netz erreichen ihn
ebenfalls. Wer das für den eigenen Server nicht hinnehmen will, installiert Gameworld
nicht.

### 2. Ein UDP-Port je Welt, nur im Heimnetz

- Jede Welt bekommt einen UDP-Port aus `GAMEWORLD_PORT_RANGE` (Standard `30000-30019`).
- Die Welten sind für das Heimnetz gedacht. Keine Portfreigabe im Router, kein UPnP.
  Fernzugriff ist über VPN geplant, nicht über offene Ports.
- Ein Port allein lässt niemanden hinein: Der Welt-Mod `gameworld_access` lehnt jeden
  Spielernamen ab, der nicht eingeladen ist, noch vor der Anmeldung. Eingeladene brauchen
  ihr Spielpasswort.
- Keine Welt steht jemals in einer Serverliste (`server_announce = false` in jeder Welt).

### 3. Der App-Container läuft ohne Rechte

Der Gameworld-Container läuft als uid 10001, ohne root-Schritt beim Start. Sein eigener
Code gehört root und lässt sich von der laufenden App nicht ändern.

### 4. Welt-Container sind gehärtet

- Jede Welt läuft als Benutzer 30000, nicht root, ohne Capabilities, mit
  `no-new-privileges`, schreibgeschütztem Root-Dateisystem, 512 MB Arbeitsspeicher
  (Abenteuer-Welt 1 GB) ohne Swap, 1 CPU und höchstens 128 Prozessen.
- Neue und wiederhergestellte Welten bekommen einen root-eigenen Weltordner mit
  Sticky-Bit und einen root-eigenen Ordner `worldmods`. Der Luanti-Prozess kann
  Zugangsdatei, Regeldatei und Gameworld-Mods weder ändern noch entfernen.
- Niemand bekommt Luanti-Adminrechte. Kinder bekommen im Spiel nie Rechte.

## Was die App speichert

Gameworld führt eine SQLite-Datenbank im eigenen Volume `nc_app_gameworld_data`. Darin:

| Daten | Form und Zweck |
|-------|----------------|
| Welten | Name, Port, Container- und Volume-Name, Spielart, Sprache der Spieltexte, Soll-Zustand, letzter Fehler |
| Einladungen | Welt, eingeladenes Konto oder Gruppe, wer eingeladen hat, wann |
| Spielernamen | ein Spielername je Nextcloud-Konto plus Zähler für "Neues Passwort" |
| Spielpasswörter | nie gespeichert. Sie werden bei Bedarf aus einem Geheimnis in der ExApp-Konfiguration von Nextcloud abgeleitet. Jede Welt bekommt nur einen SRP-Verifier, nicht das Passwort |
| Spielzeitregeln | Wochenplan, Ferienplan, Zeitfenster je Welt, Ferien des Haushalts |
| Tagesverbrauch | Tagessummen in Sekunden, nur für Kinder mit Regeln, gelöscht nach 7 Tagen. Keine Sitzungszeiten, keine IP-Adressen |
| Beitrittsversuche fremder Namen | Spielername und Uhrzeit, gelöscht nach 7 Tagen |
| Bot-Drossel | Zeitpunkt der letzten Talk-Meldung je Welt und Konto, höchstens 7 Tage |
| Einstellungen Tagesrückblick | Uhrzeit und An/Aus je Verwalter |
| Erwachsen-Markierung | Konto, welcher Verwalter sie gesetzt hat, wann |
| Verwalter-Gruppen | die zusätzlichen Gruppen, die ein Nextcloud-Admin eingetragen hat; die Gruppe `admin` verwaltet immer |
| Verwalter-Verlauf | seit wann ein Konto Gameworld verwaltet (für den neuen Besitzer eines Talk-Raums) |
| Talk-Räume | Welt, Raum-Token, handelndes Besitzerkonto, Nur-lesen-Schalter |
| Sicherungsliste | Datei-ID, Pfad, Größe und SHA-256 jeder Sicherung in Nextcloud Files |
| Einstellungen | Adresse für Spieler, Zeitzone, Basisadresse für Links in Benachrichtigungen |

Im Volume jeder Welt (`gameworld-<instanz>-<welt>`) führt Luanti Karte, Inventare und
eigene Kontodaten. Gameworld legt dort die Zugangsdatei (Spielernamen und SRP-Verifier),
die Regeldatei und ein Zählbuch mit Spielernamen und Sekunden ab.

## Was die App nie tut

- Keine Telemetrie, keine Nutzungsstatistik, kein Nach-Hause-Telefonieren.
- Welten brauchen keinen Internetzugang. Gameworld holt das gepinnte Luanti-Image einmal.
- Keine Welt in einer Serverliste, keine Einstellung, die eine Welt im Internet sichtbar
  macht.
- Keine Rechte für Kinder, weder in Gameworld noch im Spiel.
- Mit dem Erwachsen-Schalter markierte Erwachsene spielen ohne Pause, Zeitfenster und
  Spielzeitgrenzen, bekommen aber nie Verwaltungsrechte oder Luanti-Adminrechte.
- Kein Mitlesen in Talk. Der Gameworld-Bot schreibt nur; der Webhook verwirft jede
  eingehende Nachricht ungelesen.
- Kein Löschen von Sicherungen. Gameworld entfernt nie selbst eine Sicherungsdatei.

## Was die eigene Kontrolle verlässt

- **Sicherungen** sind Dateien in Nextcloud Files des Verwalters, der gesichert hat,
  unter `Gameworld/Sicherungen/<Welt>/`. Von dort folgen sie der eigenen Nextcloud:
  Freigaben, externe Speicher, Serversicherungen.
- **Talk** (falls installiert): Jede Welt bekommt einen eigenen Raum. Nachrichten des Bots
  und der Mitglieder speichert Talk, nicht Gameworld. Mitglieder folgen den Einladungen
  der Welt plus allen Verwaltern.
- **Benachrichtigungen** an Verwalter (fremde Beitrittsversuche, Tagesrückblick,
  gescheiterte Sicherungen) sind normale Nextcloud-Benachrichtigungen. Aufs Handy laufen
  sie über den Push-Proxy der Nextcloud-App.
- **Spieler** verbinden sich mit ihrem Luanti-Client mit der Welt im Heimnetz. Was ein
  Client lokal speichert, liegt außerhalb von Gameworld.

## Löschen und Kontrolle

- **Gelöschte Konten:** Gameworld vergisst ein gelöschtes Nextcloud-Konto (Einladungen,
  Spielername, Regeln, Verbrauch, Erwachsen-Markierung), sobald ein Nextcloud-Admin
  Gameworld geöffnet hat. Verwalter ohne Nextcloud-Adminrechte lösen das nie aus, weil
  Nextcloud ihnen Konten außerhalb ihrer Gruppen nicht zeigt.
- **Welt löschen** entfernt Container, Volume und den Talk-Raum samt Verlauf. Sicherungen
  bleiben in Files.
- **Deaktivieren und Updates:** Bei jedem Deaktivieren, auch direkt vor einem Update oder
  einer Deinstallation, stoppt und entfernt Gameworld alle eigenen Welt-Container.
  Spielende werden kurz getrennt. Volumes und Sicherungen bleiben, die Welten kommen von
  selbst wieder, sobald Gameworld wieder läuft.
- **Deinstallieren:** AppAPI entfernt den Gameworld-Container. Das Daten-Volume
  `nc_app_gameworld_data` wird nur gelöscht, wenn man das Löschen der Daten wählt. Die
  Welt-Volumes und die Sicherungen in Files bleiben immer, absichtlich: Keine Welt geht
  still verloren.
- **Aufräumen:** Nextcloud-Admins sehen Reste früherer Installationen im
  Gameworld-Abschnitt "Reste früherer Installationen" und entfernen sie einzeln. Nach der
  Deinstallation listet `scripts/gameworld-orphans.sh` auf dem Docker-Host die Reste auf
  und entfernt sie auf Wunsch, siehe [install.de.md](install.de.md#cleanup).

## Aufbewahrung

| Daten | Aufbewahrt |
|-------|------------|
| Tagesverbrauch, fremde Beitrittsversuche, Bot-Drossel | 7 Tage |
| Welten, Einladungen, Regeln, Spielernamen | bis ein Verwalter sie löscht oder das Konto vergessen wird |
| Erwachsen-Markierung | bis zum Ausschalten oder bis das Konto vergessen wird |
| Sicherungen | bis ein Verwalter die Datei in Nextcloud Files löscht |
| Welt-Volumes nach der Deinstallation | bis zum Entfernen über die Reste-Liste oder `gameworld-orphans.sh` |
