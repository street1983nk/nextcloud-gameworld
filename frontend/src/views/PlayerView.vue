<!-- Player view: own data only (/api/me, /api/my/worlds, /api/my/playtime), never the management API. -->
<template>
	<div class="gameworld-player">
		<h2>{{ t('kids.player.title') }}</h2>
		<p class="gameworld-player__hello">
			{{ t('kids.player.hello', { name: user.display_name }) }}
		</p>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<PlaytimeCard :playtime="playtime" />

		<NcLoadingIcon v-if="loading" :size="32" />
		<NcEmptyContent
			v-else-if="worlds.length === 0 && !error"
			:name="t('kids.player.emptyName')"
			:description="t('kids.player.emptyDescription')" />
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
import PlaytimeCard from '../components/PlaytimeCard.vue'
import { errorText, getMyPlaytime, listMyWorlds } from '../api.js'
import { t } from '../i18n/index.js'

// Response of /api/me: greeting with the display name.
defineProps({
	user: {
		type: Object,
		required: true,
	},
})

const POLL_MS = 5000

const worlds = ref([])
// Own remaining time (/api/my/playtime); null until the first fetch has arrived.
const playtime = ref(null)
const loading = ref(true)
// Disappears on the next successful fetch.
const error = ref('')

// Only the response of the most recently started fetch counts (pattern from ParentView).
let refreshSeq = 0

async function refresh() {
	const seq = ++refreshSeq
	try {
		// Worlds and remaining time in the same cycle; a disturbance of one does not hide the other.
		const [mine, own] = await Promise.allSettled([listMyWorlds(), getMyPlaytime()])
		if (seq !== refreshSeq) {
			return
		}
		if (mine.status === 'fulfilled') {
			worlds.value = mine.value
		}
		if (own.status === 'fulfilled') {
			playtime.value = own.value
		}
		const failed = [mine, own].find((result) => result.status === 'rejected')
		error.value = failed ? errorText(failed.reason) : ''
	} finally {
		loading.value = false
	}
}

// Every 5 s, only with a visible tab, so that "Läuft" becomes visible without reloading.
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
