#!/bin/sh
# Real-stack smoke test 03-03: inviting through the AppAPI proxy of the dev Nextcloud,
# play password derived from the secret in appconfig_ex.
#
# Proves against the real Nextcloud what the unit tests show only with fakes:
#   - account check as manager (users.get_user) confirms gw-kind
#   - secret is created in appconfig_ex (sensitive) and read back after a
#     restart of the ExApp: password before and after identical
#   - password is not in the SQLite file of the ExApp, the player name is
#
# The password is never printed, only its pattern and a comparison of the
# sha256 values. The acceptance world is removed in any case (trap).
#
# Prerequisite: docker compose -f scripts/dev/compose.yaml up -d
# Credentials here are pure dev accounts of a loopback dev instance.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
REGISTER_SCRIPT="${SCRIPT_DIR}/register-exapp.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api"
BACKEND_PORT=10040
PID_FILE="${REPO_ROOT}/.dev/exapp.pid"
DB_FILE="${REPO_ROOT}/.dev/storage/gameworld.sqlite3"
KID=gw-kind
PASSWORD_RE='^[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}$'

PASSED=0
FAILED=0
WORLD_ID=""
WORK_DIR=$(mktemp -d)

pass() {
	PASSED=$((PASSED + 1))
	printf 'bestanden: %s\n' "$1"
}

fail() {
	FAILED=$((FAILED + 1))
	printf 'FEHLGESCHLAGEN: %s\n' "$1" >&2
}

abort() {
	printf 'ABBRUCH: %s\n' "$1" >&2
	exit 1
}

check() {
	description=$1
	shift
	if "$@"; then
		pass "${description}"
	else
		fail "${description}"
	fi
}

eq() { [ "$1" = "$2" ]; }

heartbeat_up() {
	curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1
}

# Terminates the ExApp process in a targeted way (PID file, otherwise only the process on the
# backend port); never all python.exe, so that parallel sessions keep running.
kill_backend() {
	if [ -f "${PID_FILE}" ]; then
		kill -TERM "$(cat "${PID_FILE}")" 2>/dev/null || true
	fi
	i=0
	while [ "${i}" -lt 10 ] && heartbeat_up; do
		i=$((i + 1))
		sleep 1
	done
	if heartbeat_up && command -v taskkill >/dev/null 2>&1; then
		for win_pid in $(netstat -ano 2>/dev/null \
			| awk -v p=":${BACKEND_PORT}" '$1 == "TCP" && $2 ~ p"$" && $3 ~ /:0$/ {print $5}' | sort -u); do
			MSYS_NO_PATHCONV=1 taskkill /F /T /PID "${win_pid}" >/dev/null 2>&1 || true
		done
		i=0
		while [ "${i}" -lt 10 ] && heartbeat_up; do
			i=$((i + 1))
			sleep 1
		done
	fi
	! heartbeat_up
}

cleanup() {
	status=$?
	if ! heartbeat_up; then
		printf 'starte die ExApp wieder (register-exapp.sh)\n'
		sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register-cleanup.log" 2>&1 \
			|| printf 'register-exapp.sh scheiterte, bitte von Hand starten\n' >&2
	fi
	if [ -n "${WORLD_ID}" ]; then
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null \
			"${API_URL}/worlds/${WORLD_ID}" >/dev/null 2>&1 || true
		for container in $(docker ps -aq --filter "label=gameworld.world_id=${WORLD_ID}" 2>/dev/null); do
			docker rm -f -v "${container}" >/dev/null 2>&1 || true
		done
		for volume in $(docker volume ls -q 2>/dev/null | grep -e "-${WORLD_ID}\$" || true); do
			docker volume rm "${volume}" >/dev/null 2>&1 || true
		done
	fi
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# http_code METHOD URL OUTPUT [JSON]
http_code() {
	if [ -n "${4:-}" ]; then
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$1" -d "$4" -o "$3" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	else
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X "$1" -o "$3" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	fi
}

# Password of gw-kind from GET players, only into a file (never to the output).
kid_password() {
	code=$(http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "${WORK_DIR}/players.json")
	[ "${code}" = "200" ] || return 1
	jq -r --arg kid "${KID}" '.players[]? | select(.nc_user == $kid) | .password' \
		"${WORK_DIR}/players.json" >"$1"
	[ -s "$1" ]
}

password_matches() {
	grep -Eq "${PASSWORD_RE}" "$1"
}

sha_of() {
	tr -d '\r\n' <"$1" | sha256sum | cut -d' ' -f1
}

printf '== Vorbereitung ==\n'
sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register.log" 2>&1 || {
	tail -n 30 "${WORK_DIR}/register.log" >&2
	abort 'register-exapp.sh scheiterte'
}
pass 'register-exapp.sh: ExApp läuft mit dem aktuellen Code'

CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/create.json" '{"name":"Smoke Zugang","preset":"mtg_kreativ"}')
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/create.json" 2>/dev/null || true)
check "Welt angelegt, HTTP 201 (ist ${CODE})" eq "${CODE}" 201
[ -n "${WORLD_ID}" ] || abort 'keine Welt-ID in der Antwort'

printf '\n== Einladen über den AppAPI-Proxy ==\n'
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/invite.json" \
	"{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "POST invites ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check 'Antwort: applied true' eq "$(jq -r '.applied' "${WORK_DIR}/invite.json" 2>/dev/null)" true
PLAYER_NAME=$(jq -r --arg kid "${KID}" '.players[]? | select(.nc_user == $kid) | .player_name' \
	"${WORK_DIR}/invite.json" 2>/dev/null || true)
check "Spielername vergeben (${PLAYER_NAME:-leer})" test -n "${PLAYER_NAME}"

CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/unknown.json" \
	'{"kind":"user","target":"gw-gibt-es-nicht"}')
check "Negativkontrolle: unbekanntes Konto HTTP 422 (ist ${CODE})" eq "${CODE}" 422

kid_password "${WORK_DIR}/pw-before" || abort 'GET players lieferte kein Passwort für gw-kind'
check 'GET players: Passwort passt auf das Muster (Muster ok)' password_matches "${WORK_DIR}/pw-before"
HASH_BEFORE=$(sha_of "${WORK_DIR}/pw-before")

printf '\n== Neustart der ExApp ==\n'
check 'ExApp-Prozess beendet, Heartbeat schweigt' kill_backend
sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register2.log" 2>&1 || {
	tail -n 30 "${WORK_DIR}/register2.log" >&2
	abort 'register-exapp.sh nach dem Neustart scheiterte'
}
check 'register-exapp.sh hat ein neues Backend gestartet' \
	grep -q 'starte das Backend' "${WORK_DIR}/register2.log"

kid_password "${WORK_DIR}/pw-after" || abort 'GET players nach Neustart lieferte kein Passwort'
HASH_AFTER=$(sha_of "${WORK_DIR}/pw-after")
check 'sha256 des Passworts vor und nach dem Neustart gleich (Geheimnis aus appconfig_ex)' \
	eq "${HASH_BEFORE}" "${HASH_AFTER}"

printf '\n== Passwortfreiheit der Datenbank ==\n'
[ -f "${DB_FILE}" ] || abort "SQLite-Datei fehlt: ${DB_FILE}"
# Only in a variable, never printed.
KID_PASSWORD=$(tr -d '\r\n' <"${WORK_DIR}/pw-after")
PW_HITS=$(grep -c -a -F -- "${KID_PASSWORD}" "${DB_FILE}" || true)
KID_PASSWORD=""
check "Passwort steht nicht in der SQLite-Datei (Treffer ${PW_HITS})" eq "${PW_HITS}" 0
NAME_HITS=$(grep -c -a -F -- "${PLAYER_NAME}" "${DB_FILE}" || true)
check "Positivkontrolle: Spielername steht in der SQLite-Datei (Treffer ${NAME_HITS})" test "${NAME_HITS}" -gt 0

printf '\n== Aufräumen ==\n'
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" "${WORK_DIR}/delete.out")
check "DELETE Welt HTTP 204 (ist ${CODE})" eq "${CODE}" 204
[ "${CODE}" = "204" ] && WORLD_ID=""
LEFT=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | wc -l | tr -d ' ')
check "keine Welt-Container übrig (${LEFT})" eq "${LEFT}" 0

printf '\n%s bestanden, %s fehlgeschlagen\n' "${PASSED}" "${FAILED}"
[ "${FAILED}" -eq 0 ]
