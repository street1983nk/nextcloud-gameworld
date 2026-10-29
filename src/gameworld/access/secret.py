"""The secret from which all game passwords are derived (A3).

It lives only in Nextcloud, in the app configuration of the ExApp (``appconfig_ex``,
stored as ``sensitive``: encrypted in the database and truncated in logs).
Never in SQLite, never in the repo, never in the log, never in an API response.

It survives updates and restarts of the ExApp. Only a complete
reinstall creates a new secret; then all game passwords change once,
and 03-04 provisions the worlds anew automatically.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import secrets
from collections.abc import Callable
from typing import Protocol

from nc_py_api import AsyncNextcloudApp

from gameworld.nc import close_nc

SECRET_KEY = "player_password_secret"  # noqa: S105 (key name, not a value)
SECRET_BYTES = 32
_HEX = re.compile(f"[0-9a-f]{{{2 * SECRET_BYTES}}}")

MSG_UNAVAILABLE = "Das Spielgeheimnis ist in Nextcloud gerade nicht lesbar."
MSG_UNREADABLE = "Das gespeicherte Spielgeheimnis ist unlesbar und wird nicht überschrieben."
# Template (D-25): only the exception type name is inserted, never values.
TEXT_UNAVAILABLE_TYPE = MSG_UNAVAILABLE + " ({type_name})"


class SecretUnavailableError(Exception):
    """Nextcloud does not answer or the stored value is unreadable."""


class _AppConfig(Protocol):
    async def get_value(self, key: str, default: str | None = None) -> str | None: ...

    async def set_value(self, key: str, value: str, sensitive: bool | None = None) -> None: ...


class _Nextcloud(Protocol):
    @property
    def appconfig_ex(self) -> _AppConfig: ...


FINGERPRINT_MESSAGE = b"gameworld:fingerprint"
FINGERPRINT_LENGTH = 16


def fingerprint(secret: bytes) -> str:
    """Identifier of the secret, to detect a change (reinstall).

    HMAC with a fixed message, truncated to 64 bits: not reversible (T-03-31).
    Never collides with a password message, because there a number always
    follows after the colon.
    """
    return hmac.new(secret, FINGERPRINT_MESSAGE, hashlib.sha256).hexdigest()[:FINGERPRINT_LENGTH]


def _parse(value: str) -> bytes:
    if not _HEX.fullmatch(value):
        raise SecretUnavailableError(MSG_UNREADABLE)
    return bytes.fromhex(value)


class PlayerSecret:
    """Load the secret from Nextcloud or generate it exactly once.

    An asyncio.Lock prevents double generation within the process. After
    writing, it is read back and the value read back is used. An
    unreadable value is never silently overwritten, otherwise all
    game passwords would change. Call in the app context, without set_user.
    """

    def __init__(self, nc_factory: Callable[[], _Nextcloud] = AsyncNextcloudApp) -> None:
        self._nc_factory = nc_factory
        self._lock = asyncio.Lock()
        self._value: bytes | None = None

    async def get(self) -> bytes:
        if self._value is not None:
            return self._value
        async with self._lock:
            if self._value is None:
                self._value = await self._load()
            return self._value

    async def _load(self) -> bytes:
        try:
            nc = self._nc_factory()
            try:
                config = nc.appconfig_ex
                stored = await config.get_value(SECRET_KEY)
                if stored is None:
                    await config.set_value(SECRET_KEY, secrets.token_hex(SECRET_BYTES), sensitive=True)
                    stored = await config.get_value(SECRET_KEY)
            finally:
                # Close sessions, also in the error case (WR-05).
                await close_nc(nc)
        except SecretUnavailableError:
            raise
        except Exception as exc:
            # Only type and status, never values: the exception could contain the request.
            raise SecretUnavailableError(TEXT_UNAVAILABLE_TYPE.format(type_name=type(exc).__name__)) from None
        if stored is None:
            raise SecretUnavailableError(MSG_UNAVAILABLE)
        return _parse(stored)


_player_secret: PlayerSecret | None = None


def get_player_secret() -> PlayerSecret:
    """FastAPI dependency: module-wide singleton, replaceable in tests."""
    global _player_secret
    if _player_secret is None:
        _player_secret = PlayerSecret()
    return _player_secret
