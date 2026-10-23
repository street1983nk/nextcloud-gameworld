#!/bin/sh
# Header- und WebSocket-Probe für den Browser-Spike 04.2 (Plan 03), nur Dev-Stack.
#
# Misst, welche Content-Security-Policy-, COOP-, COEP-, Feature-Policy- und
# X-Frame-Options-Header unter manual-install durch den AppAPI-PHP-Proxy beim
# Browser ankommen, vergleicht mit der direkten Antwort der ExApp auf Port 10040
# und versucht ein WebSocket-Upgrade über den PHP-Proxy.
#
# Das Admin-Passwort kommt aus GAMEWORLD_NC_ADMIN_PASSWORD oder aus
# scripts/dev/compose.yaml; es wird nie ausgegeben. Set-Cookie-Werte werden vor
# dem Schreiben des Belegs ersetzt.
#
# Aufruf: sh scripts/dev/spike-04.2/probe-headers.sh
# Ausgabe: .planning/phases/04.2-browser-spike-luanti-wasm/evidence/03-manual-install.txt
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../../.." && pwd)
COMPOSE_FILE="${REPO_ROOT}/scripts/dev/compose.yaml"
OUT="${REPO_ROOT}/.planning/phases/04.2-browser-spike-luanti-wasm/evidence/03-manual-install.txt"

NC="http://localhost:${GAMEWORLD_NC_PORT:-8091}"
PROXY="${NC}/index.php/apps/app_api/proxy/gameworld"
DIRECT="http://127.0.0.1:10040"
BUILD="${GAMEWORLD_PLAY_BUILD:-b}"

if [ -n "${GAMEWORLD_NC_ADMIN_PASSWORD:-}" ]; then
	PW="${GAMEWORLD_NC_ADMIN_PASSWORD}"
else
	PW=$(sed -n 's/^[[:space:]]*NEXTCLOUD_ADMIN_PASSWORD:[[:space:]]*//p' "${COMPOSE_FILE}" | head -n 1 | tr -d '"\r')
fi
if [ -z "${PW}" ]; then
	printf 'kein Admin-Passwort gefunden (GAMEWORLD_NC_ADMIN_PASSWORD oder compose.yaml)\n' >&2
	exit 1
fi

# Das Passwort geht über eine curl-Konfiguration auf stdin, damit es weder in der
# Prozessliste noch in einer Ausgabe steht.
TMP=$(mktemp -d)
trap 'rm -rf "${TMP}"' EXIT INT TERM

sanitize() {
	sed -e 's/^\([Ss][Ee][Tt]-[Cc][Oo][Oo][Kk][Ii][Ee]\):.*/Set-Cookie: <entfernt>/' -e 's/\r$//'
}

# probe <Titel> <auth: ja|nein> <URL> [weitere curl-Argumente]
probe() {
	title=$1
	auth=$2
	url=$3
	shift 3
	file="${TMP}/$(printf '%s' "${title}" | tr -c 'A-Za-z0-9' '_').h"
	if [ "${auth}" = "ja" ]; then
		printf 'user = "admin:%s"\n' "${PW}" | curl -sS -K - -D "${file}" -o /dev/null "$@" "${url}" 2>"${file}.err" || true
	else
		curl -sS -D "${file}" -o /dev/null "$@" "${url}" 2>"${file}.err" || true
	fi
	{
		printf '=== %s\n' "${title}"
		printf '>>> %s (Basic-Auth admin: %s)\n' "${url}" "${auth}"
		if [ -s "${file}" ]; then
			sanitize <"${file}"
		else
			printf '(keine Antwort-Header)\n'
		fi
		if [ -s "${file}.err" ]; then
			printf 'curl: %s\n' "$(tr -d '\r' <"${file}.err")"
		fi
		printf '\n'
	} >>"${TMP}/blocks"
	printf '%s\n' "${title}" >>"${TMP}/titles"
}

count_header() {
	grep -ci "^$2:" "$1" 2>/dev/null || true
}

: >"${TMP}/blocks"
: >"${TMP}/titles"

probe "proxy-play" ja "${PROXY}/play/"
probe "proxy-wasm" ja "${PROXY}/play/static/${BUILD}/probe.wasm"
probe "direkt-play" nein "${DIRECT}/play/"
probe "direkt-wasm" nein "${DIRECT}/play/static/${BUILD}/probe.wasm"
probe "proxy-ws-upgrade" ja "${PROXY}/play/ws" --http1.1 --max-time 5 \
	-H "Connection: Upgrade" -H "Upgrade: websocket" \
	-H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=="
# Vergleich: Wer erzeugt die Antwort auf den Upgrade? Derselbe Upgrade direkt an
# die ExApp und dieselbe Proxy-Adresse ohne Upgrade-Header.
probe "direkt-ws-upgrade" nein "${DIRECT}/play/ws" --http1.1 --max-time 5 \
	-H "Connection: Upgrade" -H "Upgrade: websocket" \
	-H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=="
probe "proxy-ws-ohne-upgrade" ja "${PROXY}/play/ws" --http1.1 --max-time 5

{
	printf '# Plan 04.2-03 Task 1: Header- und WS-Probe unter manual-install\n'
	printf '# Erzeugt von scripts/dev/spike-04.2/probe-headers.sh am %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	printf '# Set-Cookie-Werte ersetzt, kein Passwort im Beleg.\n\n'
	cat "${TMP}/blocks"
	printf '=== Zaehlung (Zeilen je Antwort, case-insensitiv)\n'
	printf '%-22s %-8s %4s %5s %5s %5s %5s %5s\n' anfrage status csp coop coep fp xfo pp
	while read -r t; do
		f="${TMP}/$(printf '%s' "${t}" | tr -c 'A-Za-z0-9' '_').h"
		st=$(head -n 1 "${f}" 2>/dev/null | tr -d '\r' | awk '{print $2}')
		printf '%-22s %-8s %4s %5s %5s %5s %5s %5s\n' "${t}" "${st:-keine}" \
			"$(count_header "${f}" content-security-policy)" \
			"$(count_header "${f}" cross-origin-opener-policy)" \
			"$(count_header "${f}" cross-origin-embedder-policy)" \
			"$(count_header "${f}" feature-policy)" \
			"$(count_header "${f}" x-frame-options)" \
			"$(count_header "${f}" permissions-policy)"
	done <"${TMP}/titles"
	printf '(csp = content-security-policy, fp = feature-policy, xfo = x-frame-options, pp = permissions-policy)\n'
} >"${OUT}"

cat "${OUT}"
