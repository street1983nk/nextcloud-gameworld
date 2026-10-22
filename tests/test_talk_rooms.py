"""OCS-Zugriff auf Talk-Räume (TALK-01): Pfade, Kodierung, Fehlerabbildung."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from nc_py_api import NextcloudException
from nc_py_api.talk import ConversationType

from gameworld.talk.rooms import (
    BASE,
    NcTalkRooms,
    RoomGoneError,
    RoomMember,
    TalkUnavailableError,
    clean_room_name,
    get_talk_rooms,
)
from tests.conftest import assert_closed, install_fake_nc

ROOM_TOKEN = "abc123"  # noqa: S105 (Raum-Token, kein Geheimnis)


def fake_nc() -> Any:
    nc = MagicMock()

    nc.ocs = AsyncMock(return_value=[])
    nc.talk.create_conversation = AsyncMock(return_value=SimpleNamespace(token=ROOM_TOKEN))
    nc.talk.list_participants = AsyncMock(return_value=[])
    nc.talk.get_conversation_by_token = AsyncMock(
        return_value=SimpleNamespace(conversation_type=ConversationType.GROUP, listable=0)
    )
    return nc


@pytest.fixture
def nc(monkeypatch: pytest.MonkeyPatch) -> Any:
    instance = fake_nc()
    instance.recorder = install_fake_nc(monkeypatch, instance)
    return instance


async def test_create_makes_group_room_and_hides_it(nc: Any) -> None:
    room = await NcTalkRooms().create("mama", "Gameworld: Insel")
    assert room == ROOM_TOKEN
    assert nc.recorder.users[-1] == "mama"
    nc.talk.create_conversation.assert_awaited_once_with(ConversationType.GROUP, room_name="Gameworld: Insel")
    nc.ocs.assert_awaited_once_with("PUT", f"{BASE}/abc123/listable", params={"scope": 0})


async def test_create_removes_room_when_hiding_fails(nc: Any) -> None:
    nc.ocs = AsyncMock(side_effect=[NextcloudException(500), []])
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().create("mama", "Gameworld: Insel")
    assert nc.ocs.await_args_list[-1].args == ("DELETE", f"{BASE}/abc123")


async def test_participants_are_neutral_dataclasses(nc: Any) -> None:
    nc.talk.list_participants = AsyncMock(
        return_value=[
            SimpleNamespace(attendee_id=7, actor_type="users", actor_id="lena", participant_type=3),
            SimpleNamespace(attendee_id=8, actor_type="groups", actor_id="familie", participant_type=3),
        ]
    )
    members = await NcTalkRooms().participants("mama", "a/b")
    assert members == [RoomMember(7, "users", "lena", 3), RoomMember(8, "groups", "familie", 3)]
    nc.talk.list_participants.assert_awaited_once_with("a%2Fb")
    with pytest.raises(AttributeError):
        members[0].actor_id = "x"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("call", "expected"),
    [
        (
            lambda r: r.add_user("mama", "a/b", "lena"),
            ("POST", f"{BASE}/a%2Fb/participants", {"json": {"newParticipant": "lena", "source": "users"}}),
        ),
        (
            lambda r: r.remove_attendee("mama", "a/b", 7),
            ("DELETE", f"{BASE}/a%2Fb/attendees", {"params": {"attendeeId": 7}}),
        ),
        (
            lambda r: r.promote("mama", "a/b", 7),
            ("POST", f"{BASE}/a%2Fb/moderators", {"json": {"attendeeId": 7}}),
        ),
        (
            lambda r: r.demote("mama", "a/b", 7),
            ("DELETE", f"{BASE}/a%2Fb/moderators", {"params": {"attendeeId": 7}}),
        ),
        (
            lambda r: r.set_read_only("mama", "a/b", on=True),
            ("PUT", f"{BASE}/a%2Fb/read-only", {"params": {"state": 1}}),
        ),
        (
            lambda r: r.set_read_only("mama", "a/b", on=False),
            ("PUT", f"{BASE}/a%2Fb/read-only", {"params": {"state": 0}}),
        ),
        (lambda r: r.delete("mama", "a/b"), ("DELETE", f"{BASE}/a%2Fb", {})),
    ],
)
async def test_calls_expected_ocs_paths(nc: Any, call: Any, expected: tuple[str, str, dict[str, Any]]) -> None:
    await call(NcTalkRooms())
    method, path, kwargs = expected
    nc.ocs.assert_awaited_once_with(method, path, **kwargs)
    assert nc.recorder.users[-1] == "mama"


async def test_ensure_private_leaves_private_room_alone(nc: Any) -> None:
    await NcTalkRooms().ensure_private("mama", "a/b")
    nc.talk.get_conversation_by_token.assert_awaited_once_with("a%2Fb")
    nc.ocs.assert_not_awaited()


async def test_ensure_private_closes_public_and_listable_room(nc: Any) -> None:
    nc.talk.get_conversation_by_token = AsyncMock(
        return_value=SimpleNamespace(conversation_type=ConversationType.PUBLIC, listable=2)
    )
    await NcTalkRooms().ensure_private("mama", "tok")
    calls = [(c.args, c.kwargs) for c in nc.ocs.await_args_list]
    assert (("DELETE", f"{BASE}/tok/public"), {}) in calls
    assert (("PUT", f"{BASE}/tok/listable"), {"params": {"scope": 0}}) in calls


async def test_delete_of_missing_room_is_success(nc: Any) -> None:
    nc.ocs = AsyncMock(side_effect=NextcloudException(404))
    await NcTalkRooms().delete("mama", "tok")


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_denied_or_broken_becomes_unavailable(nc: Any, status: int, caplog: pytest.LogCaptureFixture) -> None:
    nc.ocs = AsyncMock(side_effect=NextcloudException(status, info="request: POST /secret/lena"))
    with caplog.at_level(logging.WARNING), pytest.raises(TalkUnavailableError, match="Talk antwortet gerade nicht"):
        await NcTalkRooms().add_user("mama", "tok", "lena")
    assert str(status) in caplog.text
    assert "lena" not in caplog.text


async def test_network_error_becomes_unavailable(nc: Any, caplog: pytest.LogCaptureFixture) -> None:
    nc.talk.list_participants = AsyncMock(side_effect=OSError("kaputt bei lena"))
    with caplog.at_level(logging.WARNING), pytest.raises(TalkUnavailableError):
        await NcTalkRooms().participants("mama", "tok")
    assert "OSError" in caplog.text
    assert "lena" not in caplog.text


async def test_missing_room_on_participants_is_room_gone(nc: Any) -> None:
    nc.talk.list_participants = AsyncMock(side_effect=NextcloudException(404))
    with pytest.raises(RoomGoneError):
        await NcTalkRooms().participants("mama", "tok")


async def test_set_user_failure_becomes_unavailable(nc: Any) -> None:
    nc.recorder.error = NextcloudException(401)
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().promote("mama", "tok", 1)


async def test_available_reports_talk_and_bots(nc: Any) -> None:
    async def yes() -> bool:
        return True

    async def no() -> bool:
        return False

    type(nc.talk).available = property(lambda _self: yes())
    type(nc.talk).bots_available = property(lambda _self: no())
    assert await NcTalkRooms().available("mama") == (True, False)


async def test_available_failure_is_unavailable(nc: Any) -> None:
    nc.recorder.error = OSError("weg")
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().available("mama")


def test_clean_room_name_caps_and_strips_controls() -> None:
    assert clean_room_name("Gameworld: In\x00s\x1bel\n") == "Gameworld: Insel"
    assert len(clean_room_name("x" * 400)) == 255
    assert clean_room_name("‮abc") == "abc"


def test_singleton() -> None:
    assert get_talk_rooms() is get_talk_rooms()


# WR-05: Jeder Ablauf schließt seinen Client, auch im Fehlerfall.


async def test_create_uses_one_client_and_closes_it(nc: Any) -> None:
    await NcTalkRooms().create("mama", "Gameworld: Insel")
    assert nc.recorder.users == ["mama"]
    assert_closed(nc, times=1)


async def test_create_closes_client_when_hiding_fails(nc: Any) -> None:
    nc.ocs = AsyncMock(side_effect=[NextcloudException(500), []])
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().create("mama", "Gameworld: Insel")
    assert_closed(nc, times=1)


async def test_ensure_private_uses_one_client(nc: Any) -> None:
    nc.talk.get_conversation_by_token = AsyncMock(
        return_value=SimpleNamespace(conversation_type=ConversationType.PUBLIC, listable=2)
    )
    await NcTalkRooms().ensure_private("mama", "tok")
    assert nc.recorder.users == ["mama"]
    assert_closed(nc, times=1)


@pytest.mark.parametrize("error", [NextcloudException(500), NextcloudException(404), OSError("weg")])
async def test_errors_still_close_the_client(nc: Any, error: Exception) -> None:
    nc.ocs = AsyncMock(side_effect=error)
    nc.talk.list_participants = AsyncMock(side_effect=error)
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().add_user("mama", "tok", "lena")
    with pytest.raises(TalkUnavailableError):
        await NcTalkRooms().participants("mama", "tok")
    assert_closed(nc, times=2)
