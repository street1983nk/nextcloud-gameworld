<!-- Karte einer eigenen Welt: Status ohne Steuerknöpfe, Verbindungsdaten zum Kopieren, Anleitung. -->
<template>
	<section class="connection-card" :data-world-id="world.id">
		<header class="connection-card__head">
			<h3>{{ world.name }}</h3>
			<NcChip
				:text="world.status_text"
				:variant="chipVariant(world.status)"
				no-close />
		</header>

		<NcFormBox>
			<NcFormBoxCopyButton label="Adresse" :value="host" />
			<NcFormBoxCopyButton label="Port" :value="String(world.port)" />
			<NcFormBoxCopyButton label="Spielername" :value="world.player_name" />
			<!-- Der Kopierknopf zeigt seinen Wert immer an, darum fürs Passwort erst nach "Anzeigen". -->
			<NcFormBoxCopyButton v-if="revealed" label="Passwort" :value="world.password" />
		</NcFormBox>

		<div class="connection-card__password">
			<span v-if="!revealed" class="connection-card__masked" aria-label="Passwort verdeckt">
				Passwort: ••••-••••-••••
			</span>
			<NcButton variant="tertiary" @click="revealed = !revealed">
				{{ revealed ? 'Verbergen' : 'Anzeigen' }}
			</NcButton>
			<NcButton v-if="!revealed" variant="tertiary" @click="copyPassword">
				{{ copied ? 'Kopiert' : 'Passwort kopieren' }}
			</NcButton>
		</div>
		<NcNoteCard v-if="copyError" type="warning">
			{{ copyError }}
		</NcNoteCard>

		<JoinGuide :host="host" :port="world.port" :player-name="world.player_name" />
	</section>
</template>

<script setup>
import { computed, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcFormBox from '@nextcloud/vue/components/NcFormBox'
import NcFormBoxCopyButton from '@nextcloud/vue/components/NcFormBoxCopyButton'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import JoinGuide from './JoinGuide.vue'

const props = defineProps({
	// Eintrag aus /api/my/worlds: id, name, status, status_text, host, port, player_name, password.
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

const host = computed(() => props.world.host || props.fallbackHost)

function chipVariant(status) {
	return CHIP_VARIANT[status] ?? 'warning'
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
		copyError.value = 'Kopieren geht in diesem Browser nicht. Klick auf Anzeigen und schreib das Passwort ab.'
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
	gap: 12px;
	align-items: center;
	margin-bottom: 12px;
}

.connection-card__head h3 {
	margin: 0;
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
