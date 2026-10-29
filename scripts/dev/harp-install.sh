#!/bin/sh
# Installs Gameworld through a real HaRP daemon from a local registry
# into a separate test Nextcloud (plan 06-12, 06-RESEARCH 5.2 and 9). This is the
# path of a store installation without archive download and signature check: AppAPI
# reads an info.xml, HaRP pulls the image and creates the ExApp container.
# No push to ghcr.io, no certificate needed.
#
#   sh scripts/dev/harp-install.sh              install (idempotent)
#   sh scripts/dev/harp-install.sh --uninstall  remove registration, daemon and the
#                                               whole test stack including volumes
#
# The test instance (harp.compose.yaml) is separate from the dev stack: own
# Nextcloud, own Docker proxy, own network. This script never touches the dev Nextcloud on 8091,
# its manual_install registration and its worlds.
#
# Sequence: key in .dev/harp.key (gitignored, never in the repository), start
# the stack, prepare the test Nextcloud (app_api, Talk), build the image and push it to
# localhost:5000, a COPY of info.xml with registry localhost:5000
# to .dev/info-harp.xml (the original stays unchanged, T-06-55), check both
# directions of the front, re-register the daemon harp_dev (idempotent:
# first remove an existing registration and daemon of the same name), register the app via
# --info-xml, check the ExApp container for uid 10001.
#
# Runs under Git Bash: container paths need MSYS_NO_PATHCONV=1.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
HARP_COMPOSE="${SCRIPT_DIR}/harp.compose.yaml"
# Below, MSYS_NO_PATHCONV=1 applies (Git Bash); docker compose therefore gets the file
# as a Windows path, otherwise it does not find /c/... Without cygpath (Linux) it stays.
if command -v cygpath >/dev/null 2>&1; then
	HARP_COMPOSE=$(cygpath -m "${HARP_COMPOSE}")
fi
INFO_XML="${REPO_ROOT}/appinfo/info.xml"
RUN_DIR="${REPO_ROOT}/.dev"
KEY_FILE="${RUN_DIR}/harp.key"
INFO_COPY="${RUN_DIR}/info-harp.xml"
INFO_IN_CONTAINER=/tmp/info-harp.xml
APP_ID=gameworld
DAEMON=harp_dev
NC_SERVICE=harp-nc
HARP_CONTAINER=gameworld-dev-appapi-harp
FRONT_URL=http://127.0.0.1:${GAMEWORLD_HARP_PORT:-8093}
REGISTRY=localhost:5000
IMAGE_NAME=street1983nk/gameworld
EXAPP_CONTAINER=nc_app_gameworld
# The scoped proxy of the test instance under its service name in the Compose network.
DOCKER_URL=tcp://gameworld-docker-proxy:2375

MSYS_NO_PATHCONV=1
export MSYS_NO_PATHCONV

say() { printf '%s\n' "$1"; }
die() {
	printf 'harp-install: %s\n' "$1" >&2
	exit 1
}

new_key() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 24
		return
	fi
	od -vAn -N24 -tx1 /dev/urandom | tr -d ' \n'
}

harp_compose() {
	GAMEWORLD_HARP_KEY=$(cat "${KEY_FILE}")
	export GAMEWORLD_HARP_KEY
	docker compose -f "${HARP_COMPOSE}" "$@"
}

occ() {
	harp_compose exec -T -u www-data "${NC_SERVICE}" php occ "$@"
}

# in_nc URL [curl options] -> HTTP code of a request from inside the Nextcloud container
in_nc() {
	url=$1
	shift
	harp_compose exec -T "${NC_SERVICE}" curl -s -o /dev/null -w '%{http_code}' "$@" "${url}" 2>/dev/null || printf '000'
}

app_registered() {
	occ app_api:app:list 2>/dev/null | grep -q "^${APP_ID} "
}

unregister_app() {
	app_registered || return 0
	say "entferne die vorhandene Registrierung samt ExApp-Container und Datenvolume (nur Test-Instanz)"
	occ app_api:app:unregister "${APP_ID}" --rm-data --silent >/dev/null 2>&1 ||
		occ app_api:app:unregister "${APP_ID}" --rm-data --force --silent >/dev/null 2>&1 || true
	! app_registered || die "die Registrierung von ${APP_ID} ließ sich nicht entfernen"
}

unregister_daemon() {
	if occ app_api:daemon:list 2>/dev/null | grep -q " ${DAEMON} "; then
		say "entferne den Daemon ${DAEMON}"
		occ app_api:daemon:unregister "${DAEMON}" >/dev/null
	fi
}

IMAGE_TAG=$(sed -n 's:.*<image-tag>\(.*\)</image-tag>.*:\1:p' "${INFO_XML}" | head -n 1)
[ -n "${IMAGE_TAG}" ] || die "aus ${INFO_XML} ließ sich kein image-tag lesen"
LOCAL_IMAGE="${REGISTRY}/${IMAGE_NAME}:${IMAGE_TAG}"

for tool in docker curl sed grep; do
	command -v "${tool}" >/dev/null 2>&1 || die "Werkzeug ${tool} fehlt"
done

mkdir -p "${RUN_DIR}"
if [ ! -s "${KEY_FILE}" ]; then
	(
		umask 077
		new_key >"${KEY_FILE}"
	)
	say "neuer HaRP-Schlüssel in .dev/harp.key"
fi

if [ "${1:-}" = "--uninstall" ]; then
	if docker ps -q --filter "name=^gameworld-dev-harp-nc\$" | grep -q .; then
		unregister_app
		unregister_daemon
	fi
	say "baue den Test-Stack gameworld-dev-harp samt Volumes ab"
	harp_compose down -v --remove-orphans
	exit 0
fi
[ -z "${1:-}" ] || die "unbekannte Option ${1} (nur --uninstall)"

say "starte den Test-Stack gameworld-dev-harp"
harp_compose up -d

say "warte auf die Test-Nextcloud hinter ${FRONT_URL}"
i=0
until curl -sf "${FRONT_URL}/status.php" 2>/dev/null | grep -q '"installed":true'; do
	i=$((i + 1))
	[ "${i}" -lt 120 ] || die "die Test-Nextcloud meldet sich nicht unter ${FRONT_URL}/status.php"
	sleep 2
done

occ app:enable app_api >/dev/null
# The setup wizard would otherwise cover every page (pattern register-exapp.sh).
occ app:disable firstrunwizard >/dev/null 2>&1 || true
# Talk for criterion 7 (as in docs/dev-setup.md "Talk im Dev-Stack", needs internet the first time).
if ! occ app:list --output=json 2>/dev/null | grep -q '"spreed"'; then
	say "installiere Talk (spreed) in der Test-Nextcloud"
	occ app:install spreed >/dev/null 2>&1 || true
fi
occ app:enable spreed >/dev/null 2>&1 || true

i=0
until curl -sf "http://127.0.0.1:5000/v2/" >/dev/null 2>&1; do
	i=$((i + 1))
	[ "${i}" -lt 30 ] || die "die lokale Registry antwortet nicht unter 127.0.0.1:5000"
	sleep 1
done

say "baue ${LOCAL_IMAGE}"
BUILD_CONTEXT=${REPO_ROOT}
if command -v cygpath >/dev/null 2>&1; then
	BUILD_CONTEXT=$(cygpath -m "${REPO_ROOT}")
fi
docker build -t "${LOCAL_IMAGE}" "${BUILD_CONTEXT}"
say "schiebe ${LOCAL_IMAGE} in die lokale Registry"
docker push "${LOCAL_IMAGE}"

# Rewrite the copy only; the original stays as it goes into the store.
sed -e "s|<registry>ghcr.io</registry>|<registry>${REGISTRY}</registry>|" "${INFO_XML}" >"${INFO_COPY}"
grep -q "<registry>${REGISTRY}</registry>" "${INFO_COPY}" || die "die Kopie der info.xml nennt die lokale Registry nicht"
grep -q "<image>${IMAGE_NAME}</image>" "${INFO_COPY}" || die "die Kopie der info.xml nennt das Image ${IMAGE_NAME} nicht"
INFO_COPY_HOST=${INFO_COPY}
if command -v cygpath >/dev/null 2>&1; then
	INFO_COPY_HOST=$(cygpath -m "${INFO_COPY}")
fi
harp_compose cp "${INFO_COPY_HOST}" "${NC_SERVICE}:${INFO_IN_CONTAINER}"
harp_compose exec -T "${NC_SERVICE}" chmod 0644 "${INFO_IN_CONTAINER}"

# Check both directions of the front before anything is registered (lesson from Findling):
# / must reach the instance, /exapps/ the Docker engine of HaRP.
CODE=$(in_nc http://harp-front/status.php)
[ "${CODE}" = 200 ] || die "die Front reicht / nicht an die Test-Nextcloud weiter (status.php ${CODE})"
i=0
while :; do
	CODE=$(in_nc http://harp-front/exapps/app_api/v1.44/_ping -H "harp-shared-key: $(cat "${KEY_FILE}")" -H 'docker-engine-port: 24000')
	[ "${CODE}" = 200 ] && break
	i=$((i + 1))
	[ "${i}" -lt 30 ] || die "die Front erreicht die Docker-Engine von HaRP nicht (_ping ${CODE})"
	sleep 2
done

unregister_app
unregister_daemon
say "registriere den Daemon ${DAEMON}"
occ app_api:daemon:register "${DAEMON}" "HaRP Dev" docker-install http appapi-harp:8780 http://harp-front \
	--net gameworld-dev-harp_default --harp --harp_frp_address appapi-harp:8782 \
	--harp_shared_key "$(cat "${KEY_FILE}")" >/dev/null

say "registriere ${APP_ID} über ${DAEMON} aus ${INFO_IN_CONTAINER} (wartet auf das Ende der Installation)"
occ app_api:app:register "${APP_ID}" "${DAEMON}" --info-xml "${INFO_IN_CONTAINER}" \
	--env "GAMEWORLD_DOCKER_URL=${DOCKER_URL}" --wait-finish

occ app_api:app:enable "${APP_ID}" >/dev/null 2>&1 || true
occ app_api:app:list 2>/dev/null | grep "^${APP_ID} " | grep -qi enabled || die "${APP_ID} ist registriert, aber nicht aktiviert"
USER_OF=$(docker inspect --format '{{.Config.User}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r' || true)
[ "${USER_OF}" = "10001:10001" ] || die "der ExApp-Container läuft nicht als 10001:10001 (ist ${USER_OF:-leer})"
docker inspect "${HARP_CONTAINER}" >/dev/null 2>&1 || die "HaRP-Container ${HARP_CONTAINER} fehlt"
say "Gameworld läuft über ${DAEMON} aus ${LOCAL_IMAGE} als ${USER_OF} (Container ${EXAPP_CONTAINER})"
say "Test-Nextcloud: ${FRONT_URL} (admin, Passwort siehe harp.compose.yaml)"
