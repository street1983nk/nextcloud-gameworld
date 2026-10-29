"""Shared e2e fixtures.

The ``relay`` fixture (real uvicorn server of the ExApp in dev mode) is defined in
test_play_proxy_e2e.py; here it is made available to all e2e tests
without copying it (04.2-09). A test module overrides it locally if needed.
"""

from __future__ import annotations

from tests.e2e.test_play_proxy_e2e import relay

__all__ = ["relay"]
