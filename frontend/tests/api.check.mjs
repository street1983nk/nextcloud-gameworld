// Prüfskript für frontend/src/api.js (ohne Browser): node frontend/tests/api.check.mjs
// IN-08: Jede zustandsändernde Anfrage geht als JSON über post/del.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')

// Kein direkter axios.post/put/patch/delete mehr außerhalb der beiden Helfer.
const direct = [...source.matchAll(/axios\.(post|put|patch|delete)\(/g)].map((m) => m.index)
const helpers = [source.indexOf('export function post('), source.indexOf('export function del(')]
assert.ok(helpers.every((index) => index >= 0), 'Helfer post und del fehlen')
assert.equal(direct.length, 2, `direkte axios-Aufrufe: ${direct.length}`)
for (const index of direct) {
	assert.ok(helpers.some((start) => index > start && index - start < 200), 'axios-Aufruf außerhalb der Helfer')
}
// Beide Helfer setzen Content-Type application/json, del schickt einen leeren JSON-Körper.
assert.match(source, /'Content-Type': 'application\/json'/)
assert.match(source, /axios\.delete\(url, \{ data: \{\}, headers:/)
assert.match(source, /axios\.post\(url, data, \{ headers:/)
// Alle Änderungen laufen über post( oder del(.
assert.ok((source.match(/await post\(/g) ?? []).length >= 15)
assert.ok((source.match(/await del\(/g) ?? []).length >= 4)

// Browser-Spike 04.2: Status und Ticket sind exportiert, das Ticket läuft über post()
// (JSON-Pflicht, IN-08) an /api/my/play-ticket, kein eigener fetch.
assert.match(source, /export function getPlayStatus\(/)
assert.match(source, /export async function getPlayTicket\(worldId\)/)
const ticketFn = source.slice(source.indexOf('export async function getPlayTicket('))
const ticketBody = ticketFn.slice(0, ticketFn.indexOf('\n}\n'))
assert.match(ticketBody, /await post\(`\$\{apiBase\}\/api\/my\/play-ticket`/)
assert.doesNotMatch(source, /\bfetch\(/, 'kein eigener fetch in api.js')

// errorText (D-25): the own fallback comes from the dictionary, a backend detail stays unchanged.
assert.match(source, /import \{ t \} from '\.\/i18n\/index\.js'/)
const errorFn = source.slice(source.indexOf('export function errorText('))
const errorBody = errorFn.slice(0, errorFn.indexOf('\n}\n'))
assert.match(errorBody, /return detail\n/)
assert.match(errorBody, /return t\('core\.api\.requestFailed'\)/)
assert.doesNotMatch(source, /Die Anfrage an Gameworld ist fehlgeschlagen/)
const { setLanguage, t } = await import('../src/i18n/index.js')
setLanguage('de')
assert.equal(t('core.api.requestFailed'), 'Die Anfrage an Gameworld ist fehlgeschlagen.')
setLanguage('en')
assert.equal(t('core.api.requestFailed'), 'The request to Gameworld failed.')
setLanguage('fr')
assert.equal(t('core.api.requestFailed'), 'La requête vers Gameworld a échoué.')

console.log('api.check: alle Prüfungen bestanden')
