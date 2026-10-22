// Kleiner Pfad-Router für die Handy-Seiten hinter den Benachrichtigungen
// (04.1 Pattern 9), ohne vue-router.
//
// Die Embedded-Route von AppAPI nimmt einen Pfadrest an:
// /index.php/apps/app_api/embedded/gameworld/gameworld/<seite>?<parameter>.
// Pfad statt "#": das Fragment ginge beim Login-Umweg verloren.
//
// parsePath, pageParams und pagePath sind rein (Node-Prüfung in
// frontend/tests/route.check.mjs); nur currentPage und navigate greifen auf
// window zu. Parameter aus der Adresse sind manipulierbar: hier fällt alles
// weg, was nicht dem Muster entspricht, das Backend prüft erneut (T-04.1-36).
import { generateUrl } from '@nextcloud/router'

export const EMBED_STEM = '/apps/app_api/embedded/gameworld/gameworld'
export const PAGES = Object.freeze(['pause', 'versuch', 'rueckblick'])
// Ereignis nach navigate(); history.pushState selbst löst kein popstate aus.
export const ROUTE_EVENT = 'gameworld-route'

const WORLD_ID = /^[0-9a-f]{12}$/
const DAY = /^\d{4}-\d{2}-\d{2}$/

// Seite aus dem Pfad: das erste Segment nach dem Stamm, sonst "" (Übersicht).
export function parsePath(pathname) {
	if (typeof pathname !== 'string') {
		return ''
	}
	const index = pathname.indexOf(EMBED_STEM)
	if (index === -1) {
		return ''
	}
	const rest = pathname.slice(index + EMBED_STEM.length)
	if (rest !== '' && !rest.startsWith('/')) {
		return ''
	}
	const segment = rest.split('/')[1] ?? ''
	return PAGES.includes(segment) ? segment : ''
}

// Echter Kalendertag im Format JJJJ-MM-TT (2026-02-30 fällt weg).
function validDay(value) {
	if (!DAY.test(value)) {
		return false
	}
	const [year, month, day] = value.split('-').map(Number)
	const date = new Date(Date.UTC(year, month - 1, day))
	return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

// Nur bekannte, gültige Parameter: welt (Welt-ID, 12 Hex) und tag (Datum).
function cleanParams(raw) {
	const params = {}
	const welt = raw.welt
	if (typeof welt === 'string' && WORLD_ID.test(welt)) {
		params.welt = welt
	}
	const tag = raw.tag
	if (typeof tag === 'string' && validDay(tag)) {
		params.tag = tag
	}
	return params
}

export function pageParams(search) {
	const query = new URLSearchParams(typeof search === 'string' ? search : '')
	return cleanParams({ welt: query.get('welt'), tag: query.get('tag') })
}

// Pfad für generateUrl; unbekannte Seiten führen zur Übersicht.
export function pagePath(page) {
	return PAGES.includes(page) ? `${EMBED_STEM}/${page}` : EMBED_STEM
}

export function currentPage() {
	return parsePath(window.location.pathname)
}

export function currentParams() {
	return pageParams(window.location.search)
}

// Wechsel innerhalb der App ohne Neuladen; App.vue hört auf ROUTE_EVENT und popstate.
export function navigate(page, params = {}) {
	const query = new URLSearchParams(cleanParams(params ?? {})).toString()
	const url = generateUrl(pagePath(page)) + (query ? `?${query}` : '')
	window.history.pushState({}, '', url)
	window.dispatchEvent(new Event(ROUTE_EVENT))
}
