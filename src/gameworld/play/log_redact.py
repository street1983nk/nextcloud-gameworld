"""Schwärzt die Query von /play/ws in uvicorn-Logzeilen (T-04.2-36).

Das WebSocket-Ticket steht als ``?t=<Ticket>`` in der URL, weil Browser beim
WebSocket-Aufbau keine eigenen Header setzen können. uvicorn schreibt Pfad samt
Query in seine Logzeilen; ohne diesen Filter landete jedes Ticket im Log.

uvicorn loggt WebSocket-Zeilen ("WebSocket /play/ws?..." [accepted], 403 oder
Status) über den Logger ``uvicorn.error`` und HTTP-Zugriffe über ``uvicorn.access``.
Der Filter hängt darum an beiden Loggern. Es sind Logger-Filter und keine
Handler-Filter, weil uvicorns dictConfig beim Start die Handler ersetzt, die
Filter der Logger aber stehen lässt.

Andere Pfade und Query-Strings bleiben unverändert, und der Filter verschluckt
nie eine Zeile.
"""

from __future__ import annotations

import logging
import re

WS_PATH = "/play/ws"
REDACTED = "<redacted>"

# Pfad endet auf /play/ws, danach ? und die Query bis zum Leerzeichen oder Anführungszeichen.
_WS_QUERY = re.compile(r"(/play/ws)\?[^\s\"']+")
_LOGGERS = ("uvicorn.access", "uvicorn.error")


def _redact_arg(value: str) -> str:
    path, sep, query = value.partition("?")
    if sep and query and path.endswith(WS_PATH):
        return f"{path}?{REDACTED}"
    return value


class RedactWsQueryFilter(logging.Filter):
    """Ersetzt in Argumenten und Nachricht jede Query von /play/ws durch ``<redacted>``."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_arg(arg) if isinstance(arg, str) else arg for arg in record.args)
        if isinstance(record.msg, str):
            record.msg = _WS_QUERY.sub(rf"\1?{REDACTED}", record.msg)
        return True


def install_ws_query_redaction() -> None:
    """Hängt den Filter einmal an uvicorn.access und uvicorn.error (idempotent)."""
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(existing, RedactWsQueryFilter) for existing in logger.filters):
            logger.addFilter(RedactWsQueryFilter())
