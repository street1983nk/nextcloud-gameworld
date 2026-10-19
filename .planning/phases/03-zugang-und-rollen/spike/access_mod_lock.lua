-- gameworld_access (Spike): Whitelist plus Passwort-Provisionierung aus einer Datei.
-- Die ExApp schreibt gameworld_access.txt per put_archive; der Mod liest sie
-- beim Prejoin und alle 5 s. Fehlt die Datei oder ist sie unvollständig,
-- bleibt der letzte gültige Stand (Start: niemand darf rein).
local world = core.get_worldpath()
local access_path = world .. "/gameworld_access.txt"
local debug_path = world .. "/gameworld_spike.txt"
local DENY = "Du bist in diese Welt nicht eingeladen. Frag deine Eltern."
local KICK = "Deine Einladung fuer diese Welt wurde beendet."

local allowed = {}
local last = nil
local log = {}

local function note(msg)
  log[#log + 1] = os.date("!%H:%M:%S") .. " " .. msg
  core.safe_file_write(debug_path, table.concat(log, "\n"))
end

local function load()
  local f = io.open(access_path, "rb")
  if not f then return end
  local content = f:read("*a")
  f:close()
  if content == last then return end
  local lines = content:split("\n")
  if lines[1] ~= "gameworld-access 1" or lines[#lines] ~= "end" then
    note("unvollstaendig, alter Stand bleibt")
    return
  end
  local new, count = {}, 0
  for i = 2, #lines - 1 do
    local name, hash = lines[i]:match("^([%w_%-]+) (#1#[%w%+/=]+#[%w%+/=]+)$")
    if name and #name <= 20 then
      new[name] = hash
      count = count + 1
    end
  end
  allowed, last = new, content
  note("geladen: " .. count)
end

core.register_on_prejoinplayer(function(name)
  load()
  local hash = allowed[name]
  if not hash then
    note("abgelehnt: " .. name)
    return DENY
  end
  local auth = core.get_auth_handler().get_auth(name)
  if not auth or auth.password ~= hash then
    core.set_player_password(name, hash)
    note("passwort gesetzt: " .. name)
  end
  -- Selbsttest: prüft den in Python berechneten Verifier mit Luantis eigener Funktion.
  note("check_password_entry(" .. name .. "): " .. tostring(core.check_password_entry(name, hash, "Sonne-Baum-42")))
end)

local function tick()
  load()
  for _, player in ipairs(core.get_connected_players()) do
    local name = player:get_player_name()
    if not allowed[name] then core.kick_player(name, KICK) end
  end
  core.after(5, tick)
end
core.register_on_mods_loaded(function() core.after(0, tick) end)

-- Sperre nach Fehlversuchen (Spike): 5 falsche Passwörter in 10 min sperren den Namen 10 min.
local fails = {}
core.register_on_authplayer(function(name, _ip, ok)
  if ok then fails[name] = nil return end
  local now = core.get_us_time() / 1e6
  local f = fails[name]
  if not f or now - f.t > 600 then f = { n = 0, t = now } end
  f.n = f.n + 1
  fails[name] = f
end)
core.register_on_prejoinplayer(function(name)
  local f = fails[name]
  if f and f.n >= 5 and core.get_us_time() / 1e6 - f.t <= 600 then
    return "Zu viele falsche Passwoerter. Bitte in 10 Minuten nochmal versuchen."
  end
end)
