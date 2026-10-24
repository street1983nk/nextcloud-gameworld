<!-- Abschnitt "Spielzeit": eine Zeile je eingeladenem Kind (ohne Verwalter) mit Zusammenfassung, heutigem Verbrauch und Dialog. -->
<template>
	<section class="playtime">
		<h3>Spielzeit</h3>
		<p class="playtime__hint">
			Ohne Regel spielt ein Kind ohne Begrenzung. Eine Regel gilt für alle Welten zusammen.
		</p>
		<NcNoteCard v-if="error" type="warning">
			{{ error }}
		</NcNoteCard>
		<NcLoadingIcon v-if="loading" :size="32" />
		<p v-else-if="children.length === 0" class="playtime__empty">
			Noch keine Kinder eingeladen.
		</p>
		<table v-else class="playtime__list">
			<tbody>
				<tr v-for="child in children" :key="child.nc_user" :data-nc-user="child.nc_user">
					<td>
						<div class="playtime__name">
							{{ child.display_name }}
						</div>
						<div class="playtime__player">
							{{ child.player_name }}
						</div>
					</td>
					<td>
						<!-- ROLLE-04: Erwachsene bleiben in der Liste, ihre Regel ruht nur. -->
						<NcChip
							v-if="child.adult"
							text="Erwachsen: Regel ruht"
							variant="secondary"
							no-close />
						<NcChip
							v-else
							:text="summarize(child.has_rules ? child.normal : null)"
							:variant="child.has_rules ? 'primary' : 'tertiary'"
							no-close />
					</td>
					<td class="playtime__usage">
						{{ usage(child) }}
					</td>
					<td class="playtime__actions">
						<NcButton @click="editing = child">
							Bearbeiten
						</NcButton>
					</td>
				</tr>
			</tbody>
		</table>

		<PlaytimeDialog
			v-if="editing"
			:key="`playtime-${editing.nc_user}`"
			:child="editing"
			@saved="emit('changed')"
			@close="editing = null" />
	</section>
</template>

<script setup>
import { computed, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcChip from '@nextcloud/vue/components/NcChip'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import PlaytimeDialog from './PlaytimeDialog.vue'
import { summarize, todayRule, usageText, weekdayIn } from '../playtime.js'

const props = defineProps({
	// Antwort von GET /api/playtime oder null, solange nichts geladen ist.
	playtime: { type: Object, default: null },
	loading: { type: Boolean, default: false },
	error: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

// Kopie des Kindes beim Öffnen; das Neuladen der Liste ändert den offenen Dialog nicht.
const editing = ref(null)

const children = computed(() => props.playtime?.children ?? [])
const holidayActive = computed(() => (props.playtime?.holidays ?? []).some((entry) => entry.active))

// "heute 45 von 60 min", nur wenn heute ein Limit gilt; bei Erwachsenen zählt nichts.
function usage(child) {
	if (child.adult) {
		return 'zählt nicht'
	}
	if (!child.has_rules) {
		return ''
	}
	const rule = todayRule(child, holidayActive.value, weekdayIn(props.playtime?.time_zone ?? 'Europe/Berlin'))
	if (!rule) {
		return ''
	}
	if (!rule.allowed) {
		return 'heute kein Spieltag'
	}
	return rule.limit_minutes === null ? '' : usageText(child.used_today_s, rule.limit_minutes)
}
</script>

<style scoped>
.playtime {
	margin-top: 32px;
}

.playtime__hint,
.playtime__empty {
	color: var(--color-text-maxcontrast);
}

.playtime__list {
	width: 100%;
	border-collapse: collapse;
}

.playtime__list td {
	padding: 8px;
	text-align: start;
	border-bottom: 1px solid var(--color-border);
}

.playtime__name {
	font-weight: bold;
}

.playtime__player,
.playtime__usage {
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
}

.playtime__actions {
	text-align: end;
}

/* Handy: vier Spalten passen nicht in 390 px, die Zeile bricht um (Name oben, darunter Regel und Knopf). */
@media (max-width: 480px) {
	.playtime__list tr {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		border-bottom: 1px solid var(--color-border);
	}

	.playtime__list td {
		border-bottom: none;
	}

	.playtime__list td:first-child {
		flex: 1 1 100%;
		padding-bottom: 0;
	}

	.playtime__actions {
		margin-inline-start: auto;
	}
}
</style>
