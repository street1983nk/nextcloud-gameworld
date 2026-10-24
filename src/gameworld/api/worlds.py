"""Welt-API: Auflisten, Erzeugen, Starten, Stoppen, Neustarten und Löschen.

Es gibt bewusst kein Feld für Sichtbarkeit (ZUGANG-01): unbekannte Felder wie
``public`` oder ``server_announce`` werden mit 422 abgelehnt.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, get_directory
from gameworld.access.roles import RolesDep, require_verwalter
from gameworld.access.secret import PlayerSecret, get_player_secret
from gameworld.access.service import AccessService, actor_of
from gameworld.config import load_settings
from gameworld.playtime.service import TimeService
from gameworld.provisioner.client import (
    DockerProvisioner,
    DockerUnavailableError,
    ProvisionerError,
    WorldNotFoundError,
)
from gameworld.provisioner.luanti_conf import normalize_world_name
from gameworld.provisioner.presets import DEFAULT_PRESET_ID, PRESETS, validate_preset_id
from gameworld.talk.service import get_talk_service
from gameworld.worlds.ports import NoFreePortError
from gameworld.worlds.service import NOT_FOUND, DeleteOnlyError, WorldBusyError, WorldService, WorldView
from gameworld.worlds.store import WorldStore

LOG = logging.getLogger(__name__)

# Jede Route dieses Routers ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

_service: WorldService | None = None
_service_lock = threading.Lock()


def get_service() -> WorldService:
    """Modulweites Singleton, beim ersten Aufruf aus der Umgebung gebaut.

    Eine ungültige Umgebung (ValueError aus load_settings) wird zu 503 mit der
    deutschen Meldung: Die Welt-Routen bleiben erreichbar und /api/setup-check
    meldet denselben Befund als Item "config" (WR-01).
    """
    global _service
    with _service_lock:
        if _service is None:
            try:
                settings = load_settings()
            except ValueError as exc:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
            store = WorldStore(settings.storage_dir / "gameworld.sqlite3")
            store.migrate()
            provisioner = DockerProvisioner(settings.docker_url, store.instance_id())
            _service = WorldService(store, provisioner, settings)
        return _service


ServiceDep = Annotated[WorldService, Depends(get_service)]


async def refresh_snapshot(
    service: ServiceDep,
    uid: Annotated[str, Depends(require_verwalter)],
    directory: Annotated[Directory, Depends(get_directory)],
) -> None:
    """Router-Abhängigkeit der Handy-Seiten: Verwalter-Schnappschuss mit dem geprüften Konto auffrischen (CR-01).

    Gedrosselt und nie blockierend wie beim Dashboard; ein Fehler erreicht die Seite nie.
    """
    try:
        await TimeService(service, directory).refresh_admins(uid, blocking=False)
    except Exception as exc:
        LOG.warning("Verwalter-Stand beim Seitenaufruf nicht aktualisiert: %s", type(exc).__name__)


class CreateWorldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Rohwert begrenzt, danach dieselbe Prüfung wie im Dienst (Key-Injection, Länge).
    name: Annotated[str, Field(max_length=200), AfterValidator(normalize_world_name)]
    # Nur IDs aus der Registry; conf-Zeilen kommen ausschließlich aus fest kodierten
    # Presets. Vorgabe = sicherstes Preset: hält den Phase-1-Vertrag ({"name"} allein)
    # für Skripte und UI kompatibel, das Dashboard wählt ab 02-04 sichtbar vor
    # (bewusste Abweichung von der RESEARCH-Empfehlung "Pflichtfeld").
    preset: Annotated[str, Field(max_length=64), AfterValidator(validate_preset_id)] = DEFAULT_PRESET_ID


class WindowDayOut(BaseModel):
    weekday: int
    open: bool
    window_start: int | None
    window_end: int | None


class BackupJobOut(BaseModel):
    """Letzter Sicherungs- oder Wiederherstellungsauftrag (D-11); nur in der Verwalter-Ansicht."""

    kind: str
    state: str
    message: str | None
    file_name: str | None
    finished_at: str | None


class WorldOut(BaseModel):
    id: str
    name: str
    port: int
    docker_status: str
    op_state: str
    desired_state: str
    last_error: str | None
    created_at: str
    preset: str
    preset_title: str
    # Status aus Docker (running, starting, stopped, error, unknown) und Elterntext.
    status: str
    status_text: str
    # WELT-03: Online-Spieler (nur bei status running) und RAM (nur bei laufendem Container).
    players: list[str]
    memory_used_bytes: int | None
    memory_limit_bytes: int | None
    # Weltdaten fehlen oder Erstellen brach ab: nur Löschen, Starten und Neustarten geben 409.
    delete_only: bool
    # Spielernamen der Eingeladenen, ohne Passwörter (die liefert nur /api/worlds/{id}/players).
    invited_players: list[str]
    # Läuft die Welt noch ohne geladenen Zugangsschutz? Dann braucht sie einen Neustart.
    access_restart_needed: bool
    # Läuft die Welt noch ohne geladenen Zeit-Mod? Dann braucht sie einen Neustart.
    time_restart_needed: bool
    # Läuft die Welt noch mit altem Zugangs-Mod (keine Ereignisdatei)? Dann kommen keine Hinweise.
    events_restart_needed: bool
    # Welt-Zeitfenster (ZEIT-05): sieben Wochentage oder null (immer offen).
    time_window: list[WindowDayOut] | None
    # Letzter Auftrag (Sicherung oder Wiederherstellung) oder null; Fehler bleiben nach Neuladen sichtbar.
    backup_job: BackupJobOut | None = None


class WorldListOut(BaseModel):
    worlds: list[WorldOut]


class PresetOut(BaseModel):
    """Nur Elterntexte; Hashes, Limits und conf-Zeilen bleiben intern."""

    id: str
    title: str
    description: str


class PresetListOut(BaseModel):
    presets: list[PresetOut]


@router.get("/presets")
async def list_presets() -> PresetListOut:
    return PresetListOut(
        presets=[
            PresetOut(id=preset.id, title=preset.title, description=preset.description) for preset in PRESETS.values()
        ]
    )


@router.get("/worlds")
async def list_worlds(
    service: ServiceDep,
    uid: Annotated[str, Depends(require_verwalter)],
    directory: Annotated[Directory, Depends(get_directory)],
    secret: Annotated[PlayerSecret, Depends(get_player_secret)],
    roles: RolesDep,
) -> WorldListOut:
    # Abgleich beim Verwalter-Besuch (T-03-26), gedrosselt auf einmal pro Minute.
    # Er darf die Weltenliste nie blockieren (T-03-33): Fehler nur als Warnung.
    # Im Namen eines Gruppen-Verwalters entfernt er nie wegen einer 404 (P-01).
    try:
        actor = actor_of(await roles.profile(uid))
        await AccessService(service.store, service, directory, secret).sync_all(actor)
    except Exception as exc:
        LOG.warning("Abgleich der Einladungen beim Verwalter-Besuch gescheitert: %s", type(exc).__name__)
    # Verwalter-Schnappschuss für die Freistellung (A4), gedrosselt und nie
    # blockierend (try_mutation); ein Fehler erreicht die Weltenliste nie (T-04-29).
    try:
        await TimeService(service, directory).refresh_admins(uid, blocking=False)
    except Exception as exc:
        LOG.warning("Verwalter-Stand beim Verwalter-Besuch nicht aktualisiert: %s", type(exc).__name__)
    views = await service.list_worlds()
    return WorldListOut(worlds=[WorldOut(**asdict(view)) for view in views])


@router.post("/worlds", status_code=status.HTTP_201_CREATED)
async def create_world(
    body: CreateWorldRequest, service: ServiceDep, uid: Annotated[str, Depends(require_verwalter)]
) -> WorldOut:
    # Seit 03-05 ohne Weltschlüssel: Zugang nur über eingeladene, provisionierte Konten.
    # Ungültige Namen weist schon das Pydantic-Modell ab (AfterValidator mit
    # normalize_world_name, 422 mit Detail-Liste); der Dienst sieht nur noch
    # normalisierte Namen, ein eigener ValueError-Zweig wäre toter Code.
    try:
        created = await service.create_world(body.name, body.preset)
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    except NoFreePortError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from None
    # Jede Welt bekommt einen Talk-Raum (D-16); der Request wartet nie auf Talk (D-20).
    _talk_hook(lambda: get_talk_service(service.store).schedule_ensure(created.id, uid))
    return _out(created)


# IDs erzeugt nur die App (uuid4().hex[:12]); alles andere ist 422 (T-01-17).
WorldId = Annotated[str, Path(pattern="^[0-9a-f]{12}$")]


def _http_error(exc: ProvisionerError) -> HTTPException:
    """Fehler des Lebenszyklus als HTTP-Antwort mit deutscher Meldung, ohne Stacktrace."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, DockerUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, (NoFreePortError, DeleteOnlyError, WorldBusyError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _out(view: WorldView) -> WorldOut:
    return WorldOut(**asdict(view))


@router.post("/worlds/{world_id}/start")
async def start_world(world_id: WorldId, service: ServiceDep) -> WorldOut:
    try:
        return _out(await service.start_world(world_id))
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/stop")
async def stop_world(world_id: WorldId, service: ServiceDep) -> WorldOut:
    try:
        return _out(await service.stop_world(world_id))
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/restart")
async def restart_world(world_id: WorldId, service: ServiceDep) -> WorldOut:
    try:
        return _out(await service.restart_world(world_id))
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.delete("/worlds/{world_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_world(
    world_id: WorldId, service: ServiceDep, uid: Annotated[str, Depends(require_verwalter)]
) -> Response:
    del uid  # nur Verwalter (zweite Sperre); Talk handelt als Raum-Owner oder erster Verwalter
    try:
        await service.delete_world(world_id)
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    # Raum mitlöschen (D-19); scheitert Talk, bleibt delete_pending für den Abgleich.
    _talk_hook(lambda: get_talk_service(service.store).schedule_delete(world_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _talk_hook(start: Callable[[], None]) -> None:
    """Startet einen Talk-Hook; ein Fehler dabei erreicht die Welt-Route nie (D-20)."""
    try:
        start()
    except Exception as exc:
        LOG.warning("Talk-Hook nicht gestartet: %s", type(exc).__name__)
