#!/bin/sh
# Live-Prüfung Talk-Raum je Welt und Gameworld-Bot (Phase 4.1, TALK-01, TALK-02)
# gegen den laufenden Dev-Stack mit installiertem Talk (spreed) und laufender
# ExApp, ohne Fakes.
#
# Belege kommen aus curl gegen die OCS-API von Talk mit echten Nextcloud-Konten,
# aus curl gegen den AppAPI-Proxy der ExApp, aus jq und aus dem Log der ExApp
# (.dev/exapp.log: Webhook-Aufrufe, kein Chatinhalt). Einziges
# Python-Werkzeug ist der Session-Prober (tests/e2e/luanti_probe.py) über seine
# CLI. Zu jeder Verbotsprüfung gibt es eine Positivkontrolle.
#
# Voraussetzung:
#   docker compose -f scripts/dev/compose.yaml up -d
#   occ app:install spreed (siehe docs/dev-setup.md)
#   sh scripts/dev/register-exapp.sh
#
# Dauer: einige Minuten, weil die Prüfung des Abgleichs bis zu 330 s wartet
# (die ExApp-Wartung läuft alle 5 Minuten und wird nicht erzwungen).
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Spielpasswörter erscheinen nie in
# der Ausgabe. Ein trap räumt in jedem Fall auf: Welt "Abnahme Talk" (Lösch-API,
# Fallback docker rm -f -v), Wegwerfkonto gw-talk-gast. gw-kind bleibt bestehen.
# Aufgerufen aus der Phasenabnahme 04.1-09.
#
# Zugangsdaten hier sind reine Dev-Konten einer Loopback-Dev-Instanz.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
COMPOSE_FILE="${SCRIPT_DIR}/compose.yaml"
NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
ADMIN_AUTH=admin:gameworld-dev-admin
KID=gw-kind
KID_AUTH="${KID}:gw-kind-dev-pass-1"
GUEST=gw-talk-gast
GUEST_PASS=gw-talk-gast-dev-pass-1
API_URL="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld/api"
SPREED="${NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api"
NAME_WORLD="Abnahme Talk"
ROOM_NAME="Gameworld: ${NAME_WORLD}"
PROBE_HOST=127.0.0.1
# Abgleich alle 300 s plus Durchlauf des Loops; das Skript erzwingt ihn nicht.
RECONCILE_WAIT=330
TEXT_START="Die Welt ist gestartet."
TEXT_STOP="Die Welt ist gestoppt."
TEXT_JOIN="ist jetzt in der Welt."
TEXT_LEAVE="hat die Welt verlassen."
# Kinderchat-Nachricht des Tests; sie darf nie im ExApp-Log stehen.
CHAT_MARKER="Smoke Kinderchat 4711"
EXAPP_LOG="${REPO_ROOT}/.dev/exapp.log"
BACKEND_PORT=10040

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

PASSED=0
FAILED=0
TOTAL=0
WORLD_ID=""
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

# skip GRUND -> eine Prüfung, die im Dev-Stack nichts belegen kann, ehrlich ausweisen statt
# grün zählen (WR-08). Zählt weder als bestanden noch als fehlgeschlagen.
SKIPPED=0
skip() {
	SKIPPED=$((SKIPPED + 1))
	printf 'ÜBERSPRUNGEN: %s\n' "$1"
}

# backend_post BENUTZER PFAD KÖRPER -> HTTP-Code; ruft das ExApp-Backend direkt mit
# AppAPI-Authentifizierung (Secret aus .dev/exapp.secret), wie AppAPI selbst. BENUTZER leer
# heißt: ohne Nutzer, so ruft AppAPIs talk_proxy den Bot-Webhook auf.
backend_post() {
	secret=$(cat "${REPO_ROOT}/.dev/exapp.secret" 2>/dev/null || true)
	version=$(sed -n 's:.*<version>\(.*\)</version>.*:\1:p' "${REPO_ROOT}/appinfo/info.xml" | head -n 1)
	[ -n "${secret}" ] && [ -n "${version}" ] || {
		printf '000'
		return 0
	}
	auth=$(printf '%s:%s' "$1" "${secret}" | base64 | tr -d '\n')
	curl -s -X POST -H 'EX-APP-ID: gameworld' -H "EX-APP-VERSION: ${version}" -H 'AA-VERSION: 34.0.0' \
		-H "AUTHORIZATION-APP-API: ${auth}" -H 'Content-Type: application/json' -d "$3" -o /dev/null \
		-w '%{http_code}' "http://127.0.0.1:${BACKEND_PORT}$2" 2>/dev/null || printf '000'
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

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
not() { ! "$@"; }

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

# call AUTH METHODE URL AUSGABE [JSON] -> HTTP-Code; OCS-Antworten als JSON.
call() {
	if [ -n "${5:-}" ]; then
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Accept: application/json' \
			-H 'Content-Type: application/json' -X "$2" -d "$5" -o "$4" -w '%{http_code}' "$3" 2>/dev/null \
			|| printf '000'
	else
		curl -s -u "$1" -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' -H 'Accept: application/json' \
			-X "$2" -o "$4" -w '%{http_code}' "$3" 2>/dev/null || printf '000'
	fi
}

http_code() {
	call "${ADMIN_AUTH}" "$@"
}

cleanup() {
	status=$?
	if [ -n "${WORLD_ID}" ]; then
		http_code DELETE "${API_URL}/worlds/${WORLD_ID}" /dev/null >/dev/null 2>&1 || true
		for container in $(docker ps -aq --filter "label=gameworld.world_id=${WORLD_ID}" 2>/dev/null); do
			docker rm -f -v "${container}" >/dev/null 2>&1 || true
		done
		for volume in $(docker volume ls -q 2>/dev/null | grep -e "-${WORLD_ID}\$" || true); do
			docker volume rm "${volume}" >/dev/null 2>&1 || true
		done
	fi
	occ user:delete "${GUEST}" >/dev/null 2>&1 || true
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

wait_status() {
	waited=0
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		[ "${waited}" -lt "$3" ] || return 1
		sleep 1
		waited=$((waited + 1))
	done
}

# Token des Raums "Gameworld: Abnahme Talk" aus Sicht von admin, leer, wenn keiner da ist.
room_token() {
	http_code GET "${SPREED}/v4/room" "${WORK_DIR}/rooms.json" >/dev/null
	jq -r --arg n "${ROOM_NAME}" '[.ocs.data[]? | select(.name == $n) | .token][0] // empty' \
		"${WORK_DIR}/rooms.json" 2>/dev/null || true
}

wait_room() {
	waited=0
	while :; do
		TOKEN=$(room_token)
		[ -n "${TOKEN}" ] && return 0
		[ "${waited}" -lt "$1" ] || return 1
		sleep 2
		waited=$((waited + 2))
	done
}

room_field() {
	http_code GET "${SPREED}/v4/room/${TOKEN}" "${WORK_DIR}/room.json" >/dev/null
	jq -r ".ocs.data.$1 // empty" "${WORK_DIR}/room.json" 2>/dev/null || true
}

# Teilnehmer als Zeilen "actorType actorId participantType", sortiert.
participants() {
	http_code GET "${SPREED}/v4/room/${TOKEN}/participants" "${WORK_DIR}/parts.json" >/dev/null
	jq -r '.ocs.data[]? | "\(.actorType) \(.actorId) \(.participantType)"' "${WORK_DIR}/parts.json" 2>/dev/null \
		| tr -d '\r' | sort || true
}

user_ids() {
	participants | awk '$1 == "users" {print $2}' | sort | paste -sd, -
}

participant_type() {
	participants | awk -v u="$1" '$1 == "users" && $2 == u {print $3}'
}

has_user() {
	participants | awk -v u="$1" '$1 == "users" && $2 == u {found = 1} END {exit !found}'
}

wait_without_user() {
	waited=0
	while :; do
		has_user "$1" || return 0
		[ "${waited}" -lt "$2" ] || return 1
		sleep 5
		waited=$((waited + 5))
	done
}

# bot_said TEXT SEKUNDEN -> 0, sobald eine Nachricht des Bots TEXT enthält
bot_said() {
	waited=0
	while :; do
		http_code GET "${SPREED}/v1/chat/${TOKEN}?lookIntoFuture=0&limit=100&setReadMarker=0" \
			"${WORK_DIR}/chat.json" >/dev/null
		hits=$(jq -r --arg t "$1" \
			'[.ocs.data[]? | select(.actorType == "bots" and (.message | contains($t)))] | length' \
			"${WORK_DIR}/chat.json" 2>/dev/null || printf '0')
		[ "${hits:-0}" -gt 0 ] && return 0
		[ "${waited}" -lt "$2" ] || return 1
		sleep 3
		waited=$((waited + 3))
	done
}

# bot_count TEXT -> Zahl der Bot-Nachrichten mit TEXT (frisch gelesen)
bot_count() {
	http_code GET "${SPREED}/v1/chat/${TOKEN}?lookIntoFuture=0&limit=100&setReadMarker=0" \
		"${WORK_DIR}/chat.json" >/dev/null
	jq -r --arg t "$1" '[.ocs.data[]? | select(.actorType == "bots" and (.message | contains($t)))] | length' \
		"${WORK_DIR}/chat.json" 2>/dev/null || printf 'x'
}

# Erfolgreiche Webhook-Aufrufe laut Zugriffslog der ExApp (uvicorn loggt nur Pfad und Status).
# Ohne lesbares Log x statt einer Zahl: dann scheitert jeder Vergleich (WR-08).
webhook_hits() {
	if [ ! -r "${EXAPP_LOG}" ]; then
		printf 'x'
		return 0
	fi
	grep -c -F 'POST /talk/bot HTTP/1.1" 200' "${EXAPP_LOG}" 2>/dev/null || true
}

# num WERT -> 0, wenn WERT eine nicht leere Ganzzahl ist
num() { printf '%s' "$1" | grep -Eq '^[0-9]+$'; }

bot_names() {
	jq -r '[.ocs.data[]? | select(.actorType == "bots") | .actorDisplayName] | unique | join(",")' \
		"${WORK_DIR}/chat.json" 2>/dev/null || true
}

probe() {
	out=$1
	shift
	(cd "${REPO_ROOT}" && uv run python -m tests.e2e.luanti_probe "${PROBE_HOST}" "${PORT}" "$@") \
		>"${out}" 2>"${out}.err" || printf '{"result":"prober_error"}' >"${out}"
}

printf '== Voraussetzungen ==\n'
curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1 || abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}"
command -v jq >/dev/null 2>&1 || abort "jq fehlt"
SPREED_STATE=$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty' 2>/dev/null || true)
check "(1) Talk (spreed) ist aktiviert (Version ${SPREED_STATE:-keine})" ne "${SPREED_STATE}" ""
[ -n "${SPREED_STATE}" ] || abort "ohne Talk sind die Folgeprüfungen sinnlos"
CODE=$(http_code GET "${API_URL}/talk" "${WORK_DIR}/talk.json")
check "GET /api/talk HTTP 200 mit available und bots true (ist ${CODE})" eq \
	"${CODE} $(jq -r '"\(.available) \(.bots)"' "${WORK_DIR}/talk.json" 2>/dev/null || true)" "200 true true"

# Reste eines abgebrochenen Laufs entfernen.
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --arg n "${NAME_WORLD}" '.worlds[]? | select(.name == $n) | .id' "${WORK_DIR}/pre.json" \
	2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	http_code DELETE "${API_URL}/worlds/${old_id}" /dev/null >/dev/null || true
done
occ user:delete "${GUEST}" >/dev/null 2>&1 || true

printf '\n== (2) Raum je Welt ==\n'
CODE=$(http_code POST "${API_URL}/worlds" "${WORK_DIR}/world.json" "{\"name\":\"${NAME_WORLD}\",\"preset\":\"mtg_kreativ\"}")
WORLD_ID=$(jq -r '.id // empty' "${WORK_DIR}/world.json" 2>/dev/null || true)
check "POST '${NAME_WORLD}' HTTP 201 (ist ${CODE})" eq "${CODE}" 201
printf '%s' "${WORLD_ID}" | grep -Eq '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites" "${WORK_DIR}/inv.json" \
	"{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "${KID} eingeladen, HTTP 200 (ist ${CODE})" eq "${CODE}" 200
TOKEN=""
check "Raum '${ROOM_NAME}' für admin binnen 60 s" wait_room 60
[ -n "${TOKEN}" ] || abort "kein Raum, Folgeprüfungen sinnlos"
check "Raum ist Gruppenunterhaltung, Typ 2 (ist $(room_field type))" eq "$(room_field type)" 2
check "Raum ist nicht auffindbar, listable 0 (ist $(room_field listable))" eq "$(room_field listable)" 0

printf '\n== (3) Exakte Mitglieder ==\n'
waited=0
while [ "$(user_ids)" != "admin,${KID}" ] && [ "${waited}" -lt 30 ]; do
	sleep 2
	waited=$((waited + 2))
done
check "Teilnehmer sind genau admin und ${KID} (ist $(user_ids))" eq "$(user_ids)" "admin,${KID}"
check "keine Teilnehmer außer Nutzern (Gruppen, Gäste)" eq \
	"$(participants | awk '$1 != "users"' | wc -l | tr -d ' ')" 0
ADMIN_TYPE=$(participant_type admin)
check "admin ist Owner oder Moderator (Typ ${ADMIN_TYPE:-leer})" sh -c '[ "$1" = 1 ] || [ "$1" = 2 ]' _ "${ADMIN_TYPE}"
check "${KID} ist normaler Teilnehmer, Typ 3 (ist $(participant_type "${KID}"))" eq "$(participant_type "${KID}")" 3

printf '\n== (4) Kind kann niemanden hinzufügen ==\n'
add_user "${GUEST}" "${GUEST_PASS}" "Gast Talk" || abort "Konto ${GUEST} ließ sich nach drei Versuchen nicht anlegen (occ-Ausgabe oben)"
ADD_BODY="{\"newParticipant\":\"${GUEST}\",\"source\":\"users\"}"
CODE=$(call "${KID_AUTH}" POST "${SPREED}/v4/room/${TOKEN}/participants" "${WORK_DIR}/kidadd.json" "${ADD_BODY}")
# Talk antwortet Nicht-Moderatoren mit 403 (spreed NotAModeratorException, Quelltext Talk
# 24.0.6 im Dev-Stack); 000, 500 oder 404 bestehen nicht mehr (WR-08).
check "${KID} fügt ${GUEST} hinzu: abgewiesen, HTTP 403 (ist ${CODE})" eq "${CODE}" 403
check "${GUEST} ist danach nicht im Raum" not has_user "${GUEST}"

printf '\n== (5) Abgleich entfernt Fremde ==\n'
CODE=$(http_code POST "${SPREED}/v4/room/${TOKEN}/participants" "${WORK_DIR}/adminadd.json" "${ADD_BODY}")
check "Positivkontrolle: admin fügt ${GUEST} in Talk hinzu, HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Positivkontrolle: ${GUEST} ist jetzt im Raum" has_user "${GUEST}"
printf 'warte bis zu %s s auf den 5-min-Abgleich der ExApp\n' "${RECONCILE_WAIT}"
check "${GUEST} nach dem Abgleich wieder entfernt (höchstens ${RECONCILE_WAIT} s)" \
	wait_without_user "${GUEST}" "${RECONCILE_WAIT}"

printf '\n== (6) Bot im Raum ==\n'
CODE=$(http_code GET "${SPREED}/v1/bot/${TOKEN}" "${WORK_DIR}/bots.json")
BOT_STATE=$(jq -r '[.ocs.data[]? | select(.name == "Gameworld") | .state][0] // empty' "${WORK_DIR}/bots.json" \
	2>/dev/null || true)
check "Bot Gameworld im Raum aktiv (HTTP ${CODE}, state ${BOT_STATE:-leer})" eq "${CODE} ${BOT_STATE}" "200 1"

printf '\n== (7) Bot meldet Stopp und Start ==\n'
check "Welt running binnen 60 s" wait_status "${WORLD_ID}" running 60
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/stop" "${WORK_DIR}/stop.json")
check "POST stop HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Bot schreibt '${TEXT_STOP}' binnen 60 s" bot_said "${TEXT_STOP}" 60
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/start" "${WORK_DIR}/start.json")
check "POST start HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Welt wieder running binnen 60 s" wait_status "${WORLD_ID}" running 60
check "Bot schreibt '${TEXT_START}' binnen 60 s" bot_said "${TEXT_START}" 60
# Talk hängt an Bot-Namen selbst " (Bot)" an.
check "Bot-Nachrichten stehen unter dem Namen Gameworld (ist $(bot_names))" \
	sh -c '[ "$1" = "Gameworld (Bot)" ] || [ "$1" = Gameworld ]' _ "$(bot_names)"

printf '\n== (8) Bot meldet Beitritt ==\n'
CONTAINER=$(docker ps -q --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=${WORLD_ID}")
PORT=$(docker port "${CONTAINER}" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r')
http_code GET "${API_URL}/worlds/${WORLD_ID}/players" "${WORK_DIR}/players.json" >/dev/null
KID_NAME=$(jq -r --arg u "${KID}" '.players[]? | select(.nc_user == $u) | .player_name // empty' \
	"${WORK_DIR}/players.json" 2>/dev/null || true)
KID_PW=$(jq -r --arg u "${KID}" '.players[]? | select(.nc_user == $u) | .password // empty' \
	"${WORK_DIR}/players.json" 2>/dev/null || true)
check "Spielername und Passwort für ${KID} vorhanden (Name ${KID_NAME:-leer}, Länge ${#KID_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ]' _ "${KID_NAME}" "${KID_PW}"
attempt=0
JOINED=1
while :; do
	probe "${WORK_DIR}/join.json" "${KID_NAME}" "${KID_PW}" --hold 5 --timeout 30
	if [ "$(jq -r '.result' "${WORK_DIR}/join.json" 2>/dev/null)" = held ]; then
		JOINED=0
		break
	fi
	attempt=$((attempt + 1))
	[ "${attempt}" -lt 10 ] || break
	sleep 3
done
check "${KID} tritt der Welt bei (Prober: Sitzung gehalten)" eq "${JOINED}" 0
check "Bot schreibt '... ${TEXT_JOIN}' binnen 60 s" bot_said "${TEXT_JOIN}" 60
# Drossel D-22: erneut rein und raus binnen 10 Minuten bringt keine neue Meldung.
# Steht die Beitrittsmeldung schon beim ersten Blick im Chat, käme der zweite Beitritt
# sonst in die Wiederbeitritts-Sperre der Welt (etwa 2 s, "Bitte einen Moment warten").
sleep 2.5
probe "${WORK_DIR}/rejoin.json" "${KID_NAME}" "${KID_PW}" --hold 5 --timeout 30
check "Positivkontrolle: zweiter Beitritt gelingt (ist $(jq -r '"\(.result) \(.reason // "")"' "${WORK_DIR}/rejoin.json" 2>/dev/null))" \
	eq "$(jq -r '.result' "${WORK_DIR}/rejoin.json" 2>/dev/null)" held
# Takt 15 s plus Loop 5 s: nach 30 s wären neue Meldungen sicher im Chat.
sleep 30
check "Drossel: genau eine Beitrittsmeldung und keine Verlassen-Meldung (ist $(bot_count "${TEXT_JOIN}") und $(bot_count "${TEXT_LEAVE}"))" \
	eq "$(bot_count "${TEXT_JOIN}") $(bot_count "${TEXT_LEAVE}")" "1 0"

printf '\n== (8b) Webhook verwirft Kinderchats ==\n'
CODE=$(call "${KID_AUTH}" POST "${SPREED}/v1/chat/${TOKEN}" "${WORK_DIR}/kidmsg.json" \
	"{\"message\":\"${CHAT_MARKER}\"}")
check "Positivkontrolle: ${KID} schreibt in den Raum, HTTP 201 (ist ${CODE})" eq "${CODE}" 201
# Im Dev-Stack erreicht Talk die Bot-URL nicht: AppAPI trägt sie mit der Adresse
# des Browsers ein (localhost:8091), im Container lauscht dort niemand. Dass ein
# echter Kinderchat über Talk ankommt und verworfen wird, belegt darum nur eine
# Instanz mit erreichbarer eigener URL (Prüfpunkt Phase 6). Statt eines leeren
# Grüns (WR-08) prüft das Skript den Webhook direkt am Backend, so wie AppAPI ihn
# aufruft, mit Positivkontrolle für den Zähler.
skip "echter Webhook von Talk mit Kinderchat (im Dev-Stack nicht erreichbar, Prüfpunkt Phase 6)"
WEBHOOK_BEFORE=$(webhook_hits)
CHAT_BODY="{\"type\":\"Create\",\"object\":{\"name\":\"message\",\"content\":\"{\\\"message\\\":\\\"${CHAT_MARKER}\\\"}\"}}"
CODE=$(backend_post "" /talk/bot "${CHAT_BODY}")
check "Webhook wie von AppAPI (ohne Nutzer) direkt am Backend: HTTP 200 (ist ${CODE})" eq "${CODE}" 200
sleep 1
WEBHOOK_AFTER=$(webhook_hits)
check "Positivkontrolle: das Zugriffslog zählt diesen Webhook (${WEBHOOK_BEFORE} -> ${WEBHOOK_AFTER})" \
	sh -c 'printf "%s %s" "$1" "$2" | grep -Eq "^[0-9]+ [0-9]+$" && [ "$2" -eq $(($1 + 1)) ]' _ \
	"${WEBHOOK_BEFORE}" "${WEBHOOK_AFTER}"
check "Chatinhalt des Webhooks steht nicht im Log der ExApp (Log lesbar, 0 Treffer)" sh -c \
	'[ -r "$1" ] && [ "$(grep -c -F -- "$2" "$1" || true)" = 0 ]' _ "${EXAPP_LOG}" "${CHAT_MARKER}"
# IN-01: Über den Nutzer-Proxy käme jedes Konto zum Webhook; mit Nutzer gilt 403.
CODE=$(backend_post "${KID}" /talk/bot "${CHAT_BODY}")
check "Negativkontrolle: Webhook mit Nutzer ${KID} HTTP 403 (ist ${CODE})" eq "${CODE}" 403
WEBHOOK_BEFORE=$(webhook_hits)
CODE=$(curl -s -X POST -H 'OCS-APIRequest: true' -H 'Content-Type: application/json' \
	-H 'X-Nextcloud-Talk-Random: smoke' -H 'X-Nextcloud-Talk-Signature: 00' \
	-d "{\"type\":\"Create\",\"object\":{\"content\":\"${CHAT_MARKER}\"}}" -o /dev/null -w '%{http_code}' \
	"${NEXTCLOUD_URL}/ocs/v2.php/apps/app_api/api/v1/talk_proxy/gameworld/talk/bot" 2>/dev/null || printf '000')
check "talk_proxy mit gefälschter Signatur: AppAPI weist ab (HTTP ${CODE}, erwartet 404)" eq "${CODE}" 404
sleep 1
WEBHOOK_AFTER=$(webhook_hits)
check "gefälschter Aufruf erreicht die ExApp nicht (Webhook-Treffer ${WEBHOOK_BEFORE} -> ${WEBHOOK_AFTER}, Zahlen)" \
	sh -c 'printf "%s %s" "$1" "$2" | grep -Eq "^[0-9]+ [0-9]+$" && [ "$1" = "$2" ]' _ \
	"${WEBHOOK_BEFORE}" "${WEBHOOK_AFTER}"

printf '\n== (9) Nur lesen ==\n'
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/talk/read-only" "${WORK_DIR}/ro.json")
check "POST talk/read-only HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Raum readOnly 1 (ist $(room_field readOnly))" eq "$(room_field readOnly)" 1
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}/talk/read-only" "${WORK_DIR}/ro.json")
check "DELETE talk/read-only HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "Raum readOnly 0 (ist $(room_field readOnly))" eq "$(room_field readOnly)" 0

printf '\n== (10) Ausladen entfernt aus dem Raum ==\n'
CODE=$(http_code POST "${API_URL}/worlds/${WORLD_ID}/invites/remove" "${WORK_DIR}/rm.json" \
	"{\"kind\":\"user\",\"target\":\"${KID}\"}")
check "${KID} ausgeladen, HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "${KID} binnen 30 s nicht mehr Teilnehmer" wait_without_user "${KID}" 30

printf '\n== (11) Raum verschwindet mit der Welt ==\n'
CODE=$(http_code DELETE "${API_URL}/worlds/${WORLD_ID}" "${WORK_DIR}/del.json")
check "DELETE Welt HTTP 200 oder 204 (ist ${CODE})" sh -c '[ "$1" = 200 ] || [ "$1" = 204 ]' _ "${CODE}"
gone=1
waited=0
while [ "${waited}" -le 60 ]; do
	CODE=$(http_code GET "${SPREED}/v4/room/${TOKEN}" "${WORK_DIR}/gone.json")
	if [ "${CODE}" = 404 ]; then
		gone=0
		break
	fi
	sleep 3
	waited=$((waited + 3))
done
check "Raum für admin binnen 60 s weg (GET HTTP 404)" eq "${gone}" 0
check "kein Raum '${ROOM_NAME}' mehr in der Liste von admin" eq "$(room_token)" ""
WORLD_ID_DONE=${WORLD_ID}
WORLD_ID=""
check "kein Container der Welt mehr" eq \
	"$(docker ps -aq --filter "label=gameworld.world_id=${WORLD_ID_DONE}" | wc -l | tr -d ' ')" 0

if [ "${SKIPPED}" -gt 0 ]; then
	printf '%s Prüfung(en) übersprungen, im Dev-Stack nicht belegbar (siehe ÜBERSPRUNGEN)\n' "${SKIPPED}"
fi
printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
[ "${FAILED}" -eq 0 ]
