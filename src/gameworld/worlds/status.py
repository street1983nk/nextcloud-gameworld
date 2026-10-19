"""Statusmodell einer Welt, abgeleitet aus Docker (RESEARCH Pattern 3).

Rein und ohne Docker testbar. Die Datenbank liefert nur die
Operationszustände ``creating`` und ``failed`` sowie den Elternwunsch
``desired_state``; alles andere kommt aus ``docker inspect`` (State,
ExitCode, OOMKilled, StartedAt) und der mtime der Status-Datei des
Welt-Mods. Die Elterntexte stehen hier als feste Konstanten.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gameworld.provisioner.client import ContainerInfo

RUNNING = "running"
STARTING = "starting"
STOPPED = "stopped"
ERROR = "error"
UNKNOWN = "unknown"

TEXT_UNREACHABLE = "Docker nicht erreichbar"
TEXT_CREATING = "Wird erstellt"
TEXT_UNKNOWN_ERROR = "Unbekannter Fehler"
# Neutral: Ob das Volume noch da ist, prüft erst der Start (CR-01); fehlt es,
# wird die Welt zu "Weltdaten fehlen, nur Löschen".
TEXT_MISSING = "Der Server der Welt fehlt. Starten stellt ihn wieder her, falls die Weltdaten noch da sind."
TEXT_RESTARTING = "Startet immer wieder neu"
TEXT_RUNNING = "Läuft"
TEXT_STARTING = "Startet gerade"
TEXT_STOPPED = "Gestoppt"
TEXT_OOM = "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet."
TEXT_CRASHED = "Die Welt wurde unerwartet beendet (Code {code})."
TEXT_ODD_STATE = "Unerwarteter Zustand des Servers ({state})."

# Ab diesem Label-Wert bringt die Welt den Welt-Mod gameworld_status mit (02-03).
STATUS_MOD_SCHEMA = 2


@dataclass(frozen=True)
class WorldStatus:
    code: str
    text: str


def parse_docker_time(value: str) -> datetime | None:
    """Docker-Zeitstempel (auch mit Nanosekunden) als aware datetime.

    Nie gestartete Container tragen "0001-01-01T00:00:00Z"; das und jeder
    unlesbare Wert ergeben None ("noch nicht bereit"). Python kürzt die
    Nachkommastellen auf Mikrosekunden; das erhält die Ordnung (>=).
    """
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.year <= 1:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def schema_version(label: str) -> int:
    """Label gameworld.schema als Ganzzahl; fehlend oder unlesbar zählt als 1."""
    try:
        return int(label)
    except ValueError:
        return 1


def _ready(container: ContainerInfo, status_mtime: str | None) -> bool:
    """Lauscht der Server? Nur eine Status-Datei aus diesem Lauf zählt (Pitfall 3)."""
    if schema_version(container.schema) < STATUS_MOD_SCHEMA:
        # Ältere Welten ohne Status-Mod: running reicht.
        return True
    if status_mtime is None:
        return False
    written = parse_docker_time(status_mtime)
    started = parse_docker_time(container.started_at)
    return written is not None and started is not None and written >= started


def derive_status(
    *,
    op_state: str,
    desired_state: str,
    last_error: str | None,
    container: ContainerInfo | None,
    reachable: bool,
    status_mtime: str | None,
) -> WorldStatus:
    if not reachable:
        return WorldStatus(UNKNOWN, TEXT_UNREACHABLE)
    if op_state == "creating":
        return WorldStatus(STARTING, TEXT_CREATING)
    if op_state == "failed":
        return WorldStatus(ERROR, last_error or TEXT_UNKNOWN_ERROR)
    if container is None:
        return WorldStatus(ERROR, TEXT_MISSING)

    state = container.status
    if state == "restarting":
        return WorldStatus(ERROR, TEXT_RESTARTING)
    if state == "running":
        if _ready(container, status_mtime):
            return WorldStatus(RUNNING, TEXT_RUNNING)
        return WorldStatus(STARTING, TEXT_STARTING)
    if state in {"exited", "created"} and desired_state == "stopped":
        return WorldStatus(STOPPED, TEXT_STOPPED)
    if state == "exited":
        if container.oom_killed:
            return WorldStatus(ERROR, TEXT_OOM)
        if container.exit_code != 0:
            return WorldStatus(ERROR, TEXT_CRASHED.format(code=container.exit_code))
        return WorldStatus(STOPPED, TEXT_STOPPED)
    if state == "created":
        return WorldStatus(STOPPED, TEXT_STOPPED)
    # paused, dead, removing: kommen bei Gameworld-Welten regulär nicht vor.
    return WorldStatus(ERROR, TEXT_ODD_STATE.format(state=state))
