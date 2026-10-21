"""Live-Nachweis ZEIT-02: gameworld_time setzt eine Regeldatei in einer echten Luanti-Welt durch.

Die Regeldatei schreibt hier der Test selbst per put_archive (wie ab 04-03 die
ExApp aus der Datenbank). Der Session-Prober (tests/e2e/luanti_probe.py) tritt
wie ein echter Client bis on_joinplayer bei, hält die Sitzung und schneidet
Chat und Trennen mit. Fälle S1 bis S11 wie in 04-01-PLAN.md, Erwartungen nach
der Spike-Tabelle in 04-RESEARCH.md. Seriell, eine MTG-Welt.
"""

from __future__ import annotations

import re
import time
from dataclasses import replace
from datetime import datetime, timedelta
from datetime import time as clock_time
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

import anyio
import anyio.to_thread
import httpx
import pytest

from gameworld.playtime.plan import day_starts, local_day
from gameworld.provisioner.time_mod import (
    LEDGER_HEADER,
    TEXT_LIMIT,
    TEXT_WELT,
    DayGrid,
    TimeLine,
    kid_text,
    render_time_file,
)
from tests.conftest import appapi_headers
from tests.e2e.luanti_probe import join, session
from tests.e2e.test_status_e2e import wait_for_status
from tests.e2e.time_helpers import (
    HOST,
    MTG_READY,
    create_running_world,
    read_ledger,
    read_ledger_raw,
    write_access,
    write_rules,
)

pytestmark = [pytest.mark.docker, pytest.mark.usefixtures("docker_cleanup")]

# Feste Testpasswörter für Wegwerfwelten, kein Geheimnis.
PASSWORDS = {"Mia": "Sonne-Baum-42", "Papa": "Kaffee-Tasse-73", "Leo": "Tiger-Wolke-17"}
# Tagesbezug wie die ExApp: Tagesgrenzen und nächste Starts als Epochs, der Mod bildet den Satz.
ZONE = ZoneInfo("Europe/Berlin")
_NOW = int(time.time())
_TODAY = local_day(_NOW, ZONE)
DAYS = DayGrid(weekday=_TODAY.isoweekday(), starts=day_starts(_NOW, ZONE))


def _local_epoch(days_ahead: int, hour: int) -> int:
    return int(datetime.combine(_TODAY + timedelta(days=days_ahead), clock_time(hour), tzinfo=ZONE).timestamp())


# Mia: morgen ab 9 Uhr wieder; Welt: übermorgen ab 10 Uhr wieder offen.
MIA_NEXT = (_local_epoch(1, 9), 540)
WELT_NEXT = (_local_epoch(2, 10), 600)
LIMIT_TEXT = kid_text("limit", 1, (_TODAY + timedelta(days=1)).isoweekday(), 540)
WELT_TEXT = kid_text("welt", 2, (_TODAY + timedelta(days=2)).isoweekday(), 600)
NOT_INVITED = "nicht eingeladen"
COOLDOWN_PAUSE = 2.5
JOIN_TIMEOUT = 30.0
LEDGER_LINE = re.compile(r"[A-Za-z0-9_-]{1,20} [0-9]+")


def _chats(result: dict[str, object]) -> list[str]:
    events = result.get("events")
    assert isinstance(events, list)
    return [str(event["text"]) for event in events if isinstance(event, dict) and event.get("kind") == "chat"]


def _denied(result: dict[str, object], text: str) -> None:
    assert result["result"] == "denied", result
    assert result["code"] == "CUSTOM_STRING", result
    assert text in str(result["reason"]), result


def _window(cap: int, next_hint: str = "Sa-10:00", upcoming: tuple[int, int] = (-1, -1)) -> TimeLine:
    now = int(time.time())
    return TimeLine(
        cap=cap,
        start=now - 60,
        until=now + 3600,
        reason="ok",
        next_hint=next_hint,
        next_at=upcoming[0],
        next_minute=upcoming[1],
    )


FREI = TimeLine(cap=-1, start=-1, until=-1, reason="frei", next_hint="-")
WORLD_CLOSED = TimeLine(
    cap=-1, start=0, until=0, reason="welt", next_hint="Mi-10:00", next_at=WELT_NEXT[0], next_minute=WELT_NEXT[1]
)


async def test_time_mod_enforces_rules(client: httpx.AsyncClient, app_env: Path) -> None:
    world_id, port = await create_running_world(client, "mtg_kreativ", MTG_READY)
    write_access(app_env, world_id, 1, PASSWORDS)
    mia = _window(75, upcoming=MIA_NEXT)
    rules = render_time_file(1, int(time.time()), None, {"Mia": mia}, days=DAYS)
    assert LIMIT_TEXT.endswith("Morgen ab 9 Uhr kannst du wieder spielen.")
    write_rules(app_env, world_id, rules)

    # (S1) Deckel 75 s: Vorwarnung "Noch 1 Minute.", dann Trennen mit Kindertext ohne "Kicked: ".
    s1 = session(HOST, port, "Mia", PASSWORDS["Mia"], hold=110, timeout=JOIN_TIMEOUT)
    assert s1["result"] == "kicked", s1
    after = float(str(s1["after_s"]))
    assert 60 <= after <= 90, s1
    assert any("Noch 1 Minute." in chat for chat in _chats(s1)), s1
    assert LIMIT_TEXT in str(s1["reason"]), s1
    assert "Kicked" not in str(s1["reason"]), s1

    # (S2) Sofortiger Rejoin (nach der 2-s-Wiederbeitritts-Sperre): derselbe Text.
    await anyio.sleep(COOLDOWN_PAUSE)
    _denied(join(HOST, port, "Mia", PASSWORDS["Mia"]), LIMIT_TEXT)

    # (S2b) Altdatei ohne @-Zeilen (wie vor Quick 261021-481): nur der Grundsatz, keine Zeitangabe.
    plain = render_time_file(1, int(time.time()), None, {"Mia": _window(75)})
    assert b"@" not in plain
    write_rules(app_env, world_id, plain)
    await anyio.sleep(COOLDOWN_PAUSE)
    fallback = join(HOST, port, "Mia", PASSWORDS["Mia"])
    _denied(fallback, TEXT_LIMIT)
    assert "spielen" not in str(fallback["reason"]), fallback
    write_rules(app_env, world_id, rules)

    # (S3) Zählbuch im Welt-Volume.
    before = read_ledger(app_env, world_id).seconds["Mia"]
    assert 70 <= before <= 80, before

    # (S4) Neustart: Zählbuch bleibt, der Deckel gilt gegen den gespeicherten Stand.
    restarted = await client.post(f"/api/worlds/{world_id}/restart", headers=appapi_headers())
    assert restarted.status_code == 200, restarted.text
    world = await wait_for_status(client, world_id, "running", MTG_READY)
    port = int(str(world["port"]))
    assert read_ledger(app_env, world_id).seconds["Mia"] == before
    # Der Start schrieb Zugangs- und Regeldatei aus der Datenbank (leer); der Test legt sie neu.
    write_access(app_env, world_id, 1, PASSWORDS)
    write_rules(app_env, world_id, rules)
    _denied(join(HOST, port, "Mia", PASSWORDS["Mia"]), LIMIT_TEXT)

    # (S5) Positivkontrolle: Leo ohne Zeile bleibt verbunden.
    s5 = session(HOST, port, "Leo", PASSWORDS["Leo"], hold=20, timeout=JOIN_TIMEOUT)
    assert s5["result"] == "held", s5

    # (S6) Live-Push: Leo bekommt während der Sitzung den Deckel = aktueller Stand.
    await anyio.sleep(COOLDOWN_PAUSE)
    holding: dict[str, object] = {}

    async def hold_leo() -> None:
        holding.update(
            await anyio.to_thread.run_sync(partial(session, HOST, port, "Leo", PASSWORDS["Leo"], 60.0, JOIN_TIMEOUT))
        )

    async with anyio.create_task_group() as group:
        group.start_soon(hold_leo)
        await anyio.sleep(12)
        assert not holding, holding
        leo_now = read_ledger(app_env, world_id).seconds["Leo"]
        pushed_rules = render_time_file(2, int(time.time()), None, {"Mia": mia, "Leo": _window(leo_now)}, days=DAYS)
        write_rules(app_env, world_id, pushed_rules)
        pushed = time.monotonic()
    disconnected = time.monotonic() - pushed
    assert holding["result"] == "kicked", holding
    assert disconnected <= 8, disconnected
    assert TEXT_LIMIT in str(holding["reason"]), holding

    # (S7, S11) Welt geschlossen: Kind abgelehnt, Verwalter mit frei (-1 -1 -1) kommt hinein,
    # ein nicht eingeladener Name bekommt den Zugangstext (Pitfall 5).
    closed = render_time_file(
        3, int(time.time()), WORLD_CLOSED, {"Mia": mia, "Leo": _window(leo_now), "Papa": FREI}, days=DAYS
    )
    assert WELT_TEXT.startswith(TEXT_WELT)
    assert WELT_TEXT.endswith("ab 10 Uhr ist sie wieder offen.")
    assert b"\nPapa -1 -1 -1 frei -\n" in closed
    write_rules(app_env, world_id, closed)
    _denied(join(HOST, port, "Mia", PASSWORDS["Mia"]), WELT_TEXT)
    assert join(HOST, port, "Papa", PASSWORDS["Papa"])["result"] == "auth_accept"
    _denied(join(HOST, port, "Fremder"), NOT_INVITED)

    # (S8) Halbe Regeldatei (ohne end): Der alte Stand bleibt.
    write_rules(app_env, world_id, b"gameworld-time 1 4 1792792800\nMia -1 0 4000000000 ok -\n")
    await anyio.sleep(6)
    _denied(join(HOST, port, "Mia", PASSWORDS["Mia"]), WELT_TEXT)
    assert join(HOST, port, "Papa", PASSWORDS["Papa"])["result"] == "auth_accept"

    # (S9) Zählbuch: nur Kopf, "<Name> <Sekunden>" und end, keine IP-Adressen.
    lines = read_ledger_raw(app_env, world_id).decode("ascii").split("\n")
    assert lines[0].startswith(f"{LEDGER_HEADER} ")
    assert lines[-2:] == ["end", ""]
    assert all(LEDGER_LINE.fullmatch(line) for line in lines[1:-2]), lines
    assert {line.split(" ")[0] for line in lines[1:-2]} == {"Mia", "Leo"}

    # (S10) Vorwarnung nur für die kleinste Schwelle: 4 min Rest ergibt nur "Noch 5 Minuten.".
    leo_now = read_ledger(app_env, world_id).seconds["Leo"]
    write_rules(app_env, world_id, render_time_file(5, int(time.time()), None, {"Leo": _window(leo_now + 240)}))
    s10 = session(HOST, port, "Leo", PASSWORDS["Leo"], hold=20, timeout=JOIN_TIMEOUT)
    assert s10["result"] == "held", s10
    chats = _chats(s10)
    assert chats.count("Noch 5 Minuten.") == 1, chats
    assert not any("Noch 10 Minuten" in chat for chat in chats), chats
    assert len([chat for chat in chats if chat.startswith("Noch ")]) == 1, chats

    # (S12, WR-06) Zählbuch hinter dem Anker @base (etwa nach einem Restore): Der Mod gewährt
    # nie mehr als den Rest beim Ausstellen. Deckel 600 s über dem Stand, aber Anker 580 s
    # darüber: Rest 20 s, also abgelehnt. Positivkontrolle: Anker auf dem Stand, Beitritt klappt.
    await anyio.sleep(COOLDOWN_PAUSE)
    leo_now = read_ledger(app_env, world_id).seconds["Leo"]
    behind = replace(_window(leo_now + 600), base=leo_now + 580)
    write_rules(app_env, world_id, render_time_file(6, int(time.time()), None, {"Leo": behind}))
    _denied(join(HOST, port, "Leo", PASSWORDS["Leo"]), TEXT_LIMIT)
    level = replace(_window(leo_now + 600), base=leo_now)
    write_rules(app_env, world_id, render_time_file(7, int(time.time()), None, {"Leo": level}))
    await anyio.sleep(COOLDOWN_PAUSE)
    assert join(HOST, port, "Leo", PASSWORDS["Leo"])["result"] == "auth_accept"
