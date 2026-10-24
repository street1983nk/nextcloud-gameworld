#!/bin/sh
# Phasenabnahme Phase 5: prüft die drei Erfolgskriterien aus .planning/ROADMAP.md
# (Sicherung und Wiederherstellung) gegen den laufenden Dev-Stack mit echter
# Nextcloud 34.0.3, laufender ExApp (keine Fakes, echte Files-Ablage per WebDAV im
# Namen des Verwalters) und echtem Docker. Am Ende ruft es die Abnahme von Phase 4.1
# als Regression (sie ruft Phase 4 bis 1 selbst auf).
#
#   K1 Cold-Backup: Sichern trennt spielende Kinder nur nach Bestätigung, der
#      Welt-Container wird gestoppt, gesichert und wieder gestartet.
#   K2 Die Sicherung liegt in Nextcloud Files unter Gameworld/Sicherungen/<Welt>/
#      mit Namen <weltname>-JJJJ-MM-TT-HHMM.tar.gz, enthält die SQLite-Welt
#      (world.mt: backend = sqlite3) ohne Laufzeitdateien der eigenen Mods, und
#      ein zweiter Verwalter sieht sie nicht (D-13).
#   K3 Restore-Roundtrip: Mia vor der Sicherung, Leo danach, kaputte map.sqlite
#      plus Journal; nach dem Wiederherstellen ist Mia da, Leo weg, die Karte heil,
#      und die vor-restore-Sicherung liegt daneben.
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen aus der docker-CLI
# (inspect, events, cp), aus curl gegen den AppAPI-Proxy und gegen WebDAV
# (PROPFIND, GET) mit echten Nextcloud-Konten, aus jq, tar und grep. SQLite-Dateien
# liest die Python-Standardbibliothek nur lesend (mode=ro). Einziges Python-Werkzeug
# des Projekts ist der Session-Prober (tests/e2e/luanti_probe.py) über seine CLI.
#
# Spieler: Mia und Leo sind die realen Dev-Konten gw-kind (Mia-Rolle) und gw-kind2
# (Leo-Rolle, Wegwerfkonto dieses Laufs). Die Einladungen legt das Skript per API
# an; Spielname und Spielpasswort kommen aus der Einladungs-Antwort
# (GET /players) und erscheinen nie in der Ausgabe, nur ihre Länge.
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   sh scripts/dev/register-exapp.sh
#   (für die Regression zusätzlich Talk, siehe docs/dev-setup.md)
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Ein trap räumt in jedem Fall auf:
# Abnahme-Welt (Lösch-API, Fallback docker rm -f -v), die Abnahme-Dateien in den
# Files von admin (WebDAV DELETE nur auf Namen, die dem Abnahme-Muster entsprechen,
# der Ordner nur, wenn er danach leer ist), Wegwerfkonten gw-kind2 und gw-admin2,
# gw-kind nie in admin. gw-kind selbst bleibt bestehen.
#
# Fremde Welt-Container (andere ExApp-Instanzen, Testreste anderer Sitzungen)
# bleiben unangetastet; die Prüfung auf übrig gebliebene Container zählt nur, was
# dieser Lauf neu hinterlassen hätte (Grundlinie beim Start).
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
PHASE41_SCRIPT="${SCRIPT_DIR}/acceptance-phase4_1.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
MIA=gw-kind
LEO=gw-kind2
LEO_PASS=gw-kind2-dev-pass-1
ADMIN2=gw-admin2
ADMIN2_PASS=gw-admin2-dev-pass-1
ADMIN2_AUTH="${ADMIN2}:${ADMIN2_PASS}"
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
BACKEND_PORT=10040
PROBE_HOST=127.0.0.1
WORLD_NAME="Abnahme Sicherung"
# Ordner und Dateinamen nach D-01/D-02 (eigene Literale, nicht aus dem Code).
DAV_FOLDER="${NEXTCLOUD_URL}/remote.php/dav/files/admin/Gameworld/Sicherungen/Abnahme%20Sicherung"
BACKUP_RE='^Abnahme Sicherung-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}\.tar\.gz$'
VOR_RESTORE_RE='^Abnahme Sicherung-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}-vor-restore\.tar\.gz$'
# Nur diese Namen darf das Skript in den Files von admin löschen (T-05-43).
OWN_FILE_RE='^Abnahme Sicherung-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{4}(-vor-restore)?(-[0-9]+)?\.tar\.gz$'
WORLD_PATH=/var/lib/minetest/.minetest/worlds/world
# Elterntext aus backup/service.py (Teilstring) und Kindertext des Halts.
TEXT_DISCONNECT="kurz getrennt"
TEXT_HALT="Die Welt macht kurz Pause"
TEXT_HALT_SOON="Die Welt macht gleich eine kurze Pause."
JOB_WAIT=240
SESSION_TIMEOUT=30

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
MIA_JOB=""
WORK_DIR=$(mktemp -d)
BASELINE_CONTAINERS=""

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

# add_user KONTO PASSWORT ANZEIGENAME -> Wegwerfkonto frisch anlegen (Muster acceptance-phase4_1.sh)
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

# call AUTH METHODE URL AUSGABE [JSON] -> HTTP-Code
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

# WebDAV ---------------------------------------------------------------------

# dav_list URL DATEI -> HTTP-Code; die Dateinamen (dekodiert, ohne Ordner) landen zeilenweise in DATEI
dav_list() {
	list_code=$(curl -s -u "${ADMIN_AUTH}" -X PROPFIND -H 'Depth: 1' -o "${WORK_DIR}/propfind.xml" \
		-w '%{http_code}' "$1/" 2>/dev/null || printf '000')
	: >"$2"
	if [ "${list_code}" = 207 ]; then
		for href in $(grep -o '<d:href>[^<]*</d:href>' "${WORK_DIR}/propfind.xml" | sed 's#<d:href>##; s#</d:href>##'); do
			case "${href}" in
			*/) continue ;;
			esac
			encoded=${href##*/}
			printf '%b\n' "$(printf '%s' "${encoded}" | sed 's/%/\\x/g')" >>"$2"
		done
	fi
	printf '%s' "${list_code}"
}

# dav_url NAME -> URL der Datei im Abnahme-Ordner (nur Leerzeichen kommen im Namen vor)
dav_url() {
	printf '%s/%s' "${DAV_FOLDER}" "$(printf '%s' "$1" | sed 's/ /%20/g')"
}

# dav_delete_own NAME -> löscht nur Namen nach OWN_FILE_RE (T-05-43)
dav_delete_own() {
	printf '%s' "$1" | grep -Eq "${OWN_FILE_RE}" || return 1
	curl -s -u "${ADMIN_AUTH}" -X DELETE -o /dev/null "$(dav_url "$1")" >/dev/null 2>&1 || true
}

# Räumt die eigenen Abnahme-Dateien im Ordner weg; der Ordner selbst nur, wenn er danach leer ist.
dav_cleanup() {
	[ "$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav-clean.txt")" = 207 ] || return 0
	while IFS= read -r name; do
		[ -n "${name}" ] && dav_delete_own "${name}" || true
	done <"${WORK_DIR}/dav-clean.txt"
	if [ "$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav-clean.txt")" = 207 ] && [ ! -s "${WORK_DIR}/dav-clean.txt" ]; then
		curl -s -u "${ADMIN_AUTH}" -X DELETE -o /dev/null "${DAV_FOLDER}/" >/dev/null 2>&1 || true
	fi
}

# SQLite nur lesend über die Standardbibliothek ---------------------------------

# sqlite_ro DATEI SQL -> Zeilen mit | getrennt; Exit ungleich 0, wenn die Datei keine SQLite-Datei ist
sqlite_ro() {
	db_path=$1
	command -v cygpath >/dev/null 2>&1 && db_path=$(cygpath -w "$1")
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
for row in con.execute(sys.argv[2]):
    print("|".join("" if v is None else str(v) for v in row))
' "${db_path}" "$2") 2>/dev/null | tr -d '\r'
}

has_player() {
	[ "$(sqlite_ro "$1" "SELECT count(*) FROM player WHERE name = '$2'")" = 1 ]
}

integrity_ok() {
	[ "$(sqlite_ro "$1" "PRAGMA integrity_check" | head -n 1)" = ok ]
}

# Docker -----------------------------------------------------------------------

container_of() {
	docker ps -aq --no-trunc --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1"
}

started_at() {
	docker inspect --format '{{.State.StartedAt}}' "$1" 2>/dev/null | tr -d '\r' || true
}

# copy_out CONTAINER DATEI ZIELORDNER -> 0, wenn die Datei aus dem Weltordner kam
copy_out() {
	rm -f "$3/$2"
	# MSYS_NO_PATHCONV: Git Bash würde den Containerpfad sonst umschreiben.
	MSYS_NO_PATHCONV=1 docker cp "$1:${WORLD_PATH}/$2" - >"${WORK_DIR}/cp.tar" 2>/dev/null || return 1
	tar -xf "${WORK_DIR}/cp.tar" -C "$3" 2>/dev/null || return 1
	[ -f "$3/$2" ]
}

# API-Helfer -------------------------------------------------------------------

world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

# Fristen zählen echte Sekunden (date), nicht Schleifenrunden: ein Abruf über den
# AppAPI-Proxy dauert am Dev-Stack bis zu 5 s.
deadline() { printf '%s' "$(($(date +%s) + $1))"; }
before() { [ "$(date +%s)" -lt "$1" ]; }

wait_status() {
	until_ts=$(deadline "$3")
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		before "${until_ts}" || return 1
		sleep 1
	done
}

# wait_job WELT ART SEKUNDEN -> 0, sobald backup_job dieser Art fertig ist (ok oder failed);
# der Zustand steht danach in JOB_STATE, jeder beobachtete Weltstatus in BUSY_SEEN.
wait_job() {
	until_ts=$(deadline "$3")
	JOB_STATE=""
	while :; do
		JOB_STATE=$(world_field "$1" "if .backup_job.kind == \"$2\" then .backup_job.state else \"\" end")
		seen=$(jq -r --arg id "$1" '.worlds[]? | select(.id == $id) | .status' "${WORK_DIR}/field.json" 2>/dev/null || true)
		case " ${BUSY_SEEN} " in
		*" ${seen} "*) ;;
		*) BUSY_SEEN="${BUSY_SEEN} ${seen}" ;;
		esac
		case "${JOB_STATE}" in
		ok | failed) return 0 ;;
		esac
		before "${until_ts}" || return 1
		sleep 2
	done
}

player_field() {
	jq -r --arg u "$2" ".players[]? | select(.nc_user == \$u) | .$3 // empty" "$1" 2>/dev/null || true
}

probe() {
	out=$1
	shift
	(cd "${REPO_ROOT}" && uv run python -m tests.e2e.luanti_probe "${PROBE_HOST}" "${PORT}" "$@") \
		>"${out}" 2>"${out}.err" || printf '{"result":"prober_error"}' >"${out}"
}

probe_expect() {
	out=$1
	condition=$2
	limit=$3
	shift 3
	until_ts=$(deadline "${limit}")
	while :; do
		probe "${out}" "$@"
		[ "$(jq -r "${condition}" "${out}" 2>/dev/null || printf 'false')" = "true" ] && return 0
		before "${until_ts}" || return 1
		sleep 2
	done
}

probe_summary() {
	jq -r '"\(.result) \(.code // "") \(.reason // "") \(.after_s // "")"' "$1" 2>/dev/null || printf 'nicht lesbar'
}

# wait_online WELT SPIELERNAME SEKUNDEN -> 0, sobald die Weltenliste den Namen unter players führt
wait_online() {
	until_ts=$(deadline "$3")
	while :; do
		[ "$(world_field "$1" "(.players // []) | index(\"$2\") != null")" = true ] && return 0
		before "${until_ts}" || return 1
		sleep 2
	done
}

eq() { [ "$1" = "$2" ]; }
not() { ! "$@"; }
# not_grep MUSTER DATEI -> 0, wenn DATEI lesbar ist und keine Zeile auf MUSTER passt
not_grep() { [ -s "$2" ] && ! grep -Eq "$1" "$2"; }
matches() { printf '%s' "$1" | grep -Eq "$2"; }
user_present() { occ user:info "$1" >/dev/null 2>&1; }
user_absent() { ! user_present "$1"; }

# new_containers -> Anzahl Welt-Container, die beim Start noch nicht da waren
new_containers() {
	count=0
	for cid in $(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null); do
		case " ${BASELINE_CONTAINERS} " in
		*" ${cid} "*) ;;
		*) count=$((count + 1)) ;;
		esac
	done
	printf '%s' "${count}"
}

reset_fixtures() {
	occ group:removeuser admin "${MIA}" >/dev/null 2>&1 || true
	occ user:delete "${LEO}" >/dev/null 2>&1 || true
	occ user:delete "${ADMIN2}" >/dev/null 2>&1 || true
}

cleanup() {
	status=$?
	[ -n "${MIA_JOB}" ] && kill "${MIA_JOB}" 2>/dev/null || true
	for world_id in ${WORLD_IDS}; do
		delete_world_hard "${world_id}"
	done
	dav_cleanup || true
	reset_fixtures
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq grep sed awk tar uv; do
	command -v "${tool}" >/dev/null 2>&1 || abort "Werkzeug ${tool} fehlt"
done
if ! curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
	abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
occ app_api:app:list 2>/dev/null | grep -q '^gameworld ' || abort "Gameworld ist nicht registriert. Zuerst: sh scripts/dev/register-exapp.sh"
heartbeat_up || abort "ExApp antwortet nicht auf Port ${BACKEND_PORT}. Zuerst: sh scripts/dev/register-exapp.sh"
user_present "${MIA}" || abort "Konto ${MIA} fehlt (legt acceptance-phase1.sh an)"
NC_VERSION=$(curl -s "${NEXTCLOUD_URL}/status.php" | jq -r '.versionstring // empty' 2>/dev/null || true)
printf 'Nextcloud %s unter %s\n' "${NC_VERSION:-unbekannt}" "${NEXTCLOUD_URL}"
BASELINE_CONTAINERS=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | tr '\n' ' ')

printf '\n== Vorbereitung ==\n'
reset_fixtures
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --arg n "${WORLD_NAME}" '.worlds[]? | select(.name == $n) | .id' "${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	delete_world_hard "${old_id}"
done
BASELINE_CONTAINERS=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | tr '\n' ' ')
dav_cleanup
CODE=$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav-pre.txt")
check "Vorbereitung: keine Abnahme-Datei aus einem früheren Lauf in den Files von admin (PROPFIND ${CODE})" \
	sh -c '[ "$1" = 404 ] || { [ "$1" = 207 ] && ! grep -Eq "$3" "$2"; }' _ "${CODE}" "${WORK_DIR}/dav-pre.txt" "${OWN_FILE_RE}"
CODE=$(dav_list "${NEXTCLOUD_URL}/remote.php/dav/files/admin/Gameworld/Sicherungen/gibt-es-nicht-p5" "${WORK_DIR}/dav-none.txt")
check "Positivkontrolle: PROPFIND unterscheidet, ein fehlender Ordner ist 404 (ist ${CODE})" eq "${CODE}" 404
CODE=$(dav_list "${NEXTCLOUD_URL}/remote.php/dav/files/admin" "${WORK_DIR}/dav-root.txt")
check "Positivkontrolle: PROPFIND auf die Files-Wurzel von admin 207 mit Einträgen (ist ${CODE})" \
	sh -c '[ "$1" = 207 ] && [ -s "$2" ]' _ "${CODE}" "${WORK_DIR}/dav-root.txt"

add_user "${LEO}" "${LEO_PASS}" "Leo Abnahme" || abort "Konto ${LEO} ließ sich nicht anlegen (occ-Ausgabe oben)"
add_user "${ADMIN2}" "${ADMIN2_PASS}" "Verwalter Zwei" || abort "Konto ${ADMIN2} ließ sich nicht anlegen (occ-Ausgabe oben)"
occ group:adduser admin "${ADMIN2}" >/dev/null 2>&1 || abort "${ADMIN2} ließ sich nicht in admin aufnehmen"
check "zweites Verwalter-Konto ${ADMIN2} in Gruppe admin" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${ADMIN2}" '(.admin // []) | index($u) != null')" true
check "${MIA} ist kein Verwalter" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${MIA}" '(.admin // []) | index($u) != null')" false

CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/world.json" "{\"name\":\"${WORLD_NAME}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/world.json" 2>/dev/null || true)
remember_world "${WORLD_ID}"
check "POST '${WORLD_NAME}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
matches "${WORLD_ID}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
check "Welt running binnen 60 s" wait_status "${WORLD_ID}" running 60
CONTAINER=$(container_of "${WORLD_ID}")
[ -n "${CONTAINER}" ] || abort "kein Container mit Label gameworld.world_id"
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
matches "${PORT}" '^[0-9]+$' || abort "kein UDP-Port"
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv.json" "{\"kind\":\"user\",\"target\":\"${MIA}\"}")
check "POST invites ${MIA} (Mia) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "${WORK_DIR}/players.json" >/dev/null
MIA_NAME=$(player_field "${WORK_DIR}/players.json" "${MIA}" player_name)
MIA_PW=$(player_field "${WORK_DIR}/players.json" "${MIA}" password)
check "Mia: Spielname ${MIA_NAME:-leer}, Passwort vorhanden (Länge ${#MIA_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ]' _ "${MIA_NAME}" "${MIA_PW}"
check "Positivkontrolle: Mia kommt hinein (auth_accept)" \
	probe_expect "${WORK_DIR}/mia-pre.json" '.result == "auth_accept"' 20 "${MIA_NAME}" "${MIA_PW}"
sleep 2.5

printf '\n== K1 Cold-Backup ==\n'
printf 'Sitzung Mia für bis zu 120 s\n'
probe "${WORK_DIR}/k1-mia.json" "${MIA_NAME}" "${MIA_PW}" --hold 120 --timeout "${SESSION_TIMEOUT}" &
MIA_JOB=$!
check "K1 Mia ist laut Weltenliste online (binnen 30 s)" wait_online "${WORLD_ID}" "${MIA_NAME}" 30
STARTED_BEFORE=$(started_at "${CONTAINER}")
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/b-noconfirm.json" '{}')
check "K1 Negativkontrolle: Sichern ohne Bestätigung, während Mia spielt, HTTP 409 (ist ${CODE})" eq "${CODE}" 409
check "K1 409-Text nennt '${TEXT_DISCONNECT}' ($(jq -r '.detail // empty' "${WORK_DIR}/b-noconfirm.json" 2>/dev/null))" \
	eq "$(jq -r --arg t "${TEXT_DISCONNECT}" '(.detail // "") | contains($t)' "${WORK_DIR}/b-noconfirm.json" 2>/dev/null)" true
sleep 2
check "K1 Negativkontrolle: Container nach dem 409 unverändert gelaufen (StartedAt gleich)" \
	sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ "${STARTED_BEFORE}" "$(started_at "${CONTAINER}")"
check "K1 Negativkontrolle: Mia nach dem 409 weiter online" wait_online "${WORLD_ID}" "${MIA_NAME}" 4
CODE=$(http_code GET "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/list0.json")
check "K1 Negativkontrolle: nach dem 409 keine Sicherung in der Liste (HTTP ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r ".backups | length" "$2")" = 0 ]' _ "${CODE}" "${WORK_DIR}/list0.json"

EVENTS_SINCE=$(($(date +%s) - 5))
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/b-start.json" '{"confirm_disconnect":true}')
check "K1 Sichern mit Bestätigung HTTP 202 (ist ${CODE})" eq "${CODE}" 202
check "K1 Antwort zeigt backup_job backup running" \
	eq "$(jq -r '.backup_job.kind == "backup" and .backup_job.state == "running"' "${WORK_DIR}/b-start.json" 2>/dev/null)" true
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/b-twice.json" '{"confirm_disconnect":true}')
check "K1 Negativkontrolle: zweiter Auftrag während des laufenden HTTP 409 (ist ${CODE})" eq "${CODE}" 409
BUSY_SEEN=""
check "K1 Auftrag fertig binnen ${JOB_WAIT} s" wait_job "${WORLD_ID}" backup "${JOB_WAIT}"
check "K1 backup_job.state ok (ist ${JOB_STATE:-leer}, $(world_field "${WORLD_ID}" '.backup_job.message // ""'))" eq "${JOB_STATE}" ok
printf 'beobachtete Weltstatus während der Sicherung:%s\n' "${BUSY_SEEN}"
check "K1 Welt läuft danach wieder (running binnen 60 s)" wait_status "${WORLD_ID}" running 60
EVENTS_UNTIL=$(($(date +%s) + 2))
CONTAINER_AFTER=$(container_of "${WORLD_ID}")
check "K1 derselbe Container (Sicherung baut nichts neu)" eq "${CONTAINER_AFTER}" "${CONTAINER}"
STARTED_AFTER=$(started_at "${CONTAINER}")
check "K1 Container neu gestartet (StartedAt ${STARTED_BEFORE} -> ${STARTED_AFTER})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ] && [ "$1" != "$2" ]' _ "${STARTED_BEFORE}" "${STARTED_AFTER}"
docker events --since "${EVENTS_SINCE}" --until "${EVENTS_UNTIL}" --filter "container=${CONTAINER}" \
	--format '{{.Action}}' >"${WORK_DIR}/events.txt" 2>/dev/null || true
printf 'Docker-Ereignisse: %s\n' "$(tr -d '\r' <"${WORK_DIR}/events.txt" | tr '\n' ' ')"
check "K1 docker events: Container gestoppt (die) und danach wieder gestartet (start)" \
	awk '{ sub(/\r$/, "") } $0 == "die" { died = NR } $0 == "start" && died { started = 1 } END { exit !started }' \
	"${WORK_DIR}/events.txt"
check "K1 docker events: Weltdaten bei gestopptem Container gelesen (archive-path zwischen die und start)" \
	awk '{ sub(/\r$/, "") } $0 == "die" { died = 1 } $0 ~ /^archive-path/ && died { read = 1 } $0 == "start" && read { ok = 1 } END { exit !ok }' \
	"${WORK_DIR}/events.txt"
wait "${MIA_JOB}" || true
MIA_JOB=""
printf 'Mia: %s\n' "$(probe_summary "${WORK_DIR}/k1-mia.json")"
check "K1 Mia wurde getrennt (kicked) mit '${TEXT_HALT}'" \
	eq "$(jq -r --arg t "${TEXT_HALT}" '.result == "kicked" and ((.reason // "") | contains($t))' "${WORK_DIR}/k1-mia.json" 2>/dev/null)" true
check "K1 vorher Chat '${TEXT_HALT_SOON}'" \
	eq "$(jq -r --arg t "${TEXT_HALT_SOON}" '[.events[]? | select(.kind == "chat" and (.text | contains($t)))] | length > 0' \
		"${WORK_DIR}/k1-mia.json" 2>/dev/null)" true
BACKUP_FILE=$(world_field "${WORLD_ID}" '.backup_job.file_name // ""')
check "K1 backup_job.file_name nach D-02 (ist ${BACKUP_FILE:-leer})" matches "${BACKUP_FILE}" "${BACKUP_RE}"

printf '\n== K2 Datei in Nextcloud Files, SQLite-Welt, D-13 ==\n'
CODE=$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav1.txt")
printf 'PROPFIND %s: %s\n' "${CODE}" "$(tr '\n' ';' <"${WORK_DIR}/dav1.txt")"
check "K2 PROPFIND Gameworld/Sicherungen/${WORLD_NAME}/ HTTP 207 (ist ${CODE})" eq "${CODE}" 207
check "K2 genau eine Datei im Ordner, Name nach Muster <weltname>-JJJJ-MM-TT-HHMM.tar.gz" sh -c \
	'[ "$(grep -c . "$1")" = 1 ] && grep -Eq "$2" "$1"' _ "${WORK_DIR}/dav1.txt" "${BACKUP_RE}"
check "K2 Dateiname in Files gleich backup_job.file_name (nicht leer)" 	sh -c '[ -n "$2" ] && [ "$1" = "$2" ]' _ "$(head -n 1 "${WORK_DIR}/dav1.txt")" "${BACKUP_FILE}"
CODE=$(curl -s -u "${ADMIN_AUTH}" -o "${WORK_DIR}/backup.tar.gz" -w '%{http_code}' "$(dav_url "${BACKUP_FILE}")" 2>/dev/null || printf '000')
check "K2 GET der Sicherung per WebDAV HTTP 200 (ist ${CODE})" eq "${CODE}" 200
tar -tzf "${WORK_DIR}/backup.tar.gz" >"${WORK_DIR}/backup.list" 2>/dev/null || : >"${WORK_DIR}/backup.list"
printf 'Archiv: %s Einträge\n' "$(grep -c . "${WORK_DIR}/backup.list" || true)"
check "K2 tar -tzf: gameworld-backup.json an der Wurzel" grep -Eq '^(\./)?gameworld-backup\.json$' "${WORK_DIR}/backup.list"
check "K2 tar -tzf: world/map.sqlite" grep -Eq '^(\./)?world/map\.sqlite$' "${WORK_DIR}/backup.list"
check "K2 tar -tzf: kein gameworld_access.txt" not_grep 'gameworld_access\.txt' "${WORK_DIR}/backup.list"
check "K2 tar -tzf: kein worldmods/" not_grep '(^|/)worldmods(/|$)' "${WORK_DIR}/backup.list"
check "K2 tar -tzf: keine gameworld_-Laufzeitdatei" not_grep '(^|/)gameworld_[^/]*$' "${WORK_DIR}/backup.list"
mkdir -p "${WORK_DIR}/b1"
tar -xzf "${WORK_DIR}/backup.tar.gz" -C "${WORK_DIR}/b1" 2>/dev/null || true
check "K2 world/world.mt enthält backend = sqlite3 (Erfolgskriterium 2)" \
	grep -Eq '^backend *= *sqlite3' "${WORK_DIR}/b1/world/world.mt"
check "K2 world/map.sqlite der Sicherung: integrity_check ok (sqlite3 lesend)" integrity_ok "${WORK_DIR}/b1/world/map.sqlite"
BLOCKS_BACKUP=$(sqlite_ro "${WORK_DIR}/b1/world/map.sqlite" "SELECT count(*) FROM blocks")
check "K2 world/map.sqlite der Sicherung hat Blöcke (ist ${BLOCKS_BACKUP:-leer})" \
	sh -c 'printf "%s" "$1" | grep -Eq "^[0-9]+$" && [ "$1" -gt 0 ]' _ "${BLOCKS_BACKUP}"
check "K2 Mia steht in world/players.sqlite der Sicherung" has_player "${WORK_DIR}/b1/world/players.sqlite" "${MIA_NAME}"
check "K2 Manifest ist JSON und nennt die Welt-ID" \
	eq "$(jq -r '.world_id' "${WORK_DIR}/b1/gameworld-backup.json" 2>/dev/null)" "${WORLD_ID}"
FILE_SIZE=$(wc -c <"${WORK_DIR}/backup.tar.gz" | tr -d ' ')
CODE=$(http_code GET "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/list1.json")
check "K2 GET backups als admin HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 Liste: genau ein Eintrag kind backup mit Name ${BACKUP_FILE} und Größe ${FILE_SIZE}" \
	eq "$(jq -r --arg n "${BACKUP_FILE}" --argjson s "${FILE_SIZE}" \
		'(.backups | length) == 1 and .backups[0].name == $n and .backups[0].kind == "backup" and .backups[0].size == $s' \
		"${WORK_DIR}/list1.json" 2>/dev/null)" true
check "K2 Liste: total_size gleich der Dateigröße (ist $(jq -r '.total_size' "${WORK_DIR}/list1.json" 2>/dev/null))" \
	eq "$(jq -r '.total_size' "${WORK_DIR}/list1.json" 2>/dev/null)" "${FILE_SIZE}"
FILE_ID=$(jq -r '.backups[0].file_id // empty' "${WORK_DIR}/list1.json" 2>/dev/null || true)
check "K2 file_id ist eine Zahl (ist ${FILE_ID:-leer})" matches "${FILE_ID}" '^[0-9]+$'

# D-13: Positivkontrolle, dass gw-admin2 wirklich Verwalter ist und die Welt sieht.
CODE=$(call "${ADMIN2_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/a2-worlds.json")
check "K2 Positivkontrolle: ${ADMIN2} ist Verwalter, GET /api/worlds HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 Positivkontrolle: ${ADMIN2} sieht die Welt '${WORLD_NAME}'" \
	eq "$(jq -r --arg id "${WORLD_ID}" '[.worlds[]? | select(.id == $id)] | length' "${WORK_DIR}/a2-worlds.json" 2>/dev/null)" 1
CODE=$(call "${ADMIN2_AUTH}" GET "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/a2-list.json")
check "K2 D-13: GET backups als ${ADMIN2} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 D-13: ${ADMIN2} sieht keine Sicherung von admin (backups leer, total_size 0)" \
	eq "$(jq -r '(.backups | type) == "array" and (.backups | length) == 0 and .total_size == 0' "${WORK_DIR}/a2-list.json" 2>/dev/null)" true
CODE=$(call "${ADMIN2_AUTH}" POST "${API_URL}/worlds/${WORLD_ID}/restore" "${WORK_DIR}/a2-restore.json" \
	"{\"file_id\":${FILE_ID:-0},\"confirm\":true}")
check "K2 D-13: ${ADMIN2} kann die Sicherung von admin nicht wiederherstellen, HTTP 404 (ist ${CODE})" eq "${CODE}" 404

printf '\n== K3 Restore-Roundtrip ==\n'
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv2.json" "{\"kind\":\"user\",\"target\":\"${LEO}\"}")
check "K3 POST invites ${LEO} (Leo) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "${WORK_DIR}/players2.json" >/dev/null
LEO_NAME=$(player_field "${WORK_DIR}/players2.json" "${LEO}" player_name)
LEO_PW=$(player_field "${WORK_DIR}/players2.json" "${LEO}" password)
check "Leo: Spielname ${LEO_NAME:-leer}, Passwort vorhanden (Länge ${#LEO_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ] && [ "$1" != "$3" ]' _ "${LEO_NAME}" "${LEO_PW}" "${MIA_NAME}"
probe_expect "${WORK_DIR}/leo-pre.json" '.result == "auth_accept"' 20 "${LEO_NAME}" "${LEO_PW}" || true
sleep 2.5
probe "${WORK_DIR}/k3-leo.json" "${LEO_NAME}" "${LEO_PW}" --hold 8 --timeout "${SESSION_TIMEOUT}"
check "K3 Leo spielt nach der Sicherung (held, $(probe_summary "${WORK_DIR}/k3-leo.json"))" \
	eq "$(jq -r '.result' "${WORK_DIR}/k3-leo.json" 2>/dev/null)" held
sleep 3
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/stop" /dev/null)
check "K3 Welt stoppen HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 Welt stopped binnen 60 s" wait_status "${WORLD_ID}" stopped 60
mkdir -p "${WORK_DIR}/pre"
check "K3 Positivkontrolle: players.sqlite per docker cp gelesen" copy_out "${CONTAINER}" players.sqlite "${WORK_DIR}/pre"
check "K3 Positivkontrolle: Leo steht vor dem Wiederherstellen in players.sqlite" \
	has_player "${WORK_DIR}/pre/players.sqlite" "${LEO_NAME}"
check "K3 Positivkontrolle: Mia steht vor dem Wiederherstellen in players.sqlite" \
	has_player "${WORK_DIR}/pre/players.sqlite" "${MIA_NAME}"

# Weltkarte zerstören: Zufallsbytes als map.sqlite plus heißes Journal.
mkdir -p "${WORK_DIR}/broken"
head -c 65536 /dev/urandom >"${WORK_DIR}/broken/map.sqlite"
head -c 4096 /dev/urandom >"${WORK_DIR}/broken/map.sqlite-journal"
tar -cf "${WORK_DIR}/broken.tar" -C "${WORK_DIR}/broken" map.sqlite map.sqlite-journal
MSYS_NO_PATHCONV=1 docker cp - "${CONTAINER}:${WORLD_PATH}" <"${WORK_DIR}/broken.tar" >/dev/null 2>&1 \
	|| fail "K3 kaputte map.sqlite ließ sich nicht per docker cp ablegen"
mkdir -p "${WORK_DIR}/bad"
check "K3 Positivkontrolle: kaputtes Journal liegt in der Welt (docker cp)" copy_out "${CONTAINER}" map.sqlite-journal "${WORK_DIR}/bad"
copy_out "${CONTAINER}" map.sqlite "${WORK_DIR}/bad" || true
check "K3 Positivkontrolle: die Prüfung erkennt die kaputte map.sqlite (integrity_check nicht ok)" \
	not integrity_ok "${WORK_DIR}/bad/map.sqlite"

CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/restore" "${WORK_DIR}/r-noconfirm.json" "{\"file_id\":${FILE_ID:-0},\"confirm\":false}")
check "K3 Negativkontrolle: Wiederherstellen ohne confirm HTTP 409 (ist ${CODE})" eq "${CODE}" 409
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/restore" "${WORK_DIR}/r-unknown.json" '{"file_id":999999999,"confirm":true}')
check "K3 Negativkontrolle: file_id einer nicht existierenden Sicherung HTTP 404 (ist ${CODE})" eq "${CODE}" 404
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/restore" "${WORK_DIR}/r-string.json" "{\"file_id\":\"${FILE_ID:-0}\",\"confirm\":true}")
check "K3 Negativkontrolle: file_id als Text HTTP 422 (ist ${CODE})" eq "${CODE}" 422
check "K3 Negativkontrolle: nach den Ablehnungen derselbe Container, Welt weiter stopped" \
	sh -c '[ "$1" = "$2" ] && [ "$3" = stopped ]' _ "$(container_of "${WORLD_ID}")" "${CONTAINER}" \
	"$(world_field "${WORLD_ID}" '.status')"
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/restore" "${WORK_DIR}/r-start.json" "{\"file_id\":${FILE_ID:-0},\"confirm\":true}")
check "K3 Wiederherstellen mit confirm HTTP 202 (ist ${CODE})" eq "${CODE}" 202
check "K3 Antwort zeigt backup_job restore running" \
	eq "$(jq -r '.backup_job.kind == "restore" and .backup_job.state == "running"' "${WORK_DIR}/r-start.json" 2>/dev/null)" true
BUSY_SEEN=""
check "K3 Auftrag fertig binnen ${JOB_WAIT} s" wait_job "${WORLD_ID}" restore "${JOB_WAIT}"
check "K3 backup_job.state ok (ist ${JOB_STATE:-leer}, $(world_field "${WORLD_ID}" '.backup_job.message // ""'))" eq "${JOB_STATE}" ok
printf 'beobachtete Weltstatus während des Wiederherstellens:%s\n' "${BUSY_SEEN}"
# Die Welt war vor dem Wiederherstellen gestoppt; sie bleibt es, bis jemand sie startet.
STATUS_AFTER=$(world_field "${WORLD_ID}" '.status')
printf 'Status nach dem Wiederherstellen: %s\n' "${STATUS_AFTER}"
if [ "${STATUS_AFTER}" != running ]; then
	CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/start" /dev/null)
	check "K3 Welt starten HTTP 200 (ist ${CODE})" eq "${CODE}" 200
fi
check "K3 Welt läuft nach dem Wiederherstellen (running binnen 90 s)" wait_status "${WORLD_ID}" running 90
check "K3 Welt nicht delete_only" eq "$(world_field "${WORLD_ID}" '.delete_only')" false
CONTAINER=$(container_of "${WORLD_ID}")
[ -n "${CONTAINER}" ] || abort "nach dem Wiederherstellen kein Container"
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
check "K3 Mia kommt in die wiederhergestellte Welt (auth_accept)" \
	probe_expect "${WORK_DIR}/k3-mia.json" '.result == "auth_accept"' 30 "${MIA_NAME}" "${MIA_PW}"
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/stop" /dev/null)
check "K3 Welt für die Gegenprobe stoppen HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 Welt stopped binnen 60 s" wait_status "${WORLD_ID}" stopped 60
mkdir -p "${WORK_DIR}/post"
check "K3 players.sqlite per docker cp gelesen" copy_out "${CONTAINER}" players.sqlite "${WORK_DIR}/post"
check "K3 map.sqlite per docker cp gelesen" copy_out "${CONTAINER}" map.sqlite "${WORK_DIR}/post"
check "K3 Mia steht in players.sqlite (sqlite3 lesend)" has_player "${WORK_DIR}/post/players.sqlite" "${MIA_NAME}"
check "K3 Leo steht nicht mehr in players.sqlite" not has_player "${WORK_DIR}/post/players.sqlite" "${LEO_NAME}"
check "K3 Positivkontrolle: players.sqlite lesbar (Zeilen in player)" \
	sh -c 'printf "%s" "$1" | grep -Eq "^[1-9][0-9]*$"' _ "$(sqlite_ro "${WORK_DIR}/post/players.sqlite" 'SELECT count(*) FROM player')"
check "K3 map.sqlite integrity_check ok" integrity_ok "${WORK_DIR}/post/map.sqlite"
BLOCKS_AFTER=$(sqlite_ro "${WORK_DIR}/post/map.sqlite" "SELECT count(*) FROM blocks")
check "K3 map.sqlite hat Blöcke (ist ${BLOCKS_AFTER:-leer}, Sicherung ${BLOCKS_BACKUP:-leer})" \
	sh -c 'printf "%s" "$1" | grep -Eq "^[0-9]+$" && [ "$1" -gt 0 ]' _ "${BLOCKS_AFTER}"
check "K3 kein map.sqlite-journal in der Welt" not copy_out "${CONTAINER}" map.sqlite-journal "${WORK_DIR}/post"

CODE=$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav2.txt")
printf 'PROPFIND %s: %s\n' "${CODE}" "$(tr '\n' ';' <"${WORK_DIR}/dav2.txt")"
check "K3 PROPFIND HTTP 207 (ist ${CODE})" eq "${CODE}" 207
check "K3 Ordner: die Sicherung und genau eine vor-restore-Datei" sh -c \
	'[ "$(grep -c . "$1")" = 2 ] && grep -Fxq "$2" "$1" && [ "$(grep -Ec "$3" "$1")" = 1 ]' _ \
	"${WORK_DIR}/dav2.txt" "${BACKUP_FILE}" "${VOR_RESTORE_RE}"
VOR_FILE=$(grep -E "${VOR_RESTORE_RE}" "${WORK_DIR}/dav2.txt" | head -n 1 || true)
CODE=$(curl -s -u "${ADMIN_AUTH}" -o "${WORK_DIR}/vor.tar.gz" -w '%{http_code}' "$(dav_url "${VOR_FILE}")" 2>/dev/null || printf '000')
check "K3 GET der vor-restore-Datei HTTP 200 (ist ${CODE})" eq "${CODE}" 200
mkdir -p "${WORK_DIR}/vor"
tar -xzf "${WORK_DIR}/vor.tar.gz" -C "${WORK_DIR}/vor" 2>/dev/null || true
check "K3 vor-restore bewahrt den Stand davor: Leo in world/players.sqlite" \
	has_player "${WORK_DIR}/vor/world/players.sqlite" "${LEO_NAME}"
CODE=$(http_code GET "${API_URL}/worlds/${WORLD_ID}/backups" "${WORK_DIR}/list2.json")
check "K3 GET backups: zwei Einträge, einer kind vor-restore, total_size ist die Summe (HTTP ${CODE})" \
	eq "$(jq -r '(.backups | length) == 2 and ([.backups[] | select(.kind == "vor-restore")] | length) == 1
		and .total_size == ([.backups[].size] | add)' "${WORK_DIR}/list2.json" 2>/dev/null)" true

printf '\n== Aufräumen ==\n'
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" /dev/null)
check "Welt '${WORLD_NAME}' gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
CODE=$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav3.txt")
check "Die App löscht die Sicherungen nicht mit der Welt (beide Dateien noch da, PROPFIND ${CODE})" \
	sh -c '[ "$1" = 207 ] && [ "$(grep -c . "$2")" = 2 ]' _ "${CODE}" "${WORK_DIR}/dav3.txt"
dav_cleanup
CODE=$(dav_list "${DAV_FOLDER}" "${WORK_DIR}/dav4.txt")
check "Abnahme-Dateien in den Files von admin entfernt (PROPFIND ${CODE})" \
	sh -c '[ "$1" = 404 ] || { [ "$1" = 207 ] && ! grep -Eq "$3" "$2"; }' _ "${CODE}" "${WORK_DIR}/dav4.txt" "${OWN_FILE_RE}"
reset_fixtures
check "Konto ${LEO} gelöscht" user_absent "${LEO}"
check "Konto ${ADMIN2} gelöscht" user_absent "${ADMIN2}"
check "Positivkontrolle: dieselbe Abfrage erkennt das vorhandene Konto ${MIA}" user_present "${MIA}"
check "keine neuen Welt-Container übrig (ist $(new_containers))" eq "$(new_containers)" 0

printf '\n== Regression Phase 4.1 bis 1 ==\n'
if [ "${GAMEWORLD_SKIP_REGRESSION:-0}" = 1 ]; then
	fail "Regression übersprungen (GAMEWORLD_SKIP_REGRESSION=1), keine Phasenabnahme"
	printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
	exit 1
fi
# acceptance-phase4_1.sh ruft acceptance-phase4.sh, das Phase 3 bis 1 selbst aufruft.
if sh "${PHASE41_SCRIPT}" >"${WORK_DIR}/phase41.log" 2>&1; then
	pass "Regression: acceptance-phase4_1.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase41.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase4_1.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase41.log" >&2 || tail -n 20 "${WORK_DIR}/phase41.log" >&2
fi
check "Regression: Log enthält 'Phasenabnahme Phase 4.1 erfolgreich'" \
	grep -qx 'Phasenabnahme Phase 4.1 erfolgreich' "${WORK_DIR}/phase41.log"
for expected in "84 von 84 Prüfungen bestanden" "104 von 104 Prüfungen bestanden" \
	"75 von 75 Prüfungen bestanden" "109 von 109 Prüfungen bestanden"; do
	check "Regression: Log enthält '${expected}'" awk -v e="${expected}" \
		'$0 == e || (index($0, "bestanden: ") == 1 && index($0, e) > 0) { found = 1 } END { exit !found }' \
		"${WORK_DIR}/phase41.log"
done
check "nach der Regression: ExApp erreichbar" heartbeat_up

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 5 erfolgreich\n'
