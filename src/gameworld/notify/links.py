"""Absolute Deep Links auf die Handy-Seiten (rein, 04.1-RESEARCH.md Pattern 9).

Pfad statt ``#``: Beim Login-Umweg geht ein Fragment verloren, der Pfad bleibt
in ``redirect_url`` erhalten. Absolut, weil die Android-App den Link im Browser
öffnet. Die Basis-URL meldet der Browser eines Verwalters (``clean_origin``
lässt nur ``http(s)://host[:port]`` ohne Pfad, Zugangsdaten oder Fragment zu,
T-04.1-19).
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from urllib.parse import urlencode

EMBED_PATH = "/index.php/apps/app_api/embedded/gameworld/gameworld"
PAGES = frozenset({"pause", "versuch", "rueckblick"})
MAX_LINK = 4000

MSG_INVALID_ORIGIN = "Die Adresse muss wie https://cloud.example aussehen, ohne Pfad."

_ORIGIN = re.compile(r"(https?)://(\[[0-9A-Fa-f:.]+\]|[^/:?#@\[\]]+)(?::([0-9]{1,5}))?")
_HOST_LABEL = re.compile(r"[A-Za-z0-9-]{1,63}")


def _valid_host(host: str) -> bool:
    if host.startswith("["):
        try:
            ipaddress.IPv6Address(host[1:-1])
        except ValueError:
            return False
        return True
    try:
        ipaddress.IPv4Address(host)
    except ValueError:
        pass
    else:
        return True
    if len(host) > 253:
        return False
    return all(
        _HOST_LABEL.fullmatch(label) and not label.startswith("-") and not label.endswith("-")
        for label in host.split(".")
    )


def clean_origin(value: str) -> str:
    """Basis-URL ``http(s)://host[:port]``; alles andere wirft ValueError."""
    if not value or len(value) > 300 or any(unicodedata.category(char) in {"Cc", "Cf", "Zs"} for char in value):
        raise ValueError(MSG_INVALID_ORIGIN)
    match = _ORIGIN.fullmatch(value)
    if match is None or not _valid_host(match.group(2)):
        raise ValueError(MSG_INVALID_ORIGIN)
    port = match.group(3)
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError(MSG_INVALID_ORIGIN)
    return value


def page_link(origin: str, page: str, params: dict[str, str]) -> str:
    """Absoluter Link auf eine Handy-Seite; unbekannte Seite oder zu lang wirft ValueError."""
    if page not in PAGES:
        raise ValueError(f"Unbekannte Seite: {page}")
    link = f"{origin}{EMBED_PATH}/{page}"
    if params:
        link = f"{link}?{urlencode(params)}"
    if len(link) >= MAX_LINK:
        raise ValueError("Link zu lang")
    return link
