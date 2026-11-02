---
phase: quick-261102-tdb
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/gameworld/provisioner/network_probe.py
  - src/gameworld/provisioner/proxy_setup.py
  - src/gameworld/api/setup_check.py
  - tests/test_network_probe.py
  - tests/test_proxy_setup.py
  - tests/test_roles.py
  - frontend/src/components/SetupCheck.vue
  - frontend/src/i18n/de/admin.js
  - frontend/src/i18n/en/admin.js
  - frontend/src/i18n/fr/admin.js
  - frontend/tests/setupcheck.check.mjs
  - docs/install.md
  - docs/install.de.md
autonomous: true
requirements: [OWNER-GO-261102-2, OWNER-GO-261102-3, OWNER-GO-261102-4]

must_haves:
  truths:
    - "If Gameworld runs as AppAPI container nc_app_gameworld in exactly one user-defined Docker network, the setup check shows ONE proxy command plus Compose download for exactly that network (e.g. nextcloud-aio or gameworld), determined without new rights and without Docker socket"
    - "If the network cannot be determined, the setup check shows the two documented standard commands (gameworld, nextcloud-aio) plus a third one with the clearly marked placeholder <docker-network>, and says honestly that detection failed"
    - "Every shown proxy command has a Compose file download with identical content: digest-pinned image, CONTAINERS=1 IMAGES=1 VOLUMES=1 POST=1, rest 0, read-only socket, no ports"
    - "While the check is not green, the page re-checks by itself (15 s, after 20 runs 60 s), turns green without reload once the proxy answers, and stops polling when green, when the tab is hidden or when the view is left"
    - "The setup check offers copyable ufw and firewalld commands for exactly the configured GAMEWORLD_PORT_RANGE, LAN only, with placeholder <lan-network> and the hint no router port forwarding, no UPnP"
    - "Children (non-managers) get 403 on /api/setup-check and never see any command; commands are only displayed, never executed"
  artifacts:
    - path: "src/gameworld/provisioner/network_probe.py"
      provides: "detect_docker_network(): PTR lookup of own IPv4 at Docker embedded DNS 127.0.0.11, stdlib only"
      exports: ["detect_docker_network", "parse_ptr_response", "build_ptr_query"]
    - path: "src/gameworld/provisioner/proxy_setup.py"
      provides: "docker_run_command, compose_file, proxy_commands(detected), firewall_commands"
      exports: ["compose_file", "firewall_commands", "NETWORK_PLACEHOLDER", "LAN_PLACEHOLDER"]
    - path: "frontend/tests/setupcheck.check.mjs"
      provides: "static check: polling lifecycle, no client-built commands"
  key_links:
    - from: "src/gameworld/api/setup_check.py"
      to: "detect_docker_network"
      via: "anyio.to_thread.run_sync, only when a proxy-missing finding exists and docker_url is the default"
      pattern: "detect_docker_network"
    - from: "frontend/src/components/SetupCheck.vue"
      to: "result.proxy_commands[].compose / result.firewall"
      via: "Blob download + copy buttons, texts from admin i18n"
      pattern: "firewall"
---

<objective>
Make the Gameworld setup check easier, exactly the three owner-approved points of 02.11.2026 (nothing beyond):
(2) proxy copy command with the REAL Docker network name of the running Gameworld (honest fallback with marked placeholder) plus a Compose file download,
(3) self re-check in the background until green, no reload, no permanent polling,
(4) copyable LAN-only firewall commands (ufw, firewalld) for the configured UDP range.

Purpose: a parent without server knowledge gets the right command for their installation and sees the check turn green by itself. Kinderprodukt: no new rights, no Docker socket, no host port, commands are only shown.
Output: backend network probe + extended setup-check API, extended SetupCheck.vue (DE/EN/FR), docs section 7, tests, SUMMARY with every new text verbatim.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md
@src/gameworld/provisioner/proxy_setup.py
@src/gameworld/api/setup_check.py
@frontend/src/components/SetupCheck.vue
@tests/test_proxy_setup.py
@docs/install.md

<findings_from_planning>
Verified during planning (do not re-research):
- AppAPI exposes NO daemon/network info to an ExApp: OCS `/api/v1/ex-app/info/{appId}` returns only id, name, version, enabled, status (ExAppService::formatExAppInfo); `/daemons` routes are admin settings routes. So AppAPI cannot deliver the network without new rights.
- AppAPI names the ExApp container `nc_app_<appid>` (DockerActions::EX_APP_CONTAINER_PREFIX = 'nc_app_', buildExAppContainerName), so ours is `nc_app_gameworld`.
- Docker embedded DNS (127.0.0.11, only in user-defined networks) answers a PTR query for a container IP with `<container_name>.<network_name>`. Measured in the dev stack: reverse lookup of the proxy IP 172.21.0.2 gave `gameworld-dev-gameworld-docker-proxy-1.gameworld-dev_default`.
- `socket.gethostbyaddr(own_ip)` does NOT work for the own IP: /etc/hosts maps it to the container hostname first (measured: `1ac2f7726a31`). Hence a direct UDP PTR query to 127.0.0.11 is needed. No new dependency (no dnspython): hand-built query/parser with stdlib `socket`, `struct`, `secrets`.
- Dev stack: ExApp runs manual-install on the host (not in a container), dev proxy address differs from the default, so the dev page shows no commands (by design, unchanged). Proxy container: `gameworld-dev-gameworld-docker-proxy-1` in network `gameworld-dev_default`; NC container `gameworld-dev-app-1`; page http://localhost:8091. Image `python:3.13-slim-trixie` is present locally.
- Access today: router `/api/setup-check` has `Depends(require_verwalter)` (managers incl. admin), NOT admin-only. Keep exactly that (no widening, no narrowing). tests/test_roles.py ADMIN_ROUTES already asserts 403 for KID on GET /api/setup-check with run_setup_check forbidden.
- Frontend i18n `t(key, {name})` supports `{name}` placeholders (frontend/src/i18n/index.js PLACEHOLDER). All `frontend/tests/*.check.mjs` run automatically via tests/test_frontend_checks.py.
- Settings: `load_settings().port_range: tuple[int, int]` (validated, default 30000-30019, max 200 ports).
</findings_from_planning>

<interfaces>
Existing (src/gameworld/provisioner/proxy_setup.py):
- PROXY_NAME, PROXY_PORT, PROXY_IMAGE (digest pinned), PROXY_ENV (ordered tuple), PROXY_SOCKET_MOUNT, PROXY_RESTART, NETWORK_COMPOSE="gameworld", NETWORK_AIO="nextcloud-aio", _ALLOWED_NETWORKS, COMMAND_TRIGGER_IDS={"proxy_dns","proxy_refused","proxy_timeout"}
- @dataclass(frozen) ProxyCommand(id: Literal["compose","aio"], network: str, command: str)
- docker_run_command(network: str) -> str  (raises ValueError for other networks)
- _is_default_address(docker_url) -> bool
- proxy_commands(failed_ids, docker_url) -> list[ProxyCommand]

Existing (src/gameworld/api/setup_check.py): SetupCheckOut(ok, items, proxy_commands: list[ProxyCommandOut] = []); ProxyCommandOut(id, network, command); route GET /api/setup-check, router dependency require_verwalter, run_setup_check via anyio.to_thread.

Existing (SetupCheck.vue): emits 'update:ok' and 'checked' (ParentView reloads the world list on 'checked'); COMMAND_LABELS {compose, aio}; copyCommand(); check() with `checking` guard; onMounted(check).
Existing DE keys: admin.setup.notReady, unreachable, proxyWarning, recheck, commandsHeading, commandsHint, commandCompose, commandAio, copyCommand, copied, copyFailed.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Backend: network probe, network-aware commands, Compose text, firewall commands, API</name>
  <files>src/gameworld/provisioner/network_probe.py, src/gameworld/provisioner/proxy_setup.py, src/gameworld/api/setup_check.py, tests/test_network_probe.py, tests/test_proxy_setup.py, tests/test_roles.py</files>
  <behavior>
    - build_ptr_query("172.21.0.5", qid) yields a standard DNS query for 5.0.21.172.in-addr.arpa, QTYPE PTR (12), QCLASS IN, RD set, given ID.
    - parse_ptr_response(packet, qid) returns "nc_app_gameworld.nextcloud-aio" for a crafted valid answer (also with a compression pointer); returns None for wrong ID, QR bit unset, RCODE != 0, ANCOUNT 0, truncated packet, pointer loop, label over 63 or name over 255 bytes.
    - detect_docker_network(): with monkeypatched resolv.conf content lacking `nameserver 127.0.0.11` returns None without sending anything; with PTR answer `nc_app_gameworld.nextcloud-aio` returns "nextcloud-aio"; `nc_app_gameworld.gameworld` returns "gameworld"; `other_container.gameworld` (prefix mismatch) returns None; two own IPs answering two different networks returns None; a network part like "x;rm -rf /", "$(id)", "-evil", "" or over 128 chars returns None; socket timeout/OSError returns None (never raises).
    - docker_run_command accepts the two documented networks, any name matching the strict network regex, and NETWORK_PLACEHOLDER "<docker-network>"; still raises ValueError for "gameworld; rm -rf /", "$(id)", "a b", "", "-x", "--privileged".
    - proxy_commands(failed, default_url, detected="nextcloud-aio") returns exactly one ProxyCommand id="detected" network="nextcloud-aio"; with detected=None returns compose, aio, other (other uses the placeholder); non-trigger findings or non-default address still return [] (unchanged).
    - Every ProxyCommand carries compose = compose_file(network); the existing docs drift helper in tests/test_proxy_setup.py reports NO drift when applied to compose_file(network) (same image digest, env order/values, ro socket, restart), and the text contains no "ports".
    - firewall_commands((30000, 30019)) returns ufw: `sudo ufw allow proto udp from <lan-network> to any port 30000:30019` and firewalld: `sudo firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="<lan-network>" port port="30000-30019" protocol="udp" accept' && sudo firewall-cmd --reload`; for (30000, 30000) the single port form (`port 30000`, `port="30000"`).
    - API: GET /api/setup-check as manager returns `firewall` {port_range: "30000-30019", commands: [ufw, firewalld]} whenever settings load (also when ok), and proxy_commands with `compose`; detect_docker_network is called only when a trigger finding exists and the address is the default (monkeypatch spy asserts not called otherwise); config error answer has no proxy_commands and firewall null.
    - Negative: KID gets 403 on GET /api/setup-check, response body contains neither "docker run", "ufw" nor "firewall-cmd" (extend tests/test_roles.py); run_setup_check and detect_docker_network are never called for KID.
  </behavior>
  <action>
    Owner-GO point 2 and 4, backend part. RED first: write tests/test_network_probe.py and extend tests/test_proxy_setup.py / tests/test_roles.py per behavior, run, see them fail, commit `test(quick-261102-tdb): ...`. Then GREEN.

    New module src/gameworld/provisioner/network_probe.py, stdlib only (socket, struct, secrets, re, ipaddress), English docstring explaining WHY: AppAPI does not expose the daemon network to an ExApp (see findings), so Gameworld asks Docker's embedded DNS for the PTR record of its own IPv4, which is `<container>.<network>`; no rights, no Docker socket, read-only, nothing is changed. Constants: DOCKER_DNS = "127.0.0.11", DNS_PORT = 53, TIMEOUT_S = 1.0, CONTAINER_NAME = "nc_app_gameworld" (AppAPI prefix nc_app_ + APP_ID; import APP_ID from wherever lifecycle.py gets it if that import stays lightweight, else literal with comment), NETWORK_RE = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$". Functions: build_ptr_query(ip, qid) -> bytes; parse_ptr_response(packet, qid) -> str | None (validate header ID, QR=1, RCODE=0, QDCOUNT skip, first PTR answer; name decoding with compression pointers bounded to 16 hops and 255 bytes, ASCII only, return None on any anomaly, never raise); _read_resolv_conf() reading /etc/resolv.conf (OSError -> None) so tests can monkeypatch it; _own_ipv4() via socket.getaddrinfo(socket.gethostname(), None, AF_INET) deduplicated, only private addresses (ipaddress), loopback excluded; detect_docker_network() -> str | None: requires a line `nameserver 127.0.0.11`, for each own IP sends one UDP query (fresh socket, settimeout 1.0, random qid via secrets.randbits(16), recv 512 bytes, only accept datagrams from 127.0.0.11:53), takes the name, strips trailing dot, requires prefix CONTAINER_NAME + ".", remainder must match NETWORK_RE; exactly one distinct network -> return it, else None. Catch OSError/TimeoutError/struct.error/UnicodeError -> None. No caching (only runs on the failure path), no background thread.

    proxy_setup.py: extend docstring (detected network from network_probe, strictly validated; placeholder variant). Add NETWORK_PLACEHOLDER = "<docker-network>" and LAN_PLACEHOLDER = "<lan-network>" (both fail safe: `<` makes bash/PowerShell refuse the line, firewall-cmd rejects the address, so a pasted placeholder never runs with a wrong value). Replace the `_ALLOWED_NETWORKS` gate in docker_run_command with `_valid_network(network)`: documented networks, NETWORK_PLACEHOLDER, or full match of the same NETWORK_RE (import it from network_probe so there is one regex). Add compose_file(network) -> str: deterministic YAML text, two-space indent, exactly: services, gameworld-docker-proxy, image PROXY_IMAGE, restart PROXY_RESTART, environment with every PROXY_ENV pair as `KEY: value` in order, volumes `- PROXY_SOCKET_MOUNT`, networks `- <network>`, then top-level networks with `<network>:` and `external: true`; no ports key, no comments (no user-visible prose in the file). Same validation as docker_run_command. ProxyCommand gets id Literal["detected","compose","aio","other"] and field compose: str. proxy_commands(failed_ids, docker_url, detected_network: str | None): unchanged early return; detected (and valid) -> [detected]; else [compose, aio, other(NETWORK_PLACEHOLDER)]. Add @dataclass FirewallCommand(id: Literal["ufw","firewalld"], command: str) and firewall_commands(port_range: tuple[int, int]) -> list[FirewallCommand] building exactly the two strings from the behavior block from ints only (assert 1 <= low <= high <= 65535, else []).

    api/setup_check.py: ProxyCommandOut gains id Literal of the four ids and compose: str; new FirewallCommandOut(id, command) and FirewallOut(port_range: str, commands: list[FirewallCommandOut]); SetupCheckOut gains `firewall: FirewallOut | None = None`. In the route: after run_setup_check, compute failed_ids; only if `COMMAND_TRIGGER_IDS` intersects failed_ids and `_is_default_address(docker_url)` (expose a public helper `commands_wanted(failed_ids, docker_url)` in proxy_setup instead of importing the private one) call `await anyio.to_thread.run_sync(detect_docker_network)`, then proxy_commands(failed_ids, docker_url, detected). firewall = FirewallOut from settings.port_range (format "low-high"). Config-error branch unchanged (firewall None). Router dependency require_verwalter unchanged, no new route, no new permission, nothing executed. Comments English.

    Keep the existing tests green (adapt the ones that assert exactly compose+aio to the new fallback list of three; keep test_docker_run_command_rejects_other_networks semantics with the injection strings listed in the behavior).
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && uv run pytest -q tests/test_network_probe.py tests/test_proxy_setup.py tests/test_setup_check.py tests/test_roles.py tests/test_api_language.py -m "not docker" && uv run ruff check src tests && uv run ruff format --check src tests && PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright && uv run vulture</automated>
  </verify>
  <done>All behavior cases pass; network_probe.py imports stdlib only; no new dependency in pyproject.toml/uv.lock; KID negative test asserts 403 and no command strings; RED and GREEN commits exist.</done>
</task>

<task type="auto">
  <name>Task 2: Frontend: detected/fallback commands, Compose download, firewall section, self re-check (DE/EN/FR)</name>
  <files>frontend/src/components/SetupCheck.vue, frontend/src/i18n/de/admin.js, frontend/src/i18n/en/admin.js, frontend/src/i18n/fr/admin.js, frontend/tests/setupcheck.check.mjs</files>
  <action>
    Owner-GO points 2, 3, 4, frontend part. Commands and Compose text stay backend-built (single source of truth); the component never assembles a command.

    Labels: extend COMMAND_LABELS with detected -> 'admin.setup.commandDetected' (with {network} from command.network), other -> 'admin.setup.commandOther'. If no entry has id "detected" but proxyCommands is non-empty, show the paragraph 'admin.setup.networkNotDetected' above the entries. Per entry add a second secondary NcButton 'admin.setup.downloadCompose' that downloads command.compose as file `gameworld-docker-proxy.yaml` via Blob (type text/yaml) + temporary object URL + programmatic anchor click, URL revoked right after; below the entries one paragraph 'admin.setup.composeHint'.

    Firewall: below the note cards, when result.firewall is set, a native `<details class="setup-check__firewall">` with `<summary>` 'admin.setup.firewallHeading' ({range} = firewall.port_range), then 'admin.setup.firewallHint', then per command a label ('admin.setup.firewallUfw' / 'admin.setup.firewallFirewalld'), the same `<pre><code>` style as the proxy commands and a copy button reusing copyCommand (generalise copiedId keys so ufw/firewalld/proxy ids do not collide, e.g. prefix 'fw-'). Visible also when the check is green (the firewall cannot be checked from inside). Reuse existing wrapping CSS so 390 px works.

    Self re-check (point 3): setTimeout chain, never setInterval. After each check() run, if the component is still mounted, document.hidden is false and the result is not ok (result.ok !== true or unreachable), schedule the next automatic check: 15000 ms for the first 20 automatic runs, then 60000 ms. Clear the timer when ok, on document visibilitychange to hidden (on visible again and not ok: run check() at once, which re-arms), and in onBeforeUnmount (also remove the visibilitychange listener, clear the copied timer, set a `stopped` flag so an in-flight request does not re-arm). The `checking` guard stays, so manual and automatic runs never overlap; a manual "Erneut prüfen" resets the automatic counter. Emit 'checked' for the initial and manual runs and for automatic runs only when the ok state changed (otherwise ParentView would reload the world list every 15 s); 'update:ok' as before. Add one line 'admin.setup.autoRecheck' under the error card while polling is active.

    i18n: add these DE keys verbatim (real umlauts, no U+2013/U+2014, no emojis) and EN/FR equivalents with identical placeholders and literal `<docker-network>`/`<lan-network>`/command words untouched:
    'admin.setup.commandDetected': 'Netz {network} (aus der laufenden Gameworld ermittelt)'
    'admin.setup.commandOther': 'Anderes Netz: ersetze <docker-network> durch den Netznamen deines Deploy-Daemons'
    'admin.setup.networkNotDetected': 'Das Docker-Netz von Gameworld ließ sich nicht automatisch ermitteln. Nimm den Befehl für deine Installation. Läuft dein Deploy-Daemon in einem anderen Netz, nimm den letzten Befehl und ersetze den Platzhalter <docker-network>.'
    'admin.setup.downloadCompose': 'Compose-Datei herunterladen'
    'admin.setup.composeHint': 'Statt des Befehls geht auch die Compose-Datei: speichern und auf dem Server mit docker compose -f gameworld-docker-proxy.yaml up -d starten. Sie enthält dieselben Einstellungen, ohne Host-Port.'
    'admin.setup.autoRecheck': 'Gameworld prüft von selbst regelmäßig erneut und wird grün, sobald der Docker-Proxy antwortet.'
    'admin.setup.firewallHeading': 'Firewall: UDP-Ports {range} nur im Heimnetz freigeben'
    'admin.setup.firewallHint': 'Führe auf dem Server den Befehl für deine Firewall aus und ersetze vorher <lan-network> durch dein Heimnetz in der Form Netzadresse/Präfixlänge, wie es dein Router anzeigt. Keine Portweiterleitung im Router und kein UPnP: Welten sind nur fürs Heimnetz gedacht.'
    'admin.setup.firewallUfw': 'ufw (zum Beispiel Ubuntu, Debian)'
    'admin.setup.firewallFirewalld': 'firewalld (zum Beispiel Fedora, RHEL, openSUSE)'
    Also adjust the existing 'admin.setup.commandsHint' in all three languages only as far as needed so it no longer claims both networks always appear (keep its other statements: no host port, docker rm -f first, gameworld network must exist for own Compose).

    New frontend/tests/setupcheck.check.mjs (style of api.check.mjs, German assert messages like the others): asserts SetupCheck.vue uses setTimeout and clearTimeout, contains no setInterval, registers and removes 'visibilitychange', has onBeforeUnmount, uses URL.revokeObjectURL, and contains no literal 'docker run', 'ufw allow', 'firewall-cmd' or 'docker-socket-proxy' (no client-built commands); asserts all new keys exist in de/en/fr admin.js. Then `cd frontend && npm run build` (js/ output is gitignored, do not commit it).
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && node frontend/tests/setupcheck.check.mjs && (cd frontend && npm run build) && uv run pytest -q tests/test_frontend_checks.py tests/test_frontend_i18n.py tests/test_i18n.py -m "not docker" && node scripts/audit/selftest.mjs && uv run python scripts/audit/dump_catalog.py > /dev/null</automated>
  </verify>
  <done>Build green; all frontend checks green; new keys present in DE/EN/FR with matching placeholders; no setInterval; no command string literals in the component.</done>
</task>

<task type="auto">
  <name>Task 3: Docs section 7, live verification in the dev stack, full gates, SUMMARY</name>
  <files>docs/install.md, docs/install.de.md</files>
  <action>
    Docs (point 2, 3, 4; only section 7, short, EN and DE in parallel, real umlauts in DE, no U+2013/U+2014): replace the last paragraph about the docker run commands with: Gameworld determines its Docker network itself (asks Docker's internal name service for its own container `nc_app_gameworld`, no extra rights) and then shows one command for exactly this network; if that fails it shows the commands for your own Compose file (`gameworld`) and AIO (`nextcloud-aio`) plus one with the placeholder `<docker-network>`; every command can also be downloaded as Compose file with the same settings (section 3a/3b, no host port). Add: while something is missing, the page checks again by itself every 15 seconds (later every minute) and turns green without reload; it stops when green or when you leave the page. Add: the firewall commands for ufw and firewalld for the configured `GAMEWORLD_PORT_RANGE`, LAN only, replace `<lan-network>`, no port forwarding and no UPnP (section 5). Run tests/test_docs.py and tests/test_proxy_setup.py.

    Live checks (no background wait loops; foreground only; never touch worlds/volumes 788fff30-*, a60510fd-*; do not touch .planning/config.json):
    a) Real Docker DNS positive control: restart the dev ExApp with the new code the way scripts/dev/register-exapp.sh / .dev/exapp.pid do it, then in Git Bash with MSYS_NO_PATHCONV=1 run a throwaway `docker run --rm --name nc_app_gameworld --network gameworld-dev_default -v C:/Users/Student/gameworld/src/gameworld/provisioner:/probe:ro python:3.13-slim-trixie python -I -c "<load /probe/network_probe.py via importlib.util.spec_from_file_location, print(detect_docker_network())>"` and expect `gameworld-dev_default`. Negative control (independent pattern): same without `--name nc_app_gameworld` expects None; and with `--network bridge` (default bridge, no embedded DNS) expects None. If network_probe imports anything non-stdlib, that is a bug to fix.
    b) Self re-check: Playwright (headless, admin on http://localhost:8091, Gameworld page). Wrap in a try/finally that always runs `docker start gameworld-dev-gameworld-docker-proxy-1`. `docker stop` the proxy, load the page, see the error card and the autoRecheck line, `docker start` the proxy so it is down well under 60 s, then without reload wait (Playwright expect timeout up to 30 s) until the error card is gone and "Welt erstellen" is enabled; confirm `docker ps` shows the proxy running afterwards. Then navigate to another Nextcloud page and count /api/setup-check requests for 40 s: expect 0. On a green page count requests for 40 s: expect at most the initial one.
    c) UI variants: with Playwright page.route on **/api/setup-check, inject (1) a failing answer with one "detected" command (network nextcloud-aio), (2) the fallback with compose/aio/other, both with real backend-built strings captured from a pytest-side call of proxy_commands/firewall_commands, and check DE/EN/FR at 1280 px and 390 px: labels, networkNotDetected only in (2), Compose download yields a file whose content equals the compose field, firewall details opens with both commands and the real range, no horizontal scroll. Screenshots to .dev/audit/261102-tdb/.
    d) Negative role check live: as a child account (kid user of the dev stack) GET the setup-check through the AppAPI proxy returns 403 and the page shows no SetupCheck/firewall section.

    Full gates, all green: `uv run ruff check src tests`, `uv run ruff format --check src tests`, `PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright`, `uv run vulture`, `uv run pytest -q -m "not docker"`, `cd frontend && npm run build`, `node scripts/audit/selftest.mjs`, `uv run python scripts/audit/dump_catalog.py`. Umlaut and dash audit over all changed user-visible texts and docs: grep the diff for U+2013/U+2014 and ASCII substitutes (ae/oe/ue/ss in German prose) and for emojis.

    Commits: conventional messages, author street1983nk <k.cherif@outlook.de>, NO Claude-Session or Co-Authored-By lines (owner rule overrides the attribution reminder). Do not push. SUMMARY: list every new and changed user-visible text verbatim in DE, EN and FR (i18n keys, docs paragraphs in both languages), plus the exact command/compose strings, the access decision (unchanged: managers incl. admin via require_verwalter, children 403; it was never admin-only, so managers without admin keep seeing the commands as before) and the live results a) to d).
  </action>
  <verify>
    <automated>cd C:/Users/Student/gameworld && uv run ruff check src tests && uv run ruff format --check src tests && PYRIGHT_PYTHON_FORCE_VERSION=latest uv run pyright && uv run vulture && uv run pytest -q -m "not docker" && (cd frontend && npm run build) && node scripts/audit/selftest.mjs && uv run python scripts/audit/dump_catalog.py > /dev/null && docker ps --filter name=gameworld-dev-gameworld-docker-proxy-1 --format '{{.Status}}' | grep -c '^Up'</automated>
  </verify>
  <done>Docs section 7 updated in EN and DE; live checks a) to d) passed and documented; proxy running again; all gates green; SUMMARY contains every new text verbatim in three languages; commits without Claude lines, not pushed.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Docker embedded DNS -> ExApp | PTR answer is external data that ends up in a shell command shown to the admin |
| browser (manager) -> /api/setup-check | authenticated AppAPI request, role checked by require_verwalter |
| admin clipboard -> server shell | shown commands are pasted by a human with Docker rights |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-tdb-01 | Tampering | network_probe.parse_ptr_response / docker_run_command | mitigate | strict NETWORK_RE full match (alnum start, only [A-Za-z0-9_.-], max 128), required prefix nc_app_gameworld., query ID check, source address check 127.0.0.11:53, bounded name decoding; anything else -> None -> documented fallback; injection strings tested |
| T-tdb-02 | Elevation of Privilege | proxy command / compose_file | mitigate | built only from module constants plus validated network; no host port, ro socket, CONTAINERS/IMAGES/VOLUMES/POST=1 rest 0; drift test against docs; nothing is executed by Gameworld |
| T-tdb-03 | Information Disclosure | /api/setup-check | mitigate | router dependency require_verwalter unchanged; KID 403 test asserts no command strings and that probe/check are never called |
| T-tdb-04 | Denial of Service | auto re-check polling | mitigate | setTimeout chain only while not green and tab visible, 15 s then 60 s, no overlap (checking guard), stopped on unmount; probe only on failure path, 1 s UDP timeout |
| T-tdb-05 | Spoofing | placeholders <docker-network>, <lan-network> | mitigate | placeholders make the pasted line fail safely (shell parse error, firewall-cmd invalid address), never a guessed LAN or network |
| T-tdb-06 | Elevation of Privilege | firewall commands | mitigate | source restricted to LAN placeholder, UDP range from validated settings ints only; UI and docs say no port forwarding, no UPnP |
</threat_model>

<verification>
- Unit: PTR builder/parser, detection with prefix and validation, fallback, compose drift, firewall strings, API fields, KID 403.
- Live: real Docker DNS returns the dev network for a container named nc_app_gameworld (negative controls None); proxy stop/start under 60 s turns the page green without reload; no polling after leaving the page or when green.
- Gates: ruff, ruff format, pyright basic (latest), vulture, pytest, frontend build + checks, selftest.mjs, dump_catalog.py.
</verification>

<success_criteria>
- Point 2: one command + Compose download for the real network when detectable; otherwise standard commands plus marked placeholder variant; no new rights, no Docker socket, no host port.
- Point 3: background re-check until green, ends on green or leaving the view, no permanent polling.
- Point 4: ufw/firewalld commands for the configured range, LAN placeholder, hint no port forwarding, no UPnP.
- All new texts DE/EN/FR, real umlauts, no U+2013/U+2014, no emojis, verbatim in SUMMARY; docs section 7 updated in both languages.
</success_criteria>

<output>
Create `.planning/quick/261102-tdb-gameworld-setup-check-einfacher/261102-tdb-SUMMARY.md` when done.
</output>
