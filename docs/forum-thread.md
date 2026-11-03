<!--
  - SPDX-FileCopyrightText: 2026 street1983nk
  - SPDX-License-Identifier: AGPL-3.0-or-later
-->

# Forum thread for Gameworld on help.nextcloud.com

Status: posted by the owner, approved 03.11.2026

Thread URL: https://help.nextcloud.com/t/gameworld-private-luanti-game-worlds-for-families-and-schools-on-your-own-nextcloud/251686

This is the draft of the own Gameworld thread in the Nextcloud forum (category "Apps", D-28). Only the owner posts it. After posting, the thread URL goes into the line above and, as the only `discussion` element, into `appinfo/info.xml`. The forum is English, so the thread text is English.

## Title

Gameworld: private Luanti game worlds for families and schools on your own Nextcloud

## Text

Hi everyone,

I have been building Gameworld, an External App that runs private Luanti game worlds on your own Nextcloud. Parents or teachers create a world with one click, invite kids and friends through their Nextcloud accounts or groups, and the backups end up in Nextcloud Files. Everything stays on your own server.

What you get:

- Creative or gentle adventure worlds, one click each
- Only invited accounts or groups get in, any other name is turned away before the login
- One game password per account. Gameworld does not store it, the world only gets a verifier
- Play time per child across all worlds, holidays, time windows per world and a pause for all kids that also works from the phone
- An adult switch: adults play without the time rules, but never get management rights
- Manager groups for schools and clubs, set by the Nextcloud admin
- Backups in Nextcloud Files, checked before every restore
- A Talk room per world with a small bot, if Talk is installed
- No telemetry

What you need: Nextcloud 33 to 35 with AppAPI and a HaRP deploy daemon, plus a scoped docker-socket-proxy in the same Docker network. The setup check finds that network for you and gives you a command or a Compose file to copy. I tested it on Docker Compose with Nextcloud 34 and 35 and on All-in-One with HaRP.

A word on privileges, because they matter here. Gameworld talks to Docker through that proxy to create, start, stop and remove one container per world. Whoever can reach the proxy has root-equivalent rights on the host, so keep it inside the Docker network of Gameworld and never publish it on a host port. Each world also needs one UDP port (30000 to 30019 by default), meant for your home network only: no port forwarding, and worlds never show up on public server lists. The details and the remaining risk are here: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/privacy.md

The interface is in German, English and French and follows your Nextcloud language. In-game texts and the Talk room use the language chosen for each world.

What comes next: for version 2 I want to add Minecraft Java Edition (once I have checked its licence terms), dedicated servers for Steam games and bigger worlds. Right now a world holds up to 8 players at the same time.

That is also why I am looking for a pilot: a school, a club or a public organisation that would like to try it with a larger group, say a class of 30. If that sounds interesting, reply here or send me a message. I speak German, English and French.

Links:

- Repository: https://github.com/street1983nk/nextcloud-gameworld
- Installation guide: https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md
- Bug reports: https://github.com/street1983nk/nextcloud-gameworld/issues

Questions and feedback are welcome here. For bugs with steps to reproduce, a GitHub issue is easiest.
