"""Nextcloud als Verzeichnis der Konten (ROLLE-02: keine eigene Benutzerverwaltung).

Jede Prüfung läuft im Namen des einladenden Verwalters: Gameworld lädt nur
Konten ein, die Nextcloud diesem Verwalter als vorhanden bestätigt (T-03-17).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote

from nc_py_api import NextcloudException

from gameworld.nc import nc_app, nc_as

LOG = logging.getLogger(__name__)

# Schlüssel der Gegenprobe; gelesen wird nur, ob es ihn gibt, ist egal.
PROBE_KEY = "gameworld_probe"

# 998 ist der OCS-Code "nicht gefunden" der Provisioning-API.
_NOT_FOUND_CODES = frozenset({404, 998})
# Ausdrückliche Ablehnung des handelnden Kontos: 401 (AppAPI kennt das Konto nicht,
# OCS 997) und 403 (kein Admin, "must be at least a sub admin"), am Dev-Stack belegt.
_REJECTED_CODES = frozenset({401, 403, 997})

MSG_UNAVAILABLE = "Nextcloud antwortet gerade nicht. Bitte gleich noch einmal versuchen."


@dataclass(frozen=True)
class DirectoryUser:
    uid: str
    display_name: str
    enabled: bool


class DirectoryUnavailableError(Exception):
    """Nextcloud hat die Kontoprüfung nicht beantwortet."""


class DirectoryRejectedError(DirectoryUnavailableError):
    """Nextcloud lehnt das handelnde Konto ab (401/403): es ist kein Admin (mehr) oder es gibt es nicht.

    Unterklasse von DirectoryUnavailableError: Wer nur Störungen behandelt, bleibt
    beim bisherigen Verhalten (nie eine leere Gruppe, nie Rechte). Nur die
    Hintergrund-Prüfung des Verwalter-Schnappschusses unterscheidet beide Fälle.
    """


class Directory(Protocol):
    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        """Konto, wie Nextcloud es dem Verwalter zeigt; None, wenn es nicht existiert."""
        ...

    async def group_members(self, acting_uid: str, gid: str) -> list[str] | None:
        """Konto-IDs der Gruppe, als Verwalter gelesen; None, wenn es die Gruppe nicht gibt."""
        ...

    async def group_exists(self, acting_uid: str, gid: str) -> bool:
        """Gibt es die Gruppe? Gleiche Prüfung wie group_members."""
        ...

    async def app_accepted(self) -> bool:
        """Nimmt Nextcloud die ExApp selbst gerade an (Anfrage ohne Konto)? False bei jedem Fehler."""
        ...


class NcDirectory:
    """Kontoprüfung per OCS als handelnder Verwalter (``users.get_user(uid)``).

    Gruppen löst nur ein Admin auf: ``users_groups.get_members`` antwortet
    Nicht-Admins mit 403 (Pitfall 6). Darum laufen Gruppenabfragen nur im
    Verwalter-Kontext; ein 403 gilt als Störung (503), nie als leere Gruppe,
    damit kein Abgleich Zugänge wegen fehlender Rechte entfernt.
    """

    async def user(self, acting_uid: str, uid: str) -> DirectoryUser | None:
        try:
            async with nc_as(acting_uid) as nc:
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

    async def group_members(self, acting_uid: str, gid: str) -> list[str] | None:
        try:
            async with nc_as(acting_uid) as nc:
                # Auch die Gruppen-ID setzt nc_py_api roh in den Pfad.
                members = await nc.users_groups.get_members(quote(gid, safe=""))
        except NextcloudException as exc:
            if exc.status_code in _NOT_FOUND_CODES:
                return None
            LOG.warning("Gruppenabfrage bei Nextcloud gescheitert: Status %s", exc.status_code)
            if exc.status_code in _REJECTED_CODES:
                raise DirectoryRejectedError(MSG_UNAVAILABLE) from None
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        except Exception as exc:
            LOG.warning("Gruppenabfrage bei Nextcloud gescheitert: %s", type(exc).__name__)
            raise DirectoryUnavailableError(MSG_UNAVAILABLE) from None
        # Leere Gruppe: nc_py_api liefert dann {} statt [].
        return [str(member) for member in members or []]

    async def group_exists(self, acting_uid: str, gid: str) -> bool:
        return await self.group_members(acting_uid, gid) is not None

    async def app_accepted(self) -> bool:
        """Gegenprobe zu einer Ablehnung: eine App-Anfrage ohne Konto (appconfig_ex).

        Am Dev-Stack belegt: Solange Nextcloud die ExApp nicht annimmt (Start,
        Neuregistrierung), antwortet es auf jede Anfrage mit 401, auch auf diese.
        Gelingt sie, war ein 401/403 der Gruppenabfrage eine Ablehnung des Kontos.
        """
        try:
            async with nc_app() as nc:
                await nc.appconfig_ex.get_value(PROBE_KEY)
        except Exception as exc:
            LOG.warning("Nextcloud nimmt Gameworld gerade nicht an: %s", type(exc).__name__)
            return False
        return True


_directory: Directory | None = None


def get_directory() -> Directory:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _directory
    if _directory is None:
        _directory = NcDirectory()
    return _directory
