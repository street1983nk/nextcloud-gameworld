# Security policy

Gameworld runs game servers for children on a home server and talks to Docker through a scoped proxy. Security reports are very welcome.

## Reporting a vulnerability

Report privately via GitHub private vulnerability reporting: open the Security tab of this repository and choose "Report a vulnerability", or go directly to https://github.com/street1983nk/nextcloud-gameworld/security/advisories/new.

Please never open a public issue for a vulnerability.

Include:

- the Gameworld version (Nextcloud, "Apps", Gameworld)
- your setup: Nextcloud All-in-One or your own Compose file with HaRP
- the steps to reproduce and what you expected instead

## Supported versions

Only the latest release gets security fixes.

## In scope

For example:

- a player who was not invited joining a world
- escaping or widening the scoped Docker proxy, or reaching Docker endpoints beyond the documented flags
- reading or changing the data of another family or another user
- leaking game passwords
- restoring a manipulated backup archive that affects the host or other worlds
- a child account gaining management rights

## Out of scope

The remaining risks that are accepted and documented in [docs/privacy.md](docs/privacy.md) and in section 6 of [docs/install.md](docs/install.md).

## Response

Gameworld is maintained by one person, so handling is best effort. The aim is to acknowledge a report within about a week. Disclosure is coordinated: details are published after a release with the fix is available.
