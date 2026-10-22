<!-- Tagesrückblick am Abend (D-12, D-14, D-15): an/aus und Uhrzeit, gespeichert nur für den angemeldeten Verwalter. -->
<template>
	<section class="review-setting">
		<h4>Tagesrückblick am Abend</h4>
		<p class="review-setting__hint">
			Gilt nur für dich. Ohne Spielzeit an dem Tag kommt keine Nachricht.
		</p>
		<NcLoadingIcon v-if="loading" :size="20" />
		<div v-else class="review-setting__form">
			<NcCheckboxRadioSwitch
				type="switch"
				:model-value="enabled"
				:disabled="saving"
				@update:model-value="enabled = $event">
				Tagesrückblick am Abend
			</NcCheckboxRadioSwitch>
			<NcSelect
				:model-value="selectedOption"
				:options="choice.options"
				:clearable="false"
				:searchable="false"
				:disabled="saving || !enabled"
				input-label="Uhrzeit"
				@update:model-value="onMinute" />
			<NcButton variant="primary" :disabled="saving || !changed" @click="save">
				<template v-if="saving" #icon>
					<NcLoadingIcon :size="20" />
				</template>
				Speichern
			</NcButton>
		</div>
		<p v-if="changed && !saving" class="review-setting__hint">
			Noch nicht gespeichert.
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
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcCheckboxRadioSwitch from '@nextcloud/vue/components/NcCheckboxRadioSwitch'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import NcSelect from '@nextcloud/vue/components/NcSelect'
import { errorText, getReviewPrefs, saveReviewPrefs } from '../api.js'
import { reviewSelectOptions } from '../playtime.js'

const loading = ref(true)
const saving = ref(false)
const notice = ref('')
const error = ref('')
// Zuletzt gespeicherter Stand (aus der API) und die Auswahl im Formular.
const savedEnabled = ref(true)
const savedMinute = ref(null)
const enabled = ref(true)
// Optionen und Auswahl aus dem gespeicherten Wert; dirty heißt: die Anzeige weicht vom gespeicherten Wert ab.
const choice = ref(reviewSelectOptions(null))
const minute = ref(choice.value.selected)

const selectedOption = computed(() => choice.value.options.find((option) => option.value === minute.value) ?? null)

const changed = computed(() => choice.value.dirty
	|| enabled.value !== savedEnabled.value
	|| minute.value !== savedMinute.value)

function apply(prefs) {
	savedEnabled.value = Boolean(prefs.enabled)
	savedMinute.value = prefs.minute
	enabled.value = savedEnabled.value
	choice.value = reviewSelectOptions(prefs.minute)
	minute.value = choice.value.selected
}

function onMinute(option) {
	if (option) {
		minute.value = option.value
	}
}

async function load() {
	loading.value = true
	error.value = ''
	try {
		apply(await getReviewPrefs())
	} catch (err) {
		error.value = `Die Einstellung konnte nicht geladen werden: ${errorText(err)}`
	} finally {
		loading.value = false
	}
}

async function save() {
	if (!changed.value || saving.value) {
		return
	}
	saving.value = true
	notice.value = ''
	error.value = ''
	try {
		apply(await saveReviewPrefs(enabled.value, minute.value))
		notice.value = enabled.value
			? `Gespeichert. Der Rückblick kommt um ${selectedOption.value?.label ?? ''}.`
			: 'Gespeichert. Du bekommst keinen Tagesrückblick.'
	} catch (err) {
		error.value = errorText(err)
	} finally {
		saving.value = false
	}
}

onMounted(load)
</script>

<style scoped>
.review-setting {
	margin-top: 16px;
}

.review-setting__hint {
	margin: 4px 0;
	color: var(--color-text-maxcontrast);
}

.review-setting__form {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	align-items: center;
}
</style>
