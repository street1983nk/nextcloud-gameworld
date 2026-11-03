# Release audit tooling

Repeatable full test of Gameworld before a store release: language check of every
view, dialog and message (de, en, fr), layout check (desktop and 390 px), functional
and permission tests against throw-away worlds, load times.

## Prerequisites

- Dev stack running (`scripts/dev/compose.yaml`, Nextcloud on http://localhost:8091,
  ExApp registered), accounts `admin`, `gw-lehrer`, `mia` with the dev passwords.
- `uv` (Python side) and Node 20+.
- Playwright is not a project dependency. Point `NODE_PATH` at an existing npx cache,
  e.g. `NODE_PATH=<npm-cache>/_npx/<hash>/node_modules` (same pattern as
  `scripts/dev/screenshot-capture.mjs`).

## Text sources of the detector

- Frontend: `frontend/src/i18n/<lang>/index.js` (all areas).
- Server (`dump_catalog.py`): `gameworld.i18n.catalog_en` / `catalog_fr`,
  in-game texts `provisioner.access_mod.MOD_TEXTS` and `provisioner.time_mod.MOD_TEXTS`,
  notifications and Talk bot `notify.texts.NOTIFY_TEXTS` / `BOT_TEXTS`,
  backup suffix `backup.naming.PRE_RESTORE_SUFFIXES`.

## Order

```sh
uv run python scripts/audit/dump_catalog.py .dev/audit/server.json
node scripts/audit/selftest.mjs . .dev/audit/server.json          # must exit 0
NODE_PATH=... node scripts/audit/layout_selftest.mjs                # layout probe controls, must exit 0
NODE_PATH=... node scripts/audit/audit.mjs . .dev/audit/261102       # language + layout
NODE_PATH=... node scripts/audit/functional.mjs . .dev/audit/261102  # actions + permissions
NODE_PATH=... node scripts/audit/loadtimes.mjs . .dev/audit/261102   # load times
NODE_PATH=... node scripts/audit/cleanup.mjs . .dev/audit/261102     # leftovers (--dry-run to list)
```

`audit.mjs` writes `baseline-worlds.json` on its first run; `functional.mjs` needs it.
`functional.mjs` accepts `SECTIONS=1,2,3,4,5` to run parts separately; `audit.mjs`
accepts `LANGS` and `USERS`. Shared helpers live in `common.mjs`, the in-page layout
probe in `layout_probe.mjs`.

Output goes to `.dev/audit/<run>/` (gitignored): `baseline.txt`, `report.json`,
`functional.json`, `loadtimes.json`, `shots/`, text dumps.

## Safety rules

- Never touch existing worlds, containers or volumes (instance prefixes `788fff30-`,
  `a60510fd-`). The scripts only stop or delete worlds they created themselves
  (name prefix `audit261102-`) and check every ID against `baseline.txt` first.
- At most two throw-away worlds at the same time, all removed at the end.
- Account language settings (`core lang`) are recorded before the run and restored
  exactly afterwards (an unset value is deleted again).
- Destructive confirmation dialogs are only opened and cancelled, never confirmed.
