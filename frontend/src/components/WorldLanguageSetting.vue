<!-- Game language of one world (D-27): one choice for all players of the world.
     The running mods keep their language until the next start, the hint says so. -->
<template>
	<div class="world-language">
		<NcSelect
			:model-value="selected"
			:options="options"
			:clearable="false"
			:searchable="false"
			:disabled="saving"
			:input-label="t('world.language.label')"
			class="world-language__select"
			@update:model-value="choose" />
		<p class="world-language__hint">
			{{ t('world.language.hint') }}
		</p>
		<NcNoteCard v-if="world.language_restart_needed" type="info" class="world-language__note">
			{{ t('world.language.restart') }}
		</NcNoteCard>
		<NcNoteCard v-if="error" type="error" class="world-language__note">
			{{ error }}
		</NcNoteCard>
	</div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcSelect from '@nextcloud/vue/components/NcSelect'
import { errorText, setWorldLanguage } from '../api.js'
import { t } from '../i18n/index.js'

// Language names always in their own language, the same in every dictionary.
const LANGUAGE_NAMES = Object.freeze([
	{ value: 'de', label: 'Deutsch' },
	{ value: 'en', label: 'English' },
	{ value: 'fr', label: 'Français' },
])

const props = defineProps({
	// WorldOut row from GET /api/worlds (id, language, language_restart_needed).
	world: { type: Object, required: true },
})
const emit = defineEmits(['changed'])

const saving = ref(false)
const error = ref('')
// Own display value so the choice can jump back after a failed request.
const current = ref(props.world.language || 'de')

watch(() => props.world.language, (value) => {
	if (!saving.value) {
		current.value = value || 'de'
	}
})

const options = LANGUAGE_NAMES
const selected = computed(() => options.find((option) => option.value === current.value) ?? options[0])

async function choose(option) {
	const language = option?.value
	if (saving.value || !language || language === current.value) {
		return
	}
	const before = current.value
	saving.value = true
	error.value = ''
	current.value = language
	try {
		const result = await setWorldLanguage(props.world.id, language)
		current.value = result?.language || language
		emit('changed', result)
	} catch (err) {
		current.value = before
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}
</script>

<style scoped>
.world-language {
	display: flex;
	flex-direction: column;
	gap: 4px;
	margin-top: 8px;
	max-width: 100%;
	/* The world table cell inherits nowrap; without this the hint stays on one line and widens the table past the page. */
	white-space: normal;
}

/* NcSelect brings a minimum width; at 390 px it takes the full cell width. */
.world-language__select,
.world-language :deep(.v-select.select) {
	min-width: 0;
	width: 100%;
	max-width: 100%;
}

.world-language__hint {
	margin: 0;
	font-size: 0.9em;
	color: var(--color-text-maxcontrast);
	overflow-wrap: anywhere;
}

.world-language__note {
	margin: 4px 0 0;
}
</style>
