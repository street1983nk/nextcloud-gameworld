// Small path router for the phone pages behind the notifications
// (04.1 Pattern 9), without vue-router.
//
// The embedded route of AppAPI takes a path remainder:
// /index.php/apps/app_api/embedded/gameworld/gameworld/<page>?<parameter>.
// Path instead of "#": the fragment would be lost on the login detour.
//
// parsePath, pageParams and pagePath are pure (Node check in
// frontend/tests/route.check.mjs); only currentPage and navigate access
// window. Parameters from the address can be manipulated: everything that does not
// match the pattern is dropped here, the backend checks again (T-04.1-36).
import { generateUrl } from '@nextcloud/router'
import { dateLocale, t } from './i18n/index.js'

export const EMBED_STEM = '/apps/app_api/embedded/gameworld/gameworld'
export const PAGES = Object.freeze(['pause', 'versuch', 'rueckblick'])
// Event after navigate(); history.pushState itself triggers no popstate.
export const ROUTE_EVENT = 'gameworld-route'

const WORLD_ID = /^[0-9a-f]{12}$/
const DAY = /^\d{4}-\d{2}-\d{2}$/

// Page from the path: the first segment after the root, otherwise "" (overview).
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

// Real calendar day in the format YYYY-MM-DD (2026-02-30 is dropped).
function validDay(value) {
	if (!DAY.test(value)) {
		return false
	}
	const [year, month, day] = value.split('-').map(Number)
	const date = new Date(Date.UTC(year, month - 1, day))
	return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
}

// Known, valid parameters only: welt (world ID, 12 hex) and tag (date).
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

// Default for tag: today by the clock of this device (YYYY-MM-DD).
export function localDay(now = new Date()) {
	const month = String(now.getMonth() + 1).padStart(2, '0')
	const day = String(now.getDate()).padStart(2, '0')
	return `${now.getFullYear()}-${month}-${day}`
}

// Heading for a day: "Heute" or e.g. "Dienstag, 21. Oktober" in German, in the
// date format of the UI language; the first letter is upper case (French weekdays
// are lower case on their own).
export function dayLabel(tag, today = localDay()) {
	if (tag === today) {
		return t('core.route.today')
	}
	if (!validDay(tag)) {
		return ''
	}
	const [year, month, day] = tag.split('-').map(Number)
	const label = new Date(Date.UTC(year, month - 1, day)).toLocaleDateString(dateLocale(), {
		timeZone: 'UTC', weekday: 'long', day: 'numeric', month: 'long',
	})
	return label.charAt(0).toUpperCase() + label.slice(1)
}

// Path for generateUrl; unknown pages lead to the overview.
export function pagePath(page) {
	return PAGES.includes(page) ? `${EMBED_STEM}/${page}` : EMBED_STEM
}

export function currentPage() {
	return parsePath(window.location.pathname)
}

export function currentParams() {
	return pageParams(window.location.search)
}

// Switch within the app without reloading; App.vue listens to ROUTE_EVENT and popstate.
export function navigate(page, params = {}) {
	const query = new URLSearchParams(cleanParams(params ?? {})).toString()
	const url = generateUrl(pagePath(page)) + (query ? `?${query}` : '')
	window.history.pushState({}, '', url)
	window.dispatchEvent(new Event(ROUTE_EVENT))
}
