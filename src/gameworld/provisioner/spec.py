"""Die gehärtete Container-Spec einer Welt.

Die Werte sind fest kodiert (WELT-05): Eltern stellen keine Limits ein, und kein
Wert aus einer Nutzereingabe gelangt hierher. Die Argumente sind die von der App
erzeugte Instanz-ID, die Welt-ID, der vergebene Host-Port und ein Preset aus der
festen Registry (Speicherlimit und Label kommen nur von dort).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from docker.types import Mount

from gameworld.provisioner.presets import Preset

LUANTI_VERSION = "5.17.0"
LUANTI_IMAGE = "ghcr.io/luanti-org/luanti@sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947"
DATA_DIR = "/var/lib/minetest"
INTERNAL_PORT = "30000/udp"


def resource_name(instance_id: str, world_id: str) -> str:
    """Name von Container und Volume, immer mit Instanz-Präfix."""
    return f"gameworld-{instance_id}-{world_id}"


@dataclass(frozen=True)
class WorldPayload:
    """Preset und Tar-Datei-Objekt für ``put_archive``.

    Steht hier statt in archive.py, weil client.py archive.py nicht importieren
    darf (archive.py importiert ProvisionerError aus client.py).
    """

    preset: Preset
    archive: BinaryIO


def world_spec(instance_id: str, world_id: str, host_port: int, preset: Preset) -> dict[str, object]:
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
            # Schema 2: Preset gesetzt und Welt-Mod gameworld_status vorhanden.
            # 02-04 wertet die Bereitschaft (Status-Datei) nur ab Schema 2 aus.
            "gameworld.schema": "2",
            "gameworld.preset": preset.id,
            "gameworld.engine": "luanti",
            "gameworld.engine_version": LUANTI_VERSION,
            "gameworld.port": str(host_port),
        },
        "mounts": [Mount(target=DATA_DIR, source=name, type="volume")],
        # tmpfs verhindert anonyme Volumes aus den VOLUME-Direktiven des Images.
        "tmpfs": {"/etc/minetest": "size=1m", "/tmp": "size=16m"},  # noqa: S108
        # Intern immer 30000, extern der vergebene Port; LAN-Spieler brauchen 0.0.0.0.
        "ports": {INTERNAL_PORT: ("0.0.0.0", host_port)},  # noqa: S104
        # Gleiches Limit für Speicher und Swap: kein Auslagern auf dem Heimserver.
        "mem_limit": preset.mem_limit,
        "memswap_limit": preset.mem_limit,
        "pids_limit": 128,
        "nano_cpus": 1_000_000_000,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,
        # Kein automatischer Neustart: verhindert OOM-Crash-Schleifen auf dem Heimserver.
        "restart_policy": {"Name": "no"},
        "log_config": {"Type": "json-file", "Config": {"max-size": "5m", "max-file": "2"}},
    }
