<!-- Handy-Seite Pause (ELTERN-01, D-01 bis D-06, D-25, D-29): Pause für alle Kinder in allen Welten. -->
<template>
	<div class="mobile-page">
		<h2>{{ t('kids.pause.title') }}</h2>

		<div v-if="loading" class="mobile-page__loading">
			<NcLoadingIcon :size="32" />
		</div>

		<template v-else>
			<template v-if="!pause?.active">
				<NcNoteCard type="info">
					{{ t('kids.pause.warning') }}
				</NcNoteCard>
				<NcNoteCard type="info">
					{{ t('kids.pause.notCounted') }}
				</NcNoteCard>
				<div class="mobile-page__buttons mobile-page__buttons--stack">
					<NcButton
						v-for="option in PAUSE_OPTIONS"
						:key="option.minutes"
						variant="primary"
						size="large"
						wide
						:disabled="saving"
						@click="start(option.minutes)">
						{{ tn('kids.pause.minutes', option.minutes) }}
					</NcButton>
				</div>
				<div class="mobile-page__buttons">
					<NcButton variant="secondary" :disabled="saving" @click="schluss">
						{{ t('kids.pause.stopToday') }}
					</NcButton>
				</div>
			</template>

			<template v-else-if="pause.art === 'schluss'">
				<div aria-live="polite">
					<NcNoteCard type="warning">
						{{ t('kids.pause.stoppedToday') }}
					</NcNoteCard>
				</div>
				<div class="mobile-page__buttons">
					<NcButton variant="primary" size="large" :disabled="saving" @click="end">
						{{ t('kids.pause.resume') }}
					</NcButton>
				</div>
			</template>

			<template v-else>
				<div aria-live="polite">
					<NcNoteCard type="warning">
						<strong>{{ pauseUntilText(pause.until_clock) }}</strong>
					</NcNoteCard>
				</div>
				<div class="mobile-page__buttons">
					<NcButton variant="primary" size="large" :disabled="saving" @click="end">
						{{ t('kids.pause.resume') }}
					</NcButton>
					<NcButton variant="secondary" size="large" :disabled="saving" @click="schluss">
						{{ t('kids.pause.stopToday') }}
					</NcButton>
				</div>
			</template>

			<NcNoteCard
				v-for="note in worldNotes"
				:key="note.key"
				type="info">
				{{ note.text }}
			</NcNoteCard>
		</template>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<div class="mobile-page__buttons mobile-page__back">
			<NcButton variant="tertiary" @click="navigate('')">
				{{ t('kids.common.back') }}
			</NcButton>
		</div>
	</div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { endPause, errorText, getPause, startPause, stopForToday } from '../api.js'
import { t, tn } from '../i18n/index.js'
import { pauseUntilText } from '../playtime.js'
import { navigate } from '../route.js'

// Exactly the durations the backend accepts (D-02); labels are resolved when rendering.
const PAUSE_OPTIONS = Object.freeze([
	{ minutes: 15 },
	{ minutes: 30 },
	{ minutes: 60 },
])
// Abruf nur bei sichtbarer Seite (T-04.1-39).
const POLL_MS = 15000

const loading = ref(true)
const saving = ref(false)
const error = ref('')
const pause = ref(null)
// Hinweise je Welt aus der letzten Aktion (D-25).
const worldNotes = ref([])

let timer = null
// Nur die Antwort des zuletzt gestarteten Abrufs zählt.
let loadSeq = 0

async function load() {
	const seq = ++loadSeq
	try {
		const result = await getPause()
		if (seq === loadSeq && !saving.value) {
			pause.value = result
			error.value = ''
		}
	} catch (err) {
		if (seq === loadSeq) {
			error.value = errorText(err)
		}
	} finally {
		if (seq === loadSeq) {
			loading.value = false
		}
	}
}

function notesFrom(result) {
	const notes = []
	for (const world of result?.worlds ?? []) {
		if (world.restarted) {
			notes.push({ key: `restart-${world.id}`, text: t('kids.pause.restarted', { name: world.name }) })
		} else if (world.applied === false) {
			notes.push({ key: `later-${world.id}`, text: t('kids.pause.later', { name: world.name }) })
		}
	}
	return notes
}

// Doppelklick-Schutz: solange saving läuft, startet keine zweite Aktion.
async function act(action) {
	if (saving.value) {
		return
	}
	saving.value = true
	error.value = ''
	worldNotes.value = []
	loadSeq += 1
	try {
		const result = await action()
		pause.value = result
		worldNotes.value = notesFrom(result)
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

function start(minutes) {
	return act(() => startPause(minutes))
}

function end() {
	return act(endPause)
}

function schluss() {
	return act(stopForToday)
}

// document.hidden: Tab im Hintergrund oder Handy gesperrt, dann kein Abruf.
function tick() {
	if (!document.hidden) {
		load()
	}
}

// Zurück auf der Seite (Fokus oder Rückkehr aus dem Verlauf): sofort frisch laden.
function onReturn() {
	if (!document.hidden && !saving.value) {
		load()
	}
}

onMounted(() => {
	load()
	timer = setInterval(tick, POLL_MS)
	window.addEventListener('focus', onReturn)
	window.addEventListener('pageshow', onReturn)
})

onUnmounted(() => {
	clearInterval(timer)
	window.removeEventListener('focus', onReturn)
	window.removeEventListener('pageshow', onReturn)
})
</script>

<style scoped>
.mobile-page {
	max-width: 820px;
	padding: 24px;
	box-sizing: border-box;
	overflow-wrap: anywhere;
}

.mobile-page__loading {
	padding: 16px 0;
}

.mobile-page__buttons {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	margin-top: 16px;
}

.mobile-page__buttons--stack {
	flex-direction: column;
	max-width: 360px;
}

.mobile-page__back {
	margin-top: 32px;
}

@media (max-width: 480px) {
	.mobile-page {
		padding: 12px;
	}

	.mobile-page__buttons > * {
		width: 100%;
	}

	.mobile-page__buttons--stack {
		max-width: none;
	}
}
</style>
