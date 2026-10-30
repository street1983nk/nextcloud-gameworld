<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Die Store-Texte von Gameworld, in einer Quelle

Diese Datei ist die eine Quelle aller Texte, die Gameworld im Nextcloud App Store zeigt:
`<summary>` und `<description>` je Sprache (Englisch ohne `lang`, Deutsch
`lang="de"`, Französisch `lang="fr"`, D-09) und `<name>` genau einmal ohne `lang`: AppAPI
macht aus mehreren `<name>` ein Array, die App hieß dann "Array" (belegt in Plan 06-12 per
HaRP-Installation aus der info.xml). Der Name ist in allen Sprachen "Gameworld". Die Blöcke unten stehen wortgleich in
`appinfo/info.xml`; `tests/test_info_xml.py` prüft das mechanisch
(`test_store_listing_matches_info_xml`). Wer hier etwas ändert, ändert alle drei Sprachen
und die `info.xml` mit.

Stand: Entwurf zur Owner-Abnahme vor dem Tag v1.0.0 (Plan 06-13).

## Die Regeln, die für jeden Text gelten

| Regel | Woher sie kommt |
|---|---|
| `name` und `summary` höchstens 128 Zeichen | `l10n-string` in der Store-XSD |
| Je Elementart jeder Sprachcode nur einmal, kein Element leer | `uniqueNameL10n` und Verwandte; ein leeres Element scheitert beim Upload |
| Keine Backticks und keine Tabellen in einer Beschreibung, Absätze durch Leerzeilen | Nextcloud rendert nur Überschriften, Absätze, Listen, Links und Hervorhebungen |
| Die Zeichenfolgen "public" und "announce" kommen nirgends in der `info.xml` vor, auch nicht als Teil eines Wortes (englisch, französisch) | `test_no_public_or_announce_setting`: keine Einstellung und kein Text darf nach Sichtbarkeit im Internet klingen (ZUGANG-01) |
| Abschnitt "What this app may do and why" zuerst, nach höchstens einem Einleitungssatz | D-11, Roadmap-Kriterium 4 |
| Oberflächensprachen ehrlich nennen: "Interface: German, English, French", die Oberfläche folgt der Kontosprache, Spieltexte je Welt | F-10, P-11, D-25 |
| Am Ende jeder Beschreibung genau ein Satz auf die Schwester-Apps Findling Search und MCP Connector, im Fakten-Ton, wortgleich hier und in der `info.xml` | D-28 |
| Faktenliste, kein Marketing, keine Gedankenstriche, keine Emojis, echte Umlaute und Akzente | Owner-Regeln |

## Feste Felder

- Kategorien: `games`, `tools`
- Doku: user und admin `https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md`, developer `.../docs/dev-setup.md`
- Screenshots (englischer Satz, Owner-Wahl 30.10.2026; Namen verbindlich, Spiegel holt Bilder nie neu, darum `-v1`):
  1. `docs/screenshots/worlds-v1-en.png` (Weltliste)
  2. `docs/screenshots/invite-v1-en.png` (Einladen)
  3. `docs/screenshots/kids-view-v1-en.png` (Kinder-Ansicht)
  4. `docs/screenshots/backups-v1-en.png` (Sicherungen)
  5. `docs/screenshots/playtime-v1-en.png` (Spielzeit-Dialog)
  6. `docs/screenshots/mobile-v1-en.png` (Handy-Ansicht)
- URL-Schema: `https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/master/docs/screenshots/<name>`

## Englisch (ohne `lang`)

### `<name>`

```text
Gameworld
```

### `<summary>`

```text
Private Luanti worlds for families and schools, running on your own Nextcloud
```

### `<description>`

```markdown
Private Luanti game worlds for families and schools, on your own Nextcloud server.

### What this app may do and why

- Docker access through a scoped docker-socket-proxy: Gameworld creates, starts, stops and removes one container per world. Whoever reaches this proxy controls Docker with root-equivalent rights on the host. The proxy belongs inside the Docker network of Gameworld only, never on a host port; every container in that network can reach it (with All-in-One: every AIO container, Nextcloud included).
- One UDP port per world (default 30000 to 30019), meant for the home network only. No port forwarding in the router, and no world is ever listed on any server list.
- Every world runs in its own container as an unprivileged user, with fixed memory, CPU and process limits and no Luanti admin rights for anyone. Gameworld itself runs as uid 10001.

### What it does

- Worlds with one click: creative building or a gentle adventure
- Invitations through Nextcloud accounts and groups; every player name that is not invited is refused before the login
- One game password per account, never stored; worlds only receive a verifier
- Play time per child across all worlds, holidays, time windows per world and a pause for all children from the phone
- Adult switch: marked adults play without pause and play time rules, never with management rights
- Manager groups for schools and clubs, set by Nextcloud admins
- Backups in Nextcloud Files, checked before every restore
- One Talk room per world with a Gameworld bot, if Talk is installed
- No telemetry

### Before you install

- Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon
- The scoped docker-socket-proxy in the same Docker network as Gameworld, set up by the admin (guide below; if it is missing, the setup check shows a ready-to-copy command)
- Interface: German, English, French (follows the Nextcloud account language); in-game texts per world

### Uninstalling and updates

- Disabling and every update stop and remove the world containers. Players are disconnected for a moment, and the worlds come back on their own.
- Uninstalling leaves the world volumes and the backups in Files in place on purpose. Nextcloud admins remove leftovers in the app; after the uninstall, the script gameworld-orphans.sh on the Docker host lists and removes them.

Privacy and privileges: [docs/privacy.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/privacy.md)

Installation guide: [docs/install.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md)

From the same developer: Findling Search (full text search in the Nextcloud search bar) and MCP Connector (connects MCP assistants to Nextcloud).
```

## Deutsch (`lang="de"`)

### `<summary lang="de">`

```text
Private Luanti-Welten für Familien und Schulen, auf der eigenen Nextcloud
```

### `<description lang="de">`

```markdown
Private Luanti-Spielwelten für Familien und Schulen, auf dem eigenen Nextcloud-Server.

### Was diese App darf und warum

- Docker-Zugriff über einen gescopten docker-socket-proxy: Gameworld erstellt, startet, stoppt und entfernt einen Container je Welt. Wer diesen Proxy erreicht, steuert Docker mit root-gleichen Rechten auf dem Host. Der Proxy gehört nur ins Docker-Netz von Gameworld, nie an einen Host-Port; jeder Container in diesem Netz erreicht ihn (bei All-in-One: jeder AIO-Container, auch Nextcloud).
- Ein UDP-Port je Welt (Standard 30000 bis 30019), nur für das Heimnetz gedacht. Keine Portfreigabe im Router, und keine Welt steht jemals in einer Serverliste.
- Jede Welt läuft in einem eigenen Container als Benutzer ohne Rechte, mit festen Grenzen für Arbeitsspeicher, CPU und Prozesse und ohne Luanti-Adminrechte für irgendwen. Gameworld selbst läuft als uid 10001.

### Was Gameworld kann

- Welten per Klick: kreatives Bauen oder ein sanftes Abenteuer
- Einladen über Nextcloud-Konten und Gruppen; jeder nicht eingeladene Spielername wird vor der Anmeldung abgelehnt
- Ein Spielpasswort je Konto, nie gespeichert; Welten bekommen nur einen Verifier
- Spielzeit je Kind über alle Welten, Ferien, Zeitfenster je Welt und eine Pause für alle Kinder vom Handy aus
- Erwachsen-Schalter: markierte Erwachsene spielen ohne Pause und Spielzeitregeln, nie mit Verwaltungsrechten
- Verwalter-Gruppen für Schulen und Vereine, eingestellt von Nextcloud-Admins
- Sicherungen in Nextcloud Files, geprüft vor jedem Wiederherstellen
- Ein Talk-Raum je Welt mit Gameworld-Bot, wenn Talk installiert ist
- Keine Telemetrie

### Vor der Installation

- Nextcloud 33 bis 35 mit AppAPI und einem HaRP-Deploy-Daemon
- Der gescopte docker-socket-proxy im selben Docker-Netz wie Gameworld, eingerichtet vom Admin (Anleitung unten; fehlt er, zeigt der Setup-Check einen fertigen Befehl zum Kopieren)
- Oberfläche: Deutsch, Englisch, Französisch (folgt der Nextcloud-Kontosprache); Spieltexte je Welt

### Deinstallieren und Updates

- Deaktivieren und jedes Update stoppen und entfernen die Welt-Container. Spielende werden kurz getrennt, die Welten kommen von selbst wieder.
- Das Deinstallieren lässt die Welt-Volumes und die Sicherungen in Files absichtlich stehen. Nextcloud-Admins entfernen Reste in der App; nach der Deinstallation listet das Skript gameworld-orphans.sh auf dem Docker-Host sie auf und entfernt sie.

Datenschutz und Privilegien: [docs/privacy.de.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/privacy.de.md)

Installationsanleitung: [docs/install.de.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.de.md)

Vom selben Entwickler: Findling Search (Volltextsuche über die Nextcloud-Suchleiste) und MCP Connector (verbindet MCP-Assistenten mit Nextcloud).
```

## Französisch (`lang="fr"`)

### `<summary lang="fr">`

```text
Mondes Luanti privés pour familles et écoles, sur votre propre Nextcloud
```

### `<description lang="fr">`

```markdown
Des mondes de jeu Luanti privés pour les familles et les écoles, sur votre propre serveur Nextcloud.

### Ce que cette application peut faire et pourquoi

- Accès à Docker via un docker-socket-proxy restreint : Gameworld crée, démarre, arrête et supprime un conteneur par monde. Qui atteint ce proxy contrôle Docker avec des droits équivalents à root sur l'hôte. Le proxy doit rester dans le réseau Docker de Gameworld, jamais sur un port de l'hôte ; tout conteneur de ce réseau peut l'atteindre (avec All-in-One : tout conteneur AIO, Nextcloud compris).
- Un port UDP par monde (par défaut 30000 à 30019), prévu pour le réseau domestique uniquement. Aucune redirection de port dans le routeur, et aucun monde n'est jamais listé sur une liste de serveurs.
- Chaque monde tourne dans son propre conteneur avec un utilisateur sans privilèges, des limites fixes de mémoire, de CPU et de processus, et sans droits d'administrateur Luanti pour personne. Gameworld lui-même tourne avec l'uid 10001.

### Ce que fait Gameworld

- Des mondes en un clic : construction créative ou aventure douce
- Invitations via les comptes et groupes Nextcloud ; tout nom de joueur non invité est refusé avant la connexion
- Un mot de passe de jeu par compte, jamais stocké ; les mondes ne reçoivent qu'un vérificateur
- Temps de jeu par enfant sur tous les mondes, vacances, plages horaires par monde et une pause pour tous les enfants depuis le téléphone
- Interrupteur adulte : les adultes marqués jouent sans pause ni règles de temps de jeu, jamais avec des droits de gestion
- Groupes de gestionnaires pour écoles et associations, définis par les administrateurs Nextcloud
- Sauvegardes dans Nextcloud Files, vérifiées avant chaque restauration
- Un salon Talk par monde avec un bot Gameworld, si Talk est installé
- Pas de télémétrie

### Avant l'installation

- Nextcloud 33 à 35 avec AppAPI et un démon de déploiement HaRP
- Le docker-socket-proxy restreint dans le même réseau Docker que Gameworld, mis en place par l'administrateur (guide ci-dessous, en anglais ; s'il manque, la vérification de configuration affiche une commande prête à copier)
- Interface : allemand, anglais, français (selon la langue du compte Nextcloud) ; textes du jeu par monde

### Désinstallation et mises à jour

- La désactivation et chaque mise à jour arrêtent et suppriment les conteneurs des mondes. Les joueurs sont déconnectés un instant, et les mondes reviennent d'eux-mêmes.
- La désinstallation laisse volontairement en place les volumes des mondes et les sauvegardes dans Files. Les administrateurs Nextcloud suppriment les restes dans l'application ; après la désinstallation, le script gameworld-orphans.sh sur l'hôte Docker les liste et les supprime.

Confidentialité et privilèges : [docs/privacy.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/privacy.md)

Guide d'installation : [docs/install.md](https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md)

Du même développeur : Findling Search (recherche plein texte dans la barre de recherche de Nextcloud) et MCP Connector (connecte les assistants MCP à Nextcloud).
```

## Was bewusst nicht drinsteht

Dieser Abschnitt ist die Begründung und gehört nicht in die `info.xml`.

- **Kein Versprechen zu Spielen über das Internet.** Welten sind für das Heimnetz gedacht;
  Fernzugriff kommt erst später über VPN. Ein Text, der Spielen mit Freunden anderswo
  verspricht, würde zu Portfreigaben verleiten (P-11).
- **Kein Minecraft.** Gameworld 1.0.0 kann nur Luanti. Minecraft ist ein eigener späterer
  Meilenstein mit EULA-Prüfung und wird nicht angekündigt.
- **Keine weiteren Oberflächensprachen.** Die Oberfläche gibt es auf Deutsch, Englisch und
  Französisch, mehr nicht; andere Kontosprachen sehen die englische Oberfläche. Das Listing
  verspricht keine weitere Sprache.
- **Kein Wort über die Sichtbarkeit des Images.** Dass das ghcr-Paket für jeden abrufbar sein
  muss, ist Release-Mechanik und steht in den Release-Plänen, nicht im Listing.
- **Keine Zahlen, die nicht gemessen sind.** Speichergrenzen und Portbereich stehen so im Code;
  eine Aussage wie "läuft auf jedem Heimserver" fehlt bewusst.
- **Kein Vergleich mit anderen Gameserver-Panels.**

## Abnahme

Abnahme: Owner, 30.10.2026
