// Check script for frontend/src/origin.js (without browser): node frontend/tests/origin.check.mjs
import assert from 'node:assert/strict'

const { DISMISS_KEY, originQuestion, readDismissed, rememberDismissed } = await import('../src/origin.js')
const { setLanguage, t } = await import('../src/i18n/index.js')

setLanguage('de')

const ask = { origin: 'https://cloud.example', proposed: 'http://192.168.1.10', saved: false, confirm_needed: true }

// Question only on confirm_needed
assert.deepEqual(originQuestion(ask, null), { current: 'https://cloud.example', proposed: 'http://192.168.1.10' })
assert.equal(originQuestion({ ...ask, confirm_needed: false }, null), null)
assert.equal(originQuestion({ ...ask, confirm_needed: 'true' }, null), null)
assert.equal(originQuestion({ ...ask, saved: true, confirm_needed: false }, null), null)
// Broken or missing response: no question
assert.equal(originQuestion(null, null), null)
assert.equal(originQuestion(undefined, null), null)
assert.equal(originQuestion({ ...ask, origin: null }, null), null)
assert.equal(originQuestion({ ...ask, proposed: 42 }, null), null)
// Already answered with "Nein": do not ask again, but a different new address does ask
assert.equal(originQuestion(ask, 'http://192.168.1.10'), null)
assert.deepEqual(originQuestion(ask, 'http://anders.example'), { current: 'https://cloud.example', proposed: 'http://192.168.1.10' })

// Storage
const map = new Map()
const storage = { getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, v) }
assert.equal(readDismissed(storage), null)
rememberDismissed(storage, 'http://192.168.1.10')
assert.equal(map.get(DISMISS_KEY), 'http://192.168.1.10')
assert.equal(readDismissed(storage), 'http://192.168.1.10')
// Without or with broken storage: no error
const broken = { getItem: () => { throw new Error('gesperrt') }, setItem: () => { throw new Error('voll') } }
assert.equal(readDismissed(broken), null)
assert.equal(readDismissed(null), null)
rememberDismissed(broken, 'x')
rememberDismissed(null, 'x')

// English and French (D-25): origin.js itself has no visible text, the question data
// stay the same in every language; the shared fallback text of the request helpers
// is translated.
for (const lang of ['en', 'fr']) {
	setLanguage(lang)
	assert.deepEqual(originQuestion(ask, null), { current: 'https://cloud.example', proposed: 'http://192.168.1.10' })
}
setLanguage('en')
assert.equal(t('core.api.requestFailed'), 'The request to Gameworld failed.')
setLanguage('fr')
assert.equal(t('core.api.requestFailed'), 'La requête vers Gameworld a échoué.')
setLanguage('de')

console.log('origin.check: alle Prüfungen bestanden')
