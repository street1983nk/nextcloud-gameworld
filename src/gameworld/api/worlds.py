"""Welt-API: Auflisten, Erzeugen, Starten, Stoppen und Löschen.

Es gibt bewusst kein Feld für Sichtbarkeit (ZUGANG-01): unbekannte Felder wie
``public`` oder ``server_announce`` werden mit 422 abgelehnt.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.config import load_settings
from gameworld.provisioner.client import (
    DockerProvisioner,
    DockerUnavailableError,
    ProvisionerError,
    WorldNotFoundError,
)
from gameworld.provisioner.luanti_conf import normalize_world_name
from gameworld.worlds.ports import NoFreePortError
from gameworld.worlds.service import NOT_FOUND, WorldService, WorldView
from gameworld.worlds.store import WorldStore

router = APIRouter(prefix="/api")

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


class CreateWorldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Rohwert begrenzt, danach dieselbe Prüfung wie im Dienst (Key-Injection, Länge).
    name: Annotated[str, Field(max_length=200), AfterValidator(normalize_world_name)]


class WorldOut(BaseModel):
    id: str
    name: str
    port: int
    docker_status: str
    op_state: str
    desired_state: str
    last_error: str | None
    created_at: str


class CreatedWorldOut(WorldOut):
    world_key: str


class WorldListOut(BaseModel):
    worlds: list[WorldOut]


@router.get("/worlds")
async def list_worlds(service: ServiceDep) -> WorldListOut:
    views = await service.list_worlds()
    return WorldListOut(worlds=[WorldOut(**asdict(view)) for view in views])


@router.post("/worlds", status_code=status.HTTP_201_CREATED)
async def create_world(body: CreateWorldRequest, service: ServiceDep) -> CreatedWorldOut:
    # Ungültige Namen weist schon das Pydantic-Modell ab (AfterValidator mit
    # normalize_world_name, 422 mit Detail-Liste); der Dienst sieht nur noch
    # normalisierte Namen, ein eigener ValueError-Zweig wäre toter Code.
    try:
        created = await service.create_world(body.name)
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    except NoFreePortError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from None
    return CreatedWorldOut(**asdict(created))


# IDs erzeugt nur die App (uuid4().hex[:12]); alles andere ist 422 (T-01-17).
WorldId = Annotated[str, Path(pattern="^[0-9a-f]{12}$")]


def _http_error(exc: ProvisionerError) -> HTTPException:
    """Fehler des Lebenszyklus als HTTP-Antwort mit deutscher Meldung, ohne Stacktrace."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, DockerUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, NoFreePortError):
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


@router.delete("/worlds/{world_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_world(world_id: WorldId, service: ServiceDep) -> Response:
    try:
        await service.delete_world(world_id)
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
