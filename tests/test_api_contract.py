"""API-Vertrag ohne Docker: kein Sichtbarkeitsfeld, keine Injection, nur signierte Aufrufe."""

import httpx
import pytest

from tests.conftest import appapi_headers


@pytest.mark.parametrize(
    "body",
    [
        {"name": "x", "server_announce": True},
        {"name": "x", "public": True},
        {"name": "Welt\nserver_announce = true"},
    ],
)
async def test_rejected_bodies_return_422(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.post("/api/worlds", json=body, headers=appapi_headers())
    assert response.status_code == 422


async def test_invalid_name_detail_carries_german_message(client: httpx.AsyncClient) -> None:
    """422-Detail-Liste trägt die deutsche Namensmeldung; das Frontend zeigt detail[0].msg (WR-03)."""
    response = await client.post("/api/worlds", json={"name": "Mias & Leos Welt"}, headers=appapi_headers())
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert "Weltname" in detail[0]["msg"]


async def test_unsigned_request_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds", json={"name": "x"})
    assert response.status_code == 401
