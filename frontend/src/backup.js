// Reine Hilfen für Sichern und Wiederherstellen (Phase 5), ohne Vue; geprüft von
// frontend/tests/backup.check.mjs.

const MIB = 1048576
const GIB = 1073741824

// Unter 1 GiB ganze MB, ab 1 GiB GB mit höchstens einer Nachkommastelle ("1 GB", "1,5 GB").
export function formatBytes(bytes) {
	if (bytes < GIB) {
		return `${Math.round(bytes / MIB)} MB`
	}
	const gb = (Math.round((bytes / GIB) * 10) / 10).toString().replace('.', ',')
	return `${gb} GB`
}

// D-09: gleicher Wortlaut wie das Backend (backup/service.py PLAYERS_ONLINE_*).
export function playersWarning(count) {
	if (count === 1) {
		return 'In der Welt spielt gerade 1 Kind, es wird kurz getrennt.'
	}
	return `In der Welt spielen gerade ${count} Kinder, sie werden kurz getrennt.`
}

// D-04/D-05: Sicherheitsabfrage vor jedem Wiederherstellen.
export function restoreQuestion(fileName) {
	return `Die Welt wird auf den Stand von ${fileName} zurückgesetzt. Der aktuelle Stand wird vorher als Sicherung mit dem Zusatz vor-restore abgelegt.`
}

// D-11: Zeile zum letzten Auftrag (backup_job) der Welt; leer, wenn nichts zu melden ist.
export function jobNote(job) {
	if (!job) {
		return ''
	}
	const restore = job.kind === 'restore'
	if (job.state === 'failed') {
		const reason = job.message ?? ''
		return restore ? `Wiederherstellen fehlgeschlagen: ${reason}` : `Sicherung fehlgeschlagen: ${reason}`
	}
	if (job.state === 'running') {
		return restore ? 'Wiederherstellen läuft ...' : 'Sicherung läuft ...'
	}
	return ''
}

function pad(value) {
	return String(value).padStart(2, '0')
}

// Deutsches Format TT.MM.JJJJ HH:MM in der Ortszeit des Browsers; Unlesbares bleibt, wie es ist.
export function formatDate(iso) {
	const date = new Date(iso)
	if (typeof iso !== 'string' || Number.isNaN(date.getTime())) {
		return String(iso ?? '')
	}
	return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

// Ist ein Auftrag zwischen zwei Abrufen fertig geworden? Dann lädt der Sicherungsbereich
// seine Liste neu (T-05-52).
export function jobFinished(prev, next) {
	const nextState = next?.state
	if (nextState !== 'ok' && nextState !== 'failed') {
		return false
	}
	if (prev?.state === 'running') {
		return true
	}
	return (next?.finished_at ?? null) !== (prev?.finished_at ?? null)
}
