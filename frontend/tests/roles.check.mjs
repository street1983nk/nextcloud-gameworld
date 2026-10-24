// Prüfskript für frontend/src/roles.js (rein, ohne Vue): node frontend/tests/roles.check.mjs
// Die Soll-Texte stehen hier als eigene Literale (abgeschrieben aus 06-UI-SPEC.md B1),
// nicht aus roles.js übernommen: unabhängige Gegenprobe.
import assert from 'node:assert/strict'
import {
	BOUNDARY_TEXT,
	CHILDREN_WARNING,
	NC_ADMIN_ONLY_TEXT,
	NO_SCOPE_TEXT,
	ONLY_ADMIN_TEXT,
	SEARCH_DOWN_TEXT,
	SECTION_HINT,
	groupAddedText,
	groupRemovedText,
	groupUnknownText,
	loadErrorText,
	scopeHint,
} from '../src/roles.js'

// scopeHint (D-01): alphabetisch, leer heißt null
assert.equal(
	scopeHint(['klasse', 'lehrkraefte']),
	'Du kannst Konten aus deinen Gruppen einladen: klasse, lehrkraefte. Andere Konten zeigt dir Nextcloud nicht.',
)
assert.equal(
	scopeHint(['lehrkraefte', 'klasse']),
	'Du kannst Konten aus deinen Gruppen einladen: klasse, lehrkraefte. Andere Konten zeigt dir Nextcloud nicht.',
)
assert.equal(
	scopeHint(['Zebra', 'äpfel', 'birne']),
	'Du kannst Konten aus deinen Gruppen einladen: äpfel, birne, Zebra. Andere Konten zeigt dir Nextcloud nicht.',
)
assert.equal(scopeHint(['klasse']), 'Du kannst Konten aus deinen Gruppen einladen: klasse. Andere Konten zeigt dir Nextcloud nicht.')
assert.equal(scopeHint([]), null)
assert.equal(scopeHint(undefined), null)
assert.equal(scopeHint(null), null)
// Eingabe bleibt unverändert
const input = ['b', 'a']
scopeHint(input)
assert.deepEqual(input, ['b', 'a'])

assert.equal(
	NO_SCOPE_TEXT,
	'Nextcloud zeigt dir keine Konten zum Einladen. Bitte einen Nextcloud-Admin, dich in die Gruppe der Kinder aufzunehmen oder zum Gruppenadmin zu machen.',
)

// Meldungen der Gruppenliste
assert.equal(groupAddedText('lehrkraefte'), 'Die Gruppe lehrkraefte verwaltet Gameworld ab sofort.')
assert.equal(
	groupRemovedText('lehrkraefte'),
	'Die Gruppe lehrkraefte verwaltet Gameworld nicht mehr. Ihre Mitglieder verlieren die Verwaltung sofort, außer sie sind in einer anderen Verwalter-Gruppe.',
)
assert.equal(groupUnknownText('x'), 'Die Gruppe x gibt es in Nextcloud nicht. Bitte wähle eine Gruppe aus der Liste.')
assert.equal(
	loadErrorText('Nextcloud antwortet gerade nicht.'),
	'Die Verwalter-Gruppen konnten nicht geladen werden: Nextcloud antwortet gerade nicht.',
)

// Feste Texte des Abschnitts
assert.equal(
	SECTION_HINT,
	'Mitglieder dieser Gruppen verwalten Gameworld wie du: Welten erstellen, Spieler einladen, Spielzeiten, Ferien und Pause einstellen. Nextcloud-Admin werden sie dadurch nicht.',
)
assert.equal(
	CHILDREN_WARNING,
	'Wähle keine Gruppe, in der Kinder sind. Jedes Mitglied einer Verwalter-Gruppe kann Kinder einladen und die Pause aufheben. Gameworld kann das nicht prüfen.',
)
assert.equal(
	BOUNDARY_TEXT,
	'Gruppen-Verwalter ohne Nextcloud-Admin laden nur Konten aus Gruppen ein, in denen sie selbst Mitglied oder Gruppenadmin sind. Andere Konten zeigt ihnen Nextcloud nicht. Gelöschte und deaktivierte Konten räumt Gameworld nur auf, wenn ein Nextcloud-Admin Gameworld geöffnet hat.',
)
assert.equal(ONLY_ADMIN_TEXT, 'Bisher verwaltet nur die Gruppe admin Gameworld.')
assert.equal(NC_ADMIN_ONLY_TEXT, 'Nur Nextcloud-Admins können Verwalter-Gruppen ändern.')
assert.equal(SEARCH_DOWN_TEXT, 'Die Gruppensuche in Nextcloud ist gerade nicht möglich.')

console.log('roles.check.mjs: alle Prüfungen bestanden')
