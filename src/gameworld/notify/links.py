"""Absolute Deep Links auf die Handy-Seiten (rein, 04.1-RESEARCH.md Pattern 9).

Pfad statt ``#``: Beim Login-Umweg geht ein Fragment verloren, der Pfad bleibt
in ``redirect_url`` erhalten. Absolut, weil die Android-App den Link im Browser
öffnet. Die Basis-URL meldet der Browser eines Verwalters: Origin plus Webroot
der Nextcloud (``@nextcloud/router`` getRootUrl, etwa ``/nextcloud`` bei einer
Installation im Unterordner, WR-04). ``clean_origin`` lässt nur
``http(s)://host[:port]`` mit einem streng geprüften Pfad zu, ohne Zugangsdaten,
Query, Fragment oder Punkt-Segmente (T-04.1-19). ``page_link`` setzt
Basis-URL plus ``EMBED_PATH`` zusammen.

Welche Basis-URL gilt, entscheidet ``decide_origin`` (Owner-Entscheid
22.10.2026, "Erste merken, Wechsel nur bestätigt"): Die erste gemeldete Adresse
wird gespeichert, eine abweichende nur nach Bestätigung, und eine https-Adresse
wird nie durch eine http-Adresse ersetzt.
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
    """Basis-URL ``http(s)://host[:port][/webroot]``; alles andere wirft ValueError.

    Der Webroot besteht nur aus Segmenten ``[A-Za-z0-9._~-]+``, ohne ``.`` und
    ``..``, ohne abschließenden Schrägstrich.
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
    """Origin des Browsers (ohne Pfad) plus Webroot zu einer geprüften Basis-URL (ValueError bei Ungültigem)."""
    match = _ORIGIN.fullmatch(clean_origin(origin))
    if match is None or match.group(4):
        raise ValueError(MSG_INVALID_ORIGIN)
    if webroot and (not webroot.startswith("/") or webroot.endswith("/")):
        raise ValueError(MSG_INVALID_ORIGIN)
    return clean_origin(origin + webroot)


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


def app_link(origin: str) -> str:
    """Absoluter Link auf die Übersicht der Gameworld-Seite (Welten, Sicherungen)."""
    return f"{origin}{EMBED_PATH}"


@dataclass(frozen=True)
class OriginDecision:
    """Ergebnis von decide_origin: speichern ja/nein, Rückfrage nötig ja/nein."""

    store: bool
    confirm_needed: bool


def decide_origin(current: str | None, proposed: str, *, confirm: bool) -> OriginDecision:
    """Erste Adresse merken, Wechsel nur bestätigt, nie von https auf http (WR-04, Owner 22.10.2026).

    ``current`` ist die gespeicherte, gültige Basis-URL oder None, ``proposed`` die
    eben gemeldete (schon geprüft). Ohne gespeicherte Adresse wird gespeichert.
    Gleiche Adresse: nichts zu tun. https durch http: nie, auch nicht bestätigt,
    und ohne Rückfrage. Sonst nur mit ``confirm``, ohne kommt die Rückfrage.
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
