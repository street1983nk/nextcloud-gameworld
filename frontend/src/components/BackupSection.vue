<!-- Backups of a world (BACKUP-01/02): list, total size, back up now and restore. Gameworld never removes a backup (D-08). -->
<template>
	<NcDialog
		v-if="!confirm"
		:open="true"
		:name="t('parent.backup.title', { name: world.name })"
		size="large"
		@update:open="onOpen">
		<div class="backup-section">
			<p class="backup-section__hint">
				{{ t('parent.backup.hint') }}
			</p>
			<p v-if="note" class="backup-section__job" aria-live="polite">
				{{ note }}
			</p>
			<NcNoteCard v-if="error" type="error">
				{{ error }}
			</NcNoteCard>
			<NcNoteCard v-if="listError" type="warning">
				{{ listError }}
			</NcNoteCard>

			<NcLoadingIcon v-if="loading" :size="32" />
			<template v-else-if="listing">
				<p v-if="listing.backups.length === 0" class="backup-section__empty">
					{{ t('parent.backup.empty') }}
				</p>
				<ul v-else class="backup-section__list">
					<li v-for="entry in listing.backups" :key="entry.file_id" class="backup-section__entry">
						<div class="backup-section__entry-text">
							<span class="backup-section__name">{{ entry.name }}</span>
							<span class="backup-section__meta">
								{{ formatDate(entry.created_at) }}, {{ formatBytes(entry.size) }}
							</span>
							<NcChip
								v-if="entry.kind === 'vor-restore'"
								class="backup-section__kind"
								:text="t('parent.backup.beforeRestore')"
								variant="secondary"
								no-close />
						</div>
						<NcButton :disabled="locked" @click="askRestore(entry)">
							{{ t('parent.backup.restore') }}
						</NcButton>
					</li>
				</ul>
				<p class="backup-section__total">
					{{ t('parent.backup.totalSize', { size: formatBytes(listing.total_size) }) }}
				</p>
				<p v-if="listing.other_files > 0" class="backup-section__hint">
					{{ t('parent.backup.otherFiles', { count: listing.other_files }) }}
				</p>
			</template>
		</div>

		<template #actions>
			<NcButton variant="tertiary" :disabled="saving" @click="close">
				{{ t('parent.common.close') }}
			</NcButton>
			<NcButton
				v-if="!world.delete_only"
				variant="primary"
				:disabled="locked"
				@click="askBackup">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('parent.backup.backupNow') }}
			</NcButton>
		</template>
	</NcDialog>

	<!-- Confirmation (D-04/D-09): replaces the section while it is open. -->
	<NcDialog
		v-else
		:open="true"
		:name="confirm.kind === 'restore' ? t('parent.backup.restoreTitle') : t('parent.backup.backupTitle')"
		@update:open="onConfirmOpen">
		<div class="backup-section">
			<p v-if="confirm.kind === 'restore'">
				{{ restoreQuestion(confirm.entry.name) }}
			</p>
			<p v-if="playerCount > 0" class="backup-section__warning">
				{{ playersWarning(playerCount) }}
			</p>
			<NcNoteCard v-if="error" type="error">
				{{ error }}
			</NcNoteCard>
		</div>

		<template #actions>
			<NcButton variant="tertiary" :disabled="saving" @click="cancelConfirm">
				{{ t('parent.common.cancel') }}
			</NcButton>
			<NcButton variant="primary" :disabled="locked" @click="runConfirmed">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ confirm.kind === 'restore' ? t('parent.backup.restore') : t('parent.backup.backupAnyway') }}
			</NcButton>
		</template>
	</NcDialog>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { errorText, listBackups, restoreBackup, startBackup } from '../api.js'
import { formatBytes, formatDate, jobFinished, jobNote, playersWarning, restoreQuestion } from '../backup.js'
import { t } from '../i18n/index.js'

const props = defineProps({
	// { id, name, players, delete_only, status } of the world, current from the polling.
	world: { type: Object, required: true },
	// world.backup_job from the 5 s polling ({ kind, state, message, file_name, finished_at }) or null.
	backupJob: { type: Object, default: null },
})
const emit = defineEmits(['changed', 'close'])

// Response of GET .../backups ({ backups, total_size, other_files }) or null.
const listing = ref(null)
const loading = ref(true)
const listError = ref('')
const saving = ref(false)
const error = ref('')
// Open confirmation: { kind: 'backup' } or { kind: 'restore', entry } or null.
const confirm = ref(null)

const BUSY_STATUS = new Set(['backing_up', 'restoring'])

const playerCount = computed(() => (props.world.players ?? []).length)
const jobRunning = computed(() => props.backupJob?.state === 'running')
// T-05-38: no second job while one is running (the backend would answer 409).
const locked = computed(() => saving.value || jobRunning.value || BUSY_STATUS.has(props.world.status))
const note = computed(() => jobNote(props.backupJob))

// Only the response of the most recently started request counts.
let loadSeq = 0

async function load() {
	const seq = ++loadSeq
	try {
		const result = await listBackups(props.world.id)
		if (seq === loadSeq) {
			listing.value = result
			listError.value = ''
		}
	} catch (err) {
		if (seq === loadSeq) {
			listError.value = t('parent.backup.loadError', { detail: errorText(err) })
		}
	} finally {
		if (seq === loadSeq) {
			loading.value = false
		}
	}
}

// T-05-52: when a job ends, the new entry appears without closing and reopening.
watch(
	() => ({ state: props.backupJob?.state ?? null, finished_at: props.backupJob?.finished_at ?? null }),
	(next, prev) => {
		if (jobFinished(prev, next)) {
			load()
		}
	},
)

function askBackup() {
	if (locked.value) {
		return
	}
	error.value = ''
	if (playerCount.value > 0) {
		confirm.value = { kind: 'backup' }
		return
	}
	run({ kind: 'backup' }, false)
}

// D-04: every restore goes through the safety prompt.
function askRestore(entry) {
	if (locked.value) {
		return
	}
	error.value = ''
	confirm.value = { kind: 'restore', entry }
}

function runConfirmed() {
	const pending = confirm.value
	if (pending) {
		run(pending, playerCount.value > 0)
	}
}

async function run(pending, confirmDisconnect) {
	if (locked.value) {
		return
	}
	saving.value = true
	error.value = ''
	try {
		if (pending.kind === 'restore') {
			await restoreBackup(props.world.id, pending.entry.file_id, confirmDisconnect)
		} else {
			await startBackup(props.world.id, confirmDisconnect)
		}
		confirm.value = null
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

function cancelConfirm() {
	if (!saving.value) {
		confirm.value = null
		error.value = ''
	}
}

function onConfirmOpen(open) {
	if (!open) {
		cancelConfirm()
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

onMounted(load)
</script>

<style scoped>
.backup-section {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.backup-section__hint,
.backup-section__meta,
.backup-section__empty {
	margin: 0;
	color: var(--color-text-maxcontrast);
}

.backup-section__job,
.backup-section__warning {
	margin: 0;
	font-weight: bold;
}

.backup-section__list {
	display: flex;
	flex-direction: column;
	gap: 8px;
	margin: 0;
	padding: 0;
	list-style: none;
}

.backup-section__entry {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
	justify-content: space-between;
	padding: 8px 0;
	border-bottom: 1px solid var(--color-border);
}

.backup-section__entry-text {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.backup-section__name {
	overflow-wrap: anywhere;
}

.backup-section__meta {
	font-size: 0.9em;
}

.backup-section__total {
	margin: 0;
	font-weight: bold;
}
</style>
