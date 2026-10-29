"""Game types (presets) of a world, pure and without Docker.

The switches per preset come from the settingtypes.txt of the respective
game zip. No user value reaches minetest.conf or the container spec:
the API accepts only a preset ID from this registry, all lines and
limits are hard-coded here.
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

# Switches from the settingtypes.txt of VoxeLibre 0.92.4. Memory: the
# RESEARCH spike measured up to 501 MiB while generating the map, hence 1 GiB without
# swap (512 MiB as with the creative preset would lead to OOM when exploring).
# Hunger stays on, therefore deliberately no line here.
VOXELIBRE_SANFT = Preset(
    id="voxelibre_sanft",
    title="Abenteuer (sanft)",
    description="VoxeLibre: Überleben mit friedlichen Tieren, Inventar bleibt beim Tod.",
    game_zip="mineclone2-39534.zip",
    game_sha256="6215d4da27900874959ff586fb266091be3d4161b9d4f5d27ce0d0cdc49f1af2",
    game_dir="mineclone2",
    gameid="mineclone2",
    mem_limit="1g",
    default_privs="interact, shout",
    conf_lines=(
        "creative_mode = false",
        "enable_damage = true",
        "enable_pvp = false",
        "only_peaceful_mobs = true",
        "mobs_griefing = false",
        "mcl_explosions_griefing = false",
        "enable_fire = false",
        "mcl_keepInventory = true",
        "mcl_enable_commandblocks = false",
    ),
)

# Order = display order in the dashboard.
PRESETS: dict[str, Preset] = {preset.id: preset for preset in (MTG_KREATIV, VOXELIBRE_SANFT)}
DEFAULT_PRESET_ID = MTG_KREATIV.id


# Template (D-25); the inserted titles are translated per language in the catalogs.
TEXT_UNKNOWN_PRESET_ID = "Unbekannte Spielart. Erlaubt sind: {titles}."


def unknown_preset_message(titles: list[str]) -> str:
    """Message for an unknown game type with the given (possibly translated) titles."""
    return TEXT_UNKNOWN_PRESET_ID.format(titles=", ".join(titles))


def _unknown_message() -> str:
    return unknown_preset_message([preset.title for preset in PRESETS.values()])


def get_preset(preset_id: str) -> Preset:
    """Preset for the ID or ValueError with a German message."""
    preset = PRESETS.get(preset_id)
    if preset is None:
        raise ValueError(_unknown_message())
    return preset


def validate_preset_id(value: str) -> str:
    """Pydantic AfterValidator: lets only registry IDs through."""
    get_preset(value)
    return value
