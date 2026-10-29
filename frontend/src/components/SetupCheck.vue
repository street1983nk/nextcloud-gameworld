<template>
	<div class="setup-check">
		<NcLoadingIcon v-if="checking && !result" :size="20" />

		<NcNoteCard v-if="unreachable" type="error" :heading="t('admin.setup.notReady')">
			<p>{{ t('admin.setup.unreachable') }}</p>
		</NcNoteCard>

		<NcNoteCard v-if="errors.length > 0" type="error" :heading="t('admin.setup.notReady')">
			<ul class="setup-check__list">
				<li v-for="item in errors" :key="item.id">
					{{ item.message }}
				</li>
			</ul>
		</NcNoteCard>

		<NcNoteCard v-if="warnings.length > 0" type="warning" :heading="t('admin.setup.proxyWarning')">
			<ul class="setup-check__list">
				<li v-for="item in warnings" :key="item.id">
					{{ item.message }}
				</li>
			</ul>
		</NcNoteCard>

		<NcButton v-if="unreachable || errors.length > 0 || warnings.length > 0" :disabled="checking" @click="check">
			<template v-if="checking" #icon>
				<NcLoadingIcon :size="20" />
			</template>
			{{ t('admin.setup.recheck') }}
		</NcButton>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import NcButton from '@nextcloud/vue/components/NcButton'
import NcLoadingIcon from '@nextcloud/vue/components/NcLoadingIcon'
import NcNoteCard from '@nextcloud/vue/components/NcNoteCard'
import { getSetupCheck } from '../api.js'
import { t } from '../i18n/index.js'

// checked: after every check run (success or failure), so that the world list follows.
const emit = defineEmits(['update:ok', 'checked'])

const result = ref(null)
const checking = ref(false)
const unreachable = ref(false)

const failed = computed(() => (result.value?.items ?? []).filter((item) => !item.ok))
const errors = computed(() => failed.value.filter((item) => item.severity === 'error'))
const warnings = computed(() => failed.value.filter((item) => item.severity === 'warning'))

async function check() {
	if (checking.value) {
		return
	}
	checking.value = true
	try {
		result.value = await getSetupCheck()
		unreachable.value = false
		emit('update:ok', result.value.ok === true)
	} catch {
		result.value = null
		unreachable.value = true
		emit('update:ok', false)
	} finally {
		checking.value = false
		emit('checked')
	}
}

onMounted(check)
</script>

<style scoped>
.setup-check {
	margin-bottom: 16px;
}

.setup-check__list {
	margin: 0;
	padding-inline-start: 20px;
	list-style: disc;
}
</style>
