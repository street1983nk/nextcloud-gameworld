<!-- Spieleransicht: nur eigene Daten (/api/me, /api/my/worlds), nie die Verwaltungs-API. -->
<template>
	<div class="gameworld-player">
		<h2>Meine Welten</h2>
		<p class="gameworld-player__hello">
			Hallo {{ user.display_name }}!
		</p>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<NcLoadingIcon v-if="loading" :size="32" />
		<NcEmptyContent
			v-else-if="worlds.length === 0 && !error"
			name="Du bist noch zu keiner Welt eingeladen"
			description="Sobald deine Eltern dich in eine Welt einladen, steht hier, wie du hineinkommst." />
		<template v-else>
			<ConnectionCard v-for="world in worlds" :key="world.id" :world="world" />
		</template>
	</div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import NcEmptyContent from '@nextcloud/vue/components/NcEmptyContent'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import ConnectionCard from '../components/ConnectionCard.vue'
import { errorText, listMyWorlds } from '../api.js'

// Antwort von /api/me: Anrede mit dem Anzeigenamen.
defineProps({
	user: {
		type: Object,
		required: true,
	},
})

const POLL_MS = 5000

const worlds = ref([])
const loading = ref(true)
// Verschwindet beim nächsten erfolgreichen Abruf.
const error = ref('')

// Nur die Antwort des zuletzt gestarteten Abrufs zählt (Muster aus ParentView).
let refreshSeq = 0

async function refresh() {
	const seq = ++refreshSeq
	try {
		const result = await listMyWorlds()
		if (seq === refreshSeq) {
			worlds.value = result
			error.value = ''
		}
	} catch (err) {
		if (seq === refreshSeq) {
			error.value = errorText(err)
		}
	} finally {
		loading.value = false
	}
}

// Alle 5 s, nur bei sichtbarem Tab, damit "Läuft" ohne Neuladen sichtbar wird.
let timer = null
let unmounted = false

function schedule() {
	clearTimeout(timer)
	timer = null
	if (!unmounted && document.visibilityState === 'visible') {
		timer = setTimeout(async () => {
			await refresh()
			schedule()
		}, POLL_MS)
	}
}

function onTabChange() {
	if (document.visibilityState === 'visible') {
		refresh()
	}
	schedule()
}

onMounted(async () => {
	document.addEventListener('visibilitychange', onTabChange)
	await refresh()
	schedule()
})

onUnmounted(() => {
	unmounted = true
	clearTimeout(timer)
	timer = null
	document.removeEventListener('visibilitychange', onTabChange)
})
</script>

<style scoped>
.gameworld-player {
	max-width: 820px;
	padding: 24px;
}

.gameworld-player__hello {
	margin-bottom: 16px;
}
</style>
