"""Redacts the query of /play/ws in uvicorn log lines (T-04.2-36).

The WebSocket ticket is in the URL as ``?t=<ticket>``, because browsers cannot set
their own headers when opening a WebSocket. uvicorn writes the path including the
query into its log lines; without this filter every ticket would end up in the log.

uvicorn logs WebSocket lines ("WebSocket /play/ws?..." [accepted], 403 or
status) via the logger ``uvicorn.error`` and HTTP accesses via ``uvicorn.access``.
The filter therefore attaches to both loggers. They are logger filters and not
handler filters, because uvicorn's dictConfig replaces the handlers at startup but
leaves the loggers' filters in place.

Other paths and query strings stay unchanged, and the filter never
swallows a line.
"""

from __future__ import annotations

import logging
import re

WS_PATH = "/play/ws"
REDACTED = "<redacted>"

# Path ends with /play/ws, then ? and the query up to the space or quotation mark.
_WS_QUERY = re.compile(r"(/play/ws)\?[^\s\"']+")
_LOGGERS = ("uvicorn.access", "uvicorn.error")


def _redact_arg(value: str) -> str:
    path, sep, query = value.partition("?")
    if sep and query and path.endswith(WS_PATH):
        return f"{path}?{REDACTED}"
    return value


class RedactWsQueryFilter(logging.Filter):
    """Replaces every query of /play/ws in arguments and message with ``<redacted>``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(arg) if isinstance(arg, str) else arg for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = _WS_QUERY.sub(rf"\1?{REDACTED}", record.msg)
        return True


def install_ws_query_redaction() -> None:
    """Attaches the filter once to uvicorn.access and uvicorn.error (idempotent)."""
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactWsQueryFilter) for existing in logger.filters):
            logger.addFilter(RedactWsQueryFilter())
