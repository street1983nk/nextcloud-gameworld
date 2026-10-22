#!/bin/sh
# Phasenabnahme Phase 1: prüft die fünf Erfolgskriterien aus .planning/ROADMAP.md
# gegen den laufenden Dev-Stack (Nextcloud 8091, gescopter Docker-Proxy,
# ExApp als Host-Prozess).
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen nur aus der
# docker-CLI, aus curl gegen Nextcloud und den Proxy, aus tar und grep. Die
# Python-Testhelfer des Projekts werden nicht benutzt. Zu jeder Prüfung gibt
# es, wo sinnvoll, eine Negativkontrolle (das Verbotene scheitert) und eine
# Positivkontrolle (die Messmethode selbst funktioniert).
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   sh scripts/dev/register-exapp.sh
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Der Docker-Proxy wird für K5 kurz
# gestoppt und in jedem Fall per trap wieder gestartet. Welten der Abnahme werden
# am Ende entfernt, der Nutzer gw-kind bleibt für die Playwright-Abnahme stehen.
# Weltschlüssel aus den Antworten werden nie ausgegeben.
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
KID_USER=gw-kind
KID_PASS=gw-kind-dev-pass-1
KID_AUTH="${KID_USER}:${KID_PASS}"
PAGE_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/embedded/gameworld/gameworld"
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
BUNDLE_URL="${PROXY_BASE}/js/gameworld-main.js"
DOCKER_PROXY_URL=http://127.0.0.1:23750
PROXY_SERVICE=gameworld-docker-proxy
PROXY_CONTAINER=gameworld-dev-gameworld-docker-proxy-1
IMAGE_DIGEST=sha256:db682caec367977ac2661c81e3cdbd1f1dbbae596f6fa7d791c0031107d59947
NAME_A="Abnahme A"
NAME_B="Abnahme B"

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
PROXY_STOPPED=0
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

# http_code METHODE URL AUTH AUSGABE [JSON]
http_code() {
	if [ -n "${5:-}" ]; then
		curl -s -u "$3" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
			-X "$1" -d "$5" -o "$4" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	else
		curl -s -u "$3" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X "$1" -o "$4" -w '%{http_code}' "$2" 2>/dev/null || printf '000'
	fi
}

remember_world() {
	[ -n "$1" ] && WORLD_IDS="${WORLD_IDS} $1"
	return 0
}

container_of() {
	docker ps -aq --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1"
}

inspect() {
	docker inspect -f "$2" "$1" 2>/dev/null || printf 'nicht lesbar'
}

wait_running() {
	# wait_running CONTAINER ERWARTUNG SEKUNDEN -> 0 bei Erfolg
	waited=0
	while [ "$(inspect "$1" '{{.State.Running}}')" != "$2" ]; do
		[ "${waited}" -lt "$3" ] || return 1
		sleep 1
		waited=$((waited + 1))
	done
	return 0
}

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
empty() { [ -z "$1" ]; }
nonempty() { [ -n "$1" ]; }
contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq tar grep; do
	command -v "${tool}" >/dev/null 2>&1 || abort "Werkzeug ${tool} fehlt"
done
if ! curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
	abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
APP_LIST=$(occ app_api:app:list 2>/dev/null || true)
if ! printf '%s\n' "${APP_LIST}" | grep -q '^gameworld '; then
	abort "Gameworld ist nicht registriert. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
if [ "$(docker compose -f "${COMPOSE_FILE}" ps "${PROXY_SERVICE}" --format '{{.State}}' 2>/dev/null)" != "running" ]; then
	abort "${PROXY_SERVICE} läuft nicht. Zuerst: docker compose -f scripts/dev/compose.yaml up -d"
fi

# Reste eines abgebrochenen früheren Laufs mit denselben Weltnamen entfernen.
http_code GET "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --arg a "${NAME_A}" --arg b "${NAME_B}" \
	'.worlds[]? | select(.name == $a or .name == $b or .name == "Abnahme Proxy") | .id' \
	"${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	remember_world "${old_id}"
	curl -s -u "${ADMIN_AUTH}" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -X DELETE -o /dev/null "${API_URL}/worlds/${old_id}" || true
done

printf '\n== K1 Installation und Top-Menü ==\n'
# K1 Installation und Top-Menü; Nicht-Admin sieht Seite und Bundle, aber keine Verwaltung
check "K1 occ app_api:app:list zeigt gameworld als enabled" \
	sh -c 'printf "%s\n" "$1" | grep "^gameworld " | grep -q "\[enabled\]"' _ "${APP_LIST}"

PAGE_CODE=$(http_code GET "${PAGE_URL}" "${ADMIN_AUTH}" "${WORK_DIR}/page-admin.html")
check "K1 Seite als admin HTTP 200 (ist ${PAGE_CODE})" eq "${PAGE_CODE}" 200
check "K1 Seite als admin referenziert gameworld-main" grep -q 'gameworld-main' "${WORK_DIR}/page-admin.html"

ADMIN_BUNDLE=$(http_code GET "${BUNDLE_URL}" "${ADMIN_AUTH}" /dev/null)
check "K1 Positivkontrolle: Bundle als admin HTTP 200 (ist ${ADMIN_BUNDLE})" eq "${ADMIN_BUNDLE}" 200

if occ user:info "${KID_USER}" >/dev/null 2>&1; then
	printf 'Nutzer %s existiert schon\n' "${KID_USER}"
else
	docker compose -f "${COMPOSE_FILE}" exec -T -u www-data -e OC_PASS="${KID_PASS}" app \
		php occ user:add --password-from-env --display-name="Kind (Dev)" "${KID_USER}" >/dev/null \
		|| abort "Nutzer ${KID_USER} ließ sich nicht anlegen"
	printf 'Nutzer %s angelegt\n' "${KID_USER}"
fi
KID_ADMIN=$(occ group:list --output=json 2>/dev/null | jq -r --arg u "${KID_USER}" '(.admin // []) | index($u) // "nein"')
check "K1 ${KID_USER} ist nicht in der Gruppe admin" eq "${KID_ADMIN}" nein

# Positivkontrolle: gw-kind kann sich überhaupt anmelden. Sonst wäre ein 401
# unten ein falscher Beleg für die Sperre.
KID_LOGIN=$(http_code GET "${NEXTCLOUD_URL}/ocs/v2.php/cloud/user?format=json" "${KID_AUTH}" "${WORK_DIR}/kid-user.json")
check "K1 Positivkontrolle: ${KID_USER} meldet sich an, OCS cloud/user 200 (ist ${KID_LOGIN})" eq "${KID_LOGIN}" 200

# seit 03-02: Kinder sehen Seite und Bundle, Verwaltung bleibt gesperrt
# (AppAPI-Route ADMIN plus require_verwalter in Python).
KID_PAGE=$(http_code GET "${PAGE_URL}" "${KID_AUTH}" "${WORK_DIR}/page-kid.html")
check "K1 Seite für ${KID_USER} HTTP 200 (ist ${KID_PAGE})" eq "${KID_PAGE}" 200
KID_BUNDLE=$(http_code GET "${BUNDLE_URL}" "${KID_AUTH}" /dev/null)
check "K1 Bundle für ${KID_USER} HTTP 200 (ist ${KID_BUNDLE})" eq "${KID_BUNDLE}" 200

KID_API=$(http_code GET "${API_URL}/worlds" "${KID_AUTH}" /dev/null)
# AppAPI weist Nicht-Admins auf ADMIN-Routen vor dem Backend mit 404 ab (am Dev-Stack belegt);
# ein abgestürztes Backend (500, 503) oder curl-Fehler (000) besteht so nicht mehr (WR-08).
check "K1 Negativkontrolle: Welt-API für ${KID_USER} HTTP 404 (ist ${KID_API})" eq "${KID_API}" 404

KID_ME=$(http_code GET "${API_URL}/me" "${KID_AUTH}" "${WORK_DIR}/me-kid.json")
check "K1 /api/me für ${KID_USER} HTTP 200 (ist ${KID_ME})" eq "${KID_ME}" 200
KID_ROLE=$(jq -r '.role // empty' "${WORK_DIR}/me-kid.json" 2>/dev/null || true)
check "K1 /api/me für ${KID_USER} meldet Rolle spieler (ist ${KID_ROLE})" eq "${KID_ROLE}" spieler

ADMIN_ME=$(http_code GET "${API_URL}/me" "${ADMIN_AUTH}" "${WORK_DIR}/me-admin.json")
ADMIN_ROLE=$(jq -r '.role // empty' "${WORK_DIR}/me-admin.json" 2>/dev/null || true)
check "K1 Positivkontrolle: /api/me als admin HTTP 200 und Rolle verwalter (ist ${ADMIN_ME}, ${ADMIN_ROLE})" \
	eq "${ADMIN_ME}/${ADMIN_ROLE}" 200/verwalter

printf '\n== K2 Lebenszyklus und Parallelität ==\n'
# K2 Lebenszyklus und Parallelität
CODE_A=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/a.json" "{\"name\":\"${NAME_A}\"}")
ID_A=$(jq -r '.id // empty' "${WORK_DIR}/a.json" 2>/dev/null || true)
remember_world "${ID_A}"
CODE_B=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/b.json" "{\"name\":\"${NAME_B}\"}")
ID_B=$(jq -r '.id // empty' "${WORK_DIR}/b.json" 2>/dev/null || true)
remember_world "${ID_B}"
check "K2 POST '${NAME_A}' HTTP 201 (ist ${CODE_A})" eq "${CODE_A}" 201
check "K2 POST '${NAME_B}' HTTP 201 (ist ${CODE_B})" eq "${CODE_B}" 201
[ -n "${ID_A}" ] && [ -n "${ID_B}" ] || abort "Antworten ohne id, weitere Prüfungen sinnlos"

CONTAINER_A=$(container_of "${ID_A}")
CONTAINER_B=$(container_of "${ID_B}")
[ -n "${CONTAINER_A}" ] && [ -n "${CONTAINER_B}" ] || abort "kein Container mit Label gameworld.world_id für A oder B"

RUNNING_BOTH=$(docker ps -q --filter "label=gameworld.world_id=${ID_A}"; docker ps -q --filter "label=gameworld.world_id=${ID_B}")
check "K2 beide Container gleichzeitig running (docker ps)" eq "$(printf '%s\n' "${RUNNING_BOTH}" | grep -c .)" 2

PORT_A=$(inspect "${CONTAINER_A}" '{{index .Config.Labels "gameworld.port"}}')
PORT_B=$(inspect "${CONTAINER_B}" '{{index .Config.Labels "gameworld.port"}}')
# Beide Ports müssen Zahlen sein: ein leerer Wert (inspect gescheitert) besteht nicht (WR-08).
check "K2 Ports verschieden (A=${PORT_A}, B=${PORT_B})" sh -c \
	'printf "%s %s" "$1" "$2" | grep -Eq "^[0-9]+ [0-9]+$" && [ "$1" != "$2" ]' _ "${PORT_A}" "${PORT_B}"
for pair in "A ${CONTAINER_A} ${PORT_A}" "B ${CONTAINER_B} ${PORT_B}"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	PORTS=$(docker port "$2" 2>/dev/null || true)
	check "K2 docker port $1 zeigt 30000/udp auf Host-Port $3" \
		sh -c 'printf "%s\n" "$1" | grep -Eq "^30000/udp -> [^ ]+:$2\$"' _ "${PORTS}" "$3"
	check "K2 docker port $1 veröffentlicht nur UDP, kein TCP" \
		sh -c '! printf "%s\n" "$1" | grep -q "/tcp"' _ "${PORTS}"
	IMAGE_REF=$(inspect "$2" '{{.Config.Image}}')
	check "K2 Image-Ref $1 enthält den Luanti-5.17.0-Digest" contains "${IMAGE_REF}" "${IMAGE_DIGEST}"
done

for pair in "A ${CONTAINER_A}" "B ${CONTAINER_B}"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	waited=0
	while ! docker logs "$2" 2>&1 | grep -q 'listening on'; do
		[ "${waited}" -lt 30 ] || break
		sleep 1
		waited=$((waited + 1))
	done
	check "K2 Log $1 enthält binnen 30 s 'listening on'" \
		sh -c 'docker logs "$1" 2>&1 | grep -q "listening on"' _ "$2"
done

http_code GET "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/list.json" >/dev/null
LISTED=$(jq -r --arg a "${ID_A}" --arg b "${ID_B}" \
	'[.worlds[] | select(.id == $a or .id == $b) | .docker_status] | join(" ")' "${WORK_DIR}/list.json" 2>/dev/null || true)
check "K2 Liste zeigt beide Welten mit Status running (ist '${LISTED}')" eq "${LISTED}" "running running"

printf '\n== K3 Limits ==\n'
# K3 Limits und Härtung (vor dem Löschen aus K2)
for pair in "A ${CONTAINER_A}" "B ${CONTAINER_B}"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	c=$2
	check "K3 $1 Memory 536870912" eq "$(inspect "$c" '{{.HostConfig.Memory}}')" 536870912
	check "K3 $1 MemorySwap 536870912" eq "$(inspect "$c" '{{.HostConfig.MemorySwap}}')" 536870912
	check "K3 $1 PidsLimit 128" eq "$(inspect "$c" '{{.HostConfig.PidsLimit}}')" 128
	check "K3 $1 NanoCpus 1000000000" eq "$(inspect "$c" '{{.HostConfig.NanoCpus}}')" 1000000000
	check "K3 $1 CapDrop [\"ALL\"]" eq "$(inspect "$c" '{{json .HostConfig.CapDrop}}')" '["ALL"]'
	check "K3 $1 SecurityOpt enthält no-new-privileges:true" \
		contains "$(inspect "$c" '{{json .HostConfig.SecurityOpt}}')" '"no-new-privileges:true"'
	check "K3 $1 ReadonlyRootfs true" eq "$(inspect "$c" '{{.HostConfig.ReadonlyRootfs}}')" true
	check "K3 $1 Privileged false" eq "$(inspect "$c" '{{.HostConfig.Privileged}}')" false
	check "K3 $1 Config.User 30000:30000" eq "$(inspect "$c" '{{.Config.User}}')" 30000:30000
	MOUNT_TYPES=$(docker inspect "$c" | jq -r '[.[0].Mounts[].Type] | unique | join(",")')
	FOREIGN=$(docker inspect "$c" | jq -r '[.[0].Mounts[] | select(.Type != "volume" and .Type != "tmpfs")] | length')
	BINDS=$(docker inspect "$c" | jq -r '.[0].HostConfig.Binds // [] | length')
	check "K3 $1 keine Bind-Mounts (Mount-Typen '${MOUNT_TYPES}', Binds ${BINDS})" \
		eq "${FOREIGN}:${BINDS}:$([ -n "${MOUNT_TYPES}" ] && printf ja)" "0:0:ja"
done
CODE_MEM=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/mem.json" '{"name":"x","mem_limit":"8g"}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/mem.json" 2>/dev/null || true)"
check "K3 Negativkontrolle: POST mit mem_limit 8g HTTP 422 (ist ${CODE_MEM})" eq "${CODE_MEM}" 422

printf '\n== K4 Privat per Default ==\n'
# K4 Privat per Default, gelesen per docker cp und tar
# MSYS_NO_PATHCONV: Git Bash würde den Containerpfad sonst in einen Windows-Pfad umschreiben.
MSYS_NO_PATHCONV=1 docker cp "${CONTAINER_A}:/var/lib/minetest/minetest.conf" - >"${WORK_DIR}/conf.tar" 2>/dev/null || true
tar -xOf "${WORK_DIR}/conf.tar" >"${WORK_DIR}/minetest.conf" 2>/dev/null || true
CONF="${WORK_DIR}/minetest.conf"
check "K4 Positivkontrolle: minetest.conf per docker cp gelesen (nicht leer)" test -s "${CONF}"
check "K4 server_announce = false" grep -qx 'server_announce = false' "${CONF}"
check "K4 disallow_empty_password = true" grep -qx 'disallow_empty_password = true' "${CONF}"
check "K4 default_password mit nicht leerem Wert" grep -Eq '^default_password = [^ ]+' "${CONF}"
# Seit 02-01 Kreativ-Preset mit fly, fast: genau eine default_privs-Zeile, sie beginnt
# mit interact, shout und enthält keine Admin-Rechte.
PRIVS_LINES=$(grep -c '^default_privs[[:space:]]*=' "${CONF}" 2>/dev/null || true)
check "K4 genau eine default_privs-Zeile (ist ${PRIVS_LINES})" eq "${PRIVS_LINES}" 1
check "K4 default_privs beginnt mit interact, shout und ohne Admin-Rechte" \
	sh -c 'line=$(grep "^default_privs[[:space:]]*=" "$1") || exit 1
		case "$line" in "default_privs = interact, shout"*) ;; *) exit 1 ;; esac
		! printf "%s\n" "${line#*=}" | grep -Eqw "server|privs|ban|kick|give|password|protection_bypass"' _ "${CONF}"
check "K4 keine Zeile name =" sh -c '! grep -Eq "^name[[:space:]]*=" "$1"' _ "${CONF}"
TAR_LIST=$(tar -tvf "${WORK_DIR}/conf.tar" 2>/dev/null || true)
printf 'tar -tv: %s\n' "$(printf '%s' "${TAR_LIST}" | awk '{print $1, $2}')"
check "K4 conf gehört root und hat Modus -r--r--r--" \
	sh -c 'printf "%s\n" "$1" | grep -Eq "^-r--r--r-- (root|0)/(root|0) "' _ "${TAR_LIST}"

CODE_ANN=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/ann.json" '{"name":"x","server_announce":true}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/ann.json" 2>/dev/null || true)"
check "K4 Negativkontrolle: POST mit server_announce true HTTP 422 (ist ${CODE_ANN})" eq "${CODE_ANN}" 422
CODE_INJ=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/inj.json" '{"name":"Welt\nserver_announce = true"}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/inj.json" 2>/dev/null || true)"
check "K4 Negativkontrolle: Weltname mit Zeilenumbruch HTTP 422 (ist ${CODE_INJ})" eq "${CODE_INJ}" 422

# Die Page Visibility API des Browsers (Polling seit 02-04) ist keine
# Sichtbarkeitsoption einer Welt; nur diese beiden Namen werden ausgeblendet,
# jedes andere Vorkommen in derselben Zeile zählt weiter.
strip_page_visibility() {
	sed -E 's/document\.visibilityState|visibilitychange//g' | grep -iE 'announce|serverlist|visibility' || true
}
STATIC_HITS=$(grep -rniE 'announce|serverlist|visibility' "${REPO_ROOT}/frontend/src" "${REPO_ROOT}/appinfo/info.xml" \
	| strip_page_visibility)
check "K4 statisch: kein announce/serverlist/visibility in frontend/src und info.xml" empty "${STATIC_HITS}"
check "K4 Positivkontrolle: der Filter lässt eine echte Sichtbarkeitsoption durch" \
	nonempty "$(printf '%s\n' "if (document.visibilityState) world.visibility = 'public'" | strip_page_visibility)"
CONTROL_HITS=$(grep -rniE 'announce|serverlist|visibility' "${REPO_ROOT}/src/gameworld/provisioner/luanti_conf.py" || true)
check "K4 Positivkontrolle: dasselbe grep findet die Keys in luanti_conf.py" nonempty "${CONTROL_HITS}"

# Lebenszyklus aus K2 zu Ende: stoppen, starten, löschen
printf '\n== K2 Stoppen, Starten, Löschen ==\n'
CODE=$(http_code POST "${API_URL}/worlds/${ID_A}/stop" "${ADMIN_AUTH}" /dev/null)
check "K2 POST stop A HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 A State.Running false" wait_running "${CONTAINER_A}" false 35
check "K2 B läuft weiter, State.Running true" eq "$(inspect "${CONTAINER_B}" '{{.State.Running}}')" true
CODE=$(http_code POST "${API_URL}/worlds/${ID_A}/start" "${ADMIN_AUTH}" /dev/null)
check "K2 POST start A HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K2 A State.Running wieder true" wait_running "${CONTAINER_A}" true 30

NAME_CA=$(inspect "${CONTAINER_A}" '{{.Name}}' | sed 's:^/::')
NAME_CB=$(inspect "${CONTAINER_B}" '{{.Name}}' | sed 's:^/::')
for pair in "A ${ID_A}" "B ${ID_B}"; do
	# shellcheck disable=SC2086
	set -- ${pair}
	CODE=$(http_code DELETE "${API_URL}/worlds/$2" "${ADMIN_AUTH}" /dev/null)
	check "K2 DELETE $1 HTTP 204 (ist ${CODE})" eq "${CODE}" 204
done
LEFT_CONTAINERS=$(docker ps -a --format '{{.Names}}' | grep -x -e "${NAME_CA}" -e "${NAME_CB}" || true)
check "K2 docker ps -a ohne die beiden Container" empty "${LEFT_CONTAINERS}"
LEFT_VOLUMES=$(docker volume ls -q | grep -x -e "${NAME_CA}" -e "${NAME_CB}" || true)
check "K2 docker volume ls ohne die beiden Volumes" empty "${LEFT_VOLUMES}"

printf '\n== K5 Proxy und Setup-Check ==\n'
# K5 Proxy-Scope, Loopback-Bindung, Setup-Check mit gestopptem Proxy
PING=$(curl -s -o /dev/null -w '%{http_code}' "${DOCKER_PROXY_URL}/_ping" 2>/dev/null || printf '000')
check "K5 Positivkontrolle: Proxy /_ping HTTP 200 (ist ${PING})" eq "${PING}" 200
EXEC=$(curl -s -X POST -o /dev/null -w '%{http_code}' "${DOCKER_PROXY_URL}/exec/x/start" 2>/dev/null || printf '000')
check "K5 Proxy POST /exec/x/start HTTP 403 (ist ${EXEC})" eq "${EXEC}" 403
INFO=$(curl -s -o /dev/null -w '%{http_code}' "${DOCKER_PROXY_URL}/info" 2>/dev/null || printf '000')
check "K5 Proxy /info HTTP 403 (ist ${INFO})" eq "${INFO}" 403
HOST_IPS=$(docker inspect "${PROXY_CONTAINER}" | jq -r '[.[0].HostConfig.PortBindings[][] | .HostIp] | unique | join(",")')
check "K5 Proxy-Port nur auf 127.0.0.1 gebunden (HostIp '${HOST_IPS}')" eq "${HOST_IPS}" 127.0.0.1
check "K5 docker port zeigt nur 127.0.0.1" \
	sh -c 'p=$(docker port "$1"); [ -n "$p" ] && ! printf "%s\n" "$p" | grep -v "127.0.0.1:" | grep -q .' _ "${PROXY_CONTAINER}"

http_code GET "${API_URL}/setup-check" "${ADMIN_AUTH}" "${WORK_DIR}/sc1.json" >/dev/null
check "K5 setup-check vorher \"ok\":true" eq "$(jq -r '.ok' "${WORK_DIR}/sc1.json" 2>/dev/null)" true

printf 'stoppe %s\n' "${PROXY_SERVICE}"
PROXY_STOPPED=1
docker compose -f "${COMPOSE_FILE}" stop "${PROXY_SERVICE}" >/dev/null 2>&1 || true
check "K5 Proxy wirklich gestoppt (State exited)" \
	eq "$(docker compose -f "${COMPOSE_FILE}" ps -a "${PROXY_SERVICE}" --format '{{.State}}' 2>/dev/null)" exited

SC_CODE=$(http_code GET "${API_URL}/setup-check" "${ADMIN_AUTH}" "${WORK_DIR}/sc2.json")
check "K5 setup-check bei gestopptem Proxy HTTP 200 (ist ${SC_CODE})" eq "${SC_CODE}" 200
check "K5 setup-check bei gestopptem Proxy \"ok\":false" eq "$(jq -r '.ok' "${WORK_DIR}/sc2.json" 2>/dev/null)" false
check "K5 setup-check nennt gameworld-docker-proxy" grep -q 'gameworld-docker-proxy' "${WORK_DIR}/sc2.json"
printf 'Meldung: %s\n' "$(jq -r '[.items[] | select(.ok == false) | .message] | join(" | ")' "${WORK_DIR}/sc2.json" 2>/dev/null)"

CODE_DOWN=$(http_code POST "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/down.json" '{"name":"Abnahme Proxy"}')
remember_world "$(jq -r '.id // empty' "${WORK_DIR}/down.json" 2>/dev/null || true)"
check "K5 POST /api/worlds bei gestopptem Proxy HTTP 503 (ist ${CODE_DOWN})" eq "${CODE_DOWN}" 503
DETAIL_DOWN=$(jq -r '.detail // empty' "${WORK_DIR}/down.json" 2>/dev/null || true)
check "K5 503 mit deutscher Meldung ('${DETAIL_DOWN}')" \
	sh -c 'printf "%s" "$1" | grep -q -e "Bitte" -e "prüfen" -e "erreicht"' _ "${DETAIL_DOWN}"

printf 'starte %s\n' "${PROXY_SERVICE}"
start_proxy
waited=0
SC_OK=false
while [ "${waited}" -le 10 ]; do
	http_code GET "${API_URL}/setup-check" "${ADMIN_AUTH}" "${WORK_DIR}/sc3.json" >/dev/null
	SC_OK=$(jq -r '.ok' "${WORK_DIR}/sc3.json" 2>/dev/null || printf 'false')
	[ "${SC_OK}" = "true" ] && break
	sleep 1
	waited=$((waited + 1))
done
PROXY_STOPPED=0
check "K5 setup-check nach Neustart binnen 10 s \"ok\":true (nach ${waited} s)" eq "${SC_OK}" true

# Gewolltes Verhalten aus 01-03: Ein gescheiterter POST bleibt als Zeile mit
# op_state failed und der Fehlermeldung sichtbar, ohne Container, und lässt sich
# löschen.
http_code GET "${API_URL}/worlds" "${ADMIN_AUTH}" "${WORK_DIR}/post.json" >/dev/null
GHOST=$(jq -r '[.worlds[]? | select(.name == "Abnahme Proxy") | "\(.op_state)/\(.docker_status)"] | join(",")' \
	"${WORK_DIR}/post.json" 2>/dev/null || printf 'unbekannt')
check "K5 der gescheiterte POST steht höchstens als failed ohne Container in der Liste (ist '${GHOST}')" \
	sh -c '[ -z "$1" ] || [ "$1" = "failed/missing" ]' _ "${GHOST}"
for ghost_id in $(jq -r '.worlds[]? | select(.name == "Abnahme Proxy") | .id' "${WORK_DIR}/post.json" 2>/dev/null || true); do
	remember_world "${ghost_id}"
	check "K5 Positivkontrolle: Container der gescheiterten Welt existiert nicht" empty "$(container_of "${ghost_id}")"
	CODE=$(http_code DELETE "${API_URL}/worlds/${ghost_id}" "${ADMIN_AUTH}" /dev/null)
	check "K5 gescheiterte Welt per DELETE entfernbar HTTP 204 (ist ${CODE})" eq "${CODE}" 204
done

DOCKER_IMPORTS=$(grep -rln "import docker\|from docker" "${REPO_ROOT}/src/gameworld" | grep -v provisioner/ || true)
check "K5 statisch: docker-py nur unter provisioner/ importiert" empty "${DOCKER_IMPORTS}"
CONTROL_IMPORTS=$(grep -rln "import docker\|from docker" "${REPO_ROOT}/src/gameworld" | grep provisioner/ || true)
check "K5 Positivkontrolle: dasselbe grep findet die Importe im Provisioner" nonempty "${CONTROL_IMPORTS}"

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 1 erfolgreich\n'
