// Zugriff auf die Welt-API der ExApp über den Nextcloud-Proxy.
//
// @nextcloud/axios setzt das requesttoken, damit Nextcloud den Aufruf gegen
// CSRF prüfen kann. Die Basis-URL kommt vom Backend (lifecycle.py, Initial
// State gameworld_config): unter manual-install der AppAPI-Proxy, unter HaRP
// /exapps/gameworld.
import axios from '@nextcloud/axios'
import { loadState } from '@nextcloud/initial-state'
import { generateOcsUrl, generateUrl } from '@nextcloud/router'

const fallback = { apiBase: generateUrl('/apps/app_api/proxy/gameworld') }

// AppAPI stellt den Initial State im Namen der App app_api bereit
// (TopMenuController::viewExAppPage, IInitialState von app_api) und speichert
// den Wert als JSON-Text; im Dokument steht er darum doppelt kodiert.
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

// Deutsche Meldung aus einer Fehlerantwort der API (detail als Text oder als
// FastAPI-Validierungsliste), sonst ein allgemeiner Satz.
export function errorText(err) {
	const detail = err?.response?.data?.detail
	if (typeof detail === 'string' && detail !== '') {
		return detail
	}
	const msg = Array.isArray(detail) ? detail[0]?.msg : undefined
	if (typeof msg === 'string' && msg !== '') {
		return msg.replace(/^Value error, /, '')
	}
	return 'Die Anfrage an Gameworld ist fehlgeschlagen.'
}

// Für alle angemeldeten Konten: Nutzer, Anzeigename und Rolle (verwalter oder spieler).
export async function getMe() {
	const response = await axios.get(`${apiBase}/api/me`)
	return response.data
}

// Eigene Welten mit Verbindungsdaten (für jedes Konto, nur eigene Daten).
export async function listMyWorlds() {
	const response = await axios.get(`${apiBase}/api/my/worlds`)
	return response.data.worlds
}

// Eigene Restzeit heute (nur eigene Werte; die UID kommt aus der AppAPI-Anfrage).
export async function getMyPlaytime() {
	const response = await axios.get(`${apiBase}/api/my/playtime`)
	return response.data
}

// Spieler-Adresse (nur Verwalter); leer heißt: Hostname des Browsers.
export async function getSettings() {
	const response = await axios.get(`${apiBase}/api/settings`)
	return response.data
}

export async function saveSettings(joinHost) {
	const response = await axios.post(`${apiBase}/api/settings`, { join_host: joinHost })
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
	const response = await axios.post(`${apiBase}/api/worlds`, { name, preset })
	return response.data
}

export async function startWorld(id) {
	const response = await axios.post(`${apiBase}/api/worlds/${id}/start`)
	return response.data
}

export async function stopWorld(id) {
	const response = await axios.post(`${apiBase}/api/worlds/${id}/stop`)
	return response.data
}

// Neustart läuft im Backend als Stoppen plus Starten (gleiche Port-Saga wie Start).
export async function restartWorld(id) {
	const response = await axios.post(`${apiBase}/api/worlds/${id}/restart`)
	return response.data
}

export async function deleteWorld(id) {
	await axios.delete(`${apiBase}/api/worlds/${id}`)
}

// Einladungen und Spieler (03-03/03-04). Passwörter kommen abgeleitet aus der
// API und werden im Frontend nie gespeichert, nur angezeigt.
export async function listPlayers(worldId) {
	const response = await axios.get(`${apiBase}/api/worlds/${worldId}/players`)
	return response.data
}

// kind: 'user' oder 'group'; das Backend prüft Konto oder Gruppe erneut bei Nextcloud.
export async function invite(worldId, kind, target) {
	const response = await axios.post(`${apiBase}/api/worlds/${worldId}/invites`, { kind, target })
	return response.data
}

export async function removeInvite(worldId, kind, target) {
	const response = await axios.post(`${apiBase}/api/worlds/${worldId}/invites/remove`, { kind, target })
	return response.data
}

// Neues Passwort in allen Welten des Kontos; das alte gilt sofort nicht mehr.
export async function rotatePassword(ncUser) {
	const response = await axios.post(`${apiBase}/api/players/password`, { nc_user: ncUser })
	return response.data
}

export async function renamePlayer(ncUser, playerName) {
	const response = await axios.post(`${apiBase}/api/players/name`, { nc_user: ncUser, player_name: playerName })
	return response.data
}

// Spielzeit (04-03 bis 04-05): Kinder mit Regeln und Verbrauch, Ferien, Zeitzone.
export async function getPlaytime() {
	const response = await axios.get(`${apiBase}/api/playtime`)
	return response.data
}

// normal und holiday sind je 7 Tage im API-Format; holiday null heißt: Normalplan gilt auch in den Ferien.
export async function saveChildPlan(ncUser, normal, holiday) {
	const response = await axios.post(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`, { normal, holiday })
	return response.data
}

// Keine Begrenzung: alle Regeln des Kindes entfernen.
export async function clearChildPlan(ncUser) {
	const response = await axios.delete(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`)
	return response.data
}

// Ferienliste des Haushalts; Daten als JJJJ-MM-TT, Bezeichnung optional.
export async function addHoliday(label, startDate, endDate) {
	const response = await axios.post(`${apiBase}/api/playtime/holidays`, { label, start_date: startDate, end_date: endDate })
	return response.data
}

export async function removeHoliday(id) {
	const response = await axios.delete(`${apiBase}/api/playtime/holidays/${encodeURIComponent(id)}`)
	return response.data
}

// IANA-Name, etwa Europe/Berlin; das Backend kennt nur Namen aus tzdata.
export async function setTimeZone(timeZone) {
	const response = await axios.post(`${apiBase}/api/playtime/time-zone`, { time_zone: timeZone })
	return response.data
}

// days: genau 7 Tage { weekday, open, window_start, window_end }; "immer offen" ist clearWorldWindow.
export async function setWorldWindow(worldId, days) {
	const response = await axios.post(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`, { days })
	return response.data
}

export async function clearWorldWindow(worldId) {
	const response = await axios.delete(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`)
	return response.data
}

// Suche über Nextclouds eigene Autovervollständigung (Benutzer 0, Gruppen 1),
// mit Nextclouds Regeln, wer wen finden darf. Keine eigene Benutzerliste.
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
