// Prüfskript für frontend/src/orphans.js (rein, ohne Vue): node frontend/tests/orphans.check.mjs
// Texte wörtlich aus 06-UI-SPEC.md B3.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { formatDate } from '../src/backup.js'
import {
	CLEANUP_DOCS_URL,
	EMPTY_TEXT,
	INTRO_TEXT,
	LIFECYCLE_TEXT,
	SCRIPT_SEGMENTS,
	SCRIPT_TEXT,
	containerMeta,
	containerQuestion,
	inUseText,
	removedText,
	unavailableText,
	volumeMeta,
	volumeQuestion,
} from '../src/orphans.js'

assert.equal(CLEANUP_DOCS_URL, 'https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#cleanup')

assert.equal(
	containerQuestion('gw-x'),
	'Container »gw-x« stoppen und entfernen? Wer darauf spielt, wird getrennt. Der Spielstand bleibt erhalten.',
)
assert.equal(
	volumeQuestion('gameworld-a-b'),
	'Spielstand »gameworld-a-b« endgültig löschen? Die Welt und alles Gebaute darin sind danach weg, Gameworld kann das nicht rückgängig machen. Sicherungen in deinen Nextcloud-Dateien bleiben.',
)

const iso = '2026-10-20T08:15:00Z'
assert.equal(containerMeta({ state: 'exited', created: iso }), `Stand: gestoppt, angelegt ${formatDate(iso)}`)
assert.equal(containerMeta({ state: 'running', created: iso }), `Stand: läuft, angelegt ${formatDate(iso)}`)
assert.equal(containerMeta({ state: 'created', created: iso }), `Stand: gestoppt, angelegt ${formatDate(iso)}`)
// Docker kann created leer liefern (06-08): dann ohne Datumsteil.
assert.equal(containerMeta({ state: 'running', created: '' }), 'Stand: läuft')
assert.equal(volumeMeta({ created: iso }), `angelegt ${formatDate(iso)}`)
assert.equal(volumeMeta({ created: '' }), '')

assert.equal(removedText('container', 'x'), 'Container x entfernt.')
assert.equal(removedText('volume', 'x'), 'Spielstand x gelöscht.')
assert.equal(inUseText('x'), 'Der Spielstand x wird noch von einem Container benutzt. Entferne zuerst den Container.')
assert.equal(
	unavailableText('Fehler'),
	'Die Suche nach Resten ist gerade nicht möglich: Fehler Der Setup-Check oben zeigt, was fehlt.',
)

assert.equal(
	EMPTY_TEXT,
	'Keine Reste gefunden. Alles, was Gameworld auf diesem Server angelegt hat, gehört zu einer Welt in der Liste oben.',
)
assert.equal(
	INTRO_TEXT,
	'Hier stehen Welt-Container und Spielstände, die Gameworld angelegt hat, die aber zu keiner Welt dieser Installation gehören. Das passiert zum Beispiel nach einer Neuinstallation mit gelöschten App-Daten. Gameworld fasst nur eigene Container und Spielstände an.',
)
assert.equal(
	LIFECYCLE_TEXT,
	'Beim Deaktivieren und bei jedem Update der App stoppt Gameworld alle Welten und entfernt ihre Container. Wer gerade spielt, wird kurz getrennt. Spielstände und Sicherungen bleiben, danach baut Gameworld die Welten von selbst wieder auf.',
)
assert.equal(
	SCRIPT_TEXT,
	'Nach dem Deinstallieren gibt es diese Liste nicht mehr. Dann hilft das Skript gameworld-orphans.sh auf dem Docker-Host: Es zeigt Reste nur an und löscht sie erst mit --remove-containers oder --remove-volumes.',
)
// Die Darstellung mit code-Elementen ergibt denselben Text.
assert.equal(SCRIPT_SEGMENTS.map((part) => part.text).join(''), SCRIPT_TEXT)
assert.deepEqual(
	SCRIPT_SEGMENTS.filter((part) => part.code).map((part) => part.text),
	['gameworld-orphans.sh', '--remove-containers', '--remove-volumes'],
)

// Keine Gedankenstriche und keine Ersatz-Umlaute in den Texten.
const source = await readFile(new URL('../src/orphans.js', import.meta.url), 'utf8')
assert.doesNotMatch(source, /[–—]/)

// api.js: drei Aufrufe gegen die 06-08-Routen, Änderungen über post().
const api = await readFile(new URL('../src/api.js', import.meta.url), 'utf8')
assert.match(api, /export async function listOrphans\(\)/)
assert.match(api, /axios\.get\(`\$\{apiBase\}\/api\/admin\/orphans`\)/)
assert.match(api, /export async function removeOrphanContainer\(id\)/)
assert.match(api, /await post\(`\$\{apiBase\}\/api\/admin\/orphans\/container\/remove`, \{ id \}\)/)
assert.match(api, /export async function removeOrphanVolume\(name\)/)
assert.match(api, /await post\(`\$\{apiBase\}\/api\/admin\/orphans\/volume\/remove`, \{ name \}\)/)

// OrphanSection.vue (sobald vorhanden): kein v-html, kein Polling, Link mit rel.
const vue = await readFile(new URL('../src/components/OrphanSection.vue', import.meta.url), 'utf8').catch(() => null)
if (vue !== null) {
	assert.doesNotMatch(vue, /v-html|setInterval/)
	assert.match(vue, /rel="noopener noreferrer"/)
	assert.match(vue, /Container \$\{.*\} entfernen/)
	assert.match(vue, /Spielstand \$\{.*\} endgültig löschen/)
	assert.match(vue, /aria-label="Reste erneut suchen"/)
	assert.match(vue, /listOrphans/)
	assert.match(vue, /\.focus\(\)/)
}

console.log('orphans.check: alle Prüfungen bestanden')
