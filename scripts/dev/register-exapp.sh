#!/bin/sh
# Starts the Gameworld ExApp as a host process and registers it in the
# dev Nextcloud (compose project gameworld-dev, port 8091).
#
# One command from the running Compose stack to the registered, enabled ExApp.
# The template is the registration script of Findling; structure and idempotence are
# taken over, only IDs, ports and paths are swapped.
#
# Idempotence with one deliberate exception: an existing registration is removed
# first. A backend that already answers its heartbeat keeps running
# with the secret from .dev/exapp.secret as long as it matches the sources.
# A process with another version, with a missing route or with older code than
# src/ is stopped and restarted, with one line that names the reason.
# Without this check an old process answers 404 after a plan with a new route,
# and that looks like a bug in Nextcloud.
#
# .dev/ is gitignored, no secret of a local run reaches the repository.
# Everything concerning Nextcloud runs through the container (occ via compose exec),
# there is no PHP on the development machine.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"

BACKEND_ID=gameworld
DAEMON_NAME=manual_install
BACKEND_PORT=10040
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
# The one file that says what the ExApp is and which routes it exposes.
# Version and route list are read from it below, so that nothing diverges.
INFO_XML="${REPO_ROOT}/appinfo/info.xml"
# The Nextcloud container reaches the host process under this name, never
# under localhost (extra_hosts in compose.yaml).
HOST_FROM_CONTAINER=host.docker.internal
RUN_DIR="${REPO_ROOT}/.dev"
LOG_FILE="${RUN_DIR}/exapp.log"
# Logs of earlier backends: each start puts the old exapp.log here instead of
# overwriting it. Otherwise, after an unplanned end (acceptance with several
# restarts), exactly the log that shows the reason is gone. The newest LOG_KEEP stay.
LOG_DIR="${RUN_DIR}/logs"
LOG_KEEP=20
PID_FILE="${RUN_DIR}/exapp.pid"
SECRET_FILE="${RUN_DIR}/exapp.secret"
VERSION_FILE="${RUN_DIR}/exapp.version"
# Version and route checksum of the last successful registration.
REGISTRATION_FILE="${RUN_DIR}/exapp.registered"
# 0.0.0.0, because Docker Desktop reaches the host through its own bridge address.
# The secret protects the port; with GAMEWORLD_APP_HOST the binding can be
# narrowed to this bridge address.
BACKEND_HOST="${GAMEWORLD_APP_HOST:-0.0.0.0}"
# The scoped Docker proxy from compose.yaml, published on loopback only.
GAMEWORLD_DOCKER_URL=tcp://127.0.0.1:23750
GAMEWORLD_PORT_RANGE=30000-30019
BUNDLE="${REPO_ROOT}/js/gameworld-main.js"

new_secret() {
	if command -v openssl >/dev/null 2>&1; then
		openssl rand -hex 16
		return
	fi
	od -vAn -N16 -tx1 /dev/urandom | tr -d ' \n'
}

nextcloud_occ() {
	docker compose -f "${COMPOSE_FILE}" exec -T -u www-data app php occ "$@"
}

stop_backend() {
	if [ ! -f "${PID_FILE}" ]; then
		printf 'keine PID-Datei unter %s, hier gibt es nichts zu stoppen\n' "${PID_FILE}"
		return 0
	fi
	OLD_PID=$(cat "${PID_FILE}")
	if [ -n "${OLD_PID}" ] && kill -0 "${OLD_PID}" 2>/dev/null; then
		printf 'stoppe das Backend mit PID %s\n' "${OLD_PID}"
		kill -TERM "${OLD_PID}" 2>/dev/null || true
		i=0
		while [ "${i}" -lt 10 ]; do
			if ! kill -0 "${OLD_PID}" 2>/dev/null; then
				break
			fi
			i=$((i + 1))
			sleep 1
		done
		kill -KILL "${OLD_PID}" 2>/dev/null || true
	else
		printf 'entferne die veraltete PID-Datei %s\n' "${PID_FILE}"
	fi
	rm -f "${PID_FILE}"
	# uv starts python as a child process; on Windows the child survives the
	# parent process. As long as the port still answers, it counts as occupied.
	i=0
	while [ "${i}" -lt 10 ]; do
		if ! curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1; then
			return 0
		fi
		i=$((i + 1))
		sleep 1
	done
	printf 'Port %s antwortet nach dem Stopp weiter. Den Prozess dort beenden und erneut starten.\n' \
		"${BACKEND_PORT}" >&2
	exit 1
}

# Reads the routes from info.xml as lines "url verb level" with AppAPI numbers
# (PUBLIC 0, USER 1, ADMIN 2).
declared_routes() {
	awk '
		BEGIN { FS = "[<>]" }
		/<routes>/ { inside = 1; next }
		/<\/routes>/ { inside = 0; next }
		inside != 1 { next }
		/<url>/ { url = $3; next }
		/<verb>/ { verb = $3; next }
		/<access_level>/ { level = $3; next }
		/<\/route>/ {
			if (url == "" || verb == "" || level == "") next
			number = -1
			if (level == "PUBLIC") number = 0
			if (level == "USER") number = 1
			if (level == "ADMIN") number = 2
			if (number < 0) {
				printf "unbekanntes access_level %s in den Routen von info.xml\n", level > "/dev/stderr"
				exit 1
			}
			printf "%s %s %d\n", url, verb, number
			url = ""
			verb = ""
			level = ""
		}
	' "${INFO_XML}"
}

app_api_authorization() {
	printf 'admin:%s' "$1" | base64 | tr -d '\r\n'
}

# Empty if the running backend matches the sources, otherwise the reason.
stale_reason() {
	stale_auth=$(app_api_authorization "$1")
	stale_version=$(cat "${VERSION_FILE}" 2>/dev/null || true)
	if [ "${stale_version}" != "${BACKEND_VERSION}" ]; then
		printf 'es wurde mit Version %s gestartet, die Quellen sagen %s' \
			"${stale_version:-unbekannt}" "${BACKEND_VERSION}"
		return 0
	fi
	if [ -n "$(find "${REPO_ROOT}/src" -name '*.py' -newer "${PID_FILE}" 2>/dev/null | head -n 1)" ]; then
		printf 'unter src/ gibt es Python-Dateien, die neuer sind als der Prozess'
		return 0
	fi
	stale_code=$(curl -s -o /dev/null -w '%{http_code}' \
		-H "EX-APP-ID: ${BACKEND_ID}" \
		-H "EX-APP-VERSION: ${BACKEND_VERSION}" \
		-H "AUTHORIZATION-APP-API: ${stale_auth}" \
		"http://127.0.0.1:${BACKEND_PORT}/api/worlds" 2>/dev/null || printf '000')
	if [ "${stale_code}" != "200" ]; then
		printf 'die signierte Route api/worlds antwortet mit %s statt 200' "${stale_code}"
		return 0
	fi
}

# Builds the frontend if the bundle is missing or older than frontend/src.
keep_previous_log() {
	[ -s "${LOG_FILE}" ] || return 0
	mkdir -p "${LOG_DIR}"
	kept="${LOG_DIR}/exapp-$(date +%Y%m%d-%H%M%S)-$$.log"
	mv "${LOG_FILE}" "${kept}"
	printf 'Log des vorigen Backends liegt in %s\n' "${kept}"
	# File names without spaces (date, time, PID), so ls is safe here.
	ls -1t "${LOG_DIR}"/exapp-*.log 2>/dev/null | tail -n +$((LOG_KEEP + 1)) | while read -r old; do
		rm -f "${old}"
	done
}

build_frontend() {
	if [ ! -f "${REPO_ROOT}/frontend/package.json" ]; then
		printf 'frontend/package.json fehlt, das Bundle %s kann nicht gebaut werden\n' "${BUNDLE}" >&2
		exit 1
	fi
	if [ -f "${BUNDLE}" ] \
		&& [ -z "$(find "${REPO_ROOT}/frontend/src" "${REPO_ROOT}/frontend/package.json" \
			"${REPO_ROOT}/frontend/vite.config.js" -newer "${BUNDLE}" 2>/dev/null | head -n 1)" ]; then
		printf 'Frontend-Bundle ist aktuell\n'
		return 0
	fi
	printf 'baue das Frontend nach %s\n' "${BUNDLE}"
	if [ ! -d "${REPO_ROOT}/frontend/node_modules" ]; then
		npm --prefix "${REPO_ROOT}/frontend" ci --ignore-scripts
	fi
	npm --prefix "${REPO_ROOT}/frontend" run build
	if [ ! -f "${BUNDLE}" ]; then
		printf 'der Build lief, aber %s fehlt\n' "${BUNDLE}" >&2
		exit 1
	fi
}

BACKEND_VERSION=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "${INFO_XML}" | head -n 1)
if [ -z "${BACKEND_VERSION}" ]; then
	printf 'aus %s ließ sich keine Version lesen\n' "${INFO_XML}" >&2
	exit 1
fi

ROUTE_LINES=$(declared_routes)
if [ -z "${ROUTE_LINES}" ]; then
	printf 'aus %s ließ sich keine Route lesen\n' "${INFO_XML}" >&2
	exit 1
fi
ROUTES_DECLARED=$(grep -c '<route>' "${INFO_XML}")
ROUTES_PARSED=$(printf '%s\n' "${ROUTE_LINES}" | wc -l | tr -d ' ')
if [ "${ROUTES_DECLARED}" != "${ROUTES_PARSED}" ]; then
	printf '%s deklariert %s Routen, gelesen wurden %s\n' \
		"${INFO_XML}" "${ROUTES_DECLARED}" "${ROUTES_PARSED}" >&2
	exit 1
fi

ROUTES_JSON=""
while read -r route_url route_verb route_level; do
	[ -n "${route_url}" ] || continue
	if [ -n "${ROUTES_JSON}" ]; then
		ROUTES_JSON="${ROUTES_JSON},"
	fi
	ROUTES_JSON="${ROUTES_JSON}{\"url\":\"${route_url}\",\"verb\":\"${route_verb}\",\"access_level\":${route_level},\"headers_to_exclude\":[]}"
done <<EOF
${ROUTE_LINES}
EOF

printf 'registriere Version %s mit %s Routen aus appinfo/info.xml\n' "${BACKEND_VERSION}" "${ROUTES_PARSED}"

mkdir -p "${RUN_DIR}"

# Provide game files hash-checked before anything starts. A
# backend with missing or damaged games never starts.
if ! sh "${REPO_ROOT}/scripts/fetch-games.sh"; then
	printf 'Spieldateien fehlen oder sind beschädigt, siehe scripts/fetch-games.sh\n' >&2
	exit 1
fi

build_frontend

printf 'warte auf %s\n' "${NEXTCLOUD_URL}"
i=0
while [ "${i}" -lt 60 ]; do
	if curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
		break
	fi
	i=$((i + 1))
	sleep 2
done
if [ "${i}" -ge 60 ]; then
	printf 'Nextcloud antwortet nicht unter %s/status.php\n' "${NEXTCLOUD_URL}" >&2
	printf 'zuerst starten: docker compose -f %s up -d\n' "${COMPOSE_FILE}" >&2
	exit 1
fi

printf 'aktiviere app_api\n'
nextcloud_occ app:enable app_api
# The setup wizard lays itself over every page at the first login and
# thereby blocks browser checks (Playwright); off in the dev Nextcloud.
nextcloud_occ app:disable firstrunwizard >/dev/null 2>&1 || true

REUSE_BACKEND=0
BACKEND_SECRET=""
if curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1; then
	if [ -r "${SECRET_FILE}" ]; then
		BACKEND_SECRET=$(cat "${SECRET_FILE}")
		STALE=$(stale_reason "${BACKEND_SECRET}")
		if [ -z "${STALE}" ]; then
			printf 'Backend antwortet schon auf Port %s und passt zu den Quellen, Secret aus %s\n' \
				"${BACKEND_PORT}" "${SECRET_FILE}"
			REUSE_BACKEND=1
		else
			printf 'starte das Backend auf Port %s neu, weil %s\n' "${BACKEND_PORT}" "${STALE}"
			stop_backend
		fi
	else
		printf 'auf Port %s antwortet ein Heartbeat, aber %s fehlt.\n' "${BACKEND_PORT}" "${SECRET_FILE}" >&2
		printf 'Das Secret ist unbekannt, der Handshake könnte nur scheitern. Den Prozess\n' >&2
		printf 'beenden und dieses Skript erneut starten.\n' >&2
		exit 1
	fi
else
	stop_backend
fi

# Protection of the running worlds (D-17, plan 06-12): removing an active
# registration first calls /enabled?enabled=0, and Gameworld clears away
# all its own world containers. With a reused backend its
# secret still applies, so the call would arrive. Therefore: if the registration already matches
# (same version, same routes), it stays. Otherwise the backend restarts
# with a new secret, then it rejects the call with the old secret (401)
# and no world is cleared away.
ROUTES_SUM=$(printf '%s' "${ROUTES_JSON}" | cksum | awk '{print $1}')
WANT_REGISTRATION="${BACKEND_VERSION} ${ROUTES_SUM}"
if [ "${REUSE_BACKEND}" -eq 1 ] && nextcloud_occ app_api:app:list 2>/dev/null | grep "^${BACKEND_ID} " | grep -q .; then
	if nextcloud_occ app_api:app:list 2>/dev/null | grep "^${BACKEND_ID} " | grep -q "${BACKEND_VERSION}.*enabled" \
		&& [ "$(cat "${REGISTRATION_FILE}" 2>/dev/null || true)" = "${WANT_REGISTRATION}" ]; then
		printf 'Registrierung passt schon (Version %s, gleiche Routen), bleibt unverändert\n' "${BACKEND_VERSION}"
		printf 'registriert und aktiviert: %s/index.php/apps/app_api/embedded/%s/%s\n' \
			"${NEXTCLOUD_URL}" "${BACKEND_ID}" "${BACKEND_ID}"
		exit 0
	fi
	printf 'starte das Backend mit neuem Secret neu, weil die Registrierung erneuert wird (sonst räumte /enabled?enabled=0 die Welten ab)\n'
	stop_backend
	REUSE_BACKEND=0
fi

if [ "${REUSE_BACKEND}" -eq 0 ]; then
	# New secret per run, never a fixed one in the repository (T-01-11).
	BACKEND_SECRET=$(new_secret)
	(
		umask 077
		printf '%s\n' "${BACKEND_SECRET}" >"${SECRET_FILE}"
	)
	printf '%s\n' "${BACKEND_VERSION}" >"${VERSION_FILE}"
	keep_previous_log
	printf 'starte das Backend auf %s:%s, Log in %s\n' "${BACKEND_HOST}" "${BACKEND_PORT}" "${LOG_FILE}"
	(
		# cwd = repo root: set_handlers mounts js/ and img/ relative to it.
		cd "${REPO_ROOT}" || exit 1
		APP_ID="${BACKEND_ID}"
		APP_SECRET="${BACKEND_SECRET}"
		APP_PORT="${BACKEND_PORT}"
		APP_HOST="${BACKEND_HOST}"
		APP_VERSION="${BACKEND_VERSION}"
		APP_PERSISTENT_STORAGE="${RUN_DIR}/storage"
		export APP_ID APP_SECRET APP_PORT APP_HOST APP_VERSION APP_PERSISTENT_STORAGE
		export NEXTCLOUD_URL GAMEWORLD_DOCKER_URL GAMEWORLD_PORT_RANGE
		# A hard crash (Fatal Python error, access violation) thus still writes
		# a traceback to the log instead of letting the process vanish silently.
		PYTHONFAULTHANDLER=1
		export PYTHONFAULTHANDLER
		exec uv run python -m gameworld.main
	) >"${LOG_FILE}" 2>&1 &
	printf '%s\n' "$!" >"${PID_FILE}"

	i=0
	while [ "${i}" -lt 30 ]; do
		if curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1; then
			break
		fi
		i=$((i + 1))
		sleep 1
	done
	if [ "${i}" -ge 30 ]; then
		printf 'Backend antwortet nicht auf den Heartbeat, letzte Logzeilen:\n' >&2
		tail -n 40 "${LOG_FILE}" >&2 || true
		exit 1
	fi
fi

nextcloud_occ app_api:app:unregister "${BACKEND_ID}" >/dev/null 2>&1 || true

if nextcloud_occ app_api:daemon:list 2>/dev/null | grep -q "${DAEMON_NAME}"; then
	printf 'Deploy-Daemon %s existiert schon\n' "${DAEMON_NAME}"
else
	printf 'registriere den Deploy-Daemon %s\n' "${DAEMON_NAME}"
	nextcloud_occ app_api:daemon:register --net host \
		"${DAEMON_NAME}" "Manual Install" manual-install http \
		"${HOST_FROM_CONTAINER}" "${NEXTCLOUD_URL}"
fi

printf 'registriere die ExApp, das blockiert bis zum Ende des Handshakes\n'
nextcloud_occ app_api:app:register "${BACKEND_ID}" "${DAEMON_NAME}" --json-info \
	"{\"id\":\"${BACKEND_ID}\",\"name\":\"Gameworld\",\"daemon_config_name\":\"${DAEMON_NAME}\",\"version\":\"${BACKEND_VERSION}\",\"secret\":\"${BACKEND_SECRET}\",\"port\":${BACKEND_PORT},\"scopes\":[],\"system\":0,\"routes\":[${ROUTES_JSON}]}" \
	--force-scopes --wait-finish

# The registration usually enables the app already; enable is then a
# harmless second call. The state in the list afterwards is what counts.
nextcloud_occ app_api:app:enable "${BACKEND_ID}" >/dev/null 2>&1 || true
if ! nextcloud_occ app_api:app:list 2>/dev/null | grep "${BACKEND_ID}" | grep -qi 'enabled'; then
	printf 'Gameworld ist registriert, aber nicht aktiviert:\n' >&2
	nextcloud_occ app_api:app:list >&2 || true
	exit 1
fi
printf '%s\n' "${WANT_REGISTRATION}" >"${REGISTRATION_FILE}"
printf 'registriert und aktiviert: %s/index.php/apps/app_api/embedded/%s/%s\n' \
	"${NEXTCLOUD_URL}" "${BACKEND_ID}" "${BACKEND_ID}"
