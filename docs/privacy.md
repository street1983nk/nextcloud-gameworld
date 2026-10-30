<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Privacy, privileges and data flow

Deutsch: [privacy.de.md](privacy.de.md)

**Scope:** what extra privileges Gameworld needs on your server and why, what personal
data it stores, where it stores it, what it never does, and what happens on disabling,
updating and uninstalling. This is a technical description for administrators and
parents, not a legal privacy statement. The instance operator remains the data
controller.

## The short version

Gameworld runs private Luanti game worlds on your own Nextcloud server. It sends no
telemetry, calls no third party of its own and lists no world on any server list. Only
invited Nextcloud accounts can join a world.

To do that, Gameworld needs two things that an ordinary Nextcloud app does not need:
access to Docker through a scoped proxy, and one UDP port per world. Both are explained
below, including the remaining risk. Please read
[What this app may do and why](#what-this-app-may-do-and-why) before you install it.

## What this app may do and why

### 1. Docker access through a scoped docker-socket-proxy

Every world is its own container. Gameworld creates, starts, stops and removes these
containers through `tecnativa/docker-socket-proxy` (v0.5.0, pinned by digest in
[install.md](install.md)). Gameworld never talks to the Docker socket directly.

The proxy allows exactly these parts of the Docker API:

| Flag | Value | Why Gameworld needs it |
|------|-------|------------------------|
| `CONTAINERS` | 1 | create, start, stop and remove world containers, read their state and logs |
| `IMAGES` | 1 | pull the pinned Luanti image `ghcr.io/luanti-org/luanti:5.17.0` |
| `POST` | 1 | every changing request (create, start, stop, remove, copy files into a world) |
| `VOLUMES` | 1 | create and delete the volume that holds a world |
| everything else | 0 | `EXEC`, `INFO`, `NETWORKS`, `BUILD`, `SYSTEM`, `SECRETS`, `SWARM`, `NODES`, `SERVICES`, `TASKS`, `PLUGINS`, `CONFIGS`, `DISTRIBUTION`, `AUTH` stay closed |

The honest part: with `CONTAINERS=1` and `POST=1`, anyone who can reach the proxy can
create a container with any volume mounted, including the host file system. That is
practically root on the host. The proxy can not limit which containers are created.

How the risk is contained:

- The proxy runs only in the Docker network of Gameworld, never with a host port, not
  even on `127.0.0.1`.
- The setup check in Gameworld warns when `GAMEWORLD_DOCKER_URL` points at a raw Docker
  socket or at an address outside private networks.
- Gameworld itself only creates fixed, hardened world containers (see point 4) and only
  touches containers that carry its own instance label.

The remaining risk: every container in the same Docker network can reach the proxy. With
Nextcloud All-in-One the proxy sits in the network `nextcloud-aio`, so every AIO
container, Nextcloud itself included, can reach it. Other ExApps in the same deploy
network can reach it as well. If that is not acceptable for your server, do not install
Gameworld.

### 2. One UDP port per world, home network only

- Each world gets one UDP port from `GAMEWORLD_PORT_RANGE` (default `30000-30019`).
- The worlds are meant for the home network. Do not forward these ports in the router
  and do not use UPnP. Remote play is planned through a VPN, not through open ports.
- A port alone does not let anyone in: the world mod `gameworld_access` refuses every
  player name that is not invited, before the login. Invited players need their game
  password.
- No world is ever listed on any server list (`server_announce = false` in every world).

### 3. The app container runs unprivileged

The Gameworld container runs as uid 10001, without any root step at start. Its own code
is owned by root and can not be changed by the running app.

### 4. World containers are hardened

- Each world runs as user 30000, not root, with all capabilities dropped,
  `no-new-privileges`, a read-only root file system, 512 MB memory (adventure world
  1 GB) without swap, 1 CPU and at most 128 processes.
- New and restored worlds get a root-owned world folder with sticky bit and a root-owned
  `worldmods` folder, so the Luanti process can not change or remove the access file, the
  rules file or the Gameworld mods.
- Nobody gets Luanti admin rights. Children never get privileges in the game.

## What the app stores

Gameworld keeps one SQLite database in its own volume `nc_app_gameworld_data`. It holds:

| Data | Form and purpose |
|------|------------------|
| Worlds | name, port, container and volume name, game type, language of the in-game texts, desired state, last error |
| Invitations | world, invited account or group, who invited, when |
| Player names | one game name per Nextcloud account plus a counter for "new password" |
| Game passwords | never stored. They are derived on demand from a secret in the ExApp configuration of Nextcloud. Each world only receives an SRP verifier, not the password |
| Play time rules | weekly plan, holiday plan, time windows per world, holidays of the household |
| Daily usage | daily totals in seconds, only for children with rules, deleted after 7 days. No session times, no IP addresses |
| Join attempts of unknown names | player name and time, deleted after 7 days |
| Bot throttle | time of the last Talk message per world and account, at most 7 days |
| Daily review settings | time and on/off per manager |
| Adult marking | account, which manager set it, when |
| Manager groups | the extra groups a Nextcloud admin added; the group `admin` always manages |
| Manager history | since when an account manages Gameworld (used to pick the new owner of a Talk room) |
| Talk rooms | world, room token, acting owner account, read-only flag |
| Backup list | file id, path, size and SHA-256 of each backup in Nextcloud Files |
| Settings | address for players, time zone, base address for notification links |

Inside each world volume (`gameworld-<instance>-<world>`) Luanti keeps the map, player
inventories and its own account data. Gameworld adds the access file (player names and
SRP verifiers), the rules file and a usage ledger with player names and seconds.

## What the app never does

- No telemetry, no usage statistics, no call home.
- Worlds need no internet access. Gameworld pulls the pinned Luanti image once.
- No world on any server list, no setting that makes a world visible on the internet.
- No privileges for children, neither in Gameworld nor in the game.
- Adults marked with the adult switch play without pause, time windows and play time
  limits, but they never get management rights or Luanti admin rights.
- No reading of Talk messages. The Gameworld bot only writes; the webhook discards every
  incoming message unread.
- No deleting of backups. Gameworld never removes a backup file on its own.

## What leaves your control

- **Backups** are files in Nextcloud Files of the manager who created them, under
  `Gameworld/Sicherungen/<world>/`. From there they follow your Nextcloud: sharing,
  external storage, server backups.
- **Talk** (if installed): every world gets its own room. Messages of the bot and of the
  members are stored by Talk, not by Gameworld. Room members follow the invitations of
  the world plus all managers.
- **Notifications** to managers (unknown join attempts, daily review, failed backups) are
  ordinary Nextcloud notifications. On a phone they travel through the push proxy that
  the Nextcloud app uses.
- **Players** connect from their Luanti client to the world in your home network. What a
  client stores locally is outside of Gameworld.

## Deletion and user control

- **Deleted accounts:** Gameworld forgets a deleted Nextcloud account (invitations,
  player name, rules, usage, adult marking) once a Nextcloud admin has opened Gameworld.
  Managers without Nextcloud admin rights never trigger this, because Nextcloud hides
  accounts outside their groups from them.
- **Deleting a world** removes its container, its volume and its Talk room with the
  history. Backups stay in Files.
- **Disabling and updates:** Every time Gameworld is disabled, also right before an
  update or an uninstall, it stops and removes all its world containers. Players are
  disconnected for a short moment. Volumes and backups stay, and the worlds come back on
  their own when Gameworld runs again.
- **Uninstalling:** AppAPI removes the Gameworld container. The data volume
  `nc_app_gameworld_data` is only deleted when you choose to delete the data. The world
  volumes and the backups in Files always stay on purpose, so no world is lost silently.
- **Cleaning up:** Nextcloud admins see leftovers of earlier installations in the
  Gameworld section "Leftovers from earlier installations" and can remove them one by one. After
  the uninstall, `scripts/gameworld-orphans.sh` on the Docker host lists the leftovers and
  removes them on request, see [install.md](install.md#cleanup).

## Retention

| Data | Kept for |
|------|----------|
| Daily usage, unknown join attempts, bot throttle | 7 days |
| Worlds, invitations, rules, player names | until deleted by a manager or until the account is forgotten |
| Adult marking | until switched off or until the account is forgotten |
| Backups | until a manager deletes the file in Nextcloud Files |
| World volumes after uninstall | until removed with the cleanup list or `gameworld-orphans.sh` |
