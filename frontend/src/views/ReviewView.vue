<!-- Phone page daily review (ELTERN-03, D-12 to D-14): minutes per child and world of one day. -->
<template>
	<div class="mobile-page">
		<h2>{{ t('kids.review.title') }}</h2>
		<p v-if="heading" class="mobile-page__day">
			{{ heading }}
		</p>

		<div v-if="loading" class="mobile-page__loading">
			<NcLoadingIcon :size="32" />
		</div>

		<template v-else-if="!error">
			<p v-if="kids.length === 0" class="mobile-page__empty">
				{{ t('kids.review.empty') }}
			</p>
			<ul v-else class="review">
				<li v-for="kid in kids" :key="kid.nc_user" class="review__kid">
					<p class="review__line">
						<strong>{{ kid.display_name }}</strong>
						{{ minutesText(kid.minutes) }}<span v-if="kid.limit_reached" class="review__limit"> {{ t('kids.review.limitReached') }}</span>
					</p>
					<ul v-if="kid.worlds.length > 0" class="review__worlds">
						<li v-for="world in kid.worlds" :key="world.world_id">
							{{ t('kids.review.worldMinutes', { world: world.world_name, minutes: minutesText(world.minutes) }) }}
						</li>
					</ul>
				</li>
			</ul>
			<p class="mobile-page__hint">
				{{ t('kids.review.hint') }}
			</p>
		</template>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<div class="mobile-page__buttons mobile-page__back">
			<NcButton variant="tertiary" @click="navigate('')">
				{{ t('kids.common.back') }}
			</NcButton>
		</div>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { errorText, getReview } from '../api.js'
import { t } from '../i18n/index.js'
import { minutesText } from '../playtime.js'
import { currentParams, dayLabel, navigate } from '../route.js'

// tag from the link is already checked (route.js); the backend checks again. Without
// tag the backend picks today in the household time zone, not the clock
// of this device (IN-04); day and "heute" come from the response.
const linkDay = currentParams().tag ?? null

const loading = ref(true)
const error = ref('')
const kids = ref([])
const day = ref(linkDay ?? '')
const today = ref('')

const heading = computed(() => (day.value ? dayLabel(day.value, today.value) : ''))

onMounted(async () => {
	try {
		const review = await getReview(linkDay)
		kids.value = review.kids ?? []
		day.value = review.day ?? day.value
		today.value = review.today ?? ''
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

.mobile-page__hint {
	margin: 12px 0 0;
	color: var(--color-text-maxcontrast);
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

.review {
	margin: 8px 0 0;
	padding: 0;
	list-style: none;
}

.review__kid {
	padding: 10px 0;
	border-bottom: 1px solid var(--color-border);
}

.review__line {
	margin: 0;
}

.review__limit {
	color: var(--color-warning-text, var(--color-text-maxcontrast));
}

.review__worlds {
	margin: 4px 0 0;
	padding-inline-start: 16px;
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
