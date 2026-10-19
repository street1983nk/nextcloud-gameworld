"""Private Defaults in der minetest.conf, Presets und Schutz vor Key-Injection (ZUGANG-01, WELT-01)."""

import pytest

from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt
from gameworld.provisioner.presets import PRESETS, Preset, get_preset, validate_preset_id

EXPECTED_LINES = [
    "server_announce = false",
    "server_announce_send_players = false",
    "serverlist_url =",
    "disallow_empty_password = true",
    "default_password = k3y",
    "default_privs = interact, shout, fly, fast",
    "basic_privs = interact, shout",
    "max_users = 8",
    "enable_client_modding = false",
    "secure.enable_security = true",
    "port = 30000",
]

KREATIV_LINES = [
    "creative_mode = true",
    "enable_damage = false",
    "enable_pvp = false",
    "enable_tnt = false",
    "enable_fire = false",
]

FORBIDDEN_PRIVS = {
    "server",
    "privs",
    "ban",
    "kick",
    "password",
    "basic_privs",
    "protection_bypass",
    "rollback",
    "give",
    "teleport",
    "bring",
}

BASE_KEYS = ("server_announce", "default_password", "secure.", "name", "port", "max_users")

ALL_PRESETS = list(PRESETS.values())


def _render(preset: Preset) -> list[str]:
    return [line.rstrip() for line in render_minetest_conf("Testwelt", "k3y", preset).splitlines()]


def _lines() -> list[str]:
    return _render(get_preset("mtg_kreativ"))


def _key(line: str) -> str:
    return line.split("=", 1)[0].strip()


def test_private_defaults_are_present() -> None:
    lines = _lines()
    for expected in EXPECTED_LINES:
        assert expected in lines, expected
    assert "server_name = Testwelt" in lines


def test_kreativ_preset_lines() -> None:
    lines = _lines()
    for expected in KREATIV_LINES:
        assert expected in lines, expected
    privs = [line for line in lines if _key(line) == "default_privs"]
    assert privs == ["default_privs = interact, shout, fly, fast"]


def test_get_preset_kreativ() -> None:
    preset = get_preset("mtg_kreativ")
    assert preset.title == "Bauen (kreativ)"
    assert preset.gameid == "minetest"
    assert preset.game_dir == "minetest_game"
    assert preset.game_zip == "minetest_game-38214.zip"
    assert preset.mem_limit == "512m"


def test_get_preset_unknown_names_allowed_titles() -> None:
    with pytest.raises(ValueError, match=r"Unbekannte Spielart\. Erlaubt sind: Bauen \(kreativ\)"):
        get_preset("xyz")
    with pytest.raises(ValueError, match="Unbekannte Spielart"):
        validate_preset_id("xyz")
    assert validate_preset_id("mtg_kreativ") == "mtg_kreativ"


@pytest.mark.parametrize("preset", ALL_PRESETS, ids=[preset.id for preset in ALL_PRESETS])
def test_every_preset_keeps_hardening(preset: Preset) -> None:
    lines = [line for line in _render(preset) if line]
    keys = [_key(line) for line in lines]
    assert len(keys) == len(set(keys)), keys
    assert "server_announce = false" in lines
    assert "secure.enable_security = true" in lines
    assert "name" not in keys
    privs = [line for line in lines if _key(line) == "default_privs"]
    assert len(privs) == 1
    granted = {priv.strip() for priv in privs[0].split("=", 1)[1].split(",")}
    assert not granted & FORBIDDEN_PRIVS
    for conf_line in preset.conf_lines:
        key = _key(conf_line)
        assert not any(key == base or (base.endswith(".") and key.startswith(base)) for base in BASE_KEYS), key


@pytest.mark.parametrize("preset", ALL_PRESETS, ids=[preset.id for preset in ALL_PRESETS])
def test_world_mt_follows_preset(preset: Preset) -> None:
    lines = render_world_mt(preset).splitlines()
    assert f"gameid = {preset.gameid}" in lines
    for backend in ("backend", "player_backend", "auth_backend", "mod_storage_backend"):
        assert f"{backend} = sqlite3" in lines


def test_no_name_key_and_never_announced() -> None:
    lines = _lines()
    assert not any(line.startswith("name") for line in lines)
    assert not any("server_announce = true" in line for line in lines)


def test_normalize_collapses_whitespace() -> None:
    assert normalize_world_name("  Mias   Welt ") == "Mias Welt"


def test_normalize_accepts_umlauts() -> None:
    assert normalize_world_name("Spaß mit Öl") == "Spaß mit Öl"


@pytest.mark.parametrize(
    "raw",
    ["Welt\nserver_announce = true", "", "a" * 41, "a=b", "x\x00"],
)
def test_normalize_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError, match="Weltname"):
        normalize_world_name(raw)
