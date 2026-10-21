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
kennt ok und welt. ``naechste`` ist ein Token wie ``Sa-10:00``, ``-`` heißt:
keine nächste Spielzeit. Der neue Mod zeigt das Token nicht mehr an; es bleibt
nur für Mods in laufenden Containern stehen, die vor dem Update gestartet sind.

Seit Quick 261021-481 (Owner-Entscheid 21.10.2026: Kindertexte ohne "0 Uhr" und
"Mitternacht") kommen zwei Zeilentypen dazu, beide mit ``@`` am Anfang::

    @tage <wd0> <d0> <d1> ... <d8>               (direkt nach dem Kopf)
    @start <Spielername|welt> <Epoch> <Minute>   (direkt nach der Zeile davon)

``@tage`` nennt den ISO-Wochentag (1..7) des lokalen Tages ``d0`` (heute beim
Schreiben) und die neun Epoch-Anfänge der lokalen Tage heute bis heute+8 (aus
zoneinfo, also auch an 23-h- und 25-h-Tagen richtig). ``@start`` nennt den
Epoch der nächsten Fensteröffnung und ihre lokale Minute 0..1439; der Mod zeigt
eine Uhrzeit nur bei Minute > 0 (eine echte Startzeit der Eltern). Den
Tagesbezug ("Heute", "Morgen", "Am Samstag", "Nächsten Samstag") bildet der Mod
selbst gegen die eigene Uhr: So stimmt er auch nach Mitternacht, bevor die
ExApp neu schreibt. Kompatibilität: Alte Mods lesen nur Zeilen, die mit
``[%w_%-]`` beginnen, und überspringen ``@``-Zeilen (``@`` kommt in
Spielernamen nie vor, kein Fail-open); der neue Mod liest Dateien ohne
``@``-Zeilen und zeigt dann den Grundsatz ohne Zeitangabe.

Seit WR-06 (Review Phase 4) folgt einer Zeile mit Deckel (``cap`` >= 0) noch::

    @base <Spielername> <Sekunden>

``base`` ist der Zählbuch-Stand, gegen den die ExApp den Deckel gerechnet hat
(``cap - base`` = Rest beim Ausstellen). Liegt das Zählbuch des Mods beim Laden
darunter (Zählbuch gelöscht, Sicherung zurückgespielt), verschiebt der Mod den
Deckel um den Unterschied: Er gewährt dann nie mehr als den Rest beim Ausstellen,
auch wenn die ExApp bis zum Fensterende nicht neu schreibt. Im Normalfall ist
der Mod-Stand mindestens ``base`` und nichts ändert sich. ``base`` wechselt nur
mit dem Deckel, nicht in jedem Takt (Pitfall 6). Alte Mods überspringen die Zeile.

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

import itertools
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
# Owner-Entscheid 21.10.2026: nie "0 Uhr", "Mitternacht", ein Datum oder eine
# Kurzform wie "Mi 00:00"; Tagesbezug und Uhrzeit setzt kid_text (Python) bzw.
# text() im Lua aus den Bausteinen zusammen.
TEXT_LIMIT = "Deine Spielzeit für heute ist vorbei."
TEXT_FENSTER = "Jetzt ist keine Spielzeit."
TEXT_FENSTER_EARLY = "Jetzt ist noch keine Spielzeit."
TEXT_TAG = "Heute ist kein Spieltag."
TEXT_WELT = "Diese Welt ist gerade zu."
TEXT_START = "Gameworld startet gleich. Bitte gleich nochmal versuchen."
TEXT_WARN_10 = "Noch 10 Minuten Spielzeit. Komm langsam zum Ende und verabschiede dich."
TEXT_WARN_5 = "Noch 5 Minuten."
TEXT_WARN_1 = "Noch 1 Minute."
TEXT_PLAY = " kannst du spielen."
TEXT_PLAY_AGAIN = " kannst du wieder spielen."
TEXT_OPEN_AGAIN = " ist sie wieder offen."
DAY_TODAY = "Heute"
DAY_TOMORROW = "Morgen"
DAY_ON = "Am "
DAY_NEXT = "Nächsten "
CLOCK_FROM = " ab "
CLOCK_UNIT = " Uhr"
WEEKDAY_NAMES = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
TEXTS = (
    TEXT_LIMIT,
    TEXT_FENSTER,
    TEXT_FENSTER_EARLY,
    TEXT_TAG,
    TEXT_WELT,
    TEXT_START,
    TEXT_WARN_10,
    TEXT_WARN_5,
    TEXT_WARN_1,
    TEXT_PLAY,
    TEXT_PLAY_AGAIN,
    TEXT_OPEN_AGAIN,
    DAY_TODAY,
    DAY_TOMORROW,
    DAY_ON,
    DAY_NEXT,
    CLOCK_FROM,
    CLOCK_UNIT,
)
# Neun Tagesanfänge (heute bis heute+8) in der Zeile @tage; mehr als 7 Tage voraus zeigt niemand.
DAY_COUNT = 9
MAX_DAYS_AHEAD = 7
_DAY_MINUTES = 1440
# Wochentage als Lua-Liste (Dezimal-Escapes, die Lua-Quelle bleibt ASCII).
_WEEKDAYS_LUA = ", ".join(_lua_string(name) for name in WEEKDAY_NAMES)
_BASE = {"limit": TEXT_LIMIT, "tag": TEXT_TAG, "fenster": TEXT_FENSTER, "welt": TEXT_WELT, "start": TEXT_START}


def _clock(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return str(hours) if minutes == 0 else f"{hours}:{minutes:02d}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def kid_text(
    reason: str,
    days_ahead: int | None = None,
    weekday: int | None = None,
    minute: int | None = None,
    *,
    reached: bool = False,
) -> str:
    """Kindertext zu Grund und nächstem Start; spiegelt text() im Lua-Mod exakt.

    ``days_ahead`` 0..7 (0 = heute), ``weekday`` ISO 1..7, ``minute`` 0..1439
    lokal. Fehlt eine Angabe oder liegt sie außerhalb, steht nur der Grundsatz da.
    Eine Uhrzeit erscheint nur bei ``minute`` > 0 (echte Startzeit der Eltern).
    ``reached``: Der nächste Start ist schon erreicht, die Regeldatei also älter als
    der Tageswechsel (ganzer Tag ohne Limit, am Tagesende getrennt). Dann gilt
    TEXT_START statt "Jetzt ist noch keine Spielzeit. Heute kannst du spielen.",
    das sich widerspräche (WR-07); die ExApp schreibt binnen 15 s neu.
    """
    base = _BASE.get(reason, TEXT_FENSTER)
    if reason == "start" or reached:
        return TEXT_START
    if days_ahead is None or weekday is None or minute is None:
        return base
    if not all(_is_int(value) for value in (days_ahead, weekday, minute)):
        return base
    if not (0 <= days_ahead <= MAX_DAYS_AHEAD and 1 <= weekday <= 7 and 0 <= minute < _DAY_MINUTES):
        return base
    if reason == "fenster" and days_ahead == 0:
        base = TEXT_FENSTER_EARLY
    if days_ahead == 0:
        day = DAY_TODAY
    elif days_ahead == 1:
        day = DAY_TOMORROW
    elif days_ahead < MAX_DAYS_AHEAD:
        day = DAY_ON + WEEKDAY_NAMES[weekday - 1]
    else:
        day = DAY_NEXT + WEEKDAY_NAMES[weekday - 1]
    if minute > 0:
        day += CLOCK_FROM + _clock(minute) + CLOCK_UNIT
    if reason == "welt":
        tail = TEXT_OPEN_AGAIN
    elif days_ahead == 0:
        tail = TEXT_PLAY
    else:
        tail = TEXT_PLAY_AGAIN
    return f"{base} {day}{tail}"


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
local FENSTER_EARLY = {_lua_string(TEXT_FENSTER_EARLY)}
local PLAY = {_lua_string(TEXT_PLAY)}
local PLAY_AGAIN = {_lua_string(TEXT_PLAY_AGAIN)}
local OPEN_AGAIN = {_lua_string(TEXT_OPEN_AGAIN)}
local DAY_TODAY = {_lua_string(DAY_TODAY)}
local DAY_TOMORROW = {_lua_string(DAY_TOMORROW)}
local DAY_ON = {_lua_string(DAY_ON)}
local DAY_NEXT = {_lua_string(DAY_NEXT)}
local CLOCK_FROM = {_lua_string(CLOCK_FROM)}
local CLOCK_UNIT = {_lua_string(CLOCK_UNIT)}
local WEEKDAYS = {{ {_WEEKDAYS_LUA} }}

-- valid: nil = noch nie geladen, "missing" = keine Datei (keine Regeln),
-- "broken" = beim Start nur eine ungueltige Datei (alle zu), "ok" = Regeln da.
local rules, world_rule, last, valid, generation = {{}}, nil, nil, nil, 0
-- days: Wochentag von Tag 0 und 9 Tagesanfaenge (Zeile @tage); starts: je Schluessel
-- (Spielername oder "welt") Epoch und lokale Minute der naechsten Oeffnung (@start).
local days, starts = nil, {{}}
-- shifts: je Name, um wie viel das Zaehlbuch beim Laden unter @base lag (WR-06).
local shifts = {{}}
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
  local new, new_world, new_days, new_starts, new_bases = {{}}, nil, nil, {{}}, {{}}
  for i = 2, #lines - 1 do
    local line = lines[i]
    local sname, sat, smin = line:match("^@start ([%w_%-]+) (%d+) (%d+)$")
    local bname, bsecs = line:match("^@base ([%w_%-]+) (%d+)$")
    local wf, wu, wr, wn = line:match("^welt (%-?%d+) (%-?%d+) (%a+) ([%w:%-]+)$")
    if line:match("^@tage ") then
      -- Genau 10 Zahlen, Wochentag 1..7, Anfaenge streng steigend; sonst Zeile ignorieren.
      local nums = {{}}
      if line:match("^@tage [%d ]+$") then
        for num in line:gmatch("%d+") do nums[#nums + 1] = tonumber(num) end
      end
      local good = #nums == 10 and nums[1] >= 1 and nums[1] <= 7
      for k = 3, #nums do
        if nums[k] <= nums[k - 1] then good = false end
      end
      if good then
        local bounds = {{}}
        for k = 2, 10 do bounds[k - 2] = nums[k] end
        new_days = {{ wd = nums[1], s = bounds }}
      end
    elseif sname then
      local m = tonumber(smin)
      if #sname <= 20 and m <= 1439 then new_starts[sname] = {{ at = tonumber(sat), minute = m }} end
    elseif bname then
      if #bname <= 20 then new_bases[bname] = tonumber(bsecs) end
    elseif wf then
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
  -- Zaehlbuch unter dem Stand, gegen den der Deckel gerechnet ist: Deckel verschieben (WR-06).
  local new_shifts = {{}}
  for name, base in pairs(new_bases) do
    local behind = base - (used[name] or 0)
    if behind > 0 then new_shifts[name] = behind end
  end
  rules, world_rule, last, valid, generation = new, new_world, content, "ok", tonumber(gen)
  days, starts, shifts = new_days, new_starts, new_shifts
end

-- Restzeit in Sekunden, Grund und Schluessel des naechsten Starts ("welt" oder
-- der Spielername, siehe starts); nil = unbegrenzt.
local function left(name)
  if valid == "broken" then return 0, "start", nil end
  local t = now()
  local r = rules[name]
  if r and r.reason == "frei" then return nil end
  local best, why, key = nil, nil, nil
  if world_rule then
    if t < world_rule.from or t >= world_rule.until_t then return 0, "welt", "welt" end
    best, why, key = world_rule.until_t - t, "welt", "welt"
  end
  if r then
    if r.reason == "tag" then return 0, "tag", name end
    local closed = r.reason == "limit" and "limit" or "fenster"
    if t < r.from or t >= r.until_t then return 0, closed, name end
    local w = r.until_t - t
    if not best or w < best then best, why, key = w, closed, name end
    if r.cap >= 0 then
      local rest = r.cap - (shifts[name] or 0) - (used[name] or 0)
      if rest < best then best, why, key = rest, "limit", name end
    end
  end
  return best, why, key
end

-- Index 0..7 des lokalen Tages, in dem Epoch t liegt (Tag k = [s[k], s[k+1])), sonst nil.
local function day_index(t)
  if not days then return nil end
  for k = 0, 7 do
    if t >= days.s[k] and t < days.s[k + 1] then return k end
  end
  return nil
end

-- Tagesbezug mit Uhrzeit, z. B. "Morgen ab 9 Uhr", und Tage ab heute; nil, wenn etwas fehlt.
local function day_phrase(key)
  local st = key and starts[key]
  if not st then return nil end
  local i, j = day_index(now()), day_index(st.at)
  if not i or not j or j - i < 0 or j - i > 7 then return nil end
  local ahead = j - i
  local wd = ((days.wd - 1 + j) % 7) + 1
  local s
  if ahead == 0 then
    s = DAY_TODAY
  elseif ahead == 1 then
    s = DAY_TOMORROW
  elseif ahead < 7 then
    s = DAY_ON .. WEEKDAYS[wd]
  else
    s = DAY_NEXT .. WEEKDAYS[wd]
  end
  if st.minute > 0 then
    local h = math.floor(st.minute / 60)
    local m = st.minute % 60
    local clock = m == 0 and tostring(h) or string.format("%d:%02d", h, m)
    s = s .. CLOCK_FROM .. clock .. CLOCK_UNIT
  end
  return s, ahead
end

-- Satz fuer das Kind; spiegelt kid_text in time_mod.py exakt.
local function text(why, key)
  local s = TEXT[why] or TEXT.fenster
  if why == "start" then return s end
  -- Naechster Start schon erreicht: Die Regeldatei ist aelter als der Tageswechsel,
  -- die ExApp schreibt gleich neu; nie "Heute kannst du spielen" beim Trennen (WR-07).
  local st = key and starts[key]
  if st and st.at <= now() then return TEXT.start end
  local phrase, ahead = day_phrase(key)
  if not phrase then return s end
  if why == "fenster" and ahead == 0 then s = FENSTER_EARLY end
  local tail
  if why == "welt" then
    tail = OPEN_AGAIN
  elseif ahead == 0 then
    tail = PLAY
  else
    tail = PLAY_AGAIN
  end
  return s .. " " .. phrase .. tail
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
  local l, why, key = left(name)
  if l and l < MIN_LEFT then return text(why, key) end
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
    local l, why, key = left(name)
    if l then
      if l <= 0 then
        core.disconnect_player(name, text(why, key))
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
    """Eine Zeile der Regeldatei; ``cap`` -1 = kein Tageslimit, ``frei``-Zeilen -1 -1 -1.

    ``next_at`` und ``next_minute`` (Epoch und lokale Minute der nächsten
    Fensteröffnung) ergeben die Zeile ``@start``; -1 und -1 heißt: keine.
    ``base`` (Zählbuch-Stand, gegen den ``cap`` gerechnet ist) ergibt die Zeile
    ``@base``; -1 heißt: keine (WR-06).
    """

    cap: int
    start: int
    until: int
    reason: str
    next_hint: str
    next_at: int = -1
    next_minute: int = -1
    base: int = -1


@dataclass(frozen=True)
class DayGrid:
    """Zeile ``@tage``: ISO-Wochentag von heute und neun Epoch-Tagesanfänge (heute bis heute+8)."""

    weekday: int
    starts: tuple[int, ...]


@dataclass(frozen=True)
class Ledger:
    """Zählbuch einer Welt: Schreibzeitpunkt (Epoch), geladene Generation, Sekunden je Name."""

    written_at: int
    generation: int
    seconds: dict[str, int]


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


def _start_line(key: str, line: TimeLine) -> str | None:
    """Zeile ``@start`` oder None, wenn die Zeile keinen nächsten Start trägt."""
    at, minute = line.next_at, line.next_minute
    if not (_is_int(at) and _is_int(minute)):
        raise ValueError("Ungültiger nächster Start in der Regeldatei: nur ganze Zahlen.")
    if (at, minute) == (-1, -1):
        return None
    if line.reason == "frei":
        raise ValueError("Ungültiger nächster Start in der Regeldatei: frei-Zeilen haben keinen.")
    if at < 0 or not 0 <= minute < _DAY_MINUTES:
        raise ValueError("Ungültiger nächster Start in der Regeldatei: Epoch und Minute 0 bis 1439 gehören zusammen.")
    return f"@start {key} {at} {minute}"


def _base_line(key: str, line: TimeLine) -> str | None:
    """Zeile ``@base`` oder None ohne Anker; nur zu einer Zeile mit Deckel (cap >= 0)."""
    if not _is_int(line.base):
        raise ValueError("Ungültiger Zählbuch-Anker in der Regeldatei: nur ganze Zahlen.")
    if line.base == -1:
        return None
    if line.base < 0 or line.cap < 0 or line.base > line.cap:
        raise ValueError("Ungültiger Zählbuch-Anker in der Regeldatei: nur zu einem Deckel und nie darüber.")
    return f"@base {key} {line.base}"


def _days_line(days: DayGrid) -> str:
    starts = days.starts
    if not _is_int(days.weekday) or not 1 <= days.weekday <= 7:
        raise ValueError("Ungültige Tagesgrenzen in der Regeldatei: Wochentag 1 bis 7.")
    if not isinstance(starts, tuple) or len(starts) != DAY_COUNT or not all(_is_int(value) for value in starts):
        raise ValueError("Ungültige Tagesgrenzen in der Regeldatei: genau neun ganze Zahlen.")
    if starts[0] < 0 or any(later <= earlier for earlier, later in itertools.pairwise(starts)):
        raise ValueError("Ungültige Tagesgrenzen in der Regeldatei: nie negativ, streng steigend.")
    return "@tage " + " ".join(str(value) for value in (days.weekday, *starts))


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


def render_time_file(
    generation: int,
    issued_at: int,
    world: TimeLine | None,
    players: dict[str, TimeLine],
    days: DayGrid | None = None,
) -> bytes:
    """Regeldatei der Welt, sortiert und deterministisch.

    Reihenfolge: Kopf, ``@tage``, Welt-Zeile, ``@start welt``, je Spieler (sortiert)
    seine Zeile und direkt danach ``@start <name>`` und ``@base <name>``, zuletzt
    ``end``. Ohne ``days``, nächste Starts und Anker sind die Bytes dieselben wie
    vor den ``@``-Zeilen.
    Jeder ungültige Eintrag wirft ValueError, nie wird still übersprungen: Ein
    Zeilenumbruch im Namen oder Token könnte sonst fremde Zeilen einschleusen.
    """
    if not _is_int(generation) or generation < 0:
        raise ValueError("Die Generation der Regeldatei darf nicht negativ sein.")
    if not _is_int(issued_at) or issued_at < 0:
        raise ValueError("Der Zeitpunkt der Regeldatei darf nicht negativ sein.")
    lines = [f"{TIME_HEADER} {generation} {issued_at}"]
    if days is not None:
        lines.append(_days_line(days))
    if world is not None:
        lines.append(_world_line(world))
        start = _start_line("welt", world)
        if start is not None:
            lines.append(start)
    for name, line in sorted(players.items()):
        lines.append(_player_line(name, line))
        start = _start_line(name, line)
        if start is not None:
            lines.append(start)
        base = _base_line(name, line)
        if base is not None:
            lines.append(base)
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
