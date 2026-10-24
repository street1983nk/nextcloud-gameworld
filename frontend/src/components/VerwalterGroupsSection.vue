<!-- Verwalter-Gruppen (UI-SPEC B1, ROLLE-03): nur für Nextcloud-Admins eingehängt; gesperrt ist die Änderung serverseitig (require_nc_admin). -->
<template>
	<section class="verwalter-groups">
		<h3>Verwalter-Gruppen</h3>
		<p class="verwalter-groups__hint">
			{{ SECTION_HINT }}
		</p>
		<NcNoteCard type="warning">
			{{ CHILDREN_WARNING }}
		</NcNoteCard>

		<NcNoteCard v-if="loadError" type="warning">
			{{ loadError }}
		</NcNoteCard>

		<NcLoadingIcon v-if="loading" :size="20" />
		<template v-else-if="groups !== null">
			<ul class="verwalter-groups__list">
				<li class="verwalter-groups__entry">
					<div class="verwalter-groups__entry-text">
						<span class="verwalter-groups__name">admin</span>
					</div>
					<NcChip variant="tertiary" text="immer dabei" no-close />
				</li>
				<li v-for="gid in groups" :key="gid" class="verwalter-groups__entry">
					<div class="verwalter-groups__entry-text">
						<span class="verwalter-groups__name">{{ gid }}</span>
						<span v-if="displayNameOf(gid)" class="verwalter-groups__meta">{{ displayNameOf(gid) }}</span>
					</div>
					<NcButton
						class="verwalter-groups__remove"
						variant="error"
						:aria-label="`Gruppe ${gid} entfernen`"
						:disabled="saving"
						@click="remove(gid)">
						Entfernen
					</NcButton>
				</li>
			</ul>
			<p v-if="groups.length === 0" class="verwalter-groups__hint">
				{{ ONLY_ADMIN_TEXT }}
			</p>

			<div class="verwalter-groups__add">
				<NcSelect
					v-model="selected"
					class="verwalter-groups__select"
					:options="options"
					:loading="searching"
					:disabled="saving"
					:filterable="false"
					label="label"
					input-label="Gruppe"
					placeholder="Gruppenname eingeben"
					@search="onSearch" />
				<NcButton
					ref="addButton"
					class="verwalter-groups__add-button"
					variant="primary"
					:disabled="saving || !selected"
					@click="add">
					<template v-if="saving" #icon>
						<NcLoadingIcon :size="20" />
					</template>
					Gruppe hinzufügen
				</NcButton>
			</div>
		</template>

		<p class="verwalter-groups__hint">
			{{ BOUNDARY_TEXT }}
		</p>

		<div class="verwalter-groups__notice" aria-live="polite">
			<NcNoteCard v-if="notice" type="success">
				{{ notice }}
			</NcNoteCard>
		</div>
		<NcNoteCard v-if="searchError" type="warning">
			{{ searchError }}
		</NcNoteCard>
		<div v-if="error" ref="errorCard" tabindex="-1" class="verwalter-groups__error">
			<NcNoteCard type="error">
				{{ error }}
			</NcNoteCard>
		</div>
	</section>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcSelect from '@nextcloud/vue/components/NcSelect'
import {
	addVerwalterGroup,
	errorText,
	getVerwalterGroups,
	removeVerwalterGroup,
	searchGroups,
} from '../api.js'
import {
	BOUNDARY_TEXT,
	CHILDREN_WARNING,
	NC_ADMIN_ONLY_TEXT,
	ONLY_ADMIN_TEXT,
	SEARCH_DOWN_TEXT,
	SECTION_HINT,
	groupAddedText,
	groupRemovedText,
	groupUnknownText,
	loadErrorText,
} from '../roles.js'

// 403: Rechte inzwischen entzogen; der Elternteil lädt /api/me neu und blendet aus.
const emit = defineEmits(['forbidden'])

const ADMIN_GROUP = 'admin'
const SEARCH_DELAY_MS = 300
// Backend-Text bei 422 für eine unbekannte Gruppe (api/admin.py MSG_UNKNOWN_GROUP).
const UNKNOWN_MARK = 'gibt es in Nextcloud nicht'

const loading = ref(true)
const loadError = ref('')
// Letzter Serverstand ohne admin; null, solange nichts geladen ist.
const groups = ref(null)
const saving = ref(false)
const notice = ref('')
const error = ref('')
const searchError = ref('')
const searching = ref(false)
const found = ref([])
const selected = ref(null)
// Anzeigenamen aus der Gruppensuche (die Liste selbst liefert nur IDs).
const names = ref({})
const addButton = ref(null)
const errorCard = ref(null)

// admin und bereits gewählte Gruppen erscheinen nicht als Option.
const options = computed(() => {
	const taken = new Set(groups.value ?? [])
	return found.value
		.filter((hit) => hit.id !== ADMIN_GROUP && !taken.has(hit.id))
		.map((hit) => ({
			id: hit.id,
			displayName: hit.display_name,
			label: hit.display_name && hit.display_name !== hit.id ? `${hit.display_name} (${hit.id})` : hit.id,
		}))
})

function displayNameOf(gid) {
	const name = names.value[gid]
	return typeof name === 'string' && name !== '' && name !== gid ? name : ''
}

async function load() {
	loading.value = true
	loadError.value = ''
	try {
		groups.value = await getVerwalterGroups()
	} catch (err) {
		if (err?.response?.status === 403) {
			error.value = NC_ADMIN_ONLY_TEXT
			emit('forbidden')
		} else {
			loadError.value = loadErrorText(errorText(err))
		}
	} finally {
		loading.value = false
	}
}

let timer = null
// Nur die Antwort der zuletzt gestarteten Suche zählt.
let searchSeq = 0

function onSearch(term) {
	clearTimeout(timer)
	const query = (term ?? '').trim()
	if (query === '') {
		searching.value = false
		return
	}
	searching.value = true
	timer = setTimeout(async () => {
		const seq = ++searchSeq
		try {
			const hits = await searchGroups(query)
			if (seq === searchSeq) {
				found.value = Array.isArray(hits) ? hits : []
				for (const hit of found.value) {
					names.value[hit.id] = hit.display_name
				}
				searchError.value = ''
			}
		} catch {
			if (seq === searchSeq) {
				searchError.value = SEARCH_DOWN_TEXT
			}
		} finally {
			if (seq === searchSeq) {
				searching.value = false
			}
		}
	}, SEARCH_DELAY_MS)
}

// Fokus nach der Aktion (UI-SPEC-Nachtrag): auf die Fehlermeldung, sonst auf "Gruppe hinzufügen".
async function focusAfterAction() {
	await nextTick()
	if (error.value && errorCard.value) {
		errorCard.value.focus()
		return
	}
	addButton.value?.$el?.focus()
}

function failed(err, gid) {
	const status = err?.response?.status
	const detail = errorText(err)
	if (status === 403) {
		error.value = NC_ADMIN_ONLY_TEXT
		emit('forbidden')
	} else if (status === 422 && detail.includes(UNKNOWN_MARK)) {
		error.value = groupUnknownText(gid)
	} else {
		error.value = detail
	}
}

async function add() {
	const option = selected.value
	if (saving.value || !option) {
		return
	}
	const gid = option.id
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		groups.value = await addVerwalterGroup(gid)
		if (option.displayName) {
			names.value[gid] = option.displayName
		}
		selected.value = null
		notice.value = groupAddedText(gid)
	} catch (err) {
		failed(err, gid)
	} finally {
		saving.value = false
	}
	await focusAfterAction()
}

async function remove(gid) {
	if (saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		groups.value = await removeVerwalterGroup(gid)
		notice.value = groupRemovedText(gid)
	} catch (err) {
		failed(err, gid)
	} finally {
		saving.value = false
	}
	await focusAfterAction()
}

onMounted(load)

onUnmounted(() => {
	clearTimeout(timer)
})
</script>

<style scoped>
.verwalter-groups {
	margin-top: 32px;
}

.verwalter-groups__hint {
	margin: 4px 0;
	color: var(--color-text-maxcontrast);
}

.verwalter-groups__list {
	display: flex;
	flex-direction: column;
	gap: 8px;
	margin: 8px 0 0;
	padding: 0;
	list-style: none;
}

.verwalter-groups__entry {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
	justify-content: space-between;
	padding: 8px 0;
	border-bottom: 1px solid var(--color-border);
}

.verwalter-groups__entry-text {
	display: flex;
	flex-direction: column;
	gap: 2px;
	min-width: 0;
}

.verwalter-groups__name {
	font-weight: bold;
	overflow-wrap: anywhere;
}

.verwalter-groups__meta {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
	overflow-wrap: anywhere;
}

.verwalter-groups__remove {
	margin-inline-start: auto;
}

.verwalter-groups__add {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: flex-end;
	margin-top: 16px;
}

.verwalter-groups__error:focus {
	outline: 2px solid var(--color-primary-element);
	outline-offset: 2px;
}

@media (max-width: 480px) {
	.verwalter-groups__select {
		flex: 1 1 100%;
	}

	.verwalter-groups__add-button {
		width: 100%;
	}
}
</style>
