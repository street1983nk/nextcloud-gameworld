# syntax=docker/dockerfile:1
#
# ExApp-Image von Gameworld (PLATT-01, D-14). Vorlage: nextcloud-mcp-connector/Dockerfile.
#
# Vier Stufen: Bundle (Node), Spiele (Prüfsummen), Python-Umgebung (uv), Laufzeit.
# Werkzeuge der ersten drei Stufen landen nie im veröffentlichten Image.
#
# Kein EXPOSE: AppAPI übergibt APP_PORT beim Start, hinter HaRP gibt es gar keinen
# TCP-Port (Unix-Socket plus frpc-Tunnel).
#
# Jede Basis ist per Index-Digest gepinnt (amd64 und arm64 unter demselben Digest).
# Der Tag wandert, der Digest nicht (T-06-SC).

# --------------------------------------------------------------------------------------
# Stufe 1: Oberfläche bauen (js/gameworld-main.js, nicht im Git)
# --------------------------------------------------------------------------------------
FROM node:22-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
# --ignore-scripts: keine install-Hooks fremder Pakete im Bau.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/vite.config.js ./
COPY frontend/src ./src
# vite.config.js schreibt nach ../js, also /src/js.
RUN npm run build && test -s /src/js/gameworld-main.js

# --------------------------------------------------------------------------------------
# Stufe 2: Spiele holen und gegen vendor/games/SHA256SUMS prüfen
# --------------------------------------------------------------------------------------
# Debian-slim aus derselben Python-Basis: ein Digest weniger zu pflegen.
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS games

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY scripts/fetch-games.sh ./scripts/fetch-games.sh
# minetest_game liegt im Git, VoxeLibre lädt fetch-games.sh und legt es nur bei
# stimmender Prüfsumme ab; die erneute Prüfung aller Zeilen sichert auch das Git-Zip.
COPY vendor/games/SHA256SUMS vendor/games/minetest_game-38214.zip vendor/games/README.md ./vendor/games/
RUN sh scripts/fetch-games.sh \
    && cd vendor/games \
    && sha256sum -c SHA256SUMS

# --------------------------------------------------------------------------------------
# Stufe 3: gesperrte Python-Umgebung auflösen
# --------------------------------------------------------------------------------------
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS build

# uv als gepinnter Release per Digest statt curl | sh.
COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src

# --frozen: uv.lock ist die Wahrheit, ein abgewichenes pyproject.toml lässt den Bau
# scheitern. --no-dev: keine Test- und Prüfwerkzeuge.
# Editierbar (ohne --no-editable): archive.py findet vendor/games über den Pfad des
# Quellbaums (parents[3] von /app/src/gameworld/provisioner/archive.py = /app). Darum
# liegt src/ in der Laufzeit unter genau demselben Pfad.
RUN uv sync --frozen --no-dev \
    && /app/.venv/bin/python -m compileall -q /app/src

# --------------------------------------------------------------------------------------
# Laufzeit
# --------------------------------------------------------------------------------------
# Derselbe Digest wie die Bau-Stufe: die Umgebung läuft auf der libc, gegen die sie
# gebaut wurde.
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS runtime

LABEL org.opencontainers.image.source="https://github.com/street1983nk/nextcloud-gameworld" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.title="Gameworld"

# curl braucht die HaRP-Integration und der Healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# frpc, der Tunnel-Client für HaRP (start.sh startet ihn). 0.71.1 wie HaRP-Dockerfile und
# app-skeleton-python (Stand 24.10.2026). Konstanten statt ARGs, damit --build-arg den
# Pin nicht aushebeln kann; sha256sum -c lässt den Bau bei fremdem Binary scheitern.
ARG TARGETARCH
RUN set -eux; \
    FRP_VERSION=0.71.1; \
    FRP_AMD64_SHA256=1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803; \
    FRP_ARM64_SHA256=8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019; \
    case "${TARGETARCH:-amd64}" in \
        arm64) FRP_ARCH=arm64; FRP_SHA256="${FRP_ARM64_SHA256}" ;; \
        amd64) FRP_ARCH=amd64; FRP_SHA256="${FRP_AMD64_SHA256}" ;; \
        *) echo "nicht unterstützte Architektur: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --proto '=https' --tlsv1.2 -o /tmp/frp.tar.gz \
        "https://github.com/fatedier/frp/releases/download/v${FRP_VERSION}/frp_${FRP_VERSION}_linux_${FRP_ARCH}.tar.gz"; \
    echo "${FRP_SHA256}  /tmp/frp.tar.gz" | sha256sum -c -; \
    tar -C /tmp -xzf /tmp/frp.tar.gz; \
    install -m 0755 "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}/frpc" /usr/local/bin/frpc; \
    rm -rf "/tmp/frp_${FRP_VERSION}_linux_${FRP_ARCH}" /tmp/frp.tar.gz

# Fester Dienstnutzer vor jedem chown (D-22, T-06-43).
RUN groupadd --gid 10001 exapp \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin exapp

COPY scripts/image/entrypoint.sh scripts/image/start.sh scripts/image/healthcheck.sh /
RUN chmod 0755 /entrypoint.sh /start.sh /healthcheck.sh \
    # start.sh schreibt /frpc.toml; in / darf der Dienstnutzer nichts anlegen.
    && install -o 10001 -g 10001 -m 0600 /dev/null /frpc.toml \
    # AppAPI mountet das Volume nc_app_gameworld_data hier. Ein frisches benanntes Volume
    # übernimmt Besitzer und Modus dieses Verzeichnisses (D-22).
    && install -d -o 10001 -g 10001 -m 0700 /nc_app_gameworld_data \
    # HaRP legt /certs/frp mit der Identität des Containers an (Connector Plan 02-04).
    && install -d -o 10001 -g 10001 -m 0700 /certs

# Code gehört root und ist für 10001 nur lesbar (WR-13): COPY ohne Besitzerwechsel.
# Schreibbar sind nur /nc_app_gameworld_data, /certs und /frpc.toml. Keine
# Browser-Spike-Artefakte (D-23: Spike-Flag aus, die Routen antworten 404).
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY --from=frontend /src/js /app/js
COPY --from=games /src/vendor/games /app/vendor/games
COPY img /app/img
COPY appinfo /app/appinfo
COPY LICENSE /app/LICENSE

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# App-Root: set_handlers mountet js/ und img/ relativ zum Arbeitsverzeichnis.
WORKDIR /app
USER 10001:10001

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 CMD ["/healthcheck.sh"]

# Erst die Wächter, dann das unveränderte HaRP-start.sh mit dem Startbefehl.
ENTRYPOINT ["/entrypoint.sh", "/app/.venv/bin/python", "-m", "gameworld.main"]
