"""Short-lived Nextcloud clients that always close their connections (WR-05).

Every ``AsyncNextcloudApp`` builds two niquests sessions (``adapter`` for OCS,
``adapter_dav`` for WebDAV) with a keep-alive pool. nc_py_api offers no
public ``close``; without closing, only the GC cleans up the connections,
also in foreign threads (.planning/debug/resolved/backend-windows-invalidstate.md).

Therefore clients exist only as context managers:

- ``nc_as(uid)``: on behalf of an account. The account goes straight into the
  constructor instead of via ``set_user``; this avoids the capabilities request that
  ``set_user`` triggers every time. If a call needs capabilities (Talk,
  notifications), nc_py_api loads them on demand as this account.
- ``nc_app()``: in the app context without a user (bot registration, app configuration).

One client per call, never one shared via ``set_user``: nc_py_api reads the
account only at request time (``_add_auth``), so concurrent coroutines would
otherwise switch the identity under each other.
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
    """Close both sessions of a client; errors while closing never disturb (only the type name in the log)."""
    session = getattr(nc, "_session", None)
    for name in _ADAPTERS:
        adapter = getattr(session, name, None)
        close = getattr(adapter, "close", None)
        if close is None:
            continue
        try:
            await close()
        except Exception as exc:
            LOG.debug("Nextcloud session not closed: %s", type(exc).__name__)


@asynccontextmanager
async def nc_as(uid: str, **options: Any) -> AsyncIterator[AsyncNextcloudApp]:
    """Client on behalf of ``uid``; closes its sessions also in the error case.

    ``options`` go unchanged to ``AsyncNextcloudApp``. Backup clients set
    ``npa_timeout_dav=600`` (MOVE of large files) and ``chunked_upload_v2=False``
    (upload v1, backup/files.py).
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
    """Client in the app context without a user; closes its sessions also in the error case."""
    nc = AsyncNextcloudApp()
    try:
        yield nc
    finally:
        await close_nc(nc)
