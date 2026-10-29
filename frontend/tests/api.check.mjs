// Check script for frontend/src/api.js (without browser): node frontend/tests/api.check.mjs
// IN-08: every state-changing request goes out as JSON via post/del.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const source = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')

// No direct axios.post/put/patch/delete any more outside the two helpers.
const direct = [...source.matchAll(/axios\.(post|put|patch|delete)\(/g)].map((m) => m.index)
const helpers = [source.indexOf('export function post('), source.indexOf('export function del(')]
assert.ok(helpers.every((index) => index >= 0), 'Helfer post und del fehlen')
assert.equal(direct.length, 2, `direkte axios-Aufrufe: ${direct.length}`)
for (const index of direct) {
	assert.ok(helpers.some((start) => index > start && index - start < 200), 'axios-Aufruf außerhalb der Helfer')
}
// Both helpers set Content-Type application/json, del sends an empty JSON body.
assert.match(source, /'Content-Type': 'application\/json'/)
assert.match(source, /axios\.delete\(url, \{ data: \{\}, headers:/)
assert.match(source, /axios\.post\(url, data, \{ headers:/)
// All changes go through post( or del(.
assert.ok((source.match(/await post\(/g) ?? []).length >= 15)
assert.ok((source.match(/await del\(/g) ?? []).length >= 4)

// Browser spike 04.2: status and ticket are exported, the ticket goes through post()
// (JSON requirement, IN-08) to /api/my/play-ticket, no own fetch.
assert.match(source, /export function getPlayStatus\(/)
assert.match(source, /export async function getPlayTicket\(worldId\)/)
const ticketFn = source.slice(source.indexOf('export async function getPlayTicket('))
const ticketBody = ticketFn.slice(0, ticketFn.indexOf('\n}\n'))
assert.match(ticketBody, /await post\(`\$\{apiBase\}\/api\/my\/play-ticket`/)
assert.doesNotMatch(source, /\bfetch\(/, 'kein eigener fetch in api.js')

// World language (D-27): POST with JSON body {language} to /api/worlds/{id}/language.
assert.match(source, /export async function setWorldLanguage\(worldId, language\)/)
const langFn = source.slice(source.indexOf('export async function setWorldLanguage('))
const langBody = langFn.slice(0, langFn.indexOf('\n}\n'))
assert.match(langBody, /await post\(`\$\{apiBase\}\/api\/worlds\/\$\{encodeURIComponent\(worldId\)\}\/language`, \{ language \}\)/)
assert.doesNotMatch(langBody, /await del\(/)

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
