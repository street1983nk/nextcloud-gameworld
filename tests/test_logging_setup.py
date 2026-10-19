"""Regressionstest fuer T-02-32: Reconciler-Logs muessen ankommen.

Bewusst ohne caplog.at_level, weil das den Level selbst setzen wuerde und
damit genau den Fehler verdeckt, um den es geht: Unter der echten
Startkonfiguration (Import von gameworld.main) muss der gameworld-Logger
INFO-Meldungen tatsaechlich ausgeben.
"""

from __future__ import annotations

import logging

import gameworld.main  # noqa: F401  # richtet beim Import das Logging ein


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
        logging.getLogger("gameworld.worlds.service").info("Abgleich Welt %s: %s", "test", "START")
    finally:
        log.removeHandler(sammler)
    assert any("Abgleich Welt" in record.getMessage() for record in aufgefangen)
