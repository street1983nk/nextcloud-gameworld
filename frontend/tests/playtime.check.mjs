// Prüfskript für frontend/src/playtime.js (rein, ohne Vue): node frontend/tests/playtime.check.mjs
import assert from 'node:assert/strict'
import {
	HOLIDAY_PRESET,
	LIMIT_OPTIONS,
	NO_LIMIT_OPTION,
	PRESETS,
	formatClock,
	formatMinutes,
	fromApiDays,
	fromWindowDays,
	summarize,
	toApiDays,
	toWindowDays,
	usageText,
	validateDays,
	windowSummary,
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
	assert.deepEqual(entry, { weekday: entry.weekday, allowed: true, limit_minutes: 60, window_start: 0, window_end: 1140 })
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
assert.equal(summarize(PRESETS.taeglich), 'Jeden Tag 1 Std, bis 19 Uhr')
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
assert.equal(PRESETS.taeglich[0].window_start, 0)

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

console.log('playtime.check: alle Prüfungen bestanden')
