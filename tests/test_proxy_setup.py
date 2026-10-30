"""Scoped Docker proxy: one source of truth for the docs and the setup check.

The drift test pins the ``gameworld-docker-proxy`` service blocks in docs/install.md
and docs/install.de.md (sections 3a and 3b) against the constants in
``gameworld.provisioner.proxy_setup``; positive controls prove that the comparison
actually notices a changed flag, digest, mount or an added host port.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import httpx
import pytest

from gameworld.api import setup_check as setup_check_api
from gameworld.provisioner import proxy_setup
from gameworld.provisioner.proxy_setup import (
    NETWORK_AIO,
    NETWORK_COMPOSE,
    PROXY_ENV,
    PROXY_IMAGE,
    PROXY_NAME,
    PROXY_RESTART,
    PROXY_SOCKET_MOUNT,
    docker_run_command,
    proxy_commands,
)
from gameworld.provisioner.setup_check import CheckItem, SetupCheckResult
from tests.conftest import appapi_headers

ROOT = Path(__file__).resolve().parents[1]
INSTALL_DOCS = [ROOT / "docs" / "install.md", ROOT / "docs" / "install.de.md"]
SECTIONS = [("### 3a.", NETWORK_COMPOSE), ("### 3b.", NETWORK_AIO)]
DEFAULT_URL = "tcp://gameworld-docker-proxy:2375"


# --- Drift helper ---------------------------------------------------------------------------


def _service_block(doc_text: str, section_heading_prefix: str) -> str | None:
    start = doc_text.find(section_heading_prefix)
    if start < 0:
        return None
    end = doc_text.find("\n### ", start + len(section_heading_prefix))
    section = doc_text[start : end if end >= 0 else len(doc_text)]
    fence = re.search(r"```yaml\n(.*?)```", section, re.DOTALL)
    if fence is None:
        return None
    yaml = fence.group(1)
    service = re.search(rf"^  {PROXY_NAME}:\n(.*?)(?=^  \S|^\S|\Z)", yaml, re.DOTALL | re.MULTILINE)
    return service.group(1) if service is not None else None


def _list_under(block: str, key: str) -> list[str]:
    match = re.search(rf"^    {key}:\n((?:      - .*\n|\s*#.*\n)*)", block, re.MULTILINE)
    if match is None:
        return []
    return re.findall(r"^      - (\S+)", match.group(1), re.MULTILINE)


def _service_drift(doc_text: str, section_heading_prefix: str, expected_network: str) -> list[str]:
    """Human-readable differences between one docs service block and the constants."""
    block = _service_block(doc_text, section_heading_prefix)
    if block is None:
        return [f"{section_heading_prefix}: no {PROXY_NAME} service block found"]
    drift: list[str] = []
    image = re.search(r"^    image: (\S+)", block, re.MULTILINE)
    if image is None or image.group(1) != PROXY_IMAGE:
        drift.append(f"image differs: {image.group(1) if image else None!r}")
    env_match = re.search(r"^    environment:\n((?:      .*\n)*)", block, re.MULTILINE)
    env_lines = env_match.group(1) if env_match else ""
    env = tuple(re.findall(r"^      ([A-Z_]+): (\S+)", env_lines, re.MULTILINE))
    if env != PROXY_ENV:
        drift.append(f"environment differs: {env!r}")
    if _list_under(block, "volumes") != [PROXY_SOCKET_MOUNT]:
        drift.append(f"volumes differ: {_list_under(block, 'volumes')!r}")
    restart = re.search(r"^    restart: (\S+)", block, re.MULTILINE)
    if restart is None or restart.group(1) != PROXY_RESTART:
        drift.append("restart policy differs")
    if re.search(r"^\s*ports:", block, re.MULTILINE):
        drift.append("ports key present (the proxy must have no host port)")
    if _list_under(block, "networks") != [expected_network]:
        drift.append(f"networks differ: {_list_under(block, 'networks')!r}")
    return drift


@pytest.mark.parametrize("doc", INSTALL_DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize(("heading", "network"), SECTIONS, ids=["3a", "3b"])
def test_docs_match_the_proxy_constants(doc: Path, heading: str, network: str) -> None:
    assert _service_drift(doc.read_text(encoding="utf-8"), heading, network) == []


def _mutations() -> list[tuple[str, str, str]]:
    digest = PROXY_IMAGE.rsplit(":", 1)[1]
    changed = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    return [
        ("exec_open", "EXEC: 0", "EXEC: 1"),
        ("digest", digest, changed),
        ("mount_rw", "docker.sock:ro", "docker.sock"),
        ("auth_deleted", "      AUTH: 0\n", ""),
        (
            "port_added",
            "    restart: unless-stopped\n",
            '    restart: unless-stopped\n    ports:\n      - "2375:2375"\n',
        ),
    ]


@pytest.mark.parametrize("doc", INSTALL_DOCS, ids=lambda p: p.name)
@pytest.mark.parametrize(("heading", "network"), SECTIONS, ids=["3a", "3b"])
@pytest.mark.parametrize(("name", "old", "new"), _mutations(), ids=[m[0] for m in _mutations()])
def test_drift_check_notices_changes(doc: Path, heading: str, network: str, name: str, old: str, new: str) -> None:
    """Positive control: a mutated docs block yields a non-empty drift list."""
    text = doc.read_text(encoding="utf-8")
    assert old in text, name
    mutated = text.replace(old, new)
    assert _service_drift(mutated, heading, network) != [], name


def test_drift_check_notices_wrong_network() -> None:
    text = INSTALL_DOCS[0].read_text(encoding="utf-8")
    assert _service_drift(text, "### 3a.", NETWORK_AIO) != []


# --- Command shape --------------------------------------------------------------------------


@pytest.mark.parametrize("network", [NETWORK_COMPOSE, NETWORK_AIO])
def test_docker_run_command_shape(network: str) -> None:
    command = docker_run_command(network)
    assert "\n" not in command
    args = shlex.split(command)
    assert args[:3] == ["docker", "run", "-d"]
    assert args[-1] == PROXY_IMAGE
    joined = " ".join(args)
    assert f"--name {PROXY_NAME}" in joined
    assert f"--network {network}" in joined
    assert f"--restart {PROXY_RESTART}" in joined
    assert f"-v {PROXY_SOCKET_MOUNT}" in joined
    env = [args[i + 1] for i, arg in enumerate(args) if arg == "-e"]
    assert env == [f"{key}={value}" for key, value in PROXY_ENV]
    for forbidden in ("-p", "--publish", "--privileged"):
        assert forbidden not in args
    # The SECRETS=0 flag closes the secrets endpoint; apart from it no secret may appear.
    lowered = command.replace("-e SECRETS=0", "").lower()
    for forbidden in ("hp_shared_key", "secret", "password"):
        assert forbidden not in lowered


def test_proxy_env_closes_everything_except_the_four_needed() -> None:
    env = dict(PROXY_ENV)
    assert {key for key, value in env.items() if value == "1"} == {"CONTAINERS", "IMAGES", "POST", "VOLUMES"}
    assert env["EXEC"] == "0"
    assert env["INFO"] == "0"


@pytest.mark.parametrize("network", ["bridge", "host", "gameworld; rm -rf /", "", "nextcloud-aio "])
def test_docker_run_command_rejects_other_networks(network: str) -> None:
    with pytest.raises(ValueError, match="unsupported network"):
        docker_run_command(network)


@pytest.mark.parametrize("failed", ["proxy_dns", "proxy_refused", "proxy_timeout"])
def test_proxy_commands_for_proxy_failures(failed: str) -> None:
    commands = proxy_commands([failed], DEFAULT_URL)
    assert [(c.id, c.network) for c in commands] == [("compose", NETWORK_COMPOSE), ("aio", NETWORK_AIO)]
    assert commands[0].command == docker_run_command(NETWORK_COMPOSE)


@pytest.mark.parametrize(
    ("failed", "url"),
    [
        ([], DEFAULT_URL),
        (["containers", "reachable"], DEFAULT_URL),
        (["proxy_dns"], "tcp://my-proxy:2375"),
        (["proxy_refused"], "tcp://gameworld-docker-proxy:2376"),
        (["proxy_timeout"], "unix:///var/run/docker.sock"),
    ],
)
def test_no_proxy_commands_otherwise(failed: list[str], url: str) -> None:
    assert proxy_commands(failed, url) == []


def test_module_documents_its_role() -> None:
    assert proxy_setup.__doc__ is not None
    assert "install.md" in proxy_setup.__doc__


# --- API ------------------------------------------------------------------------------------


def _result(*failed: str) -> SetupCheckResult:
    items = [CheckItem(id=item_id, ok=False, severity="error", message="x") for item_id in failed]
    items.append(CheckItem(id="images", ok=True, severity="error", message="y"))
    return SetupCheckResult(ok=not failed, items=items)


@pytest.mark.parametrize("failed", ["proxy_dns", "proxy_refused", "proxy_timeout"])
async def test_api_returns_commands(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, failed: str) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result(failed))
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["proxy_commands"] == [
        {"id": "compose", "network": NETWORK_COMPOSE, "command": docker_run_command(NETWORK_COMPOSE)},
        {"id": "aio", "network": NETWORK_AIO, "command": docker_run_command(NETWORK_AIO)},
    ]


@pytest.mark.parametrize(
    ("failed", "url"),
    [((), DEFAULT_URL), (("containers",), DEFAULT_URL), (("proxy_dns",), "tcp://other-proxy:2375")],
)
async def test_api_returns_no_commands(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, failed: tuple[str, ...], url: str
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", url)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result(*failed))
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["proxy_commands"] == []


async def test_api_config_error_has_no_commands(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "kaputt")
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["items"][0]["id"] == "config"
    assert body["proxy_commands"] == []
