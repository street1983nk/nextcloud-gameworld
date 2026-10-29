"""Notification loop: foreign attempts, review, maintenance and NcNotifier (04.1-04)."""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest
from nc_py_api import NextcloudException

from gameworld.access.directory import DirectoryUnavailableError
from gameworld.config import load_settings
from gameworld.notify import loop
from gameworld.notify import service as notify_service
from gameworld.notify.loop import META_LINK_ORIGIN, maintain_once, run_once
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import FakeDirectory, FakeNotifier, assert_closed, give_rules, install_fake_nc
from tests.test_pause_api import VERIFIER, _row
from tests.test_service_lifecycle import FakeProvisioner

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 10, 21)
EMBED = "https://cloud.example/index.php/apps/app_api/embedded/gameworld/gameworld"


def _epoch(hour: int, minute: int = 0) -> int:
    return int(datetime(2026, 10, 21, hour, minute, tzinfo=BERLIN).timestamp())


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    world_store.insert_world(_row(W1, "Wiese", 30015))
    world_store.insert_world(_row(W2, "Burg", 30016))
    world_store.insert_player(PlayerRow(nc_user="gw-kind", player_name="Lena", rotation=0))
    give_rules(world_store, "gw-kind")
    world_store.apply_world_access(W1, {"gw-kind": VERIFIER})
    world_store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "mama"]))
    world_store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    return world_store


@pytest.fixture
def service(store: WorldStore) -> WorldService:
    return WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())


async def _run(service: WorldService, notifier: FakeNotifier, directory: FakeDirectory, now: int) -> None:
    await run_once(service, notifier, directory, now)


async def test_deny_notifies_every_admin_with_deep_link(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert [call[0] for call in fake_notifier.calls] == ["admin", "mama"]
    uid, subject, message, params, link = fake_notifier.calls[0]
    del uid
    assert subject == "Unbekannter Spielername in {world}"
    assert message == "{player} wollte um {time} beitreten."
    assert params["player"]["name"] == "Fremder"
    assert params["world"]["name"] == "Wiese"
    assert params["time"]["name"] == "18:05"
    assert link == f"{EMBED}/versuch?welt={W1}&tag=2026-10-21"
    assert store.outbox_batch() == []
    assert [row.player_name for row in store.attempts(DAY)] == ["Fremder"]


async def test_deny_throttled_per_name_world_day_and_case_variants_ignored(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    store.add_outbox(W1, "deny", "fremder", _epoch(18, 7))
    store.add_outbox(W1, "deny", "LENA", _epoch(18, 8))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 9))
    assert len(fake_notifier.calls) == 2
    assert store.outbox_batch() == []
    assert [(row.player_name, row.count) for row in store.attempts(DAY)] == [("Fremder", 2)]


async def test_deny_summary_after_five(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    for index in range(7):
        store.add_outbox(W1, "deny", f"Fremd{index}", _epoch(18, index))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 30))
    subjects = [call[1] for call in fake_notifier.calls]
    assert subjects == ["Unbekannter Spielername in {world}"] * 5 + ["Weitere Beitrittsversuche"]
    assert fake_notifier.calls[-1][4] == f"{EMBED}/versuch?tag=2026-10-21"


async def test_empty_admin_snapshot_sends_nothing(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.set_meta(META_TIME_ADMINS, "[]")
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 2700})
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert fake_notifier.calls == []
    assert store.outbox_batch() == []


async def test_deleted_world_and_rows_without_handler_are_dropped(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.add_outbox("bbbbbbbbbbb1", "deny", "Fremder", _epoch(18, 5))
    store.add_outbox(W1, "unbekannt", "Lena", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert fake_notifier.calls == []
    assert store.outbox_batch() == []


async def test_origin_falls_back_to_nextcloud_url_and_missing_means_no_send(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.set_meta(META_LINK_ORIGIN, "")
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert fake_notifier.calls[0][4].startswith("http://localhost:8091/index.php/apps/app_api/embedded/")
    fake_notifier.calls.clear()
    monkeypatch.delenv("NEXTCLOUD_URL")
    store.add_outbox(W1, "deny", "Anderer", _epoch(18, 7))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 8))
    assert fake_notifier.calls == []
    assert {row.player_name for row in store.attempts(DAY)} == {"Fremder", "Anderer"}


async def test_missing_origin_does_not_use_up_daily_hints(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IN-05: without a link address the 5 single notices of the day are preserved."""
    store.set_meta(META_LINK_ORIGIN, "")
    monkeypatch.delenv("NEXTCLOUD_URL")
    for index in range(6):
        store.add_outbox(W1, "deny", f"Fremd{index}", _epoch(18, index))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 10))
    assert fake_notifier.calls == []
    assert len(store.attempts(DAY)) == 6
    store.set_meta(META_LINK_ORIGIN, "https://cloud.example")
    store.add_outbox(W1, "deny", "Fremd0", _epoch(18, 20))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 21))
    assert [call[1] for call in fake_notifier.calls] == ["Unbekannter Spielername in {world}"] * 2


async def test_nextcloud_url_with_webroot_gives_working_links(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WR-04: NEXTCLOUD_URL with a subfolder (and /index.php) no longer drops out."""
    store.set_meta(META_LINK_ORIGIN, "")
    monkeypatch.setenv("NEXTCLOUD_URL", "https://example.org/nextcloud/index.php/")
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert fake_notifier.calls[0][4].startswith(
        "https://example.org/nextcloud/index.php/apps/app_api/embedded/gameworld/gameworld/versuch?"
    )


async def test_handler_error_is_isolated(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(context: loop.NotifyContext, row: object) -> None:
        del context, row
        raise RuntimeError("kaputt")

    monkeypatch.setitem(loop.HANDLERS, "kaputt", broken)
    store.add_outbox(W1, "kaputt", "", _epoch(18, 4))
    store.add_outbox(W1, "deny", "Fremder", _epoch(18, 5))
    await _run(service, fake_notifier, fake_directory, _epoch(18, 6))
    assert len(fake_notifier.calls) == 2
    assert store.outbox_batch() == []


async def test_review_once_per_admin_and_day_even_after_restart(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 2000})
    store.book_usage(W2, DAY, {}, {}, play={"gw-kind": 700})
    await _run(service, fake_notifier, fake_directory, _epoch(19, 59))
    assert fake_notifier.calls == []
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert len(fake_notifier.calls) == 1
    uid, subject, message, params, link = fake_notifier.calls[0]
    assert uid == "admin"
    assert subject == "Tagesrückblick"
    assert message == "Heute gespielt: {kids}"
    assert params["kids"]["name"] == "Kind (Dev) 45 Min."
    assert link == f"{EMBED}/rueckblick?tag=2026-10-21"
    await _run(service, fake_notifier, fake_directory, _epoch(20, 5))
    # Restart: new service, fresh loop state, same database.
    loop.LOOP_STATE = loop.LoopState()
    restarted = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    await _run(restarted, fake_notifier, fake_directory, _epoch(21, 0))
    assert len(fake_notifier.calls) == 1


async def test_review_notification_never_names_guest_without_rules(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    """IN-03: guest child without rules does not appear with minutes in the evening notification."""
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    store.insert_player(PlayerRow(nc_user="gast-kind", player_name="Gast", rotation=0))
    fake_directory.users["gast-kind"] = ("Gast Kind", True)
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 600, "gast-kind": 1800})
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert [call[3]["kids"]["name"] for call in fake_notifier.calls] == ["Kind (Dev) 10 Min."]


async def test_review_with_only_guest_play_sends_nothing(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.insert_player(PlayerRow(nc_user="gast-kind", player_name="Gast", rotation=0))
    store.book_usage(W1, DAY, {}, {}, play={"gast-kind": 1800})
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert fake_notifier.calls == []


async def test_verified_maintenance_drops_review_prefs_of_former_admins(
    service: WorldService, store: WorldStore, fake_directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IN-03: review settings of earlier managers do not linger indefinitely."""
    monkeypatch.setattr(loop, "MAINTENANCE", [])
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin", "anna"]))
    store.set_review_pref("anna", enabled=True, minute=600)
    store.set_review_pref("admin", enabled=False, minute=1200)
    fake_directory.groups["admin"] = ["admin"]
    await maintain_once(service, fake_directory)
    assert store.review_pref("anna") == (True, 1200)  # default: row gone
    assert store.review_pref("admin") == (False, 1200)


async def test_outage_keeps_review_prefs(
    service: WorldService, store: WorldStore, fake_directory: FakeDirectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross-check: without a confirmed state nothing is deleted."""
    monkeypatch.setattr(loop, "MAINTENANCE", [])
    store.set_review_pref("mama", enabled=False, minute=600)
    fake_directory.error = DirectoryUnavailableError("weg")
    await maintain_once(service, fake_directory)
    assert store.review_pref("mama") == (False, 600)


async def test_review_without_play_sends_nothing_but_marks_day_done(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    """WR-03: without playtime until the time of day no message, and late play triggers none any more."""
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert fake_notifier.calls == []
    assert store.review_was_sent("admin", DAY)
    assert store.review_was_sent("mama", DAY)
    # A child starts at 20:10 (still in the window): no "Heute gespielt: Lena 1 Min." with partial data.
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 60})
    await _run(service, fake_notifier, fake_directory, _epoch(20, 10))
    assert fake_notifier.calls == []


async def test_review_not_sent_after_window_when_play_starts_late(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    """WR-03, example from the review: default 20:00, ExApp was down until 21:30, play from 21:30."""
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 60})
    await _run(service, fake_notifier, fake_directory, _epoch(21, 30))
    assert fake_notifier.calls == []
    assert not store.review_was_sent("admin", DAY)


async def test_early_review_time_does_not_fire_in_the_morning(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    store.set_review_pref("admin", enabled=True, minute=15)
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 600})
    await _run(service, fake_notifier, fake_directory, _epoch(9, 0))
    assert fake_notifier.calls == []
    # Positive control: in the window after 0:15 it comes.
    await _run(service, fake_notifier, fake_directory, _epoch(0, 20))
    assert [call[1] for call in fake_notifier.calls] == ["Tagesrückblick"]


async def test_review_respects_pref_and_falls_back_to_player_name(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    store.set_review_pref("admin", enabled=False, minute=1200)
    store.set_review_pref("mama", enabled=True, minute=1230)
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 20})
    fake_directory.users.pop("gw-kind")
    await _run(service, fake_notifier, fake_directory, _epoch(20, 15))
    assert fake_notifier.calls == []
    await _run(service, fake_notifier, fake_directory, _epoch(20, 30))
    assert [(call[0], call[3]["kids"]["name"]) for call in fake_notifier.calls] == [("mama", "Lena 1 Min.")]


async def test_maintenance_refreshes_snapshot_and_runs_hooks(
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.set_meta(META_TIME_ADMINS, json.dumps(["admin"]))
    fake_directory.groups["admin"] = ["admin", "mama"]
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        assert world_service is service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, fake_directory)
    assert json.loads(store.get_meta(META_TIME_ADMINS) or "[]") == ["admin", "mama"]
    assert seen == ["admin"]


async def test_maintenance_with_empty_snapshot_does_nothing(
    service: WorldService,
    store: WorldStore,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.set_meta(META_TIME_ADMINS, "[]")
    seen: list[str] = []

    async def hook(world_service: WorldService, acting_uid: str) -> None:
        del world_service
        seen.append(acting_uid)

    monkeypatch.setattr(loop, "MAINTENANCE", [(hook, False)])
    await maintain_once(service, fake_directory)
    assert fake_directory.group_calls == []
    assert seen == []


async def test_notify_forever_survives_errors(service: WorldService, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def failing(*args: object) -> None:
        del args
        calls.append(1)
        raise RuntimeError("kaputt")

    monkeypatch.setattr(loop, "run_once", failing)
    task = asyncio.create_task(loop.notify_forever(service, interval_seconds=0.01))
    # Wait for the event instead of a fixed time: the first maintenance (check of the
    # snapshot before the first send) takes longer on slow machines.
    for _ in range(500):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 2


def _fake_app(monkeypatch: pytest.MonkeyPatch, error: Exception | None = None) -> MagicMock:
    app = MagicMock()
    app.notifications.create = AsyncMock(side_effect=error, return_value="obj")
    app.recorder = install_fake_nc(monkeypatch, app)
    return app


async def test_nc_notifier_sets_user_and_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _fake_app(monkeypatch)
    params = {"world": {"type": "highlight", "id": W1, "name": "Wiese"}}
    ok = await notify_service.NcNotifier().notify("mama", "S {world}", "M {world}", params, "https://x/y")
    assert ok
    assert app.recorder.users == ["mama"]
    app.notifications.create.assert_awaited_once_with(
        "S {world}", "M {world}", subject_params=params, message_params=params, link="https://x/y"
    )
    assert_closed(app, times=1)


@pytest.mark.parametrize("error", [NextcloudException(404, "Not found"), NextcloudException(500), RuntimeError("x")])
async def test_nc_notifier_errors_return_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    app = _fake_app(monkeypatch, error)
    ok = await notify_service.NcNotifier().notify("mama", "S", "M", {}, "https://x/y")
    assert not ok
    assert app.notifications.create.await_count == 1
    assert_closed(app, times=1)
    assert "mama" not in caplog.text


async def test_maintenance_runs_as_own_task_and_does_not_block_sending(
    service: WorldService,
    store: WorldStore,
    fake_notifier: FakeNotifier,
    fake_directory: FakeDirectory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IN-06: a hanging Talk reconciliation delays no foreign-attempt notices; shutdown cancels it."""
    fake_directory.groups["admin"] = ["admin", "mama"]
    hook_started = asyncio.Event()
    hook_cancelled: list[bool] = []

    async def hanging(world_service: WorldService, acting_uid: str) -> None:
        del world_service, acting_uid
        hook_started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            hook_cancelled.append(True)
            raise

    monkeypatch.setattr(loop, "MAINTENANCE", [(hanging, False)])
    store.add_outbox(W1, "deny", "Fremder", int(datetime.now(BERLIN).timestamp()))
    task = asyncio.create_task(loop.notify_forever(service, interval_seconds=0.01))
    await asyncio.wait_for(hook_started.wait(), timeout=5)
    for _ in range(500):
        if fake_notifier.calls:
            break
        await asyncio.sleep(0.01)
    assert {call[0] for call in fake_notifier.calls} == {"admin", "mama"}
    maintenance = loop.LOOP_STATE.maintenance_task
    assert maintenance is not None
    assert not maintenance.done()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert maintenance.done()
    assert hook_cancelled == [True]
