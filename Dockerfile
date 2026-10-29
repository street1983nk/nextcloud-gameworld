# syntax=docker/dockerfile:1
#
# Gameworld ExApp image (PLATT-01, D-14). Template: nextcloud-mcp-connector/Dockerfile.
#
# Four stages: bundle (Node), games (checksums), Python environment (uv), runtime.
# Tools of the first three stages never end up in the published image.
#
# No EXPOSE: AppAPI passes APP_PORT at start, behind HaRP there is no
# TCP port at all (Unix socket plus frpc tunnel).
#
# Every base is pinned by index digest (amd64 and arm64 under the same digest).
# The tag moves, the digest does not (T-06-SC).

# --------------------------------------------------------------------------------------
# Stage 1: build the UI (js/gameworld-main.js, not in Git)
# --------------------------------------------------------------------------------------
FROM node:22-slim@sha256:de170b39439eb0e5a3444ad7d60b015614a381e10fecae2e30ec9e735122f38d AS frontend

WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
# --ignore-scripts: no install hooks of third-party packages during the build.
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY frontend/vite.config.js ./
COPY frontend/src ./src
# vite.config.js writes to ../js, i.e. /src/js.
RUN npm run build && test -s /src/js/gameworld-main.js

# --------------------------------------------------------------------------------------
# Stage 2: fetch games and verify them against vendor/games/SHA256SUMS
# --------------------------------------------------------------------------------------
# Debian slim from the same Python base: one digest less to maintain.
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS games

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY scripts/fetch-games.sh ./scripts/fetch-games.sh
# minetest_game is in Git, fetch-games.sh downloads VoxeLibre and stores it only with
# a matching checksum; re-checking all lines also secures the Git zip.
COPY vendor/games/SHA256SUMS vendor/games/minetest_game-38214.zip vendor/games/README.md ./vendor/games/
RUN sh scripts/fetch-games.sh \
    && cd vendor/games \
    && sha256sum -c SHA256SUMS

# --------------------------------------------------------------------------------------
# Stage 3: resolve the locked Python environment
# --------------------------------------------------------------------------------------
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS build

# uv as a pinned release by digest instead of curl | sh.
COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src

# --frozen: uv.lock is the truth, a diverged pyproject.toml makes the build
# fail. --no-dev: no test and check tools.
# Editable (without --no-editable): archive.py finds vendor/games via the path of the
# source tree (parents[3] of /app/src/gameworld/provisioner/archive.py = /app). Therefore
# src/ sits at exactly the same path in the runtime.
RUN uv sync --frozen --no-dev \
    && /app/.venv/bin/python -m compileall -q /app/src

# --------------------------------------------------------------------------------------
# Runtime
# --------------------------------------------------------------------------------------
# Same digest as the build stage: the environment runs on the libc it was
# built against.
FROM python:3.13-slim@sha256:57b29a7c050c4e679e4bea572e14b3965cf4b5839de2da49d55e49ffc4024f39 AS runtime

LABEL org.opencontainers.image.source="https://github.com/street1983nk/nextcloud-gameworld" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.title="Gameworld"

# curl is needed by the HaRP integration and the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# frpc, the tunnel client for HaRP (start.sh starts it). 0.71.1 like the HaRP Dockerfile and
# app-skeleton-python (as of 24.10.2026). Constants instead of ARGs, so that --build-arg cannot
# override the pin; sha256sum -c makes the build fail on a foreign binary.
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

# Fixed service user before any chown (D-22, T-06-43).
RUN groupadd --gid 10001 exapp \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin exapp

COPY scripts/image/entrypoint.sh scripts/image/start.sh scripts/image/healthcheck.sh /
RUN chmod 0755 /entrypoint.sh /start.sh /healthcheck.sh \
    # start.sh writes /frpc.toml; the service user may not create anything in /.
    && install -o 10001 -g 10001 -m 0600 /dev/null /frpc.toml \
    # AppAPI mounts the volume nc_app_gameworld_data here. A fresh named volume
    # takes over owner and mode of this directory (D-22).
    && install -d -o 10001 -g 10001 -m 0700 /nc_app_gameworld_data \
    # HaRP creates /certs/frp with the identity of the container (Connector plan 02-04).
    && install -d -o 10001 -g 10001 -m 0700 /certs

# Code belongs to root and is read-only for 10001 (WR-13): COPY without changing the owner.
# Only /nc_app_gameworld_data, /certs and /frpc.toml are writable. No
# browser spike artifacts (D-23: spike flag off, the routes answer 404).
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

# App root: set_handlers mounts js/ and img/ relative to the working directory.
WORKDIR /app
USER 10001:10001

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 CMD ["/healthcheck.sh"]

# First the guards, then the unchanged HaRP start.sh with the start command.
ENTRYPOINT ["/entrypoint.sh", "/app/.venv/bin/python", "-m", "gameworld.main"]
