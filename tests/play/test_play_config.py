"""Reine Regeln des Browser-Spikes: Schalter, Origins, disable_for, Header (04.2-02)."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

import pytest

from gameworld.play.config import (
    allowed_origins,
    auth_variant,
    origin_allowed,
    play_base,
    play_disable_for,
    play_mode,
    play_www_dir,
    security_headers,
    udp_host,
)


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        # Positivkontrollen: die drei bekannten Modi.
        ({}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": "off"}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": "dev"}, "dev"),
        ({"GAMEWORLD_BROWSER_SPIKE": "harp"}, "harp"),
        # Manipulierte Eingaben: alles Unbekannte bleibt aus.
        ({"GAMEWORLD_BROWSER_SPIKE": "DEV"}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": "on"}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": "1"}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": ""}, "off"),
        ({"GAMEWORLD_BROWSER_SPIKE": " dev"}, "off"),
    ],
)
def test_play_mode(environ: dict[str, str], expected: str) -> None:
    assert play_mode(environ) == expected


def test_play_disable_for_only_in_dev() -> None:
    assert play_disable_for("dev") == ["play", "play/*"]
    assert play_disable_for("off") == []
    assert play_disable_for("harp") == []


# Unabhängige Gegenprobe mit fnmatch direkt (so prüft AppAPIAuthMiddleware den Pfad
# ohne führenden Schrägstrich): Die Ticket-Route und jede api/*-Route bleiben geschützt.
PROTECTED = [
    "api/my/play-ticket",
    "api/my/worlds",
    "api/worlds",
    "api/me",
    "heartbeat",
    "init",
    "enabled",
    "js/gameworld-main.js",
    "talk/bot",
    "playx",
    "api/play/ws",
]


@pytest.mark.parametrize("path", PROTECTED)
def test_disable_for_never_hits_protected(path: str) -> None:
    assert not any(fnmatch(path, pattern) for pattern in play_disable_for("dev"))


@pytest.mark.parametrize("path", ["play", "play/", "play/ws", "play/launch", "play/static/a/luanti.wasm"])
def test_disable_for_hits_play_paths(path: str) -> None:
    # Positivkontrolle: ohne Treffer hier wäre die Gegenprobe oben wertlos.
    assert any(fnmatch(path, pattern) for pattern in play_disable_for("dev"))


def test_allowed_origins_normalized() -> None:
    environ = {"GAMEWORLD_PLAY_ORIGINS": "http://localhost:8092, https://Host.ts.net/"}
    assert allowed_origins(environ) == frozenset({"http://localhost:8092", "https://host.ts.net"})


@pytest.mark.parametrize(
    "value",
    [
        # Manipulierte Eingaben: fremdes Schema, Pfad, Query, Fragment, Zugangsdaten, leer.
        "",
        " , ",
        "ftp://host.example",
        "ws://host.example",
        "javascript:alert(1)",
        "https://host.example/path",
        "https://host.example?x=1",
        "https://host.example#frag",
        "https://user@host.example",
        "https://host.example:99999",
        "host.example",
        "null",
    ],
)
def test_allowed_origins_rejects(value: str) -> None:
    assert allowed_origins({"GAMEWORLD_PLAY_ORIGINS": value}) == frozenset()


def test_allowed_origins_default_empty() -> None:
    assert allowed_origins({}) == frozenset()


ALLOWED = frozenset({"http://localhost:8092", "https://host.ts.net"})


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        # Positivkontrollen.
        ("http://localhost:8092", True),
        ("https://host.ts.net", True),
        ("https://HOST.ts.net", True),
        ("https://host.ts.net/", True),
        # Manipulierte Eingaben.
        (None, False),
        ("null", False),
        ("", False),
        ("http://localhost:8092.evil.example", False),
        ("http://LOCALHOST:8092/x", False),
        ("http://localhost:8093", False),
        ("https://localhost:8092", False),
        ("http://localhost", False),
        ("https://host.ts.net.evil.example", False),
        ("https://evil.example@host.ts.net", False),
        ("wss://host.ts.net", False),
    ],
)
def test_origin_allowed(origin: str | None, expected: bool) -> None:
    assert origin_allowed(origin, ALLOWED) is expected


def _csp_directives(csp: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            result[tokens[0]] = tokens[1:]
    return result


def test_security_headers() -> None:
    headers = security_headers(frozenset({"https://host.ts.net"}))
    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert headers["Cross-Origin-Embedder-Policy"] == "require-corp"
    assert headers["Cross-Origin-Resource-Policy"] == "same-origin"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["Permissions-Policy"] == "fullscreen=(self)"
    assert headers["Feature-Policy"] == "fullscreen 'self'"
    csp = headers["Content-Security-Policy"]
    assert "script-src 'self' 'wasm-unsafe-eval'" in csp
    assert "worker-src 'self' blob:" in csp
    assert "frame-ancestors 'none'" in csp
    assert "base-uri 'none'" in csp
    directives = _csp_directives(csp)
    assert directives["default-src"] == ["'none'"]
    assert directives["connect-src"] == ["'self'", "wss://host.ts.net"]
    assert "dustlabs" not in csp


def test_security_headers_ws_forms() -> None:
    directives = _csp_directives(security_headers(ALLOWED)["Content-Security-Policy"])
    assert sorted(directives["connect-src"]) == sorted(["'self'", "ws://localhost:8092", "wss://host.ts.net"])


def test_security_headers_without_origins() -> None:
    directives = _csp_directives(security_headers(frozenset())["Content-Security-Policy"])
    assert directives["connect-src"] == ["'self'"]


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, "password"),
        ({"GAMEWORLD_PLAY_AUTH": "password"}, "password"),
        ({"GAMEWORLD_PLAY_AUTH": "proxy_srp"}, "proxy_srp"),
        ({"GAMEWORLD_PLAY_AUTH": "PROXY_SRP"}, "password"),
        ({"GAMEWORLD_PLAY_AUTH": "none"}, "password"),
    ],
)
def test_auth_variant(environ: dict[str, str], expected: str) -> None:
    assert auth_variant(environ) == expected


def test_paths_and_hosts_defaults(tmp_path: Path) -> None:
    assert play_www_dir({}) == (Path.cwd() / ".dev" / "luanti-wasm-www").resolve()
    assert play_www_dir({"GAMEWORLD_PLAY_WWW": str(tmp_path)}) == tmp_path.resolve()
    assert play_base({}) == "/exapps/gameworld"
    assert play_base({"GAMEWORLD_PLAY_BASE": "/apps/x/"}) == "/apps/x"
    assert udp_host({}) == "127.0.0.1"
    assert udp_host({"GAMEWORLD_PLAY_UDP_HOST": "10.0.0.5"}) == "10.0.0.5"
