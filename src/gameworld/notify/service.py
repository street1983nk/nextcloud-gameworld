"""Versand von Nextcloud-Benachrichtigungen über AppAPI (04.1-RESEARCH.md Pattern 4).

Je Empfänger ein eigener, kurzlebiger Client im Namen des Empfängers
(``gameworld.nc.nc_as``, schließt seine Sessions, WR-05): AppAPI stellt die
Benachrichtigung dem Nutzer aus ``authorization-app-api`` zu. Ein Fehler wird
nie wiederholt (404 heißt: notifications-App aus) und nur mit Statuscode oder
Typname geloggt, nie mit Empfänger oder Inhalt (T-04.1-21).
"""

from __future__ import annotations

import logging
from typing import Protocol

from nc_py_api import NextcloudException

from gameworld.nc import nc_as

LOG = logging.getLogger(__name__)

Params = dict[str, dict[str, str]]


class Notifier(Protocol):
    async def notify(self, uid: str, subject: str, message: str, params: Params, link: str) -> bool:
        """Benachrichtigung an ``uid``; True, wenn Nextcloud sie angenommen hat."""
        ...


class NcNotifier:
    """Echter Versand über ``notifications.create`` im Namen des Empfängers."""

    async def notify(self, uid: str, subject: str, message: str, params: Params, link: str) -> bool:
        try:
            async with nc_as(uid) as nc:
                await nc.notifications.create(subject, message, subject_params=params, message_params=params, link=link)
        except NextcloudException as exc:
            if exc.status_code == 404:
                LOG.warning("Benachrichtigung nicht zustellbar (notifications-App aus?): Status 404")
            else:
                LOG.warning("Benachrichtigung gescheitert: Status %s", exc.status_code)
            return False
        except Exception as exc:
            LOG.warning("Benachrichtigung gescheitert: %s", type(exc).__name__)
            return False
        return True


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _notifier
    if _notifier is None:
        _notifier = NcNotifier()
    return _notifier
