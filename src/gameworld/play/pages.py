"""Spielseite des Browser-Spikes und Auslieferung der luanti-wasm-Artefakte (04.2-02).

Das Spiel braucht ein eigenes Top-Level-Dokument mit COOP/COEP (crossOriginIsolated,
RESEARCH Pattern 3); in der Nextcloud-Seite kann es nicht laufen. Jede Antwort dieses
Routers trägt darum die Header aus ``security_headers`` (Cross-Origin-Embedder-Policy
require-corp, Cross-Origin-Resource-Policy same-origin, CSP), auch jede 404.

Artefakte kommen nur aus ``play_www_dir()/<a|b>/``: Build-Ordner fest, Endungen aus
einer Liste, Pfad nach ``resolve`` innerhalb des Build-Ordners, reguläre Datei. Alle
Ablehnungen sind dieselbe 404 ohne Pfad im Text.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from starlette.responses import FileResponse

from gameworld.play.app import require_play_enabled
from gameworld.play.config import allowed_origins, play_www_dir, security_headers

router = APIRouter(prefix="/play", dependencies=[Depends(require_play_enabled)])

BUILDS = frozenset({"a", "b"})
STATIC_TYPES: dict[str, str] = {
    ".wasm": "application/wasm",
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".json": "application/json",
    ".pack": "application/octet-stream",
    ".data": "application/octet-stream",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".css": "text/css",
    ".html": "text/html",
}
# Relativ zum Arbeitsverzeichnis wie map_app_static (cwd = Repo-Root, main.py).
WEBPLAY_DIR = "webplay"


def _headers(cache: str) -> dict[str, str]:
    return {**security_headers(allowed_origins()), "Cache-Control": cache}


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, headers=_headers("no-store"))


def _page_file(name: str, media_type: str) -> FileResponse:
    path = Path.cwd() / WEBPLAY_DIR / name
    if not path.is_file():
        raise _not_found()
    return FileResponse(path, media_type=media_type, headers=_headers("no-store"))


@router.get("/")
async def play_page() -> FileResponse:
    return _page_file("play.html", "text/html")


@router.get("/play.js")
async def play_script() -> FileResponse:
    return _page_file("play.js", "text/javascript")


def resolve_artifact(www: Path, build: str, path: str) -> tuple[Path, str] | None:
    """Datei und Content-Type eines Artefakts oder None; rein bis auf das Dateisystem."""
    if build not in BUILDS:
        return None
    media_type = STATIC_TYPES.get(Path(path).suffix.lower())
    if media_type is None or "\0" in path:
        return None
    try:
        base = (www / build).resolve()
        target = (base / path).resolve()
    except (OSError, ValueError):
        return None
    if target == base or not target.is_relative_to(base) or not target.is_file():
        return None
    return target, media_type


@router.get("/static/{build}/{path:path}")
async def play_static(build: str, path: str) -> FileResponse:
    found = resolve_artifact(play_www_dir(), build, path)
    if found is None:
        raise _not_found()
    target, media_type = found
    return FileResponse(target, media_type=media_type, headers=_headers("no-cache"))
