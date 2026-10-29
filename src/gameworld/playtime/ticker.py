"""The 15 s time tick as a lifespan task (O-03, pattern 5).

Analogous to ``worlds.reconciler.reconcile_forever``: the tick books the
counter ledger of all running worlds and keeps their rule files current
(``WorldService.tick_time``). Every error is logged and the cycle repeated;
only CancelledError (shutdown) ends the loop.

The interval is never exactly 10 s: the HAProxy in the Docker proxy closes
keep-alive connections after 10 s (phase 2 pitfall 4).
"""

from __future__ import annotations

import asyncio
import logging

import anyio.to_thread

from gameworld.provisioner.client import ProvisionerError
from gameworld.worlds.service import WorldService

LOG = logging.getLogger(__name__)

TICK_SECONDS = 15.0


async def time_forever(service: WorldService, *, interval_seconds: float = TICK_SECONDS) -> None:
    """Book and write every interval_seconds; runs until CancelledError."""
    while True:
        try:
            # abandon_on_cancel: on shutdown, do not wait for a hanging
            # Docker call; tick_time releases _LOCK in its finally anyway.
            await anyio.to_thread.run_sync(service.tick_time, abandon_on_cancel=True)
        except ProvisionerError as exc:
            LOG.warning("Time tick skipped: %s", exc)
        except Exception:
            LOG.exception("Time tick failed")
        await asyncio.sleep(interval_seconds)
