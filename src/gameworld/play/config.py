"""Pure rules of the browser spike 04.2: switch, allowed origins, disable_for, headers.

Standard library only. Every function takes ``environ`` (default ``os.environ``), so that tests
get by without monkeypatch and the mode is read fresh on each call.

Switch ``GAMEWORLD_BROWSER_SPIKE``:

- ``off`` (default, also for every unknown value): all /play/ routes give 404.
- ``dev``: dev stack without AppAPI identity on /play/* (the PHP proxy cannot do a
  WebSocket upgrade); there the ticket alone counts (from plan 06).
- ``harp``: the auth middleware stays on everywhere, /play/* needs the HaRP identity.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

PlayMode = Literal["off", "dev", "harp"]
AuthVariant = Literal["password", "proxy_srp"]

ENV_MODE = "GAMEWORLD_BROWSER_SPIKE"
ENV_ORIGINS = "GAMEWORLD_PLAY_ORIGINS"
ENV_WWW = "GAMEWORLD_PLAY_WWW"
ENV_BASE = "GAMEWORLD_PLAY_BASE"
ENV_UDP_HOST = "GAMEWORLD_PLAY_UDP_HOST"
ENV_AUTH = "GAMEWORLD_PLAY_AUTH"

DEFAULT_WWW = ".dev/luanti-wasm-www"
DEFAULT_BASE = "/exapps/gameworld"
DEFAULT_UDP_HOST = "127.0.0.1"

# Patterns for AppAPIAuthMiddleware(disable_for=...), checked with fnmatch against the path without
# leading slash. They must never hit api/*: the ticket route
# api/my/play-ticket needs the AppAPI identity (tests/play/test_play_config.py).
DEV_DISABLE_FOR = ("play", "play/*")

_MODES: dict[str, PlayMode] = {"off": "off", "dev": "dev", "harp": "harp"}
_AUTH_VARIANTS: dict[str, AuthVariant] = {"password": "password", "proxy_srp": "proxy_srp"}
_WS_SCHEMES = {"http": "ws", "https": "wss"}


def play_mode(environ: Mapping[str, str] = os.environ) -> PlayMode:
    """Mode exactly as set (lower-cased, without spaces); anything unknown means off."""
    return _MODES.get(environ.get(ENV_MODE, "off"), "off")


def play_disable_for(mode: PlayMode) -> list[str]:
    """Exceptions of the auth middleware: only in mode dev, only play and play/*."""
    return list(DEV_DISABLE_FOR) if mode == "dev" else []


def _normalize_origin(value: str) -> str | None:
    """Canonical form scheme://host[:port] or None if not a valid origin."""
    value = value.strip()
    if not value or "?" in value or "#" in value:
        return None
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    if scheme not in _WS_SCHEMES or parts.path not in ("", "/"):
        return None
    if parts.username is not None or parts.password is not None:
        return None
    host = parts.hostname
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if ":" in host:
        host = f"[{host}]"
    return f"{scheme}://{host}" if port is None else f"{scheme}://{host}:{port}"


def allowed_origins(environ: Mapping[str, str] = os.environ) -> frozenset[str]:
    """Allowed origins from GAMEWORLD_PLAY_ORIGINS (comma-separated); empty means none."""
    result: set[str] = set()
    for entry in environ.get(ENV_ORIGINS, "").split(","):
        normalized = _normalize_origin(entry)
        if normalized is not None:
            result.add(normalized)
    return frozenset(result)


def origin_allowed(origin: str | None, allowed: frozenset[str]) -> bool:
    """Origin header against the allowed set: same normalization, then exact comparison."""
    if origin is None:
        return False
    normalized = _normalize_origin(origin)
    return normalized is not None and normalized in allowed


def _ws_form(origin: str) -> str:
    scheme, rest = origin.split("://", 1)
    return f"{_WS_SCHEMES[scheme]}://{rest}"


def security_headers(allowed: frozenset[str]) -> dict[str, str]:
    """Headers of every response of the play route (RESEARCH pattern 3).

    COOP/COEP make the document crossOriginIsolated (SharedArrayBuffer), CORP allows
    the subresources only from the same origin. connect-src names only its own
    origin and the ws(s) form of the allowed origins: a default proxy of foreign hosts
    is thus blocked even if setProxy should ever be missing (D-01).
    """
    connect = " ".join(["'self'", *(_ws_form(origin) for origin in sorted(allowed))])
    csp = "; ".join(
        [
            "default-src 'none'",
            "script-src 'self' 'wasm-unsafe-eval'",
            "worker-src 'self' blob:",
            f"connect-src {connect}",
            "img-src 'self' blob: data:",
            "style-src 'self' 'unsafe-inline'",
            "frame-ancestors 'none'",
            "base-uri 'none'",
        ]
    )
    return {
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "require-corp",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Content-Security-Policy": csp,
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "Permissions-Policy": "fullscreen=(self)",
        # Only for manual-install: the AppAPI PHP proxy would otherwise set fullscreen 'none'.
        "Feature-Policy": "fullscreen 'self'",
    }


def play_www_dir(environ: Mapping[str, str] = os.environ) -> Path:
    """Directory with the build folders a and b, relative to the working directory (repo root)."""
    return (Path.cwd() / environ.get(ENV_WWW, DEFAULT_WWW)).resolve()


def play_base(environ: Mapping[str, str] = os.environ) -> str:
    """Path prefix of the ExApp from the browser's view, without a trailing slash."""
    return environ.get(ENV_BASE, DEFAULT_BASE).rstrip("/")


def udp_host(environ: Mapping[str, str] = os.environ) -> str:
    """Destination host of the world UDP ports for the proxy (from plan 07)."""
    return environ.get(ENV_UDP_HOST, DEFAULT_UDP_HOST)


def auth_variant(environ: Mapping[str, str] = os.environ) -> AuthVariant:
    """password (variant B, default) or proxy_srp (variant A, plan 09)."""
    return _AUTH_VARIANTS.get(environ.get(ENV_AUTH, "password"), "password")
