<!-- Abschnitt "Ferien": Zeiträume für den ganzen Haushalt (O-08); die Regeln für die Ferien stehen je Kind im Spielzeit-Dialog. -->
<template>
	<section class="holidays">
		<h3>{{ t('kids.holidays.title') }}</h3>
		<p class="holidays__hint">
			{{ t('kids.holidays.hint') }}
		</p>

		<p v-if="holidays.length === 0" class="holidays__empty">
			{{ t('kids.holidays.empty') }}
		</p>
		<ul v-else class="holidays__list">
			<li v-for="entry in holidays" :key="entry.id" :data-holiday-id="entry.id">
				<span class="holidays__label">{{ entry.label || t('kids.holidays.defaultLabel') }}</span>
				<span class="holidays__range">{{ t('kids.holidays.range', { start: formatDate(entry.start_date), end: formatDate(entry.end_date) }) }}</span>
				<NcChip v-if="entry.active" :text="t('kids.holidays.running')" variant="success" no-close />
				<NcButton
					variant="tertiary"
					:disabled="busy"
					:aria-label="t('kids.holidays.removeLabel', { label: entry.label || t('kids.holidays.defaultLabel') })"
					@click="pendingRemove = entry">
					{{ t('kids.holidays.remove') }}
				</NcButton>
			</li>
		</ul>

		<form class="holidays__form" @submit.prevent="add">
			<NcTextField
				v-model="label"
				:label="t('kids.holidays.labelField')"
				:maxlength="60"
				:disabled="busy" />
			<NcDateTimePickerNative
				v-model="startDate"
				type="date"
				:label="t('kids.holidays.from')"
				:disabled="busy" />
			<NcDateTimePickerNative
				v-model="endDate"
				type="date"
				:label="t('kids.holidays.to')"
				:disabled="busy" />
			<NcButton type="submit" variant="primary" :disabled="!canAdd">
				<template v-if="busy" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('kids.holidays.add') }}
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
			:name="t('kids.holidays.removeTitle')"
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
import { dateLocale, t } from '../i18n/index.js'
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

// "2026-12-24" in the account language: de "24.12.2026", en and fr "24/12/2026". UTC on both
// sides, so the browser time zone never shifts the day; anything unexpected is shown as is.
function formatDate(value) {
	const [yyyy, mm, dd] = String(value).split('-').map(Number)
	if (!yyyy || !mm || !dd) {
		return String(value)
	}
	return new Date(Date.UTC(yyyy, mm - 1, dd)).toLocaleDateString(dateLocale(), {
		timeZone: 'UTC', day: '2-digit', month: '2-digit', year: 'numeric',
	})
}

const rangeProblem = computed(() => (startDate.value && endDate.value && isoDate(endDate.value) < isoDate(startDate.value)
	? t('kids.holidays.rangeProblem')
	: ''))
const canAdd = computed(() => !busy.value && Boolean(startDate.value) && Boolean(endDate.value) && !rangeProblem.value)

const removeMessage = computed(() => (pendingRemove.value
	? t('kids.holidays.removeQuestion', {
		label: pendingRemove.value.label || t('kids.holidays.defaultLabel'),
		start: formatDate(pendingRemove.value.start_date),
		end: formatDate(pendingRemove.value.end_date),
	})
	: ''))

// Computed so that the button labels are resolved when rendering.
const removeButtons = computed(() => [
	{ label: t('kids.common.cancel'), variant: 'tertiary' },
	{
		label: t('kids.holidays.remove'),
		variant: 'error',
		callback: () => {
			const entry = pendingRemove.value
			pendingRemove.value = null
			if (entry) {
				remove(entry)
			}
		},
	},
])

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
