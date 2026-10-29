// Check script for frontend/src/adult.js (pure, without Vue): node frontend/tests/adult.check.mjs
// Literals stand here independently of the module, word for word from 06-UI-SPEC.md B2.
import assert from 'node:assert/strict'
import { setLanguage } from '../src/i18n/index.js'
import {
	adultInviteWarning,
	adultOffText,
	adultOnText,
	confirmScope,
	confirmWarning,
	confirmLead,
	inviteSwitchMeta,
	invitedLabel,
	nowVerwalterText,
	PLAYTIME_RESTING_TEXT,
	rulesKeptText,
	switchMeta,
} from '../src/adult.js'

setLanguage('de')

// Confirmation dialog, paragraph 1 to 4
assert.equal(confirmLead(['Anna']), 'Anna spielt dann ohne Pause, Zeitfenster und Spielzeitregeln.')
assert.equal(confirmLead(['Anna', 'Ben']), 'Anna, Ben spielen dann ohne Pause, Zeitfenster und Spielzeitregeln.')
assert.equal(
	confirmScope(),
	'Das gilt sofort und in allen Welten, auch mitten im Spiel. Erwachsene erscheinen nicht im Tagesrückblick und bekommen keine Verwaltungsrechte.',
)
assert.equal(confirmWarning(), 'Markiere nur Konten von Erwachsenen, nie das Konto eines Kindes.')
assert.equal(
	rulesKeptText('Anna'),
	'Die Spielzeitregel von Anna bleibt gespeichert und gilt wieder, sobald du den Schalter ausschaltest.',
)

// Messages player list
assert.equal(
	adultOnText('Anna'),
	'Anna ist als erwachsen markiert und spielt ab sofort ohne Pause, Zeitfenster und Spielzeitregeln.',
)
assert.equal(
	adultOffText('Anna'),
	'Anna spielt wieder mit den Kinderregeln. Pause, Zeitfenster und Spielzeit gelten ab sofort. Ist gerade keine Spielzeit, trennt die Welt Anna in wenigen Sekunden.',
)
assert.equal(nowVerwalterText('Anna'), 'Anna verwaltet Gameworld inzwischen und spielt ohnehin ohne Regeln.')

// Invite dialog
assert.equal(
	adultInviteWarning('Anna', 'Fehler'),
	'Anna ist eingeladen, aber nicht als erwachsen markiert: Fehler. Du kannst es in der Spielerliste nachholen.',
)
// Detail with a final full stop (backend message) yields no doubled full stop.
assert.equal(
	adultInviteWarning('Ben', 'Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln.'),
	'Ben ist eingeladen, aber nicht als erwachsen markiert: Dieses Konto verwaltet Gameworld und spielt ohnehin ohne Regeln. Du kannst es in der Spielerliste nachholen.',
)
assert.equal(
	invitedLabel(['Anna (erwachsen)', 'Ben', 'Gruppe klasse-5a']),
	'Eingeladen: Anna (erwachsen), Ben, Gruppe klasse-5a',
)

// Meta texts and playtime section
assert.equal(switchMeta(), 'Spielt ohne Pause, Zeitfenster und Spielzeitregeln. Gilt in allen Welten.')
assert.equal(
	inviteSwitchMeta(),
	'Gilt nur für einzeln ausgewählte Konten, nicht für Gruppen. Bei Gruppen stellst du es danach in der Spielerliste je Person ein.',
)
assert.equal(
	PLAYTIME_RESTING_TEXT('Anna'),
	'Anna ist als erwachsen markiert. Diese Regel ruht und gilt erst wieder, wenn du den Schalter in der Spielerliste ausschaltest.',
)

// No dashes in the texts
for (const text of [confirmScope(), confirmWarning(), switchMeta(), inviteSwitchMeta(), adultOffText('X')]) {
	assert.doesNotMatch(text, /[\u2013\u2014]/)
}

// English and French (D-25); expected texts written out independently.
setLanguage('en')
assert.equal(confirmLead(['Anna', 'Ben']), 'Anna, Ben will then play without breaks, time windows or playtime rules.')
assert.equal(
	adultInviteWarning('Ben', 'This account manages Gameworld.'),
	'Ben is invited but not marked as an adult: This account manages Gameworld. You can do that later in the player list.',
)
setLanguage('fr')
assert.equal(confirmLead(['Anna']), 'Anna jouera alors sans pause, plage horaire ni règle de temps de jeu.')
assert.equal(confirmLead(['Anna', 'Ben']), 'Anna, Ben joueront alors sans pause, plage horaire ni règle de temps de jeu.')
assert.equal(invitedLabel(['Anna', 'Ben']), 'Invités\u00a0: Anna, Ben')
setLanguage('de')

console.log('adult.check: alle Prüfungen bestanden')
