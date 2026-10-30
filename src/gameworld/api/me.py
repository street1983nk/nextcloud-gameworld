"""Routes for all signed-in accounts: self-lookup and own worlds.

No manager lock: the AppAPI routes ^/api/me$ and ^/api/my/.* are set to USER
in info.xml. Every answer therefore contains only data of the requesting
account; the UID comes from the signed AppAPI request, never from the browser
(ROLLE-01, pitfall 7).

Since 06-02, /api/me also returns nc_admin and invite_groups for managers
(own groups plus subadmin groups, the invitation scope per D-01); players
get nc_admin false and an empty list (no group leak to children).

Since 04-07 also the own remaining time (/api/my/playtime) and per world the
window status: only today's remainder, next playtime and the current or
next opening window, never plans, usage history or values of other children.
"""

from __future__ import annotations

import anyio.to_thread
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from gameworld.access.roles import (
    ADMIN_GROUP,
    MSG_UNAVAILABLE,
    ROLE_VERWALTER,
    RolesDep,
    RoleUnavailableError,
    UserDep,
    role_of,
)
from gameworld.access.secret import SecretUnavailableError
from gameworld.api.invites import JOIN_HOST_KEY, AccessDep
from gameworld.api.language import ui_language
from gameworld.api.playtime import TimeDep
from gameworld.api.worlds import ServiceDep
from gameworld.i18n import translate
from gameworld.playtime.service import MyPlaytime, MyWorldWindow, PlaytimeUnavailableError
from gameworld.worlds.status import BACKING_UP, RESTORING

router = APIRouter(prefix="/api")

# AR-24 (T-03-39): for op_state "failed", status_text is the stored
# last_error and may carry Docker internals (container name with instance ID,
# port). The child view gets this fixed text instead; the
# manager view (/api/worlds) keeps last_error unchanged.
TEXT_WELT_PROBLEM = "Diese Welt hat gerade ein Problem. Sag deinen Eltern Bescheid."
# D-10: during backup or restore, children see only this fixed
# text; job, file names and failure reasons stay in the manager view (T-05-17).
TEXT_WELT_PAUSE = "Die Welt macht kurz Pause"
_BUSY_STATUS = frozenset({BACKING_UP, RESTORING})


class MeOut(BaseModel):
    user_id: str
    display_name: str
    role: str
    # Convenience for the UI only; the lock sits in require_nc_admin.
    nc_admin: bool = False
    invite_groups: list[str] = Field(default_factory=list[str])
    # Nextcloud account language (de, en or fr; fallback en), D-25.
    language: str = "de"


class WindowOut(BaseModel):
    """One opening window of a world: ISO weekday, minutes (end 1440 = end of day) and days from today."""

    weekday: int = Field(ge=1, le=7)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)
    # 0 = today (also for the open window), 7 = same weekday in a week.
    days_ahead: int = Field(ge=0, le=7)


class MyWorldOut(BaseModel):
    """One own world with connection data; deliberately without player list, container or RAM."""

    id: str
    name: str
    # running | starting | stopped | error | unknown (from Docker), backing_up | restoring (phase 5)
    status: str
    status_text: str
    # Player address from the manager setting; None means: hostname of the browser.
    host: str | None
    port: int
    player_name: str
    # Only the own password, derived per request from the secret.
    password: str
    # Time window of the world (ZEIT-05): None = no window, otherwise open now yes/no.
    window_open: bool | None = None
    # Current (open) or next opening window, never the whole weekly plan.
    window_next: WindowOut | None = None


class MyWorldsOut(BaseModel):
    worlds: list[MyWorldOut]


class NextTimeOut(BaseModel):
    weekday: int = Field(ge=1, le=7)
    minute: int = Field(ge=0, le=1439)
    # 0 = today, 7 = same weekday in a week (for "today" in the display).
    days_ahead: int = Field(ge=0, le=7)


class MyPlaytimeOut(BaseModel):
    """Only today's remainder and next playtime (T-04-39): no plans, no usage, no sessions."""

    limited: bool
    # ok | aufgebraucht | fenster | tag; None without rules
    state: str | None
    remaining_minutes: int | None
    # Local, minutes from 00:00; None means end of day.
    until_minute: int | None
    next: NextTimeOut | None


def _playtime_out(result: MyPlaytime) -> MyPlaytimeOut:
    upcoming = result.next
    return MyPlaytimeOut(
        limited=result.limited,
        state=result.state,
        remaining_minutes=result.remaining_minutes,
        until_minute=result.until_minute,
        next=None
        if upcoming is None
        else NextTimeOut(weekday=upcoming.weekday, minute=upcoming.minute, days_ahead=upcoming.days_ahead),
    )


def _window_out(window: MyWorldWindow | None) -> WindowOut | None:
    slot = None if window is None else window.next
    if slot is None:
        return None
    return WindowOut(weekday=slot.weekday, start=slot.start, end=slot.end, days_ahead=slot.days_ahead)


@router.get("/me")
async def me(uid: UserDep, roles: RolesDep) -> MeOut:
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    role = role_of(profile, await roles.verwalter_groups())
    language = await roles.language(uid)
    if role != ROLE_VERWALTER:
        return MeOut(user_id=profile.user_id, display_name=profile.display_name, role=role, language=language)
    return MeOut(
        user_id=profile.user_id,
        display_name=profile.display_name,
        role=role,
        nc_admin=ADMIN_GROUP in profile.groups,
        invite_groups=sorted(set(profile.groups) | set(profile.subadmin)),
        language=language,
    )


@router.get("/my/worlds")
async def my_worlds(
    request: Request, uid: UserDep, roles: RolesDep, access: AccessDep, service: ServiceDep, playtime: TimeDep
) -> MyWorldsOut:
    try:
        profile = await roles.profile(uid)
        mine = await access.my_worlds(profile)
    except (RoleUnavailableError, SecretUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if not mine:
        return MyWorldsOut(worlds=[])
    # After the profile lookup: the language comes from the UI or the same cached self-lookup (T-06-76).
    language = ui_language(request) or await roles.language(uid)
    host = await anyio.to_thread.run_sync(service.store.get_meta, JOIN_HOST_KEY) or None
    views = {view.id: view for view in await service.list_worlds()}
    try:
        windows = await playtime.my_world_windows([entry.world_id for entry in mine if entry.world_id in views])
    except PlaytimeUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    worlds: list[MyWorldOut] = []
    for entry in mine:
        view = views.get(entry.world_id)
        if view is None:
            continue
        # Only for failed does last_error flow into status_text (worlds/status.py);
        # this one path gets the fixed child text here (AR-24).
        if view.op_state == "failed":
            status_text = TEXT_WELT_PROBLEM
        elif view.status in _BUSY_STATUS:
            status_text = TEXT_WELT_PAUSE
        else:
            status_text = view.status_text
        window = windows.get(entry.world_id)
        worlds.append(
            MyWorldOut(
                id=view.id,
                name=view.name,
                status=view.status,
                status_text=translate(status_text, language),
                host=host,
                port=view.port,
                player_name=entry.player_name,
                password=entry.password,
                window_open=None if window is None else window.open,
                window_next=_window_out(window),
            )
        )
    return MyWorldsOut(worlds=worlds)


@router.get("/my/playtime")
async def my_playtime(uid: UserDep, roles: RolesDep, playtime: TimeDep) -> MyPlaytimeOut:
    """Own remaining time today; display only, enforced solely in the world mod (T-04-40)."""
    try:
        profile = await roles.profile(uid)
        verwalter = role_of(profile, await roles.verwalter_groups()) == ROLE_VERWALTER
        result = await playtime.my_playtime(uid, exempt=verwalter)
    except (RoleUnavailableError, PlaytimeUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return _playtime_out(result)
