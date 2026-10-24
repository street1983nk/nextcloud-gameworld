// Texte für die Verwalter-Gruppen (UI-SPEC B1, ROLLE-03): rein, ohne Vue, per
// node frontend/tests/roles.check.mjs geprüft. Gruppen-IDs kommen nur als Text in
// die Seite (Textinterpolation, nie v-html).

export const SECTION_HINT = 'Mitglieder dieser Gruppen verwalten Gameworld wie du: Welten erstellen, Spieler einladen, Spielzeiten, Ferien und Pause einstellen. Nextcloud-Admin werden sie dadurch nicht.'

export const CHILDREN_WARNING = 'Wähle keine Gruppe, in der Kinder sind. Jedes Mitglied einer Verwalter-Gruppe kann Kinder einladen und die Pause aufheben. Gameworld kann das nicht prüfen.'

export const BOUNDARY_TEXT = 'Gruppen-Verwalter ohne Nextcloud-Admin laden nur Konten aus Gruppen ein, in denen sie selbst Mitglied oder Gruppenadmin sind. Andere Konten zeigt ihnen Nextcloud nicht. Gelöschte und deaktivierte Konten räumt Gameworld nur auf, wenn ein Nextcloud-Admin Gameworld geöffnet hat.'

export const ONLY_ADMIN_TEXT = 'Bisher verwaltet nur die Gruppe admin Gameworld.'

export const NC_ADMIN_ONLY_TEXT = 'Nur Nextcloud-Admins können Verwalter-Gruppen ändern.'

export const SEARCH_DOWN_TEXT = 'Die Gruppensuche in Nextcloud ist gerade nicht möglich.'

export const NO_SCOPE_TEXT = 'Nextcloud zeigt dir keine Konten zum Einladen. Bitte einen Nextcloud-Admin, dich in die Gruppe der Kinder aufzunehmen oder zum Gruppenadmin zu machen.'

// Grenz-Hinweis im Einladen-Dialog (D-01); null heißt: keine Gruppe, die Komponente
// zeigt dann NO_SCOPE_TEXT.
export function scopeHint(groups) {
	const list = Array.isArray(groups)
		? [...new Set(groups.map((gid) => String(gid)).filter((gid) => gid !== ''))]
		: []
	if (list.length === 0) {
		return null
	}
	list.sort((a, b) => a.localeCompare(b, 'de'))
	return `Du kannst Konten aus deinen Gruppen einladen: ${list.join(', ')}. Andere Konten zeigt dir Nextcloud nicht.`
}

export function groupAddedText(gid) {
	return `Die Gruppe ${gid} verwaltet Gameworld ab sofort.`
}

export function groupRemovedText(gid) {
	return `Die Gruppe ${gid} verwaltet Gameworld nicht mehr. Ihre Mitglieder verlieren die Verwaltung sofort, außer sie sind in einer anderen Verwalter-Gruppe.`
}

export function groupUnknownText(gid) {
	return `Die Gruppe ${gid} gibt es in Nextcloud nicht. Bitte wähle eine Gruppe aus der Liste.`
}

export function loadErrorText(detail) {
	return `Die Verwalter-Gruppen konnten nicht geladen werden: ${detail}`
}
