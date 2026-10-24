// Prüfskript für frontend/src/adult.js (rein, ohne Vue): node frontend/tests/adult.check.mjs
// Literale stehen hier unabhängig vom Modul, wörtlich aus 06-UI-SPEC.md B2.
import assert from 'node:assert/strict'
import {
	adultInviteWarning,
	adultOffText,
	adultOnText,
	CONFIRM_SCOPE,
	CONFIRM_WARNING,
	confirmLead,
	INVITE_SWITCH_META,
	invitedLabel,
	nowVerwalterText,
	PLAYTIME_RESTING_TEXT,
	rulesKeptText,
	SWITCH_META,
} from '../src/adult.js'

// Bestätigungsdialog, Absatz 1 bis 4
assert.equal(confirmLead(['Anna']), 'Anna spielt dann ohne Pause, Zeitfenster und Spielzeitregeln.')
assert.equal(confirmLead(['Anna', 'Ben']), 'Anna, Ben spielen dann ohne Pause, Zeitfenster und Spielzeitregeln.')
assert.equal(
	CONFIRM_SCOPE,
	'Das gilt sofort und in allen Welten, auch mitten im Spiel. Erwachsene erscheinen nicht im Tagesrückblick und bekommen keine Verwaltungsrechte.',
)
assert.equal(CONFIRM_WARNING, 'Markiere nur Konten von Erwachsenen, nie das Konto eines Kindes.')
assert.equal(
	rulesKeptText('Anna'),
	'Die Spielzeitregel von Anna bleibt gespeichert und gilt wieder, sobald du den Schalter ausschaltest.',
)

// Meldungen Spielerliste
assert.equal(
	adultOnText('Anna'),
	'Anna ist als erwachsen markiert und spielt ab sofort ohne Pause, Zeitfenster und Spielzeitregeln.',
)
assert.equal(
	adultOffText('Anna'),
	'Anna spielt wieder mit den Kinderregeln. Pause, Zeitfenster und Spielzeit gelten ab sofort. Ist gerade keine Spielzeit, trennt die Welt Anna in wenigen Sekunden.',
)
assert.equal(nowVerwalterText('Anna'), 'Anna verwaltet Gameworld inzwischen und spielt ohnehin ohne Regeln.')

// Einladen-Dialog
assert.equal(
	adultInviteWarning('Anna', 'Fehler'),
	'Anna ist eingeladen, aber nicht als erwachsen markiert: Fehler. Du kannst es in der Spielerliste nachholen.',
)
assert.equal(
	invitedLabel(['Anna (erwachsen)', 'Ben', 'Gruppe klasse-5a']),
	'Eingeladen: Anna (erwachsen), Ben, Gruppe klasse-5a',
)

// Meta-Texte und Spielzeit-Abschnitt
assert.equal(SWITCH_META, 'Spielt ohne Pause, Zeitfenster und Spielzeitregeln. Gilt in allen Welten.')
assert.equal(
	INVITE_SWITCH_META,
	'Gilt nur für einzeln ausgewählte Konten, nicht für Gruppen. Bei Gruppen stellst du es danach in der Spielerliste je Person ein.',
)
assert.equal(
	PLAYTIME_RESTING_TEXT('Anna'),
	'Anna ist als erwachsen markiert. Diese Regel ruht und gilt erst wieder, wenn du den Schalter in der Spielerliste ausschaltest.',
)

// Keine Gedankenstriche in den Texten
for (const text of [CONFIRM_SCOPE, CONFIRM_WARNING, SWITCH_META, INVITE_SWITCH_META, adultOffText('X')]) {
	assert.doesNotMatch(text, /[–—]/)
}

console.log('adult.check: alle Prüfungen bestanden')
