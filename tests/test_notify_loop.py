"""Benachrichtigungs-Loop: Fremdversuche, Rückblick, Wartung und NcNotifier (04.1-04)."""

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

from gameworld.config import load_settings
from gameworld.notify import loop
from gameworld.notify import service as notify_service
from gameworld.notify.loop import META_LINK_ORIGIN, maintain_once, run_once
from gameworld.playtime.engine import META_TIME_ADMINS
from gameworld.provisioner.client import DockerProvisioner
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldStore
from tests.conftest import FakeDirectory, FakeNotifier
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
    assert message == "{player} wollte um {time} Uhr beitreten."
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
    # Neustart: neuer Dienst, frischer Loop-Zustand, gleiche Datenbank.
    loop.LOOP_STATE = loop.LoopState()
    restarted = WorldService(store, cast(DockerProvisioner, FakeProvisioner()), load_settings())
    await _run(restarted, fake_notifier, fake_directory, _epoch(21, 0))
    assert len(fake_notifier.calls) == 1


async def test_review_without_play_sends_nothing_but_marks_day_done(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    """WR-03: Ohne Spielzeit bis zur Uhrzeit keine Nachricht, und spätes Spielen löst keine mehr aus."""
    await _run(service, fake_notifier, fake_directory, _epoch(20, 0))
    assert fake_notifier.calls == []
    assert store.review_was_sent("admin", DAY)
    assert store.review_was_sent("mama", DAY)
    # Ein Kind fängt um 20:10 an (noch im Fenster): kein "Heute gespielt: Lena 1 Min." mit Teildaten.
    store.book_usage(W1, DAY, {}, {}, play={"gw-kind": 60})
    await _run(service, fake_notifier, fake_directory, _epoch(20, 10))
    assert fake_notifier.calls == []


async def test_review_not_sent_after_window_when_play_starts_late(
    service: WorldService, store: WorldStore, fake_notifier: FakeNotifier, fake_directory: FakeDirectory
) -> None:
    """WR-03, Beispiel aus dem Review: Vorgabe 20:00, ExApp lief bis 21:30 nicht, Spiel ab 21:30."""
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
    # Positivkontrolle: im Fenster nach 0:15 kommt er.
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

    monkeypatch.setattr(loop, "MAINTENANCE", [hook])
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

    monkeypatch.setattr(loop, "MAINTENANCE", [hook])
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
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(calls) >= 2


def _fake_app(monkeypatch: pytest.MonkeyPatch, error: Exception | None = None) -> MagicMock:
    app = MagicMock()
    app.set_user = AsyncMock()
    app.notifications.create = AsyncMock(side_effect=error, return_value="obj")
    monkeypatch.setattr(notify_service, "AsyncNextcloudApp", lambda: app)
    return app


async def test_nc_notifier_sets_user_and_creates(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _fake_app(monkeypatch)
    params = {"world": {"type": "highlight", "id": W1, "name": "Wiese"}}
    ok = await notify_service.NcNotifier().notify("mama", "S {world}", "M {world}", params, "https://x/y")
    assert ok
    app.set_user.assert_awaited_once_with("mama")
    app.notifications.create.assert_awaited_once_with(
        "S {world}", "M {world}", subject_params=params, message_params=params, link="https://x/y"
    )


@pytest.mark.parametrize("error", [NextcloudException(404, "Not found"), NextcloudException(500), RuntimeError("x")])
async def test_nc_notifier_errors_return_false(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, error: Exception
) -> None:
    app = _fake_app(monkeypatch, error)
    ok = await notify_service.NcNotifier().notify("mama", "S", "M", {}, "https://x/y")
    assert not ok
    assert app.notifications.create.await_count == 1
    assert "mama" not in caplog.text
