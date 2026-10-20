<!-- Verwalteransicht: das Dashboard der Eltern (seit 03-02 nur für die Gruppe admin). -->
<template>
	<div class="gameworld">
		<h2>Gameworld</h2>
		<p class="gameworld__hint">
			Jede Welt ist privat: Nur eingeladene Nextcloud-Konten können beitreten. Gameworld kündigt keine Welt im Internet an.
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

		<NcNoteCard v-if="createdWorld" type="success">
			<p>Welt erstellt. Lade jetzt Spieler ein.</p>
			<NcButton variant="primary" @click="openInvite(createdWorld)">
				Spieler einladen
			</NcButton>
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
					<th>Spieler</th>
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
						<NcNoteCard v-if="world.access_restart_needed" type="warning" class="gameworld__restart">
							Neustart nötig, damit nur Eingeladene spielen können.
						</NcNoteCard>
					</td>
					<td class="gameworld__invited">
						{{ invitedText(world) }}
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
						<template v-if="!world.delete_only">
							<NcButton @click="openInvite(world)">
								Einladen
							</NcButton>
							<NcButton @click="openPlayers(world)">
								Spieler
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

		<InviteDialog
			v-if="inviteWorld"
			:key="`invite-${inviteWorld.id}`"
			:world="inviteWorld"
			@done="refresh"
			@close="inviteWorld = null" />
		<PlayerManager
			v-if="playersWorld"
			:key="`players-${playersWorld.id}`"
			:world="playersWorld"
			@changed="refresh"
			@invite="switchToInvite"
			@close="playersWorld = null" />

		<!-- Hat sich ein Elternteil selbst eingeladen, steht hier die eigene Verbindungsinfo. -->
		<section v-if="myWorlds.length > 0" class="gameworld__mine">
			<h3>Meine Verbindungsinfo</h3>
			<ConnectionCard v-for="world in myWorlds" :key="world.id" :world="world" />
		</section>

		<JoinHostSettings />
	</div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcProgressBar from '@nextcloud/vue/components/NcProgressBar'
import NcRadioGroup from '@nextcloud/vue/components/NcRadioGroup'
import NcRadioGroupButton from '@nextcloud/vue/components/NcRadioGroupButton'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import ConnectionCard from '../components/ConnectionCard.vue'
import InviteDialog from '../components/InviteDialog.vue'
import JoinHostSettings from '../components/JoinHostSettings.vue'
import PlayerManager from '../components/PlayerManager.vue'
import SetupCheck from '../components/SetupCheck.vue'
import {
	createWorld,
	deleteWorld,
	errorText,
	listMyWorlds,
	listPresets,
	listWorlds,
	restartWorld,
	startWorld,
	stopWorld,
} from '../api.js'

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
// Nach dem Erstellen: { id, name } der neuen Welt für den Hinweis "Lade jetzt Spieler ein".
const createdWorld = ref(null)
// Offene Dialoge: { id, name } der Welt oder null.
const inviteWorld = ref(null)
const playersWorld = ref(null)
// Fehler einer Aktion: bleibt stehen, bis die nächste Aktion startet.
const error = ref('')
// Fehler beim Abfragen der Liste: verschwindet beim nächsten erfolgreichen Abruf.
const listError = ref('')
// Welt-ID -> true, solange für diese Welt eine Aktion läuft.
const busy = reactive({})
const pendingDelete = ref(null)
// Eigene Welten, falls der Verwalter sich selbst eingeladen hat (gleiche Daten wie in der Spieleransicht).
const myWorlds = ref([])

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

// Nur id und Name gehen an die Dialoge; die Liste darf sich beim Polling ändern.
function openInvite(world) {
	playersWorld.value = null
	inviteWorld.value = { id: world.id, name: world.name }
}

function openPlayers(world) {
	inviteWorld.value = null
	playersWorld.value = { id: world.id, name: world.name }
}

function switchToInvite() {
	const world = playersWorld.value
	if (world) {
		openInvite(world)
	}
}

// Spielernamen kommen gefiltert aus der API ([A-Za-z0-9_-]), Ausgabe nur per Textinterpolation.
function invitedText(world) {
	const invited = world.invited_players ?? []
	return invited.length === 0 ? 'Noch niemand eingeladen' : invited.join(', ')
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
		// Nach der Verwalterliste (deren Abgleich zuerst): eigene Welten, Fehler hier nur still.
		const mine = await listMyWorlds().catch(() => null)
		if (seq === refreshSeq) {
			worlds.value = result
			listError.value = ''
			if (mine !== null) {
				myWorlds.value = mine
			}
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
	createdWorld.value = null
	try {
		const world = await createWorld(name.value.trim(), selectedPreset.value)
		createdWorld.value = { id: world.id, name: world.name }
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
	max-width: 1040px;
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
.gameworld__invited,
.gameworld__memory-text {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.gameworld__memory {
	min-width: 160px;
}

.gameworld__mine {
	margin-top: 32px;
}

.gameworld__restart {
	margin-top: 8px;
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
