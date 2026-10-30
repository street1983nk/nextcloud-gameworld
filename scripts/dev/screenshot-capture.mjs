// Store screenshots (06-13, D-10, D-25) with Playwright against the dev stack.
//
// Prerequisite: sh scripts/dev/screenshot-demo.sh --lang <de|en|fr> (demo accounts
// of that language, e.g. mama, oma, mia, leo for de, in that account language and
// the two demo worlds of that language; world IDs per language in
// .dev/screenshot-demo.json). Playwright is
// not a project dependency: the package comes from an existing npx cache via
// NODE_PATH, e.g.
//   NODE_PATH=<npx-cache>/node_modules node scripts/dev/screenshot-capture.mjs [--lang de|en|fr] [name ...]
// Without names, all six images are created in docs/screenshots/ (-v1, the
// store mirror never reloads an image). The file name carries the language:
// de without suffix (worlds-v1.png), en and fr with -en / -fr (worlds-v1-en.png).
// Button labels come from the frontend dictionary of the language, so the capture
// clicks exactly what the account sees.
//
// Only demo data on the images: other worlds and accounts of the dev instance
// (running dev worlds of the owner, dev account gw-kind) are hidden by the capture
// by filtering responses of the Gameworld API in the browser down to the demo world IDs and
// demo accounts. Nothing is invented, only left out; the instance
// itself stays untouched. Only replacement: without a configured
// player address (join_host empty, host null in /api/my/worlds) the
// kid view shows the computer name of the browser, i.e. "localhost". The capture
// puts the example name DEMO_HOST there, as a configured
// player address would, without changing the stored setting.
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
const LANGUAGES = { de: { suffix: '', locale: 'de-DE' }, en: { suffix: '-en', locale: 'en-US' }, fr: { suffix: '-fr', locale: 'fr-FR' } }

const args = process.argv.slice(2)
let lang = 'de'
const wanted = []
for (let i = 0; i < args.length; i++) {
	if (args[i] === '--lang') {
		lang = args[++i]
	} else if (args[i].startsWith('--lang=')) {
		lang = args[i].slice('--lang='.length)
	} else {
		wanted.push(args[i])
	}
}
if (!LANGUAGES[lang]) {
	throw new Error(`--lang must be de, en or fr, not ${lang}`)
}
const { suffix: SUFFIX, locale: LOCALE } = LANGUAGES[lang]
const T = (await import(new URL(`../../frontend/src/i18n/${lang}/index.js`, import.meta.url))).default
function label(key) {
	if (!(key in T)) {
		throw new Error(`missing dictionary key ${key} (${lang})`)
	}
	return T[key]
}

const DEMO = JSON.parse(readFileSync(join(REPO, '.dev', 'screenshot-demo.json'), 'utf8'))
const ALLOWED = new Set(DEMO.by_lang?.[lang] ?? [])
if (ALLOWED.size !== 2) {
	throw new Error(`expected two demo worlds for ${lang}, run screenshot-demo.sh --lang ${lang} first`)
}
// Demo data per language, as created by screenshot-demo.sh: the parent manages, the
// family group is searched in the invite dialog, mia and leo are shared children.
const DEMO_SET = {
	de: { parent: 'mama', grandma: 'oma', family: 'Familie', firstWorld: 'Baumhaus' },
	en: { parent: 'mom', grandma: 'grandma', family: 'Family', firstWorld: 'Treehouse' },
	fr: { parent: 'maman', grandma: 'mamie', family: 'Famille', firstWorld: 'La cabane' },
}[lang]
const PARENT = DEMO_SET.parent
const FIRST_WORLD = DEMO_SET.firstWorld
const MIA = 'mia'
const password = (user) => `gameworld-demo-${user}-13`
const DEMO_USERS = new Set([PARENT, DEMO_SET.grandma, 'mia', 'leo'])
const DESKTOP = { width: 1280, height: 800 }
const MOBILE = { width: 390, height: 844 }

// Keeps only demo worlds in lists (key "worlds") and demo accounts (entries with nc_user).
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
		locale: LOCALE,
		timezoneId: 'Europe/Berlin',
		isMobile: viewport.width < 500,
		hasTouch: viewport.width < 500,
	})
	await context.route(/\/apps\/app_api\/proxy\/gameworld\/api\//, async (route) => {
		let response
		try {
			response = await route.fetch()
		} catch {
			// The 5 s fetch of the page is still running while the capture closes the context.
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
	await page.fill('#password', password(user))
	await Promise.all([page.waitForURL((url) => !url.pathname.endsWith('/login')), page.click('button[type=submit]')])
	await page.goto(APP)
	await page.waitForLoadState('networkidle')
	await page.waitForTimeout(1500)
	// No notification overlays on the images (toasts, status hints).
	await page.addStyleTag({ content: '.toastify, #notification-container, .notifications-button .notification__dot { display: none !important; }' })
	return { context, page }
}

async function shot(page, name) {
	const file = join(OUT, `${name}-v1${SUFFIX}.png`)
	await page.waitForTimeout(800)
	await page.screenshot({ path: file })
	console.log(`aufgenommen: docs/screenshots/${name}-v1${SUFFIX}.png`)
	await page.context().unrouteAll({ behavior: 'ignoreErrors' })
}

function row(page, worldName) {
	return page.locator('tr', { has: page.locator('td', { hasText: worldName }) }).first()
}

const SHOTS = {
	async worlds(browser) {
		const { context, page } = await session(browser, PARENT, DESKTOP)
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
		const { context, page } = await session(browser, PARENT, DESKTOP)
		await row(page, FIRST_WORLD).getByRole('button', { name: label('parent.common.invite') }).click()
		const dialog = page.getByRole('dialog').first()
		await dialog.waitFor()
		// Show the search open: the family group as a suggestion.
		await dialog.locator('input[type=search], input').first().click()
		// The whole display name, so that only the family group of this language is suggested.
		await page.keyboard.type(DEMO_SET.family, { delay: 80 })
		await page.getByRole('option', { name: new RegExp(DEMO_SET.family, 'i') }).first().waitFor({ timeout: 15000 })
		await shot(page, 'invite')
		await context.close()
	},
	async backups(browser) {
		const { context, page } = await session(browser, PARENT, DESKTOP)
		await row(page, FIRST_WORLD).getByRole('button', { name: label('parent.view.action.backups') }).click()
		await page.getByRole('dialog').first().waitFor()
		await page.locator('.backup-section__entry').first().waitFor({ timeout: 30000 })
		await shot(page, 'backups')
		await context.close()
	},
	async playtime(browser) {
		const { context, page } = await session(browser, PARENT, DESKTOP)
		const section = page.locator('section', { has: page.locator('h3', { hasText: label('kids.playtimeSection.title') }) }).first()
		await section.locator('li, tr', { hasText: MIA }).first().getByRole('button', { name: label('kids.playtimeSection.edit') }).click()
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
		// Kid view on the phone: credentials and playtime of Mia.
		const { context, page } = await session(browser, 'mia', MOBILE)
		await shot(page, 'mobile')
		await context.close()
	},
}

const names = wanted.length > 0 ? wanted : Object.keys(SHOTS)
mkdirSync(OUT, { recursive: true })
const browser = await chromium.launch()
try {
	for (const name of names) {
		if (!SHOTS[name]) {
			throw new Error(`unknown image: ${name}`)
		}
		await SHOTS[name](browser)
	}
} finally {
	await browser.close()
}
