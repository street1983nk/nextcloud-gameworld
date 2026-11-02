// Self-test of the foreign-word detector (positive and negative controls).
//
// The sentences are hand-written for this test, not copied from the
// dictionaries, so the check does not just mirror the implementation.
// Usage: node scripts/audit/selftest.mjs <repo> <server.json>
// Exit code 1 on any failure.
import { loadVocab, foreign } from './lang_detector.mjs'

const [REPO = '.', SERVER = '.dev/audit/server.json'] = process.argv.slice(2)
const MIN_EXCLUSIVE = 200
const counts = await loadVocab(REPO, SERVER, ['de', 'en', 'fr'])
let failed = 0
const fail = (msg) => { failed++; console.log('FAIL ' + msg) }

console.log('exclusive words per language:', JSON.stringify(counts))
for (const [lang, n] of Object.entries(counts)) {
	if (n < MIN_EXCLUSIVE) fail(`coverage ${lang}: ${n} exclusive words < ${MIN_EXCLUSIVE}`)
}

// (a) Positive controls: text in language X checked as Y must report X.
const positive = [
	{ text: 'Deine Kinder können heute Abend noch eine Stunde in der Welt spielen, danach wird gespeichert.', as: 'en', expect: 'de' },
	{ text: 'Your children may keep playing in this world for another hour before everything is saved.', as: 'fr', expect: 'en' },
	{ text: 'Vos enfants peuvent encore jouer une heure dans ce monde avant la fermeture du serveur.', as: 'de', expect: 'fr' },
	{ text: 'Open the Sicherung list to see when the world was last saved.', as: 'en', expect: 'de' },
]
for (const p of positive) {
	const hits = foreign(p.text, p.as)
	if (!hits[p.expect]?.length) fail(`positive ${p.expect} as ${p.as}: no ${p.expect} hit for "${p.text}" (got ${JSON.stringify(hits)})`)
	else console.log(`ok   positive ${p.expect} as ${p.as}: ${hits[p.expect].join(', ')}`)
}

// (b) Negative controls: clean text in its own language must have no hit.
const negative = [
	{ text: 'Hier siehst du, wann deine Welt zuletzt gesichert wurde und wer gerade mitspielt.', lang: 'de' },
	{ text: 'Here you can see when your world was last saved and who is playing right now.', lang: 'en' },
	{ text: 'Ici, vous voyez quand votre monde a été sauvegardé et qui joue en ce moment.', lang: 'fr' },
]
for (const n of negative) {
	const hits = foreign(n.text, n.lang)
	if (Object.keys(hits).length) fail(`negative ${n.lang}: unexpected hits ${JSON.stringify(hits)} for "${n.text}"`)
	else console.log(`ok   negative ${n.lang}: no hit`)
}

console.log(failed ? `SELFTEST FAILED (${failed})` : 'SELFTEST PASSED')
process.exit(failed ? 1 : 0)
