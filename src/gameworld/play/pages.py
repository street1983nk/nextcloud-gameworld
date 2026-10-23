"""Spielseite des Browser-Spikes und Auslieferung der luanti-wasm-Artefakte (04.2-02).

Das Spiel braucht ein eigenes Top-Level-Dokument mit COOP/COEP (crossOriginIsolated,
RESEARCH Pattern 3); in der Nextcloud-Seite kann es nicht laufen. Jede Antwort dieses
Routers trägt darum die Header aus ``security_headers`` (Cross-Origin-Embedder-Policy
require-corp, Cross-Origin-Resource-Policy same-origin, CSP), auch jede 404.

Artefakte kommen nur aus ``play_www_dir()/<a|b>/``: Build-Ordner fest, Endungen aus
einer Liste, Pfad nach ``resolve`` innerhalb des Build-Ordners, reguläre Datei. Alle
Ablehnungen sind dieselbe 404 ohne Pfad im Text.

Release-Ordner: build_www.sh legt launcher.js, luanti.js, worker.js und packs/ in
``www/<release>/`` ab (release = 12 Hex-Zeichen, je Build zufällig), und launcher.js
lädt sie über den relativen Pfad ``<release>/...``, aufgelöst gegen die URL des
Dokuments (/play/). Darum gibt es zusätzlich ``/play/<release>/<datei>``: Der
Release-Name bestimmt eindeutig den Build-Ordner, danach gelten dieselben Prüfungen.
``/play/release/<a|b>`` nennt play.js den Release-Namen eines Builds.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from starlette.convertors import Convertor, register_url_convertor
from starlette.responses import FileResponse, JSONResponse

from gameworld.play.app import require_play_enabled
from gameworld.play.config import allowed_origins, play_www_dir, security_headers

RELEASE_PATTERN = "[0-9a-f]{12}"
_RELEASE_RE = re.compile(RELEASE_PATTERN)


class ReleaseConvertor(Convertor[str]):
    """Pfadteil nur aus 12 kleinen Hex-Zeichen (Release-Name aus build_www.sh)."""

    regex = RELEASE_PATTERN

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


# Eigener Konverter statt {release}: Die Route trifft so nur Release-Namen und
# verdeckt keine späteren /play/<wort>/...-Routen (Plan 06/07).
register_url_convertor("gwrelease", ReleaseConvertor())

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


def resolve_artifact(www: Path, build: str, path: str, release: str = "") -> tuple[Path, str] | None:
    """Datei und Content-Type eines Artefakts oder None; rein bis auf das Dateisystem.

    Mit ``release`` ist die Grenze der Release-Ordner, nicht der ganze Build-Ordner.
    """
    if build not in BUILDS or (release and not _RELEASE_RE.fullmatch(release)):
        return None
    media_type = STATIC_TYPES.get(Path(path).suffix.lower())
    if media_type is None or "\0" in path:
        return None
    try:
        base = (www / build / release).resolve()
        target = (base / path).resolve()
    except (OSError, ValueError):
        return None
    if target == base or not target.is_relative_to(base) or not target.is_file():
        return None
    return target, media_type


def find_release(www: Path, build: str) -> str | None:
    """Name des einzigen Release-Ordners eines Builds oder None (keiner oder mehrere)."""
    if build not in BUILDS:
        return None
    try:
        names = [
            entry.name
            for entry in (www / build).iterdir()
            if _RELEASE_RE.fullmatch(entry.name) and entry.is_dir() and not entry.is_symlink()
        ]
    except OSError:
        return None
    return names[0] if len(names) == 1 else None


def _artifact_response(found: tuple[Path, str] | None) -> FileResponse:
    if found is None:
        raise _not_found()
    target, media_type = found
    return FileResponse(target, media_type=media_type, headers=_headers("no-cache"))


@router.get("/release/{build}")
async def play_release(build: str) -> JSONResponse:
    release = find_release(play_www_dir(), build)
    if release is None:
        raise _not_found()
    return JSONResponse({"release": release}, headers=_headers("no-store"))


@router.get("/static/{build}/{path:path}")
async def play_static(build: str, path: str) -> FileResponse:
    return _artifact_response(resolve_artifact(play_www_dir(), build, path))


@router.get("/{release:gwrelease}/{path:path}")
async def play_release_file(release: str, path: str) -> FileResponse:
    www = play_www_dir()
    for build in sorted(BUILDS):
        if find_release(www, build) == release:
            return _artifact_response(resolve_artifact(www, build, path, release))
    raise _not_found()
