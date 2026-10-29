"""API contract without Docker: no visibility field, no injection, only registry presets, only signed calls."""

import httpx
import pytest

from tests.conftest import appapi_headers


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "server_announce": True},
        {"name": "x", "public": True},
        {"name": "Welt\nserver_announce = true"},
        {"name": "x", "preset": "mtg_kreativ", "mem_limit": "8g"},
    ],
)
async def test_rejected_bodies_return_422(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.post("/api/worlds", json=body, headers=appapi_headers())
    assert response.status_code == 422


async def test_invalid_name_detail_carries_german_message(client: httpx.AsyncClient) -> None:
    """The 422 detail list carries the German name message; the frontend shows detail[0].msg (WR-03)."""
    response = await client.post("/api/worlds", json={"name": "Mias & Leos Welt"}, headers=appapi_headers())
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert "Weltname" in detail[0]["msg"]


async def test_unsigned_request_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds", json={"name": "x"})
    assert response.status_code == 401


async def test_unknown_preset_returns_422_with_german_message(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds", json={"name": "x", "preset": "survival_hart"}, headers=appapi_headers())
    assert response.status_code == 422
    assert "Unbekannte Spielart" in response.json()["detail"][0]["msg"]


async def test_presets_lists_registry_without_internals(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/presets", headers=appapi_headers())
    assert response.status_code == 200
    presets = response.json()["presets"]
    assert [preset["id"] for preset in presets] == ["mtg_kreativ", "voxelibre_sanft"]
    assert presets[0]["title"] == "Bauen (kreativ)"
    assert presets[1]["title"] == "Abenteuer (sanft)"
    for preset in presets:
        assert preset["description"]
        assert set(preset) == {"id", "title", "description"}
