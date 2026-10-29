"""Sending Nextcloud notifications via AppAPI (04.1-RESEARCH.md pattern 4).

One own short-lived client per recipient on behalf of the recipient
(``gameworld.nc.nc_as``, closes its sessions, WR-05): AppAPI delivers the
notification to the user from ``authorization-app-api``. An error is
never retried (404 means: notifications app off) and logged only with status code or
type name, never with recipient or content (T-04.1-21).
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
        """Notification to ``uid``; True if Nextcloud accepted it."""
        ...


class NcNotifier:
    """Real sending via ``notifications.create`` on behalf of the recipient."""

    async def notify(self, uid: str, subject: str, message: str, params: Params, link: str) -> bool:
        try:
            async with nc_as(uid) as nc:
                await nc.notifications.create(subject, message, subject_params=params, message_params=params, link=link)
        except NextcloudException as exc:
            if exc.status_code == 404:
                LOG.warning("Notification not deliverable (notifications app off?): status 404")
            else:
                LOG.warning("Notification failed: status %s", exc.status_code)
            return False
        except Exception as exc:
            LOG.warning("Notification failed: %s", type(exc).__name__)
            return False
        return True


_notifier: Notifier | None = None


def get_notifier() -> Notifier:
    """Module-wide singleton; tests inject a fake."""
    global _notifier
    if _notifier is None:
        _notifier = NcNotifier()
    return _notifier
