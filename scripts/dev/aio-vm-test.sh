#!/bin/sh
# Repeatable install test of Gameworld on Nextcloud All-in-One with HaRP (plan 06-15,
# D-20, 06-RESEARCH section 9 and F-06). Runs as root on a short-lived cloud VM AFTER
# AIO is fully set up: domain with TLS, Nextcloud installed, optional container "HaRP"
# switched on (AppAPI then creates the daemon harp_aio by itself).
#
#   sh aio-vm-test.sh --info-xml ./info-aio.xml [--tag 1.0.0-rc.2] [--url https://cloud.example]
#   sh aio-vm-test.sh --cleanup
#
# --info-xml  copy of appinfo/info.xml whose image-tag is the tag under test (registry
#             ghcr.io and image street1983nk/gameworld unchanged); harp-install.sh
#             --source ghcr writes exactly such a copy to .dev/info-harp.xml.
# --tag       expected image-tag (default 1.0.0-rc.2); the script refuses a copy with
#             another tag, so the run never proves a different image than intended.
# --url       public Nextcloud URL; default overwrite.cli.url of the instance.
#
# Sequence, each step with an explicit check:
#   1. AIO containers present, daemon harp_aio registered and HaRP.
#   2. Register Gameworld on harp_aio from the info.xml copy (--wait-finish), BEFORE the
#      Docker proxy exists: this is the state of a fresh store installation.
#   3. Test account (admin group, random password, never printed) via occ.
#   4. Setup check without proxy: must fail with a proxy finding and must detect the
#      network nextcloud-aio itself (network_probe, Docker DNS PTR); the offered
#      docker run line and Compose file must name that network.
#   5. Start the scoped Docker proxy with docker run in nextcloud-aio (name
#      gameworld-docker-proxy, flags as scripts/dev/compose.yaml, NO host port, T-06-63).
#   6. Setup check again: no error.
#   7. Create a world, wait for running, check the UDP port via docker port and ss -uln.
#   8. Summary without passwords (T-06-64).
#
# --cleanup removes the test world, test account, Docker proxy and the app (with data).
# Then delete the VM and the domain (D-20).
#
# State between run and cleanup lives in /root/.gameworld-aio-test (0700): user name,
# world id and the curl netrc file with the test password (0600). Nothing of it is printed.
set -eu

NC_CONTAINER=nextcloud-aio-nextcloud
HARP_CONTAINER=nextcloud-aio-harp
AIO_NETWORK=nextcloud-aio
DAEMON=harp_aio
APP_ID=gameworld
EXAPP_CONTAINER=nc_app_gameworld
PROXY_NAME=gameworld-docker-proxy
PROXY_IMAGE=tecnativa/docker-socket-proxy:v0.5.0@sha256:1f5038b54f06c3e18422902cf00ba21803d1c97805aae032e5e6673d532d3459
DOCKER_URL=tcp://${PROXY_NAME}:2375
IMAGE_NAME=street1983nk/gameworld
TEST_USER=gw-aio-test
WORLD_NAME="AIO Prüfwelt"
STATE_DIR=/root/.gameworld-aio-test
NETRC=${STATE_DIR}/netrc
INFO_IN_CONTAINER=/tmp/gameworld-info-aio.xml

TAG=1.0.0-rc.2
INFO_XML=
NC_URL=
MODE=run
FAILS=0

say() { printf '%s\n' "$1"; }
die() {
	printf 'aio-vm-test: ABBRUCH: %s\n' "$1" >&2
	exit 1
}
pass() { printf 'OK      %s\n' "$1"; }
fail() {
	printf 'FEHLER  %s\n' "$1"
	FAILS=$((FAILS + 1))
}
check() {
	label=$1
	shift
	if "$@"; then pass "${label}"; else fail "${label}"; fi
}

# occ as www-data, the way the AIO documentation calls it.
occ() {
	docker exec --user www-data "${NC_CONTAINER}" php occ "$@"
}

# api METHOD PATH OUTFILE [JSON] -> HTTP code; credentials only from the netrc file.
api() {
	if [ -n "${4:-}" ]; then
		curl -s --netrc-file "${NETRC}" -H 'OCS-APIRequest: true' -H 'Accept: application/json' \
			-H 'Content-Type: application/json' -X "$1" -d "$4" -o "$3" -w '%{http_code}' \
			"${API_URL}$2" 2>/dev/null || printf '000'
	else
		curl -s --netrc-file "${NETRC}" -H 'OCS-APIRequest: true' -H 'Accept: application/json' \
			-X "$1" -o "$3" -w '%{http_code}' "${API_URL}$2" 2>/dev/null || printf '000'
	fi
}

new_password() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 24
		return
	fi
	od -vAn -N24 -tx1 /dev/urandom | tr -d ' \n'
}

state_get() {
	[ -f "${STATE_DIR}/$1" ] && cat "${STATE_DIR}/$1" || true
}

while [ "$#" -gt 0 ]; do
	case "$1" in
	--cleanup) MODE=cleanup ;;
	--info-xml)
		[ "$#" -ge 2 ] || die "--info-xml braucht einen Pfad"
		INFO_XML=$2
		shift
		;;
	--tag)
		[ "$#" -ge 2 ] || die "--tag braucht einen Wert"
		TAG=$2
		shift
		;;
	--url)
		[ "$#" -ge 2 ] || die "--url braucht eine Adresse"
		NC_URL=$2
		shift
		;;
	*) die "unbekannte Option $1 (--info-xml <pfad>, --tag <tag>, --url <url>, --cleanup)" ;;
	esac
	shift
done

[ "$(id -u)" = 0 ] || die "als root ausführen (docker exec, ss)"
for tool in docker curl jq grep sed; do
	command -v "${tool}" >/dev/null 2>&1 || die "Werkzeug ${tool} fehlt (Debian/Ubuntu: apt-get install -y ${tool})"
done
printf '%s\n' "${TAG}" | grep -Eq '^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$' || die "ungültiges Tag ${TAG}"
docker inspect "${NC_CONTAINER}" >/dev/null 2>&1 || die "Container ${NC_CONTAINER} fehlt (AIO nicht fertig eingerichtet?)"

if [ -z "${NC_URL}" ]; then
	NC_URL=$(occ config:system:get overwrite.cli.url 2>/dev/null | tr -d '\r' || true)
fi
NC_URL=${NC_URL%/}
case "${NC_URL}" in
https://*) ;;
*) die "keine https-Adresse der Instanz (${NC_URL:-leer}); mit --url https://<domain> angeben" ;;
esac
API_URL="${NC_URL}/index.php/apps/app_api/proxy/${APP_ID}/api"
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

# Cleanup ---------------------------------------------------------------
if [ "${MODE}" = cleanup ]; then
	WORLD_ID=$(state_get world_id)
	if [ -n "${WORLD_ID}" ] && [ -f "${NETRC}" ]; then
		CODE=$(api DELETE "/worlds/${WORLD_ID}" "${WORK}/del.json")
		say "Welt ${WORLD_ID} per API gelöscht (HTTP ${CODE})"
	fi
	if [ -n "${WORLD_ID}" ]; then
		for c in $(docker ps -aq --filter "label=gameworld.world_id=${WORLD_ID}"); do
			docker rm -f -v "${c}" >/dev/null 2>&1 || true
		done
		for v in $(docker volume ls -q | grep -e "-${WORLD_ID}\$" || true); do
			docker volume rm "${v}" >/dev/null 2>&1 || true
		done
	fi
	occ user:delete "${TEST_USER}" >/dev/null 2>&1 && say "Testkonto ${TEST_USER} gelöscht" || true
	if occ app_api:app:list 2>/dev/null | grep -q "^${APP_ID} "; then
		occ app_api:app:unregister "${APP_ID}" --rm-data --silent >/dev/null 2>&1 ||
			occ app_api:app:unregister "${APP_ID}" --rm-data --force --silent >/dev/null 2>&1 || true
		say "App ${APP_ID} samt Daten entfernt"
	fi
	docker rm -f "${PROXY_NAME}" >/dev/null 2>&1 && say "Docker-Proxy ${PROXY_NAME} entfernt" || true
	LEFT=$(docker ps -aq --filter "label=gameworld.managed=true" | wc -l | tr -d ' ')
	say "verbleibende Gameworld-Welt-Container: ${LEFT}"
	rm -rf "${STATE_DIR}"
	say "Aufräumen fertig. Jetzt VM und Domain löschen (D-20)."
	exit 0
fi

# Run -------------------------------------------------------------------
[ -n "${INFO_XML}" ] || die "--info-xml <pfad> fehlt (Kopie der info.xml mit image-tag ${TAG})"
[ -f "${INFO_XML}" ] || die "${INFO_XML} nicht gefunden"
grep -q '<registry>ghcr.io</registry>' "${INFO_XML}" || die "die info.xml-Kopie nennt nicht die Registry ghcr.io"
grep -q "<image>${IMAGE_NAME}</image>" "${INFO_XML}" || die "die info.xml-Kopie nennt nicht das Image ${IMAGE_NAME}"
grep -q "<image-tag>${TAG}</image-tag>" "${INFO_XML}" || die "die info.xml-Kopie hat nicht das image-tag ${TAG}"
EXPECTED_IMAGE="ghcr.io/${IMAGE_NAME}:${TAG}"

say "== 1 AIO und HaRP =="
say "Instanz: ${NC_URL}"
NC_VERSION=$(curl -s "${NC_URL}/status.php" | jq -r '.versionstring // empty' 2>/dev/null || true)
say "Nextcloud ${NC_VERSION:-unbekannt}"
check "Container ${HARP_CONTAINER} läuft" \
	sh -c '[ "$(docker inspect --format "{{.State.Running}}" "$1" 2>/dev/null)" = true ]' _ "${HARP_CONTAINER}"
check "Netz ${AIO_NETWORK} vorhanden" sh -c 'docker network inspect "$1" >/dev/null 2>&1' _ "${AIO_NETWORK}"
occ app_api:daemon:list >"${WORK}/daemons.txt" 2>/dev/null || true
check "Daemon ${DAEMON} registriert und HaRP" \
	awk -F'|' -v d="${DAEMON}" '{ for (i = 1; i <= NF; i++) gsub(/^ +| +$/, "", $i) }
		$3 == d && $9 == "yes" { found = 1 } END { exit !found }' "${WORK}/daemons.txt"
[ "${FAILS}" = 0 ] || die "AIO ist nicht bereit (HaRP im AIO-Interface einschalten)"
docker inspect "${PROXY_NAME}" >/dev/null 2>&1 &&
	die "${PROXY_NAME} existiert schon; zuerst sh aio-vm-test.sh --cleanup"
occ app_api:app:list 2>/dev/null | grep -q "^${APP_ID} " &&
	die "${APP_ID} ist schon registriert; zuerst sh aio-vm-test.sh --cleanup"

say "== 2 Gameworld registrieren (ohne Docker-Proxy, wie eine frische Store-Installation) =="
docker cp "${INFO_XML}" "${NC_CONTAINER}:${INFO_IN_CONTAINER}"
docker exec "${NC_CONTAINER}" chmod 0644 "${INFO_IN_CONTAINER}"
occ app_api:app:register "${APP_ID}" "${DAEMON}" --info-xml "${INFO_IN_CONTAINER}" \
	--env "GAMEWORLD_DOCKER_URL=${DOCKER_URL}" --wait-finish
occ app_api:app:enable "${APP_ID}" >/dev/null 2>&1 || true
occ app_api:app:list >"${WORK}/apps.txt" 2>/dev/null || true
say "app_api:app:list: $(grep "^${APP_ID} " "${WORK}/apps.txt" | tr -d '\r')"
check "${APP_ID} registriert und aktiviert" sh -c 'grep "^gameworld " "$1" | grep -q enabled' _ "${WORK}/apps.txt"
EXAPP_IMAGE=$(docker inspect --format '{{.Config.Image}}' "${EXAPP_CONTAINER}" 2>/dev/null || true)
check "ExApp-Container aus ${EXPECTED_IMAGE} (ist ${EXAPP_IMAGE:-leer})" [ "${EXAPP_IMAGE}" = "${EXPECTED_IMAGE}" ]
DIGESTS=$(docker image inspect --format '{{join .RepoDigests " "}}' "$(docker inspect --format '{{.Image}}' "${EXAPP_CONTAINER}" 2>/dev/null)" 2>/dev/null || true)
say "Image-Digest: ${DIGESTS:-unbekannt}"
check "ExApp-Container läuft als 10001:10001" \
	[ "$(docker inspect --format '{{.Config.User}}' "${EXAPP_CONTAINER}" 2>/dev/null)" = 10001:10001 ]
EXAPP_NETS=$(docker inspect --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "${EXAPP_CONTAINER}" 2>/dev/null || true)
check "ExApp-Container im Netz ${AIO_NETWORK} (ist ${EXAPP_NETS})" sh -c 'case " $1" in *" $2 "*) exit 0 ;; esac; exit 1' _ "${EXAPP_NETS}" "${AIO_NETWORK}"
check "ExApp-Container ohne Docker-Socket" \
	sh -c '! docker inspect --format "{{range .Mounts}}{{.Source}} {{end}}" "$1" | grep -q docker.sock' _ "${EXAPP_CONTAINER}"
# F-06: AIO HaRP deploys in direct mode without HP_SHARED_KEY; only presence is printed.
if docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${EXAPP_CONTAINER}" | grep -q '^HP_SHARED_KEY='; then
	say "Hinweis: HP_SHARED_KEY im ExApp-Container gesetzt (Wert nicht ausgegeben)"
else
	say "Hinweis: kein HP_SHARED_KEY im ExApp-Container (Direktmodus, F-06)"
fi

say "== 3 Testkonto =="
mkdir -p "${STATE_DIR}"
chmod 0700 "${STATE_DIR}"
PASSWORD=$(new_password)
HOST=$(printf '%s\n' "${NC_URL}" | sed -e 's|^https://||' -e 's|[/:].*$||')
(
	umask 077
	printf 'machine %s login %s password %s\n' "${HOST}" "${TEST_USER}" "${PASSWORD}" >"${NETRC}"
)
occ user:delete "${TEST_USER}" >/dev/null 2>&1 || true
# Password over stdin, so it never shows up in a process list or in docker inspect.
printf '%s\n' "${PASSWORD}" | docker exec -i --user www-data "${NC_CONTAINER}" sh -c \
	'IFS= read -r OC_PASS && export OC_PASS && exec php occ user:add --password-from-env --display-name "Gameworld AIO-Test" --group admin "$1"' \
	_ "${TEST_USER}" >/dev/null
unset PASSWORD
check "Testkonto ${TEST_USER} in der Gruppe admin" sh -c 'docker exec --user www-data "$1" php occ user:info "$2" | grep -q "admin"' _ "${NC_CONTAINER}" "${TEST_USER}"
i=0
until [ "$(api GET /me "${WORK}/me.json")" = 200 ]; do
	i=$((i + 1))
	[ "${i}" -lt 60 ] || break
	sleep 3
done
check "GET /api/me über den AppAPI-Proxy HTTP 200, Rolle verwalter" \
	[ "$(jq -r .role "${WORK}/me.json" 2>/dev/null)" = verwalter ]

say "== 4 Setup-Check ohne Docker-Proxy =="
CODE=$(api GET /setup-check "${WORK}/sc1.json")
say "Befunde: $(jq -c '[.items[]? | select(.ok == false) | .id]' "${WORK}/sc1.json" 2>/dev/null)"
say "Proxy-Befehle: $(jq -c '[.proxy_commands[]? | {id, network}]' "${WORK}/sc1.json" 2>/dev/null)"
check "Setup-Check HTTP 200 mit ok false (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .ok "$2")" = false ]' _ "${CODE}" "${WORK}/sc1.json"
check "Befund proxy_dns, proxy_refused oder proxy_timeout" \
	[ "$(jq -r '[.items[]? | select(.ok == false and (.id == "proxy_dns" or .id == "proxy_refused" or .id == "proxy_timeout"))] | length > 0' "${WORK}/sc1.json" 2>/dev/null)" = true ]
check "Netz selbst erkannt: proxy_commands[0] = detected ${AIO_NETWORK}" \
	[ "$(jq -r '.proxy_commands[0] | "\(.id) \(.network)"' "${WORK}/sc1.json" 2>/dev/null)" = "detected ${AIO_NETWORK}" ]
check "angezeigter docker-run-Befehl und Compose-Datei nennen ${AIO_NETWORK} (external)" \
	[ "$(jq -r --arg n "${AIO_NETWORK}" '.proxy_commands[0] | (.command | contains("--network " + $n)) and
		(.compose | contains($n)) and (.compose | contains("external: true"))' "${WORK}/sc1.json" 2>/dev/null)" = true ]
check "angezeigter Befehl ohne Host-Port (-p)" \
	[ "$(jq -r '.proxy_commands[0].command | test(" -p |--publish")' "${WORK}/sc1.json" 2>/dev/null)" = false ]

say "== 5 Docker-Proxy im Netz ${AIO_NETWORK} starten (kein Host-Port) =="
docker run -d --name "${PROXY_NAME}" --restart unless-stopped --network "${AIO_NETWORK}" \
	-v /var/run/docker.sock:/var/run/docker.sock:ro \
	-e CONTAINERS=1 -e IMAGES=1 -e POST=1 -e VOLUMES=1 \
	-e EXEC=0 -e INFO=0 -e NETWORKS=0 -e BUILD=0 -e SYSTEM=0 -e SECRETS=0 -e SWARM=0 \
	-e NODES=0 -e SERVICES=0 -e TASKS=0 -e PLUGINS=0 -e CONFIGS=0 -e DISTRIBUTION=0 -e AUTH=0 \
	"${PROXY_IMAGE}" >/dev/null
check "${PROXY_NAME} läuft" sh -c '[ "$(docker inspect --format "{{.State.Running}}" "$1")" = true ]' _ "${PROXY_NAME}"
check "${PROXY_NAME} ohne Host-Port" sh -c '[ -z "$(docker port "$1")" ]' _ "${PROXY_NAME}"

say "== 6 Setup-Check mit Docker-Proxy =="
i=0
while :; do
	api GET /setup-check "${WORK}/sc2.json" >/dev/null
	[ "$(jq -r '.ok and ([.items[]? | select(.ok == false and .severity == "error")] | length == 0)' "${WORK}/sc2.json" 2>/dev/null)" = true ] && break
	i=$((i + 1))
	[ "${i}" -lt 20 ] || break
	sleep 3
done
say "Warnungen: $(jq -c '[.items[]? | select(.ok == false) | .id]' "${WORK}/sc2.json" 2>/dev/null)"
check "Setup-Check ohne Fehler" \
	[ "$(jq -r '.ok and ([.items[]? | select(.ok == false and .severity == "error")] | length == 0)' "${WORK}/sc2.json" 2>/dev/null)" = true ]
say "Firewall-Portbereich laut Setup-Check: $(jq -r '.firewall.port_range // "unbekannt"' "${WORK}/sc2.json" 2>/dev/null)"

say "== 7 Welt anlegen und UDP-Port prüfen =="
CODE=$(api POST /worlds "${WORK}/new.json" "{\"name\":\"${WORLD_NAME}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK}/new.json" 2>/dev/null || true)
[ -z "${WORLD_ID}" ] || printf '%s\n' "${WORLD_ID}" >"${STATE_DIR}/world_id"
check "POST /api/worlds HTTP 201 (ist ${CODE})" [ "${CODE}" = 201 ]
STATUS=
i=0
while [ -n "${WORLD_ID}" ]; do
	api GET /worlds "${WORK}/worlds.json" >/dev/null
	STATUS=$(jq -r --arg id "${WORLD_ID}" '.worlds[]? | select(.id == $id) | .status' "${WORK}/worlds.json" 2>/dev/null || true)
	[ "${STATUS}" = running ] && break
	i=$((i + 1))
	[ "${i}" -lt 60 ] || break
	sleep 3
done
check "Welt running binnen 180 s (ist ${STATUS:-leer})" [ "${STATUS}" = running ]
PORT=$(jq -r --arg id "${WORLD_ID}" '.worlds[]? | select(.id == $id) | .port' "${WORK}/worlds.json" 2>/dev/null || true)
CONTAINER=$(docker ps -q --filter "label=gameworld.world_id=${WORLD_ID}" | head -n 1)
say "Welt-Port laut API: ${PORT:-leer}"
say "docker port: $(docker port "${CONTAINER}" 2>/dev/null | tr '\n' ' ')"
check "docker port zeigt ${PORT}/udp" sh -c 'docker port "$1" 2>/dev/null | grep -q ":$2\$"' _ "${CONTAINER}" "${PORT}"
if command -v ss >/dev/null 2>&1; then
	check "ss -uln: UDP ${PORT} lauscht" sh -c 'ss -Huln | grep -q ":$1 "' _ "${PORT}"
else
	say "Hinweis: ss fehlt, UDP-Prüfung nur per docker port"
fi
say "Beitritt optional: Luanti-Client 5.17 auf ${HOST}:${PORT} (Konto ${TEST_USER} einladen); UDP ${PORT} in der VM-Firewall öffnen"

say "== 8 Zusammenfassung =="
say "Nextcloud ${NC_VERSION:-unbekannt}, Daemon ${DAEMON}, Image ${EXAPP_IMAGE:-leer}"
say "Netz der ExApp: ${EXAPP_NETS}; Setup-Check erkannt: $(jq -r '.proxy_commands[0] | "\(.id) \(.network)"' "${WORK}/sc1.json" 2>/dev/null)"
say "Welt ${WORLD_ID:-keine}: ${STATUS:-leer}, UDP ${PORT:-leer}"
if [ "${FAILS}" = 0 ]; then
	say "AIO-Prüflauf erfolgreich (keine Passwörter in dieser Ausgabe)"
	say "Danach: sh aio-vm-test.sh --cleanup, dann VM und Domain löschen"
	exit 0
fi
say "AIO-Prüflauf mit ${FAILS} Fehlern; Ausgabe an Claude geben, danach --cleanup"
exit 1
