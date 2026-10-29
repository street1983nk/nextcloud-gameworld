"""Setup check against the real, scoped dev proxy."""

from __future__ import annotations

import httpx
import pytest

from tests.conftest import appapi_headers

pytestmark = pytest.mark.docker


async def test_setup_check_against_dev_proxy(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/setup-check", headers=appapi_headers())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert [item for item in body["items"] if not item["ok"]] == []
