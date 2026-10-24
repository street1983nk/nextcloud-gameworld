#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Baut das App-Store-Archiv von Gameworld: dist/gameworld-<version>.tar.gz.
#
# Das Store-Artefakt ist NICHT das Docker-Image. Es ist ein tar.gz mit genau einem
# Top-Ordner gameworld/ mit appinfo/info.xml, img/app.svg und LICENSE. Das Image wird
# nur aus info.xml (docker-install) referenziert und von AppAPI bei der Installation
# aus ghcr.io gezogen. Vorlage: nextcloud-mcp-connector/scripts/build_store_release.sh,
# hier POSIX-sh statt bash und ohne grep -P.
#
# Aufruf: sh scripts/build-store-release.sh
# Die Version kommt aus appinfo/info.xml <version>.
#
# Signatur nur zur Diagnose und nur, wenn GAMEWORLD_SIGN_KEY auf einen Schlüssel zeigt:
# tar.gz ist nicht bytegenau reproduzierbar, der Store prüft das heruntergeladene
# Release-Asset. Die Einreichungs-Signatur entsteht über genau diese Datei, nie über
# das lokale Archiv.
set -eu

APP_ID="gameworld"
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
INFO_XML="${ROOT}/appinfo/info.xml"

fail() {
	printf 'FEHLER: %s\n' "$1" >&2
	exit 1
}

[ -f "${INFO_XML}" ] || fail "${INFO_XML} fehlt"
VERSION=$(sed -n 's:.*<version>\([^<]*\)</version>.*:\1:p' "${INFO_XML}" | head -n 1)
[ -n "${VERSION}" ] || fail "keine <version> in appinfo/info.xml"

for required in appinfo/info.xml img/app.svg LICENSE; do
	[ -f "${ROOT}/${required}" ] || fail "${required} fehlt"
done

STAGE=$(mktemp -d)
trap 'rm -rf "${STAGE}"' EXIT INT TERM

mkdir -p "${STAGE}/${APP_ID}/appinfo" "${STAGE}/${APP_ID}/img"
cp "${ROOT}/appinfo/info.xml" "${STAGE}/${APP_ID}/appinfo/info.xml"
cp "${ROOT}/img/app.svg" "${STAGE}/${APP_ID}/img/app.svg"
cp "${ROOT}/LICENSE" "${STAGE}/${APP_ID}/LICENSE"

OUT_DIR="${ROOT}/dist"
mkdir -p "${OUT_DIR}"
ARCHIVE="${OUT_DIR}/${APP_ID}-${VERSION}.tar.gz"
rm -f "${ARCHIVE}"
tar --numeric-owner --owner=0 --group=0 -czf "${ARCHIVE}" -C "${STAGE}" "${APP_ID}"
printf 'gebaut: %s\n' "${ARCHIVE}"

if command -v sha256sum >/dev/null 2>&1; then
	sha256sum "${ARCHIVE}"
elif command -v shasum >/dev/null 2>&1; then
	shasum -a 256 "${ARCHIVE}"
fi

if [ -n "${GAMEWORLD_SIGN_KEY:-}" ]; then
	[ -f "${GAMEWORLD_SIGN_KEY}" ] || fail "GAMEWORLD_SIGN_KEY zeigt auf keine Datei"
	printf '\nbase64 SHA-512-Signatur über das LOKALE Archiv (nur Diagnose):\n'
	openssl dgst -sha512 -sign "${GAMEWORLD_SIGN_KEY}" "${ARCHIVE}" | openssl base64 -A
	printf '\n'
	printf 'Hinweis: diese Signatur NICHT einreichen, sondern das heruntergeladene Release-Asset signieren.\n' >&2
fi
