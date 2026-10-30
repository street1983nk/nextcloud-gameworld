"""World API: list, create, start, stop, restart and delete.

There is deliberately no field for visibility (ZUGANG-01): unknown fields such as
``public`` or ``server_announce`` are rejected with 422.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from gameworld.access.directory import Directory, get_directory
from gameworld.access.roles import RolesDep, RoleService, require_verwalter
from gameworld.access.secret import PlayerSecret, get_player_secret
from gameworld.access.service import AccessService, actor_of
from gameworld.api.language import LangDep
from gameworld.config import load_settings
from gameworld.i18n import SOURCE_LANGUAGE, translate, translate_optional
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

# Every route of this router is management: second lock next to the AppAPI route ADMIN.
router = APIRouter(prefix="/api", dependencies=[Depends(require_verwalter)])

_service: WorldService | None = None
_service_lock = threading.Lock()


def get_service() -> WorldService:
    """Module-wide singleton, built from the environment on the first call.

    An invalid environment (ValueError from load_settings) becomes 503 with the
    German message: the world routes stay reachable and /api/setup-check
    reports the same finding as item "config" (WR-01).
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
    """Router dependency of the phone pages: refresh the manager snapshot with the checked account (CR-01).

    Throttled and never blocking, like on the dashboard; an error never reaches the page.
    """
    try:
        await TimeService(service, directory).refresh_admins(uid, blocking=False)
    except Exception as exc:
        LOG.warning("Manager state not updated on page view: %s", type(exc).__name__)


class CreateWorldRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Raw value limited, then the same check as in the service (key injection, length).
    name: Annotated[str, Field(max_length=200), AfterValidator(normalize_world_name)]
    # Only IDs from the registry; conf lines come exclusively from hard-coded
    # presets. Default = safest preset: keeps the phase 1 contract ({"name"} alone)
    # compatible for scripts and UI, the dashboard visibly preselects from 02-04
    # (deliberate deviation from the RESEARCH recommendation "required field").
    preset: Annotated[str, Field(max_length=64), AfterValidator(validate_preset_id)] = DEFAULT_PRESET_ID


class WorldLanguageRequest(BaseModel):
    """World language of the mod texts (D-27); only these three values, anything else is 422."""

    model_config = ConfigDict(extra="forbid")

    language: Literal["de", "en", "fr"]


class WindowDayOut(BaseModel):
    weekday: int
    open: bool
    window_start: int | None
    window_end: int | None


class BackupJobOut(BaseModel):
    """Last backup or restore job (D-11); only in the manager view."""

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
    # Status from Docker (running, starting, stopped, error, unknown) and parent text.
    status: str
    status_text: str
    # WELT-03: online players (only with status running) and RAM (only with a running container).
    players: list[str]
    memory_used_bytes: int | None
    memory_limit_bytes: int | None
    # World data missing or creation aborted: only delete, start and restart give 409.
    delete_only: bool
    # Player names of the invitees, without passwords (only /api/worlds/{id}/players supplies those).
    invited_players: list[str]
    # Is the world still running without the access protection loaded? Then it needs a restart.
    access_restart_needed: bool
    # Is the world still running without the time mod loaded? Then it needs a restart.
    time_restart_needed: bool
    # Is the world still running with the old access mod (no event file)? Then no hints arrive.
    events_restart_needed: bool
    # World time window (ZEIT-05): seven weekdays or null (always open).
    time_window: list[WindowDayOut] | None
    # Last job (backup or restore) or null; errors stay visible after a reload.
    backup_job: BackupJobOut | None = None
    # World language of the mod texts (D-27); a running world started with another one needs a restart.
    language: str
    language_restart_needed: bool


class WorldListOut(BaseModel):
    worlds: list[WorldOut]


class PresetOut(BaseModel):
    """Parent texts only; hashes, limits and conf lines stay internal."""

    id: str
    title: str
    description: str


class PresetListOut(BaseModel):
    presets: list[PresetOut]


@router.get("/presets")
async def list_presets(language: LangDep) -> PresetListOut:
    return PresetListOut(
        presets=[
            PresetOut(
                id=preset.id,
                title=translate(preset.title, language),
                description=translate(preset.description, language),
            )
            for preset in PRESETS.values()
        ]
    )


@router.get("/worlds")
async def list_worlds(
    service: ServiceDep,
    uid: Annotated[str, Depends(require_verwalter)],
    directory: Annotated[Directory, Depends(get_directory)],
    secret: Annotated[PlayerSecret, Depends(get_player_secret)],
    roles: RolesDep,
    language: LangDep,
) -> WorldListOut:
    _start_visit(service, uid, directory, secret, roles)
    views = await service.list_worlds()
    return WorldListOut(worlds=[_out(view, language) for view in views])


# Reconciliation tasks of manager visits; at most one at a time (both steps are throttled globally anyway).
_VISIT_TASKS: set[asyncio.Task[None]] = set()
VISIT_SHUTDOWN_SECONDS = 5.0


async def _visit(
    service: WorldService, uid: str, directory: Directory, secret: PlayerSecret, roles: RoleService
) -> None:
    # Reconciliation on a manager visit (T-03-26), throttled to once per minute.
    # It must never block the world list (T-03-33): it runs beside the request, because
    # one group query at Nextcloud takes about a second and a visit asks one per group
    # and world; errors only as a warning. On behalf of a group manager it never
    # removes because of a 404 (P-01).
    try:
        actor = actor_of(await roles.profile(uid))
        await AccessService(service.store, service, directory, secret).sync_all(actor)
    except Exception as exc:
        LOG.warning("Invitation reconciliation on manager visit failed: %s", type(exc).__name__)
    # Manager snapshot for the exemption (A4), throttled and never
    # blocking (try_mutation); an error never reaches the world list (T-04-29).
    try:
        await TimeService(service, directory).refresh_admins(uid, blocking=False)
    except Exception as exc:
        LOG.warning("Manager state not updated on manager visit: %s", type(exc).__name__)


def _start_visit(
    service: WorldService, uid: str, directory: Directory, secret: PlayerSecret, roles: RoleService
) -> None:
    """Starts the visit reconciliation unless one is still running; the world list does not wait for it."""
    if _VISIT_TASKS:
        return
    task = asyncio.create_task(_visit(service, uid, directory, secret, roles))
    _VISIT_TASKS.add(task)
    task.add_done_callback(_VISIT_TASKS.discard)


async def drain_visits() -> None:
    """Waits until the running visit reconciliation is finished (tests)."""
    while _VISIT_TASKS:
        await asyncio.gather(*list(_VISIT_TASKS), return_exceptions=True)


async def shutdown_visits(grace_seconds: float = VISIT_SHUTDOWN_SECONDS) -> int:
    """Lifespan end: wait up to ``grace_seconds``, then cancel the visit reconciliation; number cancelled."""
    pending = set(_VISIT_TASKS)
    if not pending:
        return 0
    _done, still = await asyncio.wait(pending, timeout=grace_seconds)
    for task in still:
        task.cancel()
    if still:
        await asyncio.gather(*still, return_exceptions=True)
    return len(still)


@router.post("/worlds", status_code=status.HTTP_201_CREATED)
async def create_world(
    body: CreateWorldRequest, service: ServiceDep, uid: Annotated[str, Depends(require_verwalter)], language: LangDep
) -> WorldOut:
    # Since 03-05 without a world key: access only via invited, provisioned accounts.
    # Invalid names are already rejected by the Pydantic model (AfterValidator with
    # normalize_world_name, 422 with a detail list); the service only sees
    # normalized names, a separate ValueError branch would be dead code.
    try:
        # The world speaks the creating admin's account language (D-27); the body stays unchanged.
        created = await service.create_world(body.name, body.preset, language)
    except DockerUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from None
    except NoFreePortError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except ProvisionerError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from None
    # Every world gets a Talk room (D-16); the request never waits for Talk (D-20).
    _talk_hook(lambda: get_talk_service(service.store).schedule_ensure(created.id, uid))
    return _out(created, language)


# IDs are generated only by the app (uuid4().hex[:12]); anything else is 422 (T-01-17).
WorldId = Annotated[str, Path(pattern="^[0-9a-f]{12}$")]


def _http_error(exc: ProvisionerError) -> HTTPException:
    """Lifecycle errors as an HTTP response with a message in German source text, without a stack trace."""
    if isinstance(exc, WorldNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND)
    if isinstance(exc, DockerUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, (NoFreePortError, DeleteOnlyError, WorldBusyError)):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _out(view: WorldView, language: str) -> WorldOut:
    """Response of a world; server texts (also stored ones like last_error) in the account language (D-25)."""
    out = WorldOut(**asdict(view))
    if language == SOURCE_LANGUAGE:
        return out
    job = out.backup_job
    return out.model_copy(
        update={
            "status_text": translate(out.status_text, language),
            "preset_title": translate(out.preset_title, language),
            "last_error": translate_optional(out.last_error, language),
            "backup_job": None
            if job is None
            else job.model_copy(update={"message": translate_optional(job.message, language)}),
        }
    )


@router.post("/worlds/{world_id}/start")
async def start_world(world_id: WorldId, service: ServiceDep, language: LangDep) -> WorldOut:
    try:
        return _out(await service.start_world(world_id), language)
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/stop")
async def stop_world(world_id: WorldId, service: ServiceDep, language: LangDep) -> WorldOut:
    try:
        return _out(await service.stop_world(world_id), language)
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/restart")
async def restart_world(world_id: WorldId, service: ServiceDep, language: LangDep) -> WorldOut:
    try:
        return _out(await service.restart_world(world_id), language)
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.post("/worlds/{world_id}/language")
async def set_world_language(
    world_id: WorldId, body: WorldLanguageRequest, service: ServiceDep, language: LangDep
) -> WorldOut:
    """Change the world language (D-27). POST because AppAPI allows only GET, POST and DELETE.

    Applies from the next start; until then the world shows language_restart_needed.
    The router-wide require_verwalter refuses players with 403 (T-06-86).
    """
    try:
        return _out(await service.set_world_language(world_id, body.language), language)
    except ProvisionerError as exc:
        raise _http_error(exc) from None


@router.delete("/worlds/{world_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_world(
    world_id: WorldId, service: ServiceDep, uid: Annotated[str, Depends(require_verwalter)]
) -> Response:
    del uid  # managers only (second lock); Talk acts as room owner or first manager
    try:
        await service.delete_world(world_id)
    except ProvisionerError as exc:
        raise _http_error(exc) from None
    # Also delete the room (D-19); if Talk fails, delete_pending stays for the reconciliation.
    _talk_hook(lambda: get_talk_service(service.store).schedule_delete(world_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _talk_hook(start: Callable[[], None]) -> None:
    """Starts a Talk hook; an error there never reaches the world route (D-20)."""
    try:
        start()
    except Exception as exc:
        LOG.warning("Talk hook not started: %s", type(exc).__name__)
