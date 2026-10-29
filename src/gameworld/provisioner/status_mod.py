"""The world mod gameworld_status, as constants in the code.

Every new world gets it in the payload under ``worldmods``. On loading the
mods and on every join or leave it writes the sorted names of the connected
players into ``gameworld_players.txt`` in the world folder. It writes
player names only, no IP addresses. It needs neither
``secure.trusted_mods`` nor ``secure.http_mods``: atomic writing into the
own world folder is allowed even with ``secure.enable_security = true``.
"""

from __future__ import annotations

import re

from gameworld.provisioner.spec import DATA_DIR

MOD_NAME = "gameworld_status"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

MOD_INIT_LUA = """\
-- gameworld_status: reports the connected players to the Gameworld dashboard.
-- Writes player names only, no IP addresses.
local path = core.get_worldpath() .. "/gameworld_players.txt"

local function write()
  local names = {}
  for _, player in ipairs(core.get_connected_players()) do
    names[#names + 1] = player:get_player_name()
  end
  table.sort(names)
  core.safe_file_write(path, table.concat(names, "\\n"))
end

-- after(0): in the leave callback the leaving player is still in the list.
core.register_on_joinplayer(function() core.after(0, write) end)
core.register_on_leaveplayer(function() core.after(0, write) end)
core.register_on_mods_loaded(function() core.after(0, write) end)
"""

MOD_CONF = f"""\
name = {MOD_NAME}
description = Meldet verbundene Spieler an das Gameworld-Dashboard
"""

PLAYERS_FILE_NAME = "gameworld_players.txt"
# Path in the container; the ExApp reads it via get_archive (02-04, 02-05).
PLAYERS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{PLAYERS_FILE_NAME}"

# Valid Luanti player names (T-02-23): everything else, also IP-like lines,
# spaces, umlauts or markup, never reaches the dashboard.
PLAYER_NAME = re.compile(r"[A-Za-z0-9_-]{1,20}")
MAX_PLAYERS = 64


def parse_players(content: bytes) -> list[str]:
    """Player names from the status file in file order, without duplicates.

    Invalid UTF-8 does not abort (replacement characters fall through the filter).
    At most MAX_PLAYERS names; the provisioner has already truncated the content.
    """
    names: list[str] = []
    for line in content.decode("utf-8", "replace").splitlines():
        if PLAYER_NAME.fullmatch(line) and line not in names:
            names.append(line)
            if len(names) == MAX_PLAYERS:
                break
    return names
