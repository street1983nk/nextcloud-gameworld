"""TimeEngine: booking, rendering, generation, end-of-day boundary and opt-in (04-03)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from gameworld.playtime.engine import META_TIME_ADMINS, TimeEngine, parse_admins
from gameworld.playtime.pause import ART_PAUSE, ART_SCHLUSS, PauseState
from gameworld.playtime.plan import DayRule, WeekPlan, day_bounds, day_starts, load_zone, local_day
from gameworld.provisioner.time_mod import LEDGER_HEADER, Ledger
from gameworld.worlds.store import PlayerRow, WorldRow, WorldStore

# Sat 2026-10-24 12:00 Europe/Berlin (golden vector 1792792800 = start of day, plus 12 h).
FIXED = 1792836000
VERIFIER = "#1#c2FsdA==#dmVyaWZpZXI="
ZONE = load_zone("")
TODAY = local_day(FIXED, ZONE)


def _clock() -> float:
    return float(FIXED)


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


@pytest.fixture
def engine(store: WorldStore) -> TimeEngine:
    return TimeEngine(store, clock=_clock)


def _world(store: WorldStore, world_id: str, port: int) -> None:
    store.insert_world(
        WorldRow(
            id=world_id,
            name="Welt",
            port=port,
            container_name=f"gw-x-{world_id}",
            volume_name=f"gw-x-{world_id}",
            world_key="k",
            engine_version="5.17.0",
            desired_state="running",
            op_state="ready",
            last_error=None,
            created_at="2026-10-24T10:00:00+00:00",
        )
    )


def _player(store: WorldStore, nc_user: str, name: str) -> None:
    store.insert_player(PlayerRow(nc_user=nc_user, player_name=name, rotation=0))


def _invite(store: WorldStore, world_id: str, nc_user: str) -> None:
    store.apply_world_access(world_id, {**store.world_access(world_id), nc_user: VERIFIER})


def _week(*, allowed: bool = True, limit: int | None = None, ws: int | None = None, we: int | None = None) -> WeekPlan:
    return WeekPlan({weekday: DayRule(allowed, limit, ws, we) for weekday in range(1, 8)})


def _plan(store: WorldStore, nc_user: str, normal: WeekPlan, holiday: WeekPlan | None = None) -> None:
    store.set_child_plan(nc_user, normal, holiday, "admin", "2026-10-24T10:00:00+00:00")


def _lines(data: bytes) -> list[str]:
    return data.decode("ascii").split("\n")


def _line(data: bytes, name: str) -> list[str] | None:
    for line in _lines(data):
        parts = line.split(" ")
        if parts and parts[0] == name:
            return parts
    return None


def _generation(data: bytes) -> int:
    return int(_lines(data)[0].split(" ")[2])


# Booking


def test_book_increments_only_children_with_rules(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _player(store, "gw-leo", "Leo")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_ledger_seen("w1", {"Mia": 40})

    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Mia": 55, "Leo": 7}))

    assert store.usage("gw-mia", TODAY) == 15
    assert store.usage("gw-leo", TODAY) == 0
    assert store.ledger_seen("w1") == {"Mia": 55, "Leo": 7}


def test_book_first_contact_only_anchors(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))

    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Mia": 100}))

    assert store.usage("gw-mia", TODAY) == 0
    assert store.ledger_seen("w1") == {"Mia": 100}


def test_book_is_atomic_no_double_count_after_failure(engine: TimeEngine, store: WorldStore, app_env: Path) -> None:
    """WR-05: if anchoring fails, usage stays old as well; the next tick counts exactly once."""
    import sqlite3

    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_ledger_seen("w1", {"Mia": 40})
    db = sqlite3.connect(app_env / "gameworld.sqlite3")
    with db:
        db.execute(
            "CREATE TRIGGER fail_seen BEFORE INSERT ON time_ledger_seen BEGIN SELECT RAISE(ABORT, 'gesperrt'); END"
        )
    ledger = Ledger(written_at=FIXED, generation=1, seconds={"Mia": 100})

    with pytest.raises(sqlite3.IntegrityError):
        engine.book("w1", ledger)
    assert store.usage("gw-mia", TODAY) == 0
    assert store.ledger_seen("w1") == {"Mia": 40}

    with db:
        db.execute("DROP TRIGGER fail_seen")
    db.close()
    engine.book("w1", ledger)
    assert store.usage("gw-mia", TODAY) == 60
    assert store.ledger_seen("w1") == {"Mia": 100}


def test_book_none_changes_nothing(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_ledger_seen("w1", {"Mia": 40})

    engine.book("w1", None)

    assert store.usage("gw-mia", TODAY) == 0
    assert store.ledger_seen("w1") == {"Mia": 40}


# Rendering


def test_render_cap_for_child_with_limit(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    store.set_ledger_seen("w1", {"Mia": 900})
    store.add_usage("gw-mia", TODAY, 2700)

    data, changed = engine.render("w1")

    assert changed is True
    parts = _line(data, "Mia")
    assert parts is not None
    # cap = seen (900) + rest (3600 - 2700 = 900) = 1800, reason ok.
    assert parts[1] == "1800"
    assert parts[4] == "ok"
    # The window never ends after the local end of day (O-04).
    assert int(parts[3]) <= day_bounds(TODAY, ZONE)[1]


def _base(data: bytes, name: str) -> int | None:
    for line in _lines(data):
        parts = line.split(" ")
        if parts[:2] == ["@base", name]:
            return int(parts[2])
    return None


def test_render_base_anchor_follows_cap_not_every_tick(engine: TimeEngine, store: WorldStore) -> None:
    """WR-06: @base = seen state against which the cap is calculated; stays as long as the cap stays."""
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    store.set_ledger_seen("w1", {"Mia": 900})

    first, _ = engine.render("w1")
    assert _base(first, "Mia") == 900
    mia = _line(first, "Mia")
    assert mia is not None
    assert mia[1] == "4500"

    # Mia plays 120 s here: usage and seen state grow equally, the cap stays.
    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Mia": 1020}))
    second, changed = engine.render("w1")
    assert changed is False
    assert second == first

    # Usage from another world: cap drops, the anchor follows the new state.
    store.add_usage("gw-mia", TODAY, 300)
    third, changed = engine.render("w1")
    assert changed is True
    assert _base(third, "Mia") == 1020
    # Without a limit no cap and no anchor.
    _plan(store, "gw-mia", _week())
    fourth, _ = engine.render("w1")
    assert _base(fourth, "Mia") is None


def test_render_shares_quota_across_worlds(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _world(store, "w2", 30016)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=20))
    _invite(store, "w1", "gw-mia")
    _invite(store, "w2", "gw-mia")
    store.add_usage("gw-mia", TODAY, 600)
    store.set_ledger_seen("w2", {"Mia": 300})

    data, _ = engine.render("w2")

    parts = _line(data, "Mia")
    assert parts is not None
    # Cap in world B = seen_B (300) + (limit 1200 - usage 600) = 900.
    assert parts[1] == "900"


def test_render_generation_stable_without_change(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")

    first, changed1 = engine.render("w1")
    second, changed2 = engine.render("w1")

    assert changed1 is True
    assert changed2 is False
    assert second == first

    store.add_usage("gw-mia", TODAY, 60)
    third, changed3 = engine.render("w1")

    assert changed3 is True
    assert _generation(third) == _generation(first) + 1
    row = store.get_world("w1")
    assert row is not None
    assert row.time_generation == _generation(third)


def test_render_before_window_caps_coming_window(engine: TimeEngine, store: WorldStore) -> None:
    """WR-02: before the window (12:00, window 15 to 19) the cap already carries the window.

    This way the mod opens by itself from ``from`` on; with the cap ``seen + 0`` it would
    have said "Spielzeit vorbei" until the ExApp wrote again.
    """
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _player(store, "gw-leo", "Leo")
    _plan(store, "gw-mia", _week(limit=60, ws=900, we=1140))
    _plan(store, "gw-leo", _week(ws=900, we=1140))
    _invite(store, "w1", "gw-mia")
    _invite(store, "w1", "gw-leo")
    store.set_ledger_seen("w1", {"Mia": 500})
    store.add_usage("gw-mia", TODAY, 600)

    data, _ = engine.render("w1")

    mia = _line(data, "Mia")
    leo = _line(data, "Leo")
    assert mia is not None
    assert leo is not None
    start = int(datetime.combine(TODAY, time(15), tzinfo=ZONE).timestamp())
    # Reason stays window, boundaries block until 15:00; cap 500 + (3600 - 600).
    assert mia[1:5] == ["3500", str(start), mia[3], "fenster"]
    # Without a limit: no cap (-1), also before the window.
    assert leo[1] == "-1"
    assert leo[4] == "fenster"


def test_render_day_not_allowed(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    weekday = TODAY.isoweekday()
    days = {wd: DayRule(wd != weekday, 60, None, None) for wd in range(1, 8)}
    _plan(store, "gw-mia", WeekPlan(days))
    _invite(store, "w1", "gw-mia")

    data, _ = engine.render("w1")

    parts = _line(data, "Mia")
    assert parts is not None
    assert parts[4] == "tag"
    assert (parts[2], parts[3]) == ("0", "0")


def test_render_skips_children_without_rules(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _player(store, "gw-leo", "Leo")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    _invite(store, "w1", "gw-leo")

    data, _ = engine.render("w1")

    assert _line(data, "Mia") is not None
    assert _line(data, "Leo") is None


def test_render_without_rules_is_empty(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-leo", "Leo")
    _invite(store, "w1", "gw-leo")

    data, changed = engine.render("w1")

    assert changed is True
    assert _lines(data)[1:] == ["end", ""]


# Holidays and time zone (04-04)


def _not_today() -> WeekPlan:
    weekday = TODAY.isoweekday()
    return WeekPlan({wd: DayRule(wd != weekday, 60, None, None) for wd in range(1, 8)})


def test_render_holiday_plan_applies_in_holiday(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _not_today(), _week())
    _invite(store, "w1", "gw-mia")
    store.add_holiday(TODAY, TODAY, "Herbstferien")

    data, _ = engine.render("w1")

    parts = _line(data, "Mia")
    assert parts is not None
    assert parts[4] == "ok"
    assert int(parts[3]) == day_bounds(TODAY, ZONE)[1]


def test_render_holiday_ended_yesterday_uses_normal(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _not_today(), _week())
    _invite(store, "w1", "gw-mia")
    store.add_holiday(TODAY - timedelta(days=2), TODAY - timedelta(days=1), "Vorbei")

    data, _ = engine.render("w1")

    parts = _line(data, "Mia")
    assert parts is not None
    assert parts[4] == "tag"


def test_render_follows_time_zone_without_cache(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week())
    _invite(store, "w1", "gw-mia")

    berlin, _ = engine.render("w1")
    store.set_meta("time_zone", "Pacific/Kiritimati")
    kiritimati, changed = engine.render("w1")

    zone = load_zone("Pacific/Kiritimati")
    berlin_parts = _line(berlin, "Mia")
    parts = _line(kiritimati, "Mia")
    assert berlin_parts is not None
    assert parts is not None
    assert changed is True
    assert int(berlin_parts[3]) == day_bounds(TODAY, ZONE)[1]
    assert int(parts[3]) == day_bounds(local_day(FIXED, zone), zone)[1]
    assert parts[3] != berlin_parts[3]


# Child view


def test_child_state_none_without_rules(engine: TimeEngine, store: WorldStore) -> None:
    _player(store, "gw-leo", "Leo")
    assert engine.child_state("gw-leo") is None


def test_child_state_with_rules(engine: TimeEngine, store: WorldStore) -> None:
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    store.add_usage("gw-mia", TODAY, 1800)

    state = engine.child_state("gw-mia")

    assert state is not None
    assert state.reason == "ok"
    assert state.rest_s == 3600 - 1800


# Ledger format as input (as the mod writes it)


def test_book_parses_mod_ledger(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_ledger_seen("w1", {"Mia": 10})
    content = f"{LEDGER_HEADER} {FIXED} 3\nMia 70\nend\n".encode("ascii")

    from gameworld.provisioner.time_mod import parse_ledger

    parsed = parse_ledger(content)
    assert parsed is not None
    engine.book("w1", parsed)

    assert store.usage("gw-mia", TODAY) == 60


# World window and manager exemption (04-05, ZEIT-05, O-11/A4)

# Wed 2026-10-21 09:00 and Thu 2026-10-22 12:00 Europe/Berlin (summer time, before the switch on 25.10.).
WED_0900 = FIXED - 3 * 86400 - 3 * 3600
THU_1200 = FIXED - 2 * 86400


def _epoch(day: date, hour: int) -> int:
    return int(datetime.combine(day, time(hour), tzinfo=ZONE).timestamp())


def test_world_line_before_window_on_open_day(store: WorldStore) -> None:
    _world(store, "w1", 30015)
    store.replace_world_window("w1", {3: (600, 720)})
    engine = TimeEngine(store, clock=lambda: float(WED_0900))

    data, _ = engine.render("w1")

    wednesday = local_day(WED_0900, ZONE)
    assert wednesday.isoweekday() == 3
    assert _line(data, "welt") == ["welt", str(_epoch(wednesday, 10)), str(_epoch(wednesday, 12)), "welt", "Mi-10:00"]
    starts = " ".join(str(value) for value in day_starts(WED_0900, ZONE))
    assert _lines(data)[1:5] == [
        f"@tage 3 {starts}",
        f"welt {_epoch(wednesday, 10)} {_epoch(wednesday, 12)} welt Mi-10:00",
        f"@start welt {_epoch(wednesday, 10)} 600",
        "end",
    ]


def test_world_line_on_closed_day_points_to_next_open_day(store: WorldStore) -> None:
    _world(store, "w1", 30015)
    store.replace_world_window("w1", {3: (600, 720)})
    engine = TimeEngine(store, clock=lambda: float(THU_1200))

    data, _ = engine.render("w1")

    assert _line(data, "welt") == ["welt", "0", "0", "welt", "Mi-10:00"]
    # Next Wednesday 28.10. 10:00 (after the switch, winter time).
    next_wed = local_day(THU_1200, ZONE) + timedelta(days=6)
    assert _line(data, "@start") == ["@start", "welt", str(_epoch(next_wed, 10)), "600"]
    assert _lines(data)[1].startswith("@tage 4 ")


def test_world_without_window_has_no_world_line(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    data, _ = engine.render("w1")
    assert _line(data, "welt") is None


def test_invited_admin_gets_frei_line_without_window(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "admin", "Chef")
    _player(store, "gw-leo", "Leo")
    _invite(store, "w1", "admin")
    _invite(store, "w1", "gw-leo")
    store.set_meta(META_TIME_ADMINS, '["admin"]')

    data, _ = engine.render("w1")

    assert _line(data, "Chef") == ["Chef", "-1", "-1", "-1", "frei", "-"]
    # Child without rules and without management: no row (opt-in, T-04-27).
    assert _line(data, "Leo") is None
    # Only frei rows: no @tage and no @start, bytes as before the @ lines.
    assert b"@" not in data


def test_frei_beats_old_rules_and_child_never_frei(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    store.replace_world_window("w1", {1: (600, 720)})
    _player(store, "admin", "Chef")
    _player(store, "gw-mia", "Mia")
    _invite(store, "w1", "admin")
    _invite(store, "w1", "gw-mia")
    _plan(store, "admin", _week(limit=30))
    _plan(store, "gw-mia", _week(limit=30))
    store.set_meta(META_TIME_ADMINS, '["admin"]')

    data, _ = engine.render("w1")

    assert _line(data, "Chef") == ["Chef", "-1", "-1", "-1", "frei", "-"]
    mia = _line(data, "Mia")
    assert mia is not None
    assert mia[4] != "frei"


@pytest.mark.parametrize("raw", [None, "", "kaputt", '{"admin": 1}', "[1, 2]"])
def test_missing_or_broken_admin_snapshot_gives_no_frei(engine: TimeEngine, store: WorldStore, raw: str | None) -> None:
    _world(store, "w1", 30015)
    _player(store, "admin", "Chef")
    _invite(store, "w1", "admin")
    if raw is not None:
        store.set_meta(META_TIME_ADMINS, raw)

    data, _ = engine.render("w1")

    assert _line(data, "Chef") is None


def test_parse_admins_reads_sorted_json_list() -> None:
    assert parse_admins('["admin", "lehrerin"]') == frozenset({"admin", "lehrerin"})
    assert parse_admins(None) == frozenset()


# Next start and day boundaries in the rules file (quick 261021-481)


def test_render_used_up_child_gets_day_grid_and_start(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60, ws=540, we=1140))
    _invite(store, "w1", "gw-mia")
    store.add_usage("gw-mia", TODAY, 3600)

    data, _ = engine.render("w1")

    starts = day_starts(FIXED, ZONE)
    assert _lines(data)[1] == "@tage 6 " + " ".join(str(value) for value in starts)
    mia = _line(data, "Mia")
    assert mia is not None
    assert mia[4:] == ["limit", "So-09:00"]
    # Sunday 9:00 local after the switch at 3:00: start of day Sunday + 10 h (25-hour day).
    assert _lines(data)[_lines(data).index(" ".join(mia)) + 1] == f"@start Mia {starts[1] + 10 * 3600} 540"


def test_render_with_day_grid_stays_stable(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60, ws=540, we=1140))
    _invite(store, "w1", "gw-mia")

    first, changed1 = engine.render("w1")
    second, changed2 = engine.render("w1")

    assert b"@tage" in first
    assert (changed1, changed2) == (True, False)
    assert second == first


# 04.1-02: daily play time per account and world (play_daily, pitfall 3)


def test_book_counts_play_daily_only_for_kids_with_rules(engine: TimeEngine, store: WorldStore) -> None:
    """IN-03 (owner 22.10.2026, "Nur Kinder mit Regeln"): guest children without rules are not counted."""
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _player(store, "gw-leo", "Leo")
    _player(store, "papa", "Papa")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_meta(META_TIME_ADMINS, '["papa"]')
    store.set_ledger_seen("w1", {"Mia": 40, "Leo": 0, "Papa": 0, "Fremd": 0})

    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Mia": 55, "leo": 7, "Papa": 9, "Fremd": 3}))

    # Positive control Mia (rules), negative Leo (guest child without rules), Papa (manager), Fremd (no account).
    assert store.play_seconds(TODAY) == {("gw-mia", "w1"): 15}
    assert store.usage("gw-mia", TODAY) == 15
    assert store.usage("gw-leo", TODAY) == 0
    assert store.usage("papa", TODAY) == 0
    # The seen state is anchored for everyone: Leo does not count twice later either.
    assert store.ledger_seen("w1")["leo"] == 7


def test_book_play_daily_adds_up_per_world(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _world(store, "w2", 30016)
    _player(store, "gw-leo", "Leo")
    _plan(store, "gw-leo", _week())
    for world_id in ("w1", "w2"):
        store.set_ledger_seen(world_id, {"Leo": 0})
    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Leo": 20}))
    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Leo": 50}))
    engine.book("w2", Ledger(written_at=FIXED, generation=1, seconds={"Leo": 5}))
    assert store.play_seconds(TODAY) == {("gw-leo", "w1"): 50, ("gw-leo", "w2"): 5}


def test_render_prunes_notify_tables_after_seven_days(engine: TimeEngine, store: WorldStore, app_env: Path) -> None:
    import sqlite3

    _world(store, "w1", 30015)
    old, kept = TODAY - timedelta(days=8), TODAY - timedelta(days=7)
    db = sqlite3.connect(app_env / "gameworld.sqlite3")
    with db:
        for day in (old, kept):
            iso = day.isoformat()
            db.execute(
                "INSERT INTO play_daily (day, nc_user, world_id, seconds) VALUES (?, 'gw-leo', 'w1', 60)", (iso,)
            )
            db.execute(
                "INSERT INTO join_attempts (day, world_id, name_fold, player_name, first_at, last_at, count) "
                "VALUES (?, 'w1', 'fremd', 'Fremd', 1, 1, 1)",
                (iso,),
            )
            db.execute("INSERT INTO daily_flags (day, flag) VALUES (?, 'x')", (iso,))
            db.execute("INSERT INTO review_sent (nc_user, day) VALUES ('papa', ?)", (iso,))

    old_at = int(datetime.combine(old, time(0), ZONE).timestamp())
    kept_at = int(datetime.combine(kept, time(0), ZONE).timestamp())
    store.set_bot_presence("w1", "gw-alt", "join", old_at)
    store.set_bot_presence("w1", "gw-neu", "join", kept_at)

    engine.render("w1")

    with db:
        for table in ("play_daily", "join_attempts", "daily_flags", "review_sent"):
            days = [str(row[0]) for row in db.execute(f"SELECT day FROM {table}")]  # noqa: S608
            assert days == [kept.isoformat()], table
    db.close()
    # IN-03: the bot throttle (account and time) has the same 7-day period.
    assert store.bot_presence_at("w1", "gw-alt") is None
    assert store.bot_presence_at("w1", "gw-neu") == kept_at


# Pause in the rules file (04.1-03)


def _pause_lines(data: bytes) -> list[str]:
    return [line for line in _lines(data) if line.startswith("@pause")]


def _morgen_lines(data: bytes) -> list[str]:
    return [line for line in _lines(data) if line.startswith("@morgen")]


def test_render_active_pause_writes_pause_line_without_morgen(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 930, art=ART_PAUSE))

    data, _ = engine.render("w1")

    assert _pause_lines(data) == [f"@pause {FIXED + 30} {FIXED + 930} pause"]
    assert _morgen_lines(data) == []


def test_render_schluss_writes_morgen_only_for_world_players_with_plan(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _world(store, "w2", 30016)
    _player(store, "gw-mia", "Mia")
    _player(store, "gw-leo", "Leo")
    _player(store, "gw-ida", "Ida")
    _plan(store, "gw-mia", _week(ws=540, we=1140))
    _plan(store, "gw-ida", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    _invite(store, "w1", "gw-leo")
    _invite(store, "w2", "gw-ida")
    midnight = day_starts(FIXED, ZONE)[1]
    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=midnight, art=ART_SCHLUSS))

    data, _ = engine.render("w1")

    assert _pause_lines(data) == [f"@pause {FIXED + 30} {midnight} schluss"]
    # Leo without a plan is missing, Ida plays in another world.
    assert _morgen_lines(data) == ["@morgen Mia 540"]


def test_render_expired_pause_same_bytes_as_without_and_clears_state(store: WorldStore) -> None:
    clock = [float(FIXED)]
    engine = TimeEngine(store, clock=lambda: clock[0])
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    _invite(store, "w1", "gw-mia")
    without, _ = engine.render("w1")
    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 930, art=ART_PAUSE))

    paused, changed = engine.render("w1")
    assert changed is True
    assert _pause_lines(paused)

    clock[0] = float(FIXED + 930)
    after, changed_after = engine.render("w1")

    assert changed_after is True
    assert _generation(after) > _generation(paused)
    assert _pause_lines(after) == []
    # Except for the header (generation, time) the same bytes as without a pause.
    assert _lines(after)[1:] == _lines(without)[1:]
    assert store.get_pause() is None


def test_expired_pause_announces_end_once_in_every_world(store: WorldStore) -> None:
    """IN-09: if the pause expires on its own, each world gets "pause_end" once (silent as with Resume)."""
    clock = [float(FIXED)]
    engine = TimeEngine(store, clock=lambda: clock[0])
    _world(store, "w1", 30015)
    _world(store, "w2", 30016)
    _world(store, "w3", 30017)
    store.update_world("w3", desired_state="deleted")
    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 930, art=ART_PAUSE))
    engine.render("w1")
    assert store.outbox_batch() == []
    clock[0] = float(FIXED + 930)
    engine.render("w1")
    engine.render("w2")
    engine.render("w1")
    rows = [(row.world_id, row.kind) for row in store.outbox_batch()]
    assert sorted(rows) == [("w1", "pause_end"), ("w2", "pause_end")]


def test_expired_schluss_ends_silently(store: WorldStore) -> None:
    """Counter-check: "Für heute Schluss" ends at midnight without a bot message."""
    clock = [float(FIXED)]
    engine = TimeEngine(store, clock=lambda: clock[0])
    _world(store, "w1", 30015)
    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 930, art=ART_SCHLUSS))
    clock[0] = float(FIXED + 930)
    engine.render("w1")
    assert store.get_pause() is None
    assert store.outbox_batch() == []


def test_render_pause_change_changes_cache_key(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-leo", "Leo")
    _invite(store, "w1", "gw-leo")
    engine.render("w1")
    assert engine.render("w1")[1] is False

    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 930, art=ART_PAUSE))
    assert engine.render("w1")[1] is True
    assert engine.render("w1")[1] is False

    store.set_pause(PauseState(started_by="admin", ab=FIXED + 30, bis=FIXED + 1830, art=ART_PAUSE))
    assert engine.render("w1")[1] is True

    store.clear_pause()
    data, changed = engine.render("w1")
    assert changed is True
    assert _pause_lines(data) == []


# Halt before the cold backup (05-03, D-09)


def _halt_lines(data: bytes) -> list[str]:
    return [line for line in _lines(data) if line.startswith("@halt")]


def test_set_halt_writes_halt_line_only_for_that_world(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _world(store, "w2", 30016)
    engine.render("w1")
    engine.render("w2")
    assert engine.render("w1")[1] is False

    engine.set_halt("w1", FIXED + 15)

    data, changed = engine.render("w1")
    assert changed is True
    assert _halt_lines(data) == [f"@halt {FIXED + 15}"]
    assert _lines(data)[-2:] == ["end", ""]
    assert _lines(data)[-3] == f"@halt {FIXED + 15}"
    assert engine.render("w1")[1] is False
    other, other_changed = engine.render("w2")
    assert other_changed is False
    assert _halt_lines(other) == []


def test_clear_halt_renders_without_halt(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    without, _ = engine.render("w1")
    engine.set_halt("w1", FIXED + 15)
    halted, _ = engine.render("w1")

    engine.clear_halt("w1")

    data, changed = engine.render("w1")
    assert changed is True
    assert _halt_lines(data) == []
    assert _generation(data) > _generation(halted)
    assert _lines(data)[1:] == _lines(without)[1:]
    # Without a halt, clear_halt has no effect.
    engine.clear_halt("w1")
    assert engine.render("w1")[1] is False


def test_forget_keeps_halt(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    engine.set_halt("w1", FIXED + 15)
    engine.render("w1")

    engine.forget("w1")

    data, changed = engine.render("w1")
    assert changed is True
    assert _halt_lines(data) == [f"@halt {FIXED + 15}"]


def test_halt_is_not_persisted(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    engine.set_halt("w1", FIXED + 15)
    fresh = TimeEngine(store, clock=_clock)
    data, _ = fresh.render("w1")
    assert _halt_lines(data) == []


# ROLLE-04: adult switch (frei = manager union | adults)

FREI_LINE = ["-1", "-1", "-1", "frei", "-"]


def test_adult_renders_frei_and_toggle_changes_bytes(engine: TimeEngine, store: WorldStore) -> None:
    """Switching changes the bytes of the rules file; the dormant plan applies again after switching back."""
    _world(store, "w1", 30015)
    store.replace_world_window("w1", dict.fromkeys(range(1, 8), (600, 720)))
    _player(store, "gw-kind", "Kind")
    _invite(store, "w1", "gw-kind")
    # "0 Minuten heute": day not allowed (the plan does not permit a limit of 0).
    _plan(store, "gw-kind", _week(allowed=False))

    child_bytes, _ = engine.render("w1")
    child_line = _line(child_bytes, "Kind")
    assert child_line is not None
    assert child_line[4] != "frei"
    assert child_line[1] == "0"

    store.set_adult("gw-kind", set_by="admin", set_at="2026-10-24T10:00:00+00:00")
    adult_bytes, changed = engine.render("w1")

    assert changed is True
    assert adult_bytes != child_bytes
    assert _line(adult_bytes, "Kind") == ["Kind", *FREI_LINE]
    # World row stays (applies to children), frei overrides it for the adult.
    assert _line(adult_bytes, "welt") is not None

    store.clear_adult("gw-kind")
    back_bytes, changed_back = engine.render("w1")

    assert changed_back is True
    assert back_bytes != adult_bytes
    back_line = _line(back_bytes, "Kind")
    assert back_line is not None
    assert back_line[1:] == child_line[1:]
    # Plan stayed in the database.
    assert "gw-kind" in store.child_plans()


def test_frei_set_is_part_of_cache_key(engine: TimeEngine, store: WorldStore) -> None:
    """T-06-18: new generation on switching even without a visible row (adult not invited)."""
    _world(store, "w1", 30015)
    _player(store, "gw-kind", "Kind")
    _invite(store, "w1", "gw-kind")
    _plan(store, "gw-kind", _week(limit=30))
    first, _ = engine.render("w1")
    store.set_adult("gw-gast", set_by="admin", set_at="2026-10-24T10:00:00+00:00")
    second, changed = engine.render("w1")
    assert changed is True
    assert _generation(second) == _generation(first) + 1


def test_book_skips_adult_usage_and_play(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-kind", "Kind")
    _player(store, "gw-oma", "Oma")
    _plan(store, "gw-kind", _week(limit=60))
    _plan(store, "gw-oma", _week(limit=60))
    store.set_adult("gw-oma", set_by="admin", set_at="2026-10-24T10:00:00+00:00")
    store.set_ledger_seen("w1", {"Kind": 0, "Oma": 0})

    engine.book("w1", Ledger(written_at=FIXED, generation=1, seconds={"Kind": 120, "Oma": 120}))

    # Positive control child, negative adults (dormant plan does not count).
    assert store.usage("gw-kind", TODAY) == 120
    assert store.usage("gw-oma", TODAY) == 0
    assert store.play_seconds(TODAY) == {("gw-kind", "w1"): 120}
    # State anchored anyway: after switching back nothing is booked retroactively.
    assert store.ledger_seen("w1")["Oma"] == 120
