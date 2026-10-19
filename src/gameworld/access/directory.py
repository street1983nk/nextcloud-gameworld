"""Nextcloud als Verzeichnis der Konten (ROLLE-02: keine eigene Benutzerverwaltung).

Jede Prüfung läuft im Namen des einladenden Verwalters: Gameworld lädt nur
Konten ein, die Nextcloud diesem Verwalter als vorhanden bestätigt (T-03-17).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from nc_py_api import AsyncNextcloudApp, NextcloudException

LOG = logging.getLogger(__name__)

# 998 ist der OCS-Code "nicht gefunden" der Provisioning-API.
_NOT_FOUND_CODES = frozenset({404, 998})

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."


@dataclass(frozen=True)
class DirectoryUser:
    uid: str
    display_name: str
    enabled: bool


class DirectoryUnavailableError(Exception):
    """Nextcloud hat die Kontoprüfung nicht beantwortet."""


class Directory(Protocol):
    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        """Konto, wie Nextcloud es dem Verwalter zeigt; None, wenn es nicht existiert."""
        ...


class NcDirectory:
    """Kontoprüfung per OCS als handelnder Verwalter (``users.get_user(uid)``)."""

    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        try:
            nc = AsyncNextcloudApp()
            await nc.set_user(acting_uid)
            # nc_py_api setzt die ID ungeprüft in den Pfad: kodieren, damit "/" oder ".." nichts umlenkt.
            info = await nc.users.get_user(quote(uid, safe=""))
        except NextcloudException as exc:
            if exc.status_code in _NOT_FOUND_CODES:
                return None
            LOG.warning("Kontoprüfung bei Nextcloud gescheitert: Status %s", exc.status_code)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        except Exception as exc:
            LOG.warning("Kontoprüfung bei Nextcloud gescheitert: %s", type(exc).__name__)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        canonical = info.user_id or uid
        return DirectoryUser(uid=canonical, display_name=info.display_name or canonical, enabled=bool(info.enabled))


_directory: Directory | None = None


def get_directory() -> Directory:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _directory
    if _directory is None:
        _directory = NcDirectory()
    return _directory
