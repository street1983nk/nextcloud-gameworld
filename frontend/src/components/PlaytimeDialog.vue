<!-- Spielzeit eines Kindes: Voreinstellungen, Wochenplan als Tages-Kacheln und eigene Regeln für die Ferien (O-07, O-08, O-10). -->
<template>
	<NcDialog
		:open="true"
		:name="`Spielzeit für ${child.display_name}`"
		size="large"
		@update:open="onOpen">
		<div class="playtime-dialog">
			<NcNoteCard v-if="child.adult" type="info">
				{{ PLAYTIME_RESTING_TEXT(child.display_name) }}
			</NcNoteCard>
			<p class="playtime-dialog__hint">
				Die Regeln gelten sofort in allen Welten zusammen. Wähle eine Voreinstellung und passe danach jeden Tag an.
			</p>
			<div class="playtime-dialog__presets" role="group" aria-label="Voreinstellungen">
				<NcButton
					v-for="choice in PRESET_CHOICES"
					:key="choice.key"
					:variant="activePreset === choice.key ? 'primary' : 'secondary'"
					:disabled="saving"
					@click="applyPreset(choice.key)">
					{{ choice.label }}
				</NcButton>
			</div>

			<p v-if="!limited" class="playtime-dialog__none">
				Ohne Regel spielt {{ child.display_name }} ohne Begrenzung. Wähle oben eine Voreinstellung, um Spielzeiten festzulegen.
			</p>
			<template v-else>
				<h3>Normale Woche</h3>
				<DayTiles v-model:days="normal" :disabled="saving" @update:days="activePreset = ''" />

				<h3>In den Ferien</h3>
				<NcCheckboxRadioSwitch v-model="ownHoliday" type="switch" :disabled="saving">
					Eigene Regeln in den Ferien
				</NcCheckboxRadioSwitch>
				<p v-if="!ownHoliday" class="playtime-dialog__hint">
					In den Ferien gilt dieselbe Woche wie oben.
				</p>
				<DayTiles v-else v-model:days="holiday" :disabled="saving" />
			</template>

			<NcNoteCard v-if="invalid" type="warning">
				Bei mindestens einem Tag liegt das Ende nicht nach dem Beginn.
			</NcNoteCard>
			<NcNoteCard v-if="error" type="error">
				{{ error }}
			</NcNoteCard>
			<NcNoteCard v-if="pending" type="warning">
				{{ pending }}
			</NcNoteCard>
		</div>

		<template #actions>
			<NcButton v-if="pending" variant="primary" @click="close">
				Schließen
			</NcButton>
			<template v-else>
				<NcButton variant="tertiary" :disabled="saving" @click="close">
					Abbrechen
				</NcButton>
				<NcButton variant="primary" :disabled="saving || invalid" @click="save">
					<template v-if="saving" #icon>
						<NcLoadingIcon :size="20" />
					</template>
					Speichern
				</NcButton>
			</template>
		</template>
	</NcDialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import DayTiles from './DayTiles.vue'
import { clearChildPlan, errorText, saveChildPlan } from '../api.js'
import { PLAYTIME_RESTING_TEXT } from '../adult.js'
import {
	HOLIDAY_PRESET,
	PRESETS,
	fromApiDays,
	notAppliedText,
	toApiDays,
	validateDays,
} from '../playtime.js'

const props = defineProps({
	// Kind aus GET /api/playtime: nc_user, display_name, has_rules, normal, holiday.
	child: { type: Object, required: true },
})
const emit = defineEmits(['saved', 'close'])

// Reihenfolge und Beschriftung der Voreinstellungsknöpfe (O-07); die Tage stehen in playtime.js.
const PRESET_CHOICES = [
	{ key: 'keine', label: 'Keine Begrenzung' },
	{ key: 'wochenende', label: 'Nur am Wochenende' },
	{ key: 'taeglich', label: 'Jeden Tag 1 Stunde' },
	{ key: 'schultage', label: 'Schultage kurz, Wochenende länger' },
]

// Ohne Regeln ist "Keine Begrenzung" gewählt (Opt-in, O-10).
const limited = ref(Boolean(props.child.has_rules && props.child.normal))
const activePreset = ref(limited.value ? '' : 'keine')
const normal = ref(fromApiDays(props.child.normal ?? PRESETS.wochenende))
const ownHoliday = ref(Boolean(props.child.holiday))
const holiday = ref(fromApiDays(props.child.holiday ?? HOLIDAY_PRESET))
const saving = ref(false)
const error = ref('')
// Gespeichert, aber noch nicht in jeder Welt (applied false, WR-08): Der Dialog bleibt mit Hinweis offen.
const pending = ref('')

const invalid = computed(() => limited.value && (
	Object.keys(validateDays(normal.value)).length > 0
	|| (ownHoliday.value && Object.keys(validateDays(holiday.value)).length > 0)))

// Eine Voreinstellung setzt die Kacheln; "Keine Begrenzung" blendet sie aus.
function applyPreset(key) {
	const days = PRESETS[key]
	if (!days) {
		limited.value = false
	} else {
		limited.value = true
		normal.value = fromApiDays(days)
	}
	// Erst nach dem Setzen markieren; DayTiles meldet nur Änderungen durch Eltern.
	activePreset.value = key
}

async function save() {
	if (saving.value || invalid.value) {
		return
	}
	saving.value = true
	error.value = ''
	try {
		let result
		if (limited.value) {
			result = await saveChildPlan(
				props.child.nc_user,
				toApiDays(normal.value),
				ownHoliday.value ? toApiDays(holiday.value) : null,
			)
		} else {
			result = await clearChildPlan(props.child.nc_user)
		}
		emit('saved')
		pending.value = notAppliedText(result)
		if (!pending.value) {
			emit('close')
		}
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

function close() {
	if (!saving.value) {
		emit('close')
	}
}

function onOpen(open) {
	if (!open) {
		close()
	}
}
</script>

<style scoped>
.playtime-dialog {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.playtime-dialog h3 {
	margin: 8px 0 0;
}

.playtime-dialog__hint,
.playtime-dialog__none {
	margin: 0;
	color: var(--color-text-maxcontrast);
}

.playtime-dialog__presets {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
}
</style>
