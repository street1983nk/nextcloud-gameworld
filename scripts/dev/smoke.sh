#!/bin/sh
# Durchstich durch die Dev-Nextcloud: Seite, Welt erstellen, gehärteter
# Container, Liste, Aufräumen.
#
# Setzt den laufenden Stack (docker compose -f scripts/dev/compose.yaml up -d)
# und eine registrierte ExApp (sh scripts/dev/register-exapp.sh) voraus.
# Exit 0 nur, wenn jeder Schritt stimmt; jede Abweichung endet mit einer
# deutschen Meldung und Exit 1. Der Weltschlüssel aus der Antwort wird nie
# ausgegeben.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
AUTH=admin:gameworld-dev-admin
PAGE_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/embedded/gameworld/gameworld"
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api/worlds"
DB_FILE="${REPO_ROOT}/.dev/storage/gameworld.sqlite3"
# Erwartete Härtung: 512 MiB Speicher = Swap, 128 Prozesse, alle Capabilities weg, Root-FS nur lesbar.
EXPECTED_HARDENING='true 536870912 536870912 128 ["ALL"] true'

WORK_DIR=$(mktemp -d)
WORLD_ID=""
CONTAINER_ID=""

fail() {
	printf 'FEHLER: %s\n' "$1" >&2
	exit 1
}

# Aufräumen läuft auch nach einem Fehler. Eine Lösch-API gibt es erst mit
# Plan 01-03, darum entfernt das Skript Container, Volume und die Zeile in der
# Dev-Datenbank selbst; sonst belegt jeder Lauf einen der 20 UDP-Ports.
cleanup() {
	status=$?
	if [ -n "${CONTAINER_ID}" ]; then
		VOLUMES=$(docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' \
			"${CONTAINER_ID}" 2>/dev/null || true)
		docker rm -f -v "${CONTAINER_ID}" >/dev/null 2>&1 || true
		for volume in ${VOLUMES}; do
			docker volume rm "${volume}" >/dev/null 2>&1 || true
		done
	fi
	if [ -n "${WORLD_ID}" ] && [ -f "${DB_FILE}" ]; then
		(cd "${REPO_ROOT}" && uv run python -c \
			'import sqlite3, sys; c = sqlite3.connect(sys.argv[1]); c.execute("DELETE FROM worlds WHERE id = ?", (sys.argv[2],)); c.commit()' \
			"${DB_FILE}" "${WORLD_ID}") || printf 'WARNUNG: Zeile %s blieb in %s\n' "${WORLD_ID}" "${DB_FILE}" >&2
	fi
	rm -rf "${WORK_DIR}"
	if [ "${status}" -eq 0 ]; then
		printf 'aufgeräumt: Container, Volume und Datenbankzeile der Smoke-Welt\n'
	fi
	exit "${status}"
}
trap cleanup EXIT

json_field() {
	uv run --project "${REPO_ROOT}" python -c \
		'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))[sys.argv[2]])' "$1" "$2"
}

# (1) Die Top-Menü-Seite antwortet dem Admin mit 200 und lädt das Bundle.
PAGE_CODE=$(curl -s -u "${AUTH}" -o "${WORK_DIR}/page.html" -w '%{http_code}' "${PAGE_URL}" || printf '000')
[ "${PAGE_CODE}" = "200" ] || fail "Seite ${PAGE_URL} antwortet mit ${PAGE_CODE} statt 200"
grep -q 'gameworld-main' "${WORK_DIR}/page.html" || fail "Seite referenziert gameworld-main nicht"
printf 'ok: Seite 200 und referenziert gameworld-main\n'

# Das Bundle selbst muss über den Proxy kommen (Route js ist ADMIN).
BUNDLE_CODE=$(curl -s -u "${AUTH}" -o /dev/null -w '%{http_code}' \
	"${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/js/gameworld-main.js" || printf '000')
[ "${BUNDLE_CODE}" = "200" ] || fail "Bundle über den Proxy antwortet mit ${BUNDLE_CODE} statt 200"
printf 'ok: Bundle über den Proxy 200\n'

# (2) Welt über den AppAPI-Proxy erstellen. OCS-APIRequest: true ist der Weg,
# den Nextcloud für Basic-Auth-Clients ohne Sitzungs-Token vorsieht.
WORLD_NAME="Smoke Welt $(date +%s)"
POST_CODE=$(curl -s -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
	-X POST -d "{\"name\":\"${WORLD_NAME}\"}" -o "${WORK_DIR}/created.json" -w '%{http_code}' \
	"${API_URL}" || printf '000')
if [ "${POST_CODE}" != "201" ]; then
	DETAIL=$(sed -n 's/.*"detail":"\([^"]*\)".*/\1/p' "${WORK_DIR}/created.json" 2>/dev/null || true)
	fail "POST ${API_URL} antwortet mit ${POST_CODE} statt 201 ${DETAIL}"
fi
WORLD_ID=$(json_field "${WORK_DIR}/created.json" id)
[ -n "${WORLD_ID}" ] || fail "Antwort ohne id"
printf 'ok: POST 201, Welt %s\n' "${WORLD_ID}"

# (3) Der Container dieser Welt läuft mit der gehärteten Spec.
CONTAINER_ID=$(docker ps -aq --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=${WORLD_ID}")
[ -n "${CONTAINER_ID}" ] || fail "kein Container mit Label gameworld.world_id=${WORLD_ID}"
HARDENING=$(docker inspect -f \
	'{{.State.Running}} {{.HostConfig.Memory}} {{.HostConfig.MemorySwap}} {{.HostConfig.PidsLimit}} {{json .HostConfig.CapDrop}} {{.HostConfig.ReadonlyRootfs}}' \
	"${CONTAINER_ID}")
[ "${HARDENING}" = "${EXPECTED_HARDENING}" ] || fail "Härtung weicht ab: '${HARDENING}' statt '${EXPECTED_HARDENING}'"
printf 'ok: Container läuft gehärtet (%s)\n' "${HARDENING}"

# (4) Die Liste enthält die Welt mit docker_status running.
LIST_CODE=$(curl -s -u "${AUTH}" -H 'OCS-APIRequest: true' -o "${WORK_DIR}/list.json" -w '%{http_code}' \
	"${API_URL}" || printf '000')
[ "${LIST_CODE}" = "200" ] || fail "GET ${API_URL} antwortet mit ${LIST_CODE} statt 200"
LISTED=$(uv run --project "${REPO_ROOT}" python -c \
	'import json, sys; ws = json.load(open(sys.argv[1], encoding="utf-8"))["worlds"]; print(next((w["docker_status"] for w in ws if w["id"] == sys.argv[2]), "fehlt"))' \
	"${WORK_DIR}/list.json" "${WORLD_ID}")
[ "${LISTED}" = "running" ] || fail "Welt ${WORLD_ID} steht in der Liste mit Status ${LISTED} statt running"
printf 'ok: Liste zeigt die Welt mit Status running\n'

# (5) Aufräumen übernimmt der EXIT-Trap.
printf 'Durchstich erfolgreich\n'
