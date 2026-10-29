"""Gameworld bot in Talk: register, enable per room, send signed (TALK-02).

The bot writes under its own name "Gameworld", never on behalf of a
parent (D-21 to D-24). nc_py_api takes care of registration and secret
(``AsyncTalkBot.enabled_handler``, stored in ``appconfig_ex``); messages are sent
HMAC-signed via ``AsyncTalkBot.send_message`` without a user context.

Without Talk or without ``bots-v1`` nothing happens (D-20, pitfall 8). Logs
name only status codes and type names, never texts or names (T-04.1-32).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Protocol
from urllib.parse import quote

from nc_py_api import AsyncNextcloudApp, NextcloudException
from nc_py_api.talk_bot import AsyncTalkBot, aget_bot_secret

from gameworld.nc import nc_app, nc_as

LOG = logging.getLogger(__name__)

# Registered once for all accounts when the app is enabled, so there is no account
# language: the description is English (fallback language en, D-25).
BOT_DESCRIPTION = "Reports events from Gameworld worlds"
BOT = AsyncTalkBot("/talk/bot", "Gameworld", BOT_DESCRIPTION)
# This is how the URL ends under which AppAPI registers the bot with Talk (talk_proxy).
BOT_URL_SUFFIX = "/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot"

STATUS_CREATED = 201
STATUS_UNAUTHORIZED = 401


class BotMissingError(Exception):
    """Talk does not (yet) know the Gameworld bot."""


class _BotEntry(Protocol):
    @property
    def bot_id(self) -> int: ...

    @property
    def url(self) -> str: ...


class BotSender(Protocol):
    async def register(self) -> bool:
        """Registers the bot once per process, if Talk supports bots."""
        ...

    async def ensure_enabled(self, token: str, acting_uid: str) -> None:
        """Enables the bot in the room (idempotent), as a manager."""
        ...

    async def send(self, token: str, text: str, *, silent: bool) -> bool:
        """Sends a message; True only on success."""
        ...


def find_bot_id(bots: Iterable[_BotEntry]) -> int | None:
    """Talk ID of the Gameworld bot from the admin list; None without a match."""
    for entry in bots:
        if entry.url.endswith(BOT_URL_SUFFIX):
            return entry.bot_id
    return None


async def register(nc: AsyncNextcloudApp) -> bool:
    """Registers the bot via AppAPI, but only if Talk offers bots.

    Since AppAPI 34 every registration brings a new secret; if the bot is already
    in Talk, Talk rejects that ("same URL and a different secret"). If the stored
    secret is still there, the bot keeps signing with it: then it counts as
    registered instead of failing every 5 minutes. Without a secret the error stays.
    """
    if not await nc.talk.bots_available:
        return False
    try:
        await BOT.enabled_handler(True, nc)
    except NextcloudException as exc:
        if await aget_bot_secret(BOT.callback_url) is None:
            raise
        LOG.info("Talk bot was already registered (status %s), the stored secret still applies", exc.status_code)
    _forget_rooms()
    return True


async def unregister(nc: AsyncNextcloudApp) -> None:
    """Unregisters the bot when the ExApp is deactivated."""
    _forget_rooms()
    await BOT.enabled_handler(False, nc)


def _forget_rooms() -> None:
    """After registering or unregistering, Talk ID and enablements no longer apply."""
    if isinstance(_bot, NcBot):
        _bot.forget()


class NcBot:
    """Real bot; remembers registration, bot ID and enabled rooms in the process."""

    def __init__(self) -> None:
        self._registered = False
        self._bot_id: int | None = None
        self._enabled: set[str] = set()

    async def register(self) -> bool:
        if self._registered:
            return True
        async with nc_app() as nc:
            self._registered = await register(nc)
        return self._registered

    async def ensure_enabled(self, token: str, acting_uid: str) -> None:
        if token in self._enabled:
            return
        # Find and enable the bot in one short-lived client (WR-05).
        async with nc_as(acting_uid) as nc:
            if self._bot_id is None:
                self._bot_id = find_bot_id(await nc.talk.list_bots())
                if self._bot_id is None:
                    raise BotMissingError
            try:
                # nc_py_api puts the token raw into the path.
                await nc.talk.enable_bot(quote(token, safe=""), self._bot_id)
            except Exception:
                # Bot possibly re-registered (new Talk ID): search again next time.
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
            LOG.warning("Bot message not sent: %s", type(exc).__name__)
            return False
        status = response.status_code
        if status == STATUS_CREATED:
            return True
        if status == STATUS_UNAUTHORIZED:
            # Bot no longer active in the room: enable it again at the next reconciliation.
            self._enabled.discard(token)
        LOG.warning("Bot message not sent: status %s", status)
        return False


_bot: BotSender | None = None


def get_bot() -> BotSender:
    """Module-wide singleton; tests inject a fake."""
    global _bot
    if _bot is None:
        _bot = NcBot()
    return _bot
