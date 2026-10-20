"""Routen für alle angemeldeten Konten: Selbstauskunft und eigene Welten.

Keine Verwalter-Sperre: AppAPI-Routen ^/api/me$ und ^/api/my/.* stehen in
info.xml auf USER. Jede Antwort enthält darum nur Daten des anfragenden
Kontos; die UID kommt aus der signierten AppAPI-Anfrage, nie aus dem Browser
(ROLLE-01, Pitfall 7).
"""

from __future__ import annotations

import anyio.to_thread
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from gameworld.access.roles import MSG_UNAVAILABLE, RolesDep, RoleUnavailableError, UserDep, role_of
from gameworld.access.secret import SecretUnavailableError
from gameworld.api.invites import JOIN_HOST_KEY, AccessDep
from gameworld.api.worlds import ServiceDep

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


class MyWorldsOut(BaseModel):
    worlds: list[MyWorldOut]


@router.get("/me")
async def me(uid: UserDep, roles: RolesDep) -> MeOut:
    try:
        profile = await roles.profile(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    return MeOut(user_id=profile.user_id, display_name=profile.display_name, role=role_of(profile))


@router.get("/my/worlds")
async def my_worlds(uid: UserDep, roles: RolesDep, access: AccessDep, service: ServiceDep) -> MyWorldsOut:
    try:
        profile = await roles.profile(uid)
        mine = await access.my_worlds(profile)
    except (RoleUnavailableError, SecretUnavailableError):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if not mine:
        return MyWorldsOut(worlds=[])
    host = await anyio.to_thread.run_sync(service.store.get_meta, JOIN_HOST_KEY) or None
    views = {view.id: view for view in await service.list_worlds()}
    worlds: list[MyWorldOut] = []
    for entry in mine:
        view = views.get(entry.world_id)
        if view is None:
            continue
        # Nur bei failed fließt last_error in status_text (worlds/status.py);
        # dieser eine Pfad bekommt hier den festen Kindertext (AR-24).
        status_text = TEXT_WELT_PROBLEM if view.op_state == "failed" else view.status_text
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
            )
        )
    return MyWorldsOut(worlds=worlds)
