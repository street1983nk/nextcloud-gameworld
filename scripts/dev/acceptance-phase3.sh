#!/bin/sh
# Phasenabnahme Phase 3: prüft die fünf Erfolgskriterien aus .planning/ROADMAP.md
# (Zugang und Rollen) gegen den laufenden Dev-Stack mit echter Nextcloud und
# ruft am Ende die Abnahmen von Phase 1 und Phase 2 als Regression.
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen aus der
# docker-CLI, aus curl gegen den AppAPI-Proxy mit echten Nextcloud-Konten, aus
# jq, tar und grep. Einziges Python-Werkzeug ist der UDP-Prober
# (tests/e2e/luanti_probe.py) über seine CLI; er spricht das Luanti-Protokoll
# gegen eine echte Welt und nutzt keinen Codepfad der ExApp außer den
# SRP-Konstanten N und G. Zu jeder Prüfung gibt es, wo sinnvoll, eine
# Negativkontrolle (das Verbotene scheitert) und eine Positivkontrolle (die
# Messmethode selbst funktioniert).
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   sh scripts/dev/register-exapp.sh
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Spielpasswörter erscheinen nie in
# der Ausgabe, nur ihr Muster und Vergleiche von sha256-Werten. Ein trap räumt in
# jedem Fall auf: Abnahme-Welt (Lösch-API, Fallback docker rm -f -v), Gruppe
# gw-familie, Wegwerfkonto gw-abnahme2, Spieler-Adresse zurück auf leer und
# gw-kind wieder aus der Gruppe admin. gw-kind selbst bleibt bestehen.
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
REGISTER_SCRIPT="${SCRIPT_DIR}/register-exapp.sh"
PHASE1_SCRIPT="${SCRIPT_DIR}/acceptance-phase1.sh"
PHASE2_SCRIPT="${SCRIPT_DIR}/acceptance-phase2.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
KID=gw-kind
KID_AUTH="${KID}:gw-kind-dev-pass-1"
GUEST=gw-abnahme2
GUEST_PASS=gw-abnahme2-dev-pass-1
GROUP=gw-familie
PAGE_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/embedded/gameworld/gameworld"
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
BUNDLE_URL="${PROXY_BASE}/js/gameworld-main.js"
DOCKER_PROXY_URL=http://127.0.0.1:23750
BACKEND_PORT=10040
PID_FILE="${REPO_ROOT}/.dev/exapp.pid"
DB_FILE="${REPO_ROOT}/.dev/storage/gameworld.sqlite3"
ACCESS_FILE=/var/lib/minetest/.minetest/worlds/world/gameworld_access.txt
PROBE_HOST=127.0.0.1
JOIN_HOST=192.168.178.20
ROLE_CACHE_WAIT=35
NAME_WORLD="Abnahme Zugang"
NAME_RE='^[A-Za-z0-9_-]{1,20}$'
PASSWORD_RE='^[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}-[a-hj-km-np-z2-9]{4}$'

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
KID_IN_ADMIN=0
BACKEND_DOWN=0
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

heartbeat_up() {
	curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1
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

# Alles, was die Abnahme anlegt oder umstellt, wieder in den Ausgangszustand.
reset_fixtures() {
	occ group:removeuser admin "${KID}" >/dev/null 2>&1 || true
	occ group:delete "${GROUP}" >/dev/null 2>&1 || true
	occ user:delete "${GUEST}" >/dev/null 2>&1 || true
}

cleanup() {
	status=$?
	if [ "${KID_IN_ADMIN}" -eq 1 ]; then
		printf 'entferne %s wieder aus der Gruppe admin\n' "${KID}"
	fi
	if [ "${BACKEND_DOWN}" -eq 1 ] || ! heartbeat_up; then
		printf 'starte die ExApp wieder (register-exapp.sh)\n'
		sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register-cleanup.log" 2>&1 \
			|| printf 'register-exapp.sh scheiterte, bitte von Hand starten\n' >&2
	fi
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
		-X POST -d '{"join_host":""}' -o /dev/null "${API_URL}/settings" >/dev/null 2>&1 || true
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
	tar -xOf "$3.tar" >"$3" 2>/dev/null || true
	tar -tvf "$3.tar" --numeric-owner >"$3.list" 2>/dev/null || true
}

# players_to DATEI -> GET players als admin
players_to() {
	http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "$1"
}

# player_field DATEI NC_USER FELD -> Feld eines Spielers aus einer players-Antwort
player_field() {
	jq -r --arg u "$2" ".players[]? | select(.nc_user == \$u) | .$3 // empty" "$1" 2>/dev/null || true
}

# Ein Join-Versuch über die Prober-CLI, JSON nach $1; Passwort nur als Argument.
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
	jq -r '"\(.result) \(.code // "") \(.reason // "")"' "$1" 2>/dev/null || printf 'nicht lesbar'
}

sha_of() {
	printf '%s' "$1" | sha256sum | cut -d' ' -f1
}

matches() {
	printf '%s' "$1" | grep -Eq "$2"
}

# Zählt Fundstellen eines festen Strings in einer Datei (binär-tolerant).
hits_in() {
	grep -c -a -F -- "$1" "$2" 2>/dev/null || true
}

role_of() {
	call "$1" GET "${API_URL}/me" "${WORK_DIR}/me.json" >/dev/null
	jq -r '.role // empty' "${WORK_DIR}/me.json" 2>/dev/null || true
}

# Spalten der Tabelle players: sqlite3, sonst die Standardbibliothek
# (nur lesend, unabhängig vom Code der ExApp).
players_columns() {
	if command -v sqlite3 >/dev/null 2>&1; then
		sqlite3 -readonly "${DB_FILE}" "PRAGMA table_info(players)" | cut -d'|' -f2 | paste -sd, -
		return
	fi
	db_path=${DB_FILE}
	command -v cygpath >/dev/null 2>&1 && db_path=$(cygpath -w "${DB_FILE}")
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sqlite3, sys
con = sqlite3.connect("file:" + sys.argv[1].replace("\\", "/") + "?mode=ro", uri=True)
print(",".join(row[1] for row in con.execute("PRAGMA table_info(players)")))
' "${db_path}") 2>/dev/null | tr -d '\r'
}

user_present() { occ user:info "$1" >/dev/null 2>&1; }
user_absent() { ! user_present "$1"; }

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
empty() { [ -z "$1" ]; }
nonempty() { [ -n "$1" ]; }
contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq tar grep awk sha256sum uv; do
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

# Reste eines abgebrochenen früheren Laufs entfernen.
reset_fixtures
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --arg a "${NAME_WORLD}" '.worlds[]? | select(.name == $a) | .id' "${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	remember_world "${old_id}"
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null "${API_URL}/worlds/${old_id}" || true
done

printf '\n== K1 Einladen und Provisionieren ==\n'
# K1 Einladen von Konten und Gruppen; Zugang wird in die Welt geschrieben
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/world.json" "{\"name\":\"${NAME_WORLD}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/world.json" 2>/dev/null || true)
remember_world "${WORLD_ID}"
check "K1 POST '${NAME_WORLD}' (Kreativ) HTTP 201 (ist ${CODE})" eq "${CODE}" 201
[ -n "${WORLD_ID}" ] || abort "Antwort ohne id"
CONTAINER=$(container_of "${WORLD_ID}")
[ -n "${CONTAINER}" ] || abort "kein Container mit Label gameworld.world_id"
check "K1 Welt running binnen 40 s" wait_status "${WORLD_ID}" running 40
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
check "K1 docker port liefert einen UDP-Port (ist ${PORT:-leer})" matches "${PORT}" '^[0-9]+$'

CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv-kid.json" "{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "K1 POST invites user ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
players_to "${WORK_DIR}/p1.json" >/dev/null
KID_NAME=$(player_field "${WORK_DIR}/p1.json" "${KID}" player_name)
KID_PW=$(player_field "${WORK_DIR}/p1.json" "${KID}" password)
check "K1 GET players: ${KID} mit Spielername '${KID_NAME}' nach Muster" matches "${KID_NAME}" "${NAME_RE}"
check "K1 GET players: Passwort von ${KID} passt auf das Muster (Länge ${#KID_PW})" matches "${KID_PW}" "${PASSWORD_RE}"

occ group:add "${GROUP}" >/dev/null 2>&1 || true
docker compose -f "${COMPOSE_FILE}" exec -T -u www-data -e OC_PASS="${GUEST_PASS}" app \
	php occ user:add --password-from-env --display-name="Gast Abnahme" "${GUEST}" >/dev/null 2>&1 \
	|| abort "Konto ${GUEST} ließ sich nicht anlegen"
occ group:adduser "${GROUP}" "${GUEST}" >/dev/null 2>&1 || abort "${GUEST} ließ sich nicht in ${GROUP} aufnehmen"
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv-group.json" "{\"kind\":\"group\",\"target\":\"${GROUP}\"}")
check "K1 POST invites group ${GROUP} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
players_to "${WORK_DIR}/p2.json" >/dev/null
GUEST_NAME=$(player_field "${WORK_DIR}/p2.json" "${GUEST}" player_name)
GUEST_PW=$(player_field "${WORK_DIR}/p2.json" "${GUEST}" password)
GUEST_VIA=$(player_field "${WORK_DIR}/p2.json" "${GUEST}" via)
check "K1 GET players: ${GUEST} über die Gruppe (via ${GUEST_VIA:-leer})" contains "${GUEST_VIA}" group
check "K1 GET players: ${GUEST} mit Spielername '${GUEST_NAME}' nach Muster" matches "${GUEST_NAME}" "${NAME_RE}"
check "K1 GET players: Passwort von ${GUEST} passt auf das Muster" matches "${GUEST_PW}" "${PASSWORD_RE}"
check "K1 GET players: ${KID} weiterhin direkt eingeladen (via user)" \
	eq "$(player_field "${WORK_DIR}/p2.json" "${KID}" via)" user

CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv-neg.json" '{"kind":"user","target":"gibt-es-nicht"}')
check "K1 Negativkontrolle: invites user gibt-es-nicht HTTP 422 (ist ${CODE})" eq "${CODE}" 422

# Gegenprobe direkt im Weltordner: Was steht in der Zugangsdatei?
read_file "${CONTAINER}" "${ACCESS_FILE}" "${WORK_DIR}/access.txt"
tr -d '\r' <"${WORK_DIR}/access.txt" >"${WORK_DIR}/access.lf"
check "K1 Zugangsdatei per docker cp gelesen (Positivkontrolle)" test -s "${WORK_DIR}/access.lf"
check "K1 Kopfzeile 'gameworld-access 1 <Generation>'" \
	sh -c 'head -n 1 "$1" | grep -Eqx "gameworld-access 1 [0-9]+"' _ "${WORK_DIR}/access.lf"
check "K1 Schlusszeile 'end'" eq "$(tail -n 1 "${WORK_DIR}/access.lf")" end
check "K1 Zugangsdatei enthält '${KID_NAME}' und '${GUEST_NAME}'" \
	sh -c 'grep -q "^$2 " "$1" && grep -q "^$3 " "$1"' _ "${WORK_DIR}/access.lf" "${KID_NAME}" "${GUEST_NAME}"
ACCESS_META=$(awk '{print $1, $2}' "${WORK_DIR}/access.txt.list" 2>/dev/null | head -n 1)
check "K1 Zugangsdatei gehört root und ist -r--r--r-- (ist ${ACCESS_META:-leer})" eq "${ACCESS_META}" "-r--r--r-- 0/0"
check "K1 kein Spielpasswort im Klartext in der Zugangsdatei" \
	sh -c '[ "$(grep -c -F -- "$2" "$1" || true)" = 0 ] && [ "$(grep -c -F -- "$3" "$1" || true)" = 0 ]' _ \
	"${WORK_DIR}/access.lf" "${KID_PW}" "${GUEST_PW}"

printf '\n== K2 Join nur für Eingeladene ==\n'
# K2 Nicht Eingeladene kommen nicht hinein, Eingeladene mit den Nextcloud-Daten schon
probe "${WORK_DIR}/j-fremd.json" Fremder
printf 'Fremder: %s\n' "$(probe_summary "${WORK_DIR}/j-fremd.json")"
check "K2 Negativ-Join 'Fremder': denied mit 'nicht eingeladen'" \
	eq "$(jq -r '.result == "denied" and ((.reason // "") | contains("nicht eingeladen"))' "${WORK_DIR}/j-fremd.json" 2>/dev/null)" true
check "K2 Positiv-Join ${KID} mit Name und Passwort aus Nextcloud: auth_accept" \
	probe_expect "${WORK_DIR}/j-kid.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"
printf '%s: %s\n' "${KID}" "$(probe_summary "${WORK_DIR}/j-kid.json")"
probe "${WORK_DIR}/j-wrong.json" "${KID_NAME}" "falsch-falsch-falsch"
check "K2 Negativkontrolle: falsches Passwort WRONG_PASSWORD (ist $(probe_summary "${WORK_DIR}/j-wrong.json"))" \
	eq "$(jq -r '.code // empty' "${WORK_DIR}/j-wrong.json" 2>/dev/null)" WRONG_PASSWORD

check "K2 Positivkontrolle: ${GUEST} mit altem Passwort auth_accept" \
	probe_expect "${WORK_DIR}/j-guest-old.json" '.result == "auth_accept"' 10 "${GUEST_NAME}" "${GUEST_PW}"

CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites/remove" "${WORK_DIR}/rm-kid.json" "{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "K2 POST invites/remove ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 nach Entfernen: ${KID} denied mit 'nicht eingeladen'" \
	probe_expect "${WORK_DIR}/j-kid-rm.json" '.result == "denied" and ((.reason // "") | contains("nicht eingeladen"))' 10 \
	"${KID_NAME}" "${KID_PW}"

STARTED_BEFORE=$(inspect "${CONTAINER}" '{{.State.StartedAt}}')
CODE=$(http_code POST "${API_URL}/players/password" "${WORK_DIR}/rot.json" "{\"nc_user\":\"${GUEST}\"}")
check "K2 POST players/password ${GUEST} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
GUEST_PW_NEW=$(jq -r '.password // empty' "${WORK_DIR}/rot.json" 2>/dev/null || true)
check "K2 neues Passwort nach Muster und anders als das alte" \
	sh -c 'printf "%s" "$1" | grep -Eq "$3" && [ "$1" != "$2" ]' _ "${GUEST_PW_NEW}" "${GUEST_PW}" "${PASSWORD_RE}"
check "K2 altes Passwort von ${GUEST} danach WRONG_PASSWORD" \
	probe_expect "${WORK_DIR}/j-guest-old2.json" '.code == "WRONG_PASSWORD"' 10 "${GUEST_NAME}" "${GUEST_PW}"
check "K2 neues Passwort von ${GUEST} auth_accept" \
	probe_expect "${WORK_DIR}/j-guest-new.json" '.result == "auth_accept"' 10 "${GUEST_NAME}" "${GUEST_PW_NEW}"
GUEST_PW=${GUEST_PW_NEW}
STARTED_AFTER=$(inspect "${CONTAINER}" '{{.State.StartedAt}}')
check "K2 ohne Neustart der Welt (State.StartedAt unverändert)" eq "${STARTED_AFTER}" "${STARTED_BEFORE}"
EXEC=$(curl -s -X POST -o /dev/null -w '%{http_code}' "${DOCKER_PROXY_URL}/exec/x/start" 2>/dev/null || printf '000')
check "K2 Docker-Proxy POST /exec/x/start weiterhin 403 (ist ${EXEC})" eq "${EXEC}" 403

printf '\n== K3 Verbindungsinfo für das Kind ==\n'
# K3 Kinder sehen ihre Welten mit Adresse, Port, Spielername und Passwort
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv-kid2.json" "{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "K3 ${KID} wieder eingeladen, HTTP 200 (ist ${CODE})" eq "${CODE}" 200
players_to "${WORK_DIR}/p3.json" >/dev/null
CODE=$(call "${KID_AUTH}" GET "${API_URL}/my/worlds" "${WORK_DIR}/my.json")
check "K3 GET /my/worlds als ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 genau die Abnahme-Welt in der Liste" \
	eq "$(jq -r '[.worlds[].id] | join(",")' "${WORK_DIR}/my.json" 2>/dev/null)" "${WORLD_ID}"
MY_PORT=$(jq -r '.worlds[0].port // empty' "${WORK_DIR}/my.json" 2>/dev/null || true)
check "K3 port gleich docker port (UDP) ${PORT} (ist ${MY_PORT:-leer})" eq "${MY_PORT}" "${PORT}"
check "K3 player_name gleich der Verwalter-Ansicht" \
	eq "$(jq -r '.worlds[0].player_name // empty' "${WORK_DIR}/my.json" 2>/dev/null)" "$(player_field "${WORK_DIR}/p3.json" "${KID}" player_name)"
MY_PW=$(jq -r '.worlds[0].password // empty' "${WORK_DIR}/my.json" 2>/dev/null || true)
ADMIN_VIEW_PW=$(player_field "${WORK_DIR}/p3.json" "${KID}" password)
check "K3 password gleich der Verwalter-Ansicht (sha256-Vergleich)" \
	sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ "$(sha_of "${MY_PW}")" "$(sha_of "${ADMIN_VIEW_PW}")"
check "K3 Positivkontrolle: diese Daten lassen ${KID} in die Welt (auth_accept)" \
	probe_expect "${WORK_DIR}/j-kid-my.json" '.result == "auth_accept"' 10 \
	"$(jq -r '.worlds[0].player_name' "${WORK_DIR}/my.json")" "${MY_PW}"
CODE=$(http_code POST "${API_URL}/settings" "${WORK_DIR}/set.json" "{\"join_host\":\"${JOIN_HOST}\"}")
check "K3 POST settings join_host ${JOIN_HOST} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
call "${KID_AUTH}" GET "${API_URL}/my/worlds" "${WORK_DIR}/my2.json" >/dev/null
check "K3 host in /my/worlds gleich ${JOIN_HOST}" eq "$(jq -r '.worlds[0].host // empty' "${WORK_DIR}/my2.json" 2>/dev/null)" "${JOIN_HOST}"
CODE=$(http_code POST "${API_URL}/settings" "${WORK_DIR}/set-neg.json" '{"join_host":"http://x"}')
check "K3 Negativkontrolle: join_host 'http://x' HTTP 422 (ist ${CODE})" eq "${CODE}" 422
http_code GET "${API_URL}/settings" "${WORK_DIR}/set-get.json" >/dev/null
check "K3 nach dem 422 bleibt join_host ${JOIN_HOST}" eq "$(jq -r '.join_host' "${WORK_DIR}/set-get.json" 2>/dev/null)" "${JOIN_HOST}"

printf '\n== K4 Kind-Ansicht und Sperre ==\n'
# K4 Kinder sehen die Seite, aber keine Verwaltung und keine fremden Zugänge
CODE=$(call "${KID_AUTH}" GET "${PAGE_URL}" "${WORK_DIR}/page-kid.html")
check "K4 Seite als ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${KID_AUTH}" GET "${BUNDLE_URL}" /dev/null)
check "K4 Bundle als ${KID} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${KID_AUTH}" GET "${API_URL}/worlds" /dev/null)
check "K4 Negativkontrolle: GET /api/worlds als ${KID} nicht 200 (ist ${CODE})" ne "${CODE}" 200
CODE=$(call "${KID_AUTH}" POST "${API_URL}/worlds" "${WORK_DIR}/kid-create.json" '{"name":"Kind darf nicht","preset":"mtg_kreativ"}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/kid-create.json" 2>/dev/null || true)"
check "K4 Negativkontrolle: POST /api/worlds als ${KID} nicht 200/201 (ist ${CODE})" \
	sh -c '[ "$1" != 200 ] && [ "$1" != 201 ]' _ "${CODE}"
CODE=$(call "${KID_AUTH}" GET "${API_URL}/worlds/${WORLD_ID}/players" /dev/null)
check "K4 Negativkontrolle: GET players als ${KID} nicht 200 (ist ${CODE})" ne "${CODE}" 200
CODE=$(call "${KID_AUTH}" POST "${API_URL}/players/password" /dev/null "{\"nc_user\":\"${GUEST}\"}")
check "K4 Negativkontrolle: POST players/password als ${KID} nicht 200 (ist ${CODE})" ne "${CODE}" 200
CODE=$(call "${KID_AUTH}" GET "${API_URL}/settings" /dev/null)
check "K4 Negativkontrolle: GET settings als ${KID} nicht 200 (ist ${CODE})" ne "${CODE}" 200
players_to "${WORK_DIR}/p4.json" >/dev/null
check "K4 Passwort von ${GUEST} nach den Kind-Aufrufen unverändert" \
	eq "$(sha_of "$(player_field "${WORK_DIR}/p4.json" "${GUEST}" password)")" "$(sha_of "${GUEST_PW}")"
check "K4 /my/worlds von ${KID} enthält weder Name noch Passwort von ${GUEST}" \
	sh -c '[ "$(grep -c -F -- "$2" "$1" || true)" = 0 ] && [ "$(grep -c -F -- "$3" "$1" || true)" = 0 ]' _ \
	"${WORK_DIR}/my2.json" "${GUEST_NAME}" "${GUEST_PW}"
check "K4 Positivkontrolle: dasselbe grep findet beide in der Verwalter-Antwort" \
	sh -c '[ "$(grep -c -F -- "$2" "$1" || true)" != 0 ] && [ "$(grep -c -F -- "$3" "$1" || true)" != 0 ]' _ \
	"${WORK_DIR}/p4.json" "${GUEST_NAME}" "${GUEST_PW}"

printf '\n== K5 Rollen aus Nextcloud, keine gespeicherten Passwörter ==\n'
# K5 Rollen kommen aus Nextcloud, keine eigene Benutzerverwaltung, kein Passwort in der DB
check "K5 /api/me für ${KID}: role spieler" eq "$(role_of "${KID_AUTH}")" spieler
check "K5 /api/me für admin: role verwalter" eq "$(role_of "${ADMIN_AUTH}")" verwalter
KID_IN_ADMIN=1
occ group:adduser admin "${KID}" >/dev/null 2>&1 || true
printf 'warte %s s (Rollen-Cache)\n' "${ROLE_CACHE_WAIT}"
sleep "${ROLE_CACHE_WAIT}"
check "K5 ${KID} in Gruppe admin: role verwalter" eq "$(role_of "${KID_AUTH}")" verwalter
occ group:removeuser admin "${KID}" >/dev/null 2>&1 || true
KID_ADMIN=$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${KID}" '(.admin // []) | index($u) // "nein"')
check "K5 ${KID} sofort wieder aus admin entfernt" eq "${KID_ADMIN}" nein
[ "${KID_ADMIN}" = nein ] && KID_IN_ADMIN=0
printf 'warte %s s (Rollen-Cache)\n' "${ROLE_CACHE_WAIT}"
sleep "${ROLE_CACHE_WAIT}"
check "K5 ${KID} nach dem Entfernen: role spieler" eq "$(role_of "${KID_AUTH}")" spieler

COLUMNS=$(players_columns)
check "K5 Tabelle players hat genau nc_user, player_name, rotation (ist ${COLUMNS:-leer})" \
	eq "${COLUMNS}" "nc_user,player_name,rotation"
DB_ALL="${WORK_DIR}/db-all.bin"
cat "${DB_FILE}" "${DB_FILE}-wal" >"${DB_ALL}" 2>/dev/null || cat "${DB_FILE}" >"${DB_ALL}"
PW_HITS=$(hits_in "${KID_PW}" "${DB_ALL}")
check "K5 Passwort von ${KID} steht nicht in der SQLite-Datei (Treffer ${PW_HITS})" eq "${PW_HITS}" 0
GUEST_PW_HITS=$(hits_in "${GUEST_PW}" "${DB_ALL}")
check "K5 Passwort von ${GUEST} steht nicht in der SQLite-Datei (Treffer ${GUEST_PW_HITS})" eq "${GUEST_PW_HITS}" 0
NAME_HITS=$(hits_in "${KID_NAME}" "${DB_ALL}")
check "K5 Positivkontrolle: dasselbe grep findet den Spielernamen (Treffer ${NAME_HITS})" test "${NAME_HITS}" -gt 0

printf 'beende den ExApp-Prozess (Neustart)\n'
OLD_PID=$(cat "${PID_FILE}" 2>/dev/null || true)
BACKEND_DOWN=1
check "K5 ExApp-Prozess beendet, Heartbeat schweigt" kill_backend
sh "${REGISTER_SCRIPT}" >"${WORK_DIR}/register.log" 2>&1 || true
BACKEND_DOWN=0
check "K5 register-exapp.sh hat ein neues Backend gestartet" \
	sh -c 'grep -q "starte das Backend" "$1" && [ "$(cat "$2")" != "$3" ]' _ \
	"${WORK_DIR}/register.log" "${PID_FILE}" "${OLD_PID}"
players_to "${WORK_DIR}/p5.json" >/dev/null
check "K5 nach Neustart dasselbe Passwort für ${KID} (Geheimnis aus Nextcloud, sha256-Vergleich)" \
	eq "$(sha_of "$(player_field "${WORK_DIR}/p5.json" "${KID}" password)")" "$(sha_of "${KID_PW}")"
check "K5 nach Neustart lässt dasselbe Passwort ${KID} in die Welt" \
	probe_expect "${WORK_DIR}/j-kid-restart.json" '.result == "auth_accept"' 10 "${KID_NAME}" "${KID_PW}"
OWN_USERS=$(grep -rn --include='*.py' 'users/add\|createUser\|password_hash' "${REPO_ROOT}/src/gameworld" || true)
check "K5 statisch: keine eigene Kontenverwaltung in src/gameworld" empty "${OWN_USERS}"
printf 'def x():\n    createUser()\n' >"${WORK_DIR}/probe.py"
check "K5 Positivkontrolle: dasselbe grep findet createUser in einer Probedatei" \
	nonempty "$(grep -rn --include='*.py' 'users/add\|createUser\|password_hash' "${WORK_DIR}" || true)"

printf '\n== Aufräumen ==\n'
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" /dev/null)
check "Aufräumen DELETE '${NAME_WORLD}' HTTP 204 (ist ${CODE})" eq "${CODE}" 204
CODE=$(http_code POST "${API_URL}/settings" /dev/null '{"join_host":""}')
check "Aufräumen join_host zurück auf leer HTTP 200 (ist ${CODE})" eq "${CODE}" 200
reset_fixtures
check "Aufräumen Konto ${GUEST} gelöscht" user_absent "${GUEST}"
check "Positivkontrolle: dieselbe Abfrage erkennt das vorhandene Konto ${KID}" user_present "${KID}"
check "Aufräumen Gruppe ${GROUP} gelöscht" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg g "${GROUP}" 'has($g)')" false
check "Aufräumen ${KID} nicht in admin" \
	eq "$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${KID}" '(.admin // []) | index($u) // "nein"')" nein
LEFT=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | wc -l | tr -d ' ')
check "keine Welt-Container übrig (ist ${LEFT})" eq "${LEFT}" 0

printf '\n== Regression Phase 1 und Phase 2 ==\n'
# Nur für schnelle Iterationen: übersprungene Regression zählt als Fehlschlag.
if [ "${GAMEWORLD_SKIP_REGRESSION:-0}" = 1 ]; then
	fail "Regression übersprungen (GAMEWORLD_SKIP_REGRESSION=1), keine Phasenabnahme"
	printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
	exit 1
fi
if sh "${PHASE1_SCRIPT}" >"${WORK_DIR}/phase1.log" 2>&1; then
	pass "Regression: acceptance-phase1.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase1.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase1.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase1.log" >&2 || tail -n 20 "${WORK_DIR}/phase1.log" >&2
fi
if sh "${PHASE2_SCRIPT}" >"${WORK_DIR}/phase2.log" 2>&1; then
	pass "Regression: acceptance-phase2.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase2.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase2.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase2.log" >&2 || tail -n 20 "${WORK_DIR}/phase2.log" >&2
fi

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 3 erfolgreich\n'
