"""Der Welt-Mod gameworld_status, als Konstanten im Code.

Jede neue Welt bekommt ihn im Payload unter ``worldmods``. Er schreibt beim
Laden der Mods und bei jedem Betreten oder Verlassen die sortierten Namen der
verbundenen Spieler in ``gameworld_players.txt`` im Weltordner. Er schreibt
ausschließlich Spielernamen, keine IP-Adressen. Er braucht weder
``secure.trusted_mods`` noch ``secure.http_mods``: Atomares Schreiben in den
eigenen Weltordner ist auch mit ``secure.enable_security = true`` erlaubt.
"""

from __future__ import annotations

import re

from gameworld.provisioner.spec import DATA_DIR

MOD_NAME = "gameworld_status"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

MOD_INIT_LUA = """\
-- gameworld_status: meldet die verbundenen Spieler an das Gameworld-Dashboard.
-- Schreibt nur Spielernamen, keine IP-Adressen.
local path = core.get_worldpath() .. "/gameworld_players.txt"

local function write()
  local names = {}
  for _, player in ipairs(core.get_connected_players()) do
    names[#names + 1] = player:get_player_name()
  end
  table.sort(names)
  core.safe_file_write(path, table.concat(names, "\\n"))
end

-- after(0): Im Leave-Callback ist der gehende Spieler noch in der Liste.
core.register_on_joinplayer(function() core.after(0, write) end)
core.register_on_leaveplayer(function() core.after(0, write) end)
core.register_on_mods_loaded(function() core.after(0, write) end)
"""

MOD_CONF = f"""\
name = {MOD_NAME}
description = Meldet verbundene Spieler an das Gameworld-Dashboard
"""

PLAYERS_FILE_NAME = "gameworld_players.txt"
# Pfad im Container; die ExApp liest ihn per get_archive (02-04, 02-05).
PLAYERS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{PLAYERS_FILE_NAME}"

# Gültige Luanti-Spielernamen (T-02-23): Alles andere, auch IP-artige Zeilen,
# Leerzeichen, Umlaute oder Markup, erreicht das Dashboard nie.
PLAYER_NAME = re.compile(r"[A-Za-z0-9_-]{1,20}")
MAX_PLAYERS = 64


def parse_players(content: bytes) -> list[str]:
    """Spielernamen aus der Status-Datei in Dateireihenfolge, ohne Duplikate.

    Ungültiges UTF-8 bricht nicht ab (Ersatzzeichen fallen durch den Filter).
    Höchstens MAX_PLAYERS Namen; den Inhalt hat der Provisioner schon gekappt.
    """
    names: list[str] = []
    for line in content.decode("utf-8", "replace").splitlines():
        if PLAYER_NAME.fullmatch(line) and line not in names:
            names.append(line)
            if len(names) == MAX_PLAYERS:
                break
    return names
