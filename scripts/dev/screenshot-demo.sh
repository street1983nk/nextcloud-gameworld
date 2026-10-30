#!/bin/sh
# Demo data for the store screenshots (06-13, D-10, D-25) in the dev stack.
#
# Creates only throwaway accounts and worlds with child-friendly demo names, so that the
# images never show real accounts, worlds or backups:
#   Groups   per language a family group (children and grandma) and a manager
#            group (D-01): de familie/eltern, en family/parents, fr famille/parents.
#            Group and account IDs are visible in the interface (invite hint, player
#            names), so the adults and groups exist once per language and an
#            English image never shows a German ID.
#   Accounts per language a parent (manager via the manager group, member of the
#            family group) and a grandma (in the family group, marked as adult):
#            de mama/oma, en mom/grandma, fr maman/mamie; the children mia and leo
#            are shared and sit in every family group. --lang sets the account
#            language of the accounts of that language and of mia and leo.
#   Worlds   one pair per language, both created by that parent and running:
#              de  "Baumhaus" (mtg_kreativ) and "Inselabenteuer" (voxelibre_sanft)
#              en  "Treehouse" and "Island adventure"
#              fr  "La cabane" and "Île aux aventures"
#            (world names allow only letters, digits, spaces, dots, hyphens and
#            underscores, so no apostrophe as in "L'île")
#            the first one invites mia, leo and the grandma, the second one the family group;
#            the world language equals --lang (D-27). Demo worlds of the other
#            languages are stopped (RAM rule: home server, nothing in parallel).
#   Rules    playtime rule for mia (Mon to Fri 60 min 15 to 19 o'clock, Sat and Sun
#            90 min), a backup of the first world in the files of the parent
#
# Account language (D-25): --lang sets the Nextcloud account language of the demo
# accounts and, for the duration of the run, of the admin account that drives the
# script. The previous admin value is read first, kept in the state file and restored
# on exit (also after an abort) and by --cleanup (T-06-101).
#
# Idempotent: what exists stays, only what is missing is created. With
# --cleanup the script removes everything again (worlds of all languages including
# containers, volumes and Talk rooms via the API, manager group, accounts including
# files, groups). It never touches foreign worlds (e.g. running dev worlds of other
# instances): only what carries a demo name AND whose ID this script recorded in
# .dev/screenshot-demo.json is deleted or stopped.
#
# The images are taken afterwards by scripts/dev/screenshot-capture.mjs (Playwright,
# see the header there) with the same --lang. This script writes the IDs of the demo
# worlds per language to .dev/screenshot-demo.json (gitignored), so that the capture
# shows only them.
#
# Credentials: pure dev accounts of the loopback instance; passwords and
# play passwords never appear in the output.
#
# Usage:  sh scripts/dev/screenshot-demo.sh [--lang de|en|fr]   create (default de)
#         sh scripts/dev/screenshot-demo.sh --cleanup           remove again
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_USER=admin
ADMIN_AUTH="${ADMIN_USER}:gameworld-dev-admin"
NC_CONTAINER=gameworld-dev-app-1
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api"
OCS_URL="${NEXTCLOUD_URL}/ocs/v2.php/cloud"
STATE_FILE="${REPO_ROOT}/.dev/screenshot-demo.json"

# All demo accounts and groups of all languages: --cleanup removes exactly these.
ALL_DEMO_USERS="mama oma mom grandma maman mamie mia leo"
ALL_DEMO_GROUPS="familie family famille eltern parents"
# All demo world names of all languages: only these are ever deleted or stopped.
DEMO_WORLD_NAMES="Baumhaus|Inselabenteuer|Treehouse|Island adventure|La cabane|Île aux aventures"
# Minimum free RAM before a world start; GAMEWORLD_DEMO_MIN_RAM_MB lowers it on a busy dev machine.
BACKUP_WAIT=240
START_WAIT=180

WORK_DIR=$(mktemp -d)
ADMIN_LANG_SET=0

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
		# Body through a file: on Windows a native curl gets its arguments in the ANSI code page,
		# which breaks UTF-8 world names such as "Île aux aventures".
		printf '%s' "$5" >"${WORK_DIR}/body.json"
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' -H 'Content-Type: application/json' \
			-X "$2" --data-binary "@${WORK_DIR}/body.json" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	else
		# Content-Type even without a body: otherwise the CSRF check of the app rejects DELETE with 403.
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' -H 'Content-Type: application/json' \
			-X "$2" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	fi
}

# ocs_edit KIND ID VALUE -> sets the display name of a user or group (OCS provisioning API)
ocs_edit() {
	code=$(curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Accept: application/json' \
		-X PUT --data-urlencode key=displayname --data-urlencode "value=$3" \
		-o "${WORK_DIR}/ocs.json" -w '%{http_code}' "${OCS_URL}/$1/$2" 2>/dev/null || printf '000')
	[ "${code}" = 200 ] || abort "Anzeigename von $2 nicht gesetzt (HTTP ${code})"
}

# Throwaway passwords of the loopback dev instance, same scheme for every demo account.
password_of() {
	printf 'gameworld-demo-%s-13' "$1"
}

display_of() {
	case "$1" in
	mama) printf 'Mama' ;;
	oma) printf 'Oma' ;;
	mom) printf 'Mom' ;;
	grandma) printf 'Grandma' ;;
	maman) printf 'Maman' ;;
	mamie) printf 'Mamie' ;;
	mia) printf 'Mia' ;;
	leo) printf 'Leo' ;;
	esac
}

group_display_of() {
	case "$1" in
	familie) printf 'Familie' ;;
	family) printf 'Family' ;;
	famille) printf 'Famille' ;;
	eltern) printf 'Eltern' ;;
	parents) printf 'Parents' ;;
	esac
}

# Accounts, groups and world names of DEMO_LANG.
set_language_data() {
	case "${DEMO_LANG}" in
	de)
		PARENT=mama
		GRANDMA=oma
		G_FAMILY=familie
		G_PARENTS=eltern
		W_FIRST="Baumhaus"
		W_SECOND="Inselabenteuer"
		;;
	en)
		PARENT=mom
		GRANDMA=grandma
		G_FAMILY=family
		G_PARENTS=parents
		W_FIRST="Treehouse"
		W_SECOND="Island adventure"
		;;
	fr)
		PARENT=maman
		GRANDMA=mamie
		G_FAMILY=famille
		G_PARENTS=parents
		W_FIRST="La cabane"
		W_SECOND="Île aux aventures"
		;;
	esac
	PARENT_AUTH="${PARENT}:$(password_of "${PARENT}")"
	DEMO_USERS="${PARENT} ${GRANDMA} mia leo"
}

user_present() { occ user:info "$1" >/dev/null 2>&1; }

ensure_user() {
	if user_present "$1"; then
		say "Konto $1 vorhanden"
	else
		docker exec -u www-data -e OC_PASS="$(password_of "$1")" "${NC_CONTAINER}" \
			php occ user:add --password-from-env --display-name="$(display_of "$1")" "$1" >"${WORK_DIR}/add.log" 2>&1 ||
			abort "Konto $1 nicht angelegt: $(tr '\r\n' '  ' <"${WORK_DIR}/add.log" | cut -c1-200)"
		say "Konto $1 angelegt"
	fi
	occ user:setting "$1" core lang "${DEMO_LANG}" >/dev/null
}

ensure_group() {
	occ group:add --display-name="$(group_display_of "$1")" "$1" >/dev/null 2>&1 || true
	ocs_edit groups "$1" "$(group_display_of "$1")"
}

in_group() {
	occ group:adduser "$1" "$2" >/dev/null 2>&1 || true
}

state_or_empty() {
	if [ -f "${STATE_FILE}" ]; then
		printf '%s' "${STATE_FILE}"
	else
		printf '{"worlds":[]}' >"${WORK_DIR}/empty-state.json"
		printf '%s' "${WORK_DIR}/empty-state.json"
	fi
}

# state_update JQ_FILTER [jq args...] -> rewrites the state file atomically
state_update() {
	filter=$1
	shift
	mkdir -p "$(dirname "${STATE_FILE}")"
	jq -c "$@" "${filter}" "$(state_or_empty)" >"${WORK_DIR}/state.json"
	mv "${WORK_DIR}/state.json" "${STATE_FILE}"
}

# --- Account language of the admin (T-06-101) -------------------------------------------

admin_lang_now() {
	occ user:setting "${ADMIN_USER}" core lang 2>/dev/null | tr -d '\r\n' || true
}

# Remembers the admin language once (an earlier aborted run already stored it) and sets DEMO_LANG.
set_admin_lang() {
	if [ "$(jq -r 'has("admin_lang")' "$(state_or_empty)")" != true ]; then
		state_update '.admin_lang = $v' --arg v "$(admin_lang_now)"
	fi
	say "Kontosprache ${ADMIN_USER} vorher: $(jq -r '.admin_lang' "${STATE_FILE}" | sed 's/^$/(nicht gesetzt)/')"
	ADMIN_LANG_SET=1
	occ user:setting "${ADMIN_USER}" core lang "${DEMO_LANG}" >/dev/null
}

restore_admin_lang() {
	[ -f "${STATE_FILE}" ] || return 0
	[ "$(jq -r 'has("admin_lang")' "${STATE_FILE}" 2>/dev/null)" = true ] || return 0
	before=$(jq -r '.admin_lang' "${STATE_FILE}")
	if [ -n "${before}" ]; then
		occ user:setting "${ADMIN_USER}" core lang "${before}" >/dev/null
	else
		occ user:setting --delete "${ADMIN_USER}" core lang >/dev/null 2>&1 || true
	fi
	state_update 'del(.admin_lang)'
	say "Kontosprache ${ADMIN_USER} wiederhergestellt: $(admin_lang_now | sed 's/^$/(nicht gesetzt)/')"
}

on_exit() {
	if [ "${ADMIN_LANG_SET}" -eq 1 ]; then
		restore_admin_lang || printf 'WARNUNG: Kontosprache %s nicht wiederhergestellt, --cleanup holt das nach\n' "${ADMIN_USER}" >&2
	fi
	rm -rf "${WORK_DIR}"
}
trap on_exit EXIT
trap 'exit 1' INT TERM

# --- Worlds -------------------------------------------------------------------------------

# world_id NAME -> ID of the recorded demo world NAME (empty if none)
world_id() {
	call "${PARENT_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/worlds.json" >/dev/null
	printf '%s' "$1" >"${WORK_DIR}/name.txt"
	jq -r --rawfile n "${WORK_DIR}/name.txt" --slurpfile s "$(state_or_empty)" \
		'(($s[0].worlds) // []) as $mine
		| [.worlds[]? | select(.name == $n and (.id as $id | $mine | index($id) != null))][0].id // empty' \
		"${WORK_DIR}/worlds.json" 2>/dev/null | tr -d '\r' || true
}

# name_taken NAME -> 0 if a foreign world (not from this script) carries the demo name
name_taken() {
	printf '%s' "$1" >"${WORK_DIR}/name.txt"
	jq -e --rawfile n "${WORK_DIR}/name.txt" --slurpfile s "$(state_or_empty)" \
		'(($s[0].worlds) // []) as $mine
		| any(.worlds[]?; .name == $n and (.id as $id | $mine | index($id) == null))' \
		"${WORK_DIR}/worlds.json" >/dev/null 2>&1
}

world_field() {
	call "${PARENT_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null | tr -d '\r' || true
}

wait_field() {
	until_ts=$(($(date +%s) + $4))
	while [ "$(date +%s)" -lt "${until_ts}" ]; do
		[ "$(world_field "$1" "$2")" = "$3" ] && return 0
		sleep 3
	done
	return 1
}

# record_world ID -> record the ID at once (all languages and per DEMO_LANG), so that
# --cleanup works even after an abort
record_world() {
	state_update '.worlds = (((.worlds // []) + [$id]) | unique)
		| .by_lang[$lang] = (((.by_lang[$lang] // []) + [$id]) | unique)' \
		--arg id "$1" --arg lang "${DEMO_LANG}"
}

is_demo_name() {
	printf '%s' "${DEMO_WORLD_NAMES}" | tr '|' '\n' | grep -Fqx -- "$1"
}

# ensure_world NAME PRESET -> sets WID
ensure_world() {
	WID=$(world_id "$1")
	if [ -n "${WID}" ]; then
		record_world "${WID}"
		say "Welt $1 vorhanden"
		return 0
	fi
	name_taken "$1" && abort "Eine fremde Welt heißt schon $1; Demo-Namen nur für Demo-Welten"
	require_ram
	code=$(call "${PARENT_AUTH}" POST "${API_URL}/worlds" "${WORK_DIR}/new.json" \
		"$(printf '{"name":"%s","preset":"%s"}' "$1" "$2")")
	case "${code}" in
	200 | 201 | 202) ;;
	*) abort "Welt $1 nicht angelegt (HTTP ${code}): $(jq -r '.detail // empty' "${WORK_DIR}/new.json" 2>/dev/null)" ;;
	esac
	WID=$(jq -r '.id // empty' "${WORK_DIR}/new.json")
	[ -n "${WID}" ] || abort "Welt $1 ohne ID"
	record_world "${WID}"
	say "Welt $1 angelegt"
}

# ensure_running ID NAME -> starts the world if needed and waits for "running"
ensure_running() {
	if [ "$(world_field "$1" '.status')" != running ]; then
		require_ram
		call "${PARENT_AUTH}" POST "${API_URL}/worlds/$1/start" "${WORK_DIR}/start.json" '{}' >/dev/null
	fi
	wait_field "$1" '.status' running "${START_WAIT}" || abort "$2 läuft nicht"
}

# ensure_language ID NAME -> world language = DEMO_LANG, restarted so that no restart hint shows
ensure_language() {
	if [ "$(world_field "$1" '.language')" != "${DEMO_LANG}" ]; then
		code=$(call "${PARENT_AUTH}" POST "${API_URL}/worlds/$1/language" "${WORK_DIR}/lang.json" "{\"language\":\"${DEMO_LANG}\"}")
		[ "${code}" = 200 ] || abort "Weltsprache von $2 HTTP ${code}"
		say "Weltsprache von $2: ${DEMO_LANG}"
	fi
	if [ "$(world_field "$1" '.language_restart_needed')" = true ]; then
		call "${PARENT_AUTH}" POST "${API_URL}/worlds/$1/restart" "${WORK_DIR}/restart.json" '{}' >/dev/null
		sleep 3
		wait_field "$1" '.language_restart_needed' false "${START_WAIT}" || abort "$2 startet nicht neu"
		wait_field "$1" '.status' running "${START_WAIT}" || abort "$2 läuft nach dem Neustart nicht"
	fi
}

# Stops the recorded demo worlds of the other languages (RAM), never foreign worlds.
stop_other_languages() {
	call "${ADMIN_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/all.json" >/dev/null
	for id in $(jq -r --arg lang "${DEMO_LANG}" '(.worlds // []) - (.by_lang[$lang] // []) | .[]' "$(state_or_empty)" | tr -d '\r'); do
		name=$(jq -r --arg id "${id}" '.worlds[]? | select(.id == $id) | .name' "${WORK_DIR}/all.json" | tr -d '\r')
		state=$(jq -r --arg id "${id}" '.worlds[]? | select(.id == $id) | .status' "${WORK_DIR}/all.json" | tr -d '\r')
		is_demo_name "${name}" || continue
		# A world of the current language that is not yet listed under by_lang (older state file).
		[ "${name}" = "${W_FIRST}" ] && continue
		[ "${name}" = "${W_SECOND}" ] && continue
		[ "${state}" = stopped ] && continue
		call "${ADMIN_AUTH}" POST "${API_URL}/worlds/${id}/stop" "${WORK_DIR}/stop.json" '{}' >/dev/null
		say "Welt ${name} gestoppt (andere Sprache)"
	done
}

invite() {
	code=$(call "${PARENT_AUTH}" POST "${API_URL}/worlds/$1/invites" "${WORK_DIR}/inv.json" "{\"kind\":\"$2\",\"target\":\"$3\"}")
	case "${code}" in
	200 | 409) ;;
	*) abort "Einladung $2 $3 HTTP ${code}: $(jq -r '.detail // empty' "${WORK_DIR}/inv.json" 2>/dev/null)" ;;
	esac
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
	[ "${mb:-0}" -ge "${GAMEWORLD_DEMO_MIN_RAM_MB:-1200}" ] || abort "weniger als ${GAMEWORLD_DEMO_MIN_RAM_MB:-1200} MB frei, keine weitere Welt starten"
}

week_plan() {
	jq -nc '[range(1; 8) as $d
		| if $d <= 5 then {weekday: $d, allowed: true, limit_minutes: 60, window_start: 900, window_end: 1140}
		else {weekday: $d, allowed: true, limit_minutes: 90, window_start: null, window_end: null} end]
		| {normal: ., holiday: null}'
}

cleanup() {
	# Only worlds whose ID this script recorded AND which carry a demo name.
	if [ -f "${STATE_FILE}" ]; then
		call "${ADMIN_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/worlds.json" >/dev/null
		for id in $(jq -r '.worlds[]?' "${STATE_FILE}" | tr -d '\r'); do
			name=$(jq -r --arg id "${id}" '.worlds[]? | select(.id == $id) | .name' "${WORK_DIR}/worlds.json" | tr -d '\r')
			if [ -z "${name}" ]; then
				say "Welt ${id} gibt es nicht mehr"
			elif is_demo_name "${name}"; then
				code=$(call "${ADMIN_AUTH}" DELETE "${API_URL}/worlds/${id}" "${WORK_DIR}/del.json")
				say "Welt ${name} (${id}) gelöscht (HTTP ${code})"
			else
				say "Welt ${id} heißt nicht wie eine Demo-Welt: bleibt stehen"
			fi
		done
	fi
	restore_admin_lang
	for group in eltern parents; do
		call "${ADMIN_AUTH}" POST "${API_URL}/admin/verwalter-groups/remove" /dev/null "{\"gid\":\"${group}\"}" >/dev/null
	done
	for user in mia leo oma grandma mamie; do
		call "${ADMIN_AUTH}" DELETE "${API_URL}/playtime/children/${user}" /dev/null >/dev/null
	done
	for user in ${ALL_DEMO_USERS}; do
		if user_present "${user}"; then
			occ user:delete "${user}" >/dev/null 2>&1 && say "Konto ${user} gelöscht"
		fi
	done
	for group in ${ALL_DEMO_GROUPS}; do
		occ group:delete "${group}" >/dev/null 2>&1 || true
	done
	rm -f "${STATE_FILE}"
	say "Demo-Daten entfernt"
}

DEMO_LANG=de
DO_CLEANUP=0
while [ $# -gt 0 ]; do
	case "$1" in
	--cleanup) DO_CLEANUP=1 ;;
	--lang)
		[ $# -ge 2 ] || abort "--lang braucht de, en oder fr"
		DEMO_LANG=$2
		shift
		;;
	--lang=*) DEMO_LANG=${1#--lang=} ;;
	*) abort "unbekanntes Argument $1 (erlaubt: --lang de|en|fr, --cleanup)" ;;
	esac
	shift
done
case "${DEMO_LANG}" in
de | en | fr) ;;
*) abort "--lang braucht de, en oder fr, nicht ${DEMO_LANG}" ;;
esac
set_language_data

docker inspect "${NC_CONTAINER}" >/dev/null 2>&1 || abort "Dev-Stack läuft nicht (${NC_CONTAINER})"
[ "$(call "${ADMIN_AUTH}" GET "${API_URL}/me" /dev/null)" = 200 ] || abort "Gameworld antwortet nicht unter ${API_URL}"

if [ "${DO_CLEANUP}" -eq 1 ]; then
	cleanup
	exit 0
fi

say "== Sprache ${DEMO_LANG} =="
set_admin_lang

say "== Konten und Gruppen =="
for user in ${DEMO_USERS}; do
	ensure_user "${user}"
done
ensure_group "${G_FAMILY}"
ensure_group "${G_PARENTS}"
in_group "${G_PARENTS}" "${PARENT}"
for user in ${DEMO_USERS}; do
	in_group "${G_FAMILY}" "${user}"
done
code=$(call "${ADMIN_AUTH}" POST "${API_URL}/admin/verwalter-groups/add" "${WORK_DIR}/vg.json" "{\"gid\":\"${G_PARENTS}\"}")
case "${code}" in
200 | 409) say "Verwalter-Gruppe ${G_PARENTS} aktiv" ;;
*) abort "Verwalter-Gruppe ${G_PARENTS} HTTP ${code}" ;;
esac
[ "$(call "${PARENT_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/me.json")" = 200 ] || abort "${PARENT} erreicht /api/me nicht"
[ "$(jq -r '.role' "${WORK_DIR}/me.json")" = verwalter ] || abort "${PARENT} ist keine Verwalterin"

say "== Welten =="
stop_other_languages
ensure_world "${W_FIRST}" mtg_kreativ
FIRST_ID=${WID}
ensure_running "${FIRST_ID}" "${W_FIRST}"
ensure_language "${FIRST_ID}" "${W_FIRST}"
ensure_world "${W_SECOND}" voxelibre_sanft
SECOND_ID=${WID}
ensure_running "${SECOND_ID}" "${W_SECOND}"
ensure_language "${SECOND_ID}" "${W_SECOND}"

say "== Einladungen =="
for user in mia leo "${GRANDMA}"; do
	invite "${FIRST_ID}" user "${user}"
done
invite "${SECOND_ID}" group "${G_FAMILY}"

say "== Erwachsen und Spielzeit =="
code=$(call "${PARENT_AUTH}" POST "${API_URL}/players/adult" "${WORK_DIR}/adult.json" "{\"nc_user\":\"${GRANDMA}\",\"adult\":true}")
[ "${code}" = 200 ] || abort "${GRANDMA} nicht als erwachsen markiert (HTTP ${code})"
say "${GRANDMA} als erwachsen markiert"
code=$(call "${PARENT_AUTH}" POST "${API_URL}/playtime/children/mia" "${WORK_DIR}/plan.json" "$(week_plan)")
[ "${code}" = 200 ] || abort "Spielzeitregel für mia HTTP ${code}: $(jq -r '.detail // empty' "${WORK_DIR}/plan.json" 2>/dev/null)"
say "Spielzeitregel für mia gespeichert"

say "== Sicherung =="
call "${PARENT_AUTH}" GET "${API_URL}/worlds/${FIRST_ID}/backups" "${WORK_DIR}/backups.json" >/dev/null
if [ "$(jq -r '(.backups // []) | length' "${WORK_DIR}/backups.json" 2>/dev/null || printf 0)" -gt 0 ]; then
	say "Sicherung von ${W_FIRST} vorhanden"
else
	code=$(call "${PARENT_AUTH}" POST "${API_URL}/worlds/${FIRST_ID}/backups" "${WORK_DIR}/b.json" '{"confirm_disconnect":true}')
	[ "${code}" = 202 ] || abort "Sicherung nicht gestartet (HTTP ${code})"
	wait_field "${FIRST_ID}" '.backup_job.state // ""' ok "${BACKUP_WAIT}" || abort "Sicherung nicht fertig"
	wait_field "${FIRST_ID}" '.status' running "${START_WAIT}" || abort "${W_FIRST} läuft nach der Sicherung nicht"
	say "Sicherung von ${W_FIRST} fertig"
fi

say "Demo-Daten (${DEMO_LANG}) bereit, Welt-IDs in .dev/screenshot-demo.json"
