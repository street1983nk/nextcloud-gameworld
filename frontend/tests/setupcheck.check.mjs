// Check script for SetupCheck.vue (without browser): node frontend/tests/setupcheck.check.mjs
// Owner-GO 02.11.2026: self re-check with a clean lifecycle, commands only from the backend,
// new texts in de, en and fr.
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

// Normalise line endings: with core.autocrlf the working tree may hold CRLF.
const source = (await readFile(new URL('../src/components/SetupCheck.vue', import.meta.url), 'utf8')).replace(/\r\n/g, '\n')
const script = source.slice(source.indexOf('<script setup>'), source.indexOf('</script>'))
const template = source.slice(0, source.indexOf('<script setup>'))

// Polling: setTimeout chain, never setInterval; cleared on hidden tab and on unmount.
assert.match(script, /setTimeout\(/, 'kein setTimeout für die Selbstprüfung')
assert.match(script, /clearTimeout\(autoTimer\)/, 'Zeitgeber der Selbstprüfung wird nie gelöscht')
assert.doesNotMatch(source, /setInterval/, 'setInterval ist verboten (Dauerabfrage)')
assert.match(script, /addEventListener\('visibilitychange', onTabChange\)/, 'visibilitychange nicht registriert')
assert.match(script, /removeEventListener\('visibilitychange', onTabChange\)/, 'visibilitychange nicht entfernt')
assert.match(script, /onBeforeUnmount\(/, 'onBeforeUnmount fehlt')
const unmount = script.slice(script.indexOf('onBeforeUnmount('))
assert.match(unmount, /stopped = true/, 'beim Verlassen wird die Selbstprüfung nicht gestoppt')
assert.match(unmount, /clearAuto\(\)/, 'beim Verlassen bleibt der Zeitgeber stehen')
assert.match(unmount, /clearTimeout\(copiedTimer\)/, 'beim Verlassen bleibt der Kopiert-Zeitgeber stehen')
// Intervals: 15 s for the first 20 automatic runs, then 60 s.
assert.match(script, /AUTO_FAST_MS = 15000/)
assert.match(script, /AUTO_SLOW_MS = 60000/)
assert.match(script, /AUTO_FAST_RUNS = 20/)
// No re-arming when green, hidden or stopped; no overlap thanks to the checking guard.
const schedule = script.slice(script.indexOf('function scheduleAuto('), script.indexOf('async function runCheck('))
assert.match(schedule, /if \(stopped \|\| document\.hidden \|\| isGreen\(\)\) \{\n\t\treturn/, 'Selbstprüfung läuft weiter, obwohl grün, verdeckt oder verlassen')
const run = script.slice(script.indexOf('async function runCheck('), script.indexOf('function check('))
assert.match(run, /if \(checking\.value\) \{\n\t\treturn/, 'Prüfläufe können sich überlappen')
assert.match(run, /if \(stopped\) \{\n\t\treturn/, 'eine laufende Anfrage stellt nach dem Verlassen neu')
// The world list only reloads on manual runs or when the ok state changed.
assert.match(run, /if \(!automatic \|\| ok !== lastOk\) \{\n\t\temit\('checked'\)/, 'checked bei jeder Selbstprüfung')

// Compose download via Blob with a revoked object URL.
assert.match(script, /new Blob\(\[command\.compose\]/, 'Compose-Text kommt nicht aus dem Backend-Feld')
assert.match(script, /URL\.revokeObjectURL\(url\)/, 'Objekt-URL wird nicht freigegeben')

// No client-built commands: no command words in the component at all.
for (const literal of ['docker run', 'ufw allow', 'firewall-cmd', 'docker-socket-proxy', 'docker compose']) {
	assert.ok(!source.includes(literal), `Befehlstext im Client: ${literal}`)
}
// Commands are only displayed, never executed or sent anywhere.
assert.doesNotMatch(script, /\beval\(|new Function\(|\bfetch\(|axios/, 'Befehle dürfen nicht ausgeführt oder verschickt werden')
assert.match(template, /<details v-if="firewall" class="setup-check__firewall">/, 'Firewall-Abschnitt fehlt')
assert.match(template, /command\.command/, 'Befehl wird nicht aus dem Backend angezeigt')

// All new keys exist in de, en and fr and are used by the component.
const NEW_KEYS = [
	'admin.setup.commandDetected',
	'admin.setup.commandOther',
	'admin.setup.networkNotDetected',
	'admin.setup.downloadCompose',
	'admin.setup.composeHint',
	'admin.setup.autoRecheck',
	'admin.setup.firewallHeading',
	'admin.setup.firewallHint',
	'admin.setup.firewallUfw',
	'admin.setup.firewallFirewalld',
]
for (const lang of ['de', 'en', 'fr']) {
	const { default: table } = await import(new URL(`../src/i18n/${lang}/admin.js`, import.meta.url))
	for (const key of NEW_KEYS) {
		assert.equal(typeof table[key], 'string', `${lang}: Schlüssel ${key} fehlt`)
	}
	assert.ok(table['admin.setup.commandOther'].includes('<docker-network>'), `${lang}: Platzhalter <docker-network> fehlt`)
	assert.ok(table['admin.setup.networkNotDetected'].includes('<docker-network>'), `${lang}: Platzhalter <docker-network> fehlt`)
	assert.ok(table['admin.setup.firewallHint'].includes('<lan-network>'), `${lang}: Platzhalter <lan-network> fehlt`)
	assert.ok(table['admin.setup.firewallHint'].includes('UPnP'), `${lang}: Hinweis auf UPnP fehlt`)
	assert.ok(table['admin.setup.composeHint'].includes('gameworld-docker-proxy.yaml'), `${lang}: Dateiname fehlt`)
}
for (const key of NEW_KEYS) {
	assert.ok(source.includes(`'${key}'`), `Schlüssel ${key} wird in SetupCheck.vue nicht benutzt`)
}

console.log(`setupcheck.check: Selbstprüfung, Download und ${NEW_KEYS.length} neue Schlüssel in de, en, fr geprüft`)
