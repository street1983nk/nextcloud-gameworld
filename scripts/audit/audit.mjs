// Language and layout audit: every main view, every dialog of a world row (also
// the destructive confirmation dialogs, opened and cancelled only), the dialogs
// inside the player manager (new password, rename, adult), playtime, holiday,
// talk and orphan dialogs, per account (admin, gw-lehrer, mia), language (de, en,
// fr) and viewport (1280x900 and 390x844). Every collected text goes through the
// foreign-word detector; every view gets a screenshot and a machine check for
// horizontal scrolling and clipped texts.
//
// The world row dialogs run on a throw-away world (name prefix audit261102-) that
// the NC admin creates via the API and deletes at the end. Account languages are
// restored to the values recorded in <out>/baseline.txt.
//
// Usage: NODE_PATH=... node scripts/audit/audit.mjs <repo> <outdir>
import { writeFileSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { loadVocab, foreign } from './lang_detector.mjs'
import { layoutProbe } from './layout_probe.mjs'
import {
	chromium, APP, LANGS, ACCOUNTS, PREFIX, login, waitApp, api, dictionary, setLang, getLang,
	baselineLangs, baselineWorldIds, assertThrowaway, sleep,
} from './common.mjs'

const [REPO = '.', OUT = '.dev/audit/261102'] = process.argv.slice(2)
const SHOTS = join(OUT, 'shots')
const TEXTS = join(OUT, 'texts')
mkdirSync(SHOTS, { recursive: true })
mkdirSync(TEXTS, { recursive: true })
const SERVER_JSON = process.env.SERVER_JSON ?? join(OUT, '..', 'server.json')
await loadVocab(REPO, SERVER_JSON, LANGS)
const VIEWPORTS = { 1280: { width: 1280, height: 900 }, 390: { width: 390, height: 844 } }
const ONLY_USERS = process.env.USERS ? process.env.USERS.split(',') : Object.keys(ACCOUNTS)

const langsBefore = baselineLangs(OUT)
const report = []
const layout = []
const browser = await chromium.launch()

function slug(s) { return String(s).replace(/[^a-z0-9]+/gi, '_').replace(/^_|_$/g, '').slice(0, 60) }

function record(lang, user, width, where, text, extra = {}) {
	const hits = foreign(text, lang)
	report.push({ lang, user, width, where, hits, chars: text.length, ...extra })
	writeFileSync(join(TEXTS, `${lang}-${user}-${slug(where)}-${width}.txt`), text)
}

// Horizontal scrolling of the page or of a scroll container, and clipped texts.
async function checkLayout(page, lang, user, width, where) {
	const result = await page.evaluate(layoutProbe)
	layout.push({ lang, user, width, where, ...result })
	const file = join(SHOTS, `${lang}-${user}-${slug(where)}-${width}.png`)
	await page.screenshot({ path: file, fullPage: true }).catch(() => page.screenshot({ path: file }))
	return result
}

const mainText = (page) => page.evaluate(() => document.querySelector('main')?.innerText ?? '')
const dialogText = (page) => page.evaluate(() => [...document.querySelectorAll('[role=dialog]')].map((d) => d.innerText).join('\n'))

// Escape first (keyboard path); if a dialog stays open, its close button, then a reload.
// Returns whether Escape alone closed everything (recorded as escapeClosed).
const escapeLog = []
async function closeDialogs(page, where = '') {
	if (!(await page.locator('[role=dialog]').count())) return true
	for (let i = 0; i < 3; i++) {
		await page.keyboard.press('Escape')
		await page.waitForTimeout(500)
		if (!(await page.locator('[role=dialog]').count())) { escapeLog.push({ where, escapeClosed: true }); return true }
	}
	escapeLog.push({ where, escapeClosed: false })
	for (let i = 0; i < 3; i++) {
		const close = page.locator('[role=dialog] .modal-container__close').first()
		if (!(await close.count())) break
		await close.click({ timeout: 3000 }).catch(() => {})
		await page.waitForTimeout(600)
		if (!(await page.locator('[role=dialog]').count())) return false
	}
	await page.reload()
	await page.waitForTimeout(4000)
	return false
}

async function capture(page, lang, user, width, where, getText = dialogText) {
	try {
		const text = await getText(page)
		record(lang, user, width, where, text)
		await checkLayout(page, lang, user, width, where)
	} catch (err) {
		report.push({ lang, user, width, where, hits: {}, error: String(err).split('\n')[0].slice(0, 200) })
	}
}

async function tryStep(lang, user, width, where, fn) {
	try {
		await fn()
	} catch (err) {
		report.push({ lang, user, width, where, hits: {}, error: String(err).split('\n')[0].slice(0, 200) })
	}
}

// --- throw-away world (created by gw-lehrer, also visible to the NC admin) -----------
let world = null
let holidayId = null
const baselineIds = baselineWorldIds(OUT)

async function setupWorld() {
	const ctx = await browser.newContext({ viewport: VIEWPORTS[1280] })
	const page = await ctx.newPage()
	await login(page, 'admin')
	const listing = await api(page, 'de', 'GET', '/api/worlds')
	if (!baselineIds.size) {
		const worlds = listing.body.worlds.map((w) => ({ id: w.id, name: w.name, status: w.status, desired_state: w.desired_state }))
		writeFileSync(join(OUT, 'baseline-worlds.json'), JSON.stringify(worlds, null, 1))
		for (const w of worlds) baselineIds.add(w.id)
	}
	// Created by the NC admin: a group manager like gw-lehrer may only invite members of
	// their own groups (mia is not), and mia is needed for the player dialogs.
	const created = await api(page, 'de', 'POST', '/api/worlds', { name: PREFIX + 'ui' })
	if (created.status !== 201) throw new Error(`create throw-away world: ${created.status} ${created.detail}`)
	world = created.body
	assertThrowaway(world, baselineIds)
	for (let i = 0; i < 60; i++) {
		const w = (await api(page, 'de', 'GET', '/api/worlds')).body.worlds.find((x) => x.id === world.id)
		if (w && w.op_state !== 'creating') break
		await sleep(2000)
	}
	// mia as a player so that the player dialogs (password, rename, adult) exist.
	const inv = await api(page, 'de', 'POST', `/api/worlds/${world.id}/invites`, { kind: 'user', target: 'mia' })
	report.push({ lang: 'de', user: 'admin', width: 0, where: 'setup invite mia', hits: {}, status: inv.status, note: `status ${inv.status} ${inv.detail}` })
	// HOLIDAY=1: a future holiday (no effect today) so that the holiday remove dialog exists.
	if (process.env.HOLIDAY === '1') {
		const h = await api(page, 'de', 'POST', '/api/playtime/holidays', { label: 'audit261102', start_date: '2027-07-01', end_date: '2027-07-02' })
		holidayId = h.body?.id ?? null
		report.push({ lang: 'de', user: 'admin', width: 0, where: 'setup holiday', hits: {}, status: h.status, note: `status ${h.status} id ${holidayId}` })
	}
	await ctx.close()
}

async function teardownWorld() {
	if (!world) return
	const ctx = await browser.newContext({ viewport: VIEWPORTS[1280] })
	const page = await ctx.newPage()
	await login(page, 'admin')
	if (holidayId !== null) {
		const h = await api(page, 'de', 'DELETE', `/api/playtime/holidays/${holidayId}`)
		report.push({ lang: 'de', user: 'admin', width: 0, where: 'teardown holiday', hits: {}, status: h.status, note: `status ${h.status}` })
	}
	await api(page, 'de', 'POST', `/api/worlds/${world.id}/invites/remove`, { kind: 'user', target: 'mia' })
	assertThrowaway(world, baselineIds)
	const del = await api(page, 'de', 'DELETE', `/api/worlds/${world.id}`)
	report.push({ lang: 'de', user: 'admin', width: 0, where: 'teardown delete', hits: {}, status: del.status, note: `status ${del.status} ${del.detail}` })
	if (del.status !== 204) throw new Error(`teardown delete failed: ${del.status} ${del.detail}`)
	await ctx.close()
}

// --- per account --------------------------------------------------------------------
async function auditManager(page, lang, user, width, t) {
	const row = () => page.locator(`tr[data-world-id="${world.id}"]`)
	const rowButton = (key) => row().getByRole('button', { name: t[key], exact: true })
	const reopen = async () => { await page.goto(APP); await waitApp(page, user) }

	// Row dialogs. Start/stop/restart are direct actions without dialog: never clicked.
	for (const key of ['parent.common.invite', 'parent.view.action.players', 'parent.view.action.timeWindow', 'parent.view.action.backups', 'parent.view.action.delete']) {
		await tryStep(lang, user, width, `dialog ${key}`, async () => {
			await closeDialogs(page, `${lang} ${user} ${width}`)
			await rowButton(key).click({ timeout: 8000 })
			await page.locator('[role=dialog]').first().waitFor({ timeout: 8000 })
			await page.waitForTimeout(1000)
			// Dialogs load their data after opening (players, backups): wait for the spinner to go.
			await page.waitForFunction(() => ![...document.querySelectorAll('[role=dialog] .loading-icon')].length, null, { timeout: 15000 }).catch(() => {})
			await page.waitForTimeout(1000)
			await capture(page, lang, user, width, `dialog ${key}`)
			if (key === 'parent.view.action.players') {
				const dlg = page.locator('[role=dialog]').first()
				// New password: warning with cancel, never confirmed.
				await tryStep(lang, user, width, 'dialog players newPassword', async () => {
					await dlg.getByRole('button', { name: t['parent.players.newPassword'], exact: true }).first().click({ timeout: 5000 })
					await page.waitForTimeout(800)
					await capture(page, lang, user, width, 'dialog players newPassword')
					await dlg.locator('.players__confirm').getByRole('button', { name: t['parent.common.cancel'], exact: true }).first().click({ timeout: 5000 })
				})
				await tryStep(lang, user, width, 'dialog players rename', async () => {
					await dlg.getByRole('button', { name: t['parent.players.rename'], exact: true }).first().click({ timeout: 5000 })
					await page.waitForTimeout(800)
					await capture(page, lang, user, width, 'dialog players rename')
					await dlg.locator('.players__rename .players__confirm').getByRole('button', { name: t['parent.common.cancel'], exact: true }).first().click({ timeout: 5000 })
				})
				// Adult switch: opens the confirmation only when switching on; cancelled.
				await tryStep(lang, user, width, 'dialog players adult', async () => {
					const sw = dlg.locator('.players__adult input').first()
					if (await sw.isChecked()) { report.push({ lang, user, width, where: 'dialog players adult', hits: {}, note: 'already adult, confirmation not opened' }); return }
					await dlg.locator('.players__adult').first().getByText(t['parent.players.adult'], { exact: true }).click({ timeout: 5000 })
					await page.getByRole('dialog', { name: t['parent.common.markAdult'] }).waitFor({ timeout: 5000 })
					await page.waitForTimeout(800)
					await capture(page, lang, user, width, 'dialog players adult confirm')
					await page.getByRole('dialog', { name: t['parent.common.markAdult'] }).getByRole('button', { name: t['parent.common.cancel'], exact: true }).click({ timeout: 5000 })
					await page.waitForTimeout(800)
				})
			}
			await closeDialogs(page, `${lang} ${user} ${width} ${key}`)
		})
	}
	// Talk recreate dialog, only offered in some room states.
	await tryStep(lang, user, width, 'dialog talk recreate', async () => {
		const btn = row().getByRole('button', { name: t['admin.talk.recreate'], exact: true })
		if (!(await btn.count())) { report.push({ lang, user, width, where: 'dialog talk recreate', hits: {}, note: 'not offered for this room state' }); return }
		await btn.first().click({ timeout: 5000 })
		await page.waitForTimeout(1500)
		await capture(page, lang, user, width, 'dialog talk recreate')
		await closeDialogs(page, `${lang} ${user} ${width}`)
	})
	// Playtime edit dialog of every child.
	await reopen()
	const edit = page.locator('main .playtime').getByRole('button', { name: t['kids.playtimeSection.edit'], exact: true })
	const edits = await edit.count()
	for (let i = 0; i < edits; i++) {
		await tryStep(lang, user, width, `dialog playtime ${i}`, async () => {
			await closeDialogs(page, `${lang} ${user} ${width}`)
			await edit.nth(i).click({ timeout: 5000 })
			await page.waitForTimeout(1500)
			await capture(page, lang, user, width, `dialog playtime ${i}`)
			await closeDialogs(page, `${lang} ${user} ${width}`)
		})
	}
	// Holiday remove dialog (only if holidays exist), cancelled.
	await tryStep(lang, user, width, 'dialog holiday remove', async () => {
		// The button carries an aria-label ("<label> entfernen"), so match its visible text.
		const btn = page.locator('main .holidays button', { hasText: t['kids.holidays.remove'] })
		if (!(await btn.count())) { report.push({ lang, user, width, where: 'dialog holiday remove', hits: {}, note: 'no holiday entered' }); return }
		await btn.first().click({ timeout: 5000 })
		await page.waitForTimeout(1200)
		await capture(page, lang, user, width, 'dialog holiday remove')
		await closeDialogs(page, `${lang} ${user} ${width}`)
	})
	// Orphan dialog (NC admin only), cancelled with Escape, never confirmed.
	if (user === 'admin') {
		await tryStep(lang, user, width, 'dialog orphan', async () => {
			const btn = page.locator('main .orphans').getByRole('button', { name: new RegExp(`^(${t['admin.orphans.remove']}|${t['admin.orphans.delete']})$`) })
			if (!(await btn.count())) { report.push({ lang, user, width, where: 'dialog orphan', hits: {}, note: 'no orphans listed' }); return }
			await btn.first().click({ timeout: 5000 })
			await page.waitForTimeout(1200)
			await capture(page, lang, user, width, 'dialog orphan')
			await closeDialogs(page, `${lang} ${user} ${width}`)
		})
	}
	// Phone pages behind the notifications.
	for (const sub of ['pause', 'versuch', 'rueckblick']) {
		await tryStep(lang, user, width, `page ${sub}`, async () => {
			await page.goto(`${APP}/${sub}`)
			await page.waitForTimeout(4000)
			await capture(page, lang, user, width, `page ${sub}`, mainText)
		})
	}
	await reopen()
}

async function auditKid(page, lang, user, width, t) {
	// Show the password (local toggle only), then capture again.
	await tryStep(lang, user, width, 'kid password shown', async () => {
		const btn = page.locator('main').getByRole('button', { name: t['kids.connection.show'], exact: true })
		if (!(await btn.count())) return
		await btn.first().click({ timeout: 5000 })
		await page.waitForTimeout(800)
		await capture(page, lang, user, width, 'main password shown', mainText)
	})
}

try {
	await setupWorld()
	for (const lang of LANGS) {
		const t = await dictionary(REPO, lang)
		for (const user of Object.keys(ACCOUNTS)) setLang(REPO, user, lang)
		for (const user of ONLY_USERS) {
			const context = await browser.newContext({ viewport: VIEWPORTS[1280], locale: { de: 'de-DE', en: 'en-US', fr: 'fr-FR' }[lang] })
			const page = await context.newPage()
			try {
				await login(page, user)
				for (const [width, vp] of Object.entries(VIEWPORTS)) {
					await page.setViewportSize(vp)
					await page.goto(APP)
					await waitApp(page, user)
					await capture(page, lang, user, width, 'main', mainText)
					if (user === 'mia') await auditKid(page, lang, user, width, t)
					else await auditManager(page, lang, user, width, t)
				}
			} catch (err) {
				report.push({ lang, user, where: 'ERROR', hits: {}, error: String(err).slice(0, 300) })
			}
			await context.close()
		}
	}
} finally {
	try { await teardownWorld() } catch (err) { report.push({ where: 'teardown ERROR', hits: {}, error: String(err).slice(0, 300) }) }
	for (const [user, lang] of Object.entries(langsBefore)) setLang(REPO, user, lang)
	await browser.close()
}

const langsAfter = Object.fromEntries(Object.keys(ACCOUNTS).map((u) => [u, getLang(REPO, u)]))
writeFileSync(join(OUT, 'report.json'), JSON.stringify({ world: world && { id: world.id, name: world.name }, langsBefore, langsAfter, report, layout, escapeLog }, null, 1))
for (const r of report) {
	const flagged = Object.entries(r.hits ?? {}).map(([k, v]) => `${k}: ${v.join(', ')}`).join(' | ')
	console.log(`${r.lang ?? '--'} ${String(r.user ?? '').padEnd(9)} ${String(r.width ?? '').padEnd(4)} ${String(r.where).padEnd(40)} ${r.error ?? r.note ?? (flagged || 'ok')} (${r.chars ?? 0})`)
}
const bad = layout.filter((l) => l.pageScroll || l.clipped.length)
console.log(`layout: ${layout.length} views, ${bad.length} with horizontal scroll or clipped text`)
for (const l of bad) console.log(`  ${l.lang} ${l.user} ${l.width} ${l.where}: scroll=${l.pageScroll} clipped=${l.clipped.map((c) => c.text.slice(0, 40)).join(' | ')}`)
for (const e of escapeLog.filter((x) => !x.escapeClosed)) console.log(`  escape did not close: ${e.where}`)
console.log('langs before', JSON.stringify(langsBefore), 'after', JSON.stringify(langsAfter))
