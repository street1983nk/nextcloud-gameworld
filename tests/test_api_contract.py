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


async def test_unsigned_request_returns_401(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/worlds", json={"name": "x"})
    assert response.status_code == 401
