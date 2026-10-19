"""Abgleich von Soll-Zustand (SQLite) und Ist-Zustand (Docker-Labels), PLATT-02.

Regeltabelle (RESEARCH Pattern 4):

| Fall                                              | Boot              | Periodisch    |
|---------------------------------------------------|-------------------|---------------|
| desired running, Container exited/created, ohne OOM | START           | NONE          |
| desired running, OOMKilled                        | MARK_OOM          | NONE          |
| desired running, Container fehlt, Volume da       | RECREATE          | NONE          |
| desired running, Container fehlt, Volume fehlt    | MARK_DATA_MISSING | NONE          |
| desired stopped, Container läuft (von Hand)       | ADOPT_RUNNING     | ADOPT_RUNNING |
| op_state creating (Prozess starb beim Erzeugen)   | MARK_INTERRUPTED  | NONE          |
| desired deleted (Löschen brach ab)                | RETRY_DELETE      | NONE          |
| op_state failed                                   | NONE              | NONE          |
| eigener Container ohne Zeile                      | nur melden        | nur melden    |
| Container fremder Instanz                         | nie gelistet      | nie gelistet  |

Gestartet wird nur beim Boot, also einmal pro Prozessstart nach einem
Host-Reboot oder ExApp-Update. Periodisch wird nie gestartet und nie neu
erzeugt: Ein Reconciler, der abgestürzte oder per OOM beendete Welten alle
30 s wieder hochfährt, wäre eine Crash-Schleife durch die Hintertür, genau
die, die restart_policy "no" an den Welten verhindert. Neustart nach einem
Absturz bleibt ein Elternklick. Fehlgeschlagene Welten (op_state failed)
fasst der Abgleich ebenfalls nicht an; sie warten auf Starten oder Löschen.
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

# Bis Docker antwortet (Proxy nach einem Reboot evtl. später oben, Pitfall 5).
BOOT_RETRY_SECONDS = 5.0
# Nie exakt 10 s: Der HAProxy im Docker-Proxy schließt Keep-Alive nach 10 s (Pitfall 4).
INTERVAL_SECONDS = 30.0


class ReconcileAction(StrEnum):
    NONE = "none"
    START = "start"
    RECREATE = "recreate"
    MARK_OOM = "mark_oom"
    ADOPT_RUNNING = "adopt_running"
    MARK_INTERRUPTED = "mark_interrupted"
    RETRY_DELETE = "retry_delete"
    MARK_DATA_MISSING = "mark_data_missing"


def needs_volume_check(row: WorldRow, container: ContainerInfo | None) -> bool:
    """Nur hier entscheidet das Volume zwischen RECREATE und MARK_DATA_MISSING."""
    return container is None and row.desired_state == "running" and row.op_state not in {"creating", "failed"}


def decide_boot(row: WorldRow, container: ContainerInfo | None, volume_exists: bool) -> ReconcileAction:
    if row.desired_state == "deleted":
        return ReconcileAction.RETRY_DELETE
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
    """Nur Zustand pflegen: Docker gewinnt bei von Hand gestarteten Welten, sonst nichts."""
    if (
        row.desired_state == "stopped"
        and row.op_state not in {"creating", "failed"}
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
    """Boot-Abgleich, bis er vollständig gelang, danach periodische Pflege.

    Läuft als Task im Lifespan; jeder Fehler wird geloggt und der Zyklus
    wiederholt. Nur CancelledError (Herunterfahren) beendet die Schleife.
    """
    booted = False
    while True:
        try:
            if booted:
                await service.periodic_reconcile()
            else:
                booted = await service.boot_reconcile()
                if booted:
                    LOG.info("Boot-Abgleich der Welten abgeschlossen")
        except ProvisionerError as exc:
            LOG.warning("Abgleich der Welten übersprungen: %s", exc)
        except Exception:
            LOG.exception("Abgleich der Welten fehlgeschlagen")
        await asyncio.sleep(interval_seconds if booted else boot_retry_seconds)
