<!-- Sieben Tages-Kacheln Mo bis So: für den Wochenplan eines Kindes, den Ferienplan und das Zeitfenster einer Welt (ohne Limit). -->
<template>
	<div class="day-tiles">
		<div
			v-for="entry in days"
			:key="entry.weekday"
			class="day-tiles__tile"
			:class="{ 'day-tiles__tile--off': !entry.allowed }"
			:data-weekday="entry.weekday">
			<div class="day-tiles__name">
				{{ longName(entry.weekday) }}
			</div>
			<NcCheckboxRadioSwitch
				type="switch"
				:model-value="entry.allowed"
				:disabled="disabled"
				@update:model-value="patch(entry.weekday, { allowed: $event })">
				{{ withLimit ? 'Spielen erlaubt' : 'Offen' }}
			</NcCheckboxRadioSwitch>
			<template v-if="entry.allowed">
				<NcSelect
					v-if="withLimit"
					:model-value="limitOption(entry.limit)"
					:options="limitOptions"
					:clearable="false"
					:searchable="false"
					:disabled="disabled"
					input-label="Tageslimit"
					@update:model-value="patch(entry.weekday, { limit: $event?.value ?? null })" />
				<NcCheckboxRadioSwitch
					:model-value="entry.fullDay"
					:disabled="disabled"
					@update:model-value="patch(entry.weekday, { fullDay: $event })">
					ganzer Tag
				</NcCheckboxRadioSwitch>
				<div v-if="!entry.fullDay" class="day-tiles__window">
					<NcDateTimePickerNative
						type="time"
						label="von"
						step="900"
						:model-value="minutesToDate(entry.start)"
						:disabled="disabled"
						@update:model-value="onTime(entry.weekday, 'start', $event)" />
					<NcDateTimePickerNative
						type="time"
						label="bis"
						step="900"
						:model-value="minutesToDate(entry.end)"
						:disabled="disabled"
						@update:model-value="onTime(entry.weekday, 'end', $event)" />
				</div>
				<p v-if="problems[entry.weekday]" class="day-tiles__problem">
					{{ problems[entry.weekday] }}
				</p>
			</template>
			<p v-else class="day-tiles__off">
				{{ withLimit ? 'Kein Spieltag' : 'Geschlossen' }}
			</p>
			<NcButton
				v-if="entry.weekday === 1"
				variant="tertiary"
				:disabled="disabled"
				@click="copyToSchoolDays">
				Für alle Schultage übernehmen
			</NcButton>
		</div>
	</div>
</template>

<script setup>
import { computed } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcDateTimePickerNative from '@nextcloud/vue/components/NcDateTimePickerNative'
import NcSelect from '@nextcloud/vue/components/NcSelect'
import {
	LIMIT_OPTIONS,
	NO_LIMIT_OPTION,
	WEEKDAYS,
	dateToMinutes,
	minutesToDate,
	validateDays,
} from '../playtime.js'

defineProps({
	// Mit Tageslimit (Kinder) oder ohne (Welt-Zeitfenster).
	withLimit: { type: Boolean, default: true },
	disabled: { type: Boolean, default: false },
})

// Kacheln aus playtime.js: { weekday, allowed, limit, fullDay, start, end }.
const days = defineModel('days', { type: Array, required: true })

const limitOptions = [NO_LIMIT_OPTION, ...LIMIT_OPTIONS]
const problems = computed(() => validateDays(days.value))

function longName(weekday) {
	return WEEKDAYS[weekday - 1].long
}

function limitOption(limit) {
	return limitOptions.find((option) => option.value === limit) ?? NO_LIMIT_OPTION
}

// Immer eine neue Liste, damit der Elterndialog die Änderung sieht.
function patch(weekday, changes) {
	days.value = days.value.map((entry) => (entry.weekday === weekday ? { ...entry, ...changes } : entry))
}

// Ein geleertes Zeitfeld ändert nichts; 00:00 als Ende heißt Mitternacht.
function onTime(weekday, field, date) {
	if (!date || Number.isNaN(date.getTime())) {
		return
	}
	patch(weekday, { [field]: dateToMinutes(date, field === 'end') })
}

// Montag auf Dienstag bis Freitag kopieren.
function copyToSchoolDays() {
	const monday = days.value.find((entry) => entry.weekday === 1)
	if (!monday) {
		return
	}
	days.value = days.value.map((entry) => (entry.weekday >= 2 && entry.weekday <= 5 ? { ...monday, weekday: entry.weekday } : entry))
}
</script>

<style scoped>
.day-tiles {
	display: grid;
	grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
	gap: 12px;
}

.day-tiles__tile {
	display: flex;
	flex-direction: column;
	gap: 8px;
	padding: 12px;
	border: 1px solid var(--color-border);
	border-radius: var(--border-radius-large);
	background: var(--color-main-background);
}

.day-tiles__tile--off {
	background: var(--color-background-hover);
}

/* NcSelect bringt eine Mindestbreite mit; in der Kachel bleibt es in deren Breite. */
.day-tiles__tile :deep(.v-select.select) {
	min-width: 0;
	width: 100%;
	max-width: 100%;
}

.day-tiles__tile :deep(.button-vue__text) {
	white-space: normal;
	text-align: start;
}

.day-tiles__name {
	font-weight: bold;
}

.day-tiles__window {
	display: flex;
	gap: 8px;
}

.day-tiles__off {
	margin: 0;
	color: var(--color-text-maxcontrast);
}

.day-tiles__problem {
	margin: 0;
	color: var(--color-text-error, var(--color-error));
}
</style>
