"""The world mod gameworld_access and the access file, as constants in the code.

The enforcement "invited only" sits in the game server (ZUGANG-03): the mod
reads the file ``gameworld_access.txt`` in the world folder on every join attempt and every 5 s,
which only the ExApp writes via ``put_archive`` (root, 0444).

Format of the access file (ASCII, lines sorted, deterministic)::

    gameworld-access 1 <generation>
    <player name> #1#<salt>#<verifier>
    end

The mod rejects names that are not invited in the prejoin, i.e. before
authentication, and for invited names sets the
SRP verifier in the same callback via ``core.set_player_password``. If the file is missing or head
or closing line are missing (half written), the last valid state stays; on
server start without a valid file nobody gets in. After a successful load
the mod writes the generation to ``gameworld_access_state.txt``.

Five wrong passwords block a name for ten minutes (in memory only).
Players whose invitation ends are disconnected by the mod in the 5 s tick via
``core.disconnect_player`` (without "Kicked: " before the text). An invitee
who is still connected under his name or left less than 2 s ago
is rejected in the prejoin with a waiting text (rejoin block
against the rejoin crash of Luanti 5.17.0, 04-RESEARCH.md pitfall 1). The mod writes
no IP addresses and needs neither ``secure.trusted_mods`` nor
``secure.http_mods``. The Lua source stays pure ASCII: the texts for the
children are here as Python constants with umlauts and go into the mod as
Lua decimal escapes (UTF-8 bytes).

Since phase 4.1 the mod additionally writes the event file
``gameworld_events.txt`` (uid 30000, atomic via ``core.safe_file_write``), the
only way from the world to the ExApp (04.1-RESEARCH.md pattern 1, no new
port)::

    gameworld-events 1 <last sequence>
    <sequence> <epoch> <kind> <player name>
    end

Kinds: ``deny`` (foreign name, only in the branch before the rejection text, never for a
case variant, block or waiting time; throttled to one ``deny`` per name
and minute and 30 per minute), ``join``, ``leave`` and ``warn10`` (from the time mod
via the global table ``gameworld_access.event``). At most 200
event lines, the oldest drop out; the sequence continues across restarts,
because the mod reads in the old file at start. On loading it writes
the file once immediately: that shows the ExApp that the running mod can do events
and pause (pattern 3). The file contains only sequence, epoch, kind and name,
never IP addresses or passwords.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from gameworld.provisioner.spec import DATA_DIR
from gameworld.provisioner.status_mod import PLAYER_NAME

MOD_NAME = "gameworld_access"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

ACCESS_FILE_NAME = "gameworld_access.txt"
STATE_FILE_NAME = "gameworld_access_state.txt"
# Paths in the container; the ExApp writes ACCESS_FILE and reads STATE_FILE (03-05).
ACCESS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{ACCESS_FILE_NAME}"
STATE_FILE = f"{DATA_DIR}/.minetest/worlds/world/{STATE_FILE_NAME}"
ACCESS_HEADER = "gameworld-access 1"
# Event file (phase 4.1): only the mod writes it, the ExApp reads it in the tick.
EVENTS_FILE_NAME = "gameworld_events.txt"
EVENTS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{EVENTS_FILE_NAME}"
EVENTS_HEADER = "gameworld-events 1"
EVENTS_MAX_LINES = 200
EVENT_KINDS = frozenset({"deny", "join", "leave", "warn10"})
# Throttle against a deny flood (T-04.1-01), in the mod's memory only.
DENY_PER_NAME_SECONDS = 60
DENY_PER_MINUTE = 30

# Texts for the children (Luanti shows them on a rejected join or on disconnect).
TEXT_DENY = "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
TEXT_KICK = "Deine Einladung für diese Welt wurde beendet."
TEXT_LOCKED = "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen."
# Without the invited name (IN-07): whoever reaches the UDP port would otherwise learn the
# exact spelling of an invited child's player name.
TEXT_CASE_HINT = "Achte auf Groß- und Kleinschreibung bei deinem Spielernamen."
TEXT_WAIT = "Bitte einen Moment warten und dann nochmal beitreten."


class ModTexts(NamedTuple):
    """Texts of gameworld_access in one world language (refused join or disconnect)."""

    deny: str
    kick: str
    locked: str
    case_hint: str
    wait: str


# World language (D-27): the Lua code is the same in every language, only these literals change.
# German is the source language and stays byte-identical (golden test in tests/test_mod_texts.py).
MOD_TEXTS: dict[str, ModTexts] = {
    "de": ModTexts(TEXT_DENY, TEXT_KICK, TEXT_LOCKED, TEXT_CASE_HINT, TEXT_WAIT),
    "en": ModTexts(
        deny="You are not invited to this world. Ask your parents.",
        kick="Your invitation to this world has ended.",
        locked="Too many wrong passwords. Please try again in 10 minutes.",
        case_hint="Check the capital and small letters in your player name.",
        wait="Please wait a moment and then join again.",
    ),
    "fr": ModTexts(
        deny="Tu n\u2019as pas d\u2019invitation pour ce monde. Demande à tes parents.",
        kick="Ton invitation pour ce monde est terminée.",
        locked="Trop de mots de passe faux. Réessaie dans 10 minutes.",
        case_hint="Fais attention aux majuscules et aux minuscules de ton nom de joueur.",
        wait="Attends un instant, puis reviens dans le monde.",
    ),
}

VERIFIER = re.compile(r"#1#[A-Za-z0-9+/=]+#[A-Za-z0-9+/=]+")


def _lua_string(text: str) -> str:
    """Lua string literal in pure ASCII; non-ASCII as decimal escapes of the UTF-8 bytes."""
    parts: list[str] = []
    for byte in text.encode("utf-8"):
        char = chr(byte)
        if byte >= 0x80 or char in '"\\' or byte < 0x20:
            parts.append(f"\\{byte:03d}")
        else:
            parts.append(char)
    return '"' + "".join(parts) + '"'


def mod_texts(language: object) -> ModTexts:
    """Text bundle of ``language``; anything unsupported (value from the database) gives German."""
    if isinstance(language, str) and language in MOD_TEXTS:
        return MOD_TEXTS[language]
    return MOD_TEXTS["de"]


_KINDS_LUA = ", ".join(f"{kind} = true" for kind in sorted(EVENT_KINDS))


def mod_init_lua(language: object = "de") -> str:
    """init.lua of gameworld_access; only the text literals depend on ``language`` (T-06-85).

    The value never reaches the Lua source itself, it only selects a fixed bundle.
    """
    texts = mod_texts(language)
    return f"""\
-- gameworld_access: only invitees enter this world.
-- Only Gameworld writes the access file. The mod writes no IP addresses.
local world = core.get_worldpath()
local access_path = world .. "/{ACCESS_FILE_NAME}"
local state_path = world .. "/{STATE_FILE_NAME}"
local events_path = world .. "/{EVENTS_FILE_NAME}"
local DENY = {_lua_string(texts.deny)}
local KICK = {_lua_string(texts.kick)}
local LOCKED = {_lua_string(texts.locked)}
local CASE_HINT = {_lua_string(texts.case_hint)}
local WAIT = {_lua_string(texts.wait)}
local FAIL_LIMIT = 5
local LOCK_SECONDS = 600
local TICK_SECONDS = 5
-- Rejoin block: a join under the same name within less than
-- 0.5 s after leaving crashes Luanti 5.17.0 (the games' on_joinplayer
-- gets nil, 04-RESEARCH.md pitfall 1). A gap of 2 s prevents that.
local COOLDOWN = 2
local EVENTS_MAX = {EVENTS_MAX_LINES}
local DENY_NAME_SECONDS = {DENY_PER_NAME_SECONDS}
local DENY_PER_MINUTE = {DENY_PER_MINUTE}
local KINDS = {{ {_KINDS_LUA} }}

local allowed, last = {{}}, nil

local function now()
  return core.get_us_time() / 1e6
end

-- Event file: ring buffer with a running sequence, restart-proof in the world folder.
-- Only sequence, epoch (os.time), kind and name; no IP addresses, no passwords.
local seq, event_lines = 0, {{}}
do
  local f = io.open(events_path, "rb")
  if f then
    local content = f:read("*a") or ""
    f:close()
    local lines = content:split("\\n")
    local head = (lines[1] or ""):match("^gameworld%-events 1 (%d+)$")
    if head then
      -- Broken file without a closing line: no lines, but the sequence keeps running.
      seq = tonumber(head)
      if lines[#lines] == "end" then
        for i = 2, #lines - 1 do
          local s, _, kind, name = lines[i]:match("^(%d+) (%d+) (%l+%d*) ([%w_%-]+)$")
          if s and KINDS[kind] and #name <= 20 and tonumber(s) <= seq then
            event_lines[#event_lines + 1] = lines[i]
          end
        end
      end
    end
  end
end

local function write_events()
  while #event_lines > EVENTS_MAX do table.remove(event_lines, 1) end
  local out = {{ "{EVENTS_HEADER} " .. seq }}
  for _, line in ipairs(event_lines) do out[#out + 1] = line end
  out[#out + 1] = "end"
  core.safe_file_write(events_path, table.concat(out, "\\n") .. "\\n")
end

local function event(kind, name)
  if not KINDS[kind] or type(name) ~= "string" then return end
  if #name > 20 or not name:match("^[%w_%-]+$") then return end
  seq = seq + 1
  event_lines[#event_lines + 1] = seq .. " " .. os.time() .. " " .. kind .. " " .. name
  write_events()
end

-- Throttle for deny: one per name per DENY_NAME_SECONDS, DENY_PER_MINUTE in total
-- per sliding minute. Both tables stay small (reported attempts only).
local deny_last, deny_recent = {{}}, {{}}

local function deny_allowed(name)
  local t = now()
  local keep = {{}}
  for _, at in ipairs(deny_recent) do
    if t - at < 60 then keep[#keep + 1] = at end
  end
  deny_recent = keep
  for other, at in pairs(deny_last) do
    if t - at >= DENY_NAME_SECONDS then deny_last[other] = nil end
  end
  if deny_last[name] or #deny_recent >= DENY_PER_MINUTE then return false end
  deny_last[name] = t
  deny_recent[#deny_recent + 1] = t
  return true
end

-- If the file is missing or not complete (e.g. in the middle of writing),
-- the old state stays. At start the old state is: nobody.
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

-- Only whether another spelling exists; the name itself never goes to the client (IN-07).
local function case_variant(name)
  local lower = name:lower()
  for allowed_name in pairs(allowed) do
    if allowed_name:lower() == lower then return allowed_name end
  end
end

-- Block after failed attempts, in memory only.
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

-- Time of leaving per name (in memory only, invitees only).
local left_at = {{}}

core.register_on_joinplayer(function(player)
  event("join", player:get_player_name())
end)

core.register_on_leaveplayer(function(player)
  local name = player:get_player_name()
  left_at[name] = core.get_us_time()
  event("leave", name)
end)

local function too_soon(name)
  if core.get_player_by_name(name) then return true end
  local t = left_at[name]
  if not t then return false end
  if (core.get_us_time() - t) / 1e6 < COOLDOWN then return true end
  left_at[name] = nil
  return false
end

core.register_on_prejoinplayer(function(name)
  if locked(name) then return LOCKED end
  load()
  local hash = allowed[name]
  if not hash then
    local variant = case_variant(name)
    if variant then return CASE_HINT end
    -- Only a foreign name is reported (D-10, D-29), throttled.
    if deny_allowed(name) then event("deny", name) end
    return DENY
  end
  -- Still connected or just left: make them wait briefly.
  if too_soon(name) then return WAIT end
  -- Before login: creates the account or sets the password anew.
  local auth = core.get_auth_handler().get_auth(name)
  if not auth or auth.password ~= hash then
    core.set_player_password(name, hash)
  end
end)

-- builtin/game/auth.lua checks before all mods whether the name already exists in another spelling
-- and then names the registered name (IN-07). This check therefore runs first:
-- of several rejections the first one counts (RUN_CALLBACKS_MODE_OR).
do
  local callbacks = core.registered_on_prejoinplayers
  table.insert(callbacks, 1, table.remove(callbacks))
end

local function tick()
  load()
  for _, player in ipairs(core.get_connected_players()) do
    local name = player:get_player_name()
    -- disconnect_player: no "Kicked: " before the child text.
    if not allowed[name] then core.disconnect_player(name, KICK) end
  end
  core.after(TICK_SECONDS, tick)
end

-- Write once at start: marker for the ExApp that this mod can do events.
core.register_on_mods_loaded(function()
  write_events()
  core.after(0, tick)
end)

-- Luanti convention: global with the mod name; gameworld_time reports warn10 through it.
gameworld_access = {{ event = event }}
"""


MOD_INIT_LUA = mod_init_lua("de")

MOD_CONF = f"""\
name = {MOD_NAME}
description = Nur von Gameworld eingeladene Spieler betreten die Welt
"""


def render_access_file(generation: int, entries: dict[str, str]) -> bytes:
    """Access file from player name -> verifier, sorted and deterministic.

    Every invalid entry raises ValueError, nothing is silently skipped: a
    line break in the name or verifier could otherwise smuggle in foreign lines.
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
