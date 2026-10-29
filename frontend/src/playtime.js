// Playtime in the browser: presets, summaries and conversion between the day
// tiles and the API (minutes from 00:00 local time, end exclusive).
//
// Pure, without Vue and without Nextcloud packages: also runs under Node
// (frontend/tests/playtime.check.mjs). The backend validates every input
// independently; the check here is only for convenience.
//
// Kid texts (owner decision 21.10.2026): in German the same sentences as the world
// mod (kid_text in src/gameworld/provisioner/time_mod.py), never "0 Uhr",
// "Mitternacht", a date or an abbreviation; day reference "Heute", "Morgen",
// "Am Samstag", "Nächsten Samstag", a clock time only for a real start time.
// All texts come from the i18n dictionaries (area core); sentences that combine a
// day and a time use one template per language with a {when} placeholder.
import { t, tn } from './i18n/index.js'

const FULL_DAY = 1440
// Defaults when a tile switches from "whole day" to a time window.
const DEFAULT_START = 540
const DEFAULT_END = 1140
// Chips stay short; if the text gets longer, the time window is dropped (it is in the dialog).
const MAX_CHIP = 30

// ISO weekdays, 1 = Monday.
const ISO_WEEKDAYS = Object.freeze([1, 2, 3, 4, 5, 6, 7])

// { weekday, short, long } per ISO weekday in the UI language ("Mo"/"Montag" in German).
export function weekdays() {
	return Object.freeze(ISO_WEEKDAYS.map((weekday) => Object.freeze({
		weekday,
		short: t(`core.playtime.weekdayShort.${weekday}`),
		long: t(`core.playtime.weekdayLong.${weekday}`),
	})))
}

// German "45 min", "1 Std", "1 Std 30 min"
export function formatMinutes(minutes) {
	const hours = Math.floor(minutes / 60)
	const rest = minutes % 60
	if (hours === 0) {
		return t('core.playtime.duration.minutes', { minutes: rest })
	}
	return rest === 0
		? t('core.playtime.duration.hours', { hours })
		: t('core.playtime.duration.hoursMinutes', { hours, minutes: rest })
}

function clockParts(minutes) {
	return { hours: Math.floor(minutes / 60), minutes: String(minutes % 60).padStart(2, '0') }
}

// Start of a range: German "19", "19:30" (without "Uhr", for "9 bis 19 Uhr").
function clockShort(minutes) {
	const parts = clockParts(minutes)
	return minutes % 60 === 0
		? t('core.playtime.clock.rangeStartHour', parts)
		: t('core.playtime.clock.hourMinute', parts)
}

// German "19 Uhr", "19:30" (with minutes without "Uhr", owner decision 22.10.2026);
// 1440 is "24 Uhr" (end of the day). English "19:00", French "19 h" and "19 h 30".
export function formatClock(minutes) {
	const parts = clockParts(minutes)
	return minutes % 60 === 0
		? t('core.playtime.clock.hour', parts)
		: t('core.playtime.clock.hourMinute', parts)
}

// Daily limit choice: 15 min to 4 h in steps of 15 minutes; "no limit" separately.
export function limitOptions() {
	return Object.freeze(
		Array.from({ length: 16 }, (_, index) => Object.freeze({ value: 15 * (index + 1), label: formatMinutes(15 * (index + 1)) })),
	)
}

export function noLimitOption() {
	return Object.freeze({ value: null, label: t('core.playtime.noLimit') })
}

function apiDay(weekday, allowed, limit = null, start = null, end = null) {
	return Object.freeze({ weekday, allowed, limit_minutes: limit, window_start: start, window_end: end })
}

function week(rule) {
	return Object.freeze(ISO_WEEKDAYS.map((weekday) => rule(weekday)))
}

// Presets after O-07 in the API format; none = no rules (opt-in, O-10).
export const PRESETS = Object.freeze({
	keine: null,
	wochenende: week((weekday) => (weekday >= 6 ? apiDay(weekday, true, 120, 540, 1140) : apiDay(weekday, false))),
	taeglich: week((weekday) => apiDay(weekday, true, 60, 540, 1140)),
	schultage: week((weekday) => (weekday >= 6
		? apiDay(weekday, true, 120, 540, 1140)
		: apiDay(weekday, true, 60, 900, 1140))),
})

// Suggestion for the holidays: every day 2 h, 9 to 20 o'clock.
export const HOLIDAY_PRESET = week((weekday) => apiDay(weekday, true, 120, 540, 1200))

function shortName(weekday) {
	return t(`core.playtime.weekdayShort.${weekday}`)
}

// German "Jeden Tag", "Sa und So", "Mo bis Fr", "Mi", "Mo, Mi und Fr"; inline uses the
// lower-case "jeden Tag" for the middle of a sentence.
function daysLabel(days, inline = false) {
	const sorted = [...days].sort((a, b) => a - b)
	if (sorted.length === 7) {
		return t(inline ? 'core.playtime.days.everyInline' : 'core.playtime.days.every')
	}
	if (sorted.length === 1) {
		return shortName(sorted[0])
	}
	const contiguous = sorted.every((weekday, index) => index === 0 || weekday === sorted[index - 1] + 1)
	if (contiguous && sorted.length >= 3) {
		return t('core.playtime.days.range', { from: shortName(sorted[0]), to: shortName(sorted[sorted.length - 1]) })
	}
	const names = sorted.map(shortName)
	return t('core.playtime.days.list', { list: names.slice(0, -1).join(', '), last: names[names.length - 1] })
}

// German "9 bis 19 Uhr", "bis 19 Uhr", "ab 9 Uhr", "ganztags"; null without a window.
function rangeText(start, end) {
	if (start === null || end === null) {
		return null
	}
	if (start === 0 && end === FULL_DAY) {
		return t('core.playtime.range.allDay')
	}
	if (start === 0) {
		return t('core.playtime.range.until', { end: formatClock(end) })
	}
	if (end === FULL_DAY) {
		return t('core.playtime.range.from', { start: formatClock(start) })
	}
	return t('core.playtime.range.between', { start: clockShort(start), end: formatClock(end) })
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

// Short text for a child's chip (API days or null).
export function summarize(days) {
	if (!days) {
		return t('core.playtime.summary.none')
	}
	const allowed = days.filter((entry) => entry.allowed)
	if (allowed.length === 0) {
		return t('core.playtime.summary.noPlayDay')
	}
	const groups = groupBy(allowed, (entry) => `${entry.limit_minutes}|${entry.window_start}|${entry.window_end}`)
	if (groups.length === 1) {
		const { first, weekdays: groupDays } = groups[0]
		const label = daysLabel(groupDays)
		const limit = first.limit_minutes === null ? null : formatMinutes(first.limit_minutes)
		const window = rangeText(first.window_start, first.window_end)
		let head = label
		const parts = []
		if (groupDays.length === 7) {
			if (limit) {
				head = t('core.playtime.summary.daysRule', { days: label, rule: limit })
			}
		} else if (limit) {
			parts.push(groupDays.length > 1 ? t('core.playtime.summary.each', { limit }) : limit)
		}
		if (!limit && !window) {
			return t('core.playtime.summary.daysNoLimit', { days: label })
		}
		const withWindow = [head, ...parts, ...(window ? [window] : [])].join(', ')
		if (withWindow.length <= MAX_CHIP || !limit || !window) {
			return withWindow
		}
		return [head, ...parts].join(', ')
	}
	if (groups.length === 2) {
		return groups
			.map(({ first, weekdays: groupDays }) => {
				const rule = first.limit_minutes !== null
					? formatMinutes(first.limit_minutes)
					: (rangeText(first.window_start, first.window_end) ?? t('core.playtime.noLimit'))
				return t('core.playtime.summary.daysRule', { days: daysLabel(groupDays), rule })
			})
			.join(', ')
	}
	return t('core.playtime.summary.custom')
}

// Chip of a world from time_window: German "Offen Mi 10 bis 12 Uhr"; empty without a window.
export function windowSummary(days) {
	if (!days) {
		return ''
	}
	const open = days.filter((entry) => entry.open)
	if (open.length === 0) {
		return t('core.playtime.window.closed')
	}
	const groups = groupBy(open, (entry) => `${entry.window_start}|${entry.window_end}`)
	const label = daysLabel(open.map((entry) => entry.weekday), true)
	if (groups.length > 1) {
		return t('core.playtime.window.varies', { days: label })
	}
	const { first } = groups[0]
	const range = rangeText(first.window_start, first.window_end) ?? t('core.playtime.range.allDay')
	return t('core.playtime.window.open', { days: label, range })
}

// Tile model: { weekday, allowed, limit, fullDay, start, end } (minutes).
function tile(weekday, allowed, limit, fullDay, start, end) {
	return { weekday, allowed, limit, fullDay, start, end }
}

// API days (or null) into editable tiles; always copies.
export function fromApiDays(days) {
	return ISO_WEEKDAYS.map((weekday) => {
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

// Tiles into API days; a day that is not allowed carries neither limit nor window.
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

// World window (time_window or null) into tiles without limit.
export function fromWindowDays(days) {
	return ISO_WEEKDAYS.map((weekday) => {
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

// Tiles into world window days; "ganzer Tag" means 0 to 1440.
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

// Weekday -> hint text for tiles whose end is not after their start.
export function validateDays(tiles) {
	const problems = {}
	for (const entry of tiles) {
		if (entry.allowed && !entry.fullDay && entry.end <= entry.start) {
			problems[entry.weekday] = t('core.playtime.validate.endAfterStart')
		}
	}
	return problems
}

// German "heute 45 von 60 min"
export function usageText(usedSeconds, limitMinutes) {
	return t('core.playtime.usage', { used: Math.floor(usedSeconds / 60), limit: limitMinutes })
}

// Minutes into a clock time for <input type="time"> (1440 shows 00:00).
export function minutesToDate(minutes) {
	const value = minutes % FULL_DAY
	return new Date(2000, 0, 1, Math.floor(value / 60), value % 60)
}

// Clock time from the picker into minutes; as end, 00:00 means midnight (1440).
export function dateToMinutes(date, isEnd) {
	const minutes = date.getHours() * 60 + date.getMinutes()
	return isEnd && minutes === 0 ? FULL_DAY : minutes
}

const WEEKDAY_INDEX = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 }

// ISO weekday (1..7) now in the household time zone.
export function weekdayIn(timeZone, now = new Date()) {
	try {
		const name = new Intl.DateTimeFormat('en-US', { timeZone, weekday: 'short' }).format(now)
		return WEEKDAY_INDEX[name] ?? null
	} catch {
		return null
	}
}

// Rule of a child that applies today (holiday plan when holidays are running and one is set).
export function todayRule(child, holidayActive, weekday) {
	const plan = holidayActive && child.holiday ? child.holiday : child.normal
	return plan?.find((entry) => entry.weekday === weekday) ?? null
}

function longName(weekday) {
	return ISO_WEEKDAYS.includes(weekday) ? t(`core.playtime.weekdayLong.${weekday}`) : ''
}

// Day reference like kid_text in the world mod: German "Heute ab 15 Uhr", "Morgen",
// "Am Samstag ab 9:30", "Nächsten Mittwoch"; a clock time only for minute > 0. null for
// missing or nonsensical input. The phrase fills {when} in the sentence templates.
function dayPhrase(next) {
	const ahead = next?.days_ahead
	const minute = next?.minute
	if (!Number.isInteger(ahead) || ahead < 0 || ahead > 7 || !Number.isInteger(minute) || minute < 0 || minute >= FULL_DAY) {
		return null
	}
	let day
	if (ahead === 0) {
		day = t('core.playtime.when.today')
	} else if (ahead === 1) {
		day = t('core.playtime.when.tomorrow')
	} else {
		const name = longName(next.weekday)
		if (!name) {
			return null
		}
		day = t(ahead === 7 ? 'core.playtime.when.next' : 'core.playtime.when.on', { day: name })
	}
	return minute > 0 ? t('core.playtime.when.withTime', { day, time: formatClock(minute) }) : day
}

// Blocking states of /api/my/playtime (API values, not translated).
const KID_BLOCKED_STATES = Object.freeze(['aufgebraucht', 'fenster', 'tag'])

function blockedText(state) {
	return KID_BLOCKED_STATES.includes(state) ? t(`core.playtime.kid.blocked.${state}`) : null
}

// Kid text from /api/my/playtime; null means no block (no rules or nothing to say today).
export function kidPlaytimeText(playtime) {
	if (!playtime?.limited) {
		return null
	}
	const blocked = blockedText(playtime.state)
	if (blocked) {
		const phrase = dayPhrase(playtime.next)
		if (!phrase) {
			return blocked
		}
		const today = playtime.next.days_ahead === 0
		// Before the window that still opens today.
		const base = playtime.state === 'fenster' && today ? t('core.playtime.kid.early') : blocked
		return t(today ? 'core.playtime.kid.playToday' : 'core.playtime.kid.playAgain', { base, when: phrase })
	}
	const until = playtime.until_minute === null || playtime.until_minute === undefined
		? null
		: formatClock(playtime.until_minute)
	const remaining = playtime.remaining_minutes
	if (remaining === null || remaining === undefined) {
		return until ? t('core.playtime.kid.untilOnly', { until }) : null
	}
	const minutes = tn('core.playtime.kid.remaining', remaining)
	return until
		? t('core.playtime.kid.remainingUntil', { minutes, until })
		: t('core.playtime.kid.remainingOnly', { minutes })
}

// "aufgebraucht", "fenster", "tag" show as a warning, everything else as info.
export function kidPlaytimeBlocked(playtime) {
	return KID_BLOCKED_STATES.includes(playtime?.state)
}

// Chip of a world in the kid view: German "Heute offen, 10 bis 12 Uhr" or
// "Diese Welt ist gerade zu. Am Mittwoch ab 10 Uhr ist sie wieder offen."; null without a time window.
export function windowText(world) {
	if (world?.window_open === null || world?.window_open === undefined) {
		return null
	}
	const slot = world.window_next
	if (world.window_open) {
		return slot
			? t('core.playtime.world.openTodayRange', { range: rangeText(slot.start, slot.end) })
			: t('core.playtime.world.openToday')
	}
	const closed = t('core.playtime.world.closed')
	const phrase = slot ? dayPhrase({ weekday: slot.weekday, minute: slot.start, days_ahead: slot.days_ahead }) : null
	return phrase ? t('core.playtime.world.opensAgain', { closed, when: phrase }) : closed
}

// Daily summary (04.1-07): German "45 Min." per child and world.
export function minutesText(minutes) {
	return t('core.playtime.minutesShort', { minutes })
}

// Break page: until_clock from /api/pause (H:MM in the household time zone).
export function pauseUntilText(untilClock) {
	return typeof untilClock === 'string' && untilClock !== ''
		? t('core.playtime.pause.until', { until: untilClock })
		: t('core.playtime.pause.running')
}

// Review setting (04.1-08): default 20:00, choice 0:15 to 23:45 in a 15 minute grid.
// Minute 0 is missing (text rule: never "0 Uhr"); before 0:15 an evening review has no use.
export const REVIEW_DEFAULT_MINUTE = 1200

export function reviewTimeOptions() {
	return Array.from({ length: 95 }, (_, index) => {
		const value = 15 * (index + 1)
		return { value, label: formatClock(value) }
	})
}

// Choice for the saved value: a value outside the grid (1..1439) appears as an
// additional option; 0 is never shown but set to 0:15 and marked as unsaved.
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

// Talk hints (D-20); empty when there is nothing to say. A former manager as Talk owner
// is no longer an info hint but the warning from formerOwnerText (UI-SPEC B4).
export function talkMissingText() {
	return t('core.playtime.talk.missing')
}

export function talkHint(status) {
	if (!status) {
		return ''
	}
	if (status.available === false) {
		return talkMissingText()
	}
	return ''
}

// Talk room takeover (UI-SPEC B4, D-16/D-19). Talk does not let Gameworld change the
// owner, so only "recreate room" is left. Names and tokens only as text, never as HTML.
export function formerOwnerText(ownerDisplay) {
	if (ownerDisplay) {
		return t('core.playtime.talk.formerOwner', { owner: ownerDisplay })
	}
	return t('core.playtime.talk.formerOwnerUnknown')
}

export function recreateQuestion(worldName, ownerDisplay) {
	const owner = ownerDisplay || t('core.playtime.talk.formerManager')
	return t('core.playtime.talk.recreateQuestion', { world: worldName, owner })
}

export function recreatedText() {
	return t('core.playtime.talk.recreated')
}

// Locked case: text before and after the occ command, so the command can be shown as <code>.
export function orphanedBefore() {
	return t('core.playtime.talk.orphanedBefore')
}

export function orphanedAfter() {
	return t('core.playtime.talk.orphanedAfter')
}

export function orphanedCommand(token) {
	return `occ talk:room:delete ${token}`
}

export function orphanedText(token) {
	return `${orphanedBefore()}${orphanedCommand(token)}${orphanedAfter()}`
}

// Response with applied false (WR-08): saved, but at least one world does not carry the new
// state yet. Running worlds catch up within the 15 s cycle, stopped ones on their next start.
export function notAppliedMessage() {
	return t('core.playtime.notApplied')
}

// Hint for an API response; empty when every world already carries the new state.
export function notAppliedText(result) {
	return result?.applied === false ? notAppliedMessage() : ''
}
