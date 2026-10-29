"""Manager API for backups (BACKUP-01, D-07 to D-09, D-12, D-13).

Management only: second lock next to the AppAPI route ADMIN (require_verwalter
router-wide, T-05-20). The acting account comes solely from the
dependency, never from the body. The body is strict (T-05-21): only
``confirm_disconnect`` as a real JSON bool, extra fields are 422.

``POST /api/worlds/{id}/backups`` answers 202 at once with the world view
(``backup_job`` running); the flow runs in the background, the UI
polls the world list. ``GET`` returns only backups in the own files
with an own record (D-13).

``POST /api/worlds/{id}/restore`` takes only ``file_id`` (real integer),
``confirm`` and ``confirm_disconnect``; without ``confirm`` 409, a foreign or
unknown backup 404 (BACKUP-02, D-04, D-13), otherwise 202 with status
``restoring``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from gameworld.access.roles import require_verwalter
from gameworld.api.language import LangDep
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

# Every route is management: second lock next to the AppAPI route ADMIN (T-05-20).
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])


class BackupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # D-09: if children are playing, the backup disconnects them only after confirmation.
    confirm_disconnect: bool = False


# SQLite stores integers with 64 bits; larger values would be a 500 error instead of 422.
MAX_FILE_ID = 2**63 - 1
MSG_BAD_FILE_ID = "file_id muss eine positive ganze Zahl sein."


def _whole_number(value: object) -> object:
    """Only real JSON integers: "7", 7.0 or true are 422 (pattern from api/pause.py)."""
    if type(value) is not int:
        raise ValueError(MSG_BAD_FILE_ID)
    return value


class RestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Only the file ID from the own list; path and account never come from the body (T-05-28).
    file_id: Annotated[int, BeforeValidator(_whole_number), Field(ge=1, le=MAX_FILE_ID)]
    # D-04: without explicit confirmation nothing is restored (409).
    confirm: bool = False
    # D-09: if children are playing, restoring disconnects them only after confirmation.
    confirm_disconnect: bool = False


class BackupOut(BaseModel):
    """A valid backup; without a path, only the file name in the own files."""

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
    world_id: WorldId,
    worlds: ServiceDep,
    backups: BackupDep,
    uid: VerwalterDep,
    language: LangDep,
    body: BackupRequest | None = None,
) -> WorldOut:
    request = body or BackupRequest()
    try:
        await backups.start_backup(world_id, uid, confirm_disconnect=request.confirm_disconnect)
    except PlayersOnline as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    return await _current(worlds, world_id, language)


@router.post("/worlds/{world_id}/restore", status_code=status.HTTP_202_ACCEPTED)
async def start_restore(
    world_id: WorldId,
    body: RestoreRequest,
    worlds: ServiceDep,
    backups: BackupDep,
    uid: VerwalterDep,
    language: LangDep,
) -> WorldOut:
    """Restore an own backup of this world (BACKUP-02); 202, the flow runs in the background.

    Even a world that can otherwise only be deleted is allowed (D-15).
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
    return await _current(worlds, world_id, language)


async def _current(worlds: ServiceDep, world_id: str, language: str) -> WorldOut:
    """Current view, so that backup_job and the busy status are visible immediately."""
    for view in await worlds.list_worlds():
        if view.id == world_id:
            return _out(view, language)
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
