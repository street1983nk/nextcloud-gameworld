"""Der Welt-Mod gameworld_access und die Zugangsdatei, als Konstanten im Code.

Die Durchsetzung "nur Eingeladene" sitzt im Spielserver (ZUGANG-03): Der Mod
liest bei jedem Join-Versuch und alle 5 s die Datei ``gameworld_access.txt`` im
Weltordner, die nur die ExApp per ``put_archive`` schreibt (root, 0444).

Format der Zugangsdatei (ASCII, Zeilen sortiert, deterministisch)::

    gameworld-access 1 <Generation>
    <Spielername> #1#<Salz>#<Verifier>
    end

Der Mod lehnt nicht eingeladene Namen im Prejoin ab, also vor der
Authentifizierung, und setzt für eingeladene Namen im selben Callback den
SRP-Verifier per ``core.set_player_password``. Fehlt die Datei oder fehlen Kopf
oder Schlusszeile (halb geschrieben), bleibt der zuletzt gültige Stand; beim
Serverstart ohne gültige Datei darf niemand hinein. Nach erfolgreichem Laden
schreibt der Mod die Generation nach ``gameworld_access_state.txt``.

Fünf falsche Passwörter sperren einen Namen für zehn Minuten (nur im Speicher).
Spieler, deren Einladung endet, trennt der Mod im 5-s-Takt. Der Mod schreibt
nie IP-Adressen und braucht weder ``secure.trusted_mods`` noch
``secure.http_mods``. Der Lua-Quelltext bleibt reines ASCII: Die Texte an die
Kinder stehen hier als Python-Konstanten mit Umlauten und gehen als
Lua-Dezimal-Escapes (UTF-8-Bytes) in den Mod.
"""

from __future__ import annotations

import re

from gameworld.provisioner.spec import DATA_DIR
from gameworld.provisioner.status_mod import PLAYER_NAME

MOD_NAME = "gameworld_access"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

ACCESS_FILE_NAME = "gameworld_access.txt"
STATE_FILE_NAME = "gameworld_access_state.txt"
# Pfade im Container; die ExApp schreibt ACCESS_FILE und liest STATE_FILE (03-05).
ACCESS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{ACCESS_FILE_NAME}"
STATE_FILE = f"{DATA_DIR}/.minetest/worlds/world/{STATE_FILE_NAME}"
ACCESS_HEADER = "gameworld-access 1"

# Texte an die Kinder (Luanti zeigt sie beim abgelehnten Join oder beim Trennen).
TEXT_DENY = "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
TEXT_KICK = "Deine Einladung für diese Welt wurde beendet."
TEXT_LOCKED = "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen."
TEXT_CASE_HINT = "Achte auf Groß- und Kleinschreibung: "

VERIFIER = re.compile(r"#1#[A-Za-z0-9+/=]+#[A-Za-z0-9+/=]+")


def _lua_string(text: str) -> str:
    """Lua-Stringliteral in reinem ASCII; Nicht-ASCII als Dezimal-Escapes der UTF-8-Bytes."""
    parts: list[str] = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if byte >= 0x80 or char in '"\\' or byte < 0x20:
            parts.append(f"\\{byte:03d}")
        else:
            parts.append(char)
    return '"' + "".join(parts) + '"'


MOD_INIT_LUA = f"""\
-- gameworld_access: Nur Eingeladene betreten diese Welt.
-- Die Zugangsdatei schreibt nur Gameworld. Der Mod schreibt keine IP-Adressen.
local world = core.get_worldpath()
local access_path = world .. "/{ACCESS_FILE_NAME}"
local state_path = world .. "/{STATE_FILE_NAME}"
local DENY = {_lua_string(TEXT_DENY)}
local KICK = {_lua_string(TEXT_KICK)}
local LOCKED = {_lua_string(TEXT_LOCKED)}
local CASE_HINT = {_lua_string(TEXT_CASE_HINT)}
local FAIL_LIMIT = 5
local LOCK_SECONDS = 600
local TICK_SECONDS = 5

local allowed, last = {{}}, nil

local function now()
  return core.get_us_time() / 1e6
end

-- Fehlt die Datei oder ist sie nicht komplett (etwa mitten im Schreiben),
-- bleibt der alte Stand. Beim Start ist der alte Stand: niemand.
local function load()
  local f = io.open(access_path, "rb")
  if not f then return end
  local content = f:read("*a")
  f:close()
  if not content or content == last then return end
  local lines = content:split("\\n")
  local generation = (lines[1] or ""):match("^gameworld%-access 1 (%d+)$")
  if not generation or lines[#lines] ~= "end" then return end
  local new = {{}}
  for i = 2, #lines - 1 do
    local name, hash = lines[i]:match("^([%w_%-]+) (#1#[%w%+/=]+#[%w%+/=]+)$")
    if name and #name <= 20 then new[name] = hash end
  end
  allowed, last = new, content
  core.safe_file_write(state_path, generation)
end

local function case_variant(name)
  local lower = name:lower()
  for allowed_name in pairs(allowed) do
    if allowed_name:lower() == lower then return allowed_name end
  end
end

-- Sperre nach Fehlversuchen, nur im Speicher.
local fails = {{}}

local function locked(name)
  local f = fails[name]
  if not f or not f.until_t then return false end
  if now() < f.until_t then return true end
  fails[name] = nil
  return false
end

core.register_on_authplayer(function(name, _ip, ok)
  if ok then
    fails[name] = nil
    return
  end
  local t = now()
  local f = fails[name]
  if not f or t - f.t > LOCK_SECONDS then f = {{ n = 0, t = t }} end
  f.n = f.n + 1
  if f.n >= FAIL_LIMIT then f.until_t = t + LOCK_SECONDS end
  fails[name] = f
end)

core.register_on_prejoinplayer(function(name)
  if locked(name) then return LOCKED end
  load()
  local hash = allowed[name]
  if not hash then
    local variant = case_variant(name)
    if variant then return CASE_HINT .. variant end
    return DENY
  end
  -- Vor der Anmeldung: legt das Konto an oder setzt das Passwort neu.
  local auth = core.get_auth_handler().get_auth(name)
  if not auth or auth.password ~= hash then
    core.set_player_password(name, hash)
  end
end)

local function tick()
  load()
  for _, player in ipairs(core.get_connected_players()) do
    local name = player:get_player_name()
    if not allowed[name] then core.kick_player(name, KICK) end
  end
  core.after(TICK_SECONDS, tick)
end

core.register_on_mods_loaded(function() core.after(0, tick) end)
"""

MOD_CONF = f"""\
name = {MOD_NAME}
description = Nur von Gameworld eingeladene Spieler betreten die Welt
"""


def render_access_file(generation: int, entries: dict[str, str]) -> bytes:
    """Zugangsdatei aus Spielername -> Verifier, sortiert und deterministisch.

    Jeder ungültige Eintrag wirft ValueError, nie wird still übersprungen: Ein
    Zeilenumbruch im Namen oder Verifier könnte sonst fremde Zeilen einschleusen.
    """
    if generation < 0:
        raise ValueError("Die Generation der Zugangsliste darf nicht negativ sein.")
    lines = [f"{ACCESS_HEADER} {generation}"]
    for name, verifier in sorted(entries.items()):
        if not (PLAYER_NAME.fullmatch(name) and VERIFIER.fullmatch(verifier)):
            raise ValueError("Ungültiger Zugangseintrag: Spielername oder Verifier hat nicht die erwartete Form.")
        lines.append(f"{name} {verifier}")
    lines.append("end")
    return ("\n".join(lines) + "\n").encode("ascii")
