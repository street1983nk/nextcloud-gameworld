"""Statusmodell ohne Docker: jede Zeile der Tabelle aus RESEARCH Pattern 3."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gameworld.provisioner.client import ContainerInfo
from gameworld.worlds.status import (
    ERROR,
    RUNNING,
    STARTING,
    STOPPED,
    UNKNOWN,
    WorldStatus,
    derive_status,
    parse_docker_time,
    schema_version,
)

STARTED = "2026-10-19T18:19:46.947430723Z"
LATER = "2026-10-19T18:19:47.000000001Z"
EARLIER = "2026-10-19T18:19:46.000000001Z"
ZERO = "0001-01-01T00:00:00Z"


def _container(
    status: str,
    *,
    exit_code: int = 0,
    oom_killed: bool = False,
    started_at: str = STARTED,
    schema: str = "2",
) -> ContainerInfo:
    return ContainerInfo(
        "cid",
        "gameworld-x-0123456789ab",
        "0123456789ab",
        status,
        30015,
        exit_code=exit_code,
        oom_killed=oom_killed,
        started_at=started_at,
        schema=schema,
    )


def _derive(
    container: ContainerInfo | None,
    *,
    op_state: str = "ready",
    desired_state: str = "running",
    last_error: str | None = None,
    reachable: bool = True,
    status_mtime: str | None = None,
) -> WorldStatus:
    return derive_status(
        op_state=op_state,
        desired_state=desired_state,
        last_error=last_error,
        container=container,
        reachable=reachable,
        status_mtime=status_mtime,
    )


def test_unreachable_docker_is_unknown() -> None:
    assert _derive(None, reachable=False, op_state="failed") == WorldStatus(UNKNOWN, "Docker nicht erreichbar")


def test_creating_is_starting() -> None:
    assert _derive(None, op_state="creating") == WorldStatus(STARTING, "Wird erstellt")


def test_failed_shows_last_error() -> None:
    status = _derive(_container("running"), op_state="failed", last_error="Kein freier UDP-Port gefunden.")
    assert status == WorldStatus(ERROR, "Kein freier UDP-Port gefunden.")


def test_failed_without_message_has_fallback() -> None:
    assert _derive(None, op_state="failed") == WorldStatus(ERROR, "Unbekannter Fehler")


def test_missing_container_is_error() -> None:
    """Ohne Volume-Prüfung nie "Weltdaten vorhanden" behaupten (CR-01)."""
    status = _derive(None)
    assert status == WorldStatus(
        ERROR, "Der Server der Welt fehlt. Starten stellt ihn wieder her, falls die Weltdaten noch da sind."
    )
    assert "vorhanden" not in status.text


def test_restarting_is_error() -> None:
    assert _derive(_container("restarting")) == WorldStatus(ERROR, "Startet immer wieder neu")


def test_running_with_fresh_status_file() -> None:
    assert _derive(_container("running"), status_mtime=LATER) == WorldStatus(RUNNING, "Läuft")


def test_running_with_same_timestamp_counts_as_ready() -> None:
    assert _derive(_container("running"), status_mtime=STARTED).code == RUNNING


@pytest.mark.parametrize("mtime", [None, EARLIER, ZERO, "kaputt"])
def test_running_without_fresh_status_file_is_starting(mtime: str | None) -> None:
    assert _derive(_container("running"), status_mtime=mtime) == WorldStatus(STARTING, "Startet gerade")


def test_running_with_unreadable_started_at_is_starting() -> None:
    assert _derive(_container("running", started_at="nie"), status_mtime=LATER).code == STARTING


def test_running_schema_one_needs_no_status_file() -> None:
    assert _derive(_container("running", schema="1")) == WorldStatus(RUNNING, "Läuft")


@pytest.mark.parametrize("state", ["exited", "created"])
def test_stopped_by_parent(state: str) -> None:
    container = _container(state, exit_code=137, oom_killed=True)
    assert _derive(container, desired_state="stopped") == WorldStatus(STOPPED, "Gestoppt")


def test_oom_killed_is_error() -> None:
    status = _derive(_container("exited", exit_code=137, oom_killed=True))
    assert status == WorldStatus(ERROR, "Die Welt hatte zu wenig Arbeitsspeicher und wurde beendet.")


def test_unexpected_exit_shows_code() -> None:
    status = _derive(_container("exited", exit_code=137))
    assert status == WorldStatus(ERROR, "Die Welt wurde unerwartet beendet (Code 137).")


def test_clean_exit_while_desired_running_is_stopped() -> None:
    assert _derive(_container("exited", exit_code=0)) == WorldStatus(STOPPED, "Gestoppt")


def test_created_without_creating_op_state_is_stopped() -> None:
    assert _derive(_container("created")) == WorldStatus(STOPPED, "Gestoppt")


def test_parse_docker_time_with_nanoseconds() -> None:
    assert parse_docker_time(STARTED) == datetime(2026, 10, 19, 18, 19, 46, 947430, tzinfo=UTC)


@pytest.mark.parametrize("value", [ZERO, "", "kaputt"])
def test_parse_docker_time_rejects_zero_and_garbage(value: str) -> None:
    assert parse_docker_time(value) is None


def test_parse_docker_time_naive_is_utc() -> None:
    assert parse_docker_time("2026-10-19T18:19:46") == datetime(2026, 10, 19, 18, 19, 46, tzinfo=UTC)


@pytest.mark.parametrize(("label", "expected"), [("2", 2), ("1", 1), ("10", 10), ("", 1), ("zwei", 1)])
def test_schema_version(label: str, expected: int) -> None:
    assert schema_version(label) == expected
