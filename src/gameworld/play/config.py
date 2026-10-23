"""Reine Regeln des Browser-Spikes 04.2: Schalter, erlaubte Origins, disable_for, Header.

Nur stdlib. Jede Funktion nimmt ``environ`` (Vorgabe ``os.environ``), damit Tests
ohne monkeypatch auskommen und der Modus je Aufruf frisch gelesen wird.

Schalter ``GAMEWORLD_BROWSER_SPIKE``:

- ``off`` (Vorgabe, auch für jeden unbekannten Wert): alle /play/-Routen geben 404.
- ``dev``: Dev-Stack ohne AppAPI-Identität an /play/* (der PHP-Proxy kann kein
  WebSocket-Upgrade); dort trägt allein das Ticket (ab Plan 06).
- ``harp``: Die Auth-Middleware bleibt überall an, /play/* braucht die HaRP-Identität.
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

# Muster für AppAPIAuthMiddleware(disable_for=...), per fnmatch gegen den Pfad ohne
# führenden Schrägstrich geprüft. Sie dürfen nie api/* treffen: Die Ticket-Route
# api/my/play-ticket braucht die AppAPI-Identität (tests/play/test_play_config.py).
DEV_DISABLE_FOR = ("play", "play/*")

_MODES: dict[str, PlayMode] = {"off": "off", "dev": "dev", "harp": "harp"}
_AUTH_VARIANTS: dict[str, AuthVariant] = {"password": "password", "proxy_srp": "proxy_srp"}
_WS_SCHEMES = {"http": "ws", "https": "wss"}


def play_mode(environ: Mapping[str, str] = os.environ) -> PlayMode:
    """Modus exakt wie gesetzt (kleingeschrieben, ohne Leerzeichen); Unbekanntes heißt off."""
    return _MODES.get(environ.get(ENV_MODE, "off"), "off")


def play_disable_for(mode: PlayMode) -> list[str]:
    """Ausnahmen der Auth-Middleware: nur im Modus dev, nur play und play/*."""
    return list(DEV_DISABLE_FOR) if mode == "dev" else []


def _normalize_origin(value: str) -> str | None:
    """Kanonische Form schema://host[:port] oder None, wenn kein gültiger Origin."""
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
    """Erlaubte Origins aus GAMEWORLD_PLAY_ORIGINS (kommagetrennt); leer heißt keiner."""
    result: set[str] = set()
    for entry in environ.get(ENV_ORIGINS, "").split(","):
        normalized = _normalize_origin(entry)
        if normalized is not None:
            result.add(normalized)
    return frozenset(result)


def origin_allowed(origin: str | None, allowed: frozenset[str]) -> bool:
    """Origin-Header gegen die erlaubte Menge: gleiche Normalisierung, dann exakter Vergleich."""
    if origin is None:
        return False
    normalized = _normalize_origin(origin)
    return normalized is not None and normalized in allowed


def _ws_form(origin: str) -> str:
    scheme, rest = origin.split("://", 1)
    return f"{_WS_SCHEMES[scheme]}://{rest}"


def security_headers(allowed: frozenset[str]) -> dict[str, str]:
    """Header jeder Antwort der Spielroute (RESEARCH Pattern 3).

    COOP/COEP machen das Dokument crossOriginIsolated (SharedArrayBuffer), CORP erlaubt
    die Unterressourcen nur vom gleichen Origin. connect-src nennt nur den eigenen
    Origin und die ws(s)-Form der erlaubten Origins: Ein Default-Proxy fremder Hosts
    wird so auch dann blockiert, wenn setProxy einmal fehlen sollte (D-01).
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
        # Nur für manual-install: der AppAPI-PHP-Proxy setzt sonst fullscreen 'none'.
        "Feature-Policy": "fullscreen 'self'",
    }


def play_www_dir(environ: Mapping[str, str] = os.environ) -> Path:
    """Verzeichnis mit den Build-Ordnern a und b, relativ zum Arbeitsverzeichnis (Repo-Root)."""
    return (Path.cwd() / environ.get(ENV_WWW, DEFAULT_WWW)).resolve()


def play_base(environ: Mapping[str, str] = os.environ) -> str:
    """Pfadpräfix der ExApp aus Browsersicht, ohne Schrägstrich am Ende."""
    return environ.get(ENV_BASE, DEFAULT_BASE).rstrip("/")


def udp_host(environ: Mapping[str, str] = os.environ) -> str:
    """Zielhost der Welt-UDP-Ports für den Proxy (ab Plan 07)."""
    return environ.get(ENV_UDP_HOST, DEFAULT_UDP_HOST)


def auth_variant(environ: Mapping[str, str] = os.environ) -> AuthVariant:
    """password (Variante B, Vorgabe) oder proxy_srp (Variante A, Plan 09)."""
    return _AUTH_VARIANTS.get(environ.get(ENV_AUTH, "password"), "password")
