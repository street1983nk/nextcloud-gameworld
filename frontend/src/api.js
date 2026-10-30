// Access to the world API of the ExApp through the Nextcloud proxy.
//
// @nextcloud/axios sets the requesttoken, but the AppAPI proxy does not check it
// (NoCSRFRequired, IN-08). The JSON requirement for changes (post, del below) is
// therefore what protects against cross-site requests. The base URL comes from the backend (lifecycle.py, initial
// state gameworld_config): the AppAPI proxy under manual-install, and
// /exapps/gameworld under HaRP.
import axios from '@nextcloud/axios'
import { loadState } from '@nextcloud/initial-state'
import { generateOcsUrl, generateUrl } from '@nextcloud/router'
import { currentLanguage, t } from './i18n/index.js'

const fallback = { apiBase: generateUrl('/apps/app_api/proxy/gameworld') }

// AppAPI provides the initial state in the name of the app app_api
// (TopMenuController::viewExAppPage, IInitialState of app_api) and stores
// the value as JSON text; in the document it is therefore double-encoded.
function readConfig() {
	const raw = loadState('app_api', 'gameworld_config', fallback)
	if (typeof raw !== 'string') {
		return raw
	}
	try {
		return JSON.parse(raw)
	} catch {
		return fallback
	}
}

export const apiBase = readConfig().apiBase ?? fallback.apiBase

// The UI language goes along with every request to the ExApp API, so that server
// texts match the UI even right after a language change (the backend caches the
// account language for 30 s). Requests to Nextcloud itself stay untouched.
export const UI_LANGUAGE_HEADER = 'X-Gameworld-Language'

axios.interceptors.request.use((config) => {
	if (typeof config.url === 'string' && config.url.startsWith(apiBase)) {
		config.headers.set(UI_LANGUAGE_HEADER, currentLanguage())
	}
	return config
})

// IN-08: every change goes out as JSON, even without content. The backend rejects
// state-changing requests without Content-Type application/json (403), so that
// a form on a foreign site cannot trigger anything; the AppAPI proxy does not check
// the requesttoken.
const JSON_HEADERS = Object.freeze({ 'Content-Type': 'application/json' })

export function post(url, data = {}) {
	return axios.post(url, data, { headers: { ...JSON_HEADERS } })
}

export function del(url) {
	return axios.delete(url, { data: {}, headers: { ...JSON_HEADERS } })
}

// Message from an API error response (detail as text or as a FastAPI validation
// list); a detail string from the backend is shown unchanged (the backend translates
// it itself), otherwise a general sentence in the UI language.
export function errorText(err) {
	const detail = err?.response?.data?.detail
	if (typeof detail === 'string' && detail !== '') {
		return detail
	}
	const msg = Array.isArray(detail) ? detail[0]?.msg : undefined
	if (typeof msg === 'string' && msg !== '') {
		return msg.replace(/^Value error, /, '')
	}
	return t('core.api.requestFailed')
}

// For all signed-in accounts: user, display name and role (verwalter or spieler).
export async function getMe() {
	const response = await axios.get(`${apiBase}/api/me`)
	return response.data
}

// Own worlds with connection data (for every account, own data only).
export async function listMyWorlds() {
	const response = await axios.get(`${apiBase}/api/my/worlds`)
	return response.data.worlds
}

// Own remaining time today (own values only; the UID comes from the AppAPI request).
export async function getMyPlaytime() {
	const response = await axios.get(`${apiBase}/api/my/playtime`)
	return response.data
}

// Browser spike 04.2: is "Im Browser spielen" switched on? Asked once per page load
// (all cards share the result); on error it counts as off.
let playStatusPromise = null

export function getPlayStatus() {
	if (playStatusPromise === null) {
		playStatusPromise = axios.get(`${apiBase}/api/my/play-status`)
			.then((response) => response.data?.enabled === true)
			.catch(() => false)
	}
	return playStatusPromise
}

// One-time ticket (60 s) for the own, running world: { ticket, play_path }. The
// ticket travels only in the URL fragment to the play page, never in path or query.
export async function getPlayTicket(worldId) {
	const response = await post(`${apiBase}/api/my/play-ticket`, { world_id: worldId })
	return response.data
}

// Player address (managers only); empty means: the browser's hostname.
export async function getSettings() {
	const response = await axios.get(`${apiBase}/api/settings`)
	return response.data
}

export async function saveSettings(joinHost) {
	const response = await post(`${apiBase}/api/settings`, { join_host: joinHost })
	return response.data
}

export async function getSetupCheck() {
	const response = await axios.get(`${apiBase}/api/setup-check`)
	return response.data
}

export async function listPresets() {
	const response = await axios.get(`${apiBase}/api/presets`)
	return response.data.presets
}

export async function listWorlds() {
	const response = await axios.get(`${apiBase}/api/worlds`)
	return response.data.worlds
}

export async function createWorld(name, preset) {
	const response = await post(`${apiBase}/api/worlds`, { name, preset })
	return response.data
}

export async function startWorld(id) {
	const response = await post(`${apiBase}/api/worlds/${id}/start`)
	return response.data
}

export async function stopWorld(id) {
	const response = await post(`${apiBase}/api/worlds/${id}/stop`)
	return response.data
}

// Restart runs in the backend as stop plus start (same port saga as start).
export async function restartWorld(id) {
	const response = await post(`${apiBase}/api/worlds/${id}/restart`)
	return response.data
}

export async function deleteWorld(id) {
	await del(`${apiBase}/api/worlds/${id}`)
}

// Backups (phase 5, managers only): list of own, verified backups only
// ({ backups, total_size, other_files }); deleting is deliberately absent (D-08).
export async function listBackups(worldId) {
	const response = await axios.get(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/backups`)
	return response.data
}

// 202 with the world; 409 with text when children are playing and confirmDisconnect is missing (D-09).
export async function startBackup(worldId, confirmDisconnect = false) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/backups`, {
		confirm_disconnect: Boolean(confirmDisconnect),
	})
	return response.data
}

// Only the file ID from the own list; confirm true is the safety prompt (D-04).
export async function restoreBackup(worldId, fileId, confirmDisconnect = false) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/restore`, {
		file_id: fileId,
		confirm: true,
		confirm_disconnect: Boolean(confirmDisconnect),
	})
	return response.data
}

// Invitations and players (03-03/03-04). Passwords arrive derived from the
// API and are never stored in the frontend, only displayed.
export async function listPlayers(worldId) {
	const response = await axios.get(`${apiBase}/api/worlds/${worldId}/players`)
	return response.data
}

// kind: 'user' or 'group'; the backend checks the account or group again with Nextcloud.
export async function invite(worldId, kind, target) {
	const response = await post(`${apiBase}/api/worlds/${worldId}/invites`, { kind, target })
	return response.data
}

export async function removeInvite(worldId, kind, target) {
	const response = await post(`${apiBase}/api/worlds/${worldId}/invites/remove`, { kind, target })
	return response.data
}

// New password in all worlds of the account; the old one stops working immediately.
export async function rotatePassword(ncUser) {
	const response = await post(`${apiBase}/api/players/password`, { nc_user: ncUser })
	return response.data
}

// ROLLE-04: mark an account as adult or remove the mark; applies in all worlds.
export async function setAdult(ncUser, adult) {
	const response = await post(`${apiBase}/api/players/adult`, { nc_user: ncUser, adult })
	return response.data
}

export async function renamePlayer(ncUser, playerName) {
	const response = await post(`${apiBase}/api/players/name`, { nc_user: ncUser, player_name: playerName })
	return response.data
}

// Playtime (04-03 to 04-05): children with rules and usage, holidays, time zone.
export async function getPlaytime() {
	const response = await axios.get(`${apiBase}/api/playtime`)
	return response.data
}

// normal and holiday are 7 days each in the API format; holiday null means: the normal plan also applies during the holidays.
export async function saveChildPlan(ncUser, normal, holiday) {
	const response = await post(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`, { normal, holiday })
	return response.data
}

// No limit: remove all rules of the child.
export async function clearChildPlan(ncUser) {
	const response = await del(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`)
	return response.data
}

// Holiday list of the household; dates as YYYY-MM-DD, label optional.
export async function addHoliday(label, startDate, endDate) {
	const response = await post(`${apiBase}/api/playtime/holidays`, { label, start_date: startDate, end_date: endDate })
	return response.data
}

export async function removeHoliday(id) {
	const response = await del(`${apiBase}/api/playtime/holidays/${encodeURIComponent(id)}`)
	return response.data
}

// IANA name, e.g. Europe/Berlin; the backend only knows names from tzdata.
export async function setTimeZone(timeZone) {
	const response = await post(`${apiBase}/api/playtime/time-zone`, { time_zone: timeZone })
	return response.data
}

// days: exactly 7 days { weekday, open, window_start, window_end }; "always open" is clearWorldWindow.
export async function setWorldWindow(worldId, days) {
	const response = await post(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`, { days })
	return response.data
}

export async function clearWorldWindow(worldId) {
	const response = await del(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`)
	return response.data
}

// Pause of all worlds (04.1-03): state with until_clock (H:MM) and applied/restarted per world.
export async function getPause() {
	const response = await axios.get(`${apiBase}/api/pause`)
	return response.data
}

// minutes: exactly 15, 30 or 60 (the backend rejects anything else).
export async function startPause(minutes) {
	const response = await post(`${apiBase}/api/pause`, { minutes })
	return response.data
}

// "Weiter": end a pause or "Für heute Schluss" immediately.
export async function endPause() {
	const response = await post(`${apiBase}/api/pause/end`)
	return response.data
}

// "Für heute Schluss": until the end of the day in the household time zone.
export async function stopForToday() {
	const response = await post(`${apiBase}/api/pause/schluss`)
	return response.data
}

// Foreign attempts of one day (YYYY-MM-DD), optionally for one world only. Without day
// the backend picks today in the household time zone (IN-04); the response names
// day and today ({ day, today, attempts }).
export async function listAttempts(day = null, worldId = null) {
	const params = {}
	if (day) {
		params.day = day
	}
	if (worldId) {
		params.world = worldId
	}
	const response = await axios.get(`${apiBase}/api/attempts`, { params })
	return response.data
}

// Daily review: minutes per child and world, limit_reached only for today; without day
// today in the household time zone ({ day, today, kids }).
export async function getReview(day = null) {
	const response = await axios.get(`${apiBase}/api/review`, { params: day ? { day } : {} })
	return response.data
}

// Review on/off and time of day (minute from 00:00), per manager.
export async function getReviewPrefs() {
	const response = await axios.get(`${apiBase}/api/review/prefs`)
	return response.data
}

export async function saveReviewPrefs(enabled, minute) {
	const response = await post(`${apiBase}/api/review/prefs`, { enabled, minute })
	return response.data
}

// Talk rooms per world: available, bots and per world has_room, read_only, owner_not_admin.
export async function getTalkStatus() {
	const response = await axios.get(`${apiBase}/api/talk`)
	return response.data
}

// "Nur lesen" on is POST, off is DELETE.
export async function setTalkReadOnly(worldId, on) {
	const url = `${apiBase}/api/worlds/${encodeURIComponent(worldId)}/talk/read-only`
	const response = on ? await post(url) : await del(url)
	return response.data
}

// Game language of a world (D-27), only for managers; the answer is the WorldOut row.
export async function setWorldLanguage(worldId, language) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/language`, { language })
	return response.data
}

// Recreate the Talk room (D-19): old room including history is gone, the response is the new row from GET /api/talk.
export async function recreateTalkRoom(worldId) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/talk/recreate`)
	return response.data
}

// Manager groups (06-02, NC admins only, otherwise 403): list without admin, which the UI
// always prepends; adding and removing respond with the new list ({ groups }).
export async function getVerwalterGroups() {
	const response = await axios.get(`${apiBase}/api/admin/verwalter-groups`)
	return response.data.groups
}

export async function addVerwalterGroup(gid) {
	const response = await post(`${apiBase}/api/admin/verwalter-groups/add`, { gid })
	return response.data.groups
}

export async function removeVerwalterGroup(gid) {
	const response = await post(`${apiBase}/api/admin/verwalter-groups/remove`, { gid })
	return response.data.groups
}

// Leftovers of earlier installations (06-08, NC admins only, otherwise 403): all three routes
// respond with { containers, volumes }; 409 own/foreign or used objects, 503 Docker disturbed.
export async function listOrphans() {
	const response = await axios.get(`${apiBase}/api/admin/orphans`)
	return response.data
}

export async function removeOrphanContainer(id) {
	const response = await post(`${apiBase}/api/admin/orphans/container/remove`, { id })
	return response.data
}

export async function removeOrphanVolume(name) {
	const response = await post(`${apiBase}/api/admin/orphans/volume/remove`, { name })
	return response.data
}

// Group search through Nextcloud ([{ id, display_name }]); 503 means: search disturbed.
export async function searchGroups(query) {
	const response = await axios.get(`${apiBase}/api/admin/groups`, { params: { search: query } })
	return response.data.groups
}

// Base URL for the links in notifications: the browser's origin plus the web root
// of Nextcloud (getRootUrl, e.g. /nextcloud). The server stores only the first
// address; a different one only with confirm (response confirm_needed), and it
// never replaces an https address with http.
export async function reportOrigin(origin, webroot, confirm = false) {
	const response = await post(`${apiBase}/api/origin`, { origin, webroot, confirm })
	return response.data
}

// Search through Nextcloud's own autocomplete (users 0, groups 1),
// with Nextcloud's rules on who may find whom. No user list of our own.
export async function searchAccounts(term) {
	const response = await axios.get(generateOcsUrl('core/autocomplete/get'), {
		params: {
			search: term,
			itemType: '',
			itemId: '',
			shareTypes: [0, 1],
			limit: 20,
			format: 'json',
		},
		headers: { 'OCS-APIRequest': 'true' },
	})
	const entries = response.data?.ocs?.data ?? []
	return entries
		.filter((entry) => entry.source === 'users' || entry.source === 'groups')
		.map((entry) => ({
			kind: entry.source === 'groups' ? 'group' : 'user',
			id: String(entry.id),
			label: String(entry.label ?? entry.id),
		}))
}
