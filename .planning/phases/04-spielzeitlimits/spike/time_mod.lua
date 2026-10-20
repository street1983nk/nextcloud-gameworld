-- gameworld_time (Spike-Version Phase 4): Spielzeit und Zeitfenster durchsetzen.
-- Regeln schreibt nur Gameworld (gameworld_time.txt, root 0444).
-- Der Mod zaehlt die Online-Zeit je Spieler fortlaufend in gameworld_time_used.txt
-- (bleibt im Welt-Volume, ueberlebt Neustarts) und trennt bei Ablauf.
-- Keine IP-Adressen, kein trusted/http-Mod noetig. Texte im Spike ASCII.
local world = core.get_worldpath()
local rules_path = world .. "/gameworld_time.txt"
local used_path = world .. "/gameworld_time_used.txt"
local diag_path = world .. "/gameworld_time_diag.txt"
local TICK = 5
local WARN = { 30, 15 }          -- Spike: Sekunden; Produkt: { 600, 300, 60 }
local MIN_LEFT = 10              -- Spike: Join nur mit mindestens so viel Rest

local TEXT = {
  limit = "Deine Spielzeit fuer heute ist aufgebraucht.",
  fenster = "Gerade ist keine Spielzeit.",
  tag = "Heute ist kein Spieltag.",
  welt = "Diese Welt ist gerade geschlossen.",
  start = "Gameworld startet gleich. Bitte gleich nochmal versuchen.",
}

local rules, world_rule, last, valid = {}, nil, nil, nil   -- valid: nil = noch nie geladen
local used = {}                                            -- Sekunden je Name, monoton
local warned = {}

local function now() return os.time() end

-- Eigenes Zaehlbuch vom letzten Lauf uebernehmen (Neustart-Festigkeit).
do
  local f = io.open(used_path, "rb")
  if f then
    local content = f:read("*a") or ""
    f:close()
    local lines = content:split("\n")
    if (lines[1] or ""):match("^gameworld%-time%-used 1 ") and lines[#lines] == "end" then
      for i = 2, #lines - 1 do
        local name, secs = lines[i]:match("^([%w_%-]+) (%d+)$")
        if name then used[name] = tonumber(secs) end
      end
    end
  end
end

local function write_used()
  local out = { "gameworld-time-used 1 " .. now() }
  local names = {}
  for name in pairs(used) do names[#names + 1] = name end
  table.sort(names)
  for _, name in ipairs(names) do out[#out + 1] = name .. " " .. math.floor(used[name]) end
  out[#out + 1] = "end"
  core.safe_file_write(used_path, table.concat(out, "\n") .. "\n")
end

local function load()
  local f = io.open(rules_path, "rb")
  if not f then
    if valid == nil then valid = "missing" end   -- nie geschrieben: keine Regeln
    return
  end
  local content = f:read("*a")
  f:close()
  if not content or content == last then return end
  local lines = content:split("\n")
  if not (lines[1] or ""):match("^gameworld%-time 1 %d+ %d+$") or lines[#lines] ~= "end" then
    if valid == nil then valid = "broken" end    -- unvollstaendig beim Start: zu
    return
  end
  local new, new_world = {}, nil
  for i = 2, #lines - 1 do
    local until_w, reason_w, next_w = lines[i]:match("^welt (%-?%d+) (%a+) ([%w:%-]+)$")
    if until_w then
      new_world = { until_t = tonumber(until_w), reason = reason_w, next = next_w }
    else
      local name, rem, until_t, basis, reason, nxt =
        lines[i]:match("^([%w_%-]+) (%-?%d+) (%-?%d+) (%d+) (%a+) ([%w:%-]+)$")
      if name and #name <= 20 then
        new[name] = { remaining = tonumber(rem), until_t = tonumber(until_t), basis = tonumber(basis),
                      reason = reason, next = nxt }
      end
    end
  end
  rules, world_rule, last, valid = new, new_world, content, "ok"
end

-- Restzeit in Sekunden und Grundcode; nil = unbegrenzt.
local function left(name)
  if valid == "broken" then return 0, "start", "-" end
  local t = now()
  local best, why, nxt = nil, nil, "-"
  local r = rules[name]
  local exempt = r and r.reason == "frei"
  if world_rule and world_rule.until_t >= 0 and not exempt then
    best, why, nxt = world_rule.until_t - t, "welt", world_rule.next
  end
  if r and not exempt then
    if r.until_t >= 0 then
      local w = r.until_t - t
      if not best or w < best then best, why, nxt = w, (r.reason ~= "ok" and r.reason or "fenster"), r.next end
    end
    if r.remaining >= 0 then
      local spent = math.max(0, (used[name] or 0) - r.basis)
      local rem = r.remaining - spent
      if not best or rem < best then best, why, nxt = rem, "limit", r.next end
    end
  end
  return best, why, nxt
end

local function text(why, nxt)
  local s = TEXT[why] or TEXT.fenster
  if nxt and nxt ~= "-" then s = s .. " Naechste Spielzeit: " .. nxt:gsub("-", " ") end
  return s
end

-- Schutz gegen den Engine-Wettlauf beim sofortigen Wieder-Beitreten (Spike C):
-- Der alte Spieler steckt noch in der Liste, get_player_by_name liefert fuer den
-- neuen nil, und on_joinplayer der Spiele (MTG creative, VoxeLibre vl_legacy) stuerzt ab.
local COOLDOWN = 2
local left_at = {}
core.register_on_leaveplayer(function(player) left_at[player:get_player_name()] = core.get_us_time() end)

core.register_on_prejoinplayer(function(name)
  load()
  local l, why, nxt = left(name)
  if l and l < MIN_LEFT then return text(why, nxt) end   -- Regeltext hat Vorrang
  local t = left_at[name]
  if core.get_player_by_name(name) or (t and (core.get_us_time() - t) / 1e6 < COOLDOWN) then
    return "Bitte einen Moment warten und dann nochmal beitreten."
  end
end)

local last_us = core.get_us_time()
local function tick()
  load()
  local now_us = core.get_us_time()
  local dt = (now_us - last_us) / 1e6
  last_us = now_us
  local players = core.get_connected_players()
  for _, player in ipairs(players) do
    local name = player:get_player_name()
    used[name] = (used[name] or 0) + dt
    local l, why, nxt = left(name)
    if l then
      if l <= 0 then
        core.disconnect_player(name, text(why, nxt))
      else
        warned[name] = warned[name] or {}
        for _, w in ipairs(WARN) do
          if l <= w and not warned[name][w] then
            warned[name][w] = true
            core.chat_send_player(name, "Noch " .. math.ceil(l) .. " Sekunden Spielzeit.")
          elseif l > w then
            warned[name][w] = nil
          end
        end
      end
    end
  end
  if #players > 0 then write_used() end
  core.after(TICK, tick)
end

core.register_on_leaveplayer(function(player) warned[player:get_player_name()] = nil end)
core.register_on_shutdown(write_used)
core.register_on_mods_loaded(function()
  core.safe_file_write(diag_path, "os_time " .. os.time() .. "\nlocal " .. os.date("%Y-%m-%d %H:%M %z") ..
    "\nutc " .. os.date("!%Y-%m-%d %H:%M") .. "\n")
  core.after(0, tick)
end)
