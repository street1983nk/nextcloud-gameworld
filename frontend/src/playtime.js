// Spielzeit im Browser: Voreinstellungen, Zusammenfassungen und Umrechnung
// zwischen den Tages-Kacheln und der API (Minuten ab 00:00 lokal, Ende exklusiv).
//
// Rein, ohne Vue und ohne @nextcloud: läuft auch unter Node
// (frontend/tests/playtime.check.mjs). Das Backend prüft jede Eingabe
// unabhängig; die Prüfung hier ist nur Komfort.
//
// Kindertexte (Owner-Entscheid 21.10.2026): dieselben Sätze wie im Welt-Mod
// (kid_text in src/gameworld/provisioner/time_mod.py), nie "0 Uhr",
// "Mitternacht", ein Datum oder eine Kurzform; Tagesbezug "Heute", "Morgen",
// "Am Samstag", "Nächsten Samstag", eine Uhrzeit nur bei echter Startzeit.

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
	taeglich: week((weekday) => apiDay(weekday, true, 60, 540, 1140)),
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
function rangeText(start, end) {
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
		const window = rangeText(first.window_start, first.window_end)
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
					: (rangeText(first.window_start, first.window_end) ?? 'ohne Limit')
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
	return `Offen ${label} ${rangeText(first.window_start, first.window_end) ?? 'ganztags'}`
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

function longName(weekday) {
	return WEEKDAYS[weekday - 1]?.long ?? ''
}

// Tagesbezug wie kid_text im Welt-Mod: "Heute ab 15 Uhr", "Morgen", "Am Samstag ab 9:30 Uhr",
// "Nächsten Mittwoch"; eine Uhrzeit nur bei Minute > 0. null bei fehlenden oder unsinnigen Angaben.
function dayPhrase(next) {
	const ahead = next?.days_ahead
	const minute = next?.minute
	if (!Number.isInteger(ahead) || ahead < 0 || ahead > 7 || !Number.isInteger(minute) || minute < 0 || minute >= FULL_DAY) {
		return null
	}
	let day
	if (ahead === 0) {
		day = 'Heute'
	} else if (ahead === 1) {
		day = 'Morgen'
	} else {
		const name = longName(next.weekday)
		if (!name) {
			return null
		}
		day = ahead === 7 ? `Nächsten ${name}` : `Am ${name}`
	}
	return minute > 0 ? `${day} ab ${formatClock(minute)}` : day
}

const KID_BLOCKED = Object.freeze({
	aufgebraucht: 'Deine Spielzeit für heute ist vorbei.',
	fenster: 'Jetzt ist keine Spielzeit.',
	tag: 'Heute ist kein Spieltag.',
})
// Vor dem Fenster, das heute noch öffnet.
const KID_EARLY = 'Jetzt ist noch keine Spielzeit.'
const WORLD_CLOSED = 'Diese Welt ist gerade zu.'

// Kindertext aus /api/my/playtime; null heißt: kein Block (keine Regeln oder heute nichts zu sagen).
export function kidPlaytimeText(playtime) {
	if (!playtime?.limited) {
		return null
	}
	const blocked = KID_BLOCKED[playtime.state]
	if (blocked) {
		const phrase = dayPhrase(playtime.next)
		if (!phrase) {
			return blocked
		}
		const today = playtime.next.days_ahead === 0
		const base = playtime.state === 'fenster' && today ? KID_EARLY : blocked
		return `${base} ${phrase}${today ? ' kannst du spielen.' : ' kannst du wieder spielen.'}`
	}
	const until = playtime.until_minute === null || playtime.until_minute === undefined
		? null
		: formatClock(playtime.until_minute)
	const remaining = playtime.remaining_minutes
	if (remaining === null || remaining === undefined) {
		return until ? `Heute kannst du bis ${until} spielen.` : null
	}
	const minutes = remaining === 1 ? 'Heute noch 1 Minute' : `Heute noch ${remaining} Minuten`
	return until ? `${minutes}, bis ${until}.` : `${minutes}.`
}

// Hinweis "aufgebraucht", "fenster", "tag" als Warnung, sonst Info.
export function kidPlaytimeBlocked(playtime) {
	return Boolean(KID_BLOCKED[playtime?.state])
}

// Chip einer Welt in der Kind-Ansicht: "Heute offen, 10 bis 12 Uhr" bzw.
// "Diese Welt ist gerade zu. Am Mittwoch ab 10 Uhr ist sie wieder offen."; null ohne Zeitfenster.
export function windowText(world) {
	if (world?.window_open === null || world?.window_open === undefined) {
		return null
	}
	const slot = world.window_next
	if (world.window_open) {
		return slot ? `Heute offen, ${rangeText(slot.start, slot.end)}` : 'Heute offen'
	}
	const phrase = slot ? dayPhrase({ weekday: slot.weekday, minute: slot.start, days_ahead: slot.days_ahead }) : null
	return phrase ? `${WORLD_CLOSED} ${phrase} ist sie wieder offen.` : WORLD_CLOSED
}

// Rückblick (04.1-07): "45 Min." je Kind und Welt.
export function minutesText(minutes) {
	return `${minutes} Min.`
}

// Pause-Seite: until_clock aus /api/pause (H:MM in der Haushalts-Zeitzone).
export function pauseUntilText(untilClock) {
	return typeof untilClock === 'string' && untilClock !== '' ? `Pause bis ${untilClock} Uhr` : 'Pause läuft'
}

// Rückblick-Einstellung (04.1-08): Vorgabe 20 Uhr, Auswahl 0:15 bis 23:45 im 15-Minuten-Raster.
// Minute 0 fehlt (Text-Regel: nie "0 Uhr"); vor 0:15 hat ein Abendrückblick keinen Nutzen.
export const REVIEW_DEFAULT_MINUTE = 1200

export function reviewTimeOptions() {
	return Array.from({ length: 95 }, (_, index) => {
		const value = 15 * (index + 1)
		return { value, label: formatClock(value) }
	})
}

// Auswahl für den gespeicherten Wert: Ein Wert außerhalb des Rasters (1..1439) erscheint als
// zusätzliche Option; 0 wird nie angezeigt, sondern auf 0:15 gesetzt und als ungespeichert markiert.
export function reviewSelectOptions(stored) {
	const options = reviewTimeOptions()
	if (stored === null || stored === undefined) {
		return { options, selected: REVIEW_DEFAULT_MINUTE, dirty: false }
	}
	if (!Number.isInteger(stored) || stored <= 0 || stored >= FULL_DAY) {
		return { options, selected: options[0].value, dirty: true }
	}
	if (!options.some((option) => option.value === stored)) {
		options.push({ value: stored, label: formatClock(stored) })
		options.sort((a, b) => a.value - b.value)
	}
	return { options, selected: stored, dirty: false }
}

// Talk-Hinweise (D-20, D-27); leer, wenn nichts zu sagen ist.
export const TALK_MISSING_TEXT = 'Talk ist auf diesem Server nicht installiert. Gameworld funktioniert ohne Talk-Räume weiter.'

export function talkHint(status) {
	if (!status) {
		return ''
	}
	if (status.available === false) {
		return TALK_MISSING_TEXT
	}
	if (status.owner_not_admin) {
		const owner = status.owner_display
			? `${status.owner_display}, der kein Verwalter mehr ist`
			: 'einem früheren Verwalter'
		return `Der Talk-Raum gehört noch ${owner}. Den Besitz kannst du in Talk in den Raum-Einstellungen übertragen.`
	}
	return ''
}

// Antwort mit applied false (WR-08): gespeichert, aber mindestens eine Welt trägt den neuen
// Stand noch nicht. Laufende Welten holt der 15-s-Takt nach, gestoppte der nächste Start.
export const NOT_APPLIED_TEXT = 'Gespeichert, aber noch nicht in jeder Welt angekommen. '
	+ 'Gameworld versucht es alle 15 Sekunden erneut, bis die Welt erreichbar ist. '
	+ 'Eine gestoppte Welt übernimmt die Änderung beim nächsten Start.'

// Hinweistext zur API-Antwort; leer, wenn alle Welten den neuen Stand schon tragen.
export function notAppliedText(result) {
	return result?.applied === false ? NOT_APPLIED_TEXT : ''
}
