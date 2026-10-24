<!-- Reste früherer Installationen (UI-SPEC B3, D-15/D-17): nur für Nextcloud-Admins eingehängt; gesperrt ist das Entfernen serverseitig (require_nc_admin, nur fremde gameworld-Objekte). -->
<template>
	<section class="orphans">
		<h3>{{ t('admin.orphans.title') }}</h3>
		<p class="orphans__hint">
			{{ introText() }}
		</p>
		<p class="orphans__hint">
			{{ lifecycleText() }}
		</p>

		<NcLoadingIcon v-if="loading && entries === null" :size="20" />
		<template v-else-if="entries !== null">
			<ul
				v-if="entries.length > 0"
				ref="listEl"
				class="orphans__list"
				tabindex="-1"
				:aria-label="t('admin.orphans.title')">
				<li v-for="entry in entries" :key="entry.key" class="orphans__entry">
					<div class="orphans__entry-text">
						<div class="orphans__entry-head">
							<NcChip
								v-if="entry.kind === 'container'"
								variant="tertiary"
								:text="t('admin.orphans.chipContainer')"
								no-close />
							<NcChip
								v-else
								variant="secondary"
								:text="t('admin.orphans.chipVolume')"
								no-close />
							<span class="orphans__name">{{ entry.name }}</span>
						</div>
						<span v-if="entry.meta" class="orphans__meta">{{ entry.meta }}</span>
					</div>
					<NcButton
						v-if="entry.kind === 'container'"
						class="orphans__remove"
						variant="error"
						:aria-label="t('admin.orphans.removeContainerLabel', { name: entry.name })"
						:disabled="busy || loading"
						@click="ask(entry)">
						{{ t('admin.orphans.remove') }}
					</NcButton>
					<NcButton
						v-else
						class="orphans__remove"
						variant="error"
						:aria-label="t('admin.orphans.deleteVolumeLabel', { name: entry.name })"
						:disabled="busy || loading"
						@click="ask(entry)">
						{{ t('admin.orphans.delete') }}
					</NcButton>
				</li>
			</ul>
			<p
				v-else
				ref="emptyEl"
				class="orphans__hint"
				tabindex="-1">
				{{ emptyText() }}
			</p>
		</template>

		<div class="orphans__notice" aria-live="polite">
			<NcNoteCard v-if="notice" type="success">
				{{ notice }}
			</NcNoteCard>
		</div>
		<NcNoteCard v-if="warning" type="warning">
			{{ warning }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<NcButton
			class="orphans__rescan"
			variant="secondary"
			:aria-label="t('admin.orphans.rescanLabel')"
			:disabled="busy || loading"
			@click="rescan">
			<template v-if="loading" #icon>
				<NcLoadingIcon :size="20" />
			</template>
			{{ t('admin.orphans.rescan') }}
		</NcButton>

		<p class="orphans__hint">
			<template v-for="(part, index) in scriptSegments()" :key="index">
				<code v-if="part.code">{{ part.text }}</code>
				<template v-else>
					{{ part.text }}
				</template>
			</template>
		</p>
		<p class="orphans__hint">
			<a
				class="orphans__link"
				:href="CLEANUP_DOCS_URL"
				target="_blank"
				rel="noopener noreferrer">
				{{ t('admin.orphans.docsLink') }}
			</a>
		</p>

		<NcDialog
			v-if="pending"
			:open="true"
			:name="pending.kind === 'container' ? t('admin.orphans.removeContainer') : t('admin.orphans.deleteVolumeTitle')"
			:message="pendingMessage"
			:buttons="pendingButtons"
			@update:open="onDialogOpen" />
	</section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { errorText, listOrphans, removeOrphanContainer, removeOrphanVolume } from '../api.js'
import {
	CLEANUP_DOCS_URL,
	containerMeta,
	containerQuestion,
	emptyText,
	introText,
	inUseText,
	lifecycleText,
	removedText,
	scriptSegments,
	unavailableText,
	volumeMeta,
	volumeQuestion,
} from '../orphans.js'
import { ncAdminOnlyText } from '../roles.js'
import { t } from '../i18n/index.js'

// 403: Rechte inzwischen entzogen; der Elternteil lädt /api/me neu und blendet aus.
const emit = defineEmits(['forbidden'])

// Backend text on 409 for world data still in use (06-08, api/admin.py MSG_ORPHAN_IN_USE), in
// every account language the server translates it to (06-18 catalogs).
const IN_USE_MARKS = ['noch von einem Container benutzt', 'still used by a container', 'encore utilisées par un conteneur']

const loading = ref(true)
const busy = ref(false)
// Letzter Serverstand als flache Liste; null, solange nichts geladen ist.
const entries = ref(null)
const notice = ref('')
const warning = ref('')
const error = ref('')
const pending = ref(null)
const listEl = ref(null)
const emptyEl = ref(null)

function toEntries(data) {
	const containers = Array.isArray(data?.containers) ? data.containers : []
	const volumes = Array.isArray(data?.volumes) ? data.volumes : []
	return [
		...containers.map((item) => ({
			kind: 'container',
			key: `container-${item.id}`,
			ref: item.id,
			name: item.name || item.id,
			meta: containerMeta(item),
		})),
		...volumes.map((item) => ({
			kind: 'volume',
			key: `volume-${item.name}`,
			ref: item.name,
			name: item.name,
			meta: volumeMeta(item),
		})),
	]
}

// Fokuspunkt B3 (UI-SPEC-Nachtrag): die Restliste, im Leerzustand der Leer-Absatz.
async function focusList() {
	await nextTick()
	const target = listEl.value ?? emptyEl.value
	target?.focus()
}

function failed(err, entry) {
	const status = err?.response?.status
	const detail = errorText(err)
	if (status === 403) {
		error.value = ncAdminOnlyText()
		emit('forbidden')
	} else if (status === 503) {
		warning.value = unavailableText(detail)
	} else if (status === 409 && entry?.kind === 'volume' && IN_USE_MARKS.some((mark) => detail.includes(mark))) {
		error.value = inUseText(entry.name)
	} else {
		error.value = detail
	}
}

// Nur die Antwort des zuletzt gestarteten Abrufs zählt.
let seq = 0

async function load() {
	const mine = ++seq
	loading.value = true
	warning.value = ''
	error.value = ''
	try {
		const data = await listOrphans()
		if (mine === seq) {
			entries.value = toEntries(data)
		}
	} catch (err) {
		if (mine === seq) {
			failed(err, null)
		}
	} finally {
		if (mine === seq) {
			loading.value = false
		}
	}
}

async function rescan() {
	if (busy.value || loading.value) {
		return
	}
	notice.value = ''
	await load()
	await focusList()
}

function ask(entry) {
	if (busy.value || loading.value) {
		return
	}
	pending.value = entry
}

const pendingMessage = computed(() => {
	const entry = pending.value
	if (!entry) {
		return ''
	}
	return entry.kind === 'container' ? containerQuestion(entry.name) : volumeQuestion(entry.name)
})

const pendingButtons = computed(() => [
	{ label: t('admin.common.cancel'), variant: 'tertiary' },
	{
		label: pending.value?.kind === 'container' ? t('admin.orphans.removeContainer') : t('admin.orphans.deleteVolume'),
		variant: 'error',
		callback: () => {
			const entry = pending.value
			pending.value = null
			if (entry) {
				remove(entry)
			}
		},
	},
])

function onDialogOpen(open) {
	if (!open) {
		pending.value = null
	}
}

async function remove(entry) {
	if (busy.value) {
		return
	}
	busy.value = true
	notice.value = ''
	warning.value = ''
	error.value = ''
	// Ein laufender Abruf darf die Serverantwort des Entfernens nicht überschreiben.
	const mine = ++seq
	try {
		const data = entry.kind === 'container'
			? await removeOrphanContainer(entry.ref)
			: await removeOrphanVolume(entry.ref)
		if (mine === seq) {
			entries.value = toEntries(data)
		}
		notice.value = removedText(entry.kind, entry.name)
	} catch (err) {
		failed(err, entry)
	} finally {
		busy.value = false
		loading.value = false
	}
	await focusList()
}

onMounted(load)
</script>

<style scoped>
.orphans {
	margin-top: 32px;
}

.orphans__hint {
	margin: 4px 0;
	color: var(--color-text-maxcontrast);
}

.orphans__list {
	display: flex;
	flex-direction: column;
	gap: 8px;
	margin: 8px 0 0;
	padding: 0;
	list-style: none;
}

.orphans__list:focus,
.orphans__hint:focus {
	outline: 2px solid var(--color-primary-element);
	outline-offset: 2px;
}

.orphans__entry {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
	justify-content: space-between;
	padding: 8px 0;
	border-bottom: 1px solid var(--color-border);
}

.orphans__entry-text {
	display: flex;
	flex-direction: column;
	gap: 4px;
	min-width: 0;
}

.orphans__entry-head {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
	min-width: 0;
}

.orphans__name {
	font-weight: bold;
	overflow-wrap: anywhere;
	min-width: 0;
}

.orphans__meta {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
	overflow-wrap: anywhere;
}

.orphans__remove {
	margin-inline-start: auto;
}

.orphans__rescan {
	margin-top: 16px;
}

.orphans__notice {
	margin-top: 8px;
}

.orphans__link {
	color: var(--color-primary-element);
	text-decoration: underline;
}

@media (max-width: 480px) {
	.orphans__entry-text {
		flex: 1 1 100%;
	}
}
</style>
