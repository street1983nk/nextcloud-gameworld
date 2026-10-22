"""Rollen allein aus Nextcloud-Gruppen (ROLLE-02, Owner-Entscheid A1).

Verwalter sind die Mitglieder der Nextcloud-Gruppe ``admin``, alle anderen
angemeldeten Konten sind Spieler. Gameworld speichert weder Rollen noch Konten.

Die Verwaltungsrouten sind doppelt gesperrt: AppAPI-Route ADMIN in info.xml und
``require_verwalter`` hier (ROLLE-01). Antwortet Nextcloud nicht, gibt es 503
und nie Verwalterrechte (Pitfall 5).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from gameworld.nc import nc_as

ADMIN_GROUP = "admin"
ROLE_VERWALTER = "verwalter"
ROLE_SPIELER = "spieler"
CACHE_SECONDS = 30.0

MSG_NOT_LOGGED_IN = "Nicht angemeldet."
MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
MSG_FORBIDDEN = "Nur Eltern können Welten verwalten."


@dataclass(frozen=True)
class Profile:
    user_id: str
    display_name: str
    groups: tuple[str, ...]


class RoleUnavailableError(Exception):
    """Die Selbstauskunft bei Nextcloud ist fehlgeschlagen."""


Lookup = Callable[[str], Awaitable[Profile]]


def role_of(profile: Profile) -> str:
    return ROLE_VERWALTER if ADMIN_GROUP in profile.groups else ROLE_SPIELER


async def nc_profile(uid: str) -> Profile:
    """Selbstauskunft im Namen des Nutzers (/ocs/v1.php/cloud/user); der Client schließt danach (WR-05)."""
    async with nc_as(uid) as nc:
        info = await nc.users.get_user()
    return Profile(user_id=uid, display_name=info.display_name or uid, groups=tuple(info.groups))


class RoleService:
    """Fragt die Gruppen je Nutzer ab und merkt sich nur Erfolge für 30 s."""

    def __init__(self, lookup: Lookup) -> None:
        self._lookup = lookup
        self._cache: dict[str, tuple[float, Profile]] = {}

    async def profile(self, uid: str) -> Profile:
        cached = self._cache.get(uid)
        now = time.monotonic()
        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            profile = await self._lookup(uid)
        except Exception as exc:  # jede Störung heißt: Rolle unbekannt, nie Verwalter
            self._cache.pop(uid, None)
            raise RoleUnavailableError(str(exc)) from exc
        self._cache[uid] = (now, profile)
        return profile

    async def role(self, uid: str) -> str:
        return role_of(await self.profile(uid))


_role_service: RoleService | None = None


def get_role_service() -> RoleService:
    """FastAPI-Dependency: modulweites Singleton mit der echten Selbstauskunft."""
    global _role_service
    if _role_service is None:
        _role_service = RoleService(nc_profile)
    return _role_service


def current_user(request: Request) -> str:
    """Nutzer-ID, die AppAPIAuthMiddleware nach geprüfter Signatur ablegt."""
    uid = request.scope.get("username") or ""
    if not uid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=MSG_NOT_LOGGED_IN)
    return uid


UserDep = Annotated[str, Depends(current_user)]
RolesDep = Annotated[RoleService, Depends(get_role_service)]


async def require_verwalter(uid: UserDep, roles: RolesDep) -> str:
    """Zweite Sperre jeder Verwaltungsroute: 403 für Nicht-Admins, 503 bei Störung."""
    try:
        role = await roles.role(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if role != ROLE_VERWALTER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_FORBIDDEN)
    return uid
