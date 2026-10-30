<!-- Manager view: the dashboard of the parents (since 03-02 for the group admin only). -->
<template>
	<div class="gameworld">
		<h2>Gameworld</h2>
		<p class="gameworld__hint">
			{{ t('parent.view.privacyHint') }}
		</p>

		<!-- Pause for all children (ELTERN-01, D-06): entry to the pause page and state of the running pause. -->
		<section class="gameworld__pause" :class="{ 'gameworld__pause--active': pause?.active }">
			<div class="gameworld__pause-text">
				<h3>{{ t('parent.view.pauseTitle') }}</h3>
				<p v-if="pause?.active" class="gameworld__pause-state" aria-live="polite">
					{{ pauseText }}
				</p>
			</div>
			<NcButton :variant="pause?.active ? 'secondary' : 'primary'" @click="navigate('pause')">
				{{ pause?.active ? t('parent.view.pauseManage') : t('parent.view.pauseOpen') }}
			</NcButton>
		</section>

		<SetupCheck @update:ok="onSetupOk" @checked="refresh" />

		<NcNoteCard v-if="presetsError" type="error">
			{{ presetsError }}
		</NcNoteCard>

		<form class="gameworld__form" @submit.prevent="submit">
			<NcRadioGroup v-if="presets.length > 0" v-model="selectedPreset" :label="t('parent.view.gameType')">
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
					:label="t('parent.view.worldName')"
					:maxlength="40"
					:disabled="creating" />
				<NcButton
					type="submit"
					variant="primary"
					:disabled="!canCreate">
					<template v-if="creating" #icon>
						<NcLoadingIcon :size="20" />
					</template>
					{{ t('parent.view.createWorld') }}
				</NcButton>
			</div>
		</form>

		<NcNoteCard v-if="createdWorld" type="success">
			<p>{{ t('parent.view.created') }}</p>
			<NcButton variant="primary" @click="openInvite(createdWorld)">
				{{ t('parent.common.invitePlayers') }}
			</NcButton>
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>
		<NcNoteCard v-if="listError" type="warning">
			{{ listError }}
		</NcNoteCard>

		<!-- Without Talk once above the list (D-20); the worlds keep running without Talk rooms. -->
		<NcNoteCard v-if="talk && talk.available === false" type="info">
			{{ talkHint(talk) }}
		</NcNoteCard>

		<NcLoadingIcon v-if="loading" :size="32" />
		<p v-else-if="worlds.length === 0" class="gameworld__empty">
			{{ t('parent.view.empty') }}
		</p>
		<table v-else class="gameworld__list">
			<thead>
				<tr>
					<th>{{ t('parent.view.column.name') }}</th>
					<th>{{ t('parent.view.column.gameType') }}</th>
					<th>{{ t('parent.view.column.port') }}</th>
					<th>{{ t('parent.view.column.status') }}</th>
					<th>{{ t('parent.view.column.players') }}</th>
					<th>{{ t('parent.view.column.memory') }}</th>
					<th>{{ t('parent.view.column.actions') }}</th>
				</tr>
			</thead>
			<tbody>
				<tr v-for="world in worlds" :key="world.id" :data-world-id="world.id">
					<td class="gameworld__name">
						{{ world.name }}
						<div v-if="world.status === 'running'" class="gameworld__players">
							{{ playersText(world) }}
						</div>
						<NcChip
							v-if="world.time_window"
							class="gameworld__window"
							:text="windowSummary(world.time_window)"
							variant="secondary"
							no-close />
						<TalkRoomStatus
							v-if="!world.delete_only"
							:world="world"
							:status="talkFor(world)"
							@changed="loadTalk" />
						<WorldLanguageSetting
							v-if="!world.delete_only"
							:world="world"
							@changed="refresh" />
					</td>
					<td>{{ world.preset_title }}</td>
					<td>{{ world.port }}</td>
					<td>
						<NcChip
							class="gameworld__status"
							:text="world.status_text"
							:variant="chipVariant(world.status)"
							no-close />
						<NcNoteCard v-if="world.access_restart_needed && world.time_restart_needed" type="warning" class="gameworld__restart">
							{{ t('parent.view.restart.accessAndTime') }}
						</NcNoteCard>
						<NcNoteCard v-else-if="world.access_restart_needed" type="warning" class="gameworld__restart">
							{{ t('parent.view.restart.access') }}
						</NcNoteCard>
						<NcNoteCard v-else-if="world.time_restart_needed" type="warning" class="gameworld__restart">
							{{ t('parent.view.restart.time') }}
						</NcNoteCard>
						<NcNoteCard v-else-if="world.events_restart_needed" type="warning" class="gameworld__restart">
							{{ t('parent.view.restart.events') }}
						</NcNoteCard>
						<!-- D-11: a failed job stays until the next one runs (also after reloading). -->
						<NcNoteCard v-if="world.backup_job?.state === 'failed'" type="error" class="gameworld__restart">
							{{ jobNote(world.backup_job) }}
						</NcNoteCard>
						<div v-else-if="world.backup_job?.state === 'running'" class="gameworld__job">
							{{ jobNote(world.backup_job) }}
						</div>
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
						<span v-else class="gameworld__memory-text">{{ t('parent.view.memoryInactive') }}</span>
					</td>
					<td class="gameworld__actions">
						<NcLoadingIcon v-if="busy[world.id]" :size="20" />
						<!-- World data missing or creation aborted: starting would start an empty or half world, only deleting remains. -->
						<template v-if="!world.delete_only">
							<template v-if="isActive(world)">
								<NcButton
									:disabled="actionsLocked(world)"
									@click="run(world, stopWorld)">
									{{ t('parent.view.action.stop') }}
								</NcButton>
								<NcButton
									:disabled="actionsLocked(world)"
									@click="run(world, restartWorld)">
									{{ t('parent.view.action.restart') }}
								</NcButton>
							</template>
							<NcButton
								v-else
								:disabled="actionsLocked(world)"
								@click="run(world, startWorld)">
								{{ t('parent.view.action.start') }}
							</NcButton>
						</template>
						<template v-if="!world.delete_only">
							<NcButton :disabled="backupBusy(world)" @click="openInvite(world)">
								{{ t('parent.common.invite') }}
							</NcButton>
							<NcButton :disabled="backupBusy(world)" @click="openPlayers(world)">
								{{ t('parent.view.action.players') }}
							</NcButton>
							<NcButton :disabled="backupBusy(world)" @click="openWindow(world)">
								{{ t('parent.view.action.timeWindow') }}
							</NcButton>
						</template>
						<!-- Also with missing world data: restoring rescues the world (D-15). -->
						<NcButton @click="openBackups(world)">
							{{ t('parent.view.action.backups') }}
						</NcButton>
						<NcButton
							variant="error"
							:disabled="Boolean(busy[world.id]) || backupBusy(world)"
							@click="pendingDelete = world">
							{{ t('parent.view.action.delete') }}
						</NcButton>
					</td>
				</tr>
			</tbody>
		</table>

		<NcDialog
			v-if="pendingDelete"
			:open="true"
			:name="t('parent.view.deleteTitle')"
			:message="deleteMessage"
			:buttons="deleteButtons"
			@update:open="onDialogOpen" />

		<InviteDialog
			v-if="inviteWorld"
			:key="`invite-${inviteWorld.id}`"
			:world="inviteWorld"
			:me="me"
			@done="refresh"
			@close="inviteWorld = null" />
		<PlayerManager
			v-if="playersWorld"
			:key="`players-${playersWorld.id}`"
			:world="playersWorld"
			@changed="refresh"
			@invite="switchToInvite"
			@close="playersWorld = null" />
		<WorldWindowDialog
			v-if="windowWorld"
			:key="`window-${windowWorld.id}`"
			:world="windowWorld"
			@saved="refresh"
			@close="windowWorld = null" />
		<BackupSection
			v-if="backupWorld"
			:key="`backups-${backupWorld.id}`"
			:world="backupWorld"
			:backup-job="backupJob"
			@changed="refresh"
			@close="backupsWorldId = null" />

		<PlaytimeSection
			:playtime="playtime"
			:loading="playtimeLoading"
			:error="playtimeError"
			@changed="loadPlaytime" />
		<HolidayList :holidays="playtime?.holidays ?? []" @changed="loadPlaytime" />

		<!-- If a parent invited themselves, their own connection info is shown here. -->
		<section v-if="myWorlds.length > 0" class="gameworld__mine">
			<h3>{{ t('parent.view.myConnection') }}</h3>
			<ConnectionCard v-for="world in myWorlds" :key="world.id" :world="world" />
		</section>

		<JoinHostSettings />
		<TimeZoneSetting :time-zone="playtime?.time_zone ?? ''" @changed="onTimeZoneChanged" />
		<ReviewSetting />
		<VerwalterGroupsSection v-if="me?.nc_admin === true" @forbidden="onVerwalterForbidden" />
		<NcNoteCard v-else-if="verwalterForbidden" type="error" class="gameworld__verwalter-forbidden">
			{{ ncAdminOnlyText() }}
		</NcNoteCard>
		<OrphanSection v-if="me?.nc_admin === true" @forbidden="onVerwalterForbidden" />
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
import BackupSection from '../components/BackupSection.vue'
import ConnectionCard from '../components/ConnectionCard.vue'
import HolidayList from '../components/HolidayList.vue'
import InviteDialog from '../components/InviteDialog.vue'
import JoinHostSettings from '../components/JoinHostSettings.vue'
import OrphanSection from '../components/OrphanSection.vue'
import PlayerManager from '../components/PlayerManager.vue'
import PlaytimeSection from '../components/PlaytimeSection.vue'
import ReviewSetting from '../components/ReviewSetting.vue'
import SetupCheck from '../components/SetupCheck.vue'
import TalkRoomStatus from '../components/TalkRoomStatus.vue'
import TimeZoneSetting from '../components/TimeZoneSetting.vue'
import VerwalterGroupsSection from '../components/VerwalterGroupsSection.vue'
import WorldLanguageSetting from '../components/WorldLanguageSetting.vue'
import WorldWindowDialog from '../components/WorldWindowDialog.vue'
import { formatBytes, jobNote } from '../backup.js'
import { t } from '../i18n/index.js'
import { pauseUntilText, talkHint, windowSummary } from '../playtime.js'
import { ncAdminOnlyText } from '../roles.js'
import { navigate } from '../route.js'
import {
	createWorld,
	deleteWorld,
	errorText,
	getPause,
	getPlaytime,
	getTalkStatus,
	listMyWorlds,
	listPresets,
	listWorlds,
	restartWorld,
	startWorld,
	stopWorld,
} from '../api.js'

defineProps({
	// Response of /api/me (App.vue); nc_admin shows the admin sections (convenience only,
	// locking happens on the server), invite_groups is used by the invite dialog.
	me: { type: Object, required: false, default: null },
})
// reload-me: App.vue reloads /api/me (rights revoked in the meantime, 403).
const emit = defineEmits(['reload-me'])

// Manager groups answered 403: the section disappears with the new /api/me, the notice stays.
const verwalterForbidden = ref(false)

function onVerwalterForbidden() {
	verwalterForbidden.value = true
	emit('reload-me')
}

// Status codes come from the API (worlds/status.py), and so do the texts.
const CHIP_VARIANT = {
	running: 'success',
	starting: 'warning',
	stopped: 'tertiary',
	error: 'error',
	unknown: 'warning',
	backing_up: 'warning',
	restoring: 'warning',
}
// Phase 5 (D-10): while a backup or restore is running, the actions of the world are locked.
const BACKUP_BUSY_STATUS = new Set(['backing_up', 'restoring'])
const POLL_MS = 5000
// Playtime (usage today) changes slowly: reload at most every 30 s.
const PLAYTIME_POLL_MS = 30000
// From this share of the limit on, the RAM bar is marked as an error.
const MEMORY_WARN_PERCENT = 90

const worlds = ref([])
const loading = ref(true)
const creating = ref(false)
// Until the setup check has passed, "Welt erstellen" stays locked.
const setupOk = ref(false)
const presets = ref([])
const presetsError = ref('')
const selectedPreset = ref('')
const name = ref('')
// After creating: { id, name } of the new world for the hint "Lade jetzt Spieler ein".
const createdWorld = ref(null)
// Open dialogs: { id, name } of the world or null.
const inviteWorld = ref(null)
const playersWorld = ref(null)
// Time window dialog: { id, name, time_window } copied on opening.
const windowWorld = ref(null)
// Backup section: the world ID only; data and backup_job come reactively from the polled
// list, otherwise the section would never see the end of a job (T-05-52).
const backupsWorldId = ref(null)
// Error of an action: stays until the next action starts.
const error = ref('')
// Error when fetching the list: disappears on the next successful fetch.
const listError = ref('')
// World ID -> true while an action is running for this world.
const busy = reactive({})
const pendingDelete = ref(null)
// Own worlds, if the manager invited themselves (same data as in the player view).
const myWorlds = ref([])
// Response of GET /api/playtime (children, holidays, time zone) or null.
const playtime = ref(null)
const playtimeLoading = ref(true)
const playtimeError = ref('')
let playtimeLoadedAt = 0
// GET /api/pause and GET /api/talk; in the playtime cycle (at most every 30 s). Errors stay silent:
// the card then shows only the entry, the Talk rows stay empty.
const pause = ref(null)
const talk = ref(null)

const pauseText = computed(() => (pause.value?.art === 'schluss'
	? t('parent.view.pauseEndOfDay')
	: pauseUntilText(pause.value?.until_clock)))

const backupSource = computed(() => (backupsWorldId.value === null
	? null
	: worlds.value.find((world) => world.id === backupsWorldId.value) ?? null))

// Only the required fields; if the world disappears from the list, the section closes.
const backupWorld = computed(() => {
	const world = backupSource.value
	if (!world) {
		return null
	}
	return {
		id: world.id,
		name: world.name,
		players: world.players ?? [],
		delete_only: Boolean(world.delete_only),
		status: world.status,
	}
})

const backupJob = computed(() => backupSource.value?.backup_job ?? null)

const selectedDescription = computed(() => presets.value.find((preset) => preset.id === selectedPreset.value)?.description ?? '')

const canCreate = computed(() => setupOk.value
	&& !creating.value
	&& selectedPreset.value !== ''
	&& name.value.trim() !== '')

// With Talk the room of the world including its history is lost as well (D-19).
const deleteMessage = computed(() => {
	if (!pendingDelete.value) {
		return ''
	}
	const base = t('parent.view.deleteMessage', { name: pendingDelete.value.name })
	return talk.value?.available
		? `${base} ${t('parent.view.deleteTalk')}`
		: base
})

// Computed so the labels are resolved at render time, not at module evaluation.
const deleteButtons = computed(() => [
	{ label: t('parent.common.cancel'), variant: 'tertiary' },
	{
		label: t('parent.view.deleteConfirm'),
		variant: 'error',
		callback: () => {
			const world = pendingDelete.value
			pendingDelete.value = null
			if (world) {
				run(world, deleteWorld)
			}
		},
	},
])

function onDialogOpen(open) {
	if (!open) {
		pendingDelete.value = null
	}
}

// Only id and name go to the dialogs; the list may change while polling.
function openInvite(world) {
	playersWorld.value = null
	windowWorld.value = null
	backupsWorldId.value = null
	inviteWorld.value = { id: world.id, name: world.name }
}

function openPlayers(world) {
	inviteWorld.value = null
	windowWorld.value = null
	backupsWorldId.value = null
	playersWorld.value = { id: world.id, name: world.name }
}

function openWindow(world) {
	inviteWorld.value = null
	playersWorld.value = null
	backupsWorldId.value = null
	windowWorld.value = { id: world.id, name: world.name, time_window: world.time_window ?? null }
}

function openBackups(world) {
	inviteWorld.value = null
	playersWorld.value = null
	windowWorld.value = null
	backupsWorldId.value = world.id
}

// The time zone changes which day it is today: reload playtime and world list.
function onTimeZoneChanged() {
	loadPlaytime()
	refresh()
}

function switchToInvite() {
	const world = playersWorld.value
	if (world) {
		openInvite(world)
	}
}

// Player names come filtered from the API ([A-Za-z0-9_-]), output only by text interpolation.
function invitedText(world) {
	const invited = world.invited_players ?? []
	return invited.length === 0 ? t('parent.view.nobodyInvited') : invited.join(', ')
}

function chipVariant(status) {
	return CHIP_VARIANT[status] ?? 'warning'
}

// Names come filtered from the API ([A-Za-z0-9_-]) and are output only by text interpolation.
function playersText(world) {
	const players = world.players ?? []
	if (players.length === 0) {
		return t('parent.view.nobodyOnline')
	}
	return t('parent.view.onlineNow', { names: players.join(', ') })
}

function memoryPercent(world) {
	const percent = Math.round((world.memory_used_bytes / world.memory_limit_bytes) * 100)
	return Math.min(100, Math.max(0, percent))
}

function memoryText(world) {
	return t('parent.view.memory', { used: formatBytes(world.memory_used_bytes), limit: formatBytes(world.memory_limit_bytes) })
}

// A backup or restore is running (status or job from the API, D-10).
function backupBusy(world) {
	return BACKUP_BUSY_STATUS.has(world.status) || world.backup_job?.state === 'running'
}

// During a job the world counts as active: no start button, stop and restart locked.
function isActive(world) {
	return world.status === 'running' || world.status === 'starting' || BACKUP_BUSY_STATUS.has(world.status)
}

// Without Docker nothing can be started or stopped; deleting remains (own dialog).
function actionsLocked(world) {
	return Boolean(busy[world.id]) || world.status === 'unknown' || backupBusy(world)
}

// Fetches can overtake each other (polling, action, setup check); only the response
// of the most recently started fetch may set the list.
let refreshSeq = 0

async function refresh() {
	const seq = ++refreshSeq
	try {
		const result = await listWorlds()
		// After the manager list (whose sync comes first): own worlds, errors here only silent.
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

// Only the response of the most recently started fetch counts (as with the world list).
let playtimeSeq = 0

async function loadPlaytime() {
	const seq = ++playtimeSeq
	playtimeLoadedAt = Date.now()
	try {
		const result = await getPlaytime()
		if (seq === playtimeSeq) {
			playtime.value = result
			playtimeError.value = ''
		}
	} catch (err) {
		if (seq === playtimeSeq) {
			playtimeError.value = t('parent.view.playtimeLoadError', { detail: errorText(err) })
		}
	} finally {
		if (seq === playtimeSeq) {
			playtimeLoading.value = false
		}
	}
}

// Only the response of the most recently started fetch counts.
let pauseSeq = 0
let talkSeq = 0

async function loadPause() {
	const seq = ++pauseSeq
	try {
		const result = await getPause()
		if (seq === pauseSeq) {
			pause.value = result
		}
	} catch {
		// Silent: the button to the pause page stays, an error is shown there.
	}
}

async function loadTalk() {
	const seq = ++talkSeq
	try {
		const result = await getTalkStatus()
		if (seq === talkSeq) {
			talk.value = result
		}
	} catch {
		// Silent: Gameworld keeps working without the Talk state (D-20).
	}
}

// Entry of a world from GET /api/talk plus available; null while nothing is loaded.
function talkFor(world) {
	if (!talk.value) {
		return null
	}
	const entry = (talk.value.worlds ?? []).find((item) => item.world_id === world.id)
	return { has_room: false, read_only: false, owner_not_admin: false, token: null, owner_display: null, ...entry, available: talk.value.available }
}

// In the cycle of the world list, but at most every 30 s (playtime, pause, Talk together).
function maybeLoadPlaytime() {
	if (Date.now() - playtimeLoadedAt >= PLAYTIME_POLL_MS) {
		loadPlaytime()
		loadPause()
		loadTalk()
	}
}

// Every 5 s, only with a visible tab; immediately after every action (run, submit).
let timer = null
// After teardown a still running fetch must not set a new timer.
let unmounted = false

function schedule() {
	clearTimeout(timer)
	timer = null
	if (!unmounted && document.visibilityState === 'visible') {
		timer = setTimeout(async () => {
			await refresh()
			maybeLoadPlaytime()
			schedule()
		}, POLL_MS)
	}
}

function onTabChange() {
	if (document.visibilityState === 'visible') {
		refresh()
		maybeLoadPlaytime()
	}
	schedule()
}

async function loadPresets() {
	try {
		presets.value = await listPresets()
		selectedPreset.value = presets.value[0]?.id ?? ''
		presetsError.value = ''
	} catch (err) {
		presetsError.value = t('parent.view.presetsLoadError', { detail: errorText(err) })
	}
}

// The event checked updates the world list after every check run (also "Erneut prüfen").
function onSetupOk(ok) {
	setupOk.value = ok
}

// Runs an action for a world and then reloads the list, because
// the status always comes from Docker.
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
	await Promise.all([loadPresets(), refresh(), loadPlaytime(), loadPause(), loadTalk()])
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
	max-width: 1120px;
	padding: 24px;
}

.gameworld__hint {
	margin-bottom: 16px;
	color: var(--color-text-maxcontrast);
}

.gameworld__pause {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
	justify-content: space-between;
	margin-bottom: 16px;
	padding: 12px 16px;
	border: 1px solid var(--color-border);
	border-radius: var(--border-radius-large);
}

.gameworld__pause--active {
	border-color: var(--color-warning);
}

.gameworld__pause h3 {
	margin: 0;
}

.gameworld__pause-state {
	margin: 4px 0 0;
	font-weight: bold;
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

/* Room for the language selection: below about 210 px its label and value are cut off. */
.gameworld__name {
	min-width: 210px;
}

.gameworld__mine {
	margin-top: 32px;
}

.gameworld__verwalter-forbidden {
	margin-top: 32px;
}

/* The table cells inherit nowrap; notes and job lines wrap instead of widening the table past the page. */
.gameworld__restart {
	margin-top: 8px;
	white-space: normal;
}

.gameworld__job {
	margin-top: 8px;
	white-space: normal;
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.gameworld__window {
	margin-top: 4px;
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
