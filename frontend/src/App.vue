<template>
	<NcContent app-name="gameworld">
		<NcAppContent>
			<div class="gameworld">
				<h2>Gameworld</h2>
				<p class="gameworld__hint">
					Jede Welt ist privat: Nur wer den Weltschlüssel kennt, kann beitreten. Gameworld kündigt keine Welt im Internet an.
				</p>

				<form class="gameworld__form" @submit.prevent="submit">
					<NcTextField
						v-model="name"
						label="Weltname"
						:maxlength="40"
						:disabled="creating" />
					<NcButton
						type="submit"
						variant="primary"
						:disabled="creating || name.trim() === ''">
						<template v-if="creating" #icon>
							<NcLoadingIcon :size="20" />
						</template>
						Welt erstellen
					</NcButton>
				</form>

				<NcNoteCard v-if="createdKey" type="success">
					Welt erstellt. Weltschlüssel für den Beitritt: <strong>{{ createdKey }}</strong>
				</NcNoteCard>
				<NcNoteCard v-if="error" type="error">
					{{ error }}
				</NcNoteCard>

				<NcLoadingIcon v-if="loading" :size="32" />
				<p v-else-if="worlds.length === 0" class="gameworld__empty">
					Noch keine Welt. Erstelle die erste Welt mit einem Namen.
				</p>
				<table v-else class="gameworld__list">
					<thead>
						<tr>
							<th>Name</th>
							<th>UDP-Port</th>
							<th>Status</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="world in worlds" :key="world.id">
							<td>{{ world.name }}</td>
							<td>{{ world.port }}</td>
							<td>{{ statusText(world) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</NcAppContent>
	</NcContent>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import NcAppContent from '@nextcloud/vue/components/NcAppContent'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcContent from '@nextcloud/vue/components/NcContent'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import { createWorld, listWorlds } from './api.js'

const STATUS_TEXT = {
	running: 'läuft',
	exited: 'gestoppt',
	created: 'gestoppt',
	missing: 'Container fehlt',
	unknown: 'Docker nicht erreichbar',
}

const worlds = ref([])
const loading = ref(true)
const creating = ref(false)
const name = ref('')
const createdKey = ref('')
const error = ref('')

function errorText(err) {
	const detail = err?.response?.data?.detail
	if (typeof detail === 'string' && detail !== '') {
		return detail
	}
	return 'Die Anfrage an Gameworld ist fehlgeschlagen.'
}

function statusText(world) {
	if (world.op_state === 'failed') {
		return `Fehler: ${world.last_error ?? 'unbekannt'}`
	}
	return STATUS_TEXT[world.docker_status] ?? world.docker_status
}

async function refresh() {
	try {
		worlds.value = await listWorlds()
	} catch (err) {
		error.value = errorText(err)
	} finally {
		loading.value = false
	}
}

async function submit() {
	if (creating.value || name.value.trim() === '') {
		return
	}
	creating.value = true
	error.value = ''
	createdKey.value = ''
	try {
		const world = await createWorld(name.value.trim())
		// Nur diese eine Antwort enthält den Schlüssel; die Liste zeigt ihn nie.
		createdKey.value = world.world_key
		name.value = ''
		await refresh()
	} catch (err) {
		error.value = errorText(err)
	} finally {
		creating.value = false
	}
}

onMounted(refresh)
</script>

<style scoped>
.gameworld {
	max-width: 720px;
	padding: 24px;
}

.gameworld__hint {
	margin-bottom: 16px;
	color: var(--color-text-maxcontrast);
}

.gameworld__form {
	display: flex;
	gap: 12px;
	align-items: flex-end;
	margin-bottom: 16px;
}

.gameworld__form button {
	flex-shrink: 0;
}

.gameworld__empty {
	margin-top: 16px;
}

.gameworld__list {
	width: 100%;
	margin-top: 16px;
	border-collapse: collapse;
}

.gameworld__list th,
.gameworld__list td {
	padding: 8px;
	text-align: start;
	border-bottom: 1px solid var(--color-border);
}
</style>
