// Spielzeit im Browser: Voreinstellungen, Zusammenfassungen und Umrechnung
// zwischen den Tages-Kacheln und der API (Minuten ab 00:00 lokal, Ende exklusiv).
//
// Rein, ohne Vue und ohne @nextcloud: läuft auch unter Node
// (frontend/tests/playtime.check.mjs). Das Backend prüft jede Eingabe
// unabhängig; die Prüfung hier ist nur Komfort.

const FULL_DAY = 1440
// Vorgaben, wenn eine Kachel von "ganzer Tag" auf ein Zeitfenster wechselt.
const DEFAULT_START = 540
const DEFAULT_END = 1140
// Chips bleiben kurz; wird der Text länger, entfällt das Zeitfenster (steht im Dialog).
const MAX_CHIP = 30

export const WEEKDAYS = Object.freeze([
	{ weekday: 1, short: 'Mo', long: 'Montag' },
	{ weekday: 2, short: 'Di', long: 'Dienstag' },
	{ weekday: 3, short: 'Mi', long: 'Mittwoch' },
	{ weekday: 4, short: 'Do', long: 'Donnerstag' },
	{ weekday: 5, short: 'Fr', long: 'Freitag' },
	{ weekday: 6, short: 'Sa', long: 'Samstag' },
	{ weekday: 7, short: 'So', long: 'Sonntag' },
].map((entry) => Object.freeze(entry)))

const SCHOOL_DAYS = [1, 2, 3, 4, 5]

// "45 min", "1 Std", "1 Std 30 min"
export function formatMinutes(minutes) {
	const hours = Math.floor(minutes / 60)
	const rest = minutes % 60
	if (hours === 0) {
		return `${rest} min`
	}
	return rest === 0 ? `${hours} Std` : `${hours} Std ${rest} min`
}

// "19", "19:30" (ohne "Uhr", für "9 bis 19 Uhr")
function clockShort(minutes) {
	const hours = Math.floor(minutes / 60)
	const rest = minutes % 60
	return rest === 0 ? String(hours) : `${hours}:${String(rest).padStart(2, '0')}`
}

// "19 Uhr", "19:30 Uhr"; 1440 ist "24 Uhr" (Ende des Tages).
export function formatClock(minutes) {
	return `${clockShort(minutes)} Uhr`
}

// Tageslimit-Auswahl: 15 min bis 4 Std im 15-Minuten-Raster; "ohne Limit" extra.
export const LIMIT_OPTIONS = Object.freeze(
	Array.from({ length: 16 }, (_, index) => Object.freeze({ value: 15 * (index + 1), label: formatMinutes(15 * (index + 1)) })),
)
export const NO_LIMIT_OPTION = Object.freeze({ value: null, label: 'ohne Limit' })

function apiDay(weekday, allowed, limit = null, start = null, end = null) {
	return Object.freeze({ weekday, allowed, limit_minutes: limit, window_start: start, window_end: end })
}

function week(rule) {
	return Object.freeze(WEEKDAYS.map(({ weekday }) => rule(weekday)))
}

// Voreinstellungen nach O-07 im API-Format; keine = keine Regeln (Opt-in, O-10).
export const PRESETS = Object.freeze({
	keine: null,
	wochenende: week((weekday) => (weekday >= 6 ? apiDay(weekday, true, 120, 540, 1140) : apiDay(weekday, false))),
	taeglich: week((weekday) => apiDay(weekday, true, 60, 0, 1140)),
	schultage: week((weekday) => (weekday >= 6
		? apiDay(weekday, true, 120, 540, 1140)
		: apiDay(weekday, true, 60, 900, 1140))),
})

// Vorschlag für die Ferien: jeden Tag 2 Std, 9 bis 20 Uhr.
export const HOLIDAY_PRESET = week((weekday) => apiDay(weekday, true, 120, 540, 1200))

function shortName(weekday) {
	return WEEKDAYS[weekday - 1].short
}

// "Jeden Tag", "Sa und So", "Mo bis Fr", "Mi", "Mo, Mi und Fr"
function daysLabel(weekdays) {
	const sorted = [...weekdays].sort((a, b) => a - b)
	if (sorted.length === 7) {
		return 'Jeden Tag'
	}
	if (sorted.length === 1) {
		return shortName(sorted[0])
	}
	const contiguous = sorted.every((weekday, index) => index === 0 || weekday === sorted[index - 1] + 1)
	if (contiguous && sorted.length >= 3) {
		return `${shortName(sorted[0])} bis ${shortName(sorted[sorted.length - 1])}`
	}
	const names = sorted.map(shortName)
	return `${names.slice(0, -1).join(', ')} und ${names[names.length - 1]}`
}

// "9 bis 19 Uhr", "bis 19 Uhr", "ab 9 Uhr", "ganztags"; null ohne Fenster.
function windowText(start, end) {
	if (start === null || end === null) {
		return null
	}
	if (start === 0 && end === FULL_DAY) {
		return 'ganztags'
	}
	if (start === 0) {
		return `bis ${formatClock(end)}`
	}
	if (end === FULL_DAY) {
		return `ab ${formatClock(start)}`
	}
	return `${clockShort(start)} bis ${formatClock(end)}`
}

function groupBy(days, keyOf) {
	const groups = new Map()
	for (const entry of days) {
		const key = keyOf(entry)
		if (!groups.has(key)) {
			groups.set(key, { first: entry, weekdays: [] })
		}
		groups.get(key).weekdays.push(entry.weekday)
	}
	return [...groups.values()]
}

// Kurztext für den Chip eines Kindes (API-Tage oder null).
export function summarize(days) {
	if (!days) {
		return 'Keine Begrenzung'
	}
	const allowed = days.filter((entry) => entry.allowed)
	if (allowed.length === 0) {
		return 'Kein Spieltag'
	}
	const groups = groupBy(allowed, (entry) => `${entry.limit_minutes}|${entry.window_start}|${entry.window_end}`)
	if (groups.length === 1) {
		const { first, weekdays } = groups[0]
		const label = daysLabel(weekdays)
		const limit = first.limit_minutes === null ? null : formatMinutes(first.limit_minutes)
		const window = windowText(first.window_start, first.window_end)
		let head = label
		const parts = []
		if (label === 'Jeden Tag') {
			if (limit) {
				head = `${label} ${limit}`
			}
		} else if (limit) {
			parts.push(weekdays.length > 1 ? `je ${limit}` : limit)
		}
		if (!limit && !window) {
			return `${label}, ohne Limit`
		}
		const withWindow = [head, ...parts, ...(window ? [window] : [])].join(', ')
		if (withWindow.length <= MAX_CHIP || !limit || !window) {
			return withWindow
		}
		return [head, ...parts].join(', ')
	}
	if (groups.length === 2) {
		return groups
			.map(({ first, weekdays }) => {
				const rule = first.limit_minutes !== null
					? formatMinutes(first.limit_minutes)
					: (windowText(first.window_start, first.window_end) ?? 'ohne Limit')
				return `${daysLabel(weekdays)} ${rule}`
			})
			.join(', ')
	}
	return 'Eigener Wochenplan'
}

// Chip einer Welt aus time_window: "Offen Mi 10 bis 12 Uhr"; ohne Fenster leer.
export function windowSummary(days) {
	if (!days) {
		return ''
	}
	const open = days.filter((entry) => entry.open)
	if (open.length === 0) {
		return 'Geschlossen'
	}
	const groups = groupBy(open, (entry) => `${entry.window_start}|${entry.window_end}`)
	const label = daysLabel(open.map((entry) => entry.weekday)).replace('Jeden Tag', 'jeden Tag')
	if (groups.length > 1) {
		return `Offen ${label}, je nach Tag`
	}
	const { first } = groups[0]
	return `Offen ${label} ${windowText(first.window_start, first.window_end) ?? 'ganztags'}`
}

// Kachel-Modell: { weekday, allowed, limit, fullDay, start, end } (Minuten).
function tile(weekday, allowed, limit, fullDay, start, end) {
	return { weekday, allowed, limit, fullDay, start, end }
}

// API-Tage (oder null) in bearbeitbare Kacheln; immer Kopien.
export function fromApiDays(days) {
	return WEEKDAYS.map(({ weekday }) => {
		const entry = days?.find((item) => item.weekday === weekday)
		if (!entry) {
			return tile(weekday, true, 60, true, DEFAULT_START, DEFAULT_END)
		}
		const fullDay = entry.window_start === null || entry.window_end === null
		return tile(
			weekday,
			entry.allowed,
			entry.limit_minutes,
			fullDay,
			fullDay ? DEFAULT_START : entry.window_start,
			fullDay ? DEFAULT_END : entry.window_end,
		)
	})
}

// Kacheln in API-Tage; ein nicht erlaubter Tag trägt weder Limit noch Fenster.
export function toApiDays(tiles) {
	return [...tiles]
		.sort((a, b) => a.weekday - b.weekday)
		.map((entry) => {
			if (!entry.allowed) {
				return { weekday: entry.weekday, allowed: false, limit_minutes: null, window_start: null, window_end: null }
			}
			return {
				weekday: entry.weekday,
				allowed: true,
				limit_minutes: entry.limit,
				window_start: entry.fullDay ? null : entry.start,
				window_end: entry.fullDay ? null : entry.end,
			}
		})
}

// Welt-Fenster (time_window oder null) in Kacheln ohne Limit.
export function fromWindowDays(days) {
	return WEEKDAYS.map(({ weekday }) => {
		const entry = days?.find((item) => item.weekday === weekday)
		if (!entry) {
			return tile(weekday, true, null, false, DEFAULT_START, DEFAULT_END)
		}
		if (!entry.open || entry.window_start === null || entry.window_end === null) {
			return tile(weekday, Boolean(entry.open), null, Boolean(entry.open), DEFAULT_START, DEFAULT_END)
		}
		const fullDay = entry.window_start === 0 && entry.window_end === FULL_DAY
		return tile(
			weekday,
			true,
			null,
			fullDay,
			fullDay ? DEFAULT_START : entry.window_start,
			fullDay ? DEFAULT_END : entry.window_end,
		)
	})
}

// Kacheln in Welt-Fenstertage; "ganzer Tag" heißt 0 bis 1440.
export function toWindowDays(tiles) {
	return [...tiles]
		.sort((a, b) => a.weekday - b.weekday)
		.map((entry) => {
			if (!entry.allowed) {
				return { weekday: entry.weekday, open: false, window_start: null, window_end: null }
			}
			return {
				weekday: entry.weekday,
				open: true,
				window_start: entry.fullDay ? 0 : entry.start,
				window_end: entry.fullDay ? FULL_DAY : entry.end,
			}
		})
}

// Wochentag -> Hinweistext für Kacheln mit Ende nicht nach Beginn.
export function validateDays(tiles) {
	const problems = {}
	for (const entry of tiles) {
		if (entry.allowed && !entry.fullDay && entry.end <= entry.start) {
			problems[entry.weekday] = 'Das Ende muss nach dem Beginn liegen.'
		}
	}
	return problems
}

// "heute 45 von 60 min"
export function usageText(usedSeconds, limitMinutes) {
	return `heute ${Math.floor(usedSeconds / 60)} von ${limitMinutes} min`
}

// Minuten in eine Uhrzeit für <input type="time"> (1440 zeigt 00:00).
export function minutesToDate(minutes) {
	const value = minutes % FULL_DAY
	return new Date(2000, 0, 1, Math.floor(value / 60), value % 60)
}

// Uhrzeit aus dem Picker in Minuten; als Ende heißt 00:00 Mitternacht (1440).
export function dateToMinutes(date, isEnd) {
	const minutes = date.getHours() * 60 + date.getMinutes()
	return isEnd && minutes === 0 ? FULL_DAY : minutes
}

const WEEKDAY_INDEX = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }

// ISO-Wochentag (1..7) jetzt in der Zeitzone des Haushalts.
export function weekdayIn(timeZone, now = new Date()) {
	try {
		const name = new Intl.DateTimeFormat('en-US', { timeZone, weekday: 'short' }).format(now)
		return WEEKDAY_INDEX[name] ?? null
	} catch {
		return null
	}
}

// Heute geltende Regel eines Kindes (Ferienplan, wenn Ferien laufen und einer gesetzt ist).
export function todayRule(child, holidayActive, weekday) {
	const plan = holidayActive && child.holiday ? child.holiday : child.normal
	return plan?.find((entry) => entry.weekday === weekday) ?? null
}
