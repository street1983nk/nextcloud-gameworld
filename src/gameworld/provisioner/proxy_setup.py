"""Single source of truth for the scoped Docker proxy Gameworld talks to.

The proxy configuration shown in docs/install.md and docs/install.de.md (sections 3a
and 3b, Compose snippets), the ready-to-copy ``docker run`` commands and Compose files
the setup check offers when the proxy is missing, and the LAN-only firewall commands
are built from the constants below. tests/test_proxy_setup.py fails as soon as the docs
or the Compose file drift from them.

The commands are built only from module constants plus one network name. That name is
either one of the two documented networks, the network ``network_probe`` detected
(strictly validated against ``NETWORK_RE``), or the placeholder ``<docker-network>``.
Nothing from a request or the configuration is interpolated as text; the firewall port
range comes from the validated integer settings. Gameworld only shows the commands, it
never runs them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from gameworld.provisioner.network_probe import NETWORK_RE

PROXY_NAME = "gameworld-docker-proxy"
PROXY_PORT = 2375
PROXY_IMAGE = (
    "tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459"
)
# Only what Gameworld needs is open; everything else is closed explicitly, so a changed
# image default opens nothing. Order as in the docs.
PROXY_ENV: tuple[tuple[str, str], ...] = (
    ("CONTAINERS", "1"),
    ("IMAGES", "1"),
    ("POST", "1"),
    ("VOLUMES", "1"),
    ("EXEC", "0"),
    ("INFO", "0"),
    ("NETWORKS", "0"),
    ("BUILD", "0"),
    ("SYSTEM", "0"),
    ("SECRETS", "0"),
    ("SWARM", "0"),
    ("NODES", "0"),
    ("SERVICES", "0"),
    ("TASKS", "0"),
    ("PLUGINS", "0"),
    ("CONFIGS", "0"),
    ("DISTRIBUTION", "0"),
    ("AUTH", "0"),
)
PROXY_SOCKET_MOUNT = "/var/run/docker.sock:/var/run/docker.sock:ro"
PROXY_RESTART = "unless-stopped"
NETWORK_COMPOSE = "gameworld"
NETWORK_AIO = "nextcloud-aio"
# Placeholders fail safe when pasted unchanged: "<" makes bash and PowerShell refuse
# the line, docker compose rejects the network name and firewall-cmd the address. So a
# placeholder never runs with a guessed value.
NETWORK_PLACEHOLDER = "<docker-network>"
LAN_PLACEHOLDER = "<lan-network>"
# Docker's built-in networks: "host" would put the proxy on a host port, "bridge" and
# "none" have no embedded DNS, so Gameworld could not find the proxy there by name.
_RESERVED_NETWORKS = frozenset({"host", "bridge", "none"})
# Plain YAML scalars that YAML 1.1 reads as bool or null; such network names get quoted.
_YAML_WORDS = frozenset({"y", "n", "yes", "no", "true", "false", "on", "off", "null"})
_PLAIN_YAML = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
# Setup-check findings a freshly created proxy container fixes.
COMMAND_TRIGGER_IDS = frozenset({"proxy_dns", "proxy_refused", "proxy_timeout"})

CommandId = Literal["detected", "compose", "aio", "other"]


@dataclass(frozen=True)
class ProxyCommand:
    id: CommandId
    network: str
    command: str
    compose: str


@dataclass(frozen=True)
class FirewallCommand:
    id: Literal["ufw", "firewalld"]
    command: str


def _valid_network(network: str) -> bool:
    if network in {NETWORK_COMPOSE, NETWORK_AIO, NETWORK_PLACEHOLDER}:
        return True
    return network not in _RESERVED_NETWORKS and re.fullmatch(NETWORK_RE, network) is not None


def _require_network(network: str) -> None:
    if not _valid_network(network):
        raise ValueError(f"unsupported network: {network!r}")


def docker_run_command(network: str) -> str:
    """One-line ``docker run`` for the proxy in ``network``.

    One line on purpose: it pastes identically into bash, sh and PowerShell. No host
    port, read-only socket, no secrets.
    """
    _require_network(network)
    parts = [
        "docker run -d",
        f"--name {PROXY_NAME}",
        f"--restart {PROXY_RESTART}",
        f"--network {network}",
        f"-v {PROXY_SOCKET_MOUNT}",
        *(f"-e {key}={value}" for key, value in PROXY_ENV),
        PROXY_IMAGE,
    ]
    return " ".join(parts)


def _yaml_network(network: str) -> str:
    if network == NETWORK_PLACEHOLDER:
        return network
    if _PLAIN_YAML.fullmatch(network) and network.lower() not in _YAML_WORDS:
        return network
    # Only validated [A-Za-z0-9_.-] names get here, so double quotes need no escaping.
    return f'"{network}"'


def compose_file(network: str) -> str:
    """Compose file with the same proxy settings as ``docker_run_command``.

    Deterministic text without comments, so it needs no translation; no ports key, the
    network is external (it belongs to the deploy daemon).
    """
    _require_network(network)
    name = _yaml_network(network)
    lines = [
        "services:",
        f"  {PROXY_NAME}:",
        f"    image: {PROXY_IMAGE}",
        f"    restart: {PROXY_RESTART}",
        "    environment:",
        *(f"      {key}: {value}" for key, value in PROXY_ENV),
        "    volumes:",
        f"      - {PROXY_SOCKET_MOUNT}",
        "    networks:",
        f"      - {name}",
        "networks:",
        f"  {name}:",
        "    external: true",
    ]
    return "\n".join(lines) + "\n"


def _is_default_address(docker_url: str) -> bool:
    """True only for tcp/http on PROXY_NAME:PROXY_PORT, the address the commands create."""
    try:
        parts = urlsplit(docker_url.strip())
        port = parts.port or PROXY_PORT
    except ValueError:
        return False
    return parts.scheme in {"tcp", "http"} and parts.hostname == PROXY_NAME and port == PROXY_PORT


def commands_wanted(failed_ids: Iterable[str], docker_url: str) -> bool:
    """True when a freshly created proxy at the default address would fix the findings."""
    return not COMMAND_TRIGGER_IDS.isdisjoint(failed_ids) and _is_default_address(docker_url)


def _command(command_id: CommandId, network: str) -> ProxyCommand:
    return ProxyCommand(
        id=command_id, network=network, command=docker_run_command(network), compose=compose_file(network)
    )


def proxy_commands(
    failed_ids: Iterable[str], docker_url: str, detected_network: str | None = None
) -> list[ProxyCommand]:
    """Proxy commands when they would fix the findings, else none.

    With a detected network exactly one command for it; otherwise own Compose, AIO and
    one with the placeholder ``<docker-network>``.
    """
    if not commands_wanted(failed_ids, docker_url):
        return []
    if detected_network and detected_network != NETWORK_PLACEHOLDER and _valid_network(detected_network):
        return [_command("detected", detected_network)]
    return [
        _command("compose", NETWORK_COMPOSE),
        _command("aio", NETWORK_AIO),
        _command("other", NETWORK_PLACEHOLDER),
    ]


def firewall_commands(port_range: tuple[int, int]) -> list[FirewallCommand]:
    """ufw and firewalld commands opening the UDP range for the LAN placeholder only."""
    low, high = port_range
    if not 1 <= low <= high <= 65535:
        return []
    ufw_ports = str(low) if low == high else f"{low}:{high}"
    firewalld_ports = str(low) if low == high else f"{low}-{high}"
    rich_rule = (
        f'rule family="ipv4" source address="{LAN_PLACEHOLDER}" port port="{firewalld_ports}" protocol="udp" accept'
    )
    return [
        FirewallCommand(id="ufw", command=f"sudo ufw allow proto udp from {LAN_PLACEHOLDER} to any port {ufw_ports}"),
        FirewallCommand(
            id="firewalld",
            command=f"sudo firewall-cmd --permanent --add-rich-rule='{rich_rule}' && sudo firewall-cmd --reload",
        ),
    ]
