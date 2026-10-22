#!/bin/sh
# Phasenabnahme Phase 2: prüft die vier Erfolgskriterien aus .planning/ROADMAP.md
# gegen den laufenden Dev-Stack (Nextcloud 8091, gescopter Docker-Proxy,
# ExApp als Host-Prozess) und ruft am Ende die Phase-1-Abnahme als Regression.
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen nur aus der
# docker-CLI, aus curl gegen Nextcloud, aus tar, jq und grep. Die Python-
# Testhelfer des Projekts werden nicht benutzt. Zu jeder Prüfung gibt es, wo
# sinnvoll, eine Negativkontrolle (das Verbotene scheitert) und eine
# Positivkontrolle (die Messmethode selbst funktioniert).
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   sh scripts/dev/register-exapp.sh
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Der Docker-Proxy wird für K2 kurz
# gestoppt, der ExApp-Prozess für K4 zweimal beendet; beides stellt ein trap in
# jedem Fall wieder her. Welten der Abnahme werden am Ende entfernt (Lösch-API,
# Fallback docker rm -f -v). Weltschlüssel aus den Antworten werden nie
# ausgegeben. Höchstens eine VoxeLibre-Welt existiert gleichzeitig (RAM).
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
REGISTER_SCRIPT="${SCRIPT_DIR}/register-exapp.sh"
PHASE1_SCRIPT="${SCRIPT_DIR}/acceptance-phase1.sh"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api"
DOCKER_PROXY_URL=http://127.0.0.1:23750
PROXY_SERVICE=gameworld-docker-proxy
BACKEND_PORT=10040
PID_FILE="${REPO_ROOT}/.dev/exapp.pid"
DATA_DIR=/var/lib/minetest
WORLD_DIR="${DATA_DIR}/.minetest/worlds/world"
MEM_KREATIV=536870912
MEM_SANFT=1073741824

NAME_KREATIV="Abnahme Kreativ"
NAME_SANFT="Abnahme Abenteuer"
NAME_STATUS="Abnahme Status"
NAME_DOWN="Abnahme Tot"
NAME_R1="Abnahme R1"
NAME_R2="Abnahme R2"

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
PROXY_STOPPED=0
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

hint() {
	printf 'Hinweis: %s\n' "$1"
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

start_proxy() {
	docker compose -f "${COMPOSE_FILE}" start "${PROXY_SERVICE}" >/dev/null 2>&1 || true
}

heartbeat_up() {
	curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1
}

# Beendet den ExApp-Host-Prozess. Unter Windows überlebt das Python-Kind von uv
# den Elternprozess; dann wird der Prozess auf dem Port per taskkill beendet.
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

register_backend() {
	sh "${REGISTER_SCRIPT}" >"$1" 2>&1
}

cleanup() {
	status=$?
	if [ "${PROXY_STOPPED}" -eq 1 ]; then
		printf 'starte %s wieder\n' "${PROXY_SERVICE}"
		start_proxy
		i=0
		while [ "${i}" -lt 15 ] && ! curl -sf "${DOCKER_PROXY_URL}/_ping" >/dev/null 2>&1; do
			i=$((i + 1))
			sleep 1
		done
	fi
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
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# http_code METHODE URL AUSGABE [JSON]
http_code() {
	if [ -n "${4:-}" ]; then
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$1" -d "$4" -o "$3" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	else
		curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X "$1" -o "$3" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	fi
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

# world_field ID JQ-AUSDRUCK -> Feld der Welt aus GET /worlds
world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

# wait_status ID ERWARTUNG SEKUNDEN -> 0 bei Erfolg, Wartezeit in WAITED
wait_status() {
	WAITED=0
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		[ "${WAITED}" -lt "$3" ] || return 1
		sleep 1
		WAITED=$((WAITED + 1))
	done
}

# read_file CONTAINER PFAD ZIEL -> Inhalt einer Datei per docker cp und tar
read_file() {
	# MSYS_NO_PATHCONV: Git Bash würde den Containerpfad sonst umschreiben.
	MSYS_NO_PATHCONV=1 docker cp "$1:$2" - >"$3.tar" 2>/dev/null || true
	tar -xOf "$3.tar" >"$3" 2>/dev/null || true
}

# create_world NAME PRESET(leer = One-Click) ZIEL -> HTTP-Code, merkt die ID
create_world() {
	if [ -n "$2" ]; then
		body="{\"name\":\"$1\",\"preset\":\"$2\"}"
	else
		body="{\"name\":\"$1\"}"
	fi
	code=$(http_code POST "${API_URL}/worlds" "$3" "${body}")
	remember_world "$(jq -r '.id // empty' "$3" 2>/dev/null || true)"
	printf '%s' "${code}"
}

# Doppelte Schlüssel einer conf-Datei (Kommentare und Leerzeilen ignoriert).
dup_keys() {
	grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$1" | cut -d= -f1 | sed 's/[[:space:]]*$//' | sort | uniq -d
}

# Spiegelt die Lage aller Nicht-Gameworld-Container: ID, Name, Zustand, Startzeit.
foreign_snapshot() {
	ids=$(docker ps -aq --no-trunc 2>/dev/null || true)
	[ -n "${ids}" ] || return 0
	# shellcheck disable=SC2086
	docker inspect -f '{{.Id}} {{.Name}} {{.State.Status}} {{.State.StartedAt}} gw={{index .Config.Labels "gameworld.managed"}}' \
		${ids} 2>/dev/null | grep -v ' gw=true$' | sort || true
}

# Zeilen aus $1, deren ID in $2 noch existiert, aber mit anderem Inhalt.
changed_lines() {
	awk 'NR == FNR { before[$1] = $0; next } ($1 in before) && before[$1] != $0 { print }' "$1" "$2"
}

# MemUsage aus docker stats ("45.3MiB / 512MiB") als Byte-Zahl.
to_bytes() {
	printf '%s\n' "$1" | awk '{
		v = $1; n = v + 0; u = v; sub(/^[0-9.]+/, "", u)
		f = 1
		if (u == "KiB") f = 1024; else if (u == "MiB") f = 1048576; else if (u == "GiB") f = 1073741824
		else if (u == "kB") f = 1000; else if (u == "MB") f = 1000000; else if (u == "GB") f = 1000000000
		printf "%d\n", n * f
	}'
}

epoch_of() {
	date -u -d "$(printf '%s' "$1" | cut -c1-19)Z" +%s 2>/dev/null || printf '0'
}

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
empty() { [ -z "$1" ]; }
nonempty() { [ -n "$1" ]; }
contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq tar grep awk date; do
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
if [ "$(docker compose -f "${COMPOSE_FILE}" ps "${PROXY_SERVICE}" --format '{{.State}}' 2>/dev/null)" != "running" ]; then
	abort "${PROXY_SERVICE} läuft nicht. Zuerst: docker compose -f scripts/dev/compose.yaml up -d"
fi

# Reste eines abgebrochenen früheren Laufs mit denselben Weltnamen entfernen.
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --arg a "${NAME_KREATIV}" --arg b "${NAME_SANFT}" --arg c "${NAME_STATUS}" \
	--arg d "${NAME_DOWN}" --arg e "${NAME_R1}" --arg f "${NAME_R2}" \
	'.worlds[]? | select(.name == $a or .name == $b or .name == $c or .name == $d or .name == $e or .name == $f) | .id' \
	"${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	remember_world "${old_id}"
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null "${API_URL}/worlds/${old_id}" || true
done

printf '\n== K1 Presets per One-Click ==\n'
# K1 Presets per One-Click, ohne Konfigfragen
CODE=$(http_code GET "${API_URL}/presets" "${WORK_DIR}/presets.json")
check "K1 GET /presets HTTP 200 (ist ${CODE})" eq "${CODE}" 200
PRESET_IDS=$(jq -r '[.presets[].id] | sort | join(",")' "${WORK_DIR}/presets.json" 2>/dev/null || true)
check "K1 genau die Presets mtg_kreativ und voxelibre_sanft (ist '${PRESET_IDS}')" \
	eq "${PRESET_IDS}" "mtg_kreativ,voxelibre_sanft"
EMPTY_TITLES=$(jq -r '[.presets[] | select((.title // "") == "")] | length' "${WORK_DIR}/presets.json" 2>/dev/null || printf 'x')
check "K1 jedes Preset hat einen nicht leeren Titel" eq "${EMPTY_TITLES}" 0

CODE_K=$(create_world "${NAME_KREATIV}" "" "${WORK_DIR}/kreativ.json")
check "K1 One-Click POST '${NAME_KREATIV}' ohne preset HTTP 201 (ist ${CODE_K})" eq "${CODE_K}" 201
ID_K=$(jq -r '.id // empty' "${WORK_DIR}/kreativ.json" 2>/dev/null || true)
check "K1 One-Click wählt mtg_kreativ" eq "$(jq -r '.preset // empty' "${WORK_DIR}/kreativ.json" 2>/dev/null)" mtg_kreativ
CODE_S=$(create_world "${NAME_SANFT}" voxelibre_sanft "${WORK_DIR}/sanft.json")
check "K1 POST '${NAME_SANFT}' mit voxelibre_sanft HTTP 201 (ist ${CODE_S})" eq "${CODE_S}" 201
ID_S=$(jq -r '.id // empty' "${WORK_DIR}/sanft.json" 2>/dev/null || true)
[ -n "${ID_K}" ] && [ -n "${ID_S}" ] || abort "Antworten ohne id, weitere Prüfungen sinnlos"
C_K=$(container_of "${ID_K}")
C_S=$(container_of "${ID_S}")
[ -n "${C_K}" ] && [ -n "${C_S}" ] || abort "kein Container mit Label gameworld.world_id für Kreativ oder Abenteuer"

for pair in "Kreativ ${C_K} ${MEM_KREATIV} mtg_kreativ" "Abenteuer ${C_S} ${MEM_SANFT} voxelibre_sanft"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	check "K1 $1 Memory $3" eq "$(inspect "$2" '{{.HostConfig.Memory}}')" "$3"
	check "K1 $1 MemorySwap $3" eq "$(inspect "$2" '{{.HostConfig.MemorySwap}}')" "$3"
	check "K1 $1 RestartPolicy no" eq "$(inspect "$2" '{{.HostConfig.RestartPolicy.Name}}')" no
	check "K1 $1 Label gameworld.preset $4" eq "$(inspect "$2" '{{index .Config.Labels "gameworld.preset"}}')" "$4"
	check "K1 $1 Label gameworld.schema 2" eq "$(inspect "$2" '{{index .Config.Labels "gameworld.schema"}}')" 2
done

read_file "${C_K}" "${DATA_DIR}/minetest.conf" "${WORK_DIR}/k.conf"
read_file "${C_K}" "${WORLD_DIR}/world.mt" "${WORK_DIR}/k.mt"
read_file "${C_S}" "${DATA_DIR}/minetest.conf" "${WORK_DIR}/s.conf"
read_file "${C_S}" "${WORLD_DIR}/world.mt" "${WORK_DIR}/s.mt"
check "K1 Positivkontrolle: beide conf und world.mt per docker cp gelesen" \
	sh -c 'test -s "$1" && test -s "$2" && test -s "$3" && test -s "$4"' _ \
	"${WORK_DIR}/k.conf" "${WORK_DIR}/k.mt" "${WORK_DIR}/s.conf" "${WORK_DIR}/s.mt"
check "K1 Kreativ creative_mode = true" grep -qx 'creative_mode = true' "${WORK_DIR}/k.conf"
check "K1 Kreativ enable_damage = false" grep -qx 'enable_damage = false' "${WORK_DIR}/k.conf"
for pair in "Kreativ k" "Abenteuer s"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	conf="${WORK_DIR}/$2.conf"
	check "K1 $1 genau eine default_privs-Zeile (ist $(grep -c '^default_privs[[:space:]]*=' "${conf}" || true))" \
		eq "$(grep -c '^default_privs[[:space:]]*=' "${conf}" || true)" 1
	check "K1 $1 default_privs ohne server, privs, ban, kick, give, password" \
		sh -c '! grep "^default_privs[[:space:]]*=" "$1" | cut -d= -f2 | grep -Eqw "server|privs|ban|kick|give|password"' _ "${conf}"
	check "K1 $1 server_announce = false" grep -qx 'server_announce = false' "${conf}"
	check "K1 $1 keine doppelten Keys in minetest.conf" empty "$(dup_keys "${conf}")"
	check "K1 $1 keine doppelten Keys in world.mt" empty "$(dup_keys "${WORK_DIR}/$2.mt")"
done
check "K1 Abenteuer only_peaceful_mobs = true" grep -qx 'only_peaceful_mobs = true' "${WORK_DIR}/s.conf"
check "K1 Abenteuer mcl_keepInventory = true" grep -qx 'mcl_keepInventory = true' "${WORK_DIR}/s.conf"
check "K1 Abenteuer enable_pvp = false" grep -qx 'enable_pvp = false' "${WORK_DIR}/s.conf"
check "K1 Kreativ world.mt gameid = minetest" grep -qx 'gameid = minetest' "${WORK_DIR}/k.mt"
check "K1 Abenteuer world.mt gameid = mineclone2" grep -qx 'gameid = mineclone2' "${WORK_DIR}/s.mt"
cat "${WORK_DIR}/k.conf" "${WORK_DIR}/k.conf" >"${WORK_DIR}/doppelt.conf"
check "K1 Positivkontrolle: dieselbe uniq-Prüfung findet Dubletten in einer verdoppelten Datei" \
	nonempty "$(dup_keys "${WORK_DIR}/doppelt.conf")"

CODE=$(create_world "x" survival_hart "${WORK_DIR}/neg1.json")
check "K1 Negativkontrolle: preset survival_hart HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/neg2.json" '{"name":"x","preset":"mtg_kreativ","mem_limit":"8g"}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/neg2.json" 2>/dev/null || true)"
check "K1 Negativkontrolle: preset plus mem_limit HTTP 422 (ist ${CODE})" eq "${CODE}" 422

# Nie zwei VoxeLibre-Welten gleichzeitig: Abenteuer sofort wieder löschen.
CODE=$(http_code DELETE "${API_URL}/worlds/${ID_S}" /dev/null)
check "K1 DELETE '${NAME_SANFT}' HTTP 204 (ist ${CODE})" eq "${CODE}" 204
check "K1 Abenteuer-Container ist weg" empty "$(container_of "${ID_S}")"

printf '\n== K2 Lebenszyklus und Status aus Docker ==\n'
# K2 Starten, Stoppen, Neustarten; Status kommt aus Docker, nicht aus der DB
CODE=$(create_world "${NAME_STATUS}" "" "${WORK_DIR}/status.json")
check "K2 POST '${NAME_STATUS}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
ID_ST=$(jq -r '.id // empty' "${WORK_DIR}/status.json" 2>/dev/null || true)
[ -n "${ID_ST}" ] || abort "Antwort ohne id für '${NAME_STATUS}'"
C_ST=$(container_of "${ID_ST}")
[ -n "${C_ST}" ] || abort "kein Container für '${NAME_STATUS}'"
check "K2 status running binnen 30 s" wait_status "${ID_ST}" running 30
printf 'gewartet: %s s\n' "${WAITED}"
check "K2 status_text bei running ist 'Läuft'" eq "$(world_field "${ID_ST}" '.status_text')" "Läuft"

CODE=$(http_code POST "${API_URL}/worlds/${ID_ST}/stop" /dev/null)
check "K2 POST stop HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 status stopped nach stop" wait_status "${ID_ST}" stopped 35
check "K2 Gegenprobe docker: State.Running false" eq "$(inspect "${C_ST}" '{{.State.Running}}')" false
CODE=$(http_code POST "${API_URL}/worlds/${ID_ST}/start" /dev/null)
check "K2 POST start HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 status running nach start binnen 30 s" wait_status "${ID_ST}" running 30

STARTED_BEFORE=$(inspect "${C_ST}" '{{.State.StartedAt}}')
CODE=$(http_code POST "${API_URL}/worlds/${ID_ST}/restart" /dev/null)
check "K2 POST restart HTTP 200 (ist ${CODE})" eq "${CODE}" 200
STARTED_AFTER=$(inspect "${C_ST}" '{{.State.StartedAt}}')
printf 'StartedAt vorher %s, nachher %s\n' "${STARTED_BEFORE}" "${STARTED_AFTER}"
check "K2 State.StartedAt nach restart neuer" \
	sh -c '[ "$1" != "$2" ] && [ "$(printf "%s\n%s\n" "$1" "$2" | sort | tail -n 1)" = "$2" ]' _ \
	"${STARTED_BEFORE}" "${STARTED_AFTER}"
check "K2 status running nach restart binnen 30 s" wait_status "${ID_ST}" running 30

# Von außen gestoppt: die DB sagt weiter running, der Status folgt Docker.
docker stop "${C_ST}" >/dev/null
check "K2 docker stop von außen: status stopped binnen 10 s" wait_status "${ID_ST}" stopped 10
check "K2 desired_state bleibt running (Beleg: Status aus Docker, nicht aus der DB)" \
	eq "$(world_field "${ID_ST}" '.desired_state')" running
CODE=$(http_code POST "${API_URL}/worlds/${ID_ST}/start" /dev/null)
check "K2 Positivkontrolle: POST start danach HTTP 200 und running" \
	sh -c '[ "$1" = 200 ]' _ "${CODE}"
check "K2 status running nach erneutem start" wait_status "${ID_ST}" running 30

docker kill "${C_ST}" >/dev/null
check "K2 docker kill von außen: status error binnen 10 s" wait_status "${ID_ST}" error 10
TEXT=$(world_field "${ID_ST}" '.status_text')
printf 'status_text: %s\n' "${TEXT}"
check "K2 status_text enthält 'unerwartet'" contains "${TEXT}" unerwartet
CODE=$(http_code POST "${API_URL}/worlds/${ID_ST}/start" /dev/null)
check "K2 Positivkontrolle: POST start nach kill HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 status running nach start binnen 30 s" wait_status "${ID_ST}" running 30

printf 'stoppe %s\n' "${PROXY_SERVICE}"
PROXY_STOPPED=1
docker compose -f "${COMPOSE_FILE}" stop "${PROXY_SERVICE}" >/dev/null 2>&1 || true
check "K2 Proxy wirklich gestoppt (State exited)" \
	eq "$(docker compose -f "${COMPOSE_FILE}" ps -a "${PROXY_SERVICE}" --format '{{.State}}' 2>/dev/null)" exited
waited=0
NOT_UNKNOWN=x
while [ "${waited}" -le 10 ]; do
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/down-list.json" >/dev/null
	COUNT=$(jq -r '.worlds | length' "${WORK_DIR}/down-list.json" 2>/dev/null || printf '0')
	NOT_UNKNOWN=$(jq -r '[.worlds[] | select(.status != "unknown")] | length' "${WORK_DIR}/down-list.json" 2>/dev/null || printf 'x')
	[ "${NOT_UNKNOWN}" = "0" ] && [ "${COUNT}" -ge 1 ] && break
	sleep 1
	waited=$((waited + 1))
done
check "K2 bei gestopptem Proxy alle ${COUNT} Welten status unknown" eq "${NOT_UNKNOWN}" 0
CODE=$(create_world "${NAME_DOWN}" "" "${WORK_DIR}/down.json")
check "K2 POST bei gestopptem Proxy HTTP 503 (ist ${CODE})" eq "${CODE}" 503
http_code GET "${API_URL}/worlds" "${WORK_DIR}/down-after.json" >/dev/null
GHOST=$(jq -r --arg n "${NAME_DOWN}" '[.worlds[]? | select(.name == $n)] | length' "${WORK_DIR}/down-after.json" 2>/dev/null || printf 'x')
check "K2 keine Zeile '${NAME_DOWN}' nach dem gescheiterten POST (ist ${GHOST})" eq "${GHOST}" 0
check "K2 Positivkontrolle: dieselbe jq-Suche findet '${NAME_STATUS}'" \
	eq "$(jq -r --arg n "${NAME_STATUS}" '[.worlds[]? | select(.name == $n)] | length' "${WORK_DIR}/down-after.json" 2>/dev/null)" 1
printf 'starte %s\n' "${PROXY_SERVICE}"
start_proxy
check "K2 nach Proxy-Start binnen 15 s wieder running" wait_status "${ID_ST}" running 15
PROXY_STOPPED=0
printf 'gewartet: %s s\n' "${WAITED}"

printf '\n== K3 Spieler und RAM ==\n'
# K3 Spieler und Arbeitsspeicher pro Welt
http_code GET "${API_URL}/worlds" "${WORK_DIR}/k3.json" >/dev/null
USED=$(jq -r --arg id "${ID_ST}" '.worlds[] | select(.id == $id) | .memory_used_bytes' "${WORK_DIR}/k3.json")
LIMIT=$(jq -r --arg id "${ID_ST}" '.worlds[] | select(.id == $id) | .memory_limit_bytes' "${WORK_DIR}/k3.json")
PLAYERS=$(jq -c --arg id "${ID_ST}" '.worlds[] | select(.id == $id) | .players' "${WORK_DIR}/k3.json")
check "K3 memory_limit_bytes ${MEM_KREATIV} (ist ${LIMIT})" eq "${LIMIT}" "${MEM_KREATIV}"
check "K3 0 < memory_used_bytes <= memory_limit_bytes (ist ${USED})" \
	sh -c 'case "$1" in ""|null|*[!0-9]*) exit 1 ;; esac; [ "$1" -gt 0 ] && [ "$1" -le "$2" ]' _ "${USED}" "${LIMIT}"
MEM_USAGE=$(docker stats --no-stream --format '{{.MemUsage}}' "${C_ST}" 2>/dev/null || true)
CLI_BYTES=$(to_bytes "${MEM_USAGE}")
printf 'API %s Byte (%s MiB), docker stats %s (%s Byte)\n' "${USED}" "$((USED / 1048576))" "${MEM_USAGE}" "${CLI_BYTES}"
check "K3 Gegenprobe docker stats im selben Bereich (höchstens Faktor 2)" \
	sh -c '[ "$2" -gt 0 ] && [ $(($1 * 2)) -ge "$2" ] && [ $(($2 * 2)) -ge "$1" ]' _ "${USED}" "${CLI_BYTES}"
check "K3 players ist [] ohne Client (ist ${PLAYERS})" eq "${PLAYERS}" "[]"

STATUS_DIR="${WORK_DIR}/statusfile"
mkdir -p "${STATUS_DIR}"
MSYS_NO_PATHCONV=1 docker cp "${C_ST}:${WORLD_DIR}/gameworld_players.txt" - >"${WORK_DIR}/players.tar" 2>/dev/null || true
tar -xf "${WORK_DIR}/players.tar" -C "${STATUS_DIR}" 2>/dev/null || true
check "K3 Status-Datei per docker cp vorhanden" test -f "${STATUS_DIR}/gameworld_players.txt"
FILE_EPOCH=$(stat -c %Y "${STATUS_DIR}/gameworld_players.txt" 2>/dev/null || printf '0')
START_EPOCH=$(epoch_of "$(inspect "${C_ST}" '{{.State.StartedAt}}')")
printf 'Status-Datei mtime %s, StartedAt %s (Sekunden)\n' "${FILE_EPOCH}" "${START_EPOCH}"
check "K3 Status-Datei nicht älter als State.StartedAt" \
	sh -c '[ "$2" -gt 0 ] && [ "$1" -ge "$2" ]' _ "${FILE_EPOCH}" "${START_EPOCH}"

CODE=$(http_code POST "${API_URL}/worlds/${ID_K}/stop" /dev/null)
check "K3 POST stop '${NAME_KREATIV}' HTTP 200 (ist ${CODE})" eq "${CODE}" 200
wait_status "${ID_K}" stopped 35 || true
check "K3 gestoppte Welt memory_used_bytes null" eq "$(world_field "${ID_K}" '.memory_used_bytes')" null
check "K3 gestoppte Welt players []" eq "$(world_field "${ID_K}" '.players | tojson')" "[]"

LOGS_HITS=$(grep -rn --include='*.py' 'logs(' "${REPO_ROOT}/src/gameworld" || true)
check "K3 statisch: kein logs( in src/gameworld" empty "${LOGS_HITS}"
CDB_HITS=$(grep -rn --include='*.py' 'content.luanti.org' "${REPO_ROOT}/src/gameworld" || true)
check "K3 statisch: kein content.luanti.org in src/gameworld" empty "${CDB_HITS}"
check "K3 Positivkontrolle: dasselbe grep findet content.luanti.org in CLAUDE.md" \
	grep -q 'content.luanti.org' "${REPO_ROOT}/CLAUDE.md"

for world_id in "${ID_K}" "${ID_ST}"; do
	CODE=$(http_code DELETE "${API_URL}/worlds/${world_id}" /dev/null)
	check "K3 Aufräumen DELETE ${world_id} HTTP 204 (ist ${CODE})" eq "${CODE}" 204
done

printf '\n== K4 Update und Reboot ==\n'
# K4 Nach ExApp-Update und Host-Reboot stimmt das Dashboard wieder
CODE=$(create_world "${NAME_R1}" "" "${WORK_DIR}/r1.json")
check "K4 POST '${NAME_R1}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
CODE=$(create_world "${NAME_R2}" "" "${WORK_DIR}/r2.json")
check "K4 POST '${NAME_R2}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
ID_R1=$(jq -r '.id // empty' "${WORK_DIR}/r1.json" 2>/dev/null || true)
ID_R2=$(jq -r '.id // empty' "${WORK_DIR}/r2.json" 2>/dev/null || true)
[ -n "${ID_R1}" ] && [ -n "${ID_R2}" ] || abort "Antworten ohne id für R1 oder R2"
wait_status "${ID_R1}" running 30 || true
wait_status "${ID_R2}" running 30 || true
CODE=$(http_code POST "${API_URL}/worlds/${ID_R2}/stop" /dev/null)
check "K4 POST stop R2 HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K4 R1 running, R2 stopped vor dem Update" \
	sh -c '[ "$1" = running ] && [ "$2" = stopped ]' _ \
	"$(world_field "${ID_R1}" '.status')" "$(world_field "${ID_R2}" '.status')"
C_R1=$(container_of "${ID_R1}")
C_R2=$(container_of "${ID_R2}")
foreign_snapshot >"${WORK_DIR}/foreign-before.txt"
check "K4 Positivkontrolle: Fremd-Schnappschuss enthält gameworld-dev-app-1" \
	grep -q '/gameworld-dev-app-1 ' "${WORK_DIR}/foreign-before.txt"
check "K4 Fremd-Schnappschuss enthält keine Abnahme-Welt" \
	sh -c '! grep -q -e "$1" -e "$2" "$3"' _ "${C_R1}" "${C_R2}" "${WORK_DIR}/foreign-before.txt"

# (a) Update-Simulation: Prozess beenden, neu registrieren ohne --rm-data.
printf 'beende den ExApp-Prozess (Update-Simulation)\n'
BACKEND_DOWN=1
OLD_PID=$(cat "${PID_FILE}" 2>/dev/null || true)
check "K4a ExApp-Prozess beendet, Heartbeat schweigt" kill_backend
register_backend "${WORK_DIR}/register-a.log" || true
BACKEND_DOWN=0
check "K4a register-exapp.sh hat ein neues Backend gestartet" \
	sh -c 'grep -q "starte das Backend auf" "$1" && [ "$(cat "$2")" != "$3" ]' _ \
	"${WORK_DIR}/register-a.log" "${PID_FILE}" "${OLD_PID}"
wait_status "${ID_R1}" running 20 || true
http_code GET "${API_URL}/worlds" "${WORK_DIR}/after-a.json" >/dev/null
check "K4a beide IDs nach dem Update gelistet, preset mtg_kreativ" \
	eq "$(jq -r --arg a "${ID_R1}" --arg b "${ID_R2}" \
		'[.worlds[] | select(.id == $a or .id == $b) | .preset] | join(",")' "${WORK_DIR}/after-a.json" 2>/dev/null)" \
	"mtg_kreativ,mtg_kreativ"
check "K4a R1 running" eq "$(world_field "${ID_R1}" '.status')" running
check "K4a R2 stopped" eq "$(world_field "${ID_R2}" '.status')" stopped
check "K4a Container-IDs unverändert" \
	sh -c '[ "$(docker ps -aq --no-trunc --filter label=gameworld.world_id=$1)" = "$3" ] &&
		[ "$(docker ps -aq --no-trunc --filter label=gameworld.world_id=$2)" = "$4" ]' _ \
	"${ID_R1}" "${ID_R2}" "${C_R1}" "${C_R2}"

# (b) Reboot-Simulation: Prozess beenden, R1 von außen stoppen, neu starten.
printf 'beende den ExApp-Prozess und stoppe R1 (Reboot-Simulation)\n'
docker inspect -f '{{.Id}} {{.Name}} {{.State.Status}} {{.State.StartedAt}}' "${C_R1}" >"${WORK_DIR}/r1-before.txt"
BACKEND_DOWN=1
check "K4b ExApp-Prozess beendet, Heartbeat schweigt" kill_backend
docker stop "${C_R1}" >/dev/null
check "K4b R1 von außen gestoppt (State.Running false)" eq "$(inspect "${C_R1}" '{{.State.Running}}')" false
register_backend "${WORK_DIR}/register-b.log" || true
BACKEND_DOWN=0
check "K4b R1 binnen 40 s wieder running" wait_status "${ID_R1}" running 40
printf 'gewartet: %s s\n' "${WAITED}"
check "K4b R1 gleiche Container-ID" eq "$(container_of "${ID_R1}")" "${C_R1}"
check "K4b R1 State.Running true (docker)" eq "$(inspect "${C_R1}" '{{.State.Running}}')" true
check "K4b R2 weiterhin exited (docker)" eq "$(inspect "${C_R2}" '{{.State.Status}}')" exited
check "K4b R2 status stopped" eq "$(world_field "${ID_R2}" '.status')" stopped
check "K4b RestartPolicy R1 und R2 no" \
	eq "$(inspect "${C_R1}" '{{.HostConfig.RestartPolicy.Name}}') $(inspect "${C_R2}" '{{.HostConfig.RestartPolicy.Name}}')" "no no"

foreign_snapshot >"${WORK_DIR}/foreign-after.txt"
CHANGED=$(changed_lines "${WORK_DIR}/foreign-before.txt" "${WORK_DIR}/foreign-after.txt")
check "K4 Negativkontrolle: kein Nicht-Gameworld-Container verändert (State, StartedAt)" empty "${CHANGED}"
[ -z "${CHANGED}" ] || printf 'verändert: %s\n' "${CHANGED}"
GONE=$(awk 'NR == FNR { after[$1] = 1; next } !($1 in after) { print $2 }' \
	"${WORK_DIR}/foreign-after.txt" "${WORK_DIR}/foreign-before.txt")
[ -z "${GONE}" ] || hint "kurzlebige Fremdcontainer verschwunden (nicht von hier): $(printf '%s' "${GONE}" | tr '\n' ' ')"
docker inspect -f '{{.Id}} {{.Name}} {{.State.Status}} {{.State.StartedAt}}' "${C_R1}" >"${WORK_DIR}/r1-after.txt"
check "K4 Positivkontrolle: derselbe Vergleich erkennt den Neustart von R1" \
	nonempty "$(changed_lines "${WORK_DIR}/r1-before.txt" "${WORK_DIR}/r1-after.txt")"

for world_id in "${ID_R1}" "${ID_R2}"; do
	CODE=$(http_code DELETE "${API_URL}/worlds/${world_id}" /dev/null)
	check "K4 Aufräumen DELETE ${world_id} HTTP 204 (ist ${CODE})" eq "${CODE}" 204
done
LEFT=""
for world_id in ${WORLD_IDS}; do
	LEFT="${LEFT}$(container_of "${world_id}")"
done
check "K4 keine Container der Abnahme-Welten übrig" empty "${LEFT}"

printf '\n== Regression Phase 1 ==\n'
if sh "${PHASE1_SCRIPT}" >"${WORK_DIR}/phase1.log" 2>&1; then
	pass "Regression: acceptance-phase1.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase1.log" | tail -n 1))"
else
	fail "Regression: acceptance-phase1.sh nicht Exit 0"
	grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase1.log" >&2 || tail -n 20 "${WORK_DIR}/phase1.log" >&2
fi

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 2 erfolgreich\n'
