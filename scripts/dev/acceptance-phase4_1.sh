#!/bin/sh
# Phase acceptance phase 4.1: checks the six success criteria from .planning/ROADMAP.md
# (parent phone: pause, notices, review, Talk room, bot) against the running
# dev stack with a real Nextcloud, running ExApp (15 s cycle and 5 s notification
# loop in the lifespan, no fakes) and installed Talk (spreed). At the end it calls the
# acceptance of phase 4 as a regression (it calls phase 1 to 3 itself).
#
# Deliberately independent of the implementation pattern: evidence comes from the docker CLI,
# from curl against the AppAPI proxy and the OCS API (notifications, Talk) with
# real Nextcloud accounts, from jq, grep and sqlite3 (if sqlite3 is missing, the
# Python standard library reads the file read-only). The only Python tool of the
# project is the session prober (tests/e2e/luanti_probe.py) through its CLI.
# Time INPUTS (weekday, minute, date in Europe/Berlin) are calculated by berlin_now via
# zoneinfo; the helper judges nothing.
#
# A real push to a phone cannot be checked in the dev stack (localhost,
# manual-install, assumption A6). Substitute: the notifications are counted in the real
# Nextcloud notification list of the managers (the same list from which
# the Nextcloud app fetches the push).
#
# Prerequisite:
#   docker compose -f scripts/dev/compose.yaml up -d
#   occ app:install spreed (see docs/dev-setup.md)
#   sh scripts/dev/register-exapp.sh
#
# Exit 0 only if every check passes. Play passwords never appear in the
# output. A trap cleans up in any case: acceptance worlds (delete API, fallback
# docker rm -f -v), running pause (POST /pause/end), review setting of
# admin (old state), rules and usage of gw-kind, throwaway accounts gw-abnahme41
# and gw-admin2, gw-kind never in admin, Talk (spreed) enabled again, ExApp running.
# gw-kind itself stays. The notifications stay in the bell of
# admin: the shared Playwright acceptance (04.1-09 step 5) taps them.
#
# Writing SQL places (only with a stopped ExApp, preparation): foreign attempts,
# day marker and review dispatch of today are deleted. The throttle
# counts single notices per day over all worlds (D-08), the review comes once per
# manager and day (D-15); without resetting, the acceptance could run only once
# a day. In addition, as in phase 4, reset_usage for gw-kind.
#
# Phase 4.1 adjusted no check of phases 1 to 4: the regression still expects
# 84 of 84, 104 of 104, 75 of 75 and 109 of 109 (phase 4 since f6ecfed
# with the check for AppAPI connection errors and its positive control).
#
# Credentials here are pure dev accounts of a loopback dev instance.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
REGISTER_SCRIPT="${SCRIPT_DIR}/register-exapp.sh"
PHASE4_SCRIPT="${SCRIPT_DIR}/acceptance-phase4.sh"
TALK_SMOKE="${SCRIPT_DIR}/smoke-talk.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
KID=gw-kind
KID_AUTH="${KID}:gw-kind-dev-pass-1"
GUEST=gw-abnahme41
GUEST_PASS=gw-abnahme41-dev-pass-1
ADMIN2=gw-admin2
ADMIN2_PASS=gw-admin2-dev-pass-1
ADMIN2_AUTH="${ADMIN2}:${ADMIN2_PASS}"
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
BUNDLE_URL="${PROXY_BASE}/js/gameworld-main.js"
EMBED_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/embedded/gameworld/gameworld"
NOTIFY_URL="${NEXTCLOUD_URL}/ocs/v2.php/apps/notifications/api/v2/notifications?format=json"
SPREED="${NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api"
BACKEND_PORT=10040
PID_FILE="${REPO_ROOT}/.dev/exapp.pid"
DB_FILE="${REPO_ROOT}/.dev/storage/gameworld.sqlite3"
PROBE_HOST=127.0.0.1
NAME_PAUSE="Abnahme Pause"
NAME_NOTALK="Abnahme Ohne Talk"
NAME_BACKFILL="Abnahme Nachlegen"
# World names of this acceptance; only these are cleared away by the pre-run as leftovers.
ACCEPTANCE_WORLDS='["Abnahme Pause","Abnahme Ohne Talk","Abnahme Nachlegen"]'
SESSION_TIMEOUT=30
# Notifications: 15 s cycle plus 5 s loop, so at most about 20 s.
NOTIFY_WAIT=30
# Talk sync every 300 s plus a pass of the loop; the script does not force it.
RECONCILE_WAIT=330
# Kid texts from provisioner/time_mod.py and access_mod.py (substrings).
TEXT_PAUSE="Kurze Pause!"
TEXT_PAUSE_SOON="In 30 Sekunden ist Pause."
TEXT_SCHLUSS="Für heute ist Schluss."
# gw-kind may play tomorrow from 9 o'clock in K1; this is how the clock time appears in the closing text.
TEXT_SCHLUSS_FULL="Für heute ist Schluss. Morgen ab 9 Uhr kannst du wieder spielen."
TEXT_DENY="nicht eingeladen"
# Upper/lower case hint from provisioner/access_mod.py (substring, IN-07: without names).
TEXT_CASE_HINT="Groß- und Kleinschreibung"
# Parent texts from notify/texts.py.
SUBJECT_ATTEMPT="Unbekannter Spielername"
SUBJECT_SUMMARY="Weitere Beitrittsversuche"
SUBJECT_REVIEW="Tagesrückblick"
MESSAGE_REVIEW="Heute gespielt:"
STRANGERS="Fremder2 Fremder3 Fremder4 Fremder5 Fremder6"

# The prober prints kid texts with umlauts; on Windows otherwise cp1252.
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
BACKEND_DOWN=0
SPREED_DISABLED=0
ADMIN_PREFS=""
KID_JOB=""
GUEST_JOB=""
ADMIN_JOB=""
WORK_DIR=$(mktemp -d)

pass() {
	PASSED=$((PASSED + 1))
	TOTAL=$((TOTAL + 1))
	printf 'bestanden: %s\n' "$1"
}

fail() {
	FAILED=$((FAILED + 1))
	TOTAL=$((TOTAL + 1))
	printf 'FEHLGESCHLAGEN: %s\n' "$1" >&2
}

abort() {
	printf 'ABBRUCH: %s\n' "$1" >&2
	exit 1
}

# check DESCRIPTION CONDITION... -> pass or fail
check() {
	description=$1
	shift
	if "$@"; then
		pass "${description}"
	else
		fail "${description}"
	fi
}

occ() {
	docker compose -f "${COMPOSE_FILE}" exec -T -u www-data app php occ "$@"
}

# add_user ACCOUNT PASSWORD DISPLAYNAME -> creates the throwaway account fresh. An old account from
# an aborted run is deleted first; occ user:add gets up to three attempts
# (the password policy may ask an external service, which can fail
# briefly). On every failure the occ output is in the log as a diagnosis; the password
# goes to occ only via the environment and never appears in the output.
add_user() {
	occ user:delete "$1" >/dev/null 2>&1 || true
	add_try=1
	while [ "${add_try}" -le 3 ]; do
		if docker compose -f "${COMPOSE_FILE}" exec -T -u www-data -e OC_PASS="$2" app \
			php occ user:add --password-from-env --display-name="$3" "$1" >"${WORK_DIR}/user-add.log" 2>&1; then
			# German dev account (D-25): without a setting Nextcloud reports its default
			# language en, and the expected texts of this acceptance run are German.
			occ user:setting "$1" core lang de >/dev/null 2>&1 || return 1
			return 0
		fi
		printf 'occ user:add %s scheiterte (Versuch %s von 3): %s\n' "$1" "${add_try}" \
			"$(tr '\r\n' '  ' <"${WORK_DIR}/user-add.log" | cut -c1-300)" >&2
		occ user:delete "$1" >/dev/null 2>&1 || true
		add_try=$((add_try + 1))
		sleep 3
	done
	return 1
}

heartbeat_up() {
	curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1
}

# Ends the ExApp host process in a targeted way (PID file, otherwise only the process on
# the backend port); never all python.exe, so that parallel sessions keep running.
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

# restart_backend LOG -> ends the ExApp in a targeted way and starts it via register-exapp.sh
restart_backend() {
	BACKEND_DOWN=1
	kill_backend || return 1
	if [ -n "${2:-}" ]; then
		"$2"
	fi
	sh "${REGISTER_SCRIPT}" >"$1" 2>&1 || return 1
	BACKEND_DOWN=0
	heartbeat_up
}

# call AUTH METHOD URL OUTPUT [JSON] -> HTTP code
call() {
	if [ -n "${5:-}" ]; then
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' -H 'Content-Type: application/json' \
			-X "$2" -d "$5" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	else
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -H 'Accept: application/json' \
			-X "$2" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	fi
}

http_code() {
	call "${ADMIN_AUTH}" "$@"
}

remember_world() {
	[ -n "$1" ] && WORLD_IDS="${WORLD_IDS} $1"
	return 0
}

delete_world_hard() {
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null \
		"${API_URL}/worlds/$1" >/dev/null 2>&1 || true
	for container in $(docker ps -aq --filter "label=gameworld.world_id=$1" 2>/dev/null); do
		docker rm -f -v "${container}" >/dev/null 2>&1 || true
	done
	for volume in $(docker volume ls -q 2>/dev/null | grep -e "-$1\$" || true); do
		docker volume rm "${volume}" >/dev/null 2>&1 || true
	done
}

# Read-only SQL access to the ExApp file: sqlite3, otherwise the standard library.
sql() {
	if command -v sqlite3 >/dev/null 2>&1; then
		sqlite3 -readonly "${DB_FILE}" "$1"
		return
	fi
	db_path=${DB_FILE}
	command -v cygpath >/dev/null 2>&1 && db_path=$(cygpath -w "${DB_FILE}")
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
for row in con.execute(sys.argv[2]):
    print("|".join("" if v is None else str(v) for v in row))
' "${db_path}" "$1") 2>/dev/null | tr -d '\r'
}

# Writing SQL access, only from the preparation with a stopped ExApp (see header).
sql_write() {
	db_path=${DB_FILE}
	command -v cygpath >/dev/null 2>&1 && db_path=$(cygpath -w "${DB_FILE}")
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=10)
with con:
    for statement in sys.argv[2:]:
        con.execute(statement)
con.close()
' "${db_path}" "$@") >/dev/null 2>&1
}

reset_usage() {
	sql_write "DELETE FROM time_usage WHERE nc_user = '$1'" || true
}

# Delete today's foreign attempts, day marker (collective message) and review dispatch.
reset_today_notify() {
	sql_write "DELETE FROM join_attempts WHERE day = '${TODAY}'" \
		"DELETE FROM daily_flags WHERE day = '${TODAY}'" \
		"DELETE FROM review_sent WHERE day = '${TODAY}'"
}

# Time INPUTS only: ISO weekday today, tomorrow, local minute, date in
# Europe/Berlin. TZ=... date does not work here (Git Bash without zoneinfo).
berlin_now() {
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("Europe/Berlin"))
day = now.date()
print(now.isoweekday(), (day + timedelta(days=1)).isoweekday(), now.hour * 60 + now.minute, day.isoformat())
') 2>/dev/null | tr -d '\r'
}

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
not() { ! "$@"; }
matches() { printf '%s' "$1" | grep -Eq "$2"; }
user_present() { occ user:info "$1" >/dev/null 2>&1; }
user_absent() { ! user_present "$1"; }

reset_fixtures() {
	http_code POST "${API_URL}/pause/end" /dev/null >/dev/null 2>&1 || true
	http_code DELETE "${API_URL}/playtime/children/${KID}" /dev/null >/dev/null 2>&1 || true
	reset_usage "${KID}"
	occ group:removeuser admin "${KID}" >/dev/null 2>&1 || true
	occ user:delete "${GUEST}" >/dev/null 2>&1 || true
	occ user:delete "${ADMIN2}" >/dev/null 2>&1 || true
}

cleanup() {
	status=$?
	for job in ${KID_JOB} ${GUEST_JOB} ${ADMIN_JOB}; do
		kill "${job}" 2>/dev/null || true
	done
	if [ "${SPREED_DISABLED}" -eq 1 ]; then
		printf 'aktiviere Talk wieder\n'
		occ app:enable spreed >/dev/null 2>&1 || printf 'occ app:enable spreed scheiterte, bitte von Hand\n' >&2
	fi
	if [ "${BACKEND_DOWN}" -eq 1 ] || ! heartbeat_up; then
		printf 'starte die ExApp wieder (register-exapp.sh)\n'
		sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register-cleanup.log" 2>&1 \
			|| printf 'register-exapp.sh scheiterte, bitte von Hand starten\n' >&2
	fi
	for world_id in ${WORLD_IDS}; do
		delete_world_hard "${world_id}"
	done
	if [ -n "${ADMIN_PREFS}" ]; then
		http_code POST "${API_URL}/review/prefs" /dev/null "${ADMIN_PREFS}" >/dev/null 2>&1 || true
	fi
	reset_fixtures
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

container_of() {
	docker ps -aq --no-trunc --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1"
}

world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

wait_status() {
	waited=0
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		[ "${waited}" -lt "$3" ] || return 1
		sleep 1
		waited=$((waited + 1))
	done
}

player_field() {
	jq -r --arg u "$2" ".players[]? | select(.nc_user == \$u) | .$3 // empty" "$1" 2>/dev/null || true
}

# A join attempt or (with --hold) a session via the prober CLI, JSON to $1.
probe() {
	out=$1
	shift
	(cd "${REPO_ROOT}" && uv run python -m tests.e2e.luanti_probe "${PROBE_HOST}" "${PORT}" "$@") \
		>"${out}" 2>"${out}.err" || printf '{"result":"prober_error"}' >"${out}"
}

# probe_expect FILE JQ-CONDITION SECONDS NAME [PW] -> 0 as soon as the condition holds
probe_expect() {
	out=$1
	condition=$2
	limit=$3
	shift 3
	waited=0
	while :; do
		probe "${out}" "$@"
		[ "$(jq -r "${condition}" "${out}" 2>/dev/null || printf 'false')" = "true" ] && return 0
		[ "${waited}" -lt "${limit}" ] || return 1
		sleep 2
		waited=$((waited + 2))
	done
}

probe_summary() {
	jq -r '"\(.result) \(.code // "") \(.reason // "") \(.after_s // "")"' "$1" 2>/dev/null || printf 'nicht lesbar'
}

denied_with() {
	[ "$(jq -r --arg t "$2" '.result == "denied" and ((.reason // "") | contains($t))' "$1" 2>/dev/null)" = true ]
}

result_is() {
	[ "$(jq -r '.result' "$1" 2>/dev/null)" = "$2" ]
}

usage_today() {
	sql "SELECT COALESCE(SUM(seconds), 0) FROM time_usage WHERE nc_user = '$1' AND day = '${TODAY}'" | head -n 1
}

play_today() {
	sql "SELECT COALESCE(SUM(seconds), 0) FROM play_daily WHERE nc_user = '$1' AND day = '${TODAY}'" | head -n 1
}

# Notifications ---------------------------------------------------------

# num VALUE -> 0 if VALUE is a non-empty integer (WR-08: empty fetches never pass)
num() { printf '%s' "$1" | grep -Eq '^[0-9]+$'; }
# eq_num A B -> both numbers and equal
eq_num() { num "$1" && num "$2" && [ "$1" = "$2" ]; }

# notif_fetch AUTH FILE -> list of notifications as JSON; exit 1 on an HTTP code other than 200
# or a response without an OCS list (WR-08: a 401 or 404 never means "no notices").
notif_fetch() {
	fetch_code=$(call "$1" GET "${NOTIFY_URL}" "$2")
	[ "${fetch_code}" = 200 ] || return 1
	[ "$(jq -r '(.ocs.data | type) == "array"' "$2" 2>/dev/null)" = true ]
}

# notif_max AUTH -> highest notification_id of the account (baseline, 0 without entries), x on fetch failure
notif_max() {
	notif_fetch "$1" "${WORK_DIR}/nmax.json" || {
		printf 'x'
		return 0
	}
	jq -r '[.ocs.data[]?.notification_id] | max // 0' "${WORK_DIR}/nmax.json" 2>/dev/null || printf 'x'
}

# notif_new AUTH BASELINE SUBJECT FILE -> new Gameworld notifications with SUBJECT (JSON list);
# on a fetch failure or invalid baseline FEHLER is in FILE (no JSON, length fails).
notif_new() {
	if ! num "$2" || ! notif_fetch "$1" "${WORK_DIR}/nall.json"; then
		printf 'FEHLER' >"$4"
		return 0
	fi
	jq -c --argjson b "$2" --arg s "$3" \
		'[.ocs.data[]? | select(.app == "gameworld" and .notification_id > $b and (.subject | contains($s)))]' \
		"${WORK_DIR}/nall.json" >"$4" 2>/dev/null || printf 'FEHLER' >"$4"
}

# notif_count AUTH BASELINE SUBJECT -> count, x on fetch failure (then every eq fails)
notif_count() {
	notif_new "$1" "$2" "$3" "${WORK_DIR}/ncount.json"
	jq -r 'length' "${WORK_DIR}/ncount.json" 2>/dev/null || printf 'x'
}

# notif_wait AUTH BASELINE SUBJECT COUNT SECONDS -> 0 as soon as at least COUNT are there
notif_wait() {
	waited=0
	while :; do
		[ "$(notif_count "$1" "$2" "$3")" -ge "$4" ] 2>/dev/null && return 0
		[ "${waited}" -lt "$5" ] || return 1
		sleep 3
		waited=$((waited + 3))
	done
}

# Talk ---------------------------------------------------------------------

room_token_of() {
	http_code GET "${SPREED}/v4/room" "${WORK_DIR}/rooms.json" >/dev/null
	jq -r --arg n "Gameworld: $1" '[.ocs.data[]? | select(.name == $n) | .token][0] // empty' \
		"${WORK_DIR}/rooms.json" 2>/dev/null || true
}

# Prerequisites ---------------------------------------------------------
for tool in docker curl jq grep awk uv; do
	command -v "${tool}" >/dev/null 2>&1 || abort "Werkzeug ${tool} fehlt"
done
if ! curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
	abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
occ app_api:app:list 2>/dev/null | grep -q '^gameworld ' || abort "Gameworld ist nicht registriert. Zuerst: sh scripts/dev/register-exapp.sh"
heartbeat_up || abort "ExApp antwortet nicht auf Port ${BACKEND_PORT}. Zuerst: sh scripts/dev/register-exapp.sh"
user_present "${KID}" || abort "Konto ${KID} fehlt (legt acceptance-phase1.sh an)"
[ -f "${DB_FILE}" ] || abort "SQLite-Datei fehlt: ${DB_FILE}"
[ -n "$(berlin_now)" ] || abort "berlin_now liefert nichts (tzdata im venv? uv sync)"
SPREED_VERSION=$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty' 2>/dev/null || true)
[ -n "${SPREED_VERSION}" ] || abort "Talk (spreed) ist nicht aktiviert (siehe docs/dev-setup.md, Talk im Dev-Stack)"
[ -f "${TALK_SMOKE}" ] || abort "smoke-talk.sh fehlt"

# The review test (K3) sets the running minute minus 1: for that it needs minute 16
# or later, and the run should not cross midnight (day boundary).
set -- $(berlin_now)
if [ "$3" -lt 16 ]; then
	pause=$(((16 - $3) * 60))
	printf 'Es ist kurz nach Mitternacht, warte %s s bis 0:16\n' "${pause}"
	sleep "${pause}"
elif [ "$3" -ge 1380 ]; then
	pause=$(((1456 - $3) * 60))
	printf 'Es ist nach 23 Uhr (Lauf etwa 40 Minuten), warte %s s bis 0:16\n' "${pause}"
	sleep "${pause}"
fi
set -- $(berlin_now)
TODAY_WD=$1
TOMORROW_WD=$2
TODAY=$4
printf 'Zeit-Eingaben (Europe/Berlin): Wochentag %s, morgen %s, Minute %s, Datum %s\n' "$1" "$2" "$3" "$4"

printf '\n== Vorbereitung ==\n'
reset_fixtures
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --argjson names "${ACCEPTANCE_WORLDS}" \
	'.worlds[]? | select(.name as $n | $names | index($n)) | .id' "${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	delete_world_hard "${old_id}"
done
# Baseline: world containers that existed before this run (other ExApp instances,
# test leftovers of other sessions) stay untouched and do not count as leftovers at the end.
BASELINE_CONTAINERS=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | tr '
' ' ')

for account in "${GUEST}:${GUEST_PASS}:Gast Abnahme 41" "${ADMIN2}:${ADMIN2_PASS}:Verwalter Zwei"; do
	uid=${account%%:*}
	rest=${account#*:}
	add_user "${uid}" "${rest%%:*}" "${rest#*:}" || abort "Konto ${uid} ließ sich nach drei Versuchen nicht anlegen (occ-Ausgabe oben)"
done
occ group:adduser admin "${ADMIN2}" >/dev/null 2>&1 || abort "${ADMIN2} ließ sich nicht in admin aufnehmen"
check "zweites Verwalter-Konto ${ADMIN2} in Gruppe admin" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${ADMIN2}" '(.admin // []) | index($u) != null')" true

# Targeted restart: fresh manager snapshot without throttle; today's
# notification data are reset as long as nobody writes.
printf 'starte die ExApp gezielt neu (Zurücksetzen der heutigen Hinweise)\n'
check "Vorbereitung: ExApp gezielt neu gestartet, heutige Hinweise zurückgesetzt" \
	restart_backend "${WORK_DIR}/register-pre.log" reset_today_notify
heartbeat_up || abort "ExApp nach dem Neustart nicht erreichbar"
check "Vorbereitung: keine Fremdversuche und kein Rückblick-Versand für ${TODAY} (sqlite3)" \
	eq "$(sql "SELECT (SELECT count(*) FROM join_attempts WHERE day = '${TODAY}') + (SELECT count(*) FROM review_sent WHERE day = '${TODAY}')")" 0

# First address applies, a change only when confirmed (WR-04): the acceptance confirms explicitly.
CODE=$(http_code POST "${API_URL}/origin" "${WORK_DIR}/origin.json" \
	"{\"origin\":\"${NEXTCLOUD_URL}\",\"webroot\":\"\",\"confirm\":true}")
check "POST /api/origin ${NEXTCLOUD_URL} (bestätigt) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
ORIGIN_NOW=$(sql "SELECT value FROM meta WHERE key = 'link_origin'")
check "link_origin ist ${NEXTCLOUD_URL} (ist ${ORIGIN_NOW:-leer})" eq "${ORIGIN_NOW}" "${NEXTCLOUD_URL}"
CODE=$(call "${KID_AUTH}" POST "${API_URL}/origin" /dev/null '{"origin":"http://evil.example","confirm":true}')
# Since 06-02 (ROLLE-03) all routes are USER; the lock sits in the backend (require_verwalter) and answers exactly 403.
check "Negativkontrolle: ${KID} setzt die Basis-URL nicht, HTTP 403 (ist ${CODE})" eq "${CODE}" 403
ORIGIN_AFTER=$(sql "SELECT value FROM meta WHERE key = 'link_origin'")
check "Negativkontrolle: link_origin danach unverändert (ist ${ORIGIN_AFTER:-leer})" \
	sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ "${ORIGIN_AFTER}" "${ORIGIN_NOW}"
CODE=$(http_code GET "${API_URL}/worlds" "${WORK_DIR}/visit.json")
check "Verwalter-Besuch GET /api/worlds HTTP 200 (ist ${CODE})" eq "${CODE}" 200
ADMINS=""
waited=0
while [ "${waited}" -le 15 ]; do
	ADMINS=$(sql "SELECT value FROM meta WHERE key = 'time_admins'")
	printf '%s' "${ADMINS}" | grep -q "\"${ADMIN2}\"" && break
	sleep 3
	waited=$((waited + 3))
done
check "Verwalter-Schnappschuss enthält admin und ${ADMIN2}, nicht ${KID} (ist ${ADMINS:-leer})" sh -c \
	'printf "%s" "$1" | grep -q "\"admin\"" && printf "%s" "$1" | grep -q "\"$2\"" && ! printf "%s" "$1" | grep -q "\"$3\""' \
	_ "${ADMINS}" "${ADMIN2}" "${KID}"

# Review off until K3: this way none arrives too early if the clock is already past the default.
http_code GET "${API_URL}/review/prefs" "${WORK_DIR}/prefs-old.json" >/dev/null
ADMIN_PREFS=$(jq -c '{enabled, minute}' "${WORK_DIR}/prefs-old.json" 2>/dev/null || true)
check "GET /review/prefs von admin lesbar (ist ${ADMIN_PREFS:-leer})" matches "${ADMIN_PREFS}" '"minute":[0-9]+'
CODE=$(http_code POST "${API_URL}/review/prefs" /dev/null '{"enabled":false,"minute":1200}')
check "Rückblick admin vorerst aus HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${ADMIN2_AUTH}" POST "${API_URL}/review/prefs" /dev/null '{"enabled":false,"minute":1200}')
check "Rückblick ${ADMIN2} aus HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${KID_AUTH}" POST "${API_URL}/review/prefs" /dev/null '{"enabled":true,"minute":600}')
# A crashed backend (500, 503) or curl error (000) does not pass this way (WR-08).
check "Negativkontrolle: ${KID} hat keine Rückblick-Einstellung, HTTP 403 (ist ${CODE})" eq "${CODE}" 403
KID_PREFS=$(sql "SELECT count(*) FROM review_prefs WHERE nc_user = '${KID}'")
check "Negativkontrolle: keine Rückblick-Zeile für ${KID} in review_prefs (ist ${KID_PREFS:-leer})" eq "${KID_PREFS}" 0

CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/world.json" "{\"name\":\"${NAME_PAUSE}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/world.json" 2>/dev/null || true)
remember_world "${WORLD_ID}"
check "POST '${NAME_PAUSE}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
matches "${WORLD_ID}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
check "Welt running binnen 60 s" wait_status "${WORLD_ID}" running 60
CONTAINER=$(container_of "${WORLD_ID}")
[ -n "${CONTAINER}" ] || abort "kein Container mit Label gameworld.world_id"
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
matches "${PORT}" '^[0-9]+$' || abort "kein UDP-Port"
for target in "${KID}" "${GUEST}" admin; do
	CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv.json" "{\"kind\":\"user\",\"target\":\"${target}\"}")
	check "POST invites user ${target} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
done
http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "${WORK_DIR}/players.json" >/dev/null
KID_NAME=$(player_field "${WORK_DIR}/players.json" "${KID}" player_name)
KID_PW=$(player_field "${WORK_DIR}/players.json" "${KID}" password)
GUEST_NAME=$(player_field "${WORK_DIR}/players.json" "${GUEST}" player_name)
GUEST_PW=$(player_field "${WORK_DIR}/players.json" "${GUEST}" password)
ADMIN_NAME=$(player_field "${WORK_DIR}/players.json" admin player_name)
ADMIN_PW=$(player_field "${WORK_DIR}/players.json" admin password)
check "Spielernamen und Passwörter vorhanden (${KID_NAME}, ${GUEST_NAME}, ${ADMIN_NAME}; Längen ${#KID_PW}, ${#GUEST_PW}, ${#ADMIN_PW})" \
	sh -c 'for v in "$@"; do [ -n "$v" ] || exit 1; done' _ "${KID_NAME}" "${KID_PW}" "${GUEST_NAME}" "${GUEST_PW}" "${ADMIN_NAME}" "${ADMIN_PW}"
# gw-kind gets rules (today whole day 120 min, tomorrow from 9 o'clock), so that its
# usage counts and the closing text can name a real start time; gw-abnahme41
# stays without rules (the pause applies to all children, even without rules).
PLAN=$(jq -nc --argjson t "${TODAY_WD}" --argjson m "${TOMORROW_WD}" '{normal: [range(1; 8) as $d
	| if $d == $t then {weekday: $d, allowed: true, limit_minutes: 120, window_start: 0, window_end: 1440}
	elif $d == $m then {weekday: $d, allowed: true, limit_minutes: 120, window_start: 540, window_end: 1140}
	else {weekday: $d, allowed: false} end]}')
CODE=$(http_code POST "${API_URL}/playtime/children/${KID}" "${WORK_DIR}/plan.json" "${PLAN}")
check "Regeln für ${KID} (heute ganzer Tag, morgen ab 9 Uhr) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Positivkontrolle: ${KID} kommt vor der Pause hinein (auth_accept)" \
	probe_expect "${WORK_DIR}/pre-kid.json" '.result == "auth_accept"' 15 "${KID_NAME}" "${KID_PW}"
sleep 2.5

printf '\n== K1 Pause für alle Welten ==\n'
# K1 Parents pause all worlds from the phone, children separately, managers stay (SC 1)
printf 'Sitzungen %s, %s und admin für bis zu 70 s\n' "${KID}" "${GUEST}"
probe "${WORK_DIR}/k1-kid.json" "${KID_NAME}" "${KID_PW}" --hold 70 --timeout "${SESSION_TIMEOUT}" &
KID_JOB=$!
probe "${WORK_DIR}/k1-guest.json" "${GUEST_NAME}" "${GUEST_PW}" --hold 70 --timeout "${SESSION_TIMEOUT}" &
GUEST_JOB=$!
probe "${WORK_DIR}/k1-admin.json" "${ADMIN_NAME}" "${ADMIN_PW}" --hold 70 --timeout "${SESSION_TIMEOUT}" &
ADMIN_JOB=$!
sleep 10
CODE=$(http_code POST "${API_URL}/pause" "${WORK_DIR}/pause.json" '{"minutes":15}')
check "K1 POST /pause minutes 15 HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K1 Antwort active true, art pause, bis = ab + 900 s" \
	eq "$(jq -r '.active == true and .art == "pause" and (.bis - .ab) == 900' "${WORK_DIR}/pause.json" 2>/dev/null)" true
check "K1 Antwort nennt until_clock H:MM (ist $(jq -r '.until_clock' "${WORK_DIR}/pause.json" 2>/dev/null))" \
	matches "$(jq -r '.until_clock // empty' "${WORK_DIR}/pause.json" 2>/dev/null)" '^[0-9]{1,2}:[0-9]{2}$'
check "K1 Welt '${NAME_PAUSE}' applied true (Regeldatei in der laufenden Welt)" \
	eq "$(jq -r --arg id "${WORLD_ID}" '.worlds[]? | select(.id == $id) | .applied' "${WORK_DIR}/pause.json" 2>/dev/null)" true
CODE=$(http_code POST "${API_URL}/pause" /dev/null '{"minutes":20}')
check "K1 Negativkontrolle: minutes 20 HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(http_code POST "${API_URL}/pause" /dev/null '{"minutes":"15"}')
check "K1 Negativkontrolle: minutes als Text HTTP 422 (ist ${CODE})" eq "${CODE}" 422
PAUSE_BEFORE=$(sql "SELECT bis FROM pause_state WHERE id = 1")
CODE=$(call "${KID_AUTH}" POST "${API_URL}/pause" /dev/null '{"minutes":15}')
check "K1 Negativkontrolle: ${KID} startet keine Pause, HTTP 403 (ist ${CODE})" eq "${CODE}" 403
PAUSE_AFTER=$(sql "SELECT bis FROM pause_state WHERE id = 1")
check "K1 Negativkontrolle: Pausenende danach unverändert (${PAUSE_BEFORE:-leer} -> ${PAUSE_AFTER:-leer})" \
	eq_num "${PAUSE_AFTER}" "${PAUSE_BEFORE}"
wait "${KID_JOB}" || true
KID_JOB=""
wait "${GUEST_JOB}" || true
GUEST_JOB=""
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k1-kid.json")"
jq -r '.events[]? | "  \(.t) s \(.kind): \(.text)"' "${WORK_DIR}/k1-kid.json" 2>/dev/null || true
check "K1 ${KID} getrennt (result kicked)" result_is "${WORK_DIR}/k1-kid.json" kicked
check "K1 Trenntext von ${KID} enthält '${TEXT_PAUSE}'" \
	eq "$(jq -r --arg t "${TEXT_PAUSE}" '(.reason // "") | contains($t)' "${WORK_DIR}/k1-kid.json" 2>/dev/null)" true
KICK_AFTER=$(jq -r '.after_s // 0' "${WORK_DIR}/k1-kid.json" 2>/dev/null || printf '0')
check "K1 vorher Chat '${TEXT_PAUSE_SOON}'" \
	eq "$(jq -r --arg t "${TEXT_PAUSE_SOON}" --argjson k "${KICK_AFTER}" \
		'[.events[]? | select(.kind == "chat" and (.text | contains($t)) and .t < $k)] | length > 0' \
		"${WORK_DIR}/k1-kid.json" 2>/dev/null)" true
check "K1 Trennen erst nach dem Vorlauf: Pause etwa 10 s nach Sitzungsbeginn plus 30 s, also 35 bis 60 s (ist ${KICK_AFTER} s)" \
	awk -v v="${KICK_AFTER}" 'BEGIN { exit !(v + 0 >= 35 && v + 0 <= 60) }'
printf '%s: %s\n' "${GUEST}" "$(probe_summary "${WORK_DIR}/k1-guest.json")"
check "K1 ${GUEST} ohne Regeln ebenfalls getrennt mit '${TEXT_PAUSE}'" sh -c \
	'[ "$(jq -r --arg t "$2" ".result == \"kicked\" and ((.reason // \"\") | contains(\$t))" "$1")" = true ]' _ \
	"${WORK_DIR}/k1-guest.json" "${TEXT_PAUSE}"
# Wait out the rejoin lock of the world (about 2 s after leaving).
sleep 2.5
probe "${WORK_DIR}/k1-join.json" "${KID_NAME}" "${KID_PW}"
check "K1 Beitritt von ${KID} in der Pause denied mit '${TEXT_PAUSE}' ($(probe_summary "${WORK_DIR}/k1-join.json"))" \
	denied_with "${WORK_DIR}/k1-join.json" "${TEXT_PAUSE}"
# The ExApp books the seconds until disconnect only in the next 15 s cycle; therefore first
# wait one cycle plus loop (20 s), then measure over two further cycles.
sleep 20
USAGE_A=$(usage_today "${KID}")
PLAY_A=$(play_today "${KID}")
printf 'warte zwei Takte (35 s): Verbrauch %s s, Spielzeit %s s\n' "${USAGE_A}" "${PLAY_A}"
sleep 35
USAGE_B=$(usage_today "${KID}")
PLAY_B=$(play_today "${KID}")
# Both sides must be numbers: if sql fails, both would otherwise be empty and equal (WR-08).
check "K1 time_usage von ${KID} steigt in der Pause nicht (${USAGE_A:-leer} -> ${USAGE_B:-leer})" \
	eq_num "${USAGE_B}" "${USAGE_A}"
check "K1 play_daily von ${KID} steigt in der Pause nicht (${PLAY_A:-leer} -> ${PLAY_B:-leer})" eq_num "${PLAY_B}" "${PLAY_A}"
wait "${ADMIN_JOB}" || true
ADMIN_JOB=""
printf 'admin: %s\n' "$(probe_summary "${WORK_DIR}/k1-admin.json")"
check "K1 Verwalter admin bleibt 70 s verbunden (result held)" result_is "${WORK_DIR}/k1-admin.json" held
http_code GET "${API_URL}/pause" "${WORK_DIR}/pause-get.json" >/dev/null
check "K1 GET /pause meldet die laufende Pause (active true)" \
	eq "$(jq -r '.active' "${WORK_DIR}/pause-get.json" 2>/dev/null)" true
CODE=$(http_code POST "${API_URL}/pause/end" "${WORK_DIR}/pause-end.json")
check "K1 POST /pause/end HTTP 200, active false (ist ${CODE} $(jq -r '.active' "${WORK_DIR}/pause-end.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '.active' "${WORK_DIR}/pause-end.json" 2>/dev/null)" "200 false"
check "K1 nach Weiter: ${KID} auth_accept" \
	probe_expect "${WORK_DIR}/k1-after.json" '.result == "auth_accept"' 15 "${KID_NAME}" "${KID_PW}"
USAGE_S=$(usage_today "${KID}")
CODE=$(http_code POST "${API_URL}/pause/schluss" "${WORK_DIR}/schluss.json")
check "K1 POST /pause/schluss HTTP 200, art schluss (ist ${CODE} $(jq -r '.art' "${WORK_DIR}/schluss.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '.art' "${WORK_DIR}/schluss.json" 2>/dev/null)" "200 schluss"
check "K1 nach Schluss: ${KID} denied mit '${TEXT_SCHLUSS}'" \
	probe_expect "${WORK_DIR}/k1-schluss.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_SCHLUSS}\"))" 15 \
	"${KID_NAME}" "${KID_PW}"
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k1-schluss.json")"
check "K1 Schluss-Text nennt die Startzeit von morgen ('${TEXT_SCHLUSS_FULL}')" \
	denied_with "${WORK_DIR}/k1-schluss.json" "${TEXT_SCHLUSS_FULL}"
sleep 20
USAGE_S2=$(usage_today "${KID}")
check "K1 time_usage nach Schluss unverändert (${USAGE_S:-leer} -> ${USAGE_S2:-leer})" eq_num "${USAGE_S2}" "${USAGE_S}"
CODE=$(http_code POST "${API_URL}/pause/end" "${WORK_DIR}/pause-end2.json")
check "K1 POST /pause/end nach Schluss HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K1 Positivkontrolle: nach Weiter kommt ${KID} wieder hinein" \
	probe_expect "${WORK_DIR}/k1-after2.json" '.result == "auth_accept"' 15 "${KID_NAME}" "${KID_PW}"

printf '\n== K2 Hinweis bei fremdem Beitrittsversuch ==\n'
# K2 Foreign name: notice to all managers with link, throttled (SC 2)
BASE_ADMIN=$(notif_max "${ADMIN_AUTH}")
BASE_ADMIN2=$(notif_max "${ADMIN2_AUTH}")
BASE_KID=$(notif_max "${KID_AUTH}")
check "K2 Grundlinien der Benachrichtigungen lesbar (admin ${BASE_ADMIN}, ${ADMIN2} ${BASE_ADMIN2}, ${KID} ${BASE_KID})" \
	sh -c 'for v in "$@"; do printf "%s" "$v" | grep -Eq "^[0-9]+$" || exit 1; done' _ \
	"${BASE_ADMIN}" "${BASE_ADMIN2}" "${BASE_KID}"
printf 'Grundlinie der Benachrichtigungen: admin %s, %s %s, %s %s\n' \
	"${BASE_ADMIN}" "${ADMIN2}" "${BASE_ADMIN2}" "${KID}" "${BASE_KID}"
probe "${WORK_DIR}/k2-f1.json" Fremder1
check "K2 'Fremder1' denied mit '${TEXT_DENY}' ($(probe_summary "${WORK_DIR}/k2-f1.json"))" \
	denied_with "${WORK_DIR}/k2-f1.json" "${TEXT_DENY}"
check "K2 admin bekommt binnen ${NOTIFY_WAIT} s einen Hinweis '${SUBJECT_ATTEMPT}'" \
	notif_wait "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_ATTEMPT}" 1 "${NOTIFY_WAIT}"
notif_new "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_ATTEMPT}" "${WORK_DIR}/k2-admin.json"
check "K2 admin hat genau einen Hinweis (ist $(jq -r 'length' "${WORK_DIR}/k2-admin.json"))" \
	eq "$(jq -r 'length' "${WORK_DIR}/k2-admin.json")" 1
jq -r '.[0] | "  Betreff: \(.subject)\n  Text: \(.message)\n  Link: \(.link)"' "${WORK_DIR}/k2-admin.json" 2>/dev/null || true
check "K2 Betreff nennt die Welt '${NAME_PAUSE}'" \
	eq "$(jq -r --arg w "${NAME_PAUSE}" '.[0].subject | contains($w)' "${WORK_DIR}/k2-admin.json" 2>/dev/null)" true
# Since da2ad56 the text reads "<Name> wollte um H:MM beitreten." (without "Uhr").
check "K2 Text nennt Fremder1 und eine Uhrzeit" \
	eq "$(jq -r '.[0].message | (contains("Fremder1") and test("um [0-9]{1,2}:[0-9]{2} beitreten"))' "${WORK_DIR}/k2-admin.json" 2>/dev/null)" true
LINK=$(jq -r '.[0].link // empty' "${WORK_DIR}/k2-admin.json" 2>/dev/null || true)
check "K2 Link absolut auf die Seite versuch mit welt=${WORLD_ID} und tag=${TODAY} (ist ${LINK:-leer})" sh -c \
	'case "$1" in "$2"/versuch*) ;; *) exit 1 ;; esac; printf "%s" "$1" | grep -q "welt=$3" && printf "%s" "$1" | grep -q "tag=$4"' \
	_ "${LINK}" "${EMBED_URL}" "${WORLD_ID}" "${TODAY}"
notif_wait "${ADMIN2_AUTH}" "${BASE_ADMIN2}" "${SUBJECT_ATTEMPT}" 1 15 || true
notif_new "${ADMIN2_AUTH}" "${BASE_ADMIN2}" "${SUBJECT_ATTEMPT}" "${WORK_DIR}/k2-admin2.json"
check "K2 ${ADMIN2} bekommt ebenfalls genau einen Hinweis (ist $(jq -r 'length' "${WORK_DIR}/k2-admin2.json"))" \
	eq "$(jq -r 'length' "${WORK_DIR}/k2-admin2.json")" 1
ADMIN2_LINK=$(jq -r '.[0].link // empty' "${WORK_DIR}/k2-admin2.json" 2>/dev/null || true)
check "K2 Link von ${ADMIN2} gleich dem von admin (nicht leer)" sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ \
	"${ADMIN2_LINK}" "${LINK}"
check "K2 ${KID} hat keinen Hinweis (ist $(notif_count "${KID_AUTH}" "${BASE_KID}" ""))" \
	eq "$(notif_count "${KID_AUTH}" "${BASE_KID}" "")" 0
printf 'Fremder1 fünfmal erneut, Groß/Klein-Variante und falsches Passwort\n'
i=1
while [ "${i}" -le 5 ]; do
	probe "${WORK_DIR}/k2-again.json" Fremder1
	sleep 1
	i=$((i + 1))
done
CASE_NAME=$(printf '%s' "${KID_NAME}" | tr '[:lower:]' '[:upper:]')
[ "${CASE_NAME}" = "${KID_NAME}" ] && CASE_NAME=$(printf '%s' "${KID_NAME}" | tr '[:upper:]' '[:lower:]')
probe "${WORK_DIR}/k2-case.json" "${CASE_NAME}"
# The expected result is the concrete rejection, never "not auth_accept": a prober error (world
# not reachable) would otherwise pass (WR-08). The notice does not name the invited name (IN-07).
check "K2 Groß/Klein-Variante '${CASE_NAME}' denied mit '${TEXT_CASE_HINT}', ohne den Namen ($(probe_summary "${WORK_DIR}/k2-case.json"))" \
	sh -c '[ "$(jq -r --arg t "$2" --arg n "$3" ".result == \"denied\" and ((.reason // \"\") | (contains(\$t) and (contains(\$n) | not)))" "$1" 2>/dev/null)" = true ]' _ \
	"${WORK_DIR}/k2-case.json" "${TEXT_CASE_HINT}" "${KID_NAME}"
probe "${WORK_DIR}/k2-wrongpw.json" "${KID_NAME}" "falsch-falsch-falsch"
check "K2 falsches Passwort für ${KID_NAME} denied mit WRONG_PASSWORD ($(probe_summary "${WORK_DIR}/k2-wrongpw.json"))" \
	sh -c '[ "$(jq -r ".result == \"denied\" and .code == \"WRONG_PASSWORD\"" "$1" 2>/dev/null)" = true ]' _ \
	"${WORK_DIR}/k2-wrongpw.json"
sleep "${NOTIFY_WAIT}"
check "K2 Drossel: admin hat nach Wiederholung, Variante und falschem Passwort weiter genau einen Hinweis (ist $(notif_count "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_ATTEMPT}"))" \
	eq "$(notif_count "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_ATTEMPT}")" 1
check "K2 kein Hinweis zur Variante '${CASE_NAME}' (D-29)" \
	eq "$(jq -r --arg n "${CASE_NAME}" '[.[] | select(.message | contains($n))] | length' "${WORK_DIR}/ncount.json" 2>/dev/null)" 0
printf 'fünf weitere neue Namen: %s\n' "${STRANGERS}"
for stranger in ${STRANGERS}; do
	probe "${WORK_DIR}/k2-${stranger}.json" "${stranger}"
	sleep 1
done
check "K2 admin hat binnen ${NOTIFY_WAIT} s die Sammelnachricht '${SUBJECT_SUMMARY}'" \
	notif_wait "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_SUMMARY}" 1 "${NOTIFY_WAIT}"
sleep 10
for who in "admin:${ADMIN_AUTH}:${BASE_ADMIN}" "${ADMIN2}:${ADMIN2_AUTH}:${BASE_ADMIN2}"; do
	label=${who%%:*}
	rest=${who#*:}
	base=${rest##*:}
	auth=${rest%:*}
	singles=$(notif_count "${auth}" "${base}" "${SUBJECT_ATTEMPT}")
	summaries=$(notif_count "${auth}" "${base}" "${SUBJECT_SUMMARY}")
	check "K2 ${label}: insgesamt 5 Einzelhinweise und genau eine Sammelnachricht (ist ${singles} und ${summaries})" \
		eq "${singles} ${summaries}" "5 1"
done
notif_new "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_SUMMARY}" "${WORK_DIR}/k2-summary.json"
check "K2 Link der Sammelnachricht zeigt auf versuch mit tag=${TODAY}" sh -c \
	'case "$1" in "$2"/versuch*tag="$3"*) exit 0 ;; *) exit 1 ;; esac' _ \
	"$(jq -r '.[0].link // empty' "${WORK_DIR}/k2-summary.json")" "${EMBED_URL}" "${TODAY}"
CODE=$(http_code GET "${API_URL}/attempts?day=${TODAY}" "${WORK_DIR}/attempts.json")
check "K2 GET /attempts?day=${TODAY} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 Liste enthält Fremder1 bis Fremder6 mit Uhrzeit H:MM und Welt '${NAME_PAUSE}'" \
	eq "$(jq -r --arg w "${NAME_PAUSE}" '[.attempts[]? | select(.world_name == $w and (.clock | test("^[0-9]{1,2}:[0-9]{2}$"))) | .player_name]
		| (index("Fremder1") != null) and (index("Fremder2") != null) and (index("Fremder3") != null)
		and (index("Fremder4") != null) and (index("Fremder5") != null) and (index("Fremder6") != null)' \
		"${WORK_DIR}/attempts.json" 2>/dev/null)" true
# The repetitions of Fremder1 within 60 s do not raise the counter: the world mod
# reports at most one deny per name per 60 s (access_mod.DENY_PER_NAME_SECONDS).
check "K2 Fremder1 genau einmal in der Liste (ist $(jq -r '[.attempts[]? | select(.player_name == "Fremder1")] | length' "${WORK_DIR}/attempts.json"))" \
	eq "$(jq -r '[.attempts[]? | select(.player_name == "Fremder1")] | length' "${WORK_DIR}/attempts.json" 2>/dev/null)" 1
check "K2 Variante '${CASE_NAME}' und ${KID_NAME} stehen nicht in der Liste" \
	eq "$(jq -r --arg a "${CASE_NAME}" --arg b "${KID_NAME}" '[.attempts[]? | select((.player_name | ascii_downcase) == ($a | ascii_downcase) or .player_name == $b)] | length' \
		"${WORK_DIR}/attempts.json" 2>/dev/null)" 0
CODE=$(http_code GET "${API_URL}/attempts?day=${TODAY}&world=${WORLD_ID}" "${WORK_DIR}/attempts-w.json")
check "K2 Filter world=${WORLD_ID}: HTTP 200 und 6 Namen (ist ${CODE} $(jq -r '.attempts | length' "${WORK_DIR}/attempts-w.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '.attempts | length' "${WORK_DIR}/attempts-w.json" 2>/dev/null)" "200 6"
CODE=$(http_code GET "${API_URL}/attempts?day=kaputt" /dev/null)
check "K2 Negativkontrolle: day=kaputt HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(call "${KID_AUTH}" GET "${API_URL}/attempts?day=${TODAY}" /dev/null)
check "K2 Negativkontrolle: ${KID} liest /attempts nicht, HTTP 403 (ist ${CODE})" eq "${CODE}" 403

printf '\n== K3 Tagesrückblick ==\n'
# K3 Review once a day per manager, can be switched off, restart-proof (SC 3)
printf 'Sitzung %s für 70 s\n' "${KID}"
probe "${WORK_DIR}/k3-kid.json" "${KID_NAME}" "${KID_PW}" --hold 70 --timeout "${SESSION_TIMEOUT}"
check "K3 ${KID} spielt 70 s (result held)" result_is "${WORK_DIR}/k3-kid.json" held
PLAY_K3=""
waited=0
while [ "${waited}" -le 30 ]; do
	PLAY_K3=$(play_today "${KID}")
	[ "${PLAY_K3:-0}" -ge 60 ] 2>/dev/null && break
	sleep 3
	waited=$((waited + 3))
done
check "K3 play_daily von ${KID} heute mindestens 60 s (ist ${PLAY_K3:-leer})" sh -c '[ "${1:-0}" -ge 60 ]' _ "${PLAY_K3}"
set -- $(berlin_now)
REVIEW_MINUTE=$(($3 - 1))
BASE_ADMIN=$(notif_max "${ADMIN_AUTH}")
BASE_ADMIN2=$(notif_max "${ADMIN2_AUTH}")
CODE=$(http_code POST "${API_URL}/review/prefs" "${WORK_DIR}/prefs.json" "{\"enabled\":true,\"minute\":${REVIEW_MINUTE}}")
check "K3 Rückblick admin an, Minute ${REVIEW_MINUTE} (jetzt minus 1): HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(http_code POST "${API_URL}/review/prefs" /dev/null '{"enabled":true,"minute":1440}')
check "K3 Negativkontrolle: Minute 1440 HTTP 422 (ist ${CODE})" eq "${CODE}" 422
check "K3 admin bekommt binnen ${NOTIFY_WAIT} s einen '${SUBJECT_REVIEW}'" \
	notif_wait "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_REVIEW}" 1 "${NOTIFY_WAIT}"
sleep 10
notif_new "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_REVIEW}" "${WORK_DIR}/k3-review.json"
jq -r '.[0] | "  Betreff: \(.subject)\n  Text: \(.message)\n  Link: \(.link)"' "${WORK_DIR}/k3-review.json" 2>/dev/null || true
check "K3 genau ein Rückblick für admin (ist $(jq -r 'length' "${WORK_DIR}/k3-review.json"))" \
	eq "$(jq -r 'length' "${WORK_DIR}/k3-review.json")" 1
check "K3 Text enthält '${MESSAGE_REVIEW}' und Minuten" \
	eq "$(jq -r --arg t "${MESSAGE_REVIEW}" '.[0].message | (contains($t) and test("[0-9]+ Min\\."))' "${WORK_DIR}/k3-review.json" 2>/dev/null)" true
check "K3 Link absolut auf rueckblick?tag=${TODAY}" sh -c \
	'case "$1" in "$2"/rueckblick*tag="$3"*) exit 0 ;; *) exit 1 ;; esac' _ \
	"$(jq -r '.[0].link // empty' "${WORK_DIR}/k3-review.json")" "${EMBED_URL}" "${TODAY}"
check "K3 ${ADMIN2} (Rückblick aus) bekommt keinen (ist $(notif_count "${ADMIN2_AUTH}" "${BASE_ADMIN2}" "${SUBJECT_REVIEW}"))" \
	eq "$(notif_count "${ADMIN2_AUTH}" "${BASE_ADMIN2}" "${SUBJECT_REVIEW}")" 0
printf 'starte die ExApp gezielt neu (Rückblick darf nicht doppelt kommen)\n'
check "K3 ExApp gezielt neu gestartet" restart_backend "${WORK_DIR}/register-k3.log"
sleep 30
check "K3 nach Neustart und 30 s weiter genau ein Rückblick (ist $(notif_count "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_REVIEW}"))" \
	eq "$(notif_count "${ADMIN_AUTH}" "${BASE_ADMIN}" "${SUBJECT_REVIEW}")" 1
check "K3 review_sent hat genau eine Zeile für admin am ${TODAY} (sqlite3)" \
	eq "$(sql "SELECT count(*) FROM review_sent WHERE nc_user = 'admin' AND day = '${TODAY}'")" 1
check "K3 review_sent hat keine Zeile für ${ADMIN2} (sqlite3)" \
	eq "$(sql "SELECT count(*) FROM review_sent WHERE nc_user = '${ADMIN2}' AND day = '${TODAY}'")" 0
CODE=$(http_code GET "${API_URL}/review?day=${TODAY}" "${WORK_DIR}/review.json")
check "K3 GET /review?day=${TODAY} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 Rückblick zeigt ${KID} mit Minuten größer 0 in '${NAME_PAUSE}' (ist $(jq -c --arg u "${KID}" '[.kids[]? | select(.nc_user == $u) | {minutes, worlds: [.worlds[].world_name]}]' "${WORK_DIR}/review.json" 2>/dev/null))" \
	eq "$(jq -r --arg u "${KID}" --arg w "${NAME_PAUSE}" '[.kids[]? | select(.nc_user == $u and .minutes > 0 and ([.worlds[]?.world_name] | index($w) != null))] | length' "${WORK_DIR}/review.json" 2>/dev/null)" 1
check "K3 Verwalter erscheinen nicht im Rückblick" \
	eq "$(jq -r --arg a "${ADMIN2}" '[.kids[]? | select(.nc_user == "admin" or .nc_user == $a)] | length' "${WORK_DIR}/review.json" 2>/dev/null)" 0
CODE=$(call "${KID_AUTH}" GET "${API_URL}/review?day=${TODAY}" /dev/null)
check "K3 Negativkontrolle: ${KID} liest /review nicht, HTTP 403 (ist ${CODE})" eq "${CODE}" 403
# Without playtime no review arrives (D-14): a fresh day without playtime cannot be produced in the
# running stack; proven by tests/test_notify_loop.py.

printf '\n== K4 Handy-Seiten hinter den Links ==\n'
# K4 Links open the Gameworld pages pause, versuch, rueckblick (SC 4)
for page in "pause" "versuch?welt=${WORLD_ID}&tag=${TODAY}" "rueckblick?tag=${TODAY}"; do
	CODE=$(curl -s -u "${ADMIN_AUTH}" -o "${WORK_DIR}/page.html" -w '%{http_code}' "${EMBED_URL}/${page}" 2>/dev/null || printf '000')
	check "K4 GET .../${page} als admin HTTP 200 und lädt gameworld-main.js (ist ${CODE})" sh -c \
		'[ "$1" = 200 ] && grep -q "gameworld-main.js" "$2"' _ "${CODE}" "${WORK_DIR}/page.html"
done
LOCATION=$(curl -s -o /dev/null -H 'Accept: text/html,application/xhtml+xml' -w '%{http_code} %{redirect_url}' \
	"${EMBED_URL}/versuch?welt=${WORLD_ID}&tag=${TODAY}" 2>/dev/null || true)
printf 'ohne Sitzung: %s\n' "${LOCATION}"
check "K4 ohne Sitzung: Umleitung auf den Login mit redirect_url samt Pfad und Query (Annahme A1)" sh -c \
	'set -- $1; [ "$1" = 303 ] || [ "$1" = 302 ] || exit 1; case "$2" in */login?redirect_url=*/embedded/gameworld/gameworld/versuch*welt*tag*) exit 0 ;; *) exit 1 ;; esac' \
	_ "${LOCATION}"
call "${ADMIN_AUTH}" GET "${BUNDLE_URL}" "${WORK_DIR}/bundle.js" >/dev/null
for text in "Pause für alle Kinder" "Beitrittsversuche" "Tagesrückblick"; do
	check "K4 Text '${text}' im ausgelieferten Bundle" \
		sh -c '[ "$(grep -c -F -- "$2" "$1" || true)" != 0 ]' _ "${WORK_DIR}/bundle.js" "${text}"
done
check "K4 Negativkontrolle: dasselbe grep findet einen erfundenen Text nicht" \
	sh -c '[ "$(grep -c -F -- "Pause für alle Hamster" "$1" || true)" = 0 ]' _ "${WORK_DIR}/bundle.js"

CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" /dev/null)
check "Welt '${NAME_PAUSE}' gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
# smoke-talk.sh expects its initial state: exactly admin as manager (otherwise
# gw-admin2 would rightly be a member of every room) and gw-kind without rules.
CODE=$(http_code DELETE "${API_URL}/playtime/children/${KID}" /dev/null)
check "Regeln von ${KID} wieder gelöscht HTTP 200 (ist ${CODE})" eq "${CODE}" 200
reset_usage "${KID}"
occ user:delete "${ADMIN2}" >/dev/null 2>&1 || true
check "Konto ${ADMIN2} vor dem Talk-Smoke gelöscht" user_absent "${ADMIN2}"
check "ExApp gezielt neu gestartet (Verwalter-Schnappschuss ohne Drossel)" restart_backend "${WORK_DIR}/register-k5.log"
http_code GET "${API_URL}/worlds" /dev/null >/dev/null
waited=0
while [ "${waited}" -le 15 ]; do
	ADMINS=$(sql "SELECT value FROM meta WHERE key = 'time_admins'")
	printf '%s' "${ADMINS}" | grep -q '"admin"' && ! printf '%s' "${ADMINS}" | grep -q "\"${ADMIN2}\"" && break
	sleep 3
	waited=$((waited + 3))
done
# An empty value (sql failed) never passes: admin must be in it, ${ADMIN2} must not (WR-08).
check "Verwalter-Schnappschuss ohne ${ADMIN2}, mit admin (ist ${ADMINS:-leer})" sh -c \
	'printf "%s" "$1" | grep -q "\"admin\"" && ! printf "%s" "$1" | grep -q "\"$2\""' _ "${ADMINS}" "${ADMIN2}"

printf '\n== K5 Talk-Raum je Welt und K6 Bot (smoke-talk.sh) ==\n'
# K5 Talk room per world with exact members, read-only, room disappears with the world (SC 5)
# K6 Gameworld bot announces start, stop, join throttled; without Talk everything keeps running (SC 6)
printf 'smoke-talk.sh läuft (bis zu 330 s Wartezeit für den Abgleich)\n'
if sh "${TALK_SMOKE}" >"${WORK_DIR}/talk.log" 2>&1; then
	pass "K5/K6 smoke-talk.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/talk.log" | tail -n 1))"
else
	fail "K5/K6 smoke-talk.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/talk.log" >&2 || tail -n 20 "${WORK_DIR}/talk.log" >&2
fi
check "K5/K6 Talk-Smoke ohne Fehlschlag (Zählerzeile N von N)" sh -c \
	'line=$(grep "Prüfungen bestanden" "$1" | tail -n 1); set -- $line; [ -n "$1" ] && [ "$1" = "$3" ]' _ "${WORK_DIR}/talk.log"

printf '\n== K6 ohne Talk ==\n'
occ app:disable spreed >/dev/null 2>&1 || true
SPREED_DISABLED=1
check "K6 occ app:disable spreed: Talk ist aus" \
	eq "$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // "aus"')" aus
# The ExApp asks for the Talk capabilities at most every 300 s; the targeted restart
# makes the check possible at once instead of waiting 5 minutes.
check "K6 ExApp gezielt neu gestartet (Talk-Fähigkeiten frisch)" restart_backend "${WORK_DIR}/register-k6.log"
CODE=$(http_code GET "${API_URL}/talk" "${WORK_DIR}/talk-off.json")
check "K6 GET /api/talk HTTP 200 mit available false (ist ${CODE} $(jq -r '.available' "${WORK_DIR}/talk-off.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '.available' "${WORK_DIR}/talk-off.json" 2>/dev/null)" "200 false"
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/w-notalk.json" "{\"name\":\"${NAME_NOTALK}\",\"preset\":\"mtg_kreativ\"}")
NOTALK_ID=$(jq -r '.id // empty' "${WORK_DIR}/w-notalk.json" 2>/dev/null || true)
remember_world "${NOTALK_ID}"
check "K6 ohne Talk: POST /worlds HTTP 201 (ist ${CODE})" eq "${CODE}" 201
CODE=$(http_code POST "${API_URL}/worlds/${NOTALK_ID}/invites" /dev/null "{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "K6 ohne Talk: Einladen HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(http_code GET "${API_URL}/worlds" "${WORK_DIR}/w-list.json")
check "K6 ohne Talk: GET /worlds HTTP 200 mit der Welt (ist ${CODE})" \
	eq "${CODE} $(jq -r --arg id "${NOTALK_ID}" '[.worlds[]? | select(.id == $id)] | length' "${WORK_DIR}/w-list.json" 2>/dev/null)" "200 1"
CODE=$(http_code DELETE "${API_URL}/worlds/${NOTALK_ID}" /dev/null)
check "K6 ohne Talk: DELETE Welt HTTP 204 (ist ${CODE})" eq "${CODE}" 204
occ app:enable spreed >/dev/null 2>&1 || true
check "K6 occ app:enable spreed: Talk ist wieder an" \
	ne "$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty')" ""
SPREED_DISABLED=0
ENABLED_AT=$(date +%s)
# The ExApp does not know about it yet (capabilities in memory): the room of the new world
# comes from the 5 min sync (backfill D-20), not from the creation.
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/w-back.json" "{\"name\":\"${NAME_BACKFILL}\",\"preset\":\"mtg_kreativ\"}")
BACK_ID=$(jq -r '.id // empty' "${WORK_DIR}/w-back.json" 2>/dev/null || true)
remember_world "${BACK_ID}"
check "K6 nach erneutem Aktivieren: POST /worlds HTTP 201 (ist ${CODE})" eq "${CODE}" 201
printf 'warte bis zu %s s auf den Raum aus dem Abgleich\n' "${RECONCILE_WAIT}"
BACK_TOKEN=""
while :; do
	BACK_TOKEN=$(room_token_of "${NAME_BACKFILL}")
	[ -n "${BACK_TOKEN}" ] && break
	[ "$(($(date +%s) - ENABLED_AT))" -lt "${RECONCILE_WAIT}" ] || break
	sleep 5
done
check "K6 Raum 'Gameworld: ${NAME_BACKFILL}' nachgelegt, $(($(date +%s) - ENABLED_AT)) s nach dem Aktivieren (höchstens ${RECONCILE_WAIT} s)" \
	ne "${BACK_TOKEN}" ""
if [ -n "${BACK_TOKEN}" ]; then
	BOT_STATE=""
	waited=0
	while [ "${waited}" -le 30 ]; do
		http_code GET "${SPREED}/v1/bot/${BACK_TOKEN}" "${WORK_DIR}/bots-back.json" >/dev/null
		BOT_STATE=$(jq -r '[.ocs.data[]? | select(.name == "Gameworld") | .state][0] // empty' "${WORK_DIR}/bots-back.json" 2>/dev/null || true)
		[ "${BOT_STATE}" = 1 ] && break
		sleep 5
		waited=$((waited + 5))
	done
	check "K6 Bot Gameworld im nachgelegten Raum aktiv (state ${BOT_STATE:-leer})" eq "${BOT_STATE}" 1
	http_code GET "${API_URL}/talk" "${WORK_DIR}/talk-on.json" >/dev/null
	check "K6 GET /api/talk meldet available und bots true und den Raum der Welt" \
		eq "$(jq -r --arg id "${BACK_ID}" '.available and .bots and ([.worlds[]? | select(.world_id == $id and .has_room)] | length == 1)' "${WORK_DIR}/talk-on.json" 2>/dev/null)" true
else
	fail "K6 Bot im nachgelegten Raum nicht prüfbar (kein Raum)"
	fail "K6 GET /api/talk mit Raum nicht prüfbar (kein Raum)"
fi
CODE=$(http_code DELETE "${API_URL}/worlds/${BACK_ID}" /dev/null)
check "K6 Welt '${NAME_BACKFILL}' gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
gone=1
waited=0
while [ "${waited}" -le 60 ]; do
	[ -z "$(room_token_of "${NAME_BACKFILL}")" ] && { gone=0; break; }
	sleep 3
	waited=$((waited + 3))
done
check "K6 Raum der gelöschten Welt binnen 60 s weg" eq "${gone}" 0

printf '\n== Aufräumen ==\n'
if [ -n "${ADMIN_PREFS}" ]; then
	CODE=$(http_code POST "${API_URL}/review/prefs" /dev/null "${ADMIN_PREFS}")
	check "Rückblick-Einstellung von admin zurück auf ${ADMIN_PREFS} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
fi
reset_fixtures
http_code GET "${API_URL}/pause" "${WORK_DIR}/pause-final.json" >/dev/null
check "Aufräumen keine Pause aktiv" eq "$(jq -r '.active' "${WORK_DIR}/pause-final.json" 2>/dev/null)" false
check "Aufräumen Konto ${GUEST} gelöscht" user_absent "${GUEST}"
check "Aufräumen Konto ${ADMIN2} gelöscht" user_absent "${ADMIN2}"
check "Positivkontrolle: dieselbe Abfrage erkennt das vorhandene Konto ${KID}" user_present "${KID}"
check "Aufräumen ${KID} nicht in admin" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${KID}" '(.admin // []) | index($u) // "nein"')" nein
check "Aufräumen Talk (spreed) aktiviert" ne "$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty')" ""
LEFT=0
for cid in $(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null); do
	case " ${BASELINE_CONTAINERS} " in
	*" ${cid} "*) ;;
	*) LEFT=$((LEFT + 1)) ;;
	esac
done
check "keine Welt-Container übrig (ist ${LEFT}, fremde vor dem Lauf nicht gezählt)" eq "${LEFT}" 0

printf '\n== Regression Phase 1 bis 4 ==\n'
if [ "${GAMEWORLD_SKIP_REGRESSION:-0}" = 1 ]; then
	fail "Regression übersprungen (GAMEWORLD_SKIP_REGRESSION=1), keine Phasenabnahme"
	printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
	exit 1
fi
# acceptance-phase4.sh calls acceptance-phase3.sh, which calls phase 1 and 2 itself.
if sh "${PHASE4_SCRIPT}" >"${WORK_DIR}/phase4.log" 2>&1; then
	pass "Regression: acceptance-phase4.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase4.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase4.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase4.log" >&2 || tail -n 20 "${WORK_DIR}/phase4.log" >&2
fi
for expected in "84 von 84 Prüfungen bestanden" "104 von 104 Prüfungen bestanden" \
	"75 von 75 Prüfungen bestanden" "109 von 109 Prüfungen bestanden"; do
	# Only the sum line or a bestanden line counts, never a quote in a FEHLGESCHLAGEN line.
	check "Regression: Log enthält '${expected}'" awk -v e="${expected}" \
		'$0 == e || (index($0, "bestanden: ") == 1 && index($0, e) > 0) { found = 1 } END { exit !found }' \
		"${WORK_DIR}/phase4.log"
done
check "nach der Regression: Talk (spreed) aktiviert und ExApp erreichbar" sh -c \
	'[ -n "$1" ] && curl -sf "http://127.0.0.1:$2/heartbeat" >/dev/null' _ \
	"$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty')" "${BACKEND_PORT}"

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 4.1 erfolgreich\n'
