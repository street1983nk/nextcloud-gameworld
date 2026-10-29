#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Builds the Gameworld app store archive: dist/gameworld-<version>.tar.gz.
#
# The store artifact is NOT the Docker image. It is a tar.gz with exactly one
# top folder gameworld/ with appinfo/info.xml, img/app.svg and LICENSE. The image is
# referenced only from info.xml (docker-install) and pulled by AppAPI at install
# time from ghcr.io. Template: nextcloud-mcp-connector/scripts/build_store_release.sh,
# here POSIX sh instead of bash and without grep -P.
#
# Usage: sh scripts/build-store-release.sh
# The version comes from appinfo/info.xml <version>.
#
# Signature for diagnosis only and only if GAMEWORLD_SIGN_KEY points to a key:
# tar.gz is not byte-for-byte reproducible, the store checks the downloaded
# release asset. The submission signature is made over exactly that file, never over
# the local archive.
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
