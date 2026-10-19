"""minetest.conf und world.mt einer Welt (ZUGANG-01: privat per Default)."""

from __future__ import annotations

import re
import unicodedata

MAX_NAME_LENGTH = 40
NAME_ERROR = (
    "Der Weltname darf 1 bis 40 Zeichen lang sein und nur Buchstaben, Ziffern, "
    "Leerzeichen, Punkt, Bindestrich und Unterstrich enthalten."
)
_ALLOWED = re.compile(r"[\w .\-]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_world_name(raw: str) -> str:
    """Bringt einen Weltnamen auf eine sichere Zeile oder wirft ValueError.

    Steuerzeichen werden vor dem Zusammenfassen der Leerzeichen geprüft: ein
    Zeilenumbruch im Rohwert ist ein Fehler, keine Normalisierung. Sonst könnte
    ein Name mit Zeilenumbruch einen zweiten Key wie server_announce einschleusen.
    """
    if any(unicodedata.category(char).startswith("C") for char in raw):
        raise ValueError(NAME_ERROR)
    name = _WHITESPACE.sub(" ", raw.strip())
    if not 1 <= len(name) <= MAX_NAME_LENGTH or not _ALLOWED.fullmatch(name):
        raise ValueError(NAME_ERROR)
    return name


def render_minetest_conf(world_name: str, world_key: str) -> str:
    """Gehärtete Server-Konfiguration; Keys gegen Luanti 5.17.0 geprüft.

    Bewusst ohne ``name``: sonst bekäme ein Spieler automatisch alle Rechte.
    """
    lines = [
        f"server_name = {world_name}",
        "server_announce = false",
        "server_announce_send_players = false",
        "serverlist_url =",
        "disallow_empty_password = true",
        f"default_password = {world_key}",
        "default_privs = interact, shout",
        "basic_privs = interact, shout",
        "max_users = 8",
        "enable_rollback_recording = false",
        "secure.enable_security = true",
        "secure.trusted_mods =",
        "secure.http_mods =",
        "enable_client_modding = false",
        "update_information_url =",
        "port = 30000",
    ]
    return "\n".join(lines) + "\n"


def render_world_mt() -> str:
    """Welt-Metadaten mit SQLite für alle Backends."""
    lines = [
        "gameid = minetest",
        "backend = sqlite3",
        "player_backend = sqlite3",
        "auth_backend = sqlite3",
        "mod_storage_backend = sqlite3",
    ]
    return "\n".join(lines) + "\n"
