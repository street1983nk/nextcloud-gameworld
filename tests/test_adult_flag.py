"""Erwachsen-Schalter je Konto (ROLLE-04, D-05 bis D-08): Store, Engine, API und Negativtests."""

from __future__ import annotations

import io
import sqlite3
import tarfile
from datetime import date
from pathlib import Path
from typing import cast

import httpx
import pytest

from gameworld.api.worlds import get_service
from gameworld.config import load_settings
from gameworld.notify.loop import collect_play
from gameworld.playtime.plan import DayRule, WeekPlan
from gameworld.provisioner.access_mod import render_access_file
from gameworld.provisioner.archive import build_world_files
from gameworld.provisioner.client import DockerProvisioner
from gameworld.provisioner.luanti_conf import render_minetest_conf, render_world_mt
from gameworld.provisioner.presets import get_preset
from gameworld.provisioner.spec import world_spec
from gameworld.provisioner.time_mod import RULES_FILE_NAME
from gameworld.worlds import service as worlds_service
from gameworld.worlds.service import WorldService
from gameworld.worlds.store import PlayerRow, WorldRow, WorldStore
from tests.conftest import appapi_headers, give_rules
from tests.test_service_lifecycle import FakeProvisioner

SET_AT = "2026-10-24T10:00:00+00:00"


@pytest.fixture
def store(app_env: Path) -> WorldStore:
    world_store = WorldStore(app_env / "gameworld.sqlite3")
    world_store.migrate()
    return world_store


def _raw_adults(db: Path) -> list[tuple[str, str, str]]:
    """Inhalt der Tabelle adults per eigener Abfrage (nicht über die Store-Methode)."""
    connection = sqlite3.connect(db)
    try:
        rows = connection.execute("SELECT nc_user, set_by, set_at FROM adults ORDER BY nc_user").fetchall()
    finally:
        connection.close()
    return [(str(a), str(b), str(c)) for a, b, c in rows]


# Store


def test_set_and_clear_adult(store: WorldStore, app_env: Path) -> None:
    assert store.adults() == set()
    store.set_adult("gw-kind", set_by="admin", set_at=SET_AT)
    assert store.adults() == {"gw-kind"}
    # Wer und wann bleiben gespeichert (T-06-19).
    assert _raw_adults(app_env / "gameworld.sqlite3") == [("gw-kind", "admin", SET_AT)]
    store.clear_adult("gw-kind")
    assert store.adults() == set()
    assert _raw_adults(app_env / "gameworld.sqlite3") == []


def test_clear_adult_on_unmarked_account_is_no_error(store: WorldStore) -> None:
    store.clear_adult("gw-niemand")
    assert store.adults() == set()


def test_set_adult_twice_replaces_marker(store: WorldStore, app_env: Path) -> None:
    store.set_adult("gw-kind", set_by="admin", set_at=SET_AT)
    store.set_adult("gw-kind", set_by="lehrerin", set_at="2026-10-24T11:00:00+00:00")
    assert _raw_adults(app_env / "gameworld.sqlite3") == [("gw-kind", "lehrerin", "2026-10-24T11:00:00+00:00")]


# Tagesrückblick (D-05: Erwachsene erscheinen nicht)


def test_adult_never_in_daily_review_even_with_minutes_before_switch(store: WorldStore) -> None:
    day = date(2026, 10, 24)
    for uid in ("gw-kind", "gw-oma"):
        give_rules(store, uid)
    # Minuten von heute früh, als gw-oma noch als Kind lief.
    store.book_usage("w1", day, {}, {}, play={"gw-kind": 300, "gw-oma": 300})
    assert collect_play(store, day, ()) == {"gw-kind": {"w1": 300}, "gw-oma": {"w1": 300}}

    store.set_adult("gw-oma", set_by="admin", set_at=SET_AT)

    assert collect_play(store, day, ()) == {"gw-kind": {"w1": 300}}


# API: POST /api/players/adult (nur Verwalter), erweiterte Ausgaben, Negativtests

W1 = "aaaaaaaaaaa1"
W2 = "aaaaaaaaaaa2"
VERIFIER = "#1#c2FsdA==#dmVyaWZpZXI="
KID = "gw-kind"
FORBIDDEN = "Nur Eltern können Welten verwalten."
# Erwartete frei-Zeile als Literal (nicht aus der Engine abgeleitet).
FREI_LINE = "Kind -1 -1 -1 frei -"


def _row(world_id: str, port: int) -> WorldRow:
    return WorldRow(
        id=world_id,
        name=f"Welt {world_id}",
        port=port,
        container_name=f"gw-x-{world_id}",
        volume_name=f"gw-x-{world_id}",
        world_key="k",
        engine_version="5.17.0",
        desired_state="running",
        op_state="ready",
        last_error=None,
        created_at="2026-10-20T10:00:00+00:00",
    )


@pytest.fixture
def api_store(store: WorldStore) -> WorldStore:
    store.insert_world(_row(W1, 30015))
    store.insert_world(_row(W2, 30016))
    store.insert_player(PlayerRow(nc_user=KID, player_name="Kind", rotation=0))
    store.insert_player(PlayerRow(nc_user="admin", player_name="Chef", rotation=0))
    for world_id in (W1, W2):
        store.apply_world_access(world_id, {KID: VERIFIER, "admin": VERIFIER})
    return store


@pytest.fixture
def fake() -> FakeProvisioner:
    provisioner = FakeProvisioner()
    provisioner.containers[W1] = (30015, "running")
    provisioner.containers[W2] = (30016, "running")
    return provisioner


@pytest.fixture
def pushes() -> list[str]:
    return []


@pytest.fixture
def service(
    api_store: WorldStore, fake: FakeProvisioner, pushes: list[str], monkeypatch: pytest.MonkeyPatch
) -> WorldService:
    from gameworld.main import APP

    world_service = WorldService(api_store, cast(DockerProvisioner, fake), load_settings())
    original = world_service.push_time

    def spy(world_id: str) -> bool:
        # Sofortige Wirkung nur unter der Welt-Sperre (Sperr-Regel, D-08).
        assert worlds_service._LOCK.locked()  # pyright: ignore[reportPrivateUsage]
        pushes.append(world_id)
        return original(world_id)

    monkeypatch.setattr(world_service, "push_time", spy)
    monkeypatch.setitem(APP.dependency_overrides, get_service, lambda: world_service)
    return world_service


def _dump(db: Path) -> list[str]:
    """Ganze Datenbank als SQL-Text (roher Vergleich vorher/nachher, unabhängig vom Store)."""
    connection = sqlite3.connect(db)
    try:
        return list(connection.iterdump())
    finally:
        connection.close()


def _last_rules(fake: FakeProvisioner, world_id: str) -> list[str]:
    for written_world, archive in reversed(fake.written):
        if written_world != world_id:
            continue
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
            if RULES_FILE_NAME in tar.getnames():
                handle = tar.extractfile(RULES_FILE_NAME)
                assert handle is not None
                return handle.read().decode("ascii").split("\n")
    raise AssertionError("keine Regeldatei geschrieben")


async def _adult(client: httpx.AsyncClient, body: object, user: str = "admin") -> httpx.Response:
    return await client.post("/api/players/adult", json=body, headers=appapi_headers(user))


async def _warm(client: httpx.AsyncClient, pushes: list[str]) -> None:
    """Erster Verwalter-Besuch legt den Verwalter-Schnappschuss an (schreibt dabei alle Welten neu).

    Danach zählt ``pushes`` nur noch, was der Erwachsen-Schalter selbst schreibt.
    """
    assert (await client.get("/api/playtime", headers=appapi_headers())).status_code == 200
    pushes.clear()


async def test_verwalter_marks_adult_with_immediate_effect(
    client: httpx.AsyncClient,
    service: WorldService,
    api_store: WorldStore,
    fake: FakeProvisioner,
    pushes: list[str],
    app_env: Path,
) -> None:
    del service
    await _warm(client, pushes)
    give_rules(api_store, KID)

    response = await _adult(client, {"nc_user": KID, "adult": True})

    assert response.status_code == 200, response.text
    assert response.json() == {"nc_user": KID, "adult": True, "applied": True}
    assert sorted(pushes) == [W1, W2]
    assert [row[:2] for row in _raw_adults(app_env / "gameworld.sqlite3")] == [(KID, "admin")]
    for world_id in (W1, W2):
        assert FREI_LINE in _last_rules(fake, world_id)


async def test_back_to_child_restores_rules_without_dialog(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore, fake: FakeProvisioner, pushes: list[str]
) -> None:
    del service
    give_rules(api_store, KID)
    assert (await _adult(client, {"nc_user": KID, "adult": True})).status_code == 200
    pushes.clear()

    response = await _adult(client, {"nc_user": KID, "adult": False})

    assert response.status_code == 200, response.text
    assert response.json() == {"nc_user": KID, "adult": False, "applied": True}
    assert api_store.adults() == set()
    assert sorted(pushes) == [W1, W2]
    kind_lines = [line for line in _last_rules(fake, W1) if line.startswith("Kind ")]
    assert len(kind_lines) == 1
    assert kind_lines[0] != FREI_LINE


async def test_verwalter_account_cannot_be_marked_adult(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore, pushes: list[str]
) -> None:
    del service
    await _warm(client, pushes)
    response = await _adult(client, {"nc_user": "admin", "adult": True})
    assert response.status_code == 409
    assert response.json()["detail"] == "Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln."
    assert api_store.adults() == set()
    assert pushes == []


async def test_unknown_account_404_and_extra_field_422(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore, pushes: list[str]
) -> None:
    del service
    await _warm(client, pushes)
    unknown = await _adult(client, {"nc_user": "gw-niemand", "adult": True})
    assert unknown.status_code == 404
    extra = await _adult(client, {"nc_user": KID, "adult": True, "verwalter": True})
    assert extra.status_code == 422
    missing = await _adult(client, {"nc_user": KID})
    assert missing.status_code == 422
    assert api_store.adults() == set()
    assert pushes == []


@pytest.mark.parametrize("target", [KID, "gw-kind2"])
async def test_kind_setzt_sich_selbst_erwachsen_403_ohne_db_aenderung_ohne_push(
    client: httpx.AsyncClient,
    service: WorldService,
    api_store: WorldStore,
    pushes: list[str],
    app_env: Path,
    target: str,
) -> None:
    """Kind setzt sich selbst erwachsen -> 403, adults() unverändert, kein push_time (T-06-16)."""
    del service
    give_rules(api_store, KID)
    db = app_env / "gameworld.sqlite3"
    before = _dump(db)

    response = await _adult(client, {"nc_user": target, "adult": True}, user=KID)

    assert response.status_code == 403
    assert response.json()["detail"] == FORBIDDEN
    assert _dump(db) == before
    assert _raw_adults(db) == []
    assert api_store.adults() == set()
    assert pushes == []
    # Positivkontrolle: Dieselbe Anfrage als Verwalter ändert die Datenbank.
    assert (await _adult(client, {"nc_user": KID, "adult": True})).status_code == 200
    assert _dump(db) != before


@pytest.mark.parametrize("path", ["/api/my/adult", "/api/my/players/adult", "/api/my/playtime"])
async def test_no_writing_adult_path_under_api_my(
    client: httpx.AsyncClient, service: WorldService, app_env: Path, pushes: list[str], path: str
) -> None:
    del service
    db = app_env / "gameworld.sqlite3"
    before = _dump(db)
    response = await client.post(path, json={"nc_user": KID, "adult": True}, headers=appapi_headers(KID))
    assert response.status_code in {404, 405}
    assert _dump(db) == before
    assert pushes == []


def test_only_play_ticket_writes_under_api_my() -> None:
    """Strukturtest: Unter /api/my/ schreibt höchstens das Spiel-Ticket, nie ein Erwachsen-Pfad."""
    from gameworld.main import APP

    paths: dict[str, dict[str, object]] = APP.openapi()["paths"]
    writing = {path for path, operations in paths.items() if path.startswith("/api/my") and set(operations) - {"get"}}
    assert writing <= {"/api/my/play-ticket"}
    assert not [path for path in paths if path.startswith("/api/my") and "adult" in path]
    # Positivkontrolle: Die Verwalter-Route ist sichtbar.
    assert set(paths["/api/players/adult"]) == {"post"}


async def test_player_list_has_adult_verwalter_has_rules(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore
) -> None:
    del service
    give_rules(api_store, KID)
    assert (await _adult(client, {"nc_user": KID, "adult": True})).status_code == 200

    response = await client.get(f"/api/worlds/{W1}/players", headers=appapi_headers())

    assert response.status_code == 200, response.text
    flags = {p["nc_user"]: (p["adult"], p["verwalter"], p["has_rules"]) for p in response.json()["players"]}
    assert flags == {KID: (True, False, True), "admin": (False, True, False)}


async def test_playtime_list_and_my_playtime_for_adult(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore
) -> None:
    del service
    api_store.set_child_plan(
        KID, WeekPlan({day: DayRule(True, 30, None, None) for day in range(1, 8)}), None, "admin", SET_AT
    )
    mine_child = await client.get("/api/my/playtime", headers=appapi_headers(KID))
    assert mine_child.json()["limited"] is True
    assert (await _adult(client, {"nc_user": KID, "adult": True})).status_code == 200

    listed = await client.get("/api/playtime", headers=appapi_headers())
    assert listed.status_code == 200, listed.text
    [child] = listed.json()["children"]
    assert (child["nc_user"], child["adult"], child["has_rules"]) == (KID, True, True)
    mine = await client.get("/api/my/playtime", headers=appapi_headers(KID))
    assert mine.status_code == 200
    assert mine.json()["limited"] is False


def _world_config(store: WorldStore, world_id: str) -> dict[str, bytes]:
    """Welt-Konfiguration aus den echten Erzeugern (spec, luanti_conf, access_mod, archive)."""
    row = store.get_world(world_id)
    assert row is not None
    preset = get_preset(row.preset)
    access_file = render_access_file(row.access_generation, store.access_entries(world_id))
    return {
        "minetest.conf": render_minetest_conf(row.name, row.world_key, preset).encode("utf-8"),
        "world.mt": render_world_mt(preset).encode("utf-8"),
        "access": access_file,
        "world_files": build_world_files(access_file),
        "spec": repr(world_spec("inst", world_id, row.port, preset)).encode("utf-8"),
    }


async def test_welt_konfiguration_fuer_erwachsenen_byte_identisch(
    client: httpx.AsyncClient, service: WorldService, api_store: WorldStore, fake: FakeProvisioner
) -> None:
    """T-06-17: Erwachsen ändert nur die frei-Zeile der Regeldatei, nie Rechte oder Zugang."""
    del service
    give_rules(api_store, KID)
    # Erst als Kind rendern lassen (Rückschalten ohne Markierung ist erlaubt und schreibt die Datei).
    assert (await _adult(client, {"nc_user": KID, "adult": False})).status_code == 200
    child_config = _world_config(api_store, W1)
    child_rules = _last_rules(fake, W1)

    assert (await _adult(client, {"nc_user": KID, "adult": True})).status_code == 200

    assert _world_config(api_store, W1) == child_config
    conf = child_config["minetest.conf"].decode("utf-8")
    privs = [line for line in conf.splitlines() if line.startswith("default_privs")]
    assert len(privs) == 1
    assert "server" not in privs[0]
    assert "privs" not in privs[0].split("=", 1)[1]
    adult_rules = _last_rules(fake, W1)

    # Nur Kopf (Generation, Zeitpunkt), die Zeile des Kindes und seine Startzeilen ändern sich;
    # @tage fällt weg, weil keine Zeile mehr einen nächsten Start trägt.
    def rest(lines: list[str]) -> list[str]:
        return [line for line in lines[1:] if not line.startswith(("Kind ", "@start Kind ", "@tage "))]

    assert rest(adult_rules) == rest(child_rules)
    assert [line for line in child_rules if line.startswith("Kind ")] != [FREI_LINE]
    assert [line for line in adult_rules if line.startswith("Kind ")] == [FREI_LINE]
    assert not [line for line in adult_rules if line.startswith("@start Kind ")]
