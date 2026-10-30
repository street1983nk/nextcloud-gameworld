---
phase: quick-261030-sbz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/gameworld/provisioner/proxy_setup.py
  - src/gameworld/api/setup_check.py
  - tests/test_proxy_setup.py
  - frontend/src/components/SetupCheck.vue
  - frontend/src/i18n/de/admin.js
  - frontend/src/i18n/en/admin.js
  - frontend/src/i18n/fr/admin.js
  - docs/install.md
  - docs/install.de.md
  - SECURITY.md
  - CONTRIBUTING.md
  - README.md
  - README.de.md
  - README.fr.md
  - tests/test_docs.py
autonomous: true
requirements: [QUICK-261030-SBZ]

must_haves:
  truths:
    - "When the setup check reports proxy_dns, proxy_refused or proxy_timeout, the Gameworld page shows two ready-to-copy docker run commands (AIO network nextcloud-aio, own Compose with HaRP network gameworld), each with a copy button"
    - "The proxy configuration in these commands (image + digest, every flag, read-only socket, no host port, name gameworld-docker-proxy) comes from one Python constant and a test fails if docs/install.md or docs/install.de.md 3a/3b drift from it (positive control proves detection)"
    - "At 390 px width the command boxes do not make the page scroll sideways"
    - "Labels and hints exist in de/en/fr; frontend i18n tests stay green"
    - "docs/install.md and docs/install.de.md section 7 mention that the page shows these commands"
    - "SECURITY.md and CONTRIBUTING.md exist in the repo root (English), linked by one line in the Documentation section of all three READMEs"
  artifacts:
    - path: "src/gameworld/provisioner/proxy_setup.py"
      provides: "Single source of truth for the scoped proxy (image, flags, mount, networks) and docker run builder"
      contains: "sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459"
    - path: "tests/test_proxy_setup.py"
      provides: "Drift test docs vs constant, with positive controls; command shape tests; API tests"
    - path: "frontend/src/components/SetupCheck.vue"
      provides: "Copyable command boxes"
      contains: "proxy_commands"
    - path: "SECURITY.md"
      provides: "Private vulnerability reporting policy"
    - path: "CONTRIBUTING.md"
      provides: "Dev start, local gates, conventions"
  key_links:
    - from: "src/gameworld/api/setup_check.py"
      to: "src/gameworld/provisioner/proxy_setup.py"
      via: "proxy_commands field built from failed item ids"
      pattern: "proxy_commands"
    - from: "frontend/src/components/SetupCheck.vue"
      to: "/api/setup-check response field proxy_commands"
      via: "result.proxy_commands rendered in pre + copy button"
      pattern: "result\\.value\\?\\.proxy_commands|proxy_commands"
    - from: "tests/test_proxy_setup.py"
      to: "docs/install.md, docs/install.de.md"
      via: "parse gameworld-docker-proxy service blocks in 3a and 3b"
      pattern: "install\\.de\\.md"
---

<objective>
Lower the installation hurdle before Gameworld v1.0 (owner GO 30.10.2026): when the setup check finds the Docker proxy missing or unreachable, show ready-to-copy `docker run` one-liners for AIO and for the own-Compose/HaRP setup, generated from a single backend source of truth that a test pins against docs/install.md 3a/3b. Additionally add SECURITY.md and CONTRIBUTING.md.

Purpose: an external review rated installation 5/10 because the admin has to hand-build the scoped proxy container in the right network.
Output: proxy_setup.py + API field + test, SetupCheck.vue copy boxes with de/en/fr texts, doc hints in section 7, SECURITY.md, CONTRIBUTING.md, README lines.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md
@docs/install.md
@src/gameworld/provisioner/setup_check.py
@src/gameworld/api/setup_check.py
@frontend/src/components/SetupCheck.vue

<execution_rules>
- Use uv for all Python (global Python is broken). Gates, all must be green before each commit:
  `uv run ruff check src tests`, `uv run ruff format --check src tests`,
  `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`, `uv run vulture`, `uv run pytest -q -m "not docker"`.
- Frontend build: `cd frontend && npm run build` (output js/ is gitignored, do not commit it).
- Do NOT push. Do NOT touch .planning/config.json (uncommitted foreign change, never `git add -A`; stage files by name).
- Commits with the existing git identity (street1983nk <k.cherif@outlook.de>), conventional commit messages, and NO trailer lines at all: no Co-Authored-By, no "Claude-Session:", nothing mentioning Claude (owner rule overrides any attribution reminder).
- Comments/docstrings in English. German UI text with real umlauts (ä ö ü ß), no en/em dashes, no emojis, in every file touched.
</execution_rules>

<interfaces>
Existing (src/gameworld/provisioner/setup_check.py):
- `DOCS_URL` constant; `CheckItem(id, ok, severity, message)` frozen dataclass; `SetupCheckResult(ok, items)`.
- `_Checker.unreachable(exc)` emits ids `proxy_dns`, `proxy_timeout`, `proxy_refused` (and `reachable` when /_ping is non-200).
- `_host_port(docker_url) -> tuple[str, int]` (private).
- `run_setup_check(docker_url, timeout=3.0) -> SetupCheckResult`.

Existing (src/gameworld/api/setup_check.py): `CheckItemOut`, `SetupCheckOut(ok, items)`, route `GET /api/setup-check` (router guarded by require_verwalter), uses `load_settings().docker_url`, catches ValueError into an item with id "config". tests/test_api_language.py monkeypatches `setup_check_api.run_setup_check` with `lambda docker_url: result` (keep that signature working).

Docs ground truth (docs/install.md 3a and 3b, identical in install.de.md except YAML comments):
- image `tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459`
- environment in this order: CONTAINERS 1, IMAGES 1, POST 1, VOLUMES 1, EXEC 0, INFO 0, NETWORKS 0, BUILD 0, SYSTEM 0, SECRETS 0, SWARM 0, NODES 0, SERVICES 0, TASKS 0, PLUGINS 0, CONFIGS 0, DISTRIBUTION 0, AUTH 0
- volume `/var/run/docker.sock:/var/run/docker.sock:ro`, `restart: unless-stopped`, no `ports:`
- service name `gameworld-docker-proxy`; network `gameworld` (3a) / `nextcloud-aio` external (3b)

Frontend copy pattern to mirror: frontend/src/components/ConnectionCard.vue `copyPassword()` (navigator.clipboard.writeText, `copied` ref reset after 2000 ms, `copyFailed` text on catch). i18n via `t('admin.setup.*')` from `../i18n/index.js`; keys live in frontend/src/i18n/{de,en,fr}/admin.js under the "// SetupCheck.vue" block.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Backend single source of truth, proxy_commands in the setup-check API, drift test</name>
  <files>src/gameworld/provisioner/proxy_setup.py, src/gameworld/api/setup_check.py, tests/test_proxy_setup.py</files>
  <behavior>
    - docker_run_command("gameworld") and docker_run_command("nextcloud-aio") each contain `--name gameworld-docker-proxy`, `--network <net>`, `--restart unless-stopped`, `-v /var/run/docker.sock:/var/run/docker.sock:ro`, one `-e KEY=VALUE` per flag in PROXY_ENV order, and end with the pinned image; they contain no `-p`, `--publish`, `--privileged`, `HP_SHARED_KEY`, `secret` or `password`.
    - docker_run_command with any network not in the allowed set raises ValueError (no free-text interpolation).
    - Drift test: for docs/install.md and docs/install.de.md, the `gameworld-docker-proxy:` service block of 3a and of 3b yields exactly PROXY_IMAGE, PROXY_ENV (same keys, values, order), the read-only socket mount, `restart: unless-stopped`, no `ports:` key, and network `gameworld` (3a) / `nextcloud-aio` (3b).
    - Positive controls: the same comparison helper applied to the doc text with `EXEC: 0` replaced by `EXEC: 1`, with one digest hex char changed, with the `:ro` removed, with the `AUTH: 0` line deleted, and with a `ports:` line inserted each reports a non-empty drift list.
    - API: when run_setup_check returns a failed item with id proxy_dns, proxy_refused or proxy_timeout and the configured docker_url is the default host gameworld-docker-proxy port 2375, GET /api/setup-check returns `proxy_commands` with two entries in the order compose then aio, each `{id, network, command}`; for an all-ok result, for other failure ids (e.g. containers) and for a non-default docker_url host it returns `proxy_commands: []`; the "config" error path returns `proxy_commands: []`.
  </behavior>
  <action>
    Create src/gameworld/provisioner/proxy_setup.py (module docstring in English explaining it is the single source for the proxy shown in docs/install.md 3a/3b and in the setup check). Public constants: PROXY_NAME = "gameworld-docker-proxy", PROXY_PORT = 2375, PROXY_IMAGE (full tag+digest as above), PROXY_ENV as a tuple of (key, value) string pairs in the documented order, PROXY_SOCKET_MOUNT = "/var/run/docker.sock:/var/run/docker.sock:ro", PROXY_RESTART = "unless-stopped", NETWORK_COMPOSE = "gameworld", NETWORK_AIO = "nextcloud-aio", COMMAND_TRIGGER_IDS = frozenset of proxy_dns, proxy_refused, proxy_timeout. Function docker_run_command(network: str) -> str builds a single-line command (one line on purpose: pastes identically into bash, sh and PowerShell, lowest hurdle; the Compose snippets stay in the docs): `docker run -d --name gameworld-docker-proxy --restart unless-stopped --network <net> -v <mount> -e K=V ... <image>`; raise ValueError for networks other than the two constants. Function proxy_commands(failed_ids: Iterable[str], docker_url: str) -> list[ProxyCommand] (frozen dataclass id/network/command; ids "compose" and "aio") that returns both commands only if failed_ids intersects COMMAND_TRIGGER_IDS and the docker_url host/port equal PROXY_NAME/PROXY_PORT (the commands create exactly that name, so they would not fix a custom GAMEWORLD_DOCKER_URL); reuse the URL parsing from setup_check by making a small public wrapper or importing _host_port via a public alias host_port in setup_check.py only if needed (avoid duplicating parsing logic; if you add a public alias, keep the private name working for existing tests).
    In src/gameworld/api/setup_check.py add ProxyCommandOut(id: Literal["compose","aio"], network: str, command: str) and a field `proxy_commands: list[ProxyCommandOut] = []` on SetupCheckOut; fill it from the failed item ids of the result and docker_url; config-error path leaves it empty. Commands are not translated (language-neutral), so no backend catalog changes are needed.
    Create tests/test_proxy_setup.py: a pure helper `_service_drift(doc_text: str, section_heading_prefix: str, expected_network: str) -> list[str]` that cuts the section between `### 3a.`/`### 3b.` and the next `### `, finds the first fenced yaml block, cuts the `  gameworld-docker-proxy:` service up to the next 2-space-indented key or top-level key, and parses with regex (no new dependency; YAML comments ignored) image, environment `KEY: value` lines in order, volumes, restart, presence of `ports:`, networks; compare against the constants and return human-readable differences. Parametrize over install.md and install.de.md and over 3a/3b. Add the positive controls listed in behavior and the command-shape and API tests (API tests follow the monkeypatch pattern of tests/test_api_language.py: monkeypatch `gameworld.api.setup_check.run_setup_check` and the GAMEWORLD_DOCKER_URL env var or load_settings as the existing tests do). Write the tests first, see them fail, then implement.
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_proxy_setup.py tests/test_setup_check.py tests/test_api_language.py tests/test_docs.py -m "not docker"</automated>
  </verify>
  <done>New tests pass including every positive control; existing setup-check and language tests unchanged and green; ruff, ruff format, pyright (latest), vulture green. Commit: `feat(setup): copyable proxy commands in the setup check from one source`.</done>
</task>

<task type="auto">
  <name>Task 2: SetupCheck.vue copy boxes, de/en/fr texts, doc hint in section 7</name>
  <files>frontend/src/components/SetupCheck.vue, frontend/src/i18n/de/admin.js, frontend/src/i18n/en/admin.js, frontend/src/i18n/fr/admin.js, docs/install.md, docs/install.de.md</files>
  <action>
    In SetupCheck.vue add a computed `proxyCommands` = result.value?.proxy_commands ?? []. Inside the existing error NcNoteCard (after the list), when proxyCommands is non-empty, render a block: a short heading (admin.setup.commandsHeading), a hint paragraph (admin.setup.commandsHint), then for each command (key command.id) a label (admin.setup.commandCompose for id compose, admin.setup.commandAio for id aio), a `<pre class="setup-check__command"><code>{{ command.command }}</code></pre>` and an NcButton copy button (label admin.setup.copyCommand, switching to admin.setup.copied for 2 s for that id only). Copy logic mirrors ConnectionCard.vue copyPassword: navigator.clipboard.writeText inside try/catch; on failure show admin.setup.copyFailed (tell the user to select the text and copy it by hand). Order compose first, aio second as delivered by the API. Never build or alter command text in the frontend (single source stays in the backend).
    Mobile 390 px: the pre must not widen the page: CSS on .setup-check__command with max-width: 100%, box-sizing: border-box, white-space: pre-wrap, overflow-wrap: anywhere, margin and padding small, monospace, background var(--color-background-dark), border-radius var(--border-radius); also min-width: 0 on the containing flex/grid children if any. Wrapping (not inner horizontal scroll) is preferred because the whole command stays visible.
    i18n: add these keys to the "// SetupCheck.vue" block of de, en and fr admin.js with natural texts. Suggested meaning: commandsHeading "Docker-Proxy mit einem Befehl anlegen" / "Create the Docker proxy with one command" / French equivalent; commandsHint: run the matching command on the server as a user with Docker rights, then choose "Erneut prüfen"; it creates the container gameworld-docker-proxy with exactly the settings from the guide and no host port; if a container with that name already exists, remove it first with docker rm -f gameworld-docker-proxy; for own Compose the network gameworld must already exist (created by the HaRP Compose file). commandCompose "Eigenes Compose mit HaRP (Netz gameworld)", commandAio "Nextcloud All-in-One (Netz nextcloud-aio)", copyCommand "Befehl kopieren", copied "Kopiert", copyFailed. German with real umlauts, no dashes, no emojis; French fully French (no German leftovers except proper names already allowed). If tests/test_frontend_i18n.py flags something legitimate (e.g. product names like gameworld-docker-proxy), add a reasoned row to tests/i18n_foreign_exceptions.tsv or tests/frontend_i18n_exceptions.tsv rather than weakening tests.
    Docs: in section 7 of docs/install.md add one short paragraph after the table intro or before the closing sentence: if the proxy is missing or unreachable (proxy_dns, proxy_refused, proxy_timeout), the Gameworld page additionally shows a ready-to-copy docker run command for AIO and for your own Compose file, with the same settings as section 3a/3b. Same in German in docs/install.de.md section 7 (real umlauts). Do not add headings (test_install_versions_share_structure compares heading counts).
  </action>
  <verify>
    <automated>cd frontend && npm run build && cd .. && uv run pytest -q tests/test_frontend_i18n.py tests/test_docs.py -m "not docker" && grep -c "overflow-wrap: anywhere" frontend/src/components/SetupCheck.vue</automated>
  </verify>
  <done>Build succeeds; frontend i18n and docs tests green; all three admin.js files have the same new keys; SetupCheck.vue renders commands only from proxy_commands; CSS wraps long lines. If a local dev stack is running, additionally check at 390 px viewport with Playwright (document.documentElement.scrollWidth <= 390); otherwise state in the summary that the 390 px check is CSS-based and should be part of the owner acceptance. Full Python gate set green. Commit: `feat(setup): show copyable proxy commands on the Gameworld page`.</done>
</task>

<task type="auto">
  <name>Task 3: SECURITY.md, CONTRIBUTING.md, README links</name>
  <files>SECURITY.md, CONTRIBUTING.md, README.md, README.de.md, README.fr.md, tests/test_docs.py</files>
  <action>
    SECURITY.md (English, short, factual): Reporting: privately via GitHub private vulnerability reporting ("Report a vulnerability" under the Security tab, https://github.com/street1983nk/nextcloud-gameworld/security/advisories/new), never a public issue; include version, setup (AIO or own Compose), steps. Supported versions: latest release only. In scope examples: a non-invited player joining a world, escaping or widening the scoped Docker proxy, reading or changing another family's or user's data, leaking game passwords, restore of a manipulated backup archive affecting the host or other worlds, a child account gaining management rights. Out of scope: accepted remaining risks documented in [docs/privacy.md](docs/privacy.md) and docs/install.md section 6. Response: solo maintainer, best effort, aim to acknowledge within about a week; coordinated disclosure after a fixed release.
    CONTRIBUTING.md (English, short): start with docs/dev-setup.md; open an issue before larger changes; required local gates before a PR exactly: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`, `uv run vulture`, `uv run pytest -q -m "not docker"`, and `cd frontend && npm ci && npm run build` (frontend checks run as part of pytest: tests/test_frontend_i18n.py); conventions: comments and docstrings in English, user-visible texts in German, English and French via the i18n dictionaries (frontend/src/i18n, src/gameworld/i18n), German with real umlauts, no em or en dashes, no emojis; conventional commit messages (feat, fix, docs, test, refactor, chore); licence AGPL-3.0-or-later, contributions under the same licence. No dashes U+2013/U+2014 and no emojis in either file.
    READMEs: the "## Documentation" / "## Dokumentation" / French documentation section is the natural place; add exactly one line each: EN "- [Contributing](CONTRIBUTING.md) and [security policy](SECURITY.md)", DE "- [Mitwirken](CONTRIBUTING.md) und [Sicherheitsrichtlinie](SECURITY.md) (Englisch)", FR in French with "(en anglais)". Check the French section heading first and keep existing lines untouched.
    tests/test_docs.py: add ROOT / "SECURITY.md" and ROOT / "CONTRIBUTING.md" to PUBLIC_DOCS so the dash/emoji and relative-link tests cover them.
    Read-only check (do not change remote settings): run `gh api repos/street1983nk/nextcloud-gameworld/private-vulnerability-reporting` and report in the summary whether private vulnerability reporting is enabled; if not, the owner must enable it under Settings, Security (Claude does not change it).
  </action>
  <verify>
    <automated>uv run pytest -q tests/test_docs.py tests/test_frontend_i18n.py -m "not docker" && grep -c "security/advisories/new" SECURITY.md && grep -c "PYRIGHT_PYTHON_FORCE_VERSION=latest" CONTRIBUTING.md</automated>
  </verify>
  <done>Both files exist, covered by docs tests (links resolve, no dashes/emojis); one link line per README; full Python gate set and `uv run pytest -q -m "not docker"` green. Commit: `docs: add SECURITY.md and CONTRIBUTING.md`. Nothing pushed; .planning/config.json untouched.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| browser to /api/setup-check | management-only route (require_verwalter + AppAPI ADMIN), response now contains shell commands the admin will run as root-equivalent |
| docs to running proxy | admin copies commands into a host shell with Docker rights |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-sbz-01 | Tampering | proxy_setup.docker_run_command | mitigate | commands built only from module constants; network restricted to two allowed values (ValueError otherwise); no request data, docker_url or user text interpolated |
| T-sbz-02 | Elevation of privilege | proxy flags in commands | mitigate | drift test pins image digest, every flag (EXEC/INFO/... = 0), :ro mount and absence of ports against docs/install.md and install.de.md, with positive controls |
| T-sbz-03 | Information disclosure | commands in UI | mitigate | no secrets (no HP_SHARED_KEY, no passwords) in commands, asserted by test; route stays verwalter-only |
| T-sbz-04 | Information disclosure | SECURITY.md reporting path | mitigate | reports go to private GitHub advisories, never public issues |
| T-sbz-SC | Tampering | package installs | accept | no new npm/pip packages in this plan |
</threat_model>

<verification>
- `uv run ruff check src tests`, `uv run ruff format --check src tests`, `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`, `uv run vulture`, `uv run pytest -q -m "not docker"` all green.
- `cd frontend && npm run build` succeeds.
- `git log -3 --format=%B` shows no trailer lines; `git status` shows .planning/config.json still modified and unstaged; nothing pushed.
</verification>

<success_criteria>
- Setup-check failure proxy_dns/refused/timeout on the default proxy address shows two copyable one-liners identical in configuration to docs 3a/3b.
- Drift between constant and either install doc fails a test; positive controls prove it.
- de/en/fr texts present, i18n tests green, no sideways scroll at 390 px by CSS.
- SECURITY.md and CONTRIBUTING.md present and linked once per README.
</success_criteria>

<output>
Create `.planning/quick/261030-sbz-setup-check-copy-commands-and-security-c/261030-sbz-SUMMARY.md` when done (include the private vulnerability reporting status and how the 390 px check was done).
</output>
