<!-- Spieler einer Welt: Spielername, Passwort (verdeckt), Herkunft, Erwachsen-Schalter (ROLLE-04), Passwort neu, Umbenennen, Einladungen entfernen. -->
<template>
	<NcDialog
		v-if="!confirmAdult"
		:open="true"
		:name="t('parent.players.title', { name: world.name })"
		size="large"
		@update:open="onOpen">
		<NcLoadingIcon v-if="loading" :size="32" />
		<template v-else>
			<NcNoteCard v-if="loadError" type="error">
				{{ loadError }}
			</NcNoteCard>
			<NcNoteCard v-if="error" type="error">
				{{ error }}
			</NcNoteCard>
			<NcNoteCard v-if="notice" type="success">
				{{ notice }}
			</NcNoteCard>
			<NcNoteCard v-if="notApplied" type="info">
				{{ t('parent.common.notApplied') }}
			</NcNoteCard>
			<NcNoteCard v-if="adultNotApplied" type="info">
				{{ notAppliedMessage() }}
			</NcNoteCard>
			<NcNoteCard v-if="info" type="info">
				{{ info }}
			</NcNoteCard>

			<p v-if="!loadError && players.length === 0" class="players__empty">
				{{ t('parent.players.empty') }}
			</p>

			<ul v-else class="players__list">
				<li
					v-for="player in players"
					:key="player.nc_user"
					class="players__item"
					:data-nc-user="player.nc_user">
					<div class="players__head">
						<strong>{{ player.display_name }}</strong>
						<NcChip
							v-if="player.verwalter"
							variant="tertiary"
							:text="t('parent.players.verwalter')"
							no-close />
						<NcChip
							v-else-if="player.adult"
							variant="secondary"
							:text="t('parent.players.adult')"
							no-close />
						<span class="players__via">{{ viaText(player.via) }}</span>
					</div>

					<!-- Verwalter spielen ohnehin ohne Regeln und bekommen keinen Schalter (D-06). -->
					<div v-if="!player.verwalter" class="players__adult">
						<NcCheckboxRadioSwitch
							type="switch"
							:model-value="Boolean(adultShown[player.nc_user])"
							:disabled="busy || adultSaving === player.nc_user"
							:description="switchMeta()"
							@update:model-value="(on) => toggleAdult(player, on)">
							{{ t('parent.players.adult') }}
						</NcCheckboxRadioSwitch>
					</div>

					<NcFormBox>
						<NcFormBoxCopyButton :label="t('parent.players.playerName')" :value="player.player_name" />
						<NcFormBoxCopyButton
							v-if="revealed[player.nc_user]"
							:label="t('parent.players.password')"
							:value="player.password" />
					</NcFormBox>

					<div class="players__password">
						<span v-if="!revealed[player.nc_user]" class="players__masked" :aria-label="t('parent.players.passwordHidden')">
							{{ t('parent.players.passwordMasked') }}
						</span>
						<NcButton variant="tertiary" @click="toggleReveal(player)">
							{{ revealed[player.nc_user] ? t('parent.players.hide') : t('parent.players.show') }}
						</NcButton>
						<NcButton
							v-if="!revealed[player.nc_user]"
							variant="tertiary"
							@click="copyPassword(player)">
							{{ copied === player.nc_user ? t('parent.players.copied') : t('parent.players.copyPassword') }}
						</NcButton>
					</div>

					<div class="players__actions">
						<NcButton :disabled="busy" @click="askRotate(player)">
							{{ t('parent.players.newPassword') }}
						</NcButton>
						<NcButton :disabled="busy" @click="startRename(player)">
							{{ t('parent.players.rename') }}
						</NcButton>
					</div>

					<NcNoteCard v-if="rotating === player.nc_user" type="warning">
						<p>{{ t('parent.players.rotateWarning') }}</p>
						<div class="players__confirm">
							<NcButton variant="tertiary" :disabled="busy" @click="rotating = ''">
								{{ t('parent.common.cancel') }}
							</NcButton>
							<NcButton variant="warning" :disabled="busy" @click="confirmRotate(player)">
								{{ t('parent.players.rotateConfirm') }}
							</NcButton>
						</div>
					</NcNoteCard>

					<div v-if="renaming === player.nc_user" class="players__rename">
						<NcNoteCard type="warning">
							{{ t('parent.players.renameWarning') }}
						</NcNoteCard>
						<NcTextField
							v-model="newName"
							:label="t('parent.players.newPlayerName')"
							:maxlength="20"
							:disabled="busy" />
						<div class="players__confirm">
							<NcButton variant="tertiary" :disabled="busy" @click="renaming = ''">
								{{ t('parent.common.cancel') }}
							</NcButton>
							<NcButton
								variant="primary"
								:disabled="busy || newName.trim() === ''"
								@click="confirmRename(player)">
								{{ t('parent.players.saveName') }}
							</NcButton>
						</div>
					</div>
				</li>
			</ul>

			<h3 class="players__title">
				{{ t('parent.players.invitesTitle') }}
			</h3>
			<p v-if="invites.length === 0" class="players__empty">
				{{ t('parent.players.noInvites') }}
			</p>
			<ul v-else class="players__invites">
				<li v-for="entry in invites" :key="`${entry.kind}:${entry.target}`" class="players__invite">
					<span>{{ inviteText(entry) }}</span>
					<NcButton variant="error" :disabled="busy" @click="remove(entry)">
						{{ t('parent.players.remove') }}
					</NcButton>
				</li>
			</ul>
		</template>

		<template #actions>
			<NcButton variant="tertiary" @click="emit('close')">
				{{ t('parent.common.close') }}
			</NcButton>
			<NcButton variant="primary" @click="emit('invite')">
				{{ t('parent.common.invitePlayers') }}
			</NcButton>
		</template>
	</NcDialog>

	<!-- Bestätigung beim Einschalten (D-07): ersetzt den Spieler-Dialog, solange sie offen ist. -->
	<NcDialog
		v-else
		:open="true"
		:name="t('parent.common.markAdult')"
		@update:open="onConfirmOpen">
		<div class="players__adult-confirm">
			<p class="players__adult-lead">
				{{ confirmLead([confirmAdult.display_name]) }}
			</p>
			<p>{{ confirmScope() }}</p>
			<p class="players__adult-note">
				{{ confirmWarning() }}
			</p>
			<p v-if="confirmAdult.has_rules" class="players__adult-note">
				{{ rulesKeptText(confirmAdult.display_name) }}
			</p>
			<NcNoteCard v-if="confirmError" type="error">
				{{ confirmError }}
			</NcNoteCard>
		</div>

		<template #actions>
			<NcButton variant="tertiary" :disabled="confirmSaving" @click="cancelAdult">
				{{ t('parent.common.cancel') }}
			</NcButton>
			<NcButton variant="warning" :disabled="confirmSaving" @click="confirmAdultOn">
				<template v-if="confirmSaving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('parent.common.markAdult') }}
			</NcButton>
		</template>
	</NcDialog>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcFormBox from '@nextcloud/vue/components/NcFormBox'
import NcFormBoxCopyButton from '@nextcloud/vue/components/NcFormBoxCopyButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTextField from '@nextcloud/vue/components/NcTextField'
import {
	errorText,
	listPlayers,
	removeInvite,
	renamePlayer,
	rotatePassword,
	setAdult,
} from '../api.js'
import {
	adultOffText,
	adultOnText,
	confirmLead,
	confirmScope,
	confirmWarning,
	nowVerwalterText,
	rulesKeptText,
	switchMeta,
} from '../adult.js'
import { t } from '../i18n/index.js'
import { notAppliedMessage } from '../playtime.js'

const props = defineProps({
	// { id, name } der Welt; nur id geht an die API.
	world: { type: Object, required: true },
})
// changed: Einladungen oder Namen geändert, das Dashboard lädt die Liste neu.
const emit = defineEmits(['changed', 'close', 'invite'])

// Passwörter liegen nur in diesem Dialog im Speicher, nie im Browser-Speicher.
const players = ref([])
const invites = ref([])
const loading = ref(true)
const loadError = ref('')
const error = ref('')
const notice = ref('')
const notApplied = ref(false)
const busy = ref(false)
// nc_user -> true, solange das Passwort sichtbar ist.
const revealed = reactive({})
const copied = ref('')
const rotating = ref('')
const renaming = ref('')
const newName = ref('')
const adultNotApplied = ref(false)
const info = ref('')
// Eigene Anzeige der Erwachsen-Schalter (nc_user -> bool), damit sie bei Fehler zurückspringen.
const adultShown = reactive({})
// nc_user, dessen Schalter gerade speichert.
const adultSaving = ref('')
// { nc_user, display_name, has_rules } solange die Bestätigung offen ist, sonst null.
const confirmAdult = ref(null)
const confirmSaving = ref(false)
const confirmError = ref('')

function apply(result) {
	players.value = result?.players ?? []
	invites.value = result?.invites ?? []
	// Sofortige Wirkung sichtbar: die Schalter folgen der Serverantwort.
	for (const player of players.value) {
		if (adultSaving.value !== player.nc_user) {
			adultShown[player.nc_user] = Boolean(player.adult)
		}
	}
}

async function load() {
	try {
		apply(await listPlayers(props.world.id))
		loadError.value = ''
	} catch (err) {
		loadError.value = errorText(err)
	} finally {
		loading.value = false
	}
}

function viaText(via) {
	if (typeof via === 'string' && via.startsWith('group:')) {
		return t('parent.players.viaGroup', { group: via.slice('group:'.length) })
	}
	if (via === 'group') {
		return t('parent.players.viaSomeGroup')
	}
	return t('parent.players.direct')
}

function inviteText(entry) {
	if (entry.kind === 'group') {
		return t('parent.players.inviteGroup', { group: entry.target })
	}
	const player = players.value.find((item) => item.nc_user === entry.target)
	return player ? `${player.display_name} (${entry.target})` : entry.target
}

function toggleReveal(player) {
	revealed[player.nc_user] = !revealed[player.nc_user]
}

async function copyPassword(player) {
	try {
		await navigator.clipboard.writeText(player.password)
		copied.value = player.nc_user
		setTimeout(() => {
			if (copied.value === player.nc_user) {
				copied.value = ''
			}
		}, 2000)
	} catch {
		error.value = t('parent.players.copyFailed')
	}
}

function resetMessages() {
	error.value = ''
	notice.value = ''
	notApplied.value = false
	adultNotApplied.value = false
	info.value = ''
}

// Fokus zurück auf die Schalterzeile der Person (UI-SPEC B2, Barrierefreiheit).
async function focusAdultRow(ncUser) {
	await nextTick()
	setTimeout(() => {
		const rows = document.querySelectorAll('.players__item')
		const row = [...rows].find((item) => item.dataset.ncUser === ncUser)
		row?.querySelector('.players__adult input')?.focus()
	}, 0)
}

async function reloadPlayers() {
	try {
		apply(await listPlayers(props.world.id))
	} catch (err) {
		error.value = errorText(err)
	}
}

function toggleAdult(player, on) {
	if (busy.value || adultSaving.value) {
		return
	}
	resetMessages()
	rotating.value = ''
	renaming.value = ''
	if (on) {
		// Einschalten nur nach Bestätigung (D-07); der Schalter bleibt bis dahin aus.
		adultShown[player.nc_user] = false
		confirmError.value = ''
		confirmAdult.value = {
			nc_user: player.nc_user,
			display_name: player.display_name,
			has_rules: Boolean(player.has_rules),
		}
		return
	}
	switchOff(player)
}

// Ausschalten wirkt sofort ohne Dialog (macht die Regeln strenger).
async function switchOff(player) {
	adultSaving.value = player.nc_user
	adultShown[player.nc_user] = false
	try {
		const result = await setAdult(player.nc_user, false)
		adultShown[player.nc_user] = Boolean(result?.adult)
		notice.value = adultOffText(player.display_name)
		adultNotApplied.value = result?.applied === false
		adultSaving.value = ''
		await reloadPlayers()
		emit('changed')
	} catch (err) {
		adultShown[player.nc_user] = true
		error.value = errorText(err)
	} finally {
		adultSaving.value = ''
		focusAdultRow(player.nc_user)
	}
}

function cancelAdult() {
	if (confirmSaving.value) {
		return
	}
	const ncUser = confirmAdult.value?.nc_user
	confirmAdult.value = null
	confirmError.value = ''
	if (ncUser) {
		focusAdultRow(ncUser)
	}
}

function onConfirmOpen(open) {
	if (!open) {
		cancelAdult()
	}
}

async function confirmAdultOn() {
	const target = confirmAdult.value
	if (!target || confirmSaving.value) {
		return
	}
	confirmSaving.value = true
	confirmError.value = ''
	try {
		const result = await setAdult(target.nc_user, true)
		adultShown[target.nc_user] = Boolean(result?.adult)
		notice.value = adultOnText(target.display_name)
		adultNotApplied.value = result?.applied === false
		confirmAdult.value = null
		await reloadPlayers()
		emit('changed')
		focusAdultRow(target.nc_user)
	} catch (err) {
		if (err?.response?.status === 409) {
			// Konto wurde inzwischen Verwalter: Hinweis statt Fehler, Liste neu laden.
			confirmAdult.value = null
			info.value = nowVerwalterText(target.display_name)
			await reloadPlayers()
			emit('changed')
		} else {
			// Fehler im Dialog, er bleibt offen; der Schalter bleibt aus.
			confirmError.value = errorText(err)
		}
	} finally {
		confirmSaving.value = false
	}
}

function askRotate(player) {
	resetMessages()
	renaming.value = ''
	rotating.value = player.nc_user
}

function startRename(player) {
	resetMessages()
	rotating.value = ''
	renaming.value = player.nc_user
	newName.value = player.player_name
}

// Passwort neu und Umbenennen gelten für das Konto in allen Welten; danach die Liste neu laden.
async function change(action, success) {
	busy.value = true
	resetMessages()
	try {
		const result = await action()
		notice.value = success
		notApplied.value = result?.applied === false
		rotating.value = ''
		renaming.value = ''
		apply(await listPlayers(props.world.id))
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		busy.value = false
	}
}

function confirmRotate(player) {
	change(() => rotatePassword(player.nc_user), t('parent.players.rotated', { name: player.display_name }))
}

function confirmRename(player) {
	const name = newName.value.trim()
	change(() => renamePlayer(player.nc_user, name), t('parent.players.renamed', { name: player.display_name, newName: name }))
}

async function remove(entry) {
	busy.value = true
	resetMessages()
	try {
		const result = await removeInvite(props.world.id, entry.kind, entry.target)
		apply(result)
		notice.value = t('parent.players.inviteRemoved')
		notApplied.value = result?.applied === false
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		busy.value = false
	}
}

function onOpen(open) {
	if (!open) {
		emit('close')
	}
}

onMounted(load)

defineExpose({ reload: load })
</script>

<style scoped>
.players__list,
.players__invites {
	list-style: none;
	margin: 0;
	padding: 0;
}

.players__item {
	display: flex;
	flex-direction: column;
	gap: 8px;
	padding: 12px 0;
	border-bottom: 1px solid var(--color-border);
}

.players__head {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
}

.players__adult {
	display: flex;
	flex-direction: column;
	min-width: 0;
}

.players__adult :deep(.checkbox-content__description) {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.players__adult-confirm {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.players__adult-confirm p {
	margin: 0;
}

.players__adult-lead {
	font-weight: bold;
}

.players__adult-note {
	color: var(--color-text-maxcontrast);
}

.players__via,
.players__masked,
.players__empty {
	color: var(--color-text-maxcontrast);
}

.players__password,
.players__actions,
.players__confirm {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
}

.players__rename {
	display: flex;
	flex-direction: column;
	gap: 8px;
}

.players__title {
	margin-top: 16px;
}

.players__invite {
	display: flex;
	justify-content: space-between;
	align-items: center;
	padding: 6px 0;
}
</style>
