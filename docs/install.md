<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Installing Gameworld

Deutsch: [install.de.md](install.de.md)

Guide for Nextcloud admins. What Gameworld may do and why is described in detail in [privacy.md](privacy.md).

The Gameworld interface follows the language of the Nextcloud account (German, English or French); texts in the game and in the Talk room follow the language of the world. Texts are quoted below as shown in English.

## 1. Installing from the App Store

1. Set up the deploy daemon and the Docker proxy (sections 2 and 3). Without both, AppAPI can not start Gameworld.
2. In Nextcloud, open "Apps", find Gameworld (category "Games") and install it. AppAPI pulls the image `ghcr.io/street1983nk/gameworld` and starts it through the HaRP deploy daemon.
3. The default environment variables fit when the proxy is called `gameworld-docker-proxy` and sits in the same network (section 4).
4. Open Gameworld from the menu. The setup check (section 7) tests the proxy; a world can only be created once it is green.

Requirements:

- Nextcloud 33 to 35 with the AppAPI app and a HaRP deploy daemon. The older Docker Socket Proxy as deploy daemon is deprecated in AppAPI and not supported.
- Docker on the server with Engine API 1.44 or newer.
- A UDP port range on the server, one port per world (default 30000 to 30019).

## 2. What Gameworld needs in addition

- A tightly scoped Docker proxy (`tecnativa/docker-socket-proxy`) through which Gameworld manages the world containers. Gameworld never talks to Docker through the socket directly.
- A UDP port range on the server, one port per world.
- Both live in the same Docker network as Gameworld. That is the network in which the deploy daemon starts the ExApps.

## 3. Deploy daemon and Docker proxy

### 3a. Default: your own Compose file with HaRP

HaRP, the ExApps and the Docker proxy share their own Docker network `gameworld`. The proxy has no host port.

```yaml
services:
  appapi-harp:
    image: ghcr.io/nextcloud/nextcloud-appapi-harp:release
    restart: unless-stopped
    environment:
      # Secret from a file, never in clear text in the Compose file.
      HP_SHARED_KEY_FILE: /run/secrets/harp_shared_key
      NC_INSTANCE_URL: https://cloud.example.org
    secrets:
      - harp_shared_key
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - ./harp-certs:/certs
    ports:
      # Only for the reverse proxy of Nextcloud (forwarding of /exapps/).
      - "127.0.0.1:8780:8780"
    networks:
      - gameworld

  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
    restart: unless-stopped
    environment:
      # Only what Gameworld needs.
      CONTAINERS: 1
      IMAGES: 1
      POST: 1
      VOLUMES: 1
      # Everything else explicitly closed, so a changed image default opens nothing.
      EXEC: 0
      INFO: 0
      NETWORKS: 0
      BUILD: 0
      SYSTEM: 0
      SECRETS: 0
      SWARM: 0
      NODES: 0
      SERVICES: 0
      TASKS: 0
      PLUGINS: 0
      CONFIGS: 0
      DISTRIBUTION: 0
      AUTH: 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    # No host port on purpose: the proxy is reachable inside the network gameworld only.
    networks:
      - gameworld

networks:
  gameworld:
    name: gameworld

secrets:
  harp_shared_key:
    file: ./harp_shared_key.txt
```

- Create the secret once, for example with `openssl rand -hex 32 > harp_shared_key.txt`, and make the file readable for root only.
- Configure the reverse proxy of Nextcloud so that `/exapps/` goes to `127.0.0.1:8780` (examples for nginx, Apache and Caddy in the HaRP README).
- Register the daemon in Nextcloud: "Administration settings", "AppAPI", "Register daemon", template HaRP, network `gameworld`, FRP address `appapi-harp:8782`, the same secret. Or with occ:
  `occ app_api:daemon:register harp_gameworld "HaRP" docker-install http <harp-address>:8780 https://cloud.example.org --net gameworld --harp --harp_frp_address appapi-harp:8782 --harp_shared_key <secret>`
- The proxy image is pinned by digest; an update is a deliberate decision.

### 3b. Nextcloud All-in-One (AIO)

- In the AIO interface, switch on the optional container "HaRP". AppAPI then creates the daemon `harp_aio` on its own; ExApps run in the network `nextcloud-aio`.
- Start the Docker proxy from a Compose file of its own next to AIO and attach it to the network `nextcloud-aio`:

```yaml
services:
  gameworld-docker-proxy:
    image: tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
    restart: unless-stopped
    environment:
      CONTAINERS: 1
      IMAGES: 1
      POST: 1
      VOLUMES: 1
      EXEC: 0
      INFO: 0
      NETWORKS: 0
      BUILD: 0
      SYSTEM: 0
      SECRETS: 0
      SWARM: 0
      NODES: 0
      SERVICES: 0
      TASKS: 0
      PLUGINS: 0
      CONFIGS: 0
      DISTRIBUTION: 0
      AUTH: 0
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    # No host port.
    networks:
      - nextcloud-aio

networks:
  nextcloud-aio:
    external: true
```

- Remaining risk with AIO: every container in the network `nextcloud-aio`, Nextcloud itself included, can then reach the proxy (section 6).

### 3c. Host network (not recommended)

- The daemon template "HaRP Proxy (Host)" starts ExApps in the host network. Gameworld can then reach the proxy only through a host port.
- If you use it anyway, bind the proxy to loopback only (`ports: ["127.0.0.1:2375:2375"]`) and set `GAMEWORLD_DOCKER_URL=tcp://127.0.0.1:2375`.
- Warning: every process on the server and every container in the host network can then use the proxy, which means controlling Docker with root-equivalent rights. Prefer section 3a.

## 4. Configuring Gameworld

| Variable | Default | Meaning |
|----------|---------|---------|
| `GAMEWORLD_DOCKER_URL` | `tcp://gameworld-docker-proxy:2375` | Address of the Docker proxy, never a raw Docker socket |
| `GAMEWORLD_PORT_RANGE` | `30000-30019` | UDP port range for worlds, at most 200 ports |

## 5. UDP ports

- Worlds are meant for the home network only.
- Do not set up port forwarding in the router and do not use UPnP on the router.
- Remote access comes later through a VPN.
- The firewall of the server has to allow the UDP range in the LAN.

## 6. Remaining risk, stated honestly

- With `CONTAINERS=1` and `POST=1`, anyone who reaches the proxy can create any container, including privileged ones and ones with the host file system mounted. That is root-equivalent on the server.
- Therefore: never publish the proxy on a host port, run it inside the Docker network of Gameworld only.
- Shared Docker network: every container in this network can reach the proxy. These are other ExApps of the same deploy daemon and, with AIO, all containers in the network `nextcloud-aio`, Nextcloud included.
- Gameworld itself only creates fixed, hardened world containers: user 30000 (not root), all capabilities dropped, read-only file system, 512 MB RAM (adventure world 1 GB), 1 CPU, 128 processes.
- The Gameworld container itself runs as uid 10001, not as root.
- Gameworld only changes containers that carry its own instance label.
- New and restored worlds have a root-owned world folder with sticky bit and a root-owned `worldmods` folder: Luanti can neither change nor delete the access file, the rules file or the Gameworld mods. Worlds from versions before 1.0.0 get a root-owned `worldmods` at their next start; the world folder is only hardened by a backup followed by a restore (section 12).

<a id="setup-check"></a>

## 7. Setup check

The Gameworld page checks the Docker proxy when it opens. The check changes nothing: changing requests only go to the non-existent resource `gameworld-probe-nonexistent`. As long as an error is open, "Create world" stays locked. Every message ends with a link to this section.

| Message (as shown in English) | Meaning | Fix |
|----------------------------|---------|-----|
| Gameworld cannot find the service gameworld-docker-proxy (`proxy_dns`) | the name of the proxy can not be resolved | The proxy sits in another Docker network or has another name. Attach it to the network of the deploy daemon (section 3a: `gameworld`, with AIO `nextcloud-aio`) |
| The Docker proxy at host:port is not responding (`proxy_timeout`) | no answer in time | Usually another Docker network or a firewall in front of the port. Check network and firewall |
| The Docker proxy at host:port does not accept connections (`proxy_refused`) | connection refused | Start the container `gameworld-docker-proxy` (`docker ps`), check the port in `GAMEWORLD_DOCKER_URL` |
| Gameworld should never talk to the Docker socket directly (warning, `docker_url_socket`) | the address points at a raw Docker socket | Set `GAMEWORLD_DOCKER_URL` to `tcp://gameworld-docker-proxy:2375`, no `unix://` |
| The Docker proxy is on an address outside the private network (warning, `docker_url_exposed`) | the proxy address is outside private networks | Remove the host port of the proxy, use the service name inside the Docker network |
| Gameworld cannot reach the Docker proxy | proxy not reachable | Start the service `gameworld-docker-proxy`, check `GAMEWORLD_DOCKER_URL` and the network |
| Docker Engine too old, API 1.44 or newer required | Docker engine too old | Update Docker on the server |
| The Docker proxy does not allow access to containers | no access to containers | Set `CONTAINERS=1` |
| The Docker proxy does not allow write requests | no changing requests allowed | Set `POST=1` |
| The Docker proxy does not allow access to images | no access to images | Set `IMAGES=1` |
| The Docker proxy does not allow access to volumes | no access to volumes | Set `VOLUMES=1` |
| Not checked: set POST=1 first | not checked yet | Set `POST=1`, then check again |
| The Docker proxy is too open: commands in containers are allowed (warning) | exec allowed | Set `EXEC=0` |
| The Docker proxy reveals system information (warning) | system information exposed | Set `INFO=0` |
| Unexpected answer from the Docker proxy to method and path: HTTP code | unexpected answer | Compare proxy image and flags with section 3 |
| Gameworld is not responding | Gameworld does not answer | Check the ExApp in the Nextcloud settings (AppAPI) |

After every change to the proxy, restart the service and choose "Check again" on the Gameworld page.

## 8. Memory, restarts and updates

- Every world has a fixed memory limit without swap: creative world ("Build (creative)") 512 MB, adventure world ("Adventure (gentle)") 1 GB. It can not be changed.
- Rough sizing for a home server: the sum of the limits of all worlds running at the same time plus Nextcloud has to fit into memory.
- Worlds have no restart policy of their own in Docker.
- After a server restart, Gameworld starts all worlds that were running before, during its own start. Stopped worlds stay stopped.
- A world that was ended because of low memory does not start on its own. The dashboard shows the reason, starting is one click.

### Disabling and updates

- Every time Gameworld is disabled, also right before an update and before an uninstall, Gameworld stops and removes all its own world containers. Players are disconnected for a short moment.
- Volumes with the game data, invitations, rules and backups stay unchanged.
- As soon as Gameworld runs again (after enabling or after the update), Gameworld rebuilds the containers of all worlds that were running before. The worlds come back on their own, children simply join again.
- So there are never unmanaged game servers without pause and play time rules while Gameworld is not running.

## 9. Access, roles and game passwords

### Roles

- Managers are the members of the Nextcloud group `admin` and of the manager groups (below). Only they create, start, stop and delete worlds and invite players. All managers see all worlds and operate pause, holidays, time zone and address for players; backups stay separate per manager.
- Players are all invited Nextcloud accounts, directly or through an invited Nextcloud group. They only see their own worlds with the connection info, no control buttons and no other players.
- Gameworld has no user management of its own. Roles come from Nextcloud with every request (cached for up to 30 seconds). Whoever is removed from all manager groups loses management after 30 seconds at the latest.

### Manager groups

- Default: only the group `admin` manages Gameworld. It always stays a manager group.
- Nextcloud admins add more groups in the section "Manager groups" of the Gameworld page, for example for teachers or group leaders. Only Nextcloud admins see this section. Members of these groups do not become Nextcloud admins.
- Invitation boundary: group managers without Nextcloud admin rights only invite accounts from groups in which they are a member or group admin themselves. Nextcloud does not show them other accounts; Gameworld does not work around this boundary.
- Gameworld only cleans up deleted and disabled accounts when a Nextcloud admin has opened Gameworld. Group managers never trigger this, because Nextcloud does not show them all accounts.
- Warning: do not choose a group that contains children. Every member of a manager group can invite children and lift the pause. Gameworld can not check this.

### Adult switch

- Managers mark an account as adult in the invite dialog or later in the player list. It applies to the account globally, in all worlds.
- Switching it on asks for a confirmation that states the consequences in plain words. Switching it off needs no dialog.
- What it does: the account plays without pause, time windows and play time rules at once, even in the middle of a game. An existing play time rule stays stored and applies again as soon as the switch is off. Adults do not appear in the daily review.
- What it never does: adults get no management rights in Gameworld and no Luanti admin rights. They need an invitation and a game password like everybody else.
- Only mark accounts of adults, never the account of a child.

### Only invited players get in

- Every world gets the world mod `gameworld_access`. It refuses every name that is not invited, before the login in the game. The message in the game reads "You are not invited to this world. Ask your parents." (in the language of the world)
- Inviting, removing and new passwords take effect at once, without restarting the world. Players whose invitation ends are disconnected by the world within a few seconds.
- Five wrong passwords lock a player name for ten minutes.
- Worlds that were already running before this update get the access protection only with the next restart of the world (stop and start in the dashboard).

### Player name and game passwords

- Every account has exactly one player name and one game password, valid for all worlds it is invited to. The password has the form `xxxx-xxxx-xxxx`.
- Gameworld stores no game passwords. They are derived on demand from a secret that lives in the Nextcloud configuration of the ExApp. The world only knows an SRP verifier, not the password.
- "New password" in the player management invalidates the old one at once, in all worlds, without restart.
- "Rename" assigns a new player name. In the game that is a new player with its own game progress.
- Updates of the ExApp keep the secret, all game passwords stay the same.
- Edge case reinstall: if Gameworld is uninstalled and installed again, a new secret is created, because AppAPI deletes the configuration of the ExApp on uninstall, even when the data stays. Then all game passwords change once. Gameworld writes the new credentials into all worlds on its own; the children then need the new password from their Gameworld page.

### Address for players

- The dashboard settings contain the "Player address": host name or IP address of the server in the home network, without `http://` and without port. The children see this address in their connection info.
- If the field stays empty, Gameworld shows the host name from the address bar of the browser. That does not fit when Nextcloud is opened through `localhost` or through an internet address; then enter the home network address.
- The port of each world is a UDP port from the range in section 5. It has to be reachable in the home network.
- No access from the internet without VPN: no port forwarding in the router, see section 5.

## 10. Play time

### Basic rules

- Play time is opt-in: without a rule there is no limit. Every child starts with "No limit".
- A child has one single daily allowance across all worlds. Whoever may play one hour a day can spread it over several worlds, but can not play one hour in each world. Gameworld balances the usage between the worlds every 15 seconds.
- It is set in the section "Playtime" below the list of worlds, with "Edit" per child. Four presets help to start: "No limit", "Weekends only" (Sat and Sun 2 hours each, 9:00 to 19:00), "1 hour every day" (9:00 to 19:00) and "Short on school days, longer at weekends" (Mon to Fri 1 hour, 15:00 to 19:00; Sat and Sun 2 hours, 9:00 to 19:00). After that, every day can be changed in its tile: playing allowed or not, daily limit, time from and to, or the whole day.
- Usage counts time spent online. Whoever is only connected and does nothing (AFK) uses play time as well.
- Managers never have time rules and always get in. If an account is removed from all manager groups, Gameworld notices it in the background after about 60 seconds at most; from then on the rules apply to this account like to everyone else.

### Holidays

- The section "Holidays" is a list of periods for the whole household (from, to, optional label). A running period is marked "in progress".
- In the play time dialog, every child has its own block "During holidays" (suggestion: 2 hours every day, 9:00 to 20:00). Without an own holiday plan, the normal week applies during holidays.

### Time zone

- All times apply in the time zone of the household, default `Europe/Berlin`. It is set in the settings below the address for players; the button "Use this browser's time zone" sets the zone of the browser. Gameworld handles daylight saving time itself.

### Time window per world

- With "Time window" in the world row, a world is only open at certain times, for example for a school or club world ("Open Wed 10:00 to 12:00").
- The world keeps running outside the window. Children do not get in and are disconnected at the end of the window; managers and accounts marked as adult always get in.

### In the game

- Children see the block "Your playtime today" on their Gameworld page with the remaining time or the next play time.
- In the game the chat warns at 10, 5 and 1 minute left. At the end the world disconnects the child with a text like "Your playtime for today is over. Tomorrow from 9:00 you can play again." A join outside the allowed time is refused with a fitting text, such as "Today is not a play day. On Saturday from 9:00 you can play again." or "This world is closed right now. Today from 10:00 it will be open again." A time is only shown when the parents have set a start time; with "whole day" it reads for example "Tomorrow you can play again." The same sentences appear on the Gameworld page of the child.
- Whoever leaves the world has to wait about 2 seconds before joining again ("Please wait a moment and then join again."). This protects the world from a crash of Luanti 5.17.0 on an immediate rejoin.
- Worlds that were already running before this update enforce play times only after the next restart of the world. The dashboard then shows "Restart needed so that playtimes apply.".

### Known behaviour

- Day boundary at 00:00: a child with rules is disconnected at 00:00, even if the plan allows the whole day (fail closed at the day boundary). After the next time tick, about 15 seconds later at most, it can join again.
- When a child joins a world for the very first time, the seconds until the first time tick (about 20 at most) stay uncounted. This happens once per child and world and prevents double counting.

### Failure behaviour

- World restart: changes nothing. The world keeps its own usage ledger in the world volume; after a restart, a crash or a server restart, usage and rules keep applying.
- ExApp restart or update: the worlds keep enforcing the last written state and keep counting. After the start, Gameworld books the usage afterwards.
- ExApp down for longer, same day: the limit keeps applying in every world, but the balancing between worlds rests. Whoever plays in two worlds at the same time can play twice as long until the ExApp returns.
- ExApp down over midnight: children with rules no longer get in after the end of the day until the ExApp runs again (fail closed). Children without rules are not affected.

### Data minimisation

- Gameworld only stores daily totals in seconds and only for children with rules. Children without rules are not counted.
- Daily totals are deleted after 7 days.
- No times of single sessions, no IP addresses. The ledger in the world only contains player names and seconds.

## 11. Parent phone and Talk

### Pause for all worlds

- At the top of the Gameworld page there is the card "Break for all children". It leads to the pause page, which also works well on a phone: 15, 30 or 60 minutes.
- Children get the message "Break in 30 seconds." in the game 30 seconds before and are then disconnected with "Short break! Your parents need you right now. You can keep playing afterwards." Until the end of the pause they do not get in. This applies to all children, also children without play time rules.
- Managers and accounts marked as adult stay in the world and can join at any time.
- "Resume" ends the pause at once. "Done for today" locks until midnight; the child then reads for example "That is it for today. Tomorrow from 9:00 you can play again." If tomorrow is no play day according to the plan, only "That is it for today." is shown.
- The pause does not count towards play time. Time windows keep running: if a window ends during the pause, the pause does not extend it.
- Worlds with an older Gameworld mod are restarted automatically when a pause starts, so the pause takes effect reliably.

### Notifications on the phone

- Gameworld sends hints as ordinary Nextcloud notifications to all managers. On the phone they arrive through the Nextcloud app. Requirement: the app "Notifications" is enabled and the instance can send push (push proxy of the Nextcloud app, default for instances reachable from the internet).
- A tap on the notification opens the matching Gameworld page in the browser. Whoever is not logged in logs in and lands on the page right after.
- Gameworld remembers the address for the links on the first visit of a manager (also with Nextcloud in a sub folder, such as `https://example.org/nextcloud`). If a manager later opens Gameworld through another address, the page asks once: "Open links in notifications through this address from now on?" with the old and the new address. Only after "Yes, this address" the new one applies. Gameworld never replaces an https address with an http address; then no question appears either.

### Hint on a join attempt by a stranger

- If a player name that is not invited tries to join a world, all managers get "Unknown player name in <world>" with name and time. The page "Join attempts" shows all attempts of the day; "Invite someone" invites as usual. Allowing a foreign name directly is deliberately not possible.
- Throttled: at most one hint per name, world and day, at most 5 a day in total, then exactly one summary message "More join attempts".
- No hint on a wrong game password of an invited child and on a different upper and lower case of an invited name.

### Daily review

- Every manager gets the "Daily summary" once in the evening with the minutes played per child, default 20 o'clock. Every manager sets time and on/off in the settings ("Daily summary in the evening").
- The review only comes within half an hour after the set time. If nobody has played by then, none comes that day, even if somebody plays later. Also after a restart it comes at most once a day.
- The review (notification and page) only lists children for whom this household has set play time rules. Invited children without rules, such as friends from other families, never appear with minutes.

### Talk room per world

- If the app Talk is installed, every world gets its own room "Gameworld: <world>". It is never open to everyone and can not be found.
- Members follow the invitations of the world: invited accounts and groups plus all managers. Whoever joins an invited group later appears in the room after the next sync (within 5 minutes). Whoever is added in Talk by hand without being invited is removed again at the sync.
- Managers are moderators. "Read only" in the world row locks writing in the room. Calls follow the Talk defaults of the instance.
- When the world is deleted, Gameworld deletes the room with its history; the delete dialog says so.
- Without Talk, Gameworld keeps working unchanged. If Talk is installed or enabled again later, Gameworld creates the missing rooms at the next sync.

### Who owns the Talk room

- Gameworld keeps one acting owner account per room. If this account is deleted or is no manager any more, the longest-serving manager takes over the room on its own at the next sync.
- Talk itself does not let Gameworld change the owner. A former manager whose account still exists therefore stays owner in the sense of Talk and can keep reading the room. The world card then shows a hint and the button "Recreate room": the old room is deleted with its whole history, the new one gets all invited accounts and managers, but no longer the former manager. This never happens automatically.
- Locked case: if nobody who could manage the old room is left, Gameworld creates a new room and reports the old one. Only a Nextcloud admin on the server can then delete it with `occ talk:room:delete <token>`; the Gameworld page shows the token.

### Gameworld bot

- The bot "Gameworld" writes into the room of the world: "The world has started." and "The world has stopped.", "<Name> is now in the world." and "<Name> has left the world." (at most every 10 minutes per person and world), "Break until H:MM.", "Playtime is over for today.", "The break is over." (on "Resume" and when the pause ends on its own) and "10 minutes of playtime left for <Name>." (at most once a day per child and world, even if it reconnects).
- Display names appear without a real "@" in the bot text, so a name like "@all" pings nobody.
- Only pause, "Playtime is over for today." and the 10-minute warning come with sound. Start, stop, join, leave and the end of the pause come silently.
- The bot does not read the messages of the children.

### Data minimisation

- Gameworld stores no chat content from Talk.
- For the review and the hints, Gameworld only stores daily totals of play time per child with rules and world, and player names and times of join attempts by strangers. Both are deleted after 7 days.
- For throttling the bot messages, Gameworld remembers the time of the last message per world and account, also for 7 days at most. The review setting of an account that is no manager any more is deleted at the next sync. The acting owner account of a Talk room stays stored as long as the room exists (takeover see "Who owns the Talk room").

## 12. Backups

### Where the backups are

- In the management view, every world has the area "Backups". "Back up now" puts a file into your own Nextcloud files: `Gameworld/Backups/<world name>/<world name>-YYYY-MM-DD-HHMM.tar.gz` (time in the household time zone).
- The folder name follows the account language of the manager: `Gameworld/Backups` (English), `Gameworld/Sicherungen` (German), `Gameworld/Sauvegardes` (French). After a language change, older backups stay in their folder and remain in the list.
- The file lies in the files of the manager who made the backup. It can be downloaded, shared or included in your own server backup like any other file.
- The list shows date and size per backup, below it the total size. Gameworld never deletes a backup on its own, not even when the world is deleted. The manager deletes old backups in Nextcloud Files.
- With several managers, each sees only their own backups in the list. Everyone can restore from their own backups only.

### What is backed up and what is not

- The whole world is backed up: map, player data, inventories and game progress (the SQLite files of the world folder).
- Not backed up are the invitations, game passwords, play time rules and the Gameworld mods. They come from Gameworld itself and are set up fresh after the restore, as are the world settings (`world.mt`), which are contained in the file but never taken from it.

### Short pause during a backup

- For a clean backup Gameworld halts the world shortly: children read "The world is taking a short break soon." in the game and are disconnected with "The world is taking a short break. It will be back in a moment." Afterwards the world starts again on its own, usually after a few seconds.
- If children are playing, Gameworld asks first, for example "1 child is playing in the world right now and will be disconnected briefly.". Only after confirming does it start.
- During the backup the world card shows "Backing up ...", the other buttons of the world are locked meanwhile. If the backup fails, for example because the space in the Nextcloud files is not enough, the reason appears on the world card, the world keeps running, and the manager who started the backup gets a notification. The same applies to a failed restore.

### Restore

- "Restore" on a backup resets the world to that state. The confirmation names the file; without confirmation nothing happens.
- Before that, Gameworld stores the current state as its own backup with the suffix `before-restore` next to it. Whoever made a mistake simply restores that file.
- Gameworld checks every backup before applying it: only backups of this world, unchanged since they were stored, are applied. Gameworld refuses a changed or foreign file, and the world then stays as it was.
- Space on the server: a restore temporarily needs up to three times the backup size in free space (downloaded backup, backup of the current state, unpacked world). A backup needs about the single size.

<a id="cleanup"></a>

## 13. Uninstalling and cleaning up

### What stays after uninstalling

- Before uninstalling, AppAPI disables Gameworld. Gameworld then stops and removes all its own world containers (section 8).
- AppAPI removes the Gameworld container. It deletes the data volume `nc_app_gameworld_data` only when "Delete data" is chosen.
- The volumes of the worlds (`gameworld-<instance>-<world>`) and the backups in Nextcloud Files always stay, on purpose: no world is lost silently.
- A reinstall without "Delete data" takes the worlds over again; the game passwords change once (section 9). After "Delete data", a new installation no longer knows the old worlds; their volumes and containers are leftovers then.

### Removing leftovers in the app

- While Gameworld is installed, the section "Leftovers from earlier installations" on the Gameworld page shows containers and game data of other, earlier Gameworld installations on this Docker host. Only Nextcloud admins see this section.
- Every entry can be removed one by one, each with its own confirmation. Gameworld never touches its own worlds or containers without the Gameworld label there.
- Removing game data deletes the world for good. Check for a backup first.

### Leftovers after uninstalling: gameworld-orphans.sh

After the uninstall, a script on the Docker host helps. It needs the docker CLI with rights on the Docker daemon (root or group docker).

```sh
curl -fsSLO https://raw.githubusercontent.com/street1983nk/nextcloud-gameworld/master/scripts/gameworld-orphans.sh
sh gameworld-orphans.sh
```

- Without options the script only lists: containers with the label `gameworld.managed=true` and volumes named after the scheme `gameworld-<instance>-<world>`. It changes nothing.
- `--remove-containers` removes the listed containers after the typed confirmation `yes`.
- `--remove-volumes` deletes the listed volumes and with them the game data inside, always after the typed confirmation `delete`.
- `--yes` only skips the question for containers, never the one for volumes.
- Nextcloud, AppAPI, HaRP, the Docker proxy and other projects are never touched.
- Warning about `--remove-volumes`: the worlds are gone for good afterwards. Check the backups in Nextcloud Files first. If Gameworld is still running, its own worlds are part of the list; the script warns then.
