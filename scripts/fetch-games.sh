#!/bin/sh
# Fetches the game zips that are not in Git because of their size into
# vendor/games and checks every file against vendor/games/SHA256SUMS.
#
# Runs only during setup (scripts/dev/register-exapp.sh) and during the image build,
# never by Gameworld at runtime. Gameworld itself downloads nothing from ContentDB.
#
# A file is stored only if its checksum matches: the download first lands
# in a .part file in the same directory, is checked and only then moved
# atomically to the target name with mv. On a mismatch the .part file is
# deleted and the script ends with exit 1.
#
# Offline variant: GAMEWORLD_GAME_SOURCE_DIR points to a directory with
# a file of the same name, which is taken instead of the download. The
# checksum is checked then as well.
#
# Idempotent: an existing file with a matching checksum stays untouched.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
GAMES_DIR="${REPO_ROOT}/vendor/games"
SUMS_FILE="${GAMES_DIR}/SHA256SUMS"

# Files to fetch as "filename URL", one line per game.
# VoxeLibre 0.92.4, ContentDB package Wuzzy/mineclone2, release 39534.
# The release download link of ContentDB, not the CDN upload address: since
# 27.10.2026 cdn.content.luanti.org serves a certificate for *.b-cdn.net and
# curl refuses it. The link redirects to content.luanti.org/storage; the file
# is byte for byte the same (SHA256SUMS unchanged).
GAMES='mineclone2-39534.zip https://content.luanti.org/packages/Wuzzy/mineclone2/releases/39534/download/'

fail() {
	printf 'FEHLER: %s\n' "$1" >&2
	exit 1
}

sha256_of() {
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum "$1" | cut -d ' ' -f 1
		return
	fi
	if command -v shasum >/dev/null 2>&1; then
		shasum -a 256 "$1" | cut -d ' ' -f 1
		return
	fi
	fail "weder sha256sum noch shasum gefunden, die Prüfsumme lässt sich nicht berechnen"
}

[ -f "${SUMS_FILE}" ] || fail "${SUMS_FILE} fehlt"

printf '%s\n' "${GAMES}" | while read -r name url; do
	[ -n "${name}" ] || continue
	expected=$(grep "  ${name}\$" "${SUMS_FILE}" | cut -d ' ' -f 1 | head -n 1 || true)
	[ -n "${expected}" ] || fail "Keine Prüfsumme für ${name} in SHA256SUMS"

	target="${GAMES_DIR}/${name}"
	if [ -f "${target}" ] && [ "$(sha256_of "${target}")" = "${expected}" ]; then
		printf '%s vorhanden und geprüft\n' "${name}"
		continue
	fi

	part="${target}.part"
	rm -f "${part}"
	if [ -n "${GAMEWORLD_GAME_SOURCE_DIR:-}" ]; then
		source_file="${GAMEWORLD_GAME_SOURCE_DIR}/${name}"
		[ -f "${source_file}" ] || fail "${source_file} fehlt (GAMEWORLD_GAME_SOURCE_DIR)"
		printf 'übernehme %s aus %s\n' "${name}" "${GAMEWORLD_GAME_SOURCE_DIR}"
		cp "${source_file}" "${part}"
	else
		printf 'lade %s von %s\n' "${name}" "${url}"
		if ! curl -fsSL --proto '=https' --tlsv1.2 -o "${part}" "${url}"; then
			rm -f "${part}"
			fail "Download von ${name} fehlgeschlagen"
		fi
	fi

	actual=$(sha256_of "${part}")
	if [ "${actual}" != "${expected}" ]; then
		rm -f "${part}"
		fail "Prüfsumme von ${name} stimmt nicht, Datei verworfen"
	fi
	mv -f "${part}" "${target}"
	printf '%s abgelegt und geprüft\n' "${name}"
done
