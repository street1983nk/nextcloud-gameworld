# Phase 5: Backup und Restore - Pattern Map

**Mapped:** 2026-10-23
**Files analyzed:** 32 (8 neu im Backend, 1 neue Vue-Komponente, 12 geänderte Dateien, 6 neue Tests, 5 erweiterte Tests)
**Analogs found:** 31 / 32 (einzige Lücke: Hintergrund-Job mit HTTP 202, dafür Mischanalog aus Talk-Hooks plus Welt-Saga)

Grundregel für den Planer: Fast jeder Baustein existiert schon. Neue Dateien kopieren die Muster unten wörtlich (Docstring-Stil auf Deutsch mit echten Umlauten, `from __future__ import annotations`, `LOG = logging.getLogger(__name__)`, nur Welt-ID und Fehlertyp ins Log, feste deutsche Meldungskonstanten `MSG_*`/`TEXT_*` am Modulkopf).

## File Classification

| Neue/geänderte Datei | Rolle | Datenfluss | Nächstes Analog | Qualität |
|---|---|---|---|---|
| `src/gameworld/backup/__init__.py` | Paket | , | `src/gameworld/notify/__init__.py` (1 Zeile Docstring) | exact |
| `src/gameworld/backup/archive.py` | utility (rein) | streaming transform (tar r\| nach w:gz) | `src/gameworld/provisioner/archive.py` | exact |
| `src/gameworld/backup/naming.py` | utility (rein) | transform | `src/gameworld/provisioner/luanti_conf.py` (`normalize_world_name`) | role-match |
| `src/gameworld/backup/files.py` | service (Adapter) | file-I/O über WebDAV | `src/gameworld/notify/service.py` + `src/gameworld/nc.py` | exact (Protocol + Singleton + `nc_as`) |
| `src/gameworld/backup/service.py` | service (Ablauf) | batch, Hintergrund-Task | `src/gameworld/worlds/service.py` (Sperre, `_launch`, Saga) + `src/gameworld/talk/service.py` (Task-Set) | role-match (kombiniert) |
| `src/gameworld/api/backups.py` | route | request-response (202 + Polling) | `src/gameworld/api/worlds.py` + `src/gameworld/api/pause.py` | exact |
| `frontend/src/components/BackupSection.vue` | component | request-response, Liste | `frontend/src/components/WorldWindowDialog.vue` + Löschdialog in `ParentView.vue` | exact |
| `src/gameworld/provisioner/client.py` (ändern) | provisioner | streaming (get_archive), file-I/O (put_archive) | eigene Methoden `read_time_ledger`/`_read_world_file`, `write_world_files`, `create_world_container` | exact |
| `src/gameworld/provisioner/time_mod.py` (ändern) | config-Renderer + Lua | event-driven (5-s-Nachladen) | eigene `@pause`-Zeile (`_pause_line`, Lua `paused`/`tick`) | exact |
| `src/gameworld/playtime/engine.py` (ändern) | service | transform | eigenes `_active_pause` + `_render_cached`-Schlüssel | exact |
| `src/gameworld/worlds/status.py` (ändern) | model (rein) | transform | eigenes `creating` -> `STARTING`/`TEXT_CREATING` | exact |
| `src/gameworld/worlds/reconciler.py` (ändern) | model (rein) | event-driven (Boot) | eigenes `MARK_INTERRUPTED` | exact |
| `src/gameworld/worlds/service.py` (ändern) | service | CRUD | eigene `_refuse_delete_only`, `_track_run_state`, `_pause_world`, `_apply` | exact |
| `src/gameworld/worlds/store.py` (ändern) | store | CRUD | `talk_rooms`-Tabelle + Methoden, `migrate()`, `delete_notify_data` | exact |
| `src/gameworld/nc.py` (ändern) | utility | request-response | eigenes `nc_as` | exact |
| `src/gameworld/api/me.py` (ändern) | route | request-response | eigenes `TEXT_WELT_PROBLEM` (AR-24) | exact |
| `src/gameworld/api/worlds.py` (ändern) | route | request-response | eigenes `WorldOut` | exact |
| `src/gameworld/main.py` (ändern) | config | , | eigenes `include_router`, `shutdown_talk` im Lifespan | exact |
| `frontend/src/api.js` (ändern) | utility | request-response | `setWorldWindow`/`clearWorldWindow`, `post`, `errorText` | exact |
| `frontend/src/views/ParentView.vue` (ändern) | view | Polling 5 s | eigenes `CHIP_VARIANT`, `actionsLocked`, `run`, Löschdialog | exact |
| `src/gameworld/notify/loop.py` + `texts.py` (optional, D-16) | service | pub-sub (Outbox) | `HANDLERS`-Tabelle, `_fixed`, `NcNotifier` | exact |
| `tests/test_backup_archive.py` | test | , | `tests/test_archive.py` | exact |
| `tests/test_backup_naming.py` | test | , | `tests/test_luanti_conf.py` | role-match |
| `tests/test_backup_service.py` | test | , | `tests/test_service_lifecycle.py` (`FakeProvisioner`) | exact |
| `tests/test_backups_api.py` | test | , | `tests/test_pause_api.py`, `tests/test_invites_api.py` | exact |
| `tests/e2e/test_backup_restore_e2e.py` | test (docker) | , | `tests/e2e/test_reconcile_e2e.py` + `tests/e2e/luanti_probe.py` | exact |
| `scripts/dev/acceptance-phase5.sh` | test (Abnahme) | , | `scripts/dev/acceptance-phase4_1.sh` | exact |
| Erweitern: `tests/test_reconciler.py`, `tests/test_status.py`, `tests/test_time_mod.py`, `tests/test_store.py`, `tests/test_nc.py`, `tests/test_my_worlds.py` | test | , | jeweils die Datei selbst | exact |
| `appinfo/info.xml` | config | , | KEINE Änderung nötig: `^/api/.*` mit `GET,POST,DELETE` steht schon auf ADMIN (Zeilen 108-110) | , |

## Pattern Assignments

### `src/gameworld/backup/archive.py` (utility, streaming transform)

**Analog:** `src/gameworld/provisioner/archive.py`

**Imports und Konstanten** (Zeilen 21-44): stdlib-only, Konstanten der Mods importieren statt Strings duplizieren.
```python
from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
from typing import BinaryIO, cast

from gameworld.provisioner import access_mod, status_mod, time_mod
from gameworld.provisioner.client import ProvisionerError

LUANTI_UID = 30000
ROOT_UID = 0
```
Ausschlussliste aus Konstanten bauen: `access_mod.ACCESS_FILE_NAME`, `access_mod.STATE_FILE_NAME`, `access_mod.EVENTS_FILE_NAME` (access_mod.py Zeilen 61-68), `time_mod.RULES_FILE_NAME`, `time_mod.LEDGER_FILE_NAME` (time_mod.py Zeilen 101-102). `status_mod` hat nur `PLAYERS_FILE` als Vollpfad (status_mod.py Zeile 46), den Basisnamen per `PLAYERS_FILE.rsplit("/", 1)[1]` ableiten oder in status_mod eine Konstante `PLAYERS_FILE_NAME` ergänzen (gleiches Muster wie access_mod).

**Pfadsicherheit wiederverwenden** (Zeilen 73-82), nie neu bauen:
```python
def _safe_relative(name: str) -> str | None:
    """Normalisierter relativer Pfad oder None, wenn er aus dem Ziel ausbrechen würde."""
    if not name or name.startswith(("/", "\\")) or "\\" in name or ":" in name:
        return None
    if ".." in name.split("/"):
        return None
    cleaned = normpath(name)
    if cleaned in (".", "") or cleaned.startswith("../"):
        return None
    return cleaned
```
Import aus fremdem Modul ist privat; Muster für den pyright-Kommentar steht in `time_mod.py` Zeile 94:
`from gameworld.provisioner.access_mod import _lua_string  # pyright: ignore[reportPrivateUsage]`. Besser: `_safe_relative` in `provisioner/archive.py` öffentlich als `safe_relative` exportieren (alter Name als Alias bleibt).

**TarInfo-Normierung** (Zeilen 109-136), für `normalized(member, name)` und Manifest:
```python
def _add_dir(tar: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.uid = info.gid = LUANTI_UID
    info.mode = 0o755
    info.mtime = FIXED_MTIME
    tar.addfile(info)

def _file_info(name: str, size: int, *, uid: int, mode: int, mtime: int = FIXED_MTIME) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.uid = info.gid = uid
    info.mode = mode
    info.size = size
    info.mtime = mtime
    return info
```
Für Restore: mtime aus dem Archiv übernehmen (`mtime=member.mtime`), uid 30000, 0644/0755, `uname`/`gname` leer.

**Spool-Datei und Aufräumen im Fehlerfall** (Zeilen 205-242): genau dieses try/except-BaseException-close-Muster für die Snapshot-Temp-Datei nehmen, aber `tempfile.TemporaryFile(dir=settings.storage_dir / "tmp")` statt `SpooledTemporaryFile` (RESEARCH Pattern 2).
```python
spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX_BYTES)  # noqa: SIM115
try:
    ...
    with tarfile.open(fileobj=cast(BinaryIO, spool), mode="w", format=tarfile.PAX_FORMAT) as tar:
        ...
    spool.seek(0)
except BaseException:
    spool.close()
    raise
```

**Fehlerabbildung bei Tar-/Dateisystemfehlern:** wie `worlds/service.py` `_payload` (Zeilen 574-576):
```python
except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
    LOG.warning("Weltdaten für Welt %s nicht vorbereitet: %r", row.id, exc)
    raise ProvisionerError(PAYLOAD_FAILED) from exc
```
Für Backup: eigene Fehlerklassen `BackupError(Exception)`, `RestoreRejected(BackupError)` mit festen Texten; ENOSPC (`OSError` mit `errno.ENOSPC`) auf "Nicht genug freier Speicherplatz auf dem Server" (RESEARCH Pitfall 10).

**Wichtig (Tar-Wurzel):** Docker liefert Snapshot-Einträge mit Präfix `world/` (RESEARCH Pattern 1). `put_archive` am Ziel `WORLD_PATH` erwartet dagegen Namen relativ zum Weltordner (so baut `build_world_files` Zeilen 152-172 seine Namen: `worldmods/...`, ohne Präfix). Das Restore-Tar muss deshalb entweder `world/` abschneiden oder nach `f"{DATA_DIR}/.minetest/worlds"` eingespielt werden. Der Plan muss das eindeutig festlegen und testen.

**Strom-Lesen eines Docker-Archivs** (client.py Zeilen 155-167, `_first_member_content`): Stream-Modus `"r|"` ist bereits Projektmuster.
```python
with tarfile.open(fileobj=io.BytesIO(raw), mode="r|") as tar:
    member = tar.next()
    if member is None or not member.isfile():
        return b"", False
    extracted = tar.extractfile(member)
```

---

### `src/gameworld/backup/naming.py` (utility, rein)

**Analog:** `src/gameworld/provisioner/luanti_conf.py` Zeilen 10-31 (feste Fehlertexte als Konstante, Regex am Modulkopf, rein und ohne I/O).
```python
MAX_NAME_LENGTH = 40
NAME_ERROR = (...)
_ALLOWED = re.compile(r"[\w .\-]+")
_WHITESPACE = re.compile(r"\s+")

def normalize_world_name(raw: str) -> str:
    if any(unicodedata.category(char).startswith("C") for char in raw):
        raise ValueError(NAME_ERROR)
    name = _WHITESPACE.sub(" ", raw.strip())
```
`_ALLOWED` erlaubt `.` (Pitfall 4): Ordnername aus Weltnamen ableiten, Punkte/Leerzeichen am Rand entfernen, `.`/`..`/leer und reservierte Namen (CON, NUL, COM1 ...) durch `Welt-<world_id[:6]>` ersetzen. Zeitstempel in Haushalts-Zeitzone: `TimeEngine.zone()` (engine.py Zeilen 132-134) bzw. `load_zone(store.get_meta("time_zone") or "")`.

---

### `src/gameworld/backup/files.py` (Adapter, file-I/O über WebDAV)

**Analog 1:** `src/gameworld/notify/service.py` (ganzes Modul, 57 Zeilen): Protocol plus echter Adapter plus modulweites Singleton, das Tests ersetzen. Genau dieses Muster ermöglicht die "Ordner-Attrappe" im e2e-Test.
```python
class Notifier(Protocol):
    async def notify(self, uid: str, subject: str, message: str, params: Params, link: str) -> bool:
        ...

class NcNotifier:
    async def notify(self, uid: str, subject: str, message: str, params: Params, link: str) -> bool:
        try:
            async with nc_as(uid) as nc:
                await nc.notifications.create(...)
        except NextcloudException as exc:
            if exc.status_code == 404:
                LOG.warning("... Status 404")
            ...
            return False

_notifier: Notifier | None = None

def get_notifier() -> Notifier:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _notifier
    if _notifier is None:
        _notifier = NcNotifier()
    return _notifier
```
Übertragen: `class BackupFiles(Protocol)` mit `ensure_folder`, `unique_path`, `upload`, `stat`, `listdir`, `download_to`, `delete_own`; `NcBackupFiles` nutzt `nc_as(uid, npa_timeout_dav=600, chunked_upload_v2=False)`; `_files`/`get_backup_files()`. `NextcloudException.status_code == 507` auf festen Text abbilden (RESEARCH Pattern 3), 404 bei `listdir` heißt leere Liste.

**Analog 2:** `src/gameworld/nc.py` Zeilen 50-59: jeder Aufruf ein eigener Client, Sessions immer schließen (WR-05).
```python
@asynccontextmanager
async def nc_as(uid: str) -> AsyncIterator[AsyncNextcloudApp]:
    """Client im Namen von ``uid``; schließt seine Sessions auch im Fehlerfall."""
    if not uid:
        raise ValueError(MSG_NO_USER)
    nc = AsyncNextcloudApp(user=uid)
    try:
        yield nc
    finally:
        await close_nc(nc)
```

---

### `src/gameworld/nc.py` (ändern)

Erweiterung `nc_as(uid: str, **options: object)` und Weitergabe an `AsyncNextcloudApp(user=uid, **options)`. Docstring-Zeile ergänzen (Timeout und Upload-v1 für Backups). Test-Fake `NcRecorder.__call__(**kwargs)` in `tests/conftest.py` Zeilen 133-145 nimmt schon beliebige Keyword-Argumente an und merkt `kwargs.get("user")`; dort zusätzlich die Optionen merken, damit `tests/test_nc.py` prüfen kann, dass Backup-Clients `npa_timeout_dav=600` und `chunked_upload_v2=False` bekommen und trotzdem geschlossen werden (`assert_closed`, Zeilen 161-167).

---

### `src/gameworld/backup/service.py` (service, Hintergrund-Ablauf)

**Analog A, Sperrabschnitte und Worker-Threads:** `src/gameworld/worlds/service.py`

Async-Fassade über `anyio.to_thread.run_sync` (Zeilen 232-242):
```python
async def start_world(self, world_id: str) -> WorldView:
    return await anyio.to_thread.run_sync(self._start_world_sync, world_id)
```
Kurze Sperre über die öffentliche `mutation()` (Zeilen 317-322), nie `_LOCK` direkt, nie verschachtelt (`_LOCK` ist nicht reentrant, Docstring `apply_pause_sync` Zeilen 496-498):
```python
def mutation(self) -> contextlib.AbstractContextManager[None]:
    """Dieselbe Sperre wie Welt-Mutationen, mit Cache-Verwurf (für den Zugangsdienst).
    Nur aus einem Worker-Thread betreten (anyio.to_thread), nie im Event-Loop.
    """
    return self._mutating()
```
Stopp mit No-op bei fehlendem Container (Zeilen 956-970) und Neustart über `stop` plus `_launch` (Zeilen 972-991, nie `container.restart`):
```python
with self._mutating():
    row = self._row(world_id)
    self._refuse_delete_only(row)
    self._store.update_world(world_id, desired_state="running")
    try:
        try:
            self._provisioner.stop(world_id)
        except WorldNotFoundError:
            LOG.info("Welt %s: Container fehlt, Neustart erzeugt ihn neu", world_id)
        self._launch(row)
    except ProvisionerError as exc:
        self._fail(world_id, exc)
        raise
    self._store.update_world(world_id, op_state="ready", last_error=None)
```
Für D-11 ("Welt startet IMMER wieder"): Stopp und Neustart als `try/finally` um den Snapshot; Neustart nur, wenn `desired_state == "running"` war (Pitfall 7).

Zählbuch vor dem Tausch verbuchen (Zeilen 293-315, `_book_ledger`) und Regeldatei-Cache verwerfen (Zeilen 380-390, `self._time.forget(world_id)`). `_book_ledger` ist privat: im WorldService eine öffentliche Methode ergänzen (Muster: `mutation()`/`push_time()` sind die öffentlichen Einstiege für andere Dienste).

Frische Welt über den Phase-1-Pfad (Zeilen 903-913 in `_create_world_sync` und 826-828 in `_launch`):
```python
self._provisioner.ensure_image()
with self._payload(row) as payload:
    self._provisioner.create_world_container(row.id, row.port, payload, reuse_volume=True)
```
Für Restore: `remove_world(world_id, keep_volume=False)` (client.py Zeilen 360-375), dann `create_world_container(..., reuse_volume=False)`, dann `put_world_archive`, dann `_launch(row)`. Achtung: `create_world_container` räumt bei `reuse_volume=False` im Fehlerfall das Volume selbst ab (client.py Zeilen 315-322).

Unerwartete Fehler auf festen Text abbilden, Typ nur ins Log (Zeilen 914-920):
```python
except Exception as exc:
    LOG.exception("Erzeugen von Welt %s scheiterte unerwartet", world_id)
    failure = ProvisionerError(CREATE_FAILED)
    ...
    raise failure from exc
```

**Analog B, Hintergrund-Tasks mit verfolgtem Set:** `src/gameworld/talk/service.py` Zeilen 359-401 und 415-419.
```python
def _spawn(self, what: str, world_id: str, work: Coroutine[Any, Any, None]) -> None:
    task = asyncio.get_running_loop().create_task(self._tracked(what, world_id, work))
    self._tasks.add(task)

async def _tracked(self, what: str, world_id: str, work: Coroutine[Any, Any, None]) -> None:
    try:
        await self._isolated(what, world_id, work)
    finally:
        current = asyncio.current_task()
        if current is not None:
            self._tasks.discard(current)

async def shutdown(self, grace_seconds: float = SHUTDOWN_SECONDS) -> int:
    pending = set(self._tasks)
    if not pending:
        return 0
    _done, still = await asyncio.wait(pending, timeout=grace_seconds)
    for task in still:
        task.cancel()
    ...
```
Plus `drain()` (Zeilen 382-385) für Tests. Modul-Singleton `get_backup_service(...)` und `shutdown_backups()` wie `get_talk_service`/`shutdown_talk` (Zeilen 404-419).

---

### `src/gameworld/api/backups.py` (route, request-response 202)

**Analog:** `src/gameworld/api/worlds.py` (Router, IDs, Fehlerabbildung) und `src/gameworld/api/pause.py` (eigener Router mit strengem Body).

Router mit Verwaltersperre routerweit (worlds.py Zeile 40, pause.py Zeile 31):
```python
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])
```
Welt-ID-Validierung (worlds.py Zeile 206), wiederverwenden per Import:
```python
WorldId = Annotated[str, Path(pattern="^[0-9a-f]{12}$")]
```
Strenger Body (pause.py Zeilen 36-46): `model_config = ConfigDict(extra="forbid", strict=True)`; `file_id` als echte Ganzzahl wie `_whole_number`; `confirm`/`confirm_disconnect` als `bool` (strict lehnt `"true"` ab).

Abhängigkeiten und UID (worlds.py Zeilen 67, 184-187; pause.py Zeile 71):
```python
ServiceDep = Annotated[WorldService, Depends(get_service)]
VerwalterDep = Annotated[str, Depends(require_verwalter)]

@router.post("/worlds", status_code=status.HTTP_201_CREATED)
async def create_world(body: CreateWorldRequest, service: ServiceDep, uid: Annotated[str, Depends(require_verwalter)]) -> WorldOut:
```
Neu: `@router.post("/worlds/{world_id}/backups", status_code=status.HTTP_202_ACCEPTED)`, `@router.get("/worlds/{world_id}/backups")`, `@router.post("/worlds/{world_id}/restore", status_code=status.HTTP_202_ACCEPTED)`.

Fehlerabbildung (worlds.py Zeilen 209-217), um eigene Busy-/Bestätigungsfehler (409) erweitern:
```python
def _http_error(exc: ProvisionerError) -> HTTPException:
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, DockerUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, (NoFreePortError, DeleteOnlyError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))
```
409 bei Spielern online ohne `confirm_disconnect`: Detail als Objekt `{players: N, message: ...}` ist neu; `frontend/src/api.js` `errorText` (Zeilen 47-57) liest nur `detail` als Text oder Liste. Entweder `detail` als Text lassen und die Zahl in einem eigenen Feld der GET-Liste liefern (Spielerzahl steht ohnehin in `WorldOut.players`), oder `errorText` erweitern. Empfehlung: Frontend fragt die Zahl aus `world.players.length` vor dem Dialog, Backend erzwingt mit 409 und Text.

Fire-and-forget-Hook, dessen Fehler die Route nie erreicht (worlds.py Zeilen 262-267):
```python
def _talk_hook(start: Callable[[], None]) -> None:
    try:
        start()
    except Exception as exc:
        LOG.warning("Talk-Hook nicht gestartet: %s", type(exc).__name__)
```

---

### `src/gameworld/provisioner/client.py` (ändern: Snapshot und Datei-Objekt-Einspielen)

**Analog:** eigene Methoden. Lesen am gestoppten Container (Zeilen 454-472 und 492-517):
```python
def _read_world_file(self, world_id: str, path: str, label: str, *, ...) -> StatusFile | None:
    container = self._owned(world_id)
    try:
        stream, stat = container.get_archive(path)
    except docker.errors.NotFound:
        return None
    try:
        content, truncated = _first_member_content(_read_capped(stream, archive_max), file_max)
    except (tarfile.TarError, EOFError) as exc:
        raise ProvisionerError(f"{label} ist nicht lesbar.") from exc
```
Für den Snapshot NICHT `self._read(...)` (zweiter Versuch, Zeilen 234-252) verwenden, sondern einen einzigen `with self._guarded():`-Block, in dem auch iteriert wird (RESEARCH Pattern 1, Pitfall 8). Container nur über `_owned` (Zeilen 263-283). Stream schließen wie `_read_capped` (Zeilen 148-152):
```python
finally:
    close = getattr(stream, "close", None)
    if callable(close):
        close()
```
Zustandsprüfung vor dem Lesen: `container.reload()` und `container.status == "running"` -> `ProvisionerError` (Erfolgskriterium 2).

Einspielen mit Datei-Objekt: Muster `create_world_container` (Zeilen 308-314, `container.put_archive(DATA_DIR, payload.archive)` mit BinaryIO) plus `write_world_files` (Zeilen 342-353, Ziel `WORLD_PATH`, deutscher Fehlertext bei `False`):
```python
with self._guarded():
    container = self._owned(world_id)
    if not container.put_archive(WORLD_PATH, archive):
        raise ProvisionerError("Docker hat die Zugangsliste der Welt nicht angenommen.")
```
Neue Methode `put_world_archive(world_id, archive: BinaryIO)` mit eigenem Text ("Docker hat die Sicherung nicht angenommen."). `FakeProvisioner` in `tests/test_service_lifecycle.py` (Zeilen 50-184) um `snapshot_to`/`put_world_archive` ergänzen (Felder als `field(default_factory=...)` wie `written`, Zeile 77).

---

### `src/gameworld/provisioner/time_mod.py` (ändern: `@halt`)

**Analog:** die `@pause`-Zeile im selben Modul.

Python-Seite: Dataclass wie `PauseLine` (Zeilen 661-667), Render-Prüfung wie `_pause_line` (Zeilen 731-738), Einhängen in `render_time_file` (Zeilen 770-818) als Keyword-Argument mit Vorgabe `None` (Bytes ohne `@halt` bleiben identisch, Test `test_rules_file_without_pause_is_unchanged` in `tests/test_time_mod.py` Zeilen 477-481 als Vorlage):
```python
def _pause_line(pause: PauseLine) -> str:
    if not isinstance(pause.art, str) or pause.art not in PAUSE_ARTS:
        raise ValueError("Ungültige Pause in der Regeldatei: Art pause oder schluss.")
    if not (_is_int(pause.ab) and _is_int(pause.bis)):
        raise ValueError("Ungültige Pause in der Regeldatei: nur ganze Zahlen.")
    if pause.ab < 0 or pause.bis <= pause.ab:
        raise ValueError("Ungültige Pause in der Regeldatei: nie negativ, Ende nach dem Beginn.")
    return f"@pause {pause.ab} {pause.bis} {pause.art}"
```
Kindertexte als Konstanten plus Aufnahme in `TEXTS` (Zeilen 143-169) und als Lua-Escape (Zeilen 295-298):
```python
TEXT_PAUSE = "Kurze Pause! Deine Eltern brauchen dich gerade. Danach kannst du weiterspielen."
...
local PAUSE_TEXT = {_lua_string(TEXT_PAUSE)}
```
Neu: `TEXT_HALT_SOON = "Die Welt macht gleich eine kurze Pause."`, `TEXT_HALT = "Die Welt macht kurz Pause. Gleich geht es weiter."`.

Lua-Seite: Parser-Zweig wie `@pause` (Zeilen 367 und 390-395), Zustand `halt` neben `pause` (Zeile 314), Zuweisung am Ende von `load()` (Zeile 418). Durchsetzung wie Pause in Prejoin (Zeilen 562-567) und `tick` (Zeilen 589-597):
```lua
local p = paused(name)
if p and now() >= pause.ab then
  core.disconnect_player(name, pause_text(name))
else
  if p and pause_warned[name] ~= pause.ab then
    pause_warned[name] = pause.ab
    core.chat_send_player(name, PAUSE_SOON)
  end
```
Für `@halt` einmal `core.chat_send_all(...)` je `ab` (RESEARCH Pattern 6). Achtung f-String: geschweifte Klammern im Lua-Code verdoppeln (`{{ }}`), Quelle bleibt ASCII.

---

### `src/gameworld/playtime/engine.py` (ändern: flüchtiger Halt je Welt)

**Analog:** `_active_pause` (Zeilen 136-147) und `_render_cached` (Zeilen 279-302). Der Halt muss in den Cache-Schlüssel, sonst schreibt `push_time` ihn nie (Kommentar Zeile 289: "Pause und Morgen-Minuten gehören in den Schlüssel, sonst schreibt der Takt die Pause nie."):
```python
key = (
    *self._body_key(world_line, players, days),
    pause,
    None if morgen is None else tuple(sorted(morgen.items())),
)
```
Halt nur im Speicher (`self._halts: dict[str, int]` neben `self._cache`, Zeile 119), Setzen/Löschen über öffentliche Methoden, gerendert in `render` (Zeilen 183-241) und an `render_time_file(..., halt=...)` übergeben. `forget()` (Zeilen 243-250) bleibt unverändert.

---

### `src/gameworld/worlds/status.py` (ändern)

**Analog:** `creating`-Zweig (Zeilen 96-101) und Code-Konstanten (Zeilen 19-37):
```python
RUNNING = "running"
STARTING = "starting"
...
TEXT_CREATING = "Wird erstellt"

if not reachable:
    return WorldStatus(UNKNOWN, TEXT_UNREACHABLE)
if op_state == "creating":
    return WorldStatus(STARTING, TEXT_CREATING)
```
Neu: `BACKING_UP = "backing_up"`, `RESTORING = "restoring"`, `TEXT_BACKING_UP = "Wird gesichert ..."`, `TEXT_RESTORING = "Wird wiederhergestellt ..."`; Zweige direkt nach `reachable`, vor `creating`. `restoring_swap` zeigt ebenfalls `RESTORING`. Docstring Zeilen 1-8 ("Die Datenbank liefert nur die Operationszustände creating und failed") anpassen. Test-Vorlage: `tests/test_status.py`.

---

### `src/gameworld/worlds/reconciler.py` (ändern)

**Analog:** `MARK_INTERRUPTED` (Zeilen 49-57, 65-71), Regeltabelle im Docstring (Zeilen 3-16) um drei Zeilen erweitern.
```python
class ReconcileAction(StrEnum):
    ...
    MARK_INTERRUPTED = "mark_interrupted"

def decide_boot(row: WorldRow, container: ContainerInfo | None, volume_exists: bool) -> ReconcileAction:
    if row.desired_state == "deleted":
        return ReconcileAction.RETRY_DELETE
    if row.op_state == "creating":
        return ReconcileAction.MARK_INTERRUPTED
```
Neu: `restoring_swap` -> `MARK_RESTORE_INTERRUPTED` (vor jeder Volume-Logik). `backing_up`/`restoring` -> neue Aktion `CLEAR_BUSY` (op_state `ready`, danach normale Regeln; alternativ im Dienst vor `decide_boot` zurücksetzen). `needs_volume_check` (Zeilen 60-62) und `decide_periodic` (Zeilen 85-94) bekommen die Busy-Menge in `row.op_state not in {...}`. Eine gemeinsame Konstante `BUSY_OP_STATES = frozenset({"backing_up", "restoring", "restoring_swap"})` hier definieren und überall importieren. Test-Vorlage: `BOOT_TABLE` in `tests/test_reconciler.py` Zeilen 65-70 (`pytest.param(..., id=...)`).

---

### `src/gameworld/worlds/service.py` (ändern: Guards, Ansicht, Abgleich)

- **Guard:** wie `_refuse_delete_only` (Zeilen 872-876) eine statische `_refuse_busy(row)` mit eigener `WorldBusyError(ProvisionerError)` (Muster `DeleteOnlyError`, Zeilen 110-111) und Aufruf in `_start_world_sync` (Zeile 946), `_restart_world_sync` (Zeile 979), `_stop_world_sync` (Zeile 958) und `_delete_world_sync` (Zeile 1076). In `api/worlds.py` `_http_error` auf 409 abbilden.
  ```python
  @staticmethod
  def _refuse_delete_only(row: WorldRow) -> None:
      if delete_only(row):
          raise DeleteOnlyError(row.last_error or RECONCILE_DATA_MISSING)
  ```
- **Neue Meldung** `RESTORE_INTERRUPTED` neben `RECONCILE_INTERRUPTED` (Zeilen 88-92), ausdrücklich NICHT in `DELETE_ONLY_ERRORS` (Zeile 101).
- **`_pause_world`** (Zeilen 531-555): Neustart-Zweig für Busy-Welten überspringen, `push_time` bleibt.
- **`_track_run_state`** (Zeilen 424-440): wie `desired_state == "deleted"` (Zeile 431) Busy-Welten mit `continue` überspringen (Pitfall 9).
- **`_apply`** (Zeilen 1035-1056): neue `case`-Zweige wie `MARK_INTERRUPTED`:
  ```python
  case ReconcileAction.MARK_INTERRUPTED:
      self._store.update_world(row.id, op_state="failed", last_error=RECONCILE_INTERRUPTED)
  ```
- **`WorldView`** (Zeilen 119-149): neues Feld `backup_job` NACH `time_window` mit Vorgabe `None` (Dataclass-Reihenfolge), in `_view` (Zeilen 152-196) befüllen und in `_copy` (Zeilen 199-206) mitkopieren, falls veränderlich. `_collect`/`_view_from_docker` (Zeilen 617-646, 757-781) liefern es für beide Zweige (auch "Docker nicht erreichbar").
- **`_status_file`** (Zeilen 648-663) liest nur bei `op_state not in {"creating", "failed"}`; Busy-Zustände ergänzen, damit kein Statuslesen während des Tauschs.
- **Löschen** (Zeilen 1085-1092): Backup-Zeilen bleiben bei Welt-Löschung erhalten (D-08, Dateien liegen in Files) oder werden explizit gelöscht; Entscheidung im Plan festhalten, Muster `delete_notify_data`.

---

### `src/gameworld/worlds/store.py` (ändern: Schema 7)

**Analog:** `talk_rooms` (Tabelle Zeilen 171-178, Dataclass Zeilen 297-306, Methoden Zeilen 1151-1200).
```python
SCHEMA_VERSION = "6"   # -> "7"

CREATE TABLE IF NOT EXISTS talk_rooms (
  world_id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  owner_uid TEXT NOT NULL,
  read_only INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'ok'
);
```
Neue Tabellen `backups` (file_id INTEGER, owner_uid, world_id, path, name, size, sha256, preset, kind, created_at; Index/PK auf (owner_uid, file_id)) und `backup_jobs` (world_id PK, kind, state, message, file_name, started_at, finished_at). Da die Tabellen per `CREATE TABLE IF NOT EXISTS` im `SCHEMA`-Skript stehen, braucht `migrate()` (Zeilen 333-357) keine ALTER-Zeile; nur `SCHEMA_VERSION` anheben und eine Konstante `BACKUP_TABLES = frozenset({...})` wie `NOTIFY_TABLES` (Zeilen 184-198) für den Migrationstest. Dataclass `BackupRow` frozen wie `TalkRoomRow`, Zeilenumwandler wie `_talk_row` (Zeilen 1192-1200). Verbindungen immer über `with self._connect() as connection:` (Zeilen 324-331). Event-Cursor-Reset als eigene Methode (`DELETE FROM event_cursor WHERE world_id = ?`, Muster `delete_notify_data` Zeilen 1093-1107). `owner_uid` ist kein Kinderkonto, also nicht in `ACCOUNT_TABLES` (Zeilen 222-232); im Kommentar dort begründen wie bei `talk_rooms.owner_uid`.

---

### `src/gameworld/api/me.py` (ändern: Kindertext)

**Analog:** AR-24-Muster Zeilen 35-39 und 152-154:
```python
TEXT_WELT_PROBLEM = "Diese Welt hat gerade ein Problem. Sag deinen Eltern Bescheid."
...
status_text = TEXT_WELT_PROBLEM if view.op_state == "failed" else view.status_text
```
Neu: `TEXT_WELT_PAUSE = "Die Welt macht kurz Pause"` für `view.status in {BACKING_UP, RESTORING}`; Kinder sehen nie `backup_job` oder Dateinamen. Test-Vorlage: `tests/test_my_worlds.py`.

---

### `src/gameworld/api/worlds.py` (ändern)

`WorldOut` (Zeilen 104-133) um `backup_job: BackupJobOut | None = None` ergänzen; `_out` arbeitet mit `WorldOut(**asdict(view))` (Zeilen 220-221), deshalb muss das Feld in `WorldView` und `WorldOut` gleich heißen und `BackupJobOut` ein Pydantic-Modell sein, in das das `asdict`-Ergebnis passt (Muster `WindowDayOut`, Zeilen 97-101, für `time_window`). `_http_error` um `WorldBusyError` -> 409 erweitern.

---

### `src/gameworld/main.py` (ändern)

Router einhängen wie Zeilen 103-111 (`APP.include_router(backups.router)`), Import in Zeile 18 alphabetisch. Beim Beenden offene Backup-Tasks wie `shutdown_talk` (Zeilen 86-93) abbrechen:
```python
try:
    cancelled = await shutdown_talk()
except Exception as exc:
    LOG.warning("Talk-Hooks beim Beenden nicht abgeschlossen: %s", type(exc).__name__)
else:
    if cancelled:
        LOG.info("Beim Beenden %d offene Talk-Hooks abgebrochen", cancelled)
```

---

### `frontend/src/components/BackupSection.vue` (component)

**Analog 1:** `frontend/src/components/WorldWindowDialog.vue` (ganzes Modul): Props `world` (nur `{ id, name }` kopiert), `emit('saved'|'close')`, `saving`/`error`-Refs, `NcNoteCard type="error"` für Fehler, Knopf mit `NcLoadingIcon` im `#icon`-Slot, `<style scoped>` mit `var(--color-text-maxcontrast)`.
```vue
<NcButton variant="primary" :disabled="saving || invalid || noOpenDay" @click="submit(false)">
	<template v-if="saving" #icon>
		<NcLoadingIcon :size="20" />
	</template>
	Speichern
</NcButton>
```
```js
async function submit(alwaysOpen) {
	if (saving.value || ...) { return }
	saving.value = true
	error.value = ''
	try {
		const result = await setWorldWindow(props.world.id, ...)
		emit('saved')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
```
**Analog 2:** Bestätigungsdialog in `ParentView.vue` Zeilen 190-196 und 338-368 (`NcDialog` mit `:message` als `computed` und `:buttons`-Array, `callback` setzt den Zustand vor `run(...)` zurück). Für D-09 die Warnung "In der Welt spielen gerade N Kinder, sie werden kurz getrennt" genauso als `computed`-Nachricht; für D-04 die Sicherheitsabfrage beim Restore.

Größenformat: `formatBytes` aus `ParentView.vue` Zeilen 421-428 nach `frontend/src/playtime.js` oder eine kleine Hilfsdatei verschieben und in beiden importieren (nicht duplizieren). Kein `v-html`; Dateinamen nur per Textinterpolation (Kommentar-Muster Zeilen 402 und 412).

---

### `frontend/src/api.js` (ändern)

**Analog:** Zeilen 212-221:
```js
export async function setWorldWindow(worldId, days) {
	const response = await post(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`, { days })
	return response.data
}
```
Neu: `listBackups(worldId)` (axios.get), `startBackup(worldId, confirmDisconnect)`, `restoreBackup(worldId, fileId, confirmDisconnect)`. Änderungen immer über `post` (JSON-Pflicht IN-08, Zeilen 31-39).

---

### `frontend/src/views/ParentView.vue` (ändern)

- `CHIP_VARIANT` (Zeilen 277-283) um `backing_up: 'warning'`, `restoring: 'warning'` ergänzen.
- `actionsLocked` (Zeilen 443-446) zusätzlich bei `backing_up`/`restoring` sperren; auch Löschen-Knopf (Zeilen 179-184) sperrt heute nur über `busy[world.id]`, dort die Busy-Status ergänzen (D-10).
- `isActive` (Zeilen 439-441) entscheidet Stoppen/Neustarten vs. Starten; Busy-Status gesondert behandeln.
- Einstieg "Sichern" in der Aktionsspalte (Zeilen 168-178, gleicher `!world.delete_only`-Block, aber Restore muss laut D-15 auch bei `delete_only` erreichbar sein) und Dialog-Öffnen wie `openWindow` (Zeilen 383-387: andere Dialoge schließen, nur `{ id, name }` übergeben).
- Job-Fehler (D-11) aus `world.backup_job` als `NcNoteCard type="error"` in der Statusspalte wie die Neustart-Hinweise (Zeilen 119-130).
- Polling bleibt unverändert (5 s, `schedule`, Zeilen 543-566); kein eigener Job-Poll.

---

### `src/gameworld/notify/loop.py` + `texts.py` (optional, D-16 nur Fehler)

**Analog:** `HANDLERS`-Tabelle (loop.py Zeilen 321-331) und Zustellung `_deliver` (Zeilen 172-179) bzw. direkt `get_notifier().notify(uid, ...)` aus `notify/service.py`. Texte als Konstanten in `notify/texts.py` (Zeilen 17-23, Muster `ATTEMPT_SUBJECT`/`ATTEMPT_MESSAGE`). Outbox-Zeile im Fehlerpfad mit `store.add_outbox(world_id, kind, "", now, detail)` (store.py Zeile 910). Wenn ein neuer Handler mehr als eine Handvoll Zeilen kostet: weglassen (Discretion-Zeile), Weltkarte zeigt den Fehler.

---

### Tests

**`tests/test_backup_archive.py`** , Analog `tests/test_archive.py` Zeilen 1-80: Hilfen `_members`/`_read` öffnen Tars mit `mode="r:"` und schließen im `finally`; kleine In-Memory-Tars als Eingabe (Muster `_test_game` mit `"../ausbruch.txt"`, Zeile 60, für Negativtests `../`, Symlink, Hardlink, `worldmods/x/init.lua`, `.lua`, `world.mt`, `game/`, fehlende `map.sqlite`, Zip-Bombe-Verhältnis, Manifest fremder Welt/Preset).

**`tests/test_backup_service.py`** , Analog `tests/test_service_lifecycle.py`: `FakeProvisioner` (Zeilen 50-184) erweitern (`snapshots: dict[str, bytes]`, `put_archives: list[...]`, `snapshot_error`), Reihenfolge über `calls` prüfen ("stop:<id>", "start:<id>"), Fehlerinjektion über `*_errors`-Listen. Nebenläufigkeitstest (Pitfall 3): während eines künstlich blockierten Uploads muss `apply_pause_sync` sofort durchlaufen. Fake für `BackupFiles` wie `FakeNotifier` (conftest.py Zeilen 296-314) und per `monkeypatch.setattr(files_module, "_files", FakeFiles())` in `app_env` (conftest.py Zeilen 101-106) setzen.

**`tests/test_backups_api.py`** , Analog `tests/test_pause_api.py`/`tests/test_invites_api.py`: `appapi_headers(user)` (conftest.py Zeilen 66-74), Fixture `app_env`; Negativtests: Nicht-Verwalter 403, fremde `file_id` 404, Body mit Zusatzfeld 422, `"1"` statt `1` 422, Spieler online ohne Bestätigung 409, Busy 409.

**`tests/e2e/test_backup_restore_e2e.py`** , Analog `tests/e2e/test_reconcile_e2e.py` Zeilen 1-70: `pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]`, eigener `docker.DockerClient` aus `docker_url()` für die unabhängige Gegenprobe (Owner-Regel: nie das Muster der Umsetzung), `fresh_service()` für Absturz-Simulation (Boot-Abgleich nach `restoring_swap`). Spielstand per `tests/e2e/luanti_probe.py` `session(..., name="Mia", hold=5)`.

**`scripts/dev/acceptance-phase5.sh`** , Analog `scripts/dev/acceptance-phase4_1.sh` Kopf (Zeilen 1-60): `set -eu`, `SCRIPT_DIR`/`REPO_ROOT`/`COMPOSE_FILE`, Dev-Konten, `trap`-Aufräumen, Belege nur aus docker-CLI, curl gegen AppAPI-Proxy und WebDAV, jq, Python-stdlib-`sqlite3` lesend; Regression der Vorphasen am Ende.

**Erweitern:** `tests/test_time_mod.py` (Zeilen 440-502: Texte in `TEXTS` und als `_lua_string` in `MOD_INIT_LUA`, Zeilenreihenfolge, Bytes ohne `@halt` unverändert, Textverbot für Gedankenstriche Zeile 466), `tests/test_reconciler.py` (`BOOT_TABLE`), `tests/test_status.py`, `tests/test_store.py` (Schema 7, `BACKUP_TABLES`), `tests/test_nc.py` (Optionen, `assert_closed`), `tests/test_my_worlds.py` (Kindertext Pause).

## Shared Patterns

### Verwaltersperre
**Quelle:** `src/gameworld/api/worlds.py` Zeile 40, `src/gameworld/api/pause.py` Zeile 31
**Anwenden auf:** `api/backups.py` (alle Routen)
```python
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])
```
UID nur aus `Depends(require_verwalter)`, nie aus dem Body. Restore nur für DB-Einträge mit `owner_uid == uid` und passender `world_id` (D-13).

### Docker-Fehler kapseln
**Quelle:** `src/gameworld/provisioner/client.py` Zeilen 205-232 (`_guarded`)
**Anwenden auf:** alle neuen Provisioner-Methoden. Lesende Metadaten-Aufrufe über `_read` (einmal wiederholen), Strom-Lesen und Mutationen nur über `_guarded` (nie wiederholen).

### Kurze Sperre, lange Arbeit ohne Sperre
**Quelle:** `src/gameworld/worlds/service.py` Zeilen 317-339 (`mutation`, `try_mutation`) und 604-612 (`_mutating`)
**Anwenden auf:** `backup/service.py`. Nur Status setzen plus Stopp und Tausch plus Start unter Sperre; Snapshot, Upload, Download, Validierung ohne Sperre, abgesichert durch persistierten Busy-`op_state`. Takt und Abgleiche nehmen `try_mutation`/`_LOCK.acquire(blocking=False)` und überspringen dann (Zeilen 452-454, 995-997).

### Feste deutsche Fehlertexte, Typ nur ins Log
**Quelle:** `src/gameworld/worlds/service.py` Zeilen 78-101; `src/gameworld/notify/service.py` Zeilen 37-45; `src/gameworld/lifecycle.py` Zeilen 47-50
**Anwenden auf:** alle neuen Module
```python
except Exception as exc:
    LOG.warning("Benachrichtigung gescheitert: %s", type(exc).__name__)
```
Nie Dateinamen, Spielernamen, Pfade aus Files oder Inhalte ins Log (T-04.1-08); nur Welt-ID, Fehlertyp, Größen.

### Nextcloud-Clients immer schließen
**Quelle:** `src/gameworld/nc.py` Zeilen 36-69
**Anwenden auf:** `backup/files.py`. Je Vorgang `async with nc_as(uid, ...) as nc:`, kein geteilter Client, kein `set_user`.

### Kindgerechte Status-Texte
**Quelle:** `src/gameworld/api/me.py` Zeilen 35-39 und 152-154
**Anwenden auf:** `/api/my/worlds` für `backing_up`/`restoring`.

### Polling statt Job-Endpunkt
**Quelle:** `frontend/src/views/ParentView.vue` Zeilen 284, 448-472, 543-566; `src/gameworld/worlds/service.py` Zeilen 74-77 (Listen-Cache 2 s, jede Mutation verwirft ihn)
**Anwenden auf:** Job-Status in `WorldView.backup_job`. Jede Job-Zustandsänderung muss den Cache verwerfen (`_invalidate_cache` über `mutation()` oder eine öffentliche Methode).

### Singleton plus Fake für Tests
**Quelle:** `src/gameworld/notify/service.py` Zeilen 49-57; `tests/conftest.py` Zeilen 77-122 (`app_env` setzt alle Singletons zurück)
**Anwenden auf:** `backup/files.py` (`_files`) und `backup/service.py` (Job-Dienst); in `app_env` zurücksetzen.

## No Analog Found

| Datei/Teil | Rolle | Datenfluss | Grund |
|---|---|---|---|
| HTTP 202 plus Hintergrund-Job mit persistiertem Job-Zustand (`backup/service.py`, Job-Teil) | service | batch | Bisher gibt es nur kurze Talk-Hooks ohne persistierten Zustand. Kombination aus `talk/service.py` (Task-Set, Shutdown) und `worlds/store.py` (`talk_rooms`-Zustandsspalte) plus RESEARCH "Code Examples: Ablauf Backup" verwenden. |
| Chunked Upload/Streaming-Download nach Files | Adapter | file-I/O | Files-API wird im Projekt zum ersten Mal genutzt; Aufrufe nach RESEARCH Pattern 3 (`upload_stream`, `by_path`, `download2stream`, `delete(not_fail=True)`), Rahmen aus `notify/service.py`. |

## Metadata

**Analog search scope:** `src/gameworld/**` (provisioner, worlds, api, notify, talk, playtime, nc.py, main.py, config.py), `frontend/src/**`, `tests/**`, `scripts/dev/**`, `appinfo/info.xml`
**Files scanned:** 34 gelesen (davon 8 vollständig), Dateiliste von rund 200 Dateien gesichtet
**Pattern extraction date:** 2026-10-23
