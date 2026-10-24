#!/bin/sh
# Findet Reste von Gameworld auf dem Docker-Host und entfernt sie auf Wunsch.
#
# Gedacht für die Zeit nach dem Deinstallieren der ExApp (ROADMAP Phase 6,
# Kriterium 3): Gameworld räumt beim Deaktivieren seine Welt-Container selbst
# ab, die Volumes mit den Spielständen bleiben aber absichtlich liegen
# (D-15/D-17), und ein abgebrochenes Deaktivieren kann Container hinterlassen.
#
# Wirkung nur auf
#   - Container mit dem Label gameworld.managed=true (Welt-Container jeder
#     Gameworld-Instanz auf diesem Host) und
#   - Volumes, deren Name dem Schema gameworld-<instanz>-<welt> folgt
#     (^gameworld-[a-z0-9-]+$, also nie Compose-Volumes mit Unterstrich).
# Alles andere (Nextcloud, AppAPI, HaRP, der Docker-Proxy, andere Projekte)
# wird nie angefasst. Die Filter von docker werden im Skript ein zweites Mal
# geprüft.
#
# Standard ist nur Auflisten. Entfernen erst mit --remove-containers bzw.
# --remove-volumes und nach getippter Bestätigung; --yes überspringt nur die
# Frage für Container, nie die für Volumes (Spielstände gehen sonst verloren).
#
# Läuft auf dem Docker-Host, braucht die docker CLI mit Rechten auf den
# Host-Daemon (root oder Gruppe docker). Ausgaben auf Englisch, weil das Skript
# Store-Nutzer weltweit erreicht.
set -eu

VOLUME_PATTERN='^gameworld-[a-z0-9-]+$'
TAB=$(printf '\t')

usage() {
	cat <<'EOF'
Usage: gameworld-orphans.sh [--remove-containers] [--remove-volumes] [--yes]

Lists Gameworld leftovers on this Docker host: world containers with the label
gameworld.managed=true and volumes named gameworld-<instance>-<world>.
Without options nothing is changed.

  --remove-containers  remove the listed containers (asks, type "yes")
  --remove-volumes     delete the listed volumes and the game worlds stored in
                       them (always asks, type "delete")
  --yes                skip the container question; never skips the volume question
  -h, --help           show this help

Run it after uninstalling the Gameworld app. While Gameworld is still
installed, its own worlds are listed too; download backups first.
EOF
}

fail() {
	printf 'ERROR: %s\n' "$1" >&2
	exit 1
}

REMOVE_CONTAINERS=0
REMOVE_VOLUMES=0
ASSUME_YES=0
for arg in "$@"; do
	case "${arg}" in
	--remove-containers) REMOVE_CONTAINERS=1 ;;
	--remove-volumes) REMOVE_VOLUMES=1 ;;
	--yes) ASSUME_YES=1 ;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		printf 'Unknown option: %s\n\n' "${arg}" >&2
		usage >&2
		exit 2
		;;
	esac
done

command -v docker >/dev/null 2>&1 || fail "docker CLI not found. Run this on the Docker host of your Nextcloud."

# list_containers -> Zeilen "ID<TAB>Name<TAB>Instanz<TAB>Status", nur mit Label managed=true
list_containers() {
	raw=$(docker ps -a --filter "label=gameworld.managed=true" \
		--format '{{.ID}}	{{.Names}}	{{.Label "gameworld.managed"}}	{{.Label "gameworld.instance"}}	{{.Status}}') ||
		fail "Cannot talk to the Docker daemon. Run as root or as a member of the docker group."
	printf '%s\n' "${raw}" | while IFS="${TAB}" read -r cid name managed instance state; do
		# Zweite Prüfung am Ergebnis: nur echte Gameworld-Welt-Container.
		[ "${managed}" = "true" ] || continue
		[ -n "${cid}" ] || continue
		printf '%s\t%s\t%s\t%s\n' "${cid}" "${name}" "${instance}" "${state}"
	done
}

# list_volumes -> Volume-Namen nach dem Gameworld-Schema
list_volumes() {
	raw=$(docker volume ls -q --filter "name=gameworld-") ||
		fail "Cannot talk to the Docker daemon. Run as root or as a member of the docker group."
	# Zweite Prüfung: docker filtert nach Teilstring, das Skript nach dem vollen Schema.
	printf '%s\n' "${raw}" | grep -E "${VOLUME_PATTERN}" || true
}

count_lines() {
	if [ -z "$1" ]; then
		printf '0'
	else
		printf '%s\n' "$1" | wc -l | tr -d ' '
	fi
}

ask() {
	printf '%s ' "$1"
	answer=""
	read -r answer || answer=""
	[ "${answer}" = "$2" ]
}

show() {
	if [ -n "${CONTAINERS}" ]; then
		printf 'Gameworld containers (%s):\n' "$(count_lines "${CONTAINERS}")"
		printf '%s\n' "${CONTAINERS}" | while IFS="${TAB}" read -r cid name instance state; do
			printf '  %s  instance=%s  %s  (%s)\n' "${name}" "${instance:-?}" "${state}" "${cid}"
		done
	fi
	if [ -n "${VOLUMES}" ]; then
		printf 'Gameworld volumes (%s):\n' "$(count_lines "${VOLUMES}")"
		printf '%s\n' "${VOLUMES}" | sed 's/^/  /'
	fi
}

CONTAINERS=$(list_containers)
VOLUMES=$(list_volumes)

if [ -z "${CONTAINERS}" ] && [ -z "${VOLUMES}" ]; then
	printf 'No Gameworld leftovers found.\n'
	exit 0
fi

show

EXAPP=$(docker ps -a -q --filter "name=nc_app_gameworld" 2>/dev/null || true)
if [ -n "${EXAPP}" ]; then
	printf '\nWARNING: The Gameworld app container (nc_app_gameworld) still exists.\n'
	printf 'The list above then includes the worlds of that installation.\n'
fi

if [ "${REMOVE_CONTAINERS}" -eq 0 ] && [ "${REMOVE_VOLUMES}" -eq 0 ]; then
	printf '\nNothing was changed. Use --remove-containers or --remove-volumes to clean up.\n'
	exit 0
fi

FAILED=0

if [ "${REMOVE_CONTAINERS}" -eq 1 ] && [ -n "${CONTAINERS}" ]; then
	n=$(count_lines "${CONTAINERS}")
	if [ "${ASSUME_YES}" -eq 1 ] || ask "Remove ${n} Gameworld containers? Type yes:" "yes"; then
		for cid in $(printf '%s\n' "${CONTAINERS}" | cut -f 1); do
			if docker rm -f "${cid}" >/dev/null; then
				printf 'Removed container %s\n' "${cid}"
			else
				printf 'Could not remove container %s\n' "${cid}" >&2
				FAILED=$((FAILED + 1))
			fi
		done
	else
		printf 'Containers kept.\n'
	fi
fi

if [ "${REMOVE_VOLUMES}" -eq 1 ]; then
	# Neu lesen: Volumes und Container können sich seit der Liste geändert haben.
	VOLUMES=$(list_volumes)
	if [ -n "${VOLUMES}" ]; then
		n=$(count_lines "${VOLUMES}")
		printf '\nVolumes hold the game worlds. Download backups in Nextcloud Files first if you still need them.\n'
		# Bewusst ohne --yes: Spielstände nie ohne Tippen löschen.
		if ask "This deletes the game worlds stored in ${n} volumes permanently. Type delete:" "delete"; then
			for volume in ${VOLUMES}; do
				if docker volume rm "${volume}" >/dev/null; then
					printf 'Deleted volume %s\n' "${volume}"
				else
					printf 'Could not delete volume %s (still used by a container?)\n' "${volume}" >&2
					FAILED=$((FAILED + 1))
				fi
			done
		else
			printf 'Volumes kept.\n'
		fi
	fi
fi

[ "${FAILED}" -eq 0 ] || exit 1
