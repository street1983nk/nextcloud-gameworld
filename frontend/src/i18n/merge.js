// Merges the per-area dictionaries of one language into a single flat table.
//
// Lives in its own module so the language indexes (de/en/fr/index.js) do not
// import the runtime in i18n/index.js, which imports them in turn.

// areas: { core: {...}, parent: {...}, ... }. Every key must start with its
// area prefix and may appear only once across all areas; a violation throws
// at import time so a broken dictionary never reaches the page.
export function mergeAreas(areas) {
	const merged = {}
	for (const [area, table] of Object.entries(areas)) {
		for (const [key, value] of Object.entries(table)) {
			if (Object.prototype.hasOwnProperty.call(merged, key)) {
				throw new Error(`i18n: duplicate key ${key}`)
			}
			if (!key.startsWith(`${area}.`)) {
				throw new Error(`i18n: key ${key} does not start with its area prefix ${area}.`)
			}
			merged[key] = value
		}
	}
	return Object.freeze(merged)
}
