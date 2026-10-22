<template>
	<NcContent app-name="gameworld">
		<NcAppContent>
			<div v-if="loading" class="gameworld-shell">
				<NcLoadingIcon :size="32" />
			</div>
			<div v-else-if="error" class="gameworld-shell">
				<NcNoteCard type="error">
					{{ error }}
				</NcNoteCard>
			</div>
			<ParentView v-else-if="me.role === 'verwalter'" />
			<PlayerView v-else :user="me" />
		</NcAppContent>
	</NcContent>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import NcAppContent from '@nextcloud/vue/components/NcAppContent'
import NcContent from '@nextcloud/vue/components/NcContent'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import ParentView from './views/ParentView.vue'
import PlayerView from './views/PlayerView.vue'
import { getMe, reportOrigin } from './api.js'
import { ROUTE_EVENT, currentPage } from './route.js'

// Die Rolle kommt allein vom Backend (/api/me, Gruppe admin). Die Weiche hier
// blendet nur aus; gesperrt ist die Verwaltung serverseitig (403). Kinder sehen
// immer ihre Ansicht, auch auf einem Verwalter-Pfad (T-04.1-38).
const loading = ref(true)
const error = ref('')
const me = ref(null)
// Handy-Seite aus dem Pfad (route.js): "pause", "versuch", "rueckblick" oder "" (Übersicht).
const page = ref(currentPage())

function syncPage() {
	page.value = currentPage()
}

onMounted(async () => {
	window.addEventListener('popstate', syncPage)
	window.addEventListener(ROUTE_EVENT, syncPage)
	try {
		me.value = await getMe()
	} catch (err) {
		const detail = err?.response?.data?.detail
		error.value = typeof detail === 'string' && detail !== ''
			? detail
			: 'Gameworld konnte nicht geladen werden. Bitte lade die Seite neu.'
	} finally {
		loading.value = false
	}
	if (me.value?.role === 'verwalter') {
		// Basis-URL für absolute Links in Benachrichtigungen (Pattern 9); best effort.
		reportOrigin(window.location.origin).catch(() => {})
	}
})

onBeforeUnmount(() => {
	window.removeEventListener('popstate', syncPage)
	window.removeEventListener(ROUTE_EVENT, syncPage)
})
</script>

<style scoped>
.gameworld-shell {
	max-width: 820px;
	padding: 24px;
}
</style>
