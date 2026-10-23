# Phase 5: Backup und Restore - Research

**Researched:** 2026-10-23
**Domain:** Cold-Backup von Luanti-Welten über die Docker-Archive-API (gescopter tecnativa-Proxy) nach Nextcloud Files (nc_py_api 0.30.3, WebDAV-Chunked-Upload), Restore an Ort und Stelle, Status-/Reconciler-Integration
**Confidence:** HIGH für Docker-/Code-Muster (im Code und am Dev-Stack belegt), MEDIUM für das WebDAV-Upload-Verhalten unter Last und Kontingent

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Ablageort und Dateiname
- **D-01:** Backups landen in den Files des auslösenden Verwalters unter `Gameworld/Sicherungen/<Weltname>/` (Standard-Files-Features wie Teilen/Versionen bleiben nutzbar).
- **D-02:** Dateiname `<weltname>-JJJJ-MM-TT-HHMM.tar.gz` (sortiert sich selbst, Welt und Zeitpunkt sofort erkennbar). Format tar.gz.
- **D-03:** Inhalt: NUR Weltdaten (Weltordner mit map.sqlite, world.mt, Spielstand). Zugangsdatei (gameworld_access.txt) und Spielzeit-Zählbuch (gameworld_time*.txt) werden NICHT mitgesichert, sondern nach dem Restore frisch aus der ExApp provisioniert.

#### Restore-Verhalten
- **D-04:** Restore überschreibt die bestehende Welt an Ort und Stelle (nach Sicherheitsabfrage). Keine Restore-als-neue-Welt-Variante in v1.
- **D-05:** Vor jedem Restore legt die App automatisch ein Sicherheits-Backup des aktuellen Stands an (gleicher Ordner, Namenszusatz `vor-restore`). Restore ist damit immer umkehrbar.
- **D-06:** Nach dem Restore gilt der AKTUELLE Stand für Zugänge und Spielzeit: Zugangsdatei und Zeitregeln werden frisch provisioniert; Einladungen/Widerrufe/Limits von heute gelten, nur der Spielstand kommt aus dem Backup. Bereits genutzte Spielzeit von heute bleibt angerechnet (Zählbuch wird nicht zurückgesetzt; konsistent zu D-03).

#### Backup-Liste und Aufbewahrung
- **D-07:** Die Weltenansicht zeigt die vorhandenen Sicherungen (Datum, Größe) direkt aus dem Files-Ordner gelesen, mit Wiederherstellen-Knopf je Eintrag.
- **D-08:** Die App löscht NIE selbst Backups (alle behalten). Eltern räumen bei Bedarf in Nextcloud Files auf; die Liste zeigt die Gesamtgröße.

#### Ablauf-UX während Backup/Restore
- **D-09:** Sind beim Auslösen Spieler online: Verwalter sieht Warnung "In der Welt spielen gerade N Kinder, sie werden kurz getrennt" und muss bestätigen; die Spieler bekommen vorher einen kurzen Chat-Hinweis ("Die Welt macht gleich eine kurze Pause"), dann Stopp, Backup, Neustart.
- **D-10:** Eigene Phasen-Status: Weltkarte zeigt "Wird gesichert..." bzw. "Wird wiederhergestellt..." als eigenen Weltstatus (Muster wie "Startet gerade" aus Phase 2); Kinder-Ansicht kindgerecht "Die Welt macht kurz Pause"; Aktions-Knöpfe währenddessen gesperrt.
- **D-11:** Fehlerfall: Die Welt startet nach einem Backup-/Upload-Fehler IMMER wieder (Spielbetrieb geht vor); Verwalter sieht eine klare Fehlermeldung mit Grund; unvollständige Backup-Dateien werden aufgeräumt und nie als gültige Sicherung gelistet.

### Claude's Discretion
- Technischer Weg des Archiv-Streams (get_archive über Hilfs-/Kurzzeitcontainer vs. direkter Volume-Zugriff), Upload per nc_py_api `files.upload_stream`, Timeouts, maximale Größenbehandlung, tar-Normalisierung.
- Exakte API-Routen- und Statusmodell-Gestaltung (konsistent zu bestehenden Mustern aus Phase 2).
- Ob der Chat-Hinweis über den bestehenden Welt-Mod-Weg oder einen vorhandenen Mechanismus läuft (einfachster belastbarer Weg; wenn unverhältnismäßig teuer, Befund an Owner statt Eigenbau).
- Benachrichtigung nach Abschluss (z.B. über den bestehenden Notify-Weg aus Phase 4.1) optional, wenn billig zu haben.

### Deferred Ideas (OUT OF SCOPE)
- Automatische/geplante Backups (Zeitplan) , v2, BACKUP-01 ist bewusst manuell.
- Aufbewahrungsregeln (nur letzte N, Alterslöschung) , v2, App löscht in v1 nie selbst (D-08).
- Restore als neue Welt / Welt-Duplikation , v2 (D-04).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| BACKUP-01 | Elternteil kann pro Welt manuell ein Backup nach Nextcloud Files auslösen; der Snapshot ist konsistent (Welt wird sauber gestoppt oder eingefroren) | Pattern 1 (Cold-Snapshot über get_archive am gestoppten Container, kein Hilfscontainer), Pattern 2 (Streaming-Tar-Filter nach tar.gz in anonyme Temp-Datei), Pattern 3 (Upload per `upload_stream`, eindeutiger Zielname, Größenprüfung, DB-Eintrag), Pattern 6 (Chat-Hinweis per `@halt`-Zeile), Pattern 7 (Status/Sperren) |
| BACKUP-02 | Elternteil kann eine Welt aus einem Backup in Nextcloud Files wiederherstellen (Restore-Roundtrip funktioniert nachweislich) | Pattern 4 (Download, SHA-256-Prüfung, Validierung VOR dem Stopp), Pattern 5 (frisches Volume über den Phase-1-Erzeugungspfad statt Überschreiben, Zählbuch bewahren, Stufenmarker für Absturzsicherheit), Abschnitt Roundtrip-Test |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- Python-ExApp über AppAPI, `AsyncNextcloudApp` (keine Sync-API von nc_py_api), docker-py 7.2.0 synchron und in FastAPI per `anyio.to_thread` gekapselt.
- Docker nur über den tecnativa-Proxy mit CONTAINERS=1, IMAGES=1, VOLUMES=1, POST=1, alles andere 0 (kein EXEC). Kein roher Socket.
- `tarfile` (stdlib) plus nc_py_api Files (`files.upload_stream` für große Archive) ist die vorgegebene Backup-Technik; Welt vor dem Tar stoppen (map.sqlite ist laufend inkonsistent).
- Luanti 5.17.0 per Digest gepinnt; Konfiguration nur über Dateien, die die ExApp schreibt.
- Qualitätsgates lokal grün vor Commit: ruff (Vollsatz), pyright basic (`PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture, pytest.
- Kindersicherheit ist Produktkern: keine Admin-Rechte für Kinder, keine offenen Wege für fremden Code.
- Globale Owner-Regeln (aus `~/.claude/CLAUDE.md` und Memory): Deutsch mit echten Umlauten in Prosa und UI-Texten, keine Umlaute in Code-Bezeichnern/URLs; keine Gedankenstriche (U+2013/U+2014); keine Emojis; Commits nur als Owner ohne Claude-Trailer; Gameworld: sicherheitsrelevante Teile mit höchster Sorgfalt, Deep Review und `/gsd-secure-phase` plus Negativtests Pflicht; "nicht vermuten, prüfen" (Belege per Befehl, Gegenprobe mit unabhängigem Muster).
- GSD-Workflow: Änderungen nur über `/gsd-execute-phase` bzw. `/gsd-quick`.

## Summary

Die Phase braucht **keine neue Bibliothek**. Alles Nötige ist im Projekt schon vorhanden und an mindestens einer Stelle live belegt: `container.get_archive` liest Dateien aus dem Volume eines **gestoppten** Welt-Containers (so verbucht `_time_file` heute schon das Zählbuch vor jedem Start), `put_archive` schreibt in Volumes nie gestarteter Container (Phase-1-Lehre), `create_world_container` plus `_launch` bauen eine Welt vollständig und deterministisch aus Preset, Mods, Zugangs- und Regeldatei. Ein Kurzzeit-Hilfscontainer, wie ihn CLAUDE.md noch als Möglichkeit nennt, ist **nicht nötig**: Docker hängt das Volume für den Archiv-Endpunkt selbst ein, auch wenn der Container steht. Der Dev-Stack zeigt außerdem, dass Spiele eigene Dateien in den Weltordner schreiben (VoxeLibre: `mcl_maps/`, `doc.mt`), deshalb muss das Backup **alles außer einer festen Ausschlussliste** sichern, nicht nur eine Handvoll bekannter Dateien.

Für den Restore ist "Dateien drüberschreiben" die falsche Technik: `put_archive` kann nichts löschen. Eine alte `map.sqlite-journal` (heißes Journal nach einem Absturz, genau dem typischen Anlass für einen Restore) bliebe neben der zurückgespielten `map.sqlite` liegen, und SQLite würde sie beim nächsten Öffnen in die fremde Datenbank zurückrollen. Empfohlen ist deshalb: **Container und Volume entfernen und über den vorhandenen Phase-1-Erzeugungspfad neu anlegen**, dann den gefilterten Weltinhalt aus der Sicherung plus das bewahrte Zählbuch (D-06) per `put_archive` einspielen, bevor `_launch` startet. Das ist nur sicher, wenn vorher drei Dinge feststehen: die gewählte Sicherung ist lokal heruntergeladen, per SHA-256 gegen den eigenen DB-Eintrag geprüft und vollständig validiert; die `vor-restore`-Sicherung (D-05) liegt geprüft in Files; ein persistierter Stufenmarker sagt dem Boot-Abgleich, dass eine Welt mitten im Tausch steckt (sonst würde er sie als "Weltdaten fehlen, nur Löschen" markieren).

Die größten Planungsrisiken liegen nicht in Docker, sondern in der **Nebenläufigkeit**: Ein Backup dauert Minuten. Die bestehende globale Sperre `_LOCK` darf nicht so lange gehalten werden, sonst hängen Pause vom Handy, Einladungen und der 15-s-Zeittakt aller Welten. Deshalb: Sperre nur für kurze Abschnitte (Status setzen plus Stopp, Tausch plus Start), dazwischen schützt ein persistierter `op_state` (`backing_up`, `restoring`, `restoring_swap`) gegen Start, Neustart, Löschen und Pause-Neustart. Lange Abläufe laufen als Hintergrund-Task (HTTP 202 plus Polling über die vorhandene 5-s-Weltenliste), nie im Request.

**Primary recommendation:** Cold-Snapshot per `get_archive` direkt am gestoppten Welt-Container in eine anonyme Temp-Datei streamen (gefiltert, tar.gz, SHA-256), Welt sofort wieder starten, dann per `upload_stream` hochladen; Restore immer über "frisches Volume plus Phase-1-Erzeugungspfad", abgesichert durch geprüfte `vor-restore`-Sicherung und Stufenmarker im `op_state`.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Backup/Restore auslösen, Bestätigung bei Spielern online | API / Backend (FastAPI, `require_verwalter`) | Browser (Dialog, Polling) | Verwalter-Aktion; die Spielerzahl kennt nur das Backend sicher (Status-Datei), Bestätigung serverseitig erzwingen |
| Welt stoppen, Snapshot lesen, Volume neu anlegen | API / Backend (Provisioner über Docker-Proxy) | Docker-Engine | Einziger Zugriff auf Volumes ist die Docker-API (ExApp kann nichts mounten) |
| Tar-Filter, Kompression, SHA-256, Validierung | API / Backend (Worker-Thread) | , | CPU- und I/O-Arbeit, nie im Event-Loop |
| Ablage, Listing, Download | Nextcloud Files (WebDAV über nc_py_api im Namen des Verwalters) | API / Backend | D-01/D-07: Files ist die Quelle der Liste; Standardfunktionen (Teilen, Versionen) bleiben |
| Integritätsnachweis (Name, file_id, Größe, SHA-256, Welt, Preset) | Database / Storage (ExApp-SQLite) | , | Files ist für den Verwalter beschreibbar; nur ein eigener Eintrag macht eine Datei vertrauenswürdig |
| Chat-Hinweis und Trennen vor dem Stopp | Spielserver (Welt-Mod gameworld_time, Regeldatei) | API / Backend (schreibt `@halt`) | Luanti hat kein RCON; der Datei-Kanal mit 5-s-Nachladen existiert bereits |
| Status "Wird gesichert/wiederhergestellt", Sperre der Knöpfe | API / Backend (`derive_status`, `op_state`) | Browser | Gleiche Mechanik wie "Wird erstellt"/"Startet gerade" aus Phase 2 |
| Absturzsicherheit (Prozess stirbt mitten im Ablauf) | API / Backend (Boot-Abgleich) | Database / Storage | Nur der persistierte `op_state` überlebt einen Neustart |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| docker (docker-py) | 7.2.0 (installiert, gepinnt) | `Container.get_archive` (Snapshot), `put_archive` (Restore), `remove`/`create` (frisches Volume) | Schon einziger Docker-Client; `get_archive(path, chunk_size=2 MiB)` liefert einen Generator, Default-Chunk 2 MiB [VERIFIED: .venv docker/api/container.py, docker/constants.py] |
| nc_py_api | 0.30.3 (installiert, gepinnt) | `files.makedirs`, `files.listdir`, `files.by_path`, `files.upload_stream`, `files.download2stream`, `files.delete` | Offizielles Framework, bereits für Talk/Notify im Einsatz; Upload chunked mit abschließendem MOVE [VERIFIED: .venv nc_py_api/files/files_async.py] |
| tarfile, gzip, hashlib, tempfile (stdlib) | Python 3.13 | Stream-Lesen (Stream-Modus `mode="r\|"`), Schreiben (`mode="w:gz"`), SHA-256, anonyme Temp-Datei | Keine Abhängigkeit, im Projekt bereits Muster (`archive.py`) [CITED: docs.python.org/3/library/tarfile.html] |
| anyio | via FastAPI | `anyio.to_thread.run_sync` für alle Docker- und Tar-Arbeit | Projektmuster aus `worlds/service.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sqlite3 (stdlib) | Python 3.13 | Nur im Roundtrip-Test: `players.sqlite`/`map.sqlite` aus Snapshot und Restore vergleichen | Tests und Abnahmeskript (Host hat kein `sqlite3`-CLI, siehe Environment) |
| tests/e2e/luanti_probe.py | Projektcode | Spielstandwirksame Änderung ohne echten Client (`session()` tritt bis `on_joinplayer` bei) | Roundtrip-Test |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| get_archive am gestoppten Welt-Container | Kurzzeit-Hilfscontainer mit Volume-Mount | Unnötig: get_archive funktioniert am gestoppten Container (im Code belegt). Ein Hilfscontainer bringt ein neues Muster, ein zweites Image-Verhalten und Aufräumpflichten |
| Restore per frischem Volume | Überschreiben per put_archive in das bestehende Volume | put_archive löscht nichts: verwaiste Dateien und heiße SQLite-Journale bleiben liegen und können die zurückgespielte Datenbank beschädigen |
| Restore per frischem Volume | Hilfscontainer mit `sh -c "rm -rf ... && tar x"` | Funktioniert, aber führt Shell-Befehle in Containern ein (exec-artig), widerspricht dem Geist "kein exec" |
| Eigene Upload-Schleife über WebDAV | `files.upload_stream` | Eigenbau ohne Nutzen; nc_py_api räumt den Upload-Ordner im `finally` selbst auf |
| aiodocker für echtes Async-Streaming | docker-py im Worker-Thread | aiodocker wäre eine neue Abhängigkeit; der Thread-Weg reicht, weil der Snapshot in eine Datei geht |

**Installation:** keine. Es wird kein Paket hinzugefügt.

**Version verification:** Installiert und importiert am 2026-10-23: Python 3.13.13, nc_py_api 0.30.3, docker 7.2.0 [VERIFIED: `.venv/Scripts/python.exe -c "import nc_py_api, docker"`].

## Package Legitimacy Audit

Diese Phase installiert **keine** externen Pakete. slopcheck wurde deshalb nicht ausgeführt.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| (keins neu) | , | , | , | , | , | , |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
BACKUP (POST /api/worlds/{id}/backups, 202)
Verwalter-Browser
  -> API: require_verwalter, Spieler online? ohne confirm_disconnect -> 409 {players: N}
  -> Job-Start (asyncio-Task, global höchstens 1 Job)
       [Sperre kurz] op_state=backing_up, Job-Zeile "läuft"
       Spieler online? -> Regeldatei mit "@halt <ab>" schreiben -> Mod: Chat-Hinweis, ab <ab> trennen
                         -> warten bis ab + 2 s
       [Sperre kurz] docker stop (30 s) -> prüfen: Container läuft NICHT
       [Thread] get_archive(world) --2-MiB-Chunks--> IterStream -> tarfile "r|"
                 -> Filter (Ausschlussliste, nur Datei/Ordner, sichere Pfade)
                 -> tarfile "w:gz" in TemporaryFile + SHA-256 + Manifest
       [Sperre kurz] _launch (Mods, frische Zugangs-/Regeldatei, Start), op_state=ready   <- IMMER, auch bei Fehler (D-11)
       [async] Files: makedirs Gameworld/Sicherungen/<Ordner> -> eindeutiger Name
                 -> upload_stream (Chunks + MOVE) -> by_path: Größe == lokal?
                 -> ja: DB-Eintrag backups(file_id, name, size, sha256, world_id, preset, owner)
                 -> nein/Fehler: Ziel löschen (nur eigener Name), Job "fehlgeschlagen: <Grund>"
       Temp-Datei schließen (anonym, verschwindet auch bei Absturz)

RESTORE (POST /api/worlds/{id}/restore {file_id, confirm, confirm_disconnect}, 202)
  -> DB-Eintrag zu file_id + Welt + Besitzer vorhanden? sonst 404/409
  [Welt läuft weiter] Download -> TemporaryFile; SHA-256 == Eintrag? Validierung (Pfade, Typen,
                      Größen, Manifest-Preset == Welt-Preset, map.sqlite vorhanden)
                      -> gefiltertes Restore-Tar (uid 30000, Modus normiert) in zweite TemporaryFile
  [Sperre kurz] op_state=restoring, ggf. @halt + Wartezeit, docker stop
  [Thread] Sicherheits-Snapshot des aktuellen Stands (wie Backup) + Zählbuch-Bytes lesen und verbuchen
  [async] Upload "<name>-...-vor-restore.tar.gz", Größenprüfung, DB-Eintrag
          -> Fehler: Welt mit altem Stand neu starten, Job "fehlgeschlagen", ENDE (nichts zerstört)
  [Sperre] op_state=restoring_swap (persistiert) -> remove_world(keep_volume=False)
           -> create_world_container(Preset-Payload, frische conf/world.mt/Mods/Zugang/Regeln)
           -> put_archive(WORLD_PATH, Restore-Tar + Zählbuch) -> Event-Cursor zurücksetzen
           -> _launch (falls desired_state running) -> op_state=ready
           Fehler im Tausch: einmal wiederholen, dann aus lokalem Sicherheits-Snapshot,
           sonst op_state=failed mit RESTORE_INTERRUPTED (wiederholbar, NICHT delete-only)

BOOT-ABGLEICH nach Absturz
  backing_up / restoring  -> op_state=ready, dann normale Regeln (START bei desired running)
  restoring_swap          -> failed + RESTORE_INTERRUPTED, kein Start (Welt evtl. leer/halb)
```

### Recommended Project Structure
```
src/gameworld/
├── backup/
│   ├── __init__.py
│   ├── archive.py      # rein: IterStream, Filter, Snapshot-Tar bauen, Restore-Tar validieren/bauen, Manifest
│   ├── naming.py       # rein: Ordner- und Dateiname (D-01/D-02), Kollisionssuffix, Zeitzone
│   ├── files.py        # async: Files-Zugriff (makedirs, listdir, upload, download, delete) über nc_as(uid, ...)
│   └── service.py      # Ablauf Backup/Restore, Job-Zustand, Sperrabschnitte, Fehlertexte
├── api/backups.py      # GET/POST /api/worlds/{id}/backups, POST /api/worlds/{id}/restore
├── provisioner/client.py   # neu: snapshot_world(world_id) -> Iterator[bytes] (get_archive), put_world_archive(world_id, BinaryIO)
├── provisioner/time_mod.py # neu: @halt-Zeile (Render + Lua)
├── worlds/status.py        # neue Codes/Texte für backing_up/restoring
├── worlds/reconciler.py    # decide_boot/decide_periodic für die neuen op_states
├── worlds/service.py       # Busy-Guards in start/restart/delete/_pause_world, _track_run_state
└── worlds/store.py         # Schema 7: Tabellen backups, backup_jobs
frontend/src/components/BackupSection.vue  # Liste, Gesamtgröße, Knöpfe, Bestätigungsdialoge
tests/test_backup_archive.py, test_backup_naming.py, test_backup_service.py, test_backups_api.py
tests/e2e/test_backup_restore_e2e.py
scripts/dev/acceptance-phase5.sh
```

### Pattern 1: Cold-Snapshot direkt am gestoppten Container (kein Hilfscontainer)
**What:** `docker stop` (vorhandenes `provisioner.stop`, 30 s Stop-Timeout, Luanti speichert bei SIGTERM), danach den Zustand prüfen, dann `container.get_archive(WORLD_PATH)` und den Generator streamen.
**When to use:** Jeder Backup- und jeder Sicherheits-Snapshot.
**Belege:**
- `client.read_time_ledger` liest per get_archive "auch bei gestoppter Welt" und wird in `_time_file` vor jedem Start auf gestoppten Containern benutzt (Phase 4 live) [VERIFIED: src/gameworld/provisioner/client.py, worlds/service.py].
- `GET /containers/{id}/archive` hat keine Einschränkung auf laufende Container; 404 nur bei fehlendem Container oder Pfad [CITED: Docker Engine API v1.47 OpenAPI, ContainerArchive].
- Der Proxy erlaubt GET auf `/containers/...` mit CONTAINERS=1; HAProxy-Timeouts `timeout client 10m`, `timeout server 10m` sind Inaktivitäts-Timeouts, kein Gesamtlimit, `timeout http-request 10s` betrifft nur den Anfragekopf [VERIFIED: haproxy.cfg tecnativa/docker-socket-proxy v0.5.0].
- Docker liefert die Einträge mit Präfix `world/` (Basisname des angefragten Pfads); Dev-Stack-Inhalt einer VoxeLibre-Welt: `auth.sqlite, doc.mt, env_meta.txt, gameworld_*.txt, map.sqlite, map_meta.txt, mcl_maps/, mod_storage.sqlite, players.sqlite, world.mt, worldmods/` [VERIFIED: `docker cp ... - | tar -tv` am Dev-Stack, 2026-10-23].

**Wichtig:** Den lesenden Zugriff NICHT über `_read` (zweiter Versuch) laufen lassen, sondern einmal über `_guarded`: ein halb gelesener Strom darf nie still neu beginnen. Nach `stop` per `list_managed`/`reload` prüfen, dass der Container nicht `running` ist; sonst Abbruch (SQLite-Konsistenz, Erfolgskriterium 2).

```python
# provisioner/client.py (neu), Source: docker-py 7.2.0 Container.get_archive
SNAPSHOT_CHUNK = 2 * 1024 * 1024

def snapshot_world(self, world_id: str) -> Iterator[bytes]:
    """Tar-Strom des Weltordners; nur bei gestopptem Container (Erfolgskriterium 2)."""
    with self._guarded():
        container = self._owned(world_id)
        container.reload()
        if container.status == "running":
            raise ProvisionerError("Die Welt läuft noch; eine Sicherung braucht eine gestoppte Welt.")
        stream, _stat = container.get_archive(WORLD_PATH, chunk_size=SNAPSHOT_CHUNK)
    return stream  # Aufrufer liest im Worker-Thread und schließt; Transportfehler beim Lesen selbst abbilden
```

Hinweis für den Planer: Fehler, die erst beim Iterieren des Generators auftreten (Proxy bricht ab), laufen nicht mehr durch `_guarded`. Das Iterieren deshalb ebenfalls in einen `with self._guarded():`-Block legen (etwa `snapshot_to(world_id, sink)` statt Generator nach außen zu geben).

### Pattern 2: Streaming-Filter nach tar.gz in eine anonyme Temp-Datei
**What:** Docker-Generator als Datei-Objekt (`io.RawIOBase.readinto`), `tarfile.open(fileobj=..., mode="r|")` lesen, jedes zugelassene Mitglied mit `extractfile` in `tarfile.open(fileobj=spool, mode="w:gz", compresslevel=6, format=tarfile.PAX_FORMAT)` übernehmen. Speicher bleibt konstant (Chunk-Größe), der Snapshot liegt auf Platte.
**When to use:** Backup und Sicherheits-Snapshot.

Ausschlussliste Backup (D-03 plus Laufzeitdateien der eigenen Mods), Pfade relativ zum Weltordner:
- `gameworld_access.txt`, `gameworld_access_state.txt`, `gameworld_events.txt`, `gameworld_players.txt`, `gameworld_time.txt`, `gameworld_time_used.txt` (Konstanten aus `access_mod`, `status_mod`, `time_mod` nehmen, nie Strings duplizieren)
- `worldmods/` (wird bei jedem Start aus dem App-Code geschrieben)
- Alles, was kein reguläres File und kein Verzeichnis ist (Symlinks, Hardlinks, Geräte): überspringen und zählen

NICHT ausschließen: `*-journal` (heißes Journal gehört nach einem harten Stopp als Paar zur Datenbank), `world.mt` (D-03 nennt sie; beim Restore wird sie ignoriert), unbekannte Dateien und Ordner der Spiele (`mcl_maps/`, `doc.mt`).

Zusätzlich ein Manifest an die Tar-Wurzel (außerhalb von `world/`): `gameworld-backup.json` mit `format: 1`, `world_id`, `preset`, `luanti_version`, `created_at`, `kind` (`backup`/`vor-restore`). Billig und für v2 (Restore als neue Welt) wertvoll.

```python
# backup/archive.py, Source: docs.python.org/3/library/tarfile.html (Stream-Modus "r|")
class IterStream(io.RawIOBase):
    def __init__(self, chunks: Iterator[bytes]) -> None:
        self._chunks, self._rest = chunks, b""
    def readable(self) -> bool:
        return True
    def readinto(self, buffer) -> int:
        while not self._rest:
            try:
                self._rest = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(buffer), len(self._rest))
        buffer[:size], self._rest = self._rest[:size], self._rest[size:]
        return size

def write_snapshot(chunks: Iterator[bytes], sink: BinaryIO, manifest: bytes) -> SnapshotInfo:
    hasher = HashingWriter(sink)  # zählt Bytes und rechnet SHA-256 beim Schreiben
    with tarfile.open(fileobj=hasher, mode="w:gz", compresslevel=6, format=tarfile.PAX_FORMAT) as out:
        add_bytes(out, "gameworld-backup.json", manifest)
        with tarfile.open(fileobj=io.BufferedReader(IterStream(chunks), 1 << 20), mode="r|") as src:
            for member in src:
                relative = world_relative(member.name)          # "world/x" -> "x", sonst None
                if relative is None or excluded(relative) or not (member.isfile() or member.isdir()):
                    continue
                info = normalized(member, f"world/{relative}")  # uid/gid 30000, Modus 0644/0755, uname/gname leer
                out.addfile(info, src.extractfile(member) if member.isfile() else None)
    return SnapshotInfo(size=hasher.count, sha256=hasher.hexdigest())
```

`tarfile.open(mode="w:gz")` hat als Vorgabe `compresslevel=9`; auf Heimserver-CPUs ist 6 deutlich schneller bei kaum größerer Datei [CITED: docs.python.org/3/library/tarfile.html, `compresslevel` für w:gz]. Temp-Datei: `tempfile.TemporaryFile(dir=<storage_dir>/tmp)` (anonym, auf Linux sofort entkoppelt; nach einem Absturz bleibt nichts liegen). Den Ordner unter `APP_PERSISTENT_STORAGE` statt `/tmp` nehmen: das ist ein Volume, kein Container-Overlay.

### Pattern 3: Upload, Integritätsnachweis und Liste
**What:** Nach dem Neustart der Welt (Ausfallzeit endet mit dem Snapshot, nicht mit dem Upload) die Temp-Datei hochladen.

Belegtes Verhalten von `upload_stream` in 0.30.3 [VERIFIED: .venv nc_py_api/files/files_async.py]:
- legt `uploads/<user>/nc-py-api-<zufall>` an, lädt Chunks (`fp.read(chunk_size)`, Vorgabe 5 MiB), schließt mit `MOVE .../.file` und `Destination` ab, löscht den Upload-Ordner IMMER im `finally`;
- das Ziel erscheint erst durch den MOVE: ein abgebrochener Upload hinterlässt keine halbe Zieldatei (D-11);
- `MOVE` ohne `Overwrite`-Header: WebDAV-Vorgabe ist Überschreiben, deshalb den Zielnamen vorher eindeutig machen;
- Timeout je Request aus `npa_timeout_dav` (Vorgabe `NPA_TIMEOUT_DAV`=90 s), pro Client setzbar: `AsyncNextcloudApp(user=uid, npa_timeout_dav=600, chunked_upload_v2=False)` [VERIFIED: nc_py_api/_session.py RuntimeOptions];
- `download2stream(path, fp)` streamt per `iter_raw` in ein Datei-Objekt, nichts im RAM [VERIFIED: nc_py_api/_session.py download2fp].

Empfehlungen:
- `nc_as(uid)` um optionale Keyword-Argumente erweitern (Timeout, `chunked_upload_v2=False`) statt einen zweiten Client-Weg zu bauen; Sessions schließen bleibt Pflicht (WR-05).
- `chunked_upload_v2=False`: nc_py_api 0.30.3 nummeriert v2-Chunks ab 0, die Nextcloud-Doku verlangt 1 bis 10000; auf Object-Storage-Servern ist das ein bekannter Streitpunkt (PR #324) [CITED: docs.nextcloud.com chunking.html; github.com/cloud-py-api/nc_py_api/pull/324]. v1 ist überall unterstützt [ASSUMED].
- `chunk_size=10 MiB` (weniger Requests, weit unter typischen Body-Limits).
- Nach dem Upload `by_path(ziel)` und `info.size == lokale Größe` prüfen, erst dann den DB-Eintrag `backups` schreiben (file_id, Pfad, Name, Größe, SHA-256, world_id, preset, owner_uid, created_at, kind). Fehlt die Bestätigung, das eigene Ziel mit `delete(path, not_fail=True)` entfernen (nur unseren frisch gewählten Namen, nie einen fremden).
- Kontingent: Nextcloud meldet Überschreitung mit `507 Insufficient Storage`; ohne `OC-Total-Length` (setzt nc_py_api nicht) erst beim MOVE [CITED: docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/chunking.html]. `NextcloudException.status_code == 507` auf einen festen deutschen Text abbilden ("Nicht genug Speicherplatz in deinen Nextcloud-Dateien"). Optionaler Vorab-Check über `nc.users.get_user(uid).quota` (Feld `free`) [ASSUMED Feldname].
- Liste (D-07): `listdir("Gameworld/Sicherungen/<Ordner>")` als der anfragende Verwalter, 404 heißt leere Liste. Gültig gelistet wird nur, was einen DB-Eintrag mit gleicher `file_id` und gleicher Größe hat (D-11: nie halbe oder fremde Dateien als Sicherung). Gesamtgröße (D-08) = Summe der gültigen Einträge; optional zusätzlich "weitere Dateien im Ordner: N" ohne Knopf. FsNode liefert `name`, `file_id`, `info.size`, `info.last_modified` [VERIFIED: nc_py_api/files/__init__.py].

### Pattern 4: Restore-Vorbereitung VOR dem Stopp
**What:** Alles, was scheitern kann, ohne die Welt anzufassen: Download in Temp-Datei, SHA-256 gegen DB-Eintrag, vollständige Validierung, gefiltertes Restore-Tar bauen.
**Validierung (Negativtests Pflicht):**
- nur Einträge unter `world/` plus das Manifest; Manifest-`preset` muss `row.preset` entsprechen, `world_id` der Welt (sonst 409 "Diese Sicherung gehört zu einer anderen Welt");
- Pfade über das vorhandene `_safe_relative` aus `provisioner/archive.py` (kein `..`, kein absoluter Pfad, kein Backslash, kein Doppelpunkt);
- nur `isfile()`/`isdir()`; Symlinks, Hardlinks, Geräte, FIFOs: Abbruch;
- beim Restore zusätzlich verworfen: `world.mt` (wird aus dem Preset gerendert: SQLite-Backends erzwungen, kein `load_mod_*`), `worldmods/`, alle Dateien mit Endung `.lua`, Verzeichnisse `mods/` und `game/` im Weltordner [ASSUMED: ob Luanti `game/` im Weltordner lädt, ist nicht geprüft; verwerfen ist billig], alle `gameworld_*`-Dateien;
- `map.sqlite` muss vorhanden sein;
- Grenzen: Summe der entpackten Größen (Vorschlag 8 GiB), Anzahl Einträge (Vorschlag 200 000), Verhältnis entpackt zu gepackt (Vorschlag 50) gegen Zip-Bomben;
- Modus und Besitzer normieren (uid/gid 30000, 0644/0755, mtime aus dem Archiv übernehmen).

### Pattern 5: Restore per frischem Volume über den Phase-1-Pfad
**What:** Nach geprüfter `vor-restore`-Sicherung: `op_state=restoring_swap` persistieren, `remove_world(world_id, keep_volume=False)`, `ensure_image`, `create_world_container(world_id, row.port, payload)` mit dem normalen `_payload(row)` (frische `minetest.conf`, `world.mt`, Mods, Zugangs- und Regeldatei, Spiel), danach `put_archive(WORLD_PATH, restore_tar)` am noch nie gestarteten Container, dann `_launch(row)` (wenn `desired_state == "running"`), `op_state=ready`.
**Why:** `put_archive` kann nichts löschen; ein frisches Volume ist garantiert frei von heißen Journalen und verwaisten Dateien. Das Schreiben in Volumes nie gestarteter Container ist die Phase-1-Lehre; Docker akzeptiert für `PUT /containers/{id}/archive` Tar unkomprimiert, gzip, bzip2 oder xz [CITED: Docker Engine API v1.47 OpenAPI, PutContainerArchive]; das Restore-Tar darf also gzip sein und spart Platz.
**Details, die der Plan enthalten muss:**
- Zählbuch (D-06): vor dem Tausch `read_time_ledger` lesen und `_book_ledger` verbuchen; die Bytes (uid 30000, 0644) ins Restore-Tar legen. So bleibt die heute genutzte Zeit angerechnet und der Mod startet mit identischem Zählbuch. Danach `self._time.forget(world_id)`.
- Ereignis-Cursor der Welt zurücksetzen (neue Ereignisdatei beginnt bei 1; `new_events` behandelt Rücksprung zwar schon "Restore, neues Volume", der Reset macht die Erstkontakt-Regel 3 eindeutig) [VERIFIED: src/gameworld/events/parse.py].
- `client.write_world_files` nimmt heute `bytes`; eine Variante mit `BinaryIO` ergänzen (put_archive akzeptiert Datei-Objekte, so wie `create_world_container` es schon nutzt).
- Fehler im Tausch: einmal wiederholen; dann den lokalen Sicherheits-Snapshot (noch in der Temp-Datei) auf demselben Weg einspielen; erst wenn auch das scheitert `op_state=failed`, `last_error=RESTORE_INTERRUPTED` ("Das Wiederherstellen wurde unterbrochen. Bitte erneut wiederherstellen; die Sicherung vor dem Wiederherstellen liegt in Files."). Diese Meldung darf NICHT in `DELETE_ONLY_ERRORS`, und Restore muss im Zustand `failed` erlaubt sein.
- `desired_state` bleibt, wie er war: eine gestoppte Welt bleibt nach dem Restore gestoppt.

### Pattern 6: Chat-Hinweis über die Regeldatei (`@halt`)
**What:** Neue `@`-Zeile in `gameworld_time.txt`: `@halt <ab>`. Der Mod lädt die Regeldatei alle 5 s (`local TICK = 5`) [VERIFIED: provisioner/time_mod.py]; sieht er `@halt`, sendet er einmal je `ab` an alle `core.chat_send_all("Die Welt macht gleich eine kurze Pause.")`, lässt ab dann niemanden mehr hinein (prejoin-Text "Die Welt macht kurz Pause. Gleich geht es weiter.") und trennt ab `ab` alle per `core.disconnect_player(name, <Text>)` (kein "Kicked:"-Präfix, gleiches Muster wie Pause).
**Ablauf:** Nur wenn Spieler online sind (Status-Datei). `ab = jetzt + 15 s` (5 s Nachladetakt plus 10 s Lesezeit), ExApp wartet bis `ab + 2 s`, dann `docker stop`. Ohne Spieler: sofort stoppen.
**Rendern:** Ein flüchtiger Halt-Zeitpunkt je Welt im `TimeEngine` (nur im Speicher), `render` hängt die Zeile an, `push_time` schreibt sie unter der Sperre. Nach dem Neustart rendert `_launch` die Datei ohne `@halt`.
**Kompatibilität:** Alte Mods überspringen `@`-Zeilen still (dokumentiertes Verhalten seit Quick 261021-481) [VERIFIED: time_mod.py Docstring]; eine vor dem Update gestartete Welt bekommt dann eben keinen Hinweis, der Ablauf bleibt korrekt. Kosten: eine Lua-Funktion, eine Render-Zeile, Tests im Stil von `tests/test_time_mod.py`. Das ist verhältnismäßig; kein Befund an den Owner nötig.
**Nicht nehmen:** die Haushalts-Pause (`@pause`): sie gilt für alle Welten und hat eigene Texte und Outbox-Meldungen.

### Pattern 7: Status, Sperren, Reconciler
- `op_state` bekommt drei Werte: `backing_up`, `restoring`, `restoring_swap`. `derive_status` prüft sie direkt nach `reachable` und vor `creating`: `WorldStatus("backing_up", "Wird gesichert ...")` bzw. `("restoring", "Wird wiederhergestellt ...")` (Text der UI-Phase folgt der UI-Spezifikation; Codes als neue Konstanten wie `STARTING`).
- Kinder-Ansicht (`api/me.py`, `/api/my/worlds`): bei diesen Codes fester Text "Die Welt macht kurz Pause" (AR-24-Muster: nie Docker-Text an Kinder).
- Guards: `_start_world_sync`, `_restart_world_sync`, `_delete_world_sync` werfen bei Busy-`op_state` einen eigenen Fehler (HTTP 409 "Die Welt wird gerade gesichert/wiederhergestellt."); `apply_pause_sync`/`_pause_world` überspringt den Neustart busy Welten (die Regeldatei schreiben darf es weiter); `_track_run_state` überspringt busy Welten, sonst meldet der Talk-Bot "aus"/"an" (`BOT_STOP`/`BOT_START`, silent) mitten im Backup [VERIFIED: notify/loop.py].
- Nur ein Job gleichzeitig (Heimserver-Platte und -CPU): Prüfung "keine Zeile mit Busy-`op_state` und kein laufender Job" unter `_LOCK` beim Start, sonst 409.
- Periodischer Abgleich: unverändert ungefährlich, er startet nie (`decide_periodic` setzt nur `ADOPT_RUNNING` bei `desired_state == "stopped"` und laufendem Container) [VERIFIED: worlds/reconciler.py]. Eine Regel ergänzen: Busy-Zeilen nie anfassen.
- Boot-Abgleich (`decide_boot`): `backing_up` und `restoring` heißen "vor der Zerstörung abgebrochen": `op_state=ready` setzen und dann die normalen Regeln (startet die Welt, wenn sie laufen soll; D-11). `restoring_swap` heißt "Daten evtl. halb": neue Aktion `MARK_RESTORE_INTERRUPTED` (failed, wiederholbar), nie `START`, nie `MARK_DATA_MISSING`. Die Busy-Werte zusätzlich in `needs_volume_check` berücksichtigen.
- Job-Zustand: eigene Tabelle `backup_jobs` (world_id, kind, state `running|ok|failed`, message, file_name, started_at, finished_at), damit der Verwalter die Fehlermeldung (D-11) auch nach Neuladen sieht und der Boot-Abgleich laufende Jobs als abgebrochen markieren kann. In `WorldView` ein Feld `backup_job` ergänzen; die 5-s-Weltenliste trägt den Status ohne neuen Poll-Endpunkt.
- Hintergrund-Tasks: im Modul eine `set[asyncio.Task]` halten (sonst sammelt der GC sie ein), im Lifespan beim Beenden abbrechen; der Boot-Abgleich heilt den Rest.

### Anti-Patterns to Avoid
- **`_LOCK` für den ganzen Ablauf halten:** blockiert Pause vom Handy (`apply_pause_sync` nimmt `_mutating()` blockierend), Einladungen und den 15-s-Takt aller Welten für Minuten.
- **Backup/Restore im HTTP-Request ausführen:** AppAPI-/HaRP-Proxy-Timeouts [ASSUMED Größenordnung]; immer 202 plus Polling.
- **`map.sqlite` aus laufendem Container lesen** (auch nicht "nur kurz"): verletzt Erfolgskriterium 2. Vor `get_archive` den Zustand prüfen.
- **Restore durch Überschreiben ins bestehende Volume:** heiße Journale, verwaiste Dateien.
- **`world.mt`, `worldmods/` oder `.lua` aus einer Sicherung übernehmen:** Codeausführung im Spielserver, abweichende Backends.
- **Dateien in Files ohne eigenen DB-Eintrag wiederherstellen:** Files ist für Verwalter (und Freigabeempfänger) beschreibbar.
- **`_read` (zweiter Versuch) für den Snapshot-Strom:** ein zweiter Lauf nach halbem Strom ergibt doppelte Tar-Einträge.
- **Ganzen Strom in `bytes` sammeln** (`_read_capped`-Muster aus dem Status-Lesen): bei hunderten MB RAM-Spitze im ExApp-Prozess.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Chunked Upload nach Nextcloud | eigene MKCOL/PUT/MOVE-Schleife | `files.upload_stream` | räumt den Upload-Ordner im `finally` auf, Ziel erscheint erst beim MOVE |
| Streaming-Download | `files.download` (alles im RAM) | `files.download2stream(path, fp)` | Speicher konstant |
| Tar-Parsing und gzip | eigener Tar-Parser | `tarfile` Stream-Modus `r\|` und `w:gz` | PAX, lange Namen, Prüfsummen |
| Pfadsicherheit | neue Regex | `_safe_relative` aus `provisioner/archive.py` | schon geprüft und getestet |
| Welt neu aufbauen | eigener "Restore-Payload" mit Spiel und conf | `_payload(row)` plus `create_world_container` plus `_launch` | Port-Saga, Neuerzeugung, Mods, Zugang, Regeln sind dort schon richtig |
| Chat an Spieler | RCON-Ersatz, stdin, attach | Regeldatei-Zeile `@halt` im vorhandenen Zeit-Mod | Kanal mit 5-s-Nachladen existiert |
| Status-Polling | eigener Job-Poll-Endpunkt | Feld in `WorldView`, 5-s-Weltenliste | gleiche Cache- und Polling-Mechanik |

**Key insight:** Fast jeder Teilschritt existiert schon im Code. Das Risiko liegt in der Reihenfolge (was ist vor dem Zerstören bewiesen) und in der Nebenläufigkeit (wer darf die Welt währenddessen anfassen), nicht in neuer Technik.

## Common Pitfalls

### Pitfall 1: Heißes SQLite-Journal überlebt den Restore
**What goes wrong:** Nach einem Absturz liegt `map.sqlite-journal` im Volume; ein Restore per Überschreiben lässt sie liegen, SQLite rollt sie beim Öffnen in die zurückgespielte Datei zurück.
**Why it happens:** Luanti setzt nur `PRAGMA synchronous` und `foreign_keys`, kein WAL, also Rollback-Journal im DELETE-Modus [VERIFIED: luanti 5.17.0 src/database/database-sqlite3.cpp]; `put_archive` löscht nichts.
**How to avoid:** Frisches Volume (Pattern 5). Im Backup Journale NICHT ausschließen (Paar bleibt konsistent).
**Warning signs:** Welt startet nach Restore mit "database disk image is malformed" im Log.

### Pitfall 2: Boot-Abgleich macht aus einem unterbrochenen Restore eine "nur löschen"-Welt
**What goes wrong:** Prozess stirbt nach `remove_world`, Volume weg; `decide_boot` sieht `container None` plus `volume False` und setzt `MARK_DATA_MISSING` (delete-only).
**How to avoid:** `restoring_swap` persistieren, bevor irgendetwas entfernt wird; eigene Boot-Aktion; Restore im Zustand `failed` erlauben.
**Warning signs:** Test "Prozessabbruch nach remove" zeigt `delete_only: true`.

### Pitfall 3: Globale Sperre minutenlang gehalten
**What goes wrong:** Pause vom Handy hängt, Zeitregeln anderer Welten werden nicht mehr geschrieben.
**How to avoid:** Kurze Sperrabschnitte plus Busy-`op_state`-Guards (Pattern 7). Test: während eines künstlich verlangsamten Uploads `POST /api/pause` muss sofort antworten.

### Pitfall 4: Ordnername aus dem Weltnamen bricht aus oder scheitert
**What goes wrong:** `normalize_world_name` erlaubt `.` und damit Namen wie `..` oder `.` [VERIFIED: luanti_conf.py `[\w .\-]+`]; `Gameworld/Sicherungen/..` zeigt auf den Elternordner. Nextcloud mit "Windows-kompatiblen Dateinamen" lehnt Namen mit Punkt oder Leerzeichen am Ende und reservierte Namen (CON, NUL, COM1 ...) ab [ASSUMED Details der NC-Option]. Weltnamen sind nicht eindeutig (keine UNIQUE-Spalte) [VERIFIED: worlds/store.py], zwei Welten "Burg" teilen sich sonst den Ordner.
**How to avoid:** `backup/naming.py`: Punkte und Leerzeichen am Rand entfernen, `.`/`..`/leer und reservierte Namen durch `Welt-<id6>` ersetzen; die Zugehörigkeit nie aus dem Ordner ableiten, sondern aus dem DB-Eintrag (world_id, file_id). Bei abgelehntem Pfad (400/403 InvalidPath) auf `Welt-<id6>` ausweichen.

### Pitfall 5: Gleicher Dateiname in derselben Minute
**What goes wrong:** D-02 hat Minutenauflösung; zwei Sicherungen in einer Minute oder Backup plus `vor-restore` überschreiben sich (MOVE ohne `Overwrite: F`).
**How to avoid:** Vor dem Upload `by_path` prüfen und `-2`, `-3` anhängen; unter dem globalen Ein-Job-Schutz ist das rennfrei. Zeit in der Haushalts-Zeitzone (Phase-4-Einstellung, Vorgabe Europe/Berlin).

### Pitfall 6: Erfolg gemeldet, obwohl der MOVE serverseitig noch lief
**What goes wrong:** Client-Timeout beim MOVE großer Dateien, Nextcloud setzt trotzdem zusammen; die Datei existiert, der Job sagt "fehlgeschlagen".
**How to avoid:** `npa_timeout_dav` großzügig (Vorschlag 600 s); im Fehlerfall das eigene Ziel löschen (eindeutiger Name, also sicher); ohne DB-Eintrag wird eine solche Datei ohnehin nie gelistet.

### Pitfall 7: Welt bleibt nach Fehler aus
**What goes wrong:** Exception zwischen Stopp und Neustart; D-11 verlangt Neustart.
**How to avoid:** Stopp und Neustart als `try/finally` um den Snapshot; Upload erst NACH dem Neustart. Neustart nur, wenn `desired_state == "running"` war.

### Pitfall 8: Docker-Strom bricht beim Iterieren ab
**What goes wrong:** Fehler beim Lesen des Generators sind rohe `requests`/`urllib3`-Ausnahmen außerhalb von `_guarded`.
**How to avoid:** Iterieren innerhalb `_guarded`; Teilergebnis verwerfen, kein zweiter Versuch.

### Pitfall 9: Talk-Bot meldet "Welt aus/an" bei jedem Backup
**What goes wrong:** `_track_run_state` beobachtet den Stopp im 15-s-Takt und legt Outbox-Zeilen `stop`/`start` an.
**How to avoid:** Busy-Welten im Takt überspringen (Pattern 7).

### Pitfall 10: Temp-Platz reicht nicht
**What goes wrong:** Restore braucht Download (gepackt) plus Restore-Tar plus Sicherheits-Snapshot gleichzeitig auf Platte; ENOSPC mitten im Ablauf.
**How to avoid:** `OSError` beim Schreiben auf festen Text abbilden ("Nicht genug freier Speicherplatz auf dem Server"); vor dem Stopp `shutil.disk_usage` gegen 3 x Sicherungsgröße prüfen (Restore) bzw. gegen die Volume-Größe aus der letzten Sicherung (Backup, sonst kein Vorab-Check).

## Code Examples

### Ablauf Backup (Skelett, Sperrabschnitte)
```python
# backup/service.py, Muster aus worlds/service.py (mutation(), anyio.to_thread)
async def run_backup(world_id: str, uid: str) -> None:
    spool = await anyio.to_thread.run_sync(_open_spool)
    try:
        was_running = await anyio.to_thread.run_sync(svc.begin_backup, world_id)   # Sperre: op_state, @halt, stop
        try:
            info = await anyio.to_thread.run_sync(svc.snapshot_into, world_id, spool)  # ohne Sperre, Welt steht
        finally:
            await anyio.to_thread.run_sync(svc.end_offline, world_id, was_running)   # Sperre: _launch, op_state=ready
        await upload_backup(uid, world_id, spool, info)    # async, Welt läuft schon wieder
        await anyio.to_thread.run_sync(svc.job_ok, world_id)
    except Exception as exc:
        await anyio.to_thread.run_sync(svc.job_failed, world_id, user_text(exc))    # nur fester Text, Typ ins Log
    finally:
        spool.close()
```

### Upload mit eindeutigem Namen und Nachweis
```python
# backup/files.py, Source: nc_py_api 0.30.3 files_async.py (upload_stream, by_path, delete)
async def upload_backup(uid: str, folder: str, base: str, spool: BinaryIO, size: int) -> FsNode:
    async with nc_as(uid, npa_timeout_dav=600, chunked_upload_v2=False) as nc:
        await nc.files.makedirs(f"Gameworld/Sicherungen/{folder}", exist_ok=True)
        target = await unique_path(nc, folder, base)            # by_path, dann -2, -3 ...
        spool.seek(0)
        try:
            await nc.files.upload_stream(target, spool, chunk_size=10 * 1024 * 1024)
            node = await nc.files.by_path(target)
            if node is None or node.info.size != size:
                raise BackupError(MSG_UPLOAD_INCOMPLETE)
            return node
        except BaseException:
            with contextlib.suppress(Exception):
                await nc.files.delete(target, not_fail=True)
            raise
```

### Restore-Tar normieren
```python
# backup/archive.py
RESTORE_DROP_FILES = {"world.mt"}
RESTORE_DROP_DIRS = {"worldmods", "mods", "game"}

def restore_allowed(relative: str, member: tarfile.TarInfo) -> bool:
    if not (member.isfile() or member.isdir()):
        raise RestoreRejected(MSG_BAD_ENTRY)          # Abbruch statt still überspringen
    head = relative.split("/", 1)[0]
    if head in RESTORE_DROP_DIRS or relative in RESTORE_DROP_FILES:
        return False
    if relative.endswith(".lua") or head.startswith("gameworld_"):
        return False
    return True
```

## Roundtrip-Test (Erfolgskriterium 3)

Zwei Ebenen, beide automatisiert, beide Teil der Phasenabnahme:

1. **pytest e2e** `tests/e2e/test_backup_restore_e2e.py` (Marker `docker`, echter Proxy, Files-Schicht durch eine lokale Ordner-Attrappe mit derselben Schnittstelle ersetzt):
   - Welt erstellen, laufen lassen; mit `luanti_probe.session(..., name="Mia", hold=5)` beitreten (legt Mia in `auth.sqlite`/`players.sqlite` an und erzeugt Kartenblöcke um den Spawn).
   - Backup auslösen, auf `ok` warten; aus der Attrappe das Archiv öffnen: Manifest, `world/map.sqlite` vorhanden, keine `gameworld_*`-Datei, kein `worldmods/`.
   - Zerstörung nach dem Backup: zweiter Spieler "Leo" tritt bei, danach Welt stoppen und per `put_archive` eine kaputte `map.sqlite` plus eine Datei `map.sqlite-journal` hineinlegen.
   - Restore der ersten Sicherung, auf `ok` und Status `running` warten (Status-Mod-Bereitschaft belegt, dass die Welt lädt).
   - Nachweis über ein **unabhängiges Muster** (Owner-Regel: Gegenprobe nie mit dem Muster der Umsetzung): Welt stoppen, über die Docker-CLI des Hosts (`docker cp`, nicht über den Provisioner) `players.sqlite`, `map.sqlite` holen und mit `sqlite3` prüfen: Mia vorhanden, Leo nicht; `PRAGMA integrity_check` = ok; Blockzahl wie im Snapshot; kein `map.sqlite-journal`; Zählbuch-Bytes identisch mit dem Stand vor dem Restore; `vor-restore`-Datei existiert und enthält Leo.
   - Negativtests: Sicherung mit `../`, mit Symlink, mit `worldmods/x/init.lua`, mit fremdem Manifest-Preset, mit verändertem SHA-256 (Datei in der Attrappe getauscht) werden abgelehnt, die Welt bleibt unverändert und läuft.
2. **Abnahmeskript** `scripts/dev/acceptance-phase5.sh` im Stil von `acceptance-phase4_1.sh` gegen den Dev-Stack mit echter Nextcloud 34.0.3: Auslösen per curl gegen den AppAPI-Proxy, Datei per WebDAV-PROPFIND/GET mit Admin-Zugang aus Files holen und entpacken, Probe-CLI für Mia/Leo, Prüfung mit `docker cp` plus Python-stdlib-`sqlite3` (kein `sqlite3`-CLI auf dem Host), Regression der Abnahmen 1 bis 4.1 am Ende.

Byte-Gleichheit von `map.sqlite` nach dem Neustart NICHT als Kriterium nehmen: Luanti schreibt beim Start/Stopp `env_meta.txt` und möglicherweise Blöcke [ASSUMED]; inhaltliche SQLite-Abfragen sind robust.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| CLAUDE.md-Idee: Kurzzeit-Hilfscontainer für den Backup-Lesezugriff | get_archive direkt am gestoppten Welt-Container | im Projekt seit Phase 4 belegt (Zählbuch-Lesen am gestoppten Container) | weniger Code, kein neues Container-Muster |
| nc_py_api Sync-API | `AsyncNextcloudApp`, Sync-Wrapper entfallen ab 0.30 | 0.30.0 | Files-Aufrufe async, Docker/Tar im Thread |
| Chunked Upload v2 als Vorgabe in nc_py_api | v1 erzwingen (`chunked_upload_v2=False`) | Empfehlung dieser Research | robuster gegen die 0-basierte Chunk-Nummerierung |

**Deprecated/outdated:** nichts in dieser Phase.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Chunked Upload v1 funktioniert auf allen unterstützten Nextcloud-Versionen inkl. Object Storage | Pattern 3 | Upload scheitert auf S3-Instanzen; Gegenmaßnahme: v2 als Schalter, Live-Test auf Dev-Stack |
| A2 | MOVE-Zusammensetzen großer Dateien bleibt unter 600 s | Pattern 3, Pitfall 6 | Falsche Fehlermeldung; Datei wird aufgeräumt, Backup muss wiederholt werden |
| A3 | Luanti lädt aus dem Weltordner nur `worldmods/` als Code (nicht `game/`, `mods/`) | Pattern 4 | Wir verwerfen ohnehin alle drei; Risiko nur, dass eine echte Spieldatei mit diesem Namen fehlt |
| A4 | Typische Kinderwelten: 5 MB bis 2 GB, gzip-Faktor 2 bis 4 (Dev-Stack: 5,6 MB map.sqlite, Volume 7,6 bis 110 MB inkl. Spiel) | Pitfall 10, Grenzen | Grenzwerte (8 GiB, 200 000 Einträge) zu knapp oder zu weit |
| A5 | AppAPI-/HaRP-Proxy bricht lange Requests nach rund einer Minute ab | Anti-Patterns | Ohne Bedeutung, weil ohnehin 202 plus Polling empfohlen |
| A6 | Luanti speichert bei SIGTERM innerhalb von 30 s vollständig | Pattern 1 | Harter Kill nach 30 s; Journal-Paar bleibt im Backup konsistent (Pitfall 1) |
| A7 | `users.get_user(uid).quota` enthält `free` in Bytes | Pattern 3 | Vorab-Check entfällt, 507-Abbildung bleibt |
| A8 | Nach Neustart ohne Spieler ändert Luanti `map.sqlite` evtl. trotzdem | Roundtrip-Test | Nur relevant, falls jemand Byte-Gleichheit prüfen will |
| A9 | Details der NC-Option "Windows-kompatible Dateinamen" (Punkt/Leerzeichen am Ende, reservierte Namen) | Pitfall 4 | Ordner anlegen scheitert; Ausweichname `Welt-<id6>` deckt es ab |

## Open Questions (RESOLVED)

Alle fünf Fragen wurden am 23.10.2026 vom Owner entschieden und sind als D-12 bis D-16 in 05-CONTEXT.md festgehalten.

1. **Sicherungen ohne DB-Eintrag (nach Neuinstallation der ExApp oder von Hand abgelegt)** , RESOLVED: D-12 (nicht als Sicherung listen)
   - What we know: Ohne Eintrag gibt es keinen Integritätsnachweis; Restore als neue Welt ist v2 (D-04).
   - What's unclear: Soll v1 solche Dateien zeigen (ohne Knopf) oder ganz verschweigen?
   - Recommendation: v1 zeigt sie nicht als Sicherung, höchstens "weitere Dateien im Ordner: N". Das Manifest im Archiv hält v2 offen. Owner kurz bestätigen lassen.
2. **Mehrere Verwalter** , RESOLVED: D-13 (jeder sieht nur eigene)
   - What we know: D-01 legt in die Files des auslösenden Verwalters; Verwalter = Nextcloud-Admins (mehrere möglich).
   - What's unclear: Sieht Verwalter B die Sicherungen von A?
   - Recommendation: v1 listet nur die eigenen (Abfrage als der anfragende Verwalter, Datenschutz, keine fremden Files lesen). Owner bestätigen.
3. **Ausfallzeit-Modell** , RESOLVED: D-14 (Neustart direkt nach Snapshot, Upload im Hintergrund)
   - What we know: Konsistenz braucht nur während `get_archive` eine stehende Welt.
   - Recommendation: Welt direkt nach dem Snapshot neu starten, Upload danach (Status "Wird gesichert ..." bleibt als Job-Anzeige bis zum Upload-Ende, Kinder sehen die Pause nur während der Ausfallzeit). Weicht leicht von der Lesart "Stopp, Backup, Neustart" in D-09 ab, ist aber für Kinder besser; im Plan als bewusste Auslegung kennzeichnen.
4. **Restore für Welten mit "Weltdaten fehlen" (delete-only)** , RESOLVED: D-15 (erlaubt, ohne Sicherheits-Backup)
   - Recommendation: erlauben, Sicherheits-Backup dann überspringen (es gibt keinen Stand). Starker Nutzen für den eigentlichen Notfall; Owner bestätigen.
5. **Abschlussmeldung über den Notify-Weg (optional)** , RESOLVED: D-16 (nur Fehler melden)
   - Recommendation: nur Fehlermeldungen als Benachrichtigung an den auslösenden Verwalter, wenn die Outbox-Art billig zu ergänzen ist; sonst weglassen, die Weltkarte zeigt das Ergebnis.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Engine + Dev-Stack | e2e, Abnahme | ✓ | gameworld-dev läuft (NC 34.0.3, Proxy v0.5.0, zwei Welt-Container) | , |
| tecnativa/docker-socket-proxy | get_archive/put_archive/volumes | ✓ | v0.5.0 (CONTAINERS, IMAGES, POST, VOLUMES = 1) | , |
| Python 3.13 + venv | Backend, Tests | ✓ | 3.13.13, nc_py_api 0.30.3, docker 7.2.0 | , |
| jq | Abnahmeskript | ✓ | WinGet jq | , |
| sqlite3-CLI | Abnahmeskript | ✗ | , | Python-stdlib `sqlite3` lesend (wie in Phase 4.1) |
| Nextcloud Files (WebDAV) des Admin-Kontos | Upload/Download | ✓ (Dev-NC) | 34.0.3 | , |

**Missing dependencies with no fallback:** keine.
**Missing dependencies with fallback:** sqlite3-CLI (stdlib).

## Validation Architecture

`workflow.nyquist_validation` ist in `.planning/config.json` auf `false`; der Abschnitt entfällt. Der Roundtrip-Test ist trotzdem Erfolgskriterium der Phase und oben beschrieben. Schnelllauf: `uv run pytest tests -q -m "not docker"`; voll: `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest tests -q` plus `sh scripts/dev/acceptance-phase5.sh`.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | nein (AppAPI erledigt) | , |
| V3 Session Management | nein | , |
| V4 Access Control | ja | `require_verwalter` an allen neuen Routen; Restore nur für Einträge mit `owner_uid == uid` und passender `world_id`; Files-Zugriff nur `nc_as(uid)` des anfragenden Verwalters |
| V5 Input Validation | ja | pydantic mit `extra="forbid"` für Bodies; `file_id` als int; Tar-Validierung (Pattern 4) mit Negativtests |
| V6 Cryptography | ja (Integrität) | `hashlib.sha256` (stdlib), nie selbst bauen |
| V12 Files and Resources | ja | Pfadfilter `_safe_relative`, nur Datei/Ordner, Größen- und Anzahlgrenzen, keine Symlinks |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Manipulierte Sicherung in Files (fremder Lua-Code in `worldmods/`, `world.mt` mit anderen Backends/Mods) | Tampering, Elevation | SHA-256 gegen DB-Eintrag; `worldmods/`, `.lua`, `world.mt`, `mods/`, `game/` verwerfen; `world.mt` aus Preset rendern |
| Path Traversal / Symlink im Tar | Tampering | `_safe_relative`, nur `isfile`/`isdir`, Abbruch statt Überspringen |
| Zip-/Tar-Bombe füllt die Platte | Denial of Service | Grenzen für entpackte Summe, Anzahl, Verhältnis; Temp unter Storage mit Platzprüfung |
| Ordnername `..` aus dem Weltnamen | Tampering | `naming.py` mit Ersatzname, Tests für `.`, `..`, Rand-Punkte |
| Sicherung einer anderen Welt einspielen (gleicher Ordner bei gleichem Namen) | Tampering | Zuordnung nur über DB-Eintrag (world_id, file_id), Manifest-Prüfung |
| Halbe Datei gilt als Sicherung | Repudiation/Integrity | Liste nur aus DB-Einträgen mit passender Größe; eigenes Ziel bei Fehler löschen |
| Zugangsdaten aus alter Sicherung wieder gültig | Elevation | D-06: Zugangsdatei frisch; der Zugangs-Mod lehnt Nicht-Eingeladene im Prejoin ab und setzt Verifier neu [VERIFIED: access_mod.py] |
| Pfade/Namen von Kindern in Logs | Information Disclosure | Nur Welt-ID, Fehlertyp, Größen loggen (Muster T-04.1-08) |
| Pause oder Einladungen während langer Jobs blockiert | Denial of Service | Kurze Sperrabschnitte, Busy-`op_state` |

Pflicht laut Owner-Regel für Gameworld: Deep Review und `/gsd-secure-phase 05` mit Negativtests vor Phasenabschluss.

## Sources

### Primary (HIGH confidence)
- Installierter Code `.venv/Lib/site-packages/nc_py_api` 0.30.3: `files/files_async.py` (upload_stream, download2stream, by_path, makedirs, delete), `_session.py` (RuntimeOptions: npa_timeout_dav, chunked_upload_v2; download2fp), `files/__init__.py` (FsNode-Felder)
- Installierter Code `.venv/Lib/site-packages/docker` 7.2.0: `api/container.py` (get_archive, put_archive), `constants.py` (DEFAULT_DATA_CHUNK_SIZE 2 MiB)
- Docker Engine API v1.47 OpenAPI (docs.docker.com/reference/api/engine/version/v1.47.yaml): ContainerArchive, PutContainerArchive (gzip/bzip2/xz akzeptiert)
- raw.githubusercontent.com/Tecnativa/docker-socket-proxy/v0.5.0/haproxy.cfg: Timeouts
- raw.githubusercontent.com/luanti-org/luanti/5.17.0/src/database/database-sqlite3.cpp: nur `synchronous` und `foreign_keys`, kein WAL
- raw.githubusercontent.com/luanti-org/luanti/5.17.0/builtin/settingtypes.txt: `kick_msg_shutdown` existiert (nicht empfohlen, conf wird nur beim Erzeugen geschrieben)
- Projektcode: provisioner/client.py, provisioner/archive.py, provisioner/spec.py, provisioner/time_mod.py, provisioner/access_mod.py, provisioner/luanti_conf.py, worlds/service.py, worlds/status.py, worlds/reconciler.py, worlds/store.py, events/parse.py, notify/loop.py, nc.py, api/worlds.py, api/me.py, appinfo/info.xml, tests/e2e/luanti_probe.py, scripts/dev/compose.yaml
- Dev-Stack: `docker cp <welt>:/var/lib/minetest/.minetest/worlds/world - | tar -tv`, `docker system df -v` (2026-10-23)

### Secondary (MEDIUM confidence)
- docs.nextcloud.com/server/latest/developer_manual/client_apis/WebDAV/chunking.html: v2 Chunk-Nummern 1 bis 10000, 5 MB bis 5 GB, OC-Total-Length/507, Ablauf nach 24 h
- docs.python.org/3/library/tarfile.html: Stream-Modus, compresslevel

### Tertiary (LOW confidence)
- github.com/cloud-py-api/nc_py_api/pull/324: 0-basierte v2-Chunk-Nummerierung als Fehlerquelle (Ausgang des PR nicht gesehen)
- help.nextcloud.com/t/enable-chunking-v2-for-object-storage-s3/187332: v2 braucht verteiltes Memcache, sonst Rückfall auf v1

## Metadata

**Confidence breakdown:**
- Standard Stack: HIGH, keine neuen Pakete, alle APIs im installierten Code gelesen
- Architecture: HIGH für Docker-Wege (im Projekt belegt), MEDIUM für die Sperr-/Statusintegration (Entwurf, folgt den vorhandenen Mustern)
- Pitfalls: HIGH für Journal/put_archive/Sperre/Boot-Abgleich (aus Code und Quelltext), MEDIUM für WebDAV-Verhalten unter Last

**Research date:** 2026-10-23
**Valid until:** 2026-11-22 (stabiler Stack, gepinnte Versionen)
