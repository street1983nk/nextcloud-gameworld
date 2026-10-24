#!/bin/sh
# Phasenabnahme Phase 6: prüft die sieben Erfolgskriterien aus .planning/ROADMAP.md
# (Store-Release) gegen eine echte Nextcloud 34.0.3 mit echter ExApp und echtem
# Docker. Am Ende ruft es die Abnahme von Phase 5 als Regression (sie ruft Phase
# 4.1 bis 1 selbst auf).
#
# Zwei Modi (GAMEWORLD_DEPLOY):
#   manual (Standard) Dev-Stack scripts/dev/compose.yaml, ExApp als Host-Prozess
#                     über manual_install (sh scripts/dev/register-exapp.sh).
#   harp              Test-Instanz scripts/dev/harp.compose.yaml, ExApp als
#                     Container aus der lokalen Registry über einen echten
#                     HaRP-Daemon (sh scripts/dev/harp-install.sh). Kriterium 1
#                     vollständig (Registry-Image, uid 10001) belegt erst dieser
#                     Modus; die Store-Installation selbst folgt in 06-15.
#
# Kriterien, je mit Negativ- und Positivkontrolle:
#   K1 Installation: harp: app_api:app:list mit gameworld (Name Gameworld) auf
#      harp_dev, ExApp-Container aus localhost:5000 als 10001:10001 und healthy,
#      /exapps/ über HaRP ohne Anmeldung 403 (Negativ), mit Anmeldung 200 (Positiv);
#      beide Modi: Welt anlegen, nicht eingeladener Name abgewiesen (Negativ),
#      eingeladenes Kind tritt bei (Positiv, Prober-CLI).
#   K2 Setup-Check: Docker-Proxy der aktiven Instanz gestoppt, GET /api/setup-check
#      meldet proxy_refused, proxy_dns oder proxy_timeout mit Doku-Anker
#      #setup-check (Negativ); Proxy wieder an, Setup-Check ohne Fehler (Positiv).
#   K3 Lebenszyklus: harp (eigene Test-Instanz): app_api:app:disable, binnen 60 s
#      kein Container der eigenen Instanz mehr, Volume noch da; enable, die Welt
#      läuft wieder und das Kind tritt bei. Im Modus manual wird NICHT deaktiviert:
#      Der Instanz gehören dort die laufenden Welten der Dev-Umgebung (D-17 räumte
#      sie ab). Beide Modi: Orphan-Container (Label gameworld.managed=true,
#      gameworld.instance=acceptance-orphan) und Volume gameworld-acceptance-orphan-x
#      per docker CLI; GET /api/admin/orphans als admin listet beide (Positiv), als
#      gw-lehrer 403 (Negativ); Entfernen per API, docker CLI findet beide nicht
#      mehr; scripts/gameworld-orphans.sh ohne Optionen ändert nichts und nennt die
#      Orphans nicht mehr (Grundlinie fremder Objekte, Gegenprobe gegen docker CLI).
#   K4 Listing: info.xml mit genau einem <name>, de/fr-Beschreibungen mit
#      Privilegien-Überschrift, docs/privacy.md und privacy.de.md; Negativ: eine
#      erfundene Überschrift findet dasselbe grep nicht.
#   K5 Verwalter-Gruppen: gw-lehrer vor der Freischaltung 403 (Negativ), danach 200
#      (Positiv); gw-lehrer ändert keine Verwalter-Gruppen (403); lädt gw-kind-k
#      (200) und die Gruppe klasse (200) ein, gw-kind-out (403, Text) und die Gruppe
#      admin (403) nicht; 404-Falle: ein von admin direkt eingeladenes Konto
#      außerhalb der Gruppen von gw-lehrer übersteht zwei Besuche von gw-lehrer im
#      Abstand des Abgleich-Intervalls (Zugänge vorher gleich nachher); gw-kind-k
#      auf jeder Verwaltungsroute 403, auf /api/me und /api/my/worlds 200.
#   K6 Erwachsen: Regel "kein Spieltag" für gw-erwachsen, Beitritt abgewiesen
#      (Negativ); adult true, Beitritt gelingt (Positiv); gw-kind-k setzt adult für
#      sich 403, Flag unverändert; adult false trennt die gehaltene Sitzung;
#      minetest.conf vorher gleich nachher. Pause für alle (gw-lehrer): gw-kind-k
#      getrennt mit Pausentext (Negativ), gw-erwachsen tritt bei (Positiv), Ende
#      HTTP 200. Geschlossenes Welt-Zeitfenster: gw-kind-k abgewiesen mit
#      Fenstertext, gw-erwachsen tritt bei, DELETE 200; danach weder Pause noch
#      Fenster aktiv.
#   K7 Talk: gw-alt (Verwalter über lehrkraefte) besitzt den Raum seiner Welt;
#      aus lehrkraefte entfernt, zeigt GET /api/talk owner_not_admin true; recreate
#      liefert ein neues Token ohne gw-alt; zweite Welt von gw-alt, gw-alt gelöscht,
#      nach dem Abgleich owner_not_admin false und der Raum für admin erreichbar.
#      Übersprung NUR mit GAMEWORLD_SKIP_TALK=1, sonst ist fehlendes Talk ein Fehler.
#   K8 Language (D-25, D-27): gw6-en (manager, core lang en) gets /api/me language en,
#      gw6-lehrer (de) gets de; gw6-kind-en gets the English 403 text, a German kid
#      still the exact German one; a world created by gw6-en is en, one by gw6-lehrer
#      de; language xx 422, set by a player 403; a stranger is refused in English on the
#      en world and in German on the de world; a backup with a held session shows the
#      English chat hint and disconnect text; switching to fr sets
#      language_restart_needed until the restart, then the refusal is French; the join
#      attempt notification is English for gw6-en and German for gw6-lehrer (on the
#      daily throttle: summary message as positive control, announced as a hint line).
#
# Bewusst unabhängig vom Implementierungsmuster: Belege kommen aus curl gegen den
# AppAPI-Proxy, HaRP und die Talk-OCS-API mit echten Nextcloud-Konten, aus occ, aus
# der docker CLI (inspect, ps, volume, cp, stop/start nur des Docker-Proxys der
# aktiven Instanz), aus jq und grep. Einziges Python-Werkzeug des Projekts ist der
# Session-Prober (tests/e2e/luanti_probe.py) über seine CLI; die Uhrzeit der
# Haushalts-Zeitzone rechnet die Standardbibliothek (zoneinfo).
#
# Fixtures: Gruppen gw6-lehrkraefte und gw6-klasse; Wegwerfkonten gw6-lehrer
# (gw6-lehrkraefte, gw6-klasse), gw6-kind-k (gw6-klasse), gw6-kind-out (keine Gruppe),
# gw6-erwachsen (gw6-klasse), gw6-alt (gw6-lehrkraefte), for K8 gw6-en (both groups,
# lang en) and gw6-kind-en (gw6-klasse, lang en). All other accounts get core lang de.
# The gw6 prefix keeps the demo environment (gw-lehrer, lehrkraefte, klasse) untouched. Spielpasswörter erscheinen nie in der Ausgabe, nur ihre
# Länge. Zugangsdaten hier sind reine Dev-Konten von Loopback-Instanzen.
#
# Voraussetzung:
#   manual: docker compose -f scripts/dev/compose.yaml up -d
#           sh scripts/dev/register-exapp.sh   (Talk: docs/dev-setup.md)
#   harp:   sh scripts/dev/harp-install.sh
#
# Exit 0 nur, wenn jede Prüfung bestanden ist. Ein trap räumt in jedem Fall auf:
# Abnahme-Welten, Pause, Zeitfenster, Regeln, Verwalter-Gruppe, Konten, Gruppen,
# Orphan-Objekte, Docker-Proxy wieder an, ExApp wieder aktiviert. Fremde Welten
# (andere Instanzen, laufende Dev-Welten) bleiben unangetastet; die Prüfung auf
# übrig gebliebene Container zählt nur, was dieser Lauf neu hinterlassen hätte.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)
PHASE5_SCRIPT="${SCRIPT_DIR}/acceptance-phase5.sh"
ORPHANS_SCRIPT="${REPO_ROOT}/scripts/gameworld-orphans.sh"
INFO_XML="${REPO_ROOT}/appinfo/info.xml"
DEPLOY=${GAMEWORLD_DEPLOY:-manual}
case "${DEPLOY}" in
manual)
	NEXTCLOUD_URL=http://localhost:${GAMEWORLD_NC_PORT:-8091}
	ADMIN_AUTH=admin:gameworld-dev-admin
	NC_CONTAINER=gameworld-dev-app-1
	PROXY_CONTAINER=gameworld-dev-gameworld-docker-proxy-1
	;;
harp)
	NEXTCLOUD_URL=http://localhost:${GAMEWORLD_HARP_PORT:-8093}
	ADMIN_AUTH=admin:gameworld-harp-admin
	NC_CONTAINER=gameworld-dev-harp-nc
	PROXY_CONTAINER=gameworld-dev-harp-docker-proxy
	;;
*)
	printf 'ABBRUCH: GAMEWORLD_DEPLOY ist manual oder harp, nicht %s\n' "${DEPLOY}" >&2
	exit 1
	;;
esac
EXAPP_CONTAINER=nc_app_gameworld
HARP_DAEMON=harp_dev
LOCAL_IMAGE_PREFIX=localhost:5000/street1983nk/gameworld:
BACKEND_PORT=10040
PROXY_BASE="${NEXTCLOUD_URL}/index.php/apps/app_api/proxy/gameworld"
API_URL="${PROXY_BASE}/api"
SPREED="${NEXTCLOUD_URL}/ocs/v2.php/apps/spreed/api/v4"
PROBE_HOST=127.0.0.1
SESSION_TIMEOUT=30

# Own gw6-* names: the demo environment of 06-13 uses gw-lehrer, lehrkraefte and klasse
# (manager group) and must stay untouched; reset_fixtures deletes these fixtures.
G_LEHR=gw6-lehrkraefte
G_KLASSE=gw6-klasse
LEHRER=gw6-lehrer
KIND=gw6-kind-k
OUT=gw6-kind-out
ERW=gw6-erwachsen
ALT=gw6-alt
EN8=gw6-en
KIDEN8=gw6-kind-en
LEHRER_AUTH="${LEHRER}:gw-lehrer-dev-pass-6"
KIND_AUTH="${KIND}:gw-kind-k-dev-pass-6"
OUT_AUTH="${OUT}:gw-kind-out-dev-pass-6"
ERW_AUTH="${ERW}:gw-erwachsen-dev-pass-6"
ALT_AUTH="${ALT}:gw-alt-dev-pass-6"
EN8_AUTH="${EN8}:gw-en-dev-pass-8"
KIDEN8_AUTH="${KIDEN8}:gw-kind-en-dev-pass-8"
ACCOUNTS="${LEHRER} ${KIND} ${OUT} ${ERW} ${ALT} ${EN8} ${KIDEN8}"

W1_NAME="Abnahme Store"
W2_NAME="Abnahme Klasse"
W3_NAME="Abnahme Talk Alt"
W4_NAME="Abnahme Talk Erbe"
W8_NAME="Abnahme Sprache EN"
W9_NAME="Abnahme Sprache DE"
ACCEPTANCE_WORLDS='["Abnahme Store","Abnahme Klasse","Abnahme Talk Alt","Abnahme Talk Erbe","Abnahme Sprache EN","Abnahme Sprache DE"]'
ORPHAN_INSTANCE=acceptance-orphan
ORPHAN_CONTAINER=gameworld-acceptance-orphan
ORPHAN_VOLUME=gameworld-acceptance-orphan-x
LUANTI_IMAGE=ghcr.io/luanti-org/luanti:5.17.0
CONF_PATH=/var/lib/minetest/minetest.conf
DOC_ANCHOR="install.md#setup-check"
# Kindertexte aus provisioner/time_mod.py und access_mod.py (Teilstrings, eigene Literale).
TEXT_TAG="Heute ist kein Spieltag"
TEXT_PAUSE="Kurze Pause!"
TEXT_WELT="Diese Welt ist gerade zu"
TEXT_DENY="nicht eingeladen"
TEXT_OUT_OF_SCOPE="Dieses Konto ist in keiner deiner Gruppen."
TEXT_GROUP_OUT_OF_SCOPE="Diese Gruppe gehört nicht zu deinen Gruppen."
# Abgleich beim Verwalter-Besuch höchstens alle 60 s (access/service.py), Talk alle 300 s.
SYNC_WAIT=65
# K8: own expected literals, copied from the catalogs as an independent cross-check
# (catalog_en.py roles.MSG_FORBIDDEN, access_mod.py and time_mod.py MOD_TEXTS, notify/texts.py).
TEXT_FORBIDDEN_DE="Nur Eltern können Welten verwalten."
TEXT_FORBIDDEN_EN="Only parents can manage worlds."
TEXT_DENY_EN="You are not invited to this world."
TEXT_DENY_FR="Tu n’as pas d’invitation pour ce monde."
TEXT_HALT_SOON_EN="The world is taking a short break soon."
TEXT_HALT_EN="The world is taking a short break. It will be back in a moment."
TEXT_HALT_DE="Die Welt macht kurz Pause"
SUBJECT_ATTEMPT_EN="Unknown player name in"
SUBJECT_ATTEMPT_DE="Unbekannter Spielername in"
SUBJECT_SUMMARY_EN="More join attempts"
SUBJECT_SUMMARY_DE="Weitere Beitrittsversuche"
NOTIFY_URL="${NEXTCLOUD_URL}/ocs/v2.php/apps/notifications/api/v2/notifications?format=json"
NOTIFY_WAIT=120
TALK_WAIT=480

PYTHONUTF8=1
PYTHONIOENCODING=utf-8
export PYTHONUTF8 PYTHONIOENCODING

PASSED=0
FAILED=0
TOTAL=0
WORLD_IDS=""
KID_JOB=""
ERW_JOB=""
PROXY_STOPPED=0
APP_DISABLED=0
VG_ADDED=0
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

eq() { [ "$1" = "$2" ]; }
ne() { [ "$1" != "$2" ]; }
not() { ! "$@"; }
matches() { printf '%s' "$1" | grep -Eq "$2"; }
contains() { case "$1" in *"$2"*) return 0 ;; *) return 1 ;; esac; }

occ() {
	docker exec -u www-data "${NC_CONTAINER}" php occ "$@"
}

# add_user KONTO PASSWORT ANZEIGENAME -> Wegwerfkonto frisch anlegen (Muster acceptance-phase5.sh)
add_user() {
	occ user:delete "$1" >/dev/null 2>&1 || true
	add_try=1
	while [ "${add_try}" -le 3 ]; do
		if docker exec -u www-data -e OC_PASS="$2" "${NC_CONTAINER}" \
			php occ user:add --password-from-env --display-name="$3" "$1" >"${WORK_DIR}/user-add.log" 2>&1; then
			# German dev accounts: without a setting Nextcloud reports its default language,
			# and every German expected text of K1 to K7 assumes a German account (D-25).
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

user_present() { occ user:info "$1" >/dev/null 2>&1; }
user_absent() { ! user_present "$1"; }

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

detail_of() { jq -r '.detail // empty' "$1" 2>/dev/null || true; }

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

deadline() { printf '%s' "$(($(date +%s) + $1))"; }
before() { [ "$(date +%s)" -lt "$1" ]; }

world_field() {
	http_code GET "${API_URL}/worlds" "${WORK_DIR}/field.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.id == \$id) | $2" "${WORK_DIR}/field.json" 2>/dev/null || true
}

wait_status() {
	until_ts=$(deadline "$3")
	while :; do
		[ "$(world_field "$1" '.status')" = "$2" ] && return 0
		before "${until_ts}" || return 1
		sleep 2
	done
}

wait_online() {
	until_ts=$(deadline "$3")
	while :; do
		[ "$(world_field "$1" "(.players // []) | index(\"$2\") != null")" = true ] && return 0
		before "${until_ts}" || return 1
		sleep 2
	done
}

# wait_code AUTH URL CODE SEKUNDEN -> 0, sobald GET URL den Code liefert
wait_code() {
	until_ts=$(deadline "$4")
	while :; do
		[ "$(call "$1" GET "$2" "${WORK_DIR}/wait.json")" = "$3" ] && return 0
		before "${until_ts}" || return 1
		sleep 3
	done
}

container_of() {
	docker ps -aq --no-trunc --filter "label=gameworld.managed=true" --filter "label=gameworld.world_id=$1" | head -n 1
}

port_of() {
	docker port "$1" 30000/udp 2>/dev/null | head -n 1 | awk -F: '{print $NF}' | tr -d '\r'
}

player_field() {
	jq -r --arg u "$2" ".players[]? | select(.nc_user == \$u) | .$3 // empty" "$1" 2>/dev/null || true
}

# create_world AUTH NAME -> setzt NEW_ID und NEW_CODE
create_world() {
	NEW_CODE=$(call "$1" POST "${API_URL}/worlds" "${WORK_DIR}/new-world.json" "{\"name\":\"$2\",\"preset\":\"mtg_kreativ\"}")
	NEW_ID=$(jq -r '.id // empty' "${WORK_DIR}/new-world.json" 2>/dev/null || true)
	remember_world "${NEW_ID}"
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

denied_with() {
	[ "$(jq -r --arg t "$2" '.result == "denied" and ((.reason // "") | contains($t))' "$1" 2>/dev/null)" = true ]
}

kicked_with() {
	[ "$(jq -r --arg t "$2" '.result == "kicked" and ((.reason // "") | contains($t))' "$1" 2>/dev/null)" = true ]
}

accepted() {
	[ "$(jq -r '.result' "$1" 2>/dev/null)" = auth_accept ]
}

# week TAGE -> Wochenplan: an TAGE (z. B. "1,2") erlaubt ohne Grenze, sonst kein Spieltag
week() {
	jq -nc --arg days "$1" '
		($days | split(",") | map(select(. != "") | tonumber)) as $on
		| [range(1; 8) as $d
			| if any($on[]; . == $d) then {weekday: $d, allowed: true} else {weekday: $d, allowed: false} end]'
}

# zone_now ZONE -> "MINUTE" (Minuten seit 0 Uhr in der Haushalts-Zeitzone)
zone_now() {
	(cd "${WORK_DIR}" && uv run --project "${REPO_ROOT}" python -I -c '
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo(sys.argv[1]))
print(now.hour * 60 + now.minute)
' "$1") 2>/dev/null | tr -d '\r'
}

# talk_field WELT JQ -> Feld aus GET /api/talk als admin
talk_field() {
	http_code GET "${API_URL}/talk" "${WORK_DIR}/talk.json" >/dev/null
	jq -r --arg id "$1" ".worlds[]? | select(.world_id == \$id) | $2" "${WORK_DIR}/talk.json" 2>/dev/null || true
}

wait_talk() {
	until_ts=$(deadline "$3")
	while :; do
		[ "$(talk_field "$1" "$2")" = true ] && return 0
		before "${until_ts}" || return 1
		sleep 10
	done
}

# fetch_parts TOKEN -> Teilnehmerliste als admin nach parts.json, HTTP-Code in PART_CODE (nie in $(...) aufrufen)
fetch_parts() {
	PART_CODE=$(http_code GET "${SPREED}/room/$1/participants" "${WORK_DIR}/parts.json")
}

# ptype KONTO -> participantType aus der zuletzt geholten Liste (leer, wenn nicht Teilnehmer)
ptype() {
	jq -r --arg u "$1" '[.ocs.data[]? | select(.actorType == "users" and .actorId == $u) | .participantType][0] // empty' \
		"${WORK_DIR}/parts.json" 2>/dev/null || true
}

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

docker_snapshot() {
	{
		docker ps -aq --no-trunc 2>/dev/null | sort
		docker volume ls -q 2>/dev/null | sort
	} | tr -d '\r'
}

proxy_start() {
	docker start "${PROXY_CONTAINER}" >/dev/null 2>&1 || return 1
	PROXY_STOPPED=0
}

reset_fixtures() {
	http_code POST "${API_URL}/pause/end" /dev/null >/dev/null 2>&1 || true
	for account in ${ERW} ${KIND}; do
		http_code POST "${API_URL}/players/adult" /dev/null "{\"nc_user\":\"${account}\",\"adult\":false}" >/dev/null 2>&1 || true
		http_code DELETE "${API_URL}/playtime/children/${account}" /dev/null >/dev/null 2>&1 || true
	done
	for gid in ${G_LEHR} ${G_KLASSE}; do
		http_code POST "${API_URL}/admin/verwalter-groups/remove" /dev/null "{\"gid\":\"${gid}\"}" >/dev/null 2>&1 || true
	done
	for account in ${ACCOUNTS}; do
		occ user:delete "${account}" >/dev/null 2>&1 || true
	done
	for gid in ${G_LEHR} ${G_KLASSE}; do
		occ group:delete "${gid}" >/dev/null 2>&1 || true
	done
	docker rm -f "${ORPHAN_CONTAINER}" >/dev/null 2>&1 || true
	docker volume rm "${ORPHAN_VOLUME}" >/dev/null 2>&1 || true
}

cleanup() {
	status=$?
	[ -n "${KID_JOB}" ] && kill "${KID_JOB}" 2>/dev/null || true
	[ -n "${ERW_JOB}" ] && kill "${ERW_JOB}" 2>/dev/null || true
	[ "${PROXY_STOPPED}" = 1 ] && proxy_start || true
	if [ "${APP_DISABLED}" = 1 ]; then
		occ app_api:app:enable gameworld >/dev/null 2>&1 || true
		wait_code "${ADMIN_AUTH}" "${API_URL}/me" 200 120 || true
	fi
	for world_id in ${WORLD_IDS}; do
		http_code DELETE "${API_URL}/playtime/worlds/${world_id}/window" /dev/null >/dev/null 2>&1 || true
		delete_world_hard "${world_id}"
	done
	reset_fixtures
	rm -rf "${WORK_DIR}"
	exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# Voraussetzungen ---------------------------------------------------------
for tool in docker curl jq grep sed awk sort uv; do
	command -v "${tool}" >/dev/null 2>&1 || abort "Werkzeug ${tool} fehlt"
done
printf 'Modus %s: Nextcloud %s\n' "${DEPLOY}" "${NEXTCLOUD_URL}"
if ! curl -sf "${NEXTCLOUD_URL}/status.php" >/dev/null 2>&1; then
	if [ "${DEPLOY}" = harp ]; then
		abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst: sh scripts/dev/harp-install.sh"
	fi
	abort "Nextcloud antwortet nicht unter ${NEXTCLOUD_URL}. Zuerst:
  docker compose -f scripts/dev/compose.yaml up -d
  sh scripts/dev/register-exapp.sh"
fi
docker inspect "${NC_CONTAINER}" >/dev/null 2>&1 || abort "Nextcloud-Container ${NC_CONTAINER} fehlt"
docker inspect "${PROXY_CONTAINER}" >/dev/null 2>&1 || abort "Docker-Proxy ${PROXY_CONTAINER} fehlt"
occ app_api:app:list 2>/dev/null | grep -q '^gameworld ' || abort "Gameworld ist nicht registriert"
wait_code "${ADMIN_AUTH}" "${API_URL}/me" 200 60 || abort "GET /api/me als admin antwortet nicht mit 200"
if [ "${DEPLOY}" = manual ]; then
	curl -sf "http://127.0.0.1:${BACKEND_PORT}/heartbeat" >/dev/null 2>&1 ||
		abort "ExApp antwortet nicht auf Port ${BACKEND_PORT}. Zuerst: sh scripts/dev/register-exapp.sh"
fi
SPREED_VERSION=$(occ app:list --output=json 2>/dev/null | jq -r '.enabled.spreed // empty' 2>/dev/null || true)
NC_VERSION=$(curl -s "${NEXTCLOUD_URL}/status.php" | jq -r '.versionstring // empty' 2>/dev/null || true)
printf 'Nextcloud %s, Talk %s\n' "${NC_VERSION:-unbekannt}" "${SPREED_VERSION:-nicht aktiviert}"

printf '\n== Vorbereitung ==\n'
reset_fixtures
http_code GET "${API_URL}/worlds" "${WORK_DIR}/pre.json" >/dev/null
for old_id in $(jq -r --argjson names "${ACCEPTANCE_WORLDS}" \
	'.worlds[]? | select(.name as $n | $names | index($n)) | .id' "${WORK_DIR}/pre.json" 2>/dev/null || true); do
	printf 'entferne Rest eines früheren Laufs: %s\n' "${old_id}"
	delete_world_hard "${old_id}"
done
BASELINE_CONTAINERS=$(docker ps -aq --filter "label=gameworld.managed=true" 2>/dev/null | tr '\n' ' ')
printf 'Grundlinie: %s fremde oder laufende Welt-Container vor dem Lauf\n' "$(printf '%s' "${BASELINE_CONTAINERS}" | wc -w | tr -d ' ')"
occ group:add "${G_LEHR}" >/dev/null 2>&1 || abort "Gruppe ${G_LEHR} ließ sich nicht anlegen"
occ group:add "${G_KLASSE}" >/dev/null 2>&1 || abort "Gruppe ${G_KLASSE} ließ sich nicht anlegen"
add_user "${LEHRER}" "${LEHRER_AUTH#*:}" "Lehrkraft Abnahme" || abort "Konto ${LEHRER} ließ sich nicht anlegen"
add_user "${KIND}" "${KIND_AUTH#*:}" "Kind Klasse" || abort "Konto ${KIND} ließ sich nicht anlegen"
add_user "${OUT}" "${OUT_AUTH#*:}" "Kind Draußen" || abort "Konto ${OUT} ließ sich nicht anlegen"
add_user "${ERW}" "${ERW_AUTH#*:}" "Erwachsen Abnahme" || abort "Konto ${ERW} ließ sich nicht anlegen"
add_user "${ALT}" "${ALT_AUTH#*:}" "Alt Verwalter" || abort "Konto ${ALT} ließ sich nicht anlegen"
for pair in "${G_LEHR} ${LEHRER}" "${G_KLASSE} ${LEHRER}" "${G_KLASSE} ${KIND}" "${G_KLASSE} ${ERW}" "${G_LEHR} ${ALT}"; do
	set -- ${pair}
	occ group:adduser "$1" "$2" >/dev/null 2>&1 || abort "$2 ließ sich nicht in $1 aufnehmen"
done
occ group:list --output=json >"${WORK_DIR}/groups.json" 2>/dev/null || true
check "Fixtures: ${G_LEHR} = ${ALT} ${LEHRER}, ${G_KLASSE} = ${ERW} ${KIND} ${LEHRER}, ${OUT} ohne Gruppe" \
	eq "$(jq -r --arg l "${G_LEHR}" --arg k "${G_KLASSE}" --arg o "${OUT}" \
		'((.[$l] // []) | sort | join(" ")) + "|" + ((.[$k] // []) | sort | join(" ")) + "|" +
		([to_entries[] | select(.value | index($o))] | length | tostring)' "${WORK_DIR}/groups.json" 2>/dev/null)" \
	"${ALT} ${LEHRER}|${ERW} ${KIND} ${LEHRER}|0"
CODE=$(http_code GET "${API_URL}/admin/verwalter-groups" "${WORK_DIR}/vg0.json")
check "Vorbereitung: ${G_LEHR} ist keine Verwalter-Gruppe (HTTP ${CODE})" \
	eq "$(jq -r --arg g "${G_LEHR}" '(.groups // []) | index($g) == null' "${WORK_DIR}/vg0.json" 2>/dev/null)" true

printf '\n== K1 Installation ==\n'
if [ "${DEPLOY}" = harp ]; then
	occ app_api:app:list >"${WORK_DIR}/applist.txt" 2>/dev/null || true
	check "K1 app_api:app:list: gameworld (Gameworld) aktiviert ($(grep '^gameworld ' "${WORK_DIR}/applist.txt" | tr -d '\r'))" \
		grep -Eq '^gameworld \(Gameworld\): [0-9.]+ \[enabled\]' "${WORK_DIR}/applist.txt"
	occ app_api:daemon:list >"${WORK_DIR}/daemons.txt" 2>/dev/null || true
	check "K1 Daemon ${HARP_DAEMON} ist ein HaRP-Daemon (docker-install, Is HaRP yes)" \
		awk -F'|' -v d="${HARP_DAEMON}" '{ for (i = 1; i <= NF; i++) gsub(/^ +| +$/, "", $i) }
			$3 == d && $5 == "docker-install" && $9 == "yes" { found = 1 } END { exit !found }' "${WORK_DIR}/daemons.txt"
	EXAPP_IMAGE=$(docker inspect --format '{{.Config.Image}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r' || true)
	check "K1 ExApp-Container ${EXAPP_CONTAINER} aus der lokalen Registry (ist ${EXAPP_IMAGE:-leer})" \
		matches "${EXAPP_IMAGE}" "^${LOCAL_IMAGE_PREFIX}"
	check "K1 ExApp-Container läuft als 10001:10001" \
		eq "$(docker inspect --format '{{.Config.User}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r')" 10001:10001
	check "K1 Healthcheck des ExApp-Containers (Heartbeat im Image) healthy" \
		eq "$(docker inspect --format '{{.State.Health.Status}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r')" healthy
	EXAPP_NETS=$(docker inspect --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r')
	EXAPP_MOUNTS=$(docker inspect --format '{{range .Mounts}}{{.Destination}} {{end}}' "${EXAPP_CONTAINER}" 2>/dev/null | tr -d '\r')
	check "K1 ExApp-Container im Netz der Test-Instanz (${EXAPP_NETS}), ohne Docker-Socket (${EXAPP_MOUNTS})" \
		sh -c 'contains() { case "$1" in *"$2"*) return 0 ;; esac; return 1; }
		contains "$1" gameworld-dev-harp_default && ! contains "$2" docker.sock' _ "${EXAPP_NETS}" "${EXAPP_MOUNTS}"
	CODE=$(curl -s -o /dev/null -w '%{http_code}' "${NEXTCLOUD_URL}/exapps/gameworld/api/me" 2>/dev/null || printf '000')
	check "K1 Negativkontrolle: /exapps/gameworld/api/me über HaRP ohne Anmeldung abgewiesen (ist ${CODE})" \
		matches "${CODE}" '^(401|403)$'
	CODE=$(call "${ADMIN_AUTH}" GET "${NEXTCLOUD_URL}/exapps/gameworld/api/me" "${WORK_DIR}/harp-me.json")
	check "K1 /exapps/gameworld/api/me über HaRP als admin HTTP 200 und Rolle verwalter (ist ${CODE})" \
		sh -c '[ "$1" = 200 ] && [ "$(jq -r .role "$2")" = verwalter ]' _ "${CODE}" "${WORK_DIR}/harp-me.json"
else
	printf 'Hinweis: Modus manual, Registry-Installation belegt GAMEWORLD_DEPLOY=harp (Store-Weg vollständig in 06-15)\n'
	check "K1 app_api:app:list: gameworld aktiviert" sh -c 'docker exec -u www-data "$1" php occ app_api:app:list | grep "^gameworld " | grep -q enabled' _ "${NC_CONTAINER}"
fi
CODE=$(http_code GET "${API_URL}/me" "${WORK_DIR}/me-admin.json")
check "K1 GET /api/me über den AppAPI-Proxy als admin: verwalter, nc_admin true (HTTP ${CODE})" \
	eq "$(jq -r '.role == "verwalter" and .nc_admin == true' "${WORK_DIR}/me-admin.json" 2>/dev/null)" true
create_world "${ADMIN_AUTH}" "${W1_NAME}"
W1=${NEW_ID}
check "K1 POST '${W1_NAME}' HTTP 201 (ist ${NEW_CODE})" eq "${NEW_CODE}" 201
matches "${W1}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
check "K1 Welt running binnen 120 s" wait_status "${W1}" running 120
C1=$(container_of "${W1}")
[ -n "${C1}" ] || abort "kein Container mit Label gameworld.world_id=${W1}"
OWN_INSTANCE=$(docker inspect --format '{{index .Config.Labels "gameworld.instance"}}' "${C1}" 2>/dev/null | tr -d '\r')
printf 'eigene Instanz: %s\n' "${OWN_INSTANCE}"
matches "${OWN_INSTANCE}" '^[0-9a-f]{8}$' || abort "Container ohne Label gameworld.instance"
PORT=$(port_of "${C1}")
matches "${PORT}" '^[0-9]+$' || abort "kein UDP-Port"
CODE=$(http_code POST "${API_URL}/worlds/${W1}/invites" /dev/null "{\"kind\":\"user\",\"target\":\"${KIND}\"}")
check "K1 POST invites ${KIND} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
http_code GET "${API_URL}/worlds/${W1}/players" "${WORK_DIR}/p1.json" >/dev/null
KIND_NAME=$(player_field "${WORK_DIR}/p1.json" "${KIND}" player_name)
KIND_PW=$(player_field "${WORK_DIR}/p1.json" "${KIND}" password)
check "K1 ${KIND}: Spielname ${KIND_NAME:-leer}, Passwort vorhanden (Länge ${#KIND_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ]' _ "${KIND_NAME}" "${KIND_PW}"
probe "${WORK_DIR}/k1-fremd.json" Fremder6
check "K1 Negativkontrolle: 'Fremder6' abgewiesen mit '${TEXT_DENY}' ($(probe_summary "${WORK_DIR}/k1-fremd.json"))" \
	denied_with "${WORK_DIR}/k1-fremd.json" "${TEXT_DENY}"
check "K1 ${KIND} tritt bei (auth_accept)" \
	probe_expect "${WORK_DIR}/k1-kid.json" '.result == "auth_accept"' 30 "${KIND_NAME}" "${KIND_PW}"

printf '\n== K2 Setup-Check ==\n'
CODE=$(http_code GET "${API_URL}/setup-check" "${WORK_DIR}/sc0.json")
check "K2 Positivkontrolle vorher: Setup-Check ok (HTTP ${CODE})" eq "$(jq -r '.ok' "${WORK_DIR}/sc0.json" 2>/dev/null)" true
docker stop "${PROXY_CONTAINER}" >/dev/null 2>&1 && PROXY_STOPPED=1
check "K2 Docker-Proxy ${PROXY_CONTAINER} gestoppt" \
	eq "$(docker inspect --format '{{.State.Running}}' "${PROXY_CONTAINER}" 2>/dev/null | tr -d '\r')" false
CODE=$(http_code GET "${API_URL}/setup-check" "${WORK_DIR}/sc1.json")
printf 'Setup-Check ohne Proxy: %s\n' "$(jq -c '[.items[]? | select(.ok == false) | .id]' "${WORK_DIR}/sc1.json" 2>/dev/null)"
check "K2 Negativkontrolle: HTTP 200 mit ok false (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .ok "$2")" = false ]' _ "${CODE}" "${WORK_DIR}/sc1.json"
check "K2 Befund proxy_refused, proxy_dns oder proxy_timeout als Fehler" \
	eq "$(jq -r '[.items[]? | select(.ok == false and .severity == "error" and
		(.id == "proxy_refused" or .id == "proxy_dns" or .id == "proxy_timeout"))] | length > 0' "${WORK_DIR}/sc1.json" 2>/dev/null)" true
check "K2 Befund verweist auf den Doku-Anker ${DOC_ANCHOR}" \
	eq "$(jq -r --arg a "${DOC_ANCHOR}" '[.items[]? | select(.ok == false) | .message | contains($a)] | any' "${WORK_DIR}/sc1.json" 2>/dev/null)" true
proxy_start || fail "K2 Docker-Proxy ließ sich nicht wieder starten"
check "K2 Docker-Proxy läuft wieder" \
	eq "$(docker inspect --format '{{.State.Running}}' "${PROXY_CONTAINER}" 2>/dev/null | tr -d '\r')" true
sc_ok() {
	http_code GET "${API_URL}/setup-check" "${WORK_DIR}/sc2.json" >/dev/null
	[ "$(jq -r '.ok and ([.items[]? | select(.ok == false and .severity == "error")] | length == 0)' \
		"${WORK_DIR}/sc2.json" 2>/dev/null)" = true ]
}
wait_sc_ok() {
	until_ts=$(deadline 60)
	while :; do
		sc_ok && return 0
		before "${until_ts}" || return 1
		sleep 3
	done
}
check "K2 Positivkontrolle: Setup-Check wieder ohne Fehler (binnen 60 s)" wait_sc_ok
check "K2 Welt nach dem Proxy-Ausfall weiter running" wait_status "${W1}" running 30

printf '\n== K3 Lebenszyklus und Reste ==\n'
VOLUME1=$(docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}' "${C1}" 2>/dev/null | awk '{print $1}' | tr -d '\r')
printf 'Volume der Welt: %s\n' "${VOLUME1:-leer}"
if [ "${DEPLOY}" = harp ]; then
	occ app_api:app:disable gameworld >"${WORK_DIR}/disable.log" 2>&1 && APP_DISABLED=1
	check "K3 occ app_api:app:disable gameworld ($(tr -d '\r' <"${WORK_DIR}/disable.log" | tr '\n' ' '))" eq "${APP_DISABLED}" 1
	own_gone() {
		until_ts=$(deadline 60)
		while :; do
			[ -z "$(docker ps -aq --filter "label=gameworld.instance=${OWN_INSTANCE}")" ] && return 0
			before "${until_ts}" || return 1
			sleep 2
		done
	}
	check "K3 binnen 60 s kein Container mit gameworld.instance=${OWN_INSTANCE} mehr" own_gone
	check "K3 Volume ${VOLUME1:-leer} ist noch da (Spielstand bleibt)" sh -c '[ -n "$1" ] && docker volume inspect "$1" >/dev/null 2>&1' _ "${VOLUME1}"
	check "K3 Gegenprobe: fremde Container der Grundlinie unberührt" sh -c '
		for cid in $1; do docker inspect "$cid" >/dev/null 2>&1 || exit 1; done' _ "${BASELINE_CONTAINERS}"
	occ app_api:app:enable gameworld >"${WORK_DIR}/enable.log" 2>&1 && APP_DISABLED=0
	check "K3 occ app_api:app:enable gameworld" eq "${APP_DISABLED}" 0
	check "K3 ExApp antwortet wieder (GET /api/me 200 binnen 180 s)" wait_code "${ADMIN_AUTH}" "${API_URL}/me" 200 180
	check "K3 Soll-laufende Welt wieder running (binnen 180 s)" wait_status "${W1}" running 180
	C1=$(container_of "${W1}")
	check "K3 neuer Container aus dem alten Volume" sh -c '[ -n "$1" ] && docker inspect --format "{{range .Mounts}}{{.Name}} {{end}}" "$1" | grep -q "$2"' \
		_ "${C1}" "${VOLUME1}"
	PORT=$(port_of "${C1}")
	check "K3 ${KIND} tritt nach dem Aktivieren wieder bei (auth_accept)" \
		probe_expect "${WORK_DIR}/k3-kid.json" '.result == "auth_accept"' 60 "${KIND_NAME}" "${KIND_PW}"
else
	printf 'Hinweis: Modus manual, Deaktivieren/Aktivieren nur im Modus harp (eigene Test-Instanz);\n'
	printf 'der Dev-Instanz gehören laufende Welten der Dev-Umgebung, D-17 räumte sie ab.\n'
fi
docker volume create "${ORPHAN_VOLUME}" >/dev/null 2>&1 || fail "K3 Orphan-Volume ließ sich nicht anlegen"
docker create --name "${ORPHAN_CONTAINER}" --label gameworld.managed=true \
	--label "gameworld.instance=${ORPHAN_INSTANCE}" "${LUANTI_IMAGE}" >/dev/null 2>&1 || fail "K3 Orphan-Container ließ sich nicht anlegen"
ORPHAN_ID=$(docker ps -aq --no-trunc --filter "name=^${ORPHAN_CONTAINER}\$" | tr -d '\r')
check "K3 Orphan-Container und -Volume per docker CLI angelegt" \
	sh -c '[ -n "$1" ] && docker volume inspect "$2" >/dev/null 2>&1' _ "${ORPHAN_ID}" "${ORPHAN_VOLUME}"
CODE=$(http_code GET "${API_URL}/admin/orphans" "${WORK_DIR}/orph1.json")
check "K3 GET /api/admin/orphans als admin HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 Liste nennt den Orphan-Container (instance ${ORPHAN_INSTANCE})" \
	eq "$(jq -r --arg i "${ORPHAN_INSTANCE}" '[.containers[]? | select(.instance == $i)] | length' "${WORK_DIR}/orph1.json" 2>/dev/null)" 1
check "K3 Liste nennt das Orphan-Volume ${ORPHAN_VOLUME}" \
	eq "$(jq -r --arg v "${ORPHAN_VOLUME}" '[.volumes[]? | select(.name == $v)] | length' "${WORK_DIR}/orph1.json" 2>/dev/null)" 1
check "K3 Negativkontrolle: eigene Welt ${W1} steht nicht in der Liste" \
	eq "$(jq -r --arg v "${VOLUME1}" --arg i "${OWN_INSTANCE}" \
		'([.volumes[]? | select(.name == $v)] | length) + ([.containers[]? | select(.instance == $i)] | length)' \
		"${WORK_DIR}/orph1.json" 2>/dev/null)" 0
CODE=$(call "${LEHRER_AUTH}" GET "${API_URL}/admin/orphans" "${WORK_DIR}/orph-l.json")
check "K3 Negativkontrolle: GET /api/admin/orphans als ${LEHRER} HTTP 403 (ist ${CODE})" eq "${CODE}" 403
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/admin/orphans/container/remove" "${WORK_DIR}/orph-lr.json" "{\"id\":\"${ORPHAN_ID}\"}")
check "K3 Negativkontrolle: Entfernen als ${LEHRER} HTTP 403, Container bleibt (ist ${CODE})" \
	sh -c '[ "$1" = 403 ] && docker inspect "$2" >/dev/null 2>&1' _ "${CODE}" "${ORPHAN_ID}"
SNAP_BEFORE_SCRIPT=$(docker_snapshot)
CODE=$(http_code POST "${API_URL}/admin/orphans/container/remove" "${WORK_DIR}/orph-c.json" "{\"id\":\"${ORPHAN_ID}\"}")
check "K3 Orphan-Container per API entfernt HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(http_code POST "${API_URL}/admin/orphans/volume/remove" "${WORK_DIR}/orph-v.json" "{\"name\":\"${ORPHAN_VOLUME}\"}")
check "K3 Orphan-Volume per API entfernt HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K3 docker CLI findet den Orphan-Container nicht mehr" \
	eq "$(docker ps -aq --filter "label=gameworld.instance=${ORPHAN_INSTANCE}" | tr -d '\r')" ""
check "K3 docker CLI findet das Orphan-Volume nicht mehr" not docker volume inspect "${ORPHAN_VOLUME}"
CODE=$(http_code POST "${API_URL}/admin/orphans/volume/remove" "${WORK_DIR}/orph-own.json" "{\"name\":\"${VOLUME1}\"}")
check "K3 Negativkontrolle: eigenes Volume ${VOLUME1} per API abgelehnt HTTP 409, bleibt (ist ${CODE})" \
	sh -c '[ "$1" = 409 ] && docker volume inspect "$2" >/dev/null 2>&1' _ "${CODE}" "${VOLUME1}"
SNAP_BEFORE_SCRIPT=$(docker_snapshot)
sh "${ORPHANS_SCRIPT}" </dev/null >"${WORK_DIR}/orphans-script.txt" 2>&1 || true
SNAP_AFTER_SCRIPT=$(docker_snapshot)
printf 'gameworld-orphans.sh: %s\n' "$(head -n 1 "${WORK_DIR}/orphans-script.txt" | tr -d '\r')"
check "K3 gameworld-orphans.sh ohne Optionen ändert nichts (docker ps -a und volume ls gleich)" \
	eq "${SNAP_AFTER_SCRIPT}" "${SNAP_BEFORE_SCRIPT}"
check "K3 gameworld-orphans.sh nennt den entfernten Orphan nicht mehr" \
	not grep -q "${ORPHAN_INSTANCE}" "${WORK_DIR}/orphans-script.txt"
if [ -z "$(docker ps -aq --filter label=gameworld.managed=true)" ] && [ -z "$(docker volume ls -q --filter name=gameworld- | grep -E '^gameworld-[a-z0-9-]+$' || true)" ]; then
	check "K3 gameworld-orphans.sh: 'No Gameworld leftovers found.'" grep -qx 'No Gameworld leftovers found.' "${WORK_DIR}/orphans-script.txt"
else
	# Grundlinie: laufende Welten dieser und anderer Instanzen listet das Skript ehrlich mit.
	check "K3 gameworld-orphans.sh listet die vorhandenen Welt-Container (Positivkontrolle ${C1})" \
		grep -q "$(docker inspect --format '{{.Name}}' "${C1}" | tr -d '/\r')" "${WORK_DIR}/orphans-script.txt"
	check "K3 gameworld-orphans.sh: 'Nothing was changed.'" grep -q 'Nothing was changed.' "${WORK_DIR}/orphans-script.txt"
fi

printf '\n== K4 Listing und Doku ==\n'
check "K4 info.xml: genau ein <name>, ohne lang" sh -c '[ "$(grep -c "<name>Gameworld</name>" "$1")" = 1 ] && ! grep -q "<name lang=" "$1"' _ "${INFO_XML}"
check "K4 info.xml: description de mit 'Was diese App darf und warum'" \
	sh -c 'awk "/<description lang=\"de\">/,/<\/description>/" "$1" | grep -q "### Was diese App darf und warum"' _ "${INFO_XML}"
check "K4 info.xml: description fr mit 'Ce que cette application peut faire et pourquoi'" \
	sh -c 'awk "/<description lang=\"fr\">/,/<\/description>/" "$1" | grep -q "### Ce que cette application peut faire et pourquoi"' _ "${INFO_XML}"
check "K4 Negativkontrolle: dasselbe grep findet eine erfundene Überschrift nicht" \
	not sh -c 'awk "/<description lang=\"de\">/,/<\/description>/" "$1" | grep -q "### Was diese App heimlich tut"' _ "${INFO_XML}"
check "K4 docs/privacy.md und docs/privacy.de.md vorhanden und nicht leer" \
	sh -c '[ -s "$1/docs/privacy.md" ] && [ -s "$1/docs/privacy.de.md" ]' _ "${REPO_ROOT}"
check "K4 Listing verlinkt privacy.de.md und den Setup-Check-Anker der Anleitung" \
	sh -c 'grep -q "docs/privacy.de.md" "$1" && grep -q "id=\"setup-check\"" "$2/docs/install.md"' _ "${INFO_XML}" "${REPO_ROOT}"

printf '\n== K5 Verwalter-Gruppen ==\n'
CODE=$(call "${LEHRER_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/l-w0.json")
check "K5 Negativkontrolle: ${LEHRER} vor der Freischaltung GET /api/worlds HTTP 403 (ist ${CODE})" eq "${CODE}" 403
CODE=$(http_code POST "${API_URL}/admin/verwalter-groups/add" "${WORK_DIR}/vg1.json" "{\"gid\":\"${G_LEHR}\"}")
[ "${CODE}" = 200 ] && VG_ADDED=1
check "K5 admin schaltet ${G_LEHR} frei HTTP 200 (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r --arg g "$3" "(.groups // []) | index(\$g) != null" "$2")" = true ]' _ "${CODE}" "${WORK_DIR}/vg1.json" "${G_LEHR}"
check "K5 Positivkontrolle: ${LEHRER} danach GET /api/worlds HTTP 200 (binnen 40 s)" \
	wait_code "${LEHRER_AUTH}" "${API_URL}/worlds" 200 40
CODE=$(call "${LEHRER_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/me-l.json")
check "K5 /api/me ${LEHRER}: verwalter, nc_admin false, invite_groups ${G_KLASSE} ${G_LEHR} (HTTP ${CODE})" \
	eq "$(jq -r --arg k "${G_KLASSE}" --arg l "${G_LEHR}" \
		'.role == "verwalter" and .nc_admin == false and (.invite_groups == [$k, $l])' "${WORK_DIR}/me-l.json" 2>/dev/null)" true
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/admin/verwalter-groups/add" "${WORK_DIR}/vg-l.json" "{\"gid\":\"${G_KLASSE}\"}")
check "K5 Negativkontrolle: ${LEHRER} POST verwalter-groups/add HTTP 403 (ist ${CODE})" eq "${CODE}" 403
http_code GET "${API_URL}/admin/verwalter-groups" "${WORK_DIR}/vg2.json" >/dev/null
check "K5 ${G_KLASSE} ist danach keine Verwalter-Gruppe" \
	eq "$(jq -r --arg g "${G_KLASSE}" '(.groups // []) | index($g) == null' "${WORK_DIR}/vg2.json" 2>/dev/null)" true
create_world "${LEHRER_AUTH}" "${W2_NAME}"
W2=${NEW_ID}
check "K5 ${LEHRER} legt '${W2_NAME}' an HTTP 201 (ist ${NEW_CODE})" eq "${NEW_CODE}" 201
matches "${W2}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/worlds/${W2}/invites" "${WORK_DIR}/inv-k.json" "{\"kind\":\"user\",\"target\":\"${KIND}\"}")
check "K5 ${LEHRER} lädt ${KIND} ein HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/worlds/${W2}/invites" "${WORK_DIR}/inv-o.json" "{\"kind\":\"user\",\"target\":\"${OUT}\"}")
check "K5 Negativkontrolle: ${LEHRER} lädt ${OUT} ein HTTP 403 (ist ${CODE}, $(detail_of "${WORK_DIR}/inv-o.json"))" \
	sh -c '[ "$1" = 403 ] && [ "$(jq -r .detail "$2")" = "$3" ]' _ "${CODE}" "${WORK_DIR}/inv-o.json" "${TEXT_OUT_OF_SCOPE}"
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/worlds/${W2}/invites" "${WORK_DIR}/inv-g.json" "{\"kind\":\"group\",\"target\":\"${G_KLASSE}\"}")
check "K5 ${LEHRER} lädt die Gruppe ${G_KLASSE} ein HTTP 200 (ist ${CODE})" eq "${CODE}" 200
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/worlds/${W2}/invites" "${WORK_DIR}/inv-a.json" '{"kind":"group","target":"admin"}')
check "K5 Negativkontrolle: ${LEHRER} lädt die Gruppe admin ein HTTP 403 (ist ${CODE}, $(detail_of "${WORK_DIR}/inv-a.json"))" \
	sh -c '[ "$1" = 403 ] && [ "$(jq -r .detail "$2")" = "$3" ]' _ "${CODE}" "${WORK_DIR}/inv-a.json" "${TEXT_GROUP_OUT_OF_SCOPE}"
CODE=$(http_code POST "${API_URL}/worlds/${W2}/invites" /dev/null "{\"kind\":\"user\",\"target\":\"${OUT}\"}")
check "K5 admin lädt ${OUT} direkt ein (außerhalb der Gruppen von ${LEHRER}) HTTP 200 (ist ${CODE})" eq "${CODE}" 200
access_count() {
	http_code GET "${API_URL}/worlds/${W2}/players" "${WORK_DIR}/acc.json" >/dev/null
	jq -r '[.players[]?.nc_user] | sort | join(" ")' "${WORK_DIR}/acc.json" 2>/dev/null || true
}
ACCESS_BEFORE=$(access_count)
printf 'Zugänge vorher: %s\n' "${ACCESS_BEFORE}"
check "K5 Zugänge vorher enthalten ${OUT}, ${KIND} und ${ERW}" sh -c \
	'for u in $2 $3 $4; do case " $1 " in *" $u "*) ;; *) exit 1 ;; esac; done' _ "${ACCESS_BEFORE}" "${OUT}" "${KIND}" "${ERW}"
CODE1=$(call "${LEHRER_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/dash1.json")
call "${LEHRER_AUTH}" GET "${API_URL}/worlds/${W2}/players" "${WORK_DIR}/dash1p.json" >/dev/null
printf 'warte %s s (Abgleich-Intervall) bis zum zweiten Besuch von %s\n' "${SYNC_WAIT}" "${LEHRER}"
sleep "${SYNC_WAIT}"
CODE2=$(call "${LEHRER_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/dash2.json")
call "${LEHRER_AUTH}" GET "${API_URL}/worlds/${W2}/players" "${WORK_DIR}/dash2p.json" >/dev/null
sleep 3
ACCESS_AFTER=$(access_count)
check "K5 zwei Besuche von ${LEHRER} gelungen (HTTP ${CODE1} und ${CODE2})" sh -c '[ "$1" = 200 ] && [ "$2" = 200 ]' _ "${CODE1}" "${CODE2}"
check "K5 404-Falle: Zugänge vorher gleich nachher (${ACCESS_AFTER})" sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ "${ACCESS_BEFORE}" "${ACCESS_AFTER}"
CODE=$(http_code POST "${API_URL}/worlds/${W2}/invites/remove" /dev/null "{\"kind\":\"user\",\"target\":\"${OUT}\"}")
ACCESS_REVOKED=$(access_count)
check "K5 Positivkontrolle: dasselbe Zählen erkennt ein echtes Entfernen von ${OUT} (HTTP ${CODE}: ${ACCESS_REVOKED})" \
	sh -c '[ "$1" = 200 ] && [ -n "$2" ] && case " $2 " in *" $3 "*) exit 1 ;; *) exit 0 ;; esac' _ "${CODE}" "${ACCESS_REVOKED}" "${OUT}"
KID_FAILS=""
for spec in "GET ${API_URL}/worlds" "POST ${API_URL}/worlds" "GET ${API_URL}/worlds/${W2}/players" \
	"POST ${API_URL}/worlds/${W2}/invites" "POST ${API_URL}/worlds/${W2}/stop" "GET ${API_URL}/playtime" \
	"GET ${API_URL}/pause" "POST ${API_URL}/pause" "GET ${API_URL}/setup-check" "GET ${API_URL}/talk" \
	"GET ${API_URL}/settings" "GET ${API_URL}/attempts" "GET ${API_URL}/worlds/${W2}/backups" \
	"POST ${API_URL}/players/password" "GET ${API_URL}/admin/verwalter-groups" "GET ${API_URL}/admin/orphans"; do
	set -- ${spec}
	if [ "$1" = POST ]; then
		code=$(call "${KIND_AUTH}" POST "$2" /dev/null '{}')
	else
		code=$(call "${KIND_AUTH}" GET "$2" /dev/null)
	fi
	[ "${code}" = 403 ] || KID_FAILS="${KID_FAILS} $1 ${2#"${API_URL}"}=${code}"
done
check "K5 ${KIND} auf 16 Verwaltungsrouten je HTTP 403${KID_FAILS:+ (abweichend:${KID_FAILS})}" eq "${KID_FAILS}" ""
CODE=$(call "${KIND_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/me-k.json")
check "K5 Positivkontrolle: ${KIND} GET /api/me HTTP 200, Rolle ohne Verwaltung (ist ${CODE}, $(jq -r .role "${WORK_DIR}/me-k.json" 2>/dev/null))" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .role "$2")" != verwalter ]' _ "${CODE}" "${WORK_DIR}/me-k.json"
CODE=$(call "${KIND_AUTH}" GET "${API_URL}/my/worlds" "${WORK_DIR}/my-k.json")
check "K5 Positivkontrolle: ${KIND} sieht '${W2_NAME}' unter /api/my/worlds (HTTP ${CODE})" \
	eq "$(jq -r --arg id "${W2}" '[.worlds[]? | select(.id == $id)] | length' "${WORK_DIR}/my-k.json" 2>/dev/null)" 1

printf '\n== K6 Erwachsen, Pause, Zeitfenster ==\n'
check "K6 '${W2_NAME}' running binnen 120 s" wait_status "${W2}" running 120
C2=$(container_of "${W2}")
[ -n "${C2}" ] || abort "kein Container für ${W2}"
PORT=$(port_of "${C2}")
matches "${PORT}" '^[0-9]+$' || abort "kein UDP-Port für ${W2}"
http_code GET "${API_URL}/worlds/${W2}/players" "${WORK_DIR}/p2.json" >/dev/null
K2_NAME=$(player_field "${WORK_DIR}/p2.json" "${KIND}" player_name)
K2_PW=$(player_field "${WORK_DIR}/p2.json" "${KIND}" password)
ERW_NAME=$(player_field "${WORK_DIR}/p2.json" "${ERW}" player_name)
ERW_PW=$(player_field "${WORK_DIR}/p2.json" "${ERW}" password)
check "K6 Spielnamen ${K2_NAME:-leer} und ${ERW_NAME:-leer}, Passwörter vorhanden (Längen ${#K2_PW} und ${#ERW_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ] && [ -n "$3" ] && [ -n "$4" ]' _ "${K2_NAME}" "${K2_PW}" "${ERW_NAME}" "${ERW_PW}"
read_conf() {
	rm -f "${WORK_DIR}/conf.tar"
	MSYS_NO_PATHCONV=1 docker cp "${C2}:${CONF_PATH}" - >"${WORK_DIR}/conf.tar" 2>/dev/null || return 1
	tar -xOf "${WORK_DIR}/conf.tar" >"$1" 2>/dev/null
	[ -s "$1" ]
}
check "K6 minetest.conf vorher per docker cp gelesen" read_conf "${WORK_DIR}/conf-before.txt"
CODE=$(http_code POST "${API_URL}/playtime/children/${ERW}" /dev/null "{\"normal\":$(week "")}")
check "K6 Regel 'kein Spieltag' für ${ERW} HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K6 Negativkontrolle: ${ERW} abgewiesen mit '${TEXT_TAG}'" \
	probe_expect "${WORK_DIR}/k6-erw0.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_TAG}\"))" 20 \
	"${ERW_NAME}" "${ERW_PW}"
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/players/adult" "${WORK_DIR}/adult1.json" "{\"nc_user\":\"${ERW}\",\"adult\":true}")
check "K6 ${LEHRER} setzt ${ERW} adult true HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K6 Positivkontrolle: ${ERW} tritt trotz Regel bei (auth_accept binnen 20 s)" \
	probe_expect "${WORK_DIR}/k6-erw1.json" '.result == "auth_accept"' 20 "${ERW_NAME}" "${ERW_PW}"
CODE=$(call "${KIND_AUTH}" POST "${API_URL}/players/adult" "${WORK_DIR}/adult-k.json" "{\"nc_user\":\"${KIND}\",\"adult\":true}")
check "K6 Negativkontrolle: ${KIND} setzt adult für sich HTTP 403 (ist ${CODE})" eq "${CODE}" 403
http_code GET "${API_URL}/playtime" "${WORK_DIR}/pt1.json" >/dev/null
check "K6 Flags danach: ${KIND} adult false, ${ERW} adult true" \
	eq "$(jq -r --arg k "${KIND}" --arg e "${ERW}" \
		'([.children[]? | select(.nc_user == $k) | .adult] | any | not) and ([.children[]? | select(.nc_user == $e) | .adult] | any)' \
		"${WORK_DIR}/pt1.json" 2>/dev/null)" true
sleep 2.5
printf 'Sitzung %s für bis zu 60 s\n' "${ERW}"
probe "${WORK_DIR}/k6-erw-hold.json" "${ERW_NAME}" "${ERW_PW}" --hold 60 --timeout "${SESSION_TIMEOUT}" &
ERW_JOB=$!
check "K6 ${ERW} ist laut Weltenliste online (binnen 30 s)" wait_online "${W2}" "${ERW_NAME}" 30
CODE=$(http_code POST "${API_URL}/players/adult" /dev/null "{\"nc_user\":\"${ERW}\",\"adult\":false}")
check "K6 adult false HTTP 200 (ist ${CODE})" eq "${CODE}" 200
wait "${ERW_JOB}" || true
ERW_JOB=""
printf '%s: %s\n' "${ERW}" "$(probe_summary "${WORK_DIR}/k6-erw-hold.json")"
check "K6 gehaltene Sitzung von ${ERW} getrennt mit '${TEXT_TAG}'" kicked_with "${WORK_DIR}/k6-erw-hold.json" "${TEXT_TAG}"
check "K6 minetest.conf nachher gelesen" read_conf "${WORK_DIR}/conf-after.txt"
check "K6 minetest.conf vorher gleich nachher (der Schalter wirkt nur auf die Zeitregeln)" \
	cmp -s "${WORK_DIR}/conf-before.txt" "${WORK_DIR}/conf-after.txt"
check "K6 minetest.conf ohne Adminrechte für Spieler (default_privs ohne server/privs)" \
	not grep -Eq '^default_privs *=.*(server|privs)' "${WORK_DIR}/conf-after.txt"
CODE=$(http_code POST "${API_URL}/players/adult" /dev/null "{\"nc_user\":\"${ERW}\",\"adult\":true}")
check "K6 ${ERW} wieder adult true HTTP 200 (ist ${CODE})" eq "${CODE}" 200
probe_expect "${WORK_DIR}/k6-kid-pre.json" '.result == "auth_accept"' 20 "${K2_NAME}" "${K2_PW}" || true
sleep 2.5
printf 'Sitzung %s für bis zu 90 s, dann Pause für alle\n' "${KIND}"
probe "${WORK_DIR}/k6-kid-hold.json" "${K2_NAME}" "${K2_PW}" --hold 90 --timeout "${SESSION_TIMEOUT}" &
KID_JOB=$!
check "K6 ${KIND} ist laut Weltenliste online (binnen 30 s)" wait_online "${W2}" "${K2_NAME}" 30
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/pause" "${WORK_DIR}/pause.json" '{"minutes":15}')
check "K6 ${LEHRER} startet 'Pause für alle' HTTP 200, aktiv (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .active "$2")" = true ]' _ "${CODE}" "${WORK_DIR}/pause.json"
wait "${KID_JOB}" || true
KID_JOB=""
printf '%s: %s\n' "${KIND}" "$(probe_summary "${WORK_DIR}/k6-kid-hold.json")"
check "K6 Negativkontrolle: ${KIND} getrennt mit '${TEXT_PAUSE}'" kicked_with "${WORK_DIR}/k6-kid-hold.json" "${TEXT_PAUSE}"
# Nach dem Trennen sperrt der Mod 2 s jeden Wiederbeitritt ("einen Moment warten"), erst danach greift die Pause.
sleep 3
probe_expect "${WORK_DIR}/k6-kid-pause.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_PAUSE}\"))" 15 \
	"${K2_NAME}" "${K2_PW}" || true
check "K6 Negativkontrolle: ${KIND} kommt während der Pause nicht hinein ($(probe_summary "${WORK_DIR}/k6-kid-pause.json"))" \
	denied_with "${WORK_DIR}/k6-kid-pause.json" "${TEXT_PAUSE}"
probe "${WORK_DIR}/k6-erw-pause.json" "${ERW_NAME}" "${ERW_PW}"
check "K6 Positivkontrolle: ${ERW} tritt während der Pause bei (auth_accept, $(probe_summary "${WORK_DIR}/k6-erw-pause.json"))" \
	accepted "${WORK_DIR}/k6-erw-pause.json"
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/pause/end" "${WORK_DIR}/pause-end.json")
check "K6 POST /api/pause/end HTTP 200, nicht mehr aktiv (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .active "$2")" = false ]' _ "${CODE}" "${WORK_DIR}/pause-end.json"
check "K6 ${KIND} nach dem Pausenende wieder hinein (auth_accept)" \
	probe_expect "${WORK_DIR}/k6-kid-post.json" '.result == "auth_accept"' 20 "${K2_NAME}" "${K2_PW}"
http_code GET "${API_URL}/playtime" "${WORK_DIR}/ptz.json" >/dev/null
ZONE=$(jq -r '.time_zone // "Europe/Berlin"' "${WORK_DIR}/ptz.json" 2>/dev/null || printf 'Europe/Berlin')
NOW_MIN=$(zone_now "${ZONE}")
matches "${NOW_MIN}" '^[0-9]+$' || abort "Uhrzeit der Zeitzone ${ZONE} nicht berechenbar (tzdata im venv? uv sync)"
if [ "${NOW_MIN}" -ge 600 ]; then
	WIN_START=0
else
	WIN_START=1200
fi
WIN_END=$((WIN_START + 60))
printf 'Zeitzone %s, jetzt Minute %s, Fenster täglich %s bis %s (jetzt zu)\n' "${ZONE}" "${NOW_MIN}" "${WIN_START}" "${WIN_END}"
WINDOW_BODY=$(jq -nc --argjson s "${WIN_START}" --argjson e "${WIN_END}" \
	'{days: [range(1; 8) as $d | {weekday: $d, open: true, window_start: $s, window_end: $e}]}')
CODE=$(call "${LEHRER_AUTH}" POST "${API_URL}/playtime/worlds/${W2}/window" "${WORK_DIR}/win.json" "${WINDOW_BODY}")
check "K6 geschlossenes Welt-Zeitfenster gesetzt HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K6 Positivkontrolle: GET /api/worlds zeigt das Zeitfenster von '${W2_NAME}'" \
	eq "$(world_field "${W2}" '(.time_window | type) == "array"')" true
check "K6 Negativkontrolle: ${KIND} abgewiesen mit '${TEXT_WELT}'" \
	probe_expect "${WORK_DIR}/k6-kid-win.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_WELT}\"))" 20 \
	"${K2_NAME}" "${K2_PW}"
probe "${WORK_DIR}/k6-erw-win.json" "${ERW_NAME}" "${ERW_PW}"
check "K6 Positivkontrolle: ${ERW} tritt bei geschlossener Welt bei (auth_accept, $(probe_summary "${WORK_DIR}/k6-erw-win.json"))" \
	accepted "${WORK_DIR}/k6-erw-win.json"
CODE=$(call "${LEHRER_AUTH}" DELETE "${API_URL}/playtime/worlds/${W2}/window" "${WORK_DIR}/win-del.json")
check "K6 DELETE Zeitfenster HTTP 200 oder 204 (ist ${CODE})" matches "${CODE}" '^20[04]$'
check "K6 ${KIND} ohne Fenster wieder hinein (auth_accept)" \
	probe_expect "${WORK_DIR}/k6-kid-free.json" '.result == "auth_accept"' 20 "${K2_NAME}" "${K2_PW}"
http_code GET "${API_URL}/pause" "${WORK_DIR}/pause-now.json" >/dev/null
check "K6 GET /api/pause: keine Pause aktiv" eq "$(jq -r '.active' "${WORK_DIR}/pause-now.json" 2>/dev/null)" false
check "K6 GET /api/worlds: '${W2_NAME}' ohne Zeitfenster" \
	eq "$(world_field "${W2}" '.time_window == null')" true
http_code DELETE "${API_URL}/playtime/children/${ERW}" /dev/null >/dev/null || true
http_code POST "${API_URL}/players/adult" /dev/null "{\"nc_user\":\"${ERW}\",\"adult\":false}" >/dev/null || true
CODE=$(http_code DELETE "${API_URL}/worlds/${W1}" /dev/null)
check "Welt '${W1_NAME}' gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
CODE=$(http_code DELETE "${API_URL}/worlds/${W2}" /dev/null)
check "Welt '${W2_NAME}' gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204

printf '\n== K7 Talk-Übernahme ==\n'
if [ "${GAMEWORLD_SKIP_TALK:-0}" = 1 ]; then
	printf 'K7 übersprungen (GAMEWORLD_SKIP_TALK=1)\n'
elif [ -z "${SPREED_VERSION}" ]; then
	fail "K7 Talk (spreed) ist nicht aktiviert; ohne GAMEWORLD_SKIP_TALK=1 ist das ein Fehler (docs/dev-setup.md)"
else
	CODE=$(call "${ALT_AUTH}" GET "${API_URL}/worlds" /dev/null)
	check "K7 ${ALT} ist Verwalter über ${G_LEHR} (GET /api/worlds HTTP ${CODE})" wait_code "${ALT_AUTH}" "${API_URL}/worlds" 200 40
	create_world "${ALT_AUTH}" "${W3_NAME}"
	W3=${NEW_ID}
	check "K7 ${ALT} legt '${W3_NAME}' an HTTP 201 (ist ${NEW_CODE})" eq "${NEW_CODE}" 201
	matches "${W3}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
	check "K7 Talk-Raum für '${W3_NAME}' entsteht (binnen ${TALK_WAIT} s)" wait_talk "${W3}" '.has_room' "${TALK_WAIT}"
	http_code POST "${API_URL}/worlds/${W3}/stop" /dev/null >/dev/null || true
	T3=$(talk_field "${W3}" '.token // empty')
	fetch_parts "${T3}"
	TYPE=$(ptype "${ALT}")
	check "K7 ${ALT} ist Owner des Raums (participantType 1, ist ${TYPE:-leer}, HTTP ${PART_CODE})" eq "${TYPE}" 1
	check "K7 Negativkontrolle vorher: owner_not_admin false" eq "$(talk_field "${W3}" '.owner_not_admin')" false
	occ group:removeuser "${G_LEHR}" "${ALT}" >/dev/null 2>&1 || fail "K7 ${ALT} ließ sich nicht aus ${G_LEHR} entfernen"
	check "K7 nach dem Abgleich owner_not_admin true (binnen ${TALK_WAIT} s)" wait_talk "${W3}" '.owner_not_admin' "${TALK_WAIT}"
	CODE=$(http_code POST "${API_URL}/worlds/${W3}/talk/recreate" "${WORK_DIR}/recreate.json")
	T3_NEW=$(jq -r '.token // empty' "${WORK_DIR}/recreate.json" 2>/dev/null || true)
	check "K7 Raum neu angelegt HTTP 200, neues Token (ist ${CODE})" \
		sh -c '[ "$1" = 200 ] && [ -n "$2" ] && [ "$2" != "$3" ]' _ "${CODE}" "${T3_NEW}" "${T3}"
	fetch_parts "${T3_NEW}"
	TYPE=$(ptype "${ALT}")
	check "K7 ${ALT} ist im neuen Raum kein Teilnehmer (HTTP ${PART_CODE}, Typ ${TYPE:-keiner})" \
		sh -c '[ "$1" = 200 ] && [ -z "$2" ]' _ "${PART_CODE}" "${TYPE}"
	check "K7 Positivkontrolle: admin ist Moderator im neuen Raum" \
		sh -c 'case "$1" in 1|2) exit 0 ;; *) exit 1 ;; esac' _ "$(ptype admin)"
	check "K7 owner_not_admin nach dem Neuanlegen false" eq "$(talk_field "${W3}" '.owner_not_admin')" false
	occ group:adduser "${G_LEHR}" "${ALT}" >/dev/null 2>&1 || fail "K7 ${ALT} ließ sich nicht wieder in ${G_LEHR} aufnehmen"
	check "K7 ${ALT} wieder Verwalter (GET /api/worlds 200 binnen 40 s)" wait_code "${ALT_AUTH}" "${API_URL}/worlds" 200 40
	create_world "${ALT_AUTH}" "${W4_NAME}"
	W4=${NEW_ID}
	check "K7 ${ALT} legt '${W4_NAME}' an HTTP 201 (ist ${NEW_CODE})" eq "${NEW_CODE}" 201
	matches "${W4}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
	check "K7 Talk-Raum für '${W4_NAME}' entsteht (binnen ${TALK_WAIT} s)" wait_talk "${W4}" '.has_room' "${TALK_WAIT}"
	http_code POST "${API_URL}/worlds/${W4}/stop" /dev/null >/dev/null || true
	T4=$(talk_field "${W4}" '.token // empty')
	# Erst übernehmen lassen, wenn der Abgleich die übrigen Verwalter als Moderatoren
	# hinzugefügt hat: Bis dahin ist gw-alt allein im Raum (Verwalter-Schnappschuss
	# höchstens alle 60 s, Abgleich alle 5 min). Ein Verwalter-Besuch (GET /api/pause)
	# frischt den Schnappschuss auf, wie in der Oberfläche.
	room_synced() {
		until_ts=$(deadline "${TALK_WAIT}")
		while :; do
			http_code GET "${API_URL}/pause" /dev/null >/dev/null || true
			fetch_parts "${T4}"
			if [ "${PART_CODE}" = 200 ] && [ "$(ptype "${ALT}")" = 1 ]; then
				case "$(ptype admin)" in 1 | 2) return 0 ;; esac
			fi
			before "${until_ts}" || return 1
			sleep 10
		done
	}
	check "K7 ${ALT} ist Owner des zweiten Raums, admin nach dem Abgleich Moderator (binnen ${TALK_WAIT} s)" room_synced
	occ user:delete "${ALT}" >/dev/null 2>&1 || fail "K7 occ user:delete ${ALT} scheiterte"
	check "K7 Konto ${ALT} gelöscht" user_absent "${ALT}"
	taken_over() {
		[ "$(talk_field "${W4}" '.has_room and (.owner_not_admin | not) and .orphaned_token == null')" = true ]
	}
	wait_taken_over() {
		until_ts=$(deadline "${TALK_WAIT}")
		while :; do
			taken_over && return 0
			before "${until_ts}" || return 1
			sleep 10
		done
	}
	check "K7 nach dem Abgleich: Raum mit bestätigtem Verwalter als Besitzer (owner_not_admin false, binnen ${TALK_WAIT} s)" \
		wait_taken_over
	T4_NOW=$(talk_field "${W4}" '.token // empty')
	fetch_parts "${T4_NOW}"
	CODE=$(http_code GET "${SPREED}/room/${T4_NOW}" "${WORK_DIR}/room4.json")
	check "K7 Raum für admin erreichbar (GET room HTTP ${CODE})" eq "${CODE}" 200
	check "K7 Übernahme ohne neuen Raum: Token unverändert (kein Sperrfall)" sh -c '[ -n "$1" ] && [ "$1" = "$2" ]' _ "${T4_NOW}" "${T4}"
	check "K7 admin ist Moderator des übernommenen Raums" \
		sh -c 'case "$1" in 1|2) exit 0 ;; *) exit 1 ;; esac' _ "$(ptype admin)"
	for world_id in ${W3} ${W4}; do
		CODE=$(http_code DELETE "${API_URL}/worlds/${world_id}" /dev/null)
		check "Welt ${world_id} gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
	done
fi

printf '\n== K8 Sprache ==\n'
# K8 (D-25, D-27): account language for API texts, world language for game texts.
# notif_max AUTH -> highest notification_id of the account (0 without entries), x on a fetch error
notif_max() {
	code=$(call "$1" GET "${NOTIFY_URL}" "${WORK_DIR}/nmax.json")
	if [ "${code}" != 200 ]; then
		printf 'x'
		return 0
	fi
	jq -r '[.ocs.data[]?.notification_id] | max // 0' "${WORK_DIR}/nmax.json" 2>/dev/null || printf 'x'
}
# notif_subjects AUTH BASELINE FILE -> subjects of new Gameworld notifications, one per line
notif_subjects() {
	code=$(call "$1" GET "${NOTIFY_URL}" "${WORK_DIR}/nall.json")
	[ "${code}" = 200 ] || return 1
	jq -r --argjson b "$2" '.ocs.data[]? | select(.app == "gameworld" and .notification_id > $b) | .subject' \
		"${WORK_DIR}/nall.json" >"$3" 2>/dev/null
}
# wait_subject AUTH BASELINE TEXT FILE -> 0 once a new notification subject contains TEXT
wait_subject() {
	until_ts=$(deadline "${NOTIFY_WAIT}")
	while :; do
		notif_subjects "$1" "$2" "$4" && grep -qF "$3" "$4" && return 0
		before "${until_ts}" || return 1
		sleep 5
	done
}
add_user "${EN8}" "${EN8_AUTH#*:}" "English Manager" || abort "Konto ${EN8} ließ sich nicht anlegen"
add_user "${KIDEN8}" "${KIDEN8_AUTH#*:}" "English Kid" || abort "Konto ${KIDEN8} ließ sich nicht anlegen"
occ user:setting "${EN8}" core lang en >/dev/null 2>&1 || abort "Sprache von ${EN8} ließ sich nicht setzen"
occ user:setting "${KIDEN8}" core lang en >/dev/null 2>&1 || abort "Sprache von ${KIDEN8} ließ sich nicht setzen"
for pair in "${G_LEHR} ${EN8}" "${G_KLASSE} ${EN8}" "${G_KLASSE} ${KIDEN8}"; do
	set -- ${pair}
	occ group:adduser "$1" "$2" >/dev/null 2>&1 || abort "$2 ließ sich nicht in $1 aufnehmen"
done
check "K8 Konto ${EN8} hat core lang en, ${LEHRER} core lang de" sh -c \
	'[ "$(docker exec -u www-data "$1" php occ user:setting "$2" core lang | tr -d "\r")" = en ] &&
	 [ "$(docker exec -u www-data "$1" php occ user:setting "$3" core lang | tr -d "\r")" = de ]' \
	_ "${NC_CONTAINER}" "${EN8}" "${LEHRER}"

# 1. GET /api/me follows the account language.
check "K8 ${EN8} ist Verwalter über ${G_LEHR} (GET /api/worlds 200 binnen 40 s)" wait_code "${EN8_AUTH}" "${API_URL}/worlds" 200 40
CODE=$(call "${EN8_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/k8-me-en.json")
check "K8 GET /api/me als ${EN8}: HTTP 200, language en (ist ${CODE}, $(jq -r '.language // "leer"' "${WORK_DIR}/k8-me-en.json" 2>/dev/null))" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .language "$2")" = en ]' _ "${CODE}" "${WORK_DIR}/k8-me-en.json"
CODE=$(call "${LEHRER_AUTH}" GET "${API_URL}/me" "${WORK_DIR}/k8-me-de.json")
check "K8 Negativkontrolle: GET /api/me als ${LEHRER}: language de (ist $(jq -r '.language // "leer"' "${WORK_DIR}/k8-me-de.json" 2>/dev/null))" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r .language "$2")" = de ]' _ "${CODE}" "${WORK_DIR}/k8-me-de.json"

# 2. Error texts in the account language.
CODE=$(call "${KIDEN8_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/k8-forbid-en.json")
check "K8 ${KIDEN8} GET /api/worlds HTTP 403 mit '${TEXT_FORBIDDEN_EN}' (ist ${CODE}, $(detail_of "${WORK_DIR}/k8-forbid-en.json"))" \
	sh -c '[ "$1" = 403 ] && [ "$2" = "$3" ]' _ "${CODE}" "$(detail_of "${WORK_DIR}/k8-forbid-en.json")" "${TEXT_FORBIDDEN_EN}"
CODE=$(call "${KIND_AUTH}" GET "${API_URL}/worlds" "${WORK_DIR}/k8-forbid-de.json")
check "K8 Negativkontrolle: ${KIND} (de) bekommt weiter exakt '${TEXT_FORBIDDEN_DE}' (ist ${CODE})" \
	sh -c '[ "$1" = 403 ] && [ "$2" = "$3" ]' _ "${CODE}" "$(detail_of "${WORK_DIR}/k8-forbid-de.json")" "${TEXT_FORBIDDEN_DE}"

# 3. A new world takes the language of the creating manager.
create_world "${EN8_AUTH}" "${W8_NAME}"
W8=${NEW_ID}
check "K8 ${EN8} legt '${W8_NAME}' an HTTP 201, language en (ist ${NEW_CODE}, $(jq -r '.language // "leer"' "${WORK_DIR}/new-world.json" 2>/dev/null))" \
	sh -c '[ "$1" = 201 ] && [ "$(jq -r .language "$2")" = en ]' _ "${NEW_CODE}" "${WORK_DIR}/new-world.json"
matches "${W8}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"
create_world "${LEHRER_AUTH}" "${W9_NAME}"
W9=${NEW_ID}
check "K8 Negativkontrolle: ${LEHRER} legt '${W9_NAME}' an HTTP 201, language de (ist ${NEW_CODE}, $(jq -r '.language // "leer"' "${WORK_DIR}/new-world.json" 2>/dev/null))" \
	sh -c '[ "$1" = 201 ] && [ "$(jq -r .language "$2")" = de ]' _ "${NEW_CODE}" "${WORK_DIR}/new-world.json"
matches "${W9}" '^[0-9a-f]{12}$' || abort "Antwort ohne gültige id"

# 4. Only managers set the world language, only de, en or fr.
CODE=$(call "${EN8_AUTH}" POST "${API_URL}/worlds/${W8}/language" "${WORK_DIR}/k8-xx.json" '{"language":"xx"}')
check "K8 Negativkontrolle: POST language xx HTTP 422 (ist ${CODE})" eq "${CODE}" 422
CODE=$(call "${KIDEN8_AUTH}" POST "${API_URL}/worlds/${W8}/language" "${WORK_DIR}/k8-kidlang.json" '{"language":"fr"}')
check "K8 Negativkontrolle: ${KIDEN8} POST language HTTP 403 (ist ${CODE})" eq "${CODE}" 403
check "K8 Positivkontrolle: '${W8_NAME}' danach weiter en" eq "$(world_field "${W8}" '.language')" en

# 5. Refusal text in the world language (prejoin, gameworld_access).
NOTIF_EN8=$(notif_max "${EN8_AUTH}")
NOTIF_LEHRER=$(notif_max "${LEHRER_AUTH}")
check "K8 Grundlinie der Benachrichtigungen lesbar (${EN8} ${NOTIF_EN8}, ${LEHRER} ${NOTIF_LEHRER})" \
	sh -c 'printf "%s %s" "$1" "$2" | grep -Eq "^[0-9]+ [0-9]+$"' _ "${NOTIF_EN8}" "${NOTIF_LEHRER}"
check "K8 '${W8_NAME}' running binnen 120 s" wait_status "${W8}" running 120
check "K8 '${W9_NAME}' running binnen 120 s" wait_status "${W9}" running 120
C8=$(container_of "${W8}")
C9=$(container_of "${W9}")
PORT8=$(port_of "${C8}")
PORT9=$(port_of "${C9}")
matches "${PORT8}" '^[0-9]+$' || abort "kein UDP-Port für ${W8}"
matches "${PORT9}" '^[0-9]+$' || abort "kein UDP-Port für ${W9}"
PORT=${PORT8}
check "K8 Fremder8 an '${W8_NAME}' abgewiesen mit '${TEXT_DENY_EN}'" \
	probe_expect "${WORK_DIR}/k8-deny-en.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_DENY_EN}\"))" 30 \
	Fremder8 fremd-pass-8
printf 'Fremder8 an %s: %s\n' "${W8}" "$(probe_summary "${WORK_DIR}/k8-deny-en.json")"
PORT=${PORT9}
check "K8 Negativkontrolle: Fremder8 an '${W9_NAME}' (de) abgewiesen mit '${TEXT_DENY}'" \
	probe_expect "${WORK_DIR}/k8-deny-de.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_DENY}\"))" 30 \
	Fremder8 fremd-pass-8
check "K8 Gegenprobe: der deutsche Text enthält keinen englischen Satz" \
	not denied_with "${WORK_DIR}/k8-deny-de.json" "${TEXT_DENY_EN}"

# 6. Backup with a held session: chat and disconnect text in the world language.
CODE=$(call "${EN8_AUTH}" POST "${API_URL}/worlds/${W8}/invites" "${WORK_DIR}/k8-inv.json" "{\"kind\":\"user\",\"target\":\"${KIDEN8}\"}")
check "K8 ${EN8} lädt ${KIDEN8} ein HTTP 200 (ist ${CODE})" eq "${CODE}" 200
call "${EN8_AUTH}" GET "${API_URL}/worlds/${W8}/players" "${WORK_DIR}/p8.json" >/dev/null
KEN_NAME=$(player_field "${WORK_DIR}/p8.json" "${KIDEN8}" player_name)
KEN_PW=$(player_field "${WORK_DIR}/p8.json" "${KIDEN8}" password)
check "K8 Spielname ${KEN_NAME:-leer}, Passwort vorhanden (Länge ${#KEN_PW})" \
	sh -c '[ -n "$1" ] && [ -n "$2" ]' _ "${KEN_NAME}" "${KEN_PW}"
PORT=${PORT8}
check "K8 ${KIDEN8} tritt bei (auth_accept binnen 30 s)" \
	probe_expect "${WORK_DIR}/k8-kid-pre.json" '.result == "auth_accept"' 30 "${KEN_NAME}" "${KEN_PW}"
sleep 2.5
printf 'Sitzung %s für bis zu 120 s, dann Sicherung\n' "${KIDEN8}"
probe "${WORK_DIR}/k8-kid-hold.json" "${KEN_NAME}" "${KEN_PW}" --hold 120 --timeout "${SESSION_TIMEOUT}" &
KID_JOB=$!
check "K8 ${KIDEN8} ist laut Weltenliste online (binnen 30 s)" wait_online "${W8}" "${KEN_NAME}" 30
CODE=$(call "${EN8_AUTH}" POST "${API_URL}/worlds/${W8}/backups" "${WORK_DIR}/k8-backup.json" '{"confirm_disconnect":true}')
check "K8 Sicherung mit Trennbestätigung gestartet HTTP 202 (ist ${CODE})" eq "${CODE}" 202
wait "${KID_JOB}" || true
KID_JOB=""
printf '%s: %s\n' "${KIDEN8}" "$(probe_summary "${WORK_DIR}/k8-kid-hold.json")"
check "K8 Chat vor dem Trennen enthält '${TEXT_HALT_SOON_EN}'" \
	eq "$(jq -r --arg t "${TEXT_HALT_SOON_EN}" '[.events[]? | select(.kind == "chat" and (.text | contains($t)))] | length > 0' \
		"${WORK_DIR}/k8-kid-hold.json" 2>/dev/null)" true
check "K8 ${KIDEN8} getrennt mit '${TEXT_HALT_EN}'" kicked_with "${WORK_DIR}/k8-kid-hold.json" "${TEXT_HALT_EN}"
check "K8 Gegenprobe: kein deutscher Pausentext '${TEXT_HALT_DE}' im Trenngrund" \
	not kicked_with "${WORK_DIR}/k8-kid-hold.json" "${TEXT_HALT_DE}"
wait_backup() {
	until_ts=$(deadline 180)
	while :; do
		state=$(world_field "${W8}" '.backup_job.state // ""')
		[ "${state}" = ok ] && return 0
		[ "${state}" = failed ] && return 1
		before "${until_ts}" || return 1
		sleep 3
	done
}
check "K8 Sicherung fertig (backup_job ok binnen 180 s)" wait_backup
check "K8 '${W8_NAME}' läuft nach der Sicherung wieder (running binnen 90 s)" wait_status "${W8}" running 90

# 7. Switching to fr applies from the next start.
CODE=$(call "${EN8_AUTH}" POST "${API_URL}/worlds/${W8}/language" "${WORK_DIR}/k8-fr.json" '{"language":"fr"}')
check "K8 POST language fr HTTP 200, language fr, language_restart_needed true (ist ${CODE})" \
	sh -c '[ "$1" = 200 ] && [ "$(jq -r ".language + \" \" + (.language_restart_needed | tostring)" "$2")" = "fr true" ]' \
	_ "${CODE}" "${WORK_DIR}/k8-fr.json"
check "K8 Negativkontrolle: ohne Neustart weiter englisch abgewiesen" \
	probe_expect "${WORK_DIR}/k8-deny-still-en.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_DENY_EN}\"))" 30 \
	Fremder8 fremd-pass-8
CODE=$(call "${EN8_AUTH}" POST "${API_URL}/worlds/${W8}/restart" /dev/null)
check "K8 Neustart von '${W8_NAME}' HTTP 200 (ist ${CODE})" eq "${CODE}" 200
check "K8 '${W8_NAME}' nach dem Neustart running binnen 120 s" wait_status "${W8}" running 120
check "K8 language_restart_needed nach dem Neustart false" eq "$(world_field "${W8}" '.language_restart_needed')" false
C8=$(container_of "${W8}")
PORT=$(port_of "${C8}")
check "K8 Fremder8 an '${W8_NAME}' abgewiesen mit '${TEXT_DENY_FR}'" \
	probe_expect "${WORK_DIR}/k8-deny-fr.json" ".result == \"denied\" and ((.reason // \"\") | contains(\"${TEXT_DENY_FR}\"))" 30 \
	Fremder8 fremd-pass-8
printf 'Fremder8 an %s (fr): %s\n' "${W8}" "$(probe_summary "${WORK_DIR}/k8-deny-fr.json")"
check "K8 Positivkontrolle: '${W9_NAME}' blieb de" eq "$(world_field "${W9}" '.language')" de

# 8. Notification about the stranger: subject in the language of each recipient.
if wait_subject "${EN8_AUTH}" "${NOTIF_EN8}" "${SUBJECT_ATTEMPT_EN} ${W8_NAME}" "${WORK_DIR}/k8-n-en.txt"; then
	pass "K8 ${EN8} bekommt '${SUBJECT_ATTEMPT_EN} ${W8_NAME}'"
	check "K8 Negativkontrolle: ${LEHRER} bekommt '${SUBJECT_ATTEMPT_DE} ${W8_NAME}'" \
		wait_subject "${LEHRER_AUTH}" "${NOTIF_LEHRER}" "${SUBJECT_ATTEMPT_DE} ${W8_NAME}" "${WORK_DIR}/k8-n-de.txt"
	check "K8 Gegenprobe: ${EN8} hat keinen deutschen Betreff" not grep -qF "${SUBJECT_ATTEMPT_DE}" "${WORK_DIR}/k8-n-en.txt"
else
	# Daily throttle (5 hints a day, then one summary): never skipped silently.
	printf 'Hinweis: kein Einzelhinweis für %s binnen %s s (Tagesdrosselung?), Prüfung über die Sammelnachricht\n' \
		"${W8_NAME}" "${NOTIFY_WAIT}"
	notif_subjects "${EN8_AUTH}" 0 "${WORK_DIR}/k8-n-en-all.txt" || true
	notif_subjects "${LEHRER_AUTH}" 0 "${WORK_DIR}/k8-n-de-all.txt" || true
	check "K8 ${EN8} hat die englische Sammelnachricht '${SUBJECT_SUMMARY_EN}'" grep -qF "${SUBJECT_SUMMARY_EN}" "${WORK_DIR}/k8-n-en-all.txt"
	check "K8 Negativkontrolle: ${LEHRER} hat die deutsche Sammelnachricht '${SUBJECT_SUMMARY_DE}'" \
		grep -qF "${SUBJECT_SUMMARY_DE}" "${WORK_DIR}/k8-n-de-all.txt"
fi
for world_id in ${W8} ${W9}; do
	CODE=$(http_code DELETE "${API_URL}/worlds/${world_id}" /dev/null)
	check "Welt ${world_id} gelöscht HTTP 204 (ist ${CODE})" eq "${CODE}" 204
done

printf '\n== Aufräumen ==\n'
reset_fixtures
for account in ${ACCOUNTS}; do
	check "Konto ${account} entfernt" user_absent "${account}"
done
check "Positivkontrolle: dieselbe Abfrage erkennt das vorhandene Konto admin" user_present admin
check "Gruppen ${G_LEHR} und ${G_KLASSE} entfernt" sh -c \
	'! docker exec -u www-data "$1" php occ group:list --output=json | jq -e --arg a "$2" --arg b "$3" "has(\$a) or has(\$b)" >/dev/null' \
	_ "${NC_CONTAINER}" "${G_LEHR}" "${G_KLASSE}"
http_code GET "${API_URL}/admin/verwalter-groups" "${WORK_DIR}/vg-end.json" >/dev/null
check "${G_LEHR} keine Verwalter-Gruppe mehr" \
	eq "$(jq -r --arg g "${G_LEHR}" '(.groups // []) | index($g) == null' "${WORK_DIR}/vg-end.json" 2>/dev/null)" true
check "kein Orphan-Container der Abnahme übrig" eq "$(docker ps -aq --filter "label=gameworld.instance=${ORPHAN_INSTANCE}" | tr -d '\r')" ""
check "keine neuen Welt-Container übrig (ist $(new_containers))" eq "$(new_containers)" 0
check "Docker-Proxy ${PROXY_CONTAINER} läuft" \
	eq "$(docker inspect --format '{{.State.Running}}' "${PROXY_CONTAINER}" 2>/dev/null | tr -d '\r')" true

printf '\n== Regression Phase 5 bis 1 ==\n'
if [ "${GAMEWORLD_SKIP_REGRESSION:-0}" = 1 ]; then
	printf 'Regression übersprungen (GAMEWORLD_SKIP_REGRESSION=1)\n'
elif [ "${DEPLOY}" != manual ]; then
	fail "Regression nur im Modus manual (Dev-Stack); mit GAMEWORLD_SKIP_REGRESSION=1 aufrufen"
else
	# acceptance-phase5.sh ruft acceptance-phase4_1.sh, das Phase 4 bis 1 selbst aufruft.
	if sh "${PHASE5_SCRIPT}" >"${WORK_DIR}/phase5.log" 2>&1; then
		pass "Regression: acceptance-phase5.sh Exit 0 ($(grep 'Prüfungen bestanden' "${WORK_DIR}/phase5.log" | tail -n 1))"
	else
		fail "Regression: acceptance-phase5.sh nicht Exit 0"
		grep 'FEHLGESCHLAGEN\|ABBRUCH' "${WORK_DIR}/phase5.log" >&2 || tail -n 20 "${WORK_DIR}/phase5.log" >&2
	fi
	cp "${WORK_DIR}/phase5.log" "${REPO_ROOT}/.dev/acceptance-phase5-regression.log" 2>/dev/null || true
	check "Regression: Log enthält 'Phasenabnahme Phase 5 erfolgreich'" \
		grep -qx 'Phasenabnahme Phase 5 erfolgreich' "${WORK_DIR}/phase5.log"
	check "Regression: Phase 5 meldet 'Phasenabnahme Phase 4.1 erfolgreich' bestanden" \
		grep -qx "bestanden: Regression: Log enthält 'Phasenabnahme Phase 4.1 erfolgreich'" "${WORK_DIR}/phase5.log"
	# N von N je Phase 4 bis 1 (Phase 5 prüft sie im Log von Phase 4.1) und die eigene Zeile von Phase 5.
	check "Regression: vier bestandene N-von-N-Zeilen der Phasen 4 bis 1" eq "$(awk '
		$1 == "bestanden:" && $2 == "Regression:" && $3 == "Log" && $6 == "von" && $8 == "Prüfungen" &&
		substr($5, 1, 1) == "\047" && substr($5, 2) == $7 { n++ }
		END { print n + 0 }' "${WORK_DIR}/phase5.log")" 4
	check "Regression: Phase 5 selbst N von N" awk '
		NF == 5 && $2 == "von" && $4 == "Prüfungen" && $5 == "bestanden" && $1 == $3 { found = 1 }
		END { exit !found }' "${WORK_DIR}/phase5.log"
	grep -E "Prüfungen bestanden" "${WORK_DIR}/phase5.log" | sed 's/^/  /' || true
	check "nach der Regression: ExApp erreichbar" wait_code "${ADMIN_AUTH}" "${API_URL}/me" 200 60
fi

printf '\n%s von %s Prüfungen bestanden\n' "${PASSED}" "${TOTAL}"
if [ "${FAILED}" -gt 0 ]; then
	printf '%s Prüfungen fehlgeschlagen\n' "${FAILED}" >&2
	exit 1
fi
printf 'Phasenabnahme Phase 6 erfolgreich (Modus %s)\n' "${DEPLOY}"
