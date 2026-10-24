<!-- Spieler einladen: Suche über Nextclouds Autovervollständigung (Benutzer und Gruppen), keine eigene Benutzerliste. -->
<template>
	<NcDialog
		:open="true"
		:name="`Spieler einladen: ${world.name}`"
		size="normal"
		@update:open="onOpen">
		<p class="invite__hint">
			Suche nach Nextcloud-Konten oder ganzen Gruppen. Eingeladene bekommen einen Spielernamen und ein Passwort für diese Welt.
		</p>
		<template v-if="me?.nc_admin === false">
			<p v-if="scope" class="invite__scope">
				{{ scope }}
			</p>
			<NcNoteCard v-else type="info">
				{{ NO_SCOPE_TEXT }}
			</NcNoteCard>
		</template>
		<NcSelectUsers
			v-model="selected"
			:options="options"
			:loading="searching"
			:disabled="inviting"
			input-label="Konto oder Gruppe"
			placeholder="Name eingeben"
			multiple
			keep-open
			@search="onSearch" />

		<NcNoteCard v-if="invitedLabels.length > 0" type="success">
			Eingeladen: {{ invitedLabels.join(', ') }}
		</NcNoteCard>
		<NcNoteCard v-if="notApplied" type="info">
			Die Änderung wirkt beim nächsten Start der Welt.
		</NcNoteCard>
		<NcNoteCard v-if="searchError" type="warning">
			{{ searchError }}
		</NcNoteCard>
		<NcNoteCard
			v-for="failure in failures"
			:key="failure.key"
			type="error">
			{{ failure.label }}: {{ failure.detail }}
		</NcNoteCard>

		<template #actions>
			<NcButton variant="tertiary" :disabled="inviting" @click="close">
				Schließen
			</NcButton>
			<NcButton
				variant="primary"
				:disabled="inviting || selected.length === 0"
				@click="submit">
				<template v-if="inviting" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				Einladen
			</NcButton>
		</template>
	</NcDialog>
</template>

<script setup>
import { computed, onUnmounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcSelectUsers from '@nextcloud/vue/components/NcSelectUsers'
import { errorText, invite, searchAccounts } from '../api.js'
import { NO_SCOPE_TEXT, scopeHint } from '../roles.js'

const props = defineProps({
	// { id, name } der Welt; nur id geht an die API.
	world: { type: Object, required: true },
	// Antwort von /api/me; nur Gruppen-Verwalter (nc_admin false) sehen die Einladungsgrenze (D-01).
	me: { type: Object, required: false, default: null },
})
const emit = defineEmits(['done', 'close'])

const SEARCH_DELAY_MS = 300
// Symbol für Gruppen (Material Design Icons, account-group), fest im Code, nie aus Daten.
const GROUP_ICON = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12,5.5A3.5,3.5 0 0,1 15.5,9A3.5,3.5 0 0,1 12,12.5A3.5,3.5 0 0,1 8.5,9A3.5,3.5 0 0,1 12,5.5M5,8C5.56,8 6.08,8.15 6.53,8.42C6.38,9.85 6.8,11.27 7.66,12.38C7.16,13.34 6.16,14 5,14A3,3 0 0,1 2,11A3,3 0 0,1 5,8M19,8A3,3 0 0,1 22,11A3,3 0 0,1 19,14C17.84,14 16.84,13.34 16.34,12.38C17.2,11.27 17.62,9.85 17.47,8.42C17.92,8.15 18.44,8 19,8M5.5,18.25C5.5,16.18 8.41,14.5 12,14.5C15.59,14.5 18.5,16.18 18.5,18.25V20H5.5V18.25M0,20V18.5C0,17.11 1.89,15.94 4.45,15.6C3.86,16.28 3.5,17.22 3.5,18.25V20H0M24,20H20.5V18.25C20.5,17.22 20.14,16.28 19.55,15.6C22.11,15.94 24,17.11 24,18.5V20Z" /></svg>'

// Gruppen aus /api/me (eigene plus Subadmin-Gruppen), alphabetisch; null heißt: keine.
const scope = computed(() => scopeHint(props.me?.invite_groups ?? []))

const selected = ref([])
const options = ref([])
const searching = ref(false)
const searchError = ref('')
const inviting = ref(false)
const invitedLabels = ref([])
const notApplied = ref(false)
const failures = ref([])

// Modell für NcSelectUsers; kind und target gehen später an die Einladungs-API.
function toOption(entry) {
	const isGroup = entry.kind === 'group'
	return {
		id: `${entry.kind}:${entry.id}`,
		// Ohne sichtbaren Anzeigenamen steht die Konto-ID da (kein Fehlertext).
		displayName: entry.label || entry.id,
		subname: isGroup ? 'Gruppe' : entry.id,
		user: isGroup ? undefined : entry.id,
		isNoUser: isGroup,
		iconSvg: isGroup ? GROUP_ICON : undefined,
		iconName: isGroup ? 'Gruppe' : undefined,
		kind: entry.kind,
		target: entry.id,
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
			const found = await searchAccounts(query)
			if (seq === searchSeq) {
				options.value = found.map(toOption)
				searchError.value = ''
			}
		} catch {
			if (seq === searchSeq) {
				searchError.value = 'Die Suche in Nextcloud ist gerade nicht möglich.'
			}
		} finally {
			if (seq === searchSeq) {
				searching.value = false
			}
		}
	}, SEARCH_DELAY_MS)
}

// Nacheinander, damit jede Einladung ihre eigene Fehlermeldung bekommt.
async function submit() {
	if (inviting.value || selected.value.length === 0) {
		return
	}
	inviting.value = true
	failures.value = []
	invitedLabels.value = []
	notApplied.value = false
	const remaining = []
	for (const option of selected.value) {
		try {
			const result = await invite(props.world.id, option.kind, option.target)
			invitedLabels.value.push(option.displayName)
			if (result?.applied === false) {
				notApplied.value = true
			}
		} catch (err) {
			failures.value.push({ key: option.id, label: option.displayName, detail: errorText(err) })
			remaining.push(option)
		}
	}
	selected.value = remaining
	inviting.value = false
	if (invitedLabels.value.length > 0) {
		emit('done')
	}
}

function close() {
	if (!inviting.value) {
		emit('close')
	}
}

function onOpen(open) {
	if (!open) {
		close()
	}
}

onUnmounted(() => {
	clearTimeout(timer)
})
</script>

<style scoped>
.invite__hint {
	margin-bottom: 12px;
	color: var(--color-text-maxcontrast);
}

.invite__scope {
	margin-bottom: 12px;
	color: var(--color-text-maxcontrast);
}
</style>
