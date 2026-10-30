---
phase: quick-261030-sbz
plan: 01
status: complete
subsystem: setup-check, docs
tags: [setup-check, docker-proxy, install, security-policy, contributing]
requires: []
provides:
  - "proxy_setup.py: single source for the scoped proxy (image digest, flags, mount, networks) and docker run builder"
  - "GET /api/setup-check field proxy_commands (compose, aio) for proxy_dns/refused/timeout on the default address"
  - "SetupCheck.vue copy boxes in de/en/fr"
  - "SECURITY.md, CONTRIBUTING.md"
affects: [docs/install.md, docs/install.de.md, README.md, README.de.md, README.fr.md]
tech-stack:
  added: []
  patterns: ["docs drift test with positive controls against a Python constant"]
key-files:
  created:
    - src/gameworld/provisioner/proxy_setup.py
    - tests/test_proxy_setup.py
    - SECURITY.md
    - CONTRIBUTING.md
  modified:
    - src/gameworld/api/setup_check.py
    - frontend/src/components/SetupCheck.vue
    - frontend/src/i18n/de/admin.js
    - frontend/src/i18n/en/admin.js
    - frontend/src/i18n/fr/admin.js
    - docs/install.md
    - docs/install.de.md
    - README.md
    - README.de.md
    - README.fr.md
    - tests/test_docs.py
decisions:
  - "Commands only when GAMEWORLD_DOCKER_URL is tcp/http on gameworld-docker-proxy:2375 (strict check of its own, because setup_check._host_port falls back to the default host for unix:// and would wrongly trigger)"
  - "One-line docker run (pastes identically in bash, sh, PowerShell); Compose snippets stay in the docs"
  - "Secret check in the command test excludes the flag SECRETS=0, which closes the secrets endpoint"
metrics:
  completed: 2026-10-30
  tasks: 3
---

# Quick 261030-sbz: Setup-check copy commands, SECURITY.md and CONTRIBUTING.md Summary

When the setup check reports proxy_dns, proxy_refused or proxy_timeout on the default proxy address, the Gameworld page now shows two ready-to-copy `docker run` one-liners (own Compose with HaRP, network gameworld; AIO, network nextcloud-aio), built from one backend constant that a drift test pins against docs/install.md and install.de.md 3a/3b; plus SECURITY.md and CONTRIBUTING.md.

## Commits

| Task | Commit | Subject |
|------|--------|---------|
| 1 | f0bd683 | feat(setup): copyable proxy commands in the setup check from one source |
| 2 | 24ca112 | feat(setup): show copyable proxy commands on the Gameworld page |
| 3 | a178aa1 | docs: add SECURITY.md and CONTRIBUTING.md |

## Tests and counter-checks

- tests/test_proxy_setup.py: 49 tests (drift docs vs constant for 2 docs x 2 sections, 20 positive controls: EXEC 1, digest changed, `:ro` removed, AUTH line deleted, ports added; wrong network; command shape; rejected networks; trigger logic; API with and without commands, config error path).
- Counter-checks (each change reverted afterwards): EXEC=1 in PROXY_ENV, 4 drift tests fail; default-address check disabled, 4 tests fail; API not filling proxy_commands, 3 API tests fail; em dash plus broken link in SECURITY.md, 2 docs tests fail.
- RED first: test file failed on import before proxy_setup.py existed.
- Full suite: `uv run pytest -q -m "not docker"`: 2960 passed, 52 deselected (6:48).
- Gates: ruff check, ruff format --check, pyright (latest, 0 errors), vulture green.

## Live check (dev stack, Playwright)

- The dev ExApp uses GAMEWORLD_DOCKER_URL tcp://127.0.0.1:23750 (not the default), so the proxy was not stopped. Instead the /api/setup-check response was replaced in the browser by the real backend output for a missing default proxy (run_setup_check against tcp://gameworld-docker-proxy:2375 from the host gave a real proxy_dns item; proxy_commands from proxy_setup; messages via translate per language). The API wiring itself is covered by the pytest API tests.
- de, en, fr at 390 px and 1280 px: commands shown match the backend exactly, copy button switches to "Kopiert"/"Copied"/"Copié" for that entry only, clipboard holds the AIO command, `#app-content-vue` scrollWidth == clientWidth (390/390, 1264/1264).
- First run found 403 > 390 at 390 px: the note card content (flex child) grew to the long guide URL in the error message. Fixed with `overflow-wrap: anywhere` on the list and `min-width: 0` on the note card content; before/after is the counter-check (403 vs 390).
- Admin account language reset to de.

## Private vulnerability reporting

`gh api repos/street1983nk/nextcloud-gameworld/private-vulnerability-reporting` returns `{"enabled":false}`. Owner must enable it under Settings, Security ("Private vulnerability reporting"); until then the link in SECURITY.md does not accept reports.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Horizontal overflow at 390 px in the error note card**
- Found during: Task 2 live check
- Issue: the long docs URL in the existing error item widened the flex child of NcNoteCard to 403 px
- Fix: overflow-wrap anywhere on the list, min-width 0 on the note card content
- Commit: 24ca112

**2. [Rule 1 - Test precision] "secret" check vs. flag SECRETS=0**
- The plan asked that commands contain no "secret"; the documented flag `SECRETS=0` contains it. The test strips exactly `-e SECRETS=0` before checking.
- Commit: f0bd683

## Deferred Issues (pre-existing, not touched)

- `node frontend/tests/i18n.check.mjs` fails on `core.backup.kilobytes` (en same as de without exception entry) and `node frontend/tests/api.check.mjs` fails on an import pattern in api.js; both files are untouched by this plan.

## Threat model

T-sbz-01 to 04 mitigated as planned: commands only from constants, network allow-list (ValueError), no request data interpolated, drift test pins digest, flags, `:ro` and no ports; no HP_SHARED_KEY or passwords in commands (test); route stays verwalter-only.

## Self-Check: PASSED
