<!-- Phone page join attempts (ELTERN-02, D-07 to D-09): who was not invited, and the way to invite. -->
<template>
	<div class="mobile-page">
		<h2>{{ t('kids.attempts.title') }}</h2>
		<p v-if="heading" class="mobile-page__day">
			{{ heading }}
		</p>

		<NcNoteCard type="info">
			{{ t('kids.attempts.intro') }}
		</NcNoteCard>

		<div v-if="loading" class="mobile-page__loading">
			<NcLoadingIcon :size="32" />
		</div>

		<template v-else-if="!error">
			<p v-if="attempts.length === 0" class="mobile-page__empty">
				{{ emptyText }}
			</p>
			<ul v-else class="attempts">
				<li
					v-for="attempt in attempts"
					:key="`${attempt.world_id}-${attempt.player_name}`"
					class="attempts__item">
					<strong class="attempts__name">{{ attempt.player_name }}</strong>
					<span class="attempts__meta">
						{{ attempt.world_name }}, {{ attempt.clock }}<template v-if="attempt.count >= 2">{{ t('kids.attempts.repeated') }}</template>
					</span>
				</li>
			</ul>

			<div v-if="worlds.length > 0" class="mobile-page__buttons">
				<NcButton
					v-for="world in worlds"
					:key="world.id"
					variant="primary"
					@click="inviteWorld = world">
					{{ worlds.length > 1 ? t('kids.attempts.inviteWorld', { name: world.name }) : t('kids.attempts.invite') }}
				</NcButton>
			</div>
		</template>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<div class="mobile-page__buttons mobile-page__back">
			<NcButton variant="tertiary" @click="navigate('')">
				{{ t('kids.common.back') }}
			</NcButton>
		</div>

		<!-- D-09: only the normal invite dialog of the world, never a button for the foreign player name. -->
		<InviteDialog
			v-if="inviteWorld"
			:key="`invite-${inviteWorld.id}`"
			:world="inviteWorld"
			:me="me"
			@close="inviteWorld = null" />
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import InviteDialog from '../components/InviteDialog.vue'
import { errorText, listAttempts } from '../api.js'
import { t } from '../i18n/index.js'
import { currentParams, dayLabel, navigate } from '../route.js'

defineProps({
	// Response of /api/me (App.vue); the invite dialog uses it to show the invitation limit (D-01).
	me: { type: Object, required: false, default: null },
})

// Parameters from the link are already checked (route.js); the backend checks again.
// Without tag the backend picks today in the household time zone, not the
// clock of this device (IN-04); day and "heute" come from the response.
const params = currentParams()
const worldFilter = params.welt ?? null

const loading = ref(true)
const error = ref('')
const attempts = ref([])
const inviteWorld = ref(null)
const day = ref(params.tag ?? '')
const today = ref('')

const heading = computed(() => (day.value ? dayLabel(day.value, today.value) : ''))
const emptyText = computed(() => (day.value !== '' && day.value === today.value
	? t('kids.attempts.emptyToday')
	: t('kids.attempts.emptyDay')))

// Once per world { id, name } for the invite dialog, in the order of the list.
const worlds = computed(() => {
	const seen = new Map()
	for (const attempt of attempts.value) {
		if (!seen.has(attempt.world_id)) {
			seen.set(attempt.world_id, { id: attempt.world_id, name: attempt.world_name })
		}
	}
	return [...seen.values()]
})

onMounted(async () => {
	try {
		const result = await listAttempts(params.tag ?? null, worldFilter)
		attempts.value = result.attempts ?? []
		day.value = result.day ?? day.value
		today.value = result.today ?? ''
	} catch (err) {
		error.value = errorText(err)
	} finally {
		loading.value = false
	}
})
</script>

<style scoped>
.mobile-page {
	max-width: 820px;
	padding: 24px;
	box-sizing: border-box;
	overflow-wrap: anywhere;
}

.mobile-page__day {
	margin: 0 0 12px;
	color: var(--color-text-maxcontrast);
}

.mobile-page__loading {
	padding: 16px 0;
}

.mobile-page__empty {
	margin: 16px 0;
}

.mobile-page__buttons {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	margin-top: 16px;
}

.mobile-page__back {
	margin-top: 32px;
}

.attempts {
	margin: 16px 0 0;
	padding: 0;
	list-style: none;
}

.attempts__item {
	display: flex;
	flex-direction: column;
	gap: 2px;
	padding: 10px 0;
	border-bottom: 1px solid var(--color-border);
}

.attempts__meta {
	color: var(--color-text-maxcontrast);
}

@media (max-width: 480px) {
	.mobile-page {
		padding: 12px;
	}

	.mobile-page__buttons > * {
		width: 100%;
	}
}
</style>
