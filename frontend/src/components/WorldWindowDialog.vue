<!-- Time window of a world (ZEIT-05): the same day tiles without limit; outside it no child newly gets in, the world keeps running. -->
<template>
	<NcDialog
		:open="true"
		:name="t('kids.worldWindow.title', { name: world.name })"
		size="large"
		@update:open="onOpen">
		<div class="world-window">
			<p class="world-window__hint">
				{{ t('kids.worldWindow.hint') }}
			</p>
			<DayTiles v-model:days="days" :with-limit="false" :disabled="saving" />
			<p class="world-window__hint">
				{{ t('kids.worldWindow.outside') }}
			</p>
			<NcNoteCard v-if="invalid" type="warning">
				{{ t('kids.common.endNotAfterStart') }}
			</NcNoteCard>
			<NcNoteCard v-if="noOpenDay" type="warning">
				{{ t('kids.worldWindow.noOpenDay') }}
			</NcNoteCard>
			<NcNoteCard v-if="error" type="error">
				{{ error }}
			</NcNoteCard>
			<NcNoteCard v-if="pending" type="warning">
				{{ pending }}
			</NcNoteCard>
		</div>

		<template #actions>
			<NcButton v-if="pending" variant="primary" @click="close">
				{{ t('kids.common.close') }}
			</NcButton>
			<template v-else>
				<NcButton variant="tertiary" :disabled="saving" @click="close">
					{{ t('kids.common.cancel') }}
				</NcButton>
				<NcButton variant="secondary" :disabled="saving" @click="submit(true)">
					{{ t('kids.worldWindow.alwaysOpen') }}
				</NcButton>
				<NcButton variant="primary" :disabled="saving || invalid || noOpenDay" @click="submit(false)">
					<template v-if="saving" #icon>
						<NcLoadingIcon :size="20" />
					</template>
					{{ t('kids.common.save') }}
				</NcButton>
			</template>
		</template>
	</NcDialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcDialog from '@nextcloud/vue/components/NcDialog'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import DayTiles from './DayTiles.vue'
import { clearWorldWindow, errorText, setWorldWindow } from '../api.js'
import { t } from '../i18n/index.js'
import { fromWindowDays, notAppliedText, toWindowDays, validateDays } from '../playtime.js'

const props = defineProps({
	// { id, name, time_window } of the world; time_window null means always open.
	world: { type: Object, required: true },
})
const emit = defineEmits(['saved', 'close'])

const days = ref(fromWindowDays(props.world.time_window))
const saving = ref(false)
const error = ref('')
// Saved, but not yet in the world (applied false, WR-08): the dialog stays open with a notice.
const pending = ref('')

const invalid = computed(() => Object.keys(validateDays(days.value)).length > 0)
const noOpenDay = computed(() => days.value.every((entry) => !entry.allowed))

// alwaysOpen: remove the window; otherwise save the seven days.
async function submit(alwaysOpen) {
	if (saving.value || (!alwaysOpen && (invalid.value || noOpenDay.value))) {
		return
	}
	saving.value = true
	error.value = ''
	try {
		const result = alwaysOpen
			? await clearWorldWindow(props.world.id)
			: await setWorldWindow(props.world.id, toWindowDays(days.value))
		emit('saved')
		pending.value = notAppliedText(result)
		if (!pending.value) {
			emit('close')
		}
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

function close() {
	if (!saving.value) {
		emit('close')
	}
}

function onOpen(open) {
	if (!open) {
		close()
	}
}
</script>

<style scoped>
.world-window {
	display: flex;
	flex-direction: column;
	gap: 12px;
}

.world-window__hint {
	margin: 0;
	color: var(--color-text-maxcontrast);
}
</style>
