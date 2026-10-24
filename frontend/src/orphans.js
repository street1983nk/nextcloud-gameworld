// Pure helpers for the section "leftovers from earlier installations" (06-UI-SPEC B3),
// without Vue; checked by frontend/tests/orphans.check.mjs. Names only reach the DOM
// through text interpolation. All texts come from the i18n dictionaries (area core).
import { formatDate } from './backup.js'
import { t } from './i18n/index.js'

export const CLEANUP_DOCS_URL = 'https://github.com/street1983nk/nextcloud-gameworld/blob/master/docs/install.md#cleanup'

export function introText() {
	return t('core.orphans.intro')
}

export function lifecycleText() {
	return t('core.orphans.lifecycle')
}

export function emptyText() {
	return t('core.orphans.empty')
}

// Hint about the host script; the component renders the code parts as <code>.
export function scriptSegments() {
	return Object.freeze([
		{ text: t('core.orphans.script.before'), code: false },
		{ text: 'gameworld-orphans.sh', code: true },
		{ text: t('core.orphans.script.middle'), code: false },
		{ text: '--remove-containers', code: true },
		{ text: t('core.orphans.script.or'), code: false },
		{ text: '--remove-volumes', code: true },
		{ text: t('core.orphans.script.end'), code: false },
	].map((part) => Object.freeze(part)))
}

export function scriptText() {
	return scriptSegments().map((part) => part.text).join('')
}

export function containerQuestion(name) {
	return t('core.orphans.containerQuestion', { name })
}

export function volumeQuestion(name) {
	return t('core.orphans.volumeQuestion', { name })
}

function createdPart(created) {
	return typeof created === 'string' && created !== '' ? t('core.orphans.created', { date: formatDate(created) }) : ''
}

// Docker state: only "running" counts as running, everything else (exited, created, dead)
// as stopped.
export function containerMeta(container) {
	const state = t(container?.state === 'running' ? 'core.orphans.state.running' : 'core.orphans.state.stopped')
	const created = createdPart(container?.created)
	return created === ''
		? t('core.orphans.meta.state', { state })
		: t('core.orphans.meta.stateCreated', { state, created })
}

export function volumeMeta(volume) {
	return createdPart(volume?.created)
}

export function removedText(kind, name) {
	return t(kind === 'container' ? 'core.orphans.removed.container' : 'core.orphans.removed.volume', { name })
}

export function inUseText(name) {
	return t('core.orphans.inUse', { name })
}

export function unavailableText(errorText) {
	return t('core.orphans.unavailable', { error: errorText })
}
