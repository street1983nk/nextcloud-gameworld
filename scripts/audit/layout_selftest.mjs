// Positive and negative control of the layout probe on hand-made pages.
// Usage: NODE_PATH=... node scripts/audit/layout_selftest.mjs   (exit 1 on failure)
import { chromium } from './common.mjs'
import { layoutProbe } from './layout_probe.mjs'

const cases = [
	{ name: 'clean text', html: '<p>Short text</p>', scroll: false, clipped: 0 },
	{ name: 'ellipsis clipped', html: '<div style="width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">A rather long text that is cut off here</div>', scroll: false, clipped: 1 },
	{ name: 'page wider than viewport', html: '<div style="width:900px">wide</div>', scroll: true, clipped: 0 },
	{ name: 'visually hidden table head', html: '<table><thead style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)"><tr><th>Name Type Port Status Players</th></tr></thead></table>', scroll: false, clipped: 0 },
]
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 390, height: 800 } })
let failed = 0
for (const c of cases) {
	await page.setContent(`<html><body style="margin:0"><main>${c.html}</main></body></html>`)
	const r = await page.evaluate(layoutProbe)
	const ok = r.pageScroll === c.scroll && r.clipped.length === c.clipped
	if (!ok) failed++
	console.log(`${ok ? 'ok  ' : 'FAIL'} ${c.name}: scroll=${r.pageScroll} clipped=${r.clipped.length}`)
}
await browser.close()
console.log(failed ? `LAYOUT SELFTEST FAILED (${failed})` : 'LAYOUT SELFTEST PASSED')
process.exit(failed ? 1 : 0)
