"""minetest.conf and world.mt of a world (ZUGANG-01: private by default)."""

from __future__ import annotations

import re
import unicodedata

from gameworld.provisioner.presets import Preset

MAX_NAME_LENGTH = 40
NAME_ERROR = (
    "Der Weltname darf 1 bis 40 Zeichen lang sein und nur Buchstaben, Ziffern, "
    "Leerzeichen, Punkt, Bindestrich und Unterstrich enthalten."
)
_ALLOWED = re.compile(r"[\w .\-]+")
_WHITESPACE = re.compile(r"\s+")


def normalize_world_name(raw: str) -> str:
    """Bring a world name to a safe line or raise ValueError.

    Control characters are checked before the spaces are collapsed: a
    line break in the raw value is an error, not a normalization. Otherwise
    a name with a line break could smuggle in a second key like server_announce.
    """
    if any(unicodedata.category(char).startswith("C") for char in raw):
        raise ValueError(NAME_ERROR)
    name = _WHITESPACE.sub(" ", raw.strip())
    if not 1 <= len(name) <= MAX_NAME_LENGTH or not _ALLOWED.fullmatch(name):
        raise ValueError(NAME_ERROR)
    return name


def render_minetest_conf(world_name: str, world_key: str, preset: Preset) -> str:
    """Hardened server configuration; keys checked against Luanti 5.17.0.

    Deliberately without ``name``: otherwise a player would automatically get all rights.
    The preset supplies exactly one default_privs line and appends its
    hard-coded switches at the end; it never sets base keys.
    """
    lines = [
        f"server_name = {world_name}",
        "server_announce = false",
        "server_announce_send_players = false",
        "serverlist_url =",
        "disallow_empty_password = true",
        f"default_password = {world_key}",
        f"default_privs = {preset.default_privs}",
        "basic_privs = interact, shout",
        "max_users = 8",
        "enable_rollback_recording = false",
        "secure.enable_security = true",
        "secure.trusted_mods =",
        "secure.http_mods =",
        "enable_client_modding = false",
        "update_information_url =",
        "port = 30000",
        *preset.conf_lines,
    ]
    return "\n".join(lines) + "\n"


def render_world_mt(preset: Preset) -> str:
    """World metadata with the game of the preset and SQLite for all backends."""
    lines = [
        f"gameid = {preset.gameid}",
        "backend = sqlite3",
        "player_backend = sqlite3",
        "auth_backend = sqlite3",
        "mod_storage_backend = sqlite3",
    ]
    return "\n".join(lines) + "\n"
