// Prüfskript für frontend/src/backup.js (rein, ohne Vue): node frontend/tests/backup.check.mjs
import assert from 'node:assert/strict'
import {
	formatBytes,
	formatDate,
	jobFinished,
	jobNote,
	playersWarning,
	restoreQuestion,
} from '../src/backup.js'

const MIB = 1048576
const GIB = 1073741824

// formatBytes: Grenzen um 1 GiB
assert.equal(formatBytes(0), '0 MB')
assert.equal(formatBytes(MIB), '1 MB')
assert.equal(formatBytes(GIB - 1), '1024 MB')
assert.equal(formatBytes(GIB), '1 GB')
assert.equal(formatBytes(GIB * 1.5), '1,5 GB')
assert.equal(formatBytes(GIB * 12.34), '12,3 GB')

// playersWarning (D-09)
assert.equal(playersWarning(1), 'In der Welt spielt gerade 1 Kind, es wird kurz getrennt.')
assert.equal(playersWarning(3), 'In der Welt spielen gerade 3 Kinder, sie werden kurz getrennt.')

// restoreQuestion (D-04/D-05)
assert.equal(
	restoreQuestion('Burg-2026-10-23_1200.tar.gz'),
	'Die Welt wird auf den Stand von Burg-2026-10-23_1200.tar.gz zurückgesetzt. Der aktuelle Stand wird vorher als Sicherung mit dem Zusatz vor-restore abgelegt.',
)

// jobNote (D-11)
assert.equal(jobNote(null), '')
assert.equal(jobNote(undefined), '')
assert.equal(jobNote({ kind: 'backup', state: 'failed', message: 'Kein Platz.' }), 'Sicherung fehlgeschlagen: Kein Platz.')
assert.equal(jobNote({ kind: 'restore', state: 'failed', message: 'Datei kaputt.' }), 'Wiederherstellen fehlgeschlagen: Datei kaputt.')
assert.equal(jobNote({ kind: 'backup', state: 'running', message: null }), 'Sicherung läuft ...')
assert.equal(jobNote({ kind: 'restore', state: 'running', message: null }), 'Wiederherstellen läuft ...')
assert.equal(jobNote({ kind: 'backup', state: 'ok', message: null }), '')
assert.equal(jobNote({ kind: 'restore', state: 'ok', message: null }), '')

// formatDate: ohne Zonenangabe liest Date die Ortszeit, das Ergebnis ist darum fest.
assert.equal(formatDate('2026-10-23T09:05:00'), '23.10.2026 09:05')
assert.equal(formatDate('2026-01-02T23:59:00'), '02.01.2026 23:59')
assert.equal(formatDate('kaputt'), 'kaputt')
assert.equal(formatDate(null), '')

// jobFinished (T-05-52)
const running = { kind: 'backup', state: 'running', finished_at: null }
const ok1 = { kind: 'backup', state: 'ok', finished_at: '2026-10-23T10:00:00Z' }
const ok2 = { kind: 'backup', state: 'ok', finished_at: '2026-10-23T11:00:00Z' }
const failed = { kind: 'restore', state: 'failed', finished_at: '2026-10-23T12:00:00Z' }
assert.equal(jobFinished(running, ok1), true, 'running -> ok')
assert.equal(jobFinished(running, failed), true, 'running -> failed')
assert.equal(jobFinished(ok1, { ...ok1 }), false, 'ok -> ok, gleiches finished_at')
assert.equal(jobFinished(ok1, ok2), true, 'ok -> ok, neues finished_at')
assert.equal(jobFinished(null, running), false, 'null -> running')
assert.equal(jobFinished(ok1, running), false, 'ok -> running')
assert.equal(jobFinished(running, running), false, 'running -> running')
assert.equal(jobFinished(null, null), false, 'null -> null')
assert.equal(jobFinished(undefined, undefined), false, 'undefined -> undefined')
assert.equal(jobFinished(ok1, null), false, 'ok -> null')

console.log('backup.check.mjs: alle Prüfungen bestanden')
