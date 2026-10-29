#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Entrypoint of the Gameworld image: two guards, then the unchanged HaRP start.sh.
# Template: nextcloud-mcp-connector/entrypoint.sh (WR-04). The DNS rebinding line there
# is dropped, Gameworld has no MCP transport.
#
# Guard 1 (T-06-44): without /certs/frp, start.sh falls back to transport.tls.enable = false
# and then sends HP_SHARED_KEY in plain text. HaRP installs the certificate only
# in the running container, so it is waited for; if it does not arrive, the
# container does not start (unless ALLOW_PLAINTEXT_FRP=1 on a trusted local network).
#
# Guard 2 (D-22): the container runs fixed as uid 10001, without a root moment and without
# chown. A fresh volume nc_app_gameworld_data takes over owner and mode of the directory
# prepared in the image. If it belongs to root after all (e.g. after manual work), the start
# aborts here with a clear message instead of failing silently at SQLite later.
set -eu

FRP_CERT_DIR="/certs/frp"
FRP_CERT_WAIT_SECONDS="${FRP_CERT_WAIT_SECONDS:-60}"
STORAGE_DIR="${APP_PERSISTENT_STORAGE:-/nc_app_gameworld_data}"

storage_writable() {
    if [ ! -d "${STORAGE_DIR}" ]; then
        mkdir -p "${STORAGE_DIR}" 2>/dev/null || return 1
    fi
    probe="${STORAGE_DIR}/.gameworld-write-probe.$$"
    if ( : > "${probe}" ) 2>/dev/null; then
        rm -f "${probe}"
        return 0
    fi
    return 1
}

if ! storage_writable; then
    echo "Gameworld: APP_PERSISTENT_STORAGE ist nicht schreibbar für uid 10001. Bitte das Volume nc_app_gameworld_data neu anlegen lassen (App neu installieren) oder chown 10001:10001 setzen." >&2
    echo "Gameworld: Pfad ${STORAGE_DIR}, laufende uid $(id -u)." >&2
    exit 1
fi

# The directory alone is not yet the certificate: HaRP creates it with mkdir -p
# before it copies the three files. The files themselves are waited for.
frp_certs_present() {
    [ -f "${FRP_CERT_DIR}/client.crt" ] &&
        [ -f "${FRP_CERT_DIR}/client.key" ] &&
        [ -f "${FRP_CERT_DIR}/ca.crt" ]
}

if [ -n "${HP_SHARED_KEY:-}" ]; then
    waited=0
    while ! frp_certs_present && [ "${waited}" -lt "${FRP_CERT_WAIT_SECONDS}" ]; do
        if [ "${waited}" -eq 0 ]; then
            echo "waiting for HaRP to install the FRP client certificate in ${FRP_CERT_DIR}"
        fi
        sleep 1
        waited=$((waited + 1))
    done

    if ! frp_certs_present; then
        if [ "${ALLOW_PLAINTEXT_FRP:-0}" = "1" ]; then
            echo "WARNING: the certificate files in ${FRP_CERT_DIR} are still incomplete" >&2
            echo "WARNING: after ${FRP_CERT_WAIT_SECONDS}s. ALLOW_PLAINTEXT_FRP=1 is set, so" >&2
            echo "WARNING: frpc will send HP_SHARED_KEY unencrypted. Only ever do this on" >&2
            echo "WARNING: a trusted local network." >&2
        else
            echo "ERROR: ${FRP_CERT_DIR} is still missing client.crt, client.key or ca.crt" >&2
            echo "ERROR: after ${FRP_CERT_WAIT_SECONDS}s." >&2
            echo "ERROR: frpc would send HP_SHARED_KEY in the clear, and whoever reads it" >&2
            echo "ERROR: can attach their own tunnel to HaRP. Refusing to start." >&2
            echo "ERROR: The usual cause is that /certs is not writable for uid 10001, so" >&2
            echo "ERROR: the certificate installation answered 500. Set ALLOW_PLAINTEXT_FRP=1" >&2
            echo "ERROR: to override on a trusted local network, or raise" >&2
            echo "ERROR: FRP_CERT_WAIT_SECONDS on a slow host." >&2
            exit 1
        fi
    fi
fi

exec /start.sh "$@"
