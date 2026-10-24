#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Entrypoint des Gameworld-Images: zwei Wächter, dann das unveränderte HaRP-start.sh.
# Vorlage: nextcloud-mcp-connector/entrypoint.sh (WR-04). Die dortige DNS-Rebinding-Zeile
# entfällt, Gameworld hat keinen MCP-Transport.
#
# Wächter 1 (T-06-44): start.sh fällt ohne /certs/frp auf transport.tls.enable = false
# zurück und schickt HP_SHARED_KEY dann im Klartext. HaRP installiert das Zertifikat erst
# im laufenden Container, darum wird darauf gewartet; kommt es nicht, startet der
# Container nicht (außer ALLOW_PLAINTEXT_FRP=1 auf einem vertrauten lokalen Netz).
#
# Wächter 2 (D-22): Der Container läuft fest als uid 10001, ohne root-Moment und ohne
# chown. Ein frisches Volume nc_app_gameworld_data übernimmt Besitzer und Modus des im
# Image vorbereiteten Verzeichnisses. Gehört es doch root (etwa nach Handarbeit), bricht
# der Start hier mit klarer Meldung ab, statt später still an SQLite zu scheitern.
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

# Das Verzeichnis allein ist noch nicht das Zertifikat: HaRP legt es per mkdir -p an,
# bevor es die drei Dateien kopiert. Gewartet wird auf die Dateien selbst.
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
