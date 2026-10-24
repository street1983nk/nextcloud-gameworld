"""Strukturtest der Routen-Sperren (06-02, RESEARCH F-03, T-06-06, T-06-12).

Seit Phase 6 steht ^/api/.* in info.xml auf USER: AppAPI lässt jedes angemeldete
Konto bis zur ExApp durch. Die einzige Sperre der Verwaltung ist darum
require_verwalter bzw. require_nc_admin in Python. Dieser Test liest die Routen
aus der echten App (nicht aus einer Hand-Liste) und verlangt für jede Route
unter /api/ außer /api/me und /api/my/ eine der beiden Sperren im
Abhängigkeitsbaum, für /api/admin/ require_nc_admin.

Gegenprobe (Owner-Regel): Der Prüfer erkennt auf einer frischen App eine bewusst
ungesperrte Route als Verstoß; der Kind-Negativtest prüft dieselben Routen über
echte Anfragen.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

import fastapi.routing
import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from gameworld.access.roles import MSG_FORBIDDEN, MSG_NC_ADMIN_ONLY, require_nc_admin, require_verwalter
from gameworld.api import worlds
from tests.conftest import FakeDirectory, appapi_headers

INFO_XML = Path(__file__).resolve().parent.parent / "appinfo" / "info.xml"
KID = "gw-kind"
# Beispielwerte für Pfadparameter; die Sperre greift vor jeder Pfadprüfung.
SAMPLE_PARAMS = {"world_id": "aaaaaaaaaaa1", "nc_user": "gw-kind", "holiday_id": "1"}


def _flat_routes(routes: Sequence[BaseRoute]) -> list[BaseRoute]:
    """Alle Routen samt eingebundener Router; FastAPI 0.14x hält sie nicht mehr flach in app.routes."""
    flatten: Callable[[Sequence[BaseRoute]], Iterable[BaseRoute]] | None = getattr(
        fastapi.routing, "_iter_included_route_candidates", None
    )
    return list(routes) if flatten is None else list(flatten(routes))


def _dependency_calls(route: APIRoute) -> set[Callable[..., Any]]:
    """Alle Abhängigkeits-Callables einer Route, rekursiv über den ganzen Baum."""
    found: set[Callable[..., Any]] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependency = stack.pop()
        if dependency.call is not None:
            found.add(dependency.call)
        stack.extend(dependency.dependencies)
    return found


def _is_self_service(path: str) -> bool:
    """Nur eigene Daten (ROLLE-01): /api/me und /api/my/... ohne Verwalter-Sperre."""
    return path == "/api/me" or path.startswith("/api/my/")


def _is_admin(path: str) -> bool:
    return path == "/api/admin" or path.startswith("/api/admin/")


def guard_violations(app: FastAPI) -> list[str]:
    """Routen unter /api/ ohne passende Sperre, als "METHODEN PFAD"."""
    violations: list[str] = []
    for route in _flat_routes(app.routes):
        path = str(getattr(route, "path", ""))
        if not (path == "/api" or path.startswith("/api/")) or _is_self_service(path):
            continue
        if not isinstance(route, APIRoute):
            violations.append(f"{type(route).__name__} {path}")
            continue
        calls = _dependency_calls(route)
        if _is_admin(path):
            guarded = require_nc_admin in calls
        else:
            guarded = require_verwalter in calls or require_nc_admin in calls
        if not guarded:
            violations.append(f"{','.join(sorted(route.methods or ()))} {path}")
    return violations


def _app() -> FastAPI:
    from gameworld.main import APP

    return APP


def _guarded_requests() -> list[tuple[str, str, bool]]:
    """(Verb, Pfad mit Beispielwerten, Admin-Abschnitt?) für jede gesperrte Route der echten App."""
    result: list[tuple[str, str, bool]] = []
    for route in _flat_routes(_app().routes):
        if not isinstance(route, APIRoute):
            continue
        path = route.path
        if not path.startswith("/api/") or _is_self_service(path):
            continue
        concrete = re.sub(r"\{(\w+)(?::\w+)?\}", lambda match: SAMPLE_PARAMS.get(match.group(1), "x"), path)
        result.extend((method, concrete, _is_admin(path)) for method in sorted(route.methods or ()))
    return result


GUARDED = _guarded_requests()


# Struktur


def test_every_api_route_carries_a_guard() -> None:
    assert guard_violations(_app()) == []


def test_route_listing_is_not_vacuous() -> None:
    """Fände die Auflistung nach einem FastAPI-Update keine Routen mehr, wäre der Strukturtest leer."""
    paths = {path for _method, path, _admin in GUARDED}
    assert len(GUARDED) >= 40
    assert {"/api/worlds", "/api/admin/verwalter-groups", "/api/admin/groups", "/api/pause"} <= paths
    assert sum(1 for _method, _path, admin in GUARDED if admin) == 4


def test_admin_routes_carry_nc_admin_guard() -> None:
    admin_routes = [
        route
        for route in _flat_routes(_app().routes)
        if isinstance(route, APIRoute) and route.path.startswith("/api/admin/")
    ]
    assert len(admin_routes) == 4
    assert all(require_nc_admin in _dependency_calls(route) for route in admin_routes)


def test_checker_flags_an_unguarded_route() -> None:
    """Positivkontrolle des Prüfers: ungesperrt und falsch gesperrt (Admin nur mit Verwalter) sind Verstöße."""
    probe = FastAPI()
    open_router = APIRouter(prefix="/api")

    @open_router.get("/probe")
    async def probe_open() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    weak_admin = APIRouter(prefix="/api/admin", dependencies=[Depends(require_verwalter)])

    @weak_admin.post("/probe")
    async def probe_weak_admin() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    async def nested(uid: str = Depends(require_verwalter)) -> str:
        return uid

    fine = APIRouter(prefix="/api", dependencies=[Depends(nested)])

    @fine.get("/fine")
    async def probe_fine() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    admin_fine = APIRouter(prefix="/api/admin", dependencies=[Depends(require_nc_admin)])

    @admin_fine.get("/fine")
    async def probe_admin_fine() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    me = APIRouter(prefix="/api")

    @me.get("/my/own")
    async def probe_own() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {}

    for router in (open_router, weak_admin, fine, admin_fine, me):
        probe.include_router(router)
    assert guard_violations(probe) == ["GET /api/probe", "POST /api/admin/probe"]


# Negativtest über echte Anfragen


@pytest.fixture
def no_service(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Der Weltdienst darf für ein Kind nie gebaut werden."""
    del app_env
    calls: list[str] = []

    def forbidden_service() -> worlds.WorldService:
        calls.append("get_service")
        raise AssertionError("Dienst für ein Kind aufgerufen")

    monkeypatch.setitem(_app().dependency_overrides, worlds.get_service, forbidden_service)
    return calls


@pytest.mark.parametrize(("method", "path", "admin"), GUARDED, ids=[f"{m} {p}" for m, p, _a in GUARDED])
async def test_child_gets_403_on_every_guarded_route(
    client: httpx.AsyncClient,
    no_service: list[str],
    fake_directory: FakeDirectory,
    method: str,
    path: str,
    admin: bool,
) -> None:
    response = await client.request(method, path, json={}, headers=appapi_headers(KID))
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": MSG_NC_ADMIN_ONLY if admin else MSG_FORBIDDEN}
    assert no_service == []
    assert fake_directory.calls == []
    assert fake_directory.group_calls == []


# Spike-Routen (D-23): bleiben im Manifest, antworten ohne Schalter mit 404


def test_spike_routes_stay_in_manifest() -> None:
    content = INFO_XML.read_text(encoding="utf-8")
    assert "<url>^/play/.*</url>" in content
    assert "<url>^/api/my/play-ticket$</url>" in content


async def test_spike_routes_are_404_without_switch(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GAMEWORLD_BROWSER_SPIKE", raising=False)
    page = await client.get("/play/index.html", headers=appapi_headers(KID))
    assert page.status_code == 404
    ticket = await client.post("/api/my/play-ticket", json={"world_id": "aaaaaaaaaaa1"}, headers=appapi_headers(KID))
    assert ticket.status_code == 404
    # Auch ein Verwalter bekommt ohne Schalter nichts.
    admin_ticket = await client.post("/api/my/play-ticket", json={"world_id": "aaaaaaaaaaa1"}, headers=appapi_headers())
    assert admin_ticket.status_code == 404
