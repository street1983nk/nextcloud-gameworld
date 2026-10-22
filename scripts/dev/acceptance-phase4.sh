#!/bin/sh
# Phasenabnahme Phase 4: prüft die sechs Erfolgskriterien aus .planning/ROADMAP.md
# (Spielzeitlimits) gegen den laufenden Dev-Stack mit echter Nextcloud und
# laufender ExApp (Zeittakt 15 s im Lifespan, keine Fakes) und ruft am Ende die
# Abnahme von Phase 3 als Regression (sie ruft Phase 1 und 2 selbst auf).
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen aus der
# docker-CLI, aus curl gegen den AppAPI-Proxy mit echten Nextcloud-Konten, aus
# jq, tar, grep und sqlite3 (fehlt sqlite3, liest die Python-Standardbibliothek
# die Datei nur lesend). Einziges Python-Werkzeug des Projekts ist der
# Session-Prober (tests/e2e/luanti_probe.py) über seine CLI. Zeit-EINGABEN
# (Wochentag, Minute, Datum in Europe/Berlin) rechnet berlin_now per zoneinfo;
# der Helfer bewertet nichts. Zu jeder Prüfung gibt es, wo sinnvoll, eine
# Negativkontrolle (das Verbotene scheitert) und eine Positivkontrolle (die
# Messmethode selbst funktioniert).
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   sh scripts/dev/register-exapp.sh
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Spielpasswörter erscheinen nie in
# der Ausgabe. Ein trap räumt in jedem Fall auf: Abnahme-Welt (Lösch-API,
# Fallback docker rm -f -v), Regeln von gw-kind (DELETE), Ferien der Abnahme,
# Zeitzone zurück auf Europe/Berlin, Wegwerfkonto gw-abnahme4, gw-kind nie in
# admin. gw-kind selbst bleibt bestehen.
#
# Phase 4 hat keine Prüfung der Phasen 1 bis 3 angepasst: Die Regression
# erwartet weiter 84 von 84, 104 von 104 und 75 von 75.
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
REGISTER_SCRIPT="${SCRIPT_DIR}/register-exapp.sh"
PHASE3_SCRIPT="${SCRIPT_DIR}/acceptance-phase3.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
KID=gw-kind
KID_AUTH="${KID}:gw-kind-dev-pass-1"
GUEST=gw-abnahme4
GUEST_PASS=gw-abnahme4-dev-pass-1
GUEST_AUTH="${GUEST}:${GUEST_PASS}"
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
BUNDLE_URL="${PROXY_BASE}/js/gameworld-main.js"
BACKEND_PORT=10040
PID_FILE="${REPO_ROOT}/.dev/exapp.pid"
DB_FILE="${REPO_ROOT}/.dev/storage/gameworld.sqlite3"
WORLD_DIR=/var/lib/minetest/.minetest/worlds/world
RULES_FILE="${WORLD_DIR}/gameworld_time.txt"
LEDGER_FILE="${WORLD_DIR}/gameworld_time_used.txt"
PROBE_HOST=127.0.0.1
NAME_WORLD="Abnahme Spielzeit"
# Weltnamen aller Abnahmen (Phase 1 bis 4); nur diese räumt der Vorlauf als Reste weg.
ACCEPTANCE_WORLDS='["Abnahme Spielzeit","Abnahme Zugang","Abnahme A","Abnahme B","Abnahme Proxy",
"Abnahme Kreativ","Abnahme Abenteuer","Abnahme Status","Abnahme Tot","Abnahme R1","Abnahme R2"]'
HOLIDAY_LABEL="Abnahme Ferien"
SESSION_TIMEOUT=30
NAME_RE='^[A-Za-z0-9_-]{1,20}$'
PASSWORD_RE='^[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}$'
IP_RE='([0-9]{1,3}\.){3}[0-9]{1,3}'
# Kindertexte aus provisioner/time_mod.py und access_mod.py (Teilstrings).
TEXT_LIMIT="Spielzeit für heute ist vorbei"
TEXT_TAG="Heute ist kein Spieltag"
TEXT_WELT="Diese Welt ist gerade zu"
# Kindertexte ohne "0 Uhr" (Owner-Entscheid 21.10.2026): ganzer Tag ohne Uhrzeit.
TEXT_AGAIN_TOMORROW="Morgen kannst du wieder spielen."
TEXT_OPEN_TOMORROW="Morgen ab 10 Uhr ist sie wieder offen."
TEXT_DENY="nicht eingeladen"
TEXT_WAIT="einen Moment warten"
TEXT_WARN_1="Noch 1 Minute"

# Der Prober gibt Kindertexte mit Umlauten aus; unter Windows sonst cp1252.
PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
HOLIDAY_IDS=""
BACKEND_DOWN=0
KID_JOB=""
GUEST_JOB=""
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

# Abbruch, wenn eine Voraussetzung fehlt und Folgeprüfungen sinnlos wären.
abort() {
	printf 'ABBRUCH: %s\n' "$1" >&2
	exit 1
}

# check BESCHREIBUNG BEDINGUNG... -> pass oder fail
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

# add_user KONTO PASSWORT ANZEIGENAME -> legt das Wegwerfkonto frisch an. Ein Altkonto aus
# einem abgebrochenen Lauf wird vorher gelöscht; occ user:add bekommt bis zu drei Versuche
# (die Passwort-Richtlinie fragt unter Umständen einen externen Dienst, das kann kurz
# scheitern). Bei jedem Fehlschlag steht die occ-Ausgabe als Diagnose im Log; das Passwort
# geht nur per Umgebung an occ und erscheint nie in der Ausgabe.
add_user() {
	occ user:delete "$1" >/dev/null 2>&1 || true
	add_try=1
	while [ "${add_try}" -le 3 ]; do
		if docker compose -f "${COMPOSE_FILE}" exec -T -u www-data -e OC_PASS="$2" app \
			php occ user:add --password-from-env --display-name="$3" "$1" >"${WORK_DIR}/user-add.log" 2>&1; then
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

# So meldet AppAPI eine ExApp, auf deren Port niemand lauscht (Nextcloud antwortet dann 500).
CONNECT_ERROR="Failed to connect to host.docker.internal port ${BACKEND_PORT}"

# Zeilen des Nextcloud-Logs mit festem Text $1 (Logdatei aus der Konfiguration).
nc_log_lines() {
	nc_log=$(occ config:system:get logfile 2>/dev/null | tr -d '\r' || true)
	if [ -z "${nc_log}" ]; then
		nc_log="$(occ config:system:get datadirectory 2>/dev/null | tr -d '\r')/nextcloud.log"
	fi
	# MSYS_NO_PATHCONV: Git-Bash schriebe den Container-Pfad sonst in einen Windows-Pfad um;
	# die Compose-Datei bekommt ihren Windows-Pfad deshalb selbst (cygpath).
	compose_file=${COMPOSE_FILE}
	command -v cygpath >/dev/null 2>&1 && compose_file=$(cygpath -m "${COMPOSE_FILE}")
	MSYS_NO_PATHCONV=1 docker compose -f "${compose_file}" exec -T app grep -F -- "$1" "${nc_log}" 2>/dev/null || true
}

# Anzahl der Log-Einträge in Datei $2 mit Zeitstempel ab $1 (UTC, JJJJ-MM-TTTHH:MM:SS).
entries_since() {
	grep -o '"time":"[0-9T:-]*' "$2" 2>/dev/null | cut -c9- | awk -v s="$1" '$0 >= s' | wc -l | tr -d ' '
}

# Beendet gezielt den ExApp-Host-Prozess (PID-Datei, sonst nur der Prozess auf
# dem Backend-Port); nie alle python.exe, damit Parallel-Sessions weiterlaufen.
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

# call AUTH METHODE URL AUSGABE [JSON] -> HTTP-Code
call() {
	if [ -n "${5:-}" ]; then
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$2" -d "$5" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	else
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X "$2" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	fi
}

# http_code METHODE URL AUSGABE [JSON] als admin
http_code() {
	call "${ADMIN_AUTH}" "$@"
}

remember_world() {
	[ -n "$1" ] && WORLD_IDS="${WORLD_IDS} $1"
	return 0
}

remember_holiday() {
	[ -n "$1" ] && HOLIDAY_IDS="${HOLIDAY_IDS} $1"
	return 0
}

# Ferien der Abnahme (Bezeichnung) löschen, auch Reste früherer Läufe.
remove_test_holidays() {
	http_code GET "${API_URL}/playtime" "${WORK_DIR}/hol-clean.json" >/dev/null
	ids=$(jq -r --arg l "${HOLIDAY_LABEL}" '.holidays[]? | select(.label == $l) | .id' \
		"${WORK_DIR}/hol-clean.json" 2>/dev/null || true)
	for holiday_id in ${ids} ${HOLIDAY_IDS}; do
		http_code DELETE "${API_URL}/playtime/holidays/${holiday_id}" /dev/null >/dev/null 2>&1 || true
	done
}

# Alles, was die Abnahme anlegt oder umstellt, wieder in den Ausgangszustand.
reset_fixtures() {
	http_code DELETE "${API_URL}/playtime/children/${KID}" /dev/null >/dev/null 2>&1 || true
	reset_usage "${KID}"
	remove_test_holidays
	http_code POST "${API_URL}/playtime/time-zone" /dev/null '{"time_zone":"Europe/Berlin"}' >/dev/null 2>&1 || true
	occ group:removeuser admin "${KID}" >/dev/null 2>&1 || true
	occ user:delete "${GUEST}" >/dev/null 2>&1 || true
}

cleanup() {
	status=$?
	for job in ${KID_JOB} ${GUEST_JOB}; do
		kill "${job}" 2>/dev/null || true
	done
	if [ "${BACKEND_DOWN}" -eq 1 ] || ! heartbeat_up; then
		printf 'starte die ExApp wieder (register-exapp.sh)\n'
		sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register-cleanup.log" 2>&1 \
			|| printf 'register-exapp.sh scheiterte, bitte von Hand starten\n' >&2
	fi
	for world_id in ${WORLD_IDS}; do
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null \
			"${API_URL}/worlds/${world_id}" >/dev/null 2>&1 || true
		# Fallback, falls die API nicht mehr antwortet: direkt über die docker-CLI.
		for container in $(docker ps -aq --filter "label=gameworld.world_id=${world_id}" 2>/dev/null); do
			docker rm -f -v "${container}" >/dev/null 2>&1 || true
		done
		for volume in $(docker volume ls -q 2>/dev/null | grep -e "-${world_id}\$" || true); do
			docker volume rm "${volume}" >/dev/null 2>&1 || true
		done
	done
	reset_fixtures
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

container_of() {
	docker ps -aq --no-trunc --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1"
}

inspect() {
	docker inspect -f "$2" "$1" 2>/dev/null || printf 'nicht lesbar'
}

world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

wait_status() {
	WAITED=0
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		[ "${WAITED}" -lt "$3" ] || return 1
		sleep 1
		WAITED=$((WAITED + 1))
	done
}

# read_file CONTAINER PFAD ZIEL -> Inhalt per docker cp, tar-Kopf in ZIEL.list
read_file() {
	# MSYS_NO_PATHCONV: Git Bash würde den Containerpfad sonst umschreiben.
	MSYS_NO_PATHCONV=1 docker cp "$1:$2" - >"$3.tar" 2>/dev/null || true
	tar -xOf "$3.tar" 2>/dev/null | tr -d '\r' >"$3" || true
	tar -tvf "$3.tar" --numeric-owner >"$3.list" 2>/dev/null || true
}

player_field() {
	jq -r --arg u "$2" ".players[]? | select(.nc_user == \$u) | .$3 // empty" "$1" 2>/dev/null || true
}

# Ein Join-Versuch oder (mit --hold) eine Sitzung über die Prober-CLI, JSON nach $1.
probe() {
	out=$1
	shift
	(cd "${REPO_ROOT}" && uv run python -m tests.e2e.luanti_probe "${PROBE_HOST}" "${PORT}" "$@") \
		>"${out}" 2>"${out}.err" || printf '{"result":"prober_error"}' >"${out}"
}

# probe_expect DATEI JQ-BEDINGUNG SEKUNDEN NAME [PW] -> 0, sobald die Bedingung gilt
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

# denied_with DATEI TEXT -> Join abgelehnt und Begründung enthält TEXT
denied_with() {
	[ "$(jq -r --arg t "$2" '.result == "denied" and ((.reason // "") | contains($t))' "$1" 2>/dev/null)" = true ]
}

accepted() {
	[ "$(jq -r '.result' "$1" 2>/dev/null)" = auth_accept ]
}

# Lesender SQL-Zugriff auf die ExApp-Datei: sqlite3, sonst die Standardbibliothek.
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

# Verbrauch eines Kontos löschen (einzige schreibende SQL-Stelle der Abnahme). Seit WR-04
# behält "Regeln entfernen" den heutigen Verbrauch (Owner-Entscheid); die Abnahme misst K5
# aber ab null und darf an einem Tag mehrfach laufen.
reset_usage() {
	db_path=${DB_FILE}
	command -v cygpath >/dev/null 2>&1 && db_path=$(cygpath -w "${DB_FILE}")
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sqlite3, sys
con = sqlite3.connect(sys.argv[1], timeout=10)
with con:
    con.execute("DELETE FROM time_usage WHERE nc_user = ?", (sys.argv[2],))
con.close()
' "${db_path}" "$1") >/dev/null 2>&1 || true
}

# Nur Zeit-EINGABEN: ISO-Wochentag heute, morgen, lokale Minute, Datum, Epoch
# von heute 00:00 und optional von heute MINUTE (1440 = morgen 00:00), alles in
# Europe/Berlin. TZ=... date geht hier nicht (Git-Bash ohne zoneinfo).
berlin_now() {
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
tz = ZoneInfo("Europe/Berlin")
now = datetime.now(tz)
day = now.date()
def at(minute):
    d = day + timedelta(days=minute // 1440)
    m = minute % 1440
    return int(datetime(d.year, d.month, d.day, m // 60, m % 60, tzinfo=tz).timestamp())
extra = at(int(sys.argv[1])) if len(sys.argv) > 1 else ""
print(now.isoweekday(), (day + timedelta(days=1)).isoweekday(), now.hour * 60 + now.minute,
      day.isoformat(), at(0), extra)
' "$@") 2>/dev/null | tr -d '\r'
}

# week TAGE LIMIT ANFANG ENDE -> sieben Wochentage als JSON; TAGE z. B. "3" oder
# "1,2,3,4,5,6,7", LIMIT/ANFANG/ENDE als Zahl oder null; nicht genannte Tage aus.
week() {
	jq -nc --arg days "$1" --argjson limit "$2" --argjson ws "$3" --argjson we "$4" '
		($days | split(",") | map(tonumber)) as $on
		| [range(1; 8) as $d
			| if any($on[]; . == $d)
				then {weekday: $d, allowed: true, limit_minutes: $limit, window_start: $ws, window_end: $we}
				else {weekday: $d, allowed: false} end]'
}

# set_plan NORMAL [FERIEN] -> HTTP-Code von POST /playtime/children/gw-kind
set_plan() {
	if [ -n "${2:-}" ]; then
		body=$(jq -nc --argjson n "$1" --argjson h "$2" '{normal: $n, holiday: $h}')
	else
		body=$(jq -nc --argjson n "$1" '{normal: $n}')
	fi
	http_code POST "${API_URL}/playtime/children/${KID}" "${WORK_DIR}/plan.json" "${body}"
}

day_name() {
	case "$1" in
	1) printf 'Mo' ;; 2) printf 'Di' ;; 3) printf 'Mi' ;; 4) printf 'Do' ;;
	5) printf 'Fr' ;; 6) printf 'Sa' ;; 7) printf 'So' ;;
	esac
}

usage_today() {
	sql "SELECT seconds FROM time_usage WHERE nc_user = '$1' AND day = '${TODAY}'" | head -n 1
}

user_present() { occ user:info "$1" >/dev/null 2>&1; }
user_absent() { ! user_present "$1"; }

eq() { [ "$1" = "$2" ]; }
# same_nonempty A B: gleich und nicht leer; ein gescheitertes Lesen (leer) besteht nie (WR-08).
same_nonempty() { [ -n "$1" ] && [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
matches() { printf '%s' "$1" | grep -Eq "$2"; }
contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }
between() { [ -n "$1" ] && [ "$1" -ge "$2" ] && [ "$1" -le "$3" ]; }
float_between() { awk -v v="$1" -v lo="$2" -v hi="$3" 'BEGIN { exit !(v != "" && v + 0 >= lo && v + 0 <= hi) }'; }

hits_in() {
	grep -c -a -F -- "$1" "$2" 2>/dev/null || true
}

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq tar grep awk uv; do
	command -v "${tool}" >/dev/null 2>&1 || abort "Werkzeug ${tool} fehlt"
done
if ! curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
	abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
if ! occ app_api:app:list 2>/dev/null | grep -q '^gameworld '; then
	abort "Gameworld ist nicht registriert. Zuerst: sh scripts/dev/register-exapp.sh"
fi
heartbeat_up || abort "ExApp antwortet nicht auf Port ${BACKEND_PORT}. Zuerst: sh scripts/dev/register-exapp.sh"
occ user:info "${KID}" >/dev/null 2>&1 || abort "Konto ${KID} fehlt (legt acceptance-phase1.sh an)"
[ -f "${DB_FILE}" ] || abort "SQLite-Datei fehlt: ${DB_FILE}"
[ -n "$(berlin_now)" ] || abort "berlin_now liefert nichts (tzdata im venv? uv sync)"

# Nahe Mitternacht bis 00:01 warten: Fenster und Tagesgrenze gehören zu heute.
set -- $(berlin_now)
if [ "$3" -ge 1430 ]; then
	pause=$(((1441 - $3) * 60))
	printf 'Es ist kurz vor Mitternacht, warte %s s bis 00:01\n' "${pause}"
	sleep "${pause}"
fi

# Ab hier zählen AppAPI-Verbindungsfehler zur ExApp (Prüfung am Ende), UTC wie im Nextcloud-Log.
RUN_START=$(date -u +%Y-%m-%dT%H:%M:%S)

# Reste eines abgebrochenen früheren Laufs entfernen, auch Welten der Phasen 1 bis 3:
# Fiel die ExApp dort aus, löscht deren Aufräumen nur Container und Volume, die Zeile
# bleibt, und der nächste Start des Backends legt die Welt neu an.
reset_fixtures
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --argjson names "${ACCEPTANCE_WORLDS}" \
	'.worlds[]? | select(.name as $n | $names | index($n)) | .id' "${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	remember_world "${old_id}"
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null "${API_URL}/worlds/${old_id}" || true
done

printf '\n== Vorbereitung ==\n'
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/world.json" "{\"name\":\"${NAME_WORLD}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/world.json" 2>/dev/null || true)
remember_world "${WORLD_ID}"
check "POST '${NAME_WORLD}' (Kreativ) HTTP 201 (ist ${CODE})" eq "${CODE}" 201
[ -n "${WORLD_ID}" ] || abort "Antwort ohne id"
matches "${WORLD_ID}" '^[A-Za-z0-9_-]+$' || abort "unerwartete Welt-ID"
CONTAINER=$(container_of "${WORLD_ID}")
[ -n "${CONTAINER}" ] || abort "kein Container mit Label gameworld.world_id"
check "Welt running binnen 40 s" wait_status "${WORLD_ID}" running 40
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
check "docker port liefert einen UDP-Port (ist ${PORT:-leer})" matches "${PORT}" '^[0-9]+$'

add_user "${GUEST}" "${GUEST_PASS}" "Gast Abnahme 4" || abort "Konto ${GUEST} ließ sich nach drei Versuchen nicht anlegen (occ-Ausgabe oben)"
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
check "Spielernamen nach Muster (${KID_NAME}, ${GUEST_NAME}, ${ADMIN_NAME})" sh -c \
	'for n in "$2" "$3" "$4"; do printf "%s" "$n" | grep -Eq "$1" || exit 1; done' _ \
	"${NAME_RE}" "${KID_NAME}" "${GUEST_NAME}" "${ADMIN_NAME}"
check "Spielpasswörter gesetzt und nach Muster (Längen ${#KID_PW}, ${#GUEST_PW}, ${#ADMIN_PW})" sh -c \
	'for p in "$2" "$3" "$4"; do printf "%s" "$p" | grep -Eq "$1" || exit 1; done' _ \
	"${PASSWORD_RE}" "${KID_PW}" "${GUEST_PW}" "${ADMIN_PW}"
STARTED=$(inspect "${CONTAINER}" '{{.State.StartedAt}}')

set -- $(berlin_now)
TODAY_WD=$1
TOMORROW_WD=$2
NOW_MIN=$3
TODAY=$4
TOMORROW_TOKEN=$(day_name "${TOMORROW_WD}")
printf 'Zeit-Eingaben (Europe/Berlin): Wochentag %s, morgen %s, Minute %s, Datum %s\n' \
	"${TODAY_WD}" "${TOMORROW_WD}" "${NOW_MIN}" "${TODAY}"
OTHER_DAYS=$(printf '1\n2\n3\n4\n5\n6\n7\n' | grep -v -x "${TODAY_WD}" | paste -sd, -)

printf '\n== K1 Limit und Fenster pro Kind ==\n'
# K1 Eltern legen pro Kind ein Tageslimit und erlaubte Uhrzeiten fest (SC 1)
WINDOW_END=1140
[ "${NOW_MIN}" -ge 1110 ] && WINDOW_END=1440
set -- $(berlin_now "${WINDOW_END}")
EXPECT_FROM=$5
EXPECT_UNTIL=$6
CODE=$(set_plan "$(week "${TODAY_WD}" 120 0 "${WINDOW_END}")")
check "K1 POST /playtime/children/${KID} heute 120 min, 00:00 bis Minute ${WINDOW_END}: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K1 Antwort applied true (Regeldatei in der laufenden Welt)" \
	eq "$(jq -r '.applied' "${WORK_DIR}/plan.json" 2>/dev/null)" true
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt1.json" >/dev/null
check "K1 GET /playtime: ${KID} has_rules true" \
	eq "$(jq -r --arg u "${KID}" '.children[]? | select(.nc_user == $u) | .has_rules' "${WORK_DIR}/pt1.json" 2>/dev/null)" true
read_file "${CONTAINER}" "${RULES_FILE}" "${WORK_DIR}/rules1.txt"
check "K1 Regeldatei per docker cp gelesen (Positivkontrolle)" test -s "${WORK_DIR}/rules1.txt"
check "K1 Kopfzeile 'gameworld-time 1 <Generation> <Zeit>'" \
	sh -c 'head -n 1 "$1" | grep -Eqx "gameworld-time 1 [0-9]+ [0-9]+"' _ "${WORK_DIR}/rules1.txt"
check "K1 Schlusszeile 'end'" eq "$(tail -n 1 "${WORK_DIR}/rules1.txt")" end
KID_LINE=$(grep "^${KID_NAME} " "${WORK_DIR}/rules1.txt" || true)
printf 'Zeile des Kindes: %s\n' "${KID_LINE:-fehlt}"
check "K1 Zeile des Kindes: Deckel 7200 s, von ${EXPECT_FROM}, bis ${EXPECT_UNTIL}, Grund ok" \
	eq "$(printf '%s' "${KID_LINE}" | awk '{print $2, $3, $4, $5}')" "7200 ${EXPECT_FROM} ${EXPECT_UNTIL} ok"
check "K1 keine Zeile für ${GUEST} (ohne Regeln, Opt-in)" \
	eq "$(grep -c "^${GUEST_NAME} " "${WORK_DIR}/rules1.txt" || true)" 0
check "K1 Verwalter admin mit frei-Zeile (-1 -1 -1 frei -)" \
	sh -c 'grep -qx "$2 -1 -1 -1 frei -" "$1"' _ "${WORK_DIR}/rules1.txt" "${ADMIN_NAME}"
RULES_META=$(awk '{print $1, $2}' "${WORK_DIR}/rules1.txt.list" 2>/dev/null | head -n 1)
check "K1 Regeldatei gehört root und ist -r--r--r-- (ist ${RULES_META:-leer})" eq "${RULES_META}" "-r--r--r-- 0/0"
CODE=$(set_plan "$(week "${TODAY_WD}" 0 null null)")
check "K1 Negativkontrolle: limit_minutes 0 HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(set_plan "$(week "${TODAY_WD}" 60 600 540)")
check "K1 Negativkontrolle: Fensterende vor Fensteranfang HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(set_plan "$(week "${TODAY_WD}" 60 null null | jq -c '.[0:6]')")
check "K1 Negativkontrolle: nur 6 Wochentage HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(call "${KID_AUTH}" POST "${API_URL}/playtime/children/${KID}" /dev/null "{\"normal\":$(week "${TODAY_WD}" null null null)}")
# Genau 404 (AppAPI, ADMIN-Route): Ein abgestürztes Backend besteht nicht mehr (WR-08).
check "K1 Negativkontrolle: ${KID} setzt eigene Regeln, HTTP 404 (ist ${CODE})" eq "${CODE}" 404
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt1b.json" >/dev/null
check "K1 nach den Fehlversuchen gilt weiter limit 120 am heutigen Tag" \
	eq "$(jq -r --arg u "${KID}" --argjson d "${TODAY_WD}" \
		'.children[]? | select(.nc_user == $u) | .normal[]? | select(.weekday == $d) | .limit_minutes' \
		"${WORK_DIR}/pt1b.json" 2>/dev/null)" 120
check "K1 Positivkontrolle: mit dieser Regel ${KID} auth_accept" \
	probe_expect "${WORK_DIR}/k1-kid.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"

printf '\n== K2 Wochenplan ==\n'
# K2 Wochenplan je Wochentag, Server setzt ihn ohne Neustart durch (SC 2)
CODE=$(set_plan "$(week "${TOMORROW_WD}" null null null)")
check "K2 Plan nur morgen (${TOMORROW_TOKEN}) erlaubt: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
probe "${WORK_DIR}/k2-deny.json" "${KID_NAME}" "${KID_PW}"
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k2-deny.json")"
check "K2 ${KID} denied mit '${TEXT_TAG}'" denied_with "${WORK_DIR}/k2-deny.json" "${TEXT_TAG}"
check "K2 Text nennt die nächste Spielzeit '${TEXT_AGAIN_TOMORROW}'" \
	denied_with "${WORK_DIR}/k2-deny.json" "${TEXT_AGAIN_TOMORROW}"
check "K2 Text ohne '0 Uhr' und '00:00'" \
	eq "$(jq -r '(.reason // "") | test("(^|[^0-9])0 Uhr|00:00|Mitternacht")' "${WORK_DIR}/k2-deny.json" 2>/dev/null)" false
CODE=$(set_plan "$(week "${TODAY_WD}" null null null)")
check "K2 Plan heute erlaubt: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 Positivkontrolle: ${KID} auth_accept" \
	probe_expect "${WORK_DIR}/k2-ok.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"
check "K2 ohne Neustart der Welt (State.StartedAt unverändert)" \
	same_nonempty "$(inspect "${CONTAINER}" '{{.State.StartedAt}}')" "${STARTED}"
call "${ADMIN_AUTH}" GET "${BUNDLE_URL}" "${WORK_DIR}/bundle.js" >/dev/null
for preset in "Keine Begrenzung" "Nur am Wochenende" "Jeden Tag 1 Stunde" "Schultage kurz, Wochenende länger"; do
	check "K2 Voreinstellung '${preset}' im ausgelieferten Bundle" \
		sh -c '[ "$(grep -c -F -- "$2" "$1" || true)" != 0 ]' _ "${WORK_DIR}/bundle.js" "${preset}"
done
check "K2 Negativkontrolle: dasselbe grep findet eine erfundene Voreinstellung nicht" \
	sh -c '[ "$(grep -c -F -- "Jeden Tag 7 Stunden" "$1" || true)" = 0 ]' _ "${WORK_DIR}/bundle.js"

printf '\n== K3 Ferien ==\n'
# K3 Ferienplan je Kind, Ferienzeiträume für den Haushalt (SC 3)
CODE=$(set_plan "$(week "${OTHER_DAYS}" null null null)" "$(week 1,2,3,4,5,6,7 null null null)")
check "K3 Normalplan heute aus, Ferienplan jeden Tag: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
probe "${WORK_DIR}/k3-deny.json" "${KID_NAME}" "${KID_PW}"
check "K3 ohne Ferienzeitraum: ${KID} denied mit '${TEXT_TAG}' ($(probe_summary "${WORK_DIR}/k3-deny.json"))" \
	denied_with "${WORK_DIR}/k3-deny.json" "${TEXT_TAG}"
CODE=$(http_code POST "${API_URL}/playtime/holidays" "${WORK_DIR}/hol.json" \
	"{\"label\":\"${HOLIDAY_LABEL}\",\"start_date\":\"${TODAY}\",\"end_date\":\"${TODAY}\"}")
HOLIDAY_ID=$(jq -r '.id // empty' "${WORK_DIR}/hol.json" 2>/dev/null || true)
remember_holiday "${HOLIDAY_ID}"
check "K3 POST holidays ${TODAY} bis ${TODAY}: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 Positivkontrolle: in den Ferien ${KID} auth_accept" \
	probe_expect "${WORK_DIR}/k3-ok.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"
check "K3 ohne Neustart der Welt (State.StartedAt unverändert)" \
	same_nonempty "$(inspect "${CONTAINER}" '{{.State.StartedAt}}')" "${STARTED}"
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt3.json" >/dev/null
check "K3 GET /playtime: Zeitraum '${HOLIDAY_LABEL}' active true" \
	eq "$(jq -r --arg l "${HOLIDAY_LABEL}" '.holidays[]? | select(.label == $l) | .active' "${WORK_DIR}/pt3.json" 2>/dev/null)" true
CODE=$(http_code DELETE "${API_URL}/playtime/holidays/${HOLIDAY_ID}" /dev/null)
check "K3 DELETE holiday HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 nach dem Entfernen: ${KID} wieder denied mit '${TEXT_TAG}'" \
	probe_expect "${WORK_DIR}/k3-deny2.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_TAG}\"))" 10 \
	"${KID_NAME}" "${KID_PW}"
CODE=$(http_code POST "${API_URL}/playtime/holidays" /dev/null \
	"{\"label\":\"${HOLIDAY_LABEL}\",\"start_date\":\"${TODAY}\",\"end_date\":\"2000-01-01\"}")
check "K3 Negativkontrolle: Zeitraum endet vor Beginn HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(http_code POST "${API_URL}/playtime/time-zone" /dev/null '{"time_zone":"Mars/Base"}')
check "K3 Negativkontrolle: Zeitzone 'Mars/Base' HTTP 422 (ist ${CODE})" eq "${CODE}" 422
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt3b.json" >/dev/null
check "K3 Zeitzone bleibt Europe/Berlin" eq "$(jq -r '.time_zone' "${WORK_DIR}/pt3b.json" 2>/dev/null)" Europe/Berlin

printf '\n== K4 Welt-Zeitfenster ==\n'
# K4 Zeitfenster pro Welt, Verwalter immer drin, Welt läuft weiter (SC 4)
CODE=$(http_code DELETE "${API_URL}/playtime/children/${KID}" /dev/null)
check "K4 Regeln von ${KID} gelöscht (Opt-in) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
# K5 misst den Verbrauch ab null (der heutige bleibt seit WR-04 beim Entfernen stehen).
reset_usage "${KID}"
WINDOW_BODY=$(jq -nc --argjson t "${TOMORROW_WD}" \
	'{days: [range(1; 8) as $d | if $d == $t then {weekday: $d, open: true, window_start: 600, window_end: 720} else {weekday: $d, open: false} end]}')
CODE=$(http_code POST "${API_URL}/playtime/worlds/${WORLD_ID}/window" "${WORK_DIR}/win.json" "${WINDOW_BODY}")
check "K4 Welt-Fenster nur ${TOMORROW_TOKEN} 10 bis 12 Uhr: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
probe "${WORK_DIR}/k4-kid.json" "${KID_NAME}" "${KID_PW}"
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k4-kid.json")"
check "K4 ${KID} denied mit '${TEXT_WELT}'" denied_with "${WORK_DIR}/k4-kid.json" "${TEXT_WELT}"
check "K4 Text nennt die Öffnung '${TEXT_OPEN_TOMORROW}'" denied_with "${WORK_DIR}/k4-kid.json" "${TEXT_OPEN_TOMORROW}"
check "K4 Verwalter admin trotz geschlossener Welt auth_accept" \
	probe_expect "${WORK_DIR}/k4-admin.json" '.result == "auth_accept"' 10 "${ADMIN_NAME}" "${ADMIN_PW}"
probe "${WORK_DIR}/k4-fremd.json" Fremder
check "K4 'Fremder' denied mit '${TEXT_DENY}', nicht mit dem Zeittext" \
	sh -c 'jq -e --arg d "$2" --arg w "$3" ".result == \"denied\" and ((.reason // \"\") | contains(\$d)) and ((.reason // \"\") | contains(\$w) | not)" "$1" >/dev/null' _ \
	"${WORK_DIR}/k4-fremd.json" "${TEXT_DENY}" "${TEXT_WELT}"
check "K4 Container läuft weiter (State.Status running)" eq "$(inspect "${CONTAINER}" '{{.State.Status}}')" running
check "K4 Container nicht neu gestartet (StartedAt unverändert)" same_nonempty "$(inspect "${CONTAINER}" '{{.State.StartedAt}}')" "${STARTED}"
check "K4 desired_state in der SQLite-Datei running" \
	eq "$(sql "SELECT desired_state FROM worlds WHERE id = '${WORLD_ID}'")" running
CODE=$(http_code DELETE "${API_URL}/playtime/worlds/${WORLD_ID}/window" /dev/null)
check "K4 DELETE window HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K4 Positivkontrolle: ohne Fenster ${KID} auth_accept" \
	probe_expect "${WORK_DIR}/k4-kid-ok.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"

printf '\n== K5 Trennen mit Vorwarnung und Join-Sperre ==\n'
# K5 Vorwarnung, Trennen am Limit, danach keine Rückkehr; ohne Regeln kein Trennen (SC 5)
# Erstkontakt: Taucht ein Name zum ersten Mal im Zählbuch einer Welt auf, verankert
# die ExApp nur (playtime/ledger.py, Schutz gegen Doppelzählung); die Sekunden bis
# zum ersten Takt, höchstens etwa 20, bleiben einmalig je Kind und Welt ungezählt.
# Damit der Messwert nicht von dieser Lage im Takt abhängt, betritt gw-kind die
# Welt vorher einmal kurz ohne Regeln, und das Skript wartet auf die Verankerung.
probe "${WORK_DIR}/k5-warm.json" "${KID_NAME}" "${KID_PW}" --hold 3 --timeout "${SESSION_TIMEOUT}"
check "K5 Vorlauf: ${KID} ohne Regeln 3 s verbunden (held)" eq "$(jq -r '.result' "${WORK_DIR}/k5-warm.json" 2>/dev/null)" held
SEEN=0
waited=0
while [ "${waited}" -le 40 ]; do
	SEEN=$(sql "SELECT count(*) FROM time_ledger_seen WHERE world_id = '${WORLD_ID}' AND player_name = '${KID_NAME}'")
	[ "${SEEN}" = 1 ] && break
	sleep 3
	waited=$((waited + 3))
done
check "K5 Vorlauf: Zählbuch-Zeile von ${KID_NAME} binnen 40 s verankert (ist ${SEEN:-leer} nach ${waited} s)" eq "${SEEN}" 1
sleep 2.5
CODE=$(set_plan "$(week "${TODAY_WD}" 2 null null)")
check "K5 Plan heute 2 Minuten: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
printf 'Sitzungen %s (2 min) und %s (ohne Regeln) für bis zu 170 s\n' "${KID}" "${GUEST}"
probe "${WORK_DIR}/k5-kid.json" "${KID_NAME}" "${KID_PW}" --hold 170 --timeout "${SESSION_TIMEOUT}" &
KID_JOB=$!
probe "${WORK_DIR}/k5-guest.json" "${GUEST_NAME}" "${GUEST_PW}" --hold 170 --timeout "${SESSION_TIMEOUT}" &
GUEST_JOB=$!
wait "${KID_JOB}" || true
KID_JOB=""
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k5-kid.json")"
jq -r '.events[]? | "  \(.t) s \(.kind): \(.text)"' "${WORK_DIR}/k5-kid.json" 2>/dev/null || true
check "K5 ${KID} getrennt (result kicked)" eq "$(jq -r '.result' "${WORK_DIR}/k5-kid.json" 2>/dev/null)" kicked
KICK_AFTER=$(jq -r '.after_s // empty' "${WORK_DIR}/k5-kid.json" 2>/dev/null || true)
check "K5 Trennen nach 100 bis 140 s (ist ${KICK_AFTER:-leer})" float_between "${KICK_AFTER}" 100 140
check "K5 Trenntext enthält '${TEXT_LIMIT}'" \
	eq "$(jq -r --arg t "${TEXT_LIMIT}" '(.reason // "") | contains($t)' "${WORK_DIR}/k5-kid.json" 2>/dev/null)" true
check "K5 vorher Chat '${TEXT_WARN_1}'" \
	eq "$(jq -r --arg t "${TEXT_WARN_1}" --argjson k "${KICK_AFTER:-0}" \
		'[.events[]? | select(.kind == "chat" and (.text | contains($t)) and .t < $k)] | length > 0' \
		"${WORK_DIR}/k5-kid.json" 2>/dev/null)" true
sleep 2.5
probe "${WORK_DIR}/k5-rejoin.json" "${KID_NAME}" "${KID_PW}"
check "K5 nach 2,5 s: Wiederbeitritt von ${KID} denied mit '${TEXT_LIMIT}'" \
	denied_with "${WORK_DIR}/k5-rejoin.json" "${TEXT_LIMIT}"
USED=""
waited=0
while [ "${waited}" -le 30 ]; do
	USED=$(usage_today "${KID}")
	between "${USED}" 100 140 && break
	sleep 3
	waited=$((waited + 3))
done
check "K5 time_usage ${KID} ${TODAY} binnen 30 s bei 100 bis 140 s (ist ${USED:-leer} nach ${waited} s)" \
	between "${USED}" 100 140
check "K5 keine Zeile in time_usage für ${GUEST} (ohne Regeln nicht gezählt)" \
	eq "$(sql "SELECT count(*) FROM time_usage WHERE nc_user = '${GUEST}'")" 0
CODE=$(call "${KID_AUTH}" GET "${API_URL}/my/playtime" "${WORK_DIR}/my-kid.json")
check "K5 GET /my/playtime als ${KID}: HTTP 200, limited true, state aufgebraucht (ist ${CODE} $(jq -c '{limited,state}' "${WORK_DIR}/my-kid.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '"\(.limited) \(.state)"' "${WORK_DIR}/my-kid.json" 2>/dev/null)" "200 true aufgebraucht"
CODE=$(call "${GUEST_AUTH}" GET "${API_URL}/my/playtime" "${WORK_DIR}/my-guest.json")
check "K5 GET /my/playtime als ${GUEST}: HTTP 200, limited false (ist ${CODE} $(jq -c '{limited}' "${WORK_DIR}/my-guest.json" 2>/dev/null))" \
	eq "${CODE} $(jq -r '.limited' "${WORK_DIR}/my-guest.json" 2>/dev/null)" "200 false"
wait "${GUEST_JOB}" || true
GUEST_JOB=""
printf '%s: %s\n' "${GUEST}" "$(probe_summary "${WORK_DIR}/k5-guest.json")"
check "K5 Positivkontrolle: ${GUEST} ohne Regeln bleibt 170 s verbunden (result held)" \
	eq "$(jq -r '.result' "${WORK_DIR}/k5-guest.json" 2>/dev/null)" held

printf '\n== K6 Neustart- und Rejoin-Festigkeit ==\n'
# K6 Limit hält über Welt-Neustart, ExApp-Neustart und Rejoin (SC 6)
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/restart" /dev/null)
check "K6 POST restart HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K6 Welt nach dem Neustart running binnen 60 s" wait_status "${WORLD_ID}" running 60
CONTAINER=$(container_of "${WORLD_ID}")
STARTED_RESTART=$(inspect "${CONTAINER}" '{{.State.StartedAt}}')
# Beide Zeitpunkte müssen gelesen sein: ein leeres inspect besteht nicht (WR-08).
check "K6 Welt wirklich neu gestartet (StartedAt geändert, ${STARTED} -> ${STARTED_RESTART:-leer})" sh -c \
	'[ -n "$1" ] && [ -n "$2" ] && [ "$1" != "$2" ]' _ "${STARTED_RESTART}" "${STARTED}"
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
check "K6 nach Welt-Neustart: ${KID} denied mit '${TEXT_LIMIT}'" \
	probe_expect "${WORK_DIR}/k6-restart.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_LIMIT}\"))" 40 \
	"${KID_NAME}" "${KID_PW}"
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/k6-restart.json")"

printf 'beende den ExApp-Prozess (Neustart)\n'
OLD_PID=$(cat "${PID_FILE}" 2>/dev/null || true)
BACKEND_DOWN=1
check "K6 ExApp-Prozess beendet, Heartbeat schweigt" kill_backend
probe "${WORK_DIR}/k6-down.json" "${KID_NAME}" "${KID_PW}"
check "K6 ohne ExApp setzt die Welt weiter durch: ${KID} denied mit '${TEXT_LIMIT}'" \
	denied_with "${WORK_DIR}/k6-down.json" "${TEXT_LIMIT}"
sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register.log" 2>&1 || true
BACKEND_DOWN=0
check "K6 register-exapp.sh hat ein neues Backend gestartet" \
	sh -c 'grep -q "starte das Backend" "$1" && [ "$(cat "$2")" != "$3" ]' _ \
	"${WORK_DIR}/register.log" "${PID_FILE}" "${OLD_PID}"
check "K6 nach ExApp-Neustart: ${KID} weiterhin denied mit '${TEXT_LIMIT}'" \
	probe_expect "${WORK_DIR}/k6-exapp.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_LIMIT}\"))" 10 \
	"${KID_NAME}" "${KID_PW}"

read_file "${CONTAINER}" "${LEDGER_FILE}" "${WORK_DIR}/ledger.txt"
check "K6 Zählbuch per docker cp gelesen (Positivkontrolle)" test -s "${WORK_DIR}/ledger.txt"
check "K6 Kopfzeile 'gameworld-time-used 1 <Zeit> <Generation>'" \
	sh -c 'head -n 1 "$1" | grep -Eqx "gameworld-time-used 1 [0-9]+ [0-9]+"' _ "${WORK_DIR}/ledger.txt"
check "K6 Schlusszeile 'end'" eq "$(tail -n 1 "${WORK_DIR}/ledger.txt")" end
LEDGER_KID=$(awk -v n="${KID_NAME}" '$1 == n {print $2}' "${WORK_DIR}/ledger.txt")
check "K6 Zählbuch: ${KID_NAME} mit mindestens 100 s (ist ${LEDGER_KID:-leer}), über den Neustart erhalten" \
	between "${LEDGER_KID}" 100 100000
sed '1d;$d' "${WORK_DIR}/ledger.txt" >"${WORK_DIR}/ledger.body"
check "K6 jede Zählbuch-Zeile ist nur 'Spielername Sekunden'" \
	sh -c '[ "$(grep -c -v -E "^[A-Za-z0-9_-]{1,20} [0-9]+$" "$1" || true)" = 0 ]' _ "${WORK_DIR}/ledger.body"
check "K6 keine IP-ähnlichen Muster im Zählbuch" \
	sh -c '[ "$(grep -c -E "$2" "$1" || true)" = 0 ]' _ "${WORK_DIR}/ledger.txt" "${IP_RE}"
printf 'Mia 12\n10.0.0.7\n' >"${WORK_DIR}/ip-probe.txt"
check "K6 Positivkontrolle: dieselben greps finden eine IP und eine fremde Zeile in einer Probedatei" \
	sh -c '[ "$(grep -c -E "$2" "$1" || true)" != 0 ] && [ "$(grep -c -v -E "^[A-Za-z0-9_-]{1,20} [0-9]+$" "$1" || true)" != 0 ]' _ \
	"${WORK_DIR}/ip-probe.txt" "${IP_RE}"

printf 'Wiederbeitritts-Sperre: fünf Runden %s, Sitzung 2 s, Join nach 0,2 s\n' "${GUEST}"
# Sitzung und neuer Versuch laufen in EINEM Prober-Prozess (--rejoin-after): Zwei
# getrennte Aufrufe brauchen je einen Prozessstart (uv), der unter Windows bis zu
# etwa 2 s dauert und damit die 2-s-Sperre des Mods (COOLDOWN) gelegentlich schon
# überschreitet (früher 4 von 5). Der gemessene Abstand gap_s muss klar unter der
# Sperre liegen, sonst belegt die Runde nichts und zählt nicht.
STARTED_GUARD=$(inspect "${CONTAINER}" '{{.State.StartedAt}}')
GUARD_OK=0
round=1
while [ "${round}" -le 5 ]; do
	sleep 2.5
	probe "${WORK_DIR}/k6-guard.json" "${GUEST_NAME}" "${GUEST_PW}" --hold 2 --rejoin-after 0.2 \
		--timeout "${SESSION_TIMEOUT}"
	jq '.rejoin // {"result":"prober_error"}' "${WORK_DIR}/k6-guard.json" >"${WORK_DIR}/k6-wait.json" 2>/dev/null \
		|| printf '{"result":"prober_error"}' >"${WORK_DIR}/k6-wait.json"
	GAP=$(jq -r '.gap_s // "x"' "${WORK_DIR}/k6-guard.json" 2>/dev/null || printf 'x')
	printf '  Runde %s: Sitzung %s, Join nach %s s: %s\n' "${round}" \
		"$(jq -r '.result' "${WORK_DIR}/k6-guard.json" 2>/dev/null)" "${GAP}" "$(probe_summary "${WORK_DIR}/k6-wait.json")"
	if [ "$(jq -r '.result' "${WORK_DIR}/k6-guard.json" 2>/dev/null)" = held ] \
		&& awk -v g="${GAP}" 'BEGIN { exit !(g ~ /^[0-9.]+$/ && g + 0 >= 0.2 && g + 0 < 1.0) }' \
		&& denied_with "${WORK_DIR}/k6-wait.json" "${TEXT_WAIT}"; then
		GUARD_OK=$((GUARD_OK + 1))
	fi
	round=$((round + 1))
done
check "K6 fünfmal Sitzung held und Join nach 0,2 s (gemessen unter 1 s) denied mit '${TEXT_WAIT}' (ist ${GUARD_OK} von 5)" \
	eq "${GUARD_OK}" 5
sleep 2
check "K6 danach Container running" eq "$(inspect "${CONTAINER}" '{{.State.Status}}')" running
check "K6 danach StartedAt unverändert (kein Absturz)" same_nonempty "$(inspect "${CONTAINER}" '{{.State.StartedAt}}')" "${STARTED_GUARD}"
sleep 2.5
check "K6 Positivkontrolle: nach 2,5 s Pause kommt ${GUEST} wieder hinein (held)" \
	probe_expect "${WORK_DIR}/k6-again.json" '.result == "held"' 6 "${GUEST_NAME}" "${GUEST_PW}" --hold 2 --timeout "${SESSION_TIMEOUT}"

COLUMNS=$(sql "PRAGMA table_info(time_usage)" | cut -d'|' -f2 | paste -sd, -)
check "K6 Tabelle time_usage hat genau nc_user, day, seconds (ist ${COLUMNS:-leer})" eq "${COLUMNS}" "nc_user,day,seconds"
sql "SELECT * FROM time_usage" >"${WORK_DIR}/usage.rows"
check "K6 jede Zeile in time_usage ist nur Konto, Datum, Sekunden" \
	sh -c '[ "$(grep -c -v -E "^[A-Za-z0-9_.@-]{1,64}\|[0-9]{4}-[0-9]{2}-[0-9]{2}\|[0-9]+$" "$1" || true)" = 0 ]' _ "${WORK_DIR}/usage.rows"
DB_ALL="${WORK_DIR}/db-all.bin"
cat "${DB_FILE}" "${DB_FILE}-wal" >"${DB_ALL}" 2>/dev/null || cat "${DB_FILE}" >"${DB_ALL}"
PW_HITS=$(hits_in "${KID_PW}" "${DB_ALL}")
check "K6 Passwort von ${KID} steht nicht in der SQLite-Datei (Treffer ${PW_HITS})" eq "${PW_HITS}" 0
NAME_HITS=$(hits_in "${KID_NAME}" "${DB_ALL}")
check "K6 Positivkontrolle: dasselbe grep findet den Spielernamen (Treffer ${NAME_HITS})" test "${NAME_HITS}" -gt 0

printf '\n== Aufräumen ==\n'
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" /dev/null)
check "Aufräumen DELETE '${NAME_WORLD}' HTTP 204 (ist ${CODE})" eq "${CODE}" 204
reset_fixtures
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt-end.json" >/dev/null
check "Aufräumen ${KID} ohne Regeln" \
	sh -c '[ "$(jq -r --arg u "$2" "[.children[]? | select(.nc_user == \$u and .has_rules)] | length" "$1")" = 0 ]' _ \
	"${WORK_DIR}/pt-end.json" "${KID}"
check "Aufräumen keine Ferien '${HOLIDAY_LABEL}' übrig" \
	eq "$(jq -r --arg l "${HOLIDAY_LABEL}" '[.holidays[]? | select(.label == $l)] | length' "${WORK_DIR}/pt-end.json" 2>/dev/null)" 0
check "Aufräumen Zeitzone Europe/Berlin" eq "$(jq -r '.time_zone' "${WORK_DIR}/pt-end.json" 2>/dev/null)" Europe/Berlin
check "Aufräumen keine Verbrauchszeile für ${KID}" eq "$(sql "SELECT count(*) FROM time_usage WHERE nc_user = '${KID}'")" 0
check "Aufräumen Konto ${GUEST} gelöscht" user_absent "${GUEST}"
check "Positivkontrolle: dieselbe Abfrage erkennt das vorhandene Konto ${KID}" user_present "${KID}"
check "Aufräumen ${KID} nicht in admin" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${KID}" '(.admin // []) | index($u) // "nein"')" nein
LEFT=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | wc -l | tr -d ' ')
check "keine Welt-Container übrig (ist ${LEFT})" eq "${LEFT}" 0

printf '\n== Regression Phase 1 bis 3 ==\n'
# Nur für schnelle Iterationen: übersprungene Regression zählt als Fehlschlag.
if [ "${GAMEWORLD_SKIP_REGRESSION:-0}" = 1 ]; then
	fail "Regression übersprungen (GAMEWORLD_SKIP_REGRESSION=1), keine Phasenabnahme"
	printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
	exit 1
fi
# acceptance-phase3.sh ruft acceptance-phase1.sh und acceptance-phase2.sh selbst auf.
if sh "${PHASE3_SCRIPT}" >"${WORK_DIR}/phase3.log" 2>&1; then
	pass "Regression: acceptance-phase3.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase3.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase3.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase3.log" >&2 || tail -n 20 "${WORK_DIR}/phase3.log" >&2
fi
for expected in "84 von 84 Prüfungen bestanden" "104 von 104 Prüfungen bestanden" "75 von 75 Prüfungen bestanden"; do
	# Nur die Summenzeile oder eine bestanden-Zeile zählt, nie ein Zitat in einer FEHLGESCHLAGEN-Zeile.
	check "Regression: Log enthält '${expected}'" awk -v e="${expected}" \
		'$0 == e || (index($0, "bestanden: ") == 1 && index($0, e) > 0) { found = 1 } END { exit !found }' \
		"${WORK_DIR}/phase3.log"
done

printf '\n== ExApp über den ganzen Lauf erreichbar ==\n'
# Die geplanten Neustarts (Phase 4 K6, Phase 3 K5, Phase 2 K4a/K4b) machen keine
# API-Aufrufe, solange das Backend fehlt. Ein Eintrag hier heißt: Das Backend war
# ungeplant weg, und jede 500 der Abnahme in dieser Zeit ist eine Folge davon.
nc_log_lines "${CONNECT_ERROR}" >"${WORK_DIR}/nc-connect.log"
CONNECT_ERRORS=$(entries_since "${RUN_START}" "${WORK_DIR}/nc-connect.log")
if [ "${CONNECT_ERRORS}" = 0 ]; then
	pass "keine AppAPI-Verbindungsfehler zur ExApp seit Laufbeginn (ist 0)"
else
	fail "AppAPI erreichte die ExApp ${CONNECT_ERRORS}-mal nicht (Backend ungeplant weg; Logs der Backends in .dev/logs)"
fi
# Probedatei: ein Eintrag jetzt, einer vor Laufbeginn, einer mit anderem Text; zählen darf nur der erste.
for stamp_text in "$(date -u +%Y-%m-%dT%H:%M:%S)|${CONNECT_ERROR}" "2000-01-01T00:00:00|${CONNECT_ERROR}" \
	"$(date -u +%Y-%m-%dT%H:%M:%S)|Could not resolve host"; do
	printf '{"time":"%s+00:00","app":"app_api","message":"Error during request to ExApp gameworld: cURL error 7: %s"}\n' \
		"${stamp_text%%|*}" "${stamp_text#*|}"
done >"${WORK_DIR}/nc-probe.log"
grep -F -- "${CONNECT_ERROR}" "${WORK_DIR}/nc-probe.log" >"${WORK_DIR}/nc-probe-hits.log" || true
check "Positivkontrolle: dieselbe Zählung findet in einer Probedatei genau den einen Eintrag seit Laufbeginn" \
	eq "$(entries_since "${RUN_START}" "${WORK_DIR}/nc-probe-hits.log")" 1

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 4 erfolgreich\n'
