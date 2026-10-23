"""Spielseite und Artefakt-Auslieferung hinter dem Spike-Schalter (04.2-02)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gameworld.play.config import allowed_origins, security_headers
from tests.conftest import appapi_headers

ORIGINS = "http://test,https://host.ts.net"


@pytest.fixture
def www(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Artefakt-Verzeichnis mit Build a und b, dazu Köder außerhalb der Build-Ordner."""
    root = app_env / "www"
    for build in ("a", "b"):
        (root / build).mkdir(parents=True)
        (root / build / "x.wasm").write_bytes(b"\0asm\1\0\0\0")
        (root / build / "launcher.js").write_text("// launcher\n", encoding="utf-8")
    (root / "a" / "x.exe").write_bytes(b"MZ")
    (root / "c").mkdir()
    (root / "c" / "x.wasm").write_bytes(b"\0asm")
    (root / "secret").write_text("geheim", encoding="utf-8")
    (root / "escape.wasm").write_bytes(b"\0asm")
    (app_env / "pyproject.toml").write_text("geheim", encoding="utf-8")
    monkeypatch.setenv("GAMEWORLD_PLAY_WWW", str(root))
    monkeypatch.setenv("GAMEWORLD_PLAY_ORIGINS", ORIGINS)
    return root


@pytest.fixture
def dev(www: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "dev")
    return www


def _assert_security_headers(response: httpx.Response) -> None:
    for name, value in security_headers(allowed_origins()).items():
        assert response.headers.get(name) == value, name


@pytest.mark.parametrize("mode", [None, "off", "DEV", "on"])
@pytest.mark.parametrize("path", ["/play/", "/play/play.js", "/play/static/a/x.wasm", "/play/static/b/launcher.js"])
async def test_off_hides_everything(
    client: httpx.AsyncClient, www: Path, monkeypatch: pytest.MonkeyPatch, mode: str | None, path: str
) -> None:
    del www
    if mode is None:
        monkeypatch.delenv("GAMEWORLD_BROWSER_SPIKE", raising=False)
    else:
        monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", mode)
    response = await client.get(path, headers=appapi_headers("gw-kind"))
    assert response.status_code == 404
    assert b"asm" not in response.content
    assert b"launcher" not in response.content


async def test_play_page(client: httpx.AsyncClient, dev: Path) -> None:
    del dev
    response = await client.get("/play/", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert "Gameworld im Browser" in response.text
    _assert_security_headers(response)
    assert "wss://host.ts.net" in response.headers["content-security-policy"]


async def test_play_js(client: httpx.AsyncClient, dev: Path) -> None:
    del dev
    response = await client.get("/play/play.js", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    _assert_security_headers(response)


async def test_harp_mode_serves_too(client: httpx.AsyncClient, www: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    del www
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "harp")
    response = await client.get("/play/", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200


@pytest.mark.parametrize("build", ["a", "b"])
async def test_static_wasm(client: httpx.AsyncClient, dev: Path, build: str) -> None:
    del dev
    response = await client.get(f"/play/static/{build}/x.wasm", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/wasm"
    assert response.headers["cross-origin-resource-policy"] == "same-origin"
    assert response.headers["cache-control"] == "no-cache"
    assert response.content == b"\0asm\1\0\0\0"
    _assert_security_headers(response)


async def test_static_js(client: httpx.AsyncClient, dev: Path) -> None:
    del dev
    response = await client.get("/play/static/a/launcher.js", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize(
    "path",
    [
        # Manipulierte Pfade: Ausbruch, kodierter Ausbruch, fremde Endung, fremder Build.
        "/play/static/../secret",
        "/play/static/a/..%2F..%2Fpyproject.toml",
        "/play/static/a/..%2F..%2Fescape.wasm",
        "/play/static/a/..%2Fb%2Fx.wasm",
        "/play/static/%2e%2e/escape.wasm",
        "/play/static/%2e%2e/secret",
        "/play/static/a/x.exe",
        "/play/static/c/x.wasm",
        "/play/static/A/x.wasm",
        "/play/static/a/missing.wasm",
        "/play/static/a/",
        "/play/static/a",
        "/play/static/a/%00x.wasm",
    ],
)
async def test_static_rejects(client: httpx.AsyncClient, dev: Path, path: str) -> None:
    del dev
    response = await client.get(path, headers=appapi_headers("gw-kind"))
    assert response.status_code == 404
    assert b"geheim" not in response.content
    assert b"asm" not in response.content
    assert b"MZ" not in response.content
    assert "www" not in response.text


async def test_static_404_carries_headers(client: httpx.AsyncClient, dev: Path) -> None:
    del dev
    response = await client.get("/play/static/c/x.wasm", headers=appapi_headers("gw-kind"))
    assert response.status_code == 404
    _assert_security_headers(response)


async def test_api_stays_protected_in_dev(client: httpx.AsyncClient, dev: Path) -> None:
    """Gegenprobe: Ohne AppAPI-Header kommt im Modus dev nichts unter api/* durch.

    Die Middleware liest den Modus beim Import von main; geprüft wird hier die Wirkung
    auf api/*, die in jedem Modus geschützt bleibt.
    """
    del dev
    response = await client.get("/api/my/worlds")
    assert response.status_code in (401, 403)
    response = await client.post("/api/my/play-ticket", json={})
    assert response.status_code in (401, 403)
