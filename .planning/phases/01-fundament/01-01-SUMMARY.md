---
phase: 01-fundament
plan: 01
subsystem: provisioner, worlds-api
tags: [walking-skeleton, provisioner, docker, luanti, sqlite]
requires: []
provides:
  - "DockerProvisioner mit Guard _guarded() (DockerUnavailableError bei jedem Transportfehler)"
  - "world_spec() gehärtete Container-Spec, render_minetest_conf()/render_world_mt()/normalize_world_name()"
  - "build_world_payload() mit vendortem, SHA256-gepinntem minetest_game"
  - "WorldStore (SQLite meta + worlds), allocate_port(), WorldService.create_world/list_worlds"
  - "GET/POST /api/worlds, get_service()-Dependency, main.APP mit AppAPIAuthMiddleware"
  - "Dev-Compose gameworld-dev: NC 34.0.3 + gameworld-docker-proxy auf 127.0.0.1:23750"
affects: [01-02, 01-03, 01-04]
tech-stack:
  added: [nc-py-api 0.30.3, fastapi 0.143.2, uvicorn 0.54.0, docker 7.2.0, ruff 0.17.1, pyright 1.1.414, vulture 2.16, pytest 9.1.1, pytest-asyncio 1.4.0, httpx 0.28.1]
  patterns: [sync docker-py über anyio.to_thread, Kontextmanager-Guard für Fehlerabbildung, Label- und Instanzprüfung vor jeder Mutation, Docker als Quelle des Ist-Zustands]
key-files:
  created:
    - pyproject.toml
    - scripts/dev/compose.yaml
    - src/gameworld/config.py
    - src/gameworld/main.py
    - src/gameworld/api/worlds.py
    - src/gameworld/provisioner/spec.py
    - src/gameworld/provisioner/luanti_conf.py
    - src/gameworld/provisioner/archive.py
    - src/gameworld/provisioner/client.py
    - src/gameworld/worlds/store.py
    - src/gameworld/worlds/ports.py
    - src/gameworld/worlds/service.py
    - vendor/games/minetest_game-38214.zip
    - tests/e2e/test_create_world_e2e.py
  modified: []
decisions:
  - "uvicorn[standard]==0.54.0 direkt gepinnt; nc-py-api 0.30.3 lässt 0.54.0 zu, der Fallback 0.52.3 war nicht nötig"
  - "Guard bildet Daemon-Antworten ab: NotFound -> WorldNotFoundError, übrige APIError -> ProvisionerError mit deutscher Meldung (nie DockerUnavailableError), damit kein roher docker-Fehler die API erreicht"
  - "start() und discard() prüfen gameworld.managed und gameworld.instance am Container; fremde Container werden nie gestartet oder entfernt"
  - "list_worlds zeigt docker_status unknown bei jeder ProvisionerError, nicht nur bei DockerUnavailableError"
  - "minetest_game-SHA256 5b364f6b0cf31ec336319492e14106d932eb86b65a91ded99f4b25f4876519dc"
metrics:
  duration: "11 min"
  completed: "2026-10-19"
  tasks: 3
  files: 34
---

# Phase 1 Plan 01: Walking Skeleton Provisioner und Welt-API Summary

Ein signierter POST auf /api/worlds erzeugt über den gescopten tecnativa-Proxy einen laufenden Luanti-5.17.0-Container (per Digest gepinnt) mit festen Limits (512m mem = swap, 128 pids, 1 CPU, cap_drop ALL, no-new-privileges, read-only, uid 30000), benanntem Volume und root-eigener 0444-minetest.conf ohne Serverlisten-Anmeldung. Als default_password dient ein zufälliger Weltschlüssel. Der Soll-Zustand liegt in SQLite, der Ist-Zustand kommt aus Docker.

## Tasks

| Task | Name | Commit |
|------|------|--------|
| 1 | Projektgerüst, Dev-Proxy und rote Tests | 56b779f |
| 2 | Provisioner-Schicht (Spec, conf, Tar, Docker-Client mit Guard) | 4ffe39c |
| 3 | SQLite-Store, Welt-Service, Welt-API (503 statt 500) | c7eb7cd |

## Verifikation

- `GAMEWORLD_REQUIRE_DOCKER=1 uv run pytest -q -rs`: 37 passed, kein SKIPPED (e2e lief gegen den echten Proxy)
- ruff check, ruff format --check, pyright (0 errors, `PYRIGHT_PYTHON_FORCE_VERSION=latest`), vulture: alle Exit 0 auf dem ganzen Projekt
- Gegenprobe außerhalb der Tests: `curl http://127.0.0.1:23750/_ping` = OK, `POST /exec/gameworld-probe/start` = 403
- Nach dem Lauf: keine Container mit `gameworld.managed=true`, keine `gameworld-*`-Volumes übrig (Cleanup greift)
- grep-Gates: docker-py nur unter `provisioner/`, kein `server_announce = true` in src, `world_key` nie in einer Log-Zeile

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] ruff format schrieb Codeblöcke in .planning/*.md um**
- **Found during:** Task 1
- **Issue:** ruff 0.17.1 formatiert Python-Codeblöcke in Markdown; `ruff format .` hat 01-RESEARCH.md und research/ARCHITECTURE.md verändert.
- **Fix:** Änderungen zurückgenommen (`git checkout --` auf genau diese zwei Dateien), `extend-exclude = [".planning"]` in `[tool.ruff]`.
- **Commit:** 56b779f

**2. [Rule 3 - Blocking] isort hielt gameworld für Drittanbieter, solange die Module fehlten**
- **Fix:** `[tool.ruff.lint.isort] known-first-party = ["gameworld", "tests"]`.
- **Commit:** 56b779f

**3. [Rule 3 - Blocking] tests/__init__.py ergänzt**
- **Issue:** Tests importieren den Helper `appapi_headers` aus `tests.conftest`; ohne Paket nicht importierbar.
- **Commit:** 56b779f

**4. [Rule 2 - Kritisch] Guard bildet auch APIError ab**
- **Issue:** Laut Plan sollte der Guard APIError unverändert durchlassen. Dann käme z. B. ein 403 des Proxys (fehlender Scope) als roher docker-Fehler bis in die API (500 mit Stacktrace, T-01-33).
- **Fix:** NotFound -> WorldNotFoundError, sonstige APIError -> ProvisionerError mit deutscher Meldung. Weiterhin nie DockerUnavailableError; die Methoden behandeln ImageNotFound, NotFound und den Port-Konflikt vorher selbst.
- **Commit:** 4ffe39c

**5. [Rule 2 - Kritisch] Label- und Instanzprüfung in start() und discard()**
- **Issue:** Research Pitfall 1 verlangt die Prüfung vor jeder Mutation, damit über den pfadbasierten Proxy nie fremde Container (z. B. Findling, Nextcloud) angefasst werden.
- **Fix:** `_owned()` verlangt `gameworld.managed=true` und die eigene `gameworld.instance`; Test `test_foreign_container_is_not_started`.
- **Commit:** 4ffe39c

**6. [Rule 2 - Kritisch] create_world_container räumt bei gescheitertem put_archive selbst auf**
- **Issue:** Scheitert `put_archive`, kennt der Service die Container-ID noch nicht und kann nicht aufräumen.
- **Fix:** Container und Volume werden im Provisioner entfernt, bevor der Fehler weitergeht.
- **Commit:** 4ffe39c

**7. [Rule 1 - Bug] .gitignore um `.claude-active` ergänzt**
- **Issue:** Sitzungs-Markerdateien der Werkzeugkette lagen untracked im Repo und in .planning.
- **Commit:** 56b779f

### Hinweise

- `uvicorn[standard]==0.54.0` ließ sich mit nc-py-api 0.30.3 auflösen; der im Plan genannte Fallback 0.52.3 war nicht nötig.
- Im venv ist `urllib3` das Paket `urllib3-future` 2.25.902 (über niquests aus nc-py-api). `urllib3.exceptions.ProtocolError` existiert dort, requests und docker-py laufen damit; der Guard fängt die Klasse aus genau diesem Modul.
- TDD in Task 2 und 3: Die Tests zum Fehlervertrag (`test_provisioner_errors.py`, `test_service_unavailable.py`) sind zusammen mit der Implementierung entstanden, nicht in einem eigenen roten Lauf vorher. Der RED-Gate-Commit für den Gesamtplan ist 56b779f.

## TDD Gate Compliance

- RED: 56b779f `test(01-01): ...` (Lauf rot durch ImportError)
- GREEN: 4ffe39c und c7eb7cd `feat(01-01): ...`
- REFACTOR: nicht nötig

## Known Stubs

- `src/gameworld/main.py` `enabled_handler` gibt nur `""` zurück. Das ist Absicht: Top-Menü und Skript-Registrierung folgen in Plan 01-02 (`lifecycle.py`).

## Threat Flags

Keine neue Angriffsfläche außerhalb des Threat Models. Der Proxy-Port ist nur auf Loopback publiziert (T-01-01), alle übrigen Mitigations (T-01-02 bis T-01-09, T-01-33, T-01-SC) sind umgesetzt und per Test belegt.

## Self-Check: PASSED

- Dateien vorhanden: pyproject.toml, scripts/dev/compose.yaml, src/gameworld/{config,main}.py, api/worlds.py, provisioner/{spec,luanti_conf,archive,client}.py, worlds/{store,ports,service}.py, vendor/games/*, tests/* (alle 34 aus files_modified plus tests/__init__.py)
- Commits vorhanden: 56b779f, 4ffe39c, c7eb7cd
