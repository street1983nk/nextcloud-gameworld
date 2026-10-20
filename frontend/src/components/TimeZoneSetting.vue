<!-- Zeitzone des Haushalts (O-02): Vorgabe Europe/Berlin, Vorschlag aus diesem Browser; Spielzeiten und Ferien rechnen in dieser Zone. -->
<template>
	<section class="time-zone">
		<h4>Zeitzone für Spielzeiten</h4>
		<p class="time-zone__hint">
			Spielzeiten, Zeitfenster und Ferien gelten in dieser Zeitzone.
		</p>
		<div class="time-zone__form">
			<NcTimezonePicker v-model="value" :uid="pickerId" />
			<NcButton
				v-if="browserZone && browserZone !== value"
				variant="tertiary"
				:disabled="saving"
				@click="value = browserZone">
				Zeitzone dieses Browsers übernehmen
			</NcButton>
			<NcButton variant="primary" :disabled="saving || !changed" @click="save">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				Speichern
			</NcButton>
		</div>
		<p v-if="browserZone && browserZone !== value" class="time-zone__hint">
			Dieser Browser nutzt {{ browserZone }}.
		</p>
		<NcNoteCard v-if="notice" type="success">
			{{ notice }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>
	</section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTimezonePicker from '@nextcloud/vue/components/NcTimezonePicker'
import { errorText, setTimeZone } from '../api.js'

const DEFAULT_ZONE = 'Europe/Berlin'

const props = defineProps({
	// time_zone aus GET /api/playtime; leer, solange nichts geladen ist.
	timeZone: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

const pickerId = 'gameworld-time-zone'
const saved = ref(props.timeZone || DEFAULT_ZONE)
const value = ref(saved.value)
const saving = ref(false)
const notice = ref('')
const error = ref('')

// Nur aus dem Browser, kein externer Dienst (T-04-36).
function readBrowserZone() {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
	} catch {
		return ''
	}
}
const browserZone = readBrowserZone()

const changed = computed(() => value.value !== '' && value.value !== saved.value)

// Neu geladene Werte übernehmen, solange nichts ungespeichert geändert wurde.
watch(() => props.timeZone, (zone) => {
	if (!zone) {
		return
	}
	if (value.value === saved.value) {
		value.value = zone
	}
	saved.value = zone
})

async function save() {
	if (!changed.value || saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		const result = await setTimeZone(value.value)
		saved.value = result.time_zone
		value.value = result.time_zone
		notice.value = result.applied === false
			? 'Gespeichert. Welten, die gerade nicht erreichbar sind, übernehmen die Zeitzone beim nächsten Start.'
			: 'Gespeichert. Die Spielzeiten rechnen ab sofort in dieser Zeitzone.'
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
</script>

<style scoped>
.time-zone {
	margin-top: 16px;
}

.time-zone__hint {
	margin: 4px 0;
	color: var(--color-text-maxcontrast);
}

.time-zone__form {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
}

.time-zone__form > :first-child {
	min-width: 260px;
}
</style>
