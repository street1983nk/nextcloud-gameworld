---
phase: 06-store-release
plan: 10
subsystem: image
tags: [docker, image, harp, ci, ghcr, release, supply-chain, d-14, d-18, d-22]
requires: ["06-02", "06-05"]
provides:
  - "Dockerfile: vier Stufen (Node-Bundle, Spiele gegen SHA256SUMS, uv sync --frozen --no-dev, Laufzeit python:3.13-slim) mit fest USER 10001:10001"
  - "scripts/image/start.sh (HaRP, unverändert), entrypoint.sh (Klartext-FRP-Wächter + Volume-Schreibprüfung), healthcheck.sh (unverändert)"
  - ".github/workflows/image.yml: Tag v* = Multi-Arch-Image + Release mit Store-Archiv; workflow_dispatch image_tag = nur Image (rc)"
  - "scripts/build-store-release.sh: dist/gameworld-<version>.tar.gz mit gameworld/{appinfo/info.xml,img/app.svg,LICENSE}"
  - "Version 1.0.0 im Lockstep (info.xml version + image-tag, pyproject, uv.lock), NC 32 bis 35"
affects: [06-11, 06-12, 06-14, 06-16]
tech-stack:
  added: []
  patterns:
    - "Jede FROM-Zeile per Index-Digest, uv per Digest, frpc per SHA-256-Konstante je TARGETARCH"
    - "Editierbare Installation, src/ unter /app/src root-eigen: archive.py findet vendor/games über parents[3] = /app"
    - "Lockstep-Prüfung als Workflow-Schritt plus test_image_tag_lockstep"
    - ".gitattributes *.sh eol=lf, damit lokale Builds unter core.autocrlf=true keine CRLF-Skripte ins Image kopieren"
key_files:
  created:
    - Dockerfile
    - .dockerignore
    - .gitattributes
    - scripts/image/start.sh
    - scripts/image/entrypoint.sh
    - scripts/image/healthcheck.sh
    - .github/workflows/image.yml
    - scripts/build-store-release.sh
    - tests/test_image_build.py
  modified:
    - .gitignore
    - appinfo/info.xml
    - pyproject.toml
    - uv.lock
    - tests/test_info_xml.py
decisions:
  - "D-22 umgesetzt wie vom Owner am 24.10. bestätigt: fest USER 10001:10001, kein chown/gosu, kein root-Moment; Entrypoint bricht bei nicht schreibbarem Volume mit klarer Meldung ab"
  - "uv sync ohne --no-editable: archive.py löst vendor/games relativ zum Quellbaum auf; src/ liegt root-eigen unter /app/src, vorab per compileall übersetzt"
  - "Spiele-Stufe nutzt dieselbe python:3.13-slim-Basis (Debian trixie slim) statt eines eigenen Debian-Digests"
  - "python:3.13-slim auf aktuellen Index-Digest 57b29a7c... (nicht den älteren Connector-Digest)"
  - "login-action v4.7.0 (Plan-Pin), nicht v4.6.0 aus dem Connector"
metrics:
  duration: "ca. 20 min"
  completed: "2026-10-24"
  tasks: 3
  files: 14
---

# Phase 6 Plan 10: ExApp-Image, Multi-Arch-Workflow, Store-Archiv, Version 1.0.0 Summary

Mehrstufiges, durchgehend per Digest/SHA gepinntes ExApp-Image, das fest als uid 10001 läuft, mit HaRP-start.sh, Volume- und Klartext-FRP-Wächter; dazu ein Multi-Arch-Workflow nach ghcr.io mit Lockstep-Prüfung, ein POSIX-Store-Archiv-Skript und Version 1.0.0 für NC 32 bis 35.

## Commits

| Task | Commit | Inhalt |
|------|--------|--------|
| 1 | 47aa5af | Dockerfile, .dockerignore, .gitattributes, scripts/image/*, tests/test_image_build.py |
| 2 | 7f22d67 | .github/workflows/image.yml, scripts/build-store-release.sh, .gitignore (dist/), Tests |
| 3 RED | 857c923 | test_info_xml: 1.0.0, test_image_tag_lockstep, max-version 35 |
| 3 GREEN | 5f9b557 | info.xml 1.0.0 / image-tag 1.0.0 / max-version 35, pyproject 1.0.0, uv.lock |

## Lokaler Bau und Laufprobe (amd64, Docker 29.5.2)

- `docker build -t gameworld:local-test .`: Exit 0. frpc `/tmp/frp.tar.gz: OK`, `mineclone2-39534.zip abgelegt und geprüft`, `sha256sum -c SHA256SUMS` beide Zeilen OK, Bundle `js/gameworld-main.js` 1146 kB.
- Bildgröße: 163 MB komprimiert (`docker save | gzip`, 162 920 595 Byte), 497 MB entpackt. Ziel unter 400 MB komprimiert erfüllt.
- Laufprobe ohne HP_SHARED_KEY mit frischem Volume gw-img-test:
  - Health `healthy` nach ca. 8 s
  - `curl http://127.0.0.1:23000/heartbeat`: 200
  - `id`: uid=10001(exapp) gid=10001(exapp)
  - `/nc_app_gameworld_data` 10001:10001 0700, darin `gameworld.sqlite3` (exapp-eigen); `/certs` 10001:10001 0700; `/frpc.toml` 10001:10001 0600
  - `/app/src`, `/app/.venv`, `/app/js`, `/app/vendor/games` root-eigen; `touch` dort als 10001: Permission denied
  - `archive.GAMES_DIR` im Container = `/app/vendor/games` (existiert)
  - Log: Abgleich meldet erwartbar, dass der Docker-Proxy fehlt; Start nicht blockiert
- Negativproben:
  - Volume per `chown 0:0` auf root gestellt: Container endet mit Exit 1 und der Meldung "Gameworld: APP_PERSISTENT_STORAGE ist nicht schreibbar für uid 10001. ..." (D-22-Restfall)
  - `HP_SHARED_KEY` gesetzt, keine Zertifikate, `FRP_CERT_WAIT_SECONDS=2`: Exit 1, "Refusing to start" (T-06-44)
- Aufgeräumt: Container gw-img-test/gw-img-neg/gw-img-frp, Volume gw-img-test und Image gameworld:local-test entfernt; kein globales builder prune. Dev-Stack und Owner-Welten unberührt.
- Hinweis: Das geprüfte Image enthielt noch appinfo 0.1.0 (Bau vor Task 3); der Versionswechsel betrifft im Image nur die kopierte info.xml.

## Gates

- `uv run pytest -m "not docker" -q`: 2517 passed, 44 deselected
- `uv run pytest -q tests/test_image_build.py`: 14 passed (Pins, Dienstnutzer, Skripte, Workflow-SHA-Pins, Plattformen, Rechte, kein --clobber, Archivaufbau)
- ruff check, ruff format --check, pyright latest (0 errors), vulture: ohne Befund
- `uv lock --check`: OK
- `sh -n` entrypoint.sh, healthcheck.sh, build-store-release.sh; `bash -n` start.sh: OK
- actionlint nicht verfügbar: YAML per PyYAML geparst (Auslöser, Inputs, Rechte je Job geprüft); Lockstep-Schritt lokal mit bash simuliert: v0.1.0 bei 0.1.0 = 0, v0.2.0 = 1, image_tag 0.1.0-rc.1 und 0.1.0 = 0, 0.1.0-beta und 0x1x0 = 1
- Store-Archiv lokal: genau `gameworld/` mit appinfo/info.xml, img/app.svg, LICENSE, Besitzer 0:0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `--no-editable` hätte die Spiele im Image unauffindbar gemacht**
- **Found during:** Task 1
- **Issue:** `archive.py` setzt `GAMES_DIR = parents[3]/vendor/games`. Bei `--no-editable` liegt das Modul in `.venv/lib/python3.13/site-packages/...`, `parents[3]` wäre `/app/.venv/lib`; jedes Welt-Anlegen wäre mit "Spieldatei fehlt" gescheitert.
- **Fix:** `uv sync --frozen --no-dev` (editierbar), `src/` root-eigen nach `/app/src` kopiert, vorab `compileall`. Kein Python-Code geändert. Im Container belegt: `GAMES_DIR = /app/vendor/games`.
- **Files modified:** Dockerfile
- **Commit:** 47aa5af

**2. [Rule 2 - Kritisch] `.gitattributes` mit `*.sh eol=lf`**
- **Found during:** Task 1
- **Issue:** `core.autocrlf=true`; mehrere vorhandene Skripte liegen im Arbeitsbaum bereits als CRLF vor. Ein lokaler `docker build` nach frischem Checkout hätte CRLF-Skripte ins Image kopiert (`/bin/sh^M`), Entrypoint und Healthcheck wären gescheitert.
- **Fix:** `.gitattributes` (`*.sh text eol=lf`, `Dockerfile text eol=lf`); Test prüft, dass die Image-Skripte kein CRLF enthalten. Datei ist nicht in `files_modified` des Plans.
- **Commit:** 47aa5af

**3. [Rule 2] uv auch per Digest gepinnt**
- `COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85a...` statt nur Tag; Test prüft Digest bei fremden `COPY --from`-Quellen.

**4. Spiele-Stufe auf derselben python:3.13-slim-Basis** statt eines eigenen Debian-slim-Digests (ein Digest weniger, gleiche Debian-Basis).

**5. Probe unter Git Bash:** Der erste Lauf scheiterte, weil MSYS `APP_PERSISTENT_STORAGE=/nc_app_gameworld_data` in einen Windows-Pfad umschrieb; das bestätigte nebenbei den Volume-Wächter. Zweiter Lauf mit `MSYS_NO_PATHCONV=1` grün.

### D-22 (bestätigte Umsetzung)

Fest USER 10001:10001 ohne chown/gosu und ohne root-Moment, Entrypoint bricht bei nicht schreibbarem Volume klar ab: so vom Owner am 24.10. bestätigt (D-22 in 06-CONTEXT.md), keine erneute Rückfrage.

## Für 06-12/06-14

- Image: `ghcr.io/street1983nk/gameworld`, Tags `1.0.0` (Release per Git-Tag `v1.0.0`) und `1.0.0-rc.N` (workflow_dispatch, Input `image_tag`). info.xml: registry `ghcr.io`, image `street1983nk/gameworld`, image-tag `1.0.0`.
- Lokal bauen (amd64): `docker build -t gameworld:local-test .` im Repo-Root. Laufprobe:
  `MSYS_NO_PATHCONV=1 docker run -d --name gw-img-test -e APP_ID=gameworld -e APP_VERSION=1.0.0 -e APP_SECRET=local-test -e APP_HOST=0.0.0.0 -e APP_PORT=23000 -e NEXTCLOUD_URL=http://127.0.0.1 -e APP_PERSISTENT_STORAGE=/nc_app_gameworld_data -v gw-img-test:/nc_app_gameworld_data -p 127.0.0.1:23000:23000 gameworld:local-test`
- Multi-Arch lokal (nur bei Bedarf, QEMU, viel RAM): `docker buildx build --platform linux/amd64,linux/arm64 .`
- Store-Archiv: `sh scripts/build-store-release.sh` -> `dist/gameworld-1.0.0.tar.gz` (Signatur nur über das heruntergeladene Release-Asset).
- Release-Job braucht `docs/release-notes/1.0.0.md` (englische Faktenliste, 06-16), sonst Abbruch vor dem Release.
- Nach dem ersten Push: ghcr-Paket `gameworld` einmal von Hand auf öffentlich stellen, sonst kann AppAPI nicht ziehen.
- Nichts gepusht, kein Workflow ausgelöst.

## Known Stubs

Keine.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| threat_flag: T-06-SC Lieferkette | Dockerfile, .github/workflows/image.yml | Mitigiert: alle FROM per Index-Digest, uv per Digest, frpc 0.71.1 per SHA-256 je Arch, Spiele per SHA256SUMS (zweifach geprüft), Actions per 40-stelligem SHA, Provenance mode=max + SBOM + attest-build-provenance. Restrisiko: npm ci zieht aus der Registry, abgesichert nur über package-lock.json-Integrity; apt-Pakete (curl, ca-certificates) ungepinnt aus Debian |
| threat_flag: Workflow-Schreibrechte | .github/workflows/image.yml | packages: write und id-token: write nur am image-Job, contents: write nur am release-Job; Inputs nur über env in run-Blöcke (keine Ausdrucks-Injektion), persist-credentials: false |
| threat_flag: Quellkarte im Image | Dockerfile (js/gameworld-main.js.map) | 5 MB Sourcemap wird unter ^/js/.* mit ausgeliefert; Quelle ist AGPL-öffentlich, kein Geheimnis, nur Größe |

## TDD Gate Compliance

RED 857c923 (test), GREEN 5f9b557 (feat). Kein Refactor nötig.

## Self-Check: PASSED

- Dateien vorhanden: Dockerfile, .dockerignore, .gitattributes, scripts/image/{start,entrypoint,healthcheck}.sh, .github/workflows/image.yml, scripts/build-store-release.sh, tests/test_image_build.py
- Commits vorhanden: 47aa5af, 7f22d67, 857c923, 5f9b557
- `grep -c "FROM .*@sha256:" Dockerfile` = `grep -c "^FROM" Dockerfile` = 4; beide frpc-Prüfsummen im Dockerfile; `--clobber` 0 Treffer in image.yml
