"""ExApp image and supply chain: pins, service user, image scripts (without Docker, T-06-SC, T-06-43)."""

from __future__ import annotations

import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

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
    # D-22: no root entrypoint with chown/gosu.
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
            # Foreign images (uv) also by digest, own stages not.
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


WORKFLOW = ROOT / ".github" / "workflows" / "image.yml"


def _workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_actions_pinned_by_commit_sha() -> None:
    uses = [line.strip() for line in _workflow().splitlines() if line.strip().startswith(("uses:", "- uses:"))]
    assert uses
    for line in uses:
        assert re.search(r"@[0-9a-f]{40}(\s|$)", line), line
        assert re.search(r"# v\d+\.\d+\.\d+$", line), line


def test_workflow_multi_arch_and_rc_path() -> None:
    text = _workflow()
    assert "linux/amd64,linux/arm64" in text
    assert "workflow_dispatch" in text
    assert "image_tag" in text
    assert "ghcr.io/street1983nk/gameworld" in text


def test_workflow_top_permissions_read_only() -> None:
    lines = _workflow().splitlines()
    start = lines.index("permissions:")
    block: list[str] = []
    for line in lines[start + 1 :]:
        if not line.startswith(" "):
            break
        if line.strip() and not line.strip().startswith("#"):
            block.append(line.strip())
    assert block == ["contents: read"]


def test_workflow_never_replaces_assets() -> None:
    assert "--clobber" not in _workflow()


def test_workflow_lockstep_checks_all_sources() -> None:
    text = _workflow()
    for needle in ("<version>", "<image-tag>", "pyproject.toml", "GITHUB_REF_NAME#v"):
        assert needle in text, needle


def test_store_archive_layout(tmp_path: Path) -> None:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("kein sh verfügbar")
    work = tmp_path / "repo"
    for relative in ("appinfo/info.xml", "img/app.svg", "LICENSE", "scripts/build-store-release.sh"):
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    subprocess.run([sh, "scripts/build-store-release.sh"], cwd=work, check=True, capture_output=True)  # noqa: S603
    version = re.search(r"<version>([^<]+)</version>", (ROOT / "appinfo" / "info.xml").read_text(encoding="utf-8"))
    assert version is not None
    archive = work / "dist" / f"gameworld-{version.group(1)}.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
    names = [member.name.removeprefix("./") for member in members]
    assert {name.split("/")[0] for name in names} == {"gameworld"}
    files = sorted(member.name for member in members if member.isfile())
    assert files == ["gameworld/LICENSE", "gameworld/appinfo/info.xml", "gameworld/img/app.svg"]
    assert not any(".git" in name.split("/") for name in names)
    assert all(member.uid == 0 and member.gid == 0 for member in members)
