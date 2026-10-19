"""Die gehärtete Container-Spec einer Welt.

Die Werte sind fest kodiert (WELT-05): Eltern stellen keine Limits ein, und kein
Wert aus einer Nutzereingabe gelangt hierher. Die einzigen Argumente sind die
von der App erzeugte Instanz-ID, die Welt-ID und der vergebene Host-Port.
"""

from __future__ import annotations

from docker.types import Mount

LUANTI_VERSION = "5.17.0"
LUANTI_IMAGE = "ghcr.io/luanti-org/luanti@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"
DATA_DIR = "/var/lib/minetest"
INTERNAL_PORT = "30000/udp"


def resource_name(instance_id: str, world_id: str) -> str:
    """Name von Container und Volume, immer mit Instanz-Präfix."""
    return f"gameworld-{instance_id}-{world_id}"


def world_spec(instance_id: str, world_id: str, host_port: int) -> dict[str, object]:
    """Keyword-Argumente für ``containers.create``."""
    name = resource_name(instance_id, world_id)
    return {
        "image": LUANTI_IMAGE,
        "name": name,
        "command": ["--config", f"{DATA_DIR}/minetest.conf", "--world", f"{DATA_DIR}/.minetest/worlds/world"],
        "user": "30000:30000",
        "labels": {
            "gameworld.managed": "true",
            "gameworld.instance": instance_id,
            "gameworld.world_id": world_id,
            "gameworld.schema": "1",
            "gameworld.engine": "luanti",
            "gameworld.engine_version": LUANTI_VERSION,
            "gameworld.port": str(host_port),
        },
        "mounts": [Mount(target=DATA_DIR, source=name, type="volume")],
        # tmpfs verhindert anonyme Volumes aus den VOLUME-Direktiven des Images.
        "tmpfs": {"/etc/minetest": "size=1m", "/tmp": "size=16m"},  # noqa: S108
        # Intern immer 30000, extern der vergebene Port; LAN-Spieler brauchen 0.0.0.0.
        "ports": {INTERNAL_PORT: ("0.0.0.0", host_port)},  # noqa: S104
        "mem_limit": "512m",
        "memswap_limit": "512m",
        "pids_limit": 128,
        "nano_cpus": 1_000_000_000,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,
        # Kein automatischer Neustart: verhindert OOM-Crash-Schleifen auf dem Heimserver.
        "restart_policy": {"Name": "no"},
        "log_config": {"Type": "json-file", "Config": {"max-size": "5m", "max-file": "2"}},
    }
