"""Verwalter-API für Sicherungen (BACKUP-01, D-07 bis D-09, D-12, D-13).

Nur Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (require_verwalter
routerweit, T-05-20). Das handelnde Konto kommt ausschließlich aus der
Abhängigkeit, nie aus dem Körper. Der Körper ist streng (T-05-21): nur
``confirm_disconnect`` als echtes JSON-Bool, Zusatzfelder sind 422.

``POST /api/worlds/{id}/backups`` antwortet sofort 202 mit der Weltansicht
(``backup_job`` running); der Ablauf läuft im Hintergrund, die Oberfläche
fragt die Weltenliste ab. ``GET`` liefert nur Sicherungen in den eigenen Files
mit eigenem Nachweis (D-13).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, WorldId, WorldOut, _http_error, _out  # pyright: ignore[reportPrivateUsage]
from gameworld.backup.files import FilesError
from gameworld.backup.service import BackupService, PlayersOnline, get_backup_service
from gameworld.provisioner.client import ProvisionerError, WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-05-20).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # D-09: Spielen Kinder, trennt die Sicherung sie erst nach Bestätigung.
    confirm_disconnect: bool = False


class BackupOut(BaseModel):
    """Eine gültige Sicherung; ohne Pfad, nur der Dateiname in den eigenen Files."""

    file_id: int
    name: str
    size: int
    created_at: str
    kind: str


class BackupListOut(BaseModel):
    backups: list[BackupOut]
    total_size: int
    other_files: int


def get_backups(worlds: ServiceDep) -> BackupService:
    return get_backup_service(worlds)


BackupDep = Annotated[BackupService, Depends(get_backups)]
VerwalterDep = Annotated[str, Depends(require_verwalter)]


@router.post("/worlds/{world_id}/backups", status_code=status.HTTP_202_ACCEPTED)
async def start_backup(
    world_id: WorldId, worlds: ServiceDep, backups: BackupDep, uid: VerwalterDep, body: BackupRequest | None = None
) -> WorldOut:
    request = body or BackupRequest()
    try:
        await backups.start_backup(world_id, uid, confirm_disconnect=request.confirm_disconnect)
    except PlayersOnline as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    # Aktuelle Ansicht, damit backup_job sofort sichtbar ist.
    for view in await worlds.list_worlds():
        if view.id == world_id:
            return _out(view)
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)


@router.get("/worlds/{world_id}/backups")
async def list_backups(world_id: WorldId, backups: BackupDep, uid: VerwalterDep) -> BackupListOut:
    try:
        listing = await backups.list_backups(world_id, uid)
    except WorldNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND) from None
    except FilesError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    return BackupListOut(
        backups=[
            BackupOut(file_id=item.file_id, name=item.name, size=item.size, created_at=item.created_at, kind=item.kind)
            for item in listing.entries
        ],
        total_size=listing.total_size,
        other_files=listing.other_files,
    )
