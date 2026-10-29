"""Negative and positive tests of the log redaction of /play/ws (T-04.2-36).

The lines are built as in uvicorn 0.54 (same msg and args, same
formatter), so that the test checks the real format path and not just the filter.
"""

from __future__ import annotations

import copy
import io
import logging
import logging.config
from collections.abc import Iterator

import pytest
import uvicorn.config
from uvicorn.logging import AccessFormatter, DefaultFormatter

from gameworld.play.log_redact import RedactWsQueryFilter, install_ws_query_redaction

TICKET_VALUE = "GEHEIM123"
CLIENT = "127.0.0.1:5000"
WS_ACCEPTED = '%s - "WebSocket %s" [accepted]'
WS_403 = '%s - "WebSocket %s" 403'
WS_STATUS = '%s - "WebSocket %s" %d'
HTTP_ACCESS = '%s - "%s %s HTTP/%s" %d'
LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@pytest.fixture(autouse=True)
def keep_loggers() -> Iterator[None]:
    """Restore level, handler, filter and propagate of the uvicorn loggers after every test."""
    saved = {
        name: (logger.level, list(logger.handlers), list(logger.filters), logger.propagate, logger.disabled)
        for name in LOGGERS
        for logger in [logging.getLogger(name)]
    }
    yield
    for name, (level, handlers, filters, propagate, disabled) in saved.items():
        logger = logging.getLogger(name)
        logger.setLevel(level)
        logger.handlers[:] = handlers
        logger.filters[:] = filters
        logger.propagate = propagate
        logger.disabled = disabled


def _record(name: str, msg: str, args: tuple[object, ...]) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, msg, args, None)


def _format(record: logging.LogRecord, *, redact: bool) -> str:
    if redact:
        assert RedactWsQueryFilter().filter(record) is True
    formatter = AccessFormatter("%(message)s") if record.name == "uvicorn.access" else DefaultFormatter("%(message)s")
    return formatter.format(record)


WS_PATHS = [
    ("/play/ws?t=GEHEIM123", "/play/ws?<redacted>"),
    ("/exapps/gameworld/play/ws?t=GEHEIM123", "/exapps/gameworld/play/ws?<redacted>"),
    ("/play/ws?t=GEHEIM123&x=1", "/play/ws?<redacted>"),
]


@pytest.mark.parametrize(("path", "expected"), WS_PATHS)
@pytest.mark.parametrize(
    ("msg", "extra"), [(WS_ACCEPTED, ()), (WS_403, ()), (WS_STATUS, (400,))], ids=["accepted", "403", "status"]
)
def test_neg_ws_accepted_ohne_ticket(path: str, expected: str, msg: str, extra: tuple[object, ...]) -> None:
    line = _format(_record("uvicorn.error", msg, (CLIENT, path, *extra)), redact=True)
    assert expected in line
    assert TICKET_VALUE not in line
    assert "t=" not in line


@pytest.mark.parametrize(("path", "expected"), WS_PATHS)
def test_neg_http_access_ohne_ticket(path: str, expected: str) -> None:
    line = _format(_record("uvicorn.access", HTTP_ACCESS, (CLIENT, "GET", path, "1.1", 400)), redact=True)
    assert expected in line
    assert TICKET_VALUE not in line


def test_neg_bereits_formatierte_zeile() -> None:
    """Even a fully formatted msg without args loses the query."""
    line = _format(
        _record("uvicorn.error", f'{CLIENT} - "WebSocket /play/ws?t={TICKET_VALUE}" [accepted]', ()), redact=True
    )
    assert "/play/ws?<redacted>" in line
    assert TICKET_VALUE not in line


@pytest.mark.parametrize("path", ["/play/launch", "/api/my/worlds?x=1", "/play/wsx?t=1", "/play/ws"])
@pytest.mark.parametrize("name", ["uvicorn.access", "uvicorn.error"])
def test_pos_andere_pfade_unveraendert(path: str, name: str) -> None:
    """Positive control: other paths stay byte-identical, the filter swallows no line."""
    if name == "uvicorn.access":
        args: tuple[object, ...] = (CLIENT, "POST", path, "1.1", 200)
        msg = HTTP_ACCESS
    else:
        args = (CLIENT, path)
        msg = WS_ACCEPTED
    plain = _format(_record(name, msg, args), redact=False)
    redacted = _format(_record(name, msg, args), redact=True)
    assert redacted == plain
    assert path in redacted


def test_neg_ueberlebt_uvicorn_dictconfig() -> None:
    """The filter sits on the logger, uvicorn's dictConfig (as in uvicorn.run) only replaces handlers."""
    install_ws_query_redaction()
    logging.config.dictConfig(copy.deepcopy(uvicorn.config.LOGGING_CONFIG))
    sink = io.StringIO()
    error_handler = logging.StreamHandler(sink)
    error_handler.setFormatter(DefaultFormatter("%(message)s"))
    access_handler = logging.StreamHandler(sink)
    access_handler.setFormatter(AccessFormatter("%(message)s"))
    logging.getLogger("uvicorn.error").addHandler(error_handler)
    logging.getLogger("uvicorn.access").addHandler(access_handler)
    logging.getLogger("uvicorn.error").info(WS_ACCEPTED, CLIENT, f"/play/ws?t={TICKET_VALUE}")
    logging.getLogger("uvicorn.access").info(HTTP_ACCESS, CLIENT, "GET", f"/play/ws?t={TICKET_VALUE}", "1.1", 400)
    out = sink.getvalue()
    assert out.count("/play/ws?<redacted>") == 2
    assert TICKET_VALUE not in out


def test_pos_install_idempotent() -> None:
    install_ws_query_redaction()
    install_ws_query_redaction()
    for name in ("uvicorn.access", "uvicorn.error"):
        found = [f for f in logging.getLogger(name).filters if isinstance(f, RedactWsQueryFilter)]
        assert len(found) == 1
