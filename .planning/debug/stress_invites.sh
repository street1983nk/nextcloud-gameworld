#!/bin/sh
# Lasttest für die Debug-Session backend-windows-invalidstate.
#
# Erzeugt dieselbe Mischung wie die Abnahme, nur dichter: POST invites (jede
# Anfrage baut eine neue AsyncNextcloudApp-Session, Kontoprüfung und Talk-Abgleich
# gegen Nextcloud) parallel zu Anfragen, die anyio-Worker-Threads beschäftigen
# (GET worlds, GET players). Alles über den AppAPI-Proxy wie in der Abnahme.
#
# Aufruf: sh stress_invites.sh [SEKUNDEN] [PARALLEL]
# Exit 0: Backend lebt am Ende; Exit 1: Heartbeat weg oder InvalidStateError im Log.
set -u
DURATION=${1:-600}
PARALLEL=${2:-6}
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${HERE}/../.." && pwd)
API="http://localhost:${GAMEWORLD_NC_PORT:-8091}/index.php/apps/app_api/proxy/gameworld/api"
AUTH=admin:gameworld-dev-admin
LOG="${REPO_ROOT}/.dev/exapp.log"
WORK=$(mktemp -d)
NAME="Debug Last"

req() {
	if [ -n "${3:-}" ]; then
		curl -s -m 30 -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$1" -d "$3" -o /dev/null -w '%{http_code}\n' "$2" 2>/dev/null || printf '000\n'
	else
		curl -s -m 30 -u "${AUTH}" -H 'OCS-APIRequest: true' -X "$1" -o /dev/null -w '%{http_code}\n' "$2" 2>/dev/null \
			|| printf '000\n'
	fi
}

alive() {
	curl -sf -m 5 http://127.0.0.1:10040/heartbeat >/dev/null 2>&1
}

alive || { printf 'Backend antwortet nicht auf 10040\n' >&2; exit 1; }
START_LINES=$(wc -l <"${LOG}" | tr -d ' ')

curl -s -m 60 -u "${AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X POST \
	-d "{\"name\":\"${NAME}\",\"preset\":\"mtg_kreativ\"}" -o "${WORK}/world.json" "${API}/worlds" >/dev/null
WORLD=$(jq -r '.id // empty' "${WORK}/world.json")
[ -n "${WORLD}" ] || { printf 'Welt ließ sich nicht anlegen\n' >&2; cat "${WORK}/world.json" >&2; exit 1; }
printf 'Welt %s angelegt, Last %s s mit %s parallelen Schleifen\n' "${WORLD}" "${DURATION}" "${PARALLEL}"

END=$(($(date +%s) + DURATION))
i=1
while [ "${i}" -le "${PARALLEL}" ]; do
	(
		while [ "$(date +%s)" -lt "${END}" ]; do
			req POST "${API}/worlds/${WORLD}/invites" '{"kind":"user","target":"admin"}'
			req GET "${API}/worlds"
			req GET "${API}/worlds/${WORLD}/players"
		done >"${WORK}/codes-${i}.txt"
	) &
	i=$((i + 1))
done

RESULT=0
while [ "$(date +%s)" -lt "${END}" ]; do
	sleep 5
	if ! alive; then
		printf 'ABSTURZ: Heartbeat weg um %s\n' "$(date +%H:%M:%S)"
		RESULT=1
		break
	fi
done
wait

CODES=$(cat "${WORK}"/codes-*.txt | sort | uniq -c | tr '\n' ' ')
printf 'HTTP-Codes: %s\n' "${CODES}"
if tail -n +"${START_LINES}" "${LOG}" | grep -q InvalidStateError; then
	printf 'InvalidStateError im Backend-Log\n'
	RESULT=1
fi
if [ "${RESULT}" -eq 0 ] && alive; then
	printf 'STABIL: Backend lebt nach %s s Last\n' "${DURATION}"
fi

# Aufräumen: Welt über die API löschen (Backend ggf. erst neu starten lassen).
if alive; then
	printf 'Welt löschen: HTTP %s\n' "$(req DELETE "${API}/worlds/${WORLD}")"
else
	printf 'Welt %s bleibt stehen (Backend tot), nach Neustart löschen\n' "${WORLD}"
fi
rm -rf "${WORK}"
exit "${RESULT}"
