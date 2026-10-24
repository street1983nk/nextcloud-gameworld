// Texts for the manager groups (UI-SPEC B1, ROLLE-03): pure, without Vue, checked by
// node frontend/tests/roles.check.mjs. Group IDs only reach the page as text (text
// interpolation, never v-html). All texts come from the i18n dictionaries (area core)
// and are resolved on every call, so the account language set in main.js applies.
import { compareText, t } from './i18n/index.js'

export function sectionHint() {
	return t('core.roles.sectionHint')
}

export function childrenWarning() {
	return t('core.roles.childrenWarning')
}

export function boundaryText() {
	return t('core.roles.boundary')
}

export function onlyAdminText() {
	return t('core.roles.onlyAdmin')
}

export function ncAdminOnlyText() {
	return t('core.roles.ncAdminOnly')
}

export function searchDownText() {
	return t('core.roles.searchDown')
}

export function noScopeText() {
	return t('core.roles.noScope')
}

// Boundary hint in the invite dialog (D-01); null means no group, the component then
// shows noScopeText().
export function scopeHint(groups) {
	const list = Array.isArray(groups)
		? [...new Set(groups.map((gid) => String(gid)).filter((gid) => gid !== ''))]
		: []
	if (list.length === 0) {
		return null
	}
	list.sort(compareText)
	return t('core.roles.scopeHint', { groups: list.join(', ') })
}

export function groupAddedText(gid) {
	return t('core.roles.groupAdded', { gid })
}

export function groupRemovedText(gid) {
	return t('core.roles.groupRemoved', { gid })
}

export function groupUnknownText(gid) {
	return t('core.roles.groupUnknown', { gid })
}

export function loadErrorText(detail) {
	return t('core.roles.loadError', { detail })
}
