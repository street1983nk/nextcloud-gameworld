"""Play page and artifact delivery behind the spike switch (04.2-02)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from gameworld.play.config import allowed_origins, security_headers
from tests.conftest import appapi_headers

ORIGINS = "http://test,https://host.ts.net"
RELEASE_A = "0123456789ab"
RELEASE_B = "ba9876543210"


@pytest.fixture
def www(app_env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Artifact directory with builds a and b, plus a decoy outside the build folders."""
    root = app_env / "www"
    for build in ("a", "b"):
        (root / build).mkdir(parents=True)
        (root / build / "x.wasm").write_bytes(b"\0asm\1\0\0\0")
        (root / build / "launcher.js").write_text("// launcher\n", encoding="utf-8")
    for build, release in (("a", RELEASE_A), ("b", RELEASE_B)):
        (root / build / release / "packs").mkdir(parents=True)
        (root / build / release / "luanti.wasm").write_bytes(f"wasm-{build}".encode())
        (root / build / release / "worker.js").write_bytes(f"// worker {build}\n".encode())
        (root / build / release / "packs" / "base.pack").write_bytes(f"pack-{build}".encode())
        (root / build / release / ".htaccess").write_text("Header set x\n", encoding="utf-8")
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
        # Tampered paths: breakout, encoded breakout, foreign extension, foreign build.
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
    # Starlette redirects /play/static/a to /play/static/a/; the end of the chain is what counts.
    response = await client.get(path, headers=appapi_headers("gw-kind"), follow_redirects=True)
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
    """Counter-check: without an AppAPI header nothing under api/* gets through in mode dev.

    The middleware reads the mode on import of main; what is checked here is the effect
    on api/*, which stays protected in every mode.
    """
    del dev
    response = await client.get("/api/my/worlds")
    assert response.status_code in (401, 403)
    response = await client.post("/api/my/play-ticket", json={})
    assert response.status_code in (401, 403)


@pytest.mark.parametrize(("build", "release"), [("a", RELEASE_A), ("b", RELEASE_B)])
async def test_release_name(client: httpx.AsyncClient, dev: Path, build: str, release: str) -> None:
    del dev
    response = await client.get(f"/play/release/{build}", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.json() == {"release": release}
    assert response.headers["cache-control"] == "no-store"
    _assert_security_headers(response)


@pytest.mark.parametrize("build", ["c", "A", "%2e%2e", "a%2F..", ".htaccess"])
async def test_release_name_rejects_foreign_build(client: httpx.AsyncClient, dev: Path, build: str) -> None:
    del dev
    response = await client.get(f"/play/release/{build}", headers=appapi_headers("gw-kind"))
    assert response.status_code == 404


async def test_release_name_needs_exactly_one(client: httpx.AsyncClient, dev: Path) -> None:
    # Two release folders in a: unclear which applies, so none.
    (dev / "a" / "cccccccccccc").mkdir()
    response = await client.get("/play/release/a", headers=appapi_headers("gw-kind"))
    assert response.status_code == 404
    # Positive control in the same setup: b has exactly one.
    response = await client.get("/play/release/b", headers=appapi_headers("gw-kind"))
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("path", "content", "media_type"),
    [
        # Positive controls: the release name selects the build.
        (f"/play/{RELEASE_A}/luanti.wasm", b"wasm-a", "application/wasm"),
        (f"/play/{RELEASE_B}/luanti.wasm", b"wasm-b", "application/wasm"),
        (f"/play/{RELEASE_B}/worker.js", b"// worker b\n", "text/javascript"),
        (f"/play/{RELEASE_A}/packs/base.pack", b"pack-a", "application/octet-stream"),
    ],
)
async def test_release_files(client: httpx.AsyncClient, dev: Path, path: str, content: bytes, media_type: str) -> None:
    del dev
    response = await client.get(path, headers=appapi_headers("gw-kind"))
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith(media_type)
    assert response.headers["cache-control"] == "no-cache"
    _assert_security_headers(response)


@pytest.mark.parametrize(
    "path",
    [
        # Tampered paths: foreign release, capitalization, wrong length, breakout, extension.
        "/play/cccccccccccc/luanti.wasm",
        "/play/0123456789AB/luanti.wasm",
        "/play/0123456789a/luanti.wasm",
        "/play/0123456789abc/luanti.wasm",
        f"/play/{RELEASE_A}/.htaccess",
        f"/play/{RELEASE_A}/..%2F..%2Fescape.wasm",
        f"/play/{RELEASE_A}/..%2F..%2Fb%2F{RELEASE_B}%2Fluanti.wasm",
        f"/play/{RELEASE_A}/..%2Fx.wasm",
        f"/play/{RELEASE_A}/",
    ],
)
async def test_release_files_reject(client: httpx.AsyncClient, dev: Path, path: str) -> None:
    del dev
    response = await client.get(path, headers=appapi_headers("gw-kind"), follow_redirects=True)
    assert response.status_code == 404
    assert b"wasm-" not in response.content
    assert b"asm" not in response.content
    assert b"Header" not in response.content


@pytest.mark.parametrize("path", ["/play/release/a", f"/play/{RELEASE_A}/luanti.wasm"])
async def test_release_routes_off(
    client: httpx.AsyncClient, www: Path, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    del www
    monkeypatch.setenv("GAMEWORLD_BROWSER_SPIKE", "off")
    response = await client.get(path, headers=appapi_headers("gw-kind"))
    assert response.status_code == 404
