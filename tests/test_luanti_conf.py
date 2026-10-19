"""Private Defaults in der minetest.conf und Schutz vor Key-Injection (ZUGANG-01)."""

import pytest

from gameworld.provisioner.luanti_conf import normalize_world_name, render_minetest_conf, render_world_mt

EXPECTED_LINES = [
    "server_announce = false",
    "server_announce_send_players = false",
    "serverlist_url =",
    "disallow_empty_password = true",
    "default_password = k3y",
    "default_privs = interact, shout",
    "basic_privs = interact, shout",
    "max_users = 8",
    "enable_client_modding = false",
    "secure.enable_security = true",
    "port = 30000",
]


def _lines() -> list[str]:
    return [line.rstrip() for line in render_minetest_conf("Testwelt", "k3y").splitlines()]


def test_private_defaults_are_present() -> None:
    lines = _lines()
    for expected in EXPECTED_LINES:
        assert expected in lines, expected
    assert "server_name = Testwelt" in lines


def test_no_name_key_and_never_announced() -> None:
    lines = _lines()
    assert not any(line.startswith("name") for line in lines)
    assert not any("server_announce = true" in line for line in lines)


def test_world_mt_forces_sqlite() -> None:
    lines = render_world_mt().splitlines()
    assert "gameid = minetest" in lines
    assert "backend = sqlite3" in lines
    assert "auth_backend = sqlite3" in lines


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
