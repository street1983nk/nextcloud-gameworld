"""Allocation of the UDP host ports."""

from __future__ import annotations

from gameworld.provisioner.client import ProvisionerError

# Template (D-25): the range values are inserted, never translated.
TEXT_PORTS_TAKEN = "Alle UDP-Ports im Bereich {low}-{high} sind belegt."


class NoFreePortError(ProvisionerError):
    """All ports in the configured range are taken."""


def allocate_port(port_range: tuple[int, int], used: set[int]) -> int:
    """Lowest free port in the range, otherwise NoFreePortError."""
    low, high = port_range
    for port in range(low, high + 1):
        if port not in used:
            return port
    raise NoFreePortError(TEXT_PORTS_TAKEN.format(low=low, high=high))
