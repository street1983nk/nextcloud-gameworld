"""Regression test for T-02-32: reconciler logs must arrive.

Deliberately without caplog.at_level, because that would set the level itself and
thereby hide exactly the error at issue: under the real startup
configuration (import of gameworld.main) the gameworld logger
must actually emit INFO messages.
"""

from __future__ import annotations

import logging

import gameworld.main  # noqa: F401  # sets up logging on import


def test_gameworld_logger_laesst_info_durch() -> None:
    log = logging.getLogger("gameworld.worlds.service")
    assert log.isEnabledFor(logging.INFO)


def test_gameworld_logger_hat_handler() -> None:
    log = logging.getLogger("gameworld")
    assert log.handlers


def test_info_meldung_erreicht_handler() -> None:
    aufgefangen: list[logging.LogRecord] = []

    class _Sammler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            aufgefangen.append(record)

    log = logging.getLogger("gameworld")
    sammler = _Sammler(level=logging.INFO)
    log.addHandler(sammler)
    try:
        logging.getLogger("gameworld.worlds.service").info("Reconciliation world %s: %s", "test", "START")
    finally:
        log.removeHandler(sammler)
    assert any("Reconciliation world" in record.getMessage() for record in aufgefangen)
