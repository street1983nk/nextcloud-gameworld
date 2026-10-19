"""Vergabe der UDP-Host-Ports."""

from __future__ import annotations

from gameworld.provisioner.client import ProvisionerError


class NoFreePortError(ProvisionerError):
    """Alle Ports im konfigurierten Bereich sind vergeben."""


def allocate_port(port_range: tuple[int, int], used: set[int]) -> int:
    """Kleinster freier Port im Bereich, sonst NoFreePortError."""
    low, high = port_range
    for port in range(low, high + 1):
        if port not in used:
            return port
    raise NoFreePortError(f"Alle UDP-Ports im Bereich {low}-{high} sind belegt.")
