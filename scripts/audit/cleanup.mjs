// Removes leftovers of the audit: worlds whose name starts with audit261102-
// (never a baseline world) and backup folders of those worlds in the files of
// gw-lehrer. Prints the state before and after.
// Usage: NODE_PATH=... node scripts/audit/cleanup.mjs <repo> <outdir> [--dry-run]
import { join } from 'node:path'
import { writeFileSync } from 'node:fs'
import { chromium, PREFIX, login, api, dav, baselineWorldIds, assertThrowaway, sleep } from './common.mjs'

const [, OUT = '.dev/audit/261102'] = process.argv.slice(2)
const DRY = process.argv.includes('--dry-run')
const ROOTS = ['/Gameworld/Sicherungen', '/Gameworld/Backups', '/Gameworld/Sauvegardes']
const baselineIds = baselineWorldIds(OUT)
const log = []
const browser = await chromium.launch()
const ctx = await browser.newContext()
const page = await ctx.newPage()
try {
	await login(page, 'gw-lehrer')
	const worlds = (await api(page, 'de', 'GET', '/api/worlds')).body.worlds
	for (const w of worlds.filter((x) => x.name.startsWith(PREFIX))) {
		assertThrowaway(w, baselineIds)
		log.push(`world ${w.id} ${w.name} status=${w.status} op=${w.op_state} desired=${w.desired_state}`)
		if (DRY) continue
		const del = await api(page, 'de', 'DELETE', `/api/worlds/${w.id}`)
		log.push(`  DELETE -> ${del.status} ${del.detail}`)
	}
	if (!DRY) {
		for (let i = 0; i < 30; i++) {
			const left = (await api(page, 'de', 'GET', '/api/worlds')).body.worlds.filter((x) => x.name.startsWith(PREFIX))
			if (!left.length) break
			await sleep(2000)
		}
	}
	for (const root of ROOTS) {
		const r = await dav(page, 'PROPFIND', root + '/', { Depth: '1' })
		if (r.status !== 207) continue
		const names = [...r.text.matchAll(/<d:href>([^<]+)<\/d:href>/g)].map((m) => decodeURIComponent(m[1]).replace(/\/$/, '').split('/').pop())
		for (const name of names.filter((n) => n.startsWith(PREFIX))) {
			log.push(`folder ${root}/${name}`)
			if (DRY) continue
			const del = await dav(page, 'DELETE', `${root}/${encodeURIComponent(name)}`)
			log.push(`  DELETE -> ${del.status}`)
		}
	}
	const after = (await api(page, 'de', 'GET', '/api/worlds')).body.worlds.filter((x) => x.name.startsWith(PREFIX))
	log.push(`audit worlds left: ${after.length}`)
} finally {
	await browser.close()
}
console.log(log.join('\n'))
writeFileSync(join(OUT, `cleanup-${Date.now()}.log`), log.join('\n'))
