<!-- Section "Spielzeit": one row per invited child (without managers) with summary, today's usage and dialog. -->
<template>
	<section class="playtime">
		<h3>{{ t('kids.playtimeSection.title') }}</h3>
		<p class="playtime__hint">
			{{ t('kids.playtimeSection.hint') }}
		</p>
		<NcNoteCard v-if="error" type="warning">
			{{ error }}
		</NcNoteCard>
		<NcLoadingIcon v-if="loading" :size="32" />
		<p v-else-if="children.length === 0" class="playtime__empty">
			{{ t('kids.playtimeSection.empty') }}
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
						<!-- ROLLE-04: adults stay in the list, their rule is only dormant. -->
						<NcChip
							v-if="child.adult"
							:text="t('kids.playtimeSection.adultResting')"
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
							{{ t('kids.playtimeSection.edit') }}
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
import { t } from '../i18n/index.js'
import { summarize, todayRule, usageText, weekdayIn } from '../playtime.js'

const props = defineProps({
	// Response of GET /api/playtime or null while nothing is loaded.
	playtime: { type: Object, default: null },
	loading: { type: Boolean, default: false },
	error: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

// Copy of the child on opening; reloading the list does not change the open dialog.
const editing = ref(null)

const children = computed(() => props.playtime?.children ?? [])
const holidayActive = computed(() => (props.playtime?.holidays ?? []).some((entry) => entry.active))

// "heute 45 von 60 min", only when a limit applies today; for adults nothing counts.
function usage(child) {
	if (child.adult) {
		return t('kids.playtimeSection.notCounted')
	}
	if (!child.has_rules) {
		return ''
	}
	const rule = todayRule(child, holidayActive.value, weekdayIn(props.playtime?.time_zone ?? 'Europe/Berlin'))
	if (!rule) {
		return ''
	}
	if (!rule.allowed) {
		return t('kids.playtimeSection.noPlayDay')
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

/* Phone: four columns do not fit into 390 px, the row wraps (name on top, rule and button below). */
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
