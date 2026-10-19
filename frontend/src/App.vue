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
							<th>Aktionen</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="world in worlds" :key="world.id">
							<td>{{ world.name }}</td>
							<td>{{ world.port }}</td>
							<td>{{ statusText(world) }}</td>
							<td class="gameworld__actions">
								<NcLoadingIcon v-if="busy[world.id]" :size="20" />
								<NcButton
									v-if="world.docker_status !== 'running'"
									:disabled="Boolean(busy[world.id])"
									@click="run(world, startWorld)">
									Starten
								</NcButton>
								<NcButton
									v-else
									:disabled="Boolean(busy[world.id])"
									@click="run(world, stopWorld)">
									Stoppen
								</NcButton>
								<NcButton
									variant="error"
									:disabled="Boolean(busy[world.id])"
									@click="pendingDelete = world">
									Löschen
								</NcButton>
							</td>
						</tr>
					</tbody>
				</table>

				<NcDialog
					v-if="pendingDelete"
					:open="true"
					name="Welt löschen"
					:message="deleteMessage"
					:buttons="deleteButtons"
					@update:open="onDialogOpen" />
			</div>
		</NcAppContent>
	</NcContent>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import NcAppContent from '@nextcloud/vue/components/NcAppContent'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcContent from '@nextcloud/vue/components/NcContent'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import { createWorld, deleteWorld, listWorlds, startWorld, stopWorld } from './api.js'

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
// Welt-ID -> true, solange für diese Welt eine Aktion läuft.
const busy = reactive({})
const pendingDelete = ref(null)

const deleteMessage = computed(() => pendingDelete.value
	? `Welt »${pendingDelete.value.name}« endgültig löschen? Die Spielwelt und alle gebauten Dinge werden entfernt.`
	: '')

const deleteButtons = [
	{ label: 'Abbrechen', variant: 'tertiary' },
	{
		label: 'Endgültig löschen',
		variant: 'error',
		callback: () => {
			const world = pendingDelete.value
			pendingDelete.value = null
			if (world) {
				run(world, deleteWorld)
			}
		},
	},
]

function onDialogOpen(open) {
	if (!open) {
		pendingDelete.value = null
	}
}

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

// Führt eine Aktion für eine Welt aus und lädt danach die Liste neu, weil
// der Status immer aus Docker kommt.
async function run(world, action) {
	if (busy[world.id]) {
		return
	}
	busy[world.id] = true
	error.value = ''
	try {
		await action(world.id)
	} catch (err) {
		error.value = errorText(err)
	} finally {
		await refresh()
		delete busy[world.id]
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

.gameworld__actions {
	display: flex;
	gap: 8px;
	align-items: center;
}

.gameworld__list th,
.gameworld__list td {
	padding: 8px;
	text-align: start;
	border-bottom: 1px solid var(--color-border);
}
</style>
