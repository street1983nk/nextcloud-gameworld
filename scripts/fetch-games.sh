#!/bin/sh
# Holt die Spiel-Zips, die wegen ihrer Größe nicht im Git liegen, nach
# vendor/games und prüft jede Datei gegen vendor/games/SHA256SUMS.
#
# Läuft nur beim Einrichten (scripts/dev/register-exapp.sh) und beim Image-Bau,
# nie von Gameworld zur Laufzeit. Gameworld selbst lädt nichts von ContentDB.
#
# Eine Datei wird nur abgelegt, wenn ihre Prüfsumme stimmt: Der Download landet
# zuerst in einer .part-Datei im selben Verzeichnis, wird geprüft und erst dann
# per mv atomar an den Zielnamen gelegt. Bei Abweichung wird die .part-Datei
# gelöscht und das Skript endet mit Exit 1.
#
# Offline-Variante: GAMEWORLD_GAME_SOURCE_DIR zeigt auf ein Verzeichnis mit
# einer gleichnamigen Datei, die statt des Downloads übernommen wird. Die
# Prüfsumme wird auch dann geprüft.
#
# Idempotent: Eine vorhandene Datei mit stimmender Prüfsumme bleibt unberührt.
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
GAMES_DIR="${REPO_ROOT}/vendor/games"
SUMS_FILE="${GAMES_DIR}/SHA256SUMS"

# Abzurufende Dateien als "Dateiname URL", eine Zeile pro Spiel.
# VoxeLibre 0.92.4, ContentDB-Paket Wuzzy/mineclone2, Release 39534.
GAMES='mineclone2-39534.zip https://cdn.content.luanti.org/uploads/3e11bd7181.zip'

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
