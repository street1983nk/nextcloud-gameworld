"""Gameworld-Bot in Talk: registrieren, je Raum freischalten, signiert senden (TALK-02).

Der Bot schreibt unter eigenem Namen "Gameworld", nie im Namen eines
Elternteils (D-21 bis D-24). Registrierung und Geheimnis übernimmt nc_py_api
(``AsyncTalkBot.enabled_handler``, Ablage in ``appconfig_ex``); gesendet wird
HMAC-signiert über ``AsyncTalkBot.send_message`` ohne Nutzerkontext.

Ohne Talk oder ohne ``bots-v1`` passiert nichts (D-20, Pitfall 8). Logs
nennen nur Statuscodes und Typnamen, nie Texte oder Namen (T-04.1-32).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol
from urllib.parse import quote

from nc_py_api import AsyncNextcloudApp
from nc_py_api.talk_bot import AsyncTalkBot

LOG = logging.getLogger(__name__)

BOT = AsyncTalkBot("/talk/bot", "Gameworld", "Meldet Ereignisse der Gameworld-Welten")
# So endet die URL, unter der AppAPI den Bot bei Talk einträgt (talk_proxy).
BOT_URL_SUFFIX = "/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot"

STATUS_CREATED = 201
STATUS_UNAUTHORIZED = 401


class BotMissingError(Exception):
    """Talk kennt den Gameworld-Bot (noch) nicht."""


class _BotEntry(Protocol):
    @property
    def bot_id(self) -> int: ...

    @property
    def url(self) -> str: ...


class BotSender(Protocol):
    async def register(self) -> bool:
        """Registriert den Bot einmal je Prozess, falls Talk Bots kann."""
        ...

    async def ensure_enabled(self, token: str, acting_uid: str) -> None:
        """Schaltet den Bot im Raum frei (idempotent), als Verwalter."""
        ...

    async def send(self, token: str, text: str, *, silent: bool) -> bool:
        """Sendet eine Nachricht; True nur bei Erfolg."""
        ...


def find_bot_id(bots: Iterable[_BotEntry]) -> int | None:
    """Talk-ID des Gameworld-Bots aus der Admin-Liste; ohne Treffer None."""
    for entry in bots:
        if entry.url.endswith(BOT_URL_SUFFIX):
            return entry.bot_id
    return None


async def register(nc: AsyncNextcloudApp) -> bool:
    """Registriert den Bot über AppAPI, aber nur, wenn Talk Bots anbietet."""
    if not await nc.talk.bots_available:
        return False
    await BOT.enabled_handler(True, nc)
    _forget_rooms()
    return True


async def unregister(nc: AsyncNextcloudApp) -> None:
    """Meldet den Bot beim Deaktivieren der ExApp ab."""
    _forget_rooms()
    await BOT.enabled_handler(False, nc)


def _forget_rooms() -> None:
    """Nach Neu- oder Abmelden gelten Talk-ID und Freischaltungen nicht mehr."""
    if isinstance(_bot, NcBot):
        _bot.forget()


async def _as_user(acting_uid: str) -> AsyncNextcloudApp:
    nc = AsyncNextcloudApp()
    await nc.set_user(acting_uid)
    return nc


class NcBot:
    """Echter Bot; merkt sich Registrierung, Bot-ID und freigeschaltete Räume im Prozess."""

    def __init__(self) -> None:
        self._registered = False
        self._bot_id: int | None = None
        self._enabled: set[str] = set()

    async def register(self) -> bool:
        if self._registered:
            return True
        self._registered = await register(AsyncNextcloudApp())
        return self._registered

    async def ensure_enabled(self, token: str, acting_uid: str) -> None:
        if token in self._enabled:
            return
        nc = await _as_user(acting_uid)
        if self._bot_id is None:
            self._bot_id = find_bot_id(await nc.talk.list_bots())
            if self._bot_id is None:
                raise BotMissingError
        try:
            # nc_py_api setzt den Token roh in den Pfad.
            await nc.talk.enable_bot(quote(token, safe=""), self._bot_id)
        except Exception:
            # Bot womöglich neu registriert (neue Talk-ID): beim nächsten Mal neu suchen.
            self._bot_id = None
            raise
        self._enabled.add(token)

    def forget(self) -> None:
        self._bot_id = None
        self._enabled.clear()

    async def send(self, token: str, text: str, *, silent: bool) -> bool:
        try:
            response, _reference = await BOT.send_message(text, 0, silent=silent, token=quote(token, safe=""))
        except Exception as exc:
            LOG.warning("Bot-Nachricht nicht gesendet: %s", type(exc).__name__)
            return False
        status = response.status_code
        if status == STATUS_CREATED:
            return True
        if status == STATUS_UNAUTHORIZED:
            # Bot im Raum nicht (mehr) aktiv: beim nächsten Abgleich neu freischalten.
            self._enabled.discard(token)
        LOG.warning("Bot-Nachricht nicht gesendet: Status %s", status)
        return False


_bot: BotSender | None = None


def get_bot() -> BotSender:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _bot
    if _bot is None:
        _bot = NcBot()
    return _bot
