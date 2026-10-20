"""Routen für alle angemeldeten Konten: Selbstauskunft und eigene Welten.

Keine Verwalter-Sperre: AppAPI-Routen ^/api/me$ und ^/api/my/.* stehen in
info.xml auf USER. Jede Antwort enthält darum nur Daten des anfragenden
Kontos; die UID kommt aus der signierten AppAPI-Anfrage, nie aus dem Browser
(ROLLE-01, Pitfall 7).

Seit 04-07 auch die eigene Restzeit (/api/my/playtime) und je Welt der
Fensterstatus: nur heutiger Rest, nächste Spielzeit und das aktuelle oder
nächste Öffnungsfenster, nie Pläne, Verbrauchshistorie oder Werte anderer Kinder.
"""

from __future__ import annotations

import anyio.to_thread
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from gameworld.access.roles import (
    MSG_UNAVAILABLE,
    ROLE_VERWALTER,
    RolesDep,
    RoleUnavailableError,
    UserDep,
    role_of,
)
from gameworld.access.secret import SecretUnavailableError
from gameworld.api.invites import JOIN_HOST_KEY, AccessDep
from gameworld.api.playtime import TimeDep
from gameworld.api.worlds import ServiceDep
from gameworld.playtime.service import MyPlaytime, MyWorldWindow, PlaytimeUnavailableError

router = APIRouter(prefix="/api")

# AR-24 (T-03-39): Bei op_state "failed" ist status_text der gespeicherte
# last_error und kann Docker-Interna tragen (Containername mit Instanz-ID,
# Port). Die Kind-Ansicht bekommt stattdessen diesen festen Text; die
# Verwalter-Ansicht (/api/worlds) behält last_error unverändert.
TEXT_WELT_PROBLEM = "Diese Welt hat gerade ein Problem. Sag deinen Eltern Bescheid."


class MeOut(BaseModel):
    user_id: str
    display_name: str
    role: str


class WindowOut(BaseModel):
    """Ein Öffnungsfenster einer Welt: ISO-Wochentag und Minuten (Ende 1440 = Mitternacht)."""

    weekday: int = Field(ge=1, le=7)
    start: int = Field(ge=0, le=1439)
    end: int = Field(ge=1, le=1440)


class MyWorldOut(BaseModel):
    """Eine eigene Welt mit Verbindungsdaten; bewusst ohne Spielerliste, Container oder RAM."""

    id: str
    name: str
    # running | starting | stopped | error | unknown (aus Docker)
    status: str
    status_text: str
    # Spieler-Adresse aus der Verwalter-Einstellung; None heißt: Hostname des Browsers.
    host: str | None
    port: int
    player_name: str
    # Nur das eigene Passwort, pro Anfrage aus dem Geheimnis abgeleitet.
    password: str
    # Zeitfenster der Welt (ZEIT-05): None = kein Fenster, sonst jetzt offen ja/nein.
    window_open: bool | None = None
    # Aktuelles (offen) oder nächstes Öffnungsfenster, nie der ganze Wochenplan.
    window_next: WindowOut | None = None


class MyWorldsOut(BaseModel):
    worlds: list[MyWorldOut]


class NextTimeOut(BaseModel):
    weekday: int = Field(ge=1, le=7)
    minute: int = Field(ge=0, le=1439)


class MyPlaytimeOut(BaseModel):
    """Nur heutiger Rest und nächste Spielzeit (T-04-39): keine Pläne, kein Verbrauch, keine Sitzungen."""

    limited: bool
    # ok | aufgebraucht | fenster | tag; None ohne Regeln
    state: str | None
    remaining_minutes: int | None
    # Lokal, Minuten ab 00:00; None heißt Tagesende.
    until_minute: int | None
    next: NextTimeOut | None


def _playtime_out(result: MyPlaytime) -> MyPlaytimeOut:
    upcoming = result.next
    return MyPlaytimeOut(
        limited=result.limited,
        state=result.state,
        remaining_minutes=result.remaining_minutes,
        until_minute=result.until_minute,
        next=None if upcoming is None else NextTimeOut(weekday=upcoming.weekday, minute=upcoming.minute),
    )


def _window_out(window: MyWorldWindow | None) -> WindowOut | None:
    slot = None if window is None else window.next
    return None if slot is None else WindowOut(weekday=slot.weekday, start=slot.start, end=slot.end)


@router.get("/me")
async def me(uid: UserDep, roles: RolesDep) -> MeOut:
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return MeOut(user_id=profile.user_id, display_name=profile.display_name, role=role_of(profile))


@router.get("/my/worlds")
async def my_worlds(
    uid: UserDep, roles: RolesDep, access: AccessDep, service: ServiceDep, playtime: TimeDep
) -> MyWorldsOut:
    try:
        profile = await roles.profile(uid)
        mine = await access.my_worlds(profile)
    except (RoleUnavailableError, SecretUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if not mine:
        return MyWorldsOut(worlds=[])
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
        # Nur bei failed fließt last_error in status_text (worlds/status.py);
        # dieser eine Pfad bekommt hier den festen Kindertext (AR-24).
        status_text = TEXT_WELT_PROBLEM if view.op_state == "failed" else view.status_text
        window = windows.get(entry.world_id)
        worlds.append(
            MyWorldOut(
                id=view.id,
                name=view.name,
                status=view.status,
                status_text=status_text,
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
    """Eigene Restzeit heute; nur Anzeige, durchgesetzt wird allein im Welt-Mod (T-04-40)."""
    try:
        profile = await roles.profile(uid)
        result = await playtime.my_playtime(uid, exempt=role_of(profile) == ROLE_VERWALTER)
    except (RoleUnavailableError, PlaytimeUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return _playtime_out(result)
