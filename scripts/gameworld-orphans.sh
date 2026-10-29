#!/bin/sh
# Finds leftovers of Gameworld on the Docker host and removes them on request.
#
# Meant for the time after uninstalling the ExApp (ROADMAP phase 6,
# criterion 3): Gameworld clears away its world containers itself on deactivation,
# but the volumes with the save games deliberately stay behind
# (D-15/D-17), and an aborted deactivation can leave containers behind.
#
# Acts only on
#   - containers with the label gameworld.managed=true (world containers of every
#     Gameworld instance on this host) and
#   - volumes whose name follows the scheme gameworld-<instance>-<world>
#     (^gameworld-[a-z0-9-]+$, i.e. never Compose volumes with an underscore).
# Everything else (Nextcloud, AppAPI, HaRP, the Docker proxy, other projects)
# is never touched. The docker filters are checked a second time
# in the script.
#
# The default is listing only. Removal only with --remove-containers or
# --remove-volumes and after typed confirmation; --yes skips only the
# question for containers, never the one for volumes (save games would be lost otherwise).
#
# Runs on the Docker host, needs the docker CLI with rights on the
# host daemon (root or group docker). Output in English because the script
# reaches store users worldwide.
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

# list_containers -> lines "ID<TAB>Name<TAB>Instance<TAB>Status", only with label managed=true
list_containers() {
	raw=$(docker ps -a --filter "label=gameworld.managed=true" \
		--format '{{.ID}}	{{.Names}}	{{.Label "gameworld.managed"}}	{{.Label "gameworld.instance"}}	{{.Status}}') ||
		fail "Cannot talk to the Docker daemon. Run as root or as a member of the docker group."
	printf '%s\n' "${raw}" | while IFS="${TAB}" read -r cid name managed instance state; do
		# Second check on the result: only real Gameworld world containers.
		[ "${managed}" = "true" ] || continue
		[ -n "${cid}" ] || continue
		printf '%s\t%s\t%s\t%s\n' "${cid}" "${name}" "${instance}" "${state}"
	done
}

# list_volumes -> volume names following the Gameworld scheme
list_volumes() {
	raw=$(docker volume ls -q --filter "name=gameworld-") ||
		fail "Cannot talk to the Docker daemon. Run as root or as a member of the docker group."
	# Second check: docker filters by substring, the script by the full scheme.
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
	# Read again: volumes and containers may have changed since the list.
	VOLUMES=$(list_volumes)
	if [ -n "${VOLUMES}" ]; then
		n=$(count_lines "${VOLUMES}")
		printf '\nVolumes hold the game worlds. Download backups in Nextcloud Files first if you still need them.\n'
		# Deliberately without --yes: never delete save games without typing.
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
