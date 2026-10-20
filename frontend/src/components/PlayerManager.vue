<!-- Spieler einer Welt: Spielername, Passwort (verdeckt), Herkunft, Passwort neu, Umbenennen, Einladungen entfernen. -->
<template>
	<NcDialog
		:open="true"
		:name="`Spieler von ${world.name}`"
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
				Die Änderung wirkt beim nächsten Start der Welt.
			</NcNoteCard>

			<p v-if="!loadError && players.length === 0" class="players__empty">
				Noch niemand eingeladen.
			</p>

			<ul v-else class="players__list">
				<li
					v-for="player in players"
					:key="player.nc_user"
					class="players__item"
					:data-nc-user="player.nc_user">
					<div class="players__head">
						<strong>{{ player.display_name }}</strong>
						<span class="players__via">{{ viaText(player.via) }}</span>
					</div>

					<NcFormBox>
						<NcFormBoxCopyButton label="Spielername" :value="player.player_name" />
						<NcFormBoxCopyButton
							v-if="revealed[player.nc_user]"
							label="Passwort"
							:value="player.password" />
					</NcFormBox>

					<div class="players__password">
						<span v-if="!revealed[player.nc_user]" class="players__masked" aria-label="Passwort verdeckt">
							Passwort: ••••-••••-••••
						</span>
						<NcButton variant="tertiary" @click="toggleReveal(player)">
							{{ revealed[player.nc_user] ? 'Verbergen' : 'Anzeigen' }}
						</NcButton>
						<NcButton
							v-if="!revealed[player.nc_user]"
							variant="tertiary"
							@click="copyPassword(player)">
							{{ copied === player.nc_user ? 'Kopiert' : 'Passwort kopieren' }}
						</NcButton>
					</div>

					<div class="players__actions">
						<NcButton :disabled="busy" @click="askRotate(player)">
							Neues Passwort
						</NcButton>
						<NcButton :disabled="busy" @click="startRename(player)">
							Name ändern
						</NcButton>
					</div>

					<NcNoteCard v-if="rotating === player.nc_user" type="warning">
						<p>Das alte Passwort funktioniert danach nicht mehr. Das neue gilt in allen Welten dieses Kontos.</p>
						<div class="players__confirm">
							<NcButton variant="tertiary" :disabled="busy" @click="rotating = ''">
								Abbrechen
							</NcButton>
							<NcButton variant="warning" :disabled="busy" @click="confirmRotate(player)">
								Neues Passwort erzeugen
							</NcButton>
						</div>
					</NcNoteCard>

					<div v-if="renaming === player.nc_user" class="players__rename">
						<NcNoteCard type="warning">
							Mit neuem Namen beginnt im Spiel ein neuer Spielstand; Gebautes in der Welt bleibt, das Inventar des alten Namens nicht.
						</NcNoteCard>
						<NcTextField
							v-model="newName"
							label="Neuer Spielername"
							:maxlength="20"
							:disabled="busy" />
						<div class="players__confirm">
							<NcButton variant="tertiary" :disabled="busy" @click="renaming = ''">
								Abbrechen
							</NcButton>
							<NcButton
								variant="primary"
								:disabled="busy || newName.trim() === ''"
								@click="confirmRename(player)">
								Namen speichern
							</NcButton>
						</div>
					</div>
				</li>
			</ul>

			<h3 class="players__title">
				Einladungen
			</h3>
			<p v-if="invites.length === 0" class="players__empty">
				Keine Einladungen.
			</p>
			<ul v-else class="players__invites">
				<li v-for="entry in invites" :key="`${entry.kind}:${entry.target}`" class="players__invite">
					<span>{{ inviteText(entry) }}</span>
					<NcButton variant="error" :disabled="busy" @click="remove(entry)">
						Entfernen
					</NcButton>
				</li>
			</ul>
		</template>

		<template #actions>
			<NcButton variant="tertiary" @click="emit('close')">
				Schließen
			</NcButton>
			<NcButton variant="primary" @click="emit('invite')">
				Spieler einladen
			</NcButton>
		</template>
	</NcDialog>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
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
} from '../api.js'

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

function apply(result) {
	players.value = result?.players ?? []
	invites.value = result?.invites ?? []
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
		return `über Gruppe ${via.slice('group:'.length)}`
	}
	if (via === 'group') {
		return 'über eine Gruppe'
	}
	return 'direkt eingeladen'
}

function inviteText(entry) {
	if (entry.kind === 'group') {
		return `Gruppe ${entry.target}`
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
		error.value = 'Kopieren ist in diesem Browser nicht möglich. Bitte Passwort anzeigen und abschreiben.'
	}
}

function resetMessages() {
	error.value = ''
	notice.value = ''
	notApplied.value = false
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
	change(() => rotatePassword(player.nc_user), `Neues Passwort für ${player.display_name} erzeugt.`)
}

function confirmRename(player) {
	const name = newName.value.trim()
	change(() => renamePlayer(player.nc_user, name), `${player.display_name} heißt im Spiel jetzt ${name}.`)
}

async function remove(entry) {
	busy.value = true
	resetMessages()
	try {
		const result = await removeInvite(props.world.id, entry.kind, entry.target)
		apply(result)
		notice.value = 'Einladung entfernt.'
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
	gap: 8px;
	align-items: baseline;
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
