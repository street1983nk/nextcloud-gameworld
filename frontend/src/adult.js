// Reine Texte für den Erwachsen-Schalter (ROLLE-04, UI-SPEC B2), ohne Vue; geprüft von
// frontend/tests/adult.check.mjs. Namen nur per Textinterpolation ausgeben, nie als HTML.

// Bestätigungsdialog, Absatz 1 (bold): Folgen für ein oder mehrere Konten.
export function confirmLead(names) {
	const list = names.join(', ')
	const verb = names.length > 1 ? 'spielen' : 'spielt'
	return `${list} ${verb} dann ohne Pause, Zeitfenster und Spielzeitregeln.`
}

// Absatz 2 und 3.
export const CONFIRM_SCOPE = 'Das gilt sofort und in allen Welten, auch mitten im Spiel. '
	+ 'Erwachsene erscheinen nicht im Tagesrückblick und bekommen keine Verwaltungsrechte.'

export const CONFIRM_WARNING = 'Markiere nur Konten von Erwachsenen, nie das Konto eines Kindes.'

// Absatz 4, nur wenn eine Spielzeitregel existiert (has_rules).
export function rulesKeptText(name) {
	return `Die Spielzeitregel von ${name} bleibt gespeichert und gilt wieder, sobald du den Schalter ausschaltest.`
}

export function adultOnText(name) {
	return `${name} ist als erwachsen markiert und spielt ab sofort ohne Pause, Zeitfenster und Spielzeitregeln.`
}

export function adultOffText(name) {
	return `${name} spielt wieder mit den Kinderregeln. Pause, Zeitfenster und Spielzeit gelten ab sofort. `
		+ `Ist gerade keine Spielzeit, trennt die Welt ${name} in wenigen Sekunden.`
}

// Konto wurde inzwischen Verwalter (409).
export function nowVerwalterText(name) {
	return `${name} verwaltet Gameworld inzwischen und spielt ohnehin ohne Regeln.`
}

// Einladung gelungen, Markieren nicht. API-Meldungen enden meist mit Punkt, er entfällt hier.
export function adultInviteWarning(name, detail) {
	const reason = String(detail ?? '').trim().replace(/[.]+$/, '')
	return `${name} ist eingeladen, aber nicht als erwachsen markiert: ${reason}. Du kannst es in der Spielerliste nachholen.`
}

export function invitedLabel(labels) {
	return `Eingeladen: ${labels.join(', ')}`
}

export const SWITCH_META = 'Spielt ohne Pause, Zeitfenster und Spielzeitregeln. Gilt in allen Welten.'

export const INVITE_SWITCH_META = 'Gilt nur für einzeln ausgewählte Konten, nicht für Gruppen. '
	+ 'Bei Gruppen stellst du es danach in der Spielerliste je Person ein.'

export function PLAYTIME_RESTING_TEXT(name) {
	return `${name} ist als erwachsen markiert. Diese Regel ruht und gilt erst wieder, `
		+ 'wenn du den Schalter in der Spielerliste ausschaltest.'
}
