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
    LAN_PLACEHOLDER,
    NETWORK_AIO,
    NETWORK_COMPOSE,
    NETWORK_PLACEHOLDER,
    PROXY_ENV,
    PROXY_IMAGE,
    PROXY_NAME,
    PROXY_RESTART,
    PROXY_SOCKET_MOUNT,
    commands_wanted,
    compose_file,
    docker_run_command,
    firewall_commands,
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


@pytest.mark.parametrize("network", ["gameworld-dev_default", "my.net", "net2", "Nextcloud_AIO", NETWORK_PLACEHOLDER])
def test_docker_run_command_accepts_valid_networks(network: str) -> None:
    command = docker_run_command(network)
    assert f"--network {network} " in command


REJECTED_NETWORKS = [
    "gameworld; rm -rf /",
    "$(id)",
    "`id`",
    "a b",
    "",
    "-x",
    "--privileged",
    "nextcloud-aio ",
    "net\nwork",
    "a" * 129,
    "<other>",
    # Reserved Docker networks: host would put the proxy on a host port, the others
    # have no embedded DNS, so Gameworld could not find the proxy by name.
    "host",
    "bridge",
    "none",
]


@pytest.mark.parametrize("network", REJECTED_NETWORKS)
def test_docker_run_command_rejects_other_networks(network: str) -> None:
    with pytest.raises(ValueError, match="unsupported network"):
        docker_run_command(network)


@pytest.mark.parametrize("network", REJECTED_NETWORKS)
def test_compose_file_rejects_other_networks(network: str) -> None:
    with pytest.raises(ValueError, match="unsupported network"):
        compose_file(network)


@pytest.mark.parametrize("failed", ["proxy_dns", "proxy_refused", "proxy_timeout"])
def test_proxy_commands_fallback_without_detected_network(failed: str) -> None:
    commands = proxy_commands([failed], DEFAULT_URL)
    assert [(c.id, c.network) for c in commands] == [
        ("compose", NETWORK_COMPOSE),
        ("aio", NETWORK_AIO),
        ("other", NETWORK_PLACEHOLDER),
    ]
    for command in commands:
        assert command.command == docker_run_command(command.network)
        assert command.compose == compose_file(command.network)


@pytest.mark.parametrize("network", ["nextcloud-aio", "gameworld", "gameworld-dev_default"])
def test_proxy_commands_for_detected_network(network: str) -> None:
    commands = proxy_commands(["proxy_dns"], DEFAULT_URL, network)
    assert len(commands) == 1
    assert (commands[0].id, commands[0].network) == ("detected", network)
    assert commands[0].command == docker_run_command(network)
    assert commands[0].compose == compose_file(network)


@pytest.mark.parametrize("detected", ["$(id)", "host", "", "-evil", NETWORK_PLACEHOLDER])
def test_invalid_detected_network_falls_back(detected: str) -> None:
    commands = proxy_commands(["proxy_dns"], DEFAULT_URL, detected)
    assert [c.id for c in commands] == ["compose", "aio", "other"]


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
    assert proxy_commands(failed, url, "nextcloud-aio") == []
    assert commands_wanted(failed, url) is False


@pytest.mark.parametrize("failed", ["proxy_dns", "proxy_refused", "proxy_timeout"])
def test_commands_wanted(failed: str) -> None:
    assert commands_wanted([failed, "images"], DEFAULT_URL) is True
    assert commands_wanted([failed], "http://gameworld-docker-proxy") is True


# --- Compose file ---------------------------------------------------------------------------


@pytest.mark.parametrize("network", [NETWORK_COMPOSE, NETWORK_AIO, "gameworld-dev_default", NETWORK_PLACEHOLDER])
def test_compose_file_has_no_drift(network: str) -> None:
    text = compose_file(network)
    wrapped = f"### 3x.\n```yaml\n{text}```\n"
    assert _service_drift(wrapped, "### 3x.", network) == []
    assert text.endswith(f"networks:\n  {network}:\n    external: true\n")
    assert "ports" not in text
    assert "#" not in text
    assert "\t" not in text


def test_compose_file_exact_shape() -> None:
    env = "".join(f"      {key}: {value}\n" for key, value in PROXY_ENV)
    assert compose_file(NETWORK_AIO) == (
        "services:\n"
        f"  {PROXY_NAME}:\n"
        f"    image: {PROXY_IMAGE}\n"
        f"    restart: {PROXY_RESTART}\n"
        "    environment:\n"
        f"{env}"
        "    volumes:\n"
        f"      - {PROXY_SOCKET_MOUNT}\n"
        "    networks:\n"
        "      - nextcloud-aio\n"
        "networks:\n"
        "  nextcloud-aio:\n"
        "    external: true\n"
    )


@pytest.mark.parametrize("network", ["1234", "true", "Yes", "null", "0x1f", "1e3", "on", "y", "N"])
def test_compose_file_quotes_yaml_ambiguous_networks(network: str) -> None:
    text = compose_file(network)
    assert f'      - "{network}"\n' in text
    assert f'  "{network}":\n    external: true\n' in text


def test_compose_drift_helper_notices_mutation() -> None:
    """Positive control for the compose drift test."""
    text = compose_file(NETWORK_AIO).replace("EXEC: 0", "EXEC: 1")
    assert _service_drift(f"### 3x.\n```yaml\n{text}```\n", "### 3x.", NETWORK_AIO) != []


# --- Firewall commands ----------------------------------------------------------------------


FIREWALLD_RANGE = (
    'sudo firewall-cmd --permanent --add-rich-rule=\'rule family="ipv4" source address="<lan-network>"'
    ' port port="30000-30019" protocol="udp" accept\' && sudo firewall-cmd --reload'
)


def test_firewall_commands_for_a_range() -> None:
    commands = firewall_commands((30000, 30019))
    assert [(c.id, c.command) for c in commands] == [
        ("ufw", "sudo ufw allow proto udp from <lan-network> to any port 30000:30019"),
        ("firewalld", FIREWALLD_RANGE),
    ]
    assert LAN_PLACEHOLDER == "<lan-network>"


def test_firewall_commands_for_a_single_port() -> None:
    commands = firewall_commands((30000, 30000))
    assert commands[0].command == "sudo ufw allow proto udp from <lan-network> to any port 30000"
    assert 'port port="30000" protocol="udp"' in commands[1].command
    assert "30000-30000" not in commands[1].command


@pytest.mark.parametrize("port_range", [(0, 10), (10, 5), (1, 65536), (-1, 3)])
def test_firewall_commands_reject_invalid_ranges(port_range: tuple[int, int]) -> None:
    assert firewall_commands(port_range) == []


def test_firewall_commands_are_lan_only() -> None:
    for command in firewall_commands((30000, 30019)):
        assert command.command.count(LAN_PLACEHOLDER) == 1
        assert "tcp" not in command.command
        assert "0.0.0.0" not in command.command  # noqa: S104 - asserts the address is absent


def test_module_documents_its_role() -> None:
    assert proxy_setup.__doc__ is not None
    assert "install.md" in proxy_setup.__doc__


# --- API ------------------------------------------------------------------------------------


def _result(*failed: str) -> SetupCheckResult:
    items = [CheckItem(id=item_id, ok=False, severity="error", message="x") for item_id in failed]
    items.append(CheckItem(id="images", ok=True, severity="error", message="y"))
    return SetupCheckResult(ok=not failed, items=items)


@pytest.fixture
def detect_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on the network probe: records every call and answers "not detected"."""
    calls: list[str] = []

    def fake_detect() -> None:
        calls.append("called")

    monkeypatch.setattr(setup_check_api, "detect_docker_network", fake_detect)
    return calls


def _command_json(command_id: str, network: str) -> dict[str, str]:
    return {
        "id": command_id,
        "network": network,
        "command": docker_run_command(network),
        "compose": compose_file(network),
    }


FIREWALL_JSON = {
    "port_range": "30000-30019",
    "commands": [{"id": c.id, "command": c.command} for c in firewall_commands((30000, 30019))],
}


@pytest.mark.parametrize("failed", ["proxy_dns", "proxy_refused", "proxy_timeout"])
async def test_api_returns_fallback_commands(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, detect_calls: list[str], failed: str
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.delenv("GAMEWORLD_PORT_RANGE", raising=False)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result(failed))
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["proxy_commands"] == [
        _command_json("compose", NETWORK_COMPOSE),
        _command_json("aio", NETWORK_AIO),
        _command_json("other", NETWORK_PLACEHOLDER),
    ]
    assert body["firewall"] == FIREWALL_JSON
    assert detect_calls == ["called"]


async def test_api_returns_detected_command(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_detect() -> str:
        calls.append(1)
        return "nextcloud-aio"

    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.setattr(setup_check_api, "detect_docker_network", fake_detect)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result("proxy_dns"))
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["proxy_commands"] == [_command_json("detected", "nextcloud-aio")]
    assert calls == [1]


@pytest.mark.parametrize(
    ("failed", "url"),
    [((), DEFAULT_URL), (("containers",), DEFAULT_URL), (("proxy_dns",), "tcp://other-proxy:2375")],
)
async def test_api_returns_no_commands(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    detect_calls: list[str],
    failed: tuple[str, ...],
    url: str,
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", url)
    monkeypatch.delenv("GAMEWORLD_PORT_RANGE", raising=False)
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result(*failed))
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["proxy_commands"] == []
    # The firewall cannot be checked from inside, so its commands come also when ok.
    assert body["firewall"] == FIREWALL_JSON
    assert detect_calls == []


async def test_api_firewall_follows_port_range(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, detect_calls: list[str]
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "31000-31004")
    monkeypatch.setattr(setup_check_api, "run_setup_check", lambda docker_url: _result())
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["firewall"]["port_range"] == "31000-31004"
    assert body["firewall"]["commands"][0]["command"].endswith("port 31000:31004")
    assert detect_calls == []


async def test_api_config_error_has_no_commands(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, detect_calls: list[str]
) -> None:
    monkeypatch.setenv("GAMEWORLD_DOCKER_URL", DEFAULT_URL)
    monkeypatch.setenv("GAMEWORLD_PORT_RANGE", "kaputt")
    body = (await client.get("/api/setup-check", headers=appapi_headers())).json()
    assert body["items"][0]["id"] == "config"
    assert body["proxy_commands"] == []
    assert body["firewall"] is None
    assert detect_calls == []
