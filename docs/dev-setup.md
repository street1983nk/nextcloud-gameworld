# Entwicklungsumgebung

Lokale Umgebung für Gameworld: eine eigene Nextcloud 34 im Compose-Projekt `gameworld-dev`, ein gescopter Docker-Proxy und die ExApp als Host-Prozess (AppAPI-Daemon `manual-install`).

## Voraussetzungen

- Docker Desktop (unter Windows mit WSL2-Engine)
- [uv](https://docs.astral.sh/uv/) für Python 3.13
- Node 22 oder neuer mit npm für das Frontend (@nextcloud/files 4.1.0 verlangt laut Engine-Angabe Node 24; der Build läuft mit 22 und warnt nur)
- Git Bash oder eine andere POSIX-Shell für die Skripte

## Starten

1. Stack hochfahren:

   ```sh
   docker compose -f scripts/dev/compose.yaml up -d
   ```

   Nextcloud läuft danach auf <http://localhost:8091> (anderer Port per `GAMEWORLD_NC_PORT`).

2. ExApp bauen, starten und registrieren:

   ```sh
   sh scripts/dev/register-exapp.sh
   ```

   Das Skript baut bei Bedarf das Frontend nach `js/gameworld-main.js`, startet das Backend auf Port 10040 mit einem neuen Secret pro Lauf (`.dev/exapp.secret`, gitignored), registriert den Daemon `manual_install` und die ExApp und aktiviert sie. Den Einrichtungsassistenten (firstrunwizard) schaltet es in der Dev-Nextcloud ab, weil er Browser-Prüfungen blockiert. Ein Backend, das zu den Quellen passt, läuft weiter; ein veraltetes wird neu gestartet. Das Log steht in `.dev/exapp.log`.

3. Im Browser öffnen: <http://localhost:8091/index.php/apps/app_api/embedded/gameworld/gameworld>

   Anmeldung nur für die Entwicklung: `admin` / `gameworld-dev-admin`. Der Eintrag Gameworld erscheint im Top-Menü nur für Admins.

4. Durchstich prüfen (Seite, Welt erstellen, gehärteter Container, Aufräumen):

   ```sh
   sh scripts/dev/smoke.sh
   ```

## Spieldateien

`minetest_game` liegt im Git, VoxeLibre (`vendor/games/mineclone2-39534.zip`, rund 84 MB) nicht. `register-exapp.sh` holt es bei jedem Lauf hash-geprüft über `scripts/fetch-games.sh`; ist die Datei schon da und stimmt die Prüfsumme, passiert nichts. Manuell:

```sh
sh scripts/fetch-games.sh
```

Ohne Netz: `GAMEWORLD_GAME_SOURCE_DIR` auf ein Verzeichnis mit einer gleichnamigen Kopie zeigen lassen, die Prüfsumme aus `vendor/games/SHA256SUMS` wird auch dann geprüft. Gameworld selbst lädt zur Laufzeit nie etwas nach.

## Phasenabnahme

Belegt die fünf Erfolgskriterien von Phase 1 gegen den laufenden Stack, unabhängig von den Python-Testhelfern (docker-CLI, curl, tar, grep, jq):

```sh
sh scripts/dev/acceptance-phase1.sh
```

Das Skript legt bei Bedarf den Nicht-Admin `gw-kind` / `gw-kind-dev-pass-1` an (nur Dev) und lässt ihn für die Browser-Abnahme stehen. Für K5 stoppt es kurz den Dienst `gameworld-docker-proxy` und startet ihn in jedem Fall wieder. Die Abnahme-Welten entfernt es am Ende. Exit 0 nur, wenn alle Prüfungen bestanden sind; die letzte Zeile nennt "N von N Prüfungen bestanden". Voraussetzung ist `jq` im Pfad.

## Phasenabnahme Phase 2

Belegt die vier Erfolgskriterien von Phase 2 (Presets, Lebenszyklus und Status aus Docker, Spieler und RAM, Update und Reboot) gegen den laufenden Stack, ebenfalls nur mit docker-CLI, curl, tar, grep und jq:

```sh
sh scripts/dev/acceptance-phase2.sh
```

Das Skript stoppt für K2 kurz den Dienst `gameworld-docker-proxy` und beendet für K4 zweimal den ExApp-Prozess (Update- und Reboot-Simulation über `register-exapp.sh`, ohne `--rm-data`); ein trap stellt beides in jedem Fall wieder her. Es fasst nur Container mit Gameworld-Labels an und vergleicht Zustand und Startzeit aller anderen Container vor und nach K4. Höchstens eine VoxeLibre-Welt existiert gleichzeitig. Am Ende ruft es `acceptance-phase1.sh` als Regression. Laufzeit etwa 4 bis 5 Minuten, Exit 0 nur bei "N von N Prüfungen bestanden".

## Phasenabnahme Phase 3

Belegt die fünf Erfolgskriterien von Phase 3 (Einladen und Provisionieren, Join nur für Eingeladene, Verbindungsinfo für Kinder, Kind-Ansicht und Sperre, Rollen aus Nextcloud ohne gespeicherte Passwörter) gegen den laufenden Stack mit echten Nextcloud-Konten:

```sh
sh scripts/dev/acceptance-phase3.sh
```

Werkzeuge: docker-CLI, curl, jq, tar, grep, sha256sum und `uv`. Einziges Python-Werkzeug ist der UDP-Prober `tests/e2e/luanti_probe.py`, aufgerufen über seine CLI (`uv run python -m tests.e2e.luanti_probe HOST PORT NAME [PASSWORT]`, Ausgabe JSON). Die Spalten der Tabelle `players` liest das Skript mit `sqlite3`, falls installiert, sonst lesend über die Python-Standardbibliothek.

Das Skript legt kurzzeitig die Gruppe `gw-familie` und das Wegwerfkonto `gw-abnahme2` an, nimmt `gw-kind` für K5 kurz in die Gruppe `admin` auf (zweimal 35 s Wartezeit für den Rollen-Cache), setzt die Spieler-Adresse auf `192.168.178.20` und startet die ExApp einmal neu. Ein trap räumt alles in jedem Fall auf: Welt, Gruppe, Konto, Spieler-Adresse leer, `gw-kind` nicht in `admin`. Spielpasswörter erscheinen nie in der Ausgabe. Am Ende ruft es `acceptance-phase1.sh` und `acceptance-phase2.sh` als Regression. Laufzeit etwa 10 Minuten, Exit 0 nur bei "N von N Prüfungen bestanden". Mit `GAMEWORLD_SKIP_REGRESSION=1` entfällt die Regression für schnelle Iterationen; der Lauf endet dann bewusst mit Exit 1.

## Abbauen

```sh
docker compose -f scripts/dev/compose.yaml down
```

Mit `down -v` verschwinden auch die Daten der Dev-Nextcloud. Welt-Container und -Volumes tragen das Label `gameworld.managed=true` und lassen sich darüber finden.

## Sicherheitshinweis

Der Docker-Proxy ist nur auf `127.0.0.1:23750` publiziert. Wer diesen Port erreicht, kann Container erzeugen und ist damit faktisch root auf dem Host. Die Bindung an Loopback darf nicht gelockert werden. Das Backend bindet im Dev auf `0.0.0.0:10040`, damit der Nextcloud-Container es über `host.docker.internal` erreicht; geschützt ist es durch das Secret. Mit `GAMEWORLD_APP_HOST` lässt sich die Bindung einengen.

Auf demselben Rechner laufende Findling-Stacks (Port 8090) bleiben unberührt: eigener Projektname, eigene Ports, eigene Labels.
