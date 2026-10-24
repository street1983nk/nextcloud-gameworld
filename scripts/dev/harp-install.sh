#!/bin/sh
# Installiert Gameworld über einen echten HaRP-Daemon aus einer lokalen Registry
# in eine eigene Test-Nextcloud (Plan 06-12, 06-RESEARCH 5.2 und 9). Das ist der
# Weg einer Store-Installation ohne Archiv-Download und Signaturprüfung: AppAPI
# liest eine info.xml, HaRP zieht das Image und legt den ExApp-Container an.
# Kein Push nach ghcr.io, kein Zertifikat nötig.
#
#   sh scripts/dev/harp-install.sh              installieren (idempotent)
#   sh scripts/dev/harp-install.sh --uninstall  Registrierung, Daemon und den
#                                               ganzen Test-Stack samt Volumes entfernen
#
# Die Test-Instanz (harp.compose.yaml) ist vom Dev-Stack getrennt: eigene
# Nextcloud, eigener Docker-Proxy, eigenes Netz. Die Dev-Nextcloud auf 8091, ihre
# manual_install-Registrierung und ihre Welten fasst dieses Skript nie an.
#
# Ablauf: Schlüssel in .dev/harp.key (gitignored, nie im Repository), Stack
# starten, Test-Nextcloud vorbereiten (app_api, Talk), Image bauen und nach
# localhost:5000 schieben, eine KOPIE der info.xml mit registry localhost:5000
# nach .dev/info-harp.xml (das Original bleibt unverändert, T-06-55), beide
# Richtungen der Front prüfen, Daemon harp_dev neu registrieren (idempotent:
# vorhandene Registrierung und Daemon gleichen Namens zuerst entfernen), App per
# --info-xml registrieren, ExApp-Container auf uid 10001 prüfen.
#
# Läuft unter Git Bash: Containerpfade brauchen MSYS_NO_PATHCONV=1.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
HARP_COMPOSE="${SCRIPT_DIR}/harp.compose.yaml"
# Unten gilt MSYS_NO_PATHCONV=1 (Git Bash); docker compose bekommt die Datei darum
# als Windows-Pfad, sonst findet es /c/... nicht. Ohne cygpath (Linux) bleibt er.
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
# Der gescopte Proxy der Test-Instanz unter seinem Dienstnamen im Compose-Netz.
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

# in_nc URL [curl-Optionen] -> HTTP-Code eines Abrufs aus dem Nextcloud-Container
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
# Der Einrichtungsassistent legt sich sonst über jede Seite (Muster register-exapp.sh).
occ app:disable firstrunwizard >/dev/null 2>&1 || true
# Talk für Kriterium 7 (wie docs/dev-setup.md "Talk im Dev-Stack", braucht beim ersten Mal Internet).
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

# Nur die Kopie umschreiben; das Original bleibt, wie es in den Store geht.
sed -e "s|<registry>ghcr.io</registry>|<registry>${REGISTRY}</registry>|" "${INFO_XML}" >"${INFO_COPY}"
grep -q "<registry>${REGISTRY}</registry>" "${INFO_COPY}" || die "die Kopie der info.xml nennt die lokale Registry nicht"
grep -q "<image>${IMAGE_NAME}</image>" "${INFO_COPY}" || die "die Kopie der info.xml nennt das Image ${IMAGE_NAME} nicht"
INFO_COPY_HOST=${INFO_COPY}
if command -v cygpath >/dev/null 2>&1; then
	INFO_COPY_HOST=$(cygpath -m "${INFO_COPY}")
fi
harp_compose cp "${INFO_COPY_HOST}" "${NC_SERVICE}:${INFO_IN_CONTAINER}"
harp_compose exec -T "${NC_SERVICE}" chmod 0644 "${INFO_IN_CONTAINER}"

# Beide Richtungen der Front prüfen, bevor etwas registriert wird (Lehre aus Findling):
# / muss die Instanz erreichen, /exapps/ die Docker-Engine von HaRP.
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
