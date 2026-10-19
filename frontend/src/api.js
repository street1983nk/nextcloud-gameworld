// Zugriff auf die Welt-API der ExApp über den Nextcloud-Proxy.
//
// @nextcloud/axios setzt das requesttoken, damit Nextcloud den Aufruf gegen
// CSRF prüfen kann. Die Basis-URL kommt vom Backend (lifecycle.py, Initial
// State gameworld_config): unter manual-install der AppAPI-Proxy, unter HaRP
// /exapps/gameworld.
import axios from '@nextcloud/axios'
import { loadState } from '@nextcloud/initial-state'
import { generateUrl } from '@nextcloud/router'

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
