"""Manager snapshot in the background (CR-01): only admins confirmed by Nextcloud.

Review scenario: accounts ``anna`` and ``papa`` are in the snapshot, ``anna``
loses the admin rights (ex-partner, an older child accidentally made admin).
After that ``anna`` may neither receive child data nor be pulled into Talk
rooms, no new room belongs to her, and her ``frei`` row is dropped.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from nc_py_api import NextcloudException

from gameworld.access.directory import DirectoryRejectedError, DirectoryUnavailableError, NcDirectory
from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.notify import loop
from gameworld.notify.loop import META_LINK_ORIGIN, maintain_once, run_once, verify_once
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.talk.rooms import RoomMember
from gameworld.talk.service import get_talk_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import (
    FakeDirectory,
    FakeNotifier,
    FakeTalkRooms,
    appapi_headers,
    assert_closed,
    give_rules,
    install_fake_nc,
)
from tests.test_pause_api import VERIFIER, _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 21)


def _epoch(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 21, hour, minute, tzinfo=BERLIN).timestamp())


def _snapshot(store: WorldStore) -> list[str]:
    return json.loads(store.get_meta(META_TIME_ADMINS) or "null")


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    give_rules(world_store, "gw-kind")
    world_store.insert_player(PlayerRow(nc_user="anna", player_name="Anna", rotation=0))
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER, "anna": VERIFIER})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["anna", "papa"]))
    world_store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    return world_store


@pytest.fixture
def service(store: WorldStore, monkeypatch: pytest.MonkeyPatch) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    # Pin the engine clock to the test epoch: the engine prunes usage older than 7 days
    # against its clock, so a real clock would delete the rows booked on the fixed DAY.
    monkeypatch.setattr(world_service.time, "_clock", lambda: float(_epoch(20, 1)))
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


@pytest.fixture
def anna_lost_admin(fake_directory: FakeDirectory) -> FakeDirectory:
    """Nextcloud as on the dev stack: only admins resolve groups; anna is none any more."""
    fake_directory.strict = True
    fake_directory.groups["admin"] = ["papa"]
    fake_directory.users["papa"] = ("Papa", True)
    fake_directory.users["anna"] = ("Anna", True)
    return fake_directory


async def test_first_admin_lost_rights_is_dropped_and_next_one_acts(
    service: WorldService, store: WorldStore, anna_lost_admin: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        del world_service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, anna_lost_admin)
    assert anna_lost_admin.group_calls == [("anna", "admin"), ("papa", "admin")]
    assert _snapshot(store) == ["papa"]
    assert seen == ["papa"]
    assert loop.LOOP_STATE.acting == "papa"


async def test_ex_admin_gets_no_attempt_or_review_after_check(
    service: WorldService,
    store: WorldStore,
    anna_lost_admin: FakeDirectory,
    fake_notifier: FakeNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop, "MAINTENANCE", [])
    store.add_outbox(W1, "deny", "Fremder", _epoch(20, 0))
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 2700})
    await verify_once(service, anna_lost_admin)
    await run_once(service, fake_notifier, anna_lost_admin, _epoch(20, 1))
    recipients = {call[0] for call in fake_notifier.calls}
    # Positive control: papa gets the foreign attempt and the review, anna nothing.
    assert recipients == {"papa"}
    assert {call[1] for call in fake_notifier.calls} == {"Unbekannter Spielername in {world}", "Tagesrückblick"}
    # Directory calls (display names) only as a confirmed manager.
    assert {acting for acting, _uid in anna_lost_admin.calls} <= {"papa"}


async def test_notify_forever_checks_before_first_send(
    service: WorldService,
    store: WorldStore,
    anna_lost_admin: FakeDirectory,
    fake_notifier: FakeNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loop, "MAINTENANCE", [])
    store.add_outbox(W1, "deny", "Fremder", int(datetime.now(BERLIN).timestamp()))
    task = asyncio.create_task(loop.notify_forever(service, interval_seconds=0.01))
    for _ in range(200):
        if fake_notifier.calls:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert [call[0] for call in fake_notifier.calls] == ["papa"]


async def test_ex_admin_loses_frei_line(
    service: WorldService, store: WorldStore, anna_lost_admin: FakeDirectory
) -> None:
    before, _changed = service.time.render(W1)
    assert b"Anna -1 -1 -1 frei" in before
    await verify_once(service, anna_lost_admin)
    after, _changed = service.time.render(W1)
    # Without rules and without frei, anna is no longer in the rules file at all.
    assert b"Anna" not in after


async def test_all_accounts_rejected_empties_snapshot_and_skips_hooks(
    service: WorldService,
    store: WorldStore,
    anna_lost_admin: FakeDirectory,
    fake_notifier: FakeNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anna_lost_admin.groups["admin"] = ["neu"]
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        del world_service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, anna_lost_admin)
    assert _snapshot(store) == []
    assert seen == []
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await run_once(service, fake_notifier, anna_lost_admin, _epoch(18, 6))
    assert fake_notifier.calls == []


async def test_rejection_while_app_not_accepted_keeps_snapshot(
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    fake_notifier: FakeNotifier,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Start/re-registration: Nextcloud itself rejects the ExApp, every account gets 401.
    fake_directory.error = DirectoryRejectedError("401")
    fake_directory.app_ok = False
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        del world_service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, fake_directory)
    assert _snapshot(store) == ["anna", "papa"]
    assert seen == []
    assert loop.LOOP_STATE.acting is None
    # Counter-check before the queries: a later probe might already succeed while
    # the queries were still rejected (race observed on the dev stack).
    assert fake_directory.group_calls == []
    # As soon as Nextcloud accepts the ExApp again, the next run confirms and notices go out.
    fake_directory.error = None
    fake_directory.app_ok = True
    fake_directory.groups["admin"] = ["papa"]
    assert await verify_once(service, fake_directory) == "papa"
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await run_once(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert [call[0] for call in fake_notifier.calls] == ["papa"]


async def test_rejection_with_app_accepted_still_empties_snapshot(
    service: WorldService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    # Counter-check succeeds: 401/403 concerns the accounts themselves (deleted, no longer admin), fail closed.
    fake_directory.error = DirectoryRejectedError("401")
    assert await verify_once(service, fake_directory) is None
    assert _snapshot(store) == []


async def test_outage_keeps_snapshot_but_confirms_nobody(
    service: WorldService, store: WorldStore, fake_directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_directory.error = DirectoryUnavailableError("weg")
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        del world_service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, fake_directory)
    # A failure is not a rejection: the state stays, but nobody acts.
    assert _snapshot(store) == ["anna", "papa"]
    assert seen == []
    assert loop.LOOP_STATE.acting is None


async def test_account_missing_from_its_own_answer_is_not_confirmed(
    service: WorldService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    fake_directory.groups["admin"] = ["papa"]
    acting = await verify_once(service, fake_directory)
    assert acting == "papa"
    assert fake_directory.group_calls == [("anna", "admin"), ("papa", "admin")]
    assert _snapshot(store) == ["papa"]


async def test_ex_admin_removed_from_kids_room_and_never_owner(
    service: WorldService, store: WorldStore, anna_lost_admin: FakeDirectory, fake_talk: FakeTalkRooms
) -> None:
    store.insert_talk_room(W1, "tok-w1", "papa", "2026-10-21T18:00:00+00:00")
    fake_talk.rooms["tok-w1"] = [
        RoomMember(10, "users", "papa", 1),
        RoomMember(11, "users", "anna", 2),
        RoomMember(12, "users", "gw-kind", 3),
    ]
    await maintain_once(service, anna_lost_admin)
    # anna is invited to W1 as a player: she stays a participant, but without moderation.
    by_actor = {m.actor_id: m.participant_type for m in fake_talk.rooms["tok-w1"]}
    assert by_actor == {"papa": 1, "anna": 3, "gw-kind": 3}
    assert ("demote", "papa", ("tok-w1", 11)) in fake_talk.calls
    # She is not invited to W2: the new room belongs to papa, anna is not in it.
    new_room = store.talk_room(W2)
    assert new_room is not None
    assert new_room.owner_uid == "papa"
    assert "anna" not in {m.actor_id for m in fake_talk.rooms[new_room.token]}
    assert all(call[1] != "anna" for call in fake_talk.calls)
    await get_talk_service(store).drain()


async def test_ex_admin_without_invite_is_removed_from_room(
    service: WorldService, store: WorldStore, anna_lost_admin: FakeDirectory, fake_talk: FakeTalkRooms
) -> None:
    store.apply_world_access(W1, {"gw-kind": VERIFIER})
    store.insert_talk_room(W1, "tok-w1", "papa", "2026-10-21T18:00:00+00:00")
    fake_talk.rooms["tok-w1"] = [
        RoomMember(10, "users", "papa", 1),
        RoomMember(11, "users", "anna", 2),
        RoomMember(12, "users", "gw-kind", 3),
    ]
    await maintain_once(service, anna_lost_admin)
    assert {m.actor_id for m in fake_talk.rooms["tok-w1"]} == {"papa", "gw-kind"}
    assert ("remove_attendee", "papa", ("tok-w1", 11)) in fake_talk.calls


async def test_handy_pages_refresh_snapshot_with_verified_admin(
    client: httpx.AsyncClient, service: WorldService, store: WorldStore, fake_directory: FakeDirectory
) -> None:
    del service
    fake_directory.strict = True
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "anna"]))
    response = await client.get("/api/review", params={"day": "2026-10-21"}, headers=appapi_headers())
    assert response.status_code == 200, response.text
    assert fake_directory.group_calls == [("admin", "admin")]
    assert _snapshot(store) == ["admin"]


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/review?day=2026-10-21", None),
        ("GET", "/api/attempts?day=2026-10-21", None),
        ("GET", "/api/pause", None),
        ("POST", "/api/pause", {"minutes": 15}),
    ],
)
async def test_kid_never_triggers_refresh(
    client: httpx.AsyncClient,
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    method: str,
    path: str,
    body: dict[str, int] | None,
) -> None:
    del service
    response = await client.request(method, path, json=body, headers=appapi_headers("gw-kind"))
    assert response.status_code == 403
    assert fake_directory.group_calls == []
    assert _snapshot(store) == ["anna", "papa"]


def _fake_nc(monkeypatch: pytest.MonkeyPatch, error: Exception) -> MagicMock:
    app = MagicMock()
    app.ocs = AsyncMock(side_effect=error)
    install_fake_nc(monkeypatch, app)
    return app


@pytest.mark.parametrize("status", [401, 403, 997])
async def test_nc_directory_rejection_is_its_own_error(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    app = _fake_nc(monkeypatch, NextcloudException(status, "nein"))
    with pytest.raises(DirectoryRejectedError):
        await NcDirectory().group_members("anna", "admin")
    assert_closed(app, times=1)


async def test_nc_directory_app_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    app = MagicMock()
    app.appconfig_ex.get_value = AsyncMock(return_value=None)
    install_fake_nc(monkeypatch, app)
    assert await NcDirectory().app_accepted() is True
    assert_closed(app, times=1)


@pytest.mark.parametrize("error", [NextcloudException(401, "nein"), NextcloudException(500), OSError("weg")])
async def test_nc_directory_app_not_accepted(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    app = MagicMock()
    app.appconfig_ex.get_value = AsyncMock(side_effect=error)
    install_fake_nc(monkeypatch, app)
    assert await NcDirectory().app_accepted() is False
    assert_closed(app, times=1)


@pytest.mark.parametrize("error", [NextcloudException(500), NextcloudException(408), OSError("weg")])
async def test_nc_directory_outage_is_no_rejection(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    app = _fake_nc(monkeypatch, error)
    with pytest.raises(DirectoryUnavailableError) as info:
        await NcDirectory().group_members("papa", "admin")
    assert not isinstance(info.value, DirectoryRejectedError)
    assert_closed(app, times=1)
