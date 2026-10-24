// Pure texts for the adult switch (ROLLE-04, UI-SPEC B2), without Vue; checked by
// frontend/tests/adult.check.mjs. Names only go out through text interpolation, never
// as HTML. All texts come from the i18n dictionaries (area core).
import { t, tn } from './i18n/index.js'

// Confirmation dialog, paragraph 1 (bold): consequences for one or more accounts.
// More than one name takes the plural, everything else the singular.
export function confirmLead(names) {
	return tn('core.adult.confirmLead', names.length > 1 ? names.length : 1, { names: names.join(', ') })
}

// Paragraphs 2 and 3.
export function confirmScope() {
	return t('core.adult.confirmScope')
}

export function confirmWarning() {
	return t('core.adult.confirmWarning')
}

// Paragraph 4, only when a playtime rule exists (has_rules).
export function rulesKeptText(name) {
	return t('core.adult.rulesKept', { name })
}

export function adultOnText(name) {
	return t('core.adult.on', { name })
}

export function adultOffText(name) {
	return t('core.adult.off', { name })
}

// The account has become a manager in the meantime (409).
export function nowVerwalterText(name) {
	return t('core.adult.nowVerwalter', { name })
}

// Invite succeeded, marking did not. API messages usually end with a full stop; it is
// dropped here because the sentence continues.
export function adultInviteWarning(name, detail) {
	const reason = String(detail ?? '').trim().replace(/[.]+$/, '')
	return t('core.adult.inviteWarning', { name, reason })
}

export function invitedLabel(labels) {
	return t('core.adult.invitedLabel', { labels: labels.join(', ') })
}

export function switchMeta() {
	return t('core.adult.switchMeta')
}

export function inviteSwitchMeta() {
	return t('core.adult.inviteSwitchMeta')
}

export function PLAYTIME_RESTING_TEXT(name) {
	return t('core.adult.playtimeResting', { name })
}
