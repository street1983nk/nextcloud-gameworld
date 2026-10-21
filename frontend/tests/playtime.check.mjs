// Prüfskript für frontend/src/playtime.js (rein, ohne Vue): node frontend/tests/playtime.check.mjs
import assert from 'node:assert/strict'
import {
	HOLIDAY_PRESET,
	LIMIT_OPTIONS,
	NOT_APPLIED_TEXT,
	NO_LIMIT_OPTION,
	PRESETS,
	formatClock,
	formatMinutes,
	fromApiDays,
	fromWindowDays,
	kidPlaytimeText,
	notAppliedText,
	summarize,
	toApiDays,
	toWindowDays,
	usageText,
	validateDays,
	windowSummary,
	windowText,
} from '../src/playtime.js'

function day(days, weekday) {
	return days.find((entry) => entry.weekday === weekday)
}

// Voreinstellungen (O-07)
assert.equal(PRESETS.keine, null)
for (const weekday of [1, 2, 3, 4, 5]) {
	assert.deepEqual(day(PRESETS.wochenende, weekday), {
		weekday, allowed: false, limit_minutes: null, window_start: null, window_end: null,
	})
}
for (const weekday of [6, 7]) {
	assert.deepEqual(day(PRESETS.wochenende, weekday), {
		weekday, allowed: true, limit_minutes: 120, window_start: 540, window_end: 1140,
	})
}
assert.equal(PRESETS.taeglich.length, 7)
for (const entry of PRESETS.taeglich) {
	assert.deepEqual(entry, { weekday: entry.weekday, allowed: true, limit_minutes: 60, window_start: 540, window_end: 1140 })
}
for (const weekday of [1, 2, 3, 4, 5]) {
	assert.deepEqual(day(PRESETS.schultage, weekday), {
		weekday, allowed: true, limit_minutes: 60, window_start: 900, window_end: 1140,
	})
}
for (const weekday of [6, 7]) {
	assert.deepEqual(day(PRESETS.schultage, weekday), {
		weekday, allowed: true, limit_minutes: 120, window_start: 540, window_end: 1140,
	})
}
assert.equal(HOLIDAY_PRESET.length, 7)
for (const entry of HOLIDAY_PRESET) {
	assert.deepEqual(entry, { weekday: entry.weekday, allowed: true, limit_minutes: 120, window_start: 540, window_end: 1200 })
}
assert.deepEqual(PRESETS.wochenende.map((entry) => entry.weekday), [1, 2, 3, 4, 5, 6, 7])

// Voreinstellungen sind unveränderlich (Kacheln arbeiten auf Kopien)
assert.ok(Object.isFrozen(PRESETS.wochenende[0]))

// Zusammenfassungen
assert.equal(summarize(null), 'Keine Begrenzung')
assert.equal(summarize(PRESETS.wochenende), 'Sa und So, je 2 Std')
assert.equal(summarize(PRESETS.taeglich), 'Jeden Tag 1 Std, 9 bis 19 Uhr')
assert.equal(summarize(PRESETS.schultage), 'Mo bis Fr 1 Std, Sa und So 2 Std')
assert.equal(summarize(HOLIDAY_PRESET), 'Jeden Tag 2 Std, 9 bis 20 Uhr')
assert.equal(summarize(PRESETS.wochenende.map((entry) => ({ ...entry, allowed: false, limit_minutes: null, window_start: null, window_end: null }))), 'Kein Spieltag')

// Umrechnung UI <-> API ist verlustfrei
for (const days of [PRESETS.wochenende, PRESETS.taeglich, PRESETS.schultage, HOLIDAY_PRESET]) {
	assert.deepEqual(toApiDays(fromApiDays(days)), days)
}
// "ganzer Tag" wird zu window_start null und window_end null
const tiles = fromApiDays(PRESETS.taeglich)
tiles[0].fullDay = true
const api = toApiDays(tiles)
assert.equal(api[0].window_start, null)
assert.equal(api[0].window_end, null)
assert.equal(api[0].limit_minutes, 60)
// Kacheln sind Kopien, Ändern berührt die Voreinstellung nicht
assert.equal(PRESETS.taeglich[0].window_start, 540)

// Prüfung im Browser: Ende nach Beginn
const broken = fromApiDays(PRESETS.schultage)
broken[2].start = 1140
broken[2].end = 900
const problems = validateDays(broken)
assert.deepEqual(Object.keys(problems), ['3'])
assert.deepEqual(validateDays(fromApiDays(PRESETS.schultage)), {})

// Limit-Auswahl: 15 min bis 4 Std im 15-Minuten-Raster, plus "ohne Limit"
assert.equal(LIMIT_OPTIONS[0].value, 15)
assert.equal(LIMIT_OPTIONS[LIMIT_OPTIONS.length - 1].value, 240)
assert.equal(LIMIT_OPTIONS.length, 16)
assert.ok(LIMIT_OPTIONS.every((option, index) => option.value === 15 * (index + 1)))
assert.equal(NO_LIMIT_OPTION.value, null)
assert.equal(NO_LIMIT_OPTION.label, 'ohne Limit')

// Texte
assert.equal(formatMinutes(45), '45 min')
assert.equal(formatMinutes(60), '1 Std')
assert.equal(formatMinutes(90), '1 Std 30 min')
assert.equal(formatClock(1140), '19 Uhr')
assert.equal(formatClock(1170), '19:30 Uhr')
assert.equal(formatClock(1440), '24 Uhr')
assert.equal(usageText(2700, 60), 'heute 45 von 60 min')
assert.equal(usageText(0, 120), 'heute 0 von 120 min')

// Welt-Zeitfenster (ZEIT-05)
const midweek = [1, 2, 3, 4, 5, 6, 7].map((weekday) => ({
	weekday,
	open: weekday === 3,
	window_start: weekday === 3 ? 600 : null,
	window_end: weekday === 3 ? 720 : null,
}))
assert.equal(windowSummary(null), '')
assert.equal(windowSummary(midweek), 'Offen Mi 10 bis 12 Uhr')
const school = [1, 2, 3, 4, 5, 6, 7].map((weekday) => ({
	weekday,
	open: weekday <= 5,
	window_start: weekday <= 5 ? 480 : null,
	window_end: weekday <= 5 ? 780 : null,
}))
assert.equal(windowSummary(school), 'Offen Mo bis Fr 8 bis 13 Uhr')
assert.deepEqual(toWindowDays(fromWindowDays(midweek)), midweek)
assert.deepEqual(toWindowDays(fromWindowDays(school)), school)
// Ganzer Tag offen wird für die Welt zu 0 bis 1440
const allDay = fromWindowDays(null)
assert.equal(allDay.length, 7)
allDay.forEach((entry) => { entry.allowed = entry.weekday === 6; entry.fullDay = true })
assert.deepEqual(toWindowDays(allDay)[5], { weekday: 6, open: true, window_start: 0, window_end: 1440 })
assert.deepEqual(toWindowDays(allDay)[0], { weekday: 1, open: false, window_start: null, window_end: null })
assert.equal(windowSummary(toWindowDays(allDay)), 'Offen Sa ganztags')

// Kind-Ansicht (04-07): Restzeit aus /api/my/playtime
const kid = (state, remaining, until, next = null) => ({
	limited: true, state, remaining_minutes: remaining, until_minute: until, next,
})
assert.equal(kidPlaytimeText(null), null)
assert.equal(kidPlaytimeText({ limited: false, state: null, remaining_minutes: null, until_minute: null, next: null }), null)
assert.equal(kidPlaytimeText(kid('ok', 60, 1140)), 'Heute noch 60 Minuten, bis 19 Uhr.')
assert.equal(kidPlaytimeText(kid('ok', 45, null)), 'Heute noch 45 Minuten.')
assert.equal(kidPlaytimeText(kid('ok', 1, 1170)), 'Heute noch 1 Minute, bis 19:30 Uhr.')
assert.equal(kidPlaytimeText(kid('ok', null, 1140)), 'Heute kannst du bis 19 Uhr spielen.')
assert.equal(kidPlaytimeText(kid('ok', null, null)), null)
assert.equal(
	kidPlaytimeText(kid('aufgebraucht', 0, null, { weekday: 4, minute: 540, days_ahead: 1 })),
	'Deine Spielzeit für heute ist vorbei. Morgen ab 9 Uhr kannst du wieder spielen.',
)
assert.equal(
	kidPlaytimeText(kid('tag', 0, null, { weekday: 6, minute: 540, days_ahead: 3 })),
	'Heute ist kein Spieltag. Am Samstag ab 9 Uhr kannst du wieder spielen.',
)
assert.equal(
	kidPlaytimeText(kid('tag', 0, null, { weekday: 6, minute: 570, days_ahead: 3 })),
	'Heute ist kein Spieltag. Am Samstag ab 9:30 Uhr kannst du wieder spielen.',
)
assert.equal(
	kidPlaytimeText(kid('fenster', 0, null, { weekday: 3, minute: 900, days_ahead: 0 })),
	'Jetzt ist noch keine Spielzeit. Heute ab 15 Uhr kannst du spielen.',
)
assert.equal(
	kidPlaytimeText(kid('fenster', 0, null, { weekday: 4, minute: 900, days_ahead: 1 })),
	'Jetzt ist keine Spielzeit. Morgen ab 15 Uhr kannst du wieder spielen.',
)
assert.equal(
	kidPlaytimeText(kid('aufgebraucht', 0, null, { weekday: 3, minute: 0, days_ahead: 7 })),
	'Deine Spielzeit für heute ist vorbei. Nächsten Mittwoch kannst du wieder spielen.',
)
assert.equal(kidPlaytimeText(kid('tag', 0, null, null)), 'Heute ist kein Spieltag.')
assert.equal(kidPlaytimeText(kid('fenster', 0, null, null)), 'Jetzt ist keine Spielzeit.')
// Unsinnige Angaben: nur der Grundsatz, nie ein halber Satz.
assert.equal(kidPlaytimeText(kid('tag', 0, null, { weekday: 6, minute: 540, days_ahead: 8 })), 'Heute ist kein Spieltag.')
assert.equal(kidPlaytimeText(kid('tag', 0, null, { weekday: 9, minute: 540, days_ahead: 3 })), 'Heute ist kein Spieltag.')

// Welt-Fenster in der Kind-Ansicht (window_open, window_next aus /api/my/worlds)
assert.equal(windowText({ window_open: null, window_next: null }), null)
assert.equal(windowText({}), null)
assert.equal(
	windowText({ window_open: true, window_next: { weekday: 3, start: 600, end: 720, days_ahead: 0 } }),
	'Heute offen, 10 bis 12 Uhr',
)
assert.equal(
	windowText({ window_open: true, window_next: { weekday: 3, start: 0, end: 1440, days_ahead: 0 } }),
	'Heute offen, ganztags',
)
assert.equal(
	windowText({ window_open: true, window_next: { weekday: 3, start: 600, end: 1440, days_ahead: 0 } }),
	'Heute offen, ab 10 Uhr',
)
assert.equal(
	windowText({ window_open: true, window_next: { weekday: 3, start: 0, end: 720, days_ahead: 0 } }),
	'Heute offen, bis 12 Uhr',
)
assert.equal(
	windowText({ window_open: false, window_next: { weekday: 3, start: 600, end: 720, days_ahead: 2 } }),
	'Diese Welt ist gerade zu. Am Mittwoch ab 10 Uhr ist sie wieder offen.',
)
assert.equal(
	windowText({ window_open: false, window_next: { weekday: 3, start: 600, end: 720, days_ahead: 0 } }),
	'Diese Welt ist gerade zu. Heute ab 10 Uhr ist sie wieder offen.',
)
assert.equal(
	windowText({ window_open: false, window_next: { weekday: 4, start: 0, end: 1440, days_ahead: 1 } }),
	'Diese Welt ist gerade zu. Morgen ist sie wieder offen.',
)
assert.equal(
	windowText({ window_open: false, window_next: { weekday: 3, start: 600, end: 720, days_ahead: 7 } }),
	'Diese Welt ist gerade zu. Nächsten Mittwoch ab 10 Uhr ist sie wieder offen.',
)
// Ohne days_ahead (älteres Backend) kein Tagesbezug.
assert.equal(
	windowText({ window_open: false, window_next: { weekday: 3, start: 600, end: 720 } }),
	'Diese Welt ist gerade zu.',
)
assert.equal(windowText({ window_open: false, window_next: null }), 'Diese Welt ist gerade zu.')

// Verbotsliste (Owner-Entscheid 21.10.2026): nie "0 Uhr", "00:00", "Mitternacht", "24 Uhr".
// "0 Uhr" nur als eigene Zahl: "14:30 Uhr" ist erlaubt.
const FORBIDDEN = /(?<!\d)0 Uhr|00:00|Mitternacht|24 Uhr/
const MINUTES = [0, 540, 870, 1439]
for (const state of ['aufgebraucht', 'fenster', 'tag']) {
	for (let ahead = 0; ahead <= 7; ahead += 1) {
		for (const minute of MINUTES) {
			const text = kidPlaytimeText(kid(state, 0, null, { weekday: ((3 + ahead - 1) % 7) + 1, minute, days_ahead: ahead }))
			assert.ok(!FORBIDDEN.test(text), text)
		}
	}
}
for (const until of [...MINUTES.filter((minute) => minute > 0), null]) {
	for (const remaining of [1, 45, null]) {
		const text = kidPlaytimeText(kid('ok', remaining, until))
		assert.ok(text === null || !FORBIDDEN.test(text), text)
	}
}
for (let ahead = 0; ahead <= 7; ahead += 1) {
	for (const start of MINUTES) {
		for (const open of [true, false]) {
			const text = windowText({ window_open: open, window_next: { weekday: 3, start, end: 1440, days_ahead: ahead } })
			assert.ok(!FORBIDDEN.test(text), text)
		}
	}
}

// WR-08: applied false heißt "gespeichert, aber noch nicht in der Welt"; sonst kein Hinweis.
assert.equal(notAppliedText({ applied: false }), NOT_APPLIED_TEXT)
assert.equal(notAppliedText({ applied: true }), '')
assert.equal(notAppliedText({ applied: null }), '')
assert.equal(notAppliedText({}), '')
assert.equal(notAppliedText(null), '')
assert.match(NOT_APPLIED_TEXT, /^Gespeichert, aber noch nicht in jeder Welt angekommen\./)
assert.match(NOT_APPLIED_TEXT, /übernimmt die Änderung beim nächsten Start\.$/)
for (const forbidden of ['–', '—', 'uebernimmt', 'Aenderung', 'naechsten']) {
	assert.ok(!NOT_APPLIED_TEXT.includes(forbidden), forbidden)
}

console.log('playtime.check: alle Prüfungen bestanden')
