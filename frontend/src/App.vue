<template>
	<NcContent app-name="gameworld">
		<NcAppContent>
			<div class="gameworld">
				<h2>Gameworld</h2>
				<p class="gameworld__hint">
					Jede Welt ist privat: Nur wer den Weltschlüssel kennt, kann beitreten. Gameworld kündigt keine Welt im Internet an.
				</p>

				<SetupCheck @update:ok="onSetupOk" @checked="refresh" />

				<NcNoteCard v-if="presetsError" type="error">
					{{ presetsError }}
				</NcNoteCard>

				<form class="gameworld__form" @submit.prevent="submit">
					<NcRadioGroup v-if="presets.length > 0" v-model="selectedPreset" label="Spielart">
						<NcRadioGroupButton
							v-for="preset in presets"
							:key="preset.id"
							:value="preset.id"
							:label="preset.title"
							:disabled="creating" />
					</NcRadioGroup>
					<p v-if="selectedDescription" class="gameworld__preset-hint">
						{{ selectedDescription }}
					</p>
					<div class="gameworld__create">
						<NcTextField
							v-model="name"
							label="Weltname"
							:maxlength="40"
							:disabled="creating" />
						<NcButton
							type="submit"
							variant="primary"
							:disabled="!canCreate">
							<template v-if="creating" #icon>
								<NcLoadingIcon :size="20" />
							</template>
							Welt erstellen
						</NcButton>
					</div>
				</form>

				<NcNoteCard v-if="createdKey" type="success">
					Welt erstellt. Weltschlüssel für den Beitritt: <strong>{{ createdKey }}</strong>
				</NcNoteCard>
				<NcNoteCard v-if="error" type="error">
					{{ error }}
				</NcNoteCard>
				<NcNoteCard v-if="listError" type="warning">
					{{ listError }}
				</NcNoteCard>

				<NcLoadingIcon v-if="loading" :size="32" />
				<p v-else-if="worlds.length === 0" class="gameworld__empty">
					Noch keine Welt. Wähle eine Spielart, gib einen Namen ein und klicke auf Welt erstellen.
				</p>
				<table v-else class="gameworld__list">
					<thead>
						<tr>
							<th>Name</th>
							<th>Spielart</th>
							<th>UDP-Port</th>
							<th>Status</th>
							<th>Arbeitsspeicher</th>
							<th>Aktionen</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="world in worlds" :key="world.id" :data-world-id="world.id">
							<td>
								{{ world.name }}
								<div v-if="world.status === 'running'" class="gameworld__players">
									{{ playersText(world) }}
								</div>
							</td>
							<td>{{ world.preset_title }}</td>
							<td>{{ world.port }}</td>
							<td>
								<NcChip
									class="gameworld__status"
									:text="world.status_text"
									:variant="chipVariant(world.status)"
									no-close />
							</td>
							<td class="gameworld__memory">
								<template v-if="world.memory_used_bytes !== null && world.memory_limit_bytes">
									<NcProgressBar
										:value="memoryPercent(world)"
										:error="memoryPercent(world) >= MEMORY_WARN_PERCENT"
										:aria-label="memoryText(world)" />
									<span class="gameworld__memory-text">{{ memoryText(world) }}</span>
								</template>
								<span v-else class="gameworld__memory-text">nicht aktiv</span>
							</td>
							<td class="gameworld__actions">
								<NcLoadingIcon v-if="busy[world.id]" :size="20" />
								<!-- Weltdaten fehlen oder Erstellen brach ab: Starten würde eine leere oder halbe Welt starten, nur Löschen bleibt. -->
								<template v-if="!world.delete_only">
									<template v-if="isActive(world)">
										<NcButton
											:disabled="actionsLocked(world)"
											@click="run(world, stopWorld)">
											Stoppen
										</NcButton>
										<NcButton
											:disabled="actionsLocked(world)"
											@click="run(world, restartWorld)">
											Neustarten
										</NcButton>
									</template>
									<NcButton
										v-else
										:disabled="actionsLocked(world)"
										@click="run(world, startWorld)">
										Starten
									</NcButton>
								</template>
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
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import NcAppContent from '@nextcloud/vue/components/NcAppContent'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcContent from '@nextcloud/vue/components/NcContent'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcProgressBar from '@nextcloud/vue/components/NcProgressBar'
import NcRadioGroup from '@nextcloud/vue/components/NcRadioGroup'
import NcRadioGroupButton from '@nextcloud/vue/components/NcRadioGroupButton'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import SetupCheck from './components/SetupCheck.vue'
import {
	createWorld,
	deleteWorld,
	listPresets,
	listWorlds,
	restartWorld,
	startWorld,
	stopWorld,
} from './api.js'

// Statuscodes kommen aus der API (worlds/status.py), die Texte ebenfalls.
const CHIP_VARIANT = {
	running: 'success',
	starting: 'warning',
	stopped: 'tertiary',
	error: 'error',
	unknown: 'warning',
}
const POLL_MS = 5000
// Ab diesem Anteil am Limit wird der RAM-Balken als Fehler markiert.
const MEMORY_WARN_PERCENT = 90
const MIB = 1048576
const GIB = 1073741824

const worlds = ref([])
const loading = ref(true)
const creating = ref(false)
// Bis der Setup-Check bestanden ist, bleibt "Welt erstellen" gesperrt.
const setupOk = ref(false)
const presets = ref([])
const presetsError = ref('')
const selectedPreset = ref('')
const name = ref('')
const createdKey = ref('')
// Fehler einer Aktion: bleibt stehen, bis die nächste Aktion startet.
const error = ref('')
// Fehler beim Abfragen der Liste: verschwindet beim nächsten erfolgreichen Abruf.
const listError = ref('')
// Welt-ID -> true, solange für diese Welt eine Aktion läuft.
const busy = reactive({})
const pendingDelete = ref(null)

const selectedDescription = computed(() => presets.value.find((preset) => preset.id === selectedPreset.value)?.description ?? '')

const canCreate = computed(() => setupOk.value
	&& !creating.value
	&& selectedPreset.value !== ''
	&& name.value.trim() !== '')

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
	// FastAPI-Validierungsfehler (422) liefern detail als Liste von Objekten;
	// so erreicht die deutsche Meldung zu ungültigen Weltnamen die Eltern.
	const msg = Array.isArray(detail) ? detail[0]?.msg : undefined
	if (typeof msg === 'string' && msg !== '') {
		return msg.replace(/^Value error, /, '')
	}
	return 'Die Anfrage an Gameworld ist fehlgeschlagen.'
}

function chipVariant(status) {
	return CHIP_VARIANT[status] ?? 'warning'
}

// Namen kommen gefiltert aus der API ([A-Za-z0-9_-]) und werden nur per Textinterpolation ausgegeben.
function playersText(world) {
	const players = world.players ?? []
	if (players.length === 0) {
		return 'Niemand online'
	}
	return `Gerade online: ${players.join(', ')}`
}

// Unter 1 GiB ganze MB, ab 1 GiB GB mit höchstens einer Nachkommastelle ("1 GB", "1,5 GB").
function formatBytes(bytes) {
	if (bytes < GIB) {
		return `${Math.round(bytes / MIB)} MB`
	}
	const gb = (Math.round((bytes / GIB) * 10) / 10).toString().replace('.', ',')
	return `${gb} GB`
}

function memoryPercent(world) {
	const percent = Math.round((world.memory_used_bytes / world.memory_limit_bytes) * 100)
	return Math.min(100, Math.max(0, percent))
}

function memoryText(world) {
	return `Arbeitsspeicher: ${formatBytes(world.memory_used_bytes)} von ${formatBytes(world.memory_limit_bytes)}`
}

function isActive(world) {
	return world.status === 'running' || world.status === 'starting'
}

// Ohne Docker lässt sich nichts starten oder stoppen; Löschen bleibt (eigener Dialog).
function actionsLocked(world) {
	return Boolean(busy[world.id]) || world.status === 'unknown'
}

// Abrufe können sich überholen (Polling, Aktion, Setup-Check); nur die Antwort
// des zuletzt gestarteten Abrufs darf die Liste setzen.
let refreshSeq = 0

async function refresh() {
	const seq = ++refreshSeq
	try {
		const result = await listWorlds()
		if (seq === refreshSeq) {
			worlds.value = result
			listError.value = ''
		}
	} catch (err) {
		if (seq === refreshSeq) {
			listError.value = errorText(err)
		}
	} finally {
		loading.value = false
	}
}

// Alle 5 s, nur bei sichtbarem Tab; nach jeder Aktion sofort (run, submit).
let timer = null
// Nach dem Abbau darf ein noch laufender Abruf keinen neuen Timer setzen.
let unmounted = false

function schedule() {
	clearTimeout(timer)
	timer = null
	if (!unmounted && document.visibilityState === 'visible') {
		timer = setTimeout(async () => {
			await refresh()
			schedule()
		}, POLL_MS)
	}
}

function onTabChange() {
	if (document.visibilityState === 'visible') {
		refresh()
	}
	schedule()
}

async function loadPresets() {
	try {
		presets.value = await listPresets()
		selectedPreset.value = presets.value[0]?.id ?? ''
		presetsError.value = ''
	} catch (err) {
		presetsError.value = `Die Spielarten konnten nicht geladen werden: ${errorText(err)}`
	}
}

// Die Weltenliste aktualisiert das Ereignis checked nach jedem Prüflauf (auch "Erneut prüfen").
function onSetupOk(ok) {
	setupOk.value = ok
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
	if (!canCreate.value) {
		return
	}
	creating.value = true
	error.value = ''
	createdKey.value = ''
	try {
		const world = await createWorld(name.value.trim(), selectedPreset.value)
		// Nur diese eine Antwort enthält den Schlüssel; die Liste zeigt ihn nie.
		createdKey.value = world.world_key
		name.value = ''
	} catch (err) {
		error.value = errorText(err)
	} finally {
		await refresh()
		creating.value = false
	}
}

onMounted(async () => {
	document.addEventListener('visibilitychange', onTabChange)
	await Promise.all([loadPresets(), refresh()])
	schedule()
})

onUnmounted(() => {
	unmounted = true
	clearTimeout(timer)
	timer = null
	document.removeEventListener('visibilitychange', onTabChange)
})
</script>

<style scoped>
.gameworld {
	max-width: 820px;
	padding: 24px;
}

.gameworld__hint {
	margin-bottom: 16px;
	color: var(--color-text-maxcontrast);
}

.gameworld__form {
	display: flex;
	flex-direction: column;
	gap: 12px;
	margin-bottom: 16px;
}

.gameworld__preset-hint {
	margin: 0;
	color: var(--color-text-maxcontrast);
}

.gameworld__create {
	display: flex;
	gap: 12px;
	align-items: flex-end;
}

.gameworld__create button {
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

.gameworld__players,
.gameworld__memory-text {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.gameworld__memory {
	min-width: 160px;
}

.gameworld__actions {
	display: flex;
	flex-wrap: wrap;
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
