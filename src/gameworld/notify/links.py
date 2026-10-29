"""Absolute deep links to the phone pages (pure, 04.1-RESEARCH.md pattern 9).

Path instead of ``#``: on the login detour a fragment is lost, the path is kept
in ``redirect_url``. Absolute, because the Android app opens the link in the
browser. The base URL is reported by the browser of a manager: origin plus webroot
of Nextcloud (``@nextcloud/router`` getRootUrl, e.g. ``/nextcloud`` for an
installation in a subfolder, WR-04). ``clean_origin`` allows only
``http(s)://host[:port]`` with a strictly checked path, without credentials,
query, fragment or dot segments (T-04.1-19). ``page_link`` composes
base URL plus ``EMBED_PATH``.

Which base URL applies is decided by ``decide_origin`` (owner decision
22.10.2026, "remember the first, change only when confirmed"): the first reported address
is stored, a differing one only after confirmation, and an https address
is never replaced by an http address.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlencode

EMBED_PATH = "/index.php/apps/app_api/embedded/gameworld/gameworld"
PAGES = frozenset({"pause", "versuch", "rueckblick"})
MAX_LINK = 4000
MAX_BASE = 300

MSG_INVALID_ORIGIN = "Die Adresse muss wie https://cloud.example oder https://example.org/nextcloud aussehen."

_ORIGIN = re.compile(r"(https?)://(\[[0-9A-Fa-f:.]+\]|[^/:?#@\[\]]+)(?::([0-9]{1,5}))?((?:/[A-Za-z0-9._~-]+)*)")
_HOST_LABEL = re.compile(r"[A-Za-z0-9-]{1,63}")
_DOT_SEGMENTS = frozenset({".", ".."})


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
    """Base URL ``http(s)://host[:port][/webroot]``; anything else raises ValueError.

    The webroot consists only of segments ``[A-Za-z0-9._~-]+``, without ``.`` and
    ``..``, without a trailing slash.
    """
    if not value or len(value) > MAX_BASE or any(unicodedata.category(char) in {"Cc", "Cf", "Zs"} for char in value):
        raise ValueError(MSG_INVALID_ORIGIN)
    match = _ORIGIN.fullmatch(value)
    if match is None or not _valid_host(match.group(2)):
        raise ValueError(MSG_INVALID_ORIGIN)
    port = match.group(3)
    if port is not None and not 1 <= int(port) <= 65535:
        raise ValueError(MSG_INVALID_ORIGIN)
    if any(segment in _DOT_SEGMENTS for segment in match.group(4).split("/")[1:]):
        raise ValueError(MSG_INVALID_ORIGIN)
    return value


def join_base(origin: str, webroot: str) -> str:
    """Origin of the browser (without path) plus webroot into a checked base URL (ValueError if invalid)."""
    match = _ORIGIN.fullmatch(clean_origin(origin))
    if match is None or match.group(4):
        raise ValueError(MSG_INVALID_ORIGIN)
    if webroot and (not webroot.startswith("/") or webroot.endswith("/")):
        raise ValueError(MSG_INVALID_ORIGIN)
    return clean_origin(origin + webroot)


def page_link(origin: str, page: str, params: dict[str, str]) -> str:
    """Absolute link to a phone page; an unknown page or one that is too long raises ValueError."""
    if page not in PAGES:
        raise ValueError(f"Unbekannte Seite: {page}")
    link = f"{origin}{EMBED_PATH}/{page}"
    if params:
        link = f"{link}?{urlencode(params)}"
    if len(link) >= MAX_LINK:
        raise ValueError("Link zu lang")
    return link


def app_link(origin: str) -> str:
    """Absolute link to the overview of the Gameworld page (worlds, backups)."""
    return f"{origin}{EMBED_PATH}"


@dataclass(frozen=True)
class OriginDecision:
    """Result of decide_origin: store yes/no, confirmation prompt needed yes/no."""

    store: bool
    confirm_needed: bool


def decide_origin(current: str | None, proposed: str, *, confirm: bool) -> OriginDecision:
    """Remember the first address, change only when confirmed, never from https to http (WR-04, owner 22.10.2026).

    ``current`` is the stored, valid base URL or None, ``proposed`` the one
    just reported (already checked). Without a stored address it is stored.
    Same address: nothing to do. https replaced by http: never, not even when confirmed,
    and without a prompt. Otherwise only with ``confirm``, without it the prompt comes.
    """
    if current is None:
        return OriginDecision(store=True, confirm_needed=False)
    if current == proposed:
        return OriginDecision(store=False, confirm_needed=False)
    if current.startswith("https://") and not proposed.startswith("https://"):
        return OriginDecision(store=False, confirm_needed=False)
    if confirm:
        return OriginDecision(store=True, confirm_needed=False)
    return OriginDecision(store=False, confirm_needed=True)
