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

   Das Skript baut bei Bedarf das Frontend nach `js/gameworld-main.js`, startet das Backend auf Port 10040 mit einem neuen Secret pro Lauf (`.dev/exapp.secret`, gitignored), registriert den Daemon `manual_install` und die ExApp und aktiviert sie. Den Einrichtungsassistenten (firstrunwizard) schaltet es in der Dev-Nextcloud ab, weil er Browser-Prüfungen blockiert. Ein Backend, das zu den Quellen passt, läuft weiter; ein veraltetes wird neu gestartet. Das Log steht in `.dev/exapp.log`; bei jedem Neustart wandert das Log des vorigen Backends nach `.dev/logs/` (die neuesten 20 bleiben), damit nach einem ungeplanten Ende der Grund nachlesbar ist.

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

## Phasenabnahme Phase 4

Belegt die sechs Erfolgskriterien von Phase 4 (Limit und Fenster pro Kind, Wochenplan, Ferien, Welt-Zeitfenster, Trennen mit Vorwarnung und Join-Sperre, Neustart- und Rejoin-Festigkeit) gegen den laufenden Stack mit echter Nextcloud und laufender ExApp (echter 15-s-Zeittakt):

```sh
sh scripts/dev/acceptance-phase4.sh
```

Werkzeuge wie in Phase 3: docker-CLI, curl, jq, tar, grep und `uv`. Einziges Python-Werkzeug des Projekts ist der Session-Prober `tests/e2e/luanti_probe.py` über seine CLI (`... NAME PASSWORT --hold SEKUNDEN` hält eine Sitzung und schneidet Chat und Trennen mit). Die Zeit-Eingaben (Wochentag, Minute, Datum in `Europe/Berlin`) rechnet ein kleiner Helfer per `zoneinfo`; `TZ=Europe/Berlin date` funktioniert in Git Bash nicht (keine Zeitzonendaten, falsche Stunde ohne Fehlermeldung). Tabellen liest das Skript mit `sqlite3`, falls installiert, sonst lesend über die Python-Standardbibliothek. Kurz vor Mitternacht (ab 23:50) wartet das Skript bis 00:01.

Das Skript legt die Welt "Abnahme Spielzeit" und das Wegwerfkonto `gw-abnahme4` an, setzt und löscht Regeln für `gw-kind`, legt einen Ferientag an, startet die Welt einmal und die ExApp einmal neu und hält in K5 zwei Sitzungen bis zu 170 s. Ein trap räumt alles in jedem Fall auf: Welt, Regeln von `gw-kind`, Ferien, Zeitzone zurück auf `Europe/Berlin`, Konto `gw-abnahme4`, `gw-kind` nicht in `admin`. Spielpasswörter erscheinen nie in der Ausgabe. Am Ende ruft es `acceptance-phase3.sh` als Regression, das wiederum Phase 1 und 2 ruft. Laufzeit etwa 20 Minuten (davon etwa 8 für Phase 4), Exit 0 nur bei "N von N Prüfungen bestanden". Mit `GAMEWORLD_SKIP_REGRESSION=1` entfällt die Regression; der Lauf endet dann bewusst mit Exit 1.

Die Wiederbeitritts-Sperre in K6 läuft in einem einzigen Prober-Prozess (`--hold 2 --rejoin-after 0.2`), der den Abstand zwischen Trennen und neuem Versuch misst (`gap_s`); zwei getrennte Prober-Aufrufe brauchten je einen Prozessstart, der die 2-s-Sperre des Mods gelegentlich schon überschritt. Wegwerfkonten legen die Skripte über `add_user` an: ein Altkonto aus einem abgebrochenen Lauf wird vorher gelöscht, `occ user:add` bekommt bis zu drei Versuche, und bei einem Fehlschlag steht die occ-Ausgabe im Log (das Passwort nie).

## Phasenabnahme Phase 4.1

Belegt die sechs Erfolgskriterien von Phase 4.1 (Pause für alle Welten, Hinweis bei fremdem Beitrittsversuch, Tagesrückblick, Handy-Seiten hinter den Links, Talk-Raum je Welt, Gameworld-Bot und Betrieb ohne Talk) gegen den laufenden Stack mit echter Nextcloud, laufender ExApp und installiertem Talk (siehe "Talk im Dev-Stack"):

```sh
sh scripts/dev/acceptance-phase4_1.sh
```

Werkzeuge wie in Phase 4: docker-CLI, curl, jq, grep und `uv`; Benachrichtigungen zählt das Skript über die OCS-API der App Notifications (`/ocs/v2.php/apps/notifications/api/v2/notifications`) je Konto, Talk über die OCS-API von spreed. Einziges Python-Werkzeug des Projekts ist der Session-Prober über seine CLI. Für K5 und K6 ruft es `smoke-talk.sh` auf. Echter Push auf ein Handy ist im Dev-Stack nicht prüfbar (localhost, manual-install); die Benachrichtigungsliste im Web ist der Ersatz.

Das Skript legt die Welten "Abnahme Pause", "Abnahme Ohne Talk" und "Abnahme Nachlegen" und die Wegwerfkonten `gw-abnahme41` und `gw-admin2` (in `admin`) an, setzt Regeln für `gw-kind`, startet eine Pause und "Für heute Schluss", schaltet den Tagesrückblick von admin kurz um, deaktiviert Talk einmal (`occ app:disable spreed`) und startet die ExApp dreimal gezielt neu. Bei gestoppter ExApp löscht es die Fremdversuche, Tagesmerker und den Rückblick-Versand des heutigen Tages, damit es an einem Tag mehrfach laufen kann. Ein trap räumt alles in jedem Fall auf: Welten, Pause, Rückblick-Einstellung von admin, Regeln und Verbrauch von `gw-kind`, beide Konten, `gw-kind` nicht in `admin`, Talk wieder aktiviert. Die Benachrichtigungen bleiben in der Glocke von admin stehen (für die Browser-Abnahme). Zwischen 23 Uhr und 0:16 wartet es bis 0:16.

Negativkontrollen erwarten den genauen Code: Ein Kind bekommt auf Verwaltungsrouten 403 vom Backend (seit 06-02 sind alle Routen USER, die Sperre ist `require_verwalter`; vorher 404 von AppAPI), Talk antwortet Nicht-Moderatoren mit 403. Leere Abrufe (SQL, Benachrichtigungsliste mit HTTP-Code ungleich 200) bestehen nie. Prüfungen, die im Dev-Stack nichts belegen können (echter Webhook von Talk an den Bot), weist `smoke-talk.sh` als `ÜBERSPRUNGEN` aus; sie zählen weder als bestanden noch als fehlgeschlagen. Den Webhook selbst prüft das Skript direkt am Backend, so wie AppAPI ihn aufruft.

Am Ende ruft es `acceptance-phase4.sh` als Regression, das wiederum Phase 1 bis 3 ruft. Laufzeit etwa 40 Minuten (davon etwa 15 für Phase 4.1, wegen der Wartezeit auf den 5-min-Talk-Abgleich in `smoke-talk.sh` und beim Nachlegen), Exit 0 nur bei "N von N Prüfungen bestanden". Mit `GAMEWORLD_SKIP_REGRESSION=1` entfällt die Regression; der Lauf endet dann bewusst mit Exit 1.

## Phasenabnahme Phase 6 und der Store-Weg lokal (HaRP)

Belegt die sieben Erfolgskriterien von Phase 6 (Installation, Setup-Check, Deaktivieren und Reste, Listing, Verwalter-Gruppen mit 404-Falle, Erwachsen-Schalter mit Pause und Zeitfenster, Talk-Übernahme) in zwei Modi:

```sh
sh scripts/dev/register-exapp.sh
sh scripts/dev/acceptance-phase6.sh                     # manual, mit Regression Phase 5 bis 1
sh scripts/dev/harp-install.sh
GAMEWORLD_DEPLOY=harp GAMEWORLD_SKIP_REGRESSION=1 sh scripts/dev/acceptance-phase6.sh
sh scripts/dev/harp-install.sh --uninstall               # Test-Stack samt Volumes weg
```

`harp-install.sh` geht den Weg einer Store-Installation ohne Archiv und Zertifikat: eigene Test-Nextcloud 34.0.3 mit Talk, eigener Docker-Proxy, echter HaRP-Daemon, Registry auf `127.0.0.1:5000` und eine Front auf `127.0.0.1:8093` (`/exapps/` an HaRP, sonst Nextcloud). Das Skript baut das Image, schiebt es in die lokale Registry, registriert eine Kopie der `info.xml` (`.dev/info-harp.xml`, nur `registry` umgeschrieben) per `occ app_api:app:register --info-xml` und prüft, dass der ExApp-Container als `10001:10001` läuft. Der HaRP-Schlüssel liegt in `.dev/harp.key`. Die Dev-Nextcloud auf 8091 und ihre Welten fasst dieser Weg nie an; Deaktivieren (D-17) prüft die Abnahme darum nur im Modus `harp`. K7 ohne Talk ist ein Fehler, außer mit `GAMEWORLD_SKIP_TALK=1`. Laufzeit ohne Regression etwa 20 Minuten (Abgleich-Intervall und zweimal Talk-Abgleich), mit Regression im Modus manual rund eine Stunde mehr.

K8 prüft die Sprache (D-25, D-27): Ein Konto mit `occ user:setting gw6-en core lang en` bekommt englische API-Texte, seine neue Welt spricht Englisch (Ablehnung, Sicherungs-Hinweis, Trenntext), nach dem Umschalten auf Französisch und einem Neustart Französisch; deutsche Konten und Welten bleiben deutsch. Die Kontosprache setzt `occ user:setting <uid> core lang <de|en|fr>`; ohne Einstellung meldet Nextcloud seine Standardsprache (im Dev-Stack Englisch), darum setzen die Abnahmen ihre Wegwerfkonten ausdrücklich auf `de`. Alle Konten und Gruppen der Phase-6-Abnahme tragen das Präfix `gw6-`, damit die Demo-Umgebung (`gw-lehrer`, `lehrkraefte`, `klasse`) unberührt bleibt.

## Talk im Dev-Stack

Für die Talk-Räume je Welt (Phase 4.1) braucht die Dev-Nextcloud die App Talk (spreed). Einmalig installieren (braucht Internet):

```sh
docker compose -f scripts/dev/compose.yaml exec -T -u www-data app php occ app:install spreed
```

Meldet occ "already installed", reicht `occ app:enable spreed`. Geprüft mit Talk 24.0.6 auf Nextcloud 34.0.3 (Capability `spreed` mit den Features `bots-v1`, `read-only-rooms` und `listable-rooms`).

Gameworld läuft ohne Talk unverändert weiter: Welten anlegen, einladen und löschen gelingen auch dann, `GET /api/talk` meldet nur `available: false`. Wird Talk später installiert, legt der Abgleich alle 5 Minuten die fehlenden Räume an.

Jeder Raum heißt "Gameworld: Weltname", ist eine Gruppenunterhaltung, nie öffentlich und nicht auffindbar. Mitglieder sind genau die eingeladenen Konten und die Verwalter; was jemand in Talk von Hand hinzufügt, entfernt der Abgleich wieder. Wer nach der Einladung einer Gruppe neu in diese Gruppe kommt, erscheint nach dem nächsten Abgleich (spätestens nach 5 Minuten) im Talk-Raum.

## Abbauen

```sh
docker compose -f scripts/dev/compose.yaml down
```

Mit `down -v` verschwinden auch die Daten der Dev-Nextcloud. Welt-Container und -Volumes tragen das Label `gameworld.managed=true` und lassen sich darüber finden.

## Sicherheitshinweis

Der Docker-Proxy ist nur auf `127.0.0.1:23750` publiziert. Wer diesen Port erreicht, kann Container erzeugen und ist damit faktisch root auf dem Host. Die Bindung an Loopback darf nicht gelockert werden. Das Backend bindet im Dev auf `0.0.0.0:10040`, damit der Nextcloud-Container es über `host.docker.internal` erreicht; geschützt ist es durch das Secret. Mit `GAMEWORLD_APP_HOST` lässt sich die Bindung einengen.

Auf demselben Rechner laufende Findling-Stacks (Port 8090) bleiben unberührt: eigener Projektname, eigene Ports, eigene Labels.

Der AppAPI-Proxy prüft das requesttoken nicht (`#[NoCSRFRequired]`, am Dev-Stack belegt). Darum nimmt das Backend Änderungen (POST, PUT, PATCH, DELETE) mit angemeldetem Nutzer nur mit `Content-Type: application/json` und ohne `Sec-Fetch-Site: cross-site`/`same-site` an, sonst 403. Eigene Skripte schicken den Header auch bei Anfragen ohne Inhalt mit (`curl -H 'Content-Type: application/json'`), so wie die Abnahmeskripte.
