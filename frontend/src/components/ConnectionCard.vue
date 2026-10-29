<!-- Card of an own world: status without control buttons, connection data to copy, instructions. -->
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

		<!-- Browser spike 04.2: only with a running world and the spike switched on. New tab, no embedding. -->
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
			<!-- The copy button always shows its value, so for the password only after "Anzeigen". -->
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
	// Entry from /api/my/worlds: id, name, status, status_text, host, port, player_name, password,
	// window_open and window_next (time window of the world, null without a window).
	world: {
		type: Object,
		required: true,
	},
	// Player address when the parents entered none: hostname of this browser.
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
// "Heute offen, 10 bis 12 Uhr" or "Diese Welt ist gerade zu. ..."; null without a time window.
const windowHint = computed(() => windowText(props.world))

function chipVariant(status) {
	return CHIP_VARIANT[status] ?? 'warning'
}

// Fetch the ticket and open the play page in a new tab. The ticket is only in the
// fragment (never goes to a server, the play page deletes it at once); the play page
// fetches the password itself via POST, it is never in an address.
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
