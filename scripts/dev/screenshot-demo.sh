#!/bin/sh
# Demo data for the store screenshots (06-13, D-10) in the dev stack.
#
# Creates only throwaway accounts and worlds with child-friendly demo names, so that the
# images never show real accounts, worlds or backups:
#   Groups   familie (children and Oma), eltern (manager group, D-01)
#   Accounts mama (manager via eltern, member of familie), mia, leo
#            (children in familie), oma (in familie, marked as adult)
#   Worlds   "Baumhaus" (mtg_kreativ, invited: mia, leo, oma) and
#            "Inselabenteuer" (voxelibre_sanft, invited: group familie),
#            both created by mama and running
#   Rules    playtime rule for mia (Mon to Fri 60 min 15 to 19 o'clock, Sat and Sun
#            90 min), a backup of "Baumhaus" in the files of mama
#
# Idempotent: what exists stays, only what is missing is created. With
# --cleanup the script removes everything again (worlds including containers, volumes
# and Talk rooms via the API, manager group, accounts including files, groups).
# It never touches foreign worlds (e.g. running dev worlds of other instances):
# only what carries a demo name AND whose ID this script recorded in
# .dev/screenshot-demo.json is deleted.
#
# The images are taken afterwards by scripts/dev/screenshot-capture.mjs (Playwright,
# see the header there). This script writes the IDs of the demo worlds to
# .dev/screenshot-demo.json (gitignored), so that the capture shows only them.
#
# Credentials: pure dev accounts of the loopback instance; passwords and
# play passwords never appear in the output.
#
# Usage:  sh scripts/dev/screenshot-demo.sh            create
#         sh scripts/dev/screenshot-demo.sh --cleanup  remove again
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
NC_CONTAINER=gameworld-dev-app-1
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api"
STATE_FILE="${REPO_ROOT}/.dev/screenshot-demo.json"

G_FAMILIE=familie
G_ELTERN=eltern
MAMA=mama
MAMA_AUTH="${MAMA}:gameworld-demo-mama-13"
DEMO_USERS="mama mia leo oma"
W_BAUM="Baumhaus"
W_INSEL="Inselabenteuer"
BACKUP_WAIT=240
START_WAIT=180

WORK_DIR=$(mktemp -d)
trap 'rm -rf "${WORK_DIR}"' EXIT INT TERM

say() { printf '%s\n' "$1"; }
abort() {
	printf 'ABBRUCH: %s\n' "$1" >&2
	exit 1
}

occ() {
	docker exec -u www-data "${NC_CONTAINER}" php occ "$@"
}

# call AUTH METHOD URL OUTPUT [JSON] -> HTTP code (response only in OUTPUT, never on stdout)
call() {
	if [ -n "${5:-}" ]; then
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' -H 'Content-Type: application/json' \
			-X "$2" -d "$5" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	else
		# Content-Type even without a body: otherwise the CSRF check of the app rejects DELETE with 403.
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' -H 'Content-Type: application/json' \
			-X "$2" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	fi
}

password_of() {
	case "$1" in
	mama) printf 'gameworld-demo-mama-13' ;;
	mia) printf 'gameworld-demo-mia-13' ;;
	leo) printf 'gameworld-demo-leo-13' ;;
	oma) printf 'gameworld-demo-oma-13' ;;
	esac
}

display_of() {
	case "$1" in
	mama) printf 'Mama' ;;
	mia) printf 'Mia' ;;
	leo) printf 'Leo' ;;
	oma) printf 'Oma' ;;
	esac
}

user_present() { occ user:info "$1" >/dev/null 2>&1; }

ensure_user() {
	if user_present "$1"; then
		say "Konto $1 vorhanden"
		return 0
	fi
	docker exec -u www-data -e OC_PASS="$(password_of "$1")" "${NC_CONTAINER}" \
		php occ user:add --password-from-env --display-name="$(display_of "$1")" "$1" >"${WORK_DIR}/add.log" 2>&1 ||
		abort "Konto $1 nicht angelegt: $(tr '\r\n' '  ' <"${WORK_DIR}/add.log" | cut -c1-200)"
	say "Konto $1 angelegt"
}

ensure_group() {
	occ group:add "$1" >/dev/null 2>&1 || true
}

in_group() {
	occ group:adduser "$1" "$2" >/dev/null 2>&1 || true
}

# world_id NAME -> ID of the demo world NAME that belongs to mama (empty if none)
world_id() {
	call "${MAMA_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/worlds.json" >/dev/null
	jq -r --arg n "$1" --slurpfile s "$(state_or_empty)" \
		'(($s[0].worlds) // []) as $mine
		| [.worlds[]? | select(.name == $n and (.id as $id | $mine | index($id) != null))][0].id // empty' \
		"${WORK_DIR}/worlds.json" 2>/dev/null | tr -d '\r' || true
}

# name_taken NAME -> 0 if a foreign world (not from this script) carries the demo name
name_taken() {
	jq -e --arg n "$1" --slurpfile s "$(state_or_empty)" \
		'(($s[0].worlds) // []) as $mine
		| any(.worlds[]?; .name == $n and (.id as $id | $mine | index($id) == null))' \
		"${WORK_DIR}/worlds.json" >/dev/null 2>&1
}

state_or_empty() {
	if [ -f "${STATE_FILE}" ]; then
		printf '%s' "${STATE_FILE}"
	else
		printf '{"worlds":[]}' >"${WORK_DIR}/empty-state.json"
		printf '%s' "${WORK_DIR}/empty-state.json"
	fi
}

world_field() {
	call "${MAMA_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

wait_field() {
	until_ts=$(($(date +%s) + $4))
	while [ "$(date +%s)" -lt "${until_ts}" ]; do
		[ "$(world_field "$1" "$2")" = "$3" ] && return 0
		sleep 3
	done
	return 1
}

# record_world ID -> record the ID at once, so that --cleanup works even after an abort
record_world() {
	mkdir -p "$(dirname "${STATE_FILE}")"
	if [ -f "${STATE_FILE}" ]; then
		jq -c --arg id "$1" '.worlds = (((.worlds // []) + [$id]) | unique)' "${STATE_FILE}" >"${WORK_DIR}/state.json"
	else
		jq -nc --arg id "$1" '{worlds: [$id]}' >"${WORK_DIR}/state.json"
	fi
	mv "${WORK_DIR}/state.json" "${STATE_FILE}"
}

# ensure_world NAME PRESET -> sets WID
ensure_world() {
	WID=$(world_id "$1")
	if [ -n "${WID}" ]; then
		say "Welt $1 vorhanden"
		return 0
	fi
	name_taken "$1" && abort "Eine fremde Welt heißt schon $1; Demo-Namen nur für Demo-Welten"
	code=$(call "${MAMA_AUTH}" POST "${API_URL}/worlds" "${WORK_DIR}/new.json" "{\"name\":\"$1\",\"preset\":\"$2\"}")
	case "${code}" in
	200 | 201 | 202) ;;
	*) abort "Welt $1 nicht angelegt (HTTP ${code}): $(jq -r '.detail // empty' "${WORK_DIR}/new.json" 2>/dev/null)" ;;
	esac
	WID=$(jq -r '.id // empty' "${WORK_DIR}/new.json")
	[ -n "${WID}" ] || abort "Welt $1 ohne ID"
	record_world "${WID}"
	say "Welt $1 angelegt"
}

invite() {
	code=$(call "${MAMA_AUTH}" POST "${API_URL}/worlds/$1/invites" "${WORK_DIR}/inv.json" "{\"kind\":\"$2\",\"target\":\"$3\"}")
	[ "${code}" = 200 ] || abort "Einladung $2 $3 HTTP ${code}: $(jq -r '.detail // empty' "${WORK_DIR}/inv.json" 2>/dev/null)"
	say "eingeladen: $2 $3"
}

# RAM check before world starts (serial, home server rule); Windows host via PowerShell, otherwise /proc/meminfo.
free_mb() {
	if command -v powershell >/dev/null 2>&1; then
		powershell -NoProfile -Command '[int]((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1024)' 2>/dev/null | tr -d '\r'
	else
		awk '/^MemAvailable:/ { print int($2 / 1024) }' /proc/meminfo
	fi
}

require_ram() {
	mb=$(free_mb || printf '0')
	say "freier Arbeitsspeicher: ${mb} MB"
	[ "${mb:-0}" -ge 1200 ] || abort "weniger als 1200 MB frei, keine weitere Welt starten"
}

week_plan() {
	jq -nc '[range(1; 8) as $d
		| if $d <= 5 then {weekday: $d, allowed: true, limit_minutes: 60, window_start: 900, window_end: 1140}
		else {weekday: $d, allowed: true, limit_minutes: 90, window_start: null, window_end: null} end]
		| {normal: ., holiday: null}'
}

cleanup() {
	# Only worlds whose ID this script recorded AND which carry a demo name.
	if [ -f "${STATE_FILE}" ] && user_present "${MAMA}"; then
		call "${MAMA_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/worlds.json" >/dev/null
		for id in $(jq -r '.worlds[]?' "${STATE_FILE}" | tr -d ''); do
			name=$(jq -r --arg id "${id}" '.worlds[]? | select(.id == $id) | .name' "${WORK_DIR}/worlds.json" | tr -d '')
			case "${name}" in
			"${W_BAUM}" | "${W_INSEL}")
				code=$(call "${MAMA_AUTH}" DELETE "${API_URL}/worlds/${id}" "${WORK_DIR}/del.json")
				say "Welt ${name} (${id}) gelöscht (HTTP ${code})"
				;;
			"") say "Welt ${id} gibt es nicht mehr" ;;
			*) say "Welt ${id} heißt nicht wie eine Demo-Welt: bleibt stehen" ;;
			esac
		done
	fi
	call "${ADMIN_AUTH}" POST "${API_URL}/admin/verwalter-groups/remove" /dev/null "{\"gid\":\"${G_ELTERN}\"}" >/dev/null
	for user in mia leo oma; do
		call "${ADMIN_AUTH}" DELETE "${API_URL}/playtime/children/${user}" /dev/null >/dev/null
	done
	for user in ${DEMO_USERS}; do
		if user_present "${user}"; then
			occ user:delete "${user}" >/dev/null 2>&1 && say "Konto ${user} gelöscht"
		fi
	done
	occ group:delete "${G_FAMILIE}" >/dev/null 2>&1 || true
	occ group:delete "${G_ELTERN}" >/dev/null 2>&1 || true
	rm -f "${STATE_FILE}"
	say "Demo-Daten entfernt"
}

docker inspect "${NC_CONTAINER}" >/dev/null 2>&1 || abort "Dev-Stack läuft nicht (${NC_CONTAINER})"
[ "$(call "${ADMIN_AUTH}" GET "${API_URL}/me" /dev/null)" = 200 ] || abort "Gameworld antwortet nicht unter ${API_URL}"

if [ "${1:-}" = "--cleanup" ]; then
	cleanup
	exit 0
fi

say "== Konten und Gruppen =="
for user in ${DEMO_USERS}; do
	ensure_user "${user}"
done
ensure_group "${G_FAMILIE}"
ensure_group "${G_ELTERN}"
in_group "${G_ELTERN}" "${MAMA}"
for user in mama mia leo oma; do
	in_group "${G_FAMILIE}" "${user}"
done
code=$(call "${ADMIN_AUTH}" POST "${API_URL}/admin/verwalter-groups/add" "${WORK_DIR}/vg.json" "{\"gid\":\"${G_ELTERN}\"}")
case "${code}" in
200 | 409) say "Verwalter-Gruppe ${G_ELTERN} aktiv" ;;
*) abort "Verwalter-Gruppe ${G_ELTERN} HTTP ${code}" ;;
esac
[ "$(call "${MAMA_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/me.json")" = 200 ] || abort "mama erreicht /api/me nicht"
[ "$(jq -r '.role' "${WORK_DIR}/me.json")" = verwalter ] || abort "mama ist keine Verwalterin"

say "== Welten =="
require_ram
ensure_world "${W_BAUM}" mtg_kreativ
BAUM_ID=${WID}
wait_field "${BAUM_ID}" '.status' running "${START_WAIT}" || abort "Baumhaus läuft nicht"
require_ram
ensure_world "${W_INSEL}" voxelibre_sanft
INSEL_ID=${WID}
wait_field "${INSEL_ID}" '.status' running "${START_WAIT}" || abort "Inselabenteuer läuft nicht"

say "== Einladungen =="
for user in mia leo oma; do
	invite "${BAUM_ID}" user "${user}"
done
invite "${INSEL_ID}" group "${G_FAMILIE}"

say "== Erwachsen und Spielzeit =="
code=$(call "${MAMA_AUTH}" POST "${API_URL}/players/adult" "${WORK_DIR}/adult.json" '{"nc_user":"oma","adult":true}')
[ "${code}" = 200 ] || abort "oma nicht als erwachsen markiert (HTTP ${code})"
say "oma als erwachsen markiert"
code=$(call "${MAMA_AUTH}" POST "${API_URL}/playtime/children/mia" "${WORK_DIR}/plan.json" "$(week_plan)")
[ "${code}" = 200 ] || abort "Spielzeitregel für mia HTTP ${code}: $(jq -r '.detail // empty' "${WORK_DIR}/plan.json" 2>/dev/null)"
say "Spielzeitregel für mia gespeichert"

say "== Sicherung =="
call "${MAMA_AUTH}" GET "${API_URL}/worlds/${BAUM_ID}/backups" "${WORK_DIR}/backups.json" >/dev/null
if [ "$(jq -r '(.backups // []) | length' "${WORK_DIR}/backups.json" 2>/dev/null || printf 0)" -gt 0 ]; then
	say "Sicherung von Baumhaus vorhanden"
else
	code=$(call "${MAMA_AUTH}" POST "${API_URL}/worlds/${BAUM_ID}/backups" "${WORK_DIR}/b.json" '{"confirm_disconnect":true}')
	[ "${code}" = 202 ] || abort "Sicherung nicht gestartet (HTTP ${code})"
	wait_field "${BAUM_ID}" '.backup_job.state // ""' ok "${BACKUP_WAIT}" || abort "Sicherung nicht fertig"
	wait_field "${BAUM_ID}" '.status' running "${START_WAIT}" || abort "Baumhaus läuft nach der Sicherung nicht"
	say "Sicherung von Baumhaus fertig"
fi

say "Demo-Daten bereit, Welt-IDs in .dev/screenshot-demo.json"
