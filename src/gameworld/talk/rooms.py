"""Talk-Räume über die OCS-API von spreed, im Namen eines Verwalters (TALK-01).

ExApps haben für OCS keinen eigenen Systemnutzer, Talk verlangt einen
angemeldeten Nutzer. Darum läuft jeder Aufruf per ``set_user`` als Verwalter.
Logs enthalten nur Statuscode oder Typname, nie Namen oder Teilnehmerlisten
(T-04.1-27). Anruf-Einstellungen bleiben auf Talk-Standard (D-18).
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

from nc_py_api import AsyncNextcloudApp, NextcloudException
from nc_py_api.talk import ConversationType

LOG = logging.getLogger(__name__)

BASE = "/ocs/v2.php/apps/spreed/api/v4/room"
# Talk erlaubt Raumnamen bis 255 Zeichen.
ROOM_NAME_MAX = 255
# Teilnehmertypen aus spreed docs/constants.md.
TYPE_OWNER = 1
TYPE_MODERATOR = 2
TYPE_USER = 3
TYPE_GUEST_MODERATOR = 6
MODERATOR_TYPES = frozenset({TYPE_MODERATOR, TYPE_GUEST_MODERATOR})
ACTOR_USERS = "users"

MSG_UNAVAILABLE = "Talk antwortet gerade nicht. Bitte später noch einmal versuchen."


class TalkUnavailableError(Exception):
    """Talk fehlt, verweigert den Aufruf oder antwortet nicht."""


class RoomGoneError(TalkUnavailableError):
    """Talk kennt den Raum für das handelnde Konto nicht (404)."""


@dataclass(frozen=True)
class RoomMember:
    attendee_id: int
    actor_type: str
    actor_id: str
    participant_type: int


class TalkRooms(Protocol):
    async def available(self, acting_uid: str) -> tuple[bool, bool]:
        """(Talk da, Bots da) laut Capabilities."""
        ...

    async def create(self, acting_uid: str, name: str) -> str:
        """Legt einen nicht auffindbaren Gruppenraum an; liefert den Token."""
        ...

    async def participants(self, acting_uid: str, token: str) -> list[RoomMember]:
        """Alle Teilnehmer des Raums."""
        ...

    async def add_user(self, acting_uid: str, token: str, uid: str) -> None:
        """Fügt ein Nextcloud-Konto als Teilnehmer hinzu."""
        ...

    async def remove_attendee(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Entfernt einen Teilnehmer (vorher zurückstufen, Owner geht nicht)."""
        ...

    async def promote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Macht einen Teilnehmer zum Moderator."""
        ...

    async def demote(self, acting_uid: str, token: str, attendee_id: int) -> None:
        """Nimmt einem Moderator die Rechte."""
        ...

    async def set_read_only(self, acting_uid: str, token: str, *, on: bool) -> None:
        """Schaltet den Raum auf nur lesen oder zurück (D-17)."""
        ...

    async def ensure_private(self, acting_uid: str, token: str) -> None:
        """Nie öffentlich, nie auffindbar."""
        ...

    async def delete(self, acting_uid: str, token: str) -> None:
        """Löscht den Raum; ist er schon weg, gilt das als Erfolg."""
        ...


def clean_room_name(name: str) -> str:
    """Ohne Steuer- und Formatzeichen, höchstens 255 Zeichen."""
    kept = "".join(ch for ch in name if not unicodedata.category(ch).startswith("C"))
    return kept.strip()[:ROOM_NAME_MAX]


def _path(token: str, suffix: str = "") -> str:
    return f"{BASE}/{quote(token, safe='')}{suffix}"


def _unavailable(exc: Exception) -> TalkUnavailableError:
    if isinstance(exc, NextcloudException):
        LOG.warning("Talk-Aufruf gescheitert: Status %s", exc.status_code)
    else:
        LOG.warning("Talk-Aufruf gescheitert: %s", type(exc).__name__)
    return TalkUnavailableError(MSG_UNAVAILABLE)


async def _as_user(acting_uid: str) -> AsyncNextcloudApp:
    nc = AsyncNextcloudApp()
    await nc.set_user(acting_uid)
    return nc


class NcTalkRooms:
    """OCS spreed v4, je Aufruf frisch als handelnder Verwalter."""

    async def available(self, acting_uid: str) -> tuple[bool, bool]:
        try:
            nc = await _as_user(acting_uid)
            talk = bool(await nc.talk.available)
            bots = talk and bool(await nc.talk.bots_available)
        except Exception as exc:
            raise _unavailable(exc) from None
        return talk, bots

    async def create(self, acting_uid: str, name: str) -> str:
        try:
            nc = await _as_user(acting_uid)
            room = await nc.talk.create_conversation(ConversationType.GROUP, room_name=clean_room_name(name))
            token = str(room.token)
        except Exception as exc:
            raise _unavailable(exc) from None
        try:
            await nc.ocs("PUT", _path(token, "/listable"), params={"scope": 0})
        except Exception as exc:
            # Kein auffindbarer Raum ohne Eintrag: wieder wegräumen, dann melden.
            error = _unavailable(exc)
            try:
                await nc.ocs("DELETE", _path(token))
            except Exception as cleanup:
                LOG.warning("Talk-Raum nach Fehler nicht entfernt: %s", type(cleanup).__name__)
            raise error from None
        return token

    async def participants(self, acting_uid: str, token: str) -> list[RoomMember]:
        try:
            nc = await _as_user(acting_uid)
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
            nc = await _as_user(acting_uid)
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
            nc = await _as_user(acting_uid)
            room = await nc.talk.get_conversation_by_token(quote(token, safe=""))
            if int(room.conversation_type) == int(ConversationType.PUBLIC):
                await nc.ocs("DELETE", _path(token, "/public"))
            if int(room.listable) != 0:
                await nc.ocs("PUT", _path(token, "/listable"), params={"scope": 0})
        except Exception as exc:
            raise _unavailable(exc) from None

    async def delete(self, acting_uid: str, token: str) -> None:
        try:
            nc = await _as_user(acting_uid)
            await nc.ocs("DELETE", _path(token))
        except NextcloudException as exc:
            if exc.status_code == 404:
                return
            raise _unavailable(exc) from None
        except Exception as exc:
            raise _unavailable(exc) from None


_rooms: TalkRooms | None = None


def get_talk_rooms() -> TalkRooms:
    """Modulweites Singleton; Tests setzen ein Fake ein."""
    global _rooms
    if _rooms is None:
        _rooms = NcTalkRooms()
    return _rooms
