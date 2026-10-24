// Structure check for the UI dictionaries (D-25): node frontend/tests/i18n.check.mjs
//
// Runs the same validate() over a deliberately broken test table first (positive
// control: every error type a to j must be found), then over the real
// dictionaries under frontend/src/i18n (no error allowed). The runtime cases of
// frontend/src/i18n/index.js follow at the end.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import {
	FALLBACK_LANGUAGE,
	SUPPORTED_LANGUAGES,
	createTranslator,
	currentLanguage,
	dateLocale,
	mergeAreas,
	normalizeLanguage,
	setLanguage,
	t,
} from '../src/i18n/index.js'

const LANGUAGES = ['de', 'en', 'fr']
const AREAS = ['core', 'parent', 'admin', 'kids', 'world']
const PLACEHOLDER = /\{[a-zA-Z0-9_]+\}/g
const DASHES = ['–', '—']
const EMOJI = /\p{Extended_Pictographic}/u
// Same list as tests/test_frontend_privacy.py (ZUGANG-01), written out on purpose.
const FORBIDDEN = ['announce', 'serverlist', 'public', 'visibility', 'öffentlich machen', 'sichtbar machen']
// French words written without their accents.
const FRENCH_ASCII = [
	'a partir', 'ete', 'reessayer', 'ecran', 'deja', 'creer', 'cree', 'parametres', 'acces', 'regle',
	'deconnecte', 'telecharger', 'evenement', 'probleme', 'etre', 'fenetre', 'selectionne', 'general', 'reglage',
]
const FRENCH_ASCII_RE = new RegExp(`(?<!\\p{L})(${FRENCH_ASCII.join('|')})(?!\\p{L})`, 'iu')
// French typography: a narrow or normal no-break space before ? ! ; : and inside « ».
const FRENCH_PUNCT_RE = /(?<![  \d])[?!;:]|«(?![  ])|(?<![  ])»/u

function fileOf(lang, area) {
	return `frontend/src/i18n/${lang}/${area}.js`
}

function placeholders(value) {
	return [...new Set(value.match(PLACEHOLDER) ?? [])].sort()
}

// tables: { de: { core: {...}, ... }, en: {...}, fr: {...} }; exceptions: list of
// { file, key, reason }. Returns a list of { type, message } (type a to j).
export function validate(tables, exceptions) {
	const errors = []
	const fail = (type, message) => errors.push({ type, message })

	for (const area of AREAS) {
		const base = tables.de?.[area] ?? {}
		// (a) identical key sets per area
		for (const lang of LANGUAGES) {
			const keys = new Set(Object.keys(tables[lang]?.[area] ?? {}))
			for (const other of LANGUAGES) {
				for (const key of Object.keys(tables[other]?.[area] ?? {})) {
					if (!keys.has(key)) {
						fail('a', `${fileOf(lang, area)}: missing key ${key} (present in ${other})`)
					}
				}
			}
		}
		for (const lang of LANGUAGES) {
			const table = tables[lang]?.[area] ?? {}
			for (const [key, value] of Object.entries(table)) {
				const where = `${fileOf(lang, area)} ${key}`
				if (typeof value !== 'string' || value.trim() === '') {
					// (c) no empty values
					fail('c', `${where}: empty value`)
					continue
				}
				// (b) same placeholders as the German value
				if (lang !== 'de' && typeof base[key] === 'string'
					&& placeholders(base[key]).join(',') !== placeholders(value).join(',')) {
					fail('b', `${where}: placeholders ${placeholders(value)} differ from de ${placeholders(base[key])}`)
				}
				// (d) no en dash or em dash
				if (DASHES.some((dash) => value.includes(dash))) {
					fail('d', `${where}: contains a dash U+2013/U+2014`)
				}
				// (e) no emojis
				if (EMOJI.test(value)) {
					fail('e', `${where}: contains an emoji`)
				}
				// (f) plural pairs
				if (key.endsWith('.one') && !Object.hasOwn(table, `${key.slice(0, -4)}.other`)) {
					fail('f', `${where}: .one without .other`)
				}
				if (key.endsWith('.other') && !Object.hasOwn(table, `${key.slice(0, -6)}.one`)) {
					fail('f', `${where}: .other without .one`)
				}
				// (g) wording that would promise an open world (ZUGANG-01)
				const lower = value.toLowerCase()
				for (const term of FORBIDDEN) {
					if (lower.includes(term)) {
						fail('g', `${where}: forbidden term ${JSON.stringify(term)}`)
					}
				}
				if (lang === 'fr') {
					// (h) French words without accents
					const ascii = value.match(FRENCH_ASCII_RE)
					if (ascii) {
						fail('h', `${where}: French without accents ${JSON.stringify(ascii[0])}`)
					}
					// (j) no-break space before ? ! ; : and inside guillemets
					if (FRENCH_PUNCT_RE.test(value)) {
						fail('j', `${where}: French punctuation without no-break space`)
					}
				}
			}
		}
	}

	// (i) en or fr equal to de only with an exception entry, and every entry must still match
	const listed = new Set()
	for (const entry of exceptions) {
		const id = `${entry?.file} ${entry?.key}`
		listed.add(id)
		const match = /^frontend\/src\/i18n\/(en|fr)\/([a-z]+)\.js$/.exec(String(entry?.file))
		if (!match || typeof entry.reason !== 'string' || entry.reason.trim() === '') {
			fail('i', `exception ${id}: needs an en/fr dictionary file and a reason`)
			continue
		}
		const [, lang, area] = match
		const value = tables[lang]?.[area]?.[entry.key]
		const german = tables.de?.[area]?.[entry.key]
		if (value === undefined || german === undefined) {
			fail('i', `exception ${id}: key does not exist`)
		} else if (value !== german) {
			fail('i', `exception ${id}: values are no longer equal`)
		}
	}
	for (const area of AREAS) {
		for (const lang of ['en', 'fr']) {
			for (const [key, value] of Object.entries(tables[lang]?.[area] ?? {})) {
				if (value === tables.de?.[area]?.[key] && !listed.has(`${fileOf(lang, area)} ${key}`)) {
					fail('i', `${fileOf(lang, area)} ${key}: same as de without an exception entry`)
				}
			}
		}
	}
	return errors
}

// Positive control: one broken table that contains every error type.
const broken = {
	de: {
		core: {
			'core.x.missing': 'Fehlt in fr',
			'core.x.place': 'Hallo {name}',
			'core.x.dash': 'Gut',
			'core.x.ascii': 'Ab morgen',
			'core.x.same': 'Gameworld Text',
			'core.x.empty': 'Leer',
			'core.x.emoji': 'Bild',
			'core.x.plural.one': 'Eins',
			'core.x.term': 'Welt',
			'core.x.punct': 'Frage?',
		},
	},
	en: {
		core: {
			'core.x.missing': 'Missing in fr',
			'core.x.place': 'Hello {who}',
			'core.x.dash': `Good ${DASHES[1]} fine`,
			'core.x.ascii': 'From tomorrow',
			'core.x.same': 'Gameworld Text',
			'core.x.empty': ' ',
			'core.x.emoji': 'Picture \u{1F600}',
			'core.x.plural.one': 'One',
			'core.x.term': 'Make it public',
			'core.x.punct': 'Question?',
		},
	},
	fr: {
		core: {
			'core.x.place': 'Bonjour {name}',
			'core.x.dash': 'Bien',
			'core.x.ascii': 'a partir de demain',
			'core.x.same': 'Texte Gameworld',
			'core.x.empty': 'Vide',
			'core.x.emoji': 'Image',
			'core.x.plural.one': 'Un',
			'core.x.term': 'Monde',
			'core.x.punct': 'Question ?',
		},
	},
}
const brokenExceptions = [{ file: 'frontend/src/i18n/en/core.js', key: 'core.x.gone', reason: 'stale entry' }]
const found = validate(broken, brokenExceptions)
const foundTypes = new Set(found.map((error) => error.type))
for (const type of ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j']) {
	assert.ok(foundTypes.has(type), `positive control: error type ${type} not detected`)
}
// Both directions of (i): unexplained equal value and stale exception entry.
assert.ok(found.some((error) => error.type === 'i' && error.message.includes('core.x.same')), 'equal value not detected')
assert.ok(found.some((error) => error.type === 'i' && error.message.includes('core.x.gone')), 'stale exception not detected')
// Narrow no-break space and digits before ":" are accepted.
assert.equal(validate({ de: { core: { 'core.y': 'a' } }, en: { core: { 'core.y': 'b' } }, fr: { core: { 'core.y': 'c ? « d » 10:00' } } }, []).length, 0)
console.log(`i18n.check: positive control found all error types a to j (${found.length} errors)`)

// Real dictionaries
const tables = {}
for (const lang of LANGUAGES) {
	tables[lang] = {}
	for (const area of AREAS) {
		tables[lang][area] = (await import(`../src/i18n/${lang}/${area}.js`)).default
	}
}
const exceptions = JSON.parse(await readFile(new URL('./i18n.exceptions.json', import.meta.url), 'utf8'))
assert.ok(Array.isArray(exceptions), 'i18n.exceptions.json must be an array')
const realErrors = validate(tables, exceptions)
assert.deepEqual(realErrors.map((error) => error.message), [], 'dictionary errors')
for (const area of AREAS) {
	console.log(`i18n.check: ${area}: ${Object.keys(tables.de[area]).length} keys in de, en and fr`)
}

// Language indexes merge all areas
for (const lang of LANGUAGES) {
	const merged = (await import(`../src/i18n/${lang}/index.js`)).default
	const expected = AREAS.reduce((sum, area) => sum + Object.keys(tables[lang][area]).length, 0)
	assert.equal(Object.keys(merged).length, expected)
	assert.ok(Object.isFrozen(merged))
}
assert.throws(() => mergeAreas({ core: { 'core.a': '1' }, parent: { 'core.a': '2' } }), /duplicate key core\.a/)
assert.throws(() => mergeAreas({ core: { 'parent.a': '1' } }), /parent\.a/)
assert.deepEqual(mergeAreas({ core: { 'core.a': '1' }, parent: { 'parent.a': '2' } }), { 'core.a': '1', 'parent.a': '2' })

// normalizeLanguage
assert.deepEqual([...SUPPORTED_LANGUAGES], ['de', 'en', 'fr'])
assert.equal(FALLBACK_LANGUAGE, 'en')
const cases = [
	['de_DE', 'de'], ['de-CH', 'de'], ['de', 'de'], ['DE', 'de'], ['en_GB', 'en'], ['fr', 'fr'], ['fr-CA', 'fr'],
	['es', 'en'], ['pt_BR', 'en'], ['', 'en'], [null, 'en'], [undefined, 'en'], [42, 'en'], ['<script>', 'en'],
]
for (const [raw, expected] of cases) {
	assert.equal(normalizeLanguage(raw), expected, String(raw))
}

// Translator over a test table
const tr = createTranslator({
	de: { 'x.a': 'A de', 'x.name': 'Hallo {name}', 'x.n.one': '{count} Kind', 'x.n.other': '{count} Kinder' },
	en: { 'x.a': 'A en', 'x.only': 'only en', 'x.name': 'Hello {name}', 'x.n.one': '{count} child', 'x.n.other': '{count} children' },
	fr: { 'x.a': 'A fr', 'x.name': 'Bonjour {name}', 'x.n.one': '{count} enfant', 'x.n.other': '{count} enfants' },
})
assert.equal(tr.currentLanguage(), 'en')
tr.setLanguage('fr')
assert.equal(tr.currentLanguage(), 'fr')
assert.equal(tr.t('x.a'), 'A fr')
assert.equal(tr.t('x.only'), 'only en')
assert.equal(tr.t('x.unknown'), 'x.unknown')
assert.equal(tr.t('x.name', { name: 'Mia' }), 'Bonjour Mia')
assert.equal(tr.t('x.name', { name: '<b>' }), 'Bonjour <b>')
assert.equal(tr.t('x.name', { name: '$&$1' }), 'Bonjour $&$1')
assert.equal(tr.t('x.name'), 'Bonjour {name}')
assert.equal(tr.t('x.name', { other: 1 }), 'Bonjour {name}')
assert.equal(tr.tn('x.n', 0), '0 enfant')
assert.equal(tr.tn('x.n', 1), '1 enfant')
assert.equal(tr.tn('x.n', 2), '2 enfants')
tr.setLanguage('de_DE')
assert.equal(tr.tn('x.n', 0), '0 Kinder')
assert.equal(tr.tn('x.n', 1), '1 Kind')
assert.equal(tr.tn('x.n', 2), '2 Kinder')
assert.equal(tr.dateLocale(), 'de-DE')
assert.ok(tr.compareText('äpfel', 'birne') < 0)
tr.setLanguage('en')
assert.equal(tr.tn('x.n', 0), '0 children')
assert.equal(tr.tn('x.n', 1), '1 child')
assert.equal(tr.tn('x.n', 2, { count: 99 }), '2 children')
assert.equal(tr.dateLocale(), 'en-GB')
tr.setLanguage('xx')
assert.equal(tr.currentLanguage(), 'en')
tr.setLanguage('fr')
assert.equal(tr.dateLocale(), 'fr-FR')

// Runtime instance: unknown keys come back as the key, language switches are kept.
setLanguage('fr_FR')
assert.equal(currentLanguage(), 'fr')
assert.equal(dateLocale(), 'fr-FR')
assert.equal(t('core.does.not.exist'), 'core.does.not.exist')
setLanguage('es')
assert.equal(currentLanguage(), 'en')

console.log('i18n.check: all checks passed')
