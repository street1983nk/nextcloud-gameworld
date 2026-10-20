"""TimeEngine: Verbuchen, Rendern, Generation, Tagesende-Grenze und Opt-in (04-03)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from gameworld.playtime.engine import META_TIME_ADMINS, TimeEngine, parse_admins
from gameworld.playtime.plan import DayRule, WeekPlan, day_bounds, load_zone, local_day
from gameworld.provisioner.time_mod import LEDGER_HEADER, Ledger
from gameworld.worlds.store import PlayerRow, WorldRow, WorldStore

# Sa 2026-10-24 12:00 Europe/Berlin (Golden Vector 1792792800 = Tagesanfang, plus 12 h).
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


# Verbuchen


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


def test_book_none_changes_nothing(engine: TimeEngine, store: WorldStore) -> None:
    _world(store, "w1", 30015)
    _player(store, "gw-mia", "Mia")
    _plan(store, "gw-mia", _week(limit=60))
    store.set_ledger_seen("w1", {"Mia": 40})

    engine.book("w1", None)

    assert store.usage("gw-mia", TODAY) == 0
    assert store.ledger_seen("w1") == {"Mia": 40}


# Rendern


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
    # cap = gesehen (900) + rest (3600 - 2700 = 900) = 1800, Grund ok.
    assert parts[1] == "1800"
    assert parts[4] == "ok"
    # Fenster endet nie nach dem lokalen Tagesende (O-04).
    assert int(parts[3]) <= day_bounds(TODAY, ZONE)[1]


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
    # Deckel in Welt B = gesehen_B (300) + (Limit 1200 - Verbrauch 600) = 900.
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


# Ferien und Zeitzone (04-04)


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


# Kind-Ansicht


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


# Zählbuch-Format als Eingabe (wie der Mod es schreibt)


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


# Welt-Fenster und Verwalter-Freistellung (04-05, ZEIT-05, O-11/A4)

# Mi 2026-10-21 09:00 und Do 2026-10-22 12:00 Europe/Berlin (Sommerzeit, vor der Umstellung am 25.10.).
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


def test_world_line_on_closed_day_points_to_next_open_day(store: WorldStore) -> None:
    _world(store, "w1", 30015)
    store.replace_world_window("w1", {3: (600, 720)})
    engine = TimeEngine(store, clock=lambda: float(THU_1200))

    data, _ = engine.render("w1")

    assert _line(data, "welt") == ["welt", "0", "0", "welt", "Mi-10:00"]


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
    # Kind ohne Regeln und ohne Verwaltung: keine Zeile (Opt-in, T-04-27).
    assert _line(data, "Leo") is None


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
