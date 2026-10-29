"""Talk rooms via the OCS API of spreed, on behalf of a manager (TALK-01).

ExApps have no system user of their own for OCS, Talk requires a logged-in
user. Therefore every call runs as a manager, per flow with its own short-lived
client (``gameworld.nc.nc_as``, closes its sessions, WR-05).
Logs contain only status code or type name, never names or participant lists
(T-04.1-27). Call settings stay at the Talk default (D-18).
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from nc_py_api import NextcloudException
from nc_py_api.talk import ConversationType

from gameworld.nc import nc_as

LOG = logging.getLogger(__name__)

BASE = "/ocs/v2.php/apps/spreed/api/v4/room"
# Talk allows room names up to 255 characters.
ROOM_NAME_MAX = 255
# Participant types from spreed docs/constants.md.
TYPE_OWNER = 1
TYPE_MODERATOR = 2
TYPE_USER = 3
TYPE_GUEST_MODERATOR = 6
MODERATOR_TYPES = frozenset({TYPE_MODERATOR, TYPE_GUEST_MODERATOR})
ACTOR_USERS = "users"

MSG_UNAVAILABLE = "Talk antwortet gerade nicht. Bitte später noch einmal versuchen."


class TalkUnavailableError(Exception):
    """Talk is missing, refuses the call or does not answer."""


class RoomGoneError(TalkUnavailableError):
    """Talk does not know the room for the acting account (404)."""


@dataclass(frozen=True)
class RoomMember:
    attendee_id: int
    actor_type: str
    actor_id: str
    participant_type: int


class TalkRooms(Protocol):
    async def available(self, acting_uid: str) -> tuple[bool, bool]:
        """(Talk present, bots present) according to capabilities."""
        ...

    async def create(self, acting_uid: str, name: str) -> str:
        """Creates a group room that cannot be found; returns the token."""
        ...

    async def participants(self, acting_uid: str, token: str) -> list[RoomMember]:
        """All participants of the room."""
        ...

    async def add_user(self, acting_uid: str, token: str, uid: str) -> None:
        """Adds a Nextcloud account as a participant."""
        ...

    async def remove_attendee(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Removes a participant (demote first, the owner cannot be removed)."""
        ...

    async def promote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Makes a participant a moderator."""
        ...

    async def demote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Takes a moderator's rights away."""
        ...

    async def set_read_only(self, acting_uid: str, token: str, *, on: bool) -> None:
        """Sets the room to read-only or back (D-17)."""
        ...

    async def ensure_private(self, acting_uid: str, token: str) -> None:
        """Never public, never discoverable."""
        ...

    async def delete(self, acting_uid: str, token: str) -> None:
        """Deletes the room; if it is already gone, that counts as success."""
        ...


def clean_room_name(name: str) -> str:
    """Without control and format characters, at most 255 characters."""
    kept = "".join(ch for ch in name if not unicodedata.category(ch).startswith("C"))
    return kept.strip()[:ROOM_NAME_MAX]


def _path(token: str, suffix: str = "") -> str:
    return f"{BASE}/{quote(token, safe='')}{suffix}"


def _unavailable(exc: Exception) -> TalkUnavailableError:
    if isinstance(exc, NextcloudException):
        LOG.warning("Talk call failed: status %s", exc.status_code)
    else:
        LOG.warning("Talk call failed: %s", type(exc).__name__)
    return TalkUnavailableError(MSG_UNAVAILABLE)


class NcTalkRooms:
    """OCS spreed v4, per flow its own short-lived client as the acting manager (WR-05)."""

    async def available(self, acting_uid: str) -> tuple[bool, bool]:
        try:
            async with nc_as(acting_uid) as nc:
                talk = bool(await nc.talk.available)
                bots = talk and bool(await nc.talk.bots_available)
        except Exception as exc:
            raise _unavailable(exc) from None
        return talk, bots

    async def create(self, acting_uid: str, name: str) -> str:
        """Create and make "not discoverable" in one client; if the second fails, the room is removed."""
        try:
            async with nc_as(acting_uid) as nc:
                try:
                    room = await nc.talk.create_conversation(ConversationType.GROUP, room_name=clean_room_name(name))
                    token = str(room.token)
                except Exception as exc:
                    raise _unavailable(exc) from None
                try:
                    await nc.ocs("PUT", _path(token, "/listable"), params={"scope": 0})
                except Exception as exc:
                    # No discoverable room without an entry: clean it up again, then report.
                    error = _unavailable(exc)
                    try:
                        await nc.ocs("DELETE", _path(token))
                    except Exception as cleanup:
                        LOG.warning("Talk room not removed after error: %s", type(cleanup).__name__)
                    raise error from None
        except TalkUnavailableError:
            raise
        except Exception as exc:
            raise _unavailable(exc) from None
        return token

    async def participants(self, acting_uid: str, token: str) -> list[RoomMember]:
        try:
            async with nc_as(acting_uid) as nc:
                raw = await nc.talk.list_participants(quote(token, safe=""))
        except NextcloudException as exc:
            if exc.status_code == 404:
                raise RoomGoneError(MSG_UNAVAILABLE) from None
            raise _unavailable(exc) from None
        except Exception as exc:
            raise _unavailable(exc) from None
        return [
            RoomMember(
                attendee_id=int(p.attendee_id),
                actor_type=str(p.actor_type),
                actor_id=str(p.actor_id),
                participant_type=int(p.participant_type),
            )
            for p in raw
        ]

    async def _ocs(self, acting_uid: str, method: str, path: str, **kwargs: Any) -> None:
        try:
            async with nc_as(acting_uid) as nc:
                await nc.ocs(method, path, **kwargs)
        except Exception as exc:
            raise _unavailable(exc) from None

    async def add_user(self, acting_uid: str, token: str, uid: str) -> None:
        await self._ocs(
            acting_uid, "POST", _path(token, "/participants"), json={"newParticipant": uid, "source": ACTOR_USERS}
        )

    async def remove_attendee(self, acting_uid: str, token: str, attendee_id: int) -> None:
        await self._ocs(acting_uid, "DELETE", _path(token, "/attendees"), params={"attendeeId": attendee_id})

    async def promote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        await self._ocs(acting_uid, "POST", _path(token, "/moderators"), json={"attendeeId": attendee_id})

    async def demote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        await self._ocs(acting_uid, "DELETE", _path(token, "/moderators"), params={"attendeeId": attendee_id})

    async def set_read_only(self, acting_uid: str, token: str, *, on: bool) -> None:
        await self._ocs(acting_uid, "PUT", _path(token, "/read-only"), params={"state": int(on)})

    async def ensure_private(self, acting_uid: str, token: str) -> None:
        try:
            async with nc_as(acting_uid) as nc:
                room = await nc.talk.get_conversation_by_token(quote(token, safe=""))
                if int(room.conversation_type) == int(ConversationType.PUBLIC):
                    await nc.ocs("DELETE", _path(token, "/public"))
                if int(room.listable) != 0:
                    await nc.ocs("PUT", _path(token, "/listable"), params={"scope": 0})
        except Exception as exc:
            raise _unavailable(exc) from None

    async def delete(self, acting_uid: str, token: str) -> None:
        try:
            async with nc_as(acting_uid) as nc:
                await nc.ocs("DELETE", _path(token))
        except NextcloudException as exc:
            if exc.status_code == 404:
                return
            raise _unavailable(exc) from None
        except Exception as exc:
            raise _unavailable(exc) from None


_rooms: TalkRooms | None = None


def get_talk_rooms() -> TalkRooms:
    """Module-wide singleton; tests inject a fake."""
    global _rooms
    if _rooms is None:
        _rooms = NcTalkRooms()
    return _rooms
