"""Der Welt-Mod gameworld_time, die Regeldatei und das Zählbuch, als Konstanten im Code.

Die Spielzeit setzt der Spielserver durch (ZEIT-02, Owner-Entscheid O-01): Der
Mod liest bei jedem Join-Versuch und alle 5 s die Regeldatei
``gameworld_time.txt`` im Weltordner, die nur die ExApp per ``put_archive``
schreibt (root, 0444). Er zählt die Online-Zeit je Spieler in einem eigenen
Zählbuch ``gameworld_time_used.txt`` (uid 30000, per ``core.safe_file_write``),
das im Welt-Volume bleibt und beim Start wieder eingelesen wird. Ein
Welt-Neustart setzt die Zeit deshalb nicht zurück.

Format der Regeldatei (ASCII, Zeilen sortiert, deterministisch)::

    gameworld-time 1 <Generation> <ausgestellt, Epoch>
    welt <from> <until> <grund> <naechste>              (nur mit Welt-Zeitfenster)
    <Spielername> <cap> <from> <until> <grund> <naechste>
    end

``cap`` ist der Zählbuch-Stand in Sekunden, ab dem der Spieler getrennt wird
(-1 = kein Tageslimit), ``from`` und ``until`` sind absolute Epoch-Sekunden des
erlaubten Fensters (Container laufen in UTC, lokale Zeit rechnet nur die
ExApp). ``grund`` ist ok, tag, fenster, limit oder frei (Verwalter: Welt-Fenster
und eigene Grenzen gelten nicht, Zeile ``-1 -1 -1 frei -``); die Welt-Zeile
kennt ok und welt. ``naechste`` ist ein Token wie ``Sa-10:00`` für den
Kindertext, ``-`` heißt: kein Zusatz.

Format des Zählbuchs (schreibt nur der Mod)::

    gameworld-time-used 1 <os.time beim Schreiben> <geladene Generation>
    <Spielername> <Sekunden gesamt>
    end

Fehlt die Regeldatei, gibt es keine Regeln. Fehlen Kopf oder Schlusszeile (halb
geschrieben), bleibt der zuletzt gültige Stand; liegt beim Start nur eine
ungültige Datei vor, kommt niemand hinein (fail closed, O-04). Vorwarnung per
Chat bei 10, 5 und 1 Minute Rest (O-06), AFK zählt als Spielzeit (O-09). Der
Mod schreibt keine IP-Adressen und keine Sitzungszeitpunkte; der Lua-Quelltext
bleibt reines ASCII, die Kindertexte gehen als Lua-Dezimal-Escapes hinein.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gameworld.provisioner.access_mod import MOD_NAME as ACCESS_MOD_NAME
from gameworld.provisioner.access_mod import _lua_string  # pyright: ignore[reportPrivateUsage]
from gameworld.provisioner.spec import DATA_DIR
from gameworld.provisioner.status_mod import PLAYER_NAME

MOD_NAME = "gameworld_time"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

RULES_FILE_NAME = "gameworld_time.txt"
LEDGER_FILE_NAME = "gameworld_time_used.txt"
# Pfade im Container; die ExApp schreibt RULES_FILE und liest LEDGER_FILE.
RULES_FILE = f"{DATA_DIR}/.minetest/worlds/world/{RULES_FILE_NAME}"
LEDGER_FILE = f"{DATA_DIR}/.minetest/worlds/world/{LEDGER_FILE_NAME}"
TIME_HEADER = "gameworld-time 1"
LEDGER_HEADER = "gameworld-time-used 1"

REASONS = frozenset({"ok", "tag", "fenster", "limit", "frei"})
WORLD_REASONS = frozenset({"ok", "welt"})
# Namen der Schlüsselzeilen; ein Spieler darf nicht so heißen (case-insensitiv).
RESERVED_NAMES = frozenset({"welt", "end"})
TOKEN = re.compile(r"[A-Za-z0-9:-]{1,16}")
# Höchstwert einer Zählbuch-Zeile; alles darüber ist kaputt oder fremd.
LEDGER_MAX_SECONDS = 10**9

_LEDGER_HEAD = re.compile(r"gameworld-time-used 1 ([0-9]+) ([0-9]+)")
_LEDGER_LINE = re.compile(r"(\S+) ([0-9]+)")

# Texte an die Kinder (beim abgelehnten Join, beim Trennen, als Chat-Vorwarnung).
TEXT_LIMIT = "Deine Spielzeit für heute ist aufgebraucht."
TEXT_FENSTER = "Gerade ist keine Spielzeit."
TEXT_TAG = "Heute ist kein Spieltag."
TEXT_WELT = "Diese Welt ist gerade geschlossen."
TEXT_NEXT = " Nächste Spielzeit: "
TEXT_WELT_NEXT = " Sie öffnet "
TEXT_START = "Gameworld startet gleich. Bitte gleich nochmal versuchen."
TEXT_WARN_10 = "Noch 10 Minuten Spielzeit. Denk ans Speichern und Verabschieden."
TEXT_WARN_5 = "Noch 5 Minuten."
TEXT_WARN_1 = "Noch 1 Minute."
TEXTS = (
    TEXT_LIMIT,
    TEXT_FENSTER,
    TEXT_TAG,
    TEXT_WELT,
    TEXT_NEXT,
    TEXT_WELT_NEXT,
    TEXT_START,
    TEXT_WARN_10,
    TEXT_WARN_5,
    TEXT_WARN_1,
)


MOD_INIT_LUA = f"""\
-- gameworld_time: Spielzeiten und Zeitfenster von Gameworld durchsetzen.
-- Die Regeldatei schreibt nur Gameworld. Der Mod zaehlt die Online-Zeit je
-- Spieler im Zaehlbuch, das im Welt-Volume bleibt und Neustarts ueberlebt.
-- Alle Grenzen sind absolute Epoch-Sekunden (os.time), nie lokale Uhrzeit.
-- Keine IP-Adressen, keine Sitzungszeitpunkte.
local world = core.get_worldpath()
local rules_path = world .. "/{RULES_FILE_NAME}"
local ledger_path = world .. "/{LEDGER_FILE_NAME}"
local TICK = 5
local MIN_LEFT = 60
local WARN = {{ 600, 300, 60 }}
local WARN_TEXT = {{
  [600] = {_lua_string(TEXT_WARN_10)},
  [300] = {_lua_string(TEXT_WARN_5)},
  [60] = {_lua_string(TEXT_WARN_1)},
}}
local TEXT = {{
  limit = {_lua_string(TEXT_LIMIT)},
  fenster = {_lua_string(TEXT_FENSTER)},
  tag = {_lua_string(TEXT_TAG)},
  welt = {_lua_string(TEXT_WELT)},
  start = {_lua_string(TEXT_START)},
}}
local NEXT = {_lua_string(TEXT_NEXT)}
local WELT_NEXT = {_lua_string(TEXT_WELT_NEXT)}

-- valid: nil = noch nie geladen, "missing" = keine Datei (keine Regeln),
-- "broken" = beim Start nur eine ungueltige Datei (alle zu), "ok" = Regeln da.
local rules, world_rule, last, valid, generation = {{}}, nil, nil, nil, 0
local used = {{}}    -- Sekunden je Name, monoton ueber alle Neustarts
local since = {{}}   -- get_us_time, bis zu dem die Zeit gutgeschrieben ist
local warned = {{}}  -- je Name die schon gesendeten Vorwarnungen dieser Sitzung

local function now()
  return os.time()
end

-- Zaehlbuch vom letzten Lauf uebernehmen (nur mit Kopf und Schlusszeile).
do
  local f = io.open(ledger_path, "rb")
  if f then
    local content = f:read("*a") or ""
    f:close()
    local lines = content:split("\\n")
    if (lines[1] or ""):match("^gameworld%-time%-used 1 %d+ %d+$") and lines[#lines] == "end" then
      for i = 2, #lines - 1 do
        local name, secs = lines[i]:match("^([%w_%-]+) (%d+)$")
        if name and #name <= 20 then used[name] = tonumber(secs) end
      end
    end
  end
end

local function write_ledger()
  local out = {{ "gameworld-time-used 1 " .. now() .. " " .. generation }}
  local names = {{}}
  for name in pairs(used) do names[#names + 1] = name end
  table.sort(names)
  for _, name in ipairs(names) do out[#out + 1] = name .. " " .. math.floor(used[name]) end
  out[#out + 1] = "end"
  core.safe_file_write(ledger_path, table.concat(out, "\\n") .. "\\n")
end

local function load()
  local f = io.open(rules_path, "rb")
  if not f then
    if valid == nil then valid = "missing" end
    return
  end
  local content = f:read("*a")
  f:close()
  if not content or content == last then return end
  local lines = content:split("\\n")
  local gen = (lines[1] or ""):match("^gameworld%-time 1 (%d+) %d+$")
  if not gen or lines[#lines] ~= "end" then
    if valid == nil then valid = "broken" end
    return
  end
  local new, new_world = {{}}, nil
  for i = 2, #lines - 1 do
    local wf, wu, wr, wn = lines[i]:match("^welt (%-?%d+) (%-?%d+) (%a+) ([%w:%-]+)$")
    if wf then
      new_world = {{ from = tonumber(wf), until_t = tonumber(wu), reason = wr, next = wn }}
    else
      local name, cap, from, until_t, reason, nxt =
        lines[i]:match("^([%w_%-]+) (%-?%d+) (%-?%d+) (%-?%d+) (%a+) ([%w:%-]+)$")
      if name and #name <= 20 then
        new[name] = {{ cap = tonumber(cap), from = tonumber(from), until_t = tonumber(until_t),
                      reason = reason, next = nxt }}
      end
    end
  end
  rules, world_rule, last, valid, generation = new, new_world, content, "ok", tonumber(gen)
end

-- Restzeit in Sekunden, Grund und Token der naechsten Spielzeit; nil = unbegrenzt.
local function left(name)
  if valid == "broken" then return 0, "start", "-" end
  local t = now()
  local r = rules[name]
  if r and r.reason == "frei" then return nil end
  local best, why, nxt = nil, nil, "-"
  if world_rule then
    if t < world_rule.from or t >= world_rule.until_t then return 0, "welt", world_rule.next end
    best, why, nxt = world_rule.until_t - t, "welt", world_rule.next
  end
  if r then
    if r.reason == "tag" then return 0, "tag", r.next end
    local closed = r.reason == "limit" and "limit" or "fenster"
    if t < r.from or t >= r.until_t then return 0, closed, r.next end
    local w = r.until_t - t
    if not best or w < best then best, why, nxt = w, closed, r.next end
    if r.cap >= 0 then
      local rest = r.cap - (used[name] or 0)
      if rest < best then best, why, nxt = rest, "limit", r.next end
    end
  end
  return best, why, nxt
end

local function text(why, nxt)
  local s = TEXT[why] or TEXT.fenster
  if why ~= "start" and nxt and nxt ~= "-" then
    local hint = (nxt:gsub("%-", " "))
    if why == "welt" then s = s .. WELT_NEXT .. hint else s = s .. NEXT .. hint end
  end
  return s
end

-- Nur die kleinste gerade unterschrittene Schwelle senden, alle groesseren
-- gelten dann als gesendet (Beitritt mit 4 min Rest: nur "Noch 5 Minuten.").
local function warn(name, l)
  local marks = warned[name]
  if not marks then
    marks = {{}}
    warned[name] = marks
  end
  local hit = nil
  for _, w in ipairs(WARN) do
    if l <= w then hit = w elseif marks[w] then marks[w] = nil end
  end
  if hit and not marks[hit] then
    core.chat_send_player(name, WARN_TEXT[hit])
    for _, w in ipairs(WARN) do
      if w >= hit then marks[w] = true end
    end
  end
end

-- Gutschrift ab Beitritt bzw. letztem Takt, nie pauschal je Takt.
local function credit(name, now_us)
  local t = since[name]
  if not t then return end
  local dt = (now_us - t) / 1e6
  if dt > 0 then used[name] = (used[name] or 0) + dt end
  since[name] = now_us
end

core.register_on_prejoinplayer(function(name)
  load()
  local l, why, nxt = left(name)
  if l and l < MIN_LEFT then return text(why, nxt) end
end)

core.register_on_joinplayer(function(player)
  since[player:get_player_name()] = core.get_us_time()
end)

core.register_on_leaveplayer(function(player)
  local name = player:get_player_name()
  credit(name, core.get_us_time())
  since[name] = nil
  warned[name] = nil
  write_ledger()
end)

local function tick()
  load()
  local now_us = core.get_us_time()
  local players = core.get_connected_players()
  for _, player in ipairs(players) do
    local name = player:get_player_name()
    if since[name] then credit(name, now_us) else since[name] = now_us end
    local l, why, nxt = left(name)
    if l then
      if l <= 0 then
        core.disconnect_player(name, text(why, nxt))
      else
        warn(name, l)
      end
    end
  end
  if #players > 0 then write_ledger() end
  core.after(TICK, tick)
end

core.register_on_shutdown(function()
  local now_us = core.get_us_time()
  for name in pairs(since) do credit(name, now_us) end
  write_ledger()
end)

-- Einmal beim Start schreiben: Der Kopf zeigt der ExApp, welche Generation geladen ist.
core.register_on_mods_loaded(function()
  load()
  write_ledger()
  core.after(TICK, tick)
end)
"""

MOD_CONF = f"""\
name = {MOD_NAME}
description = Spielzeiten und Zeitfenster von Gameworld durchsetzen
depends = {ACCESS_MOD_NAME}
"""


@dataclass(frozen=True)
class TimeLine:
    """Eine Zeile der Regeldatei; ``cap`` -1 = kein Tageslimit, ``frei``-Zeilen -1 -1 -1."""

    cap: int
    start: int
    until: int
    reason: str
    next_hint: str


@dataclass(frozen=True)
class Ledger:
    """Zählbuch einer Welt: Schreibzeitpunkt (Epoch), geladene Generation, Sekunden je Name."""

    written_at: int
    generation: int
    seconds: dict[str, int]


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_numbers(line: TimeLine, *, frei: bool) -> None:
    if not all(_is_int(value) for value in (line.cap, line.start, line.until)):
        raise ValueError("Ungültige Zahl in der Regeldatei: nur ganze Zahlen.")
    if frei:
        if (line.cap, line.start, line.until) != (-1, -1, -1):
            raise ValueError("Ungültige Zahl in der Regeldatei: frei-Zeilen stehen auf -1 -1 -1.")
        return
    if line.cap < -1 or line.start < 0 or line.until < 0:
        raise ValueError("Ungültige Zahl in der Regeldatei: Grenzen nie negativ, Deckel mindestens -1.")


def _check_hint(line: TimeLine) -> None:
    if not (isinstance(line.next_hint, str) and TOKEN.fullmatch(line.next_hint)):
        raise ValueError("Ungültige nächste Spielzeit in der Regeldatei.")


def _player_line(name: str, line: TimeLine) -> str:
    if not PLAYER_NAME.fullmatch(name) or name.lower() in RESERVED_NAMES:
        raise ValueError("Ungültiger Spielername in der Regeldatei.")
    if line.reason not in REASONS:
        raise ValueError("Ungültiger Grund in der Regeldatei.")
    _check_numbers(line, frei=line.reason == "frei")
    _check_hint(line)
    return f"{name} {line.cap} {line.start} {line.until} {line.reason} {line.next_hint}"


def _world_line(line: TimeLine) -> str:
    if line.reason not in WORLD_REASONS:
        raise ValueError("Ungültiger Grund in der Welt-Zeile der Regeldatei.")
    _check_numbers(line, frei=False)
    _check_hint(line)
    return f"welt {line.start} {line.until} {line.reason} {line.next_hint}"


def render_time_file(generation: int, issued_at: int, world: TimeLine | None, players: dict[str, TimeLine]) -> bytes:
    """Regeldatei der Welt, sortiert und deterministisch.

    Jeder ungültige Eintrag wirft ValueError, nie wird still übersprungen: Ein
    Zeilenumbruch im Namen oder Token könnte sonst fremde Zeilen einschleusen.
    """
    if not _is_int(generation) or generation < 0:
        raise ValueError("Die Generation der Regeldatei darf nicht negativ sein.")
    if not _is_int(issued_at) or issued_at < 0:
        raise ValueError("Der Zeitpunkt der Regeldatei darf nicht negativ sein.")
    lines = [f"{TIME_HEADER} {generation} {issued_at}"]
    if world is not None:
        lines.append(_world_line(world))
    lines.extend(_player_line(name, line) for name, line in sorted(players.items()))
    lines.append("end")
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_ledger(content: bytes) -> Ledger | None:
    """Zählbuch einer Welt oder None, wenn Kopf oder Schlusszeile fehlen.

    Der Inhalt stammt aus einer vom Lua-Prozess beschreibbaren Datei: Zeilen mit
    ungültigem Namen, negativen, nicht ganzzahligen oder übergroßen Sekunden
    werden übersprungen.
    """
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        text = content.decode("ascii", "replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) < 2 or lines[-1] != "end":
        return None
    head = _LEDGER_HEAD.fullmatch(lines[0])
    if head is None:
        return None
    seconds: dict[str, int] = {}
    for raw in lines[1:-1]:
        match = _LEDGER_LINE.fullmatch(raw)
        if match is None or not PLAYER_NAME.fullmatch(match.group(1)):
            continue
        value = int(match.group(2))
        if value <= LEDGER_MAX_SECONDS:
            seconds[match.group(1)] = value
    return Ledger(written_at=int(head.group(1)), generation=int(head.group(2)), seconds=seconds)
