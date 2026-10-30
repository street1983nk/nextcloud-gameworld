"""Single source of truth for the scoped Docker proxy Gameworld talks to.

The proxy configuration shown in docs/install.md and docs/install.de.md (sections 3a
and 3b, Compose snippets) and the ready-to-copy ``docker run`` commands the setup check
offers when the proxy is missing are built from the constants below.
tests/test_proxy_setup.py fails as soon as the docs drift from them.

The commands are built only from module constants; the network is restricted to the
two documented values, nothing from a request or the configuration is interpolated.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

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
_ALLOWED_NETWORKS = frozenset({NETWORK_COMPOSE, NETWORK_AIO})
# Setup-check findings a freshly created proxy container fixes.
COMMAND_TRIGGER_IDS = frozenset({"proxy_dns", "proxy_refused", "proxy_timeout"})


@dataclass(frozen=True)
class ProxyCommand:
    id: Literal["compose", "aio"]
    network: str
    command: str


def docker_run_command(network: str) -> str:
    """One-line ``docker run`` for the proxy in ``network``.

    One line on purpose: it pastes identically into bash, sh and PowerShell. No host
    port, read-only socket, no secrets.
    """
    if network not in _ALLOWED_NETWORKS:
        raise ValueError(f"unsupported network: {network!r}")
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


def _is_default_address(docker_url: str) -> bool:
    """True only for tcp/http on PROXY_NAME:PROXY_PORT, the address the commands create."""
    try:
        parts = urlsplit(docker_url.strip())
        port = parts.port or PROXY_PORT
    except ValueError:
        return False
    return parts.scheme in {"tcp", "http"} and parts.hostname == PROXY_NAME and port == PROXY_PORT


def proxy_commands(failed_ids: Iterable[str], docker_url: str) -> list[ProxyCommand]:
    """Both commands (own Compose first, then AIO) when they would fix the findings, else none."""
    if COMMAND_TRIGGER_IDS.isdisjoint(failed_ids) or not _is_default_address(docker_url):
        return []
    return [
        ProxyCommand(id="compose", network=NETWORK_COMPOSE, command=docker_run_command(NETWORK_COMPOSE)),
        ProxyCommand(id="aio", network=NETWORK_AIO, command=docker_run_command(NETWORK_AIO)),
    ]
