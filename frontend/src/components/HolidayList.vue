<!-- Abschnitt "Ferien": Zeiträume für den ganzen Haushalt (O-08); die Regeln für die Ferien stehen je Kind im Spielzeit-Dialog. -->
<template>
	<section class="holidays">
		<h3>Ferien</h3>
		<p class="holidays__hint">
			Gilt für alle Kinder. Was in den Ferien erlaubt ist, stellst du im Spielzeit-Dialog je Kind ein.
		</p>

		<p v-if="holidays.length === 0" class="holidays__empty">
			Noch keine Ferien eingetragen.
		</p>
		<ul v-else class="holidays__list">
			<li v-for="entry in holidays" :key="entry.id" :data-holiday-id="entry.id">
				<span class="holidays__label">{{ entry.label || 'Ferien' }}</span>
				<span class="holidays__range">{{ formatDate(entry.start_date) }} bis {{ formatDate(entry.end_date) }}</span>
				<NcChip v-if="entry.active" text="läuft gerade" variant="success" no-close />
				<NcButton
					variant="tertiary"
					:disabled="busy"
					:aria-label="`${entry.label || 'Ferien'} entfernen`"
					@click="pendingRemove = entry">
					Entfernen
				</NcButton>
			</li>
		</ul>

		<form class="holidays__form" @submit.prevent="add">
			<NcTextField
				v-model="label"
				label="Bezeichnung (optional)"
				:maxlength="60"
				:disabled="busy" />
			<NcDateTimePickerNative
				v-model="startDate"
				type="date"
				label="von"
				:disabled="busy" />
			<NcDateTimePickerNative
				v-model="endDate"
				type="date"
				label="bis"
				:disabled="busy" />
			<NcButton type="submit" variant="primary" :disabled="!canAdd">
				<template v-if="busy" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				Hinzufügen
			</NcButton>
		</form>
		<NcNoteCard v-if="rangeProblem" type="warning">
			{{ rangeProblem }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>
		<NcNoteCard v-if="pending" type="warning">
			{{ pending }}
		</NcNoteCard>

		<NcDialog
			v-if="pendingRemove"
			:open="true"
			name="Ferien entfernen"
			:message="removeMessage"
			:buttons="removeButtons"
			@update:open="onDialogOpen" />
	</section>
</template>

<script setup>
import { computed, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcDateTimePickerNative from '@nextcloud/vue/components/NcDateTimePickerNative'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import { addHoliday, errorText, removeHoliday } from '../api.js'
import { notAppliedText } from '../playtime.js'

defineProps({
	// holidays aus GET /api/playtime: { id, label, start_date, end_date, active }.
	holidays: { type: Array, default: () => [] },
})
const emit = defineEmits(['changed'])

const label = ref('')
const startDate = ref(null)
const endDate = ref(null)
const busy = ref(false)
const error = ref('')
const pendingRemove = ref(null)
// Gespeichert, aber noch nicht in jeder Welt (applied false, WR-08).
const pending = ref('')

// Datum aus dem Picker (lokale Mitternacht) als JJJJ-MM-TT.
function isoDate(date) {
	const yyyy = String(date.getFullYear()).padStart(4, '0')
	const mm = String(date.getMonth() + 1).padStart(2, '0')
	const dd = String(date.getDate()).padStart(2, '0')
	return `${yyyy}-${mm}-${dd}`
}

// "2026-12-24" -> "24.12.2026"
function formatDate(value) {
	const [yyyy, mm, dd] = String(value).split('-')
	return `${dd}.${mm}.${yyyy}`
}

const rangeProblem = computed(() => (startDate.value && endDate.value && isoDate(endDate.value) < isoDate(startDate.value)
	? 'Die Ferien enden nicht vor ihrem Beginn.'
	: ''))
const canAdd = computed(() => !busy.value && Boolean(startDate.value) && Boolean(endDate.value) && !rangeProblem.value)

const removeMessage = computed(() => (pendingRemove.value
	? `»${pendingRemove.value.label || 'Ferien'}« (${formatDate(pendingRemove.value.start_date)} bis ${formatDate(pendingRemove.value.end_date)}) entfernen? Danach gilt in diesem Zeitraum die normale Woche.`
	: ''))

const removeButtons = [
	{ label: 'Abbrechen', variant: 'tertiary' },
	{
		label: 'Entfernen',
		variant: 'error',
		callback: () => {
			const entry = pendingRemove.value
			pendingRemove.value = null
			if (entry) {
				remove(entry)
			}
		},
	},
]

function onDialogOpen(open) {
	if (!open) {
		pendingRemove.value = null
	}
}

async function add() {
	if (!canAdd.value) {
		return
	}
	busy.value = true
	error.value = ''
	pending.value = ''
	try {
		const result = await addHoliday(label.value.trim(), isoDate(startDate.value), isoDate(endDate.value))
		pending.value = notAppliedText(result)
		label.value = ''
		startDate.value = null
		endDate.value = null
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		busy.value = false
	}
}

async function remove(entry) {
	busy.value = true
	error.value = ''
	pending.value = ''
	try {
		const result = await removeHoliday(entry.id)
		pending.value = notAppliedText(result)
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		busy.value = false
	}
}
</script>

<style scoped>
.holidays {
	margin-top: 32px;
}

.holidays__hint,
.holidays__empty {
	color: var(--color-text-maxcontrast);
}

.holidays__list {
	margin: 8px 0;
}

.holidays__list li {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
	padding: 4px 0;
	border-bottom: 1px solid var(--color-border);
}

.holidays__label {
	font-weight: bold;
}

.holidays__range {
	color: var(--color-text-maxcontrast);
}

.holidays__form {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: flex-end;
	margin-top: 8px;
}

.holidays__form > * {
	flex: 1 1 180px;
	max-width: 280px;
}

.holidays__form > button {
	flex: 0 0 auto;
}
</style>
