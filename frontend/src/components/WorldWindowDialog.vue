<!-- Zeitfenster einer Welt (ZEIT-05): dieselben Tages-Kacheln ohne Limit; außerhalb kommt kein Kind neu hinein, die Welt läuft weiter. -->
<template>
	<NcDialog
		:open="true"
		:name="`Zeitfenster für ${world.name}`"
		size="large"
		@update:open="onOpen">
		<div class="world-window">
			<p class="world-window__hint">
				Diese Welt ist nur zu diesen Zeiten offen. Eltern und Lehrkräfte kommen immer hinein.
			</p>
			<DayTiles v-model:days="days" :with-limit="false" :disabled="saving" />
			<p class="world-window__hint">
				Außerhalb der Zeiten läuft die Welt weiter, nur kommt niemand Neues hinein. Wer noch spielt, wird am Ende des Zeitfensters mit Vorwarnung getrennt.
			</p>
			<NcNoteCard v-if="invalid" type="warning">
				Bei mindestens einem Tag liegt das Ende nicht nach dem Beginn.
			</NcNoteCard>
			<NcNoteCard v-if="noOpenDay" type="warning">
				Mindestens ein Tag muss offen sein. Soll die Welt immer offen sein, wähle "Immer offen".
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
				<NcButton variant="secondary" :disabled="saving" @click="submit(true)">
					Immer offen
				</NcButton>
				<NcButton variant="primary" :disabled="saving || invalid || noOpenDay" @click="submit(false)">
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
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import DayTiles from './DayTiles.vue'
import { clearWorldWindow, errorText, setWorldWindow } from '../api.js'
import { fromWindowDays, notAppliedText, toWindowDays, validateDays } from '../playtime.js'

const props = defineProps({
	// { id, name, time_window } der Welt; time_window null heißt immer offen.
	world: { type: Object, required: true },
})
const emit = defineEmits(['saved', 'close'])

const days = ref(fromWindowDays(props.world.time_window))
const saving = ref(false)
const error = ref('')
// Gespeichert, aber noch nicht in der Welt (applied false, WR-08): Der Dialog bleibt mit Hinweis offen.
const pending = ref('')

const invalid = computed(() => Object.keys(validateDays(days.value)).length > 0)
const noOpenDay = computed(() => days.value.every((entry) => !entry.allowed))

// alwaysOpen: Fenster entfernen; sonst die sieben Tage speichern.
async function submit(alwaysOpen) {
	if (saving.value || (!alwaysOpen && (invalid.value || noOpenDay.value))) {
		return
	}
	saving.value = true
	error.value = ''
	try {
		const result = alwaysOpen
			? await clearWorldWindow(props.world.id)
			: await setWorldWindow(props.world.id, toWindowDays(days.value))
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
.world-window {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.world-window__hint {
	margin: 0;
	color: var(--color-text-maxcontrast);
}
</style>
