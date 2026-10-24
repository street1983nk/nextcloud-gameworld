"""ExApp-Image und Lieferkette: Pins, Dienstnutzer, Image-Skripte (ohne Docker, T-06-SC, T-06-43)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "Dockerfile"
IMAGE_SCRIPTS = ROOT / "scripts" / "image"

FRP_AMD64_SHA256 = "1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803"
FRP_ARM64_SHA256 = "8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019"


def _dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def _from_lines() -> list[str]:
    return [line for line in _dockerfile().splitlines() if line.startswith("FROM ")]


def test_runs_as_fixed_service_user() -> None:
    text = _dockerfile()
    assert "USER 10001:10001" in text
    # D-22: kein root-Entrypoint mit chown/gosu.
    assert "gosu" not in text
    assert "--chown" not in text


def test_frpc_pinned_per_architecture() -> None:
    text = _dockerfile()
    assert "FRP_VERSION=0.71.1" in text
    assert FRP_AMD64_SHA256 in text
    assert FRP_ARM64_SHA256 in text
    assert "sha256sum -c" in text


def test_every_base_pinned_by_digest() -> None:
    lines = _from_lines()
    assert len(lines) >= 2
    for line in lines:
        assert re.search(r"@sha256:[0-9a-f]{64}", line), line
        assert ":latest" not in line, line
    for line in _dockerfile().splitlines():
        if line.startswith("COPY --from=") and "/" in line.split()[1]:
            # Fremde Images (uv) ebenfalls per Digest, eigene Stufen nicht.
            source = line.split()[1].removeprefix("--from=")
            if "." in source.split("/")[0]:
                assert "@sha256:" in source, line


def test_no_spike_artifacts_in_image() -> None:
    text = _dockerfile()
    assert not re.search(r"^COPY\s+.*webplay", text, re.MULTILINE)
    assert "luanti-wasm" not in text


def test_games_checked_against_sums() -> None:
    text = _dockerfile()
    assert "scripts/fetch-games.sh" in text
    assert "sha256sum -c SHA256SUMS" in text


def test_entrypoint_and_healthcheck_wired() -> None:
    text = _dockerfile()
    assert 'ENTRYPOINT ["/entrypoint.sh"' in text
    assert 'CMD ["/healthcheck.sh"]' in text
    assert "WORKDIR /app" in text


def test_image_scripts_exist() -> None:
    for name in ("start.sh", "entrypoint.sh", "healthcheck.sh"):
        script = IMAGE_SCRIPTS / name
        assert script.is_file(), name
        assert script.read_bytes().startswith(b"#!/"), name
        assert b"\r\n" not in script.read_bytes(), f"{name} hat CRLF"
    entrypoint = (IMAGE_SCRIPTS / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'exec /start.sh "$@"' in entrypoint
    assert "nicht schreibbar für uid 10001" in entrypoint
    assert "DNS_REBINDING" not in entrypoint


def test_dockerignore_keeps_context_small() -> None:
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".git", ".planning/", "tests/", "webplay/", "js/", "node_modules/"):
        assert entry in lines, entry
