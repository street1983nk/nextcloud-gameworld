<!-- Spieleransicht: nur eigene Daten (/api/me, später /api/my/*), nie die Verwaltungs-API. -->
<template>
	<div class="gameworld-player">
		<h2>Meine Welten</h2>
		<NcEmptyContent
			name="Du bist noch zu keiner Welt eingeladen"
			description="Sobald deine Eltern dich in eine Welt einladen, steht hier, wie du hineinkommst." />
	</div>
</template>

<script setup>
import NcEmptyContent from '@nextcloud/vue/components/NcEmptyContent'

// Antwort von /api/me; 03-06 nutzt sie für die Anrede und die eigenen Welten.
defineProps({
	user: {
		type: Object,
		required: true,
	},
})
</script>

<style scoped>
.gameworld-player {
	max-width: 820px;
	padding: 24px;
}
</style>
