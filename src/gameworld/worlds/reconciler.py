"""Reconciliation of desired state (SQLite) and actual state (Docker labels), PLATT-02.

Rule table (RESEARCH pattern 4):

| Case                                              | Boot              | Periodic      |
|---------------------------------------------------|-------------------|---------------|
| desired running, container exited/created, no OOM | START             | NONE          |
| desired running, OOMKilled                        | MARK_OOM          | NONE          |
| desired running, container missing, volume there  | RECREATE          | NONE          |
| desired running, container missing, volume missing| MARK_DATA_MISSING | NONE          |
| desired stopped, container running (by hand)      | ADOPT_RUNNING     | ADOPT_RUNNING |
| op_state creating (process died while creating)   | MARK_INTERRUPTED  | NONE          |
| desired deleted (deletion was interrupted)        | RETRY_DELETE      | NONE          |
| op_state restoring_swap (swap was interrupted)    | MARK_RESTORE_INTERRUPTED | NONE   |
| op_state backing_up (backup was interrupted)      | CLEAR_BUSY, then normal | NONE    |
| op_state restoring (aborted before the swap)      | CLEAR_BUSY, then normal | NONE    |
| op_state failed                                   | NONE              | NONE          |
| own container without a row                       | report only       | report only   |
| container of a foreign instance                   | never listed      | never listed  |

Starting happens only at boot, i.e. once per process start after a host
reboot or ExApp update. Periodically nothing is started and nothing is
recreated: a reconciler that restarts crashed or OOM-killed worlds every
30 s would be a crash loop through the back door, exactly the one that the
restart_policy "no" on the worlds prevents. Restarting after a crash stays a
parent click. Failed worlds (op_state failed) are likewise not touched by
the reconciliation; they wait for start or delete.

Busy worlds (BUSY_OP_STATES) belong to the running backup or restore job;
the periodic reconciliation never touches them. An interrupted swap
(restoring_swap) is never started and never marked "world data missing",
but released for another restore (RESEARCH pitfall 2).
"""

from __future__ import annotations

import asyncio
import logging
from enum import StrEnum
from typing import TYPE_CHECKING

from gameworld.provisioner.client import ProvisionerError

if TYPE_CHECKING:
    from gameworld.provisioner.client import ContainerInfo
    from gameworld.worlds.service import WorldService
    from gameworld.worlds.store import WorldRow

LOG = logging.getLogger(__name__)

# Until Docker answers (the proxy may come up later after a reboot, pitfall 5).
BOOT_RETRY_SECONDS = 5.0
# Never exactly 10 s: the HAProxy in the Docker proxy closes keep-alive after 10 s (pitfall 4).
INTERVAL_SECONDS = 30.0

# Single source of the busy states; all other modules import them from here.
BUSY_OP_STATES = frozenset({"backing_up", "restoring", "restoring_swap"})


class ReconcileAction(StrEnum):
    NONE = "none"
    START = "start"
    RECREATE = "recreate"
    MARK_OOM = "mark_oom"
    ADOPT_RUNNING = "adopt_running"
    MARK_INTERRUPTED = "mark_interrupted"
    RETRY_DELETE = "retry_delete"
    MARK_DATA_MISSING = "mark_data_missing"
    CLEAR_BUSY = "clear_busy"
    MARK_RESTORE_INTERRUPTED = "mark_restore_interrupted"


def needs_volume_check(row: WorldRow, container: ContainerInfo | None) -> bool:
    """Only here the volume decides between RECREATE and MARK_DATA_MISSING."""
    return (
        container is None
        and row.desired_state == "running"
        and row.op_state not in {"creating", "failed"}
        and row.op_state not in BUSY_OP_STATES
    )


def decide_boot(row: WorldRow, container: ContainerInfo | None, volume_exists: bool) -> ReconcileAction:
    if row.desired_state == "deleted":
        return ReconcileAction.RETRY_DELETE
    if row.op_state == "restoring_swap":
        return ReconcileAction.MARK_RESTORE_INTERRUPTED
    if row.op_state in BUSY_OP_STATES:
        return ReconcileAction.CLEAR_BUSY
    if row.op_state == "creating":
        return ReconcileAction.MARK_INTERRUPTED
    if row.op_state == "failed":
        return ReconcileAction.NONE
    if container is None:
        if row.desired_state != "running":
            return ReconcileAction.NONE
        return ReconcileAction.RECREATE if volume_exists else ReconcileAction.MARK_DATA_MISSING
    if container.status == "running":
        return ReconcileAction.ADOPT_RUNNING if row.desired_state == "stopped" else ReconcileAction.NONE
    if row.desired_state != "running" or container.status not in {"exited", "created"}:
        return ReconcileAction.NONE
    if container.oom_killed:
        return ReconcileAction.MARK_OOM
    return ReconcileAction.START


def decide_periodic(row: WorldRow, container: ContainerInfo | None) -> ReconcileAction:
    """Maintain state only: Docker wins for worlds started by hand, nothing else."""
    if (
        row.desired_state == "stopped"
        and row.op_state not in {"creating", "failed"}
        and row.op_state not in BUSY_OP_STATES
        and container is not None
        and container.status == "running"
    ):
        return ReconcileAction.ADOPT_RUNNING
    return ReconcileAction.NONE


async def reconcile_forever(
    service: WorldService,
    *,
    boot_retry_seconds: float = BOOT_RETRY_SECONDS,
    interval_seconds: float = INTERVAL_SECONDS,
) -> None:
    """Boot reconciliation until it fully succeeded, then periodic upkeep.

    Runs as a task in the lifespan; every error is logged and the cycle
    repeated. Only CancelledError (shutdown) ends the loop.
    """
    booted = False
    while True:
        try:
            if booted:
                await service.periodic_reconcile()
            else:
                booted = await service.boot_reconcile()
                if booted:
                    LOG.info("Boot reconciliation of the worlds completed")
        except ProvisionerError as exc:
            LOG.warning("Reconciliation of the worlds skipped: %s", exc)
        except Exception:
            LOG.exception("Reconciliation of the worlds failed")
        await asyncio.sleep(interval_seconds if booted else boot_retry_seconds)
