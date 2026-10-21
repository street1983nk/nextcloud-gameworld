#!/bin/sh
# Startet die Gameworld-ExApp als Host-Prozess und registriert sie in der
# Dev-Nextcloud (compose-Projekt gameworld-dev, Port 8091).
#
# Ein Befehl vom laufenden Compose-Stack zur registrierten, aktivierten ExApp.
# Vorlage ist das Registrierungsskript von Findling; Struktur und Idempotenz sind
# übernommen, nur IDs, Ports und Pfade sind getauscht.
#
# Idempotenz mit einer bewussten Ausnahme: Eine bestehende Registrierung wird
# zuerst entfernt. Ein Backend, das schon auf seinen Heartbeat antwortet, läuft
# mit dem Secret aus .dev/exapp.secret weiter, solange es zu den Quellen passt.
# Ein Prozess mit anderer Version, mit fehlender Route oder mit älterem Code als
# src/ wird gestoppt und neu gestartet, mit einer Zeile, die den Grund nennt.
# Ohne diese Prüfung antwortet ein alter Prozess nach einem Plan mit neuer Route
# mit 404, und das sieht aus wie ein Fehler in Nextcloud.
#
# .dev/ ist gitignored, kein Secret eines lokalen Laufs gelangt ins Repository.
# Alles, was Nextcloud betrifft, läuft über den Container (occ per compose exec),
# auf dem Entwicklungsrechner gibt es kein PHP.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"

BACKEND_ID=gameworld
DAEMON_NAME=manual_install
BACKEND_PORT=10040
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
# Die eine Datei, die sagt, was die ExApp ist und welche Routen sie freigibt.
# Version und Routenliste werden unten daraus gelesen, damit nichts abweicht.
INFO_XML="${REPO_ROOT}/appinfo/info.xml"
# Der Nextcloud-Container erreicht den Host-Prozess unter diesem Namen, nie
# unter localhost (extra_hosts in compose.yaml).
HOST_FROM_CONTAINER=host.docker.internal
RUN_DIR="${REPO_ROOT}/.dev"
LOG_FILE="${RUN_DIR}/exapp.log"
# Logs früherer Backends: Jeder Start legt das alte exapp.log hier ab, statt es zu
# überschreiben. Sonst ist nach einem ungeplanten Ende (Abnahme mit mehreren
# Neustarts) genau das Log weg, das den Grund zeigt. Die neuesten LOG_KEEP bleiben.
LOG_DIR="${RUN_DIR}/logs"
LOG_KEEP=20
PID_FILE="${RUN_DIR}/exapp.pid"
SECRET_FILE="${RUN_DIR}/exapp.secret"
VERSION_FILE="${RUN_DIR}/exapp.version"
# 0.0.0.0, weil Docker Desktop den Host über eine eigene Bridge-Adresse
# erreicht. Das Secret schützt den Port; mit GAMEWORLD_APP_HOST lässt sich die
# Bindung auf diese Bridge-Adresse einengen.
BACKEND_HOST="${GAMEWORLD_APP_HOST:-0.0.0.0}"
# Der gescopte Docker-Proxy aus compose.yaml, nur auf Loopback publiziert.
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
	# uv startet python als Kindprozess; unter Windows überlebt das Kind den
	# Elternprozess. Solange der Port noch antwortet, gilt er als belegt.
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

# Liest die Routen aus info.xml als Zeilen "url verb level" mit AppAPI-Zahlen
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

# Leer, wenn das laufende Backend zu den Quellen passt, sonst der Grund.
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

# Baut das Frontend, wenn das Bundle fehlt oder älter als frontend/src ist.
keep_previous_log() {
	[ -s "${LOG_FILE}" ] || return 0
	mkdir -p "${LOG_DIR}"
	kept="${LOG_DIR}/exapp-$(date +%Y%m%d-%H%M%S)-$$.log"
	mv "${LOG_FILE}" "${kept}"
	printf 'Log des vorigen Backends liegt in %s\n' "${kept}"
	# Dateinamen ohne Leerzeichen (Datum, Uhrzeit, PID), daher ist ls hier sicher.
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

# Spieldateien hash-geprüft bereitstellen, bevor irgendetwas startet. Ein
# Backend mit fehlenden oder beschädigten Spielen startet nie.
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
# Der Einrichtungsassistent legt sich beim ersten Login über jede Seite und
# blockiert damit Browser-Prüfungen (Playwright); in der Dev-Nextcloud aus.
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

if [ "${REUSE_BACKEND}" -eq 0 ]; then
	# Neues Secret pro Lauf, nie ein festes im Repository (T-01-11).
	BACKEND_SECRET=$(new_secret)
	(
		umask 077
		printf '%s\n' "${BACKEND_SECRET}" >"${SECRET_FILE}"
	)
	printf '%s\n' "${BACKEND_VERSION}" >"${VERSION_FILE}"
	keep_previous_log
	printf 'starte das Backend auf %s:%s, Log in %s\n' "${BACKEND_HOST}" "${BACKEND_PORT}" "${LOG_FILE}"
	(
		# cwd = Repo-Root: set_handlers mountet js/ und img/ relativ dazu.
		cd "${REPO_ROOT}" || exit 1
		APP_ID="${BACKEND_ID}"
		APP_SECRET="${BACKEND_SECRET}"
		APP_PORT="${BACKEND_PORT}"
		APP_HOST="${BACKEND_HOST}"
		APP_VERSION="${BACKEND_VERSION}"
		APP_PERSISTENT_STORAGE="${RUN_DIR}/storage"
		export APP_ID APP_SECRET APP_PORT APP_HOST APP_VERSION APP_PERSISTENT_STORAGE
		export NEXTCLOUD_URL GAMEWORLD_DOCKER_URL GAMEWORLD_PORT_RANGE
		# Ein harter Absturz (Fatal Python error, Zugriffsverletzung) schreibt so
		# noch einen Traceback ins Log, statt den Prozess stumm verschwinden zu lassen.
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

# Die Registrierung aktiviert die App in der Regel schon; enable ist dann ein
# harmloser zweiter Aufruf. Maßgeblich ist der Zustand in der Liste danach.
nextcloud_occ app_api:app:enable "${BACKEND_ID}" >/dev/null 2>&1 || true
if ! nextcloud_occ app_api:app:list 2>/dev/null | grep "${BACKEND_ID}" | grep -qi 'enabled'; then
	printf 'Gameworld ist registriert, aber nicht aktiviert:\n' >&2
	nextcloud_occ app_api:app:list >&2 || true
	exit 1
fi
printf 'registriert und aktiviert: %s/index.php/apps/app_api/embedded/%s/%s\n' \
	"${NEXTCLOUD_URL}" "${BACKEND_ID}" "${BACKEND_ID}"
