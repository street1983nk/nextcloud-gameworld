// Functional, error-path and permission tests against throw-away worlds.
//
// (1) per language (serial): gw-lehrer creates audit261102-<lang>, waits for
//     running, invites (own group; mia is refused for a group manager and invited
//     by the NC admin instead), playtime limit of mia set and restored (admin),
//     time window set and removed, backup, backup folder per account language,
//     restore with the pre-restore backup suffix per language, stop, delete, and
//     the backup folder of the throw-away world is removed from Files.
// (2) NC admin: manager groups removed and re-added (Talk hint of the former
//     manager only after reload), adult switch lag measured, setup check and the
//     copyable proxy commands per language.
// (3) invalid input per language.
// (4) permissions: mia against manager and admin routes, gw-lehrer against admin
//     routes (read-only or with an invalid body).
// (5) missing Docker proxy for at most 60 s (setup check and world list).
// Every message goes through the foreign-word detector. Afterwards the Docker
// state is compared with baseline.txt.
//
// Usage: NODE_PATH=... node scripts/audit/functional.mjs <repo> <outdir>
import { writeFileSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { loadVocab, foreign } from './lang_detector.mjs'
import {
	chromium, APP, LANGS, ACCOUNTS, PREFIX, login, waitApp, api, dav, dictionary, setLang, getLang,
	baselineLangs, baselineWorldIds, assertThrowaway, sleep, PROTECTED_PREFIXES,
} from './common.mjs'

const [REPO = '.', OUT = '.dev/audit/261102'] = process.argv.slice(2)
const SERVER_JSON = process.env.SERVER_JSON ?? join(OUT, '..', 'server.json')
await loadVocab(REPO, SERVER_JSON, LANGS)
const SECTIONS = (process.env.SECTIONS ?? '1,2,3,4,5').split(',')
const ROOTS = { de: 'Gameworld/Sicherungen', en: 'Gameworld/Backups', fr: 'Gameworld/Sauvegardes' }
const SUFFIX = { de: 'vor-restore', en: 'before-restore', fr: 'avant-restauration' }
const PROXY_CONTAINER = 'gameworld-dev-gameworld-docker-proxy-1'
const UNKNOWN_ID = '000000000000'

const langsBefore = baselineLangs(OUT)
const baselineIds = baselineWorldIds(OUT)
if (!baselineIds.size) throw new Error('baseline-worlds.json missing: run audit.mjs first')
const results = []
const measures = {}
const browser = await chromium.launch()

// One result line: status check plus language check of the message.
function check(section, lang, user, step, res, expect, extra = {}) {
	const statusOk = expect === undefined || (Array.isArray(expect) ? expect.includes(res.status) : res.status === expect)
	const text = [res.detail ?? '', extra.text ?? ''].join(' ').trim()
	const hits = foreign(text, lang)
	const entry = { section, lang, user, step, status: res.status, expect, ok: statusOk && !Object.keys(hits).length, detail: res.detail, hits, ms: res.ms, ...extra }
	results.push(entry)
	return entry
}
const note = (section, lang, user, step, info) => results.push({ section, lang, user, step, ok: true, note: info })
const fail = (section, lang, user, step, err) => results.push({ section, lang, user, step, ok: false, error: String(err).split('\n')[0].slice(0, 300) })

async function session(user, viewport = { width: 1280, height: 900 }) {
	const ctx = await browser.newContext({ viewport })
	const page = await ctx.newPage()
	await login(page, user)
	return { ctx, page }
}

async function findWorld(page, lang, id) {
	return (await api(page, lang, 'GET', '/api/worlds')).body?.worlds?.find((w) => w.id === id) ?? null
}

async function waitWorld(page, lang, id, pred, seconds) {
	let w = null
	for (let i = 0; i < seconds / 2; i++) {
		w = await findWorld(page, lang, id)
		if (pred(w)) return w
		await sleep(2000)
	}
	return w
}

async function propfindNames(page, folder) {
	const r = await dav(page, 'PROPFIND', '/' + folder + '/', { Depth: '1' })
	if (r.status !== 207) return { status: r.status, names: [] }
	const names = [...r.text.matchAll(/<d:href>([^<]+)<\/d:href>/g)].map((m) => decodeURIComponent(m[1]).replace(/\/$/, '').split('/').pop())
	return { status: r.status, names: names.slice(1) }
}

async function removeAuditFolders(page, section, lang, user) {
	for (const root of Object.values(ROOTS)) {
		const { names } = await propfindNames(page, root)
		for (const name of names.filter((n) => n.startsWith(PREFIX))) {
			const del = await dav(page, 'DELETE', `/${root}/${encodeURIComponent(name)}`)
			note(section, lang, user, `files cleanup ${root}/${name}`, `DELETE ${del.status}`)
		}
	}
}

async function deleteWorld(page, section, lang, user, world) {
	assertThrowaway(world, baselineIds)
	const del = await api(page, lang, 'DELETE', `/api/worlds/${world.id}`)
	check(section, lang, user, 'delete world', del, 204)
	const gone = await waitWorld(page, lang, world.id, (w) => w === null, 60)
	note(section, lang, user, 'world gone after delete', gone === null ? 'yes' : `no: ${JSON.stringify(gone).slice(0, 200)}`)
}

const DAYS = [1, 2, 3, 4, 5, 6, 7]
const dayIn = (d) => ({ weekday: d.weekday, allowed: d.allowed, limit_minutes: d.limit_minutes, window_start: d.window_start, window_end: d.window_end })

// --- (1) lifecycle per language ------------------------------------------------------
async function lifecycle(lang) {
	const S = '1'
	setLang(REPO, 'gw-lehrer', lang)
	setLang(REPO, 'admin', lang)
	const { ctx, page } = await session('gw-lehrer')
	const admin = await session('admin')
	let world = null
	try {
		const created = await api(page, lang, 'POST', '/api/worlds', { name: `${PREFIX}${lang}` })
		check(S, lang, 'gw-lehrer', 'create world', created, 201, { text: `${created.body?.status_text ?? ''} ${created.body?.preset_title ?? ''}` })
		if (created.status !== 201) return
		world = created.body
		assertThrowaway(world, baselineIds)
		note(S, lang, 'gw-lehrer', 'world language = account language', `${world.language} (expected ${lang})`)
		let w = await waitWorld(page, lang, world.id, (x) => x && x.op_state !== 'creating', 120)
		if (w && w.status !== 'running') {
			const st = await api(page, lang, 'POST', `/api/worlds/${world.id}/start`)
			check(S, lang, 'gw-lehrer', 'start world', st, 200, { text: st.body?.status_text })
		}
		const t0 = Date.now()
		w = await waitWorld(page, lang, world.id, (x) => x && x.status === 'running', 120)
		check(S, lang, 'gw-lehrer', 'world running within 120 s', { status: w?.status === 'running' ? 200 : 0, detail: w?.status_text ?? '' }, 200, { seconds: Math.round((Date.now() - t0) / 1000) })

		// Invitations: own group allowed; mia is outside the groups of gw-lehrer.
		const invMia = await api(page, lang, 'POST', `/api/worlds/${world.id}/invites`, { kind: 'user', target: 'mia' })
		check(S, lang, 'gw-lehrer', 'invite mia as group manager (refused)', invMia, 403)
		const invGroup = await api(page, lang, 'POST', `/api/worlds/${world.id}/invites`, { kind: 'group', target: 'klasse' })
		check(S, lang, 'gw-lehrer', 'invite own group klasse', invGroup, 200)
		const remGroup = await api(page, lang, 'POST', `/api/worlds/${world.id}/invites/remove`, { kind: 'group', target: 'klasse' })
		check(S, lang, 'gw-lehrer', 'remove invite klasse', remGroup, 200)
		const invA = await api(admin.page, lang, 'POST', `/api/worlds/${world.id}/invites`, { kind: 'user', target: 'mia' })
		check(S, lang, 'admin', 'invite mia', invA, 200)
		const players = await api(admin.page, lang, 'GET', `/api/worlds/${world.id}/players`)
		note(S, lang, 'admin', 'mia in player list', String(players.body?.players?.some((p) => p.nc_user === 'mia')))
		const remA = await api(admin.page, lang, 'POST', `/api/worlds/${world.id}/invites/remove`, { kind: 'user', target: 'mia' })
		check(S, lang, 'admin', 'remove invite mia', remA, 200)

		// Playtime limit of mia (admin; gw-lehrer does not see mia), restored exactly.
		const pt = await api(admin.page, lang, 'GET', '/api/playtime')
		const mia = pt.body?.children?.find((c) => c.nc_user === 'mia')
		if (!mia) note(S, lang, 'admin', 'playtime mia', 'mia not in children list')
		else {
			const before = JSON.stringify({ has_rules: mia.has_rules, normal: mia.normal, holiday: mia.holiday })
			const set = await api(admin.page, lang, 'POST', '/api/playtime/children/mia', { normal: DAYS.map((d) => ({ weekday: d, allowed: true, limit_minutes: 45, window_start: null, window_end: null })), holiday: null })
			check(S, lang, 'admin', 'set playtime limit mia', set, 200)
			let restore
			if (mia.has_rules) restore = await api(admin.page, lang, 'POST', '/api/playtime/children/mia', { normal: mia.normal.map(dayIn), holiday: mia.holiday ? mia.holiday.map(dayIn) : null })
			else restore = await api(admin.page, lang, 'DELETE', '/api/playtime/children/mia')
			check(S, lang, 'admin', 'restore playtime mia', restore, 200)
			const again = (await api(admin.page, lang, 'GET', '/api/playtime')).body.children.find((c) => c.nc_user === 'mia')
			const after = JSON.stringify({ has_rules: again.has_rules, normal: again.normal, holiday: again.holiday })
			results.push({ section: S, lang, user: 'admin', step: 'playtime mia identical after restore', ok: before === after, note: before === after ? 'identical' : `before ${before} after ${after}` })
		}

		// Time window of the world.
		const win = await api(page, lang, 'POST', `/api/playtime/worlds/${world.id}/window`, { days: DAYS.map((d) => ({ weekday: d, open: d < 6, window_start: d < 6 ? 900 : null, window_end: d < 6 ? 1080 : null })) })
		check(S, lang, 'gw-lehrer', 'set time window', win, 200)
		const wv = await findWorld(page, lang, world.id)
		note(S, lang, 'gw-lehrer', 'time window in world list', JSON.stringify(wv?.time_window ?? null).slice(0, 200))
		const winDel = await api(page, lang, 'DELETE', `/api/playtime/worlds/${world.id}/window`)
		check(S, lang, 'gw-lehrer', 'remove time window', winDel, 200)

		// Backup and folder per account language.
		const bk = await api(page, lang, 'POST', `/api/worlds/${world.id}/backups`, {})
		check(S, lang, 'gw-lehrer', 'start backup', bk, 202, { text: bk.body?.backup_job?.message ?? '' })
		w = await waitWorld(page, lang, world.id, (x) => x && x.backup_job && x.backup_job.state !== 'running' && !['backing_up'].includes(x.op_state), 240)
		check(S, lang, 'gw-lehrer', 'backup finished', { status: w?.backup_job?.state === 'ok' ? 200 : 0, detail: w?.backup_job?.message ?? '' }, 200, { job: w?.backup_job })
		let list = await api(page, lang, 'GET', `/api/worlds/${world.id}/backups`)
		check(S, lang, 'gw-lehrer', 'list backups', list, 200, { names: list.body?.backups?.map((b) => `${b.kind}:${b.name}`) })
		const folder = await propfindNames(page, `${ROOTS[lang]}/${PREFIX}${lang}`)
		results.push({ section: S, lang, user: 'gw-lehrer', step: `backup folder ${ROOTS[lang]}/${PREFIX}${lang}`, ok: folder.status === 207 && folder.names.length > 0, note: `PROPFIND ${folder.status}: ${folder.names.join(', ')}` })
		for (const other of Object.keys(ROOTS).filter((l) => l !== lang)) {
			const f = await propfindNames(page, `${ROOTS[other]}/${PREFIX}${lang}`)
			results.push({ section: S, lang, user: 'gw-lehrer', step: `no folder in ${ROOTS[other]}`, ok: f.status !== 207, note: `PROPFIND ${f.status}` })
		}

		// Restore: without confirmation 409, with confirmation 202; pre-restore backup suffix per language.
		const file = list.body?.backups?.find((b) => b.kind === 'backup')
		if (file) {
			const noConfirm = await api(page, lang, 'POST', `/api/worlds/${world.id}/restore`, { file_id: file.file_id })
			check(S, lang, 'gw-lehrer', 'restore without confirm (409)', noConfirm, 409)
			const rs = await api(page, lang, 'POST', `/api/worlds/${world.id}/restore`, { file_id: file.file_id, confirm: true })
			check(S, lang, 'gw-lehrer', 'start restore', rs, 202, { text: rs.body?.backup_job?.message ?? '' })
			w = await waitWorld(page, lang, world.id, (x) => x && x.backup_job && x.backup_job.kind === 'restore' && x.backup_job.state !== 'running' && !['restoring', 'restoring_swap'].includes(x.op_state), 300)
			check(S, lang, 'gw-lehrer', 'restore finished', { status: w?.backup_job?.state === 'ok' ? 200 : 0, detail: w?.backup_job?.message ?? '' }, 200, { job: w?.backup_job, statusAfter: w?.status })
			list = await api(page, lang, 'GET', `/api/worlds/${world.id}/backups`)
			const pre = list.body?.backups?.find((b) => b.kind === 'vor-restore')
			results.push({ section: S, lang, user: 'gw-lehrer', step: `pre-restore backup carries "${SUFFIX[lang]}"`, ok: Boolean(pre && pre.name.includes(SUFFIX[lang])), note: list.body?.backups?.map((b) => `${b.kind}:${b.name}`).join(', ') })
		} else fail(S, lang, 'gw-lehrer', 'restore', 'no backup in list')

		// (3) invalid input while the throw-away world exists.
		if (SECTIONS.includes('3')) await invalidInput(page, lang, world)

		// Stop and delete.
		const stop = await api(page, lang, 'POST', `/api/worlds/${world.id}/stop`)
		check(S, lang, 'gw-lehrer', 'stop world', stop, 200, { text: stop.body?.status_text })
		w = await waitWorld(page, lang, world.id, (x) => x && x.status !== 'running', 60)
		note(S, lang, 'gw-lehrer', 'status after stop', `${w?.status} / ${w?.status_text}`)
		check(S, lang, 'gw-lehrer', 'status text after stop', { status: 200, detail: w?.status_text ?? '' }, 200)
		await deleteWorld(page, S, lang, 'gw-lehrer', world)
		world = null
		await removeAuditFolders(page, S, lang, 'gw-lehrer')
		const leftover = await propfindNames(page, `${ROOTS[lang]}/${PREFIX}${lang}`)
		results.push({ section: S, lang, user: 'gw-lehrer', step: 'backup folder removed', ok: leftover.status === 404, note: `PROPFIND ${leftover.status}` })
	} catch (err) {
		fail(S, lang, 'gw-lehrer', 'ERROR', err)
	} finally {
		if (world) { try { await deleteWorld(page, S, lang, 'gw-lehrer', world) } catch (err) { fail(S, lang, 'gw-lehrer', 'cleanup delete', err) } }
		await ctx.close()
		await admin.ctx.close()
	}
}

// --- (3) invalid input ---------------------------------------------------------------
async function invalidInput(page, lang, world) {
	const S = '3'
	const calls = [
		['empty world name', 'POST', '/api/worlds', { name: '' }, 422],
		['world name too long', 'POST', '/api/worlds', { name: 'x'.repeat(200) }, 422],
		['unknown preset', 'POST', '/api/worlds', { name: `${PREFIX}x`, preset: 'gibtsnicht' }, 422],
		['start unknown world', 'POST', `/api/worlds/${UNKNOWN_ID}/start`, {}, 404],
		['stop unknown world', 'POST', `/api/worlds/${UNKNOWN_ID}/stop`, {}, 404],
		['delete unknown world', 'DELETE', `/api/worlds/${UNKNOWN_ID}`, {}, 404],
		['malformed world id', 'POST', '/api/worlds/nichtda/start', {}, 422],
		['backup unknown world', 'POST', `/api/worlds/${UNKNOWN_ID}/backups`, {}, 404],
		['backup list unknown world', 'GET', `/api/worlds/${UNKNOWN_ID}/backups`, null, 404],
		['restore unknown world', 'POST', `/api/worlds/${UNKNOWN_ID}/restore`, { file_id: 1, confirm: true }, 404],
		['restore unknown file', 'POST', `/api/worlds/${world.id}/restore`, { file_id: 999999999, confirm: true }, 404],
		['holiday end before start', 'POST', '/api/playtime/holidays', { label: '', start_date: '2026-12-31', end_date: '2026-01-01' }, 422],
		['holiday bad date', 'POST', '/api/playtime/holidays', { label: '', start_date: '31.12.2026', end_date: '2027-01-01' }, 422],
		['negative pause', 'POST', '/api/pause', { minutes: -5 }, 422],
		['pause 20 minutes', 'POST', '/api/pause', { minutes: 20 }, 422],
		['invalid player name', 'POST', '/api/players/name', { nc_user: 'gw-lehrer', player_name: 'bad name!' }, [404, 422]],
		['invite unknown account', 'POST', `/api/worlds/${world.id}/invites`, { kind: 'user', target: 'gibtsnicht-audit' }, [403, 404, 422]],
		['time window six days', 'POST', `/api/playtime/worlds/${world.id}/window`, { days: DAYS.slice(0, 6).map((d) => ({ weekday: d, open: true })) }, 422],
		['time zone unknown', 'POST', '/api/playtime/time-zone', { time_zone: 'Mars/Olympus' }, 422],
		['playtime limit 0', 'POST', '/api/playtime/children/gw-lehrer', { normal: DAYS.map((d) => ({ weekday: d, allowed: true, limit_minutes: 0 })) }, [403, 404, 422]],
		['unknown route', 'GET', '/api/gibtsnicht', null, 404],
	]
	for (const [step, method, path, body, expect] of calls) {
		const res = await api(page, lang, method, path, body)
		check(S, lang, 'gw-lehrer', step, res, expect)
		if (res.status < 300) fail(S, lang, 'gw-lehrer', `${step} was ACCEPTED`, `${res.status} ${JSON.stringify(res.body).slice(0, 200)}`)
	}
	// CSRF refusal (no JSON): message language with UI header vs account language.
	const raw = await api(page, lang, 'POST', `/api/worlds/${UNKNOWN_ID}/start`, {}, { raw: true })
	check(S, lang, 'gw-lehrer', 'change without JSON content type (CSRF rule)', raw, 403)
}

// --- (4) permissions -----------------------------------------------------------------
const MANAGER_ROUTES = [
	['GET', '/api/worlds', null], ['POST', '/api/worlds', { name: '' }], ['GET', '/api/presets', null],
	['POST', `/api/worlds/${UNKNOWN_ID}/start`, {}], ['POST', `/api/worlds/${UNKNOWN_ID}/stop`, {}], ['DELETE', `/api/worlds/${UNKNOWN_ID}`, {}],
	['GET', `/api/worlds/${UNKNOWN_ID}/backups`, null], ['POST', `/api/worlds/${UNKNOWN_ID}/backups`, {}], ['POST', `/api/worlds/${UNKNOWN_ID}/restore`, { file_id: 1 }],
	['GET', `/api/worlds/${UNKNOWN_ID}/players`, null], ['POST', `/api/worlds/${UNKNOWN_ID}/invites`, { kind: 'user', target: '' }],
	['POST', '/api/players/password', { nc_user: '' }], ['POST', '/api/players/adult', { nc_user: '', adult: false }], ['POST', '/api/players/name', { nc_user: '', player_name: '' }],
	['GET', '/api/settings', null], ['POST', '/api/settings', { join_host: '%%' }],
	['GET', '/api/playtime', null], ['POST', '/api/playtime/children/mia', { normal: [] }], ['DELETE', '/api/playtime/children/nobody-audit', {}],
	['POST', '/api/playtime/holidays', { start_date: 'x', end_date: 'y' }], ['POST', '/api/playtime/time-zone', { time_zone: 'Mars/Olympus' }],
	['GET', '/api/pause', null], ['POST', '/api/pause', { minutes: 7 }], ['POST', '/api/pause/end', { invalid: true }],
	['GET', '/api/setup-check', null], ['GET', '/api/talk', null], ['POST', `/api/worlds/${UNKNOWN_ID}/talk/recreate`, {}],
	// Alerts router (prefix /api, manager guard; not under /api/admin).
	['GET', '/api/attempts', null], ['GET', '/api/review', null], ['GET', '/api/review/prefs', null],
	['POST', '/api/review/prefs', { enabled: 'x' }], ['POST', '/api/origin', { origin: 'x'.repeat(5000) }],
]
const ADMIN_ROUTES = [
	['GET', '/api/admin/verwalter-groups', null], ['POST', '/api/admin/verwalter-groups/add', { gid: '' }], ['POST', '/api/admin/verwalter-groups/remove', { gid: '' }],
	['GET', '/api/admin/groups', null], ['GET', '/api/admin/orphans', null], ['POST', '/api/admin/orphans/container/remove', { id: 'x' }],
	['POST', '/api/admin/orphans/volume/remove', { name: 'x' }],
]
async function permissions(lang) {
	const S = '4'
	for (const user of ['mia', 'gw-lehrer']) setLang(REPO, user, lang)
	for (const [user, routes] of [['mia', [...MANAGER_ROUTES, ...ADMIN_ROUTES]], ['gw-lehrer', ADMIN_ROUTES]]) {
		const { ctx, page } = await session(user)
		try {
			for (const [method, path, body] of routes) {
				const res = await api(page, lang, method, path, body)
				check(S, lang, user, `${method} ${path}`, res, 403)
			}
			// Without the UI header: refusal in the account language.
			const res = await api(page, null, 'GET', user === 'mia' ? '/api/worlds' : '/api/admin/groups')
			check(S, lang, user, 'refusal without UI language header (account language)', res, 403)
			if (user === 'mia') {
				for (const path of ['/api/me', '/api/my/worlds', '/api/my/playtime']) check(S, lang, user, `GET ${path} (allowed)`, await api(page, lang, 'GET', path), 200)
			}
		} finally {
			await ctx.close()
		}
	}
}

// --- (2) NC admin ----------------------------------------------------------------------
async function adminChecks() {
	const S = '2'
	const lang = 'de'
	for (const user of ['admin', 'gw-lehrer']) setLang(REPO, user, lang)
	const t = await dictionary(REPO, lang)
	const teacher = await session('gw-lehrer')
	const admin = await session('admin')
	let world = null
	const removedGroups = []
	try {
		// World created through the UI by gw-lehrer; Talk status without and with reload.
		const name = `${PREFIX}talk`
		await teacher.page.getByLabel(t['parent.view.worldName']).fill(name)
		await teacher.page.getByRole('button', { name: t['parent.view.createWorld'], exact: true }).click()
		const t0 = Date.now()
		await teacher.page.locator('tr', { hasText: name }).first().waitFor({ timeout: 60000 })
		world = (await api(teacher.page, lang, 'GET', '/api/worlds')).body.worlds.find((w) => w.name === name)
		assertThrowaway(world, baselineIds)
		note(S, lang, 'gw-lehrer', 'world created via UI', `${world.id} after ${Date.now() - t0} ms`)
		const rowText = async (page) => page.locator(`tr[data-world-id="${world.id}"] td`).first().innerText().catch(() => '')
		await sleep(5000)
		const talk5 = await rowText(teacher.page)
		let room = null
		for (let i = 0; i < 30 && !room?.has_room; i++) { room = (await api(teacher.page, lang, 'GET', '/api/talk')).body?.worlds?.find((x) => x.world_id === world.id); if (!room?.has_room) await sleep(2000) }
		await sleep(35000)
		const talk45 = await rowText(teacher.page)
		await teacher.page.reload(); await waitApp(teacher.page, 'gw-lehrer')
		const talkReload = await rowText(teacher.page)
		measures.talkAfterCreate = { at5s: talk5, at45sNoReload: talk45, afterReload: talkReload, apiHasRoom: room?.has_room ?? false }
		results.push({ section: S, lang, user: 'gw-lehrer', step: 'Talk room status after UI create without reload (loadTalk not polled)', ok: true, note: JSON.stringify(measures.talkAfterCreate) })

		// Adult switch lag (admin, mia invited into the throw-away world).
		check(S, lang, 'admin', 'invite mia into talk world', await api(admin.page, lang, 'POST', `/api/worlds/${world.id}/invites`, { kind: 'user', target: 'mia' }), 200)
		const before = (await api(admin.page, lang, 'GET', `/api/worlds/${world.id}/players`)).body.players.find((p) => p.nc_user === 'mia')
		note(S, lang, 'admin', 'mia adult before', String(before?.adult))
		await admin.page.goto(APP); await waitApp(admin.page, 'admin')
		const row = admin.page.locator(`tr[data-world-id="${world.id}"]`)
		await row.getByRole('button', { name: t['parent.view.action.players'], exact: true }).click()
		const dlg = admin.page.locator('[role=dialog]').first()
		await dlg.locator('.players__adult').first().waitFor({ timeout: 15000 })
		const chip = dlg.locator('.nc-chip', { hasText: t['parent.players.adult'] })
		const sw = dlg.locator('.players__adult').first().getByText(t['parent.players.adult'], { exact: true })
		const lag = async (want) => { const s = Date.now(); while (Date.now() - s < 15000) { if ((await chip.count() > 0) === want) return Date.now() - s; await sleep(50) } return null }
		if (!before?.adult) {
			await sw.click()
			const confirm = admin.page.getByRole('dialog', { name: t['parent.common.markAdult'] })
			await confirm.waitFor({ timeout: 5000 })
			await confirm.getByRole('button', { name: t['parent.common.markAdult'], exact: true }).click()
			measures.adultOnChipMs = await lag(true)
			await sleep(1500)
			await admin.page.locator('[role=dialog]').first().locator('.players__adult').first().getByText(t['parent.players.adult'], { exact: true }).click()
			measures.adultOffChipMs = await lag(false)
		} else note(S, lang, 'admin', 'adult lag', 'mia already adult: not toggled')
		await sleep(1500)
		const after = (await api(admin.page, lang, 'GET', `/api/worlds/${world.id}/players`)).body.players.find((p) => p.nc_user === 'mia')
		if (Boolean(after?.adult) !== Boolean(before?.adult)) {
			check(S, lang, 'admin', 'restore adult flag', await api(admin.page, lang, 'POST', '/api/players/adult', { nc_user: 'mia', adult: Boolean(before?.adult) }), 200)
		}
		results.push({ section: S, lang, user: 'admin', step: 'adult chip lag after switching (ms)', ok: true, note: `on ${measures.adultOnChipMs} ms, off ${measures.adultOffChipMs} ms, final adult=${after?.adult} (before ${before?.adult})` })
		await admin.page.keyboard.press('Escape')

		// Manager groups: remove the groups of gw-lehrer, Talk hint of the former manager, re-add.
		const groupsBefore = (await api(admin.page, lang, 'GET', '/api/admin/verwalter-groups')).body?.groups ?? []
		note(S, lang, 'admin', 'manager groups before', JSON.stringify(groupsBefore))
		await admin.page.goto(APP); await waitApp(admin.page, 'admin')
		const hint = t['core.playtime.talk.formerOwner'].split('{owner}')[0].trim()
		for (const gid of groupsBefore.filter((g) => ['lehrkraefte', 'klasse'].includes(g))) {
			const r = await api(admin.page, lang, 'POST', '/api/admin/verwalter-groups/remove', { gid })
			check(S, lang, 'admin', `remove manager group ${gid}`, r, 200)
			if (r.status === 200) removedGroups.push(gid)
		}
		await sleep(35000)
		const talkApi = (await api(admin.page, lang, 'GET', '/api/talk')).body?.worlds?.find((x) => x.world_id === world.id)
		const noReload = (await rowText(admin.page)).includes(hint)
		await admin.page.reload(); await waitApp(admin.page, 'admin')
		const withReload = (await rowText(admin.page)).includes(hint)
		measures.formerManagerHint = { api_owner_not_admin: talkApi?.owner_not_admin ?? null, shownWithoutReload: noReload, shownAfterReload: withReload, hintStart: hint }
		results.push({ section: S, lang, user: 'admin', step: 'Talk hint former manager (only after reload)', ok: true, note: JSON.stringify(measures.formerManagerHint) })
	} catch (err) {
		fail(S, lang, 'admin', 'ERROR', err)
	} finally {
		for (const gid of removedGroups) {
			const r = await api(admin.page, lang, 'POST', '/api/admin/verwalter-groups/add', { gid })
			check(S, lang, 'admin', `re-add manager group ${gid}`, r, 200)
		}
		const groupsAfter = (await api(admin.page, lang, 'GET', '/api/admin/verwalter-groups')).body?.groups ?? []
		note(S, lang, 'admin', 'manager groups after', JSON.stringify(groupsAfter))
		if (world) {
			await api(admin.page, lang, 'POST', `/api/worlds/${world.id}/invites/remove`, { kind: 'user', target: 'mia' })
			try { await deleteWorld(admin.page, S, lang, 'admin', world) } catch (err) { fail(S, lang, 'admin', 'cleanup delete', err) }
		}
		await teacher.ctx.close()
		await admin.ctx.close()
	}

	// Setup check per language plus the copyable proxy commands (only offered for the
	// default proxy address; the dev stack uses 127.0.0.1:23750, so rendered directly).
	const commands = JSON.parse(execFileSync('uv', ['run', 'python', '-c',
		'import json; from dataclasses import asdict; from gameworld.provisioner.proxy_setup import proxy_commands, COMMAND_TRIGGER_IDS, PROXY_NAME, PROXY_PORT; ' +
		'print(json.dumps([asdict(c) for c in proxy_commands(sorted(COMMAND_TRIGGER_IDS), f"tcp://{PROXY_NAME}:{PROXY_PORT}")]))'], { cwd: REPO, encoding: 'utf8' }).trim().split('\n').pop())
	measures.proxyCommands = commands
	for (const c of commands) {
		const need = ['docker run -d', `--network ${c.network}`, '/var/run/docker.sock:/var/run/docker.sock:ro', 'tecnativa/docker-socket-proxy', '-e CONTAINERS=1', '-e IMAGES=1', '-e VOLUMES=1', '-e POST=1', '-e EXEC=0', '--name gameworld-docker-proxy', '--restart unless-stopped']
		const missing = need.filter((n) => !c.command.includes(n))
		results.push({ section: S, lang: '-', user: '-', step: `proxy command ${c.id} complete`, ok: missing.length === 0, note: missing.length ? `missing ${missing.join(', ')}` : c.command })
	}
	const admin2 = await session('admin')
	try {
		for (const l of LANGS) {
			const td = await dictionary(REPO, l)
			const labels = ['admin.setup.commandsHeading', 'admin.setup.commandsHint', 'admin.setup.commandCompose', 'admin.setup.commandAio', 'admin.setup.copyCommand', 'admin.setup.copied', 'admin.setup.copyFailed'].map((k) => td[k]).join(' ')
			check(S, l, 'admin', 'proxy command labels', { status: 200, detail: labels }, 200)
			const sc = await api(admin2.page, l, 'GET', '/api/setup-check')
			check(S, l, 'admin', 'setup check', sc, 200, { text: (sc.body?.items ?? []).map((i) => i.message).join(' '), items: sc.body?.items, commands: sc.body?.proxy_commands?.length })
		}
	} finally {
		await admin2.ctx.close()
	}
}

// --- (5) missing Docker proxy ------------------------------------------------------------
async function missingProxy() {
	const S = '5'
	const admin = await session('admin')
	const pages = {}
	try {
		const left = (await api(admin.page, 'de', 'GET', '/api/worlds')).body.worlds.filter((w) => w.name.startsWith(PREFIX))
		if (left.length) { fail(S, '-', 'admin', 'proxy stop skipped', 'throw-away worlds still exist'); return }
		const t0 = Date.now()
		execFileSync('docker', ['stop', '-t', '5', PROXY_CONTAINER])
		try {
			for (const l of LANGS) {
				const sc = await api(admin.page, l, 'GET', '/api/setup-check')
				check(S, l, 'admin', 'setup check without proxy', sc, 200, { text: (sc.body?.items ?? []).map((i) => i.message).join(' '), items: sc.body?.items, ok_flag: sc.body?.ok })
				const wl = await api(admin.page, l, 'GET', '/api/worlds')
				check(S, l, 'admin', 'world list without proxy', wl, [200, 503], { text: (wl.body?.worlds ?? []).map((w) => w.status_text).join(' ') })
				const cr = await api(admin.page, l, 'POST', '/api/worlds', { name: '' })
				check(S, l, 'admin', 'create (invalid) without proxy', cr, 422)
				if (Date.now() - t0 > 45000) break
			}
			// UI text of the setup check section without proxy (de).
			await admin.page.goto(APP)
			await admin.page.waitForTimeout(8000)
			pages.ui = await admin.page.locator('main .setup-check').innerText().catch(() => '')
			check(S, 'de', 'admin', 'setup check UI without proxy', { status: 200, detail: pages.ui }, 200)
		} finally {
			execFileSync('docker', ['start', PROXY_CONTAINER])
			measures.proxyDownSeconds = Math.round((Date.now() - t0) / 1000)
		}
		note(S, '-', 'admin', 'proxy down seconds', String(measures.proxyDownSeconds))
		await sleep(5000)
		const back = await api(admin.page, 'de', 'GET', '/api/setup-check')
		check(S, 'de', 'admin', 'setup check after proxy restart', back, 200, { ok_flag: back.body?.ok })
	} finally {
		await admin.ctx.close()
	}
}

// --- baseline comparison ---------------------------------------------------------------
function compareBaseline() {
	const base = readFileSync(join(OUT, 'baseline.txt'), 'utf8')
	const section = (name) => base.split(`## ${name}\n`)[1]?.split('\n## ')[0].trim().split('\n') ?? []
	const state = (s) => (s.startsWith('Up') ? 'Up' : s.split(' ')[0])
	const basePs = new Map(section('docker ps -a').map((l) => { const [n, ...r] = l.split(' '); return [n, state(r.join(' '))] }))
	const nowPs = new Map(execFileSync('docker', ['ps', '-a', '--format', '{{.Names}} {{.Status}}'], { encoding: 'utf8' }).trim().split('\n').map((l) => { const [n, ...r] = l.split(' '); return [n, state(r.join(' '))] }))
	const baseVol = new Set(section('docker volume ls'))
	const nowVol = new Set(execFileSync('docker', ['volume', 'ls', '--format', '{{.Name}}'], { encoding: 'utf8' }).trim().split('\n'))
	const diff = []
	for (const [n, s] of basePs) if (nowPs.get(n) !== s) diff.push(`container ${n}: ${s} -> ${nowPs.get(n) ?? 'missing'}`)
	for (const [n] of nowPs) if (!basePs.has(n)) diff.push(`new container ${n}`)
	for (const v of baseVol) if (!nowVol.has(v)) diff.push(`volume missing ${v}`)
	for (const v of nowVol) if (!baseVol.has(v)) diff.push(`new volume ${v}`)
	const protectedTouched = diff.filter((d) => PROTECTED_PREFIXES.some((p) => d.includes(p)))
	return { diff, protectedTouched }
}

try {
	if (SECTIONS.includes('1') || SECTIONS.includes('3')) for (const lang of LANGS) await lifecycle(lang)
	if (SECTIONS.includes('4')) for (const lang of LANGS) await permissions(lang)
	if (SECTIONS.includes('2')) await adminChecks()
	if (SECTIONS.includes('5')) await missingProxy()
} finally {
	for (const [user, lang] of Object.entries(langsBefore)) setLang(REPO, user, lang)
	await browser.close()
}

const baseline = compareBaseline()
const langsAfter = Object.fromEntries(Object.keys(ACCOUNTS).map((u) => [u, getLang(REPO, u)]))
writeFileSync(join(OUT, 'functional.json'), JSON.stringify({ langsBefore, langsAfter, baseline, measures, results }, null, 1))
for (const r of results) {
	const hits = Object.entries(r.hits ?? {}).map(([k, v]) => `${k}: ${v.join(', ')}`).join(' | ')
	console.log(`${r.ok ? 'ok  ' : 'FAIL'} [${r.section}] ${r.lang} ${String(r.user).padEnd(9)} ${r.step} ${r.status ?? ''}${r.expect !== undefined ? '/' + r.expect : ''} ${hits ? 'HITS ' + hits : ''} ${r.error ?? r.note ?? (r.detail ? '"' + String(r.detail).slice(0, 120) + '"' : '')}`)
}
console.log('baseline diff:', JSON.stringify(baseline))
console.log('langs before', JSON.stringify(langsBefore), 'after', JSON.stringify(langsAfter))
console.log('measures', JSON.stringify(measures).slice(0, 1500))
