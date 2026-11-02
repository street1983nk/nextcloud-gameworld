// Foreign-word detector for the language audit.
//
// Vocabulary per language = all words of the frontend dictionary
// (frontend/src/i18n/<lang>/index.js) plus all server texts of that language
// (server.json from scripts/audit/dump_catalog.py). A word is "exclusive" for a
// language if no other audited language uses it. foreign(text, lang) reports
// every word of text that is exclusive to ANOTHER language, i.e. a word that
// should not appear in a text shown in `lang`.
import { readFileSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { join, resolve } from 'node:path'

// Words with at least four characters (letters, apostrophes, hyphens).
const WORD = /[\p{L}][\p{L}'’-]{3,}/gu
export const words = (text) => new Set((String(text).match(WORD) ?? []).map((w) => w.toLowerCase().replace(/[’']/g, "'")))

// Data, not UI text: these words come from instance data and are never translated.
const DATA_GROUPS = {
	// World names of the dev instance and of the demo data (de/en/fr demo worlds).
	worlds: 'Baumhaus Inselabenteuer Treehouse Island adventure La cabane Île aux aventures audit261102',
	// Game and product names.
	products: 'Browser Minetest VoxeLibre Nextcloud Gameworld Luanti Talk MineClone',
	// Account names, display names and Nextcloud group IDs of the dev instance
	// ("eltern" verified 02.11.2026: group ID in the manager-groups list, not UI text).
	accounts: 'mama oma mamie maman grandma mom leo mia Kind Frau Weber Familie Family Famille klasse lehrkraefte eltern parents gw-lehrer gw-kind admin localhost',
	// Language names in their own language (language switch, world language select).
	languages: 'Deutsch English Français',
	// Time zone names (IANA ids are data).
	timezones: 'Berlin Europe Paris London',
}
export const DATA = words(Object.values(DATA_GROUPS).join(' '))

let LANGS = []
let exclusive = {}

/**
 * Build the vocabularies.
 * @param {string} repo repository root
 * @param {string} serverJsonPath path of server.json
 * @param {string[]} langs audited languages
 * @returns {Promise<{[lang: string]: number}>} number of exclusive words per language
 */
export async function loadVocab(repo, serverJsonPath, langs = ['de', 'en', 'fr']) {
	LANGS = langs
	const server = JSON.parse(readFileSync(serverJsonPath, 'utf8'))
	const vocab = {}
	for (const lang of LANGS) {
		const url = pathToFileURL(join(resolve(repo), 'frontend', 'src', 'i18n', lang, 'index.js'))
		const dict = (await import(url.href)).default
		vocab[lang] = words(Object.values(dict).join(' ') + ' ' + (server[lang] ?? []).join(' '))
	}
	exclusive = {}
	for (const lang of LANGS) {
		exclusive[lang] = new Set([...vocab[lang]].filter((w) => !LANGS.some((o) => o !== lang && vocab[o].has(w))))
	}
	return Object.fromEntries(LANGS.map((l) => [l, exclusive[l].size]))
}

/**
 * Words of `text` that belong exclusively to another language.
 * @returns {{[otherLang: string]: string[]}} empty object when the text is clean
 */
export function foreign(text, lang) {
	const hits = {}
	for (const w of words(text)) {
		if (DATA.has(w)) continue
		for (const o of LANGS) {
			if (o !== lang && exclusive[o]?.has(w)) (hits[o] ??= new Set()).add(w)
		}
	}
	return Object.fromEntries(Object.entries(hits).map(([k, v]) => [k, [...v]]))
}
