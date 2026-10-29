"""Port allocation: smallest free port in the range."""

from __future__ import annotations

import pytest

from gameworld.worlds.ports import NoFreePortError, allocate_port


def test_first_port_when_nothing_is_used() -> None:
    assert allocate_port((30000, 30002), set()) == 30000


def test_skips_used_port() -> None:
    assert allocate_port((30000, 30002), {30000}) == 30001


def test_full_range_raises() -> None:
    with pytest.raises(NoFreePortError):
        allocate_port((30000, 30002), {30000, 30001, 30002})


def test_ports_outside_range_are_ignored() -> None:
    assert allocate_port((30000, 30002), {29999, 30003, 8090}) == 30000
