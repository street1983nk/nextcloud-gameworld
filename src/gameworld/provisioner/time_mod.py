"""The world mod gameworld_time, the rule file and the ledger, as constants in the code.

The game server enforces the playtime (ZEIT-02, owner decision O-01): the
mod reads the rule file ``gameworld_time.txt`` in the world folder on every join attempt
and every 5 s, which only the ExApp writes via ``put_archive``
(root, 0444). It counts the online time per player in its own
ledger ``gameworld_time_used.txt`` (uid 30000, via ``core.safe_file_write``),
which stays in the world volume and is read in again at start. A
world restart therefore does not reset the time.

Format of the rule file (ASCII, lines sorted, deterministic)::

    gameworld-time 1 <generation> <issued, epoch>
    welt <from> <until> <reason> <next>                (only with a world time window)
    <player name> <cap> <from> <until> <reason> <next>
    end

``cap`` is the ledger state in seconds from which the player is disconnected
(-1 = no daily limit), ``from`` and ``until`` are absolute epoch seconds of the
allowed window (containers run in UTC, only the ExApp computes local time).
The reason is ok, tag, fenster, limit or frei (managers: world window
and own limits do not apply, line ``-1 -1 -1 frei -``); the world line
knows ok and welt. The next token is like ``Sa-10:00``, ``-`` means:
no next playtime. The new mod no longer displays the token; it stays
only for mods in running containers that were started before the update.

Since quick 261021-481 (owner decision 21.10.2026: child texts without "0 Uhr" and
"Mitternacht") two more line types are added, both with ``@`` at the start::

    @tage <wd0> <d0> <d1> ... <d8>               (directly after the head)
    @start <player name|welt> <epoch> <minute>   (directly after the line it belongs to)

``@tage`` gives the ISO weekday (1..7) of the local day ``d0`` (today when
writing) and the nine epoch starts of the local days today to today+8 (from
zoneinfo, so also correct on 23 h and 25 h days). ``@start`` gives the
epoch of the next window opening and its local minute 0..1439; the mod shows
a clock time only for minute > 0 (a real start time set by the parents). The
day reference ("Heute", "Morgen", "Am Samstag", "Nächsten Samstag") is formed by the mod
itself against its own clock: so it is also right after midnight, before the
ExApp writes anew. Compatibility: old mods read only lines that begin with
``[%w_%-]`` and skip ``@`` lines (``@`` never occurs in
player names, no fail-open); the new mod reads files without
``@`` lines and then shows the base sentence without a time.

Since WR-06 (review phase 4) a line with a cap (``cap`` >= 0) is followed by::

    @base <player name> <seconds>

``base`` is the ledger state against which the ExApp computed the cap
(``cap - base`` = rest at issuing). If the mod's ledger is below it on loading
(ledger deleted, backup restored), the mod shifts the
cap by the difference: it then never grants more than the rest at issuing,
even if the ExApp does not rewrite until the window end. Normally the mod state
is at least ``base`` and nothing changes. ``base`` changes only
with the cap, not on every tick (pitfall 6). Old mods skip the line.

Since phase 4.1 (pause from the phone, D-03 to D-05, D-26) two more
``@`` lines are added::

    @pause <ab> <bis> <art>          (directly after @tage or after the head)
    @morgen <player name> <minute>   (only with art schluss, directly after, sorted)

``ab`` is the epoch of the disconnect (trigger + 30 s), ``bis`` the end, ``art``
is ``pause`` or ``schluss``. From ``ab`` - 30 s the mod lets nobody in except
``frei``, not even names without a rule line; connected players once get
"In 30 Sekunden ist Pause." and are disconnected from ``ab`` with the pause text.
``@morgen`` gives the local start minute of the next day for the closing text
(-1 = tomorrow is not a play day). Disconnected children use up nothing (D-05), the
ledger stays unchanged. Old mods skip both lines silently; whether the
running mod can do them is shown to the ExApp by the event file of the access mod
(same restart, no fail-open, 04.1-RESEARCH.md pitfall 1 and pattern 3).

Since phase 5 (chat notice before the cold backup, D-09) the last
``@`` line before ``end`` is added::

    @halt <ab>

``ab`` is the epoch from which the game server stops shortly (backup). If the
mod sees the line, it sends exactly once per ``ab`` to everyone "Die Welt macht gleich
eine kurze Pause.", lets nobody in from then on (not even ``frei``,
the server stops shortly) and disconnects all connected players from ``ab`` with "Die Welt
macht kurz Pause. Gleich geht es weiter.". The ExApp keeps the halt in memory
only; after the snapshot the restart writes the file without ``@halt``.
Old mods skip the line silently, then there is no notice, the flow
stays correct (05-RESEARCH.md pattern 6).

Format of the ledger (written only by the mod)::

    gameworld-time-used 1 <os.time when writing> <loaded generation>
    <player name> <seconds total>
    end

If the rule file is missing, there are no rules. If head or closing line are missing (half
written), the last valid state stays; if at start only an
invalid file exists, nobody gets in (fail closed, O-04). Advance warning via
chat at 10, 5 and 1 minute rest (O-06), AFK counts as playtime (O-09). The
mod writes no IP addresses and no session times; the Lua source
stays pure ASCII, the child texts go in as Lua decimal escapes.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import dataclass
from typing import NamedTuple

from gameworld.provisioner.access_mod import MOD_NAME as ACCESS_MOD_NAME
from gameworld.provisioner.access_mod import _lua_string  # pyright: ignore[reportPrivateUsage]
from gameworld.provisioner.spec import DATA_DIR
from gameworld.provisioner.status_mod import PLAYER_NAME

MOD_NAME = "gameworld_time"
MOD_DIR = f".minetest/worlds/world/worldmods/{MOD_NAME}"

RULES_FILE_NAME = "gameworld_time.txt"
LEDGER_FILE_NAME = "gameworld_time_used.txt"
# Paths in the container; the ExApp writes RULES_FILE and reads LEDGER_FILE.
RULES_FILE = f"{DATA_DIR}/.minetest/worlds/world/{RULES_FILE_NAME}"
LEDGER_FILE = f"{DATA_DIR}/.minetest/worlds/world/{LEDGER_FILE_NAME}"
TIME_HEADER = "gameworld-time 1"
LEDGER_HEADER = "gameworld-time-used 1"

REASONS = frozenset({"ok", "tag", "fenster", "limit", "frei"})
WORLD_REASONS = frozenset({"ok", "welt"})
# Names of the key lines; a player must not have such a name (case-insensitive).
RESERVED_NAMES = frozenset({"welt", "end"})
TOKEN = re.compile(r"[A-Za-z0-9:-]{1,16}")
# Maximum value of a ledger line; anything above is broken or foreign.
LEDGER_MAX_SECONDS = 10**9

_LEDGER_HEAD = re.compile(r"gameworld-time-used 1 ([0-9]+) ([0-9]+)")
_LEDGER_LINE = re.compile(r"(\S+) ([0-9]+)")

# Texts for the children (on a rejected join, on disconnect, as a chat advance warning).
# Owner decision 21.10.2026: never "0 Uhr", "Mitternacht", a date or a
# short form like "Mi 00:00"; day reference and clock time are assembled by kid_text (Python) or
# text() in Lua from the building blocks.
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
# Owner decisions D-03, D-04 and D-26 of 21.10.2026 (pause from the phone, phase 4.1).
TEXT_PAUSE = "Kurze Pause! Deine Eltern brauchen dich gerade. Danach kannst du weiterspielen."
TEXT_PAUSE_SOON = "In 30 Sekunden ist Pause."
TEXT_SCHLUSS = "Für heute ist Schluss."
# Chat notice before the cold backup (D-09, phase 5).
TEXT_HALT_SOON = "Die Welt macht gleich eine kurze Pause."
TEXT_HALT = "Die Welt macht kurz Pause. Gleich geht es weiter."
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
    TEXT_PAUSE,
    TEXT_PAUSE_SOON,
    TEXT_SCHLUSS,
    TEXT_HALT_SOON,
    TEXT_HALT,
)


class TimeTexts(NamedTuple):
    """Texts of gameworld_time in one world language.

    Sentences are always base + " " + day phrase + tail (kid_text here, text() in Lua).
    """

    limit: str
    fenster: str
    fenster_early: str
    tag: str
    welt: str
    start: str
    warn_10: str
    warn_5: str
    warn_1: str
    play: str
    play_again: str
    open_again: str
    day_today: str
    day_tomorrow: str
    day_on: str
    day_next: str
    clock_from: str
    clock_unit: str
    weekdays: tuple[str, ...]
    pause: str
    pause_soon: str
    schluss: str
    halt_soon: str
    halt: str


# World language (D-27): the Lua code is the same in every language, only these literals change.
# The building blocks of en and fr read naturally in the fixed German order
# (base + " " + day [+ from + clock] + tail). Owner decision 21.10.2026 holds in every
# language: never midnight, "0 Uhr" or a date; a clock time only for minute > 0.
MOD_TEXTS: dict[str, TimeTexts] = {
    "de": TimeTexts(
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
        WEEKDAY_NAMES,
        TEXT_PAUSE,
        TEXT_PAUSE_SOON,
        TEXT_SCHLUSS,
        TEXT_HALT_SOON,
        TEXT_HALT,
    ),
    "en": TimeTexts(
        limit="Your playtime for today is over.",
        fenster="It is not playtime right now.",
        fenster_early="It is not playtime yet.",
        tag="Today is not a play day.",
        welt="This world is closed right now.",
        start="Gameworld is starting. Please try again in a moment.",
        warn_10="10 minutes of playtime left. Start finishing up and say goodbye.",
        warn_5="5 minutes left.",
        warn_1="1 minute left.",
        play=" you can play.",
        play_again=" you can play again.",
        open_again=" it will be open again.",
        day_today="Today",
        day_tomorrow="Tomorrow",
        day_on="On ",
        day_next="Next ",
        clock_from=" from ",
        clock_unit=":00",
        weekdays=("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
        pause="Short break! Your parents need you right now. You can keep playing afterwards.",
        pause_soon="Break in 30 seconds.",
        schluss="That is it for today.",
        halt_soon="The world is taking a short break soon.",
        halt="The world is taking a short break. It will be back in a moment.",
    ),
    "fr": TimeTexts(
        limit="Ton temps de jeu pour aujourd\u2019hui est terminé.",
        fenster="Ce n\u2019est pas l\u2019heure de jouer.",
        fenster_early="Ce n\u2019est pas encore l\u2019heure de jouer.",
        tag="Aujourd\u2019hui, ce n\u2019est pas un jour de jeu.",
        welt="Ce monde est fermé pour le moment.",
        start="Gameworld démarre. Réessaie dans un instant.",
        warn_10="Encore 10 minutes de temps de jeu. Commence à terminer et dis au revoir.",
        warn_5="Encore 5 minutes.",
        warn_1="Encore 1 minute.",
        play=", tu peux jouer.",
        play_again=", tu pourras rejouer.",
        open_again=", il sera de nouveau ouvert.",
        day_today="Aujourd\u2019hui",
        day_tomorrow="Demain",
        day_on="Ce ",
        day_next="La semaine prochaine, ",
        clock_from=" à partir de ",
        clock_unit=" h",
        weekdays=("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"),
        pause="Petite pause. Tes parents ont besoin de toi. Ensuite, tu pourras continuer à jouer.",
        pause_soon="Pause dans 30 secondes.",
        schluss="C\u2019est fini pour aujourd\u2019hui.",
        halt_soon="Le monde va bientôt faire une petite pause.",
        halt="Le monde fait une petite pause. Ça reprend dans un instant.",
    ),
}


def mod_texts(language: object) -> TimeTexts:
    """Text bundle of ``language``; anything unsupported (value from the database) gives German."""
    if isinstance(language, str) and language in MOD_TEXTS:
        return MOD_TEXTS[language]
    return MOD_TEXTS["de"]


PAUSE_ARTS = frozenset({"pause", "schluss"})
# Lead time of the pause: for this long before the disconnect the join block applies and the advance warning comes.
PAUSE_LEAD_SECONDS = 30
# @morgen -1: tomorrow is not a play day according to the plan.
NO_TOMORROW = -1
# Nine day starts (today to today+8) in the line @tage; nobody shows more than 7 days ahead.
DAY_COUNT = 9
MAX_DAYS_AHEAD = 7
_DAY_MINUTES = 1440


def _weekdays_lua(texts: TimeTexts) -> str:
    """Weekday names as a Lua list (decimal escapes, the Lua source stays ASCII)."""
    return ", ".join(_lua_string(name) for name in texts.weekdays)


def _base(texts: TimeTexts) -> dict[str, str]:
    return {"limit": texts.limit, "tag": texts.tag, "fenster": texts.fenster, "welt": texts.welt, "start": texts.start}


def _clock(minute: int, texts: TimeTexts) -> str:
    """ "9 Uhr" on the full hour, otherwise "9:30" without unit (owner decision 22.10.2026)."""
    hours, minutes = divmod(minute, 60)
    return f"{hours}{texts.clock_unit}" if minutes == 0 else f"{hours}:{minutes:02d}"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def kid_text(
    reason: str,
    days_ahead: int | None = None,
    weekday: int | None = None,
    minute: int | None = None,
    *,
    reached: bool = False,
    language: object = "de",
) -> str:
    """Child text for reason and next start; mirrors text() in the Lua mod exactly.

    ``days_ahead`` 0..7 (0 = today), ``weekday`` ISO 1..7, ``minute`` 0..1439
    local. If a value is missing or out of range, only the base sentence stands.
    A clock time appears only for ``minute`` > 0 (real start time of the parents).
    ``reached``: the next start has already been reached, i.e. the rule file is older than
    the change of day (whole day without a limit, disconnected at the end of day). Then
    TEXT_START applies instead of "Jetzt ist noch keine Spielzeit. Heute kannst du spielen.",
    which would contradict itself (WR-07); the ExApp rewrites within 15 s.
    ``language``: world language (D-27); unsupported values give German.
    """
    texts = mod_texts(language)
    base = _base(texts).get(reason, texts.fenster)
    if reason == "start" or reached:
        return texts.start
    if days_ahead is None or weekday is None or minute is None:
        return base
    if not all(_is_int(value) for value in (days_ahead, weekday, minute)):
        return base
    if not (0 <= days_ahead <= MAX_DAYS_AHEAD and 1 <= weekday <= 7 and 0 <= minute < _DAY_MINUTES):
        return base
    if reason == "fenster" and days_ahead == 0:
        base = texts.fenster_early
    if days_ahead == 0:
        day = texts.day_today
    elif days_ahead == 1:
        day = texts.day_tomorrow
    elif days_ahead < MAX_DAYS_AHEAD:
        day = texts.day_on + texts.weekdays[weekday - 1]
    else:
        day = texts.day_next + texts.weekdays[weekday - 1]
    if minute > 0:
        day += texts.clock_from + _clock(minute, texts)
    if reason == "welt":
        tail = texts.open_again
    elif days_ahead == 0:
        tail = texts.play
    else:
        tail = texts.play_again
    return f"{base} {day}{tail}"


def pause_text(art: str, morgen_minute: int | None, *, language: object = "de") -> str:
    """Child text on disconnect and rejection during the pause; mirrors pause_text() in the Lua mod.

    ``pause``: TEXT_PAUSE. ``schluss``: "Für heute ist Schluss. Morgen kannst du
    wieder spielen.", with a clock time only for minute > 0 (real start time, never "0 Uhr").
    Minute -1 (tomorrow is not a play day according to the plan) yields only TEXT_SCHLUSS, so that the
    text promises nothing false. ``language``: world language (D-27).
    """
    texts = mod_texts(language)
    if art != "schluss":
        return texts.pause
    if morgen_minute == NO_TOMORROW:
        return texts.schluss
    day = texts.day_tomorrow
    if morgen_minute is not None and _is_int(morgen_minute) and 0 < morgen_minute < _DAY_MINUTES:
        day += texts.clock_from + _clock(morgen_minute, texts)
    return f"{texts.schluss} {day}{texts.play_again}"


def mod_init_lua(language: object = "de") -> str:
    """init.lua of gameworld_time; only the text literals depend on ``language`` (T-06-85).

    The value never reaches the Lua source itself, it only selects a fixed bundle.
    """
    t = mod_texts(language)
    return f"""\
-- gameworld_time: enforce playtimes and time windows of Gameworld.
-- Only Gameworld writes the rule file. The mod counts the online time per
-- player in the ledger, which stays in the world volume and survives restarts.
-- All boundaries are absolute epoch seconds (os.time), never local clock time.
-- No IP addresses, no session times.
local world = core.get_worldpath()
local rules_path = world .. "/{RULES_FILE_NAME}"
local ledger_path = world .. "/{LEDGER_FILE_NAME}"
local TICK = 5
local MIN_LEFT = 60
local WARN = {{ 600, 300, 60 }}
local WARN_TEXT = {{
  [600] = {_lua_string(t.warn_10)},
  [300] = {_lua_string(t.warn_5)},
  [60] = {_lua_string(t.warn_1)},
}}
local TEXT = {{
  limit = {_lua_string(t.limit)},
  fenster = {_lua_string(t.fenster)},
  tag = {_lua_string(t.tag)},
  welt = {_lua_string(t.welt)},
  start = {_lua_string(t.start)},
}}
local FENSTER_EARLY = {_lua_string(t.fenster_early)}
local PLAY = {_lua_string(t.play)}
local PLAY_AGAIN = {_lua_string(t.play_again)}
local OPEN_AGAIN = {_lua_string(t.open_again)}
local DAY_TODAY = {_lua_string(t.day_today)}
local DAY_TOMORROW = {_lua_string(t.day_tomorrow)}
local DAY_ON = {_lua_string(t.day_on)}
local DAY_NEXT = {_lua_string(t.day_next)}
local CLOCK_FROM = {_lua_string(t.clock_from)}
local CLOCK_UNIT = {_lua_string(t.clock_unit)}
local WEEKDAYS = {{ {_weekdays_lua(t)} }}
local PAUSE_TEXT = {_lua_string(t.pause)}
local PAUSE_SOON = {_lua_string(t.pause_soon)}
local SCHLUSS = {_lua_string(t.schluss)}
local PAUSE_LEAD = {PAUSE_LEAD_SECONDS}
local HALT_SOON_TEXT = {_lua_string(t.halt_soon)}
local HALT_TEXT = {_lua_string(t.halt)}

-- valid: nil = never loaded, "missing" = no file (no rules),
-- "broken" = at start only an invalid file (everyone closed), "ok" = rules present.
local rules, world_rule, last, valid, generation = {{}}, nil, nil, nil, 0
-- days: weekday of day 0 and 9 day starts (line @tage); starts: per key
-- (player name or "welt") epoch and local minute of the next opening (@start).
local days, starts = nil, {{}}
-- shifts: per name, by how much the ledger was below @base on loading (WR-06).
local shifts = {{}}
local used = {{}}    -- seconds per name, monotonic across all restarts
local since = {{}}   -- get_us_time up to which the time is credited
local warned = {{}}  -- per name the advance warnings already sent in this session
-- pause: nil or {{ ab, bis, art }} from @pause; morgen: per name the start minute
-- of the next day (@morgen, -1 = no play day); pause_warned: per name the ab
-- of the pause for which "In 30 Sekunden ist Pause." has already been sent.
local pause, morgen, pause_warned = nil, {{}}, {{}}
-- halt: nil or the epoch from @halt from which the server stops for the backup;
-- halt_warned: the halt for which the chat notice to everyone has already been sent.
local halt, halt_warned = nil, nil

local function now()
  return os.time()
end

-- Take over the ledger from the last run (only with head and closing line).
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
  local new_pause, new_morgen, new_halt = nil, {{}}, nil
  for i = 2, #lines - 1 do
    local line = lines[i]
    local sname, sat, smin = line:match("^@start ([%w_%-]+) (%d+) (%d+)$")
    local bname, bsecs = line:match("^@base ([%w_%-]+) (%d+)$")
    local pab, pbis, part = line:match("^@pause (%d+) (%d+) (%a+)$")
    local mname, mmin = line:match("^@morgen ([%w_%-]+) (%-?%d+)$")
    local hab = line:match("^@halt (%d+)$")
    local wf, wu, wr, wn = line:match("^welt (%-?%d+) (%-?%d+) (%a+) ([%w:%-]+)$")
    if line:match("^@tage ") then
      -- Exactly 10 numbers, weekday 1..7, starts strictly increasing; otherwise ignore the line.
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
    elseif pab then
      -- Only known kinds and a real time window; otherwise ignore the line.
      local ab, bis = tonumber(pab), tonumber(pbis)
      if (part == "pause" or part == "schluss") and bis > ab then
        new_pause = {{ ab = ab, bis = bis, art = part }}
      end
    elseif mname then
      local m = tonumber(mmin)
      if #mname <= 20 and m >= -1 and m <= 1439 then new_morgen[mname] = m end
    elseif hab then
      new_halt = tonumber(hab)
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
  -- Ledger below the state against which the cap was computed: shift the cap (WR-06).
  local new_shifts = {{}}
  for name, base in pairs(new_bases) do
    local behind = base - (used[name] or 0)
    if behind > 0 then new_shifts[name] = behind end
  end
  rules, world_rule, last, valid, generation = new, new_world, content, "ok", tonumber(gen)
  days, starts, shifts = new_days, new_starts, new_shifts
  pause, morgen = new_pause, new_morgen
  halt = new_halt
end

-- Remaining time in seconds, reason and key of the next start ("welt" or
-- the player name, see starts); nil = unlimited.
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

-- Index 0..7 of the local day in which epoch t lies (day k = [s[k], s[k+1])), otherwise nil.
local function day_index(t)
  if not days then return nil end
  for k = 0, 7 do
    if t >= days.s[k] and t < days.s[k + 1] then return k end
  end
  return nil
end

-- Clock time like _clock in time_mod.py: "9 Uhr" or "9:30" (without "Uhr").
local function clock(minute)
  local h = math.floor(minute / 60)
  local m = minute % 60
  return m == 0 and (tostring(h) .. CLOCK_UNIT) or string.format("%d:%02d", h, m)
end

-- Day reference with clock time, e.g. "Morgen ab 9 Uhr", and days from today; nil if something is missing.
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
    s = s .. CLOCK_FROM .. clock(st.minute)
  end
  return s, ahead
end

-- Sentence for the child; mirrors kid_text in time_mod.py exactly.
local function text(why, key)
  local s = TEXT[why] or TEXT.fenster
  if why == "start" then return s end
  -- Next start already reached: the rule file is older than the change of day,
  -- the ExApp rewrites shortly; never "Heute kannst du spielen" on disconnect (WR-07).
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

-- Pause text for the child; mirrors pause_text in time_mod.py exactly.
local function pause_text(name)
  if pause.art ~= "schluss" then return PAUSE_TEXT end
  local m = morgen[name]
  if m == -1 then return SCHLUSS end
  local s = SCHLUSS .. " " .. DAY_TOMORROW
  if m and m > 0 then s = s .. CLOCK_FROM .. clock(m) end
  return s .. PLAY_AGAIN
end

-- Pause applies to everyone except "frei", also to names without a rule line (D-05).
-- From PAUSE_LEAD seconds before the disconnect nobody gets in anymore.
local function paused(name)
  if not pause then return false end
  local r = rules[name]
  if r and r.reason == "frei" then return false end
  local t = now()
  return t >= pause.ab - PAUSE_LEAD and t < pause.bis
end

-- Send only the smallest threshold just crossed, all larger ones
-- then count as sent (join with 4 min rest: only "Noch 5 Minuten.").
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
    -- 10-minute warning as an event for the ExApp (Talk bot, TALK-02).
    if hit == 600 and gameworld_access and gameworld_access.event then
      gameworld_access.event("warn10", name)
    end
    for _, w in ipairs(WARN) do
      if w >= hit then marks[w] = true end
    end
  end
end

-- Credit from join or last tick, never a flat amount per tick.
local function credit(name, now_us)
  local t = since[name]
  if not t then return end
  local dt = (now_us - t) / 1e6
  if dt > 0 then used[name] = (used[name] or 0) + dt end
  since[name] = now_us
end

core.register_on_prejoinplayer(function(name)
  load()
  -- The server stops shortly for the backup: nobody gets in anymore, not even frei.
  if halt then return HALT_TEXT end
  if paused(name) then return pause_text(name) end
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
  pause_warned[name] = nil
  write_ledger()
end)

local function tick()
  load()
  local now_us = core.get_us_time()
  local players = core.get_connected_players()
  if halt and halt_warned ~= halt then
    -- Once per halt to everyone, before the server stops for the backup (D-09).
    halt_warned = halt
    core.chat_send_all(HALT_SOON_TEXT)
  end
  for _, player in ipairs(players) do
    local name = player:get_player_name()
    if since[name] then credit(name, now_us) else since[name] = now_us end
    -- From the halt on disconnect everyone, also frei: the server stops shortly for the backup.
    local cut = halt and now() >= halt
    local p = not cut and paused(name)
    if cut then
      core.disconnect_player(name, HALT_TEXT)
    elseif p and now() >= pause.ab then
      -- Disconnecting counts nothing anymore: disconnected children use up no time (D-05).
      core.disconnect_player(name, pause_text(name))
    else
      if p and pause_warned[name] ~= pause.ab then
        pause_warned[name] = pause.ab
        core.chat_send_player(name, PAUSE_SOON)
      end
      local l, why, key = left(name)
      if l then
        if l <= 0 then
          core.disconnect_player(name, text(why, key))
        else
          warn(name, l)
        end
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

-- Write once at start: the head shows the ExApp which generation is loaded.
core.register_on_mods_loaded(function()
  load()
  write_ledger()
  core.after(TICK, tick)
end)
"""


MOD_INIT_LUA = mod_init_lua("de")

MOD_CONF = f"""\
name = {MOD_NAME}
description = Spielzeiten und Zeitfenster von Gameworld durchsetzen
depends = {ACCESS_MOD_NAME}
"""


@dataclass(frozen=True)
class TimeLine:
    """A line of the rule file; ``cap`` -1 = no daily limit, ``frei`` lines -1 -1 -1.

    ``next_at`` and ``next_minute`` (epoch and local minute of the next
    window opening) yield the line ``@start``; -1 and -1 means: none.
    ``base`` (ledger state against which ``cap`` is computed) yields the line
    ``@base``; -1 means: none (WR-06).
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
    """Line ``@tage``: ISO weekday of today and nine epoch day starts (today to today+8)."""

    weekday: int
    starts: tuple[int, ...]


@dataclass(frozen=True)
class PauseLine:
    """Line ``@pause``: epoch of the disconnect (``ab``), end (``bis``), kind pause or schluss."""

    ab: int
    bis: int
    art: str


@dataclass(frozen=True)
class Ledger:
    """Ledger of a world: time of writing (epoch), loaded generation, seconds per name."""

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
    """Line ``@start`` or None if the line carries no next start."""
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
    """Line ``@base`` or None without an anchor; only for a line with a cap (cap >= 0)."""
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


def _pause_line(pause: PauseLine) -> str:
    if not isinstance(pause.art, str) or pause.art not in PAUSE_ARTS:
        raise ValueError("Ungültige Pause in der Regeldatei: Art pause oder schluss.")
    if not (_is_int(pause.ab) and _is_int(pause.bis)):
        raise ValueError("Ungültige Pause in der Regeldatei: nur ganze Zahlen.")
    if pause.ab < 0 or pause.bis <= pause.ab:
        raise ValueError("Ungültige Pause in der Regeldatei: nie negativ, Ende nach dem Beginn.")
    return f"@pause {pause.ab} {pause.bis} {pause.art}"


def _halt_line(ab: int) -> str:
    """Line ``@halt``: epoch from which the server stops for the backup (D-09, T-05-13)."""
    if not _is_int(ab) or ab < 0:
        raise ValueError("Ungültiger Halt in der Regeldatei: nur ganze Zahlen, nie negativ.")
    return f"@halt {ab}"


def _morgen_lines(morgen: dict[str, int]) -> list[str]:
    lines: list[str] = []
    for name, minute in sorted(morgen.items()):
        if not (isinstance(name, str) and PLAYER_NAME.fullmatch(name)):
            raise ValueError("Ungültiger Spielername in einer Morgen-Zeile der Regeldatei.")
        if not _is_int(minute) or not NO_TOMORROW <= minute < _DAY_MINUTES:
            raise ValueError("Ungültige Minute in einer Morgen-Zeile der Regeldatei: -1 bis 1439.")
        lines.append(f"@morgen {name} {minute}")
    return lines


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
    *,
    pause: PauseLine | None = None,
    morgen: dict[str, int] | None = None,
    halt: int | None = None,
) -> bytes:
    """Rule file of the world, sorted and deterministic.

    Order: head, ``@tage``, ``@pause``, ``@morgen`` (sorted, only for kind
    schluss), world line, ``@start welt``, per player (sorted) its line and
    directly after it ``@start <name>`` and ``@base <name>``, then ``@halt`` (only
    before a backup), finally ``end``. Without ``days``, ``pause``, ``halt``,
    next starts and anchors the bytes are the same as before the ``@`` lines;
    old mods skip ``@pause``, ``@morgen`` and ``@halt`` silently
    (pitfall 1: whether the mod can do the pause is shown by the event file).
    Every invalid entry raises ValueError, nothing is silently skipped: a
    line break in the name or token could otherwise smuggle in foreign lines.
    """
    if not _is_int(generation) or generation < 0:
        raise ValueError("Die Generation der Regeldatei darf nicht negativ sein.")
    if not _is_int(issued_at) or issued_at < 0:
        raise ValueError("Der Zeitpunkt der Regeldatei darf nicht negativ sein.")
    lines = [f"{TIME_HEADER} {generation} {issued_at}"]
    if days is not None:
        lines.append(_days_line(days))
    # Always check the morgen lines, write them only for the closing pause.
    morgen_lines = _morgen_lines(morgen) if morgen is not None else []
    if pause is not None:
        lines.append(_pause_line(pause))
        if pause.art == "schluss":
            lines.extend(morgen_lines)
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
    if halt is not None:
        lines.append(_halt_line(halt))
    lines.append("end")
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_ledger(content: bytes) -> Ledger | None:
    """Ledger of a world or None if head or closing line are missing.

    The content comes from a file writable by the Lua process: lines with
    an invalid name, negative, non-integer or oversized seconds
    are skipped.
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
