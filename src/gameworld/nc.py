"""Kurzlebige Nextcloud-Clients, die ihre Verbindungen immer schließen (WR-05).

Jede ``AsyncNextcloudApp`` baut zwei niquests-Sessions (``adapter`` für OCS,
``adapter_dav`` für WebDAV) mit Keep-Alive-Pool. nc_py_api bietet kein
öffentliches ``close``; ohne Schließen räumt erst der GC die Verbindungen ab,
auch in fremden Threads (.planning/debug/resolved/backend-windows-invalidstate.md).

Darum gibt es Clients nur noch als Kontextmanager:

- ``nc_as(uid)``: im Namen eines Kontos. Das Konto geht direkt in den
  Konstruktor statt über ``set_user``; so entfällt der Capabilities-Request, den
  ``set_user`` jedes Mal auslöst. Braucht ein Aufruf Capabilities (Talk,
  Benachrichtigungen), lädt nc_py_api sie bei Bedarf als dieses Konto nach.
- ``nc_app()``: im App-Kontext ohne Nutzer (Bot-Registrierung, App-Konfiguration).

Je Aufruf ein eigener Client, nie ein geteilter über ``set_user``: nc_py_api liest
das Konto erst beim Request (``_add_auth``), gleichzeitige Coroutinen würden sich
die Identität sonst gegenseitig umschalten.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from nc_py_api import AsyncNextcloudApp

LOG = logging.getLogger(__name__)

_ADAPTERS = ("adapter", "adapter_dav")

MSG_NO_USER = "Ein Nextcloud-Client im Namen eines Kontos braucht eine Konto-ID."


async def close_nc(nc: object) -> None:
    """Schließt beide Sessions eines Clients; Fehler beim Schließen stören nie (nur Typname im Log)."""
    session = getattr(nc, "_session", None)
    for name in _ADAPTERS:
        adapter = getattr(session, name, None)
        close = getattr(adapter, "close", None)
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:
            LOG.debug("Nextcloud-Session nicht geschlossen: %s", type(exc).__name__)


@asynccontextmanager
async def nc_as(uid: str, **options: Any) -> AsyncIterator[AsyncNextcloudApp]:
    """Client im Namen von ``uid``; schließt seine Sessions auch im Fehlerfall.

    ``options`` gehen unverändert an ``AsyncNextcloudApp``. Backup-Clients setzen
    ``npa_timeout_dav=600`` (MOVE großer Dateien) und ``chunked_upload_v2=False``
    (Upload v1, backup/files.py).
    """
    if not uid:
        raise ValueError(MSG_NO_USER)
    nc = AsyncNextcloudApp(user=uid, **options)
    try:
        yield nc
    finally:
        await close_nc(nc)


@asynccontextmanager
async def nc_app() -> AsyncIterator[AsyncNextcloudApp]:
    """Client im App-Kontext ohne Nutzer; schließt seine Sessions auch im Fehlerfall."""
    nc = AsyncNextcloudApp()
    try:
        yield nc
    finally:
        await close_nc(nc)
