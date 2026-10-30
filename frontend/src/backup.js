// Pure helpers for backup and restore (phase 5), without Vue; checked by
// frontend/tests/backup.check.mjs. All texts come from the i18n dictionaries (area core).
import { dateLocale, t, tn } from './i18n/index.js'

const KIB = 1024
const MIB = 1048576
const GIB = 1073741824

// Below 1 MiB whole KB (small worlds would otherwise show "0 MB"; any content at least
// "1 KB"), below 1 GiB whole MB, from 1 GiB on GB with at most one decimal ("1 GB",
// "1,5 GB" in German); the decimal separator follows the UI language, no digit grouping.
export function formatBytes(bytes) {
	const kb = bytes > 0 ? Math.max(1, Math.round(bytes / KIB)) : 0
	if (kb < KIB) {
		return t('core.backup.kilobytes', { value: kb })
	}
	if (bytes < GIB) {
		return t('core.backup.megabytes', { value: Math.round(bytes / MIB) })
	}
	const gb = Math.round((bytes / GIB) * 10) / 10
	const value = new Intl.NumberFormat(dateLocale(), { maximumFractionDigits: 1, useGrouping: false }).format(gb)
	return t('core.backup.gigabytes', { value })
}

// D-09: same wording as the backend (backup/service.py PLAYERS_ONLINE_*).
export function playersWarning(count) {
	return tn('core.backup.playersOnline', count)
}

// D-04/D-05: confirmation before every restore.
export function restoreQuestion(fileName) {
	return t('core.backup.restoreQuestion', { file: fileName })
}

// D-11: line about the last job (backup_job) of the world; empty when there is nothing to report.
export function jobNote(job) {
	if (!job) {
		return ''
	}
	const restore = job.kind === 'restore'
	if (job.state === 'failed') {
		const reason = job.message ?? ''
		return t(restore ? 'core.backup.job.restoreFailed' : 'core.backup.job.backupFailed', { reason })
	}
	if (job.state === 'running') {
		return t(restore ? 'core.backup.job.restoreRunning' : 'core.backup.job.backupRunning')
	}
	return ''
}

function pad(value) {
	return String(value).padStart(2, '0')
}

// Date and time in the browser's local time (German DD.MM.YYYY HH:MM, English and
// French DD/MM/YYYY HH:MM); unreadable input stays as it is.
export function formatDate(iso) {
	const date = new Date(iso)
	if (typeof iso !== 'string' || Number.isNaN(date.getTime())) {
		return String(iso ?? '')
	}
	return t('core.backup.dateTime', {
		day: pad(date.getDate()),
		month: pad(date.getMonth() + 1),
		year: date.getFullYear(),
		hour: pad(date.getHours()),
		minute: pad(date.getMinutes()),
	})
}

// Has a job finished between two polls? Then the backup section reloads its list (T-05-52).
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
