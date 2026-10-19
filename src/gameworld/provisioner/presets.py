"""Spielarten (Presets) einer Welt, rein und ohne Docker.

Die Schalter je Preset stammen aus der settingtypes.txt des jeweiligen
Spiel-Zips. Kein Nutzerwert erreicht minetest.conf oder die Container-Spec:
Die API nimmt nur eine Preset-ID aus dieser Registry an, alle Zeilen und
Limits sind hier fest kodiert.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    description: str
    game_zip: str
    game_sha256: str
    game_dir: str
    gameid: str
    mem_limit: str
    default_privs: str
    conf_lines: tuple[str, ...]


MTG_KREATIV = Preset(
    id="mtg_kreativ",
    title="Bauen (kreativ)",
    description="Minetest Game: unbegrenzt Blöcke, kein Schaden, Fliegen erlaubt.",
    game_zip="minetest_game-38214.zip",
    game_sha256="5b364f6b0cf31ec336319492e14106d932eb86b65a91ded99f4b25f4876519dc",
    game_dir="minetest_game",
    gameid="minetest",
    mem_limit="512m",
    default_privs="interact, shout, fly, fast",
    conf_lines=(
        "creative_mode = true",
        "enable_damage = false",
        "enable_pvp = false",
        "enable_tnt = false",
        "enable_fire = false",
    ),
)

# Reihenfolge = Anzeigereihenfolge im Dashboard.
PRESETS: dict[str, Preset] = {preset.id: preset for preset in (MTG_KREATIV,)}
DEFAULT_PRESET_ID = MTG_KREATIV.id


def _unknown_message() -> str:
    titles = ", ".join(preset.title for preset in PRESETS.values())
    return f"Unbekannte Spielart. Erlaubt sind: {titles}."


def get_preset(preset_id: str) -> Preset:
    """Preset zur ID oder ValueError mit deutscher Meldung."""
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(_unknown_message())
    return preset


def validate_preset_id(value: str) -> str:
    """Pydantic-AfterValidator: lässt nur Registry-IDs durch."""
    get_preset(value)
    return value
