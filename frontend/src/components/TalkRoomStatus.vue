<!-- Talk-Raum einer Welt (TALK-01, D-17, D-27): Link in Talk, Schalter "Nur lesen" und Hinweis zum Raum-Besitz.
     Ohne Talk zeigt die Verwaltung den Hinweis einmal oberhalb der Liste, hier steht dann nichts. -->
<template>
	<div v-if="status && status.available" class="talk-room">
		<template v-if="status.has_room">
			<a
				v-if="roomUrl"
				class="talk-room__link"
				:href="roomUrl"
				target="_blank"
				rel="noopener noreferrer">
				Talk-Raum öffnen
			</a>
			<NcCheckboxRadioSwitch
				type="switch"
				:model-value="readOnly"
				:disabled="saving"
				@update:model-value="toggle">
				Nur lesen
			</NcCheckboxRadioSwitch>
		</template>
		<span v-else class="talk-room__pending">Talk-Raum wird eingerichtet</span>
		<NcNoteCard v-if="hint" type="info" class="talk-room__note">
			{{ hint }}
		</NcNoteCard>
		<NcNoteCard v-if="notice" type="warning" class="talk-room__note">
			{{ notice }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error" class="talk-room__note">
			{{ error }}
		</NcNoteCard>
	</div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { generateUrl } from '@nextcloud/router'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { errorText, setTalkReadOnly } from '../api.js'
import { talkHint } from '../playtime.js'

const props = defineProps({
	// { id, name } der Welt.
	world: { type: Object, required: true },
	// Eintrag der Welt aus GET /api/talk plus available; null, solange nichts geladen ist.
	status: { type: Object, default: null },
})
const emit = defineEmits(['changed'])

const saving = ref(false)
const notice = ref('')
const error = ref('')
// Eigene Anzeige des Schalters, damit er beim Speichern nicht zurückspringt.
const readOnly = ref(Boolean(props.status?.read_only))

watch(() => props.status?.read_only, (value) => {
	if (!saving.value) {
		readOnly.value = Boolean(value)
	}
})

const roomUrl = computed(() => (props.status?.token
	? generateUrl('/call/{token}', { token: props.status.token })
	: ''))

const hint = computed(() => talkHint(props.status))

async function toggle(on) {
	if (saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	readOnly.value = on
	try {
		const result = await setTalkReadOnly(props.world.id, on)
		readOnly.value = result.read_only
		if (result.applied === false) {
			notice.value = 'Gespeichert. Talk übernimmt es beim nächsten Abgleich.'
		}
		emit('changed')
	} catch (err) {
		readOnly.value = !on
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
</script>

<style scoped>
.talk-room {
	display: flex;
	flex-direction: column;
	gap: 4px;
	margin-top: 8px;
}

.talk-room__link {
	color: var(--color-primary-element);
	text-decoration: underline;
}

.talk-room__pending {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.talk-room__note {
	margin: 4px 0 0;
}
</style>
