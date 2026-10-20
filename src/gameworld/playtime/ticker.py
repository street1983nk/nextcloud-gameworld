"""Der 15-s-Zeittakt als Lifespan-Task (O-03, Pattern 5).

Analog zu ``worlds.reconciler.reconcile_forever``: Der Takt verbucht das
Zählbuch aller laufenden Welten und hält ihre Regeldateien aktuell
(``WorldService.tick_time``). Jeder Fehler wird geloggt und der Zyklus
wiederholt; nur CancelledError (Herunterfahren) beendet die Schleife.

Das Intervall ist nie exakt 10 s: Der HAProxy im Docker-Proxy schließt
Keep-Alive-Verbindungen nach 10 s (Phase-2-Pitfall 4).
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
    """Verbucht und schreibt im Abstand interval_seconds; läuft bis CancelledError."""
    while True:
        try:
            # abandon_on_cancel: Beim Herunterfahren nicht auf einen hängenden
            # Docker-Aufruf warten; tick_time gibt _LOCK im finally trotzdem frei.
            await anyio.to_thread.run_sync(service.tick_time, abandon_on_cancel=True)
        except ProvisionerError as exc:
            LOG.warning("Zeittakt übersprungen: %s", exc)
        except Exception:
            LOG.exception("Zeittakt fehlgeschlagen")
        await asyncio.sleep(interval_seconds)
