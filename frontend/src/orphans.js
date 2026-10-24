// Reine Hilfen für den Abschnitt "Reste früherer Installationen" (06-UI-SPEC B3), ohne Vue;
// geprüft von frontend/tests/orphans.check.mjs. Namen kommen nur per Textinterpolation ins DOM.
import { formatDate } from './backup.js'

export const CLEANUP_DOCS_URL = 'https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#cleanup'

export const INTRO_TEXT = 'Hier stehen Welt-Container und Spielstände, die Gameworld angelegt hat, die aber zu keiner Welt dieser Installation gehören. Das passiert zum Beispiel nach einer Neuinstallation mit gelöschten App-Daten. Gameworld fasst nur eigene Container und Spielstände an.'

export const LIFECYCLE_TEXT = 'Beim Deaktivieren und bei jedem Update der App stoppt Gameworld alle Welten und entfernt ihre Container. Wer gerade spielt, wird kurz getrennt. Spielstände und Sicherungen bleiben, danach baut Gameworld die Welten von selbst wieder auf.'

export const EMPTY_TEXT = 'Keine Reste gefunden. Alles, was Gameworld auf diesem Server angelegt hat, gehört zu einer Welt in der Liste oben.'

// Hinweis aufs Host-Skript; code-Teile stellt die Komponente als <code> dar.
export const SCRIPT_SEGMENTS = Object.freeze([
	{ text: 'Nach dem Deinstallieren gibt es diese Liste nicht mehr. Dann hilft das Skript ', code: false },
	{ text: 'gameworld-orphans.sh', code: true },
	{ text: ' auf dem Docker-Host: Es zeigt Reste nur an und löscht sie erst mit ', code: false },
	{ text: '--remove-containers', code: true },
	{ text: ' oder ', code: false },
	{ text: '--remove-volumes', code: true },
	{ text: '.', code: false },
])

export const SCRIPT_TEXT = SCRIPT_SEGMENTS.map((part) => part.text).join('')

export function containerQuestion(name) {
	return `Container »${name}« stoppen und entfernen? Wer darauf spielt, wird getrennt. Der Spielstand bleibt erhalten.`
}

export function volumeQuestion(name) {
	return `Spielstand »${name}« endgültig löschen? Die Welt und alles Gebaute darin sind danach weg, Gameworld kann das nicht rückgängig machen. Sicherungen in deinen Nextcloud-Dateien bleiben.`
}

function createdPart(created) {
	return typeof created === 'string' && created !== '' ? `angelegt ${formatDate(created)}` : ''
}

// Docker-Status: nur "running" zählt als läuft, alles andere (exited, created, dead) als gestoppt.
export function containerMeta(container) {
	const state = container?.state === 'running' ? 'läuft' : 'gestoppt'
	const created = createdPart(container?.created)
	return created === '' ? `Stand: ${state}` : `Stand: ${state}, ${created}`
}

export function volumeMeta(volume) {
	return createdPart(volume?.created)
}

export function removedText(kind, name) {
	return kind === 'container' ? `Container ${name} entfernt.` : `Spielstand ${name} gelöscht.`
}

export function inUseText(name) {
	return `Der Spielstand ${name} wird noch von einem Container benutzt. Entferne zuerst den Container.`
}

export function unavailableText(errorText) {
	return `Die Suche nach Resten ist gerade nicht möglich: ${errorText} Der Setup-Check oben zeigt, was fehlt.`
}
