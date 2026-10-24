// Store-Screenshots (06-13, D-10) mit Playwright gegen den Dev-Stack.
//
// Voraussetzung: sh scripts/dev/screenshot-demo.sh (Demo-Konten mama, mia, leo,
// oma und die Welten Baumhaus und Inselabenteuer; Welt-IDs in
// .dev/screenshot-demo.json). Playwright ist keine Projektabhängigkeit: Das
// Paket kommt aus einem vorhandenen npx-Cache über NODE_PATH, etwa
//   NODE_PATH=<npx-cache>/node_modules node scripts/dev/screenshot-capture.mjs [name ...]
// Ohne Namen entstehen alle sechs Bilder in docs/screenshots/ (-v1, der
// Store-Spiegel lädt ein Bild nie neu).
//
// Nur Demo-Daten auf den Bildern: Andere Welten und Konten der Dev-Instanz
// (laufende Dev-Welten des Owners, Dev-Konto gw-kind) blendet die Aufnahme aus,
// indem sie Antworten der Gameworld-API im Browser auf die Demo-Welt-IDs und
// Demo-Konten filtert. Nichts wird erfunden, nur weggelassen; die Instanz
// selbst bleibt unberührt. Einzige Ersetzung: Ohne eingestellte
// Spieler-Adresse (join_host leer, host null in /api/my/worlds) zeigt die
// Kinder-Ansicht den Rechnernamen des Browsers, also "localhost". Die Aufnahme
// setzt dort den Beispielnamen DEMO_HOST ein, so wie es eine eingestellte
// Spieler-Adresse täte, ohne die gespeicherte Einstellung zu ändern.
import { readFileSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const require = createRequire(join(process.env.NODE_PATH ?? '.', 'x.js'))
const { chromium } = require('playwright')

const REPO = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const OUT = join(REPO, 'docs', 'screenshots')
const BASE = `http://localhost:${process.env.GAMEWORLD_NC_PORT ?? '8091'}`
const APP = `${BASE}/index.php/apps/app_api/embedded/gameworld/gameworld`
const DEMO_HOST = 'nextcloud.example.org'
const DEMO = JSON.parse(readFileSync(join(REPO, '.dev', 'screenshot-demo.json'), 'utf8'))
const ALLOWED = new Set(DEMO.worlds)
const ACCOUNTS = {
	mama: 'gameworld-demo-mama-13',
	mia: 'gameworld-demo-mia-13',
}
const DEMO_USERS = new Set(['mama', 'mia', 'leo', 'oma'])
const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }

// Behält in Listen nur Demo-Welten (Schlüssel "worlds") und Demo-Konten (Einträge mit nc_user).
function keep(key, item) {
	if (!item || typeof item !== 'object') {
		return true
	}
	if (key === 'worlds' && !ALLOWED.has(item.id ?? item.world_id)) {
		return false
	}
	return !('nc_user' in item) || DEMO_USERS.has(item.nc_user)
}

function onlyDemo(value) {
	if (Array.isArray(value)) {
		return value.map(onlyDemo)
	}
	if (value && typeof value === 'object') {
		const out = {}
		for (const [key, inner] of Object.entries(value)) {
			if (Array.isArray(inner)) {
				out[key] = inner.filter((item) => keep(key, item)).map(onlyDemo)
			} else {
				out[key] = onlyDemo(inner)
			}
		}
		return out
	}
	return value
}

async function session(browser, user, viewport) {
	const context = await browser.newContext({
		viewport,
		deviceScaleFactor: 1,
		colorScheme: 'light',
		locale: 'de-DE',
		timezoneId: 'Europe/Berlin',
		isMobile: viewport.width < 500,
		hasTouch: viewport.width < 500,
	})
	await context.route(/\/apps\/app_api\/proxy\/gameworld\/api\//, async (route) => {
		let response
		try {
			response = await route.fetch()
		} catch {
			// Der 5-s-Abruf der Seite läuft noch, während die Aufnahme den Kontext schließt.
			return route.abort().catch(() => {})
		}
		const type = response.headers()['content-type'] ?? ''
		if (!type.includes('json')) {
			return route.fulfill({ response }).catch(() => {})
		}
		let body = await response.json()
		body = onlyDemo(body)
		if (route.request().url().endsWith('/api/my/worlds')) {
			for (const world of body.worlds ?? []) {
				world.host = world.host || DEMO_HOST
			}
		}
		return route.fulfill({ response, json: body }).catch(() => {})
	})
	const page = await context.newPage()
	await page.goto(`${BASE}/index.php/login`)
	await page.fill('#user', user)
	await page.fill('#password', ACCOUNTS[user])
	await Promise.all([page.waitForURL((url) => !url.pathname.endsWith('/login')), page.click('button[type=submit]')])
	await page.goto(APP)
	await page.waitForLoadState('networkidle')
	await page.waitForTimeout(1500)
	// Keine Benachrichtigungs-Overlays auf den Bildern (Toasts, Status-Hinweise).
	await page.addStyleTag({ content: '.toastify, #notification-container, .notifications-button .notification__dot { display: none !important; }' })
	return { context, page }
}

async function shot(page, name) {
	const file = join(OUT, `${name}-v1.png`)
	await page.waitForTimeout(800)
	await page.screenshot({ path: file })
	console.log(`aufgenommen: docs/screenshots/${name}-v1.png`)
	await page.context().unrouteAll({ behavior: 'ignoreErrors' })
}

function row(page, worldName) {
	return page.locator('tr', { has: page.locator('td', { hasText: worldName }) }).first()
}

const SHOTS = {
	async worlds(browser) {
		const { context, page } = await session(browser, 'mama', DESKTOP)
		await page.locator('table.gameworld__list').waitFor()
		await page.locator('table.gameworld__list').scrollIntoViewIfNeeded()
		await page.evaluate(() => {
			const table = document.querySelector('table.gameworld__list')
			table?.scrollIntoView({ block: 'center' })
		})
		await shot(page, 'worlds')
		await context.close()
	},
	async invite(browser) {
		const { context, page } = await session(browser, 'mama', DESKTOP)
		await row(page, 'Baumhaus').getByRole('button', { name: 'Einladen' }).click()
		const dialog = page.getByRole('dialog').first()
		await dialog.waitFor()
		// Suche offen zeigen: Gruppe familie als Vorschlag.
		await dialog.locator('input[type=search], input').first().click()
		await page.keyboard.type('fam', { delay: 80 })
		await page.getByRole('option', { name: /familie/i }).first().waitFor({ timeout: 15000 })
		await shot(page, 'invite')
		await context.close()
	},
	async backups(browser) {
		const { context, page } = await session(browser, 'mama', DESKTOP)
		await row(page, 'Baumhaus').getByRole('button', { name: 'Sicherungen' }).click()
		await page.getByRole('dialog').first().waitFor()
		await page.locator('.backup-section__entry').first().waitFor({ timeout: 30000 })
		await shot(page, 'backups')
		await context.close()
	},
	async playtime(browser) {
		const { context, page } = await session(browser, 'mama', DESKTOP)
		const section = page.locator('section', { has: page.locator('h3', { hasText: 'Spielzeit' }) }).first()
		await section.locator('li, tr', { hasText: 'Mia' }).first().getByRole('button', { name: 'Bearbeiten' }).click()
		await page.getByRole('dialog').first().waitFor()
		await shot(page, 'playtime')
		await context.close()
	},
	async 'kids-view'(browser) {
		const { context, page } = await session(browser, 'mia', DESKTOP)
		await shot(page, 'kids-view')
		await context.close()
	},
	async mobile(browser) {
		// Kinder-Ansicht auf dem Handy: Zugangsdaten und Spielzeit von Mia.
		const { context, page } = await session(browser, 'mia', MOBILE)
		await shot(page, 'mobile')
		await context.close()
	},
}

const wanted = process.argv.slice(2)
const names = wanted.length > 0 ? wanted : Object.keys(SHOTS)
mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
try {
	for (const name of names) {
		if (!SHOTS[name]) {
			throw new Error(`unbekanntes Bild: ${name}`)
		}
		await SHOTS[name](browser)
	}
} finally {
	await browser.close()
}
