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
Spieler, deren Einladung endet, trennt der Mod im 5-s-Takt per
``core.disconnect_player`` (ohne "Kicked: " vor dem Text). Ein Eingeladener,
der unter seinem Namen noch verbunden ist oder vor weniger als 2 s gegangen
ist, wird im Prejoin mit einem Wartetext abgelehnt (Wiederbeitritts-Sperre
gegen den Rejoin-Absturz von Luanti 5.17.0, 04-RESEARCH.md Pitfall 1). Der Mod schreibt
nie IP-Adressen und braucht weder ``secure.trusted_mods`` noch
``secure.http_mods``. Der Lua-Quelltext bleibt reines ASCII: Die Texte an die
Kinder stehen hier als Python-Konstanten mit Umlauten und gehen als
Lua-Dezimal-Escapes (UTF-8-Bytes) in den Mod.

Seit Phase 4.1 schreibt der Mod zusätzlich die Ereignisdatei
``gameworld_events.txt`` (uid 30000, per ``core.safe_file_write`` atomar), den
einzigen Weg von der Welt zur ExApp (04.1-RESEARCH.md Pattern 1, kein neuer
Port)::

    gameworld-events 1 <letzte Sequenz>
    <Sequenz> <Epoch> <Art> <Spielername>
    end

Arten: ``deny`` (fremder Name, nur im Zweig vor dem Ablehnungstext, nie bei
Groß/Klein-Variante, Sperre oder Wartezeit; gedrosselt auf ein ``deny`` je Name
und Minute und 30 je Minute), ``join``, ``leave`` und ``warn10`` (vom Zeit-Mod
über die globale Tabelle ``gameworld_access.event``). Höchstens 200
Ereigniszeilen, die ältesten fallen heraus; die Sequenz läuft über Neustarts
weiter, weil der Mod die alte Datei beim Start einliest. Beim Laden schreibt er
die Datei sofort einmal: Das zeigt der ExApp, dass der laufende Mod Ereignisse
und Pause kann (Pattern 3). Die Datei enthält nur Sequenz, Epoch, Art und Name,
nie IP-Adressen oder Passwörter.
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
# Pfade im Container; die ExApp schreibt ACCESS_FILE und liest STATE_FILE (03-05).
ACCESS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{ACCESS_FILE_NAME}"
STATE_FILE = f"{DATA_DIR}/.minetest/worlds/world/{STATE_FILE_NAME}"
ACCESS_HEADER = "gameworld-access 1"
# Ereignisdatei (Phase 4.1): schreibt nur der Mod, die ExApp liest sie im Takt.
EVENTS_FILE_NAME = "gameworld_events.txt"
EVENTS_FILE = f"{DATA_DIR}/.minetest/worlds/world/{EVENTS_FILE_NAME}"
EVENTS_HEADER = "gameworld-events 1"
EVENTS_MAX_LINES = 200
EVENT_KINDS = frozenset({"deny", "join", "leave", "warn10"})
# Drossel gegen deny-Flut (T-04.1-01), nur im Speicher des Mods.
DENY_PER_NAME_SECONDS = 60
DENY_PER_MINUTE = 30

# Texte an die Kinder (Luanti zeigt sie beim abgelehnten Join oder beim Trennen).
TEXT_DENY = "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
TEXT_KICK = "Deine Einladung für diese Welt wurde beendet."
TEXT_LOCKED = "Zu viele falsche Passwörter. Bitte in 10 Minuten nochmal versuchen."
# Ohne den eingeladenen Namen (IN-07): Wer den UDP-Port erreicht, erführe sonst die
# genaue Schreibweise des Spielernamens eines eingeladenen Kindes.
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
    """Lua-Stringliteral in reinem ASCII; Nicht-ASCII als Dezimal-Escapes der UTF-8-Bytes."""
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
-- gameworld_access: Nur Eingeladene betreten diese Welt.
-- Die Zugangsdatei schreibt nur Gameworld. Der Mod schreibt keine IP-Adressen.
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
-- Wiederbeitritts-Sperre: Ein Join unter demselben Namen binnen weniger als
-- 0,5 s nach dem Verlassen bringt Luanti 5.17.0 zum Absturz (on_joinplayer der
-- Spiele bekommt nil, 04-RESEARCH.md Pitfall 1). 2 s Abstand verhindern das.
local COOLDOWN = 2
local EVENTS_MAX = {EVENTS_MAX_LINES}
local DENY_NAME_SECONDS = {DENY_PER_NAME_SECONDS}
local DENY_PER_MINUTE = {DENY_PER_MINUTE}
local KINDS = {{ {_KINDS_LUA} }}

local allowed, last = {{}}, nil

local function now()
  return core.get_us_time() / 1e6
end

-- Ereignisdatei: Ringpuffer mit fortlaufender Sequenz, neustartfest im Weltordner.
-- Nur Sequenz, Epoch (os.time), Art und Name; keine IP-Adressen, keine Passwoerter.
local seq, event_lines = 0, {{}}
do
  local f = io.open(events_path, "rb")
  if f then
    local content = f:read("*a") or ""
    f:close()
    local lines = content:split("\\n")
    local head = (lines[1] or ""):match("^gameworld%-events 1 (%d+)$")
    if head then
      -- Kaputte Datei ohne Schlusszeile: keine Zeilen, aber die Sequenz laeuft weiter.
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

-- Drossel fuer deny: je Name eins pro DENY_NAME_SECONDS, insgesamt DENY_PER_MINUTE
-- je gleitender Minute. Beide Tabellen bleiben klein (nur gemeldete Versuche).
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

-- Nur ob es eine andere Schreibweise gibt; der Name selbst geht nie an den Client (IN-07).
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

-- Zeitpunkt des Verlassens je Name (nur im Speicher, nur Eingeladene).
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
    -- Nur ein fremder Name wird gemeldet (D-10, D-29), gedrosselt.
    if deny_allowed(name) then event("deny", name) end
    return DENY
  end
  -- Noch verbunden oder gerade erst gegangen: kurz warten lassen.
  if too_soon(name) then return WAIT end
  -- Vor der Anmeldung: legt das Konto an oder setzt das Passwort neu.
  local auth = core.get_auth_handler().get_auth(name)
  if not auth or auth.password ~= hash then
    core.set_player_password(name, hash)
  end
end)

-- builtin/game/auth.lua prueft vor allen Mods, ob es den Namen in anderer Schreibweise
-- schon gibt, und nennt dann den registrierten Namen (IN-07). Diese Pruefung laeuft
-- deshalb zuerst: Von mehreren Ablehnungen gilt die erste (RUN_CALLBACKS_MODE_OR).
do
  local callbacks = core.registered_on_prejoinplayers
  table.insert(callbacks, 1, table.remove(callbacks))
end

local function tick()
  load()
  for _, player in ipairs(core.get_connected_players()) do
    local name = player:get_player_name()
    -- disconnect_player: kein "Kicked: " vor dem Kindertext.
    if not allowed[name] then core.disconnect_player(name, KICK) end
  end
  core.after(TICK_SECONDS, tick)
end

-- Einmal beim Start schreiben: Merker fuer die ExApp, dass dieser Mod Ereignisse kann.
core.register_on_mods_loaded(function()
  write_events()
  core.after(0, tick)
end)

-- Luanti-Konvention: Global mit Modnamen; gameworld_time meldet darueber warn10.
gameworld_access = {{ event = event }}
"""


MOD_INIT_LUA = mod_init_lua("de")

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
