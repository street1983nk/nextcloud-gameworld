"""Rollen allein aus Nextcloud-Gruppen (ROLLE-02, ROLLE-03, Owner-Entscheid A1).

Verwalter sind die Mitglieder der Verwalter-Gruppen: immer ``admin``, dazu die
Gruppen, die ein Nextcloud-Admin in meta ``verwalter_groups`` einträgt (D-02).
Alle anderen angemeldeten Konten sind Spieler. Gameworld speichert weder Rollen
noch Konten; die Rolle folgt je Anfrage aus der Selbstauskunft bei Nextcloud.

Nach Phase 6 ist ``require_verwalter`` die einzige Sperre der Verwaltungsrouten
(die AppAPI-Stufe ADMIN in info.xml entfällt in 06-02). ``require_nc_admin``
schützt die Admin-Abschnitte (D-02) und prüft ohne Cache. Antwortet Nextcloud
nicht, gibt es 503 und nie Verwalterrechte (Pitfall 5); eine kaputte Gruppen-
Konfiguration heißt: nur ``admin`` verwaltet (fail closed).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import anyio.to_thread
from fastapi import Depends, HTTPException, Request, status

from gameworld.i18n import FALLBACK_LANGUAGE, normalize_language
from gameworld.nc import nc_as

LOG = logging.getLogger(__name__)

# Echter Nextcloud-Admin = Mitglied der Gruppe admin; sie verwaltet Gameworld immer.
ADMIN_GROUP = "admin"
ROLE_VERWALTER = "verwalter"
ROLE_SPIELER = "spieler"
CACHE_SECONDS = 30.0
# meta-Schlüssel der zusätzlichen Verwalter-Gruppen (JSON-Liste von Gruppen-IDs).
META_VERWALTER_GROUPS = "verwalter_groups"
# Nextcloud erlaubt längere Gruppen-IDs; mehr nimmt Gameworld nicht an (wie die Einladungen).
GROUP_ID_MAX = 64
_ONLY_ADMIN = frozenset({ADMIN_GROUP})

MSG_NOT_LOGGED_IN = "Nicht angemeldet."
MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."
MSG_FORBIDDEN = "Nur Eltern können Welten verwalten."
MSG_NC_ADMIN_ONLY = "Nur Nextcloud-Admins dürfen das ändern."


@dataclass(frozen=True)
class Profile:
    user_id: str
    display_name: str
    groups: tuple[str, ...]
    # Gruppen, die das Konto als Subadmin verwaltet (Einladungs-Umfang, D-01).
    subadmin: tuple[str, ...] = ()
    # Account language (D-25). The default only applies to profiles built without
    # Nextcloud (tests); nc_profile always sets the value from Nextcloud.
    language: str = "de"


class RoleUnavailableError(Exception):
    """Die Selbstauskunft bei Nextcloud ist fehlgeschlagen."""


Lookup = Callable[[str], Awaitable[Profile]]
GroupsSource = Callable[[], Awaitable[frozenset[str]]]


def parse_verwalter_groups(raw: str | None) -> frozenset[str]:
    """Verwalter-Gruppen aus meta; admin ist immer dabei, kaputt oder fehlend heißt nur admin (fail closed)."""
    if not raw:
        return _ONLY_ADMIN
    try:
        value: object = json.loads(raw)
    except ValueError:
        return _ONLY_ADMIN
    if not isinstance(value, list):
        return _ONLY_ADMIN
    items: list[object] = list(value)  # pyright: ignore[reportUnknownArgumentType]
    groups = {item for item in items if isinstance(item, str) and 1 <= len(item) <= GROUP_ID_MAX}
    return frozenset(groups | {ADMIN_GROUP})


def role_of(profile: Profile, verwalter_groups: frozenset[str] = _ONLY_ADMIN) -> str:
    return ROLE_VERWALTER if set(profile.groups) & verwalter_groups else ROLE_SPIELER


async def nc_profile(uid: str) -> Profile:
    """Selbstauskunft im Namen des Nutzers (/ocs/v1.php/cloud/user); der Client schließt danach (WR-05)."""
    async with nc_as(uid) as nc:
        info = await nc.users.get_user()
    return Profile(
        user_id=uid,
        display_name=info.display_name or uid,
        groups=tuple(info.groups),
        subadmin=tuple(info.subadmin),
        language=normalize_language(info.language),
    )


class RoleService:
    """Fragt die Gruppen je Nutzer ab und merkt sich nur Erfolge für 30 s.

    ``groups`` liefert die konfigurierten Verwalter-Gruppen; fehlt die Quelle
    oder wirft sie, gilt nur ``admin``.
    """

    def __init__(self, lookup: Lookup, groups: GroupsSource | None = None) -> None:
        self._lookup = lookup
        self._groups = groups
        self._cache: dict[str, tuple[float, Profile]] = {}
        # Language only travels with the existing self-lookup (T-06-75, T-06-76):
        # last known value and time per account, plus the time of the last failed lookup.
        self._languages: dict[str, tuple[float, str]] = {}
        self._failed: dict[str, float] = {}

    async def profile(self, uid: str) -> Profile:
        cached = self._cache.get(uid)
        now = time.monotonic()
        if cached is not None and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            profile = await self._lookup(uid)
        except Exception as exc:  # jede Störung heißt: Rolle unbekannt, nie Verwalter
            self._cache.pop(uid, None)
            self._failed[uid] = now
            raise RoleUnavailableError(str(exc)) from exc
        self._cache[uid] = (now, profile)
        self._remember_language(uid, profile, now)
        return profile

    def _remember_language(self, uid: str, profile: Profile, now: float) -> None:
        self._languages[uid] = (now, profile.language)
        self._failed.pop(uid, None)

    async def language(self, uid: str) -> str:
        """Account language for response texts; never raises and never adds a Nextcloud call in the normal case.

        A fresh value (from profile or nc_admin within CACHE_SECONDS) is used as is.
        Right after a failed lookup the last known value (or en) is returned without
        asking Nextcloud again; otherwise the cached self-lookup is used.
        """
        try:
            now = time.monotonic()
            known = self._languages.get(uid)
            if known is not None and now - known[0] < CACHE_SECONDS:
                return known[1]
            failed = self._failed.get(uid)
            if failed is not None and now - failed < CACHE_SECONDS:
                return FALLBACK_LANGUAGE if known is None else known[1]
            try:
                return (await self.profile(uid)).language
            except RoleUnavailableError:
                return FALLBACK_LANGUAGE if known is None else known[1]
        except Exception as exc:  # the language must never break a response
            LOG.warning("Account language unknown, using fallback: %s", type(exc).__name__)
            return FALLBACK_LANGUAGE

    async def verwalter_groups(self) -> frozenset[str]:
        """Konfigurierte Verwalter-Gruppen; jede Störung der Quelle heißt nur admin (T-06-01)."""
        if self._groups is None:
            return _ONLY_ADMIN
        try:
            return (await self._groups()) | _ONLY_ADMIN
        except Exception as exc:  # kaputte Konfiguration gibt nie mehr Rechte
            LOG.warning("Verwalter-Gruppen nicht lesbar, nur admin verwaltet: %s", type(exc).__name__)
            return _ONLY_ADMIN

    async def role(self, uid: str) -> str:
        profile = await self.profile(uid)
        return role_of(profile, await self.verwalter_groups())

    async def nc_admin(self, uid: str) -> bool:
        """Echter Nextcloud-Admin? Immer frisch gefragt, nie aus dem Cache (Rechteausweitung, T-06-02)."""
        now = time.monotonic()
        try:
            profile = await self._lookup(uid)
        except Exception as exc:  # Störung heißt: kein Admin-Recht
            self._failed[uid] = now
            raise RoleUnavailableError(str(exc)) from exc
        # Only the language is remembered, never the profile (the role cache stays untouched).
        self._remember_language(uid, profile, now)
        return ADMIN_GROUP in profile.groups

    def invalidate(self) -> None:
        """Vergisst alle gemerkten Profile, etwa nach einer Änderung der Verwalter-Gruppen."""
        self._cache.clear()


_role_service: RoleService | None = None


async def _stored_verwalter_groups() -> frozenset[str]:
    """Verwalter-Gruppen aus dem Store des Weltdienstes, gelesen im Worker-Thread."""
    from gameworld.api.worlds import get_service  # spät: api.worlds importiert dieses Modul

    def read() -> str | None:
        return get_service().store.get_meta(META_VERWALTER_GROUPS)

    return parse_verwalter_groups(await anyio.to_thread.run_sync(read))


def get_role_service() -> RoleService:
    """FastAPI-Dependency: modulweites Singleton mit der echten Selbstauskunft."""
    global _role_service
    if _role_service is None:
        _role_service = RoleService(nc_profile, _stored_verwalter_groups)
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
    """Sperre jeder Verwaltungsroute: 403 für Spieler, 503 bei Störung."""
    try:
        role = await roles.role(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if role != ROLE_VERWALTER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_FORBIDDEN)
    return uid


async def require_nc_admin(uid: UserDep, roles: RolesDep) -> str:
    """Sperre der Admin-Abschnitte (D-02): 403 auch für Verwalter ohne Gruppe admin, 503 bei Störung."""
    try:
        is_admin = await roles.nc_admin(uid)
    except RoleUnavailableError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=MSG_UNAVAILABLE) from None
    if not is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=MSG_NC_ADMIN_ONLY)
    return uid


NcAdminDep = Annotated[str, Depends(require_nc_admin)]
