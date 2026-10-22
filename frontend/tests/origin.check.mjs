// Prüfskript für frontend/src/origin.js (ohne Browser): node frontend/tests/origin.check.mjs
import assert from 'node:assert/strict'

const { DISMISS_KEY, originQuestion, readDismissed, rememberDismissed } = await import('../src/origin.js')

const ask = { origin: 'https://cloud.example', proposed: 'http://192.168.1.10', saved: false, confirm_needed: true }

// Rückfrage nur bei confirm_needed
assert.deepEqual(originQuestion(ask, null), { current: 'https://cloud.example', proposed: 'http://192.168.1.10' })
assert.equal(originQuestion({ ...ask, confirm_needed: false }, null), null)
assert.equal(originQuestion({ ...ask, confirm_needed: 'true' }, null), null)
assert.equal(originQuestion({ ...ask, saved: true, confirm_needed: false }, null), null)
// Kaputte oder fehlende Antwort: keine Rückfrage
assert.equal(originQuestion(null, null), null)
assert.equal(originQuestion(undefined, null), null)
assert.equal(originQuestion({ ...ask, origin: null }, null), null)
assert.equal(originQuestion({ ...ask, proposed: 42 }, null), null)
// Schon mit "Nein" beantwortet: nicht erneut fragen, eine andere neue Adresse aber schon
assert.equal(originQuestion(ask, 'http://192.168.1.10'), null)
assert.deepEqual(originQuestion(ask, 'http://anders.example'), { current: 'https://cloud.example', proposed: 'http://192.168.1.10' })

// Speicher
const map = new Map()
const storage = { getItem: (k) => (map.has(k) ? map.get(k) : null), setItem: (k, v) => map.set(k, v) }
assert.equal(readDismissed(storage), null)
rememberDismissed(storage, 'http://192.168.1.10')
assert.equal(map.get(DISMISS_KEY), 'http://192.168.1.10')
assert.equal(readDismissed(storage), 'http://192.168.1.10')
// Ohne oder mit kaputtem Speicher: kein Fehler
const broken = { getItem: () => { throw new Error('gesperrt') }, setItem: () => { throw new Error('voll') } }
assert.equal(readDismissed(broken), null)
assert.equal(readDismissed(null), null)
rememberDismissed(broken, 'x')
rememberDismissed(null, 'x')

console.log('origin.check: alle Prüfungen bestanden')
