// Shared helpers of the audit scripts: accounts, occ, login, API calls from the
// logged-in page, safety guards against touching foreign worlds.
import { readFileSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { pathToFileURL } from 'node:url'
import { execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'

const require = createRequire(join(process.env.NODE_PATH ?? '.', 'x.js'))
export const { chromium } = require('playwright')

export const BASE = `http://localhost:${process.env.GAMEWORLD_NC_PORT ?? '8091'}`
export const APP_PATH = '/index.php/apps/app_api/embedded/gameworld/gameworld'
export const APP = BASE + APP_PATH
export const PROXY = '/index.php/apps/app_api/proxy/gameworld'
export const LANGS = (process.env.LANGS ?? 'de,en,fr').split(',')
// Dev-instance accounts (same passwords as the earlier dev audit script).
export const ACCOUNTS = { admin: 'gameworld-dev-admin', 'gw-lehrer': 'gw-lehrer-abnahme-13', mia: 'gameworld-demo-mia-13' }
export const PREFIX = 'audit261102-'
// Container/volume name prefixes of existing worlds that must never be touched.
export const PROTECTED_PREFIXES = ['gameworld-788fff30-', 'gameworld-a60510fd-']

export function occ(repo, ...args) {
	return execFileSync('docker', ['compose', '-p', 'gameworld-dev', '-f', join(repo, 'scripts/dev/compose.yaml'), 'exec', '-T', '-u', 'www-data', 'app', 'php', 'occ', ...args], { encoding: 'utf8' })
}

/** core lang of an account or null if unset. */
export function getLang(repo, user) {
	try {
		return occ(repo, 'user:setting', user, 'core', 'lang').trim() || null
	} catch {
		return null
	}
}

export function setLang(repo, user, lang) {
	if (lang === null) {
		try { occ(repo, 'user:setting', user, 'core', 'lang', '--delete') } catch { /* already unset */ }
	} else {
		occ(repo, 'user:setting', user, 'core', 'lang', lang)
	}
}

/** Language settings recorded in baseline.txt ("<user>: rc=0 [de]" or rc=1 = unset). */
export function baselineLangs(out) {
	const text = readFileSync(join(out, 'baseline.txt'), 'utf8')
	const result = {}
	for (const user of Object.keys(ACCOUNTS)) {
		const m = text.match(new RegExp(`^${user}: rc=(\\d+) \\[([^\\]]*)\\]`, 'm'))
		if (!m) throw new Error(`baseline.txt has no lang line for ${user}`)
		result[user] = m[1] === '0' ? m[2].trim() : null
	}
	return result
}

/** World IDs that existed before the audit (baseline-worlds.json); never stopped or deleted. */
export function baselineWorldIds(out) {
	const file = join(out, 'baseline-worlds.json')
	if (!existsSync(file)) return new Set()
	return new Set(JSON.parse(readFileSync(file, 'utf8')).map((w) => w.id))
}

export function assertThrowaway(world, baselineIds) {
	if (!world || !world.id) throw new Error('guard: no world')
	if (baselineIds.has(world.id)) throw new Error(`guard: ${world.id} is a baseline world`)
	if (!String(world.name).startsWith(PREFIX)) throw new Error(`guard: ${world.id} name ${world.name} lacks ${PREFIX}`)
}

/** Frontend dictionary of a language (flat key -> text). */
export async function dictionary(repo, lang) {
	const url = pathToFileURL(join(resolve(repo), 'frontend', 'src', 'i18n', lang, 'index.js'))
	return (await import(url.href)).default
}

export async function login(page, user) {
	await page.context().clearCookies()
	await page.goto(`${BASE}/login?redirect_url=${encodeURIComponent(APP_PATH)}`)
	await page.fill('#user', user)
	await page.fill('#password', ACCOUNTS[user])
	await page.click('button[type=submit]')
	await page.waitForURL(/gameworld/, { timeout: 30000 })
	await waitApp(page, user)
}

/** Waits until the main view is loaded (world table or kid cards, playtime list for managers). */
export async function waitApp(page, user, timeout = 60000) {
	await page.waitForFunction(() => {
		const main = document.querySelector('main')
		if (!main) return false
		if (main.querySelector('.gameworld__list, .gameworld__empty')) return true
		return !main.querySelector('.loading-icon') && main.innerText.length > 200
	}, null, { timeout })
	if (user !== 'mia') await page.waitForSelector('.playtime__list, .playtime__empty', { timeout }).catch(() => {})
	await page.waitForTimeout(1500)
}

/** API call from the logged-in page; returns { status, body, detail, ms }. */
// Changing requests always go out as JSON like the frontend (CSRF rule of the app);
// opts.raw sends them without Content-Type to provoke the refusal on purpose.
export async function api(page, lang, method, path, body, opts = {}) {
	return page.evaluate(async ({ lang, method, path, body, proxy, raw }) => {
		const headers = { requesttoken: OC.requestToken }
		if (lang) headers['X-Gameworld-Language'] = lang
		let payload
		if (method !== 'GET') {
			payload = JSON.stringify(body ?? {})
			if (!raw) headers['Content-Type'] = 'application/json'
		}
		const t0 = performance.now()
		const r = await fetch(proxy + path, { method, headers, body: payload })
		const ms = Math.round(performance.now() - t0)
		let json = null
		try { json = await r.json() } catch { json = null }
		let detail = ''
		if (json && typeof json.detail === 'string') detail = json.detail
		else if (json && Array.isArray(json.detail)) detail = json.detail.map((e) => e.msg).join(' / ')
		return { status: r.status, body: json, detail, ms }
	}, { lang, method, path, body, proxy: PROXY, raw: Boolean(opts.raw) })
}

/** WebDAV request of the logged-in account (only used for audit folders). */
export async function dav(page, method, path, headers = {}) {
	return page.evaluate(async ({ method, path, headers }) => {
		const r = await fetch('/remote.php/dav/files/' + encodeURIComponent(OC.currentUser) + path, { method, headers: { requesttoken: OC.requestToken, ...headers } })
		return { status: r.status, text: await r.text() }
	}, { method, path, headers })
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
