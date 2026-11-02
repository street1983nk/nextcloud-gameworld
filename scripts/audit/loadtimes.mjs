// Load times of the main view per account (admin, gw-lehrer, mia), language de,
// three loads each: from goto until the world table (or the kid cards) and, for
// managers, the playtime list are visible; plus the duration of the main API
// calls from the Resource Timing entries. Median and maximum go to loadtimes.json.
// Usage: NODE_PATH=... node scripts/audit/loadtimes.mjs <repo> <outdir>
import { writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { chromium, APP, ACCOUNTS, login, setLang, getLang, baselineLangs } from './common.mjs'

const [REPO = '.', OUT = '.dev/audit/261102'] = process.argv.slice(2)
const RUNS = Number(process.env.RUNS ?? 3)
const LANG = 'de'
const langsBefore = baselineLangs(OUT)
const median = (xs) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor((s.length - 1) / 2)] : null }
const result = {}
const browser = await chromium.launch()
try {
	for (const user of Object.keys(ACCOUNTS)) setLang(REPO, user, LANG)
	for (const user of Object.keys(ACCOUNTS)) {
		const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
		const page = await ctx.newPage()
		await login(page, user)
		const runs = []
		for (let i = 0; i < RUNS; i++) {
			const t0 = Date.now()
			await page.goto(APP)
			const firstSel = user === 'mia' ? '.connection-card, .gameworld-player .empty-content' : '.gameworld__list, .gameworld__empty'
			await page.waitForSelector(firstSel, { timeout: 60000 })
			const firstMs = Date.now() - t0
			let fullMs = firstMs
			if (user !== 'mia') {
				await page.waitForSelector('.playtime__list, .playtime__empty', { timeout: 60000 })
				fullMs = Date.now() - t0
			}
			await page.waitForTimeout(1500)
			const apiTimes = await page.evaluate(() => performance.getEntriesByType('resource')
				.filter((e) => e.name.includes('/proxy/gameworld/api/'))
				.map((e) => ({ path: new URL(e.name).pathname.split('/proxy/gameworld')[1], ms: Math.round(e.duration) })))
			runs.push({ firstMs, fullMs, apiTimes })
		}
		const apis = {}
		for (const r of runs) for (const a of r.apiTimes) (apis[a.path] ??= []).push(a.ms)
		result[user] = {
			runs,
			firstVisible: { median: median(runs.map((r) => r.firstMs)), max: Math.max(...runs.map((r) => r.firstMs)) },
			complete: { median: median(runs.map((r) => r.fullMs)), max: Math.max(...runs.map((r) => r.fullMs)) },
			api: Object.fromEntries(Object.entries(apis).map(([p, xs]) => [p, { median: median(xs), max: Math.max(...xs), n: xs.length }])),
		}
		await ctx.close()
	}
} finally {
	for (const [user, lang] of Object.entries(langsBefore)) setLang(REPO, user, lang)
	await browser.close()
}
const langsAfter = Object.fromEntries(Object.keys(ACCOUNTS).map((u) => [u, getLang(REPO, u)]))
writeFileSync(join(OUT, 'loadtimes.json'), JSON.stringify({ lang: LANG, runs: RUNS, langsBefore, langsAfter, result }, null, 1))
for (const [user, r] of Object.entries(result)) {
	console.log(`${user.padEnd(9)} first visible median ${r.firstVisible.median} ms max ${r.firstVisible.max} ms, complete median ${r.complete.median} ms max ${r.complete.max} ms`)
	for (const [p, a] of Object.entries(r.api)) console.log(`    ${p.padEnd(40)} median ${a.median} ms max ${a.max} ms (n=${a.n})`)
}
console.log('langs before', JSON.stringify(langsBefore), 'after', JSON.stringify(langsAfter))
