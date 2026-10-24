"""Das Geheimnis, aus dem alle Spielpasswörter abgeleitet werden (A3).

Es liegt nur in Nextcloud, in der App-Konfiguration der ExApp (``appconfig_ex``,
als ``sensitive`` gespeichert: verschlüsselt in der Datenbank und in Logs
gekürzt). Nie in SQLite, nie im Repo, nie im Log, nie in einer API-Antwort.

Es überlebt Updates und Neustarts der ExApp. Nur bei kompletter
Neuinstallation entsteht ein neues Geheimnis; dann ändern sich alle
Spielpasswörter einmalig, und 03-04 provisioniert die Welten automatisch neu.
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

SECRET_KEY = "player_password_secret"  # noqa: S105 (Schlüsselname, kein Wert)
SECRET_BYTES = 32
_HEX = re.compile(f"[0-9a-f]{{{2 * SECRET_BYTES}}}")

MSG_UNAVAILABLE = "Das Spielgeheimnis ist in Nextcloud gerade nicht lesbar."
MSG_UNREADABLE = "Das gespeicherte Spielgeheimnis ist unlesbar und wird nicht überschrieben."
# Template (D-25): only the exception type name is inserted, never values.
TEXT_UNAVAILABLE_TYPE = MSG_UNAVAILABLE + " ({type_name})"


class SecretUnavailableError(Exception):
    """Nextcloud antwortet nicht oder der gespeicherte Wert ist unlesbar."""


class _AppConfig(Protocol):
    async def get_value(self, key: str, default: str | None = None) -> str | None: ...

    async def set_value(self, key: str, value: str, sensitive: bool | None = None) -> None: ...


class _Nextcloud(Protocol):
    @property
    def appconfig_ex(self) -> _AppConfig: ...


FINGERPRINT_MESSAGE = b"gameworld:fingerprint"
FINGERPRINT_LENGTH = 16


def fingerprint(secret: bytes) -> str:
    """Kennung des Geheimnisses, um einen Wechsel (Neuinstallation) zu erkennen.

    HMAC mit fester Nachricht, auf 64 Bit gekürzt: nicht umkehrbar (T-03-31).
    Kollidiert nie mit einer Passwort-Nachricht, weil dort nach dem
    Doppelpunkt stets eine Zahl steht.
    """
    return hmac.new(secret, FINGERPRINT_MESSAGE, hashlib.sha256).hexdigest()[:FINGERPRINT_LENGTH]


def _parse(value: str) -> bytes:
    if not _HEX.fullmatch(value):
        raise SecretUnavailableError(MSG_UNREADABLE)
    return bytes.fromhex(value)


class PlayerSecret:
    """Lädt das Geheimnis aus Nextcloud oder erzeugt es genau einmal.

    Ein asyncio.Lock verhindert doppelte Erzeugung im Prozess. Nach dem
    Schreiben wird zurückgelesen und der zurückgelesene Wert genutzt. Ein
    unlesbarer Wert wird nie still überschrieben, sonst änderten sich alle
    Spielpasswörter. Aufruf im App-Kontext, ohne set_user.
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
                # Sessions schließen, auch im Fehlerfall (WR-05).
                await close_nc(nc)
        except SecretUnavailableError:
            raise
        except Exception as exc:
            # Nur Typ und Status, nie Werte: Die Ausnahme könnte die Anfrage enthalten.
            raise SecretUnavailableError(TEXT_UNAVAILABLE_TYPE.format(type_name=type(exc).__name__)) from None
        if stored is None:
            raise SecretUnavailableError(MSG_UNAVAILABLE)
        return _parse(stored)


_player_secret: PlayerSecret | None = None


def get_player_secret() -> PlayerSecret:
    """FastAPI-Dependency: modulweites Singleton, im Test ersetzbar."""
    global _player_secret
    if _player_secret is None:
        _player_secret = PlayerSecret()
    return _player_secret
