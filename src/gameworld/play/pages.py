"""Play page of the browser spike and delivery of the luanti-wasm artifacts (04.2-02).

The game needs its own top-level document with COOP/COEP (crossOriginIsolated,
RESEARCH pattern 3); it cannot run inside the Nextcloud page. Every response of this
router therefore carries the headers from ``security_headers`` (Cross-Origin-Embedder-Policy
require-corp, Cross-Origin-Resource-Policy same-origin, CSP), including every 404.

Artifacts come only from ``play_www_dir()/<a|b>/``: build folder fixed, extensions from
a list, path inside the build folder after ``resolve``, regular file. All
rejections are the same 404 without a path in the text.

Release folder: build_www.sh puts launcher.js, luanti.js, worker.js and packs/ into
``www/<release>/`` (release = 12 hex characters, random per build), and launcher.js
loads them via the relative path ``<release>/...``, resolved against the URL of the
document (/play/). Therefore there is additionally ``/play/<release>/<file>``: the
release name uniquely determines the build folder, after that the same checks apply.
``/play/release/<a|b>`` tells play.js the release name of a build.
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
    """Path part of only 12 lower-case hex characters (release name from build_www.sh)."""

    regex = RELEASE_PATTERN

    def convert(self, value: str) -> str:
        return value

    def to_string(self, value: str) -> str:
        return value


# Own converter instead of {release}: the route thus only hits release names and
# does not shadow later /play/<word>/... routes (plan 06/07).
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
# Relative to the working directory like map_app_static (cwd = repo root, main.py).
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
    """File and content type of an artifact or None; pure except for the file system.

    With ``release`` the boundary is the release folder, not the whole build folder.
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
    """Name of the only release folder of a build or None (none or several)."""
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
