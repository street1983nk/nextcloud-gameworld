<!-- Block "Deine Spielzeit heute" in the child view; without rules (limited false) nothing appears. -->
<template>
	<section v-if="text" class="playtime-card" aria-live="polite">
		<h3>{{ t('kids.playtimeCard.title') }}</h3>
		<NcNoteCard :type="blocked ? 'warning' : 'info'">
			{{ text }}
		</NcNoteCard>
	</section>
</template>

<script setup>
import { computed } from 'vue'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { t } from '../i18n/index.js'
import { kidPlaytimeBlocked, kidPlaytimeText } from '../playtime.js'

const props = defineProps({
	// Response of /api/my/playtime or null (not loaded yet).
	playtime: {
		type: Object,
		default: null,
	},
})

const text = computed(() => kidPlaytimeText(props.playtime))
const blocked = computed(() => kidPlaytimeBlocked(props.playtime))
</script>

<style scoped>
.playtime-card {
	margin-bottom: 24px;
}

.playtime-card h3 {
	margin: 0 0 8px;
}
</style>
