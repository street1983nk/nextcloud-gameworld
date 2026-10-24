// Small i18n runtime for the Gameworld UI (D-25), without any runtime dependency.
//
// Pure module: no Vue and no Nextcloud package import, so the Node checks under
// frontend/tests run without a browser. main.js sets the language once from the
// Nextcloud account language before the app mounts.
//
// Nothing here resolves a text at import time: t and tn look the key up on every
// call, so setLanguage takes effect before the first render even though ES
// modules are evaluated on import.
import de from './de/index.js'
import en from './en/index.js'
import fr from './fr/index.js'

export { mergeAreas } from './merge.js'

export const SUPPORTED_LANGUAGES = Object.freeze(['de', 'en', 'fr'])
export const FALLBACK_LANGUAGE = 'en'

const DATE_LOCALES = Object.freeze({ de: 'de-DE', en: 'en-GB', fr: 'fr-FR' })
const PLACEHOLDER = /\{([a-zA-Z0-9_]+)\}/g

// Language code before the first "_" or "-", lower case; anything but de, en
// and fr (also empty or missing values) becomes the fallback. "de_DE" (the
// formal German variant in Nextcloud) gets the same informal texts as "de".
export function normalizeLanguage(raw) {
	if (typeof raw !== 'string') {
		return FALLBACK_LANGUAGE
	}
	const code = raw.split(/[_-]/)[0].trim().toLowerCase()
	return SUPPORTED_LANGUAGES.includes(code) ? code : FALLBACK_LANGUAGE
}

// Inserts {name} placeholders as plain text; missing parameters stay visible
// as {name}. The result is never parsed as HTML (Vue text interpolation only).
function fill(template, params) {
	return template.replace(PLACEHOLDER, (match, name) => (
		params && Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
	))
}

// French uses the singular for 0 and 1, German and English only for 1.
function pluralForm(language, count) {
	if (language === 'fr') {
		return count === 0 || count === 1 ? 'one' : 'other'
	}
	return count === 1 ? 'one' : 'other'
}

// Builds an independent translator over the given dictionaries
// ({ de: {...}, en: {...}, fr: {...} }); the Node checks use it with test tables.
export function createTranslator(dictionaries) {
	let language = FALLBACK_LANGUAGE

	function lookup(key) {
		const own = dictionaries[language]
		if (own && Object.prototype.hasOwnProperty.call(own, key)) {
			return own[key]
		}
		const fallback = dictionaries[FALLBACK_LANGUAGE]
		if (fallback && Object.prototype.hasOwnProperty.call(fallback, key)) {
			return fallback[key]
		}
		return key
	}

	return Object.freeze({
		setLanguage(lang) {
			language = normalizeLanguage(lang)
		},
		currentLanguage() {
			return language
		},
		t(key, params = {}) {
			return fill(lookup(key), params)
		},
		tn(key, count, params = {}) {
			return fill(lookup(`${key}.${pluralForm(language, count)}`), { ...params, count })
		},
		compareText(a, b) {
			return String(a).localeCompare(String(b), language)
		},
		dateLocale() {
			return DATE_LOCALES[language] ?? DATE_LOCALES[FALLBACK_LANGUAGE]
		},
	})
}

const runtime = createTranslator({ de, en, fr })

export function setLanguage(lang) {
	runtime.setLanguage(lang)
}

export function currentLanguage() {
	return runtime.currentLanguage()
}

export function t(key, params = {}) {
	return runtime.t(key, params)
}

export function tn(key, count, params = {}) {
	return runtime.tn(key, count, params)
}

export function compareText(a, b) {
	return runtime.compareText(a, b)
}

export function dateLocale() {
	return runtime.dateLocale()
}
