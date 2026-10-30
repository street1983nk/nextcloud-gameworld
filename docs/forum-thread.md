<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Forum thread for Gameworld on help.nextcloud.com

Status: draft, posted by the owner

Thread URL:

This is the draft of the own Gameworld thread in the Nextcloud forum (category "Apps", D-28). Only the owner posts it. After posting, the thread URL goes into the line above and, as the only `discussion` element, into `appinfo/info.xml`. The forum is English, so the thread text is English.

## Title

Gameworld: private Luanti game worlds for families and schools on your own Nextcloud

## Text

Gameworld is an External App (ExApp) that runs private Luanti game worlds on your own Nextcloud server. Parents and teachers create a world with one click, invite children and friends through their Nextcloud accounts and groups, and keep world backups in Nextcloud Files.

What it does:

- Worlds with one click: creative building or a gentle adventure
- Only invited Nextcloud accounts or groups can join; every other player name is refused before the login
- One game password per account, never stored; worlds only receive a verifier
- Play time per child across all worlds, holidays, time windows per world and a pause for all children from the phone
- Adult switch: marked adults play without pause and play time rules, never with management rights
- Manager groups for schools and clubs, set by Nextcloud admins
- Backups in Nextcloud Files, checked before every restore
- One Talk room per world with a Gameworld bot, if Talk is installed
- No telemetry

Requirements:

- Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon
- A scoped docker-socket-proxy in the same Docker network as Gameworld, set up by the admin

Extra privileges, in short:

- Docker access through the scoped proxy: Gameworld creates, starts, stops and removes one container per world. Whoever reaches this proxy controls Docker with root-equivalent rights on the host, so it stays inside the Docker network of Gameworld and never on a host port.
- One UDP port per world (default 30000 to 30019), meant for the home network only. No port forwarding, and no world is listed on any server list.
- Details and the remaining risk: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/privacy.md

Languages: the interface is German, English and French and follows the language of the Nextcloud account; in-game texts and the Talk room follow the language chosen per world.

Links:

- Repository: https://github.com/street1983nk/nextcloud-gameworld
- Installation guide: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md
- Bug reports: https://github.com/street1983nk/nextcloud-gameworld/issues

Questions, feedback and experiences with Gameworld belong in this thread. Bugs with steps to reproduce are easiest to track as a GitHub issue.
