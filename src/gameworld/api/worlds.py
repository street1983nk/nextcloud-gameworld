"""Welt-API: Auflisten und Erzeugen.

Es gibt bewusst kein Feld für Sichtbarkeit (ZUGANG-01): unbekannte Felder wie
``public`` oder ``server_announce`` werden mit 422 abgelehnt.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.config import load_settings
from gameworld.provisioner.client import DockerProvisioner, DockerUnavailableError, ProvisionerError
from gameworld.provisioner.luanti_conf import normalize_world_name
from gameworld.worlds.ports import NoFreePortError
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import WorldStore

router = APIRouter(prefix="/api")

_service: WorldService | None = None
_service_lock = threading.Lock()


def get_service() -> WorldService:
    """Modulweites Singleton, beim ersten Aufruf aus der Umgebung gebaut."""
    global _service
    with _service_lock:
        if _service is None:
            settings = load_settings()
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
    try:
        created = await service.create_world(body.name)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    except NoFreePortError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from None
    return CreatedWorldOut(**asdict(created))
