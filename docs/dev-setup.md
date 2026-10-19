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

## Phasenabnahme

Belegt die fünf Erfolgskriterien von Phase 1 gegen den laufenden Stack, unabhängig von den Python-Testhelfern (docker-CLI, curl, tar, grep, jq):

```sh
sh scripts/dev/acceptance-phase1.sh
```

Das Skript legt bei Bedarf den Nicht-Admin `gw-kind` / `gw-kind-dev-pass-1` an (nur Dev) und lässt ihn für die Browser-Abnahme stehen. Für K5 stoppt es kurz den Dienst `gameworld-docker-proxy` und startet ihn in jedem Fall wieder. Die Abnahme-Welten entfernt es am Ende. Exit 0 nur, wenn alle Prüfungen bestanden sind; die letzte Zeile nennt "N von N Prüfungen bestanden". Voraussetzung ist `jq` im Pfad.

## Abbauen

```sh
docker compose -f scripts/dev/compose.yaml down
```

Mit `down -v` verschwinden auch die Daten der Dev-Nextcloud. Welt-Container und -Volumes tragen das Label `gameworld.managed=true` und lassen sich darüber finden.

## Sicherheitshinweis

Der Docker-Proxy ist nur auf `127.0.0.1:23750` publiziert. Wer diesen Port erreicht, kann Container erzeugen und ist damit faktisch root auf dem Host. Die Bindung an Loopback darf nicht gelockert werden. Das Backend bindet im Dev auf `0.0.0.0:10040`, damit der Nextcloud-Container es über `host.docker.internal` erreicht; geschützt ist es durch das Secret. Mit `GAMEWORLD_APP_HOST` lässt sich die Bindung einengen.

Auf demselben Rechner laufende Findling-Stacks (Port 8090) bleiben unberührt: eigener Projektname, eigene Ports, eigene Labels.
