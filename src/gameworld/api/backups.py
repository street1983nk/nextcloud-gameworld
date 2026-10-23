"""Verwalter-API für Sicherungen (BACKUP-01, D-07 bis D-09, D-12, D-13).

Nur Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (require_verwalter
routerweit, T-05-20). Das handelnde Konto kommt ausschließlich aus der
Abhängigkeit, nie aus dem Körper. Der Körper ist streng (T-05-21): nur
``confirm_disconnect`` als echtes JSON-Bool, Zusatzfelder sind 422.

``POST /api/worlds/{id}/backups`` antwortet sofort 202 mit der Weltansicht
(``backup_job`` running); der Ablauf läuft im Hintergrund, die Oberfläche
fragt die Weltenliste ab. ``GET`` liefert nur Sicherungen in den eigenen Files
mit eigenem Nachweis (D-13).

``POST /api/worlds/{id}/restore`` nimmt nur ``file_id`` (echte Ganzzahl),
``confirm`` und ``confirm_disconnect``; ohne ``confirm`` 409, fremde oder
unbekannte Sicherung 404 (BACKUP-02, D-04, D-13), sonst 202 mit Status
``restoring``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from gameworld.access.roles import require_verwalter
from gameworld.api.worlds import ServiceDep, WorldId, WorldOut, _http_error, _out  # pyright: ignore[reportPrivateUsage]
from gameworld.backup.files import FilesError
from gameworld.backup.service import (
    BackupNotFound,
    BackupService,
    PlayersOnline,
    RestoreNotConfirmed,
    get_backup_service,
)
from gameworld.provisioner.client import ProvisionerError, WorldNotFoundError
from gameworld.worlds.service import NOT_FOUND

# Jede Route ist Verwaltung: zweite Sperre neben AppAPI-Route ADMIN (T-05-20).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # D-09: Spielen Kinder, trennt die Sicherung sie erst nach Bestätigung.
    confirm_disconnect: bool = False


# SQLite speichert Ganzzahlen mit 64 Bit; größere Werte wären ein Fehler 500 statt 422.
MAX_FILE_ID = 2**63 - 1
MSG_BAD_FILE_ID = "file_id muss eine positive ganze Zahl sein."


def _whole_number(value: object) -> object:
    """Nur echte JSON-Ganzzahlen: "7", 7.0 oder true sind 422 (Muster aus api/pause.py)."""
    if type(value) is not int:
        raise ValueError(MSG_BAD_FILE_ID)
    return value


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Nur die Datei-ID aus der eigenen Liste; Pfad und Konto kommen nie aus dem Körper (T-05-28).
    file_id: Annotated[int, BeforeValidator(_whole_number), Field(ge=1, le=MAX_FILE_ID)]
    # D-04: Ohne ausdrückliche Bestätigung wird nichts wiederhergestellt (409).
    confirm: bool = False
    # D-09: Spielen Kinder, trennt das Wiederherstellen sie erst nach Bestätigung.
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
    return await _current(worlds, world_id)


@router.post("/worlds/{world_id}/restore", status_code=status.HTTP_202_ACCEPTED)
async def start_restore(
    world_id: WorldId, body: RestoreRequest, worlds: ServiceDep, backups: BackupDep, uid: VerwalterDep
) -> WorldOut:
    """Eigene Sicherung dieser Welt wiederherstellen (BACKUP-02); 202, der Ablauf läuft im Hintergrund.

    Auch eine Welt, die sonst nur noch gelöscht werden kann, ist erlaubt (D-15).
    """
    try:
        await backups.start_restore(
            world_id, uid, body.file_id, confirm=body.confirm, confirm_disconnect=body.confirm_disconnect
        )
    except (RestoreNotConfirmed, PlayersOnline) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except BackupNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    return await _current(worlds, world_id)


async def _current(worlds: ServiceDep, world_id: str) -> WorldOut:
    """Aktuelle Ansicht, damit backup_job und der Busy-Status sofort sichtbar sind."""
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
