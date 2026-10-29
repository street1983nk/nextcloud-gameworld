"""Status model of a world, derived from Docker (RESEARCH pattern 3).

Pure and testable without Docker. The database supplies the operation
states ``creating`` and ``failed``, the busy states ``backing_up``,
``restoring`` and ``restoring_swap`` (phase 5, D-10) and the parent's wish
``desired_state``; everything else comes from ``docker inspect``
(State, ExitCode, OOMKilled, StartedAt) and the mtime of the status file of
the world mod. The parent-facing texts are fixed constants here.
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
BACKING_UP = "backing_up"
RESTORING = "restoring"

TEXT_UNREACHABLE = "Docker nicht erreichbar"
TEXT_CREATING = "Wird erstellt"
TEXT_BACKING_UP = "Wird gesichert ..."
TEXT_RESTORING = "Wird wiederhergestellt ..."
TEXT_UNKNOWN_ERROR = "Unbekannter Fehler"
# Neutral: whether the volume still exists is only checked by the start (CR-01); if it is missing,
# the world becomes "world data missing, delete only".
TEXT_MISSING = "Der Server der Welt fehlt. Starten stellt ihn wieder her, falls die Weltdaten noch da sind."
TEXT_RESTARTING = "Startet immer wieder neu"
TEXT_RUNNING = "Läuft"
TEXT_STARTING = "Startet gerade"
TEXT_STOPPED = "Gestoppt"
TEXT_OOM = "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet."
TEXT_CRASHED = "Die Welt wurde unerwartet beendet (Code {code})."
TEXT_ODD_STATE = "Unerwarteter Zustand des Servers ({state})."

# From this label value on, the world ships the world mod gameworld_status (02-03).
STATUS_MOD_SCHEMA = 2


@dataclass(frozen=True)
class WorldStatus:
    code: str
    text: str


def parse_docker_time(value: str) -> datetime | None:
    """Docker timestamp (also with nanoseconds) as an aware datetime.

    Never-started containers carry "0001-01-01T00:00:00Z"; that and any
    unreadable value yield None ("not ready yet"). Python truncates the
    fractional digits to microseconds; that preserves the order (>=).
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
    """Label gameworld.schema as an integer; missing or unreadable counts as 1."""
    try:
        return int(label)
    except ValueError:
        return 1


def _ready(container: ContainerInfo, status_mtime: str | None) -> bool:
    """Is the server listening? Only a status file from this run counts (pitfall 3)."""
    if schema_version(container.schema) < STATUS_MOD_SCHEMA:
        # Older worlds without the status mod: running is enough.
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
    # Busy states before the container: the container is intentionally stopped then.
    if op_state == "backing_up":
        return WorldStatus(BACKING_UP, TEXT_BACKING_UP)
    if op_state in {"restoring", "restoring_swap"}:
        return WorldStatus(RESTORING, TEXT_RESTORING)
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
    # paused, dead, removing: do not occur regularly with Gameworld worlds.
    return WorldStatus(ERROR, TEXT_ODD_STATE.format(state=state))
