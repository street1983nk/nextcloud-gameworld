<!-- Household time zone (O-02): default Europe/Berlin, suggestion from this browser; playtimes and holidays are calculated in this zone. -->
<template>
	<section class="time-zone">
		<h4>{{ t('admin.timeZone.title') }}</h4>
		<p class="time-zone__hint">
			{{ t('admin.timeZone.hint') }}
		</p>
		<div class="time-zone__form">
			<NcTimezonePicker v-model="value" :uid="pickerId" />
			<NcButton
				v-if="browserZone && browserZone !== value"
				variant="tertiary"
				:disabled="saving"
				@click="value = browserZone">
				{{ t('admin.timeZone.useBrowser') }}
			</NcButton>
			<NcButton variant="primary" :disabled="saving || !changed" @click="save">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				{{ t('admin.common.save') }}
			</NcButton>
		</div>
		<p v-if="browserZone && browserZone !== value" class="time-zone__hint">
			{{ t('admin.timeZone.browserUses', { zone: browserZone }) }}
		</p>
		<NcNoteCard v-if="notice" type="success">
			{{ notice }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error">
			{{ error }}
		</NcNoteCard>
	</section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcTimezonePicker from '@nextcloud/vue/components/NcTimezonePicker'
import { errorText, setTimeZone } from '../api.js'
import { t } from '../i18n/index.js'

const DEFAULT_ZONE = 'Europe/Berlin'

const props = defineProps({
	// time_zone from GET /api/playtime; empty while nothing is loaded.
	timeZone: { type: String, default: '' },
})
const emit = defineEmits(['changed'])

const pickerId = 'gameworld-time-zone'
const saved = ref(props.timeZone || DEFAULT_ZONE)
const value = ref(saved.value)
const saving = ref(false)
const notice = ref('')
const error = ref('')

// From the browser only, no external service (T-04-36).
function readBrowserZone() {
	try {
		return Intl.DateTimeFormat().resolvedOptions().timeZone || ''
	} catch {
		return ''
	}
}
const browserZone = readBrowserZone()

const changed = computed(() => value.value !== '' && value.value !== saved.value)

// Adopt newly loaded values as long as nothing unsaved was changed.
watch(() => props.timeZone, (zone) => {
	if (!zone) {
		return
	}
	if (value.value === saved.value) {
		value.value = zone
	}
	saved.value = zone
})

async function save() {
	if (!changed.value || saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		const result = await setTimeZone(value.value)
		saved.value = result.time_zone
		value.value = result.time_zone
		notice.value = result.applied === false
			? t('admin.timeZone.savedLater')
			: t('admin.timeZone.saved')
		emit('changed')
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
</script>

<style scoped>
.time-zone {
	margin-top: 16px;
}

.time-zone__hint {
	margin: 4px 0;
	color: var(--color-text-maxcontrast);
}

.time-zone__form {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
}

.time-zone__form > :first-child {
	min-width: 260px;
}
</style>
