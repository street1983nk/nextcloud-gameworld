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
			<template v-else-if="me.role === 'verwalter'">
				<div v-if="originAsk" class="gameworld-origin">
					<NcNoteCard type="info">
						<p>{{ t('kids.app.originQuestion') }}</p>
						<p class="gameworld-origin__urls">
							{{ t('kids.app.originCurrent') }} <span>{{ originAsk.current }}</span><br>
							{{ t('kids.app.originProposed') }} <span>{{ originAsk.proposed }}</span>
						</p>
						<div class="gameworld-origin__actions">
							<NcButton variant="primary" :disabled="originSaving" @click="confirmOrigin">
								{{ t('kids.app.originYes') }}
							</NcButton>
							<NcButton variant="tertiary" :disabled="originSaving" @click="dismissOrigin">
								{{ t('kids.app.originNo') }}
							</NcButton>
						</div>
					</NcNoteCard>
				</div>
				<PauseView v-if="page === 'pause'" />
				<AttemptsView v-else-if="page === 'versuch'" :key="routeKey" :me="me" />
				<ReviewView v-else-if="page === 'rueckblick'" :key="routeKey" />
				<ParentView v-else :me="me" @reload-me="reloadMe" />
			</template>
			<PlayerView v-else :user="me" />
		</NcAppContent>
	</NcContent>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { getRootUrl } from '@nextcloud/router'
import NcAppContent from '@nextcloud/vue/components/NcAppContent'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcContent from '@nextcloud/vue/components/NcContent'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import AttemptsView from './views/AttemptsView.vue'
import ParentView from './views/ParentView.vue'
import PauseView from './views/PauseView.vue'
import PlayerView from './views/PlayerView.vue'
import ReviewView from './views/ReviewView.vue'
import { getMe, reportOrigin } from './api.js'
import { t } from './i18n/index.js'
import { originQuestion, readDismissed, rememberDismissed } from './origin.js'
import { ROUTE_EVENT, currentPage } from './route.js'

// Die Rolle kommt allein vom Backend (/api/me: Gruppe admin plus die konfigurierten
// Verwalter-Gruppen, nc_admin für die Admin-Abschnitte). Die Weiche hier blendet nur
// aus; gesperrt ist die Verwaltung serverseitig (403). Kinder sehen immer ihre
// Ansicht, auch auf einem Verwalter-Pfad (T-04.1-38).
const loading = ref(true)
const error = ref('')
const me = ref(null)
// Handy-Seite aus dem Pfad (route.js): "pause", "versuch", "rueckblick" oder "" (Übersicht).
const page = ref(currentPage())
// Neue Parameter (anderer Tag, andere Welt) laden die Seite neu.
const routeKey = ref(window.location.search)
// Rückfrage zur Link-Adresse (WR-04): { current, proposed } oder null.
const originAsk = ref(null)
const originSaving = ref(false)

function storage() {
	try {
		return window.localStorage
	} catch {
		return null
	}
}

async function confirmOrigin() {
	originSaving.value = true
	try {
		await reportOrigin(window.location.origin, getRootUrl(), true)
	} catch {
		// Best effort: Beim nächsten Besuch fragt die Seite erneut.
	} finally {
		originSaving.value = false
		originAsk.value = null
	}
}

function dismissOrigin() {
	if (originAsk.value) {
		rememberDismissed(storage(), originAsk.value.proposed)
	}
	originAsk.value = null
}

// Rechte haben sich geändert (403 in einem Admin-Abschnitt): /api/me neu lesen;
// schlägt das fehl, bleibt der alte Stand und der Server sperrt weiter.
async function reloadMe() {
	try {
		me.value = await getMe()
	} catch {
		// Best effort.
	}
}

function syncPage() {
	page.value = currentPage()
	routeKey.value = window.location.search
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
			: t('kids.app.loadFailed')
	} finally {
		loading.value = false
	}
	if (me.value?.role === 'verwalter') {
		// Basis-URL für absolute Links in Benachrichtigungen (Pattern 9); best effort.
		// Der Server speichert nur die erste Adresse; eine andere erst nach "Ja".
		reportOrigin(window.location.origin, getRootUrl())
			.then((result) => {
				originAsk.value = originQuestion(result, readDismissed(storage()))
			})
			.catch(() => {})
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

.gameworld-origin {
	max-width: 820px;
	padding: 12px 24px 0;
}

.gameworld-origin__urls span {
	overflow-wrap: anywhere;
	font-weight: bold;
}

.gameworld-origin__actions {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	margin-top: 8px;
}
</style>
