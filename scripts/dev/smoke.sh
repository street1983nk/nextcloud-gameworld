#!/bin/sh
# Walkthrough of the dev Nextcloud: page, two parallel worlds, hardened
# containers, list, stop, start, delete without leftovers.
#
# Requires the running stack (docker compose -f scripts/dev/compose.yaml up -d)
# and a registered ExApp (sh scripts/dev/register-exapp.sh).
# Exit 0 only if every step is right; every deviation ends with a
# German message and exit 1. World keys from the responses are never
# printed.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
AUTH=admin:gameworld-dev-admin
PAGE_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/embedded/gameworld/gameworld"
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api/worlds"
# Expected hardening: 512 MiB memory = swap, 128 processes, all capabilities dropped, root FS read-only.
EXPECTED_HARDENING='true 536870912 536870912 128 ["ALL"] true'

WORK_DIR=$(mktemp -d)
ID_A=""
ID_B=""

fail() {
	printf 'FEHLER: %s\n' "$1" >&2
	exit 1
}

# Clean up through the delete API, also after a failure. An already deleted
# world answers 404, which is no error here.
cleanup() {
	status=$?
	for world_id in ${ID_A} ${ID_B}; do
		curl -s -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null "${API_URL}/${world_id}" || true
	done
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT

json_field() {
	uv run --project "${REPO_ROOT}" python -c \
		'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

# api METHOD PATH OUTPUT_FILE [JSON] -> HTTP status
api() {
	if [ -n "${4:-}" ]; then
		curl -s -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$1" -d "$4" -o "$3" -w '%{http_code}' "${API_URL}$2" || printf '000'
	else
		curl -s -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X "$1" -o "$3" -w '%{http_code}' "${API_URL}$2" || printf '000'
	fi
}

detail() {
	sed -n 's/.*"detail":"\([^"]*\)".*/\1/p' "$1" 2>/dev/null || true
}

container_of() {
	docker ps -aq --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1"
}

running_of() {
	docker inspect -f '{{.State.Running}}' "$1"
}

wait_running() {
	# wait_running CONTAINER EXPECTATION SECONDS
	waited=0
	while [ "$(running_of "$1")" != "$2" ]; do
		[ "${waited}" -lt "$3" ] || fail "Container $1 ist nach $3 s nicht Running=$2"
		sleep 1
		waited=$((waited + 1))
	done
}

create_world() {
	# create_world NAME OUTPUT_FILE -> world ID
	code=$(api POST "" "$2" "{\"name\":\"$1\"}")
	[ "${code}" = "201" ] || fail "POST ${API_URL} für '$1' antwortet mit ${code} statt 201 $(detail "$2")"
	json_field "$2" id
}

# (1) The top menu page answers the admin with 200 and loads the bundle.
PAGE_CODE=$(curl -s -u "${AUTH}" -o "${WORK_DIR}/page.html" -w '%{http_code}' "${PAGE_URL}" || printf '000')
[ "${PAGE_CODE}" = "200" ] || fail "Seite ${PAGE_URL} antwortet mit ${PAGE_CODE} statt 200"
grep -q 'gameworld-main' "${WORK_DIR}/page.html" || fail "Seite referenziert gameworld-main nicht"
printf 'ok: Seite 200 und referenziert gameworld-main\n'

BUNDLE_CODE=$(curl -s -u "${AUTH}" -o /dev/null -w '%{http_code}' \
	"${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/js/gameworld-main.js" || printf '000')
[ "${BUNDLE_CODE}" = "200" ] || fail "Bundle über den Proxy antwortet mit ${BUNDLE_CODE} statt 200"
printf 'ok: Bundle über den Proxy 200\n'

# (2) Create two worlds through the AppAPI proxy. OCS-APIRequest: true is the
# path that Nextcloud provides for Basic auth clients without a session token.
STAMP=$(date +%s)
ID_A=$(create_world "Smoke A ${STAMP}" "${WORK_DIR}/a.json")
ID_B=$(create_world "Smoke B ${STAMP}" "${WORK_DIR}/b.json")
[ -n "${ID_A}" ] && [ -n "${ID_B}" ] || fail "Antwort ohne id"
printf 'ok: POST 201 für Welt A (%s) und Welt B (%s)\n' "${ID_A}" "${ID_B}"

# (3) Both containers run at the same time, hardened, with different ports.
CONTAINER_A=$(container_of "${ID_A}")
CONTAINER_B=$(container_of "${ID_B}")
[ -n "${CONTAINER_A}" ] || fail "kein Container mit Label gameworld.world_id=${ID_A}"
[ -n "${CONTAINER_B}" ] || fail "kein Container mit Label gameworld.world_id=${ID_B}"
for container in "${CONTAINER_A}" "${CONTAINER_B}"; do
	HARDENING=$(docker inspect -f \
		'{{.State.Running}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.PidsLimit}} {{json .HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}}' \
		"${container}")
	[ "${HARDENING}" = "${EXPECTED_HARDENING}" ] || fail "Härtung weicht ab: '${HARDENING}' statt '${EXPECTED_HARDENING}'"
done
PORT_FORMAT='{{range $p, $b := .HostConfig.PortBindings}}{{range $b}}{{.HostPort}}{{end}}{{end}}'
PORT_A=$(docker inspect -f "${PORT_FORMAT}" "${CONTAINER_A}")
PORT_B=$(docker inspect -f "${PORT_FORMAT}" "${CONTAINER_B}")
[ -n "${PORT_A}" ] && [ "${PORT_A}" != "${PORT_B}" ] || fail "Ports nicht verschieden: A=${PORT_A} B=${PORT_B}"
printf 'ok: beide Container laufen gehärtet, UDP-Ports %s und %s\n' "${PORT_A}" "${PORT_B}"

# (4) The list shows both worlds with docker_status running.
LIST_CODE=$(api GET "" "${WORK_DIR}/list.json")
[ "${LIST_CODE}" = "200" ] || fail "GET ${API_URL} antwortet mit ${LIST_CODE} statt 200"
LISTED=$(uv run --project "${REPO_ROOT}" python -c \
	'import json, sys; ws = {w["id"]: w["docker_status"] for w in json.load(open(sys.argv[1], encoding="utf-8"))["worlds"]}; print(ws.get(sys.argv[2], "fehlt"), ws.get(sys.argv[3], "fehlt"))' \
	"${WORK_DIR}/list.json" "${ID_A}" "${ID_B}")
[ "${LISTED}" = "running running" ] || fail "Liste zeigt '${LISTED}' statt 'running running'"
printf 'ok: Liste zeigt beide Welten mit Status running\n'

# (5) Stop A, B keeps running.
CODE=$(api POST "/${ID_A}/stop" "${WORK_DIR}/stop.json")
[ "${CODE}" = "200" ] || fail "POST /stop antwortet mit ${CODE} statt 200 $(detail "${WORK_DIR}/stop.json")"
wait_running "${CONTAINER_A}" false 35
[ "$(running_of "${CONTAINER_B}")" = "true" ] || fail "Welt B läuft nach dem Stoppen von A nicht mehr"
printf 'ok: Welt A gestoppt, Welt B läuft weiter\n'

# (6) Start A again.
CODE=$(api POST "/${ID_A}/start" "${WORK_DIR}/start.json")
[ "${CODE}" = "200" ] || fail "POST /start antwortet mit ${CODE} statt 200 $(detail "${WORK_DIR}/start.json")"
wait_running "${CONTAINER_A}" true 30
printf 'ok: Welt A läuft wieder\n'

# (7) Delete both; afterwards neither container nor volume of the two worlds.
for world_id in "${ID_A}" "${ID_B}"; do
	CODE=$(api DELETE "/${world_id}" "${WORK_DIR}/delete.json")
	[ "${CODE}" = "204" ] || fail "DELETE ${world_id} antwortet mit ${CODE} statt 204 $(detail "${WORK_DIR}/delete.json")"
	[ -z "$(container_of "${world_id}")" ] || fail "Container von ${world_id} existiert nach dem Löschen noch"
	LEFT=$(docker volume ls -q | grep -e "-${world_id}\$" || true)
	[ -z "${LEFT}" ] || fail "Volume ${LEFT} existiert nach dem Löschen noch"
done
LIST_CODE=$(api GET "" "${WORK_DIR}/list.json")
grep -q -e "${ID_A}" -e "${ID_B}" "${WORK_DIR}/list.json" && fail "Liste enthält gelöschte Welten noch"
printf 'ok: beide Welten mit 204 gelöscht, keine Container und Volumes übrig\n'
ID_A=""
ID_B=""

printf 'Durchstich erfolgreich\n'
