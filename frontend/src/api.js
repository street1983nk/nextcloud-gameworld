// Zugriff auf die Welt-API der ExApp über den Nextcloud-Proxy.
//
// @nextcloud/axios setzt das requesttoken; der AppAPI-Proxy prüft es aber nicht
// (NoCSRFRequired, IN-08). Gegen Cross-Site-Anfragen schützt darum die JSON-Pflicht
// der Änderungen (post, del unten). Die Basis-URL kommt vom Backend (lifecycle.py, Initial
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

// IN-08: Jede Änderung geht als JSON, auch ohne Inhalt. Das Backend lehnt
// zustandsändernde Anfragen ohne Content-Type application/json ab (403), damit
// ein Formular einer fremden Seite nichts auslösen kann; der AppAPI-Proxy prüft
// das requesttoken nicht.
const JSON_HEADERS = Object.freeze({ 'Content-Type': 'application/json' })

export function post(url, data = {}) {
	return axios.post(url, data, { headers: { ...JSON_HEADERS } })
}

export function del(url) {
	return axios.delete(url, { data: {}, headers: { ...JSON_HEADERS } })
}

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

// Browser-Spike 04.2: Ist "Im Browser spielen" eingeschaltet? Einmal je Seitenaufruf
// gefragt (alle Karten teilen das Ergebnis); bei Fehler gilt aus.
let playStatusPromise = null

export function getPlayStatus() {
	if (playStatusPromise === null) {
		playStatusPromise = axios.get(`${apiBase}/api/my/play-status`)
			.then((response) => response.data?.enabled === true)
			.catch(() => false)
	}
	return playStatusPromise
}

// Ein-Mal-Ticket (60 s) für die eigene, laufende Welt: { ticket, play_path }. Das
// Ticket wandert nur im URL-Fragment zur Spielseite, nie in Pfad oder Query.
export async function getPlayTicket(worldId) {
	const response = await post(`${apiBase}/api/my/play-ticket`, { world_id: worldId })
	return response.data
}

// Spieler-Adresse (nur Verwalter); leer heißt: Hostname des Browsers.
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

// Neustart läuft im Backend als Stoppen plus Starten (gleiche Port-Saga wie Start).
export async function restartWorld(id) {
	const response = await post(`${apiBase}/api/worlds/${id}/restart`)
	return response.data
}

export async function deleteWorld(id) {
	await del(`${apiBase}/api/worlds/${id}`)
}

// Sicherungen (Phase 5, nur Verwalter): Liste nur eigener, geprüfter Sicherungen
// ({ backups, total_size, other_files }); Löschen gibt es bewusst nicht (D-08).
export async function listBackups(worldId) {
	const response = await axios.get(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/backups`)
	return response.data
}

// 202 mit der Welt; 409 mit Text, wenn Kinder spielen und confirmDisconnect fehlt (D-09).
export async function startBackup(worldId, confirmDisconnect = false) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/backups`, {
		confirm_disconnect: Boolean(confirmDisconnect),
	})
	return response.data
}

// Nur die Datei-ID aus der eigenen Liste; confirm true ist die Sicherheitsabfrage (D-04).
export async function restoreBackup(worldId, fileId, confirmDisconnect = false) {
	const response = await post(`${apiBase}/api/worlds/${encodeURIComponent(worldId)}/restore`, {
		file_id: fileId,
		confirm: true,
		confirm_disconnect: Boolean(confirmDisconnect),
	})
	return response.data
}

// Einladungen und Spieler (03-03/03-04). Passwörter kommen abgeleitet aus der
// API und werden im Frontend nie gespeichert, nur angezeigt.
export async function listPlayers(worldId) {
	const response = await axios.get(`${apiBase}/api/worlds/${worldId}/players`)
	return response.data
}

// kind: 'user' oder 'group'; das Backend prüft Konto oder Gruppe erneut bei Nextcloud.
export async function invite(worldId, kind, target) {
	const response = await post(`${apiBase}/api/worlds/${worldId}/invites`, { kind, target })
	return response.data
}

export async function removeInvite(worldId, kind, target) {
	const response = await post(`${apiBase}/api/worlds/${worldId}/invites/remove`, { kind, target })
	return response.data
}

// Neues Passwort in allen Welten des Kontos; das alte gilt sofort nicht mehr.
export async function rotatePassword(ncUser) {
	const response = await post(`${apiBase}/api/players/password`, { nc_user: ncUser })
	return response.data
}

export async function renamePlayer(ncUser, playerName) {
	const response = await post(`${apiBase}/api/players/name`, { nc_user: ncUser, player_name: playerName })
	return response.data
}

// Spielzeit (04-03 bis 04-05): Kinder mit Regeln und Verbrauch, Ferien, Zeitzone.
export async function getPlaytime() {
	const response = await axios.get(`${apiBase}/api/playtime`)
	return response.data
}

// normal und holiday sind je 7 Tage im API-Format; holiday null heißt: Normalplan gilt auch in den Ferien.
export async function saveChildPlan(ncUser, normal, holiday) {
	const response = await post(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`, { normal, holiday })
	return response.data
}

// Keine Begrenzung: alle Regeln des Kindes entfernen.
export async function clearChildPlan(ncUser) {
	const response = await del(`${apiBase}/api/playtime/children/${encodeURIComponent(ncUser)}`)
	return response.data
}

// Ferienliste des Haushalts; Daten als JJJJ-MM-TT, Bezeichnung optional.
export async function addHoliday(label, startDate, endDate) {
	const response = await post(`${apiBase}/api/playtime/holidays`, { label, start_date: startDate, end_date: endDate })
	return response.data
}

export async function removeHoliday(id) {
	const response = await del(`${apiBase}/api/playtime/holidays/${encodeURIComponent(id)}`)
	return response.data
}

// IANA-Name, etwa Europe/Berlin; das Backend kennt nur Namen aus tzdata.
export async function setTimeZone(timeZone) {
	const response = await post(`${apiBase}/api/playtime/time-zone`, { time_zone: timeZone })
	return response.data
}

// days: genau 7 Tage { weekday, open, window_start, window_end }; "immer offen" ist clearWorldWindow.
export async function setWorldWindow(worldId, days) {
	const response = await post(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`, { days })
	return response.data
}

export async function clearWorldWindow(worldId) {
	const response = await del(`${apiBase}/api/playtime/worlds/${encodeURIComponent(worldId)}/window`)
	return response.data
}

// Pause aller Welten (04.1-03): Zustand mit until_clock (H:MM) und je Welt applied/restarted.
export async function getPause() {
	const response = await axios.get(`${apiBase}/api/pause`)
	return response.data
}

// minutes: genau 15, 30 oder 60 (das Backend lehnt alles andere ab).
export async function startPause(minutes) {
	const response = await post(`${apiBase}/api/pause`, { minutes })
	return response.data
}

// "Weiter": Pause oder "Für heute Schluss" sofort beenden.
export async function endPause() {
	const response = await post(`${apiBase}/api/pause/end`)
	return response.data
}

// "Für heute Schluss": bis zum Ende des Tages in der Haushalts-Zeitzone.
export async function stopForToday() {
	const response = await post(`${apiBase}/api/pause/schluss`)
	return response.data
}

// Fremdversuche eines Tages (JJJJ-MM-TT), optional nur einer Welt. Ohne day wählt
// das Backend den heutigen Tag der Haushalts-Zeitzone (IN-04); die Antwort nennt
// day und today ({ day, today, attempts }).
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

// Tagesrückblick: Minuten je Kind und Welt, limit_reached nur für heute; ohne day
// der heutige Tag der Haushalts-Zeitzone ({ day, today, kids }).
export async function getReview(day = null) {
	const response = await axios.get(`${apiBase}/api/review`, { params: day ? { day } : {} })
	return response.data
}

// Rückblick an/aus und Uhrzeit (Minute ab 00:00), je Verwalter.
export async function getReviewPrefs() {
	const response = await axios.get(`${apiBase}/api/review/prefs`)
	return response.data
}

export async function saveReviewPrefs(enabled, minute) {
	const response = await post(`${apiBase}/api/review/prefs`, { enabled, minute })
	return response.data
}

// Talk-Räume je Welt: available, bots und je Welt has_room, read_only, owner_not_admin.
export async function getTalkStatus() {
	const response = await axios.get(`${apiBase}/api/talk`)
	return response.data
}

// "Nur lesen" an ist POST, aus ist DELETE.
export async function setTalkReadOnly(worldId, on) {
	const url = `${apiBase}/api/worlds/${encodeURIComponent(worldId)}/talk/read-only`
	const response = on ? await post(url) : await del(url)
	return response.data
}

// Basis-URL für die Links in Benachrichtigungen: Origin des Browsers plus Webroot
// der Nextcloud (getRootUrl, etwa /nextcloud). Der Server speichert nur die erste
// Adresse; eine abweichende erst mit confirm (Antwort confirm_needed), und eine
// https-Adresse ersetzt er nie durch http.
export async function reportOrigin(origin, webroot, confirm = false) {
	const response = await post(`${apiBase}/api/origin`, { origin, webroot, confirm })
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
