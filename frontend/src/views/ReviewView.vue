<!-- Handy-Seite Tagesrückblick (ELTERN-03, D-12 bis D-14): Minuten je Kind und Welt eines Tages. -->
<template>
	<div class="mobile-page">
		<h2>Tagesrückblick</h2>
		<p v-if="heading" class="mobile-page__day">
			{{ heading }}
		</p>

		<div v-if="loading" class="mobile-page__loading">
			<NcLoadingIcon :size="32" />
		</div>

		<template v-else-if="!error">
			<p v-if="kids.length === 0" class="mobile-page__empty">
				An diesem Tag hat niemand gespielt.
			</p>
			<ul v-else class="review">
				<li v-for="kid in kids" :key="kid.nc_user" class="review__kid">
					<p class="review__line">
						<strong>{{ kid.display_name }}</strong>
						{{ minutesText(kid.minutes) }}<span v-if="kid.limit_reached" class="review__limit"> (Limit erreicht)</span>
					</p>
					<ul v-if="kid.worlds.length > 0" class="review__worlds">
						<li v-for="world in kid.worlds" :key="world.world_id">
							{{ world.world_name }}: {{ minutesText(world.minutes) }}
						</li>
					</ul>
				</li>
			</ul>
		</template>

		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>

		<div class="mobile-page__buttons mobile-page__back">
			<NcButton variant="tertiary" @click="navigate('')">
				Zur Übersicht
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
import { minutesText } from '../playtime.js'
import { currentParams, dayLabel, localDay, navigate } from '../route.js'

// tag aus dem Link ist schon geprüft (route.js); das Backend prüft erneut.
const today = localDay()
const day = currentParams().tag ?? today

const loading = ref(true)
const error = ref('')
const kids = ref([])

const heading = computed(() => dayLabel(day, today))

onMounted(async () => {
	try {
		const review = await getReview(day)
		kids.value = review.kids ?? []
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
