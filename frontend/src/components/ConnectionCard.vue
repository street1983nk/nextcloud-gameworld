<!-- Karte einer eigenen Welt: Status ohne Steuerknöpfe, Verbindungsdaten zum Kopieren, Anleitung. -->
<template>
	<section class="connection-card" :data-world-id="world.id">
		<header class="connection-card__head">
			<h3>{{ world.name }}</h3>
			<NcChip
				:text="world.status_text"
				:variant="chipVariant(world.status)"
				no-close />
			<NcChip
				v-if="windowHint"
				class="connection-card__window"
				:text="windowHint"
				:variant="world.window_open ? 'tertiary' : 'warning'"
				no-close />
		</header>

		<!-- Browser-Spike 04.2: nur bei laufender Welt und eingeschaltetem Spike. Neuer Tab, keine Einbettung. -->
		<div v-if="showPlay" class="connection-card__play">
			<NcButton variant="primary" :disabled="playStarting" @click="playInBrowser">
				{{ t('kids.connection.play') }}
			</NcButton>
		</div>
		<NcNoteCard v-if="playError" type="error">
			{{ t('kids.connection.playFailed', { detail: playError }) }}
		</NcNoteCard>

		<NcFormBox>
			<NcFormBoxCopyButton :label="t('kids.connection.address')" :value="host" />
			<NcFormBoxCopyButton :label="t('kids.connection.port')" :value="String(world.port)" />
			<NcFormBoxCopyButton :label="t('kids.connection.playerName')" :value="world.player_name" />
			<!-- Der Kopierknopf zeigt seinen Wert immer an, darum fürs Passwort erst nach "Anzeigen". -->
			<NcFormBoxCopyButton v-if="revealed" :label="t('kids.connection.password')" :value="world.password" />
		</NcFormBox>

		<div class="connection-card__password">
			<span v-if="!revealed" class="connection-card__masked" :aria-label="t('kids.connection.maskedLabel')">
				{{ t('kids.connection.masked') }}
			</span>
			<NcButton variant="tertiary" @click="revealed = !revealed">
				{{ revealed ? t('kids.connection.hide') : t('kids.connection.show') }}
			</NcButton>
			<NcButton v-if="!revealed" variant="tertiary" @click="copyPassword">
				{{ copied ? t('kids.connection.copied') : t('kids.connection.copyPassword') }}
			</NcButton>
		</div>
		<NcNoteCard v-if="copyError" type="warning">
			{{ copyError }}
		</NcNoteCard>

		<JoinGuide :host="host" :port="world.port" :player-name="world.player_name" />
	</section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcFormBox from '@nextcloud/vue/components/NcFormBox'
import NcFormBoxCopyButton from '@nextcloud/vue/components/NcFormBoxCopyButton'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import JoinGuide from './JoinGuide.vue'
import { errorText, getPlayStatus, getPlayTicket } from '../api.js'
import { t } from '../i18n/index.js'
import { windowText } from '../playtime.js'

const props = defineProps({
	// Eintrag aus /api/my/worlds: id, name, status, status_text, host, port, player_name, password,
	// window_open und window_next (Zeitfenster der Welt, null ohne Fenster).
	world: {
		type: Object,
		required: true,
	},
	// Spieler-Adresse, wenn die Eltern keine eingetragen haben: Hostname dieses Browsers.
	fallbackHost: {
		type: String,
		default: () => window.location.hostname,
	},
})

const CHIP_VARIANT = {
	running: 'success',
	starting: 'warning',
	stopped: 'tertiary',
	error: 'error',
	unknown: 'warning',
}

const revealed = ref(false)
const copied = ref(false)
const copyError = ref('')
const playEnabled = ref(false)
const playStarting = ref(false)
const playError = ref('')

onMounted(async () => {
	playEnabled.value = await getPlayStatus()
})

const showPlay = computed(() => playEnabled.value && props.world.status === 'running')

const host = computed(() => props.world.host || props.fallbackHost)
// "Heute offen, 10 bis 12 Uhr" bzw. "Diese Welt ist gerade zu. ..."; null ohne Zeitfenster.
const windowHint = computed(() => windowText(props.world))

function chipVariant(status) {
	return CHIP_VARIANT[status] ?? 'warning'
}

// Ticket holen und die Spielseite in einem neuen Tab öffnen. Das Ticket steht nur im
// Fragment (geht nie an einen Server, die Spielseite löscht es sofort); das Passwort
// holt die Spielseite selbst per POST, es steht nie in einer Adresse.
async function playInBrowser() {
	playError.value = ''
	playStarting.value = true
	try {
		const ticket = await getPlayTicket(props.world.id)
		const url = window.location.origin + ticket.play_path + '#t=' + encodeURIComponent(ticket.ticket)
		window.open(url, '_blank', 'noopener')
	} catch (err) {
		playError.value = errorText(err)
	} finally {
		playStarting.value = false
	}
}

async function copyPassword() {
	copyError.value = ''
	try {
		await navigator.clipboard.writeText(props.world.password)
		copied.value = true
		setTimeout(() => {
			copied.value = false
		}, 2000)
	} catch {
		copyError.value = t('kids.connection.copyFailed')
	}
}
</script>

<style scoped>
.connection-card {
	margin-bottom: 24px;
	padding: 16px;
	border: 1px solid var(--color-border);
	border-radius: var(--border-radius-large);
}

.connection-card__head {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
	margin-bottom: 12px;
}

.connection-card__head h3 {
	margin: 0;
}

.connection-card__play {
	margin-bottom: 12px;
}

.connection-card__password {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	align-items: center;
	margin-top: 8px;
}

.connection-card__masked {
	font-family: monospace;
}
</style>
