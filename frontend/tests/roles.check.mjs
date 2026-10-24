// Prüfskript für frontend/src/roles.js (rein, ohne Vue): node frontend/tests/roles.check.mjs
// Die Soll-Texte stehen hier als eigene Literale (abgeschrieben aus 06-UI-SPEC.md B1),
// nicht aus roles.js übernommen: unabhängige Gegenprobe.
import assert from 'node:assert/strict'
import { setLanguage } from '../src/i18n/index.js'
import {
	boundaryText,
	childrenWarning,
	ncAdminOnlyText,
	noScopeText,
	onlyAdminText,
	searchDownText,
	sectionHint,
	groupAddedText,
	groupRemovedText,
	groupUnknownText,
	loadErrorText,
	scopeHint,
} from '../src/roles.js'

setLanguage('de')

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
	noScopeText(),
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
	sectionHint(),
	'Mitglieder dieser Gruppen verwalten Gameworld wie du: Welten erstellen, Spieler einladen, Spielzeiten, Ferien und Pause einstellen. Nextcloud-Admin werden sie dadurch nicht.',
)
assert.equal(
	childrenWarning(),
	'Wähle keine Gruppe, in der Kinder sind. Jedes Mitglied einer Verwalter-Gruppe kann Kinder einladen und die Pause aufheben. Gameworld kann das nicht prüfen.',
)
assert.equal(
	boundaryText(),
	'Gruppen-Verwalter ohne Nextcloud-Admin laden nur Konten aus Gruppen ein, in denen sie selbst Mitglied oder Gruppenadmin sind. Andere Konten zeigt ihnen Nextcloud nicht. Gelöschte und deaktivierte Konten räumt Gameworld nur auf, wenn ein Nextcloud-Admin Gameworld geöffnet hat.',
)
assert.equal(onlyAdminText(), 'Bisher verwaltet nur die Gruppe admin Gameworld.')
assert.equal(ncAdminOnlyText(), 'Nur Nextcloud-Admins können Verwalter-Gruppen ändern.')
assert.equal(searchDownText(), 'Die Gruppensuche in Nextcloud ist gerade nicht möglich.')

// English and French (D-25); expected texts written out independently.
setLanguage('en')
assert.equal(scopeHint(['klasse']), 'You can invite accounts from your groups: klasse. Nextcloud doesn\'t show you any other accounts.')
assert.equal(groupAddedText('lehrkraefte'), 'The group lehrkraefte now manages Gameworld.')
assert.equal(ncAdminOnlyText(), 'Only Nextcloud admins can change manager groups.')
setLanguage('fr')
assert.equal(scopeHint(['klasse']), 'Tu peux inviter des comptes de tes groupes\u00a0: klasse. Nextcloud ne te montre pas les autres comptes.')
assert.equal(groupUnknownText('x'), 'Le groupe x n’existe pas dans Nextcloud. Choisis un groupe dans la liste.')
assert.equal(scopeHint(['Zebra', 'éclair', 'birne']), 'Tu peux inviter des comptes de tes groupes\u00a0: birne, éclair, Zebra. Nextcloud ne te montre pas les autres comptes.')
setLanguage('de')

console.log('roles.check.mjs: alle Prüfungen bestanden')
