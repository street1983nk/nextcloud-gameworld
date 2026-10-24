<!-- Spieler einladen: Suche über Nextclouds Autovervollständigung (Benutzer und Gruppen), keine eigene Benutzerliste. -->
<template>
	<NcDialog
		v-if="!confirmOpen"
		:open="true"
		:name="t('parent.invite.title', { name: world.name })"
		size="normal"
		@update:open="onOpen">
		<p class="invite__hint">
			{{ t('parent.invite.hint') }}
		</p>
		<template v-if="me?.nc_admin === false">
			<p v-if="scope" class="invite__scope">
				{{ scope }}
			</p>
			<NcNoteCard v-else type="info">
				{{ noScopeText() }}
			</NcNoteCard>
		</template>
		<NcSelectUsers
			v-model="selected"
			:options="options"
			:loading="searching"
			:disabled="inviting"
			:input-label="t('parent.invite.searchLabel')"
			:placeholder="t('parent.invite.searchPlaceholder')"
			multiple
			keep-open
			@search="onSearch" />

		<!-- ROLLE-04 (D-06): nur für einzeln gewählte Konten, Bestätigung erst beim Klick auf Einladen. -->
		<div ref="adultRow" class="invite__adult">
			<NcCheckboxRadioSwitch
				v-model="inviteAdult"
				type="switch"
				:disabled="inviting || singleAccounts.length === 0"
				:description="inviteSwitchMeta()">
				{{ t('parent.invite.asAdult') }}
			</NcCheckboxRadioSwitch>
		</div>

		<NcNoteCard v-if="invitedLabels.length > 0" type="success">
			{{ invitedLabel(invitedLabels) }}
		</NcNoteCard>
		<NcNoteCard
			v-for="warning in adultFailures"
			:key="`adult-${warning.key}`"
			type="warning">
			{{ warning.text }}
		</NcNoteCard>
		<NcNoteCard v-if="notApplied" type="info">
			{{ t('parent.common.notApplied') }}
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
				{{ t('parent.common.close') }}
			</NcButton>
			<NcButton
				variant="primary"
				:disabled="inviting || selected.length === 0"
				@click="submit">
				<template v-if="inviting" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('parent.common.invite') }}
			</NcButton>
		</template>
	</NcDialog>

	<!-- Bestätigung (D-07): ersetzt den Einladen-Dialog, die Auswahl bleibt erhalten. -->
	<NcDialog
		v-else
		:open="true"
		:name="t('parent.common.markAdult')"
		@update:open="onConfirmOpen">
		<div class="invite__confirm">
			<p class="invite__confirm-lead">
				{{ confirmLead(singleAccounts.map((option) => option.displayName)) }}
			</p>
			<p>{{ confirmScope() }}</p>
			<p class="invite__confirm-note">
				{{ confirmWarning() }}
			</p>
		</div>

		<template #actions>
			<NcButton variant="tertiary" :disabled="inviting" @click="cancelConfirm">
				{{ t('parent.common.cancel') }}
			</NcButton>
			<NcButton variant="warning" :disabled="inviting" @click="confirmInvite">
				<template v-if="inviting" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('parent.invite.asAdult') }}
			</NcButton>
		</template>
	</NcDialog>
</template>

<script setup>
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcSelectUsers from '@nextcloud/vue/components/NcSelectUsers'
import { errorText, invite, searchAccounts, setAdult } from '../api.js'
import {
	adultInviteWarning,
	confirmLead,
	confirmScope,
	confirmWarning,
	invitedLabel,
	inviteSwitchMeta,
} from '../adult.js'
import { t } from '../i18n/index.js'
import { noScopeText, scopeHint } from '../roles.js'

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
const inviteAdult = ref(false)
const confirmOpen = ref(false)
const adultFailures = ref([])
const adultRow = ref(null)

// Nur Einzelkonten lassen sich als erwachsen einladen, Gruppen nicht.
const singleAccounts = computed(() => selected.value.filter((option) => option.kind !== 'group'))

watch(() => singleAccounts.value.length, (count) => {
	if (count === 0) {
		inviteAdult.value = false
	}
})

// Modell für NcSelectUsers; kind und target gehen später an die Einladungs-API.
function toOption(entry) {
	const isGroup = entry.kind === 'group'
	return {
		id: `${entry.kind}:${entry.id}`,
		// Ohne sichtbaren Anzeigenamen steht die Konto-ID da (kein Fehlertext).
		displayName: entry.label || entry.id,
		subname: isGroup ? t('parent.invite.group') : entry.id,
		user: isGroup ? undefined : entry.id,
		isNoUser: isGroup,
		iconSvg: isGroup ? GROUP_ICON : undefined,
		iconName: isGroup ? t('parent.invite.group') : undefined,
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
				searchError.value = t('parent.invite.searchDown')
			}
		} finally {
			if (seq === searchSeq) {
				searching.value = false
			}
		}
	}, SEARCH_DELAY_MS)
}

function submit() {
	if (inviting.value || selected.value.length === 0) {
		return
	}
	if (inviteAdult.value && singleAccounts.value.length > 0) {
		// Erst die Bestätigung, dann Einladungen und Markieren.
		confirmOpen.value = true
		return
	}
	runInvites(false)
}

function confirmInvite() {
	runInvites(true)
}

function focusAdultRow() {
	nextTick(() => {
		setTimeout(() => {
			adultRow.value?.querySelector('input')?.focus()
		}, 0)
	})
}

function cancelConfirm() {
	if (inviting.value) {
		return
	}
	confirmOpen.value = false
	focusAdultRow()
}

function onConfirmOpen(open) {
	if (!open) {
		cancelConfirm()
	}
}

// Nacheinander, damit jede Einladung ihre eigene Fehlermeldung bekommt.
async function runInvites(markAdult) {
	if (inviting.value || selected.value.length === 0) {
		return
	}
	inviting.value = true
	failures.value = []
	adultFailures.value = []
	invitedLabels.value = []
	notApplied.value = false
	const remaining = []
	for (const option of selected.value) {
		let label = option.displayName
		try {
			const result = await invite(props.world.id, option.kind, option.target)
			if (result?.applied === false) {
				notApplied.value = true
			}
		} catch (err) {
			failures.value.push({ key: option.id, label: option.displayName, detail: errorText(err) })
			remaining.push(option)
			continue
		}
		if (markAdult && option.kind !== 'group') {
			try {
				const marked = await setAdult(option.target, true)
				label = t('parent.invite.adultLabel', { name: option.displayName })
				if (marked?.applied === false) {
					notApplied.value = true
				}
			} catch (err) {
				// Einladung gelungen, Markieren nicht: eigener Hinweis je Konto (T-06-23).
				adultFailures.value.push({ key: option.id, text: adultInviteWarning(option.displayName, errorText(err)) })
			}
		}
		invitedLabels.value.push(label)
	}
	selected.value = remaining
	inviting.value = false
	confirmOpen.value = false
	if (invitedLabels.value.length > 0) {
		inviteAdult.value = false
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

.invite__adult {
	margin-top: 8px;
	min-width: 0;
}

.invite__adult :deep(.checkbox-content__description) {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.invite__confirm {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.invite__confirm p {
	margin: 0;
}

.invite__confirm-lead {
	font-weight: bold;
}

.invite__confirm-note {
	color: var(--color-text-maxcontrast);
}
</style>
