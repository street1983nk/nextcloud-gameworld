// Check script for frontend/src/route.js (without browser): node frontend/tests/route.check.mjs
import assert from 'node:assert/strict'

// Minimal browser substitute for generateUrl (@nextcloud/router), history and events.
const pushed = []
const events = []
globalThis.window = {
	_oc_webroot: '',
	location: { pathname: '/index.php/apps/app_api/embedded/gameworld/gameworld/versuch', search: '?welt=abc123def456&tag=2026-10-21' },
	history: { pushState: (state, title, url) => pushed.push(url) },
	dispatchEvent: (event) => events.push(event.type),
}

const { EMBED_STEM, PAGES, currentPage, dayLabel, localDay, navigate, pageParams, pagePath, parsePath } = await import('../src/route.js')
const { setLanguage } = await import('../src/i18n/index.js')

setLanguage('de')

const stem = '/index.php/apps/app_api/embedded/gameworld/gameworld'

assert.equal(EMBED_STEM, '/apps/app_api/embedded/gameworld/gameworld')
assert.deepEqual([...PAGES], ['pause', 'versuch', 'rueckblick'])

// Path remainder after the root
assert.equal(parsePath(`${stem}/pause`), 'pause')
assert.equal(parsePath(`${stem}/versuch`), 'versuch')
assert.equal(parsePath(`${stem}/rueckblick/`), 'rueckblick')
assert.equal(parsePath(`${stem}/rueckblick/mehr`), 'rueckblick')
assert.equal(parsePath(stem), '')
assert.equal(parsePath(`${stem}/`), '')
assert.equal(parsePath(`${stem}/unbekannt`), '')
assert.equal(parsePath(`${stem}/Pause`), '')
// Pretty URLs without index.php and Nextcloud in a subfolder
assert.equal(parsePath('/apps/app_api/embedded/gameworld/gameworld/pause'), 'pause')
assert.equal(parsePath('/cloud/index.php/apps/app_api/embedded/gameworld/gameworld/versuch'), 'versuch')
// Other pages and a root that only looks similar
assert.equal(parsePath('/index.php/apps/files/pause'), '')
assert.equal(parsePath('/index.php/apps/app_api/embedded/gameworld/gameworldx/pause'), '')
assert.equal(parsePath(''), '')
assert.equal(parsePath(undefined), '')

// Parameters: only valid world ID (12 hex) and valid date
assert.deepEqual(pageParams('?welt=abc123def456&tag=2026-10-21'), { welt: 'abc123def456', tag: '2026-10-21' })
assert.deepEqual(pageParams('?tag=2026-10-21'), { tag: '2026-10-21' })
assert.deepEqual(pageParams('?welt=ABC123DEF456&tag=21.10.2026'), {})
assert.deepEqual(pageParams('?welt=abc123def45&tag=2026-1-21'), {})
assert.deepEqual(pageParams('?welt=abc123def4567'), {})
assert.deepEqual(pageParams('?welt=<script>&tag=2026-10-21x'), {})
assert.deepEqual(pageParams('?tag=2026-02-30'), {})
assert.deepEqual(pageParams('?tag=2026-13-01'), {})
assert.deepEqual(pageParams('?andere=1'), {})
assert.deepEqual(pageParams(''), {})
assert.deepEqual(pageParams(undefined), {})

// Day by the device clock and heading
assert.equal(localDay(new Date(2026, 9, 1, 23, 59)), '2026-10-01')
assert.equal(localDay(new Date(2026, 0, 31, 0, 0)), '2026-01-31')
assert.equal(dayLabel('2026-10-21', '2026-10-21'), 'Heute')
assert.equal(dayLabel('2026-10-20', '2026-10-21'), 'Dienstag, 20. Oktober')
assert.equal(dayLabel('kaputt', '2026-10-21'), '')

// Current location from window.location
assert.equal(currentPage(), 'versuch')

// Path and navigation via generateUrl and history.pushState
assert.equal(pagePath('pause'), '/apps/app_api/embedded/gameworld/gameworld/pause')
assert.equal(pagePath(''), '/apps/app_api/embedded/gameworld/gameworld')
assert.equal(pagePath('unbekannt'), '/apps/app_api/embedded/gameworld/gameworld')

navigate('pause')
assert.equal(pushed.at(-1), `${stem}/pause`)
assert.equal(events.at(-1), 'gameworld-route')

navigate('versuch', { welt: 'abc123def456', tag: '2026-10-21' })
assert.equal(pushed.at(-1), `${stem}/versuch?welt=abc123def456&tag=2026-10-21`)

// Invalid parameters never end up in the address
navigate('rueckblick', { tag: 'morgen', welt: '../x' })
assert.equal(pushed.at(-1), `${stem}/rueckblick`)

navigate('')
assert.equal(pushed.at(-1), stem)
assert.equal(pushed.length, 4)

// English and French (D-25); page IDs and parameters stay the same in every language.
setLanguage('en')
assert.equal(dayLabel('2026-10-21', '2026-10-21'), 'Today')
assert.equal(dayLabel('2026-10-20', '2026-10-21'), 'Tuesday 20 October')
assert.equal(parsePath(`${stem}/rueckblick`), 'rueckblick')
setLanguage('fr')
assert.equal(dayLabel('2026-10-21', '2026-10-21'), 'Aujourd’hui')
assert.equal(dayLabel('2026-10-20', '2026-10-21'), 'Mardi 20 octobre')
setLanguage('de')

console.log('route.check: alle Prüfungen bestanden')
