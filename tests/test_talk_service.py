"""TalkService (TALK-01): Raum je Welt, exakte Mitgliederliste, Abgleich, Löschen, Verfügbarkeit."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.talk import service as talk_service
from gameworld.talk.rooms import RoomMember, TalkUnavailableError
from gameworld.talk.service import TalkService, get_talk_service
from gameworld.worlds.store import TALK_STATE_DELETE_PENDING, TALK_STATE_OK, WorldStore
from tests.conftest import FakeTalkRooms
from tests.test_pause_api import _row

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.apply_world_access(W1, {"gw-kind": "v1"})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "papa"]))
    return world_store


@pytest.fixture
def talk(store: WorldStore, fake_talk: FakeTalkRooms) -> TalkService:
    return TalkService(store, fake_talk)


def _members(fake: FakeTalkRooms, token: str) -> dict[str, tuple[str, int]]:
    return {m.actor_id: (m.actor_type, m.participant_type) for m in fake.rooms[token]}


def _token(store: WorldStore, world_id: str = W1) -> str:
    row = store.talk_room(world_id)
    assert row is not None
    return row.token


async def test_ensure_room_creates_room_with_exact_members(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    row = store.talk_room(W1)
    assert row is not None
    assert (row.owner_uid, row.state, row.read_only) == ("admin", TALK_STATE_OK, False)
    assert ("create", "admin", ("Gameworld: Wiese",)) in fake_talk.calls
    assert _members(fake_talk, row.token) == {
        "admin": ("users", 1),
        "papa": ("users", 2),
        "gw-kind": ("users", 3),
    }


async def test_ensure_room_twice_makes_no_second_room(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    await talk.ensure_room(W1, "admin")
    assert fake_talk.methods().count("create") == 1
    assert len(store.list_talk_rooms()) == 1


async def test_sync_removes_outsiders_and_never_the_owner(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    fake_talk.rooms[token] += [
        RoomMember(901, "users", "fremd", 3),
        RoomMember(902, "groups", "familie", 3),
        RoomMember(903, "guests", "gast", 4),
        RoomMember(904, "users", "gw-kind2", 2),
        RoomMember(905, "emails", "x@example.org", 6),
        RoomMember(906, "federated_users", "a@b", 3),
    ]
    fake_talk.calls.clear()
    await talk.sync_members(W1)
    assert set(_members(fake_talk, token)) == {"admin", "papa", "gw-kind"}
    removed = [c[2][1] for c in fake_talk.calls if c[0] == "remove_attendee"]
    assert sorted(removed) == [901, 902, 903, 904, 905, 906]
    # Moderatoren erst zurückstufen, dann entfernen (Pitfall 5).
    order = [(c[0], c[2][1]) for c in fake_talk.calls if c[0] in {"demote", "remove_attendee"}]
    assert order.index(("demote", 904)) < order.index(("remove_attendee", 904))
    assert order.index(("demote", 905)) < order.index(("remove_attendee", 905))
    # Owner bleibt, auch wenn er nicht mehr Verwalter ist (D-27).
    store.set_meta(META_TIME_ADMINS, json.dumps(["papa"]))
    await talk.sync_members(W1)
    assert _members(fake_talk, token)["admin"] == ("users", 1)


async def test_kid_moderator_is_demoted_and_uninvited_moderator_removed(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    kid = next(m for m in fake_talk.rooms[token] if m.actor_id == "gw-kind")
    fake_talk._retype(token, kid.attendee_id, 2)  # pyright: ignore[reportPrivateUsage]
    await talk.sync_members(W1)
    assert _members(fake_talk, token)["gw-kind"] == ("users", 3)
    # Ausladen: erst zurückstufen, dann entfernen.
    fake_talk._retype(token, kid.attendee_id, 2)  # pyright: ignore[reportPrivateUsage]
    store.apply_world_access(W1, {})
    fake_talk.calls.clear()
    await talk.sync_members(W1)
    assert "gw-kind" not in _members(fake_talk, token)
    assert [c[0] for c in fake_talk.calls if c[0] in {"demote", "remove_attendee"}] == ["demote", "remove_attendee"]


async def test_invite_adds_and_revoke_removes(talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    store.apply_world_access(W1, {"gw-kind": "v1", "gw-kind2": "v2"})
    await talk.sync_members(W1)
    assert _members(fake_talk, token)["gw-kind2"] == ("users", 3)
    store.apply_world_access(W1, {"gw-kind2": "v2"})
    await talk.sync_members(W1)
    assert "gw-kind" not in _members(fake_talk, token)


async def test_empty_snapshot_means_no_talk_call(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    store.set_meta(META_TIME_ADMINS, "[]")
    fake_talk.calls.clear()
    await talk.sync_members(W1)
    await talk.reconcile_all()
    assert fake_talk.calls == []


async def test_without_talk_nothing_happens_and_nothing_raises(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    fake_talk.talk = False
    await talk.ensure_room(W1, "admin")
    await talk.sync_members(W1)
    await talk.reconcile_all()
    assert store.list_talk_rooms() == []
    assert set(fake_talk.methods()) == {"available"}


async def test_capability_error_counts_as_unavailable(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    fake_talk.error = TalkUnavailableError("weg")
    await talk.ensure_room(W1, "admin")
    assert store.list_talk_rooms() == []


async def test_availability_is_cached_for_five_minutes(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    del store
    await talk.ensure_room(W1, "admin")
    await talk.ensure_room(W2, "admin")
    assert fake_talk.methods().count("available") == 1
    checked = talk_service.TALK_STATE.checked_at
    assert checked is not None
    talk_service.TALK_STATE.checked_at = checked - talk_service.TALK_INTERVAL_SECONDS - 1
    await talk.sync_members(W1)
    assert fake_talk.methods().count("available") == 2


async def test_delete_room_removes_row(talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    await talk.delete_room(W1)
    assert store.talk_room(W1) is None
    assert token not in fake_talk.rooms


async def test_failed_delete_stays_pending_and_reconcile_retries(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    store.delete_world(W1)
    fake_talk.error = TalkUnavailableError("weg")
    await talk.delete_room(W1)
    row = store.talk_room(W1)
    assert row is not None
    assert row.state == TALK_STATE_DELETE_PENDING
    fake_talk.error = None
    await talk.reconcile_all()
    assert store.talk_room(W1) is None
    assert token not in fake_talk.rooms


async def test_reconcile_backfills_enforces_read_only_and_privacy(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    assert store.set_talk_read_only(W1, on=True)
    fake_talk.calls.clear()
    await talk.reconcile_all()
    w2 = store.talk_room(W2)
    assert w2 is not None
    assert ("create", "admin", ("Gameworld: Burg",)) in fake_talk.calls
    assert fake_talk.read_only[token] is True
    assert ("ensure_private", "admin", (token,)) in fake_talk.calls


async def test_reconcile_removes_room_of_vanished_world(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    store.delete_world(W1)
    await talk.reconcile_all()
    assert store.talk_room(W1) is None
    assert token not in fake_talk.rooms


async def test_room_deleted_in_talk_is_recreated(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    old = _token(store)
    fake_talk.rooms.pop(old)
    await talk.sync_members(W1)
    assert store.talk_room(W1) is None
    await talk.reconcile_all()
    assert _token(store) != old


async def test_owner_no_longer_admin_acts_as_first_admin(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    store.set_meta(META_TIME_ADMINS, json.dumps(["papa"]))
    fake_talk.calls.clear()
    await talk.sync_members(W1)
    assert {c[1] for c in fake_talk.calls} == {"papa"}
    status = await talk.status("papa")
    assert status.available is True
    by_world = {w.world_id: w for w in status.worlds}
    assert by_world[W1].owner_not_admin is True
    assert by_world[W1].has_room is True
    assert by_world[W2].has_room is False


async def test_reconcile_isolates_errors_and_logs_no_names(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms, caplog: pytest.LogCaptureFixture
) -> None:
    await talk.ensure_room(W1, "admin")
    original = fake_talk.participants

    async def broken(acting_uid: str, token: str) -> list[RoomMember]:
        if token == _token(store, W1):
            raise TalkUnavailableError("gw-kind")
        return await original(acting_uid, token)

    fake_talk.participants = broken  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        await talk.reconcile_all()
    assert store.talk_room(W2) is not None
    assert W1 in caplog.text
    assert "TalkUnavailableError" in caplog.text
    assert "gw-kind" not in caplog.text
    assert "papa" not in caplog.text


async def test_set_read_only_stores_and_applies(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    token = _token(store)
    assert await talk.set_read_only(W1, on=True) is True
    row = store.talk_room(W1)
    assert row is not None
    assert row.read_only is True
    assert fake_talk.read_only[token] is True
    assert await talk.set_read_only(W1, on=False) is True
    assert fake_talk.read_only[token] is False


async def test_set_read_only_keeps_flag_when_talk_fails(
    talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms
) -> None:
    await talk.ensure_room(W1, "admin")
    fake_talk.error = TalkUnavailableError("weg")
    assert await talk.set_read_only(W1, on=True) is False
    row = store.talk_room(W1)
    assert row is not None
    assert row.read_only is True


async def test_schedule_and_drain(talk: TalkService, store: WorldStore, fake_talk: FakeTalkRooms) -> None:
    talk.schedule_ensure(W1, "admin")
    await talk.drain()
    assert store.talk_room(W1) is not None
    store.apply_world_access(W1, {"gw-kind2": "v2"})
    talk.schedule_sync(W1)
    await talk.drain()
    assert "gw-kind2" in _members(fake_talk, _token(store))
    fake_talk.error = RuntimeError("kaputt")
    talk.schedule_delete(W1)
    await talk.drain()
    row = store.talk_room(W1)
    assert row is not None
    assert row.state == TALK_STATE_DELETE_PENDING


def test_singleton_follows_store(store: WorldStore) -> None:
    first = get_talk_service(store)
    assert get_talk_service(store) is first
